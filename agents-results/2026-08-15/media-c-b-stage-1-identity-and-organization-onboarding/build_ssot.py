#!/usr/bin/env python3
"""Build the phase-1 Media C/B SSOT machine source and generated view sources."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path


NODE_ID_RE = re.compile(r"^[A-Z]+[1-9][0-9]*$")


def is_numeric_node(node_id: str) -> bool:
    """Return whether a node is an independently inventoried leaf label."""

    return bool(NODE_ID_RE.fullmatch(node_id))


def artifact_identity(node_id: str) -> str:
    """Use a leaf deliverable ID only for numeric leaf nodes.

    Control, convergence, and release projection nodes still produce a machine
    artifact, but that artifact is not a parallel leaf deliverable.
    """

    return f"DL-{node_id}" if is_numeric_node(node_id) else f"ART-{node_id}"


BUNDLE = Path(__file__).resolve().parent
PROJECT_ROOT = BUNDLE.parents[2]
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
    "codex exec -C '/Users/vsiyo/Desktop/创业项目/自媒体创作Agent' "
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
CANONICAL = (
    "/Users/vsiyo/Library/Mobile Documents/iCloud~md~obsidian/Documents/日记/"
    "公共开发集/media/2026-08-07/media-visual-fix/agents-results/2026-08-07/"
    "media-cb-web-document-preview/ssot-development-paths.md"
)
CANONICAL_PROGRESS = str(Path(CANONICAL).with_name("implementation-progress.md"))

HASHES = {
    "audit": "d5dad457861e413ff3963da568870be907495de50c33486810fa3dbdc0d92f98",
    "attachment": "a293eb32e09589ae2e60fd07362f20ce296b70725f55ad9368c6bc63e673f8b8",
    "structure_review": "3ffc4363c735a1ca2bed7b393e48516b4aa9a5494b1f9b30f952e8eff65ab6f5",
    "latest_review": "97000cc86e80993997153e0fb193ee877daea85c5695a60cf1645bf40596d471",
    "canonical": "0f621ee97d66fb3ec4be7b8be7bc306fda4a269f81382ad232afb1187c16ac47",
    "canonical_progress": "a30bdf105e5b2b8367ff19603e19a28ad787e9743fef033e10a270a65d53d5db",
    "b_candidate_manifest": "a5e34064d554fe6a11b93f608b23202e737b40eac9dcedc4388c18dc952710be",
    "b_openapi": "6d325c6736389b7dde8eb1e5ef0c91e166d4a68578d05324dad3cadf294af9d0",
    "b_contract_test": "c1fbb5b6655ff2f4bb6f90152a8ab6705d77f6d2744744014f99e0d9dafa01a8",
    "b_validation": "52f6f4f8ec3e4d4ac4111b455424aa6ac52f00427146defc7eb09b37e22b8bea",
    "b_retry_return": "e70fdecba336c7e42ae5e9a1004e9187fea29c3fe03d90e0d6dd9f77bf42fd0a",
    "ga1_receipt": "8094d5a1acaae50f67e72cf679ee2b6666e4132e623ac018350156a9b5397707",
    "g1_receipt": "a9ee7f1b32c33755eda946df8cc9ed7e6edd181742defd955777766dd52ea8c9",
    "runner_registry": "ad3af167b07dd0287ea1f22dd3f90d893d7cffee16aea5082303d7e7b331e0ed",
    "runner_launcher": "30f15c7c9999b9d2100906aaf364e38412adeec60fb7a43263f6de6f363b5bb7",
    "m1_tool": "4c0cfef4e24625dfb671fe4736a04725432d41a4243d0be1f04d5303135a42a2",
    "m1_schema": "ad8aa24bf7481da33b26bf05e7dad37dec4ba2e9b4b2dbbf0cd9c73a1a94e7ce",
    "m1_tests": "11c13d6197b1fa61735f6d81ee8f78e92e38a2dd2ab1d9b48d0498aaded9cc09",
    "m1_validation": "05b724f6d4b252705a8ae4d6899ec8eae4867ff3b09f4543b12cef5e9269115b",
    "m1_fixture_manifest": "dece265db4b42a0ddba574932c2916aaa1efa5604b45f0243cb648e5265c4eb0",
    "i2_lifecycle": "d149a683ee0ef2825e5151005d0679f0d883e62b5810aeede637a5c87e7e1e6d",
    "i2_lifecycle_receipt": "4b4b9cee5fcf5c04367d0f72e25322e475388e1ec95d8b2c7b662300691046b5",
    "i2_validation": "1330937b7f5501fd1c05140118a20ae7f789eb3d74ee474d9828c3c647a8785d",
    "i2_lifecycle_impl": "ca419df8c77318d4ce15d873add236248be26147225363ed29e5731cb8d09013",
    "i2_account_api": "759cdd8c311e19e47cc291f9c97b22be7892a314d1f7b62bc186476c246a24bf",
    "i2_http_api": "6805c5fba5492916bc079bce87e4ed4c1633ab0c649f37d8fc0bf81a4353438f",
    "t1_contract": "775ddfa6fcfb5e04a931dfa5e03dfd08891365fc4491c16d8a6e49ede1c58611",
    "t1_harness": "13219785db38866e00387d4ce09553ef05c34ab21b5c6a4fbf9709f583d73009",
    "t1_route_gate": "6fa14dc5655ac77bd1a78bad0a132ff8ed81ac2fca8aafb2d5bb69448086f236",
    "t1_shared_test": "80759c80b90339095a255c5c1d6a831e4fbcd74e3e598fcd7a1ec8fe57d64e8d",
    "t1_validation": "da89e5418b471a255f0dc20e08085f7470f18875aefe1bb57453bca106019fac",
    "t1_receipt": "a79017ede7c186a616ab842c3c4df5c384d551e50f84155a43338ff61956f131",
    "t1_acceptance_contract": "3b19b29cdadd84cff812522f740f4a66c8205bf9e5d356b16bdbd11f63666342",
    "t1_acceptance_run": "3c9a867f75ba18ff90539654576eee4ee645507f7b1d91ad9e403e2482b4157f",
    "ma1_migration": "61e739379c9e81d3d1a5bb7239e3695d1d709e2109eb1fd816b078bacc6da475",
    "ma1_manifest": "6dd8c8034b8a3546c56bc53ac3454843f147ac35a3619037fa2d051de1efd5cd",
    "ma1_tests": "1d8dc2dc6516bef8007d4f2903c28495bb29cab7cfb1ca8a38658f8321051de0",
    "ma1_runner_tests": "dc2dea9a677fb77f0db3c8c31f27aff04cefbfeac43e658fc402831510125943",
    "ma1_receipt": "8056704a4c314bd0965767d65fe0499f9b90e66820289be1581d8d7f33bcc28a",
    "i1_login_html": "7ace5ecb3b9a14d8bcf4cd7c86bebfc8892857a31b8edfd929a3c3f00041b12d",
    "i1_login_js": "1ed4259a8ab4f492a1d323c4c4867f061843c0d4b1fb4bb2ea02533c9836f6e2",
    "i1_register_html": "12d4309211434786d403d7c987633d9a85bbe49632a3cdbd4e9e5325d570a1c6",
    "i1_verify_html": "84d20bf30aa862c6efb90a56baf04bab3e0db96c4c2fb3249c162c1a5b1eba5d",
    "i1_recover_html": "b2126f3786da69e7fc113504c89667a9d4308d41776399957531e98f415cfa8e",
    "i1_reset_html": "864097f80bcf2273971491f84ea92252a82df9fc79c8ec12947e56a94bfe725c",
    "i1_auth_css": "a428cd86b19fbd0f89bb72460d441fa27ca066bd45a591845d03e3e2cf32aa4b",
    "i1_vite_config": "45dffceaada3e9f9111ce2dfa5ed047e20fb5e7655710313951a7ccbe9407d4c",
    "i1_nginx": "4410457643280b3ac967bcd06971e2300e1499ed15edb2c6677fd38d103ac728",
    "i1_identity_qa": "d26f6c48108286e5647535994536066fa9f6db0d029aa8b1ff2d355b3ca28c9a",
    "i1_login_qa": "5b61cf52ae421e1dbe1d37d34c7c43ca3c492224aa28758c4ae40eb265d24206",
    "i1_package": "2d2a10a68bee189af24811ce4f314d60ae7af7450f61afb4f37ba8c849036c41",
    "i1_lockfile": "f3dd4e9e3671ff2d774938b96bfacf083bdfaad454ee19d8effc9d5b96541dd7",
    "i1_receipt": "54a342e69719f97a20bf5968e8ca8aaf5e4384d13abe347569d6491e7f48ab09",
}
OBSERVED_AT = "2026-08-15T20:37:42+08:00"
USER_DECISION_DATE = "2026-08-15"
K6_DECISION_DATE = "2026-08-16"
VERSIONS = "5/5/4/5"

LOCAL_DECISION_RECORDS: dict[str, dict[str, object]] = {
    "K1": {
        "approved_value": {
            "personal_authentication": "平台独立认证；个人第一版不要求飞书登录",
            "document_storage_and_preview": "所有交付文档均在云端保存和预览；个人路径使用平台内部成果容器",
            "identity_linking": "平台账号与飞书成员身份只能显式关联，不按邮箱或姓名自动合并",
        },
        "approval_authority": "user",
        "approval_evidence": "用户在 2026-08-15 明确答复：个人第一版不用飞书登录，所有交付文档在云端储存和预览。",
        "approved_at": USER_DECISION_DATE,
        "scope": "第一阶段个人登录、会话分流和第二阶段个人云端成果入口",
        "existing_data_handling": "不自动合并既有平台账号与飞书成员；需要关联时使用显式、可审计流程",
    },
    "K2": {
        "approved_value": {
            "traffic_policy": "发布后直接向全部合格用户开放",
            "cutover": "单一路径硬切换",
            "retained_controls": ["发布前门禁", "全局紧急停止", "外部写入停止"],
            "forbidden_controls": ["租户白名单", "灰度发布", "长期功能开关", "双路径"],
        },
        "approval_authority": "user",
        "approval_evidence": "用户在 2026-08-15 要求直接让所有用户使用，并采用最方便开发、最彻底干净的版本。",
        "approved_at": USER_DECISION_DATE,
        "scope": "Release 1A 与 Release 1B 的候选晋升、生产切换和紧急止损",
        "existing_data_handling": "切换前完成门禁和迁移；切换后清除旧授权与旧运行路径，不保留分租户长期兼容",
    },
    "K3": {
        "approved_value": {
            "member_onboarding": "普通成员首次完成服务端飞书授权时即时建立",
            "unique_external_member_field": "open_id",
            "field_authority": "仅接受服务端飞书授权结果；前端不得提交或覆盖 open_id",
            "directory_sync": "完整目录同步后移为非阻塞独立能力",
        },
        "approval_authority": "user",
        "approval_evidence": "用户在 2026-08-15 选择即时建立，并要求只使用一个唯一字段。",
        "approved_at": USER_DECISION_DATE,
        "scope": "Release 1B 普通成员首次进入、幂等成员关系建立与外部身份唯一约束",
        "existing_data_handling": "歧义或缺失 open_id 的存量不自动合并；先回填或人工消歧，再允许激活",
    },
    "K4": {
        "approved_value": {
            "recent_activity_ownership": "租户私有数据",
            "required_controls": ["租户归属字段", "存量前向迁移", "服务端强制过滤", "跨租户负例"],
            "unowned_legacy_rows": {
                "provable_owner": "回填到可证明租户",
                "conflicting_evidence": "隔离并进入 NEEDS_ATTENTION",
                "no_evidence": "对所有租户不可见",
            },
        },
        "approval_authority": "user",
        "approval_evidence": "用户在 2026-08-15 明确确认近期活动属于租户私有数据。",
        "approved_at": USER_DECISION_DATE,
        "scope": "近期活动的读取、写入、迁移、审计和跨租户拒绝",
        "existing_data_handling": "可证明归属则回填；证据冲突则隔离并进入 NEEDS_ATTENTION；完全无证据则对所有租户不可见",
    },
    "K5": {
        "approved_value": {
            "stage1_resource_resolver": ["组织资源发现", "网页只读镜像", "同步补水", "可信打开"],
            "stage1_ai_document_write": "页面入口隐藏且 API 返回 capability_unavailable_until_writer_migration",
            "writer_owner": "第二阶段唯一 WriterRouter",
        },
        "approval_authority": "user",
        "approval_evidence": "用户在 2026-08-15 对第一阶段资源解析边界选择推荐方案。",
        "approved_at": USER_DECISION_DATE,
        "scope": "第一阶段 I7 与第二阶段统一人工智能文档写入路由的互斥所有权",
        "existing_data_handling": "Release 1A 前页面和 API 统一关闭全局 Writer；第二阶段只由唯一 WriterRouter 从关闭态接管",
    },
    "K6": {
        "approved_value": {
            "login": {
                "accepted_identifiers": ["唯一用户名", "已验证邮箱"],
                "credential": "密码",
                "eligible_account_status": "ACTIVE",
                "failure_response": "用户名、邮箱、密码或账号状态不符合时统一返回凭据无效，不暴露账号是否存在",
                "pending_account_response": "只有密码校验通过后，才可提示该账号需要完成邮箱验证并提供重发入口",
                "success": "轮换会话标识并进入个人工作区",
                "feishu_dependency": "none",
            },
            "registration": {
                "availability": "个人用户可自助注册；只创建平台个人账号，不创建组织身份或飞书身份",
                "required_fields": ["唯一用户名", "唯一邮箱", "密码"],
                "initial_status": "PENDING_EMAIL_VERIFICATION",
                "email_required": True,
                "email_unique_after_normalization": True,
                "username_unique_after_normalization": True,
                "password_policy": {
                    "minimum_characters": 12,
                    "maximum_characters": 128,
                    "composition_rule": "不强制大小写、数字或符号组合",
                    "compromised_passwords": "拒绝已知泄露或常见弱密码",
                    "paste_and_password_manager": "允许",
                },
                "session_after_submit": "不得签发完整登录会话",
                "workspace_creation": "邮箱首次验证成功时幂等建立个人工作区",
                "public_response": "除用户名冲突需要用户改名外，提交后统一提示检查邮箱，不暴露邮箱是否已注册",
            },
            "email_verification": {
                "validity": "24 hours",
                "single_use": True,
                "resend_policy": "重发后立即撤销此前全部未使用验证链接，只有最新一封有效",
                "resend_public_response": "无论账号是否存在或是否仍待验证，都返回相同提示",
                "token_entropy_minimum_bits": 256,
                "server_storage": "只保存令牌摘要，不保存可直接使用的原值",
                "success_transition": "PENDING_EMAIL_VERIFICATION -> ACTIVE",
                "success_session": "验证成功后返回个人登录入口，不自动登录",
            },
            "password_recovery": {
                "accepted_identifiers": ["用户名", "邮箱"],
                "public_response": "无论账号是否存在、是否激活或邮箱是否已验证，都返回相同提示",
                "delivery_eligibility": "仅 ACTIVE 且拥有已验证邮箱的账号接收找回邮件",
                "validity": "30 minutes",
                "single_use": True,
                "latest_token_only": True,
                "token_entropy_minimum_bits": 256,
                "server_storage": "只保存令牌摘要，不保存可直接使用的原值",
                "reset_result": "撤销该账号全部旧会话和全部未使用找回令牌，不自动登录并返回个人登录入口",
            },
            "account_statuses": ["PENDING_EMAIL_VERIFICATION", "ACTIVE", "SUSPENDED"],
            "rate_limiting": "登录、验证邮件重发和找回请求必须同时按来源与账号标识限流；具体阈值由 B 编译为安全配置并由 T1 锁定负例",
            "session": {
                "type": "服务端不透明会话",
                "absolute_lifetime": "8 hours",
                "remember_me": False,
                "rotation": ["登录成功", "权限变化", "密码重置"],
                "cookie": ["HttpOnly", "Secure", "SameSite=Lax"],
                "cross_site_request_protection": "所有修改数据的请求校验与当前会话绑定且可轮换的保护令牌",
            },
            "existing_accounts": {
                "login": "既有平台账号可从新个人入口继续使用用户名和密码登录",
                "legacy_email": "既有邮箱不得自动视为已验证；验证前不能用邮箱登录或找回密码",
                "identity_merge": "不得按邮箱或姓名自动合并平台账号与飞书身份",
            },
            "support_boundary": {
                "allowed": ["重发标准验证或找回邮件", "撤销账号会话", "引导用户完成标准流程"],
                "forbidden": ["读取用户密码", "生成临时密码", "绕过邮箱验证", "代替用户绑定飞书身份"],
            },
            "identity_linking": "已登录用户主动发起飞书授权并二次确认后才允许绑定",
            "forbidden_paths": [
                "旧 Media 密码登录接口继续返回 404",
                "旧 Media 改密接口继续返回 404",
                "禁止按邮箱或姓名自动合并平台账号与飞书身份",
                "不提供记住我、短信找回、客服临时密码或验证成功后自动登录",
            ],
        },
        "approval_authority": "user",
        "approval_evidence": "用户在 2026-08-16 对个人平台账号具体如何登录、注册和找回明确选择推荐方案。",
        "approved_at": K6_DECISION_DATE,
        "scope": "第一阶段个人登录、自助注册、账号找回、浏览器会话、跨站请求保护和显式身份关联",
        "existing_data_handling": "既有平台账号继续从新个人入口用用户名登录；旧邮箱在完成验证前不能用于登录或找回；不恢复旧 Media 密码接口，也不自动合并平台账号与飞书身份",
    },
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


def evidence_identity(kind: str) -> dict[str, object]:
    if kind == "A":
        return {
            "evidence_level": "source",
            "source_revision": "user-request-2026-08-15",
            "artifact_hashes": [
                f"sha256:{HASHES['attachment']}",
                f"sha256:{HASHES['structure_review']}",
                f"sha256:{HASHES['latest_review']}",
            ],
            "environment_identity": "current Codex task and local attachment",
            "runtime_release_id": "n/a",
            "actor_role": "user and planning authority",
            "account_or_tenant": "n/a",
            "device_or_browser": "n/a",
            "mock_or_fixture": False,
            "observed_at": OBSERVED_AT,
            "acceptance_contract": "Phase-1 SSOT restructuring charter v4",
        }
    if kind == "A1":
        return {
            "evidence_level": "source",
            "source_revision": "audit-and-canonical-hash-baseline-2026-08-15",
            "artifact_hashes": [
                f"sha256:{HASHES['audit']}",
                f"sha256:{HASHES['canonical']}",
                f"sha256:{HASHES['canonical_progress']}",
                f"sha256:{HASHES['latest_review']}",
            ],
            "environment_identity": "local source files; non-Git project root",
            "runtime_release_id": "n/a",
            "actor_role": "main orchestrator read-only",
            "account_or_tenant": "redacted / not read",
            "device_or_browser": "n/a",
            "mock_or_fixture": False,
            "observed_at": OBSERVED_AT,
            "acceptance_contract": "Phase-1 source and runner baseline v4",
        }
    if kind == "B":
        return {
            "evidence_level": "local-runtime",
            "source_revision": f"sha256:{HASHES['b_candidate_manifest']}",
            "artifact_hashes": [
                f"sha256:{HASHES['b_openapi']}",
                f"sha256:{HASHES['b_contract_test']}",
                f"sha256:{HASHES['b_validation']}",
                f"sha256:{HASHES['b_retry_return']}",
            ],
            "environment_identity": "local macOS non-Git merge-candidate-v4 backend with existing Python virtualenv",
            "runtime_release_id": "n/a",
            "actor_role": "Luna worker with supervisor acceptance",
            "account_or_tenant": "n/a",
            "device_or_browser": "n/a",
            "mock_or_fixture": False,
            "observed_at": "2026-08-16T07:59:05Z",
            "acceptance_contract": "B-retry-2 frozen contract validation; 7 passed",
        }
    if kind == "GA1":
        return {
            "evidence_level": "source",
            "source_revision": f"sha256:{HASHES['runner_registry']}",
            "artifact_hashes": [
                f"sha256:{HASHES['runner_launcher']}",
                f"sha256:{HASHES['ga1_receipt']}",
            ],
            "environment_identity": "local runner profile registry and absolute launchers",
            "runtime_release_id": "n/a",
            "actor_role": "execution environment owner",
            "account_or_tenant": "n/a",
            "device_or_browser": "n/a",
            "mock_or_fixture": False,
            "observed_at": "2026-08-16T15:10:35+08:00",
            "acceptance_contract": str(SPECS[kind]["acceptance"]),
        }
    if kind == "G1":
        return {
            "evidence_level": "local-runtime",
            "source_revision": f"sha256:{HASHES['runner_registry']}",
            "artifact_hashes": [
                f"sha256:{HASHES['runner_launcher']}",
                f"sha256:{HASHES['g1_receipt']}",
            ],
            "environment_identity": "local runner profile capability probes",
            "runtime_release_id": "n/a",
            "actor_role": "outer orchestrator deterministic verification",
            "account_or_tenant": "local fixtures only",
            "device_or_browser": "n/a",
            "mock_or_fixture": True,
            "observed_at": "2026-08-16T07:36:47.577035+00:00",
            "acceptance_contract": str(SPECS[kind]["acceptance"]),
        }
    if kind == "M1":
        return {
            "evidence_level": "local-runtime",
            "source_revision": "stage1-no-git-rebuild-v4",
            "artifact_hashes": [
                f"sha256:{HASHES['m1_tool']}",
                f"sha256:{HASHES['m1_schema']}",
                f"sha256:{HASHES['m1_tests']}",
                f"sha256:{HASHES['m1_validation']}",
                f"sha256:{HASHES['m1_fixture_manifest']}",
            ],
            "environment_identity": "local non-Git project root with existing merge-candidate-v4 Python virtualenv",
            "runtime_release_id": "n/a",
            "actor_role": "main orchestrator deterministic local execution",
            "account_or_tenant": "n/a",
            "device_or_browser": "n/a",
            "mock_or_fixture": True,
            "observed_at": "2026-08-16T20:28:37+08:00",
            "acceptance_contract": "M1-remediation-1 frozen validation; 32 passed",
        }
    if kind == "I2":
        return {
            "evidence_level": "local-runtime",
            "source_revision": "stage1-i2-auth-routes-locked-2026-08-17",
            "artifact_hashes": [
                f"sha256:{HASHES['i2_lifecycle_impl']}",
                f"sha256:{HASHES['i2_account_api']}",
                f"sha256:{HASHES['i2_http_api']}",
                f"sha256:{HASHES['i2_lifecycle']}",
                f"sha256:{HASHES['i2_validation']}",
            ],
            "environment_identity": "local macOS isolated stage1-i2 root with existing Python virtualenv",
            "runtime_release_id": "n/a",
            "actor_role": "main orchestrator deterministic rerun",
            "account_or_tenant": "local fixtures only",
            "device_or_browser": "n/a",
            "mock_or_fixture": True,
            "observed_at": "2026-08-17T00:01:14+08:00",
            "acceptance_contract": "共享路由验收合同（T1-AUTH-ROUTES）运行 20260817T031500Z-local-final-f4a5b6；I2 20 passed, 16 skipped；保护基线 LOCKED；正式接受待完成",
        }
    if kind == "T1":
        return {
            "evidence_level": "local-runtime",
            "source_revision": "stage1-t1-auth-routes-locked-2026-08-17",
            "artifact_hashes": [
                f"sha256:{HASHES['t1_contract']}",
                f"sha256:{HASHES['t1_harness']}",
                f"sha256:{HASHES['t1_route_gate']}",
                f"sha256:{HASHES['t1_shared_test']}",
                f"sha256:{HASHES['t1_validation']}",
                f"sha256:{HASHES['i2_lifecycle']}",
            ],
            "environment_identity": "local macOS isolated stage1-t1 root with existing Python virtualenv",
            "runtime_release_id": "n/a",
            "actor_role": "main orchestrator deterministic rerun",
            "account_or_tenant": "local fixtures only",
            "device_or_browser": "n/a",
            "mock_or_fixture": True,
            "observed_at": "2026-08-17T00:01:14+08:00",
            "acceptance_contract": "共享路由验收合同（T1-AUTH-ROUTES）运行 20260817T031500Z-local-final-f4a5b6；T1 15 passed；路由一致性 GREEN；保护基线 LOCKED；正式接受待完成",
        }
    if kind == "MA1":
        return {
            "evidence_level": "local-runtime",
            "source_revision": "stage1-ma1-migration-isolated-root-2026-08-17",
            "artifact_hashes": [
                f"sha256:{HASHES['ma1_migration']}",
                f"sha256:{HASHES['ma1_manifest']}",
                f"sha256:{HASHES['ma1_tests']}",
                f"sha256:{HASHES['ma1_runner_tests']}",
                f"sha256:{HASHES['ma1_receipt']}",
            ],
            "environment_identity": "local macOS isolated stage1-ma1-migration root with existing Python virtualenv",
            "runtime_release_id": "n/a",
            "actor_role": "main orchestrator deterministic local execution",
            "account_or_tenant": "n/a",
            "device_or_browser": "n/a",
            "mock_or_fixture": True,
            "observed_at": "2026-08-17T00:47:00+08:00",
            "acceptance_contract": "MA1 frozen validation receipt EV-MA1-RERUN-20260817; 27 passed, 3 subtests passed",
        }
    if kind == "I1":
        return {
            "evidence_level": "local-runtime",
            "source_revision": "stage1-i1-isolated-root-2026-08-17",
            "artifact_hashes": [
                f"sha256:{HASHES['i1_login_html']}",
                f"sha256:{HASHES['i1_login_js']}",
                f"sha256:{HASHES['i1_register_html']}",
                f"sha256:{HASHES['i1_verify_html']}",
                f"sha256:{HASHES['i1_recover_html']}",
                f"sha256:{HASHES['i1_reset_html']}",
                f"sha256:{HASHES['i1_auth_css']}",
                f"sha256:{HASHES['i1_vite_config']}",
                f"sha256:{HASHES['i1_nginx']}",
                f"sha256:{HASHES['i1_identity_qa']}",
                f"sha256:{HASHES['i1_login_qa']}",
                f"sha256:{HASHES['i1_package']}",
                f"sha256:{HASHES['i1_lockfile']}",
                f"sha256:{HASHES['i1_receipt']}",
            ],
            "environment_identity": "local macOS isolated stage1-i1 root with existing Node dependencies",
            "runtime_release_id": "n/a",
            "actor_role": "main orchestrator deterministic local execution",
            "account_or_tenant": "n/a",
            "device_or_browser": "source QA and local Vite build; no external browser acceptance",
            "mock_or_fixture": True,
            "observed_at": "2026-08-17T00:47:00+08:00",
            "acceptance_contract": "I1 frozen validation receipt EV-I1-RERUN-20260817; stage1_identity_entry=PASS; build:media passed",
        }
    if kind in LOCAL_DECISION_RECORDS:
        approved_at = str(LOCAL_DECISION_RECORDS[kind]["approved_at"])
        return {
            "evidence_level": "source",
            "source_revision": (
                f"user-decision-k6-{approved_at}"
                if kind == "K6"
                else "user-five-decisions-2026-08-15"
            ),
            "artifact_hashes": [
                f"sha256:{HASHES['attachment']}",
                f"sha256:{HASHES['structure_review']}",
            ],
            "environment_identity": "current Codex task; user decision message",
            "runtime_release_id": "n/a",
            "actor_role": "user and product decision authority",
            "account_or_tenant": "n/a",
            "device_or_browser": "n/a",
            "mock_or_fixture": False,
            "observed_at": approved_at if kind == "K6" else USER_DECISION_DATE,
            "acceptance_contract": str(SPECS[kind]["acceptance"]),
        }
    return {
        "evidence_level": "source",
        "source_revision": "user-approved-three-stage-plan-2026-08-15",
        "artifact_hashes": [
            f"sha256:{HASHES['attachment']}",
            f"sha256:{HASHES['audit']}",
            f"sha256:{HASHES['structure_review']}",
        ],
        "environment_identity": "current Codex task and declared input files",
        "runtime_release_id": "n/a",
        "actor_role": "user and product decision authority",
        "account_or_tenant": "n/a",
        "device_or_browser": "n/a",
        "mock_or_fixture": False,
        "observed_at": OBSERVED_AT,
        "acceptance_contract": "Phase-1 stable product decisions v2 under plan v4",
    }


def worker_registration(
    node_id: str,
    task: str,
    level: str,
    dispatch: str,
    *,
    executor: str | None = None,
) -> dict[str, object]:
    """Build an auditable external-worker registration.

    ``level`` is the governance level recorded by the source model.  The
    selected primary remains an explicit Luna/Terra switch; a governance L3
    node does not silently replace that primary with the L3 escalation route.
    """

    selected = executor or PRIMARY_EXECUTOR_DEFAULT
    wrapper = PRIMARY_WRAPPER_PATHS.get(selected, L3_WRAPPER)
    worker_level = "LW" if selected in PRIMARY_EXECUTOR_OPTIONS else level
    return {
        "worker_level": worker_level,
        "wrapper": wrapper,
        "project_root": PROJECT_ROOT_TEXT,
        "invocation": CODEX_EXEC,
        "sandbox": "danger-full-access",
        "sandbox_authority": "writable sandbox",
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


def spec(
    semantic_key: str,
    stage: str,
    work_kind: str,
    domain_lane: str,
    state: str,
    title: str,
    user: str,
    inputs: str,
    processing: str,
    output: str,
    tests: str,
    acceptance: str,
    dod: str,
    task: str,
    *,
    write_authority: str = "implementation",
    acceptance_authority: str = "main orchestrator",
    level: str = "LW",
    decision_refs: bool = False,
) -> dict[str, object]:
    return {
        "semantic_key": semantic_key,
        "stage": stage,
        "work_kind": work_kind,
        "domain_lane": domain_lane,
        "execution_state": state,
        "title": title,
        "user": user,
        "inputs": inputs,
        "processing": processing,
        "output": output,
        "tests": tests,
        "acceptance": acceptance,
        "dod": dod,
        "task": task,
        "write_authority": write_authority,
        "acceptance_authority": acceptance_authority,
        "level": level,
        "decision_refs": decision_refs,
    }


SPECS: dict[str, dict[str, object]] = {
    "A": spec(
        "media.stage1.charter", "A", "charter", "governance", "ACCEPTED",
        "第一阶段章程", "产品负责人、交付负责人", "用户指令与三阶段编排文本",
        "冻结第一阶段目标、排除项、候选边界与完成声明", "第一阶段唯一开发编排边界",
        "范围一致性与阶段互斥检查", "只生成第一阶段；第二、三阶段不建包",
        "章程、证据目标与完成口径一致", "维护第一阶段章程；不修改产品代码。",
        write_authority="authoritative-contract", acceptance_authority="user and planning authority",
    ),
    "A1": spec(
        "media.stage1.source-baseline", "A", "fact-discovery", "source-facts", "ACCEPTED",
        "输入与当前状态基线", "规划者、实施者", "审计、附件、Revision 11 权威与进度文件",
        "核对校验值、正式状态、可复用底座与已知断点", "可复现的非 Git 文件基线",
        "文件校验值复算和权威路径存在性", "正式进度为 25/29，唯一后缀为 D1 到 D3A",
        "所有后续节点只消费列明的权威与校验值", "只读复核输入文件并登记证据。",
        write_authority="evidence-only",
    ),
    "K": spec(
        "media.stage1.product-decisions", "A", "decision-acceptance", "product-contract", "ACCEPTED",
        "第一阶段产品决定", "产品负责人、终端用户、组织管理员", "用户确认的三阶段思路与事实审计",
        "确认统一认证、可信意图、工作区多归属、应用身份和最小撤销边界", "已接受决定记录第 1 版",
        "决定覆盖与互斥检查", "不再生成待拍板问题文件",
        "所有实现节点引用同一决定版本", "维护已接受决定记录；不得把推荐重新降级为待决。",
        write_authority="authoritative-contract", acceptance_authority="user",
    ),
    "R1": spec(
        "media.revision11.static-acceptance", "A", "validation", "revision11", "READY",
        "Revision 11 静态与合同验收", "现有 C/B 正文用户", "canonical C-P1 不可变候选",
        "按 canonical D1 运行静态、构建、后端、OpenAPI、认证隔离和候选身份门禁", "canonical D1 验收回执",
        "canonical D1 冻结命令集", "同一候选全部门禁通过",
        "canonical D1 标记 ACCEPTED 后本投影才同步接受", "在 canonical SSOT 权威下执行 D1；不得修改候选或加入新功能。",
        write_authority="evidence-only",
    ),
    "R2": spec(
        "media.revision11.browser-acceptance", "A", "validation", "revision11", "INVALIDATED",
        "Revision 11 浏览器回归", "现有 C/B 正文用户", "R1 接受的同一候选",
        "按 canonical D2 重做桌面、移动、C/B、飞书打开、刷新和双产品登录隔离", "canonical D2 新鲜浏览器证据",
        "真实浏览器断言、网络、控制台与截图", "同一候选的 canonical D2 ACCEPTED",
        "旧证据保持失效历史，新证据绑定同一候选", "R1 接受后执行 canonical D2，不编辑候选。",
        write_authority="evidence-only",
    ),
    "R3": spec(
        "media.revision11.production-promotion", "A", "validation", "revision11", "BLOCKED",
        "Revision 11 生产原子切换", "现有生产用户", "R2 接受的不可变候选与回滚清单",
        "按 canonical D3P 执行资格检查、迁移、原子切换、重启、健康与写读验证", "生产身份与切换回执",
        "版本、健康、入口、写读与回滚点读回", "canonical D3P ACCEPTED",
        "生产只指向已验收候选并保留可验证回滚点", "仅在 canonical 授权后执行 D3P；失败立即停在所属检查点。",
        write_authority="evidence-only", acceptance_authority="runtime release owner", level="L3",
    ),
    "R4": spec(
        "media.revision11.independent-final", "A", "validation", "revision11", "BLOCKED",
        "Revision 11 独立只读终验", "产品负责人、生产用户", "R3 的生产身份和原始合同",
        "独立读取生产身份、正文权威、认证隔离、旧资产退役和正式响应", "canonical D3A 独立结论",
        "零写入生产读回与证据哈希核对", "canonical D3A ACCEPTED",
        "Revision 11 正式闭环后才解锁新候选", "zero-write 复核 canonical D3A；不得修复或修改生产。",
        write_authority="evidence-only", acceptance_authority="independent acceptance owner", level="L3",
    ),
    "B": spec(
        "media.stage1.contract-assembly", "A", "contract-assembly", "new-candidate", "BLOCKED",
        "新功能候选合同汇编", "产品、前后端、验收负责人", "R4 接受基线与 K 第 1 版决定",
        "冻结会话、工作区、Binding、Provision、错误、迁移与验收合同", "第一阶段新候选合同身份",
        "schema、OpenAPI、状态机和保护测试红灯", "没有旧新双路径或功能开关",
        "产生独立于 Revision 11 的唯一功能候选基线", "R4 接受后汇编新合同，不改写 Revision 11 候选。",
        write_authority="authoritative-contract", decision_refs=True,
    ),
    "I1": spec(
        "media.stage1.unified-login", "B", "implementation", "identity", "BLOCKED",
        "统一登录入口", "个人创作者、组织创作者", "B 冻结合同与 Media 独立飞书认证",
        "在登录首页提供个人或组织意图并启动统一 OAuth", "可访问的统一登录面",
        "键盘、移动端、错误与回退路径测试", "两种意图均进入同一认证权威且不恢复密码入口",
        "入口不自行签发授权事实", "实现统一登录页及意图选择；只写隔离候选。", decision_refs=True,
    ),
    "I2": spec(
        "media.stage1.oauth-intent-binding", "B", "implementation", "identity-security", "BLOCKED",
        "可信 OAuth 意图绑定", "所有登录用户", "I1 请求意图、OAuth state、PKCE 和回调",
        "服务端签名绑定意图、随机数、过期时间、回调和一次性消费", "可验证的认证意图收据",
        "篡改、重放、过期、错回调和并发登录负例", "浏览器回传类型不能改变服务端已绑定意图",
        "所有异常失败关闭且日志不含临时秘密", "实现 OAuth 意图绑定和负例门禁。", decision_refs=True,
    ),
    "I3": spec(
        "media.stage1.session-workspace-resolution", "B", "contract-compile", "session", "BLOCKED",
        "会话与工作区解析", "多工作区用户", "可信飞书身份、意图、Membership、Binding",
        "生成 SessionPrincipal v2 和 WorkspaceResolutionResult，支持一个用户多归属", "可信会话与工作区候选集合",
        "多组织、无成员、重复 Binding、ordinary 旧值和刷新恢复测试", "不持久化单一永久 user_type，旧 ordinary 写入被迁移或拒绝",
        "服务端是工作区、正文权威和成员角色的唯一来源", "编译会话与工作区合同并完成前向迁移。", decision_refs=True,
    ),
    "I4": spec(
        "media.stage1.personal-workspace-shell", "B", "implementation", "frontend-personal", "BLOCKED",
        "个人工作区壳", "个人创作者", "I3 的 personal_web 会话",
        "按服务端解析进入个人导航与占位工作区，不交付完整内容生产", "PersonalWorkspaceShell",
        "刷新、空状态、无权限和移动端测试", "个人选择不会进入组织配置或组织资源",
        "为第二阶段个人内容支线提供稳定入口", "实现个人工作区壳；不得加入第二阶段内容生产。", decision_refs=True,
    ),
    "I5": spec(
        "media.stage1.organization-workspace-shell", "B", "implementation", "frontend-organization", "BLOCKED",
        "组织工作区壳", "组织 owner 和 member", "I3 的 organization_lark 会话",
        "按成员与 Binding 状态展示组织工作台、安装恢复或注意状态", "OrganizationWorkspaceShell",
        "角色、空 Binding、停用、误导邀请文案和移动端测试", "affiliate 邀请不得伪装成租户成员管理",
        "页面不从前端 tenantId 或平台 admin 推断组织权限", "实现组织工作区壳和真实状态文案。", decision_refs=True,
    ),
    "I6": spec(
        "media.stage1.authorization-guards", "B", "implementation", "authorization", "BLOCKED",
        "服务端授权守卫", "所有租户用户", "Session、Membership、Binding、现有 Media API",
        "统一资源范围守卫并关闭已知跨租户读取，包括近期活动全表读取", "服务端授权与审计日志",
        "伪造 tenantId、跨组织、平台 admin 越权、撤销后写入负例", "所有业务权限来自服务端会话、成员关系和 Binding",
        "跨租户访问稳定返回 403 或规范 404 且不泄露存在性", "实现统一授权守卫并补红绿门禁。", decision_refs=True,
    ),
    "I7": spec(
        "media.stage1.binding-runtime-resolver", "B", "implementation", "binding-runtime", "BLOCKED",
        "按 Binding 解析运行资源", "组织用户、后台任务", "I3 会话、I5 组织壳、I6 守卫和 Binding",
        "按 tenant、binding 与凭据世代解析 app、secret、Wiki、父节点和 Web 域名", "BindingRuntimeResolver",
        "组织 A/B 凭据、资源、缓存和轮换隔离负例", "主应用、writer 接口和 sync/hydrate 不再依赖全局可变凭据",
        "任何缺失或撤销状态在外部调用前失败关闭", "实现按 Binding 的运行时解析器并移除全局凭据消费。", decision_refs=True,
    ),
    "I8": spec(
        "media.stage1.pilot-organization-e2e", "B", "validation", "pilot", "BLOCKED",
        "既有 Binding 试点闭环", "已绑定组织成员", "I5 到 I7、T1 和一个已知现有 Binding",
        "登录、命中 Binding、进入工作台、资源发现、Web 只读、飞书编辑和回读", "同收据 Pilot E2E 证据",
        "真实外部系统正例、跨组织负例和刷新恢复", "同一组织、同一 Binding、同一成果的端到端回执",
        "Pilot 成功先于通用 Provision，Pilot 脚本不成为长期入口", "在隔离试点组织执行真实 E2E；不接触其他租户。",
        write_authority="evidence-only", acceptance_authority="runtime acceptance owner", level="L3",
    ),
    "C1": spec(
        "media.stage1.identity-convergence", "C", "convergence", "identity", "BLOCKED",
        "身份与工作区汇合", "个人和组织用户", "I3 到 I6 的候选输出",
        "合并唯一会话、两种工作区壳和授权守卫并核对接口", "身份工作区收敛候选",
        "联合合同、角色矩阵和浏览器回归", "个人/组织可信分流及负例全部通过",
        "接受后可移交第二阶段个人内容支线，但不增加第一阶段完成度", "汇合身份候选并生成不可变哈希；不得启动第二阶段节点。",
        write_authority="shared-generated",
    ),
    "C2": spec(
        "media.stage1.pilot-convergence", "C", "convergence", "pilot", "BLOCKED",
        "Pilot 收敛门禁", "组织 Pilot 用户", "I8 的同收据证据",
        "核对身份、Binding、外部资源与回读未跨租户", "Pilot 接受结论",
        "独立证据复核", "Pilot 正例和负例均绑定同一候选",
        "只在接受后解锁通用 Provision", "zero-write 复核 Pilot 证据并记录门禁。",
        write_authority="evidence-only", acceptance_authority="independent acceptance owner", level="L3",
    ),
    "P1": spec(
        "media.stage1.provision-model", "B", "data-change", "provision-data", "BLOCKED",
        "Provision 数据与状态机", "组织管理员、运营支持", "C2 接受的 Pilot 模型与 B 合同",
        "建立安装、授权、Binding、任务、步骤、回执、幂等和状态迁移", "前向数据迁移与状态模型",
        "迁移、唯一约束、非法跳转、重试和恢复测试", "状态覆盖安装到 ACTIVE、NEEDS_ATTENTION、DISABLED、REVOKED",
        "迁移可回读且不把旧 Binding 静默解释为已激活", "实现 Provision 前向模型和迁移。", decision_refs=True,
    ),
    "P2": spec(
        "media.stage1.install-event-lifecycle", "B", "implementation", "provision-events", "BLOCKED",
        "飞书安装事件生命周期", "新组织管理员", "P1 状态模型和飞书事件合同",
        "验签、解密、去重安装/启用/停用/卸载事件并管理 app_ticket", "事件服务与幂等回执",
        "伪造签名、重放、乱序、重复和密文错误测试", "事件只影响匹配的安装身份",
        "秘密不进入日志、命令行或前端", "实现安装事件链和安全门禁。", decision_refs=True,
    ),
    "P3": spec(
        "media.stage1.admin-confirmation-owner", "B", "implementation", "provision-admin", "BLOCKED",
        "管理员确认与 owner 创建", "飞书组织管理员", "P2 安装身份与 Media 用户 OAuth 身份",
        "确认管理员资格、授权范围、资源所有者，原子创建 tenant、owner 和 Binding", "管理员授权与 owner 回执",
        "非管理员、平台 admin 越权、过期、撤销和并发确认测试", "平台 admin 不自动成为组织 owner",
        "授权和 owner 创建可幂等恢复", "实现管理员确认、tenant/owner/Binding 原子事务。", decision_refs=True,
    ),
    "P5": spec(
        "media.stage1.resource-initialization", "B", "implementation", "provision-resources", "BLOCKED",
        "组织资源配置与初始化", "组织 owner", "P3 授权、I7 解析器和资源清单",
        "选择或创建 Wiki/父节点，校验所有者，创建资源并执行唯一标记写读删冒烟", "资源绑定与动作回执",
        "权限、层级、配额、重复执行、组织 A/B 隔离测试", "所有资源编号与动作回执绑定当前 Binding",
        "外部资源创建可追踪、可重试、可反向处理", "实现资源配置、初始化和逐级读回。", decision_refs=True,
    ),
    "P6": spec(
        "media.stage1.resumable-provision-orchestrator", "B", "implementation", "provision-orchestrator", "BLOCKED",
        "可续接 Provision 编排", "新组织管理员、运营支持", "P2 到 P5 的步骤服务",
        "以幂等键、租约、步骤回执和补偿状态串联全流程", "可续接 ProvisionOrchestrator",
        "中断、超时、重复回调、进程重启、部分外部成功测试", "用户从最近安全检查点继续而非从头重来",
        "只有所有健康检查通过才进入 ACTIVE", "实现可续接编排、租约和失败处置。", decision_refs=True,
    ),
    "P7": spec(
        "media.stage1.provision-status-ui", "B", "implementation", "provision-ui", "BLOCKED",
        "Provision 状态与恢复界面", "组织管理员、支持人员", "P6 状态、步骤和错误码",
        "展示当前阶段、可执行恢复动作、注意状态和组织工作台入口", "管理员状态页与 API",
        "刷新、重复点击、无权限、移动端、错误本地化测试", "界面不泄露 secret、tenant 内部编号或他组织存在性",
        "ACTIVE 前不伪装为组织已接入", "实现状态 API 和可恢复管理员界面。", decision_refs=True,
    ),
    "P8": spec(
        "media.stage1.minimal-deprovision", "B", "implementation", "deprovision", "BLOCKED",
        "最小可逆撤销", "组织 owner、安全与支持负责人", "P6 生命周期、I7 凭据解析和资源清单",
        "停用、撤销凭据、冻结写入与成员访问，并保留审计记录", "DISABLED/REVOKED 反向生命周期",
        "撤销后写入、缓存凭据、重复撤销、恢复和跨安装负例", "只影响本安装；不执行第三阶段复杂删除或迁移",
        "撤销可回读且 ACTIVE 能力立即失效", "实现最小停用和撤销；保留审计，不做复杂资源删除。", decision_refs=True,
    ),
    "C3": spec(
        "media.stage1.provision-convergence", "C", "convergence", "provision", "BLOCKED",
        "Provision 汇合", "新组织管理员、支持人员", "P7 状态入口和 P8 反向生命周期",
        "汇合安装、授权、成员、资源、恢复和撤销为唯一候选", "Provision 不可变候选",
        "联合状态机、迁移、OpenAPI、外部动作清单和秘密扫描", "正向 ACTIVE 与反向 REVOKED 均闭环",
        "候选无功能开关、旧入口或全局凭据备用路径", "汇合 Provision 输出并冻结候选身份。",
        write_authority="shared-generated",
    ),
    "T1": spec(
        "media.stage1.shared-acceptance-harness", "B", "acceptance-design", "shared-contracts", "BLOCKED",
        "共享合同与验收 Harness", "开发、QA、安全、发布负责人", "B 合同与 K 决定",
        "维护 OpenAPI、Session 类型、迁移、错误码、审计、跨租户负例和 E2E 收据合同", "保护测试和验收矩阵",
        "红灯基线、合同生成漂移、跨租户和秘密扫描", "每个稳定失败类都有红绿门禁",
        "不会用功能开关维持旧新运行路径", "建立共享合同与 E2E Harness；不实现业务支线。", decision_refs=True,
    ),
    "C": spec(
        "media.stage1.unique-candidate", "C", "convergence", "release-candidate", "BLOCKED",
        "第一阶段唯一候选", "全部第一阶段用户", "C1、C2、C3 和 T1 接受输出",
        "核对变更、迁移、接口、生成物、外部资源清单和回滚点", "哈希绑定的第一阶段候选",
        "候选重建一致性和清单完整性", "只有一个可执行候选且 Revision 11 候选保持历史不变",
        "候选冻结后任何修改都必须重建身份并重跑 D 阶段", "汇合唯一候选；不部署、不重启。",
        write_authority="shared-generated",
    ),
    "DA": spec(
        "media.stage1.static-release-acceptance", "D", "validation", "release", "BLOCKED",
        "第一阶段静态验收", "发布负责人", "C 的不可变候选",
        "运行构建、类型、后端、OpenAPI、迁移、跨租户、秘密和清理门禁", "静态验收证据包",
        "全量受影响门禁与候选哈希复算", "所有门禁对同一候选通过",
        "失败返回所属节点修复并重建候选", "对唯一候选执行静态与合同验收。",
        write_authority="evidence-only",
    ),
    "DB": spec(
        "media.stage1.external-system-acceptance", "D", "validation", "release", "BLOCKED",
        "真实外部系统与生产验收", "个人用户、组织管理员、组织成员", "DA 接受候选和隔离验收身份",
        "原子推广后执行个人、Pilot、新组织、跨租户负例、撤销和恢复观察", "生产与飞书同收据证据",
        "真实浏览器、数据库、飞书、任务和服务读回", "目标证据达到 physical-device/external-system",
        "发布身份、账号、租户、Binding、设备和时间完整", "在批准窗口执行生产/外部系统验收与可回滚推广。",
        write_authority="evidence-only", acceptance_authority="runtime acceptance owner", level="L3",
    ),
    "DC": spec(
        "media.stage1.independent-release-decision", "D", "release-decision", "release", "BLOCKED",
        "独立终验与发布决定", "产品负责人、生产用户", "DB 同收据证据、原始要求和清除清单",
        "零写入核对范围、候选、生产、外部系统、回滚、已知负例和排除项", "独立 ACCEPTED 或拒绝结论",
        "哈希、时间、身份、证据等级和无回退核对", "所有第一阶段完成条件成立且无阶段外冒领",
        "仅 DC ACCEPTED 可宣告第一阶段完成", "zero-write 独立终验；不得修复、部署或改变状态。",
        write_authority="evidence-only", acceptance_authority="independent acceptance owner", level="L3",
    ),
}


EDGES: list[tuple[str, str, str]] = [
    ("A", "A1", "specific-output"),
    ("A1", "K", "specific-output"),
    ("A1", "R1", "specific-output"),
    ("R1", "R2", "specific-output"),
    ("R2", "R3", "specific-output"),
    ("R3", "R4", "specific-output"),
    ("K", "B", "specific-output"),
    ("R4", "B", "global-completeness"),
    ("B", "I1", "specific-output"),
    ("B", "T1", "specific-output"),
    ("I1", "I2", "specific-output"),
    ("I2", "I3", "specific-output"),
    ("I3", "I4", "specific-output"),
    ("I3", "I5", "specific-output"),
    ("I3", "I6", "specific-output"),
    ("I5", "I7", "specific-output"),
    ("I6", "I7", "specific-output"),
    ("I4", "C1", "specific-output"),
    ("I5", "C1", "specific-output"),
    ("I6", "C1", "specific-output"),
    ("I5", "I8", "specific-output"),
    ("I6", "I8", "specific-output"),
    ("I7", "I8", "specific-output"),
    ("T1", "I8", "specific-output"),
    ("I8", "C2", "specific-output"),
    ("C2", "P1", "specific-output"),
    ("P1", "P2", "specific-output"),
    ("P2", "P3", "specific-output"),
    ("P3", "P5", "specific-output"),
    ("I7", "P5", "specific-output"),
    ("P2", "P6", "specific-output"),
    ("P3", "P6", "specific-output"),
    ("P5", "P6", "specific-output"),
    ("P6", "P7", "specific-output"),
    ("P6", "P8", "specific-output"),
    ("I7", "P8", "specific-output"),
    ("P7", "C3", "specific-output"),
    ("P8", "C3", "specific-output"),
    ("C1", "C", "specific-output"),
    ("C2", "C", "specific-output"),
    ("C3", "C", "specific-output"),
    ("T1", "C", "specific-output"),
    ("C", "DA", "global-completeness"),
    ("DA", "DB", "global-completeness"),
    ("DB", "DC", "global-completeness"),
]


# Version 5 is the only live machine model. The inline version-1 definitions above
# remain readable history but are never written into the generated authority.
from stage1_model import (  # noqa: E402
    BATCHES_V4,
    CANDIDATE_IDENTITY_POLICY_OVERRIDES,
    DAG_VERSION,
    EDGES_V4,
    EXECUTION_ACTOR_OVERRIDES,
    INTERFACE_FREEZE_VERSION,
    NODE_CONTRACT_VERSION,
    NODE_ROLE_OVERRIDES,
    PLAN_VERSION,
    PRIMARY_EXECUTOR_DEFAULT,
    PRIMARY_EXECUTOR_OPTIONS,
    PRIMARY_EXECUTOR_OVERRIDES,
    RELEASE_SLICE_BY_NODE,
    SHARED_EVIDENCE_V4,
    SIDE_EFFECT_OVERRIDES,
    SPECS_V4,
    SSOT_SCHEMA_VERSION,
    TEST_WORK_OVERRIDES,
    WAVE_BY_NODE,
    selected_primary_executor,
    selected_primary_wrapper,
)

SPECS = SPECS_V4
EDGES = EDGES_V4
SHARED_EVIDENCE = SHARED_EVIDENCE_V4


incoming: dict[str, list[str]] = defaultdict(list)
outgoing: dict[str, list[str]] = defaultdict(list)
for source, target, _ in EDGES:
    incoming[target].append(source)
    outgoing[source].append(target)


def _execution_wave_by_node() -> dict[str, str]:
    """Assign deterministic DAG-depth waves with no hard dependency overlap.

    The historical wave map grouped by work theme, which is useful prose but
    not an executable parallelism contract.  A depth-derived map preserves
    genuine antichain parallelism while making every declared batch safe for
    strict schema-v2 validation.
    """

    node_ids = set(SPECS)
    indegree = {node_id: len(incoming[node_id]) for node_id in node_ids}
    depth: dict[str, int] = {}
    ready = sorted(node_id for node_id, count in indegree.items() if count == 0)
    while ready:
        node_id = ready.pop(0)
        depth[node_id] = (
            0
            if not incoming[node_id]
            else 1 + max(depth[parent] for parent in incoming[node_id])
        )
        for child in sorted(outgoing[node_id]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()
    if len(depth) != len(node_ids):
        missing = sorted(node_ids - set(depth))
        raise RuntimeError(f"cannot derive execution waves from cyclic DAG: {missing}")
    return {
        node_id: f"W-{RELEASE_SLICE_BY_NODE[node_id].removeprefix('REL-')}-{depth[node_id]}"
        for node_id in node_ids
    }


EXECUTION_WAVE_BY_NODE = _execution_wave_by_node()


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
        return EXECUTION_ACTOR_OVERRIDES[node_id]
    if transport in {"deterministic-local", "automatic-projection"}:
        return "orchestrator"
    if transport == "external-manual":
        return "human"
    if node_id == "B":
        # B has a real historical external worker return; preserve that fact.
        return "codex"
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
    if item.get("work_kind") == "data-change":
        return "reversible"
    if node_id in {"P2", "P3", "P5", "P6", "P8", "P9", "P10"}:
        return "reversible"
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
        "l3_failure_origins": [
            "product-behavior", "implementation", "architecture-complexity",
        ],
        "automatic_executor_switch": False,
    }


def _acceptance_commands(node_id: str, item: dict[str, object], work_kind: str) -> list[str]:
    override = TEST_WORK_OVERRIDES.get(node_id)
    if isinstance(override, dict):
        oracle = override.get("test_oracle")
        if isinstance(oracle, dict) and isinstance(oracle.get("spec"), str):
            return [f"bash {oracle['spec']}"]
    if work_kind in {"data-change", "production-migration"}:
        return ["python3 -m pytest -q"]
    if item.get("transport") == "deterministic-local":
        return [str(item.get("transport_command") or "python3 -c 'print(\"deterministic check\")'")]
    return [f"python3 -c 'print(\"acceptance {node_id}\")'"]


NODES: dict[str, dict[str, object]] = {}
for node_id, item in SPECS.items():
    accepted = item["execution_state"] == "ACCEPTED"
    terminal = item["execution_state"] in {"IMPLEMENTED", "VERIFIED", "ACCEPTED"}
    override = TEST_WORK_OVERRIDES.get(node_id, {})
    work_kind = str(override.get("work_kind", item["work_kind"])) if isinstance(override, dict) else str(item["work_kind"])
    role = _node_role(node_id, work_kind)
    declared_transport = item.get("transport")
    if declared_transport:
        transport: str | None = str(declared_transport)
    elif node_id == "B":
        transport = "external-codex-exec"
    elif not terminal and role == "leaf" and node_id not in {"E11"}:
        transport = "external-codex-exec"
    else:
        # Do not manufacture a worker record for already completed history.
        transport = None
    dispatch = (
        "EXITED"
        if terminal
        else "NOT_STARTED"
        if item["execution_state"] == "READY"
        else "BLOCKED"
    )
    actor = _node_actor(node_id, item, role, transport, terminal)
    decision_versions = {
        "media.stage1.stable-decisions": 2,
        "media.stage1.decision.recent-activity-ownership": 2,
        "media.stage1.decision.writer-boundary": 2,
    }
    decision_refs = [
        {
            "semantic_key": semantic_key,
            "version": decision_versions.get(semantic_key, 1),
        }
        for semantic_key in item["decision_refs"]
    ]

    registration: dict[str, object] | None = None
    if transport == "external-manual":
        registration = {
            "executor": str(item["acceptance_authority"]),
            "manual_owner": str(item["acceptance_authority"]),
            "task_argument": str(item["task"]),
            "return_path": f"{REL_BUNDLE}/manual-receipts/{node_id}.json",
            "dispatch_state": dispatch,
            "note": "manual prerequisite; zero Codex processes",
        }
    elif transport == "deterministic-local":
        receipt_name = f"{node_id}-rerun-20260817.json" if node_id in {"MA1", "I1"} else f"{node_id}.json"
        registration = {
            "executor": "outer orchestrator",
            "project_root": PROJECT_ROOT_TEXT,
            "command": str(item["transport_command"]),
            "task_argument": str(item["task"]),
            "return_path": f"{REL_BUNDLE}/deterministic-receipts/{receipt_name}",
            "determinism_key": str(item["determinism_key"]),
            "dispatch_state": dispatch,
            "note": "deterministic local execution; zero Codex processes",
        }
    elif transport == "automatic-projection":
        registration = {
            "executor": "SSOT state projector",
            "source_nodes": item["transport_sources"],
            "projection_rule": str(item["projection_rule"]),
            "task_argument": str(item["task"]),
            "return_path": f"{REL_BUNDLE}/projections/{node_id}.json",
            "dispatch_state": dispatch,
            "note": "automatic state projection; zero Codex processes",
        }
    elif transport == "external-codex-exec":
        selected_executor = selected_primary_executor(node_id)
        registration = worker_registration(
            node_id,
            str(item["task"]),
            str(item["level"]),
            dispatch,
            executor=selected_executor,
        )
        if node_id == "B" and accepted:
            registration.update(
                {
                    "return_path": f"{REL_BUNDLE}/worker-executions/B-retry-2/returns/B-retry-2-luna.json",
                    "prompt_path": str(BUNDLE / "worker-executions" / "B-retry-2" / "prompts" / "B-retry-2-luna.txt"),
                    "log_path": str(BUNDLE / "worker-executions" / "B-retry-2" / "logs" / "B-retry-2-luna.log"),
                    "ledger_path": f"{REL_BUNDLE}/worker-executions/B-retry-2/ledger/B-retry-2.json",
                    "prompt_sha256": "15765b36988bd97f2665e5ed9dde674025a23820ca04fec82a21610d84c8e89e",
                    "prompt_cleanup": "delete after exit evidence registration",
                    "runtime_handle_cleanup": "release after exit evidence registration",
                    "dispatch_state": "EXITED",
                }
            )
        registration["runtime_profile_requirement"] = item["runtime_profile"]
        profile_available = node_id == "B" or SPECS["G1"]["execution_state"] == "ACCEPTED"
        registration["runtime_profile_available"] = profile_available
        registration["launch_authorized"] = profile_available and item["execution_state"] == "READY"
        registration["blocking_capability_node"] = "none" if profile_available else "G1"

    selected_executor = selected_primary_executor(node_id)
    selected_wrapper = selected_primary_wrapper(node_id)
    deliverable_id = f"DL-{node_id}"
    produced_artifact_id = f"ART-{node_id}"
    read_set = [f"artifact:{source}" for source in sorted(incoming[node_id])] or [f"contract:{item['semantic_key']}" ]
    write_prefix = "evidence" if item["write_authority"] == "evidence-only" else "artifact"
    write_set = [f"{write_prefix}:{node_id}"]
    node = {
        "node_id": node_id,
        "semantic_key": item["semantic_key"],
        "stage": item["stage"],
        "work_kind": work_kind,
        "domain_lane": item["domain_lane"],
        "execution_state": item["execution_state"],
        "decision_state": "ACCEPTED" if node_id == "K" or node_id in LOCAL_DECISION_RECORDS else "NOT_APPLICABLE",
        "decision_version": 2 if node_id == "K" or node_id in {"K4", "K5"} else 1 if node_id in LOCAL_DECISION_RECORDS or node_id == "K6" else None,
        "readiness_mode": "FORMAL",
        "hard_dependencies": sorted(incoming[node_id]),
        "soft_dependencies": [],
        "assumption_ids": [],
        "decision_refs": decision_refs,
        "invalidation_keys": [f"{item['semantic_key']}.v5"],
        "write_authority": item["write_authority"],
        "acceptance_authority": item["acceptance_authority"],
        "unlocks": sorted(outgoing[node_id]),
        "worker_transport": transport,
        "worker_registration": registration,
        "runtime_profile_requirement": item["runtime_profile"],
        "related_evidence_ids": item["related_evidence_ids"],
        "description": item["dod"],
        "node_role": role,
        "execution_actor": actor,
        "execution_contract_ref": f"{node_id}.json",
        "execution_contract_sha256": None,
        "side_effect_class": _node_side_effect(node_id, item),
        "candidate_identity_policy": _node_candidate_policy(node_id, role),
        "deliverable_ids": [deliverable_id] if is_numeric_node(node_id) else [],
        "produced_artifact_ids": [produced_artifact_id],
        "consumed_artifact_ids": [],
        "read_set": read_set,
        "write_set": write_set,
        "resource_claims": [
            {
                "resource_id": f"node:{node_id}",
                "mode": "W",
                "isolation_key": f"node:{node_id}",
            }
        ],
        "actor_pool": {
            "codex": "codex-primary",
            "human": "human-authority",
            "external-system": "external-acceptance",
            "orchestrator": "orchestrator",
        }[actor],
        "acceptance_commands": _acceptance_commands(node_id, item, work_kind),
        "evidence_outputs": [f"{REL_BUNDLE}/validation/{node_id}-return.json"],
        "release_slice": RELEASE_SLICE_BY_NODE[node_id],
        "wave_id": EXECUTION_WAVE_BY_NODE[node_id],
    }
    if actor == "codex" and role == "leaf" and transport == "external-codex-exec":
        node.update(
            {
                "executor_route": selected_executor,
                "primary_executor": selected_executor,
                "primary_wrapper": selected_wrapper,
                "executor_attempt_policy": (
                    dict(override["executor_attempt_policy"])
                    if isinstance(override, dict) and isinstance(override.get("executor_attempt_policy"), dict)
                    else _default_attempt_policy(selected_executor, selected_wrapper)
                ),
            }
        )
        if selected_executor != PRIMARY_EXECUTOR_DEFAULT:
            node["executor_route_override"] = {
                "reason": "explicit node-level primary executor switch",
                "approved_by": "dispatch packet",
            }
    if isinstance(override, dict):
        for key, value in override.items():
            if key == "work_kind":
                continue
            if key == "executor_attempt_policy" and isinstance(value, dict):
                node[key] = dict(value)
            else:
                node[key] = value
    if actor == "orchestrator" and write_set:
        node["main_thread_write_exception"] = {
            "reason": "orchestration-only generated evidence or projection write",
            "approved_by": "SSOT orchestration owner",
            "write_set": list(write_set),
        }
    if item["execution_state"] in {"IMPLEMENTED", "VERIFIED", "ACCEPTED"}:
        node["evidence_identity"] = evidence_identity(node_id)
    if node_id == "K":
        node["decision_record"] = {
            "approved_value": {
                "authorization_source": "server session plus Membership plus Binding",
                "multi_workspace": "one user may own personal and join multiple organizations; no permanent user_type",
                "session_contract": "SessionPrincipal v2 carries tenant, workspace, body authority, member and Binding facts",
                "application_identity": "MediaClaw B is authoritative; overlapping Company OS naming is superseded",
                "candidate_policy": "Revision 11 stays immutable and external; phase 1 has independent Release 1A and Release 1B candidates",
                "provision_order": "existing-Binding Pilot must be accepted before general Provision",
                "deprovision_scope": "disable, revoke credentials, freeze writes/access and retain audit; complex deletion/migration is phase 3",
                "phase2_handoff": "C1 unlocks the personal lane, C3 unlocks the organization lane, and DC2 is the final stage-1 release projection",
            },
            "approval_authority": "user",
            "approval_evidence": "User instruction on 2026-08-15: 按照这个思路拆成三个阶段，并先生成第一阶段 SSOT",
            "approved_at": OBSERVED_AT,
        }
    if node_id in LOCAL_DECISION_RECORDS:
        node["decision_record"] = LOCAL_DECISION_RECORDS[node_id]
    NODES[node_id] = node

for node_id, node in NODES.items():
    node["consumed_artifact_ids"] = [
        artifact_identity(source) for source in sorted(incoming[node_id])
    ]


EDGE_RECORDS: list[dict[str, object]] = []
for index, (source, target, scope) in enumerate(EDGES, 1):
    edge_id = f"E-{index:03d}-{source}-{target}"
    source_node = NODES[source]
    target_node = NODES[target]
    source_candidate = source_node.get("candidate_identity_policy") != "none"
    target_candidate = target_node.get("candidate_identity_policy") != "none"
    if source == "E11" or target == "E11":
        reason_code = "external-prerequisite"
        resource_ids = ["authority:revision11-d3a"]
    elif source_candidate and target_candidate:
        reason_code = "candidate-identity"
        release_id = RELEASE_SLICE_BY_NODE.get(target, RELEASE_SLICE_BY_NODE.get(source, "REL-1A"))
        resource_ids = [f"candidate:{release_id}"]
    elif source_node.get("work_kind") in {"decision-acceptance", "contract-assembly", "acceptance-design", "contract-compile"}:
        reason_code = "contract-dependency"
        resource_ids = []
    elif target_node.get("node_role") in {"convergence", "acceptance-gate", "release-decision"}:
        reason_code = "acceptance-dependency"
        resource_ids = []
    else:
        reason_code = "data-dependency"
        resource_ids = []
    source_artifact = artifact_identity(source)
    EDGE_RECORDS.append(
        {
            "edge_id": edge_id,
            "from": source,
            "to": target,
            "dependency_type": "hard",
            "dependency_scope": scope,
            "required_state": "ACCEPTED",
            "assumption_ids": [],
            "invalidation_keys": [f"edge.{source.lower()}.{target.lower()}.v5"],
            "transferred_input": str(SPECS[source]["output"]),
            "gate_evidence": str(SPECS[source]["acceptance"]),
            "reason_code": reason_code,
            "transferred_artifact_ids": [source_artifact],
            "resource_ids": resource_ids,
            "necessity_proof": (
                f"{target} consumes the explicitly produced artifact {source_artifact}"
                if reason_code != "external-prerequisite" and reason_code != "candidate-identity"
                else (
                    "CA/CB cannot form a release candidate before the pinned Revision 11 D3A authority is accepted"
                    if reason_code == "external-prerequisite"
                    else f"{target} must retain the immutable {resource_ids[0]} identity from {source}"
                )
            ),
        }
    )


BATCHES = BATCHES_V4


def numeric_nodes() -> list[str]:
    return [node_id for node_id in NODES if is_numeric_node(node_id)]


missing_batches = sorted(set(numeric_nodes()) - set(BATCHES))
extra_batches = sorted(set(BATCHES) - set(numeric_nodes()))
if missing_batches or extra_batches:
    raise RuntimeError(
        "numeric node delivery batches drift: "
        f"missing={missing_batches}, extra={extra_batches}"
    )


def write_region(node_id: str) -> str:
    if node_id in {"A1", "K1", "K2", "K3", "K4", "K5", "K6", "GA1", "G1", "E11"}:
        return str(NODES_DIR / f"{node_id}.json")
    if node_id in {"MA1", "MB1"}:
        return str(PROJECT_ROOT / ".codex-work" / f"stage1-{node_id.lower()}-migration")
    if node_id.startswith("C") or node_id.startswith("D"):
        return str(BUNDLE / "worker-returns" / f"{node_id}.json")
    return str(PROJECT_ROOT / ".codex-work" / f"stage1-{node_id.lower()}")


DELIVERABLES = [
    [
        f"DL-{node_id}", EXECUTION_WAVE_BY_NODE[node_id], SPECS[node_id]["output"], write_region(node_id),
        cell(NODES[node_id]["hard_dependencies"]), "independent", "none", node_id, "n/a",
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
    if node_id in {"A", "A1", "K", "K1", "K2", "K3", "K4", "K5", "K6", "B", "GA1", "G1", "E11", "DA", "DB", "DC"}:
        return "G-DOC"
    if node_id in {"DB1", "DB2"}:
        return "G-RELEASE"
    if node_id in {"DA1", "DA2"}:
        return "G-STATIC"
    if node_id in {"DC1", "DC2", "C2"}:
        return "G-ZERO"
    return "G-PHASE1"


def state_reason(node_id: str) -> str:
    state = NODES[node_id]["execution_state"]
    if state == "ACCEPTED":
        return "n/a"
    if state == "VERIFIED":
        if node_id == "I2":
            return "本地生命周期与公共路由验证通过（20 passed, 16 skipped；共享路由验收合同（T1-AUTH-ROUTES）保护基线已 LOCKED）；正式接受、真实邮件/飞书和生产验收仍待完成"
        if node_id == "T1":
            return "本地共享合同与门禁验证通过（15 passed；路由一致性 GREEN）；保护测试基线已 LOCKED，正式接受与人工验收仍待完成"
        if node_id == "MA1":
            return "Release 1A 冻结迁移静态验证通过（27 passed, 3 subtests passed）；真实数据库回读、恢复和发布验收仍待完成"
        if node_id == "I1":
            return "统一认证入口源 QA 与整合候选完整 build:media 已通过（含个人工作区 deletion fixture 门禁）；真实浏览器、部署、邮件/飞书和生产验收仍待完成"
        return "本地验证通过；正式接受仍待完成"
    if state == "IMPLEMENTED":
        return "实现已落盘；独立验证仍待完成"
    if state == "READY":
        return "n/a"
    if node_id == "B":
        return (
            "合同文件与 7 项本地合同测试已通过；外部 Codex worker 的 Luna/L3 传输均失败，"
            "结构化 return 缺失，正式回执门禁未满足"
        )
    if node_id == "G1":
        return "等待 GA1 人工建立五类运行配置后执行只读验证"
    if node_id == "E11":
        return "canonical D3A 尚未 ACCEPTED"
    if node_id == "I4":
        return "等待 I3 ACCEPTED；个人工作区受保护 deletion fixture 合同已获批准并重新锁定，普通内容删除仍属于后续内容生产范围"
    deps = [dep for dep in incoming[node_id] if NODES[dep]["execution_state"] != "ACCEPTED"]
    return "等待 " + ", ".join(deps) + " ACCEPTED" if deps else "尚未进入执行波次"


def current_evidence_row(node_id: str) -> list[object]:
    if node_id == "A":
        source_revision = "user-request-and-structure-review-2026-08-15"
        hashes = ", ".join([HASHES["attachment"], HASHES["structure_review"]])
        environment = "current Codex task and two local attachments"
        actor = "user and planning authority"
        observed = OBSERVED_AT
        contract = "Phase-1 SSOT restructuring charter v4"
        mock = "false"
    elif node_id == "A1":
        source_revision = "audit-and-canonical-hash-baseline-2026-08-15"
        hashes = ", ".join([HASHES["audit"], HASHES["canonical"], HASHES["canonical_progress"], HASHES["latest_review"]])
        environment = "local source files; non-Git project root"
        actor = "main orchestrator read-only"
        observed = OBSERVED_AT
        contract = "Phase-1 source and runner baseline v4"
        mock = "false"
    elif node_id == "K":
        source_revision = "user-approved-three-stage-plan-2026-08-15"
        hashes = ", ".join([HASHES["attachment"], HASHES["audit"], HASHES["structure_review"]])
        environment = "current Codex task"
        actor = "user and product decision authority"
        observed = OBSERVED_AT
        contract = "Phase-1 stable product decisions v2 under plan v4"
        mock = "false"
    elif node_id in {"K1", "K2", "K3", "K4", "K5", "K6"}:
        decision_date = str(LOCAL_DECISION_RECORDS[node_id]["approved_at"])
        source_revision = (
            f"user-decision-k6-{decision_date}"
            if node_id == "K6"
            else "user-six-decisions-2026-08-15"
        )
        hashes = ", ".join([HASHES["attachment"], HASHES["structure_review"], HASHES["latest_review"]])
        environment = "current Codex task; user decision message"
        actor = "user and product decision authority"
        observed = decision_date if node_id == "K6" else USER_DECISION_DATE
        contract = SPECS[node_id]["acceptance"]
        mock = "false"
    elif node_id == "B":
        source_revision = f"sha256:{HASHES['b_candidate_manifest']}"
        hashes = ", ".join(
            f"sha256:{HASHES[key]}"
            for key in ("b_openapi", "b_contract_test", "b_validation", "b_retry_return")
        )
        environment = "local macOS non-Git merge-candidate-v4 backend with existing Python virtualenv"
        actor = "Luna worker with supervisor acceptance"
        observed = "2026-08-16T07:59:05Z"
        contract = "B-retry-2 frozen contract validation; 7 passed"
        mock = "false"
    elif node_id == "GA1":
        source_revision = f"sha256:{HASHES['runner_registry']}"
        hashes = ", ".join(
            [f"sha256:{HASHES['runner_launcher']}", f"sha256:{HASHES['ga1_receipt']}"]
        )
        environment = "local runner profile registry and absolute launchers"
        actor = "execution environment owner"
        observed = "2026-08-16T15:10:35+08:00"
        contract = SPECS[node_id]["acceptance"]
        mock = "false"
    elif node_id == "G1":
        source_revision = f"sha256:{HASHES['runner_registry']}"
        hashes = ", ".join(
            [f"sha256:{HASHES['runner_launcher']}", f"sha256:{HASHES['g1_receipt']}"]
        )
        environment = "local runner profile capability probes"
        actor = "outer orchestrator deterministic verification"
        observed = "2026-08-16T07:36:47.577035+00:00"
        contract = SPECS[node_id]["acceptance"]
        mock = "true"
    elif node_id == "M1":
        source_revision = "stage1-no-git-rebuild-v4"
        hashes = ", ".join(
            f"sha256:{HASHES[key]}"
            for key in ("m1_tool", "m1_schema", "m1_tests", "m1_validation", "m1_fixture_manifest")
        )
        environment = "local non-Git project root with existing merge-candidate-v4 Python virtualenv"
        actor = "main orchestrator deterministic local execution"
        observed = "2026-08-16T18:08:43+08:00"
        contract = "M1-remediation-1 frozen validation; 32 passed"
        mock = "true"
    elif node_id == "I2":
        source_revision = "stage1-i2-auth-routes-locked-2026-08-17"
        hashes = ", ".join(
            f"sha256:{HASHES[key]}"
            for key in (
                "i2_lifecycle_impl", "i2_account_api", "i2_http_api",
                "i2_lifecycle", "i2_validation",
            )
        )
        environment = "local macOS isolated stage1-i2 root with existing Python virtualenv"
        actor = "main orchestrator deterministic rerun"
        observed = "2026-08-17T00:01:14+08:00"
        contract = "共享路由验收合同（T1-AUTH-ROUTES）运行 20260817T031500Z-local-final-f4a5b6；I2 20 passed, 16 skipped；保护基线 LOCKED；正式接受待完成"
        mock = "true"
    elif node_id == "T1":
        source_revision = "stage1-t1-auth-routes-locked-2026-08-17"
        hashes = ", ".join(
            f"sha256:{HASHES[key]}"
            for key in (
                "t1_contract", "t1_harness", "t1_route_gate",
                "t1_shared_test", "t1_validation", "i2_lifecycle",
            )
        )
        environment = "local macOS isolated stage1-t1 root with existing Python virtualenv"
        actor = "main orchestrator deterministic rerun"
        observed = "2026-08-17T00:01:14+08:00"
        contract = "共享路由验收合同（T1-AUTH-ROUTES）运行 20260817T031500Z-local-final-f4a5b6；T1 15 passed；路由一致性 GREEN；保护基线 LOCKED；正式接受待完成"
        mock = "true"
    elif node_id == "MA1":
        source_revision = "stage1-ma1-migration-isolated-root-2026-08-17"
        hashes = ", ".join(
            f"sha256:{HASHES[key]}"
            for key in ("ma1_migration", "ma1_manifest", "ma1_tests", "ma1_runner_tests", "ma1_receipt")
        )
        environment = "local macOS isolated stage1-ma1-migration root with existing Python virtualenv"
        actor = "main orchestrator deterministic local execution"
        observed = "2026-08-17T00:47:00+08:00"
        contract = "MA1 frozen validation receipt EV-MA1-RERUN-20260817; 27 passed, 3 subtests passed"
        mock = "true"
    elif node_id == "I1":
        source_revision = "stage1-i1-isolated-root-2026-08-17"
        hashes = ", ".join(
            f"sha256:{HASHES[key]}"
            for key in (
                "i1_login_html", "i1_login_js", "i1_register_html", "i1_verify_html",
                "i1_recover_html", "i1_reset_html", "i1_auth_css", "i1_vite_config",
                "i1_nginx", "i1_identity_qa", "i1_login_qa", "i1_package", "i1_lockfile",
                "i1_receipt",
            )
        )
        environment = "local macOS isolated stage1-i1 root with existing Node dependencies"
        actor = "main orchestrator deterministic local execution"
        observed = "2026-08-17T00:47:00+08:00"
        contract = "I1 frozen validation receipt EV-I1-RERUN-20260817; stage1_identity_entry=PASS; build:media passed"
        mock = "true"
    else:
        source_revision = "phase1-plan-v4"
        hashes = "pending"
        environment = "planned isolated candidate"
        actor = "pending assigned worker"
        observed = "pending"
        contract = SPECS[node_id]["acceptance"]
        mock = "pending"
    evidence_level = "local-runtime" if node_id in {"B", "G1", "M1", "MA1", "I1", "I2", "T1"} else "source"
    return [
        f"EV-{node_id}-CURRENT", node_id, evidence_level, source_revision, hashes, environment,
        "n/a", actor, "n/a", "n/a", mock, observed, contract,
    ]


def shared_evidence_row(evidence: dict[str, object]) -> list[object]:
    return [
        evidence["evidence_id"],
        "A1",
        evidence["evidence_level"],
        evidence["source_revision"],
        ", ".join(str(item) for item in evidence["artifact_hashes"]),
        evidence["environment_identity"],
        "n/a",
        evidence["actor_role"],
        "local fixtures only",
        "n/a",
        str(evidence["mock_or_fixture"]).lower(),
        evidence["observed_at"],
        f"{evidence['proves']}；不证明：{evidence['does_not_prove']}",
    ]


def main_view() -> str:
    return f"""---
