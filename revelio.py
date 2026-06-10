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
import json
import sys
from dataclasses import dataclass, asdict

import fitz  # PyMuPDF


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


def _background_is_light(span_rect: fitz.Rect, fills: list[tuple[fitz.Rect, tuple]],
                         cover_ratio: float) -> bool:
    """True if the surface behind this text is light (so white text would truly vanish).

    Finds the fill that covers the most of the span. If nothing meaningful covers it,
    the background is the white page -> light. If a coloured/dark fill sits behind it
    (a table header, a chart bar), the text is readable -> not light.
    """
    area = span_rect.get_area()
    if area <= 0:
        return True
    best_cov, best_fill = 0.0, None
    for r, f in fills:
        inter = span_rect & r
        if not inter.is_empty:
            cov = inter.get_area() / area
            if cov > best_cov:
                best_cov, best_fill = cov, f
    if best_fill is None or best_cov < cover_ratio:
        return True  # nothing real behind it -> the page itself
    return min(best_fill) >= LIGHT_BG_MIN


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
                if min(r, g, b) >= NEAR_WHITE_MIN and _background_is_light(rect, fills, cover_ratio):
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


def scan(path: str, min_font: float = DEFAULT_MIN_FONT,
         cover_ratio: float = DEFAULT_COVER_RATIO) -> list[Finding]:
    findings: list[Finding] = []
    with fitz.open(path) as doc:
        for page in doc:
            findings.extend(scan_page(page, min_font, cover_ratio))
    return findings


def _print_report(path: str, findings: list[Finding]) -> None:
    if not findings:
        print(f"[ok] {path}: no hidden text detected")
        return
    print(f"[!] {path}: {len(findings)} finding(s)\n")
    order = {"HIGH": 0, "MEDIUM": 1}
    for f in sorted(findings, key=lambda x: (order[x.severity], x.page)):
        snippet = (f.text[:80] + "…") if len(f.text) > 80 else f.text
        print(f"  p{f.page}  {f.severity:<6} {f.kind:<9} {f.detail}")
        print(f"        ↳ recovered: {snippet!r}\n")


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
