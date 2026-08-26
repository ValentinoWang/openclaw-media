from __future__ import annotations

from types import SimpleNamespace

import pytest

from openclaw_app.services.stage2_external_document import BindingIdentity
from openclaw_app.services.stage2_production_factory import _FeishuOrganizationAdapter


BINDING = BindingIdentity(
    tenant_id="11111111-1111-4111-8111-111111111111",
    binding_id="binding-1",
    binding_generation=3,
    status="active",
)


class FakeService:
    def __init__(self) -> None:
        self.knowledge_base_spaces = [{"space_id": "old", "parent_node_token": "old-parent"}]


def test_binding_target_requires_current_space_and_parent_pair() -> None:
    adapter = _FeishuOrganizationAdapter(
        FakeService(),
        lambda _tenant: {
            "bindingId": "binding-1",
            "generation": 3,
            "spaceId": "space-only",
            "parentNodeToken": "",
        },
    )
    with pytest.raises(RuntimeError, match="incomplete"):
        with adapter._binding_target(BINDING):
            pass


def test_binding_target_rejects_generation_change_before_external_write() -> None:
    adapter = _FeishuOrganizationAdapter(
        FakeService(),
        lambda _tenant: {
            "bindingId": "binding-1",
            "generation": 4,
            "spaceId": "space-1",
            "parentNodeToken": "parent-1",
        },
    )
    with pytest.raises(RuntimeError, match="changed"):
        with adapter._binding_target(BINDING):
            pass


def test_binding_target_is_scoped_and_restores_service_configuration() -> None:
    service = FakeService()
    original = list(service.knowledge_base_spaces)
    adapter = _FeishuOrganizationAdapter(
        service,
        lambda _tenant: {
            "bindingId": "binding-1",
            "generation": 3,
            "spaceId": "space-1",
            "parentNodeToken": "parent-1",
        },
    )
    with adapter._binding_target(BINDING):
        assert service.knowledge_base_spaces == [
            {"space_id": "space-1", "parent_node_token": "parent-1", "pattern": "*"}
        ]
    assert service.knowledge_base_spaces == original
