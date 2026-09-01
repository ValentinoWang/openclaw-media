# Stage-2 Formal DAG Review

## Frozen identity

| Field | Value |
| --- | --- |
| Repository | `/Users/vsiyo/.Trash/mediaclaw-stylekit-publish-20260901` |
| Frozen ref | `main` at `dba33b95e9ca124f22166ca4e34ee6ba27316e31` |
| Review scope | Stage-2 SSOT, generated views, human bindings/checklists, acceptance log, development brief, and recorded evidence in the frozen tree |
| Declared progress | `3/32`: A, A1, and K are the terminal baseline; the remaining 29 nodes are `BLOCKED` |
| Stage-2 SSOT bundle | `agents-results/2026-08-15/media-c-b-stage-2-content-and-ai-document-routing` |
| Stage-1 authority | `agents-results/2026-08-15/media-c-b-stage-1-identity-and-organization-onboarding` |
| Sole report write | `acceptance/release/runs/2026-09-01-stage2-dev-brief-dba33b95/evidence/review-lanes/formal-dag.md` |

The generated progress ledger records implementation and execution evidence against source SHA `007a7f906af4e23a6a4fa5d041da4cb0641646c2`, not the frozen review SHA. A separate regeneration record uses `d3555ccb58ff616eee66e3f057a5990ac4455d02`. These are evidence-identity mismatches, not alternate identities for this review.

Reviewed authority paths include `build_ssot.py`, `.ssot/nodes/*.json`, `generated-views/10-dependency-topology.md`, `generated-views/30-node-contracts-and-acceptance.md`, `implementation-progress.md`, `generated-views/40-acceptance-execution.md`, the four ST2 acceptance fragments and human workspaces, `acceptance/human-acceptance-log.json`, and `docs/frontend/prototype/stage2-dev-brief.md`.

## Formal node/dependency table

The `SSOT hard dependencies` column is the exact incoming dependency set emitted in `.ssot/nodes/*.json`. The `additional formal blocker` column records the cross-stage projection condition where it is not represented as a local node dependency.

| Node | Stage | State | SSOT hard dependencies | Additional formal blocker | Immediate unlocks |
| --- | --- | --- | --- | --- | --- |
| A | A | terminal baseline | - | none | A1 |
| A1 | A | terminal baseline | A | none | F1, F2, F3, K |
| K | A | terminal baseline | A1 | none | B |
| F1 | A | `BLOCKED` | A1 | Stage-1 C1 and same-candidate I9 must both satisfy the automatic projection rule | B, Stage-2 C1 |
| F2 | A | `BLOCKED` | A1 | Stage-1 C3 and matching candidate identity are required | O1, S3 |
| F3 | A | `BLOCKED` | A1 | Stage-1 DC2 and matching release identity are required | C |
| B | A | `BLOCKED` | F1, K | F1 is blocked | C1, O1, S1, T1 |
| S1 | B | `BLOCKED` | B | B is blocked | S, S2, S3, S5 |
| S2 | B | `BLOCKED` | S1 | S1 is blocked | C4, O2, S |
| S3 | B | `BLOCKED` | F2, S1 | F2 and S1 are blocked | C5, O2, S, S4, S5 |
| S4 | B | `BLOCKED` | S3 | S3 is blocked | C5, O3, S |
| S5 | B | `BLOCKED` | S1, S3 | S1 and S3 are blocked | C5, O2, S |
| T1 | B | `BLOCKED` | B | B is blocked | C8, O6, S |
| Stage-2 C1 | B | `BLOCKED` | B, F1 | B and F1 are blocked | C2, C3 |
| C2 | B | `BLOCKED` | C1 | Stage-2 C1 is blocked | C4 |
| C3 | B | `BLOCKED` | C1 | Stage-2 C1 is blocked | C4 |
| C4 | B | `BLOCKED` | C2, C3, S2 | all three parents are blocked | C5 |
| C5 | B | `BLOCKED` | C4, S3, S4, S5 | all four parents are blocked | C6 |
| C6 | B | `BLOCKED` | C5 | C5 is blocked | C7 |
| C7 | B | `BLOCKED` | C6 | C6 is blocked | C8 |
| C8 | C | `BLOCKED` | C7, S, T1 | all three parents are blocked | C |
| O1 | B | `BLOCKED` | B, F2 | B and F2 are blocked | O2 |
| O2 | B | `BLOCKED` | O1, S2, S3, S5 | all four parents are blocked | O3 |
| O3 | B | `BLOCKED` | O2, S4 | both parents are blocked | O4 |
| O4 | B | `BLOCKED` | O3 | O3 is blocked | O5 |
| O5 | B | `BLOCKED` | O4 | O4 is blocked; the required Lark human lane is also incomplete | O6 |
| O6 | C | `BLOCKED` | O5, S, T1 | all three parents are blocked | C |
| S | C | `BLOCKED` | S1, S2, S3, S4, S5, T1 | the shared convergence branch is blocked | C8, O6 |
| C | C | `BLOCKED` | C8, F3, O6 | both branch convergences and F3 are blocked | DA |
| DA | D | `BLOCKED` | C | C is blocked | DB |
| DB | D | `BLOCKED` | DA | DA is blocked | DC |
| DC | D | `BLOCKED` | DB | DB is blocked | - |