ARTIFACT_CLASS: ssot-development
APPLICABILITY_DECISION: ssot
GOVERNANCE_REASON: "用户要求把第一宏观阶段重构为可独立验收的身份试点版本与自助接入版本"
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

# 自媒体创作平台第一阶段 SSOT：身份与组织接入

## 1. 业务结论与范围

### 术语说明

- **第 11 次修订候选（Revision 11）**：由原规范 SSOT 独立拥有的不可变候选。本文件只读取其独立终验节点（`D3A`）是否正式接受，不登记第 11 次修订执行节点组（`R1-R4`），不调度它们，也不向原权威写证据。
- **发布增量**：能够独立形成候选、验收、生产推广和终验结论的一组用户价值。一个宏观阶段可以包含多个发布增量。
- **工作区意图**：用户在登录页选择个人或组织，只表达希望进入哪类工作区，不构成授权。
- **待验证账号**：已经提交用户名、邮箱和密码，但尚未完成邮箱所有权验证的平台账号。它不能取得完整登录会话，也不会创建组织身份。
- **完整登录会话**：服务端确认账号状态、凭据和工作区后签发的不透明浏览器会话。注册提交、验证邮件发送和密码重置成功都不等于已经登录。
- **组织绑定（Binding）**：把组织、飞书安装身份、凭据世代、知识库空间和父节点关联起来的服务端事实。
- **组织接入（Provision）**：从安装事件、管理员确认、组织负责人创建、资源初始化到可运行或待处置状态的可续接流程。
- **外部门（`E11`）**：只读投影第 11 次修订独立终验状态的机器节点。它不执行或接管第 11 次修订，但会让两个候选在机器图上真正等待独立终验节点（`D3A`）。
- **开发基线与晋升基线**：开发基线允许提前隔离开发；晋升基线是候选发布前必须重放补丁的正式底座。发布增量 1A 使用外部门（`E11`）绑定的候选，发布增量 1B 使用独立终验节点（`DC1`）接受的候选。

