#!/usr/bin/env python3
"""Build the phase-2 Media C/B SSOT machine source and generated views."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path

from stage2_model import (
    BATCHES,
    CANDIDATE_IDENTITY_POLICY_OVERRIDES,
    DETERMINISTIC_COMMANDS,
    DAG_VERSION,
    EDGES,
    EXECUTION_ACTOR_OVERRIDES,
    INTERFACE_FREEZE_VERSION,
    NODE_CONTRACT_VERSION,
    NODE_ROLE_OVERRIDES,
    PLAN_VERSION,
    PRODUCT_DECISION_VERSION,
    PRIMARY_EXECUTOR_DEFAULT,
    PRIMARY_EXECUTOR_OPTIONS,
    PROJECTION_RULES,
    PROJECTION_SOURCE_NODES,
    RELEASE_SLICE_BY_NODE,
    SIDE_EFFECT_OVERRIDES,
    SPECS,
    SSOT_SCHEMA_VERSION,
    TRANSPORT_OVERRIDES,
    WAVE_BY_NODE,
    selected_primary_executor,
    selected_primary_wrapper,
)


NODE_ID_RE = re.compile(r"^[A-Z]+[1-9][0-9]*$")


def is_numeric_node(node_id: str) -> bool:
    """Return whether the label is an independently inventoried deliverable."""

    return bool(NODE_ID_RE.fullmatch(node_id))


def artifact_identity(node_id: str) -> str:
    """Give every node a stable artifact identity; only leaves get deliverables."""

    return f"DL-{node_id}" if is_numeric_node(node_id) else f"ART-{node_id}"


BUNDLE = Path(__file__).resolve().parent
PROJECT_ROOT = BUNDLE.parents[2]
SOURCE_ROOT = PROJECT_ROOT.parents[1]
REL_BUNDLE = BUNDLE.relative_to(PROJECT_ROOT).as_posix()
MACHINE = BUNDLE / ".ssot"
NODES_DIR = MACHINE / "nodes"
EDGES_DIR = MACHINE / "edges"
ASSUMPTIONS_DIR = MACHINE / "assumptions"
CONFLICTS_DIR = MACHINE / "conflicts"
EXECUTION_CONTRACTS_DIR = MACHINE / "execution-contracts"
VIEW_SOURCES = MACHINE / "view-sources"
GENERATED_VIEWS = BUNDLE / "generated-views"

PRIMARY_WRAPPER_PATHS = {
    "lw-luna": "/Users/vsiyo/.codex/workers/run-lw-luna.sh",
    "lw-terra": "/Users/vsiyo/.codex/workers/run-lw-terra.sh",
}
L3_WRAPPER = "/Users/vsiyo/.codex/workers/run-l3.sh"
PROJECT_ROOT_TEXT = str(PROJECT_ROOT)
CODEX_EXEC = (
    f"codex exec -C '{PROJECT_ROOT}' "
    "--skip-git-repo-check --sandbox danger-full-access"
)

AUDIT = (
    "/Users/vsiyo/Library/Mobile Documents/iCloud~md~obsidian/Documents/日记/"
    "公共开发集/public/2026-08-15/media-c-b-product-fact-audit/"
    "media-c-b-login-document-organization-audit.md"
)
ATTACHMENT = (
    "/Users/vsiyo/.codex/attachments/63a93708-8bfe-43ce-8dc7-cb079775f3b0/"
    "pasted-text.txt"
)
STRUCTURE_REVIEW = (
    "/Users/vsiyo/.codex/attachments/61fef357-7ee9-4a1a-a348-06db749a7466/"
    "pasted-text.txt"
)
LATEST_REVIEW = (
    "/Users/vsiyo/.codex/attachments/7ebe320f-6551-4294-8d1c-2b452a9b6b2b/"
    "pasted-text.txt"
)
STAGE1_BUNDLE = SOURCE_ROOT / (
    "agents-results/2026-08-15/"
    "media-c-b-stage-1-identity-and-organization-onboarding"
)
STAGE1_MAIN = STAGE1_BUNDLE / "ssot-development-paths.md"
STAGE1_PROGRESS = STAGE1_BUNDLE / "implementation-progress.md"
STAGE1_MANIFEST = STAGE1_BUNDLE / ".ssot/manifest.json"
STAGE1_K5 = STAGE1_BUNDLE / ".ssot/nodes/K5.json"
STAGE1_I9 = STAGE1_BUNDLE / ".ssot/nodes/I9.json"
STAGE1_C1 = STAGE1_BUNDLE / ".ssot/nodes/C1.json"
STAGE1_C3 = STAGE1_BUNDLE / ".ssot/nodes/C3.json"
STAGE1_DC2 = STAGE1_BUNDLE / ".ssot/nodes/DC2.json"

HASHES = {
    "audit": "d5dad457861e413ff3963da568870be907495de50c33486810fa3dbdc0d92f98",
    "attachment": "a293eb32e09589ae2e60fd07362f20ce296b70725f55ad9368c6bc63e673f8b8",
    "structure_review": "3ffc4363c735a1ca2bed7b393e48516b4aa9a5494b1f9b30f952e8eff65ab6f5",
    "latest_review": "97000cc86e80993997153e0fb193ee877daea85c5695a60cf1645bf40596d471",
    "stage1_main": "558b40b11c399fd6f5d8b9e766562a07e7ecd8968c83df9a07a60496112659e6",
    "stage1_progress": "02c1cac2205c0115e3a3d34883175650238ad9d4f2f4a5ae837143222e45447c",
    "stage1_manifest": "98baf1460664fedad729aeccd3f384d05c297c464ed689964caf628f1681f2cf",
    "stage1_k5": "76c4b2b2584333f3ceb3f43731ecbb749f75317018ead39f11729dff165f87d9",
    "stage1_i9": "d99c5697e2bb4a1c7853e2d3695852eda11a8726301b2cd6cfc805e87f3a6a28",
    "stage1_c1": "26bf849657405fed887785e52665b97f2a5ae248e0591f7365f8d72e31c5f450",
    "stage1_c3": "7b3ebfc4653099da67694396ec3374ff697b8dd50b19fc9575cac31b271488b5",
    "stage1_dc2": "e8160365df3008a9c7124abe419255821890aa9e57f997a220cb77b99d38b448",
}
OBSERVED_AT = "2026-08-15T20:37:42+08:00"
CURRENT_FACT_OBSERVED_AT = "2026-08-31T23:15:51+08:00"
CURRENT_MAIN_SHA = "b267f730ad184991305ffbcdddf39f292ca6f3c5"
CURRENT_STAGE2_ORIGIN_COMMIT = "0228256058a1d7c0de4986a943de5c96f445ee2f"
CURRENT_STAGE2_SERVICE_COUNT = 16
CURRENT_STAGE2_TEST_COUNT = 19
CURRENT_STAGE2_TEST_FUNCTION_COUNT = 167
IMPLEMENTATION_OBSERVATIONS = {
    "source-baseline": f"当前 main 为 {CURRENT_MAIN_SHA}；Stage-2 起始提交为 {CURRENT_STAGE2_ORIGIN_COMMIT}。候选分支 codex/stage2-release-20260818 已不存在。",
    "S1-S5/T1": f"已落地上下文、资料路由、唯一写入路由、成果登记/回读和能力副作用合同；主线有 {CURRENT_STAGE2_SERVICE_COUNT} 个 stage2 服务文件，Stage-2 聚焦测试为 {CURRENT_STAGE2_TEST_COUNT} 个文件、{CURRENT_STAGE2_TEST_FUNCTION_COUNT} 个测试函数。",
    "C1-C5": "已落地个人资料、研究简报、决策简报、个人上下文和个人内部成果写入流程。",
    "O1-O4": "已落地组织资料、按 Binding 写入、成果绑定、飞书回读和网页只读镜像流程。",
    "storage-topology": "三分叉存储：PostgreSQL canonical 迁移 37 个（其中包括 owned_media_accounts、tracks、publishing_packages）；SQLitePersonalContentStore 持久化个人成果；account_memory 为文件系统 JSON，位于 ~/.openclaw/media_vault/account_memory/<account_id>/。因此存在两道 join 断点，而不是 SQLite 与 Postgres 的单一断点。",
    "frontend-scope": "当前生产入口是 src/media/main.tsx -> MediaStudioApp.tsx；旧 MediaApp.tsx 已由 ea98ca3b 从源码删除。当前机器源清点为 mediaPageStructureManifest 24 面；studioOrdinaryRoutes 为 14 条（/today、/studio、/campaigns、/business、/desk、/overview、/assets、/decisions、/publishing、/reviews、/media-agent、/archives、/usage-billing、/invites），另有 studioTrackRoutes。两组机器路由全量向个人人格开放，个人/组织/管理员路由授权由统一策略、严格会话 routeGrants 和 MediaStudioRoutePolicy 共同约束。",
    "entry-state": "登录入口状态已落地为 GET /openclaw/auth/entry-state?mode=，响应 media_auth_entry_state_v1，覆盖 matched、none、expired、mismatched 四态并有测试；它与工作台路由授权是两个不同合同。",
    "route-grants": "当前 main 的 media_web_business_pages_v2 严格 schema 已包含 routeGrants，并由服务端生成、客户端校验和路由矩阵消费；这已是源码事实，但与早期‘不得增加 routeGrants’的已接受决定存在待处理合同冲突，不能提升正式节点状态。",
    "font-scope": "DS-02/DS-26 已在 main 落地：mediaDesignTokens.css 定义 --mg-text-4xl，mediaFonts.css 和本地 WOFF2 提供 DM Sans/Noto Sans SC，Google Fonts 依赖有门禁；仍需按实际部署弱网证据验收。",
    "frontend-retirement": "MediaApp.tsx 已删除且 main.tsx 无旧壳 import；该设计债务不再是当前待办。",
    "C6-C7": "当前源码观察未形成网页端个人正文修订和平台版本/发布包完整正式验收。",
    "O5": "当前只有注入式/测试形态，未形成真实飞书编辑后再回读的外部验收。",
    "C8/O6/S/C/DA/DB/DC": "属于汇合、候选、发布或独立验收节点，当前未形成正式接受结果。",
}
VERSIONS = f"{PLAN_VERSION}/{DAG_VERSION}/{INTERFACE_FREEZE_VERSION}/{NODE_CONTRACT_VERSION}"
UPSTREAM_PROJECTIONS = {
    "F1": "C1",
    "F2": "C3",
    "F3": "DC2",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def write_json(path: Path, payload: object) -> None:
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def clear_machine_fragments() -> None:
    """Remove only generated JSON fragments before a deterministic rebuild."""
    for directory in (
        NODES_DIR,
        EDGES_DIR,
        ASSUMPTIONS_DIR,
        CONFLICTS_DIR,
        EXECUTION_CONTRACTS_DIR,
    ):
        for path in directory.glob("*.json"):
            path.unlink()


def cell(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, list):
        if not value:
            return "n/a"
        value = ", ".join(str(item) for item in value)
    text = str(value).replace("\n", "<br>").replace("|", "/")
    return text if text else "n/a"


def table(headers: list[str], rows: list[list[object]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(cell(item) for item in row) + " |" for row in rows)
    return "\n".join(lines)


def verify_source_hashes() -> None:
    paths = {
        "audit": Path(AUDIT),
        "attachment": Path(ATTACHMENT),
        "structure_review": Path(STRUCTURE_REVIEW),
        "latest_review": Path(LATEST_REVIEW),
        "stage1_main": STAGE1_MAIN,
        "stage1_progress": STAGE1_PROGRESS,
        "stage1_manifest": STAGE1_MANIFEST,
        "stage1_k5": STAGE1_K5,
        "stage1_i9": STAGE1_I9,
        "stage1_c1": STAGE1_C1,
        "stage1_c3": STAGE1_C3,
        "stage1_dc2": STAGE1_DC2,
    }
    failures = []
    for key, path in paths.items():
        if not path.is_file():
            failures.append(f"missing {key}: {path}")
            continue
        actual = sha256(path)
        if actual != HASHES[key]:
            failures.append(f"hash drift {key}: expected {HASHES[key]}, got {actual}")
    if failures:
        raise RuntimeError("; ".join(failures))


def worker_registration(
    node_id: str,
    task: str,
    level: str,
    dispatch: str,
    *,
    executor: str | None = None,
) -> dict[str, object]:
    """Build the auditable registration used only by real Codex leaf work."""

    selected = executor or PRIMARY_EXECUTOR_DEFAULT
    wrapper = PRIMARY_WRAPPER_PATHS.get(selected, L3_WRAPPER)
    worker_level = "LW" if selected in PRIMARY_EXECUTOR_OPTIONS else level
    return {
        "worker_level": worker_level,
        "wrapper": wrapper,
        "wrapper_entrypoint": "exec codex exec",
        "project_root": PROJECT_ROOT_TEXT,
        "invocation": CODEX_EXEC,
        "sandbox": "danger-full-access",
        "sandbox_authority": "writable sandbox",
        "runtime_profile": "implementation-runner",
        "runtime_profile_available": False,
        "launch_authorized": False,
        "profile_authority": "stage1 G1 accepted capability receipt",
        "merge_protocol_authority": "stage1 M1 accepted deterministic patch protocol",
        "task_argument": task,
        "return_path": f"{REL_BUNDLE}/worker-returns/{node_id}.json",
        "prompt_path": str(BUNDLE / "prompts" / f"{node_id}.txt"),
        "log_path": str(BUNDLE / "worker-logs" / f"{node_id}.log"),
        "prompt_sha256": "capture-before-launch",
        "launch_barrier": "all wave PIDs registered before first wait",
        "prompt_cleanup": "delete after exit evidence registration",
        "runtime_handle_cleanup": "release after exit evidence registration",
        "codex_transcript_retention": "preserve ~/.codex/sessions and ~/.codex/archived_sessions",
        "dispatch_state": dispatch,
    }


def evidence_identity(node_id: str) -> dict[str, object]:
    if node_id == "A":
        return {
            "evidence_level": "source",
            "source_revision": "user-request-stage2-2026-08-15",
            "artifact_hashes": [
                f"sha256:{HASHES['attachment']}",
                f"sha256:{HASHES['structure_review']}",
                f"sha256:{HASHES['latest_review']}",
            ],
            "environment_identity": "current Codex task and three local attachments",
            "runtime_release_id": "n/a",
            "actor_role": "user and planning authority",
            "account_or_tenant": "n/a",
            "device_or_browser": "n/a",
            "mock_or_fixture": False,
            "observed_at": OBSERVED_AT,
            "acceptance_contract": "Phase-2 SSOT creation charter v2",
        }
    if node_id == "A1":
        return {
            "evidence_level": "source",
            "source_revision": "audit-stage1-hash-baseline-2026-08-15",
            "artifact_hashes": [
                f"sha256:{HASHES['audit']}",
                f"sha256:{HASHES['latest_review']}",
                f"sha256:{HASHES['stage1_main']}",
                f"sha256:{HASHES['stage1_progress']}",
                f"sha256:{HASHES['stage1_manifest']}",
                f"sha256:{HASHES['stage1_k5']}",
                f"sha256:{HASHES['stage1_i9']}",
                f"sha256:{HASHES['stage1_c1']}",
                f"sha256:{HASHES['stage1_c3']}",
                f"sha256:{HASHES['stage1_dc2']}",
            ],
            "environment_identity": "local source files; non-Git project root",
            "runtime_release_id": "n/a",
            "actor_role": "main orchestrator read-only",
            "account_or_tenant": "redacted / not read",
            "device_or_browser": "n/a",
            "mock_or_fixture": False,
            "observed_at": OBSERVED_AT,
            "acceptance_contract": "Phase-2 source baseline and cross-stage handoff v3",
        }
    return {
        "evidence_level": "source",
        "source_revision": "user-approved-three-stage-plan-2026-08-15",
        "artifact_hashes": [
            f"sha256:{HASHES['attachment']}",
            f"sha256:{HASHES['structure_review']}",
            f"sha256:{HASHES['audit']}",
        ],
        "environment_identity": "current Codex task and declared input files",
        "runtime_release_id": "n/a",
        "actor_role": "user and product decision authority",
        "account_or_tenant": "n/a",
        "device_or_browser": "n/a",
        "mock_or_fixture": False,
        "observed_at": OBSERVED_AT,
        "acceptance_contract": "Phase-2 product decisions v2",
    }


incoming: dict[str, list[str]] = defaultdict(list)
outgoing: dict[str, list[str]] = defaultdict(list)
for source, target, _ in EDGES:
    incoming[target].append(source)
    outgoing[source].append(target)


def _node_role(node_id: str, work_kind: str) -> str:
    if node_id in NODE_ROLE_OVERRIDES:
        return NODE_ROLE_OVERRIDES[node_id]
    if work_kind == "charter":
        return "charter"
    if work_kind == "convergence":
        return "convergence"
    if work_kind == "release-decision":
        return "release-decision"
    if work_kind == "validation":
        return "acceptance-gate"
    return "leaf"


def _node_actor(
    node_id: str,
    item: dict[str, object],
    role: str,
    transport: str | None,
    terminal: bool,
) -> str:
    if node_id in EXECUTION_ACTOR_OVERRIDES:
        configured = EXECUTION_ACTOR_OVERRIDES[node_id]
        # Historical records retain a no-retroactive-worker transport. The
        # execution actor is therefore the archival orchestrator; the
        # original approval authority remains explicit in the node contract.
        if transport == "historical-unregistered":
            return "orchestrator"
        return configured
    if transport == "historical-unregistered":
        return "orchestrator"
    if transport in {"deterministic-local", "automatic-projection"}:
        return "orchestrator"
    if transport == "external-manual":
        return "human"
    if terminal:
        return "human" if role in {"charter", "release-decision"} else "orchestrator"
    if role in {"convergence", "acceptance-gate", "release-decision", "charter"}:
        return "orchestrator"
    if item.get("work_kind") == "decision-acceptance":
        return "human"
    return "codex"


def _node_side_effect(node_id: str, item: dict[str, object]) -> str:
    if node_id in SIDE_EFFECT_OVERRIDES:
        return SIDE_EFFECT_OVERRIDES[node_id]
    return "none"


def _node_candidate_policy(node_id: str, role: str) -> str:
    if node_id in CANDIDATE_IDENTITY_POLICY_OVERRIDES:
        return CANDIDATE_IDENTITY_POLICY_OVERRIDES[node_id]
    return "freezes" if role in {"convergence", "acceptance-gate", "release-decision"} else "none"


def _default_attempt_policy(executor: str, wrapper: str) -> dict[str, object]:
    return {
        "initial_executor": executor,
        "initial_wrapper": wrapper,
        "retry_executor": executor,
        "retry_wrapper": wrapper,
        "primary_retry_limit": 1,
        "l3_executor": "l3",
        "l3_wrapper": "run-l3.sh",
        "l3_escalation_limit": 1,
        "retry_failure_origins": [
            "environment", "app-server", "browser", "database",
            "test-infrastructure", "provider-network", "provider-transport",
            "worker-transport",
        ],
        "l3_failure_origins": ["product-behavior", "implementation", "architecture-complexity"],
        "automatic_executor_switch": False,
    }


def _acceptance_commands(node_id: str, item: dict[str, object]) -> list[str]:
    if node_id in DETERMINISTIC_COMMANDS:
        return [str(DETERMINISTIC_COMMANDS[node_id])]
    return [f"python3 -c 'print(\"acceptance {node_id}\")'"]


def _zero_process_registration(
    node_id: str,
    item: dict[str, object],
    transport: str,
    dispatch: str,
) -> dict[str, object]:
    if transport == "external-manual":
        return {
            "executor": str(item["acceptance_authority"]),
            "manual_owner": str(item["acceptance_authority"]),
            "task_argument": str(item["task"]),
            "return_path": f"{REL_BUNDLE}/manual-receipts/{node_id}.json",
            "dispatch_state": dispatch,
            "note": "manual prerequisite; zero Codex processes",
        }
    if transport == "deterministic-local":
        return {
            "executor": "outer orchestrator",
            "project_root": PROJECT_ROOT_TEXT,
            "command": str(DETERMINISTIC_COMMANDS.get(node_id, "python3 -m pytest -q")),
            "task_argument": str(item["task"]),
            "return_path": f"{REL_BUNDLE}/deterministic-receipts/{node_id}.json",
            "determinism_key": f"stage2:{node_id}:v{PLAN_VERSION}",
            "dispatch_state": dispatch,
            "note": "deterministic local execution; zero Codex processes",
        }
    source_nodes = PROJECTION_SOURCE_NODES.get(
        node_id,
        [f"stage2:{source}" for source in sorted(incoming[node_id])],
    )
    projection_rule = PROJECTION_RULES.get(
        node_id,
        "只汇合已接受输入并投影节点状态；不启动 Codex 进程、不产生外部副作用。",
    )
    return {
        "executor": "SSOT state projector",
        "source_nodes": source_nodes,
        "projection_rule": projection_rule,
        "task_argument": str(item["task"]),
        "return_path": f"{REL_BUNDLE}/projections/{node_id}.json",
        "dispatch_state": dispatch,
        "note": "automatic state projection; zero Codex processes",
    }


NODES: dict[str, dict[str, object]] = {}
for node_id, item in SPECS.items():
    terminal = item["execution_state"] in {"IMPLEMENTED", "VERIFIED", "ACCEPTED"}
    role = _node_role(node_id, str(item["work_kind"]))
    if node_id in {"A", "A1", "K"}:
        transport: str | None = "historical-unregistered"
    elif node_id in TRANSPORT_OVERRIDES:
        transport = TRANSPORT_OVERRIDES[node_id]
    elif role in {"convergence", "acceptance-gate", "release-decision", "charter"}:
        transport = None
    else:
        transport = "external-codex-exec"
    dispatch = "EXITED" if terminal else "NOT_STARTED" if item["execution_state"] == "READY" else "BLOCKED"
    actor = _node_actor(node_id, item, role, transport, terminal)

    if transport == "historical-unregistered":
        registration: dict[str, object] | None = {"note": "no retroactive worker claim"}
    elif transport in {"external-manual", "deterministic-local", "automatic-projection"}:
        registration = _zero_process_registration(node_id, item, transport, dispatch)
    elif transport == "external-codex-exec":
        executor = selected_primary_executor(node_id)
        registration = worker_registration(node_id, str(item["task"]), str(item["worker_level"]), dispatch, executor=executor)
    else:
        registration = None

    decision_refs = (
        [{"semantic_key": "media.stage2.product-decisions", "version": PRODUCT_DECISION_VERSION}]
        if item["consumes_decision"]
        else []
    )
    deliverable_id = f"DL-{node_id}" if role == "leaf" and is_numeric_node(node_id) else None
    read_set = [f"artifact:{artifact_identity(source)}" for source in sorted(incoming[node_id])]
    if not read_set:
        read_set = [f"contract:{item['semantic_key']}" ]
    write_prefix = "evidence" if item["write_authority"] == "evidence-only" else "artifact"
    resource_claims: list[dict[str, object]] = [
        {"resource_id": f"node:{node_id}", "mode": "W", "isolation_key": f"node:{node_id}"}
    ]
    release_id = RELEASE_SLICE_BY_NODE[node_id]
    candidate_policy = _node_candidate_policy(node_id, role)
    if candidate_policy != "none":
        mode = "W" if candidate_policy == "freezes" else "R"
        resource_claims.append({"resource_id": f"candidate:{release_id}", "mode": mode, "isolation_key": f"candidate:{release_id}"})
    node: dict[str, object] = {
        "node_id": node_id,
        "semantic_key": item["semantic_key"],
        "stage": item["stage"],
        "work_kind": item["work_kind"],
        "domain_lane": item["domain_lane"],
        "execution_state": item["execution_state"],
        "decision_state": "ACCEPTED" if node_id == "K" else "NOT_APPLICABLE",
        "decision_version": PRODUCT_DECISION_VERSION if node_id == "K" else None,
        "readiness_mode": "FORMAL",
        "hard_dependencies": sorted(incoming[node_id]),
        "soft_dependencies": [],
        "assumption_ids": [],
        "decision_refs": decision_refs,
        "invalidation_keys": [f"{item['semantic_key']}.v{PLAN_VERSION}"],
        "write_authority": item["write_authority"],
        "acceptance_authority": item["acceptance_authority"],
        "unlocks": sorted(outgoing[node_id]),
        "worker_transport": transport,
        "worker_registration": registration,
        "description": item["dod"],
        "node_role": role,
        "execution_actor": actor,
        "execution_contract_ref": f"{node_id}.json",
        "execution_contract_sha256": None,
        "side_effect_class": _node_side_effect(node_id, item),
        "candidate_identity_policy": candidate_policy,
        "deliverable_ids": [deliverable_id] if deliverable_id else [],
        "produced_artifact_ids": [artifact_identity(node_id)],
        "consumed_artifact_ids": [],
        "read_set": read_set,
        "write_set": [f"{write_prefix}:{node_id}"],
        "resource_claims": resource_claims,
        "actor_pool": {
            "codex": "codex-primary",
            "human": "human-authority",
            "external-system": "external-acceptance",
            "orchestrator": "orchestrator",
        }[actor],
        "acceptance_commands": _acceptance_commands(node_id, item),
        "evidence_outputs": [f"{REL_BUNDLE}/validation/{node_id}-return.json"],
        "release_slice": release_id,
        "wave_id": WAVE_BY_NODE[node_id],
    }
    if actor == "orchestrator" and node.get("write_set"):
        node["main_thread_write_exception"] = {
            "reason": (
                "历史编排节点只生成或投影自身独占的 SSOT 记录；主线程不直接修改业务源码，"
                "也不写入其他节点的共享事实。"
            ),
            "approved_by": "user and planning authority",
            "write_set": list(node["write_set"]),
        }
    if actor == "codex" and transport == "external-codex-exec":
        executor = selected_primary_executor(node_id)
        wrapper = selected_primary_wrapper(node_id)
        node.update(
            {
                "executor_route": executor,
                "primary_executor": executor,
                "primary_wrapper": wrapper,
                "runtime_profile_requirement": "implementation-runner",
                "executor_attempt_policy": _default_attempt_policy(executor, wrapper),
            }
        )
    if terminal:
        node["evidence_identity"] = evidence_identity(node_id)
    if node_id == "K":
        node["decision_record"] = {
            "approved_value": {
                "ai_execution_context": "server session plus Membership plus Binding plus capability identity",
                "client_authority_boundary": "client-supplied tenant, Binding and body authority are never authorization facts",
                "personal_body_authority": "personal_web/internal; Web is the only editor authority",
                "organization_body_authority": "organization_lark/lark; Feishu Docx is the only editor authority",
                "writer_routing": "phase 1 I9 first closes every legacy AI document entry and API; phase 2 then atomically replaces that fail-closed state with the one WriterRouter",
                "artifact_closure": "write, artifact registration and required readback must all succeed before publish success",
                "tenant_data_scope": "all context sources, including 01 recent activity, use the same tenant boundary",
                "capability_side_effects": "server registry declares read sets and document side effects; read-only capabilities write nothing",
                "cutover_policy": "no long-lived dual authority, dual writers, legacy writer path, implicit fallback or global Feishu credential fallback; authority-preserving allowlists, release gates, kill switches and external-write stops are allowed",
                "stage3_exclusions": "full role matrix, approval, seats, procurement, invoices, migration, complex deletion and business analytics",
                "cross_stage_gates": "stage1 C1 unlocks shared/personal work, C3 unlocks organization work and the exclusive WriterRouter, DC2 gates the unique phase2 candidate",
                "session_envelope_boundary": "do not add routeGrants or page permissions to parseMediaSessionEnvelope; keep media_web_business_pages_v2 strict response shape unchanged",
                "entry_state_authority": "independent read-only entry-state API returns server-projected role, workspaceMode, bodyAuthority, defaultRoute, route grants and action grants",
                "entry_state_contract": "new API contract must be versioned and strict in OpenAPI/client types; exact path is frozen by B after bounded source discovery, with 401/403/409 semantics and no session envelope change",
                "route_authorization_axes": "role selects shell; workspaceMode/bodyAuthority select content authority; entry-state route/action grants select visible and executable UI; backend authorization remains final",
                "ordinary_ia_entrypoint": "MediaStudioApp is the current mounted entry; MediaApp is legacy until an entrypoint census proves otherwise. Do not delete the legacy IA before route ownership and deep-link behavior are recorded.",
                "font_delivery": "self-host DM Sans as full WOFF2; serve Noto Sans SC through unicode-range slices or a curated common-glyph subset; preload only Latin subset and keep a local fallback chain",
                "font_weight_policy": "load every used weight including 600; remove 800/850 visual dependence, map Chinese headings to available weights, set Chinese or mixed headings letter-spacing to 0 and reserve negative tracking for pure Latin/numeric display",
            },
            "approval_authority": "user",
            "approval_evidence": "User requested the phase-2 SSOT, explicitly resolved the session-envelope conflict in favor of an independent read-only entry-state API, and accepted the self-hosted font, sliced Chinese subset, and weight/tracking constraints",
            "approved_at": CURRENT_FACT_OBSERVED_AT,
        }
    NODES[node_id] = node

for node_id, node in NODES.items():
    node["consumed_artifact_ids"] = [artifact_identity(source) for source in sorted(incoming[node_id])]


EDGE_RECORDS: list[dict[str, object]] = []
for index, (source, target, scope) in enumerate(EDGES, 1):
    edge_id = f"E-{index:03d}-{source}-{target}"
    source_node = NODES[source]
    target_node = NODES[target]
    source_candidate = source_node.get("candidate_identity_policy") != "none"
    target_candidate = target_node.get("candidate_identity_policy") != "none"
    if source_candidate and target_candidate:
        reason_code = "candidate-identity"
        resource_ids = [f"candidate:{RELEASE_SLICE_BY_NODE[target]}"]
    elif source_node.get("work_kind") in {"decision-acceptance", "contract-assembly", "acceptance-design", "contract-compile"}:
        reason_code = "contract-dependency"
        resource_ids = []
    elif target_node.get("node_role") in {"convergence", "acceptance-gate", "release-decision"}:
        reason_code = "acceptance-dependency"
        resource_ids = []
    else:
        reason_code = "data-dependency"
        resource_ids = []
    transferred = [artifact_identity(source)]
    EDGE_RECORDS.append(
        {
            "edge_id": edge_id,
            "from": source,
            "to": target,
            "dependency_type": "hard",
            "dependency_scope": scope,
            "required_state": "ACCEPTED",
            "assumption_ids": [],
            "invalidation_keys": [f"edge.{source.lower()}.{target.lower()}.v{PLAN_VERSION}"],
            "transferred_input": str(SPECS[source]["output"]),
            "gate_evidence": str(SPECS[source]["acceptance"]),
            "reason_code": reason_code,
            "transferred_artifact_ids": transferred,
            "resource_ids": resource_ids,
            "necessity_proof": (
                f"{target} consumes the explicitly produced artifact {transferred[0]}"
                if reason_code != "candidate-identity"
                else f"{target} must retain the immutable {resource_ids[0]} identity from {source}"
            ),
        }
    )


def numeric_nodes() -> list[str]:
    return [node_id for node_id in NODES if re.fullmatch(r"[A-Z]+[1-9][0-9]*", node_id)]


def write_region(node_id: str) -> str:
    if node_id == "A1":
        return str(BUNDLE / "source-notes.md")
    if node_id in {"F1", "F2", "F3"}:
        return str(BUNDLE / "worker-returns" / f"{node_id}.json")
    if node_id in {"O5", "DB", "DC"}:
        return str(BUNDLE / "evidence" / node_id)
    if node_id in {"C8", "O6"}:
        return str(BUNDLE / "worker-returns" / f"{node_id}.json")
    return str(PROJECT_ROOT / ".codex-work" / f"stage2-{node_id.lower()}")


DELIVERABLES = [
    [
        f"DL-{node_id}",
        BATCHES[node_id],
        SPECS[node_id]["output"],
        write_region(node_id),
        cell(NODES[node_id]["hard_dependencies"]),
        "independent",
        "none",
        node_id,
        "n/a",
    ]
    for node_id in numeric_nodes()
]


def longest_path() -> int:
    memo: dict[str, int] = {}

    def length(node_id: str) -> int:
        if node_id in memo:
            return memo[node_id]
        children = outgoing[node_id]
        memo[node_id] = 1 if not children else 1 + max(length(child) for child in children)
        return memo[node_id]

    return max(length(node_id) for node_id in NODES)


def guard_for(node_id: str) -> str:
    if node_id in {"A", "A1", "K"}:
        return "G-DOC"
    if node_id.startswith("F"):
        return "G-UPSTREAM"
    if node_id in {"O2", "O3", "O4", "O5", "O6"}:
        return "G-FEISHU"
    if node_id in {"DA", "DB"}:
        return "G-RELEASE"
    if node_id == "DC":
        return "G-ZERO"
    return "G-PHASE2"


def state_reason(node_id: str) -> str:
    state = str(NODES[node_id]["execution_state"])
    if state == "ACCEPTED":
        return "n/a"
    upstream = {"F1": "第一阶段 C1 仍为 BLOCKED", "F2": "第一阶段 C3 仍为 BLOCKED", "F3": "第一阶段 DC2 仍为 BLOCKED"}
    if node_id in upstream:
        return upstream[node_id]
    deps = [dep for dep in incoming[node_id] if NODES[dep]["execution_state"] != "ACCEPTED"]
    return "等待 " + ", ".join(deps) + " ACCEPTED" if deps else "尚未进入执行波次"


def current_evidence_row(node_id: str) -> list[object]:
    if node_id == "A":
        return [
            "EV-A-CURRENT", "A", "source", "user-request-stage2-structure-v2-2026-08-15",
            ", ".join([HASHES["attachment"], HASHES["structure_review"], HASHES["latest_review"]]),
            "current Codex task and three local attachments", "n/a", "user and planning authority", "n/a", "n/a",
            "false", OBSERVED_AT, "Phase-2 SSOT creation charter v2",
        ]
    if node_id == "A1":
        hashes = ", ".join([
            HASHES["audit"], HASHES["structure_review"], HASHES["latest_review"],
            HASHES["stage1_main"], HASHES["stage1_progress"], HASHES["stage1_manifest"],
            HASHES["stage1_k5"], HASHES["stage1_i9"], HASHES["stage1_c1"],
            HASHES["stage1_c3"], HASHES["stage1_dc2"],
        ])
        return [
            "EV-A1-CURRENT", "A1", "source", "audit-stage1-hash-baseline-2026-08-15", hashes,
            "local source files; non-Git project root", "n/a", "main orchestrator read-only", "n/a", "n/a",
            "false", OBSERVED_AT, "Phase-2 source baseline and cross-stage handoff v3",
        ]
    if node_id == "K":
        return [
            "EV-K-CURRENT", "K", "source", "user-approved-three-stage-plan-2026-08-15",
            ", ".join([HASHES["attachment"], HASHES["structure_review"], HASHES["audit"]]), "current Codex task", "n/a",
            "user and product decision authority", "n/a", "n/a", "false", OBSERVED_AT,
            "Phase-2 product decisions v2",
        ]
    if node_id.startswith("F"):
        source_hash_key = {"F1": "stage1_c1", "F2": "stage1_c3", "F3": "stage1_dc2"}[node_id]
        projection_hashes = [HASHES["stage1_manifest"], HASHES[source_hash_key]]
        if node_id == "F1":
            projection_hashes.extend([HASHES["stage1_k5"], HASHES["stage1_i9"]])
        return [
            f"EV-{node_id}-CURRENT", node_id, "source", "stage1-projection-pending", ", ".join(projection_hashes),
            "stage1 machine source; zero-write projection", "n/a", "pending upstream acceptance owner", "n/a", "n/a",
            "pending", "pending", SPECS[node_id]["acceptance"],
        ]
    return [
        f"EV-{node_id}-CURRENT", node_id, "source", "phase2-plan-v2", "pending",
        "planned isolated candidate", "n/a", "pending assigned worker", "n/a", "n/a", "pending", "pending",
        SPECS[node_id]["acceptance"],
    ]


def main_view() -> str:
    return f"""---
