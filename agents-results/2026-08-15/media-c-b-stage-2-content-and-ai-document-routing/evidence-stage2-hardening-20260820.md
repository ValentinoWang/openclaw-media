# Stage-2 Hardening Evidence 2026-08-20

## Scope and identity

This evidence records code-side hardening and verification for the isolated
remote candidate on `ubuntu@106.52.146.37`:

- worktree: `/tmp/openclaw-stage2-handoff-final-20260819/openclaw-tag-router`;
- branch: `codex/stage2-handoff-final-20260819`;
- development baseline: `78120eea04392db2a254968cbe4d8f69f6fd7a84`;
- current binary diff digest: `sha256:ed9021a266600014bf1efe287b9dd10a38854059dbd4b2305a58285877c9e7e9`.

Changed candidate boundaries:

- server-owned request credential and tenant/source validation;
- HTTP duplicate-field and conflicting credential rejection;
- deterministic source-order fingerprints and in-progress receipt claims;
- restart-safe SQLite personal artifacts, runtime receipts, external receipts,
  schema checks, restrictive permissions, and fail-closed persisted JSON;
- Binding-scoped Feishu target isolation, trusted URL checks, revision/content
  readback, and binding-change handling.

The candidate contains eight modified implementation files and two new focused
hardening test files. No commit, push, deployment, restart, release-link change,
credential mutation, PostgreSQL write, or real Feishu write was performed.

## Focused verification

The complete remote Stage-2 test selection passed:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /home/ubuntu/selfmedia-tools/openclaw-media/.venv/bin/python -m pytest -q tests/test_stage2_*.py
172 passed in 5.79s
```

Five additional sequential runs used distinct randomized Python hash seeds.
Every run passed all 172 tests: `5 x 172 = 860/860 passed`. This is focused
fixture/static-test evidence for the candidate revision, not production proof.

The following checks also passed:

```text
PYTHONDONTWRITEBYTECODE=1 /home/ubuntu/selfmedia-tools/openclaw-media/.venv/bin/python -m compileall -q openclaw_app tests
git diff --check
```

## Browser fixture verification

The existing Python 3.11 Playwright runtime and Chromium were used against a
loopback Stage-2 fixture server. All seven cases passed:

| Case | HTTP status | Result |
| --- | ---: | --- |
| `healthz` | 200 | pass |
| `readyz` | 200 | pass |
| `personal_success` | 200 | pass |
| `personal_idempotent_replay` | 200 | pass |
| `personal_authority_negative` | 400 | pass |
| `organization_success` | 200 | pass |
| `organization_authority_negative` | 400 | pass |

Evidence identity:

- level: `browser-fixture`;
- environment: `stage2-playwright-fixture`;
- observed at: `2026-08-20T04:02:10.380354+00:00`;
- formal acceptance: `NOT_ACCEPTED`;
- raw receipt: `evidence-raw/stage2-completion-wave-20260820/evidence-stage2-playwright-fixture-20260820.json`;
- raw receipt digest: `sha256:cb601a016a737bcba51ff1637f94ff311aad3ea1b16ddb7368ea448ffb78ce60`.

This replaces the earlier statement that Playwright could not run. The project
virtualenv still lacks Playwright, but a separate existing Python 3.11 runtime
provided the browser fixture capability. The run did not use an authenticated
production session, real AI provider, real PostgreSQL data, or real Feishu.

## Coverage-map correction

`tests/test_stage2_pipeline_integration.py` exists in the candidate. The
convergence implementation is `openclaw_app/services/stage2_runtime.py`; there is
no requirement for a source module named `stage2_pipeline_integration.py`.
Therefore, absence of that source filename is not an implementation gap.

Pinned digests:

- `stage2_runtime.py`: `sha256:cbb0d056679730249800fb61b20fc9b5fa46f3a6dfc7f01a1f509cf1467d27b8`;
- `test_stage2_pipeline_integration.py`: `sha256:fce144a049400755c2ca4084a7c09e56f3c4ed0eace6b9d899ee8653a0625827`.

## Luna completion wave

Four isolated completion lanes were launched with the fixed writable
`lw-luna` route: personal, organization, HTTP, and production composition. Each
attempt failed before source work with provider `429 Too Many Requests`. The one
permitted same-primary retry for each lane failed with the same provider class.

The outcome is `transport/provider-network BLOCKED` for worker dispatch. No lane
changed source or produced a valid structured return. The bounded route is
exhausted: do not retry these lanes again, switch to `lw-terra`, escalate to L3,
or substitute `spawn_agent`.

The eight raw logs are retained under
`evidence-raw/stage2-completion-wave-20260820/`. Their SHA-256 values are:

| Log | SHA-256 |
| --- | --- |
| `luna-personal-primary.log` | `2c1cb12781885bd93781158dabcadddedcaa0f54ab88967730cf337e0bdba245` |
| `luna-personal-primary-retry.log` | `3eff031979cc2dceecbbbe9b32ed7ea6568b3df2151b018b86ba72763bc122db` |
| `luna-organization-primary.log` | `fbaf2d9ec140ea65f4667ca766183252a50f7d0064c2d1b8174d61b0f83a68bb` |
| `luna-organization-primary-retry.log` | `6b1925fe6a2a03436b235e48f37ca881c5619370dad3be8d8a73e05a24be5af4` |
| `luna-http-primary.log` | `a00b474daa2a0884aae7be69a61303c857a6dc37005decd7a8ddde1de82625cf` |
| `luna-http-primary-retry.log` | `51bfbbd76dcfe567b493ffeb4f7c11309f5f13fbc06b9cfc562a5167a9d0f7b2` |
| `luna-production-primary.log` | `5083bf7a15b05195435a963ef8004eff7beba17dac40b3f7030e543344457d73` |
| `luna-production-primary-retry.log` | `941265d57b984db2b34e0e9415f213834aa9a3a32356682fdaec9c43163a3ecf` |

## Full-suite boundary

The repository-wide `openclaw-tag-router/tests` result cannot be interpreted on
this historical handoff candidate:

1. Its shared live configuration lacks the `knowledge_research` bot expected by
   18 collection paths.
2. Its candidate `config/openclaw_bots.json` predates the `model_tiers` schema.
3. Combining current live `common/integrations` with the historical candidate
   then imports newer modules, including `resource_owner_registry`, which are
   absent from the candidate.

This is a candidate-completeness/environment-compatibility blocker, not a
Stage-2 assertion failure. Production configuration was not patched and mutable
live source was not mixed into the candidate to manufacture a repository-wide
pass.

## Formal SSOT disposition and explicit non-claims

- Code-side candidate surfaces exist for `B/T1`, `S1-S5`, `C1-C7`, `O1-O5`,
  runtime convergence, candidate assembly/release gating, HTTP, and production
  composition.
- The focused Stage-2 code candidate is verified at static/fixture and
  browser-fixture levels only.
- Formal SSOT completion remains `9.4% (3/32)`: only `A`, `A1`, and `K` are
  accepted.
- Stage-1 `C1`, `C3`, and `DC2` remain blocked, so Stage-2 projections `F1`,
  `F2`, and `F3` remain blocked and the Stage-2 formal ready frontier is empty.
- This evidence does not claim `ACCEPTED`, deployed, production-ready,
  authenticated-role, physical-device, real-provider, real-database, or real
  Feishu completion.
