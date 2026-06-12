# Revelio

[![tests](https://github.com/alexd-24/revelio/actions/workflows/tests.yml/badge.svg)](https://github.com/alexd-24/revelio/actions/workflows/tests.yml)

A static forensic scanner for PDFs. It surfaces what a document is hiding from a
reader, what it can do to a machine, what was changed after it was finalised, and
what it declares about its own origin — none of which is visible by just opening
the file.

The free "redaction checker" tools only cover one easy case (text under a black
box). Revelio goes where they stop.

## What it checks

**1. Hidden text** — content that's visually gone but still in the byte stream,
recoverable with copy-paste or a parser:

| kind      | what it catches                                   | severity |
|-----------|---------------------------------------------------|----------|
| covered   | real text under a dark fill / redaction box       | HIGH     |
| invisible | text drawn in a colour that vanishes into its background | HIGH |
| microfont | text below the legibility floor (default < 4pt)   | MEDIUM   |
| ocr-covered | invisible OCR-layer text hidden under a *scanned* redaction (a black bar painted into the page image) | HIGH |

The `invisible` check is contrast-aware: it samples the actual rendered pixels
behind each span, so white text on a coloured header or chart image is correctly
ignored, while white-on-white is flagged.

**2. Structural risk** — objects that can act on you: `/JavaScript`, `/JS`,
`/Launch`, `/OpenAction`, `/AA`, `/EmbeddedFile`, `/GoToR`, `/GoToE`,
`/SubmitForm`. Resolved through PyMuPDF so it sees objects inside compressed
object streams, plus a raw-byte pass that catches hex-escaped names
(`/J#61vaScript`) which a parser would otherwise normalize away.

**3. Revision diffing** — reconstructs each incremental-update revision by
truncating the file at successive `%%EOF` markers, then diffs the text between
versions to surface what was added or removed *after* the original save (e.g. a
value amended after signing). Single-save PDFs report nothing here.

**4. Provenance signals** — reports what a file *declares* about its origin:
generative tools named in producer/creator metadata, AI-generated markers in XMP
(IPTC `trainedAlgorithmicMedia`), and Content Credentials (C2PA) on the document
and its embedded images. With the optional `c2pa` library installed, it goes
further and *cryptographically validates* each manifest — reporting `Valid`
(with signer and claim generator), `INVALID` when the signature or content hash
fails (i.e. the file was changed after signing — tamper detection), or flagging a
marker that's present but unreadable. A valid signature from a signer that isn't
on a trust list is reported as such, not as "trusted". This is provenance, not
statistical "is it AI" guessing.

## Severity

Severity reflects how much a finding should concern you — not how confident the
detection is. Every finding is a verified fact in the bytes; severity is about
what it *means*.

- **HIGH** — likely a real problem: recoverable text hidden from a reader
  (`covered`, `ocr-covered`, `invisible`), code or launch capability
  (`javascript`, `launch`), hex-obfuscated names, content changed after the
  original save (`rev-added`, `rev-removed`), or a failed/forged signature
  (`c2pa-invalid`).
- **MEDIUM** — worth a look, may be benign: tiny `microfont` text, auto-run
  actions (`auto-action`), embedded files, or a Content Credentials marker that
  won't validate (`c2pa-unreadable`).
- **LOW** — declarative context, not a problem in itself: what the file *says*
  about its origin (`ai-tool-metadata`, `ai-declared`, a valid `c2pa-valid`
  signature), how many times it was saved (`revisions`), and remote/submit
  references.
- **INFO** — tool notes, e.g. a hint to install `c2pa-python` for validation.

## Usage

```bash
pip install pymupdf                       # core
pip install c2pa-python                    # optional — enables C2PA signature validation
python revelio.py document.pdf            # human-readable
python revelio.py document.pdf --json     # machine-readable, for pipelines
python make_test.py                       # regenerate a planted test fixture
```

Exit code is 1 when findings exist, 0 when clean — drop it into CI or a
pre-send hook.

### Web UI

Prefer drag-and-drop? Run the local server and open the page:

```bash
python serve.py        # then visit http://127.0.0.1:8000
```

It runs entirely on your machine — the PDF never leaves it — and uses only the
standard library (no extra install). Drop a PDF in and the four modules' findings
render grouped by module and severity.

## Tests

```bash
pip install pytest
pytest
```

Fourteen behavioural tests assert each module's findings on planted fixtures —
and that the controls (white-on-coloured-header, benign OCR layer, clean files)
produce no false positives. They run on every push via GitHub Actions. The C2PA
validation tests skip cleanly if `c2pa-python` isn't installed.

## Honest limits

"Clean" means *nothing was found*, not *verified safe*. The hidden-text checks
only see extractable text, so an image-only scanned page can hide content Revelio
can't read yet. For provenance, presence isn't proof (metadata is editable) and
absence is never reported as "human-made".

## Roadmap

- **Wrappers / distribution.** A hosted version, a packaged release on PyPI, and a
  library API for embedding the checks in other pipelines.
