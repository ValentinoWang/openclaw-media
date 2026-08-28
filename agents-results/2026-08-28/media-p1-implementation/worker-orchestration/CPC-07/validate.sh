#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH=. uv run --no-project \
  --python /Users/vsiyo/.local/share/uv/python/cpython-3.11.11-macos-aarch64-none/bin/python3.11 \
  --with pytest --with 'pydantic>=2,<3' --with requests \
  --with python-dotenv --with pyyaml --with openai \
  -m pytest -q tests/test_creation_anti_pattern_validation.py
git diff --check
