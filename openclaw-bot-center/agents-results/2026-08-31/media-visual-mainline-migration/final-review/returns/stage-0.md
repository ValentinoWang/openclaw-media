# Stage 0 Independent Review Return

- Task ID: `media-visual-stage-0-final-review`
- Direct parent: `media-visual-mainline-final-review`
- Scope: ledger Stage 0, `DS-01` through `DS-05`
- Review authority: zero-write independent review
- Behavioral baseline: `HEAD` and `github/main` at `84382576a4045a99aea1abb6df848ba95f0bb3d9`
- Reviewed frozen worktree diff: `48bd625ff74bae07c6b3de853f35fcce74f51dc8c6ea0ea448deca402ac737f2`

## Findings

### P0

None.

### P1-01: DS-01 exact brand token values are not implemented

- Location: `src/media/mediaDesignTokens.css:86-96`; consumed through `media.auth.css:13-16`; existing built output at `dist-media/mediaDesignTokens.css:86-96`.
- The decision source requires `--mg-primary: #1a9b68`, `--mg-primary-dark: #10684a`, and `--mg-danger: #b42318` (`loginandworkspacevisualreview.html:760`). The current source and built token CSS instead contain `#239b69`, `#126344`, and `#bd5147`.
- The auth aliases resolve correctly to the token names, but therefore resolve to the wrong approved values. This is a direct `DS-01` failure and remains user-visible in auth and SPA consumers.

### P1-02: Required network-timeout behavior is incomplete

- `fetchEntryState()` has a 5-second abort at `media.login.js:164-181`, but the shared `postJson()` at `media.login.js:58-65` has no `AbortController` or timeout.
- Consequently personal login (`media.login.js:301-326`), organization authorization start (`media.login.js:239-272`), and the session re-read in `roleLanding()` (`media.login.js:126-132`) can remain pending indefinitely. The personal and organization continue buttons remain busy while `roleLanding()` is pending (`media.login.js:406-414`), and a stalled organization start leaves the QR placeholder without a refresh/error state.
- The ledger explicitly requires network timeout handling without erroneous navigation (`loginandworkspacevisualreview.html:879-889`). This is an acceptance failure in the current GitHub-main behavior. The two-line reviewed diff in `media.login.js:392-405` adds stale-query invalidation but does not introduce this timeout gap.

### P2-01: The login QA guard does not enforce the complete timeout contract

- `scripts/qa/checkMediaLoginContract.ts:1-66` is a source-string/regex guard. Its timeout assertion at line 56 only proves that some 5-second `AbortController` exists, and its busy assertion at line 57 only covers the personal password submit.
- It does not exercise a stalled `postJson()` call, `roleLanding()`, organization authorization start, or QR refresh, and it does not assert the three exact DS-01 token values. `npm run qa:media-login-contract` can therefore pass while P1-01 and P1-02 remain present.
- No fixture-only production branch or assertion weakening was found; the gap is that the guard is static and contract-incomplete rather than an approved runtime test.

### P2-02: QR fallback actions can issue duplicate authorization starts

- `media.login.js:239-272` uses `organizationRun` to ignore stale results, but does not disable, abort, or deduplicate the request.
- Both the fallback and refresh handlers invoke it directly at `media.login.js:393-405`. Repeated clicks can therefore create concurrent `/openclaw/media/auth/feishu/start` requests. The run counter prevents stale DOM updates and the function does not redirect, so this is not an observed erroneous-navigation path, but it is not complete double-click protection.

### P3

None.

## DS-01..DS-05 disposition