本 SSOT 保留“第一宏观阶段”这一业务范围，但拆成两个独立新候选：

1. **发布增量 1A：身份分流与既有组织试点。** 个人进入个人工作区，已有组织进入组织工作区，服务端阻止串租户，并验证既有组织绑定的资源发现、网页只读镜像和可信打开。
2. **发布增量 1B：新组织自助接入。** 在已接受的 1A 基线上交付安装事件、管理员确认、组织负责人和组织绑定、资源初始化、普通成员首次飞书授权即时建立、可续接状态以及最小撤销。
3. **第一阶段后续目录成熟化交接。** 分页、部门树、增量同步和大组织恢复移出本自动调度图，只保留后续独立发布的交接记录。第一阶段仍必须交付单成员手动停用与现有会话立即撤销。

当前完成边界已经包含 **本地治理实现证据**：M1 的无 Git 候选重建协议通过冻结测试，但第一阶段产品功能尚未实现。目标完成证据仍是 **真实设备或真实外部系统证据**；文档生成、校验、本地门禁和快照都不能替代产品实现、生产推广或飞书验收。

## 2. 发布增量与用户价值

| 发布增量 | 用户价值 | 候选与验收路径 | 完成边界 |
| --- | --- | --- | --- |
| 发布增量 1A | 个人和既有组织被可信分流，旧全局文档写入器失败关闭，既有组织可读取并打开自己的资源 | `E11 + C1 + C2 + T1 + M1 + K2 -> CA -> DA1 -> DB1 -> DC1` | `DC1 ACCEPTED` |
| 发布增量 1B | 新组织负责人可完成安装与资源初始化，普通成员可即时进入并可被安全停用 | `DC1 + E11 + C3 + T1 + M1 + K2 -> CB -> DA2 -> DB2 -> DC2` | `DC2 ACCEPTED` |
| 第一阶段后续目录成熟化 | 在后续独立发布中补齐完整目录能力 | 本图只有交接记录，不创建可自动调度节点 | 不计入 1A、1B 或 `DC2` |

