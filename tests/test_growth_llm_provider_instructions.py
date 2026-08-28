from __future__ import annotations

from selfmedia.growth.knowledge_evidence_contract import KnowledgeEvidenceBundle
from selfmedia.growth.llm_runner import GrowthLLMJsonRunner


def test_growth_provider_instructions_define_editorial_role() -> None:
    captured: dict[str, object] = {}
    settings = object()
    bundle = KnowledgeEvidenceBundle.from_dict(
        {
            "bundle_id": "growth_instruction_test",
            "query": "校园体育内容策略",
            "status": "ready",
            "evidence_items": [
                {
                    "source_url": "https://example.com/research/source-1",
                    "source_type": "web_page",
                    "text_or_summary": "校园体育内容需要明确受众、场景和可验证案例。",
                    "citations": ["https://example.com/research/source-1#summary"],
                    "status": "ready",
                }
            ],
        }
    )

    def fake_provider(
        parts: list[dict[str, str]], settings_arg: object, **kwargs: object
    ) -> dict[str, object]:
        captured["parts"] = parts
        captured["settings"] = settings_arg
        captured["kwargs"] = kwargs
        return {"status": "done", "decision": "manual_review_ready"}

    result = GrowthLLMJsonRunner(provider=fake_provider, settings=settings).run_json(
        task="media_growth_decision",
        prompt="判断是否进入选题。",
        evidence_bundle=bundle,
    )

    assert result["status"] == "done"
    assert captured["settings"] is settings
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    instructions = kwargs["instructions"]
    assert isinstance(instructions, str)
    assert instructions.startswith("你是一名中文内容增长与运营编辑。")
    assert "基于已验证证据的增长判断" in instructions
    assert "输出协议：" in instructions
    assert "只输出一个合法 JSON object" in instructions
    assert "KnowledgeEvidenceBundle evidence_items" in instructions
    assert "JSON 引擎" not in instructions
    assert "JSON engine" not in instructions