| Item | State | Independent review basis |
| --- | --- | --- |
| DS-01 | **FAIL** | The three required approved values are absent from `src/media/mediaDesignTokens.css:86-96`; the built token copy carries the same wrong values. |
| DS-02 | **PASS** | The eight-level scale is present at `src/media/mediaDesignTokens.css:20-29`; `--mg-track-tight`, `--mg-track-normal`, and `--mg-track-wide` resolve to `0` at `:31-34`; the focused no-negative-tracking check passed. |
| DS-03 | **PASS (structural)** | Section 08 is the authority over the earlier mock: two cards remain, selected state compresses the selected card, and the other card becomes a switch link (`media.auth.css:256-369`, `media.login.html:63-91`). The form is bounded to `380px` and the primary form button is full width (`media.auth.css:131-132`, `:445-468`). P1-02 remains a separate review-level auth acceptance failure. |
| DS-04 | **PASS (structural)** | The login shell is a two-column layout with a narrative panel (`media.auth.css:69-106`); the mobile rule collapses the shell and hides the story panel at `media.auth.css:673-691`. No runtime visual proof is claimed. |
| DS-05 | **PASS (wiring)** | `media.auth.css:1` imports `/mediaDesignTokens.css`, aliases are defined at `:6-18`, Vite copies both auth CSS and token CSS at `vite.media.config.ts:35-41`, and the contract/Nginx static route is present at `contracts/media-auth-route-contract.json:9-12` and `deploy/nginx-openclaw-bot-center.conf:67-71`. The wiring is closed, but it transports the incorrect DS-01 values. |

The Section 08 login behavior review found the intended entry-state and fallback fencing: explicit P1 selection is required, no-mode entry does not auto-redirect, `matched/none/expired/mismatched/unavailable` states are rendered, stale queries are invalidated, history uses `pushState`/`replaceState`, and personal/continue submit actions use busy guards. The timeout and QR duplicate-request findings above are the remaining behavior gaps.

## Commands and evidence inspected

Passing focused checks:

- `npm run qa:media-login-contract`
- `npm run qa:media-registration`
- `node --check media.login.js`
- Targeted `git diff --check`
- `cmp media.auth.css src/media.auth.css` (byte-identical)
- Existing `dist-media` readback: auth CSS, token CSS, and login script match the current source copies; the absolute token import precedes the auth aliases.
- Static route inspection: `/mediaDesignTokens.css` is declared in both the route contract and Nginx configuration.

`npm run build:media` was not rerun in this zero-write lane because it mutates generated build artifacts. Existing build evidence was inspected only; it does not substitute for a fresh build, authenticated Playwright flow, isolated HTTP test, or deployed readback. Prior build evidence recorded an environment block at `/home/ubuntu/selfmedia-tools/openclaw-tag-router`.

## Frozen source verification

`frozen-source.md` was read before review and every listed identity hash recomputed. All values matched; the source is not stale.

| Frozen entry | Recomputed SHA-256 | Result |
| --- | --- | --- |
| Tracked binary diff | `48bd625ff74bae07c6b3de853f35fcce74f51dc8c6ea0ea448deca402ac737f2` | MATCH |
| `checkMediaPrimitiveAdoption.ts` | `7e0a7f7fa9fd4b1eeb544fd477169b00f6d6e51412360baaf85e483b680cdbb4` | MATCH |
| `checkMediaPrimitiveCoverage.ts` | `c93fbfe9483548e9d8e593a8c55a2c7aed1b59514bc8f55bdc0c0884bb1b0ed5` | MATCH |
| `checkMediaPrimitiveEnhancements.ts` | `f0d60bade53024e8ee2d1cd0a778416ac642790df7cefc88b69926750aeee607` | MATCH |
| `checkMediaStudioRouteMatrix.ts` | `1cfa72282daa23acbd61628965cf2d2ab44c5b7ddf674644d7d6d58b3c2309e9` | MATCH |
| `checkMediaStudioShellContract.ts` | `62003fb276f3c7f4b00bcdd351040c3897577663c2436d7066bae2b9663a4899` | MATCH |

The reviewed source identity is the frozen branch diff against baseline `84382576a4045a99aea1abb6df848ba95f0bb3d9`. Historical visual files were not treated as behavioral authority; the Section 08 decision text was used where it superseded the earlier mock.

## Residual risks

- No fresh full build, browser P1 -> P2 flow, authenticated E2E, isolated HTTP evidence, production deployment, or deployed asset readback was established by this lane.
- The Nginx alias proves the declared route and expected deployment path, not that the target deployment filesystem contains the current token file.
- The existing generated output confirms current source copying but also confirms the wrong DS-01 values.
- QR refresh/fallback request duplication and unbounded auth requests remain until the timeout and in-flight-action contracts are implemented and tested.

## Proposed state

**FAILED**

The frozen source is valid, so this is not a stale-source `BLOCKED` result. `DS-01` fails its exact-value decision, and the current auth behavior does not satisfy the ledger's network-timeout requirement. This return does not declare `ACCEPTED` or release `READY`.
