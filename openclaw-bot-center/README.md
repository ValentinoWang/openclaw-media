# OpenClaw Bot Center

This directory is the tracked source for the MediaClaw web application and its
Media build entrypoint. The deployed Media artifact is produced with:

```bash
npm ci --ignore-scripts
npm run build:media
```

The source was imported from the validated local MediaClaw frontend snapshot
used by the current release. Runtime output, dependencies, local environment
files, and QA evidence are intentionally excluded from this source tree.