第 11 次修订的独立终验节点（`D3A`）达到已接受状态（`ACCEPTED`），是两个候选的外部晋升条件，不是开发前置。身份、组织接入和测试可以在隔离候选中并行开发，但不得提前合入或发布。

## 3. 已接受的稳定决定

1. 授权只来自服务端会话、成员关系和组织绑定。前端租户编号、平台管理员身份或页面选择都不是授权事实。
2. 一个用户可以拥有个人工作区并加入多个组织；系统不保存永久单一用户类型字段（`user_type`）。
3. 会话必须返回租户、工作区、正文权威、成员角色和组织绑定状态；前端不得猜测。
4. 组织应用身份统一为自媒体组织应用（MediaClaw B）；旧产品名称（Company OS）在相同范围内失效。
5. 既有组织绑定试点先于通用组织接入。第一阶段撤销只做停用、凭据撤销、停止外部写入、冻结成员访问和保留审计。
6. 平台账号与飞书成员只能通过显式身份关联（`IL1`）连接，禁止按邮箱或姓名自动合并。
7. 身份汇合（`C1`）接受后可启动第二阶段个人内容支线；组织接入汇合（`C3`）接受后可启动第二阶段组织内容支线。

稳定方向与六项用户选择已经接受。稳定决定保存在稳定决定节点（`K`），局部决定保存在局部决定节点组（`K1-K6`）；近期活动处置和文档写入器阶段边界因本轮澄清提升到第 2 版。个人平台认证的登录、注册、找回、会话、跨站请求保护和显式身份关联由认证合同决定节点（`K6`）独立承载。