ARTIFACT_CLASS: ssot-development
APPLICABILITY_DECISION: ssot
GOVERNANCE_REASON: "用户明确要求把跨阶段身份门禁、个人内容、组织飞书正文、人工智能上下文与真实外部系统验收拆成持久的第二阶段 SSOT"
SSOT_DEPTH: L2
TARGET_EVIDENCE_LEVEL: physical-device/external-system
PLAN_VERSION: {PLAN_VERSION}
DAG_VERSION: {DAG_VERSION}
INTERFACE_FREEZE_VERSION: {INTERFACE_FREEZE_VERSION}
NODE_CONTRACT_VERSION: {NODE_CONTRACT_VERSION}
SSOT_SCHEMA_VERSION: {SSOT_SCHEMA_VERSION}
SSOT_PLANNING_COMPILER: .ssot/planning-compiler.json
SSOT_MACHINE_SOURCE: .ssot/manifest.json
---

# 自媒体创作平台第二阶段 SSOT：内容生产与人工智能文档分流

## 1. 业务结论与范围

### 术语说明

- **人工智能执行上下文（`AIExecutionContext`）**：服务端根据当前会话、成员关系、组织绑定和能力编号生成的可信任务范围。它决定本次任务属于谁、可读哪些资料以及正文写到哪里。
- **组织绑定（`Binding`）**：第一阶段建立的服务端事实，用于确定组织、飞书应用凭据世代、知识库空间和父节点。浏览器不能自行指定或覆盖它。
- **正文权威**：用户真正编辑正文的位置。个人正文以网页端（Web）内部成果为权威；组织正文以当前组织绑定下的飞书文档为权威。
- **写入路由器（`WriterRouter`）**：所有会产生文档的能力必须经过的唯一服务端入口。它按可信上下文选择个人内部成果或组织飞书文档。
- **成果回读**：写入后重新读取成果、正文版本和绑定身份，证明用户看到的结果与实际权威位置一致。
- **入口状态（`entry-state`）**：独立的只读接口返回当前会话可见页面、可执行动作和默认入口。它不是会话信封的一部分，也不能替代服务端最终授权。
- **路由授权**：决定某个页面是否显示、能否进入以及页面内哪些动作可执行；它与正文权威是两个不同维度。

