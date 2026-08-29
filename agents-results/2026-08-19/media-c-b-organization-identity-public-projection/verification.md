# Organization identity and public session projection

## Outcome

The code and immutable remote release now project the real Feishu organization name from `openclaw_account.tenants.organization_name`. The public `/session` contract exposes only `organizationName`, `organizationConnection`, and `installationConnection`; internal `bindingState`, `installationState`, and backend enum values such as `ACTIVE` are rejected by a fail-closed guard.

## Implemented boundaries

- Backend workspace resolution joins the tenant record and carries `organization_name` into the authenticated principal.
- The HTTP session handler maps internal binding/installation states to public states (`connected`, `pending`, `disabled`, `revoked`, `attention`, or `not_applicable`).
- The public session envelope and session field allowlists are enforced before serialization.
- Sensitive environment values are rejected if they appear in the public session payload.
- Personal sessions cannot carry organization names or organization connection states.
- Organization UI renders the server organization name and uses public connection labels only.

## Verification boundary

Local contract, regression, runtime, and production build checks are green. The remote immutable release, process guard, static deployment guard, health checks, and read-only tenant organization-name readback are green.

The remote Playwright shell check was performed without a session and confirmed HTTP 401 for `/api/session` with no forbidden text. A real authenticated organization browser run was not claimed because the remote QA credentials returned `invalid_credentials`; no mock session was used and no credential or cookie value was persisted. See `browser-session-redacted.json`.

Evidence files in this directory are operational evidence only, not a new SSOT authority.
