"""Persistent, outbound-only Media Agent job lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import threading
import time
from typing import Any, Callable, Mapping

from .catalog import InstalledCatalog
from .device_credentials import DeviceCredentialError, DeviceCredentialStore
from .node_registry import NodeRegistry
from .pipeline_runtime import PipelineRuntime
from .remote_client import API_VERSION, RemoteClient, RemoteError


class AgentError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_ref(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "://" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)


@dataclass(frozen=True, slots=True)
class AgentState:
    remote_base_url: str | None = None
    device_id: str | None = None
    device_label: str | None = None
    client_version: str = "0.2.0"
    catalog_digest: str | None = None
    revision: int = 1
    status: str = "stopped"
    last_code: str | None = None
    credential_ref: str | None = None
    session_ref: str | None = None
    active_job: dict[str, Any] | None = None
    workspace: str | None = None


@dataclass(slots=True)
class AgentStateStore:
    path: Path

    @staticmethod
    def _validate_credential_refs(
        device_id: Any,
        credential_ref: Any,
        session_ref: Any,
    ) -> None:
        if credential_ref is None and session_ref is None:
            return
        if not isinstance(device_id, str):
            raise AgentError("state_secret_forbidden")
        try:
            refs = DeviceCredentialStore.refs(device_id)
        except DeviceCredentialError as exc:
            raise AgentError("state_invalid") from exc
        if credential_ref is not None and credential_ref != refs.device:
            raise AgentError("state_secret_forbidden")
        if session_ref is not None and session_ref != refs.session:
            raise AgentError("state_secret_forbidden")

    def load(self) -> AgentState:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return AgentState()
        except (OSError, ValueError) as exc:
            raise AgentError("state_unavailable") from exc
        if not isinstance(raw, Mapping):
            raise AgentError("state_invalid")
        if any(str(key).lower() in {"credential", "device_credential", "session_credential", "api_key", "password", "token"} for key in raw):
            raise AgentError("state_secret_forbidden")
        allowed = {field for field in AgentState.__dataclass_fields__}
        value = {key: item for key, item in raw.items() if key in allowed}
        self._validate_credential_refs(
            value.get("device_id"), value.get("credential_ref"), value.get("session_ref")
        )
        try:
            return AgentState(**value)
        except TypeError as exc:
            raise AgentError("state_invalid") from exc

    def save(self, state: AgentState) -> None:
        self._validate_credential_refs(state.device_id, state.credential_ref, state.session_ref)
        if state.active_job is not None:
            for key in ("job_id", "run_ref"):
                if not _safe_ref(state.active_job.get(key)):
                    raise AgentError("state_invalid")
        payload = {
            "remote_base_url": state.remote_base_url,
            "device_id": state.device_id,
            "device_label": state.device_label,
            "client_version": state.client_version,
            "catalog_digest": state.catalog_digest,
            "revision": state.revision,
            "status": state.status,
            "last_code": state.last_code,
            "credential_ref": state.credential_ref,
            "session_ref": state.session_ref,
            "active_job": state.active_job,
            "workspace": state.workspace,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        temporary.replace(self.path)


RuntimeFactory = Callable[[Path, InstalledCatalog], PipelineRuntime]


@dataclass(slots=True)
class Agent:
    remote: RemoteClient
    state_store: AgentStateStore
    credential_store: DeviceCredentialStore
    workspace: Path
    catalog: InstalledCatalog = field(default_factory=InstalledCatalog)
    provider: Any | None = None
    runtime_factory: RuntimeFactory | None = None
    lease_seconds: int = 300

    def state(self) -> AgentState:
        return self.state_store.load()

    def pair(self, *, pair_code: str, device_label: str, client_version: str) -> Mapping[str, Any]:
        if not isinstance(pair_code, str) or not pair_code.strip() or not isinstance(device_label, str) or not device_label.strip():
            raise AgentError("invalid_pair_request")
        response = self.remote.pair(pair_code=pair_code, device_label=device_label, client_version=client_version)
        device = response.get("device")
        credential = response.get("device_credential")
        if not isinstance(device, Mapping) or not isinstance(device.get("device_id"), str) or not isinstance(credential, str):
            raise AgentError("invalid_pair_response")
        refs = self.credential_store.put_device(str(device["device_id"]), credential)
        session_ref = None
        session_credential = response.get("session_credential")
        if isinstance(session_credential, str) and session_credential:
            session_ref = self.credential_store.put_session(str(device["device_id"]), session_credential).session
        state = AgentState(
            remote_base_url=self.state_store.load().remote_base_url,
            device_id=str(device["device_id"]),
            device_label=str(device.get("device_label", device_label)),
            client_version=client_version,
            catalog_digest=self.catalog.manifest["catalog_digest"],
            revision=max(1, int(device.get("revision", 1))),
            status="stopped",
            credential_ref=refs.device,
            session_ref=session_ref,
            workspace=str(self.workspace),
        )
        self.state_store.save(state)
        return {"device": dict(device), "paired": True, "credential_ref": refs.device}

    def _runtime(self) -> PipelineRuntime:
        if self.runtime_factory is not None:
            return self.runtime_factory(self.workspace, self.catalog)
        return PipelineRuntime(
            self.workspace,
            catalog=self.catalog,
            node_registry=NodeRegistry(self.catalog, provider=self.provider),
        )

    def _save_status(self, state: AgentState, *, status: str, code: str | None = None, active_job: dict[str, Any] | None = None, revision: int | None = None) -> AgentState:
        updated = AgentState(
            remote_base_url=state.remote_base_url,
            device_id=state.device_id,
            device_label=state.device_label,
            client_version=state.client_version,
            catalog_digest=state.catalog_digest,
            revision=state.revision if revision is None else revision,
            status=status,
            last_code=code,
            credential_ref=state.credential_ref,
            session_ref=state.session_ref,
            active_job=active_job,
            workspace=state.workspace or str(self.workspace),
        )
        self.state_store.save(updated)
        return updated

    def _job_summary(self, job: Mapping[str, Any], *, run_ref: str) -> dict[str, Any]:
        fields = ("job_id", "state", "pipeline_id", "pipeline_version", "catalog_digest", "revision", "lease_id")
        summary = {key: job.get(key) for key in fields}
        summary["run_ref"] = run_ref
        if not _safe_ref(summary.get("job_id")) or not _safe_ref(run_ref):
            raise AgentError("invalid_job")
        return summary

    def _run_claimed_job(self, state: AgentState, job: Mapping[str, Any]) -> AgentState:
        job_id = job.get("job_id")
        if not isinstance(job_id, str):
            raise AgentError("invalid_job")
        run_ref = "runs/" + sha256(job_id.encode("utf-8")).hexdigest()[:32]
        active = self._job_summary(job, run_ref=run_ref)
        state = self._save_status(state, status="running", active_job=active, revision=int(job.get("revision", state.revision)))
        current = job
        if current.get("state") == "leased":
            current = self.remote.job_ack(job_id, ack_ref="ack/" + sha256(job_id.encode()).hexdigest()[:24], expected_revision=int(current["revision"])).get("job", {})
        if not isinstance(current, Mapping):
            raise AgentError("invalid_job_response")
        if current.get("state") == "acknowledged":
            current = self.remote.job_start(job_id, start_ref="start/" + sha256(job_id.encode()).hexdigest()[:24], expected_revision=int(current["revision"])).get("job", {})
        if not isinstance(current, Mapping) or current.get("state") != "running":
            raise AgentError("invalid_job_state")
        state = self._save_status(state, status="running", active_job=self._job_summary(current, run_ref=run_ref), revision=int(current.get("revision", state.revision)))
        pipeline_id = current.get("pipeline_id")
        pipeline_version = current.get("pipeline_version")
        digest = current.get("catalog_digest")
        inputs = current.get("input_refs")
        if not isinstance(pipeline_id, str) or not isinstance(pipeline_version, str) or digest != self.catalog.manifest["catalog_digest"] or not isinstance(inputs, list) or not inputs or not all(_safe_ref(item) for item in inputs):
            result_status, failure = "blocked", "catalog_or_input_rejected"
            result_refs: list[str] = []
        else:
            runtime = self._runtime()
            result = runtime.create_run(pipeline_id, pipeline_version, digest, run_ref=run_ref, inputs={"workspace_ref": inputs[0]})
            if result.status not in {"pending_manual", "cancelled"}:
                result = runtime.execute(run_ref, inputs={"workspace_ref": inputs[0]})
            if result.status == "succeeded" and result.receipt is not None:
                result_status, failure = "succeeded", None
                result_refs = [artifact.artifact_ref for node in result.receipt.node_receipts for artifact in node.artifacts]
            else:
                result_status, failure, result_refs = "blocked", result.code, []
        response = self.remote.job_result(
            job_id,
            result_status=result_status,
            result_refs=result_refs,
            artifact_refs=result_refs,
            failure_code=failure,
            expected_revision=int(current["revision"]),
        )
        returned = response.get("job") if isinstance(response, Mapping) else None
        final_revision = int(returned.get("revision", current["revision"])) if isinstance(returned, Mapping) else int(current["revision"])
        return self._save_status(state, status="stopped", code=result_status, active_job=None, revision=final_revision)

    def run_once(self) -> AgentState:
        state = self.state_store.load()
        if not state.device_id or not state.remote_base_url:
            return self._save_status(state, status="blocked", code="not_paired")
        try:
            credential = self.credential_store.get_device(state.device_id)
        except DeviceCredentialError as exc:
            return self._save_status(state, status="blocked", code=exc.code)
        self.remote.device_credential = credential
        try:
            heartbeat = self.remote.heartbeat(
                device_id=state.device_id,
                observed_at=_timestamp(),
                client_version=state.client_version,
                api_version=API_VERSION,
                catalog_digest=self.catalog.manifest["catalog_digest"],
                capabilities=[],
                expected_revision=max(1, state.revision),
            )
            revision = int(heartbeat.get("revision", state.revision))
            if heartbeat.get("state") == "revoked" or not heartbeat.get("api_compatible", False) or not heartbeat.get("catalog_compatible", False):
                return self._save_status(state, status="blocked", code="device_not_compatible", revision=revision)
            job: Mapping[str, Any] | None = None
            if state.active_job:
                jobs = self.remote.job_list(limit=100)
                for candidate in jobs.get("jobs", []):
                    if isinstance(candidate, Mapping) and candidate.get("job_id") == state.active_job.get("job_id"):
                        job = candidate
                        break
                if job is None:
                    return self._save_status(state, status="stopped", code="job_not_found", revision=revision)
                if job.get("state") in {"succeeded", "blocked", "failed", "expired", "cancelled"}:
                    return self._save_status(state, status="stopped", code="already_completed", active_job=None, revision=max(revision, int(job.get("revision", revision))))
            else:
                claimable = heartbeat.get("claimable_job")
                if isinstance(claimable, Mapping) and isinstance(claimable.get("job_id"), str):
                    listed = self.remote.job_list(limit=100)
                    job = next((item for item in listed.get("jobs", []) if isinstance(item, Mapping) and item.get("job_id") == claimable.get("job_id")), None)
                if job is None:
                    return self._save_status(state, status="stopped", code="idle", revision=revision)
                if job.get("state") == "queued":
                    leased = self.remote.job_lease(str(job["job_id"]), lease_seconds=self.lease_seconds, expected_revision=int(job["revision"]))
                    job = leased.get("job")
            if not isinstance(job, Mapping):
                return self._save_status(state, status="blocked", code="invalid_job", revision=revision)
            return self._run_claimed_job(self._save_status(state, status="running", revision=revision), job)
        except (RemoteError, AgentError) as exc:
            current = self.state_store.load()
            return self._save_status(
                current,
                status="blocked",
                code=getattr(exc, "code", "agent_failed"),
                active_job=current.active_job,
            )

    def run_forever(self, *, interval: float = 30.0, stop_event: threading.Event | None = None) -> None:
        stop = stop_event or threading.Event()
        while not stop.is_set():
            self.run_once()
            stop.wait(max(1.0, interval))


MediaAgent = Agent

__all__ = ["Agent", "AgentError", "AgentState", "AgentStateStore", "MediaAgent"]
