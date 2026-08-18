# Product

## Register

product

## Users

OpenClaw Media operators who monitor tenant-scoped local media pipelines,
devices, jobs, and explicit archive receipts from a Web control plane and the
macOS Media Agent CLI.

## Product Purpose

Make local execution state and cloud archive evidence understandable without pretending the browser can browse, play, download, or edit local media.

## Brand Personality

Operational, restrained, trustworthy. The interface should make state boundaries and evidence legible before adding decoration.

## Anti-references

No consumer streaming UI, fake file browser, editable timeline, decorative SaaS metric grid, hidden state conflation, or controls for unavailable local actions.

## Design Principles

- Separate business, job, analysis, and archive state explicitly.
- Show evidence-backed hashes and receipts instead of optimistic claims.
- Keep local-only media visibly local and non-interactive on Web.
- Fail closed on missing, unsafe, or cross-tenant projections.
- Preserve one consistent typed component vocabulary across control-plane pages.

## Accessibility & Inclusion

Target WCAG AA contrast, semantic status text in addition to color, keyboard-safe standard affordances, responsive dense data layouts, and reduced-motion support.

## Web control-plane projection

The established operator routes (`/overview`, `/tracks`, `/assets`, `/runs`,
`/runs/:runId`, `/publishing`, and `/reviews`) consume the same typed tenant
projection. Local collaboration is represented only by `/media-agent` and
`/archives`; standalone pipeline, device, analysis-run, and analysis-run detail
pages are not Web surfaces. The Web uses the generated API client and never
receives local media bytes, credentials, or absolute paths. Each page keeps the
local run identity and separate business, job, analysis, and archive states;
labels are rendered in Chinese while raw state values remain available for
machine reconciliation. Archive evidence includes commit hashes, image outputs
may expose their actual artifact reference as a thumbnail, and video outputs
remain explicitly local with no browser playback, download, or path controls.

The contract projection is generated with:

```sh
python /home/ubuntu/scripts/generate_media_product_contract.py
python /home/ubuntu/scripts/quality/check_media_product_contract.py --self-test
```
