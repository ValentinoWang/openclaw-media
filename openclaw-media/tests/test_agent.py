from __future__ import annotations

import json

import pytest

from openclaw_media.agent import Agent, AgentState, AgentStateStore
from openclaw_media.catalog import InstalledCatalog
from openclaw_media.device_credentials import DeviceCredentialStore


class Keyring:
    def __init__(self):
        self.values = {}

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def get_password(self, service, username):
        return self.values.get((service, username))

    def delete_password(self, service, username):
        self.values.pop((service, username), None)


class FakeRemote:
    def __init__(self, catalog):
        pipeline = catalog.manifest["pipelines"][1]
        self.job = {
            "job_id": "job_1", "state": "queued", "pipeline_id": pipeline["pipeline_id"],
            "pipeline_version": pipeline["version"], "catalog_digest": pipeline["catalog_digest"],
            "input_refs": ["media"], "output_selection": ["organization_plan"], "revision": 1,
        }
        self.result_calls = 0
        self.device_credential = None

    def heartbeat(self, **kwargs):
        return {"revision": self.job["revision"], "state": "online", "api_compatible": True, "catalog_compatible": True, "claimable_job": None if self.job["state"] == "succeeded" else {"job_id": self.job["job_id"], "state": self.job["state"]}}

    def job_list(self, **kwargs):
        return {"jobs": [self.job]}

    def job_lease(self, job_id, **kwargs):
        self.job.update(state="leased", revision=2, lease_id="lease_1")
        return {"job": self.job}

    def job_ack(self, job_id, **kwargs):
        self.job.update(state="acknowledged", revision=3)
        return {"job": self.job}

    def job_start(self, job_id, **kwargs):
        self.job.update(state="running", revision=4)
        return {"job": self.job}

    def job_result(self, job_id, **kwargs):
        self.result_calls += 1
        self.job.update(state="succeeded", revision=5)
        return {"job": self.job}


def test_agent_runs_real_pipeline_persists_safe_state_and_is_restart_idempotent(tmp_path):
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "clip.png").write_bytes(b"local-media")
    catalog = InstalledCatalog()
    remote = FakeRemote(catalog)
    credentials = DeviceCredentialStore(backend=Keyring())
    credentials.put_device("dev_1", "device-secret")
    state_store = AgentStateStore(tmp_path / "agent-state.json")
    state_store.save(AgentState(remote_base_url="http://fake", device_id="dev_1", catalog_digest=catalog.manifest["catalog_digest"], workspace=str(tmp_path)))
    agent = Agent(remote, state_store, credentials, tmp_path, catalog=catalog)
    first = agent.run_once()
    assert first.status == "stopped"
    assert first.last_code == "succeeded"
    assert remote.result_calls == 1
    raw = (tmp_path / "agent-state.json").read_text()
    assert "device-secret" not in raw
    assert str(tmp_path / "media" / "clip.png") not in raw
    restarted = Agent(remote, state_store, credentials, tmp_path, catalog=catalog)
    second = restarted.run_once()
    assert second.last_code == "idle"
    assert remote.result_calls == 1


def test_revoked_device_stops_before_claim(tmp_path):
    catalog = InstalledCatalog()
    remote = FakeRemote(catalog)
    remote.heartbeat = lambda **kwargs: {"revision": 2, "state": "revoked", "api_compatible": False, "catalog_compatible": False, "claimable_job": None}
    credentials = DeviceCredentialStore(backend=Keyring())
    credentials.put_device("dev_1", "device-secret")
    store = AgentStateStore(tmp_path / "state.json")
    store.save(AgentState(remote_base_url="http://fake", device_id="dev_1", workspace=str(tmp_path)))
    result = Agent(remote, store, credentials, tmp_path, catalog=catalog).run_once()
    assert result.status == "blocked"
    assert result.last_code == "device_not_compatible"


@pytest.mark.parametrize("field", ["credential_ref", "session_ref"])
def test_agent_state_rejects_raw_secret_refs_on_save_and_load(tmp_path, field):
    path = tmp_path / "state.json"
    store = AgentStateStore(path)
    state = AgentState(device_id="dev_1", **{field: "super-secret-value"})
    with pytest.raises(Exception) as raised:
        store.save(state)
    assert getattr(raised.value, "code", None) == "state_secret_forbidden"
    assert not path.exists()

    path.write_text(
        json.dumps({"device_id": "dev_1", field: "super-secret-value"}), encoding="utf-8"
    )
    with pytest.raises(Exception) as raised:
        store.load()
    assert getattr(raised.value, "code", None) == "state_secret_forbidden"


def test_agent_state_accepts_only_device_credential_store_refs(tmp_path):
    path = tmp_path / "state.json"
    store = AgentStateStore(path)
    store.save(
        AgentState(
            device_id="dev_1",
            credential_ref="device:dev_1:credential",
            session_ref="device:dev_1:session",
        )
    )
    assert store.load().credential_ref == "device:dev_1:credential"
    assert store.load().session_ref == "device:dev_1:session"

    with pytest.raises(Exception) as raised:
        store.save(AgentState(device_id="dev_1", credential_ref="device:dev_2:credential"))
    assert getattr(raised.value, "code", None) == "state_secret_forbidden"
