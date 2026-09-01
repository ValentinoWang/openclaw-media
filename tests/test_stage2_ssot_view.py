from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "agents-results" / "2026-08-15" / "media-c-b-stage-2-content-and-ai-document-routing"


def load_build_module():
    spec = importlib.util.spec_from_file_location("stage2_build_ssot", BUNDLE / "build_ssot.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    original_sys_path = sys.path.copy()
    try:
        sys.path.insert(0, str(BUNDLE))
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_sys_path
    return module


def test_stage2_content_context_contract_and_generated_main_view_stay_aligned() -> None:
    module = load_build_module()
    module.validate_model()
    contract = module.CONTENT_CONTEXT_CONTRACT

    assert {
        (
            route["route_id"],
            route["source_table"],
            route["entity_type"],
            route["canonical_id_field"],
        )
        for route in contract["retrieval_routes"]
    } == {
        ("02A_SourceAssets", "02A_SourceAssets_素材源", "SourceAsset", "asset_id"),
        ("02B_MaterialDeconstructions", "02B_MaterialDeconstructions_素材拆解", "MaterialDeconstruction", "deconstruction_id"),
        ("02C_CreativePatterns", "02C_CreativePatterns_创作模式", "CreativePattern", "pattern_id"),
        ("05B_BusinessOpportunities", "05B_BusinessOpportunities_商务机会", "BusinessOpportunity", "opportunity_id"),
    }
    assert {
        (dossier["dossier_type"], dossier["canonical_capability_id"])
        for dossier in contract["dossier_types"]
    } == {
        ("ExternalResearchBrief", "external_research_brief"),
        ("CommercialBrief", "commercial_brief"),
        ("DecisionBrief", "creation_decision_brief"),
    }
    assert contract["caveats"]["unsafe_configured_url_full_table_exception"]["source"] == "01_近期活动"
    assert contract["caveats"]["account_context_only"] == {
        "source": "06_CreatorProfiles_达人账号档案",
        "general_retrieval_route": False,
    }

    generated = module.main_view().strip() + "\n"
    assert "### 资料检索路线（S2）" in generated
    assert "### 三类真实档案（Growth source）" in generated
    assert "现有检索程序（`retrieval.py`）使用配置地址全表读取" in generated
    assert "不是第五条通用资料路线" in generated
    assert (BUNDLE / ".ssot" / "view-sources" / "00-main.md").read_text(encoding="utf-8") == generated
    assert (BUNDLE / "ssot-development-paths.md").read_text(encoding="utf-8") == generated

    manifest = json.loads((BUNDLE / ".ssot" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["content_context_contract"] == contract


def test_stage2_machine_markdown_has_one_declared_output_surface() -> None:
    machine = BUNDLE / ".ssot"
    manifest = json.loads((machine / "manifest.json").read_text(encoding="utf-8"))

    undeclared_machine_markdown = [
        path.relative_to(machine).as_posix()
        for path in machine.rglob("*.md")
        if path.parent != machine / "view-sources"
    ]
    assert undeclared_machine_markdown == []

    views = manifest["generated_views"]
    assert {view["source"] for view in views} == {
        "view-sources/00-main.md",
        "view-sources/10-topology.md",
        "view-sources/20-execution.md",
        "view-sources/30-acceptance.md",
        "view-sources/40-progress.md",
        "view-sources/40-acceptance-execution.md",
    }
    assert {view["output"] for view in views} == {
        "../ssot-development-paths.md",
        "../generated-views/10-dependency-topology.md",
        "../generated-views/20-execution-governance.md",
        "../generated-views/30-node-contracts-and-acceptance.md",
        "../implementation-progress.md",
        "../generated-views/40-acceptance-execution.md",
    }


def test_stage2_openproblem_is_generated_chinese_view_and_declared_for_snapshot() -> None:
    module = load_build_module()
    generated = module.openproblem_view().strip() + "\n"
    openproblem = (BUNDLE / "openproblem.md").read_text(encoding="utf-8")
    archive = json.loads((BUNDLE / "ssot-archive.json").read_text(encoding="utf-8"))

    assert openproblem == generated
    headings = [line for line in openproblem.splitlines() if line.startswith("#")]
    assert headings
    assert all(re.search(r"[\u3400-\u9fff]", heading) for heading in headings)
    for title in ("已裁决：个人开放范围", "验收边界", "工程映射表"):
        assert any(title in heading for heading in headings)
    assert archive["problem_documents"] == ["openproblem.md"]
    assert "登录布局断言（`assertAuthLayout`）" in openproblem
