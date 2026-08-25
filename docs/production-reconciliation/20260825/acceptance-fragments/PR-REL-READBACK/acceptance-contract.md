# Acceptance Contract: PR-REL-READBACK

- Task ID: PR-REL-READBACK
- Contract version: 1
- Contract status: APPROVED
- Test baseline: LOCKED
- Acceptance owner: 用户（2026-08-25 Production Reconciliation 基线批准者）
- Approval evidence: 用户提供的 2026-08-25 Production Reconciliation 基线与本任务中的“请继续”；批准范围仅为本源代码验收片段
- Request source: docs/production-reconciliation/20260825/runtime-observations.md, docs/production-reconciliation/20260825/deployment-gate.json, and PR-REL-READBACK-DESIGN-V2 task brief
- SSOT node: none
- SSOT path: none
- Readiness mode: FORMAL
- Decision refs: none
- Assumption IDs: none
- Invalidation keys: pr-rel-readback.contract, pr-rel-readback.probe-schema, pr-rel-readback.release-identity, pr-rel-readback.route-semantics, pr-rel-readback.protected-test
- Baseline identity: commit 59e2adfd34853b6929d9fa69e69585806ac9c83a, clean; 2026-08-25 redacted runtime observation and source-only deployment gate
- Human acceptance workspace: acceptance/human/PR-REL-READBACK

## User and scenario

The release integrator or release approver needs a read-only decision from a
Stage-2 user-systemd release observation. The future guard receives structured,
already captured command and probe output through an injected mapping, or an
explicit local runner that produces that mapping. The acceptance surface is
local source validation; it does not require SSH, remote execution, or a live
production request.

The intended release identity is a release root, a settings path, a service
process binding, a current pointer target, a manifest identity, and separate
direct-port and public-route HTTP observations. The result must be safe to put
in a release log.

## Problem

The adjacent `check_openclaw_bot_center_release_process.py` guard validates only
some local user-service/process facts and is not the acceptance boundary for
Stage-2 release reconciliation. The intended Stage-2 guard is currently
reserved for a future implementation. Without a locked contract and protected
negative matrix, an implementation could pass one happy path while silently
accepting an inactive service, a stale release, a mismatched manifest, or a
public-route failure hidden by the direct-port result.

## Expected outcome

For a complete injected observation, the future guard returns a structured
success result with `status=PASS` and `code=OK`. For every invalid or incomplete
observation it returns `status=FAIL` with exactly one stable failure code from
the table below, without guessing a missing value or performing a mutation.

| Failure condition | Required stable code |
| --- | --- |
| User service is not active and running | `SERVICE_INACTIVE` |
| Main PID is absent, non-numeric, or non-positive | `MAIN_PID_MISSING_OR_INVALID` |
| Main PID cwd differs from the expected release root | `PID_CWD_DRIFT` |
| `ExecStart` or the process module is not the requested Stage-2 server | `EXECSTART_MODULE_MISMATCH` |
| Settings path or server port differs from the expected release | `SETTINGS_OR_PORT_MISMATCH` |
| Current pointer target or observed release root differs from the expected release | `POINTER_RELEASE_ROOT_DRIFT` |
| Release manifest identity differs from the expected identity | `MANIFEST_IDENTITY_MISMATCH` |
| A required observation property is absent | `REQUIRED_PROPERTY_MISSING` |
| Any expected HTTP status differs from the observed status | `HTTP_STATUS_MISMATCH` |

The safe result may contain a stable code and a non-sensitive check identifier,
but it must not contain environment values, tokens, cookies, Authorization
header values, secret-bearing arguments, or a full command line.

## Non-goals

- Implementing `openclaw-tag-router/scripts/qa/check_stage2_release_process.py`.
- Reading or mutating a remote host, using SSH, using `curl`, or making any live HTTP request in this acceptance work.
- Creating a release, changing a pointer, reloading or restarting systemd, changing Nginx, reading or changing a database, or writing to Feishu.
- Reading, storing, or reproducing production environment values, credentials, cookies, Authorization headers, or secret-bearing argv.
- Proving current GitHub `main`, authenticated Stage-2 business behavior, real database or external-system behavior, device behavior, deployment activation, rollback, or formal Stage-2 completion.
- Replacing or modifying existing source, tests, evidence, `SHA256SUMS`, SSOT, or Obsidian artifacts.

## Normal path

```gherkin
Given the evaluator receives a complete redacted observation and an expected release identity
And the observation contains user-service state, MainPID process facts, pointer and manifest identity, and separate direct and public probe results
When the evaluator checks the injected observation
Then it returns status PASS and code OK
And it treats direct /healthz and /readyz independently from public /stage2/healthz and /stage2/readyz
And it emits no environment value, token, cookie, Authorization value, or full argv
And it performs no network or filesystem mutation
```

The protected test fixture uses these stable input concepts: `systemd`
properties, `process` facts, `pointer`, `manifest`, and `http_probes`. The
expected mapping supplies `service_name`, `release_root`, `settings_path`,
`port`, `pointer_path`, `manifest_identity`, and `http_statuses`. The exact
implementation may use a local runner, but the protected evaluator entry point
must consume these injected results without invoking a remote transport.

