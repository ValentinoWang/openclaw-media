from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/reconcile_stage2_human_acceptance_log.py"
LEDGER = ROOT / "acceptance/human-acceptance-log.json"
MARKDOWN = ROOT / "acceptance/human-acceptance-log.md"


def load_reconciler():
    spec = importlib.util.spec_from_file_location("stage2_human_acceptance_reconciler", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stage2_ledger_partition_matches_planning_policy_without_digest_rewrite() -> None:
    module = load_reconciler()
    payload = json.loads(LEDGER.read_text(encoding="utf-8"))
    reconciled, markdown = module.reconcile(write=False)

    assert [item["task_id"] for item in reconciled["blocking_entries"]] == [
        "ST2-HUM-SESSION-28D",
        "ST2-HUM-ORG-SCAN",
        "ST2-HUM-LARK-READBACK",
    ]
    assert [item["task_id"] for item in reconciled["non_blocking_entries"]] == [
        "ST2-HUM-LOGIN-FOLD",
        "PR-REL-READBACK",
        "PR-REL-PLANNER",
        "PR-REL-MANIFEST",
    ]
    assert reconciled["source_facts_sha256"] == payload["source_facts_sha256"]
    blocking_view, non_blocking_view = markdown.split("## 非阻塞抽查项", 1)
    assert "| - | ST2-HUM-SESSION-28D |" in blocking_view
    assert "| - | ST2-HUM-ORG-SCAN |" in blocking_view
    assert "| - | ST2-HUM-LARK-READBACK |" in blocking_view
    assert "ST2-HUM-LOGIN-FOLD" not in blocking_view
    assert "| - | ST2-HUM-LOGIN-FOLD |" in non_blocking_view
    assert MARKDOWN.read_text(encoding="utf-8") == markdown


def test_stage2_ledger_check_is_clean() -> None:
    module = load_reconciler()
    expected, markdown = module.reconcile(write=False)
    assert json.loads(LEDGER.read_text(encoding="utf-8")) == expected
    assert MARKDOWN.read_text(encoding="utf-8") == markdown
