"""Shared Content OS vault fixture for router tests.

Builds a throwaway vault directory (a temp dir laid out like the real
Obsidian vault: ``00_入口与总览/state_transition_rules.yaml`` plus a single
project's ``00_项目总览.md``) so tests exercising the Content OS project
lifecycle/bridge/queue routers don't each hand-roll their own near-identical
copy that can drift from the real frontmatter/rules shape.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from openclaw_app.router.content_os_project_lifecycle import CONTENT_OS_SPEC_VERSION


# The full 6-stage lifecycle, keyed the way state_transition_rules.yaml keys
# its transitions in production. Callers that only need a subset (e.g. the
# tail end of the lifecycle) pass their own `transitions` dict.
ALL_TRANSITIONS: dict[str, dict[str, object]] = {
    "captured_to_planned": {
        "from": "captured",
        "to": "planned",
        "allowed_actor": "cloud_openclaw_or_human",
        "required_evidence": ["01_idea_card.md", "02_project_brief.md", "04_script.md"],
    },
    "planned_to_edit_ready": {
        "from": "planned",
        "to": "edit_ready",
        "allowed_actor": "cloud_openclaw",
        "required_evidence": ["05_storyboard.md", "06_edit_decision_list.json", "result_identity_valid", "selected_editor_backend_result_valid"],
    },
    "edit_ready_to_editing": {
        "from": "edit_ready",
        "to": "editing",
        "allowed_actor": "human",
        "required_evidence": ["human_confirmed_edit_start", "selected_editor_backend_recorded"],
    },
    "editing_to_final_ready": {
        "from": "editing",
        "to": "final_ready",
        "allowed_actor": "human",
        "required_evidence": ["output_video_exists", "output_review_evidence_exists", "human_final_selected"],
    },
    "final_ready_to_published": {
        "from": "final_ready",
        "to": "published",
        "allowed_actor": "human",
        "required_evidence": ["human_published_confirmation"],
    },
}

DEFAULT_PROJECT_STATUSES: list[str] = ["captured", "planned", "edit_ready", "editing", "final_ready", "published"]

DEFAULT_PROJECT_ID = "20260710_测试项目"


def make_content_os_vault(
    *,
    status: str = "captured",
    backend: str = "handoff_pack",
    project_id: str | None = None,
    transitions: dict[str, dict[str, object]] | None = None,
    project_statuses: list[str] | None = None,
    overview_extra: dict[str, object] | None = None,
) -> tuple["tempfile.TemporaryDirectory[str]", Path, str]:
    """Create a vault with one project directory and return (tmpdir, root, project_id).

    ``project_id`` is expected in the fixtures' own ``YYYYMMDD_标题`` shape;
    ``idea_id``, the overview ``title`` and ``updated_at`` are all derived
    from it so a caller only has to pick one string. Pass ``overview_extra``
    to override/add specific frontmatter fields (e.g. a different
    ``next_action``) without losing the rest of the default overview or its
    key order (dict.update keeps an existing key's original position).
    """

    resolved_project_id = project_id or DEFAULT_PROJECT_ID
    date_part, _, title = resolved_project_id.partition("_")
    idea_id = f"idea_{date_part}_001"
    updated_at = f"{date_part[0:4]}-{date_part[4:6]}-{date_part[6:8]}T08:00:00+00:00"

    resolved_transitions = ALL_TRANSITIONS if transitions is None else transitions
    resolved_statuses = list(DEFAULT_PROJECT_STATUSES) if project_statuses is None else project_statuses

    temporary = tempfile.TemporaryDirectory()
    root = Path(temporary.name)
    project_dir = root / "08_内容项目" / resolved_project_id
    project_dir.mkdir(parents=True)

    rules = {
        "spec_version": CONTENT_OS_SPEC_VERSION,
        "project_statuses": resolved_statuses,
        "transitions": resolved_transitions,
    }
    rules_path = root / "00_入口与总览" / "state_transition_rules.yaml"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False), encoding="utf-8")

    overview = {
        "spec_version": CONTENT_OS_SPEC_VERSION,
        "doc_type": "project_overview",
        "project_id": resolved_project_id,
        "idea_id": idea_id,
        "title": title,
        "status": status,
        "project_revision": 1,
        "editor_backend": backend,
        "owner": "小李",
        "next_action": "补全素材",
        "blocked": False,
        "blocked_reason": "",
        "updated_at": updated_at,
    }
    if overview_extra:
        overview.update(overview_extra)

    content = "---\n" + yaml.safe_dump(overview, allow_unicode=True, sort_keys=False).strip() + "\n---\n\n# " + title + "\n"
    (project_dir / "00_项目总览.md").write_text(content, encoding="utf-8")

    return temporary, root, resolved_project_id