## Exception paths

- If `ActiveState` is not `active` or `SubState` is not `running`, fail with `SERVICE_INACTIVE`.
- If `MainPID` is missing, malformed, zero, or negative, fail with `MAIN_PID_MISSING_OR_INVALID`.
- If the process cwd is not the expected release root, fail with `PID_CWD_DRIFT`.
- If `ExecStart` does not identify `openclaw_app.server_cli`, or the process module is not `openclaw_app.server_cli`, fail with `EXECSTART_MODULE_MISMATCH`.
- If the settings path or port in the service/process observation does not match the expected release, fail with `SETTINGS_OR_PORT_MISMATCH`.
- If the current pointer target or observed release root does not match, fail with `POINTER_RELEASE_ROOT_DRIFT`.
- If any required manifest identity field differs, fail with `MANIFEST_IDENTITY_MISMATCH`.
- If a required property needed to make a decision is absent, fail with `REQUIRED_PROPERTY_MISSING`; never treat absence as a default or as success.
- If a direct or public probe is missing or has a wrong status, fail with `HTTP_STATUS_MISMATCH`; do not merge the two route surfaces.
- If sensitive material is present in an injected raw capture or probe metadata, the returned result remains redacted even when another check fails.
- If the evaluator cannot classify the input safely, it fails closed with a stable code and a safe summary rather than returning `PASS`.

## Invariants

- `PASS` is possible only when every required check passes.
- The evaluator is deterministic for the same injected observation and expected identity.
- Missing, malformed, contradictory, or stale data never becomes a guessed default.
- The direct-port paths `/healthz` and `/readyz` remain distinct from the public paths `/stage2/healthz` and `/stage2/readyz`; a direct 404 for the prefixed path is not silently treated as a public-route result.
- Service-manager `ExecStart`, MainPID argv, process cwd, settings path, port, pointer target, release root, and manifest identity must describe the same release.
- The evaluator and its acceptance tests do not use SSH, remote execution, or live network probes.
- The guard is read-only: it does not create, update, delete, restart, reload, switch, or repair any runtime or release state.
- Failure output exposes only stable codes and safe identifiers; it never exposes environment values, tokens, cookies, Authorization values, or full secret-bearing argv.
- The protected test file is immutable after this contract is locked; a future implementation may add its own tests but may not edit, delete, skip, weaken, or regenerate this baseline.

## Data impact

This source-only fragment has no database, file, pointer, systemd, Nginx,
Feishu, release, or deployment mutation. The future evaluator consumes in-memory
or explicitly supplied command/probe output and returns a bounded result. It
does not create an idempotency record, migrate data, retain credentials, or
perform rollback. Any captured evidence belongs to a named acceptance run and
must be redacted before storage.

## Permissions

The evaluator is available to the release integrator and automated validation
under the repository's normal read-only test permissions. No privileged account,
remote credential, service-manager write permission, database role, or Feishu
permission is required. Human approval is required for the product meaning of
the readback summary; deterministic codes and redaction remain automatic.

## Performance and reliability

The protected evaluator path must be bounded and deterministic for injected
input, with no network wait, retry, or external-service dependency. A future
explicit local runner may collect local observations only under a separately
reviewed command boundary and must pass its results to the same evaluator; a
runner timeout or malformed capture must fail closed and must not broaden the
scope to SSH or remote probing. The acceptance test suite must run repeatedly
with the same result and must not depend on host systemd, `/proc`, ports, DNS,
database, or external services.

## Acceptance criteria

| ID | Requirement | Verification layer | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | A complete injected observation returns `PASS` with `OK` and binds all release facts to one expected identity. | Unit/contract | Automatic | Yes |
| AC-02 | Inactive or non-running user service returns `SERVICE_INACTIVE`. | Unit/contract | Automatic | Yes |
| AC-03 | Missing, malformed, zero, or negative MainPID returns `MAIN_PID_MISSING_OR_INVALID`. | Unit/contract | Automatic | Yes |
| AC-04 | MainPID cwd drift returns `PID_CWD_DRIFT`. | Unit/contract | Automatic | Yes |
| AC-05 | ExecStart or process module drift returns `EXECSTART_MODULE_MISMATCH`. | Unit/contract | Automatic | Yes |
| AC-06 | Settings or port drift returns `SETTINGS_OR_PORT_MISMATCH`. | Unit/contract | Automatic | Yes |
| AC-07 | Pointer target or release-root drift returns `POINTER_RELEASE_ROOT_DRIFT`. | Unit/contract | Automatic | Yes |
| AC-08 | Manifest identity drift returns `MANIFEST_IDENTITY_MISMATCH`. | Unit/contract | Automatic | Yes |
| AC-09 | Missing required observation properties return `REQUIRED_PROPERTY_MISSING` and never default to success. | Unit/contract | Automatic | Yes |
| AC-10 | Direct and public probe status mismatches return `HTTP_STATUS_MISMATCH`. | Unit/contract | Automatic | Yes |
| AC-11 | Direct and public health/readiness route surfaces are evaluated separately, including the observed direct-prefixed 404 versus public rewritten success distinction. | Unit/contract | Automatic | Yes |
| AC-12 | Result serialization redacts environment sentinels, tokens, cookies, Authorization values, and full secret-bearing argv. | Security/unit | Automatic | Yes |
| AC-13 | The protected evaluator consumes injected data without invoking SSH, remote execution, live HTTP, or mutation. | Unit/contract | Automatic | Yes |

