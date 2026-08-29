set -euo pipefail
./backend/.venv/bin/python -m pytest -q backend/tests/test_stage1_release1b_migration.py
./backend/.venv/bin/python -m pytest -q backend/tests/test_media_stage1_shared_contract.py
