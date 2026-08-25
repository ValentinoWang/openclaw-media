# Stage 2 merge resolution — 2026-08-25

This file records the conflict resolution used to merge
`codex/stage2-handoff-final-20260819` into the current product `main`.

## Included from the final handoff branch

The merge keeps the final branch as a real second parent and imports its
Stage-2 domain/runtime work, including:

- candidate assembly and contract validation;
- external document, personal persistence, and organization pipelines;
- runtime, gateway, production composition, release gate, and server context;
- the isolated `Stage2ServerApp`;
- focused unit/integration tests and the candidate Playwright verifier.

## Intentionally retained from current main

The following production entrypoints remain on their newer `main` versions:

- `openclaw_app/app.py`
- `openclaw_app/adapters/http_api.py`
- `openclaw_app/server_cli.py`

The current files own authentication, account registration, tenant authority,
media task execution, billing, administration, and the accepted media-web API
surface. Replacing them with the older candidate entrypoints would regress the
running product.

Consequently, the old candidate-only `test_stage2_server_cli.py` is not copied
into the resolved tree. Its assertions target an entrypoint shape that no
longer matches the production CLI. The original file remains recoverable from
the merge's second parent.

## Runtime boundary after this merge

The Stage-2 services are available for composition and focused testing, but the
merge does **not** silently enable `/stage2/personal` or
`/stage2/organization` on the existing production server. A follow-up change
must integrate those routes with the current authenticated HTTP authority and
startup composition, with dedicated tests against the present server CLI.

## Acceptance boundary

Merging code does not upgrade the historical Stage-2 SSOT or prove production
acceptance. Real AI-provider verification, authenticated browser/device
coverage, deployment readback, rollback evidence, persistent cross-service
idempotency, and independent acceptance remain separate obligations.
