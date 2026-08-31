# Stage 0 remediation freeze

- Baseline HEAD: `84382576a4045a99aea1abb6df848ba95f0bb3d9`
- Tracked binary diff SHA-256: `ff23fd7f474f04529781e48d17b83f0a0ae43bea0b6c732b1a17ea8a0a25e146`
- Untracked source/QA content-list SHA-256: `c9790d4ecbc2a51dc659bc24d948b026809d6ac9cf305e8b1e5798a7075886ca`
- Combined 93-path set SHA-256: `744982513e6ebd69f0957cb39a19274627fb73869a2ff9778d030cbc209b992d`
- Stage 0 scoped content/diff stream SHA-256: `1611be335b942d49bf17f9d000cac759c32d3a20717b4551ba411299bc6c3538`
- Invalidated review surface: Stage 0 only. Stage 1, Stage 2, and Stage 3 source paths did not change.
- Remediation: mobile selected identity grid is forced to one column in both byte-identical auth CSS copies; runtime QA rejects intersecting identity-choice rectangles and executes a synthetic old-CSS negative proof.
- Coordinator green evidence: `npm run qa:media-login-contract`; Playwright runtime via `withChromiumSlot.sh -- npx tsx`; scoped oxlint; CSS byte comparison; scoped `git diff --check` all exited 0.
- Green screenshots: `/tmp/openclaw-stage0-overlap-green-final/`.
