"""Both Stage-2 HTTP entry points must map a Stage2RuntimeError code to the
same HTTP status.

adapters/http_api.py (the main service) and adapters/stage2_http_api.py (the
standalone current-main Stage-2 server, reached via stage2_server_cli.py)
each catch Stage2RuntimeError on their one /stage2 route and used to carry
their own copy of the code->status table -- the standalone server's copy
covered only the 409 group and sent every other code to 422, so the same
exception produced different statuses depending on which server handled the
request (dedup audit: exc-8-code-to-httpstatus-mapping-divergent). Both now
import services.stage2_runtime.runtime_status instead of keeping their own
table; this test pins that down at the unit level, without standing up
either HTTP server.
"""

from __future__ import annotations

from http import HTTPStatus

import pytest

from openclaw_app.adapters.http_api import _stage2_runtime_status as main_adapter_status
from openclaw_app.adapters.stage2_http_api import runtime_status as standalone_adapter_status
from openclaw_app.services.stage2_runtime import runtime_status as canonical_status


def test_both_http_adapters_import_the_same_status_function() -> None:
    # Not just equal output -- the same function object, so the table cannot
    # drift back apart by one adapter growing its own local copy again.
    assert main_adapter_status is canonical_status
    assert standalone_adapter_status is canonical_status


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("idempotency_conflict", HTTPStatus.CONFLICT),
        ("invalid_request", HTTPStatus.BAD_REQUEST),
        ("authentication_required", HTTPStatus.UNAUTHORIZED),
        ("binding_inactive", HTTPStatus.FORBIDDEN),
        ("writer_required", HTTPStatus.SERVICE_UNAVAILABLE),
        ("some_unrecognized_code", HTTPStatus.UNPROCESSABLE_ENTITY),
    ],
)
def test_both_http_adapters_return_the_same_status_per_code_group(
    code: str, expected: HTTPStatus
) -> None:
    assert main_adapter_status(code) == expected
    assert standalone_adapter_status(code) == expected
