# OpenClaw Bot Center

This directory is the tracked source for the MediaClaw web application and its
Media build entrypoint. The deployed Media artifact is produced with:

```bash
npm ci --ignore-scripts
npm run build:media
```

The source was imported from the validated local MediaClaw frontend snapshot
used by the current release. Runtime output, dependencies, local environment
files, and QA evidence are intentionally excluded from this source tree.

## No-auth static demo site

Alongside the Media build, this directory also carries a separate build
target for a no-auth static demo site: the real `MediaStudioApp` and every
production page component, backed by a browser-only fake backend instead of
the real API — no login, no backend, no real data. It exists for business
walkthroughs and outward-facing demos, not as a second frontend
implementation. See
[`docs/frontend/media-demo-site.md`](../docs/frontend/media-demo-site.md)
for the full picture (data provenance, the three demo personas, and
deployment notes).

```bash
npm run generate:demo-dataset   # (re)generate the demo dataset + capability catalog
npm run validate:demo-dataset   # check the committed files match the contract/seed
npm run dev:demo                # local dev server
npm run build:demo              # build dist-demo/
npm run preview:demo            # preview the built dist-demo/
```

The build entrypoint is `index.demo.html` / `vite.demo.config.ts`, and the
output directory is `dist-demo/` — a different artifact from `dist-media/`
and never a substitute for it.
