# OpenClaw Media main consolidation — 2026-08-26

## Goal

Make one GitHub `main` commit the only source identity for the next immutable
Stage-2 release. This change does **not** deploy or restart the active 2026-08-19
release.

## Closed source gaps

- Adds a current-main-owned isolated Stage-2 CLI and authenticated HTTP transport.
- Authenticates every write with the current `AccountAuthService`; Cookie writes
  additionally require same-origin CSRF, while disposable acceptance clients may
  use one Bearer session.
- Keeps tenant, workspace, source rows, Binding, credential generation, Feishu
  space/parent, and trusted URLs server-owned.
- Rejects mixed credentials, duplicate Authorization headers, ambiguous
  snake/camel aliases, and body/header idempotency disagreement.
- Re-checks the Writer Contract digest in the current-main composition both before
  and after production factory assembly.
- Keeps the Writer Contract provisional. Production serving requires an accepted
  integrated contract; a provisional contract is allowed only in explicit
  loopback acceptance mode.
- Enforces the locked Planner contract through the canonical facade: manifest
  inventory must be sorted and unique; the audited v1 body remains available as
  an internal compatibility module.
- Restores the missing hardening test files and adds a deterministic CI gate.

## Runtime boundaries

```text
GitHub main SHA
  -> immutable release builder
  -> openclaw_app.stage2_server_cli
  -> current AccountAuthService
  -> server-owned Stage-2 providers
  -> personal SQLite writer OR current ACTIVE Binding / Feishu writer
  -> write receipt + readback
```

The historical active release remains untouched until a later authorized release
round builds a Git-SHA directory, verifies its manifest and rollback target, runs
isolated authenticated acceptance, and switches systemd atomically.

## Contract states

- `--acceptance-mode`: loopback only; allows a provisional contract so real
  personal/organization evidence can be gathered before acceptance.
- normal serving: requires `status=accepted`, `runtimeIntegration=true`, and both
  Stage-2 endpoints in the persisted contract.
- `--verify-only`: assembles dependencies and emits a redacted identity report
  without binding a socket.

## Branch consolidation

Only `codex/main-reconciliation-20260826` carries new source changes. Historical
branches are either already merged or contain no commits not already reachable
from `main`. After merge, every retained historical ref is moved to the final
`main` SHA so it cannot be mistaken for an independent candidate.

## Explicit non-claims

- No production deployment, restart, traffic switch, database mutation, Feishu
  write, or real acceptance was performed by this source consolidation.
- HTTPS/TLS, OAuth callback, Secure Cookie, HSTS, final public-origin browser
  evidence, and formal Stage-2 SSOT acceptance remain separate.
- Formal Stage-2 SSOT remains `3/32 = 9.4%` until the authorized acceptance owner
  changes it.
