TASK_ID=foundation-route-matrix

Frozen current mainline: `84382576a4045a99aea1abb6df848ba95f0bb3d9`. The valid session schema always supplies `role` and either `personal_web/internal` or `organization_lark/lark`. The current `MediaStudioApp` makes the ordinary IA unreachable and can send an admin organization session away from `/admin/overview` even though login role landing is admin-first.

Repair the Studio route/navigation matrix with role-first authority:

- `role=admin` always receives the admin shell, navigation, default route, and admin routes regardless of workspace mode.
- an ordinary `personal_web/internal` session receives the current Studio/ordinary navigation plus a discoverable personal workspace entry; `/today` and Studio routes remain reachable, while personal ordinary legacy routes may intentionally redirect to `/workspace` and are not required to remain individually reachable; `/workspace`/preview remain personal-only.
- an ordinary `organization_lark/lark` session receives organization workspace plus Tracks only; ordinary personal pages and admin pages redirect to the organization default.
- no valid session shape falls into an unreachable ghost ordinary mode.
- preserve all current Studio route aliases and current component implementations.

Add a fail-closed static/runtime QA script that checks this matrix and catches the old impossible-ordinary/admin-order regressions. Do not edit `package.json`; integration owns wiring later.

Exclusive write scope:
- `openclaw-bot-center/src/media/MediaStudioApp.tsx`
- `openclaw-bot-center/scripts/qa/checkMediaStudioRouteMatrix.ts`

Forbidden: legacy `MediaApp.tsx`, page files, shared CSS/theme, auth, package/lockfiles, backend, existing QA scripts, and git operations.

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/MediaStudioApp.tsx openclaw-bot-center/scripts/qa/checkMediaStudioRouteMatrix.ts && cd openclaw-bot-center && npx tsx scripts/qa/checkMediaStudioRouteMatrix.ts`.

Do not commit. Write the required structured return.
