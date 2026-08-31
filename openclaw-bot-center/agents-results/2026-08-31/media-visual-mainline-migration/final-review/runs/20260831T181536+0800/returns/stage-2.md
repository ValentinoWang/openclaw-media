# Stage 2 independent release review

## Findings

1. **BLOCKING — requested DS scope is not covered by the frozen Stage 2 paths.** `stage-paths.tsv:84` and `:85` declare only `checkMediaPrimitiveEnhancements.ts` and `mediaPrimitives.css`. The blueprint defines DS-18 as the 56px icon rail (`blueprint.md:45`), DS-19 as the `data-page-prelude` placement contract (`:46`), and DS-20 as the translucent topbar with opaque fallback (`:47`). The ledger marks all three as Stage 3 and `待实施` (`loginandworkspacevisualreview.html:963`, `:964`, `:965`). The checker has no rail, prelude, or topbar assertions; its project assertions cover accent/tone/primitive selectors (`checkMediaPrimitiveEnhancements.ts:105-122`). These release requirements therefore remain unevidenced.

2. **BLOCKING — protected-test integrity is not independently established.** The permitted frozen-source record supplies HEAD, candidate-content, path-set hashes, and prior coordinator-gate claims (`frozen-source.md:5-12`), but no protected-test manifest, approved test hashes, or deletion/assertion-weakening comparison. None of the four required commands performs that comparison. A clean diff check cannot substitute for protected-test integrity evidence.

## Frozen identity

- HEAD: `84382576a4045a99aea1abb6df848ba95f0bb3d9`
- Tracked diff SHA-256: `ace6f0e42673be77c51de25895232eb88c10259add95c3297d079d17d09aaff9`
- Untracked source/QA content-list SHA-256: `78211727684da2613517c1e5ea68d7c17ada7fd1da6ac4a176cd680548430ce4`
- Combined task path-set SHA-256: `744982513e6ebd69f0957cb39a19274627fb73869a2ff9778d030cbc209b992d`
- Frozen task path count: `93`
- Stage-2 path count: `2`
- Stage-2 paths: `scripts/qa/checkMediaPrimitiveEnhancements.ts`; `src/media/mediaPrimitives.css`

## Commands and exits

| Command | Exit |
|---|---:|
| `npm run qa:media-primitive-enhancements` | 0 |
| `npm run qa:media-primitive-enhancements-self-test` | 0 |
| `npx oxlint --deny-warnings scripts/qa/checkMediaPrimitiveEnhancements.ts` | 0 |
| `git diff --check -- scripts/qa/checkMediaPrimitiveEnhancements.ts src/media/mediaPrimitives.css` | 0 |

## Red/green proof

- Green: project QA found all six accent selectors, `good`/`warn`/`info` tone selectors, shared badge/pill-tab/button-hover/state-art/reduced-motion markers, and no legacy `Metric` tones (`checkMediaPrimitiveEnhancements.ts:105-122`).
- Green: shared CSS uses inherited accent variables and reusable primitive classes (`mediaPrimitives.css:8-9`, `:212-216`, `:249-255`, `:305-326`, `:386-405`). `.mg-eyebrow` resolves tracking to zero (`mediaPrimitives.css:35-43`).
- Red: self-test rejects gradient functions, decorative hero pseudo-elements, nonzero eyebrow tracking, and legacy `Metric` tones (`checkMediaPrimitiveEnhancements.ts:135-159`).
- Green negative-fixture boundary: comments, strings, another component, and canonical `tone="accent"` are not rejected (`checkMediaPrimitiveEnhancements.ts:161-169`).

## Protected-test integrity

`UNVERIFIED` and blocking for this review. The project scan recursively checks real `src/media/**/*.tsx` consumers (`checkMediaPrimitiveEnhancements.ts:87-103`); it does not act as a protected-test hash gate. No page-specific fixture bypass was found in the permitted checker: fixtures are self-test-only, while project mode reads actual consumers.

## Residual risk

Primitive-level proof is static. Required-rule checks use string presence (`checkMediaPrimitiveEnhancements.ts:114-120`), so they do not prove computed token values, rendered inheritance, responsive shell geometry, or runtime fallback behavior. The requested build and broad checks were intentionally not run.

## Actual write scope

Only `agents-results/2026-08-31/media-visual-mainline-migration/final-review/runs/20260831T181536+0800/returns/stage-2.md` was written. No source, tests, configs, git index, commits, or existing evidence were modified.

failure_class: `SCOPE_CONTRACT_MISMATCH; PROTECTED_TEST_INTEGRITY_UNPROVEN`
failure_origin: `frozen Stage-2 path/checker covers primitive enhancements, while DS-18..20 are pending shell requirements; permitted evidence lacks protected-test baseline/hashes`

Final decision: **NOT READY**
