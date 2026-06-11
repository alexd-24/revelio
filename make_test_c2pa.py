"""Build C2PA validation fixtures for Module 4 v1.

Fetches a genuinely signed test image from the public c2pa-rs fixtures, then
produces two PDFs:
  - c2pa_valid.pdf     : the signed image embedded as-is        -> validates Valid
  - c2pa_tampered.pdf  : same image with its scan data altered  -> validates INVALID

Needs one-time internet access to fetch the signed asset (no signing is done
locally — c2pa's cert profile makes self-signing fiddly, and a real asset is a
better test anyway). Requires: pip install pymupdf c2pa-python
"""
import urllib.request
import fitz

URL = ("https://raw.githubusercontent.com/contentauth/c2pa-rs/main/"
       "sdk/tests/fixtures/CA.jpg")

try:
    signed = urllib.request.urlopen(URL, timeout=30).read()
except Exception as e:  # noqa: BLE001
    raise SystemExit(f"could not fetch the signed test image ({e}); this fixture "
                     f"needs internet access once to download {URL}")

# valid: embed the signed JPEG untouched (PyMuPDF stores it as-is, manifest intact)
doc = fitz.open()
doc.new_page().insert_image(fitz.Rect(72, 100, 200, 228), stream=signed)
doc.save("c2pa_valid.pdf")
doc.close()

# tampered: flip bytes inside the JPEG scan data — breaks the content hash while
# leaving the manifest parseable, so c2pa reports INVALID rather than unreadable.
b = bytearray(signed)
sos = b.find(b"\xFF\xDA")          # start-of-scan marker
b[sos + 300] ^= 0xFF
b[sos + 301] ^= 0xFF
doc = fitz.open()
doc.new_page().insert_image(fitz.Rect(72, 100, 200, 228), stream=bytes(b))
doc.save("c2pa_tampered.pdf")
doc.close()

print("wrote c2pa_valid.pdf (Valid) and c2pa_tampered.pdf (INVALID)")