The authoritative cross-stage map is `F1 -> Stage-1 C1`, `F2 -> Stage-1 C3`, and `F3 -> Stage-1 DC2` (`build_ssot.py:249-253`). The F1 node additionally consumes `stage1:I9` from the same candidate. The Stage-1 ledger shows C1, C3, I9, and DC2 as `BLOCKED`; their direct blockers include `IL1/I4/I5/I6/I9` for C1, `P7/P8/P9/P10` for C3, `T1` for I9, and `DB2` for DC2. The topology explicitly contains `F1 -> B`, `F1 -> Stage-2 C1`, `F2 -> O1`, `F2 -> S3`, and `F3 -> C`.

Consequently, the dependency closure is:

`Stage-1 C1 + same-candidate I9 -> F1 -> B -> shared/personal/organization branches -> C8 and O6; Stage-1 C3 -> F2 -> O1/S3; Stage-1 DC2 -> F3 -> C; C8 + O6 + F3 -> C -> DA -> DB -> DC`.

No later node is independent of all three blocked projection paths. K is already part of the terminal baseline and does not open B without F1.

## Four ST2 human-task status table

| Task | Bound node | Contract / test baseline | Binding | Checklist | H-01 | Log disposition | Handoff | Signed result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ST2-HUM-ORG-SCAN | O1 | `DRAFT` / `PLANNED` | `DRAFT` | draft | blocking | `PREPARING` in `non_blocking_entries` (`blocking: false`) | absent (`handoff_path: null`) | absent (`latest_run: null`) |
| ST2-HUM-LARK-READBACK | O5 | `DRAFT` / `PLANNED` | `DRAFT` | draft | blocking | `PREPARING` in `non_blocking_entries` (`blocking: false`) | absent (`handoff_path: null`) | absent (`latest_run: null`) |
| ST2-HUM-LOGIN-FOLD | K | `DRAFT` / `PLANNED` | `DRAFT` | draft | blocking | `PREPARING` in `non_blocking_entries` (`blocking: false`) | absent (`handoff_path: null`) | absent (`latest_run: null`) |
| ST2-HUM-SESSION-28D | DB | `DRAFT` / `PLANNED` | `DRAFT` | draft | blocking | `PREPARING` in `non_blocking_entries` (`blocking: false`) | absent (`handoff_path: null`) | absent (`latest_run: null`) |

The physical workspaces are the four `acceptance/human/2026-W36/未-2026-09-01-ST2-HUM-*/` directories. Each binding declares H-01 as blocking, while the machine log has `blocking_entries: []` and places all four in the non-blocking partition. That partition mismatch cannot clear a binding-declared blocking requirement. No `handoff.json` or signed `runs/<run-id>/result.md` exists for any of the four tasks. Recomputed contract and checklist hashes match their binding declarations, which proves file integrity only; it does not establish execution or a human result.

## Machine evidence boundary

| Evidence | Observed result | Formal interpretation |
| --- | --- | --- |
| Focused backend/contract tests | `104 passed, 12 subtests passed` | Local machine test evidence only |
| `npm run build:media` | Recorded as passed | Local build and QA evidence only |
| Screenshot matrix | `64/64` matrix cells, `72` screenshots | Local browser harness evidence only |
| Screenshot API trace | `506/506` calls handled by browser-boundary mocks; zero real calls | Does not prove a live API, organization account, or external service |
| Screenshot identity | localhost base URL, `sourceIdentity: workspace`, `reviewIdentity: REVIEW_IDENTITY_PLACEHOLDER` | Not a deployed or reviewer-identified runtime proof |
| Full Router suite | `1683 passed, 40 skipped, 32 failed`, exit code `1` | Baseline comparison says the failures are inherited, but the run is not all-green |

