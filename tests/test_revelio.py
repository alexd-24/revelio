"""Behavioural tests: every fixture must produce the findings we expect — and,
just as importantly, the controls must NOT produce false positives.
"""
import revelio


def _by_kind(findings):
    out = {}
    for f in findings:
        out.setdefault(f.kind, []).append(f)
    return out


# --- module 1: hidden text -------------------------------------------------
def test_clean_pdf_is_silent(clean_pdf):
    assert revelio.scan(clean_pdf) == []


def test_hidden_text_detected(hidden_pdf, kinds):
    found = revelio.scan(hidden_pdf)
    k = kinds(found)
    assert {"covered", "invisible", "microfont"} <= k
    # the redacted SSN is recovered verbatim
    covered = [f for f in found if f.kind == "covered"]
    assert any("123-45-6789" in f.text for f in covered)


def test_white_on_coloured_header_not_flagged(hidden_pdf):
    # the navy-header control must never be reported as invisible
    found = revelio.scan(hidden_pdf)
    assert not any("Seed domain" in f.text for f in found)


def test_severities_are_sane(hidden_pdf):
    for f in revelio.scan(hidden_pdf):
        assert f.severity in {"HIGH", "MEDIUM", "LOW", "INFO"}


# --- module 2: structural risk ---------------------------------------------
def test_structural_flags(structural_pdf, kinds):
    k = kinds(revelio.scan(structural_pdf))
    assert {"javascript", "launch", "auto-action", "embedded-file"} <= k


def test_obfuscated_name_caught(structural_pdf):
    found = revelio.scan(structural_pdf)
    obf = [f for f in found if f.kind == "obfuscated-name"]
    assert obf and obf[0].severity == "HIGH"


# --- module 3: revision diffing --------------------------------------------
def test_revision_added_text(revisions_pdf, kinds):
    found = revelio.scan(revisions_pdf)
    assert "rev-added" in kinds(found)
    assert any("9,000" in f.detail for f in found if f.kind == "rev-added")


def test_single_save_has_no_revisions(clean_pdf, kinds):
    assert "revisions" not in kinds(revelio.scan(clean_pdf))


# --- module 4: provenance --------------------------------------------------
def test_ai_tool_metadata(provenance_pdf):
    found = revelio.scan(provenance_pdf)
    tools = [f for f in found if f.kind == "ai-tool-metadata"]
    assert len(tools) == 2  # producer (firefly) + creator (canva)


def test_ai_declared_in_xmp(provenance_pdf, kinds):
    assert "ai-declared" in kinds(revelio.scan(provenance_pdf))


# --- module 1b: OCR-layer redaction ----------------------------------------
def test_ocr_covered_raster(ocr_pdf):
    found = revelio.scan(ocr_pdf)
    bk = _by_kind(found)
    # vector bar -> covered ; raster bar -> ocr-covered
    assert "covered" in bk and "ocr-covered" in bk
    assert any("95000" in f.text for f in bk["ocr-covered"])


def test_ocr_benign_layer_not_flagged(ocr_pdf):
    found = revelio.scan(ocr_pdf)
    assert not any("searchable footer" in f.text for f in found)


# --- C2PA signature validation (skips if c2pa / network unavailable) -------
def test_c2pa_valid(c2pa_valid_pdf, kinds):
    found = revelio.scan(c2pa_valid_pdf)
    assert "c2pa-valid" in kinds(found)


def test_c2pa_tampered_is_high(c2pa_tampered_pdf):
    found = revelio.scan(c2pa_tampered_pdf)
    invalid = [f for f in found if f.kind == "c2pa-invalid"]
    assert invalid and invalid[0].severity == "HIGH"
