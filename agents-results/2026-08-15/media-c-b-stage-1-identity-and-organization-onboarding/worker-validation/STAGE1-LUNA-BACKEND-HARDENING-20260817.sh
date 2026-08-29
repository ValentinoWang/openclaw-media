set -euo pipefail

test "$(shasum -a 256 backend/tests/test_media_stage1_shared_contract.py | awk '{print $1}')" = "c1fbb5b6655ff2f4bb6f90152a8ab6705d77f6d2744744014f99e0d9dafa01a8"
test "$(shasum -a 256 backend/tests/test_stage1_personal_auth_lifecycle.py | awk '{print $1}')" = "d149a683ee0ef2825e5151005d0679f0d883e62b5810aeede637a5c87e7e1e6d"

/Users/vsiyo/.local/bin/uv run \
  --python 3.13 \
  --with pytest \
  --with bcrypt \
  --with cryptography \
  --with 'psycopg[binary]' \
  env PYTHONPATH=backend python -m pytest -q \
  backend/tests/test_stage1_administrator_authorization.py \
  backend/tests/test_stage1_postgres_provisioning.py \
  backend/tests/test_stage1_provisioning_runtime.py \
  backend/tests/test_stage1_provisioning_http.py \
  backend/tests/test_server_cli_stage1_composition.py \
  backend/tests/test_account_identity_workspace.py \
  backend/tests/test_account_identity_postgres.py \
  backend/tests/test_stage1_organization_provisioning.py

/opt/homebrew/bin/python3.13 -m py_compile \
  backend/openclaw_app/services/stage1_administrator_authorization.py \
  backend/openclaw_app/services/stage1_organization_provisioning.py \
  backend/openclaw_app/services/stage1_postgres_provisioning.py \
  backend/openclaw_app/services/stage1_provisioning_runtime.py \
  backend/openclaw_app/services/stage1_feishu_provisioning_gateway.py \
  backend/openclaw_app/account/repository.py \
  backend/openclaw_app/server_cli.py
