# PR-REL-PLANNER Contract Amendment — 2026-08-26

- Task ID: PR-REL-PLANNER
- Amendment version: 1.1
- Status: APPROVED CORRECTION
- Scope: manifest inventory ordering responsibility only
- Supersedes: the ambiguous wording in contract version 1 that could be read as requiring the pure planner to independently revalidate manifest inventory ordering.

## Corrected boundary

`production-release-manifest.v1` is the authoritative manifest validator. A release manifest must pass
`openclaw_app.services.production_release_manifest.validate_manifest(...)` before it is supplied to
`plan_production_reconciliation(...)`.

The manifest validator owns:

- target-root file readback and digest verification;
- canonical safe relative paths and allowed modes;
- duplicate-path rejection;
- lexicographically sorted inventory enforcement;
- clean source identity and previous-release identity checks.

The pure planner remains input-only and performs defensive schema, identity, digest, path-policy,
pointer-CAS, rollback-compatibility, collision, redaction, and deterministic-plan checks. It does not
duplicate the filesystem-backed manifest validator and therefore does not reject an otherwise
well-formed in-memory manifest solely because its `target.files` list is not sorted.

Calling the planner directly with a manifest that has not first passed the manifest validator is
outside the production activation boundary. The activation executor must fail closed if manifest
validation has not succeeded.

## Test freeze

The existing protected planner test
`openclaw-tag-router/tests/test_production_reconciliation_planner.py` remains byte-for-byte unchanged
and is re-affirmed as the planner-unit baseline. Its synthetic inventory order is intentionally not
treated as a filesystem manifest-validation fixture.

A separate regression test locks the cross-module boundary: an unsorted real release manifest is
rejected by `production_release_manifest.validate_manifest` before planning.

## Implementation rule

There must be exactly one implementation module:
`openclaw_app/services/production_reconciliation_planner.py`.

A facade plus a copied `production_reconciliation_planner_legacy.py` implementation is forbidden.
