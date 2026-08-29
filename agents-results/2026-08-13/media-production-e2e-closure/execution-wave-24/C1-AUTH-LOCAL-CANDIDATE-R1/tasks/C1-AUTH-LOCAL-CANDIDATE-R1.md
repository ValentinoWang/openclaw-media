# C1-AUTH-LOCAL-CANDIDATE-R1

## Objective

Create the reusable, evidence-only runner for the MPE2E-AUTH-WEB v3 `local-candidate` Chromium acceptance run. The runner must exercise the current unique candidate without changing it, produce redacted browser evidence, and validate the resulting safe receipt with the protected gate.

## Frozen authority

- Project root: `/Users/vsiyo/Desktop/创业项目/自媒体创作Agent`
- Candidate root: `/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/merge-candidate-v4`
- Candidate manifest SHA-256: `f1ac786573e76aa40a0d69a10aab6dba5bd6a345596242d93f37773b59f45bcb`
- Contract: `agents-results/2026-08-13/media-production-e2e-closure/acceptance-fragments/MPE2E-AUTH-WEB/acceptance-contract.md`
- Contract version/hash: `3` / `f6978ce556758613eba0e20e4bf42159c04a96531ff2cb806327fcab9aedb5c9`
- Protected receipt gate/hash: `scripts/acceptance/test-mpe2e-auth-web.sh` / `8bf6f33d0917948821f7a6ffbbd3e5f505002fb19d77c4f1d24b9c3261e6ab2e`
- Protected source gate/hash: `scripts/acceptance/test-mpe2e-auth-workspace-source.sh` / `4e73a4b346095d2e9eea998c07562fb8066835dec644211f33afa6998a51430e`
- Current candidate source validation: `agents-results/2026-08-13/media-production-e2e-closure/execution-wave-23/C5-UNIQUE-CANDIDATE-R3/validation/C5-UNIQUE-CANDIDATE-R3.sh`

## Exclusive write scope

Write only these two files:

- `agents-results/2026-08-13/media-production-e2e-closure/execution-wave-24/C1-AUTH-LOCAL-CANDIDATE-R1/runner/run-local-candidate-e2e.sh`
- `agents-results/2026-08-13/media-production-e2e-closure/execution-wave-24/C1-AUTH-LOCAL-CANDIDATE-R1/runner/runMediaAuthLocalCandidate.mjs`

The supervisor-owned structured return path is also writable exactly as instructed by `STRUCTURED_RETURN_PATH`.

## Forbidden scope

- Do not modify the candidate, its manifests, any protected test, contract, human checklist/binding, SSOT node/edge/manifest, existing evidence, lockfile, database migration, remote host, production service, Feishu object, credential, Git state, or Obsidian snapshot.
- Do not run `spawn_agent`, another worker, commit, push, deploy, restart a service, or access real login credentials.
- Do not record password values, cookies, tokens, secrets, authorization codes, private content, or environment contents in evidence or logs.

## Runner contract

`run-local-candidate-e2e.sh` must accept exactly one argument: an existing absolute MPE2E-AUTH-WEB machine/e2e run directory whose sibling `evidence/` exists. It must fail closed on any other path. It must:

1. Recheck the frozen candidate and protected-test hashes.
2. Run the frozen C5 R3 validation and save its complete output as `evidence/backend-validation.log`.
3. Start the candidate Vite dev server on loopback with a strict, caller-overridable port, register cleanup before waiting, and save the server log.
4. Run `runMediaAuthLocalCandidate.mjs` against that server and evidence directory.
5. Require browser summary PASS, desktop `1440x1000`, mobile `390x844`, zero console/page errors, no horizontal overflow, and required screenshots.
6. Require a schema-3 redacted `local-candidate` receipt and pass it to the unchanged protected gate with `MPE2E_AUTH_WEB_MODE=local-candidate` and an absolute `MPE2E_AUTH_WEB_SAFE_METADATA_FILE`.
7. Write `evidence/evidence-manifest.sha256` for all material evidence except itself and print one stable PASS line. Never print receipt contents.

`runMediaAuthLocalCandidate.mjs` must use the candidate's installed Playwright package without adding dependencies. It must use fresh isolated browser contexts and user-facing locators. All network identity flows are controlled fixtures and the receipt must explicitly say so. It must verify:

- Account and Feishu QR are separate first-class entry points and both reach the same complete canonical session field set.
- Ordinary and administrator routes remain isolated; an ordinary `next` value cannot claim an admin route.
- Personal and organization valid workspace triples are accepted only as complete combinations; missing fields and mismatched workspace/editor/body-authority fail closed before landing.
- Feishu start accepts only a trusted HTTPS Feishu host; expired, replayed, browser-binding mismatch, cross-attempt, and unknown status cases remain unauthenticated and expose a retry action.
- Account failure uses one non-enumerating error boundary and can recover; QR expiry can refresh and recover.
- Desktop and mobile screenshots show both login methods. No screenshot, log, summary, or receipt may contain real identity data or secret values.

The receipt must satisfy every field required by the locked protected gate. Backend-only statements such as exact formal binding, cross-tenant rejection, external-blogger exclusion, lifecycle invalidation, and zero enqueue topology may be marked pass only after the frozen backend validation returned zero in the same runner invocation. Correlate UI, API, and backend resource evidence to one redacted `run_ref`. Keep `production_claim`, `real_qa`, and `promotable_to_production` false.

## Self-check

Run the frozen validation command file supplied by the supervisor. Write a structured return including task ID, actual read/write scopes, commands, changed files, evidence identities, unverified items, risks, `proposed_state`, `acceptance_self_check`, and `failure_class`. A successful implementation proposes `IMPLEMENTED`, never `ACCEPTED`.
