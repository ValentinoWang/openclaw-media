# Acceptance Run: 20260825T165620Z-uv-cpython312-e27e98

- Run ID: 20260825T165620Z-uv-cpython312-e27e98
- Task ID: PR-REL-READBACK
- Lane: machine/unit
- Status: PASS
- Acceptance contract: docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-READBACK/acceptance-contract.md
- Contract version: 1
- Contract SHA-256: ae12561d38b281fc44a299d4589c0b72a6681109002327c60f7be1cb67ced57c
- Source identity: commit:e27e98432d46eace2c95c0f7f6034419e44c73ce
- Runtime identity: uv-cpython-3.12
- Executor or reviewer: lw-luna
- Started at: 2026-08-25T16:56:42.456940Z
- Completed at: 2026-08-25T16:57:26Z
- Evidence directory: evidence/

## Scope

This machine/unit run covers AC-01 through AC-13 on the source commit
`e27e98432d46eace2c95c0f7f6034419e44c73ce`. The evaluator received only the
protected test's in-memory observation and expected identity under local
CPython 3.12.11 selected by `uv`; no host service, filesystem capture,
network, remote transport, database, Feishu, or production operation was used.

## Procedure

1. `uv run --python 3.12 python --version` returned `Python 3.12.11`.
2. `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=openclaw-tag-router uv run --python 3.12 --with pytest python -m pytest -q openclaw-tag-router/tests/test_stage2_release_readback.py` exited `0` with `13 passed, 7 subtests passed in 0.09s`.
3. `python3 -m py_compile openclaw-tag-router/scripts/qa/check_stage2_release_process.py` exited `0`.
4. `git diff --check` exited `0` before the source commit.
5. The protected test hash remained `a70096254718873de191d3cef266d8fa3ae820b26ffcf516649a3fc42d255ace`.

## Requirement disposition

| Requirement | Result | Evidence | Notes |
| --- | --- | --- | --- |
| AC-01 | PASS | evidence/protected-test-green.log | Complete injected observation returned PASS/OK. |
| AC-02 | PASS | evidence/protected-test-green.log | Inactive service rejected with the locked stable code. |
| AC-03 | PASS | evidence/protected-test-green.log | Missing and malformed MainPID cases rejected. |
| AC-04 | PASS | evidence/protected-test-green.log | PID cwd drift rejected. |
| AC-05 | PASS | evidence/protected-test-green.log | ExecStart and process-module drift rejected. |
| AC-06 | PASS | evidence/protected-test-green.log | Settings and port drift rejected. |
| AC-07 | PASS | evidence/protected-test-green.log | Pointer/release-root drift rejected. |
| AC-08 | PASS | evidence/protected-test-green.log | Manifest identity drift rejected. |
| AC-09 | PASS | evidence/protected-test-green.log | Missing required systemd properties rejected. |
| AC-10 | PASS | evidence/protected-test-green.log | HTTP status mismatch rejected. |
| AC-11 | PASS | evidence/protected-test-green.log | Direct and public route surfaces remained distinct. |
| AC-12 | PASS | evidence/protected-test-green.log | Sensitive observation material did not enter the result. |
| AC-13 | PASS | evidence/protected-test-green.log | Injected-only execution passed with external calls patched to fail. |

## Findings

None. The locked protected suite is green for the bounded local evaluator.

## Evidence manifest

| Artifact | SHA-256 | Meaning |
| --- | --- | --- |
| evidence/protected-test-green.log | 4cb64dd4f3c3f92594ada07767d7f4b99c9cedfd96b49f8f81574c016b5fa772 | Exact protected-test green output. |

## Unverified items

- It does not prove a live production readback, deployment activation, release acceptance, rollback, or current production pointer/service state.
- It does not prove authenticated Stage-2 business behavior, real database or Feishu behavior, device behavior, current GitHub `main`, or Stage-1 C1/C3/DC2 acceptance.
- It does not prove any production environment value, credential, cookie, Authorization value, or secret-bearing argv was read; the evaluator was injected-only.

## Conclusion

The protected unit/contract suite passes on the committed implementation, so
the injected Stage-2 readback evaluator satisfies AC-01 through AC-13 at the
local source-validation layer. This run must not be promoted to live readback,
deployment, release, or production acceptance evidence.
