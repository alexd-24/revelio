"""Build a PDF carrying the provenance signals Module 4 detects.

  - producer/creator metadata naming generative tools (Firefly / Canva)
  - XMP declaring AI-generated origin (IPTC trainedAlgorithmicMedia) + a C2PA hint
  - an embedded JPEG with a Content Credentials (C2PA/JUMBF) marker injected
"""
import fitz

doc = fitz.open()
page = doc.new_page()
page.insert_text((72, 90), "Campaign one-pager", fontsize=13)

# (c) embedded JPEG with a C2PA/JUMBF marker spliced in after SOI.
pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 24, 24))
pix.set_rect(pix.irect, (120, 160, 200))
jpg = pix.tobytes("jpeg")
app11 = b"\xFF\xEB\x00\x14JP" + b"jumbf" + b"c2pa" + b"urn:uuid:c2pa-test"  # crude APP11
jpg_marked = jpg[:2] + app11 + jpg[2:]
page.insert_image(fitz.Rect(72, 110, 120, 158), stream=jpg_marked)

# (a) document metadata naming AI tools
doc.set_metadata({"producer": "Adobe Firefly 3.0", "creator": "Canva"})

# (b) XMP declaring AI-generated content + a C2PA claim generator
xmp = (
    '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description '
    'xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/" '
    'xmlns:c2pa="http://c2pa.org/" '
    'Iptc4xmpExt:DigitalSourceType="http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia" '
    'c2pa:claim_generator="Adobe Firefly"/>'
    '</rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
)
doc.set_xml_metadata(xmp)

doc.save("provenance.pdf")
print("wrote provenance.pdf")
