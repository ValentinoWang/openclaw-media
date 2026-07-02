from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, root_validator, validator


ASSET_MANIFEST_SCHEMA_VERSION = "asset_manifest_v1"
MODALITY_FACTS_SCHEMA_VERSION = "modality_facts_v1"
EVIDENCE_STORE_SCHEMA_VERSION = "evidence_store_v1"

SpeechStatus = Literal["success", "no_audio", "asr_failed", "transcript_only"]
OcrStatus = Literal["success", "no_visible_text", "ocr_failed"]
CommentsStatus = Literal["verified_three_comments", "insufficient_comments", "no_comments"]
EngagementStatus = Literal["captured", "missing"]
ModalityFactStatus = Literal["success", "missing", "failed", "not_applicable", "insufficient_evidence"]


class SpeechSegment(BaseModel):
    segment_id: str
    start: float
    end: float
    text: str
    speaker: str = ""
    confidence: float | None = None

    class Config:
        extra = "allow"

    @validator("text", pre=True)
    def text_required(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("speech segment text 不能为空")
        return text


class SpeechEvidence(BaseModel):
    status: SpeechStatus
    provider: str = ""
    audio_hash: str = ""
    transcript: str = ""
    segments: list[SpeechSegment] = Field(default_factory=list)
    reason: str = ""

    class Config:
        extra = "allow"

    @root_validator(skip_on_failure=True)
    def validate_status_segments(cls, values: dict[str, Any]) -> dict[str, Any]:
        if values.get("status") == "success" and not values.get("segments"):
            raise ValueError("speech.status=success 时 segments 不能为空")
        if values.get("status") != "success":
            values["segments"] = []
        return values


class OcrTextSegment(BaseModel):
    text_segment_id: str
    asset_id: str
    bbox: list[float] = Field(default_factory=list)
    text: str
    confidence: float | None = None

    class Config:
        extra = "allow"

    @validator("text", pre=True)
    def text_required(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("ocr text 不能为空")
        return text


class OcrTextTrack(BaseModel):
    track_id: str
    text: str
    start_asset_id: str
    end_asset_id: str
    asset_ids: list[str] = Field(default_factory=list)
    confidence_avg: float | None = None

    class Config:
        extra = "allow"


class CoverTextCandidate(BaseModel):
    source: Literal["platform_cover", "first_frame", "image_cover"]
    asset_id: str
    text: str
    confidence: float | None = None

    class Config:
        extra = "allow"


class OcrEvidence(BaseModel):
    status: OcrStatus
    sampling_policy: dict[str, Any] = Field(default_factory=dict)
    visible_text_segments: list[OcrTextSegment] = Field(default_factory=list)
    text_tracks: list[OcrTextTrack] = Field(default_factory=list)
    cover_text_candidates: list[CoverTextCandidate] = Field(default_factory=list)
    reason: str = ""

    class Config:
        extra = "allow"

    @root_validator(skip_on_failure=True)
    def validate_status_segments(cls, values: dict[str, Any]) -> dict[str, Any]:
        if values.get("status") == "success" and not (values.get("visible_text_segments") or values.get("text_tracks") or values.get("cover_text_candidates")):
            raise ValueError("ocr.status=success 时 OCR 结果不能为空")
        if values.get("status") != "success":
            values["visible_text_segments"] = []
            values["text_tracks"] = []
            values["cover_text_candidates"] = []
        return values


class AssetManifestAsset(BaseModel):
    asset_id: str
    path: str
    kind: str = ""
    phase: str = ""
    role: str = "visual"

    class Config:
        extra = "allow"


class AssetManifestV1(BaseModel):
    """Canonical asset layer for the deconstruct/recreate modality DAG."""

    schema_version: Literal["asset_manifest_v1"] = ASSET_MANIFEST_SCHEMA_VERSION
    source_url: str
    media_type: Literal["video", "image_post"]
    source_path: str = ""
    work_dir: str = ""
    video_path: str = ""
    image_paths: list[str] = Field(default_factory=list)
    audio_path: str = ""
    preview_path: str = ""
    platform_asset_id: str = ""
    source_caption: str = ""
    source_title: str = ""
    published_at: str = ""
    stats: dict[str, Any] = Field(default_factory=dict)
    assets: list[AssetManifestAsset] = Field(default_factory=list)

    class Config:
        extra = "allow"

class ModalityFactsV1(BaseModel):
    """One modality fact file. It records source facts only, not creative judgment."""

    schema_version: Literal["modality_facts_v1"] = MODALITY_FACTS_SCHEMA_VERSION
    fact_type: str
    status: ModalityFactStatus = "success"
    source_refs: list[str] = Field(default_factory=list)
    facts: dict[str, Any] = Field(default_factory=dict)
    missing_reason: str = ""

    class Config:
        extra = "allow"

    @root_validator(skip_on_failure=True)
    def require_reason_for_missing(cls, values: dict[str, Any]) -> dict[str, Any]:
        if values.get("status") in {"missing", "failed", "not_applicable", "insufficient_evidence"} and not values.get("missing_reason"):
            values["missing_reason"] = str(values.get("status") or "missing")
        return values


class EvidenceStoreV1(BaseModel):
    """The single canonical fact input for the main deconstruction LLM."""

    schema_version: Literal["evidence_store_v1"] = EVIDENCE_STORE_SCHEMA_VERSION
    asset_manifest: AssetManifestV1
    modality_facts: dict[str, ModalityFactsV1] = Field(default_factory=dict)
    evidence_manifest: dict[str, dict[str, Any]] = Field(default_factory=dict)
    llm_input_compact: dict[str, Any] = Field(default_factory=dict)
    missing_evidence_report: list[dict[str, Any]] = Field(default_factory=list)

    class Config:
        extra = "allow"

    @root_validator(skip_on_failure=True)
    def validate_fact_refs(cls, values: dict[str, Any]) -> dict[str, Any]:
        manifest_ids = set((values.get("evidence_manifest") or {}).keys())
        asset_ids = {asset.asset_id for asset in (values.get("asset_manifest").assets if values.get("asset_manifest") else [])}
        allowed = manifest_ids | asset_ids
        for name, fact in (values.get("modality_facts") or {}).items():
            invalid = sorted(ref for ref in fact.source_refs if ref not in allowed)
            if invalid:
                raise ValueError(f"modality_facts.{name}.source_refs 非法: {', '.join(invalid)}")
        return values


def validate_asset_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    return _jsonable_model_dict(AssetManifestV1.parse_obj(payload))


def validate_modality_facts(payload: dict[str, Any]) -> dict[str, Any]:
    return _jsonable_model_dict(ModalityFactsV1.parse_obj(payload))


def validate_evidence_store(payload: dict[str, Any]) -> dict[str, Any]:
    return _jsonable_model_dict(EvidenceStoreV1.parse_obj(payload))


def _jsonable_model_dict(model: BaseModel) -> dict[str, Any]:
    return _jsonable(model.dict())


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
