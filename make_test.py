"""Generate a deliberately broken PDF to test the detector against."""
import fitz

doc = fitz.open()
page = doc.new_page()  # A4

# 1. CONTROL — normal visible text (should NOT be flagged)
page.insert_text((72, 90), "Public memo — nothing to hide here.", fontsize=12, color=(0, 0, 0))

# 2. FAKE REDACTION — real text with a black box drawn over it.
#    The text stays in the byte stream and is fully extractable.
secret = "Employee SSN: 123-45-6789"
page.insert_text((72, 140), secret, fontsize=12, color=(0, 0, 0))
# measure the text and cover it with a solid black rectangle
w = fitz.get_text_length(secret, fontsize=12)
page.draw_rect(fitz.Rect(70, 128, 72 + w + 2, 144), color=(0, 0, 0), fill=(0, 0, 0))

# 3. WHITE-ON-WHITE — invisible to the eye, extractable
page.insert_text((72, 190), "internal-only: project bluefin launches Q3", fontsize=12, color=(1, 1, 1))

# 4. MICROFONT — 1pt, illegible but present
page.insert_text((72, 230), "hidden microprint: contact carol@example.com", fontsize=1, color=(0, 0, 0))

# 5. CONTROL 2 — white text on a coloured table header (styled, NOT hidden).
#    This is the case that produced 40 false positives on a real thesis.
page.draw_rect(fitz.Rect(70, 268, 300, 286), color=None, fill=(0.12, 0.16, 0.38))  # navy header
page.insert_text((72, 281), "Seed domain    Sector    Phish", fontsize=11, color=(1, 1, 1))

# 6. CONTROL 3 — white text on an embedded coloured IMAGE (the chart case).
#    Vector-fill checks miss this; pixel sampling should suppress it.
chart = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 230, 18))
chart.set_rect(chart.irect, (31, 41, 97))  # solid navy raster
page.insert_image(fitz.Rect(70, 300, 300, 318), pixmap=chart)
page.insert_text((72, 313), "May  April  March  February", fontsize=11, color=(1, 1, 1))

doc.save("broken.pdf")
print("wrote broken.pdf")
