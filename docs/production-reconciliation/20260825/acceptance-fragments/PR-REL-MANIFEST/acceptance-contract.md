# Acceptance Contract: PR-REL-MANIFEST

- Task ID: PR-REL-MANIFEST
- Contract version: 1
- Contract status: APPROVED
- Test baseline: LOCKED
- Acceptance owner: User-authorized source-only Production Reconciliation owner
- Approval evidence: The user's supplied 2026-08-25 Production Reconciliation baseline `BASELINE=59e2adf` (parent source authority GitHub main `5f06780569568ccc3197f0ab16aad74bdf9d1c6f`), bounded task source `TASK_SOURCE_SHA256=a74922a742e44b1ac2b9eb556f9c858bfbd91e7ecb44bbfdf1264dda3a2a071a`, and the explicit continuation authorization in `PR-REL-MANIFEST-DESIGN-V2`. This records source-only contract authority only; it is not product, deployment, release, or production acceptance.
- Request source: Bounded task `PR-REL-MANIFEST-DESIGN-V2` supplied by the user on 2026-08-26
- SSOT node: none
- SSOT path: none
- Readiness mode: FORMAL
- Decision refs: none
- Assumption IDs: none
- Invalidation keys: pr-rel-manifest.contract, production-reconciliation-20260825.source-shas, production-reconciliation-20260825.deployment-gate, production-release-manifest-v1
- Baseline identity: branch `codex/pr-rel-manifest-design`, commit `59e2adfd34853b6929d9fa69e69585806ac9c83a`, parent source authority GitHub main `5f06780569568ccc3197f0ab16aad74bdf9d1c6f`
- Human acceptance workspace: acceptance/human/2026-W35/2026-08-25-PR-REL-MANIFEST
- UI Change declaration: none

## User and scenario

The source-only release engineer or future implementation owner needs a pure,
local production-release manifest contract before any release activation work.
The supported surface is a checked-out source tree, a target-relative inventory,
the protected tests, and a JSON manifest. This fragment does not authorize
network, deployment, service, pointer, Nginx, database, Feishu, or secret
operations.

The contract exposes the following implementation-independent public behavior
for the reserved future implementation module:

- `build_manifest(target_root, *, file_paths, previous_release_identity=None)`
  reads only the local target tree and its Git identity, and returns a v1
  manifest. `file_paths` is an explicit iterable of target-relative paths.
- `canonical_manifest_json(manifest)` returns one compact JSON text without a
  trailing newline. It sorts object keys recursively and excludes only the
  top-level `manifest_sha256` field before hashing.
- `validate_manifest(manifest, target_root, *, expected_source_sha,
  expected_previous_release_identity=None)` returns normally for a valid
  manifest and raises `ManifestValidationError` otherwise. The exception has a
  stable `.code`; failure codes are listed below.

## Problem

The frozen reconciliation evidence contains a selected-file observation, not an
immutable release manifest. It does not bind a clean Git commit to a complete
target-relative file inventory, prove each file digest and mode, or fail closed
when mutable, secret, runtime, traversal, symlink, source, manifest, or previous
release identity inputs drift.

Without this contract, a future builder could accidentally hash a different
source tree, follow a symlink, include runtime state or credentials, serialize
secret values, or accept a digest that does not describe the manifest being
validated.

## Expected outcome

Version 1 defines a deterministic manifest with exactly these top-level keys:

```json
{
  "schema_version": "production-release-manifest.v1",
  "source": {
    "git_sha": "40 lowercase hexadecimal characters",
    "git_clean": true
  },
  "target": {
    "root": ".",
    "files": [
      {
        "path": "target-relative/posix/path",
        "sha256": "64 lowercase hexadecimal characters",
        "mode": "100644"
      }
    ]
  },
  "previous_release_identity": null,
  "manifest_sha256": "64 lowercase hexadecimal characters"
}
```

`source` has no extra keys. `target` has no extra keys. Each file entry has no
extra keys. `previous_release_identity` is either `null` or an object with only
`git_sha` and `manifest_sha256`, using the same digest formats. The file list is
non-empty, sorted by `path`, and has unique paths. Modes are exactly `100644` or
`100755`; integer modes, short modes, permission-only modes, and other Git modes
are invalid.

The manifest digest is the lowercase SHA-256 hex digest of the UTF-8 bytes of
`canonical_manifest_json` after removing only the top-level
`manifest_sha256`. The canonical text is compact, recursively key-sorted,
ASCII-safe JSON with no trailing newline. File contents and secret values never
appear in the manifest or canonical text; only file digests are recorded.

