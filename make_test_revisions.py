"""Build a PDF with three incremental revisions, simulating edits after the original save.

  Revision 1: the original invoice.
  Revision 2: a line is appended amending the total (the classic "changed after signing").
  Revision 3: a VOID note is added.

Each save after the first uses incremental=True, so the file keeps all prior
revisions and ends with three %%EOF markers — exactly what scan_revisions walks.
"""
import fitz

PATH = "revised.pdf"

# Revision 1 — original
doc = fitz.open()
page = doc.new_page()
page.insert_text((72, 100), "INVOICE  —  Acme Ltd", fontsize=14)
page.insert_text((72, 130), "Invoice total: EUR 1,000", fontsize=12)
doc.save(PATH)
doc.close()

# Revision 2 — amend the total (appended, original left intact underneath)
doc = fitz.open(PATH)
doc[0].insert_text((72, 160), "Amended total: EUR 9,000", fontsize=12)
doc.save(PATH, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
doc.close()

# Revision 3 — stamp it
doc = fitz.open(PATH)
doc[0].insert_text((72, 190), "NOTE: superseded - VOID", fontsize=12)
doc.save(PATH, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
doc.close()

print(f"wrote {PATH}")