本阶段交付两条互斥但共享合同的产品闭环：

1. 个人创作者从个人资料、研究简报和决策简报进入人工智能创作，把正文写入个人内部成果，在网页端编辑和保存修订，再生成平台版本与发布包。
2. 组织创作者从当前组织资料和品牌约束进入人工智能创作，按当前会话解析出的组织绑定写入飞书文档；网页端只展示回读镜像，用户在飞书编辑后可以再次回读新版本。
3. 两条路径共享同一套服务端上下文、资料路由、写入路由、成果登记、回读状态机和能力副作用目录，但不能共享正文容器或编辑权威。
4. 写入、成果登记或必要回读任一步失败，都不能向用户标记发布成功。

正式验收口径仍以独立终验节点（`DC`）为准；当前状态必须拆成两层理解：源码层已经存在第二阶段实现，正式 SSOT 节点层仍只有 A、A1、K 三项接受。当前主线（`main`）观察到提交编号（`{CURRENT_MAIN_SHA}`），第二阶段（Stage-2）起始提交为提交编号（`{CURRENT_STAGE2_ORIGIN_COMMIT}`），包含 {CURRENT_STAGE2_SERVICE_COUNT} 个第二阶段服务文件、{CURRENT_STAGE2_TEST_COUNT} 个第二阶段测试文件和 {CURRENT_STAGE2_TEST_FUNCTION_COUNT} 个测试函数；这只证明源码与聚焦测试资产存在，不证明部署、认证浏览器/设备、真实人工智能服务或真实飞书写入后回读。只有独立终验节点（`DC`）正式接受，才可以宣布本阶段完成。

## 2. 用户与可见行为

| 用户 | 第二阶段完成后的行为 | 不在本阶段的行为 |
| --- | --- | --- |
| 个人创作者 | 使用个人资料完成研究、决策、创作、网页端正文修订、平台版本和发布包闭环 | 读取组织品牌资料、把个人正文写进部署级飞书空间 |
| 组织创作成员 | 使用当前组织资料创作，把正文写入该组织飞书文档，在网页端回读并从可信入口打开飞书继续编辑 | 在网页端修改组织正文、使用其他组织或全局飞书凭据 |
| 能力维护者 | 为每个能力声明可读资料、是否产生文档、允许容器和必要回读要求 | 让能力自行选择租户、绑定或绕过统一写入路由 |
| 发布与验收负责人 | 对同一候选执行个人全链、组织飞书全链、跨租户负例、失败关闭和回滚验收 | 用本地测试、模拟浏览器或单次写入代替真实外部系统证据 |

## 3. 已接受的产品决定

1. 人工智能执行上下文只能由服务端会话、成员关系、组织绑定和能力编号生成。前端提交的租户、绑定或正文权威不是授权事实。
2. 个人路径唯一写入个人内部成果（`personal_web/internal`），网页端是个人正文唯一编辑权威，不创建全局飞书文档。
3. 组织路径唯一写入当前会话活跃组织绑定下的飞书文档（`organization_lark/lark`），飞书是组织正文唯一编辑权威，网页端只读。
4. 第一阶段先把全部旧人工智能文档入口、直接接口、旧链接和旧任务重放统一关闭；第二阶段是人工智能文档写入的唯一规划与实现所有者，只能从该失败关闭状态原子切换到统一写入路由。第一阶段资源解析器不产生人工智能文档，只读咨询和查询能力也不得产生文档或远端副作用。
5. 资料上下文全部遵守同一租户边界。已知的近期活动全表读取问题必须在上下文节点接受前关闭。
6. 写入、成果登记和必要回读共同组成成功条件；外部部分成功必须进入可审计、可幂等续接的待处置状态。
7. 候选不保留长期双权威、旧新写入器双路径、旧写入器入口、隐式回退或部署级全局飞书凭据备用路径。租户白名单、发布门、紧急停止、只读降级和外部写入停止开关可以保留，但不能改变唯一数据与授权权威。
8. 第一阶段身份汇合节点（`C1`）只解锁共享合同和个人支线；组织接入汇合节点（`C3`）解锁组织支线和第二阶段唯一写入路由；第一阶段发布增量 1B 终验节点（`DC2`）接受前不得组装第二阶段唯一候选。
9. 会话解析函数（`parseMediaSessionEnvelope`）的严格响应结构保持不变；会话版本（`media_web_business_pages_v2`）中不得增加页面授权字段（`routeGrants`）或其他新键。
10. 页面权限改由独立只读入口状态接口返回。接口必须有独立版本、严格响应结构和 OpenAPI/客户端类型；建议逻辑接口为入口状态地址（`GET /api/media/entry-state`），若源码已有等价入口则沿用一个既有路径并在 B 节点冻结，不能形成双入口。
11. 页面授权按三个维度分开：角色字段（`role`）决定管理员或普通壳层，工作区模式字段（`workspaceMode`）与正文权威字段（`bodyAuthority`）决定正文来源，入口状态返回页面和动作授权；服务端对每个业务动作继续做最终校验。
12. 当前生产入口文件（`src/media/main.tsx`）挂载媒体工作台应用（`MediaStudioApp.tsx`）；旧媒体应用（`MediaApp.tsx`）已由 `ea98ca3b` 从源码删除。机器路由清单（`studioOrdinaryRoutes`）当前 14 条，另有轨道路由清单（`studioTrackRoutes`）、个人/组织/管理员路由及运行详情深链；两组机器路由全量向个人人格开放，查询和动作按个人会话、租户、所有者作用域执行，个人正文只写个人网页内部成果，组织绑定（Binding）、飞书写入和组织成员能力继续隔离。
13. 字体自托管是境内部署主路径：拉丁字体（DM Sans）全量自托管，中文字体（Noto Sans SC）使用字符范围切片规则（`unicode-range`）或常用字子集，只预载拉丁子集；加载清单必须包含实际使用的 600 字重，清理 800/850 视觉依赖。
14. 中文标题及无法分段的中西混排标题默认使用字距属性（`letter-spacing: 0`）；负字距只允许用于纯拉丁或数字展示位。统一回退栈把苹方字体（PingFang SC）提前，并覆盖认证页与工作台。

