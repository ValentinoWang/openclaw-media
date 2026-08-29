set -euo pipefail
cd '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent/.codex-work/stage1-integrated/backend'
.venv/bin/python -m pytest -q tests/test_stage1_organization_provisioning.py tests/test_account_identity_link.py tests/test_stage1_install_events.py
