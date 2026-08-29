set -euo pipefail
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend ./backend/.venv/bin/python -m pytest -q -p no:cacheprovider backend/tests/test_stage1_document_projection_openapi.py backend/tests/test_media_web_business_pages_contract.py backend/tests/test_media_business_documents.py backend/tests/test_media_resource_url_trust_contract.py backend/tests/test_d2_document_projection_source_identity.py
