# Media visual mainline migration blueprint

## Frozen authority

- GitHub main baseline: `84382576a4045a99aea1abb6df848ba95f0bb3d9`
- Historical stage branch: `a0580dec5a33ae5893ad30c551ec7b76ec8ed7ef`
- Ledger: `/Users/vsiyo/Downloads/loginandworkspacevisualreview.html`, DS-01 through DS-22
- Runtime entry: `src/media/main.tsx` -> `MediaStudioApp.tsx`

The GitHub main implementation is the behavioral authority. The historical branch is a visual/adoption reference only. Authentication history, fallback, session, task, cursor, error, identifier, monitoring, and Studio behavior must not regress.

## Route and role matrix

| Session | Shell | Default | Reachable product families |
| --- | --- | --- | --- |
| `role=admin`, any valid workspace mode | governance | `/admin/overview` | five admin routes only |
| ordinary + `personal_web/internal` | creator Studio | `/overview` | 11 ordinary top-level pages, run detail, current Studio pages, and the personal workspace |
| ordinary + `organization_lark/lark` | organization | `/organization-workspace` | organization workspace and Tracks |

The personal ordinary-route authority includes `/overview`, `/tracks`, `/assets`, `/decisions`, `/runs`, `/publishing`, `/reviews`, `/media-agent`, `/archives`, `/usage-billing`, `/invites`, and `/runs/:runId`. `/runs` may canonically redirect to `/studio`; it must never redirect to `/workspace`, while `/runs/:runId` and `/studio/:runId` render run detail. `/workspace` and `/workspace/preview/:artifactId` remain personal-only. No valid session may depend on a third workspace mode to reach the ordinary pages. Role authority precedes workspace presentation authority.

## Page ownership and accent

| Family | Ownership | Accent |
| --- | --- | --- |
| overview, assets, runs, run detail, personal workspace, workboard | `personal` | `studio` |
| tracks, reviews, desk | `personal` | `desk` |
| decisions, publishing, invites, campaigns | `personal` | `campaign` |
| usage/billing, business | `personal` | `business` |
| media agent | `personal` | `agent` |
| archives | `personal` | `archive` |
| organization workspace | `organization` | `campaign` |
| admin overview/access/tenants/billing/upstreams | `governance` | `desk/campaign/studio/business/agent` |
| workspace dispatcher unavailable state | `router` | session-derived or `studio` fallback |

Attribution applies to loading, empty, permission, not-found, and error route roots as well as ready state.

## Shared visual contract

- DS-02: the existing 8-level type scale remains authoritative; tracking tokens resolve to `0` and no negative letter spacing is introduced.
- DS-06: state surfaces use `SurfaceState`, `ResourceStateView`, or the `.mg-state` family when their semantics match.
- DS-07: repeated metrics use `Metric` or `.mg-metric` without changing value/label semantics.
- DS-08..11: panels, tabs, heroes, eyebrows, and buttons adopt the existing global classes where page-local geometry is not unique.
- DS-12..17: the mainline six-accent system, badge tones, pill tabs, hover lift, reduced motion, and state-art slot remain the canonical implementation.
- DS-18: shells with fewer than three navigation destinations use a 56px icon rail on desktop, with accessible names/tooltips retained.
- DS-19: `data-page-prelude` is outside any persistent rail and contains the primary heading plus up to two supporting metric/action regions.
- DS-20: the topbar uses a translucent surface with blur and an opaque fallback.
- DS-21: every route surface carries stable ownership and accent attributes.
- DS-22: personal workspace metrics are supplied by shared metric DOM/styles.

## Responsive and state verification

- Desktop: 1440x1000 and 1280x900.
- Narrow desktop/tablet: 1024x768.
- Mobile: 390x844.
- Required checks: no horizontal overflow, no incoherent overlap, stable persistent-rail sizing, visible focus, keyboard tabs/actions, reduced motion, console/page errors, and every route/state resolving to the expected renderer.
- Authentication evidence remains separate: static contract, focused tests, isolated HTTP, Playwright P1 -> P2, and deployed readback are not interchangeable.
