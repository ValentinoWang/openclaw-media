# Human Acceptance Binding: PR-REL-PLANNER

- Task ID: PR-REL-PLANNER
- Binding status: ACTIVE
- SSOT path: none
- SSOT node: none
- Acceptance contract: docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-PLANNER/acceptance-contract.md
- Contract version: 1.1 (`v1` plus the 2026-08-26 ordering-boundary amendment)
- Contract SHA-256: b3db48de31efcb66970e2d77273e74294d1bfae7f20d8c0ef950dfe42f5526e4
- Contract amendment: acceptance/human/PR-REL-PLANNER/amendment-20260826.md
- Amendment SHA-256: 9140a93b35aa3349b28c5fe453891fad4077182154e3de6bd4df0455791e942a
- Human checklist: acceptance/human/PR-REL-PLANNER/checklist.md
- Checklist SHA-256: db9d8942ec223c47351a47463dc3fdcc60ea18861336b2124f6ffde3aaa72800
- Protected planner test: openclaw-tag-router/tests/test_production_reconciliation_planner.py
- Protected test SHA-256: b3deaca939d4b6746659c1e0a83e47c923857242f06218f7d95f8a13ac07e898

## Ordering-boundary decision

The original v1 contract remains authoritative except for the manifest-inventory ordering ambiguity corrected by the 1.1 amendment. `production_release_manifest.validate_manifest` owns lexicographic inventory enforcement for real immutable releases. The pure planner does not duplicate that filesystem-backed validator.

## Item bindings

| Item | Required role | Blocking |
| --- | --- | --- |
| H-01 | Production reconciliation owner | No |
| H-02 | Production reconciliation owner | No |
| H-03 | Production reconciliation owner | No |
