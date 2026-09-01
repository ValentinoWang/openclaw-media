# Stage-2 Document Edit Validation

- Source commit: `007a7f906af4e23a6a4fa5d041da4cb0641646c2`
- Observed: `2026-09-01T16:50:00+08:00`
- Scope: T5 durable document-edit jobs and Lark receipt readback, T6 sync-batch projection, C6 save/readback and AI-revision UI, generated business-page contract.

## Passing Evidence

| Command | Result | Durable output |
| --- | --- | --- |
| `python -m pytest tests/test_document_edit_executor.py tests/test_media_business_runs.py tests/test_media_business_sync_batches.py tests/test_http_api.py tests/test_postgres_migration_runner.py tests/test_media_web_business_pages_contract.py tests/test_router_pytest_environment.py -q` | `104 passed, 12 subtests passed` | `router-focused-pytest-output.txt` |
| `npm run qa:media-stage2-document-screenshots` | 64/64 matrix cells, 72 screenshots, zero failed/pending/request/page-error cells | `stage2-document-screenshot-manifest.json` |
| `npm run build:media` | passed; Vite completed and all configured frontend gates passed | `media-build-output.txt` |

SHA-256:

```text
35113d3a55f40cfb541e0f0eab909645a6563d04ab4597188ed305e8940a30b9  router-focused-pytest-output.txt
584ace864139a7885b2bb4ecb378c9103d5fdb4dd9c80d0314b4cd5a93e2d3f3  stage2-document-screenshot-manifest.json
f282a02b1ff17a18e3aaa85a84a1ac61ca7067e14e6ce6925660c361c83c66a2  media-build-output.txt
7e403e768a336f3f808f1a2f7136627584808ce6fc8c3265c6fb03abb739818a  router-full-pytest-output.txt
64b04aab742b58467c446fb19a16f6a168da3375395a6bbce902e10a78dd963a  router-full-pytest-metadata.tsv
```

## Full-Suite Baseline

The broader Router suite at this commit reported `1683 passed, 40 skipped, 32 failed`; its source identity and exit status are in `router-full-pytest-metadata.tsv`. The same command at parent `37e58dc3` reported `1668 passed, 40 skipped, 42 failed`; the current 32 failing test identities are all present in the parent failure set. The ten removed parent failures are obsolete migration-inventory assertions. This comparison prevents treating unrelated historical failures as Stage-2 regressions, but it is not formal acceptance, production migration, live Lark write/readback, or human sign-off.
