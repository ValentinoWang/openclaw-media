set -euo pipefail
./backend/.venv/bin/python -m pytest -q backend/tests/test_stage1_resource_resolver.py
./backend/.venv/bin/python -m pytest -q backend/tests/test_media_resource_url_trust_contract.py backend/tests/test_media_stage1_shared_contract.py