这些决定构成第二阶段第 4 版范围。本阶段不重复拥有第一阶段五项已经接受的决定；其中，第一阶段资源解析边界和旧写入器关闭态仍由第一阶段独占。第一阶段写入边界决定节点（`K5`）规定关闭边界，旧写入器失败关闭节点（`I9`）负责实现该边界；第二阶段统一写入路由仍须等待组织接入投影正式接受，决定已接受不等于上游实现已完成。

## 3.1 本轮裁决的结果

本轮有一处合同冲突已经裁决：页面授权不进入现有会话信封，采用独立入口状态接口。这样保留会话解析函数（`parseMediaSessionEnvelope`）的严格兼容边界，同时允许服务端按实时角色、工作区和页面策略下发可见路由。这个接口仍是新的公共合同，必须经历 OpenAPI、服务端投影、客户端类型和合同测试的完整同步；“不改会话合同”不等于“不做接口合同工作”。

字体问题也已从“离线优化”提升为部署主路径修复。境内部署不能依赖谷歌字体服务（Google Fonts）的可达性；拉丁字体（DM Sans）体积小，直接全量自托管。中文字体（Noto Sans SC）不得把完整中文字体粗暴打包，应生成字符范围切片规则（`unicode-range`）或常用字子集，并且只预载拉丁子集。当前字体清单没有 600，后续若使用 600 必须同步补齐；认证页中的 850 和工作台对 800 的依赖必须移除。

## 3.2 本轮开发路径

1. **先做入口与合同清点（B）**：在当前生产入口、旧入口、服务端路由和 OpenAPI 中查找已有入口状态实现；确认媒体工作台应用（`MediaStudioApp`）的挂载路径、旧媒体应用（`MediaApp`）的实际引用、普通信息架构（IA）的真实数量，并把结果登记为来源证据。若没有可复用的接口，冻结一个入口状态接口（`entry-state`）的路径和版本。
2. **实现独立入口状态投影（B、S1）**：服务端从认证会话、角色字段（`role`）、工作区模式字段（`workspaceMode`）、正文权威字段（`bodyAuthority`）和能力注册表计算默认入口（`defaultRoute`）、页面授权和动作授权；响应严格校验，未认证返回 401，已认证但无权返回 403，版本过期或候选不一致返回稳定的冲突状态。任何客户端提交的租户、组织绑定、正文权威或角色都不能成为授权依据。
3. **统一路由注册表与入口（C6、C8、T1）**：用一个注册表生成导航、路由、默认入口和授权判断；媒体工作台应用（`MediaStudioApp`）作为唯一生产入口，旧媒体应用（`MediaApp`）只保留明确的退役转发或在确认无引用后删除。无权深链显示稳定的无权状态，不静默跳到另一个业务页面；页面内动作也必须按入口状态与服务端结果双重收敛。
4. **落实普通信息架构（IA）个人开放决定（K、C6、T1）**：`studioOrdinaryRoutes + studioTrackRoutes` 两组机器路由全量向个人人格开放，默认入口为个人概览；当前 `studioOrdinaryRoutes` 为 14 条，具体清单以 `mediaStudioRoutePolicy.ts` 为准。统一注册表必须为每条路由声明个人可见性和动作；查询、创建、编辑、发布、复盘、归档、计费与邀请均按个人会话、租户、所有者作用域校验。任何组织绑定（Binding）、飞书写入或组织成员动作在个人人格下稳定拒绝，不得静默切换人格。
5. **建立字体资源管线（C6、T1、DA）**：在前端资源目录生成并校验拉丁字体（DM Sans）和中文字体（Noto Sans SC）的 WOFF2 文件、切片或常用字子集，统一设计令牌样式表（`mediaDesignTokens.css`）与认证样式表（`media.auth.css`）的回退栈；加载 400/500/600/700 等实际使用字重，清理 800/850 依赖，中文标题字距为 0。只预载拉丁子集，中文切片按需加载。
6. **按真实会话和弱网验收（T1、C8、DA、DB、DC）**：覆盖普通/管理员 × 个人/组织四种合法会话，以及未认证、失效、非法信封、缺失入口状态和越权深链。浏览器拦截谷歌字体服务（Google Fonts）后分别验证字体可用与不可用两种状态，检查桌面和移动端没有溢出、截断或明显跳动。模拟会话、单纯导航文字和单次字体下载都不能替代真实合同证据。

### 本轮工程映射

| 中文对象 | 代码位置或合同 | 实施要求 |
| --- | --- | --- |
| 会话信封 | `media.login.js:parseMediaSessionEnvelope`、`mediaWebApi.ts` 严格 schema | 保持 `media_web_business_pages_v2` 和现有字段集合不变；为加字段的负例保留红灯测试 |
| 入口状态接口 | 建议 `GET /api/media/entry-state`；最终路径由 B 节点冻结 | 新建独立版本化严格响应；字段至少包含角色、工作区模式、正文权威、默认入口、页面授权和动作授权；同步 OpenAPI、服务端、客户端类型和合同测试 |
| 页面授权模型 | `MediaStudioApp.tsx`、`mediaRoleIa.ts`、统一路由注册表 | 导航、Route、默认入口和动作守卫消费同一注册表；后端仍是最终授权者 |
| 旧入口处置 | `src/media/main.tsx`、`MediaApp.tsx` | 先做生产引用清点；未证明历史代码前不得删除，确认退役后使用薄转发或删除并保留回归门禁 |
| 字体主路径 | `index.media.html`、`src/media.verify.html`、`mediaDesignTokens.css`、`media.auth.css` | 去除对 Google Fonts 的主路径依赖；DM Sans 全量自托管，Noto Sans SC 切片或子集，PingFang SC 提前，字重与字距按本轮决定执行 |

## 4. 明确排除项

- 第三阶段的完整组织负责人/成员权限矩阵、审核协作、套餐席位、采购、发票、跨租户迁移、复杂删除和经营分析。
- 自动发布到内容平台、平台侧增长结果或商业效果证明；本阶段只生成可追溯的平台版本和发布包。
- 用前端参数、页面选择、平台管理员身份或部署级凭据替代服务端会话、成员关系和组织绑定。
- 在个人与组织路径之间复制正文、建立双写同步或提供运行时回退。
- 让第一阶段组织资源解析器创建、更新或路由人工智能生成文档。
- 在第一阶段跨阶段投影未接受时提前改变第一阶段状态或冒领其完成度。

## 5. 跨阶段门禁与实施摘要

第一阶段身份汇合投影（`F1`）接受后，才能汇编共享合同并启动个人内容支线；该投影还必须证明旧人工智能文档入口已经在同一候选中失败关闭。第一阶段组织接入投影（`F2`）接受后，第二阶段唯一写入路由、组织资料、组织飞书写入和回读支线才能启动。两条支线和共享路由各自汇合后，仍须等待第一阶段必需交付终验投影（`F3`）；只有三个输入都成立，才组装第二阶段唯一候选。

当前第一阶段的身份汇合节点（`C1`）、组织接入汇合节点（`C3`）和发布增量 1B 终验节点（`DC2`）均为阻塞状态，因此第二阶段的三项跨阶段投影（`F1`、`F2`、`F3`）也全部阻塞，第二阶段当前没有合法正式就绪节点。该状态表示正式门禁尚未满足；它不再声称“没有代码”，而是明确区分源码实现观察与节点正式接受。

发布恢复采用三层合同：代码只原子切换不可变发布身份；数据库使用前向迁移和明确恢复步骤；飞书写入、登记和回读使用幂等步骤、补偿与待人工处置状态。不得把飞书动作描述成可以与代码和数据库一起原子回滚。

## 6. 实际实现标注

当前主线已经落地共享人工智能上下文、资料路由、唯一写入路由、成果登记与回读、个人内容流程、组织按绑定写入与飞书回读等第二阶段源码。个人网页端正文修订、平台版本/发布包完整流程，以及真实飞书编辑后再回读和最终汇合验收，当前文档标记为未完成或未形成正式证据。详细节点映射见实施进度文件（`implementation-progress.md`）的“实际实现台账（源码观察）”。

## 7. 工程执行附录

