from unittest.mock import Mock, patch

from common import social_runtime


def test_feishu_update_record_can_clear_explicitly_requested_empty_list() -> None:
    response = Mock(status_code=200)
    response.json.return_value = {"code": 0}
    with patch.object(social_runtime, "feishu_bitable_refs", return_value=("app", "tbl", "token")), patch.object(
        social_runtime, "feishu_ensure_fields"
    ), patch.object(social_runtime, "feishu_field_types", return_value={"近期作品链接": 4}), patch.object(
        social_runtime.requests, "put", return_value=response
    ) as put:
        social_runtime.feishu_update_record(
            "https://example.test/base/app?table=tbl",
            "rec_1",
            {"近期作品链接": []},
            specs={"近期作品链接": 4},
            write_empty_fields=True,
        )

    assert put.call_args.kwargs["json"] == {"fields": {"近期作品链接": []}}


def test_feishu_update_record_preserves_default_skip_empty_behavior() -> None:
    with patch.object(social_runtime, "feishu_bitable_refs", return_value=("app", "tbl", "token")), patch.object(
        social_runtime, "feishu_ensure_fields"
    ), patch.object(social_runtime, "feishu_field_types", return_value={"近期作品链接": 4}), patch.object(
        social_runtime.requests, "put"
    ) as put:
        social_runtime.feishu_update_record(
            "https://example.test/base/app?table=tbl",
            "rec_1",
            {"近期作品链接": []},
            specs={"近期作品链接": 4},
        )

    put.assert_not_called()
