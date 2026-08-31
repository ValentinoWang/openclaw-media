# Media visual mainline migration worker contract

Frozen identities:

- Current mainline baseline: `84382576a4045a99aea1abb6df848ba95f0bb3d9`
- Historical stage 0-3 comparison: `a0580dec5a33ae5893ad30c551ec7b76ec8ed7ef`
- Ledger source: `/Users/vsiyo/Downloads/loginandworkspacevisualreview.html`, DS-06 through DS-11 and DS-21
- Project root: `/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/openclaw-mainline-frontend`

Implement only the page or component files named in the lane task. The latest mainline file is the behavioral authority. Read the historical stage branch with `git show a0580dec:<path>` only as a visual/adoption reference. Never replace a current file wholesale with the historical version, and never revert current API handling, error normalization, cursor behavior, task contracts, account monitoring, authentication behavior, or Studio IA work.

Migrate the page onto the existing mainline shared assets where semantics match:

- `SurfaceState` / `ResourceStateView` for loading, empty, permission, not-found, and error states.
- `Metric` for repeated metric DOM.
- Global `.mg-panel`, `.mg-tabs` / `.mg-tab`, `.mg-hero` / `.mg-eyebrow`, `.mg-btn`, `.mg-badge`, and `.mg-state` classes.
- Keep page-specific layout and business-specific styles local. Remove local CSS only when the global primitive fully replaces it without visual or responsive regression.
- Add one stable root `data-accent` and `data-page-ownership` value from the lane task. Mark the actual top prelude region with `data-page-prelude` when the page has a heading/metric prelude.
- Preserve attribution on loading, unauthorized, empty, not-found, and error route roots, not only the happy path.
- Keep accessible names, roles, keyboard behavior, disabled states, reduced-motion behavior, and mobile layout intact.

Do not edit package manifests, lockfiles, shared CSS, shared UI components, route files, QA scripts, generated files, contracts, backend files, evidence outside your structured return, or any file outside the exact lane write scope. Do not run `git add`, `git commit`, `git checkout`, `git restore`, `git reset`, `git clean`, or any merge/rebase command. Do not launch subagents.

Before returning, inspect `git diff -- <owned paths>`, run the lane validation command, and write the required structured JSON return. A successful result proposes `IMPLEMENTED`, uses `acceptance_self_check: pass`, `failure_class: none`, and `failure_origin: none`. Never claim release acceptance.