- 依赖拓扑文件（`generated-views/10-dependency-topology.md`）：输入一致性、权威、跨阶段门禁、机器节点与显式边。
- 执行治理文件（`generated-views/20-execution-governance.md`）：最小交付、最大安全并行宽度、外部执行器、资源冲突和全权限护栏。
- 验收合同文件（`generated-views/30-node-contracts-and-acceptance.md`）：节点合同、正式验收矩阵、门禁抽象、证据身份与清除清单。
- 实施进度文件（`implementation-progress.md`）：正式状态、空就绪前沿、阻塞原因与下一步。
"""


def topology_view() -> str:
    input_rows = [
        ["个人可信会话、工作区与旧写入器关闭态", STAGE1_MAIN, "第一阶段 C1 与 I9", "F1/B/C1", "第一阶段机器节点", "当前 BLOCKED", "只投影正式状态、候选身份和 I9 关闭回执", "F1"],
        ["组织 Binding 与 Provision", STAGE1_MAIN, "第一阶段 C3", "F2/O1/S3", "第一阶段机器节点", "当前 BLOCKED", "只投影正式状态并约束第二阶段写入路由", "F2"],
        ["第一阶段必需交付完成", STAGE1_MAIN, "第一阶段 DC2", "F3/C", "第一阶段机器节点", "当前 BLOCKED", "禁止提前组装候选", "F3"],
        ["个人 Web 正文闭环", ATTACHMENT, "个人成果与修订", "C1-C8", "服务端会话和内部成果", "范围已接受", "第二阶段实现", "K 已接受"],
        ["人工智能文档写入所有权", f"{STAGE1_K5}; {STAGE1_I9}", "第一阶段 I7 排除写入且 I9 建立关闭态，第二阶段拥有唯一写入路由", "F1/F2/S3/C5/O2", "两阶段机器节点与写入合同", "第一阶段 K5 已接受，I9 仍阻塞", "F1 与 F2 接受后才允许 S3 正式执行", "第一阶段 K5/I9"],
        ["组织飞书正文闭环", AUDIT, "Binding、飞书文档与镜像", "O1-O6", "服务端 Binding", "主路径仍有全局凭据风险", "按 Binding 切到唯一写入路由", "K 已接受"],
        ["近期活动租户隔离", AUDIT, "资料所有者与租户范围", "S2/O1", "服务端授权守卫", "存在全表读取问题", "上下文验收前关闭", "K 已接受"],
        ["组织经营与商业化", ATTACHMENT, "未来第三阶段", "本阶段无入口", "未来独立 SSOT", "明确排除", "不生成节点", "n/a"],
    ]
    authority_rows = [
        ["第二阶段决定与编排", ".ssot/manifest.json 及 nodes/edges", "decision/orchestration", "机器校验", "是", "A-DC", "check_ssot_program.py"],
        ["第一阶段 C1/C3/DC2 正式状态", str(STAGE1_MANIFEST), "decision/orchestration", "按哈希读取上游节点", "否；只同步投影", "F1-F3", "上游 ACCEPTED 回执"],
        ["当前产品和源码事实", AUDIT, "runtime-evidence", "来源路径和事实审计", "否", "A1/S2/O2", "文件哈希与实现时源码读回"],
        ["三阶段拆分与第二阶段边界", ATTACHMENT, "domain-contract", "用户附件和本次指令", "已汇编到 K", "K", "决定记录第 4 版"],
        ["两个发布增量与写入所有权修正", STRUCTURE_REVIEW, "domain-contract", "用户提供的结构修正", "已汇编到 K 与 F2/S3", "K/F2/S3", "决定记录第 4 版与上游投影"],
        ["第一阶段第 4 版结构复核", LATEST_REVIEW, "research/hypothesis", "校验值与逐项合同映射", "已同步上游哈希、I9 关闭态和五类运行配置", "A1/F1/S3/DA/DC", "机器源与跨阶段负例"],
        ["第一阶段旧写入器关闭合同", str(STAGE1_I9), "decision/orchestration", "按哈希读取上游节点", "否；只通过 F1 投影消费", "F1/S3", "I9 与 C1 同候选 ACCEPTED 回执"],
        ["人工智能上下文与写入合同", "待 B/S1/S3 在真实源码仓冻结的唯一合同", "domain-contract", "OpenAPI、类型和保护测试", "是", "B/S1/S3/T1", "合同生成与漂移门禁"],
        ["入口状态与页面授权合同", "B 节点冻结的独立 entry-state 接口；不得写入会话信封", "domain-contract", "OpenAPI、服务端投影、客户端类型和 401/403/409 合同测试", "是", "B/S1/T1/C6", "会话严格结构负例与真实会话矩阵"],
        ["字体资源与弱网主路径", "index.media.html、src/media.verify.html、mediaDesignTokens.css、media.auth.css", "domain-contract", "字体资源清单、构建产物和 Playwright 弱网证据", "是", "C6/T1/DA", "Google Fonts 拦截、字重和布局回归"],
        ["生成 Markdown", ".ssot/view-sources/*.md -> renderer", "execution-record", "manifest 哈希绑定", "自动生成", "A", "render --check"],
    ]
    uncertainty_rows = [
        ["项目根目录没有 Git 元数据", "discoverable-fact", "source-notes.md 非 Git 文件哈希基线", "main orchestrator", "只影响本地来源版本表达", "十二项输入文件校验值"],
        ["机器源 .ssot/implementation-progress.md 曾与已发布进度视图脱同步", "discoverable-fact", ".ssot/view-sources/40-progress.md 与顶层 implementation-progress.md 同源重建", "orchestrator", "只影响生成视图一致性，不改变正式节点状态", "build_ssot.py 写入三份相同进度内容并由 render --check 校验"],
        ["第一阶段 C1、C3、DC2 未接受", "execution-blocker", "F1、F2、F3 跨阶段投影", "stage1 acceptance owners", "按三条投影局部阻塞", "上游节点 ACCEPTED 及候选哈希"],
        ["真实个人、飞书组织和验收账号", "execution-blocker", "O5/DB 受控身份台账", "runtime acceptance owner", "只阻塞真实外部动作及下游", "同收据外部系统证据"],
        ["现有能力清单与生产源码位置", "discoverable-fact", "B/S5 实现前有界查找", "contract owner", "不改变已接受产品决定", "源码、OpenAPI 和注册表读回"],
        ["第二阶段产品选择", "none", "K 决定记录与第一阶段已接受决定；studioOrdinaryRoutes + studioTrackRoutes 两组机器路由全量向个人人格开放", "user", "不重复拥有第一阶段决定；路由动作仍需按个人会话、租户、所有者作用域实现", "K ACCEPTED / route allowlist ACCEPTED"],
    ]
    revision_rows = [[
        7,
        "L2",
        "接受 studioOrdinaryRoutes + studioTrackRoutes 两组机器路由全量向个人人格开放，并冻结个人会话、租户、所有者作用域与组织能力隔离边界",
        "PLAN_VERSION 5; DAG_VERSION 5; INTERFACE_FREEZE_VERSION 5; NODE_CONTRACT_VERSION 5; PRODUCT_DECISION_VERSION 4",
        "A/A1/K/F1/F2/F3/B-S5/C1-C8/O1-O6/S/C/DA/DB/DC",
        "旧候选分支与测试数量引用；机器源进度视图漂移；会话授权与视觉资源边界待补充",
        "重建全部机器分片、执行合同、规划编译记录和生成视图并复验；保留正式节点门禁和普通 IA 产品问题",
        "main orchestrator under user-requested cross-stage synchronization",
        "2026-08-30",
    ]]
    semantic_rows = []
    for node_id, node in NODES.items():
        refs = [f"{item['semantic_key']}@{item['version']}" for item in node["decision_refs"]]
        semantic_rows.append([
            node_id, node["semantic_key"], node["work_kind"], node["domain_lane"], node["execution_state"],
            node["decision_state"], node["decision_version"], node["readiness_mode"], node["hard_dependencies"],
            node["soft_dependencies"], node["assumption_ids"], refs, node["invalidation_keys"],
            node["write_authority"], node["acceptance_authority"],
        ])
    edge_rows = [
        [
            edge["from"], edge["to"], edge["dependency_type"], edge["dependency_scope"], edge["required_state"],
            edge["assumption_ids"], edge["invalidation_keys"], edge["transferred_input"], edge["gate_evidence"],
        ]
        for edge in EDGE_RECORDS
    ]
    ascii_graph = "```text\n" + "\n".join(f"{source} -> {target}" for source, target, _ in EDGES) + "\n```"
    mermaid_graph = "```mermaid\nflowchart TD\n" + "\n".join(f"  {source} --> {target}" for source, target, _ in EDGES) + "\n```"
    return "\n\n".join([
        "# 第二阶段权威与依赖拓扑",
        "## 输入一致性",
        table(["Promised behavior", "Input location", "Owning model/field", "API or workflow entry", "Permission/state authority", "Conclusion", "Action", "Blocking decision node"], input_rows),
        "## 权威登记",
        table(["Claim/domain", "Declared authority path", "Authority layer", "Lookup method", "Change required", "Owning node", "Validation"], authority_rows),
        "生成的 Markdown 只是读取视图，不是第二套编排权威。第一阶段状态必须先在其机器节点中正式迁移，本文件的 F1-F3 才能同步；本包只读取第一阶段 K5 决定和 I9 关闭合同，不重复拥有或改写它们。",
        "## 修订台账",
        table(["Revision", "Deviation level", "Reason", "Changed versions", "Affected nodes", "Invalidated acceptance/evidence", "Nodes to rerun", "Approving authority", "Timestamp"], revision_rows),
        "## 不确定性路由",
        table(["Uncertainty", "Class", "Destination", "Owner", "Blocking scope", "Resolution evidence"], uncertainty_rows),
        "## ASCII 拓扑图",
        ascii_graph,
        "## Mermaid 依赖图",
        mermaid_graph,
        "## 语义节点登记",
        table(["Task ID", "Semantic key", "Work kind", "Domain lane", "Execution state", "Decision state", "Decision version", "Readiness mode", "Hard dependencies", "Soft dependencies", "Assumptions", "Decision refs", "Invalidation keys", "Write authority", "Acceptance authority"], semantic_rows),
        "## 依赖边登记",
        table(["From", "To", "Dependency type", "Dependency scope", "Required upstream state", "Assumption IDs", "Invalidation keys", "Transferred input", "Gate/evidence"], edge_rows),
    ])


def execution_view() -> str:
    by_batch: dict[str, list[list[object]]] = defaultdict(list)
    for row in DELIVERABLES:
        by_batch[str(row[1])].append(row)
    width_rows = []
    for batch, rows in sorted(by_batch.items()):
        logical = len({str(row[7]) for row in rows})
        slots = min(12, max(1, logical))
        width_rows.append([batch, len(rows), len(rows), 0, logical, slots, math.ceil(logical / slots)])

    registration_rows = []
    process_rows = []
    cleanup_rows = []
    profile_rows = []
    for node_id, node in NODES.items():
        transport = node.get("worker_transport")
        registration = node.get("worker_registration")
        if not isinstance(registration, dict):
            registration = {}
        dispatch = str(
            registration.get(
                "dispatch_state",
                "EXITED"
                if node.get("execution_state") in {"IMPLEMENTED", "VERIFIED", "ACCEPTED"}
                else "BLOCKED",
            )
        )
        if transport == "historical-unregistered":
            registration_rows.append([
                node_id, transport, "n/a", PROJECT_ROOT_TEXT,
                "no retroactive worker claim", "n/a", dispatch, "n/a",
            ])
            process_rows.append([
                node_id, 0, 0, "historical source or decision already accepted", "n/a",
                f"historical-{node_id}", "historical-unverified", "historical-unverified", "historical-unverified",
            ])
            cleanup_rows.append([
                node_id, "historical-unverified", "historical-unverified", "historical-unverified",
                "historical-unverified", "historical-unverified", "historical-unverified; no retroactive worker claim",
            ])
        elif transport is None:
            registration_rows.append([
                node_id, "none", "n/a", "n/a",
                "orchestrator convergence; zero Codex processes", "n/a", dispatch,
                f"{REL_BUNDLE}/worker-returns/{node_id}.json",
            ])
            process_rows.append([
                node_id, 0, 0, "orchestrator assembles accepted inputs", "main orchestrator",
                f"stage2-2-2-3-3-{node_id}", "not-applicable", "n/a", "not-applicable",
            ])
            cleanup_rows.append([
                node_id, "n/a", "n/a", "n/a", "n/a", "n/a",
                "zero Codex process; retain convergence receipt",
            ])
        elif transport in {"external-manual", "deterministic-local", "automatic-projection"}:
            zero_process_contracts = {
                "external-manual": "manual prerequisite; zero Codex processes",
                "deterministic-local": "deterministic local execution; zero Codex processes",
                "automatic-projection": "automatic state projection; zero Codex processes",
            }
            zero_process_authorities = {
                "external-manual": "not applicable",
                "deterministic-local": "bounded local process",
                "automatic-projection": "generated state only",
            }
            registration_rows.append([
                node_id, transport, "n/a", registration.get("project_root", "n/a"),
                zero_process_contracts[transport],
                zero_process_authorities[transport], dispatch,
                registration.get("return_path", "n/a"),
            ])
            process_rows.append([
                node_id, 0, 0, "structured receipt plus scoped acceptance or terminal failure",
                registration.get("executor", "outer orchestrator"),
                f"stage2-2-2-3-3-{node_id}", "not-applicable", "n/a", "not-applicable",
            ])
            cleanup_rows.append([
                node_id,
                *(["not-applicable; zero Codex process"] * 6),
            ])
            profile_rows.append([
                node_id, "zero-process", "n/a", "not-authorized",
                "transport-specific contract", "not-applicable",
            ])
        else:
            registration_rows.append([
                node_id, transport, registration.get("wrapper", "n/a"), registration.get("project_root", "n/a"),
                registration.get("invocation", "n/a"), registration.get("sandbox_authority", "n/a"),
                dispatch, registration.get("return_path", "n/a"),
            ])
            process_rows.append([
                node_id, 1, 0 if registration.get("worker_level") == "L3" else 1,
                "structured return plus scoped acceptance or terminal failure", "main orchestrator",
                f"stage2-2-2-3-3-{node_id}", "pending", registration.get("log_path", "n/a"), "pending",
            ])
            cleanup_rows.append([
                node_id, registration.get("prompt_path", "n/a"), registration.get("prompt_sha256", "n/a"),
                registration.get("launch_barrier", "n/a"), registration.get("prompt_cleanup", "n/a"),
                registration.get("runtime_handle_cleanup", "n/a"),
                registration.get("codex_transcript_retention", "n/a"),
            ])
            profile_rows.append([
                node_id,
                registration.get("runtime_profile", "n/a"),
                registration.get("runtime_profile_available", "n/a"),
                registration.get("launch_authorized", "n/a"),
                registration.get("profile_authority", "n/a"),
                registration.get("merge_protocol_authority", "n/a"),
            ])

    merge_rows = [
        ["开发基线", "允许提前开发的源码快照，以及每个文件的路径、大小与 SHA-256", "第一阶段 M1", "任何第二阶段补丁开始前复算"],
        ["晋升基线", "F3 绑定的第一阶段 DC2 已接受候选，不得继续使用提前开发时的旧基线", "第一阶段 M1、F3 与候选 C", "候选 C 重建前"],
        ["节点补丁清单", "节点、基线身份、补丁、文件归属、测试与结构化返回", "每个第二阶段实现节点", "外部工作进程退出前"],
        ["固定应用顺序", "按机器拓扑和迁移顺序应用补丁，禁止目录覆盖", "第二阶段候选汇合负责人", "候选 C 重建时"],
        ["冲突检测", "未声明的同文件重叠、过期开发基线、晋升基线冲突、漏补丁与顺序漂移均失败关闭", "第一阶段 M1 协议", "应用每个补丁前后"],
        ["候选重建", "从晋升基线重放全部已接受补丁；冲突使所属节点失效并复算唯一候选校验值", "候选 C", "每次候选变化后"],
    ]

    guard_rows = [
        [
            "G-DOC", "用户明确授权创建第二阶段 SSOT", str(BUNDLE),
            "其他 agents-results、第一阶段包、项目代码、远程系统", "none", "none", "none",
            "不得读取凭据", "十二项输入文件 SHA-256 已登记", "重跑生成器并恢复上次通过校验的视图",
            "只允许本 bundle 新增文件", "render/check/snapshot 哈希读回", "任何来源哈希或生成视图漂移",
        ],
        [
            "G-UPSTREAM", "第一阶段 C1/C3/DC2 正式节点合同", str(BUNDLE / "worker-returns"),
            "第一阶段机器节点、第一阶段候选、项目源码、生产和飞书资源", "第一阶段机器源只读入口", "none",
            "none", "不读取明文凭据", "第一阶段 manifest、节点状态和候选哈希复算",
            "无修复；状态不成立时保持 BLOCKED", "仅新增零写入投影回执", "上游节点与候选身份读回",
            "发现任何上游写入、状态伪造或哈希漂移",
        ],
        [
            "G-PHASE2", "K 第 4 版决定、第一阶段 G1 运行配置回执与 M1 汇合协议", str(PROJECT_ROOT / ".codex-work"),
            "第一阶段候选、活动发布、其他 agents-results、未授权租户、飞书真实组织",
            "隔离数据库、隔离个人成果和节点声明的测试资源", "仅节点合同列明的实现和测试",
            "禁止跨租户迁移、复杂删除和生产切换", "秘密用引用或受控输入；不得进入 argv、日志或截图",
            "每节点先捕获源码、schema、合同和运行身份", "隔离候选回退；失败进入所属状态机",
            "只允许节点专属目录、明确共享合同和机器分片", "服务端上下文、租户范围、成果和版本回读",
            "越界写入、跨租户、错正文权威、凭据泄漏或候选身份变化",
        ],
        [
            "G-FEISHU", "当前会话的活跃组织 Binding、F2 投影与 K 第 4 版正文决定",
            "隔离候选、节点证据目录和获批飞书测试文档", "其他组织、全局凭据、个人正文、生产未批准资源",
            "批准的隔离飞书组织、Wiki 空间和父节点", "仅 O2/O5 合同允许的创建、编辑和回读",
            "禁止复杂删除、搬迁或影响非测试资源", "按 Binding 解析密钥引用；明文不得进入 argv、日志或证据",
            "先读回租户、Binding、凭据世代、空间、父节点和文档身份",
            "幂等续接或隔离测试资源补偿；不得切换全局 Writer", "写前后远端版本、镜像、链接和数据库差异",
            "同一 Binding 的飞书与 Web 镜像回读", "错租户、错 Binding、回读失败、可信链接失败或未授权副作用",
        ],
        [
            "G-RELEASE", "C 候选身份与批准发布窗口", "不可变候选和本 bundle 证据目录",
            "第一阶段历史、第三阶段能力、其他项目栈和未列明租户", "批准的生产栈及隔离个人/飞书验收身份",
            "DB 只原子切换代码发布身份，并执行声明的数据库与飞书外部步骤；DA 只读或本地测试",
            "只允许声明的前向迁移、数据库恢复步骤和飞书幂等补偿", "凭据由运行环境或秘密存储提供并全程脱敏",
            "候选、生产、数据库、个人成果、飞书资源和回滚点前置读回",
            "代码回指旧发布；数据库执行恢复合同；飞书执行补偿或转入 NEEDS_ATTENTION", "发布前后哈希、schema、活动进程和外部资源差异",
            "真实浏览器、数据库、人工智能任务、个人成果、飞书和服务同收据读回",
            "任何强制负例失败、外部读回缺失、旧 Writer 存活或观察期告警",
        ],
        [
            "G-ZERO", "独立终验职责分离", str(BUNDLE / "evidence" / "DC"),
            "源码、候选、数据库、远程服务、飞书资源和节点状态源", "生产和飞书只读入口", "none", "none",
            "不读取明文凭据；只用验收身份", "读取 DB 接受的证据身份", "无修复；失败返回 owning node",
            "仅新增独立证据结论", "哈希、发布、账号、租户、Binding、成果、设备和时间读回",
            "发现任何写入、第三阶段冒领或证据身份不一致",
        ],
    ]
    concern_rows = [
        ["security / authentication / secrets", "required", "S1/S2/S3/O2/T1", "服务端上下文、防伪造、跨租户、Binding 凭据和秘密扫描"],
        ["privacy / compliance / retention", "required", "S2/C1/O1/S4", "个人与组织资料隔离、最小收据和成果保留合同"],
        ["migration / backfill / rollback", "required", "S3/S4/C5/O2/C/DB", "旧 Writer 清除、成果绑定迁移、代码切换、数据库恢复和飞书补偿"],
        ["reliability / idempotency / recovery", "required", "S4/C5/C6/O2/O3/O4", "写入、登记、回读、重放、并发和部分成功续接"],
        ["performance / scalability", "required", "S2/C4/O4/DA", "上下文资料上限、飞书回读时延、分页和并发配额"],
        ["observability / audit", "required", "S1/S4/O2/O4/DB", "租户、Binding、能力、成果、版本、时间和候选同收据"],
        ["accessibility / mobile", "required", "C6/C7/C8/DB", "个人 Web 编辑、平台版本和端到端移动浏览器回归"],
        ["internationalization", "not-applicable", "n/a", "本阶段没有新增多语言产品承诺；不得为填表制造节点"],
        ["cost / quota", "required", "S2/O2/O4/DA", "上下文预算、模型调用、飞书配额、重试上限和失败关闭"],
        ["deployment", "required", "C/DA/DB", "唯一候选、代码发布身份原子切换、旧路径清除和分层恢复"],
        ["operational / handoff", "required", "DB/DC", "活动版本、进程、外部资源、观察期、值守交接和独立读回"],
    ]
    resource_rows = [
        ["RES-SSOT", "阶段二机器源与生成视图", "A, A1, K, C, DA, DB, DC", "W/R", "single-generated-artifact", "仅主调度者汇编 manifest 和视图；其他执行者写节点分片或返回"],
        ["RES-CONTRACT", "上下文、Writer、成果和 OpenAPI 合同", "B, S1, S3, S4, S5, T1", "W", "write-write", "B 冻结接口身份；各节点独占合同分片；S 汇合后统一生成"],
        ["RES-DB", "成果、修订、远端绑定和回读 schema", "S4, C5, C6, O3, O4", "W", "single-migration", "S4 独占迁移编号；其他节点只消费已接受 schema"],
        ["RES-PERSONAL", "隔离个人工作区和内部成果", "C1, C2, C3, C4, C5, C6, C7, C8", "W/R", "workspace identity", "按个人租户和成果身份隔离；C8 只汇合已冻结子候选"],
        ["RES-FEISHU", "隔离组织 Binding、Wiki、父节点和 Docx", "O1, O2, O3, O4, O5, O6", "W/R", "external identity", "O2/O5 的外部写动作按同一 Binding 和文档串行；O6 只汇合证据"],
        ["RES-CANDIDATE", "第二阶段唯一候选", "C8, O6, S, C, DA, DB, DC", "W/R", "release identity", "C 独占组装；DA 后保持不可变；DB 推广；DC 零写入"],
        ["RES-PRODUCTION", "活动发布、数据库和外部系统", "DB, DC", "W/R", "release identity", "DB 在批准窗口独占代码切换与分层外部步骤；DC 只读并与发布职责分离"],
    ]

    return "\n\n".join([
        "# 第二阶段执行治理",
        "## 叶子交付清单",
        table(["Deliverable ID", "Parallel batch", "Deliverable", "Authority write region", "Dependencies", "Isolation decision", "Conflict class", "Owning node", "Grouping reason"], DELIVERABLES),
        "每个独立叶子交付只归属于一个数字节点。共享合同、迁移、同一飞书文档、候选和活动发布通过资源矩阵串行；可用执行槽位只改变波次，不合并节点。",
        "## 最大安全并行宽度",
        table(["Parallel batch", "Leaf deliverables", "Independent deliverables", "Conflict-grouped deliverables", "Logical lane target", "Available worker slots", "Wave count"], width_rows),
        "## Worker 执行合同",
        "真正需要独立实现进程的叶节点使用 `external-codex-exec`；历史节点、自动投影、确定性本地检查、人工外部验收和纯汇合节点均使用各自的零进程合同。Codex 注册命令包含 `codex exec -C <absolute-root> --skip-git-repo-check --sandbox danger-full-access`，注册的沙箱权威是 `writable sandbox`，包装器最终进入 `exec codex exec`。本计划禁止把 `spawn_agent`、聊天子代理或同进程协作接口登记为执行器。当前所有登记均为禁止启动，也没有启动任何外部 worker。",
        table(["Task ID", "Transport", "Wrapper", "Project root", "Literal codex exec contract", "Sandbox authority", "Dispatch state", "Return path"], registration_rows),
        "## 五类运行配置继承门",
        table(["Task ID", "Required runtime profile", "Profile available", "Launch authorized", "Profile authority", "Merge protocol authority"], profile_rows),
        "第二阶段不重新发明运行配置或无 Git 合并算法。第一阶段 G1 提供实现、静态验证、外部测试、生产发布和独立只读五类配置，M1 提供开发基线与晋升基线重建协议；F1/F2 未接受时，兼容 wrapper 不得启动。",
        "## 无 Git 候选汇合协议",
        table(["Protocol element", "Required record or behavior", "Authority", "Gate timing"], merge_rows),
        "## 有限进程预算",
        table(["Task ID", "Worker processes", "Retry limit", "Stop condition", "Cancellation owner", "Idempotency key", "PID/session", "Log path", "Exit code"], process_rows),
        "## 临时提示与运行句柄清理",
        table(["Task ID", "Prompt path", "Prompt SHA-256", "Launch barrier", "Prompt cleanup", "Runtime handle cleanup", "Codex transcript retention"], cleanup_rows),
        "## 执行门禁",
        table(["Guard ID", "Authority basis", "Allowed write roots", "Forbidden paths", "External targets", "External side effects", "Destructive actions", "Secret handling", "Baseline", "Recovery", "Postflight diff", "Readback", "Rollback condition"], guard_rows),
        "## 资源冲突矩阵",
        table(["Resource ID", "Resource", "Nodes", "Mode", "Isolation key", "Serialization rule"], resource_rows),
        "## 横切关注项",
        table(["Concern", "Decision", "Owner", "Required gate/evidence"], concern_rows),
        "## 偏差与独立复核规则",
        "L1 只修正文案、定位或非语义执行信息；L2 修改依赖、节点或验收；L3 修改租户授权、Binding、正文权威、数据迁移、外部生命周期或发布身份。L2/L3 必须更新机器分片并重建全部视图。每个发现最多做一次有界独立复核；复核不得修改候选。",
    ])


def harness_row(node_id: str, item: dict[str, object]) -> list[object]:
    kind = str(item["work_kind"])
    if kind in {"charter", "fact-discovery", "decision-acceptance"}:
        failure = "来源、决定或状态被错误改写"
        control = "docs and contract"
    elif kind in {"contract-assembly", "contract-compile", "acceptance-design"}:
        failure = "合同漂移、字段伪造或副作用未声明"
        control = "contract and scripts/quality"
    elif kind in {"validation", "release-decision"}:
        failure = "证据身份不全、越级接受或验收写入候选"
        control = "scripts/qa and evidence contract"
    elif kind == "convergence":
        failure = "子候选身份不一致、依赖缺失或汇合后仍有双路径"
        control = "scripts/quality and contract"
    else:
        failure = "租户、正文权威、版本或失败状态不符合节点合同"
        control = "scripts/quality and scripts/qa"
    return [
        node_id,
        failure,
        item["acceptance"],
        item["tests"],
        control,
        f"EV-{node_id}-CURRENT plus scoped red/green result",
        "required before ACCEPTED",
        "MCP unavailable; manually classified by Harness fields",
    ]


def acceptance_view() -> str:
    contract_rows = []
    for node_id, item in SPECS.items():
        contract_rows.append([
            node_id, item["title"], item["user"], item["inputs"], item["processing"], item["output"],
            item["tests"], item["acceptance"], item["dod"],
        ])
    evidence_rows = [current_evidence_row(node_id) for node_id in NODES]
    harness_rows = [harness_row(node_id, item) for node_id, item in SPECS.items()]
    cleanup_rows = [
        ["人工智能上下文", "client authority", "前端 tenant、Binding、正文权威或角色作为授权输入", "服务端重建并稳定拒绝保留字段", "否", "S1/T1/DA"],
        ["资料读取", "cross-tenant query", "01_近期活动全表读取及其他未限定资料查询", "切到统一 ContextBuilder 租户范围并加负例", "否", "S2/O1/DA"],
        ["个人正文", "legacy writer", "个人任务写入全局飞书或组织飞书", "C5 切到 personal_web/internal 后删除消费", "否", "C5/C8/DA"],
        ["组织正文", "fallback", "部署级全局 app/secret/space/parent 与旧 Writer", "O2 切到当前 Binding 世代解析后删除", "否", "O2/O6/DA"],
        ["跨阶段写入所有权", "duplicate authority", "第一阶段 I7 创建、更新或路由人工智能文档", "S3 接受前核对 I7 仅保留资源发现、只读镜像、同步补水和可信打开", "否", "F2/S3/DA"],
        ["组织 Web", "duplicate authority", "可编辑内部 Web 正文或 Web/飞书双写", "只保留飞书回读镜像和可信打开动作", "否", "O3/O4/O5"],
        ["成果状态", "false success", "写入成功但登记或回读失败仍标记发布成功", "进入待处置并提供幂等续接", "否", "S4/C5/O3/O4"],
        ["能力调用", "bypass", "文档型能力自选容器或只读能力产生副作用", "统一经过 WriterRouter 和副作用注册表", "否", "S3/S5/T1"],
        ["发布控制", "runtime alternate path", "长期双 Writer、旧新上下文权威、隐式回退或备用凭据", "保留唯一候选；代码原子切换、数据库按合同恢复、飞书幂等补偿", "只允许不改变权威的白名单、发布门、紧急停止、只读降级和外部写入停止", "C/DA/DB"],
        ["执行临时项", "temporary", "prompt、PID/session 句柄、隔离端口和临时飞书文档", "退出证据登记后按节点合同清理或审计保留", "日志、return、ledger 与 Codex transcript 保留", "cleanup ledger"],
    ]
    acceptance_rows = [
        ["跨阶段身份输入", "第一阶段 C1 正式接受并投影 F1", "上游状态、哈希或候选不一致必须保持阻塞", "F1/B", "第一阶段机器源与候选同身份回执"],
        ["共享人工智能上下文", "服务端生成租户、工作区、正文权威、Binding 和能力范围", "前端夹带权威字段、跨租户资料和近期活动全表读取均拒绝", "S1-S5/T1/S", "合同、数据库、能力矩阵和负例同候选证据"],
        ["个人内容闭环", "个人资料、研究、决策、创作、内部成果、Web 修订、平台版本和发布包", "组织资料、组织 Binding 和任何飞书写入必须为零", "C1-C8", "真实个人账号、浏览器、成果、修订和任务同收据"],
        ["跨阶段组织输入", "第一阶段 C3 正式接受并投影 F2", "缺失、撤销或错组织 Binding 必须保持阻塞", "F2/O1", "第一阶段机器源、Binding 和候选同身份回执"],
        ["组织飞书闭环", "组织资料、当前 Binding 写入、成果绑定、Web 回读、飞书编辑和再回读", "错组织、全局凭据、内部可编辑正文和回读失败均拒绝成功", "O1-O6", "真实飞书 Docx、Binding、远端版本和 Web 镜像同收据"],
        ["失败关闭", "写入、登记和必要回读全部成功后才标记发布成功", "部分成功、重放、并发和版本倒退进入可处置状态", "S4/C5/O2/O3/O4", "状态机、幂等键、失败收据和续接回读"],
        ["候选组装", "个人、组织、共享子候选与第一阶段 DC2 投影一致", "F3 未接受、旧 Writer 存活或子候选身份不同均禁止组装", "F3/C", "唯一候选哈希、资源清单和清理门禁"],
        ["发布", "同一候选静态通过、代码身份原子切换、真实两支端到端通过、分层恢复验证和独立终验", "第三阶段能力冒领、恢复合同缺失或任何强制负例失败均拒绝", "DA/DB/DC", "哈希绑定的生产、浏览器、数据库、人工智能任务和飞书证据"],
    ]
    return "\n\n".join([
        "# 第二阶段节点合同与验收",
        "## 完整节点合同",
        table(["Task ID", "Business target", "User", "Inputs", "Processing", "Outputs", "Tests", "Acceptance", "Completion definition"], contract_rows),
        "## 第二阶段正式验收矩阵",
        table(["Acceptance area", "Required positive path", "Required negative path", "Owning nodes", "Completion evidence"], acceptance_rows),
        "## Harness 门禁抽象",
        table(["Task ID", "Failure type", "Project invariant", "Detection", "Control location", "Gate evidence", "New guard/QA", "MCP usage"], harness_rows),
        "门禁用于在开发和验收阶段发现稳定失败类，不得成为运行时回退、兼容路径、灰度分流或第二事实来源。",
        "## 当前证据身份",
        table(["Evidence ID", "Task ID", "Evidence level", "Source revision", "Artifact hashes", "Environment", "Runtime release", "Actor role", "Account/tenant", "Device/browser", "Mock/fixture", "Observed at", "Acceptance contract"], evidence_rows),
        "当前最高已证明等级是 `source`。目标 `physical-device/external-system` 只能由 DB 和 DC 对同一不可变候选的真实浏览器、数据库、人工智能任务、个人成果、飞书文档、账号、租户、Binding、设备和时间证据达到。",
        "## 清除清单",
        table(["Scope", "Type", "Old or temporary item", "Action", "May remain", "Evidence"], cleanup_rows),
        "## 禁止路径检查",
        "第二阶段候选不得包含长期兼容接口、隐式回退、双写、旧新 Writer 并行、运行时备用凭据或把 Harness 门禁当成业务分支。前向数据库迁移可以保留必要的存储过渡；租户白名单、发布门、紧急停止、只读降级和外部写入停止开关可以保留，但不能改变唯一服务端上下文入口、唯一写入路由或正文权威。任何消费者不能在同一候选切换时，必须停在 C 之前修订迁移合同，不能用长期双路径绕过。",
        "## 最终完成声明",
        "只有 F1、F2、F3 三个跨阶段投影，共享汇合 S、个人汇合 C8、组织汇合 O6、唯一候选 C、静态验收 DA、真实外部系统验收 DB 和独立终验 DC 全部 ACCEPTED，才可声明第二阶段完成。任何第三阶段功能、模拟证据或单支线成功都不能替代该边界。",
    ])


def progress_view() -> str:
    state_rows = []
    for node_id, node in NODES.items():
        evidence = f"EV-{node_id}-CURRENT" if node["execution_state"] == "ACCEPTED" else "pending"
        state_rows.append([
            node_id, node["stage"], VERSIONS, node["execution_state"],
            1 if node["execution_state"] == "ACCEPTED" else 0,
            node["acceptance_authority"], guard_for(node_id), state_reason(node_id), evidence, node["unlocks"],
        ])
    metrics = [
        ["ready-frontier-width", 0, "F1、F2、F3 对应的第一阶段 C1、C3、DC2 正式状态均未满足"],
        ["formal-ready", 0, "没有正式就绪节点"],
        ["conditional-ready", 0, "没有活动假设，也不允许用假设绕过跨阶段门禁"],
        ["global-completeness-barriers", sum(edge[2] == "global-completeness" for edge in EDGES), "C->DA、DA->DB、DB->DC"],
        ["critical-path-length", longest_path(), "按机器源硬依赖计算的最长节点路径"],
    ]
    return "\n\n".join([
        "# 第二阶段实施进度",
        "## 当前结论",
        f"本 SSOT 已完成第 6 版事实刷新。正式完成度仍为 9.4%（3/32）：A、A1、K 已接受，其余 29 个节点仍为 BLOCKED。源码实现观察已更新：当前主线（`main`）为 `{CURRENT_MAIN_SHA}`，Stage-2 起始提交为 `{CURRENT_STAGE2_ORIGIN_COMMIT}`，包含 {CURRENT_STAGE2_SERVICE_COUNT} 个第二阶段服务文件、{CURRENT_STAGE2_TEST_COUNT} 个测试文件和 {CURRENT_STAGE2_TEST_FUNCTION_COUNT} 个测试函数；候选分支 `codex/stage2-release-20260818` 已不存在。相关提交与聚焦测试只能作为源码/静态测试证据，不能提升节点状态。第一阶段 C1、C3、DC2 尚未接受，因此本阶段当前没有合法正式就绪节点。生产认证会话解析、入口状态接口、租户资料读取、认证浏览器/设备、真实人工智能任务、真实飞书写后回读和独立外部验收仍未证明。",
        "## 状态台账",
        table(["Task ID", "Stage", "Versions", "State", "Attempt", "Owner", "Guard ID", "Blocking reason", "Evidence", "Unlocks"], state_rows),
        "## 实际实现台账（源码观察）",
        table(["节点范围", "当前源码事实", "证据边界"], [[key, value, "源码/聚焦测试观察；不等同正式节点接受"] for key, value in IMPLEMENTATION_OBSERVATIONS.items()]),
        "## 当前就绪前沿",
        table(["Frontier", "Task ID", "Eligibility", "Unsatisfied hard dependencies", "Active assumptions", "Resource decision"], []),
        "当前就绪前沿为空。不得启动 B、S1、C1、O1、C 或任何 D 阶段节点，也不得建立隔离草案来绕过正式跨阶段输入。源码已存在不等于节点已接受。",
        "## 波前指标",
        table(["Metric", "Value", "Basis"], metrics),
        "## 下一步唯一动作",
        f"继续在第一阶段权威 `{STAGE1_MAIN}` 下推进其合法就绪前沿。第一阶段 C1 正式接受后，先零写入同步 F1，才能打开共享合同和个人支线；C3 接受后同步 F2，才能打开第二阶段唯一写入路由和组织支线；DC2 接受后同步 F3，但仍须等待 C8、O6 和 S 才能组装第二阶段唯一候选。当前机器源的 `studioOrdinaryRoutes + studioTrackRoutes` 已决定全部向个人人格开放；后续只需按个人会话、租户、所有者作用域、动作权限和组织能力隔离实现，记录见 `openproblem.md`。",
        "## 第三阶段边界",
        "第二阶段 DC 接受只证明个人内容闭环、组织飞书正文闭环和 C/B 人工智能文档分流完成。完整组织角色、审核、席位、采购、发票、迁移、复杂删除和经营分析继续属于未来第三阶段，不得计入本阶段节点或完成度。",
    ])


def acceptance_execution_view() -> str:
    rows = [
        ["登录入口状态", "npm run qa:media-login-visual-runtime", "运行时 PNG 与四态矩阵", "自动化 + 人工读图", "回退态需确认不超过一屏"],
        ["普通路由矩阵", "npm run qa:media-route-matrix", "统一路由注册表与越权负例", "自动化", "导航重定向与数据/动作 403 必须分层"],
        ["共享视觉原语", "npm run qa:media-primitive-adoption", "24 面结构清单与原语使用", "自动化", "采用率不等同本地样式完全删除"],
        ["入口状态合同", "pytest openclaw-tag-router/tests/test_auth_entry_state.py", "entry-state 四态响应与错误语义", "自动化", "与工作台 route grants 合同分开验收"],
        ["Stage-1 工作台运行时", "npm run qa:media-stage1-workspace-runtime", "认证浏览器运行时截图", "自动化 + 人工读图", "不等同真实部署读回"],
        ["视觉构建门禁", "npm run build:media", "构建与视觉/结构 QA 门禁", "自动化", "记录已知基线失败，不提升 SSOT 节点状态"],
        ["全量回归", "pytest openclaw-tag-router/tests/ --ignore=tests/test_sync_lark_base_projection.py", "全量测试与基线分类", "自动化", "已知失败必须与新回归分开"],
    ]
    return "\n\n".join([
        "# 第二阶段验收执行",
        "## 自动化验收映射",
        table(["验收区域", "命令", "证据", "判读方式", "缺口/边界"], rows),
        "## 证据分层",
        "运行时门禁与截图只形成 source/local-runtime 证据，不能替代真实组织扫码、飞书编辑后再回读、28 天会话持久化部署读回或独立外部验收。",
        "## 人工验收保留项",
        "1. 真实组织扫码与部署读回。\n2. 飞书编辑后再回读。\n3. 登录回退态折线确认。\n4. 28 天会话持久化真实部署读回。",
        "## 当前合同提醒",
        "routeGrants 已进入当前源码的严格会话 schema，但早期产品决定曾明确禁止向会话信封增加该字段；该冲突需在 B 节点重新裁决，不能由静态门禁自动视为已接受。",
    ])


def source_notes() -> str:
    return f"""
