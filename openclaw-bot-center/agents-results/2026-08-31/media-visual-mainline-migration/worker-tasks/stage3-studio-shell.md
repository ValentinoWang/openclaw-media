TASK_ID=stage3-studio-shell

Frozen authority:
- GitHub main baseline: `84382576a4045a99aea1abb6df848ba95f0bb3d9`.
- Accepted route-matrix diff SHA-256 for `MediaStudioApp.tsx`: `79f95e9c0e3674b18e3c84872d879a53a1fae4e3d20f515ae785bb963a89acc0`.
- Route-matrix guard SHA-256: `d0e7e23d7af760b7585903d3f120340bb5a8eaa96968100218e78f72cd4b4572`.
- Current shell-theme SHA-256: `8cb357f86d59eae778fed47e851c39d16b3060369044629122487ac1ca6a8cfa`.
- Ledger items: DS-18 and DS-20. DS-19, DS-21, and DS-22 are owned by page/integration lanes and must not be faked here.

Implement the Stage-3 Studio shell mechanics on top of the accepted role-first route policy. Preserve `resolveStudioRoutePolicy`, all route helpers, the personal ordinary-page reachability, organization Tracks-only boundary, and admin-first authority.

Requirements:
- Compute compact navigation from the resolved visible navigation item count. On desktop, a shell with fewer than three destinations uses an exact 56px icon rail and its workspace offset is exactly 56px; this compact rule remains intended and must not be replaced with a route-family exception. Current organization navigation is the qualifying case after resolution; personal and admin shells remain full width when their resolved navigation has three or more destinations.
- Keep every compact-rail destination keyboard reachable and screen-reader named. Retain its text in the DOM and add an explicit tooltip/title for sighted pointer users. Do not replace Lucide icons with custom SVG.
- The compact rail must have a usable brand, active state, account control, and popover. At `900px` and below it must return to the existing full-width drawer pattern; compact desktop rules must not hide labels in the mobile drawer.
- Give `.studio-topbar` an opaque background fallback followed by its translucent color-mix layer, `backdrop-filter`, and `-webkit-backdrop-filter`.
- Replace negative or nonzero letter spacing touched in `mediaStudioTheme.css` with the zero-valued tracking tokens. Add a reduced-motion rule that disables shell pulse/pop animations and transform transitions without changing layout.
- Add a fail-closed `scripts/qa/checkMediaStudioShellContract.ts` guard for the item-count condition, exact 56px geometry, accessible compact navigation, mobile restoration, topbar fallback/blur, zero negative tracking, and reduced-motion coverage.

Exclusive write scope:
- `openclaw-bot-center/src/media/MediaStudioApp.tsx`
- `openclaw-bot-center/src/media/mediaStudioTheme.css`
- `openclaw-bot-center/scripts/qa/checkMediaStudioShellContract.ts`

Forbidden:
- Page files, shared primitives/tokens, auth files, package/lockfiles, existing route-matrix guard, backend, evidence outside the structured return, and git operations.

Acceptance command:
`git diff --check -- openclaw-bot-center/src/media/MediaStudioApp.tsx openclaw-bot-center/src/media/mediaStudioTheme.css openclaw-bot-center/scripts/qa/checkMediaStudioShellContract.ts && cd openclaw-bot-center && npx tsx scripts/qa/checkMediaStudioRouteMatrix.ts && npx tsx scripts/qa/checkMediaStudioShellContract.ts && ! rg -n 'letter-spacing:\\s*-' src/media/mediaStudioTheme.css`.

Do not commit. Write the required structured return.
