"""Build a small but valid PDF carrying the structural risks Module 2 detects.

Planted:
  - /OpenAction on the catalog            -> auto-action (MEDIUM)
  - /JavaScript + /JS action              -> javascript (HIGH)
  - /Launch action on a link annotation   -> launch (HIGH)
  - /EmbeddedFile stream                   -> embedded-file (MEDIUM)
  - /J#61vaScript (hex-obfuscated name)    -> javascript (HIGH) + obfuscation note
"""

objs = [
    b"<< /Type /Catalog /Pages 2 0 R /OpenAction 4 0 R "
    b"/Names << /EmbeddedFiles << /Names [(payload) 6 0 R] >> >> >>",                 # 1
    b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",                                      # 2
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Annots [5 0 R] >>",        # 3
    b"<< /S /JavaScript /JS (app.alert\\('pwned'\\);) >>",                             # 4
    b"<< /Type /Annot /Subtype /Link /Rect [0 0 100 100] "
    b"/A << /S /Launch /F (calc.exe) >> >>",                                           # 5
    b"<< /Type /Filespec /F (payload.bin) /EF << /F 7 0 R >> /J#61vaScript 0 >>",      # 6
    b"<< /Type /EmbeddedFile /Length 5 >>\nstream\nhello\nendstream",                  # 7
]

body = bytearray(b"%PDF-1.7\n")
offsets = []
for i, o in enumerate(objs, start=1):
    offsets.append(len(body))
    body += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"

xref_pos = len(body)
size = len(objs) + 1
body += f"xref\n0 {size}\n".encode()
body += b"0000000000 65535 f \n"
for off in offsets:
    body += f"{off:010d} 00000 n \n".encode()
body += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode()

with open("structural.pdf", "wb") as fh:
    fh.write(body)
print("wrote structural.pdf")