### 3.1 可复用的本地候选证据

生产闭环 SSOT 的第 23 波已经在当前共享本地候选内容校验值（`f1ac7865...45bcb`）上证明：外部博主不能提供运营资格；客户自有账号只能按租户、当前用户、平台、账号和有效正式关系唯一命中；非目标工作区、错误角色、无效维护者或成员关系必须在入队前失败关闭。该共享证据（`EV-MPE2E-C5-R3-SHARED-LOCAL`）只供显式身份关联节点（`IL1`）、会话与工作区解析节点（`I3`）、身份与工作区汇合节点（`C1`）复用测试事实和候选身份，不改变三个节点的阻塞状态（`BLOCKED`），也不证明显式身份关联完整流程、会话主体第 2 版（`SessionPrincipal v2`）、工作区解析结果（`WorkspaceResolutionResult`）、身份候选汇合、部署或生产验收。

## 4. 已拍板的局部决定

| 决定 | 已接受选择 | 直接约束 |
| --- | --- | --- |
| 个人第一版认证方式 | 个人使用平台独立认证，不要求飞书；所有交付文档在云端保存和预览；平台账号与飞书成员不得按邮箱或姓名自动合并 | `I1`、`I2` 与个人工作区入口 |
| 发布控制边界 | 发布后直接向全部合格用户开放并采用单一路径硬切换；只保留发布前门禁、全局紧急停止和外部写入停止 | `CA`、`CB` 与生产切换 |
| 第一版成员接入方式 | 普通成员首次完成服务端飞书授权时即时建立，唯一外部成员字段为 `open_id`；完整目录同步后移 | `P9`、`C3` 与发布增量 1B |
| 近期活动的数据归属 | 近期活动是租户私有数据，必须补齐归属、迁移存量、服务端过滤和跨租户负例 | `I6` 与数据迁移 |
| 第一阶段资源解析边界 | 第一阶段只做资源发现、只读镜像、同步补水和可信打开；人工智能文档写入由第二阶段唯一拥有 | `I7` 与第二阶段写入路由 |
| 个人平台认证具体合同 | 用户名或已验证邮箱加密码登录；注册后必须在二十四小时内完成单次邮箱验证；通过三十分钟单次链接找回；重置后撤销全部旧会话；浏览器使用八小时服务端会话 | `K6` 解除 `I1`、`I2` 与 `IL1` 的决定阻塞 |

六项决定的批准值、来源、适用范围和存量处理保存在机器决定节点（`.ssot/nodes/K1.json` 至 `.ssot/nodes/K6.json`）；本阶段已无开放产品问题，因此不生成开放问题文件（`openproblem.md`）。

### 4.1 个人平台账号完整流程

#### 注册

1. 用户在统一入口选择“个人创作者”，再进入个人注册页。注册只收集唯一用户名、唯一邮箱和密码，不调用飞书，也不创建组织身份。
2. 密码至少十二个字符、最多一百二十八个字符；不强制大小写、数字和符号组合，但拒绝已知泄露或常见弱密码，并允许粘贴和密码管理器填写。
3. 提交成功后，账号进入待验证状态（`PENDING_EMAIL_VERIFICATION`）。此时不签发完整登录会话；个人工作区在邮箱首次验证成功时幂等建立。
4. 系统发送二十四小时有效、只能使用一次的验证链接。用户重发邮件后，此前所有未使用链接立即失效，只有最新一封有效。
5. 验证成功后账号进入有效状态（`ACTIVE`），页面返回个人登录入口，不自动登录。过期、已使用或被重发撤销的链接只能引导用户重新发送验证邮件。

#### 登录

1. 有效账号可以输入唯一用户名或已验证邮箱，再输入密码。既有账号即使旧邮箱尚未验证，也可以继续用用户名登录。
2. 用户名、邮箱、密码或账号状态不符合时，页面统一提示“账号或密码错误”，不说明账号是否存在。只有密码已经校验通过时，待验证账号才显示完成邮箱验证的安全引导；停用账号（`SUSPENDED`）不能取得会话。
3. 登录成功后，服务端轮换会话标识并进入个人工作区。会话最长八小时，不提供“记住我”；浏览器只保存安全会话标记（Cookie），并分别启用禁止脚本读取属性（`HttpOnly`）、仅加密连接属性（`Secure`）和同站宽松限制属性（`SameSite=Lax`）。
4. 所有修改数据的请求都必须校验与当前会话绑定、可以轮换的跨站请求保护令牌。个人登录、注册、验证和找回全程不调用飞书。

#### 找回与重置

1. 用户在“忘记密码”页输入用户名或邮箱。无论账号是否存在、是否有效、邮箱是否验证，页面都返回同一句“如果账号符合条件，我们会发送邮件”，避免暴露账号信息。
2. 只有有效且拥有已验证邮箱的账号会收到找回邮件。链接三十分钟有效、只能使用一次；新邮件发出后旧链接立即失效。
3. 验证链接和找回链接都使用至少二百五十六比特熵的密码学随机值，服务端只保存摘要，不保存可直接使用的链接令牌。
4. 新密码通过同一密码策略后，服务端撤销该账号全部旧会话和全部未使用找回令牌，再返回个人登录入口；系统不自动登录。

#### 存量账号与客服边界

- 既有平台账号统一迁入新的个人入口，继续使用用户名和密码；旧邮箱不得自动视为已验证，验证前不能用于邮箱登录或密码找回。
- 客服只能重发标准验证或找回邮件、撤销会话并引导用户完成标准流程；客服不能读取密码、生成临时密码、绕过邮箱验证或代替用户绑定飞书身份。
- 旧版自媒体产品（Media）的密码登录和改密接口继续返回未找到状态（`404`）。新个人认证是独立平台合同，不能把旧接口重新开放为兼容路径。
- 平台账号与飞书身份只能由已登录用户主动发起飞书授权并二次确认后绑定，禁止按邮箱或姓名自动合并。

### 4.2 工程映射边界

| 业务动作 | 必须冻结的服务端语义 | 机器状态或对象 | 实现归属 |
| --- | --- | --- | --- |
| 提交注册 | 规范化后检查用户名与邮箱唯一性，创建待验证账号，不签发完整会话 | `PENDING_EMAIL_VERIFICATION`、邮箱验证令牌摘要 | `B` 定义合同承载位置，`I2` 编译并实现，`I1` 提供界面 |
| 验证或重发邮箱 | 二十四小时、单次使用；重发撤销旧链接；首次成功时幂等建立个人工作区 | `email_verified_at`、验证令牌状态、`ACTIVE` | `B` 定义合同承载位置，`I2` 编译并实现，`T1` 提供门禁框架 |
| 个人登录 | 仅用户名或已验证邮箱加密码；只允许有效账号；成功后轮换会话 | 服务端会话、个人工作区会话主体 | `B` 定义合同承载位置，`I1/I2/I3` 编译并实现 |
| 请求找回 | 始终返回统一提示；只有有效且邮箱已验证的账号接收邮件 | 找回令牌摘要、发送与限流记录 | `B` 定义合同承载位置，`I1/I2` 编译并实现 |
| 重置密码 | 三十分钟、单次、最新链接有效；成功后撤销全部旧会话与未使用找回令牌 | 密码凭据版本、会话撤销记录 | `B` 定义合同承载位置，`I2` 编译并实现，`T1` 提供门禁框架 |
| 安全退出 | 当前会话立即失效；支持账号支持人员按权限撤销全部会话 | 会话撤销记录 | `B` 定义合同承载位置，`I2` 编译并实现 |

认证合同决定节点（`K6`）只冻结上述业务状态、时效和安全语义，不提前指定接口地址、数据库表名或邮件供应商。共享合同汇编节点（`B`）定义唯一 OpenAPI 承载位置、错误模型和安全配置规则；个人认证实现节点（`I2`）同时消费共享合同汇编节点（`B`）与认证合同决定节点（`K6`），把具体动作编译进该唯一合同；验收节点（`T1`）提供共享红绿门禁框架。

## 5. 发布与恢复边界

禁止长期双授权、部署级全局凭据回退、双人工智能文档写入权威、租户白名单、灰度路径、长期功能开关和隐式回退。发布增量 1A 发布前，所有人工智能文档入口必须隐藏，直接接口、旧链接与旧任务重放统一返回能力不可用状态（`capability_unavailable_until_writer_migration`），外部写入调用数为零。第二阶段只能由统一写入路由（`WriterRouter`）从该关闭态接管。

恢复语义分为三层：

1. 代码发布只对不可变发布身份做原子切换。
2. 数据库使用前向迁移和明确的恢复合同，不把不可逆迁移描述为普通回滚。
3. 飞书外部动作使用幂等步骤、远端回读、补偿和待人工处置状态（`NEEDS_ATTENTION`），不得声称与代码和数据库形成跨系统原子回滚。

## 6. 明确排除项

- 第一阶段资源解析节点（`I7`）不接入人工智能文档写入器，也不决定个人或组织正文写到哪里；写入关闭节点（`I9`）确保旧全局文档写入器不可调用。
- 第二阶段拥有人工智能执行上下文、资料路由、统一文档写入器、个人内部成果和组织飞书写入。
- 第三阶段拥有完整组织角色、审核协作、席位、采购、发票、跨租户迁移、复杂删除和经营分析。
- 本文件不接管第 11 次修订候选的节点、调度、状态或证据写入权威；外部门（`E11`）仅为只读机器硬门。
- 完整组织目录成熟化移交第一阶段后续目录成熟化交接，本图不创建目录成熟化执行节点或任何自动启动入口。

## 7. 工程执行附录

### 7.1 依赖与执行关系

身份入口并行关系是：

```text
B + G1 + M1 + K1 + K6 -> I1
B + G1 + M1 + K1 + K6 -> I2
I2 + K1 + K6 -> IL1
I1 + I2 + IL1 + MA1 -> I3
```

运行环境人工初始化节点（`GA1`）不使用 Codex worker，由执行环境负责人先建立五类配置。只读能力门（`G1`）随后由确定性本地命令验证这些配置，同样不启动 Codex worker；无 Git 候选汇合节点（`M1`）负责开发基线、晋升基线与重建协议：

- 实现运行配置（`implementation-runner`）：隔离基线、最小可写目录、无生产凭据；
- 静态验证配置（`static-validation-runner`）：只读候选，允许写临时目录和临时数据库，禁止修改候选、生产数据库和外部系统；
- 外部测试配置（`external-test-runner`）：只允许访问隔离测试组织与受限外部写身份；
- 生产发布配置（`production-release-runner`）：只在批准窗口持有发布权限，并由单一发布节点使用。
- 独立只读配置（`independent-readonly-runner`）：只读候选、生产身份和外部回执，不具备修复、状态写入或外部写权限。

人工初始化节点（`GA1`）已经登记五类配置、绝对启动器和凭据边界；只读能力门（`G1`）已经通过本地启动与失败关闭探针。该证据只证明本地配置与权限边界，不证明真实外部账号、生产批准、部署或生产行为；对应外部身份和批准仍由各运行节点单独提供。

无 Git 候选汇合节点（`M1`）已经实现并验证开发基线、晋升基线、节点补丁清单、文件归属、固定应用顺序、冲突检测和候选确定性重建。`CA` 必须把 1A 补丁重放到 `E11` 候选，`CB` 必须把 1B 补丁重放到 `DC1` 候选；冲突会使受影响节点失效并重跑测试。`CA/CB` 由确定性本地脚本执行，不启动 Codex worker。

### 7.2 文件导航

