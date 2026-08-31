# Personal Route Authority Guard

- Stable failure class: authority drift makes the production Media Studio shell redirect personal ordinary pages to `/workspace`, hiding accepted ordinary implementations while a self-referential route matrix still passes.
- Include scope: `src/media/mediaStudioRoutePolicy.ts`, `src/media/MediaStudioApp.tsx`, `scripts/qa/checkMediaStudioRouteMatrix.ts`, and this guard card; the accepted Stage-2 route decision and its read-only implementation evidence.
- Exclude scope: unrelated production source/tests/evidence, package metadata, generated output, dependencies, git index/refs/commits, deployment, network/remotes, and organization Binding/Lark capability implementation.
- Red proof: the route-matrix self-check injects a synthetic resolver that redirects personal ordinary paths to `/workspace`; the independently authored accepted-outcome matrix must fail with `personal ... has the wrong accepted outcome`.
- Green proof: `npx tsx scripts/qa/checkMediaStudioRouteMatrix.ts`, `npx tsc -b tsconfig.media-u12b.json --pretty false`, `npx oxlint src/media/mediaStudioRoutePolicy.ts src/media/MediaStudioApp.tsx scripts/qa/checkMediaStudioRouteMatrix.ts`, and `git diff --check` on the four included paths pass.
- Failure output: `personal <ordinary-path> has the wrong accepted outcome` identifies a personal ordinary-route authority drift; `ordinary route policy must not redirect to the personal workspace` identifies a production `/workspace` redirect literal.
- Repair command: `bash agents-results/2026-08-31/media-visual-mainline-migration/remediation-wave/inputs/personal-route-authority.validation.sh`.
- Enforcement point: `scripts/qa/checkMediaStudioRouteMatrix.ts`, which consumes `resolveStudioRoutePolicy` and `resolveStudioRouteOutcome` and compares them with an independent accepted authority table before the media TypeScript build.
