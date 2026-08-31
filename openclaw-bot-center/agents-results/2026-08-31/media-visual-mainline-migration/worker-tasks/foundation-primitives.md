TASK_ID=foundation-primitives

Frozen identities: current mainline `84382576a4045a99aea1abb6df848ba95f0bb3d9`; historical stage final `a0580dec5a33ae5893ad30c551ec7b76ec8ed7ef`; ledger DS-02 and DS-12..DS-17.

Audit the current mainline token and primitive files against every ledger item. The current mainline files are newer and authoritative; do not replace them with the smaller historical versions. Add only genuinely missing semantics. DS-02 requires the current 8-level type scale plus reusable tracking tokens whose values are `0`. DS-12/13 require accent-aware metric/panel backgrounds, DS-14 badge good/warn/info tones, DS-15 pill tabs, DS-16 button hover lift with reduced-motion fallback, DS-17 a stable state-art slot. Keep current six named accent families and dark theme intact. Change negative letter spacing in these owned primitive files to `0` or a zero-valued tracking token.

Exclusive write scope:
- `openclaw-bot-center/src/media/mediaDesignTokens.css`
- `openclaw-bot-center/src/media/mediaPrimitives.css`

Forbidden: every page, auth file, shell theme, package/lockfile, QA script, backend, and git operations.

Acceptance command: `git diff --check -- openclaw-bot-center/src/media/mediaDesignTokens.css openclaw-bot-center/src/media/mediaPrimitives.css && ! rg -n 'letter-spacing:\\s*-' openclaw-bot-center/src/media/mediaDesignTokens.css openclaw-bot-center/src/media/mediaPrimitives.css`.

If all items already exist, make only the zero-tracking correction needed by DS-02 and report the rest as verified. Do not commit. Write the required structured return.
