#!/usr/bin/env bash
set -euo pipefail

export UV_CACHE_DIR=/tmp/openclaw-media-p1-cd08-uv-cache
PYTHONPATH=. uv run --no-project \
  --python /Users/vsiyo/.local/share/uv/python/cpython-3.11.11-macos-aarch64-none/bin/python3.11 \
  --with pytest --with 'pydantic>=2,<3' --with requests \
  --with python-dotenv --with pyyaml --with openai \
  -m pytest -q tests/test_media_context_review_bandwidth.py
git diff --check
