set -euo pipefail
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend ./backend/.venv/bin/python -m pytest -q -p no:cacheprovider backend/tests/test_stage1_install_events.py backend/tests/test_stage1_release1b_migration.py backend/tests/test_media_stage1_shared_contract.py
