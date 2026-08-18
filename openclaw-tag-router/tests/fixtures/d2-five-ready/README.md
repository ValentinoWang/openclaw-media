# D2 Five Fixed Ready Revisions

This directory is the source-owned authority for D2 fixture input. Historical
copies under `qa-evidence` or isolated work directories are evidence snapshots
only and must not be used to materialize a new D2 run.

This package freezes the five D2 dual-end narrative inputs: `research_snapshot`,
`asset_digest`, `decision_brief`, `creation_document`, and `review_report`.
Each JSON file is a valid `media.document.body.v1` body with stable canonical IDs.
`ready-revision-manifest.json` declares one immutable revision number for each
kind, the body SHA-256, IF2 binding hashes, and the required real-surface path.
The `resources/` directory contains the deterministic `640 x 360` PNG and PDF
bytes referenced by every canonical image and attachment checksum.

The package is an input contract only. It is neither a persisted database
revision nor evidence that a real React MediaApp or authorized Feishu Docx has
rendered. Before a D2 execution, persist each unchanged body as the declared
`ready` revision in an isolated test tenant, bind each declared image and
attachment resource to a real controlled runtime resource, and retain real
React/Feishu screenshots plus Feishu write-after-readback. A mock Feishu DOM,
Markdown preview, API-only JSON, hand-composed screenshot, or surface-specific
rewrite is a hard stop.

Protected blocks are intentionally outside the canonical body because their
types are not legal `media.document.body.v1` blocks. The coverage matrix requires
them to be pre-existing controlled blocks in a real Feishu Docx and requires an
explicit `422 unsupported_document_block`, no partial write, and unchanged
readback.

Regenerate and validate only with:

```bash
python3 generate_d2_fixtures.py --write --check
```

The checker calls the current source `validate_body` implementation and verifies
all fixture and resource hashes, canonical-ID order, five-kind coverage, and
protected-block matrix completeness. It does not make a network call or render
either surface.
