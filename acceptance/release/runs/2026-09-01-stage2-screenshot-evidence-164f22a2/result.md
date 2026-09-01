# Stage-2 Screenshot Evidence Revalidation

- Run ID: `STAGE2-SCREENSHOT-QA:164f22a2b798a5517acba99394240e9ac4410fff:2026-09-01T10:23:09.796Z`
- Scope: the Stage-2 C personal document editor and B organization document mirror states required by `docs/frontend/prototype/stage2-dev-brief.md`.
- Source identity: `164f22a2b798a5517acba99394240e9ac4410fff`.
- Source worktree: clean when capture started.
- Runtime: local macOS Chromium `149.0.7827.55`, served at `http://127.0.0.1` on an ephemeral port.
- Evidence boundary: `browser-boundary-mock`. All API interactions are Playwright browser-boundary mocks. This run is not evidence of a live Feishu tenant, deployed API, organization login, database readback, 28-day session, physical device, or human sign-off.

## Result

`VERIFIED_LOCAL_MOCK`

- The machine validator observed all `64/64` required C/B state and viewport cells, with no missing, duplicate, unexpected, pending, or failed cells.
- The run produced `72` PNGs. Every declared artifact was recomputed from bytes and passed SHA-256, dimension, color-count, and visible-pixel validation.
- All selector/state, route, no-horizontal-overflow, console, page-error, request-failure, and declared-mock-boundary checks passed.
- The manifest has no reviewer placeholder: `reviewIdentity` is explicitly `null`, because this is machine evidence rather than an impersonated human review.

## Prototype Baselines And Mappings

| Surface | Baseline | SHA-256 | Mapping result |
| --- | --- | --- | --- |
| C personal editor | `docs/frontend/prototype/personal-document-editor.html` | `85fd7a18c5bec69af5f58e19e2e905c0e4caa3329282f6a6d4246052f7a17bfd` | All declared states map. `aiResultProgress -> plan` is an intentional scope difference: the brief permits post-generation interpretation rather than a pre-execution confirmation. `organizationDocument -> org` is a cross-surface organization-mirror route. |
| B organization mirror | `docs/frontend/prototype/organization-document-mirror.html` | `c4fbeb9b3467ce8040999f4c510d1ac25bb8bb7b61bb53bdee681e1ba1946353` | All declared states map. `aiResultProgress -> plan` has the same documented intentional scope difference. |

## Artifact Integrity

- Machine manifest: `screenshots/manifest.json`
- Manifest SHA-256: `7e72c06dae47d9d5878b24d0671c158d9aa3ff25182f2be6e00ce1c6b10b7ac8`
- Artifact root: `screenshots/`
- Every screenshot path is repository-relative; zero declared PNG paths are absolute.
- Representative visual checks: `screenshots/C-clean-mobile-390x844.png`, `screenshots/C-conflict-desktop-1440x900.png`, and `screenshots/B-partialApplication-desktop-1440x900.png`.

## Formal Acceptance Boundary

This record replaces none of the prior review. `acceptance/release/runs/2026-09-01-stage2-dev-brief-dba33b95/result.md` remains `BLOCKED`: F1/F2/F3 still require formally accepted Stage-1 C1/I9, C3, and DC2; the four Stage-2 human tasks remain unsigned; and external/deployment evidence is absent. This revalidation repairs only the prior screenshot-evidence identity, durability, metadata, and prototype-comparison findings.

## Companion Machine Evidence

- `npm run build:media` completed successfully against source identity `164f22a2b798a5517acba99394240e9ac4410fff`. It includes the generated-contract check, media QA gates, the Stage-2 screenshot capture, TypeScript build, and Vite production build. This is local machine evidence only.
- The isolated Router baseline was run with Python 3.13 against source identity `63523678`: `1684 passed, 31 failed, 40 skipped, 285 subtests passed` for `python -m pytest tests/ --ignore=tests/test_sync_lark_base_projection.py -q`. `git diff fd1a4fa3..164f22a2 -- openclaw-tag-router` is empty, so the 31 failures are pre-existing baseline drift for this screenshot-harness scope, not a new backend regression or a pass.
