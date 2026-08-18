from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from common.social_runtime import feishu_list_records, feishu_plain_text, feishu_table_url_from_env, load_default_env_files
from common.resource_ownership import canonical_tenant_owned_resources, require_tenant_id
from integrations.feishu.media_writer import upsert_entity_record, upsert_global_entity_record
from media_model.contract import MediaModelContract, MediaModelContractError

from .contracts import TrackCreatorMembership, TrackRegistry


RecordLoader = Callable[..., list[dict[str, Any]]]
EntityUpserter = Callable[[str, str, dict[str, Any]], dict[str, Any]]
GlobalEntityUpserter = Callable[[str, str, dict[str, Any], bool], dict[str, Any]]


class TrackRepositoryError(RuntimeError):
    pass


def _default_upserter(
    entity_name: str,
    table_url: str,
    payload: dict[str, Any],
    *,
    tenant_id: str,
) -> dict[str, Any]:
    if entity_name == "TrackRegistry":
        raise TrackRepositoryError("TrackRegistry is a global read-only catalog")
    return upsert_entity_record(
        entity_name,
        table_url,
        payload,
        key_field="membership_id",
        session_tenant_id=tenant_id,
    )


def _default_global_upserter(
    entity_name: str,
    table_url: str,
    payload: dict[str, Any],
    maintainer_authorized: bool,
) -> dict[str, Any]:
    return upsert_global_entity_record(
        entity_name,
        table_url,
        payload,
        key_field="track_id",
        maintainer_authorized=maintainer_authorized,
    )


def _stable_id(prefix: str, *parts: str) -> str:
    source = ":".join(part.strip() for part in parts)
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _text(value: Any) -> str:
    return feishu_plain_text(value).strip()


def _text_list(value: Any) -> tuple[str, ...]:
    if value in (None, "", []):
        return ()
    if isinstance(value, (list, tuple, set)):
        values = (_text(item) for item in value)
    else:
        values = (_text(item) for item in str(value).splitlines())
    return tuple(dict.fromkeys(item for item in values if item))


