# Acceptance Run: 20260825T170619Z-local-source-only-cb73d9

- Run ID: 20260825T170619Z-local-source-only-cb73d9
- Task ID: PR-REL-PLANNER
- Lane: machine/unit
- Status: PASS
- Acceptance contract: docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-PLANNER/acceptance-contract.md
- Contract version: 1
- Contract SHA-256: b3db48de31efcb66970e2d77273e74294d1bfae7f20d8c0ef950dfe42f5526e4
- Source identity: commit:01a8d39e9053270c717f601c804bd2ec3a077093
- Runtime identity: uv-cpython-3.12
- Executor or reviewer: lw-luna source implementation; main coordinator evidence recovery
- Started at: 2026-08-25T17:06:19.054764Z
- Completed at: 2026-08-25T17:13:36Z
- Evidence directory: evidence/

## Scope

This local-source-only run covers AC-01 through AC-19 on source commit
`01a8d39e9053270c717f601c804bd2ec3a077093`. The implementation was produced
and committed by the bounded lw-luna worker. Its response stream then failed
with repeated HTTP 502 errors before it could finalize this evidence run. The
main coordinator reran and recorded the frozen contract, protected CPython 3.12
test, compile, hash, and diff checks against the surviving source commit. No
remote host, network service, release pointer, database, Feishu, or production
system was accessed.

## Procedure

1. Validated the APPROVED/LOCKED acceptance contract and task evidence tree.
2. Ran the protected planner suite with uv CPython 3.12; all 44 tests passed.
3. Compiled the planner service and CLI and ran `git diff --check`.
4. Recomputed the contract and protected-test hashes and confirmed that the
   protected test still matched the locked hash.
5. Audited the source commit and confirmed it changed only the two reserved
   production paths. Exact commands and outputs are stored under `evidence/`.

## Requirement disposition

| Requirement | Result | Evidence | Notes |
| --- | --- | --- | --- |
| AC-01..AC-19 | PASS | evidence/protected-test-green.txt | The 44 locked tests cover schema, full-SHA identity, safe paths, manifest validation, pointer CAS, rollback compatibility, collisions, canonical redacted output, input immutability, stable errors, and the no-external-action boundary. |
| AC-20 | PASS | docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-PLANNER/acceptance/machine/unit/runs/20260825T162942Z-cpython312-red-a1b2c3/result.md | Frozen baseline RED proof remains preserved and the protected-test hash is unchanged. |

## Findings

The lw-luna response stream failed after the source commit with repeated 502
responses. The same selected primary retry also failed before returning a
structured result, so the external supervisor correctly retained a transport
`BLOCKED` disposition. This is an execution-audit finding, not a product-test
failure. The main coordinator recovered only the existing source and evidence
scope and independently reran the frozen validation commands.

## Evidence manifest

| Artifact | SHA-256 | Meaning |
| --- | --- | --- |
| evidence/protected-test-green.txt | 76562cf9da1393a36f02fca1547f1c885aa94c48ed2155ec9b4142f610ad3005 | Exact protected-test command and green output. |
| evidence/static-contract-source-checks.txt | 310e8835fbb550d2a154bb9f17b20ac1215bad1bb44af1af08d75583074a52df | Contract, artifact-tree, compile, diff, frozen-hash, and source-identity checks. |

## Unverified items

- No deployment, pointer switch, service restart, systemd or Nginx action,
  same-round production readback, observation window, or rollback was executed.
- No authenticated Stage-2 business workflow, real database or Feishu behavior,
  device behavior, current production identity, or human release approval was
  verified.
- The local plan API is declarative only. Passing this run does not make the
  release READY and does not change formal Stage-2 SSOT acceptance status.

## Conclusion

PASS: the source commit satisfies the locked local planner contract and its 44
protected tests. The worker's missing structured return remains recorded as a
transport failure in the external supervisor ledger. This run is source-only
machine evidence, not deployment, release, production, or human acceptance.
