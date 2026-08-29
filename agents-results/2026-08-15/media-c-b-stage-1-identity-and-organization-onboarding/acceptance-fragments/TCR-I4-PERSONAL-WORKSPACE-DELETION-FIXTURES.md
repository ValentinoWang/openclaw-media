# Test Change Request: I4 / I5 personal workspace deletion fixtures

- Acceptance contract: Stage 1 machine nodes `I4` and `I5`; no separate decision-scoped acceptance fragment currently exists for these shell fixtures
- Decision refs: `media.stage1.stable-decisions@2`, `media.stage1.decision.personal-auth-contract@1`
- Invalidation keys: `media.stage1.personal-workspace-shell.v4`, `media.stage1.session-contract.v2`, `media.stage1.acceptance-harness.v4`
- Request status: APPROVED_AND_RELOCKED
- Requested by: implementation owner
- Required approver: Stage 1 acceptance owner / main orchestrator
- Previous protected-test baseline: `.codex-work/stage1-integrated/frontend/scripts/qa/checkTaskWorkspaceDeletionRecovery.ts` (`sha256:65780fdc165b8a44ac245eaa3e649639cfa8e37a140dc5ecc265b4d783c6e108`); `.codex-work/stage1-integrated/frontend/scripts/qa/checkDeletionIntentLifecycle.ts` (`sha256:17648858baa7a2d77db17ff8690d74224ed02c92cc22358ee5f56833113f49e7`)
- Relocked protected-test baseline: `.codex-work/stage1-integrated/frontend/scripts/qa/checkTaskWorkspaceDeletionRecovery.ts` (`sha256:dbb757109b4c818a1aecc7820e41feba15966a824592bef471760a09967afb14`); `.codex-work/stage1-integrated/frontend/scripts/qa/checkDeletionIntentLifecycle.ts` (`sha256:b0f7f9d2c2b079613a503db3b5a1901a8b06d29adfcd4a580afb4222312a7ddd`)
- Affected requirements: `I4` personal workspace shell and cloud-deliverable preview boundary; deletion-recovery task drawer regression coverage

## Original rule

The previous frozen fixtures modeled an authenticated `personal_web` session without `bindingState` or `installationState`, then drove the ordinary personal content page at `/assets` and its destructive asset-deletion workflow. The task recovery fixture expected the old ordinary task drawer contract to be reachable from `/overview`.

## Proposed rule

Re-lock the affected fixtures against the current Stage 1 session schema, including `bindingState: NOT_APPLICABLE` and `installationState: NOT_APPLICABLE` for personal sessions. The personal deletion-intent fixture asserts the Stage 1 read-only cloud-deliverable shell, redirects from excluded ordinary-content routes, and proves the absence of destructive content mutations; ordinary asset deletion remains in the later content-production acceptance scope. The task recovery fixture retains its no-mutation task-status assertion against the personal shell. Production session parsing rejects missing binding or installation fields instead of synthesizing compatibility values.

## Reason

The approved Stage 1 decisions make personal login independent of Feishu and limit the first personal release to server-authorized cloud storage and preview of deliverables. The current backend session contract emits typed binding and installation projections, and the frontend parser intentionally requires them. The frozen deletion-intent fixture therefore fails before its intended assertions because it supplies an obsolete session shape and requests a page that Stage 1 explicitly does not expose. The task recovery fixture likewise cannot load the shell with the obsolete session shape.

## Impact

This change affects only the protected acceptance fixtures and the acceptance contract for the Stage 1 personal shell. It does not change production authorization, session fields, routes, database state, Feishu bindings, deletion APIs, or organization behavior. If approved, the affected `I4` acceptance path must be re-locked and its downstream `C1` dependency re-evaluated; unrelated authentication, organization shell, and backend fragments remain valid. Until approval and relocking, the integrated `build:media` gate remains partial.

## Alternatives considered

1. Accept missing session fields in production frontend parsing. Rejected because it weakens the current typed session contract and would create an undocumented compatibility path.
2. Expose the ordinary `/assets` and destructive deletion workflow to personal sessions. Rejected because it violates the approved Stage 1 personal read-only cloud-deliverable boundary and would reopen content-production scope.
3. Modify, skip, or weaken the protected tests without approval. Rejected by the protected-test rule.

## Approval

- Decision: APPROVED
- Approver: user / Stage 1 acceptance owner
- Approval evidence: explicit task-thread approval on 2026-08-18: `批准，我授予你后续开发认可，修改远端直接更新代码吧，别问了`
- Prior failure evidence: `deterministic-receipts/I4-I5-deletion-fixture-rerun-20260817.json`
- Approved contract version: 2
- Relocked test hashes: `checkTaskWorkspaceDeletionRecovery.ts=sha256:dbb757109b4c818a1aecc7820e41feba15966a824592bef471760a09967afb14`; `checkDeletionIntentLifecycle.ts=sha256:b0f7f9d2c2b079613a503db3b5a1901a8b06d29adfcd4a580afb4222312a7ddd`
- Focused relock result: `qa:media-session-contract`, `qa:task-workspace-deletion-recovery`, and `qa:deletion-intent-lifecycle` passed on 2026-08-18.