`build_manifest` must obtain the current `HEAD` SHA from the target Git tree and
must fail closed unless `git status --porcelain=v1 --untracked-files=all` is
empty and a resolvable `HEAD` exists. It computes each requested regular-file
digest and Git mode, rejects disallowed paths before producing output, and
returns the canonical inventory. It does not mutate the source tree.

`validate_manifest` checks the manifest digest before accepting any identity or
inventory claim, compares `source.git_sha` with `expected_source_sha`, requires
`source.git_clean` to be true, compares `previous_release_identity` with the
expected value, checks every target path against the actual target root, and
does not mutate its input or the target tree.

## Non-goals

- This fragment does not implement the reserved module, schema file, or build
  script.
- It does not create, upload, activate, switch, roll back, or read back a
  production release.
- It does not modify systemd, pointers, Nginx, databases, Feishu, Git remotes,
  or the Stage-2 SSOT state.
- It does not read real secret values, environment values, runtime state, or
  authenticated production responses.
- It does not claim that current-main Stage-2 route composition, external
  systems, deployment, rollback rehearsal, human release approval, or Stage-1
  C1/C3/DC2 acceptance exists.
- It does not require a human to repeat deterministic path, mode, digest, or
  schema assertions.

## Normal path

```gherkin
Given a Git checkout with a resolvable HEAD and no staged, unstaged, or untracked changes
And the caller supplies a non-empty list of regular, target-relative, release-safe paths
When build_manifest reads the paths and creates the v1 manifest
Then source.git_sha is the checkout HEAD, source.git_clean is true, and the inventory is sorted and unique
And each file entry contains its actual SHA-256 and an allowed Git mode
And canonical_manifest_json is deterministic and excludes manifest_sha256
And validate_manifest accepts the manifest for the same target, source SHA, and previous-release identity
```

## Exception paths

- A missing Git repository, missing HEAD, dirty index/worktree, or untracked
  file fails closed with `SOURCE_NOT_CLEAN` or `SOURCE_UNAVAILABLE`; no partial
  manifest is returned.
- A missing target file fails closed with `FILE_MISSING`. A directory, device,
  FIFO, or other non-regular file fails closed with `UNSUPPORTED_FILE_TYPE`.
- `..`, empty, dot, backslash, NUL, drive-prefixed, absolute, or root-escaping
  paths fail closed with `PATH_TRAVERSAL` or `ABSOLUTE_PATH` as applicable.
- Duplicate literal or normalized paths fail closed with `DUPLICATE_PATH`.
- Any symlink, including a symlink that resolves inside the target, fails closed
  with `UNSUPPORTED_SYMLINK`; the validator never follows it for acceptance.
- Mutable, secret, or runtime paths fail closed with `MUTABLE_PATH`,
  `SECRET_PATH`, or `RUNTIME_PATH`.
- A missing, malformed, or mismatched file digest fails closed with
  `MISSING_DIGEST`, `MALFORMED_DIGEST`, or `DIGEST_MISMATCH`.
- A missing, non-string, or unsupported mode fails closed with
  `MALFORMED_MODE`.
- A source SHA mismatch fails closed with `SOURCE_SHA_MISMATCH`. A false clean
  flag fails closed with `SOURCE_NOT_CLEAN`.
- A missing, extra, or mismatched manifest digest fails closed with
  `MANIFEST_DIGEST_MISMATCH`.
- A previous-release identity mismatch, including null versus object mismatch,
  fails closed with `PREVIOUS_RELEASE_IDENTITY_MISMATCH`.
- Unknown schema keys or secret-bearing fields fail closed with `SCHEMA_INVALID`
  or `SECRET_DISCLOSURE`. Error text must not echo secret values or file bytes.
- Canonical serialization and validation preserve the caller's objects and
  filesystem. A failed operation does not write a partial manifest.

## Invariants

1. The accepted source identity is a clean, exact 40-character lowercase Git
   commit SHA; no branch name, remote ref, mutable timestamp, or path replaces
   it.
2. `target.root` is exactly `.` and every inventory path is target-relative
   POSIX syntax. The manifest never stores an absolute local path.
3. The file list is deterministic, sorted, unique, and describes regular files
   only. Symlink metadata is never accepted as a regular file.
4. The only file metadata serialized is `path`, `sha256`, and `mode`; file bytes,
   environment values, credentials, tokens, and runtime contents are never
   serialized.
5. Canonical serialization of equivalent key orders is byte-for-byte identical
   and does not include `manifest_sha256`; changing any covered field changes
   the expected digest.
6. All invalid input fails closed with a stable code and no fallback or partial
   acceptance.