- 依赖拓扑文件（`generated-views/10-dependency-topology.md`）：输入一致性、外部门、依赖图和机器节点。
- 执行治理文件（`generated-views/20-execution-governance.md`）：叶子交付、运行配置、无 Git 汇合协议、资源和门禁。
- 验收合同文件（`generated-views/30-node-contracts-and-acceptance.md`）：完整节点合同、验收矩阵、证据和清除要求。
- 实施进度文件（`implementation-progress.md`）：当前正式状态、就绪前沿与下一步。
- 来源说明（`source-notes.md`）：输入基线、六项用户决定和已确认事实。
"""


def topology_view() -> str:
    input_rows = [
        ["Revision 11 正式状态", CANONICAL, "canonical D3A", "E11 自动投影", "原 SSOT", "当前未接受", "E11 绑定状态、候选和证据哈希，再硬阻塞 CA/CB", "n/a"],
        ["统一登录选择个人或组织", "当前用户决定与源码事实", "工作区意图", "I1 与 I2 并行", "服务端认证绑定", "个人不用飞书且平台认证合同已接受", "按 K6 实现双认证意图", "K1/K6 已接受"],
        ["个人账号完整生命周期", "当前用户决定与现有注册服务事实", "待验证账号、邮箱验证、找回令牌和服务端会话", "I1/I2/T1", "K6 决定与服务端账号状态", "当前注册成功直接签发会话，不符合目标", "按 K6 改为先验证后登录，并补齐统一找回与全部会话撤销", "K6 已接受"],
        ["一个用户多工作区", AUDIT, "Membership、Binding 与 ExplicitIdentityLink", "IL1/I3", "服务端 Session", "当前会话字段和显式关联均不足", "按 K6 显式绑定后生成 SessionPrincipal v2", "K/K6 已接受"],
        ["按组织 Binding 读取资源", AUDIT, "Binding 与资源", "I7", "服务端解析器", "当前路径依赖全局凭据", "只保留发现、镜像、同步和打开，排除人工智能写入", "K5 已接受"],
        ["组织自助接入", AUDIT, "组织接入状态与回执", "P1-P3/P5-P10", "安装事件、管理员流程、成员首次授权和失效", "只有试点脚本", "试点后形成含即时接入与最小失效的发布增量 1B", "K3 已接受"],
        ["完整组织目录", LATEST_REVIEW, "Stage 1C 交接", "后续独立发布", "不在本自动调度图", "不是 1A/1B 必需", "只保留交接；P9 即时建立，P10 提供最小失效", "K3 已接受"],
    ]
    authority_rows = [
        ["第一阶段新增合同与编排", ".ssot/manifest.json 及其 nodes/edges", "decision/orchestration", "机器校验", "是", "B-CA-DC2", "check_ssot_program.py"],
        ["Revision 11 D1-D3A 合同、调度、状态和证据", CANONICAL, "domain-contract", "E11 只读 D3A", "否；本包无执行节点", "E11", "canonical D3A 正式回执"],
        ["当前产品和代码事实", AUDIT, "runtime-evidence", "来源路径与审计证据定位", "否", "A1", "文件哈希和后续源码读回"],
        ["稳定产品决定", ATTACHMENT, "domain-contract", "用户附件和事实审计", "已汇编到 K", "K", "决定记录第 2 版"],
        ["局部产品决定", ".ssot/nodes/K1.json 至 .ssot/nodes/K6.json", "decision/orchestration", "读取用户选择、日期、范围和存量处理", "K1-K6 全部已接受", "K1-K6", "决定状态与批准记录核对"],
        ["第 4 版结构修正", LATEST_REVIEW, "research/hypothesis", "校验值与逐项合同映射", "是", "A/E11/GA1/MA1/MB1/I9/P10", "机器图与负例门禁"],
        ["账号与工作区共享本地候选证据", SHARED_EVIDENCE["EV-MPE2E-C5-R3-SHARED-LOCAL"]["source_bundle"], "runtime-evidence", "按候选、结果和验证日志校验值只读引用", "否", "IL1/I3/C1", "只复用已证明的唯一关系与工作区失败关闭；不提升节点状态"],
        ["生成 Markdown", ".ssot/view-sources/*.md -> renderer", "execution-record", "manifest 哈希绑定", "自动生成", "A", "render --check"],
    ]
    uncertainty_rows = [
        ["真实外部与生产身份尚未登记", "execution-blocker", "I8/DB1/DB2 节点身份台账", "runtime acceptance owner", "只阻塞外部测试与生产动作", "真实账号、租户、批准窗口和同收据证据"],
        ["真实飞书试点身份和验收账号", "execution-blocker", "I8/DB1/DB2 身份台账", "runtime acceptance owner", "只阻塞外部与生产动作", "同收据外部系统证据"],
        ["Revision 11 D3A 尚未接受", "evidence-gap", "canonical D3A 证据目录", "canonical owner", "只阻塞 CA 与 CB 晋升", "canonical D3A ACCEPTED"],
    ]
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
    mermaid_graph = "\n".join(
        ["```mermaid", "flowchart TD"]
        + [f"  {source} --> {target}" for source, target, _ in EDGES]
        + ["```"]
    )
    return "\n\n".join([
        "# 第一阶段权威与依赖拓扑",
        "## 输入一致性",
        table(["Promised behavior", "Input location", "Owning model/field", "API or workflow entry", "Permission/state authority", "Conclusion", "Action", "Blocking decision node"], input_rows),
        "## 权威登记",
        table(["Claim/domain", "Declared authority path", "Authority layer", "Lookup method", "Change required", "Owning node", "Validation"], authority_rows),
        "生成的主文档只是读取视图，不是第二套权威。第 11 次修订（Revision 11）在本机器依赖图（DAG）中没有执行节点；外部门（E11）是零写入自动投影，并通过真实硬边约束候选汇合节点（CA）与候选汇合节点（CB）。",
        "## 不确定性路由",
        table(["Uncertainty", "Class", "Destination", "Owner", "Blocking scope", "Resolution evidence"], uncertainty_rows),
        "## 文本拓扑图（ASCII 拓扑图）",
        "```text\nA -> A1 -> K -> B\n     |      \\-> K1..K6 (accepted) -> I1/I2 -> IL1 -> I3\n     |-> GA1 (manual, zero Codex) -> G1 (deterministic profile verification) -> M1/T1\n     \\-> E11 (automatic canonical D3A projection) --------------------+\n\nB/G1/M1/K4 -> MA1 -> I3/I6 -> I4/I5/I7/I9 -> C1/I8 -> C2\nE11 + C1 + C2 + T1 + M1 + K2 -> CA (deterministic rebuild) -> DA1 -> DB1 -> DC1\nC2/G1/M1 -> MB1 -> P1 -> P2 -> P3 -> P5/P6 -> P7/P8\nK3 + I2 + P3 + MB1 + T1 -> P9 -> P10 -> C3\nE11 + DC1 + C3 + T1 + M1 + K2 -> CB (deterministic rebuild) -> DA2 -> DB2 -> DC2\nDC1 + DC2 -> DA -> DB -> DC (automatic projections, zero Codex)\nStage 1C directory maturity: handoff only; outside this DAG\n```",
        "## 依赖图（Mermaid）",
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
        width_rows.append([
            batch,
            len(rows),
            len(rows),
            0,
            logical,
            slots,
            math.ceil(logical / slots),
            0,
            9,
            0,
        ])

    registration_rows = []
    process_rows = []
    cleanup_rows = []
    for node_id, node in NODES.items():
        transport_value = node.get("worker_transport")
        registration = node.get("worker_registration") or {}
        if transport_value is None:
            registration_rows.append([
                node_id, "none", "n/a", PROJECT_ROOT_TEXT,
                "no worker registered; completed history or thin control node",
                "n/a", "EXITED" if node["execution_state"] in {"IMPLEMENTED", "VERIFIED", "ACCEPTED"} else "BLOCKED", "n/a",
            ])
            process_rows.append([
                node_id, 0, 0, "node-local owner or historical record; no Codex process",
                "n/a", f"stage1-v5-{node_id}", "n/a", "n/a", "n/a",
            ])
            cleanup_rows.append([
                node_id, "not-applicable; zero Codex process", "not-applicable; zero Codex process",
                "not-applicable; zero Codex process", "not-applicable; zero Codex process",
                "not-applicable; zero Codex process", "not-applicable; zero Codex process",
            ])
        elif transport_value == "historical-unregistered":
            registration_rows.append([node_id, node["worker_transport"], "n/a", PROJECT_ROOT_TEXT, "no retroactive worker claim", "n/a", "EXITED", "n/a"])
            process_rows.append([node_id, 0, 0, "historical source or decision already accepted", "n/a", f"historical-{node_id}", "historical-unverified", "historical-unverified", "historical-unverified"])
            cleanup_rows.append([node_id, "historical-unverified", "historical-unverified", "historical-unverified", "historical-unverified", "historical-unverified", "historical-unverified; no retroactive worker claim"])
        elif transport_value in {"external-manual", "deterministic-local", "automatic-projection"}:
            transport = str(transport_value)
            if transport == "external-manual":
                project_root = "n/a"
                literal_contract = str(registration["note"])
                authority = "not applicable"
                stop = "named owner writes a complete receipt or records terminal refusal"
                retry_limit = 0
            elif transport == "deterministic-local":
                project_root = str(registration["project_root"])
                literal_contract = (
                    f"{registration['note']}; command={registration['command']}; "
                    f"determinism_key={registration['determinism_key']}"
                )
                authority = "bounded local process"
                stop = "two rebuilds emit the same candidate hash or fail closed"
                retry_limit = 1
            else:
                project_root = "n/a"
                literal_contract = (
                    f"{registration['note']}; rule={registration['projection_rule']}"
                )
                authority = "generated state only"
                stop = "projection receipt matches all named source states"
                retry_limit = 0
            registration_rows.append([
                node_id, transport, "n/a", project_root, literal_contract, authority,
                registration["dispatch_state"], registration["return_path"],
            ])
            process_rows.append([
                node_id, 0, retry_limit, stop, "main orchestrator",
                f"stage1-v4-{node_id}", "n/a", "n/a", "pending",
            ])
            cleanup_rows.append([
                node_id,
                "not-applicable; zero Codex process",
                "not-applicable; zero Codex process",
                "not-applicable; zero Codex process",
                "not-applicable; zero Codex process",
                "not-applicable; zero Codex process",
                "not-applicable; zero Codex process",
            ])
        else:
            registration_rows.append([
                node_id, transport_value, registration["wrapper"], registration["project_root"],
                registration["invocation"], registration["sandbox_authority"], registration["dispatch_state"], registration["return_path"],
            ])
            if node_id == "B" and node["execution_state"] == "ACCEPTED":
                process_rows.append([
                    node_id, 1, 1,
                    "structured return plus scoped acceptance or terminal failure", "main orchestrator",
                    "stage1-v4-B-retry-2", "PID 41334 / session 01a0098f-b6a1-7980-8a4b-a9359694e22b",
                    registration["log_path"], 0,
                ])
                cleanup_rows.append([
                    node_id, registration["prompt_path"], registration["prompt_sha256"], registration["launch_barrier"],
                    registration["prompt_cleanup"], registration["runtime_handle_cleanup"], registration["codex_transcript_retention"],
                ])
            else:
                process_rows.append([
                    node_id, 1, 0 if registration["worker_level"] == "L3" else 1,
                    "structured return plus scoped acceptance or terminal failure", "main orchestrator",
                    f"stage1-v4-{node_id}", "pending", registration["log_path"], "pending",
                ])
                cleanup_rows.append([
                    node_id, registration["prompt_path"], registration["prompt_sha256"], registration["launch_barrier"],
                    registration["prompt_cleanup"], registration["runtime_handle_cleanup"], registration["codex_transcript_retention"],
                ])

    profile_rows = [
        ["implementation-runner", "T1/MA1/MB1/I1-I7/I9/P1-P3/P5-P10/C1/C3", "隔离开发基线与节点最小写入根", "生产凭据、活动发布、其他租户", "VERIFIED_LOCAL", "GA1/G1 已接受；M1 可使用"],
        ["static-validation-runner", "DA1/DA2", "只读候选；可写临时目录和临时数据库", "修改候选、生产数据库和外部系统", "VERIFIED_LOCAL", "GA1/G1 已接受；候选节点另行绑定"],
        ["external-test-runner", "I8", "隔离测试组织与受限外部写身份", "生产发布和其他组织", "VERIFIED_LOCAL_FIXTURE", "真实隔离组织身份由 I8 提供"],
        ["production-release-runner", "DB1/DB2", "批准窗口、单一候选和生产发布身份", "未批准窗口与未列明外部资源", "FAIL_CLOSED_VERIFIED", "真实批准窗口由 DB1/DB2 提供"],
        ["independent-readonly-runner", "C2/DC1/DC2", "只读源码、候选、生产身份和外部回执", "源码修复、数据库写入、外部写入和节点状态写入", "VERIFIED_LOCAL", "真实只读身份由各验收节点提供"],
    ]
    merge_rows = [
        ["development_base", "提前开发所用源码快照及每个文件的路径、大小与 SHA-256", "M1", "开始任何节点 patch 前"],
        ["promotion_base", "CA 使用 E11 绑定的 canonical D3A 候选；CB 使用 DC1 接受候选", "M1/CA/CB", "候选重建前"],
        ["node patch manifest", "节点、基线身份、patch、文件 ownership、测试和 return.json", "每个实现节点", "worker 退出前"],
        ["apply order", "固定拓扑序和数据库迁移序；禁止目录覆盖", "candidate assembly owner", "CA/CB 重建时"],
        ["conflict detection", "同文件非声明重叠、过期基线、漏补丁和顺序漂移失败关闭", "M1", "应用每个 patch 前后"],
        ["candidate rebuild", "从 promotion_base 重放全部已接受 patch；冲突使所属节点失效；重复两次得到同一候选哈希", "CA/CB deterministic-local", "每次候选变化后"],
    ]
    guard_rows = [
        ["G-DOC", "用户授权与机器源第 4 版", str(BUNDLE), "其他 agents-results、canonical 包、项目代码和远程系统", "none", "none", "none", "不得读取凭据", "六个输入校验值与六项已接受决定", "重跑生成器恢复通过校验的视图", "只允许本 bundle 任务自有文件", "render/check/snapshot 哈希读回", "来源、决定记录或生成视图漂移"],
        ["G-PHASE1", "K 第 2 版稳定决定、K1-K6 已接受局部决定、GA1/G1 与 M1", str(PROJECT_ROOT / ".codex-work"), "Revision 11、活动发布、其他 agents-results 和未授权租户", "只限节点声明的隔离数据库或测试组织", "只执行节点合同列明动作", "禁止跨租户迁移和复杂资源删除", "秘密只通过受控输入，不进 argv、日志或截图", "开发基线、schema 和运行身份", "丢弃隔离候选；外部动作按回执补偿", "patch manifest 与基线差异", "Session、Membership、Binding 与节点输出", "越界写、泄密、冲突或候选漂移"],
        ["G-STATIC", "CA/CB 不可变候选与静态验证合同", "隔离构建目录、临时目录和临时数据库", "候选源、生产数据库、活动发布、凭据存储和外部系统", "none", "none", "仅清理本次隔离临时资源", "验证进程不得接收生产凭据", "候选哈希、迁移拓扑和干净临时资源", "删除临时目录和临时数据库后可重复执行", "候选哈希不变且临时资源无越界写入", "构建、合同、迁移与候选哈希回读", "候选被修改、生产资源被访问或临时写入越界"],
        ["G-RELEASE", "CA/CB 候选、K2、E11 和批准窗口", "不可变候选与本 bundle 证据目录", "Revision 11 权威、其他项目栈和未列明租户", "批准生产栈和隔离飞书组织", "仅 DB1/DB2 切换代码身份、执行迁移合同和外部步骤", "只允许前向迁移与已声明最小撤销", "凭据由生产配置注入并脱敏", "候选、数据库、飞书资源、停止开关和恢复点", "代码回指旧身份；数据库按恢复合同；飞书补偿或 NEEDS_ATTENTION", "发布前后哈希、schema、进程与外部资源差异", "真实浏览器、数据库、飞书与服务同收据", "负例失败、读回缺失或观察告警"],
        ["G-ZERO", "职责分离与 independent-readonly-runner", str(BUNDLE / "evidence"), "源码、候选、数据库、服务、飞书资源和节点状态源", "生产与飞书只读入口", "none", "none", "只用验收身份且无写凭据", "读取所属 DB1/DB2 接受证据身份", "无修复；失败返回 owning node", "仅新增独立证据结论", "哈希、发布、租户、Binding、设备和时间", "发现写入或证据身份不一致"],
    ]

    concern_rows = [
        ["security / authentication / secrets", "required", "I2/I6/P2/P3", "OAuth 防篡改、服务端授权、秘密扫描和撤销负例"],
        ["privacy / compliance / retention", "required", "I6/P8/P9", "租户隔离、open_id 最小使用、最小日志和审计保留合同"],
        ["migration / backup / recovery", "required", "MA1/MB1/P6", "两套前向迁移编号、备份身份、检查点恢复和回读"],
        ["reliability / rollback / disaster", "required", "P6/DB1/DB2", "代码原子切换、数据库恢复合同、外部幂等补偿和事故停止条件"],
        ["performance / capacity", "required", "P6/P9/P10", "即时成员并发、队列与外部配额上限；完整目录转交 Stage 1C"],
        ["observability / alerting", "required", "P6/P7/DB1/DB2", "步骤回执、NEEDS_ATTENTION、告警和观察窗口"],
        ["accessibility / internationalization / i18n", "required", "I1/I4/I5/P7", "键盘、移动端、中文错误和语义标签"],
        ["cost / external-service", "required", "P5/P9/DB2", "飞书 API 配额、重试上限和资源创建计数"],
        ["deployment / readback / monitoring", "required", "DA1/DB1/DA2/DB2", "候选身份、代码切换、生产读回和监控"],
        ["operational / handoff", "required", "C1/C3/DC2", "第二阶段移交、支持处置和独立终验责任"],
    ]

    resource_rows = [
        ["RES-R11-CANDIDATE", "Revision 11 D3A 外部状态", "E11/CA/CB", "R", "external authority", "E11 自动投影；本包不登记 canonical 执行器或写证据"],
        ["RES-MACHINE", "本 bundle 机器分片与 manifest", "A/B/CA/CB", "W", "single-generated-artifact", "唯一汇编 owner 写 manifest 和视图索引"],
        ["RES-NOGIT", "基线、patch manifest 与候选重建", "M1/all implementation/CA/CB", "W", "baseline hash", "固定应用顺序；冲突失败关闭；禁止目录 overlay"],
        ["RES-AUTH", "Session/OAuth/OpenAPI 合同", "I2/I3/I6/T1", "W", "write-write", "T1 维护共享合同；业务节点写各自实现"],
        ["RES-DB-1A", "账号、会话、工作区与近期活动 schema", "MA1/I3/I6", "W/R", "single-migration", "MA1 独占 Release 1A 迁移编号；I3/I6 只消费"],
        ["RES-DB-1B", "安装、接入回执与成员身份 schema", "MB1/P1/P3/P6/P9/P10", "W/R", "single-migration", "MB1 独占 Release 1B 迁移编号；其余节点只消费"],
        ["RES-FEISHU-PILOT", "隔离 Pilot 组织", "I8/C2", "W/R", "external identity", "I8 独占写；C2 零写入复核"],
        ["RES-PROVISION", "隔离安装、资源、成员首次授权与失效", "P2-P10", "W", "installation identity", "按安装身份、(binding_id, open_id) 和步骤租约串行外部动作"],
        ["RES-PRODUCTION", "活动发布与数据库", "DB1/DC1/DB2/DC2", "W/R", "release identity", "DB1/DB2 单写；DC1/DC2 真正只读"],
    ]

    return "\n\n".join([
        "# 第一阶段执行治理",
        "## 叶子交付清单",
        table(["Deliverable ID", "Parallel batch", "Deliverable", "Authority write region", "Dependencies", "Isolation decision", "Conflict class", "Owning node", "Grouping reason"], DELIVERABLES),
        "每个独立叶子交付只归属于一个数字节点。候选、迁移、外部安装和生成视图等共享资源通过资源表串行，不因可用工作进程（worker）数量而强行并发。",
        "## 最大安全并行宽度",
        table([
            "Parallel batch", "Leaf deliverables", "Independent deliverables",
            "Conflict-grouped deliverables", "Logical lane target",
            "Available worker slots", "Wave count", "Graph ready width",
            "Graph antichain width", "Resource-verified width",
        ], width_rows),
        "## 工作进程（Worker）执行合同",
        "人工前置使用外部人工传输（`external-manual`），候选重建使用确定性本地传输（`deterministic-local`），状态汇总使用自动投影传输（`automatic-projection`），三者都登记零个 Codex 进程。真正的人工智能实施与审查节点才使用外部 Codex 执行传输（`external-codex-exec`）。合格封装脚本（wrapper）的最终调用必须保留最终调用命令（`exec codex exec`）；聊天内子代理接口（`spawn_agent`）、聊天内子代理和同进程协作接口均不得替代外部工作进程（worker）。登记不是启动授权，也不得由本包调度第 11 次修订（Revision 11）。",
        table(["Task ID", "Transport", "Wrapper", "Project root", "Literal codex exec contract", "Sandbox authority", "Dispatch state", "Return path"], registration_rows),
        "## 五类运行配置前置",
        table(["Runtime profile", "Owning nodes", "Required capability", "Forbidden capability", "Current state", "Blocking node"], profile_rows),
        "## 无 Git 候选汇合协议",
        table(["Protocol element", "Required record or behavior", "Owner", "Gate timing"], merge_rows),
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
        "L1 只修正文案、定位或非语义执行信息；L2 修改依赖、节点或验收；L3 修改认证、权限、数据迁移、外部生命周期或发布身份。L2/L3 必须更新机器分片并重建全部视图。每个发现最多做一次有界独立复核；复核不得修改候选。",
    ])


def acceptance_view() -> str:
    contract_rows = []
    for node_id, item in SPECS.items():
        contract_rows.append([
            node_id, item["title"], item["user"], item["inputs"], item["processing"], item["output"],
            item["tests"], item["acceptance"], item["dod"],
        ])
    evidence_rows = [current_evidence_row(node_id) for node_id in NODES]
    evidence_rows.extend(shared_evidence_row(evidence) for evidence in SHARED_EVIDENCE.values())
    cleanup_rows = [
        ["Revision 11 候选", "external immutable candidate", "新登录、Provision 或 Writer 混入", "禁止；本包只读 D3A 状态", "否", "E11 到 CA/CB 的机器硬边"],
        ["身份模型", "legacy field", "永久单一 user_type 与 ordinary 工作区写入", "迁移后删除消费路径并加负例", "仅迁移读取可短期存在", "I3/DA1"],
        ["认证", "legacy interface", "Media 密码登录、改密或 OPC 回调复用", "保持隔离并加入门禁", "否", "I2/DA1"],
        ["组织凭据", "implicit fallback", "部署级全局 app/secret/space/parent 运行路径", "I7 只读资源改用 Binding；Writer 由第二阶段清除", "仅未触达 Writer 的旧路径等待第二阶段", "I7/I8/Stage2"],
        ["Pilot", "migration helper", "硬编码组织、账号、初始口令和单页脚本", "只作来源参考；P6 接管后退役", "只可保留不可执行历史证据", "C2/C3"],
        ["应用命名", "duplicate authority", "Company OS 与 MediaClaw B 重叠名称", "统一到 MediaClaw B", "否", "B/P2/DA1"],
        ["发布控制", "runtime authority", "长期双授权、双 Writer、全局凭据回退、租户白名单、灰度、长期功能开关和隐式回退", "发布前门禁通过后全量单路径切换", "只保留全局紧急停止和外部写入停止", "K2/CA/CB"],
        ["执行临时项", "temporary", "prompt、PID/session 句柄、隔离端口", "进程退出证据登记后清理", "日志、return、ledger 与 Codex transcript 保留", "cleanup ledger"],
    ]
    return "\n\n".join([
        "# 第一阶段节点合同与验收",
        "## 完整节点合同",
        table(["Task ID", "Business target", "User", "Inputs", "Processing", "Outputs", "Tests", "Acceptance", "Completion definition"], contract_rows),
        "## 第一阶段正式验收矩阵",
        table(
            ["Acceptance area", "Required positive path", "Required negative path", "Owning nodes", "Completion evidence"],
            [
                ["Revision 11 外部门", "E11 只在 canonical D3A ACCEPTED 且候选回执绑定校验值时接受", "本包不得调度 R1-R4 或写 canonical 证据", "E11 到 CA/CB 的机器硬边", "canonical D3A 状态和候选身份只读回执"],
                ["运行配置与无 Git 汇合", "五类配置通过负例且候选可确定性重建", "danger-full-access 文字合同、目录 overlay 或冲突覆盖必须拒绝", "GA1/G1/M1", "配置能力回执、patch manifest 与重建哈希"],
                ["个人注册与邮箱验证", "提交唯一用户名、唯一邮箱和合格密码后进入待验证状态；最新验证链接在二十四小时内单次激活账号并幂等建立个人工作区", "重复邮箱、重复用户名、过期链接、旧链接、重放、并发激活、弱密码或注册后直接取得完整会话必须拒绝", "K6/I1/I2/T1", "真实浏览器、受控邮件投递、账号状态、令牌摘要和个人工作区读回"],
                ["个人登录与会话", "有效账号使用用户名或已验证邮箱加密码登录；服务端轮换会话并签发八小时安全 Cookie", "待验证或停用账号、错误凭据、会话固定、跨站请求、个人流程调用飞书、进入组织资源或前端租户编号授权必须拒绝", "K1/K6/I1-I4/T1/C1", "真实浏览器、服务端会话、安全 Cookie、跨站请求保护与飞书零调用读回"],
                ["个人找回与密码重置", "找回请求始终统一应答；有效且邮箱已验证的账号收到三十分钟单次最新链接；重置后返回登录入口", "账号枚举、未验证邮箱投递、过期、旧链接、重放、限流绕过、旧会话或旧找回令牌继续有效必须拒绝", "K6/I1/I2/T1/C1", "受控邮件、令牌摘要、密码凭据版本、全部会话与找回令牌撤销读回"],
                ["存量账号与客服边界", "既有账号从新个人入口使用用户名登录，完成邮箱验证后才可用邮箱登录或找回；客服只能重发标准邮件或撤销会话", "旧邮箱自动变成已验证、客服读密码或生成临时密码、绕过验证、恢复旧 Media 密码接口或按邮箱姓名合并身份必须拒绝", "K6/I1/I2/IL1/T1", "存量迁移夹具、客服权限负例、旧接口 `404` 与身份关联审计回执"],
                ["既有组织 Pilot", "选择组织、命中 Binding、组织工作台、只读镜像、可信打开和回读", "组织 A 不得解析组织 B 资源，也不得调用 Writer", "I5-I8/C2", "同一 Binding、资源和候选的真实飞书收据"],
                ["Release 1A", "CA 静态通过、生产推广、Pilot 外部通过和独立终验", "没有 canonical D3A、K2 或恢复合同必须拒绝", "CA/DA1/DB1/DC1", "哈希绑定的生产与外部同收据证据"],
                ["新组织 Provision", "安装、管理员确认、tenant/owner/Binding、资源、普通成员首次授权和 ACTIVE", "非管理员、重放、乱序、跨安装、伪造 open_id 和中断均失败关闭或续接", "P1-P3/P5-P9/C3", "隔离飞书组织全流程与成员首次进入收据"],
                ["成员即时建立", "从服务端飞书授权结果取得 open_id，并幂等创建或复用成员关系", "前端 open_id、邮箱或姓名合并、跨租户复用、歧义存量和撤销 Binding 必须拒绝", "K3/I2/P3/P9/C3", "同一 tenant_key、open_id、Binding 与候选的服务端回执"],
                ["最小撤销", "停用、撤销凭据、冻结写入和成员访问、保留审计", "撤销后缓存凭据或旧 worker 不得继续写", "P8/C3", "REVOKED 读回和写入拒绝"],
                ["安全", "Session、Membership、Binding 与服务端 open_id 一致时访问", "伪造 tenantId/open_id、个人调组织、A 调 B、平台 admin 越权均拒绝", "I2/I6/I7/P9/T1", "服务端负例、秘密扫描和审计日志"],
                ["Release 1B", "CB 静态通过、生产推广、飞书接入通过和独立终验", "跨系统原子回滚声称、目录同步硬依赖或绕过 DC1 必须拒绝", "CB/DA2/DB2/DC2", "哈希绑定的生产与飞书同收据证据"],
                ["目录成熟化", "按 Stage 1C 交接另建独立发布合同后实现", "目录成熟化缺失不得阻塞 P9、CA、CB 或 DC2", "K3 与 Stage 1C 交接", "未来独立发布证据"],
            ],
        ),
        "## 当前证据身份",
        table(["Evidence ID", "Task ID", "Evidence level", "Source revision", "Artifact hashes", "Environment", "Runtime release", "Actor role", "Account/tenant", "Device/browser", "Mock/fixture", "Observed at", "Acceptance contract"], evidence_rows),
        "本阶段当前登记证据的最高等级为本地运行级（`local-runtime`）：B、G1、M1、T1 与 I2 只证明本地合同、运行配置门禁、认证生命周期和无 Git 候选重建协议。共享上游候选证据只作为显式身份关联节点（`IL1`）、会话与工作区解析节点（`I3`）、身份与工作区汇合节点（`C1`）的相关证据，不改变这些节点的阻塞状态。目标真实设备或外部系统级（`physical-device/external-system`）只能由 DB1/DC1 与 DB2/DC2 对各自不可变候选的真实浏览器、数据库、飞书、账号、租户、组织绑定（Binding）和时间证据达到。",
        "## 清除清单",
        table(["Scope", "Type", "Old or temporary item", "Action", "May remain", "Evidence"], cleanup_rows),
        "## 禁止路径检查",
        "候选不得包含长期双授权、全局凭据回退、双写入器（Writer）权威、租户白名单、灰度、长期功能开关、双路径或隐式回退。数据库使用前向迁移与恢复合同；飞书动作使用幂等、回读、补偿和待人工处置状态（NEEDS_ATTENTION）。发布前门禁、全局紧急停止和外部写入停止只是切换与止损机制，不得成为第二业务权威。",
        "## 最终完成声明",
        "发布增量 1A 只有独立终验节点 DC1 已接受（ACCEPTED）才完成。第一宏观阶段的必需交付只有在 DC1 与 DC2 均已接受（ACCEPTED）时完成；第一阶段后续目录成熟化（Stage 1C）明确不计入该完成门。第二阶段支线提前启动不能替代 1A 或 1B 的任何验收节点。",
    ])


def progress_view() -> str:
    state_rows = []
    for node_id, node in NODES.items():
        if node["execution_state"] in {"IMPLEMENTED", "VERIFIED", "ACCEPTED"}:
            evidence = f"EV-{node_id}-CURRENT"
        elif node["related_evidence_ids"]:
            evidence = "related: " + ", ".join(node["related_evidence_ids"]) + "; node acceptance pending"
        else:
            evidence = "pending"
        state_rows.append([
            node_id, node["stage"], VERSIONS, node["execution_state"], 1 if node["execution_state"] in {"IMPLEMENTED", "VERIFIED", "ACCEPTED"} else 0,
            node["acceptance_authority"], guard_for(node_id), state_reason(node_id), evidence, node["unlocks"],
        ])
    ready_nodes = [
        node_id
        for node_id, node in NODES.items()
        if node["execution_state"] == "READY"
    ]
    ready_rows = [
        [
            f"stage1-{node_id.lower()}-next",
            node_id,
            NODES[node_id]["readiness_mode"],
            "n/a",
            "n/a",
            "conflict-free",
        ]
        for node_id in ready_nodes
    ]
    metrics = [
        ["ready-frontier-width", len(ready_nodes), "机器源中的 READY 节点动态计算"],
        ["formal-ready", len(ready_nodes), "B 与 GA1 的 readiness_mode 均为 FORMAL"],
        ["conditional-ready", 0, "没有条件就绪节点或活动假设"],
        ["global-completeness-barriers", sum(edge[2] == "global-completeness" for edge in EDGES), "CA/CB 各自三段发布验收及 DC1->CB"],
        ["critical-path-length", longest_path(), "按机器源硬依赖计算的最长节点路径"],
    ]
    return "\n\n".join([
        "# 第一阶段实施进度",
        "## 当前结论",
        "针对阶段一真实 PostgreSQL 空库验证暴露的组织接入阻塞，候选代码已完成以下前向修复：\n\n- 新增 `cm1-043-stage1-multi-tenant-primary-user`：移除 `tenants.primary_user_id` 的旧全局唯一约束，保留每个用户最多一个个人工作区的局部唯一索引，并移除只适用于旧 `lark_tenant_bindings` 的身份外键；Stage 1 当前绑定外键和 ACTIVE 状态检查仍然有效。\n- 个人密码登录只选择 `personal_web / internal` 租户；组织会话不能修改个人密码，避免同一用户拥有多个组织租户后产生凭据歧义或越权修改。\n- 真实空库已按 `001` 到 `043` 完整安装并通过迁移校验；同一用户同时拥有个人租户和组织租户时，组织属性、owner membership、Stage 1 binding、owner `open_id` 身份及确认幂等回执均可回读。个人密码登录命中个人租户，组织会话密码修改被拒绝。\n\n本增量只产生本地候选和一次性 PostgreSQL 验证证据，不代表节点正式接受、飞书回读、浏览器验收、部署或生产发布。候选源清单和 `candidate-manifest.json` 已按修复后源码重新绑定；阶段一正式状态仍以节点级独立接受和全局门禁为准。",
        "本 SSOT 已完成第 4 版结构修订。K1 到 K6 六项局部决定已经接受；K6 已在 2026-08-16 冻结个人账号注册、验证、登录、找回、会话、存量账号和客服边界。第 23 波共享本地候选证据已登记到 IL1、I3、C1，但只证明账号唯一关系和工作区失败关闭，不改变三个节点的阻塞状态（BLOCKED）。GA1 与 G1 已分别完成人工初始化和只读失败关闭验证并接受。B 的唯一 OpenAPI 合同和 7 项本地合同测试已经通过并正式接受；M1 的唯一补丁清单、双基线独立哈希绑定、逐文件文件归属、补丁顺序、冲突检测和两次确定性重建通过 32 项冻结测试，M1 正式接受。MA1 已完成发布增量（Release 1A）迁移静态验证（27 passed、3 subtests passed）；I1 的统一认证入口源质量检查（QA）与整合候选完整 build:media 已通过，且包含重新锁定后的个人工作区 deletion fixture 门禁，但 I1 仍只能保持本地 VERIFIED，真实浏览器、部署、邮件/飞书和生产验收仍待完成。I2 与 T1 的本地生命周期、公共路由和共享合同验证均已通过，共享路由验收合同（T1-AUTH-ROUTES）保护测试基线已锁定，二者仍标记为已验证（VERIFIED）。I4/I5 的 deletion fixture 变更已由用户和阶段一验收 owner 批准并重新锁定，三项聚焦测试和整合 build:media 均已通过；这只解除合同变更阻塞，不替代 I3 的正式接受，因此两节点仍保持 BLOCKED。以上均不是正式接受（ACCEPTED）：真实数据库回读、恢复、节点级独立接受、浏览器、邮件、飞书、部署、生产和设备验收仍未完成。本地机器、结构、复杂度、视图、中文可读性、运行时技能来源及带全局归档审计的统一 bundle validator 均已通过；本包快照 `--check` 与全局 Obsidian 归档审计也已通过。不调度第 11 次修订（Revision 11），也不把本地合同、验收运行或候选重建测试描述为外部或生产证据。",
        "阶段百分比口径（2026-08-18）：代码实现与远端发布 `100%`；本轮远端认证入口稳定性修复与验证 `100%`。这里的 `100%` 只表示本轮已声明的代码、发布和运行守卫范围已经完成，不等同于第一阶段正式 SSOT 完成。阶段一正式 SSOT 当前仍为 `partial/blocked`：E11/D3A、节点级独立接受、真实邮件/飞书、认证浏览器/设备和完整外部验收仍未关闭。",
        "2026-08-18 远端代码发布与稳定性回执：本地整合候选清单 `334b5133bd8e3cf03716757028bf584d03ff798b4d8dc69eb0de3edc267ed571` 绑定前端来源清单 `0d8a9aae1b9b178342d39059e5b167f191048e78f7c261ef0d1ee15b4f11066f` 与后端来源清单 `24a3e1aaf5b99663926f90f6bcbb3ff23729b2a8d8791da044893137c9872908`；阶段一测试 `208 passed`，前端 `npm run build:media` 和运行器配置门禁通过。`ubuntu@106.52.146.37` 当前激活前端 `20260818T-stage1-auth-entry-r10`，后端运行 `openclaw-tag-router-media-tenant-20260818T-stage1-auth-media-oauth-r9`，发布协调文件一致；公开索引哈希为 `6a9d49013b0888c83c6fe557ab96e68ed93bc60c4be03b1d6f7d87a059ea72d9`。20:08 的独立只读回读确认 `healthz=200`、`readyz=200`，登录入口和 `media.login.js` 为 `200`，未登录会话为 `401`，空认证请求为合同要求的 `400`，退役密码路径为 `404`，OAuth callback 无参数为 `400`；Nginx `-t` 通过且 canonical/已加载配置哈希均为 `9e0c8f99770fc9a825b43697b2b779abe53f29b073c83638486c17423fa14128`。定时 watchdog 本次 `Result=success`，状态 `failureCount=0`、`checks=70`、`repairs=[]`，其自测和登录面合同均通过。该证据仍只证明代码发布与运行稳定性，不前移节点级独立接受，也不证明生产数据库写入、真实邮件/飞书、认证浏览器或设备验收；完整回执见 `evidence-remote-release-20260818/remote-readback-20260818T2008.json`。",
        "## 状态台账",
        table(["Task ID", "Stage", "Versions", "State", "Attempt", "Owner", "Guard ID", "Blocking reason", "Evidence", "Unlocks"], state_rows),
        "## 当前就绪前沿",
        table(["Frontier", "Task ID", "Eligibility", "Unsatisfied hard dependencies", "Active assumptions", "Resource decision"], ready_rows),
        "## 波前指标",
        table(["Metric", "Value", "Basis"], metrics),
        "## 下一步执行前沿",
        "当前没有新的就绪（READY）节点：MA1、I1、I2、T1 的本地实现/验证已登记，共享路由验收合同（T1-AUTH-ROUTES）的保护基线已锁定，但它们仍需节点级独立接受后才能解锁 IL1、I3、I6 及后续波次。I4/I5 的个人与组织工作区 deletion fixture 合同已获批准并重新锁定，三项聚焦测试已通过；这只解除合同变更阻塞，不替代 I3 的正式接受，因此不得提前推进 I4、I5 或 C1。I9、外部测试、生产发布和第 11 次修订（Revision 11）仍不在本轮启动范围；第 11 次修订继续只在原规范 SSOT 中推进。",
        "## 第二阶段移交边界",
        "C1 已接受（ACCEPTED）后第二阶段可启动个人内容支线；C3 已接受（ACCEPTED）后可启动组织内容与写入器（Writer）支线；DC2 已接受（ACCEPTED）后才可同步第一阶段最终发布投影。第二阶段拥有人工智能写入器（Writer），第一阶段 I7 只提供组织资源解析。",
    ])


def source_notes() -> str:
    return f"""