# 第二阶段来源笔记

## 固定输入

| Source | Path | SHA-256 | Use |
| --- | --- | --- | --- |
| 事实审计 | `{AUDIT}` | `{HASHES['audit']}` | 当前个人/组织正文、登录、Binding、资料和租户缺口事实 |
| 三阶段编排 | `{ATTACHMENT}` | `{HASHES['attachment']}` | 用户确认的第二阶段边界和跨阶段门禁 |
| 结构修正 | `{STRUCTURE_REVIEW}` | `{HASHES['structure_review']}` | 发布增量拆分、Writer 所有权、运行配置与分层恢复语义 |
| 第一阶段第 4 版结构复核 | `{LATEST_REVIEW}` | `{HASHES['latest_review']}` | 旧写入器关闭态、五类运行配置、晋升基线和跨阶段硬门修正 |
| 第一阶段主文档 | `{STAGE1_MAIN}` | `{HASHES['stage1_main']}` | C1、C3、DC2 合同与阶段移交语义 |
| 第一阶段进度 | `{STAGE1_PROGRESS}` | `{HASHES['stage1_progress']}` | C1、C3、DC2 当前正式状态 |
| 第一阶段机器清单 | `{STAGE1_MANIFEST}` | `{HASHES['stage1_manifest']}` | 上游机器源身份和生成视图基线 |
| 第一阶段写入边界决定 | `{STAGE1_K5}` | `{HASHES['stage1_k5']}` | I7 与第二阶段 Writer 的唯一所有权边界 |
| 第一阶段旧写入器关闭节点 | `{STAGE1_I9}` | `{HASHES['stage1_i9']}` | 页面、接口、旧链接和旧任务重放的失败关闭合同 |
| 第一阶段身份汇合节点 | `{STAGE1_C1}` | `{HASHES['stage1_c1']}` | F1 的直接状态与候选输入 |
| 第一阶段组织接入汇合节点 | `{STAGE1_C3}` | `{HASHES['stage1_c3']}` | F2 的直接状态与候选输入 |
| 第一阶段必需交付终验节点 | `{STAGE1_DC2}` | `{HASHES['stage1_dc2']}` | F3 的直接状态、发布身份与晋升基线输入 |

