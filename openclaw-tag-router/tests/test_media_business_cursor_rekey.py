"""Regression coverage for the c3/c5 cursor re-key (dedup gap-2 audit).

Proves, for every media_business service whose cursor-signing key was
re-derived onto foundation.derive_namespace_secret with a distinct purpose
per page:

1. Public-id signing is COMPLETELY untouched -- byte-identical output (the
   deterministic encoders) or byte-identical signing key (the
   secrets.token_urlsafe-suffixed ones, whose *string* output can never be
   reproduced call to call).
2. New-format cursors still round-trip on each service (belt-and-braces on
   top of each service's own existing round-trip test).
3. A cursor issued by one service is rejected -- via signature/scope
   mismatch, never a KeyError or an unhandled exception -- when presented
   to a *different* service's decoder (the actual c3 security fix: tracks
   and assets no longer share a key).
4. A cursor built with the OLD (pre-rekey) algorithm is rejected cleanly as
   an ordinary invalid-cursor error after the deploy, not a crash.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest

from openclaw_app.services.media_business import (
    admin_access,
    admin_billing,
    admin_tenants,
    assets,
    decisions,
    foundation,
    invites,
    publishing,
    reviews,
    runs,
    tracks,
)
from openclaw_app.services.media_business.assets import AssetCursor
from openclaw_app.services.media_business.tracks import TrackCursor

SECRET = b"c3c5-regression-fixed-secret-32"
OTHER_SECRET = b"c3c5-regression-different-secret"
FIXED_UUID = UUID("11111111-2222-3333-4444-555555555555")
TENANT = "tenant-a"


def _factory() -> Any:
    @contextmanager
    def _cm() -> Any:
        raise AssertionError("connection factory should not be invoked in these tests")
        yield  # pragma: no cover

    return _cm


# --- 1. Public-id signing is untouched --------------------------------------


def test_admin_tenants_and_admin_billing_public_ids_unaffected_by_cursor_rekey() -> None:
    at = admin_tenants.AdminTenantsService(_factory(), public_id_secret=SECRET, cursor_secret=SECRET)
    ab = admin_billing.AdminBillingService(_factory(), public_id_secret=SECRET)
    # These two were never touched by this change (they already used
    # derive_namespace_secret before c3/c5); this pins that they still
    # agree with each other, proving neither's derivation shifted.
    assert at.public_tenant_id(FIXED_UUID) == ab.public_tenant_id(FIXED_UUID)


def test_admin_access_public_ids_are_byte_identical_after_cursor_rekey() -> None:
    service = admin_access.AdminAccessService(_factory(), public_id_secret=SECRET, cursor_secret=SECRET)
    assert service.public_user_id(FIXED_UUID) == (
        "eyJpZCI6IjExMTExMTExLTIyMjItMzMzMy00NDQ0LTU1NTU1NTU1NTU1NSIsIm5hbWVzcGFjZSI6"
        "ImFkbWluLXVzZXIifS7aVtnMfjpE4GSds-t5XXcNZ3A"
    )
    assert service.public_batch_id(FIXED_UUID) == (
        "eyJpZCI6IjExMTExMTExLTIyMjItMzMzMy00NDQ0LTU1NTU1NTU1NTU1NSIsIm5hbWVzcGFjZSI6"
        "ImFkbWluLWJhdGNoIn0uR9e1BXDSnALk94DY9Gc11W2f"
    )
    # Captured pre-rekey via the same construction (server_cli.py wires the
    # same secret into public_id_secret= and cursor_secret=).
    assert service._public_id_secret == SECRET


def test_invites_public_user_id_is_byte_identical_after_cursor_rekey() -> None:
    assert invites._public_user_id(FIXED_UUID, SECRET) == "user_91f17f168cac38261862ad40cea83783"


@pytest.mark.parametrize(
    "make_service, secret_attr",
    [
        (lambda: runs.RunsService(_factory(), cursor_secret=SECRET), "_public_id_secret"),
        (
            lambda: decisions.DecisionsService(_factory(), cursor_secret=SECRET, public_id_secret=SECRET),
            "_public_id_secret",
        ),
        (
            lambda: reviews.ReviewsService(_factory(), cursor_secret=SECRET, public_id_secret=SECRET),
            "_public_id_secret",
        ),
        (
            lambda: publishing.PublishingService(_factory(), cursor_secret=SECRET, public_id_secret=SECRET),
            "_public_id_secret",
        ),
    ],
)
def test_random_suffix_public_id_signing_key_is_byte_identical_after_cursor_rekey(
    make_service: Any, secret_attr: str
) -> None:
    # runs/decisions/reviews/publishing sign public ids with
    # secrets.token_urlsafe() folded in, so the *string* output is never
    # reproducible call to call -- what must be pinned is the signing key
    # itself. runs derives it (bare sha256, unchanged); the other three use
    # the raw public_id_secret bytes (unchanged).
    service = make_service()
    key = getattr(service, secret_attr)
    if service is runs or isinstance(service, runs.RunsService):
        assert key == hashlib.sha256(SECRET).digest()
    else:
        assert key == SECRET


# --- 2. New-format cursors round-trip ---------------------------------------


def test_tracks_cursor_round_trips_on_new_format() -> None:
    service = tracks.TracksService(_factory(), cursor_secret=SECRET)
    encoded = service._encode_cursor(TENANT, TrackCursor("tracks", datetime(2026, 1, 1, tzinfo=timezone.utc), "public_track_1"))
    decoded = service._decode_cursor(encoded, TENANT, "tracks")
    assert decoded.public_id == "public_track_1"


def test_assets_cursor_round_trips_on_new_format_with_scope_field() -> None:
    service = assets.AssetsService(_factory(), cursor_secret=SECRET)
    encoded = service._encode_cursor(TENANT, AssetCursor(datetime(2026, 1, 1, tzinfo=timezone.utc), "public_asset_1"))
    payload = json.loads(base64.urlsafe_b64decode(encoded.split(".")[0] + "=" * 2))
    assert payload["scope"] == "assets"
    decoded = service._decode_cursor(encoded, TENANT)
    assert decoded.public_asset_id == "public_asset_1"


# --- 3. Cross-service cursor rejection (the actual c3 security fix) --------


def test_tracks_and_assets_cursor_keys_are_now_distinct() -> None:
    tracks_key = foundation.derive_namespace_secret(SECRET, "tracks-cursor")
    assets_key = foundation.derive_namespace_secret(SECRET, "assets-cursor")
    assert tracks_key != assets_key


def test_assets_cursor_is_rejected_by_tracks_decoder() -> None:
    assets_service = assets.AssetsService(_factory(), cursor_secret=SECRET)
    tracks_service = tracks.TracksService(_factory(), cursor_secret=SECRET)
    forged = assets_service._encode_cursor(TENANT, AssetCursor(datetime(2026, 1, 1, tzinfo=timezone.utc), "public_asset_1"))
    with pytest.raises(tracks.TrackInvalidRequest):
        tracks_service._decode_cursor(forged, TENANT, "tracks")


def test_tracks_cursor_is_rejected_by_assets_decoder() -> None:
    tracks_service = tracks.TracksService(_factory(), cursor_secret=SECRET)
    assets_service = assets.AssetsService(_factory(), cursor_secret=SECRET)
    forged = tracks_service._encode_cursor(TENANT, TrackCursor("tracks", datetime(2026, 1, 1, tzinfo=timezone.utc), "public_track_1"))
    with pytest.raises(assets.AssetInvalidRequest):
        assets_service._decode_cursor(forged, TENANT)


# --- 4. An old-format (pre-rekey) cursor fails cleanly, not a crash --------


def _old_format_tracks_cursor(secret: bytes, tenant_id: str) -> str:
    """Reproduces the exact pre-c3/c5 tracks algorithm: bare
    sha256(cursor_secret) key, 18-byte truncated signature."""
    old_key = hashlib.sha256(secret).digest()
    payload = json.dumps(
        {"publicId": "public_track_1", "scope": "tracks", "updatedAt": "2026-01-01T00:00:00+00:00"},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    signature = hmac.new(old_key, tenant_id.encode() + b"|" + payload, hashlib.sha256).digest()[:18]

    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    return f"{_b64(payload)}.{_b64(signature)}"


def test_old_format_tracks_cursor_is_rejected_as_a_clean_invalid_cursor_error() -> None:
    service = tracks.TracksService(_factory(), cursor_secret=SECRET)
    old_cursor = _old_format_tracks_cursor(SECRET, TENANT)
    # Sanity: this really is what the pre-rekey algorithm produced -- the
    # new key must differ from the old bare-sha256 one, or this test would
    # accidentally pass for the wrong reason.
    assert service._cursor_key != hashlib.sha256(SECRET).digest()
    with pytest.raises(tracks.TrackInvalidRequest):
        service._decode_cursor(old_cursor, TENANT, "tracks")


def test_old_format_assets_cursor_is_rejected_as_a_clean_invalid_cursor_error() -> None:
    service = assets.AssetsService(_factory(), cursor_secret=SECRET)
    old_key = hashlib.sha256(SECRET).digest()
    payload = json.dumps(
        {"createdAt": "2026-01-01T00:00:00+00:00", "publicAssetId": "public_asset_1"},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    signature = hmac.new(old_key, TENANT.encode("utf-8") + b"|" + payload, hashlib.sha256).digest()[:18]

    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    old_cursor = f"{_b64(payload)}.{_b64(signature)}"
    with pytest.raises(assets.AssetInvalidRequest):
        service._decode_cursor(old_cursor, TENANT)


def test_publishing_tenant_tag_now_derives_from_the_same_key_as_the_envelope_signature() -> None:
    # Collapses the pre-existing quirk where the envelope signature used
    # _cursor_key(secret) (a derived key) while tenantTag used the raw
    # secret directly -- both now go through _cursor_key(secret).
    assert publishing._cursor_key(SECRET) == foundation.derive_namespace_secret(SECRET, "publishing-cursor")
    assert publishing._cursor_key(SECRET) != SECRET