## Human acceptance

| ID | Summary | Checklist path | Required role | Blocking |
| --- | --- | --- | --- | --- |
| H-01 | 人工确认读回摘要能够区分 direct-port 与 public-route 的健康/就绪语义，并能据此理解发布结论。 | acceptance/human/PR-REL-READBACK/checklist.md#h-01 | 生产发布验收负责人 | Yes |
| H-02 | 人工确认验收材料只呈现安全摘要且流程保持只读，不把本地红证据或 fixture 证据误称为生产证明。 | acceptance/human/PR-REL-READBACK/checklist.md#h-02 | 生产发布验收负责人 | Yes |

## Protected acceptance tests

| Path | SHA-256 | Covers |
| --- | --- | --- |
| openclaw-tag-router/tests/test_stage2_release_readback.py | a70096254718873de191d3cef266d8fa3ae820b26ffcf516649a3fc42d255ace | AC-01 through AC-13; protected negative matrix, route distinction, injected-only execution, and output redaction |

## Requirements-test traceability

| Requirement | Verification | Evidence target | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | Protected unit/contract test | openclaw-tag-router/tests/test_stage2_release_readback.py::test_accepts_complete_readback | Automatic | Yes |
| AC-02 | Protected unit/contract test | openclaw-tag-router/tests/test_stage2_release_readback.py::test_rejects_inactive_service | Automatic | Yes |
| AC-03 | Protected unit/contract test | openclaw-tag-router/tests/test_stage2_release_readback.py::test_rejects_missing_or_bad_main_pid | Automatic | Yes |
| AC-04 | Protected unit/contract test | openclaw-tag-router/tests/test_stage2_release_readback.py::test_rejects_pid_cwd_drift | Automatic | Yes |
| AC-05 | Protected unit/contract test | openclaw-tag-router/tests/test_stage2_release_readback.py::test_rejects_execstart_or_module_mismatch | Automatic | Yes |
| AC-06 | Protected unit/contract test | openclaw-tag-router/tests/test_stage2_release_readback.py::test_rejects_settings_or_port_mismatch | Automatic | Yes |
| AC-07 | Protected unit/contract test | openclaw-tag-router/tests/test_stage2_release_readback.py::test_rejects_pointer_or_release_root_drift | Automatic | Yes |
| AC-08 | Protected unit/contract test | openclaw-tag-router/tests/test_stage2_release_readback.py::test_rejects_manifest_identity_mismatch | Automatic | Yes |
| AC-09 | Protected unit/contract test | openclaw-tag-router/tests/test_stage2_release_readback.py::test_rejects_missing_required_property | Automatic | Yes |
| AC-10 | Protected unit/contract test | openclaw-tag-router/tests/test_stage2_release_readback.py::test_rejects_http_status_mismatch | Automatic | Yes |
| AC-11 | Protected unit/contract test | openclaw-tag-router/tests/test_stage2_release_readback.py::test_keeps_direct_and_public_routes_distinct | Automatic | Yes |
| AC-12 | Protected security/unit test | openclaw-tag-router/tests/test_stage2_release_readback.py::test_redacts_sensitive_observation_material | Automatic | Yes |
| AC-13 | Protected unit/contract test | openclaw-tag-router/tests/test_stage2_release_readback.py::test_evaluator_uses_injected_observation_only | Automatic | Yes |
| H-01 | Scripted human product review | acceptance/human/PR-REL-READBACK/checklist.md#h-01 | Human | Yes |
| H-02 | Scripted human boundary review | acceptance/human/PR-REL-READBACK/checklist.md#h-02 | Human | Yes |

## Exploratory testing

After the future implementation exists, explore contradictory combinations such
as a matching pointer with a stale manifest, a matching direct probe with a
failed public probe, duplicate or reordered probe entries, extra systemd
properties, malformed JSON-like values, interrupted local runner output, and
repeated evaluation of the same observation. Exploratory findings may add a
separate run, but they cannot weaken AC-01 through AC-13 or replace the
protected tests.

## Production monitoring and rollback

This fragment defines no production monitoring, activation, rollback, or
deployment proof. Those actions remain outside the approved source-only scope
and require a separate release decision with fresh authenticated deployment
readback. The current 2026-08-25 observations are background authority for
route semantics and are not a run result for this contract.

## Risks and open decisions

No product decision is unresolved within the approved fragment. The future
implementation must preserve the injected-evaluator boundary, the exact stable
codes, the direct/public route split, and redaction invariants. A change to any
of those is an invalidation event for this contract and its protected-test
hash, not an implementation detail to be silently adjusted. Production proof,
current-main identity, authenticated business behavior, real database or
external-system readback, deployment activation, rollback rehearsal, and
Stage-1 C1/C3/DC2 acceptance remain unverified and outside this fragment.
