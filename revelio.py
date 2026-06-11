#!/usr/bin/env python3
"""
Revelio — surface text a PDF is hiding from the human eye.

v0 catches three of the most common "looks clean, isn't" failures:
  1. Covered text   — real text sitting under a solid dark rectangle
                      (the classic failed / cosmetic redaction).
  2. Invisible text — text drawn in white / near-white on a white page.
  3. Microfont text — text too small to read (default < 4pt) but fully extractable.

All three are visually absent yet remain in the byte stream, so anyone with
copy-paste or a parser can recover them. This is the gap the free browser
"redaction checkers" only half-cover.

Usage:
    python revelio.py document.pdf
    python revelio.py document.pdf --json
    python revelio.py document.pdf --min-font 4 --cover-ratio 0.6

Dependency: PyMuPDF  (pip install pymupdf)
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from dataclasses import dataclass, asdict

import fitz  # PyMuPDF

try:
    import c2pa  # optional: enables Module 4 v1 signature validation
    HAVE_C2PA = True
except Exception:  # noqa: BLE001
    HAVE_C2PA = False


# ---- tunables -------------------------------------------------------------
DARK_FILL_MAX = 0.30      # a fill counts as "dark" if its brightest channel < this (0..1)
NEAR_WHITE_MIN = 240      # text counts as "invisible" if every channel >= this (0..255)
DEFAULT_MIN_FONT = 4.0    # text smaller than this (pt) is flagged as microfont
DEFAULT_COVER_RATIO = 0.6 # a span is "covered" if >= this fraction of its area sits under a dark rect
LIGHT_BG_MIN = 0.85       # a fill counts as a "light" background (white text on it = actually invisible)


@dataclass
class Finding:
    page: int          # 1-based
    kind: str          # covered | invisible | microfont
    severity: str      # HIGH | MEDIUM
    text: str          # the recovered (hidden) text
    detail: str        # human-readable explanation
    bbox: tuple        # (x0, y0, x1, y1)


def _span_rgb(color_int: int) -> tuple[int, int, int]:
    """PyMuPDF stores span colour as a packed sRGB int."""
    return (color_int >> 16) & 255, (color_int >> 8) & 255, color_int & 255


def _filled_rects(page: fitz.Page) -> list[tuple[fitz.Rect, tuple]]:
    """Every filled vector rect with its fill colour, plus redaction annots (treated as black)."""
    out: list[tuple[fitz.Rect, tuple]] = []
    for d in page.get_drawings():
        fill = d.get("fill")
        if fill:
            out.append((fitz.Rect(d["rect"]), tuple(fill)))
    annot = page.first_annot
    while annot:
        if annot.type[0] == fitz.PDF_ANNOT_REDACT:
            out.append((fitz.Rect(annot.rect), (0.0, 0.0, 0.0)))
        annot = annot.next
    return out


def _background_is_light(page: fitz.Page, span_rect: fitz.Rect) -> bool:
    """True if the surface actually rendered behind this text is light.

    Renders just the span's region and samples pixels. Because the candidate text
    is white, on a truly light background almost every pixel is light; on a coloured
    header, chart bar, or embedded image most pixels are dark/saturated. This sees
    vector fills AND raster images AND gradients, unlike inspecting drawings alone.
    """
    clip = fitz.Rect(span_rect)
    if clip.is_empty or clip.get_area() <= 0:
        return True
    try:
        pix = page.get_pixmap(clip=clip, alpha=False)
    except Exception:  # noqa: BLE001 — degenerate clip etc.
        return True
    total = pix.width * pix.height
    if total == 0:
        return True
    data, n = pix.samples, pix.n
    thresh = LIGHT_BG_MIN * 255
    step = max(1, total // 4000)          # sample at most ~4000 pixels
    light = sampled = 0
    for i in range(0, total, step):
        o = i * n
        if min(data[o], data[o + 1], data[o + 2]) >= thresh:
            light += 1
        sampled += 1
    return (light / sampled) >= 0.5


def _covered_ratio(span_rect: fitz.Rect, dark_rects: list[fitz.Rect]) -> float:
    area = span_rect.get_area()
    if area <= 0:
        return 0.0
    covered = 0.0
    for r in dark_rects:
        inter = span_rect & r
        if not inter.is_empty:
            covered += inter.get_area()
    return min(covered / area, 1.0)


def scan_page(page: fitz.Page, min_font: float, cover_ratio: float) -> list[Finding]:
    findings: list[Finding] = []
    fills = _filled_rects(page)
    dark_rects = [r for r, f in fills if max(f) < DARK_FILL_MAX]
    pno = page.number + 1

    data = page.get_text("dict")
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                rect = fitz.Rect(span["bbox"])
                size = span.get("size", 0.0)
                r, g, b = _span_rgb(span.get("color", 0))

                # 1. covered text (failed redaction)
                ratio = _covered_ratio(rect, dark_rects)
                if ratio >= cover_ratio:
                    findings.append(Finding(
                        pno, "covered", "HIGH", text,
                        f"{ratio:.0%} of this text sits under a dark fill / redaction box "
                        f"but is still extractable", tuple(rect)))
                    continue  # one finding per span is enough to flag it

                # 2. invisible text: white/near-white AND a light surface behind it.
                #    White text on a coloured header or chart bar is styled, not hidden.
                if min(r, g, b) >= NEAR_WHITE_MIN and _background_is_light(page, rect):
                    findings.append(Finding(
                        pno, "invisible", "HIGH", text,
                        f"text colour rgb({r},{g},{b}) is invisible against a light background",
                        tuple(rect)))
                    continue

                # 3. microfont
                if 0 < size < min_font:
                    findings.append(Finding(
                        pno, "microfont", "MEDIUM", text,
                        f"font size {size:.1f}pt is below the {min_font:g}pt legibility floor",
                        tuple(rect)))
    return findings


# ---- Module 2: structural risk flags --------------------------------------
# Object-level features that give a PDF the ability to act on you: run code,
# auto-trigger, launch programs, carry payloads. Counterpart to Didier Stevens'
# pdfid, but resolved through PyMuPDF (so it sees objects inside compressed
# object streams) and de-obfuscated (so hex-escaped names can't hide).
RISKY: dict[str, tuple[str, str, str]] = {
    # token        kind             severity  description
    "/JavaScript": ("javascript",   "HIGH",   "embedded JavaScript"),
    "/JS":         ("javascript",   "HIGH",   "embedded JavaScript"),
    "/Launch":     ("launch",       "HIGH",   "Launch action can run an external program"),
    "/OpenAction": ("auto-action",  "MEDIUM", "runs automatically when the document opens"),
    "/AA":         ("auto-action",  "MEDIUM", "Additional Action fires on an event (open/close/page)"),
    "/EmbeddedFile": ("embedded-file", "MEDIUM", "a file is embedded inside the PDF"),
    "/GoToR":      ("remote-goto",  "LOW",    "references an external file"),
    "/GoToE":      ("embedded-goto","LOW",    "jumps into an embedded file"),
    "/SubmitForm": ("submit-form",  "LOW",    "can submit data to a URL"),
}


def _deobfuscate(s: str) -> str:
    """Decode PDF name hex escapes so /J#61vaScript reads as /JavaScript."""
    return re.sub(r"#([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), s)


def scan_structure(doc: fitz.Document) -> list[Finding]:
    """Walk every object and flag code-execution / payload-carrying features."""
    findings: list[Finding] = []
    patterns = {kw: re.compile(re.escape(kw) + r"(?![A-Za-z])") for kw in RISKY}
    seen: set[tuple[str, int]] = set()

    for xref in range(1, doc.xref_length()):
        try:
            raw = doc.xref_object(xref, compressed=True) or ""
        except Exception:  # noqa: BLE001 — free/broken object
            continue
        deh = _deobfuscate(raw)
        for kw, (kind, sev, desc) in RISKY.items():
            if not patterns[kw].search(deh):
                continue
            key = (kind, xref)
            if key in seen:
                continue
            seen.add(key)
            findings.append(Finding(0, kind, sev, f"object {xref}", desc, ()))
    return findings


def scan_raw_obfuscation(path: str) -> list[Finding]:
    """Catch hex-escaped risky names in the raw bytes, before any parser cleans them.

    PyMuPDF normalizes /J#61vaScript back to /JavaScript, erasing the evasion signal,
    so name-obfuscation can only be seen at the byte level (the pdfid approach).
    """
    findings: list[Finding] = []
    try:
        data = open(path, "rb").read()
    except OSError:
        return findings
    for m in re.finditer(rb"/[A-Za-z0-9#]+", data):
        tok = m.group().decode("latin-1")
        if "#" not in tok:
            continue
        decoded = _deobfuscate(tok)
        if decoded in RISKY:
            findings.append(Finding(
                0, "obfuscated-name", "HIGH", f"offset {m.start()}",
                f"name hex-escaped to {decoded} to dodge keyword scanners", ()))
    return findings


# ---- Module 3: revision diffing -------------------------------------------
# An incrementally-saved PDF appends each new version to the end of the file,
# each ending in %%EOF. Truncating the bytes at each %%EOF reconstructs an
# earlier version; diffing the text between consecutive versions reveals what
# was changed or added *after* the original save — the forensic smoking gun.
def _added_lines(old_text: str, new_text: str, cap: int = 25) -> list[str]:
    """Non-trivial lines present in new_text but not in old_text."""
    old = {ln.strip() for ln in old_text.splitlines() if len(ln.strip()) >= 3}
    out, seen = [], set()
    for ln in new_text.splitlines():
        s = ln.strip()
        if len(s) >= 3 and s not in old and s not in seen:
            seen.add(s)
            out.append(s)
            if len(out) >= cap:
                break
    return out


def scan_revisions(path: str) -> list[Finding]:
    """Reconstruct each incremental-update revision and diff their text."""
    findings: list[Finding] = []
    try:
        data = open(path, "rb").read()
    except OSError:
        return findings
    eofs = [m.end() for m in re.finditer(rb"%%EOF", data)]
    if len(eofs) <= 1:
        return findings  # single save — nothing was appended after the original

    findings.append(Finding(
        0, "revisions", "LOW", f"{len(eofs)} revisions",
        f"file has {len(eofs)} saved revisions (incremental updates); normal for "
        f"signed or re-edited PDFs — check the changes below", ()))

    prev = None
    for i, end in enumerate(eofs):
        try:
            d = fitz.open(stream=data[:end], filetype="pdf")
            text = "\n".join(p.get_text() for p in d)
            d.close()
        except Exception:  # noqa: BLE001 — a boundary that isn't a clean revision
            continue
        if prev is not None:
            for ln in _added_lines(prev, text):
                findings.append(Finding(
                    0, "rev-added", "HIGH", f"revision {i + 1}",
                    f"text added in revision {i + 1}: {ln!r}", ()))
            for ln in _added_lines(text, prev):
                findings.append(Finding(
                    0, "rev-removed", "HIGH", f"revision {i + 1}",
                    f"text present earlier but gone by revision {i + 1}: {ln!r}", ()))
        prev = text
    return findings


# ---- Module 4: provenance signals (v0 — presence only) --------------------
# Reports what a file *declares* about its own origin: AI/generative tools named
# in metadata, AI-generated markers in XMP, and Content Credentials (C2PA) on the
# document or its embedded images. This is provenance, NOT statistical "is it AI"
# guessing — every finding is a verifiable fact in the bytes. Two honest limits,
# baked into the wording: presence isn't proof (metadata is editable, manifests
# need signature validation — a v1 job), and absence is never reported as "human".
AI_TOOL_HINTS = [
    "firefly", "dall-e", "dall·e", "dalle", "midjourney", "stable diffusion",
    "stablediffusion", "canva", "microsoft designer", "designer.microsoft",
    "bing image creator", "leonardo.ai", "ideogram", "imagen", "recraft",
    "flux.1", "adobe express", "gpt-4o", "nano banana", "grok",
]
AI_DECLARED = [b"trainedAlgorithmicMedia", b"compositeWithTrainedAlgorithmicMedia"]
C2PA_MARKERS = [b"c2pa", b"jumbf", b"contentauth", b"urn:uuid:c2pa"]


def _image_xrefs(doc: fitz.Document) -> set[int]:
    xrefs: set[int] = set()
    for pno in range(doc.page_count):
        for info in doc.get_page_images(pno):
            xrefs.add(info[0])
    return xrefs


def scan_provenance(doc: fitz.Document) -> list[Finding]:
    findings: list[Finding] = []

    # 1. document metadata naming a generative tool
    md = doc.metadata or {}
    for field in ("producer", "creator"):
        val = (md.get(field) or "").strip()
        low = val.lower()
        hit = next((h for h in AI_TOOL_HINTS if h in low), None)
        if hit:
            findings.append(Finding(
                0, "ai-tool-metadata", "LOW", f"{field}={val!r}",
                f"{field} metadata names a generative tool ({hit}); the document "
                f"declares this — not proof, metadata is editable", ()))

    # 2. XMP packet: AI-generated declaration and/or C2PA at document level
    try:
        xmp = doc.get_xml_metadata() or ""
    except Exception:  # noqa: BLE001
        xmp = ""
    xb = xmp.encode("utf-8", "ignore")
    decl = next((m for m in AI_DECLARED if m in xb), None)
    if decl:
        findings.append(Finding(
            0, "ai-declared", "LOW", "XMP metadata",
            f"XMP declares AI-generated content ({decl.decode()}) per the IPTC "
            f"digital-source vocabulary", ()))
    c2pa_seen = False
    if any(c in xb for c in C2PA_MARKERS):
        c2pa_seen = True
        if not HAVE_C2PA:
            findings.append(Finding(
                0, "content-credentials", "LOW", "XMP metadata",
                "document carries Content Credentials (C2PA) — present but unverified; "
                "install c2pa-python to validate the signature", ()))

    # 3. embedded images carrying Content Credentials or an AI-generated marker
    for xref in sorted(_image_xrefs(doc)):
        try:
            blob = doc.extract_image(xref).get("image", b"")
        except Exception:  # noqa: BLE001
            continue
        if not blob:
            continue
        if any(c in blob for c in C2PA_MARKERS):
            c2pa_seen = True
            if not HAVE_C2PA:
                findings.append(Finding(
                    0, "content-credentials", "LOW", f"image xref {xref}",
                    "embedded image carries Content Credentials (C2PA) — present but "
                    "unverified; install c2pa-python to validate the signature", ()))
        if any(m in blob for m in AI_DECLARED):
            findings.append(Finding(
                0, "ai-declared", "LOW", f"image xref {xref}",
                "embedded image declares AI-generated origin in its metadata", ()))
    return findings


def _validate_c2pa_blob(blob: bytes, mime: str, where: str) -> list[Finding]:
    """Run the c2pa Reader on one blob and turn its verdict into a Finding."""
    try:
        reader = c2pa.Reader(mime, stream=io.BytesIO(blob))
    except Exception:  # noqa: BLE001 — no manifest / unreadable format
        return []
    try:
        state = str(reader.get_validation_state())
        store = json.loads(reader.json())
    except Exception:  # noqa: BLE001
        return []

    active = store.get("active_manifest")
    m = (store.get("manifests") or {}).get(active, {}) if active else {}
    issuer = (m.get("signature_info") or {}).get("issuer") or "unknown signer"
    gens = m.get("claim_generator_info") or []
    gen = ", ".join(g.get("name", "?") for g in gens) if isinstance(gens, list) else str(gens)

    ai = None
    for a in m.get("assertions", []):
        if a.get("label", "").startswith("c2pa.actions"):
            for act in a.get("data", {}).get("actions", []):
                src = act.get("digitalSourceType") or ""
                if "trainedAlgorithmicMedia" in src:
                    ai = src.rsplit("/", 1)[-1]

    low = state.lower()
    if "invalid" in low:
        verdict = (f"Content Credentials INVALID ({state}) — a manifest is present but its "
                   f"signature/hash fails: the content was changed after signing, or the "
                   f"manifest is broken. Signer claimed: {issuer!r}")
        kind, sev = "c2pa-invalid", "HIGH"
    else:
        verdict = f"Content Credentials {state} — signed by {issuer!r}; generator: {gen or 'n/a'}"
        if "trusted" not in low:
            verdict += "; signature is internally valid but the signer is not on a trust list"
        kind, sev = "c2pa-valid", "LOW"
    if ai:
        verdict += f"; declares AI-generated origin ({ai})"
    return [Finding(0, kind, sev, where, verdict, ())]


def validate_c2pa(doc: fitz.Document, path: str) -> list[Finding]:
    """Module 4 v1: cryptographically validate any Content Credentials present.

    Validates the PDF itself (for Acrobat-style signed PDFs) and each embedded
    image carrying a C2PA marker. A marker that's present but yields no readable,
    valid manifest is reported (never silently dropped) — a corrupt or stripped
    manifest is itself a red flag. Only runs when the optional c2pa library is
    installed; otherwise scan_provenance emits a presence note plus an install hint.
    """
    if not HAVE_C2PA:
        return []
    findings: list[Finding] = []
    unreadable = ("a Content Credentials marker is present but no valid manifest could "
                  "be read — it may be corrupt, truncated, or stripped; treat with suspicion")

    # document-level: only assert a verdict if a real PDF-level manifest reads.
    # (A bare marker in the raw bytes is usually an embedded image's, handled below.)
    try:
        findings += _validate_c2pa_blob(open(path, "rb").read(), "application/pdf", "document")
    except OSError:
        pass

    # embedded images: marker confirmed in *this* image's bytes, so silence = corrupt.
    for xref in sorted(_image_xrefs(doc)):
        try:
            info = doc.extract_image(xref)
            blob, ext = info.get("image", b""), info.get("ext", "")
        except Exception:  # noqa: BLE001
            continue
        if not blob or not any(c in blob for c in C2PA_MARKERS):
            continue
        res = _validate_c2pa_blob(blob, f"image/{ext or 'jpeg'}", f"image xref {xref}")
        findings += res or [Finding(0, "c2pa-unreadable", "MEDIUM",
                                    f"image xref {xref}", unreadable, ())]
    return findings


def scan(path: str, min_font: float = DEFAULT_MIN_FONT,
         cover_ratio: float = DEFAULT_COVER_RATIO) -> list[Finding]:
    findings: list[Finding] = []
    with fitz.open(path) as doc:
        for page in doc:
            findings.extend(scan_page(page, min_font, cover_ratio))
        findings.extend(scan_structure(doc))
        findings.extend(scan_provenance(doc))
        findings.extend(validate_c2pa(doc, path))
    findings.extend(scan_raw_obfuscation(path))
    findings.extend(scan_revisions(path))
    return findings


def _print_report(path: str, findings: list[Finding]) -> None:
    if not findings:
        print(f"[ok] {path}: nothing flagged")
        return
    print(f"[!] {path}: {len(findings)} finding(s)\n")
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFO": 3}
    for f in sorted(findings, key=lambda x: (order.get(x.severity, 9), x.page)):
        loc = "doc" if f.page == 0 else f"p{f.page}"
        snippet = (f.text[:80] + "…") if len(f.text) > 80 else f.text
        verb = "at" if not f.bbox else "recovered"
        print(f"  {loc:<4} {f.severity:<6} {f.kind:<13} {f.detail}")
        print(f"        ↳ {verb}: {snippet!r}\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Surface text a PDF is hiding from the eye.")
    ap.add_argument("pdf", help="path to the PDF to inspect")
    ap.add_argument("--json", action="store_true", help="emit findings as JSON")
    ap.add_argument("--min-font", type=float, default=DEFAULT_MIN_FONT,
                    help=f"microfont threshold in pt (default {DEFAULT_MIN_FONT})")
    ap.add_argument("--cover-ratio", type=float, default=DEFAULT_COVER_RATIO,
                    help=f"coverage fraction to flag a redaction (default {DEFAULT_COVER_RATIO})")
    args = ap.parse_args(argv)

    try:
        findings = scan(args.pdf, args.min_font, args.cover_ratio)
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
    else:
        _print_report(args.pdf, findings)

    # exit non-zero when something was found — handy in CI / pre-send gates
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
