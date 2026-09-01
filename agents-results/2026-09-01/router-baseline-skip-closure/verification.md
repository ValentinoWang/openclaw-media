# Router Baseline Closure Verification

- Verified source commit: `ef3481f92815883304d9363184a6d6f25411ffe5`
- Environment: Python 3.12.3 on the 106 verification host.
- Database: disposable `openclaw_router_test_20260901_baseline_fix_full`, created from `template0` and migrated in empty mode.
- Command: `scripts/qa/run_router_pytest.sh` with all six PostgreSQL test variables bound to the disposable database.
- Result: `1764 passed, 0 failed, 0 errors, 0 skipped` in 135.611 seconds.
- Pytest exit code: `0`.
- Skip guard exit code: `0`.

## Artifact Hashes

- `pytest-junit.xml`: `8dfe14ddd7655c5eb32269863e693645a688e33961d8385f971d3f8e2d7bd093`
- `pytest-output.txt`: `8a273066de16e1dfc27f6a11e009927d93f6fb5f06c43354f24b6b9a5c85f12c`
- `migration-output.txt`: `9395b94aaec1a27bb7093a7646218fa34870f1c406b8b1bc937f6093a9902397`
- `run-metadata.tsv`: `79417a20007349d7dab7ff1c0a34f7b17011acb89e0fe938ec4e303e71e3e241`
- `requirements-test.txt`: `b854d65d3a64f8dbbfbfb13e1acf497434112270d8981765cd3ef403659a864a`

The full runtime artifacts remained on the disposable verification host until remote readback completed; only this concise, hash-bound record is tracked.
