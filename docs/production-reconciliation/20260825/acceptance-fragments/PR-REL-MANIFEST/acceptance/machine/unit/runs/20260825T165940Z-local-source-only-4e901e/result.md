# Acceptance Run: 20260825T165940Z-local-source-only-4e901e

- Run ID: 20260825T165940Z-local-source-only-4e901e
- Task ID: PR-REL-MANIFEST
- Lane: machine/unit
- Status: PASS
- Acceptance contract: docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-MANIFEST/acceptance-contract.md
- Contract version: 1
- Contract SHA-256: 8ffe2adebbf86aad61b0c1396b623a1321a6a97958eb1f327177481024000537
- Source identity: commit:7d385d3
- Runtime identity: uv-cpython-3.12
- Executor or reviewer: lw-luna
- Started at: 2026-08-25T16:59:40.318249Z
- Completed at: 2026-08-25T17:00:31Z
- Evidence directory: evidence/

## Scope

This local-source-only run covers the implementation of the reserved v1
production-release manifest API, schema, and builder at source commit
`7d385d3e117fe8848b8412c2630100dc0fd8b8c4`. It covers AC-01 through AC-19
and AC-21 through the protected CPython 3.12 test, contract validation, JSON
schema parse, Python compilation, and source diff checks. No network, service,
database, deployment, release pointer, or production system was accessed.

## Procedure

The protected command and its exact output are in
`evidence/protected-test-green.txt`. Contract, schema, compile, diff, and
frozen-hash commands and their exact output are in
`evidence/static-contract-source-checks.txt`.

## Requirement disposition

| Requirement | Result | Evidence | Notes |
| --- | --- | --- | --- |
| AC-01..AC-19 | PASS | evidence/protected-test-green.txt | 30 protected tests passed under uv CPython 3.12; covers schema, source identity, path policy, symlink/type rejection, digests, modes, canonical JSON, previous identity, immutability, and redacted stable errors. |
| AC-20 | PASS | docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-MANIFEST/acceptance/machine/unit/runs/20260826T000000Z-red-proof-a1b2c3/result.md | Frozen baseline red proof is preserved; the protected test file remained unchanged. |
| AC-21 | PASS | evidence/static-contract-source-checks.txt | Contract passed, hashes matched, source HEAD was recorded, and only the three reserved production paths changed in the source commit. |

## Findings

None. The run is source-only and passed.

## Evidence manifest

| Artifact | SHA-256 | Meaning |
| --- | --- | --- |
| evidence/protected-test-green.txt | 5f380eb37e04611cd863cb6c2658008bedaa1811dfc1a0ef209ccd8922d5fc28 | Exact protected test command and green output. |
| evidence/static-contract-source-checks.txt | 0f2d517223ffc30bc7cfe85b0c540075f7366bb213d3f1696eb263a91e43fbcc | Exact contract, schema, compile, diff, and frozen-hash checks and output. |

## Unverified items

This run does not prove current-main route composition, authenticated E2E,
device behavior, real AI/provider behavior, database or Feishu behavior,
deployment readback, service binding, pointer CAS, activation, rollback,
monitoring, human release approval, Stage-1 C1/C3/DC2 acceptance, or formal
Stage-2 SSOT status. It does not authorize or claim a release or production
acceptance.

## Conclusion

PASS: the acceptance-locked source implementation and its protected local
automated evidence are complete at commit
`7d385d3e117fe8848b8412c2630100dc0fd8b8c4`. This is not release or
production acceptance.
