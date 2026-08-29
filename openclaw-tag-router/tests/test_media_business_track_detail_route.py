from __future__ import annotations

from openclaw_app.adapters.media_business_dispatcher import (
    CANONICAL_PREFIX,
    MEDIA_BUSINESS_ROUTE_BINDINGS,
    MediaBusinessDispatcher,
    resolve_media_business_operation,
)


TRACK_ID = "record_008bbc93d6"


def test_listed_track_identity_resolves_and_dispatches_to_get_track() -> None:
    match = resolve_media_business_operation("GET", f"{CANONICAL_PREFIX}/tracks/{TRACK_ID}")

    assert match is not None
    assert match.operation_id == "getTrack"
    assert match.path_parameters == {"publicTrackId": TRACK_ID}

    handlers = {
        route.operation_id: (
            lambda route_match, _request: (route_match.operation_id, dict(route_match.path_parameters))
        )
        for route in MEDIA_BUSINESS_ROUTE_BINDINGS
    }
    handled, response = MediaBusinessDispatcher(handlers).dispatch(
        "GET", f"{CANONICAL_PREFIX}/tracks/{TRACK_ID}", {"actor": "test"}
    )

    assert handled is True
    assert response == ("getTrack", {"publicTrackId": TRACK_ID})


def test_asset_preview_identity_resolves_to_same_origin_route() -> None:
    match = resolve_media_business_operation(
        "GET", f"{CANONICAL_PREFIX}/assets/asset_123456/preview"
    )
    assert match is not None
    assert match.operation_id == "getAssetPreview"
    assert match.path_parameters == {"publicAssetId": "asset_123456"}


def test_account_monitor_identity_resolves_under_owned_account() -> None:
    match = resolve_media_business_operation(
        "GET", f"{CANONICAL_PREFIX}/owned-accounts/account_123456/monitor"
    )
    assert match is not None
    assert match.operation_id == "getAccountMonitor"
    assert match.path_parameters == {"publicAccountId": "account_123456"}
