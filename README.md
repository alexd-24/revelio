# Revelio

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
and its embedded images. Presence detection only — every finding is worded as a
declaration, never proof. This is provenance, not statistical "is it AI" guessing.

## Usage

```bash
pip install pymupdf
python revelio.py document.pdf            # human-readable
python revelio.py document.pdf --json     # machine-readable, for pipelines
python make_test.py                       # regenerate a planted test fixture
```

Exit code is 1 when findings exist, 0 when clean — drop it into CI or a
pre-send hook.

## Honest limits

"Clean" means *nothing was found*, not *verified safe*. The hidden-text checks
only see extractable text, so an image-only scanned page can hide content Revelio
can't read yet. For provenance, presence isn't proof (metadata is editable) and
absence is never reported as "human-made".

## Roadmap

- **Provenance v1.** Verify the C2PA manifest signature and assertion chain
  (needs the `c2pa` library); flag a manifest whose claims don't match the file.
- **Harder hidden-text cases.** Off-page text, invisible render mode (Tr 3 — the
  OCR layer left under a scanned redaction, which the browser tools explicitly
  can't handle), and clipped / zero-size glyphs.
- **Wrappers.** A thin web upload UI (client-side for privacy) and/or a library API.
