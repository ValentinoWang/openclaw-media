# MediaClaw Feishu Login Fix Verification

Date: 2026-08-19 (Asia/Shanghai)

## Production changes

- Stopped the ten stale Vite processes that owned ports `5179-5183` and `5188-5192`.
- Kept MediaClaw backend on `127.0.0.1:8787` and OPC on `127.0.0.1:8098`.
- Created Stage 1 installation `36946b05-998b-53a9-8d48-756861a1c730` for `media-pilot`.
- Created and activated Stage 1 Binding generation `1`, retaining `legacy_binding_id=3`.
- Promoted five existing active Feishu member identities to the active generation.
- Matched the actual MediaClaw Feishu application ID `cli_a97e4492acb8dbd6`.

## Code behavior

- Feishu login now accepts a server-returned `open_id` or stable `union_id` within the current tenant and active Binding.
- Ordinary-member JIT onboarding fails closed when the organization owner has no explicit active Feishu identity Binding.
- Browser fields cannot supply or override either identity value.

## Evidence

- Local compile: PASS.
- Focused backend tests: `37 passed, 15 skipped`.
- Remote release: `openclaw-tag-router-media-tenant-20260819T-feishu-union-r3`.
- Remote release manifest: PASS.
- Release process guard: PASS, service PID `4110515`.
- Real browser OAuth: callback reached `/openclaw/media/organization-workspace`, page showed `Binding 状态 ACTIVE`.
- Real browser reload: remained on the organization workspace with no login redirect.
- Database readback: installation ACTIVE, generation ACTIVE, five bound active identities.
- Listener audit: no `5179-5192`; `8098` and `8787` remain listening only on `127.0.0.1`.

## Remaining boundary

The five legacy identity rows retain their original app-scoped `open_id` and stable `union_id`; the current MediaClaw app is matched through `union_id`. No automatic merge by display name or email was added.