项目根目录不是 Git 仓库。本包以这些文件校验值作为初始非 Git 来源基线。生成器在每次重建前复算全部校验值；任一输入漂移都会停止生成，必须先重新审查阶段边界和上游状态。

## 已确认事实

- 第一阶段 C1、C3、DC2 当前均为 `BLOCKED`，因此第二阶段三个跨阶段投影也全部保持 `BLOCKED`。
- {CURRENT_FACT_OBSERVED_AT} 观察到的源码事实：主线（`main`）为 `{CURRENT_MAIN_SHA}`，Stage-2 起始提交为 `{CURRENT_STAGE2_ORIGIN_COMMIT}`，包含 {CURRENT_STAGE2_SERVICE_COUNT} 个第二阶段服务文件、{CURRENT_STAGE2_TEST_COUNT} 个第二阶段测试文件和 {CURRENT_STAGE2_TEST_FUNCTION_COUNT} 个测试函数；候选分支 `codex/stage2-release-20260818` 已不存在。该事实属于源码/聚焦测试证据，不改变正式节点状态。
- 第一阶段 K5 已于 2026-08-15 接受：I7 只负责资源发现、只读镜像、同步补水和可信打开，I9 必须先把旧人工智能文档入口统一失败关闭。I9 当前仍为 `BLOCKED`，且第一阶段 C1 直接依赖 I9；因此 F1 不会仅凭决定记录提前接受。S3 仍依赖 F2，只能在组织接入投影接受后从该关闭态切换到唯一写入路由。
- 当前产品已经有统一成果结构和个人 Web/组织飞书的正文权威方向，但第一阶段身份、组织接入和最终生产验收尚未关闭。
- 当前会话、人工智能上下文和能力调用尚未形成统一可信的租户、工作区、Binding 与正文权威合同。
- 本轮已裁决页面授权不进入 `parseMediaSessionEnvelope`；采用独立只读入口状态接口承载页面与动作授权。该接口本身属于新的公共合同，必须经过 OpenAPI、服务端投影、客户端类型和合同测试同步。
- 本轮已确认字体自托管是境内部署主路径：DM Sans 全量自托管，Noto Sans SC 使用 `unicode-range` 切片或常用字子集，只预载拉丁子集；加载清单需补齐实际使用的 600，清除 800/850 视觉依赖，中文标题字距为 0。
- 当前主运行路径仍存在部署级全局飞书凭据消费，不能证明组织 A 与组织 B 的写入隔离。
- 近期活动存在全表读取问题；上下文路由验收前必须关闭该稳定跨租户失败类。
- 个人完整内容生产、组织按 Binding 智能写入、成果登记、写后回读、飞书编辑后再回读和真实双支线端到端均未形成正式接受证据。源码存在不等于节点接受。

## 阶段归属

