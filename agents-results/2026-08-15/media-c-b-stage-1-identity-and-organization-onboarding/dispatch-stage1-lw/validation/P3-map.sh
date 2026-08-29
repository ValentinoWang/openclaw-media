set -euo pipefail
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend ./backend/.venv/bin/python -m pytest -q -p no:cacheprovider backend/tests/test_stage1_release1b_migration.py backend/tests/test_stage1_member_onboarding.py backend/tests/test_account_identity_workspace.py backend/tests/test_workspace_resolution.py
