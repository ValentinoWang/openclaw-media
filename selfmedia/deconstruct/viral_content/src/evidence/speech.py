from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .schemas import SpeechEvidence


SPEECH_CACHE_FILENAME = "speech_evidence.json"


def sha256_file(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _read_text(path: str | Path | None) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.is_file() or p.stat().st_size <= 0:
        return ""
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _cache_path(audio_path: str | Path) -> Path:
    return Path(audio_path).resolve().parent / SPEECH_CACHE_FILENAME


def _load_cached_speech(audio_path: str | Path, audio_hash: str) -> dict[str, Any] | None:
    path = _cache_path(audio_path)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("schema_version") != "speech_evidence_v1":
        return None
    if str(payload.get("audio_hash") or "") != audio_hash:
        return None
    evidence = payload.get("speech") if isinstance(payload.get("speech"), dict) else payload
    try:
        return SpeechEvidence.parse_obj(evidence).dict()
    except Exception:
        return None


def _write_cached_speech(audio_path: str | Path, evidence: dict[str, Any]) -> None:
    path = _cache_path(audio_path)
    payload = {
        "schema_version": "speech_evidence_v1",
        "audio_hash": evidence.get("audio_hash", ""),
        "speech": evidence,
    }
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return


def _first_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _first_time(payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 1000:
            number = number / 1000.0
        return max(0.0, number)
    return None


def _collect_segments(payload: Any, inherited_speaker: str = "") -> list[dict[str, Any]]:
    if isinstance(payload, list):
        result: list[dict[str, Any]] = []
        for item in payload:
            result.extend(_collect_segments(item, inherited_speaker))
        return result
    if not isinstance(payload, dict):
        return []
    speaker = _first_text(payload, ("speaker_id", "speaker", "spk", "speaker_no")) or inherited_speaker
    result: list[dict[str, Any]] = []
    for key in ("sentences", "sentence", "segments", "segment", "transcripts", "results"):
        value = payload.get(key)
        if isinstance(value, (list, dict)):
            result.extend(_collect_segments(value, speaker))
    text = _first_text(payload, ("text", "transcript", "content", "sentence_text"))
    start = _first_time(payload, ("begin_time", "start_time", "start", "begin"))
    end = _first_time(payload, ("end_time", "end"))
    if text and start is not None:
        if end is None or end <= start:
            end = start + max(0.5, min(6.0, len(text) / 6.0))
        confidence: float | None = None
        try:
            raw_conf = payload.get("confidence") or payload.get("score")
            confidence = float(raw_conf) if raw_conf is not None else None
        except (TypeError, ValueError):
            confidence = None
        result.append({"start": start, "end": end, "text": text, "speaker": speaker, "confidence": confidence})
    return result


def _segments_from_json(path: str | Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    p = Path(path)
    if not p.is_file() or p.stat().st_size <= 0:
        return []
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_segments = _collect_segments(payload)
    raw_segments.sort(key=lambda item: (float(item.get("start") or 0), float(item.get("end") or 0)))
    segments: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_segments, 1):
        segments.append(
            {
                "segment_id": f"sp_{idx:03d}",
                "start": round(float(item.get("start") or 0), 3),
                "end": round(float(item.get("end") or 0), 3),
                "text": str(item.get("text") or "").strip(),
                "speaker": str(item.get("speaker") or ""),
                "confidence": item.get("confidence"),
            }
        )
    return [item for item in segments if item["text"]]


def _candidate_segment_json_paths(audio_path: str | Path, transcript_path: str | Path | None) -> list[Path]:
    base = Path(audio_path).resolve().parent
    candidates = [
        base / "speech_segments.json",
        base / "transcript_segments.json",
        base / "asr_result.json",
    ]
    if transcript_path:
        p = Path(transcript_path)
        candidates.extend([p.with_suffix(".json"), p.with_name(f"{p.stem}_segments.json")])
    seen: set[Path] = set()
    result: list[Path] = []
    for item in candidates:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def build_speech_evidence(audio_path: str | None, transcript_path: str | None = None) -> dict[str, Any]:
    transcript = _read_text(transcript_path)
    if not audio_path:
        return SpeechEvidence(status="no_audio", provider="", transcript=transcript, reason="audio_path_missing").dict()
    audio = Path(audio_path)
    if not audio.is_file() or audio.stat().st_size <= 0:
        return SpeechEvidence(status="no_audio", provider="", transcript=transcript, reason="audio_file_missing").dict()

    audio_hash = sha256_file(audio)
    cached = _load_cached_speech(audio, audio_hash)
    if cached:
        return cached

    segments: list[dict[str, Any]] = []
    for candidate in _candidate_segment_json_paths(audio, transcript_path):
        segments = _segments_from_json(candidate)
        if segments:
            break
    if segments:
        if not transcript:
            transcript = "\n".join(item["text"] for item in segments)
        evidence = SpeechEvidence(
            status="success",
            provider="cached_segments",
            audio_hash=audio_hash,
            transcript=transcript,
            segments=segments,
        ).dict()
        _write_cached_speech(audio, evidence)
        return evidence

    if transcript:
        return SpeechEvidence(
            status="transcript_only",
            provider="cached_transcript",
            audio_hash=audio_hash,
            transcript=transcript,
            reason="transcript_has_no_timestamps",
        ).dict()

    return SpeechEvidence(
        status="asr_failed",
        provider="not_configured",
        audio_hash=audio_hash,
        transcript="",
        reason="no_transcript_or_segment_sidecar",
    ).dict()


def speech_summary_for_prompt(speech: dict[str, Any], *, max_segments: int = 40) -> str:
    status = str(speech.get("status") or "")
    if status == "success":
        lines = [f"speech.status=success；以下口播段落可被 LLM 引用，必须使用真实 segment_id："]
        for item in speech.get("segments") or []:
            lines.append(
                f"- {item.get('segment_id')} [{item.get('start')}-{item.get('end')}] {str(item.get('text') or '').strip()[:160]}"
            )
            if len(lines) > max_segments:
                lines.append("- ...（已截断，完整 speech.segments 见 facts/speech_facts.json 与 evidence_store）")
                break
        return "\n".join(lines)
    if status == "transcript_only":
        text = " ".join(str(speech.get("transcript") or "").split())
        return (
            "speech.status=transcript_only；只有 transcript 文本，没有可引用 segment_id。"
            "LLM 只能把它作为摘要背景，不得编造证据引用。\n"
            f"逐字稿摘要：{text[:1000]}"
        )
    return f"speech.status={status or 'unknown'}；无可靠 ASR 时间线，LLM 不得输出口播功能判断。原因：{speech.get('reason', '')}"