7. Validation is read-only and does not rewrite the manifest, source tree, or
   target tree.

The path policy is deliberately explicit for this v1 release boundary:

- Runtime prefixes: `runtime/` and `run/`.
- Mutable prefixes: `state/`, `var/`, `cache/`, `logs/`, `tmp/`, and
  `uploads/`; mutable suffixes: `.db`, `.sqlite`, `.sqlite3`, `.log`, `.pid`,
  `.sock`, `.lock`, and `.jsonl`.
- Secret paths: `.env` and `.env.*`, the observed `stage2.env` and
  `session-material.env`, segments or basenames named `secret`, `secrets`,
  `credential`, `credentials`, `token`, `tokens`, or `password`, and secret
  material suffixes `.pem`, `.key`, `.p12`, `.pfx`, and `.jks`.

## Data impact

The builder reads Git metadata and explicitly requested file bytes from a local
checkout, and returns an in-memory manifest. The script in the reserved future
scope may write one manifest output file chosen by its caller; this contract
does not authorize any other write. The validator is read-only. There is no
database migration, external side effect, retention policy, cleanup, rollback
write, or persistent state change in this fragment. A previous-release identity
is compared only as an immutable input; it is never updated.

## Permissions

The local source-only operator may run the builder and validator against an
authorized checkout. No credential, environment value, runtime-state read,
network access, deployment action, service action, or release approval is
permitted. Human review may judge operational clarity and whether the contract
is suitable for a later release workflow, but it may not override a deterministic
validator result or authorize production mutation.

## Performance and reliability

The validator and canonical serializer are deterministic local operations with
time proportional to the manifest entry count and file bytes read. They must not
call a network service, wait on a service, or retry an external dependency. Git
or filesystem errors are terminal fail-closed outcomes. The builder must not
emit a partial result after any error. The protected tests use small temporary
trees and must remain repeatable without network access.

## Acceptance criteria

| ID | Requirement | Verification layer | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | The v1 schema has the exact required top-level, source, target, file-entry, and previous-release identity shape. | Unit | Automatic | Yes |
| AC-02 | The builder binds a clean Git HEAD SHA and rejects dirty or untracked source trees. | Integration-contract | Automatic | Yes |
| AC-03 | The target root is `.` and traversal, absolute, drive-prefixed, backslash, NUL, and root-escaping paths are rejected. | Unit | Automatic | Yes |
| AC-04 | Duplicate inventory paths are rejected before acceptance. | Unit | Automatic | Yes |
| AC-05 | Symlinks and non-regular files are rejected without following them. | Unit | Automatic | Yes |
| AC-06 | Mutable path prefixes and mutable file suffixes are rejected. | Unit | Automatic | Yes |
| AC-07 | Secret paths and secret-bearing schema fields are rejected without reading or echoing secret values. | Unit | Automatic | Yes |
| AC-08 | Runtime path prefixes are rejected. | Unit | Automatic | Yes |
| AC-09 | Missing or malformed file digests are rejected. | Unit | Automatic | Yes |
| AC-10 | File digest mismatches against the target bytes are rejected. | Unit | Automatic | Yes |
| AC-11 | Only modes `100644` and `100755` are accepted; malformed modes fail closed. | Unit | Automatic | Yes |
| AC-12 | A manifest source SHA that differs from the expected source SHA is rejected. | Unit | Automatic | Yes |
| AC-13 | Canonical JSON is compact, sorted, deterministic, newline-free, and excludes `manifest_sha256` from hashing. | Unit | Automatic | Yes |
| AC-14 | Missing, extra, or mismatched manifest digests are rejected. | Unit | Automatic | Yes |
| AC-15 | Previous-release identity mismatches are rejected, including null/object differences. | Unit | Automatic | Yes |
| AC-16 | Unknown schema fields and invalid identity/digest shapes are rejected with stable fail-closed errors. | Unit | Automatic | Yes |
| AC-17 | The builder emits a sorted target-relative inventory with actual file digests and modes. | Integration-contract | Automatic | Yes |
| AC-18 | Valid validation does not mutate the manifest input or target tree. | Unit | Automatic | Yes |
| AC-19 | Failure codes are stable and error output does not contain file bytes or secret values. | Unit | Automatic | Yes |
| AC-20 | The protected test file is red on the frozen baseline because the public implementation does not exist. | Static and unit | Automatic | Yes |
| AC-21 | The implementation declaration remains limited to the three reserved future paths and does not claim deployment or release acceptance. | Static review | Automatic | Yes |

## Human acceptance

