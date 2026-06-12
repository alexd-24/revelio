"""Shared fixtures: each builds a planted PDF in a temp dir so tests are hermetic.

These mirror the make_test_*.py demo generators, but are self-contained so the
suite never touches the working directory or the network (except the C2PA tests,
which fetch a real signed asset and skip cleanly if offline / c2pa not installed).
"""
import os
import sys
import urllib.request

import fitz
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import revelio  # noqa: E402

C2PA_FIXTURE_URL = ("https://raw.githubusercontent.com/contentauth/c2pa-rs/main/"
                    "sdk/tests/fixtures/CA.jpg")


def _kinds(findings):
    return {f.kind for f in findings}


@pytest.fixture
def kinds():
    return _kinds


@pytest.fixture
def clean_pdf(tmp_path):
    """An ordinary document with nothing to hide."""
    p = tmp_path / "clean.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 90), "Quarterly update", fontsize=14)
    page.insert_text((72, 120), "All figures are final and visible.", fontsize=11)
    doc.save(p)
    doc.close()
    return str(p)


@pytest.fixture
def hidden_pdf(tmp_path):
    """covered + invisible + microfont, with two controls that must NOT flag."""
    p = tmp_path / "hidden.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 90), "Public memo, nothing to hide here.", fontsize=12)
    secret = "Employee SSN: 123-45-6789"
    page.insert_text((72, 140), secret, fontsize=12)
    w = fitz.get_text_length(secret, fontsize=12)
    page.draw_rect(fitz.Rect(70, 128, 72 + w + 2, 144), color=(0, 0, 0), fill=(0, 0, 0))
    page.insert_text((72, 190), "internal-only project bluefin", fontsize=12, color=(1, 1, 1))
    page.insert_text((72, 230), "hidden microprint contact", fontsize=1)
    # control: white text on a coloured header (styled, not hidden)
    page.draw_rect(fitz.Rect(70, 268, 300, 286), color=None, fill=(0.12, 0.16, 0.38))
    page.insert_text((72, 281), "Seed domain Sector Phish", fontsize=11, color=(1, 1, 1))
    doc.save(p)
    doc.close()
    return str(p)


@pytest.fixture
def structural_pdf(tmp_path):
    """Hand-built PDF carrying /JS, /Launch, /OpenAction, /EmbeddedFile + obfuscation."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R /OpenAction 4 0 R "
        b"/Names << /EmbeddedFiles << /Names [(payload) 6 0 R] >> >> >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Annots [5 0 R] >>",
        b"<< /S /JavaScript /JS (app.alert\\('pwned'\\);) >>",
        b"<< /Type /Annot /Subtype /Link /Rect [0 0 100 100] "
        b"/A << /S /Launch /F (calc.exe) >> >>",
        b"<< /Type /Filespec /F (payload.bin) /EF << /F 7 0 R >> /J#61vaScript 0 >>",
        b"<< /Type /EmbeddedFile /Length 5 >>\nstream\nhello\nendstream",
    ]
    body = bytearray(b"%PDF-1.7\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(body))
        body += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref_pos = len(body)
    size = len(objs) + 1
    body += f"xref\n0 {size}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        body += f"{off:010d} 00000 n \n".encode()
    body += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode()
    p = tmp_path / "structural.pdf"
    p.write_bytes(body)
    return str(p)


@pytest.fixture
def revisions_pdf(tmp_path):
    """Three incremental revisions; revision 2 amends a value."""
    p = str(tmp_path / "revised.pdf")
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "Invoice total: EUR 1,000", fontsize=12)
    doc.save(p)
    doc.close()
    doc = fitz.open(p)
    doc[0].insert_text((72, 140), "Amended total: EUR 9,000", fontsize=12)
    doc.save(p, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()
    return p


@pytest.fixture
def provenance_pdf(tmp_path):
    """AI-tool metadata + AI-generated XMP declaration."""
    p = str(tmp_path / "provenance.pdf")
    doc = fitz.open()
    doc.new_page().insert_text((72, 90), "Campaign one-pager", fontsize=13)
    doc.set_metadata({"producer": "Adobe Firefly 3.0", "creator": "Canva"})
    xmp = (
        '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description '
        'xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/" '
        'Iptc4xmpExt:DigitalSourceType="http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"/>'
        '</rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
    )
    doc.set_xml_metadata(xmp)
    doc.save(p)
    doc.close()
    return p


@pytest.fixture
def ocr_pdf(tmp_path):
    """Invisible (Tr 3) text under a vector bar and under a raster bar."""
    p = str(tmp_path / "ocr.pdf")
    doc = fitz.open()
    pg = doc.new_page(width=340, height=250)
    pg.draw_rect(pg.rect, color=None, fill=(0.97, 0.97, 0.95))
    pg.insert_text((20, 60), "VECTOR-HIDDEN ssn 111-22-3333", fontsize=11, render_mode=3)
    pg.draw_rect(fitz.Rect(16, 48, 270, 64), color=None, fill=(0, 0, 0))
    pg.insert_text((20, 120), "RASTER-HIDDEN salary EUR 95000", fontsize=11, render_mode=3)
    bar = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 260, 18))
    bar.set_rect(bar.irect, (0, 0, 0))
    pg.insert_image(fitz.Rect(16, 108, 276, 126), pixmap=bar)
    pg.insert_text((20, 180), "ordinary searchable footer line", fontsize=11, render_mode=3)
    doc.save(p)
    doc.close()
    return p


def _fetch_signed_jpeg():
    return urllib.request.urlopen(C2PA_FIXTURE_URL, timeout=30).read()


@pytest.fixture
def c2pa_valid_pdf(tmp_path):
    pytest.importorskip("c2pa")
    try:
        signed = _fetch_signed_jpeg()
    except Exception:  # noqa: BLE001
        pytest.skip("could not fetch signed C2PA fixture (offline)")
    p = str(tmp_path / "c2pa_valid.pdf")
    doc = fitz.open()
    doc.new_page().insert_image(fitz.Rect(72, 100, 200, 228), stream=signed)
    doc.save(p)
    doc.close()
    return p


@pytest.fixture
def c2pa_tampered_pdf(tmp_path):
    pytest.importorskip("c2pa")
    try:
        signed = bytearray(_fetch_signed_jpeg())
    except Exception:  # noqa: BLE001
        pytest.skip("could not fetch signed C2PA fixture (offline)")
    sos = signed.find(b"\xFF\xDA")
    signed[sos + 300] ^= 0xFF
    signed[sos + 301] ^= 0xFF
    p = str(tmp_path / "c2pa_tampered.pdf")
    doc = fitz.open()
    doc.new_page().insert_image(fitz.Rect(72, 100, 200, 228), stream=bytes(signed))
    doc.save(p)
    doc.close()
    return p