# 第一阶段来源笔记

## 固定输入

| Source | Path | SHA-256 | Use |
| --- | --- | --- | --- |
| 事实审计 | `{AUDIT}` | `{HASHES['audit']}` | 当前产品、源码、发布与缺口事实 |
| 三阶段编排 | `{ATTACHMENT}` | `{HASHES['attachment']}` | 用户确认的阶段边界与工程并行思路 |
| 结构审查 | `{STRUCTURE_REVIEW}` | `{HASHES['structure_review']}` | Release 1A/1B、开放决定、运行配置与恢复语义修正 |
| 第 4 版结构复核 | `{LATEST_REVIEW}` | `{HASHES['latest_review']}` | 自举死锁、E11 硬边、认证合同、迁移 owner、Writer 关闭、晋升基线和成员安全修正 |
| Revision 11 权威 | `{CANONICAL}` | `{HASHES['canonical']}` | D1-D3A 合同与正式节点状态 |
| Revision 11 进度 | `{CANONICAL_PROGRESS}` | `{HASHES['canonical_progress']}` | 最新实施进度交叉核对 |
| 账号与工作区共享本地候选 | `{SHARED_EVIDENCE['EV-MPE2E-C5-R3-SHARED-LOCAL']['source_bundle']}` | `f1ac786573e76aa40a0d69a10aab6dba5bd6a345596242d93f37773b59f45bcb` | 只读复用外部博主隔离、客户账号唯一正式关系和工作区失败关闭证据；不提升 IL1、I3、C1 状态 |