Human judgment is limited to source-only operational clarity. These items are
non-blocking for source-only code completion and do not duplicate deterministic
manifest assertions.

| ID | Summary | Checklist path | Required role | Blocking |
| --- | --- | --- | --- | --- |
| H-01 | The source-only boundary and remaining release blockers are understandable to an operator. | acceptance/human/2026-W35/2026-08-25-PR-REL-MANIFEST/checklist.md#h-01 | Production reconciliation owner | No |
| H-02 | The future implementation scope and handoff evidence are clear without inferring extra deployment authority. | acceptance/human/2026-W35/2026-08-25-PR-REL-MANIFEST/checklist.md#h-02 | Production reconciliation owner | No |

## Protected acceptance tests

| Path | SHA-256 | Covers |
| --- | --- | --- |
| openclaw-tag-router/tests/test_production_release_manifest.py | dd653b45ebce1d09593f232673506262e7720dff571474fe5f1afc19737e0187 | AC-01 through AC-20: schema, clean source identity, inventory policy, canonical serialization, digest and mode validation, previous identity, non-mutation, secret disclosure, and red baseline |

## Requirements-test traceability

| Requirement | Verification | Evidence target | Mode | Blocking |
| --- | --- | --- | --- | --- |
| AC-01 | Protected test module | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-02 | Protected Git fixture tests | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-03 | Protected path parameterization | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-04 | Protected duplicate-path test | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-05 | Protected symlink and file-type tests | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-06 | Protected mutable-path tests | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-07 | Protected secret-path and serializer tests | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-08 | Protected runtime-path test | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-09 | Protected missing and malformed digest tests | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-10 | Protected target-byte digest test | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-11 | Protected mode parameterization | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-12 | Protected source mismatch test | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-13 | Protected canonical JSON test | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-14 | Protected manifest digest mismatch test | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-15 | Protected previous identity test | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-16 | Protected unknown-field test | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-17 | Protected builder inventory test | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-18 | Protected non-mutation test | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-19 | Protected error-code and secret-output tests | openclaw-tag-router/tests/test_production_release_manifest.py | Automatic | Yes |
| AC-20 | Red-proof run under the fragment acceptance tree | docs/production-reconciliation/20260825/acceptance-fragments/PR-REL-MANIFEST/acceptance/machine/unit/runs/<run-id>/result.md | Automatic | Yes |
| AC-21 | Contract, reserved-scope declaration, clean-tree check, and user return | acceptance-contract.md and structured return | Automatic | Yes |
| H-01 | Project-level Chinese human checklist | acceptance/human/2026-W35/2026-08-25-PR-REL-MANIFEST/checklist.md#h-01 | Human | No |
| H-02 | Project-level Chinese human checklist | acceptance/human/2026-W35/2026-08-25-PR-REL-MANIFEST/checklist.md#h-02 | Human | No |

## Exploratory testing

Exploration is optional and cannot override the protected baseline. If later
performed, probe Unicode filenames, case-sensitive duplicate spellings, very
large file lists, empty files, executable `100755` files, broken symlinks,
permission errors, interrupted reads, unusual JSON scalar types, and changes to
the target between inventory and validation. Record any probe under the task
acceptance tree with a unique run ID; do not convert an exploratory observation
into a release claim without a separate approved contract.

## Production monitoring and rollback

Not applicable to this source-only fragment. No production process is started,
no release pointer is changed, and no rollback is executed. A later deployment
contract must separately define active-release readback, pointer CAS, rollback
target validation, monitoring thresholds, and authorized human approval.

## Risks and open decisions

The v1 acceptance decision is approved for the exact source-only contract above.
The following are explicitly outside this fragment and remain unverified:

- current-main authenticated Stage-2 route composition and real external-system
  behavior;
- deployment readback, service binding, pointer CAS, activation, and rollback
  rehearsal;
- production/device evidence, real AI/provider evidence, database evidence, and
  Feishu evidence;
- Stage-1 C1/C3/DC2 acceptance and formal Stage-2 SSOT status;
- human approval to use a future manifest for an actual production release.

Reserved future implementation scope, declared here and intentionally not
written by this task:

- `openclaw-tag-router/openclaw_app/services/production_release_manifest.py`
- `openclaw-tag-router/openclaw_app/contracts/production-release-manifest.v1.schema.json`
- `openclaw-tag-router/scripts/build_production_release_manifest.py`

The exact user-authorized scope is the only approval recorded here. Any change
to the manifest fields, path policy, error codes, public call surface, reserved
implementation paths, deployment authority, or release claim requires a new or
superseding acceptance decision.