class TrackRepository:
    def __init__(
        self,
        *,
        tenant_id: str,
        track_table_url: str,
        membership_table_url: str,
        creator_profile_table_url: str,
        contract: MediaModelContract | None = None,
        record_loader: RecordLoader = feishu_list_records,
        entity_upserter: EntityUpserter = _default_upserter,
        global_entity_upserter: GlobalEntityUpserter = _default_global_upserter,
        tenant_owned_resources=None,
    ) -> None:
        if not track_table_url or not membership_table_url or not creator_profile_table_url:
            raise TrackRepositoryError("Track repository requires all three canonical Feishu table URLs")
        self.track_table_url = track_table_url
        self.membership_table_url = membership_table_url
        self.creator_profile_table_url = creator_profile_table_url
        self.contract = contract or MediaModelContract()
        self.record_loader = record_loader
        self.entity_upserter = entity_upserter
        self.global_entity_upserter = global_entity_upserter
        self.tenant_id = require_tenant_id(tenant_id)
        self.tenant_owned_resources = tenant_owned_resources or canonical_tenant_owned_resources()

    @classmethod
    def from_env(cls, *, tenant_id: str) -> "TrackRepository":
        load_default_env_files()
        return cls(
            track_table_url=feishu_table_url_from_env("MEDIA_OS_TRACK_REGISTRY_URL"),
            membership_table_url=feishu_table_url_from_env("MEDIA_OS_TRACK_CREATOR_MEMBERSHIP_URL"),
            creator_profile_table_url=feishu_table_url_from_env("MEDIA_OS_CREATOR_PROFILES_V2_URL"),
            tenant_id=tenant_id,
        )

    def _canonical_records(self, entity_name: str, table_url: str) -> list[dict[str, Any]]:
        if entity_name in {"CreatorProfile", "TrackCreatorMembership"}:
            return self._tenant_private_records(entity_name, table_url)
        rows: list[dict[str, Any]] = []
        for record in self.record_loader(table_url):
            fields = record.get("fields") if isinstance(record, dict) else None
            if not isinstance(fields, dict):
                continue
            rows.append(self.contract.normalize_record_fields(entity_name, fields))
        return rows

    def _tenant_private_records(self, entity_name: str, table_url: str) -> list[dict[str, Any]]:
        owner_service = self.tenant_owned_resources
        resource_type, id_field = {
            "CreatorProfile": ("media.creator_profile", "creator_profile_id"),
            "TrackCreatorMembership": (
                "media.track_creator_membership",
                "membership_id",
            ),
        }[entity_name]
        display_id_field = self.contract.feishu_field_name(entity_name, id_field)
        rows: list[dict[str, Any]] = []
        for owner in owner_service.registry.list_all_by_tenant(
            self.tenant_id,
            resource_type=resource_type,
        ):
            records = self.record_loader(
                table_url,
                page_size=2,
                filter_formula=(
                    f'CurrentValue.[{display_id_field}] = "{owner.canonical_resource_id}"'
                ),
            )
            if len(records) != 1:
                raise TrackRepositoryError(
                    f"{entity_name} canonical projection is missing or duplicated"
                )
            record = records[0]
            owner_service.assert_projection_read(
                resource_type,
                owner.canonical_resource_id,
                session_tenant_id=self.tenant_id,
                fields=record.get("fields") or {},
                projection_source=(
                    f"feishu:{entity_name}/{record.get('record_id') or 'missing'}"
                ),
            )
            rows.append(
                self.contract.normalize_record_fields(
                    entity_name,
                    record.get("fields") or {},
                )
            )
        return rows

    def list_tracks(self, *, include_inactive: bool = True) -> list[TrackRegistry]:
        tracks: list[TrackRegistry] = []
        for row in self._canonical_records("TrackRegistry", self.track_table_url):
            try:
                track = TrackRegistry(
                    track_id=_text(row.get("track_id")),
                    track_name=_text(row.get("track_name")),
                    parent_track_id=_text(row.get("parent_track_id")),
                    description=_text(row.get("description")),
                    platform_scope=_text_list(row.get("platform_scope")),
                    status=_text(row.get("status")),
                    alias_names=_text_list(row.get("alias_names")),
                )
            except ValueError as exc:
                raise TrackRepositoryError(f"invalid persisted TrackRegistry row: {exc}") from exc
            if not track.track_id or not track.track_name:
                raise TrackRepositoryError("persisted TrackRegistry row is missing track_id or track_name")
            if include_inactive or track.status == "active":
                tracks.append(track)
        return sorted(tracks, key=lambda item: (item.track_name, item.track_id))

    def get_track(self, track_id: str) -> TrackRegistry | None:
        expected = track_id.strip()
        return next((item for item in self.list_tracks() if item.track_id == expected), None)

    def find_track(self, value: str) -> TrackRegistry | None:
        expected = _text(value).casefold()
        if not expected:
            return None
        for item in self.list_tracks():
            names = (item.track_id, item.track_name, *item.alias_names)
            if any(_text(name).casefold() == expected for name in names):
                return item
        return None

    def get_creator_profile(self, creator_profile_id: str) -> dict[str, Any] | None:
        expected = _text(creator_profile_id)
        if not expected:
            return None
        return next(
            (
                row
                for row in self._canonical_records("CreatorProfile", self.creator_profile_table_url)
                if _text(row.get("creator_profile_id")) == expected
            ),
            None,
        )

    def list_memberships(
        self,
        *,
        track_id: str = "",
        include_rejected: bool = False,
    ) -> list[TrackCreatorMembership]:
        memberships: list[TrackCreatorMembership] = []
        for row in self._canonical_records("TrackCreatorMembership", self.membership_table_url):
            try:
                membership = TrackCreatorMembership(
                    membership_id=_text(row.get("membership_id")),
                    track_id=_text(row.get("track_id")),
                    creator_profile_id=_text(row.get("creator_profile_id")),
                    platform=_text(row.get("platform")),
                    author_id=_text(row.get("author_id")),
                    account_name_snapshot=_text(row.get("account_name_snapshot")),
                    role=_text(row.get("role")),
                    fit_score=int(float(_text(row.get("fit_score")) or 0)),
                    fit_reason=_text(row.get("fit_reason")),
                    content_use_case=_text(row.get("content_use_case")),
                    business_use_case=_text(row.get("business_use_case")),
                    evidence_refs=_text_list(row.get("evidence_refs")),
                    source_capability=_text(row.get("source_capability")),
                    status=_text(row.get("status")),
                    last_evaluated_at=_text(row.get("last_evaluated_at")),
                    metrics_snapshot_id=_text(row.get("metrics_snapshot_id")),
                )
            except (TypeError, ValueError) as exc:
                raise TrackRepositoryError(f"invalid persisted TrackCreatorMembership row: {exc}") from exc
            if not membership.membership_id or not membership.track_id or not membership.creator_profile_id:
                raise TrackRepositoryError("persisted TrackCreatorMembership row is missing its identity fields")
            if track_id and membership.track_id != track_id:
                continue
            if not include_rejected and membership.status == "rejected":
                continue
            memberships.append(membership)
        return sorted(memberships, key=lambda item: (item.track_id, -item.fit_score, item.membership_id))

    def upsert_track(
        self,
        track: TrackRegistry | dict[str, Any],
        *,
        maintainer_authorized: bool = False,
    ) -> dict[str, Any]:
        if not maintainer_authorized:
            raise TrackRepositoryError("TrackRegistry mutation requires maintainer authorization")
        payload = track.to_dict() if isinstance(track, TrackRegistry) else dict(track)
        track_name = _text(payload.get("track_name"))
        if not track_name:
            raise TrackRepositoryError("TrackRegistry requires track_name")
        existing_tracks = self.list_tracks(include_inactive=True)
        existing_by_name = next(
            (item for item in existing_tracks if item.track_name.casefold() == track_name.casefold()),
            None,
        )
        requested_id = _text(payload.get("track_id"))
        track_id = requested_id or (
            existing_by_name.track_id
            if existing_by_name is not None
            else _stable_id("track", track_name.casefold())
        )
        if existing_by_name is not None and existing_by_name.track_id != track_id:
            raise TrackRepositoryError(
                f"duplicate TrackRegistry name already owned by track_id={existing_by_name.track_id}"
            )
        existing_by_id = next((item for item in existing_tracks if item.track_id == track_id), None)
        parent_track_id = _text(payload.get("parent_track_id"))
        if parent_track_id == track_id:
            raise TrackRepositoryError("TrackRegistry cannot be its own parent")
        if parent_track_id and not any(item.track_id == parent_track_id for item in existing_tracks):
            raise TrackRepositoryError(f"unknown parent TrackRegistry: {parent_track_id}")
        try:
            entity = TrackRegistry(
                track_id=track_id,
                track_name=track_name,
                parent_track_id=parent_track_id,
                description=_text(payload.get("description")),
                platform_scope=_text_list(payload.get("platform_scope")),
                status=_text(payload.get("status")) or "active",
                alias_names=_text_list(payload.get("alias_names")),
            )
            self.contract.validate_payload("TrackRegistry", entity.to_dict())
        except (MediaModelContractError, TypeError, ValueError) as exc:
            raise TrackRepositoryError(f"track requires manual correction: {exc}") from exc
        if existing_by_id is not None and existing_by_id.to_dict() == entity.to_dict():
            return {
                "mode": "noop",
                "entity": "TrackRegistry",
                "entity_payload": entity.to_dict(),
            }
        result = self.global_entity_upserter(
            "TrackRegistry",
            self.track_table_url,
            entity.to_dict(),
            maintainer_authorized,
        )
        readback = result.get("readback_payload")
        if isinstance(readback, dict):
            normalized_readback = TrackRegistry(
                track_id=_text(readback.get("track_id")),
                track_name=_text(readback.get("track_name")),
                parent_track_id=_text(readback.get("parent_track_id")),
                description=_text(readback.get("description")),
                platform_scope=_text_list(readback.get("platform_scope")),
                status=_text(readback.get("status")),
                alias_names=_text_list(readback.get("alias_names")),
            )
            if normalized_readback.to_dict() != entity.to_dict():
                raise TrackRepositoryError("TrackRegistry readback mismatch")
        return {**result, "entity_payload": entity.to_dict()}

    def upsert_membership(self, membership: TrackCreatorMembership | dict[str, Any]) -> dict[str, Any]:
        payload = membership.to_dict() if isinstance(membership, TrackCreatorMembership) else dict(membership)
        track_id = _text(payload.get("track_id"))
        creator_profile_id = _text(payload.get("creator_profile_id"))
        if not track_id or not creator_profile_id:
            raise TrackRepositoryError("TrackCreatorMembership requires track_id and creator_profile_id")
        if not _text(payload.get("membership_id")):
            payload["membership_id"] = _stable_id("membership", track_id, creator_profile_id)
        evidence_refs = _text_list(payload.get("evidence_refs"))
        required_semantic = {
            "fit_reason": _text(payload.get("fit_reason")),
            "source_capability": _text(payload.get("source_capability")),
            "last_evaluated_at": _text(payload.get("last_evaluated_at")),
        }
        missing = [name for name, value in required_semantic.items() if not value]
        if not evidence_refs:
            missing.append("evidence_refs")
        if missing:
            raise TrackRepositoryError(f"membership evidence is incomplete; pending_manual required: {sorted(missing)}")
        try:
            entity = TrackCreatorMembership(
                membership_id=_text(payload.get("membership_id")),
                track_id=track_id,
                creator_profile_id=creator_profile_id,
                platform=_text(payload.get("platform")),
                author_id=_text(payload.get("author_id")),
                account_name_snapshot=_text(payload.get("account_name_snapshot")),
                role=_text(payload.get("role")),
                fit_score=payload.get("fit_score", 0),
                fit_reason=required_semantic["fit_reason"],
                content_use_case=_text(payload.get("content_use_case")),
                business_use_case=_text(payload.get("business_use_case")),
                evidence_refs=evidence_refs,
                source_capability=required_semantic["source_capability"],
                status=_text(payload.get("status")) or "candidate",
                last_evaluated_at=required_semantic["last_evaluated_at"],
                metrics_snapshot_id=_text(payload.get("metrics_snapshot_id")),
            )
        except ValueError as exc:
            raise TrackRepositoryError(f"membership requires manual correction: {exc}") from exc
        if not self.get_track(entity.track_id):
            raise TrackRepositoryError(f"unknown TrackRegistry: {entity.track_id}")
        profile_ids = {
            _text(row.get("creator_profile_id"))
            for row in self._canonical_records("CreatorProfile", self.creator_profile_table_url)
        }
        if entity.creator_profile_id not in profile_ids:
            raise TrackRepositoryError(f"unknown CreatorProfile: {entity.creator_profile_id}")
        existing_membership = next(
            (item for item in self.list_memberships(include_rejected=True) if item.membership_id == entity.membership_id),
            None,
        )
        if existing_membership and existing_membership.to_dict() == entity.to_dict():
            return {
                "mode": "noop",
                "entity": "TrackCreatorMembership",
                "entity_payload": entity.to_dict(),
            }
        duplicate = next(
            (
                item
                for item in self.list_memberships(include_rejected=True)
                if item.track_id == entity.track_id
                and item.creator_profile_id == entity.creator_profile_id
                and item.membership_id != entity.membership_id
            ),
            None,
        )
        if duplicate:
            raise TrackRepositoryError(
                f"duplicate track/profile relation already owned by membership_id={duplicate.membership_id}"
            )
        write_payload = entity.to_dict()
        write_payload["evidence_refs"] = "\n".join(entity.evidence_refs)
        if self.entity_upserter is _default_upserter:
            result = _default_upserter(
                "TrackCreatorMembership",
                self.membership_table_url,
                write_payload,
                tenant_id=self.tenant_id,
            )
        else:
            result = self.entity_upserter(
                "TrackCreatorMembership",
                self.membership_table_url,
                write_payload,
            )
        return {**result, "entity_payload": entity.to_dict()}