项目根目录不是 Git 仓库。本包以这些文件校验值作为规划基线；M1 已经建立逐文件基线快照、patch manifest、ownership、应用顺序、冲突检测和确定性重建。后续节点必须消费该协议，不能用目录覆盖代替合并。

## 用户决定

| 决定节点 | 批准日期 | 已接受选择 | 机器权威 |
| --- | --- | --- | --- |
| K1 | 2026-08-15 | 个人使用平台独立认证，不要求飞书；交付文档在云端保存和预览 | `.ssot/nodes/K1.json` |
| K2 | 2026-08-15 | 发布后向全部合格用户开放，使用单一路径硬切换 | `.ssot/nodes/K2.json` |
| K3 | 2026-08-15 | 普通成员首次服务端飞书授权时以 `open_id` 即时建立 | `.ssot/nodes/K3.json` |
| K4 | 2026-08-15 | 近期活动属于租户私有数据 | `.ssot/nodes/K4.json` |
| K5 | 2026-08-15 | 第一阶段排除人工智能文档写入，统一写入路由由第二阶段拥有 | `.ssot/nodes/K5.json` |
| K6 | 2026-08-16 | 用户名或已验证邮箱加密码登录；注册必须验证邮箱；找回链接三十分钟单次有效；八小时不透明会话；重置后撤销全部旧会话；飞书身份只允许主动授权并二次确认后绑定 | `.ssot/nodes/K6.json` |

用户决定来自当前 Codex 任务中的明确答复；独立文件输入仅提供问题背景。每个机器决定记录均保存批准日期、适用范围和存量处理，不把背景附件的推荐误写成用户批准。

## 决定集状态

六项局部产品决定已经全部接受，当前没有待拍板问题。`K6` 明确要求注册和验证不自动登录、找回不暴露账号是否存在、密码重置撤销全部旧会话和未使用找回令牌；旧 Media 密码登录和改密接口继续返回 `404`，并禁止按邮箱或姓名自动合并平台账号与飞书身份。

## 已确认事实

- Revision 11 当前是 `25/29 ACCEPTED`；唯一合法后缀是 `D1 -> D2 -> D3P -> D3A`。
- Revision 11 的节点、执行调度、状态和证据仍由 canonical SSOT 独占。本包没有 R1-R4 节点或 canonical 证据写入路径。
- Revision 11 候选已经包含统一正文结构、C Web/B 飞书编辑权威和服务端工作区模式，但未完成生产终验。
- 当前生产登录不等于个人/组织可信分流；当前会话缺少完整租户类型、正文权威、成员角色和 Binding 信息。
- 当前个人注册成功后直接签发 Media 会话；K6 已将目标合同改为先进入待验证状态，邮箱验证成功后仍需从新个人入口登录。该目标是已接受产品合同，不是当前运行态已实现事实。
- Binding schema 能表达组织凭据和资源落点，但主运行路径仍依赖部署级全局凭据。
- 当前 Pilot 脚本硬编码特定组织与账号，成员同步没有完整分页，并包含不可产品化的秘密处理；完整目录同步不再阻塞 Release 1A/1B。
- 已知租户边界问题包括近期活动全表读取；已知工作区数据问题包括旧 `ordinary` 写入与约束不一致。
- 自助安装、管理员确认、普通成员即时建立、资源初始化、可续接 Provision 和反向生命周期尚未形成真实产品闭环。
- `/Users/vsiyo/.codex/workers/` 只有通用 L1-L4 与 LW wrapper，尚无实现、静态验证、外部测试、生产发布和独立只读五类可验证运行配置。
- 第 23 波共享本地候选绑定前端 200 项与后端 609 项；非数据库、迁移和 PostgreSQL 门禁已通过。该证据不包含第一阶段显式身份关联、完整会话解析、部署或生产读回，因此 `IL1`、`I3`、`C1` 继续阻塞。

## 阶段拆分

- 第一阶段：Release 1A 身份与既有组织 Pilot；Release 1B 自助 Provision、普通成员即时建立与最小撤销；完整目录成熟化只保留 Stage 1C 交接，不进入本机器图。
- 第二阶段：个人内容生产、C/B 人工智能上下文与 Writer 分流；Writer 明确不属于 I7。
- 第三阶段：完整组织权限、审核、商业化、迁移、复杂删除和经营分析。仅记录排除边界，不生成 SSOT。
    """


def _planning_kind(node_id: str, node: dict[str, object]) -> str:
    work_kind = str(node["work_kind"])
    if node_id == "DC":
        # The final projection is the terminal proof node for REL-1B while
        # retaining its zero-write orchestrator execution actor.
        return "release"
    if node.get("worker_transport") == "automatic-projection":
        return "automatic-projection"
    if work_kind == "charter" or work_kind == "decision-acceptance":
        return "decision"
    if work_kind == "data-change":
        return "production-migration"
    if work_kind == "release-decision":
        return "release"
    if work_kind == "convergence":
        return "convergence"
    if work_kind in {"verification-remediation", "frozen-acceptance", "deterministic-check", "test-authoring"}:
        return work_kind
    if work_kind == "fact-discovery":
        return "decision"
    return "implementation"


def _planning_side_effects(node_id: str, node: dict[str, object]) -> list[str]:
    if node_id in {"MA1", "MB1", "P1"}:
        return ["database"]
    if node_id in {"P2", "P3", "P5", "P6", "P8", "P9", "P10"}:
        return ["lark-api"]
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
        "execution_identity": f"stage1:{node_id}:primary",
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
        "lark-api": "saga",
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
    if "database" in side_effects and kind == "production-migration":
        reasons.append("production-migration")
    if "lark-api" in side_effects:
        reasons.append("external-side-effect")
    if kind == "release":
        reasons.append("production-release")
    if reasons:
        escalation: dict[str, object] = {"reasons": reasons}
        if "multi-executor" in reasons:
            record["worker"] = worker
        if "production-migration" in reasons:
            escalation.update(
                {
                    "migration_owner": str(item["acceptance_authority"]),
                    "recovery_contract": "使用命名备份和前向修复；回读失败时停止晋升。",
                    "promotion_baseline": "revision-11-accepted-base",
                }
            )
        if "external-side-effect" in reasons:
            escalation.update(
                {
                    "evidence_contract": f"将 {node_id} 的外部动作、回读与同一安装身份绑定。",
                    "recovery_contract": "幂等重试、只补偿本节点拥有的资源，无法确认时进入 NEEDS_ATTENTION。",
                    "external_identity": f"isolated-lark-{node_id.lower()}",
                }
            )
        if "production-release" in reasons:
            escalation.update(
                {
                    "immutable_release_identity": f"{RELEASE_SLICE_BY_NODE[node_id]}-candidate-v5",
                    "promotion_baseline": "revision-11-d3a-accepted-base",
                    "recovery_contract": "仅允许按已批准回滚点恢复；验收节点本身零写入。",
                }
            )
        record["escalation"] = escalation

    # Test-work contracts are copied from the machine node without changing
    # the frozen oracle or the selected executor.
    for field in (
        "execution_actor",
        "executor_route",
        "primary_executor",
        "primary_wrapper",
        "executor_attempt_policy",
        "priority_class",
        "test_oracle",
        "source_write",
        "interactive_loop",
        "lifecycle",
        "observability",
        "completion",
        "stop_conditions",
        "resource_contract",
        "proof_context",
    ):
        if field in node:
            record[field] = node[field]
    return record


def planning_compiler() -> dict[str, object]:
    release_nodes: dict[str, list[str]] = defaultdict(list)
    wave_nodes: dict[str, list[str]] = defaultdict(list)
    for node_id in NODES:
        release_nodes[RELEASE_SLICE_BY_NODE[node_id]].append(node_id)
        wave_nodes[EXECUTION_WAVE_BY_NODE[node_id]].append(node_id)
    worker_count = sum(
        1
        for node in NODES.values()
        if _planning_worker(str(node["node_id"]), node) is not None
    )
    implementation_counts = {
        release_id: sum(
            1
            for node_id in node_ids
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
            "selection_authority": "existing-ssot",
            "rationale": "现有身份与组织接入 SSOT 具有两个可独立验收的发布增量、外部飞书边界和迁移晋升顺序；本次只补齐未完成节点的执行合同，不重排已接受历史。",
        },
        "external_systems": ["lark", "mail"],
        "acceptance_layers": ["static-test", "local-runtime", "external-system"],
        "scheduling_model": "static-wave",
        "scheduling_hints": [],
        "release_boundary_compiler": {
            "boundary_required": True,
            "decision_authority": "existing-ssot",
            "rationale": "Release 1A 的身份与既有组织 Pilot 和 Release 1B 的新组织 Provision 具有独立用户价值、验收与失败边界。",
        },
        "macro_phases": [
            {
                "id": "PHASE-1",
                "title": "身份与组织接入第一宏观阶段",
                "release_ids": ["REL-1A", "REL-1B"],
            }
        ],
        "release_slices": [
            {
                "id": "REL-1A",
                "macro_phase_id": "PHASE-1",
                "title": "身份分流与既有组织 Pilot",
                "user_value": "个人用户进入个人工作区，既有组织用户进入正确的组织工作区并完成资源只读试点。",
                "independent_acceptance": "同一候选在身份分流、会话、租户隔离和既有 Binding Pilot 上完成验收。",
                "independent_failure": "1A 候选失败时保持未晋升，不阻止 1B 在已接受基线上的独立开发。",
                "future_phase_required_for_success": False,
                "acceptance_node_id": "DC1",
                "release_candidate_artifact_id": "candidate:REL-1A",
                "independent_proof_artifact_id": "proof:REL-1A",
                "acceptance_command": "python3 -m pytest -q --acceptance-release REL-1A --acceptance-node DC1",
                "development_baseline": "stage1-1a-development-base-v5",
                "promotion_baseline": "revision-11-d3a-accepted-base",
                "release_candidate": "stage1-release-1a-candidate-v5",
                "node_ids": release_nodes["REL-1A"],
            },
            {
                "id": "REL-1B",
                "macro_phase_id": "PHASE-1",
                "title": "新组织 Provision、成员即时建立与最小撤销",
                "user_value": "新组织可完成安装、管理员确认、资源初始化、成员首次授权和最小撤销。",
                "independent_acceptance": "同一候选在安装事件、Binding、成员 open_id、可续接状态和撤销回读上完成验收。",
                "independent_failure": "1B 候选失败时保持可恢复待处置，不改写已接受的 1A 候选。",
                "future_phase_required_for_success": False,
                "acceptance_node_id": "DC",
                "release_candidate_artifact_id": "candidate:REL-1B",
                "independent_proof_artifact_id": "proof:REL-1B",
                "acceptance_command": "python3 -m pytest -q --acceptance-release REL-1B --acceptance-node DC",
                "development_baseline": "stage1-1b-development-base-v5",
                "promotion_baseline": "stage1-release-1a-candidate-v5",
                "release_candidate": "stage1-release-1b-candidate-v5",
                "node_ids": release_nodes["REL-1B"],
            },
        ],
        "waves": [
            {
                "id": wave_id,
                "release_id": RELEASE_SLICE_BY_NODE[node_ids[0]],
                "node_ids": node_ids,
            }
            for wave_id, node_ids in wave_nodes.items()
        ],
        "nodes": [_planning_node(node_id, NODES[node_id]) for node_id in NODES],
        "artifacts": {
            "ssot_bundle": True,
            "generated_views": ["main", "dependency-topology", "execution-governance", "contracts-acceptance", "implementation-progress"],
            "worker_ledger": worker_count > 0,
            "evidence_identity_registry": True,
            "resource_matrix": worker_count >= 2,
            "runner_registry": worker_count > 0,
        },
        "complexity_budget": {
            "authority": "existing-ssot",
            "rationale": "两个发布增量需要 L2 编排；预算按当前 50 个机器节点、未完成 Codex 叶子和五个生成视图精确声明。",
            "limits": {
                "total_nodes": len(NODES),
                "implementation_nodes_per_release": max(implementation_counts.values()),
                "codex_worker_nodes": worker_count,
                "generated_views": 5,
            },
            "exception": None,
        },
        "goal_size_detector": {
            "split_required": False,
            "split_strategy": "release",
        },
    }


def write_execution_contracts() -> None:
    EXECUTION_CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    for stale in EXECUTION_CONTRACTS_DIR.glob("*.json"):
        stale.unlink()
    for node_id, node in NODES.items():
        payload = {
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
        }
        for field in (
            "test_oracle", "source_write", "interactive_loop", "lifecycle",
            "observability", "completion", "stop_conditions", "resource_contract",
            "executor_attempt_policy", "proof_context",
        ):
            if field in node:
                payload[field] = node[field]
        path = EXECUTION_CONTRACTS_DIR / f"{node_id}.json"
        write_json(path, payload)
        node["execution_contract_sha256"] = sha256(path)


def build() -> None:
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

    for directory in (NODES_DIR, EDGES_DIR, ASSUMPTIONS_DIR, CONFLICTS_DIR):
        for stale_record in directory.glob("*.json"):
            stale_record.unlink()

    write_execution_contracts()
    write_json(MACHINE / "planning-compiler.json", planning_compiler())

    for node_id, payload in NODES.items():
        write_json(NODES_DIR / f"{node_id}.json", payload)
    for payload in EDGE_RECORDS:
        write_json(EDGES_DIR / f"{payload['edge_id']}.json", payload)

    views = [
        ("main", "00-main.md", "../ssot-development-paths.md", main_view()),
        ("dependency-topology", "10-topology.md", "../generated-views/10-dependency-topology.md", topology_view()),
        ("execution-governance", "20-execution.md", "../generated-views/20-execution-governance.md", execution_view()),
        ("contracts-acceptance", "30-acceptance.md", "../generated-views/30-node-contracts-and-acceptance.md", acceptance_view()),
        ("implementation-progress", "40-progress.md", "../implementation-progress.md", progress_view()),
    ]
    generated_views = []
    for view_id, source_name, output, content in views:
        source_path = VIEW_SOURCES / source_name
        write_text(source_path, content)
        output_path = (MACHINE / output).resolve()
        if output_path != BUNDLE and BUNDLE not in output_path.parents:
            raise ValueError(f"generated view escapes SSOT bundle: {output}")
        write_text(output_path, content)
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
        "machine_validation_profile": "release",
        "parallelism_contract_version": 1,
        "execution_contract_validation": "strict",
        "main_thread_policy": "orchestration-only",
        "main_thread_source_write": False,
        "execution_contracts_dir": "execution-contracts",
        "planning_compiler": "planning-compiler.json",
        "generated_main": "../ssot-development-paths.md",
        "generated_views": generated_views,
        "nodes_dir": "nodes",
        "edges_dir": "edges",
        "assumptions_dir": "assumptions",
        "conflicts_dir": "conflicts",
        "actor_pools": {
            "codex-primary": {"actor": "codex", "capacity": 4},
            "human-authority": {"actor": "human", "capacity": 1},
            "external-acceptance": {"actor": "external-system", "capacity": 1},
            "orchestrator": {"actor": "orchestrator", "capacity": 1},
        },
        "executor_policy": {
            "schema_version": 3,
            "default_primary_executor": PRIMARY_EXECUTOR_DEFAULT,
            "default_writable_parallel_executor": PRIMARY_EXECUTOR_DEFAULT,
            "default_writable_wrapper": PRIMARY_EXECUTOR_OPTIONS[PRIMARY_EXECUTOR_DEFAULT],
            "fallback_executor": "l3",
            "fallback_wrapper": "run-l3.sh",
            "primary_retry_limit": 1,
            "l3_escalation_limit": 1,
            "allowed_primary_executors": dict(PRIMARY_EXECUTOR_OPTIONS),
        },
        "external_gates": [
            {
                "node_id": "E11",
                "semantic_key": "media.external.revision11-d3a",
                "required_state": "ACCEPTED",
                "authority_path": CANONICAL,
                "authority_revision": "revision11-d3a",
                "consumers": ["CA", "CB"],
                "projection_mode": "automatic-projection",
                "canonical_evidence_write_allowed": False,
            }
        ],
        "stage_handoffs": [
            {
                "handoff_id": "stage-1c-directory-maturity",
                "title": "完整组织目录成熟化",
                "status": "OUTSIDE_CURRENT_DAG",
                "source_decision_node": "K3",
                "excluded_from_completion_nodes": ["CA", "CB", "DC1", "DC2"],
                "required_future_scope": [
                    "分页目录读取",
                    "部门树",
                    "增量同步",
                    "大组织恢复",
                ],
            }
        ],
        "shared_evidence": list(SHARED_EVIDENCE.values()),
    }
    write_json(MACHINE / "manifest.json", manifest)
    write_text(BUNDLE / "source-notes.md", source_notes())
    (BUNDLE / "openproblem.md").unlink(missing_ok=True)
    write_json(
        BUNDLE / "ssot-archive.json",
        {
            "schema_version": 1,
            "artifact_class": "ssot-development",
            "artifact_date": "2026-08-15",
            "project_name": "openclaw-media",
            "ssot_name": "media-c-b-stage-1-identity-organization-onboarding",
            "main_document": "ssot-development-paths.md",
            "problem_documents": [],
        },
    )


if __name__ == "__main__":
    build()
