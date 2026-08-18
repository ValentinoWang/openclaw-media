# openclaw-media release runbook

The wheel is built once from this package root and is the only CLI runtime. Its
supported Python contract is CPython `>=3.12,<3.14`, matching package metadata,
the lockfile, and `openclaw-media doctor`. The release build and installation
verification target is macOS on CPython 3.12 (`macos-13`, x86_64), without
publishing credentials in jobs:

```sh
python -m pip wheel . --no-deps --wheel-dir dist
python -m openclaw_media.release dist/openclaw_media-*.whl --output dist/CLIRelease.json
python /home/ubuntu/scripts/generate_media_product_contract.py
python /home/ubuntu/scripts/quality/check_media_product_contract.py --self-test
uv tool install --force dist/openclaw_media-*.whl
openclaw-media --version
uv tool upgrade --reinstall dist/openclaw_media-*.whl
openclaw-media --version
uv tool uninstall openclaw-media
```

The readback must show the wheel's `Name`, `Version`, `Requires-Python`, one
`openclaw-media` console entry, wheel SHA-256, packaged catalog digest, minimum
Web API version, and deterministic dependency SBOM. A release fails closed on
metadata, catalog, or console-entry drift. Publishing is a separate
credentialed pipeline.
