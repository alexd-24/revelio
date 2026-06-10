# Revelio

Surface text a PDF is hiding from the human eye — the content that's visually
gone but still sitting in the byte stream, recoverable with copy-paste or a parser.

The free "redaction checker" tools only cover the easy case (text under a black
box). Revelio's goal is to go where they stop.

## v0 (this)
Static detection of three common "looks clean, isn't" failures:

| kind      | what it catches                                   | severity |
|-----------|---------------------------------------------------|----------|
| covered   | real text under a dark fill / redaction box       | HIGH     |
| invisible | white / near-white text on a white page           | HIGH     |
| microfont | text below the legibility floor (default < 4pt)   | MEDIUM   |

```bash
pip install pymupdf
python revelio.py document.pdf            # human-readable
python revelio.py document.pdf --json     # machine-readable, for pipelines
python make_test.py                       # regenerate the broken.pdf fixture
```

Exit code is 1 when findings exist, 0 when clean — drop it into CI or a
pre-send hook.

## Roadmap
- **Module 2 — structural risk flags. ✅ done.** Flags objects that can act on you:
  `/JavaScript`, `/JS`, `/Launch`, `/OpenAction`, `/AA`, `/EmbeddedFile`,
  `/GoToR`, `/GoToE`, `/SubmitForm`. Resolved through PyMuPDF so it sees objects
  inside compressed object streams, plus a raw-byte pass that catches hex-escaped
  names (`/J#61vaScript`) which the parser would otherwise normalize away.
- **Module 3 — revision diffing. ✅ done.** Reconstructs each incremental-update
  revision by truncating the file at successive `%%EOF` markers, then diffs the
  text between consecutive versions to surface what was added or removed *after*
  the original save (e.g. a value amended after signing). Single-save PDFs report
  nothing here.
- **Harder hidden-text cases.** Off-page text, invisible render mode (Tr 3 — the
  OCR layer left under a scanned redaction, which the browser tools explicitly
  can't handle), and clipped/zero-size glyphs.
- **Wrappers.** Now that the core is solid: a thin web upload UI (client-side for
  privacy) and/or a library API.
```
```
