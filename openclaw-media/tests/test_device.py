import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

import openclaw_media
from openclaw_media import DeviceRegistry, LocalAgentJob


ACTION = "media.output.review.v1"


def _pair(registry: DeviceRegistry, tenant: str, name: str, now: int = 0):
    code = registry.issue_pair(tenant, name, now=now)
    outcome = registry.redeem_pair(tenant, code, now=now + 1)
    assert outcome.code == "paired"
    assert outcome.device is not None and outcome.credential is not None
    return outcome


def _heartbeat(registry: DeviceRegistry, pair, now: int = 2):
    outcome = registry.heartbeat(
        pair.device.tenant_id,
        pair.credential,
        revision=pair.device.revision,
        now=now,
    )
    assert outcome.code == "heartbeat_ok"
    return outcome


def test_pair_heartbeat_claim_ack_run_result_and_public_contract():
    registry = DeviceRegistry(heartbeat_ttl=20, lease_ttl=10)
    pair = _pair(registry, "tenant-a", "Editing Mac")
    heartbeat = _heartbeat(registry, pair)
    queued = registry.create_job("tenant-a", ACTION).job

    leased = registry.claim(
        "tenant-a", pair.credential, queued.job_id, revision=queued.revision, now=3
    ).job
    assert leased.status == "leased" and leased.device_id == pair.device.device_id
    acknowledged = registry.acknowledge(
        "tenant-a", pair.credential, leased.job_id, revision=leased.revision, now=4
    ).job
    running = registry.start(
        "tenant-a",
        pair.credential,
        acknowledged.job_id,
        revision=acknowledged.revision,
        now=5,
    ).job
    result = registry.complete(
        "tenant-a",
        pair.credential,
        running.job_id,
        revision=running.revision,
        now=6,
    )

    assert result.code == "result_succeeded"
    assert result.job.status == "succeeded"
    assert result.job.revision == 5
    assert registry.complete(
        "tenant-a",
        pair.credential,
        running.job_id,
        revision=running.revision,
        now=6,
    ) == result
    assert "credential" not in json.dumps(heartbeat.model_dump())
    assert pair.credential not in repr(pair)
    with pytest.raises(ValidationError):
        result.job.status = "failed"
    assert LocalAgentJob is openclaw_media.LocalAgentJob
    assert not hasattr(openclaw_media, "Job")


def test_pair_code_expiry_cross_tenant_and_revoke_fail_closed_without_consuming():
    registry = DeviceRegistry(pair_ttl=5)
    code = registry.issue_pair("tenant-a", "Mac", now=10)
    assert registry.redeem_pair("tenant-b", code, now=11).code == "tenant_forbidden"
    pair = registry.redeem_pair("tenant-a", code, now=11)
    assert pair.code == "paired"
    assert registry.redeem_pair("tenant-a", code, now=11).code == "pair_invalid"

    expired = registry.issue_pair("tenant-a", "Other Mac", now=20)
    assert registry.redeem_pair("tenant-a", expired, now=26).code == "pair_expired"
    assert registry.redeem_pair("tenant-b", expired, now=26).code == "tenant_forbidden"

    before = pair.device.model_dump()
    assert registry.revoke("tenant-b", pair.device.device_id).code == "tenant_forbidden"
    assert registry.heartbeat(
        "tenant-a", pair.credential, revision=before["revision"], now=12
    ).code == "heartbeat_ok"
    revoked = registry.revoke("tenant-a", pair.device.device_id)
    assert revoked.code == "revoked" and revoked.device.revision == 2
    assert registry.revoke("tenant-a", pair.device.device_id) == revoked
    assert registry.heartbeat(
        "tenant-a", pair.credential, revision=2, now=13
    ).code == "credential_invalid"


def test_double_claim_stale_write_lease_expiry_and_reclaim_are_atomic():
    registry = DeviceRegistry(heartbeat_ttl=100, lease_ttl=5)
    first = _pair(registry, "tenant-a", "Mac 1")
    second = _pair(registry, "tenant-a", "Mac 2")
    _heartbeat(registry, first)
    _heartbeat(registry, second)
    queued = registry.create_job("tenant-a", ACTION).job

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(
            pool.map(
                lambda credential: registry.claim(
                    "tenant-a",
                    credential,
                    queued.job_id,
                    revision=queued.revision,
                    now=3,
                ),
                (first.credential, second.credential),
            )
        )
    assert sorted(item.code for item in claims) == ["already_claimed", "claimed"]
    leased = next(item.job for item in claims if item.code == "claimed")
    owner = first if leased.device_id == first.device.device_id else second
    reclaimer = second if owner is first else first

    assert registry.acknowledge(
        "tenant-a", owner.credential, leased.job_id, revision=queued.revision, now=4
    ).code == "stale_revision"
    assert registry.acknowledge(
        "tenant-a", owner.credential, leased.job_id, revision=leased.revision, now=9
    ).code == "lease_expired"
    assert registry.get_job("tenant-a", leased.job_id).job == leased

    reclaimed = registry.claim(
        "tenant-a",
        reclaimer.credential,
        leased.job_id,
        revision=leased.revision,
        now=9,
    )
    assert reclaimed.code == "reclaimed"
    assert reclaimed.job.device_id == reclaimer.device.device_id
    assert reclaimed.job.revision == leased.revision + 1
    assert registry.acknowledge(
        "tenant-a",
        owner.credential,
        leased.job_id,
        revision=reclaimed.job.revision,
        now=10,
    ).code == "tenant_forbidden"


def test_wrong_action_cross_tenant_and_expired_heartbeat_never_mutate_job():
    registry = DeviceRegistry(heartbeat_ttl=3, lease_ttl=5)
    owner = _pair(registry, "tenant-a", "Mac")
    foreign = _pair(registry, "tenant-b", "PC")
    _heartbeat(registry, owner)
    _heartbeat(registry, foreign)

    for action in (
        "shell.exec",
        "env.dump",
        "/Users/alice/private.mov",
        "C:\\Users\\alice\\private.mov",
        "media.unknown.v1",
    ):
        outcome = registry.create_job("tenant-a", action)
        assert outcome.code == "wrong_action" and outcome.job is None

    queued = registry.create_job("tenant-a", ACTION).job
    frozen = queued.model_dump()
    assert registry.claim(
        "tenant-b", foreign.credential, queued.job_id, revision=queued.revision, now=3
    ).code == "tenant_forbidden"
    assert registry.get_job("tenant-b", queued.job_id).code == "tenant_forbidden"
    assert registry.get_job("tenant-a", queued.job_id).job.model_dump() == frozen
    assert registry.claim(
        "tenant-a", owner.credential, queued.job_id, revision=queued.revision, now=6
    ).code == "lease_expired"
    assert registry.get_job("tenant-a", queued.job_id).job.model_dump() == frozen

    public_dump = json.dumps(registry.get_job("tenant-a", queued.job_id).model_dump())
    assert "Users" not in public_dump
    assert "HOME" not in public_dump
    assert "shell" not in public_dump
