# Router Pytest Zero-Skip Guard Card

- Failure class: Router tests silently return exit code 0 when required fixtures or environments cause skips.
- Layer: project runtime/QA gate.
- Stage: enforced.
- Severity: release-gate.
- Scope: test cases collected by `scripts/qa/run_router_pytest.sh`; the runner no longer excludes a test file.
- Trigger: any `<testcase>` contains a `<skipped>` child, the JUnit report has no test cases, its root/counts are invalid, or the report directory is not empty before the run.
- Repair path: provide the required disposable fixture or environment, remove an obsolete test instead of skipping it, and start each run with an empty evidence directory.
- Cost: negligible XML parsing after the complete Router suite.
- Retirement: remove when the selected pytest version has an equivalent built-in fail-on-skip option covered by the same red/green proof.

## Proof

- Historical red: the PostgreSQL baseline returned exit code 0 with 40 skipped tests.
- Synthetic red: `test_router_skip_guard_has_red_and_green_runtime_proof` builds a JUnit report with one skipped case and requires guard exit code 3 plus the exact test id.
- Structural red: the same test rejects zero-test reports, invalid roots, and inconsistent `tests`/`skipped` suite counts.
- Runner red: `test_router_runner_propagates_the_skip_guard_failure` proves a pytest exit 0 plus one skipped case produces runner exit 3 and matching metadata.
- Green: the same test builds a report with no skipped cases and requires exit code 0.
- Database negative proof: `test_router_runner_rejects_missing_or_non_disposable_database_url` requires fail-closed behavior before migration for a missing URL and for `postgresql:///production`.
- Full green: `scripts/qa/run_router_pytest.sh` must finish with every collected test passed and the skip guard at 0.
