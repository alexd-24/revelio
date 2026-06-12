"""Build a PDF exercising the OCR-layer redaction check (Module 1, ocr-covered).

Simulates a scanned-and-OCR'd page with four lines of invisible (Tr 3) text:
  A  hidden under a VECTOR black bar   -> caught by the existing `covered` check
  B  hidden under a RASTER black image -> caught by the new `ocr-covered` check
  C  a benign searchable line (no bar) -> correctly ignored
  D  a normal VISIBLE heading          -> not invisible, ignored
"""
import fitz

doc = fitz.open()
p = doc.new_page(width=340, height=250)
p.draw_rect(p.rect, color=None, fill=(0.97, 0.97, 0.95))  # light "scan" background

# A: invisible text under a vector black bar
p.insert_text((20, 60), "VECTOR-HIDDEN ssn 111-22-3333", fontsize=11, render_mode=3)
p.draw_rect(fitz.Rect(16, 48, 270, 64), color=None, fill=(0, 0, 0))

# B: invisible text under a raster black image bar (the case nothing else catches)
p.insert_text((20, 120), "RASTER-HIDDEN salary EUR 95000", fontsize=11, render_mode=3)
bar = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 260, 18))
bar.set_rect(bar.irect, (0, 0, 0))
p.insert_image(fitz.Rect(16, 108, 276, 126), pixmap=bar)

# C: benign invisible searchable line, nothing over it
p.insert_text((20, 180), "ordinary searchable footer line", fontsize=11, render_mode=3)

# D: a normal visible heading (control)
p.insert_text((20, 215), "Visible heading", fontsize=12, render_mode=0)

doc.save("ocr.pdf")
print("wrote ocr.pdf")
