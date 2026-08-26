# Human Acceptance Binding: PR-REL-PLANNER

- Task ID: PR-REL-PLANNER
- Binding status: ACTIVE
- SSOT path: none
- SSOT node: none
- Acceptance contract: docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-PLANNER/acceptance-contract-v2.md
- Contract version: 2
- Contract SHA-256: b92b59c1b56df6d0edb6554f3c048a0f846b871421a6ebe242ca96a97eca42e4
- Human checklist: acceptance/human/PR-REL-PLANNER/checklist-v2.md
- Checklist SHA-256: 0a340369cabdff6a1a50bf807477f88ed16a331639331df756965fdef35537b9
- Protected test: openclaw-tag-router/tests/test_production_reconciliation_planner.py
- Protected test SHA-256: b3deaca939d4b6746659c1e0a83e47c923857242f06218f7d95f8a13ac07e898

## Version-2 decision

Version 2 resolves the v1 planner/fixture ordering conflict without weakening the immutable-release manifest gate. Planner-local manifest inventory order is not an acceptance condition; duplicate and unsafe paths remain invalid. Actual release manifests must still pass the stricter sorted-inventory `production_release_manifest.validate_manifest` gate.

## Item bindings

| Item | Required role | Blocking |
| --- | --- | --- |
| H-01 | Production reconciliation owner | Yes |
| H-02 | Production reconciliation owner | Yes |
| H-03 | Production reconciliation owner | Yes |