- 第一阶段权威：身份、工作区、旧写入器关闭态、现有 Binding 试点、通用 Provision 和最小撤销。本包只投影 C1、C3、DC2，并读取 K5/I9 交接合同，不写上游状态。
- 第二阶段权威：本包拥有的个人内容闭环、共享人工智能上下文、唯一 Writer、组织飞书正文闭环和阶段二发布验收；第一阶段 I7 只能提供资源发现、只读镜像、同步补水和可信打开。
- 第三阶段权威：完整组织权限、审核协作、商业化、迁移、复杂删除和经营分析。本包只记录排除边界，不创建第三阶段节点。
"""


def _planning_kind(node_id: str, node: dict[str, object]) -> str:
    work_kind = str(node["work_kind"])
    if node.get("worker_transport") == "automatic-projection":
        return "automatic-projection"
    if work_kind in {"charter", "decision-acceptance", "fact-discovery"}:
        return "decision"
    if work_kind == "release-decision":
        return "release"
    if work_kind == "convergence":
        return "convergence"
    return "implementation" if work_kind not in {"validation"} else "validation"


def _planning_side_effects(node_id: str, node: dict[str, object]) -> list[str]:
    if node_id in {"O2", "O3", "O4", "O5"}:
        return ["lark-api"]
    if node_id == "DB":
        return ["deployment", "lark-api"]
    return []


def _planning_worker(node_id: str, node: dict[str, object]) -> dict[str, object] | None:
    if (
        node.get("execution_state") in {"IMPLEMENTED", "VERIFIED", "ACCEPTED"}
        or node.get("node_role") != "leaf"
        or node.get("execution_actor") != "codex"
        or node.get("worker_transport") != "external-codex-exec"
    ):
        return None
    return {
        "execution_identity": f"stage2:{node_id}:primary",
        "runtime": str(node.get("runtime_profile_requirement") or "implementation-runner"),
        "return_path": f"{REL_BUNDLE}/worker-executions/{node_id}/returns/{node_id}-primary.json",
        "resource_locks": [f"node:{node_id}"],
    }


def _planning_node(node_id: str, node: dict[str, object]) -> dict[str, object]:
    item = SPECS[node_id]
    kind = _planning_kind(node_id, node)
    side_effects = _planning_side_effects(node_id, node)
    transaction_models = {
        "database": "database-transaction",
        "external-api": "saga",
        "lark-api": "saga",
        "deployment": "immutable-release",
    }
    record: dict[str, object] = {
        "id": node_id,
        "goal": str(item["task"]),
        "dependencies": sorted(str(dep) for dep in node["hard_dependencies"]),
        "acceptance": str(item["acceptance"]),
        "owner": str(item["acceptance_authority"]),
        "kind": kind,
        "side_effects": side_effects,
        "transaction_models": {domain: transaction_models[domain] for domain in side_effects},
    }
    worker = _planning_worker(node_id, node)
    reasons: list[str] = []
    if worker is not None:
        reasons.append("multi-executor")
    if "lark-api" in side_effects:
        reasons.append("external-side-effect")
    if "deployment" in side_effects or kind == "release":
        reasons.append("production-release")
    if reasons:
        escalation: dict[str, object] = {"reasons": reasons}
        if worker is not None:
            record["worker"] = worker
        if "external-side-effect" in reasons:
            escalation.update(
                {
                    "evidence_contract": f"将 {node_id} 的外部动作、回读与同一 Binding 和候选身份绑定。",
                    "recovery_contract": "幂等重试、只补偿本节点拥有的资源，无法确认时进入 NEEDS_ATTENTION。",
                    "external_identity": f"isolated-lark-{node_id.lower()}",
                }
            )
        if "production-release" in reasons:
            escalation.update(
                {
                    "immutable_release_identity": f"REL-2-candidate-v{PLAN_VERSION}",
                    "promotion_baseline": "stage1-dc2-accepted-candidate",
                    "recovery_contract": "代码只切换不可变身份；数据库和飞书分别执行各自恢复或补偿合同。",
                }
            )
        record["escalation"] = escalation
    for field in (
        "execution_actor", "executor_route", "primary_executor", "primary_wrapper",
        "runtime_profile_requirement", "executor_attempt_policy",
    ):
        if field in node:
            record[field] = node[field]
    return record


def planning_compiler() -> dict[str, object]:
    release_nodes: dict[str, list[str]] = defaultdict(list)
    wave_nodes: dict[str, list[str]] = defaultdict(list)
    for node_id in NODES:
        release_nodes[str(RELEASE_SLICE_BY_NODE[node_id])].append(node_id)
        wave_nodes[str(WAVE_BY_NODE[node_id])].append(node_id)
    worker_count = sum(1 for node in NODES.values() if _planning_worker(str(node["node_id"]), node) is not None)
    implementation_counts = {
        release_id: sum(
            1 for node_id in node_ids
            if _planning_kind(node_id, NODES[node_id]) in {"implementation", "production-migration"}
        )
        for release_id, node_ids in release_nodes.items()
    }
    return {
        "planning_compiler_schema_version": 1,
        "classification": {
            "applicability": "ssot",
            "ssot_depth": "L2",
            "artifact_policy": "create-ssot",
            "selection_authority": "user",
            "rationale": "用户明确要求把第二阶段作为持久 SSOT；个人内容、组织飞书正文、共享人工智能路由、入口状态权限和真实外部验收必须在同一候选上协调。",
            "decision_versions": {"media.stage2.product-decisions": PRODUCT_DECISION_VERSION},
        },
        "external_systems": ["lark", "database", "browser"],
        "acceptance_layers": ["static-test", "local-runtime", "external-system", "physical-device"],
        "scheduling_model": "static-wave",
        "scheduling_hints": [],
        "release_boundary_compiler": {
            "boundary_required": False,
            "decision_authority": "user",
            "rationale": "个人和组织是同一第二阶段 WriterRouter 与候选的一部分，只有共享合同、两条子候选和唯一候选全部汇合后才能独立验收；因此保留一个 REL-2 发布切片并用执行波次表达容量。",
        },
        "macro_phases": [{"id": "PHASE-2", "title": "内容生产与人工智能文档分流第二宏观阶段", "release_ids": ["REL-2"]}],
        "release_slices": [{
            "id": "REL-2",
            "macro_phase_id": "PHASE-2",
            "title": "个人内容、组织飞书正文与统一写入路由",
            "user_value": "个人和组织创作者分别完成自己的正文生产闭环，并在同一候选上证明唯一文档写入权威。",
            "independent_acceptance": "个人子候选、组织子候选、共享路由和真实外部验收均可在本发布切片内完成。",
            "independent_failure": "任一支线失败时保持候选未晋升，不改写第一阶段已接受身份和组织接入候选。",
            "future_phase_required_for_success": False,
            "development_baseline": "stage2-development-base-v4",
            "promotion_baseline": "stage1-dc2-accepted-candidate",
            "release_candidate": "stage2-rel-2-candidate-v4",
            "acceptance_node_id": "DC",
            "release_candidate_artifact_id": "candidate:REL-2",
            "independent_proof_artifact_id": "proof:REL-2",
            "acceptance_command": "python3 -m pytest -q backend/tests frontend --stage2-acceptance",
            "node_ids": release_nodes["REL-2"],
        }],
        "waves": [
            {"id": wave_id, "release_id": "REL-2", "node_ids": node_ids}
            for wave_id, node_ids in sorted(wave_nodes.items())
        ],
        "nodes": [_planning_node(node_id, NODES[node_id]) for node_id in NODES],
        "artifacts": {
            "ssot_bundle": True,
            "generated_views": ["main", "dependency-topology", "execution-governance", "contracts-acceptance", "implementation-progress", "acceptance-execution"],
            "worker_ledger": worker_count > 0,
            "evidence_identity_registry": True,
            "resource_matrix": worker_count >= 2,
            "runner_registry": worker_count > 0,
        },
        "complexity_budget": {
            "authority": "user",
            "rationale": "一个发布切片、十五个执行波次和节点级外部副作用合同足以表达第二阶段；入口状态与字体工作作为既有节点的合同内容，不额外制造平行节点。",
            "limits": {
                "total_nodes": len(NODES),
                "implementation_nodes_per_release": max(implementation_counts.values()),
                "codex_worker_nodes": worker_count,
                "generated_views": 6,
            },
            "exception": None,
        },
        "goal_size_detector": {"split_required": False, "split_strategy": "none"},
    }


def write_execution_contracts() -> None:
    EXECUTION_CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    for stale in EXECUTION_CONTRACTS_DIR.glob("*.json"):
        stale.unlink()
    for node_id, node in NODES.items():
        payload: dict[str, object] = {
            "contract_id": node_id,
            "schema_version": 1,
            "node_id": node_id,
            "node_role": node["node_role"],
            "execution_actor": node["execution_actor"],
            "work_kind": node["work_kind"],
            "write_authority": node["write_authority"],
            "read_set": node["read_set"],
            "write_set": node["write_set"],
            "resource_claims": node["resource_claims"],
            "acceptance_commands": node["acceptance_commands"],
            "evidence_outputs": node["evidence_outputs"],
            "worker_transport": node["worker_transport"],
            "release_slice": node["release_slice"],
            "wave_id": node["wave_id"],
        }
        if node.get("executor_attempt_policy") is not None:
            payload["executor_attempt_policy"] = node["executor_attempt_policy"]
        if node.get("worker_registration") is not None:
            payload["worker_registration"] = node["worker_registration"]
        path = EXECUTION_CONTRACTS_DIR / f"{node_id}.json"
        write_json(path, payload)
        node["execution_contract_sha256"] = sha256(path)


def validate_model() -> None:
    node_ids = set(SPECS)
    if len({str(item["semantic_key"]) for item in SPECS.values()}) != len(SPECS):
        raise RuntimeError("duplicate semantic key")
    if any(source not in node_ids or target not in node_ids for source, target, _ in EDGES):
        raise RuntimeError("edge references unknown node")
    if len({(source, target) for source, target, _ in EDGES}) != len(EDGES):
        raise RuntimeError("duplicate edge")
    missing_batches = sorted(set(numeric_nodes()) - set(BATCHES))
    if missing_batches:
        raise RuntimeError(f"numeric nodes missing delivery batches: {missing_batches}")
    if set(node_id for node_id, node in NODES.items() if node["execution_state"] == "ACCEPTED") != {"A", "A1", "K"}:
        raise RuntimeError("unexpected accepted-node set")
    if any(node["execution_state"] != "BLOCKED" for node_id, node in NODES.items() if node_id not in {"A", "A1", "K"}):
        raise RuntimeError("phase-2 nodes must remain blocked at planning baseline")
    edge_pairs = {(source, target) for source, target, _ in EDGES}
    required_projection_edges = {
        ("F1", "B"),
        ("F1", "C1"),
        ("F2", "S3"),
        ("F2", "O1"),
        ("F3", "C"),
    }
    missing_projection_edges = sorted(required_projection_edges - edge_pairs)
    if missing_projection_edges:
        raise RuntimeError(f"missing cross-stage projection edges: {missing_projection_edges}")
    if UPSTREAM_PROJECTIONS != {"F1": "C1", "F2": "C3", "F3": "DC2"}:
        raise RuntimeError(f"unexpected upstream projection map: {UPSTREAM_PROJECTIONS}")
    if "F2" not in NODES["S3"]["hard_dependencies"]:
        raise RuntimeError("S3 must remain blocked on the stage-1 C3 projection through F2")
    expected_transports = {
        "F1": "automatic-projection",
        "F2": "automatic-projection",
        "F3": "automatic-projection",
        "S": "automatic-projection",
        "C8": "automatic-projection",
        "O6": "automatic-projection",
        "C": "automatic-projection",
        "DA": "deterministic-local",
        "O5": "external-manual",
        "DB": "external-manual",
        "DC": "external-manual",
    }
    for node_id, expected_transport in expected_transports.items():
        if NODES[node_id]["worker_transport"] != expected_transport:
            raise RuntimeError(
                f"unexpected transport for {node_id}: "
                f"expected {expected_transport}, got {NODES[node_id]['worker_transport']}"
            )
    for node_id in {"A", "A1", "K"}:
        if NODES[node_id]["worker_transport"] != "historical-unregistered":
            raise RuntimeError(f"historical node {node_id} must not receive a worker")
    for node_id in {"S", "C8", "O6", "C"}:
        if NODES[node_id]["execution_actor"] != "orchestrator":
            raise RuntimeError(f"thin convergence node {node_id} must be orchestrator-owned")
        if NODES[node_id]["worker_transport"] != "automatic-projection":
            raise RuntimeError(f"thin convergence node {node_id} must use zero-process projection")


def build() -> None:
    verify_source_hashes()
    validate_model()
    for directory in (
        NODES_DIR,
        EDGES_DIR,
        ASSUMPTIONS_DIR,
        CONFLICTS_DIR,
        EXECUTION_CONTRACTS_DIR,
        VIEW_SOURCES,
        GENERATED_VIEWS,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    clear_machine_fragments()

    # Contracts are written first so every node shard can bind the exact
    # content hash without a circular manifest dependency.
    write_execution_contracts()

    for node_id, payload in NODES.items():
        write_json(NODES_DIR / f"{node_id}.json", payload)
    for payload in EDGE_RECORDS:
        write_json(EDGES_DIR / f"{payload['edge_id']}.json", payload)
    write_json(MACHINE / "planning-compiler.json", planning_compiler())

    views = [
        ("main", "00-main.md", "../ssot-development-paths.md", main_view()),
        ("dependency-topology", "10-topology.md", "../generated-views/10-dependency-topology.md", topology_view()),
        ("execution-governance", "20-execution.md", "../generated-views/20-execution-governance.md", execution_view()),
        ("contracts-acceptance", "30-acceptance.md", "../generated-views/30-node-contracts-and-acceptance.md", acceptance_view()),
        ("implementation-progress", "40-progress.md", "../implementation-progress.md", progress_view()),
        ("acceptance-execution", "40-acceptance-execution.md", "../generated-views/40-acceptance-execution.md", acceptance_execution_view()),
    ]
    generated_views = []
    for view_id, source_name, output, content in views:
        source_path = VIEW_SOURCES / source_name
        write_text(source_path, content)
        output_path = (MACHINE / output).resolve()
        write_text(output_path, content)
        if view_id == "implementation-progress":
            write_text(MACHINE / "implementation-progress.md", content)
        generated_views.append(
            {
                "view_id": view_id,
                "source": f"view-sources/{source_name}",
                "source_sha256": sha256(source_path),
                "output": output,
            }
        )

    manifest = {
        "ssot_schema_version": SSOT_SCHEMA_VERSION,
        "artifact_class": "ssot-development",
        "plan_version": PLAN_VERSION,
        "dag_version": DAG_VERSION,
        "interface_freeze_version": INTERFACE_FREEZE_VERSION,
        "node_contract_version": NODE_CONTRACT_VERSION,
        "machine_validation_profile": "full",
        "parallelism_contract_version": 1,
        "execution_contract_validation": "strict",
        "main_thread_policy": "orchestration-only",
        "main_thread_source_write": False,
        "execution_contracts_dir": "execution-contracts",
        "planning_compiler": "planning-compiler.json",
        "actor_pools": {
            "codex-primary": {"actor": "codex", "capacity": 12},
            "human-authority": {"actor": "human", "capacity": 4},
            "external-acceptance": {"actor": "external-system", "capacity": 2},
            "orchestrator": {"actor": "orchestrator", "capacity": 1},
        },
        "executor_policy": {
            "schema_version": 3,
            "allowed_primary_executors": PRIMARY_EXECUTOR_OPTIONS,
            "default_primary_executor": PRIMARY_EXECUTOR_DEFAULT,
            "default_writable_parallel_executor": PRIMARY_EXECUTOR_DEFAULT,
            "default_writable_wrapper": PRIMARY_EXECUTOR_OPTIONS[PRIMARY_EXECUTOR_DEFAULT],
            "fallback_executor": "l3",
            "fallback_wrapper": "run-l3.sh",
            "primary_retry_limit": 1,
            "l3_escalation_limit": 1,
        },
        "upstream_projections": [
            {
                "projection_node": projection_node,
                "source_bundle": STAGE1_BUNDLE.relative_to(SOURCE_ROOT).as_posix(),
                "source_node": source_node,
                "source_manifest_sha256": HASHES["stage1_manifest"],
                "source_node_sha256": HASHES[f"stage1_{source_node.lower()}"],
                "required_state": "ACCEPTED",
            }
            for projection_node, source_node in UPSTREAM_PROJECTIONS.items()
        ],
        "cross_stage_contracts": [
            {
                "contract_id": "stage1-writer-fail-closed-to-stage2-writer-router",
                "decision_node": "K5",
                "decision_node_sha256": HASHES["stage1_k5"],
                "closure_node": "I9",
                "closure_node_sha256": HASHES["stage1_i9"],
                "closure_required_via_projection": "F1",
                "organization_route_unlock_projection": "F2",
                "handoff_target_node": "S3",
                "closed_error": "capability_unavailable_until_writer_migration",
                "handoff_rule": "replace the accepted fail-closed state atomically; never enable a parallel legacy writer",
            }
        ],
        "generated_main": "../ssot-development-paths.md",
        "generated_views": generated_views,
        "nodes_dir": "nodes",
        "edges_dir": "edges",
        "assumptions_dir": "assumptions",
        "conflicts_dir": "conflicts",
    }
    write_json(MACHINE / "manifest.json", manifest)
    write_text(BUNDLE / "source-notes.md", source_notes())
    write_json(
        BUNDLE / "ssot-archive.json",
        {
            "schema_version": 1,
            "artifact_class": "ssot-development",
            "artifact_date": "2026-08-15",
            "project_name": "openclaw-media",
            "ssot_name": "media-c-b-stage-2-content-ai-document-routing",
            "main_document": "ssot-development-paths.md",
            "problem_documents": ["openproblem.md"],
        },
    )


if __name__ == "__main__":
    build()