The screenshots and tests therefore remain source/local-runtime evidence. They do not prove real organization QR login, live Binding resolution, real Feishu edit and readback, real database readback, 28-day deployed session persistence, physical-device evidence, or independent external sign-off. The development brief also requires `agents-results/**` to remain read-only and states that source presence does not change node state (`docs/frontend/prototype/stage2-dev-brief.md:14-17`).

Two recorded evidence declarations are stale relative to their files:

- `media-build-output.txt`: declared `f282a02b1ff17a18e3aaa85a84a1ac61ca7067e14e6ce6925660c361c83c66a2`; actual `c5a7db35702c8e535fee0d3f58fc47b095aba0c9737047bb777957370199b758`.
- `router-full-pytest-output.txt`: declared `7e403e768a336f3f808f1a2f7136627584808ce6fc8c3265c6fb03abb739818a`; actual `30c251c2333fb1c2f08a4491b259801f0477e879557543ba3b4d317bda65dacc`.

## Exact ready frontier

`READY_FRONTIER = ∅` and `ready-frontier-width = 0`.

There is no legal independent formal acceptance frontier after the terminal baseline. F1, F2, and F3 are each blocked by an authoritative Stage-1 input; B, O1, S3, the personal chain, C8, O6, C, and every D node are then blocked directly or transitively. The generated progress ledger records the same empty frontier (`implementation-progress.md:63-78`), and the generated acceptance view states that local runtime evidence cannot replace the external and independent evidence layers (`generated-views/40-acceptance-execution.md:26-49`).

## Severity-first findings

1. **CRITICAL - F-DAG-001: all three cross-stage projections are blocked.** Stage-1 C1, C3, and DC2 remain `BLOCKED`; F1 also requires same-candidate I9. `build_ssot.py` requires the projection conditions and dependency edges, so no later Stage-2 node can lawfully advance from the current inputs. Evidence: Stage-1 `implementation-progress.md:43-72`, Stage-2 `.ssot/nodes/F1.json`, `F2.json`, `F3.json`, and `generated-views/10-dependency-topology.md:7-9,48-107`.

2. **HIGH - F-HUM-001: all four required human lanes are unfinished.** Every ST2 contract is `DRAFT` with a `PLANNED` test baseline; every binding and checklist is draft; every H-01 is blocking; no handoff or signed result exists. The acceptance log's empty blocking partition is contradicted by the binding-level blocking declarations and cannot be used as clearance.

3. **HIGH - F-EVID-001: current visual and test evidence is local and mocked.** The screenshot manifest records localhost, placeholder review identity, and 506 browser-boundary mock calls. The full suite exits `1` with 32 failures. Inherited-baseline classification is useful diagnostic context, but it is not external runtime proof or a formal state transition.

4. **MEDIUM - F-ID-001: evidence identity and two declared hashes do not match.** The recorded source SHA differs from the frozen review SHA, another regeneration report has a third source SHA, and the two output hashes above are stale. This prevents treating the recorded outputs as a clean immutable evidence set for the frozen identity.

## SSOT mutation assessment

Yes. Changing a node state to create a later frontier would violate the SSOT.

- `build_ssot.py:1777-1780` requires exactly the three terminal baseline nodes to carry terminal state and requires every other phase-2 node to remain `BLOCKED` at this planning baseline.
- `build_ssot.py:1781-1795` checks the projection edges, the `F1/F2/F3` upstream map, and the F2 dependency on S3.
- `.ssot/nodes/F1.json`, `F2.json`, and `F3.json` declare zero-write automatic projection rules whose source conditions are not met.
- Rewriting `.ssot/nodes`, progress, or generated views would be a source/view mutation, not evidence of completion, and would make the deterministic SSOT checks inconsistent with the current Stage-1 authority.

The only lawful progression is to resolve the Stage-1 C1/I9, C3, and DC2 inputs in their owning SSOT, then perform the declared zero-write projections with matching candidate/release identity. This review does not perform that progression.

## Failure classification and proposed state

- `failure_class`: `formal-dependency-blocker`
- `failure_origin`: `authoritative-stage1-state-and-unavailable-external-acceptance-inputs`
- `proposed_state`: `BLOCKED`

This is `BLOCKED`, rather than `FAILED`, because the decisive failures are unavailable authoritative upstream state and missing external/human acceptance inputs; the current tree does not provide a legal independent route around them.
