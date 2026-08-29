from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, fields, is_dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from common.canonical_digest import prefixed_digest

from ..router.tag_capabilities import TAG_CAPABILITIES, TagCapability
from .capability_input_contracts import CAPABILITY_INPUT_CONTRACTS


CATALOG_SCHEMA_VERSION = "capability_catalog_v3"
_WRITE_MODES = frozenset({"reply_and_persist", "persist_and_update_status", "confirm_then_persist"})
_NO_WRITE_TARGETS = frozenset({"", "none"})


class CapabilityRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class FieldOption:
    value: str
    label: str
    aliases: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class FormatDefinition:
    name: str
    min: float | None
    max: float | None
    pattern: str
    url_schemes: tuple[str, ...]


@dataclass(frozen=True)
class ConditionDefinition:
    source: str
    operator: str
    value: Any


@dataclass(frozen=True)
class FieldDefinition:
    key: str
    source_label: str
    label: str
    input_type: str
    value_type: str
    format: FormatDefinition
    required: bool
    default_value: Any
    options: tuple[FieldOption, ...]
    placeholder: str
    help_text: str
    order: int
    visible_when: tuple[ConditionDefinition, ...]
    enabled_when: tuple[ConditionDefinition, ...]
    semantic_owner: str
    persistence_owner: str
    provenance: str


@dataclass(frozen=True)
class ValidationRule:
    type: str
    fields: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class VariantDefinition:
    variant_id: str
    label: str
    required_fields: tuple[str, ...]
    required_any_of: tuple[tuple[str, ...], ...]
    pre_actions: tuple[str, ...]
    controlled_input_fields: tuple[str, ...]
    forbidden_fields: tuple[str, ...]
    field_values: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class HierarchyDefinition:
    category_id: str
    category_name: str
    category_order: int
    object_id: str
    object_name: str
    object_order: int
    action_id: str
    action_name: str
    action_order: int

    @property
    def path_ids(self) -> tuple[str, ...]:
        return tuple(item for item in (self.category_id, self.object_id, self.action_id) if item)

    @property
    def path_names(self) -> tuple[str, ...]:
        return tuple(item for item in (self.category_name, self.object_name, self.action_name) if item)


@dataclass(frozen=True)
class ConfirmationPolicy:
    stage: str
    message: str


@dataclass(frozen=True)
class AttachmentPolicy:
    types: tuple[str, ...]
    max_count: int
    max_bytes: int


@dataclass(frozen=True)
class CapabilityDefinition:
    capability_id: str
    internal_code: str
    internal_label: str
    label: str
    display_name: str
    description: str
    example: str
    aliases: tuple[str, ...]
    bots: tuple[str, ...]
    hierarchy: HierarchyDefinition
    fields: tuple[FieldDefinition, ...]
    variants: tuple[VariantDefinition, ...]
    validation_rules: tuple[ValidationRule, ...]
    supported_attachments: tuple[str, ...]
    attachment_policy: AttachmentPolicy
    status: str
    enabled: bool
    visibility: str
    risk_level: str
    effect: str
    confirmation_policy: ConfirmationPolicy
    handler: str
    consumes: tuple[str, ...]
    produces: tuple[str, ...]
    writes_to: tuple[str, ...]
    source_system: str
    ssot_refs: tuple[str, ...]
    input_contract_source: str
    search_keywords: tuple[str, ...]
    provenance: str
    display_order: int


_PRIMARY_LABELS = {
    "shooting_execution_plan": "拍摄",
    "creation_checklist_lookup": "作品验收",
    "selfmedia_creation": "创作",
    "style_polish_run": "润色",
}

_CATEGORY_IDS = {
    "创作运行": "creation_operations",
    "发布准备": "publishing_preparation",
    "发布前 Gate": "pre_publish_gate",
    "商务 / Brief": "business_brief",
    "商务 / 商单交付": "commercial_delivery",
    "数据复盘": "data_review",
    "素材 / 灵感池": "source_inspiration",
    "能力目录": "general_capabilities",
    "表达优化": "expression_optimization",
    "账号内容地图": "account_content_map",
    "选题与决策": "topic_decision",
    "文档维护": "document_maintenance",
}
_CATEGORY_ORDER = {name: order for order, name in enumerate(_CATEGORY_IDS)}

# Media's public task picker is driven by this table. The source labels remain
# router protocol values; this table owns the user-facing name, explanation,
# and the parsed meaning of legacy `>` / `-` entry syntax.
_MEDIA_CAPABILITY_PRESENTATIONS: dict[str, dict[str, object]] = {
    "inspiration_archive": {"display_name": "灵感归档", "description": "把零散想法整理成可继续发展的灵感记录。", "path": ("素材", "灵感", "归档")},
    "vlog_inspiration_capture": {"display_name": "Vlog 灵感整理", "description": "把现场想到的 Vlog 片段和附件整理成可用灵感。", "path": ("素材", "灵感", "Vlog")},
    "source_asset_intake": {"display_name": "素材入池", "description": "收集链接、文字和原始表达，进入素材池。", "path": ("素材", "素材收集")},
    "activity_archive": {"display_name": "活动素材整理", "description": "整理平台活动 Brief，沉淀为选题素材。", "path": ("素材", "活动 Brief")},
    "viral_deconstruction": {"display_name": "内容结构拆解", "description": "拆解短视频或图文的结构、镜头和表达。", "path": ("素材", "内容拆解")},
    "shooting_execution_plan": {"display_name": "拍摄执行计划", "description": "把已确认的选题转成拍摄执行计划。", "path": ("创作", "拍摄执行")},
    "selfmedia_creation": {"display_name": "创作初稿生成", "description": "按平台生成内容创作初稿。", "path": ("创作", "内容创作")},
    "style_polish_run": {"display_name": "文案表达优化", "description": "把标题、正文或口播优化成自然表达。", "path": ("创作", "表达优化")},
    "account_track_strategy": {"display_name": "账号内容策略", "description": "围绕账号、平台与赛道梳理内容方向。", "path": ("选题", "内容策略")},
    "creation_decision_brief": {"display_name": "选题 Brief 整理", "description": "把素材和证据整理成可判断的选题 Brief。", "path": ("选题", "选题判断")},
    "selfmedia_creation_consultation": {"display_name": "创作决策咨询", "description": "基于账号数据回答创作决策问题。", "path": ("选题", "创作咨询")},
    "platform_hotlist": {"display_name": "热榜查询", "description": "查询平台热榜，发现可验证的内容方向。", "path": ("选题", "平台热榜")},
    "external_research_brief": {"display_name": "内容调研 Brief", "description": "基于证据整理内容调研 Brief。", "path": ("选题", "内容调研")},
    "commercial_brief": {"display_name": "品牌合作 Brief", "description": "把品牌合作要求整理成可执行的 Brief。", "path": ("商务", "品牌合作")},
    "commercial_delivery_draft": {"display_name": "商单交付初稿", "description": "根据品牌要求生成商单交付初稿。", "path": ("商务", "商单交付")},
    "id_business": {"display_name": "达人商务信息", "description": "查询达人档案，整理 PR 商务信息。", "path": ("商务", "达人商务")},
    "publishing_pack_build": {"display_name": "发布内容包", "description": "整理标题、封面、正文、标签和互动信息。", "path": ("发布", "发布准备")},
    "creation_checklist_lookup": {"display_name": "创作检查清单", "description": "查询创作检查清单，核对发布前准备项。", "path": ("发布", "发布前检查")},
    "work_acceptance_report": {"display_name": "成稿成片验收", "description": "按创作要求验收成片或成稿。", "path": ("发布", "作品验收")},
    "media_growth_review": {"display_name": "成果人工复核", "description": "复核已生成的内容产物及其证据。", "path": ("发布", "人工复核")},
    "selfmedia_data_review": {"display_name": "作品数据复盘", "description": "根据作品数据复盘表现和下一步动作。", "path": ("数据", "作品复盘")},
    "post_review_signal": {"display_name": "项目复盘记录", "description": "记录项目复盘结论和下一步动作。", "path": ("数据", "项目复盘")},
    "selfmedia_cognition_accumulation": {"display_name": "自媒体认知沉淀", "description": "沉淀或修正自媒体领域的认知。", "path": ("知识", "自媒体认知")},
    "owned_media_account_lookup": {"display_name": "自有账号管理", "description": "查看和维护自有账号的内容定位。", "path": ("账号", "自有账号")},
    "track_registry_lookup": {"display_name": "赛道库维护", "description": "查询、注册和维护统一的内容赛道。", "path": ("账号", "赛道管理")},
    "track_creator_membership_query": {"display_name": "赛道博主关系", "description": "确认赛道与博主之间的关系。", "path": ("账号", "赛道管理", "博主关系")},
    "creator_profile_lookup": {"display_name": "博主档案查询", "description": "查询外部博主档案。", "path": ("账号", "博主档案", "查询")},
    "creator_profile_upsert": {"display_name": "博主档案入库", "description": "把确认后的博主资料写入档案。", "path": ("账号", "博主档案", "入库")},
    "document_edit": {"display_name": "内容文档修改", "description": "修改已有的内容文档。", "path": ("文档", "文档维护")},
    "universal_deletion": {"display_name": "内容产物删除", "description": "预览并确认删除内容产物。", "path": ("系统", "数据管理")},
    "recent_records_summary": {"display_name": "最近记录整理", "description": "整理最近的素材与任务记录。", "path": ("系统", "记录管理", "整理")},
    "recent_records_lookup": {"display_name": "最近记录查询", "description": "查询最近产生的记录。", "path": ("系统", "记录管理", "查询")},
    "record_sync": {"display_name": "记录同步", "description": "同步尚未完成同步的记录。", "path": ("系统", "记录管理", "同步")},
    "task_status_lookup": {"display_name": "任务状态查询", "description": "查询任务执行状态。", "path": ("系统", "任务状态")},
}

_MEDIA_CATEGORY_ORDER = {name: order for order, name in enumerate(("素材", "创作", "选题", "商务", "发布", "数据", "知识", "账号", "文档", "系统"))}
_MEDIA_BRANCH_ORDER = {
    "素材": ("灵感", "素材收集", "活动 Brief", "内容拆解"),
    "创作": ("拍摄执行", "内容创作", "表达优化"),
    "选题": ("内容策略", "选题判断", "创作咨询", "平台热榜", "内容调研"),
    "商务": ("品牌合作", "商单交付", "达人商务"),
    "发布": ("发布准备", "发布前检查", "作品验收", "人工复核"),
    "数据": ("作品复盘", "项目复盘"),
    "知识": ("自媒体认知",),
    "账号": ("自有账号", "赛道管理", "博主档案"),
    "文档": ("文档维护",),
    "系统": ("数据管理", "记录管理", "任务状态"),
}
_MEDIA_CAPABILITY_IDS = frozenset(_MEDIA_CAPABILITY_PRESENTATIONS)


def _stable_token(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _effect(capability: TagCapability) -> str:
    if capability.risk_level == "destructive":
        return "destructive"
    targets = {str(item).strip().lower() for item in capability.writes_to}
    if targets - _NO_WRITE_TARGETS or capability.default_mode in _WRITE_MODES and capability.requires_confirmation:
        return "write"
    return "read"


def _confirmation_policy(capability: TagCapability, effect: str) -> ConfirmationPolicy:
    if effect == "destructive":
        return ConfirmationPolicy("destructive_preview_apply", "先预览影响范围，再由用户确认执行。")
    if capability.canonical_capability_id == "creator_profile_upsert":
        return ConfirmationPolicy("after_candidate", "先生成待确认候选，再由用户确认写入。")
    if effect == "write":
        return ConfirmationPolicy("before_execute", "执行写入前需要用户确认。")
    return ConfirmationPolicy("none", "")


def _hierarchy(capability: TagCapability, label: str) -> HierarchyDefinition:
    presentation = _MEDIA_CAPABILITY_PRESENTATIONS.get(capability.canonical_capability_id)
    if presentation is not None:
        path = tuple(str(item) for item in presentation["path"])
        category_name, object_name = path[:2]
        action_name = path[2] if len(path) == 3 else ""
        category_id = _stable_token("category", category_name)
        object_id = _stable_token("object", f"{category_name}:{object_name}")
        action_id = _stable_token("action", f"{capability.canonical_capability_id}:{action_name}") if action_name else ""
        branch_order = _MEDIA_BRANCH_ORDER[category_name].index(object_name)
        sibling_ids = [
            capability_id
            for capability_id, item in _MEDIA_CAPABILITY_PRESENTATIONS.items()
            if tuple(item["path"][:2]) == (category_name, object_name)
        ]
        action_order = sibling_ids.index(capability.canonical_capability_id) if action_name else 0
        return HierarchyDefinition(
            category_id,
            category_name,
            _MEDIA_CATEGORY_ORDER[category_name],
            object_id,
            object_name,
            branch_order,
            action_id,
            action_name,
            action_order,
        )
    category_name = capability.frontend_group or "能力目录"
    category_id = _CATEGORY_IDS.get(category_name, _stable_token("category", category_name))
    category_order = _CATEGORY_ORDER.get(category_name, len(_CATEGORY_ORDER))
    if capability.canonical_capability_id in {"creator_profile_lookup", "creator_profile_upsert"}:
        action = "查询" if capability.canonical_capability_id == "creator_profile_lookup" else "入库"
        action_id = "query" if action == "查询" else "create"
        return HierarchyDefinition(category_id, category_name, category_order, "creator", "博主", 0, action_id, action, 0 if action_id == "query" else 1)
    if capability.canonical_capability_id == "track_creator_membership_query":
        return HierarchyDefinition(category_id, category_name, category_order, "track", "赛道", 0, "relationship", "关系", 1)
    return HierarchyDefinition(
        category_id,
        category_name,
        category_order,
        capability.canonical_capability_id,
        label,
        0,
        "",
        "",
        0,
    )


def _choose_primary(entries: list[TagCapability]) -> TagCapability:
    preferred = _PRIMARY_LABELS.get(entries[0].canonical_capability_id)
    if preferred:
        for entry in entries:
            if entry.label == preferred:
                return entry
    return entries[0]


def _compile_definition(entries: list[TagCapability], order: int) -> CapabilityDefinition:
    primary = _choose_primary(entries)
    presentation = _MEDIA_CAPABILITY_PRESENTATIONS.get(primary.canonical_capability_id)
    if primary.canonical_capability_id in _MEDIA_CAPABILITY_IDS:
        if presentation is None:
            raise CapabilityRegistryError(f"{primary.canonical_capability_id} has no public media presentation")
    contract = CAPABILITY_INPUT_CONTRACTS.get(primary.canonical_capability_id)
    if contract is None:
        raise CapabilityRegistryError(f"enabled capability {primary.canonical_capability_id} has no capability-ID input contract")
    label_to_key: dict[str, str] = {}
    fields: list[FieldDefinition] = []
    base_required = {str(item) for item in contract.get("requiredFields") or ()}
    for item in contract.get("fieldDefinitions") or ():
        source_label = str(item.get("sourceLabel") or "")
        key = str(item.get("key") or "")
        if not source_label or not key:
            raise CapabilityRegistryError(f"{primary.canonical_capability_id} has an invalid field definition")
        label_to_key[source_label] = key
        options = tuple(
            FieldOption(
                str(option["value"]),
                str(option["label"]),
                tuple(str(alias) for alias in option.get("aliases") or ()),
                str(option.get("source") or ""),
            )
            for option in item.get("options") or ()
        )
        raw_format = item.get("format") or {}
        if not isinstance(raw_format, Mapping):
            raise CapabilityRegistryError(f"{primary.canonical_capability_id}/{key} has an invalid format contract")

        def conditions(name: str) -> tuple[ConditionDefinition, ...]:
            return tuple(
                ConditionDefinition(str(condition.get("source") or ""), str(condition.get("operator") or ""), condition.get("value"))
                for condition in item.get(name) or ()
            )

        fields.append(
            FieldDefinition(
                key=key,
                source_label=source_label,
                label=str(item.get("label") or source_label),
                input_type=str(item.get("inputType") or "text"),
                value_type=str(item.get("valueType") or "string"),
                format=FormatDefinition(
                    name=str(raw_format.get("name") or ""),
                    min=float(raw_format["min"]) if raw_format.get("min") is not None else None,
                    max=float(raw_format["max"]) if raw_format.get("max") is not None else None,
                    pattern=str(raw_format.get("pattern") or ""),
                    url_schemes=tuple(str(value) for value in raw_format.get("urlSchemes") or ()),
                ),
                required=source_label in base_required,
                default_value=item.get("defaultValue"),
                options=options,
                placeholder=str(item.get("placeholder") or ""),
                help_text=str(item.get("helpText") or ""),
                order=int(item.get("order") or 0),
                visible_when=conditions("visibleWhen"),
                enabled_when=conditions("enabledWhen"),
                semantic_owner=str(item.get("semanticOwner") or ""),
                persistence_owner=str(item.get("persistenceOwner") or ""),
                provenance=str(item.get("provenance") or ""),
            )
        )

    def resolve(values: Iterable[Any]) -> tuple[str, ...]:
        resolved = []
        for raw in values:
            source_label = str(raw)
            if source_label not in label_to_key:
                raise CapabilityRegistryError(f"{primary.label} references unknown field {source_label}")
            resolved.append(label_to_key[source_label])
        return tuple(resolved)

    variants: list[VariantDefinition] = []
    for raw in contract.get("variants") or ():
        raw_id = str(raw.get("id") or "").strip()
        if not raw_id:
            raise CapabilityRegistryError(f"{primary.label} has an empty variant id")
        field_values = {
            label_to_key[str(key)]: tuple(str(value) for value in values)
            for key, values in (raw.get("fieldValues") or {}).items()
        }
        variants.append(
            VariantDefinition(
                variant_id=raw_id,
                label=str(raw.get("description") or raw_id),
                required_fields=resolve(raw.get("requiredFields") or ()),
                required_any_of=tuple(resolve(group) for group in raw.get("requiredAnyOf") or ()),
                pre_actions=tuple(str(item) for item in raw.get("preActions") or ()),
                controlled_input_fields=resolve(raw.get("controlledInputFields") or ()),
                forbidden_fields=resolve(raw.get("forbiddenFields") or ()),
                field_values=MappingProxyType(field_values),
            )
        )
    if not variants:
        variants.append(VariantDefinition("default", "标准输入", resolve(base_required), (), (), (), ()))
    variant_ids = [item.variant_id for item in variants]
    if len(variant_ids) != len(set(variant_ids)):
        raise CapabilityRegistryError(f"{primary.label} has duplicate variant ids")
    rules = tuple(
        ValidationRule("at_least_one", resolve(group), "、".join(str(item) for item in group) + "至少填写一项")
        for group in contract.get("requiredAnyOf") or ()
    )
    effect = _effect(primary)
    confirmation = _confirmation_policy(primary, effect)
    if effect in {"write", "destructive"} and confirmation.stage == "none":
        raise CapabilityRegistryError(f"write capability {primary.label} has no confirmation policy")
    aliases = tuple(
        dict.fromkeys(
            item
            for entry in entries
            for item in (entry.label, *entry.aliases)
            if item and item != primary.label
        )
    )
    enabled = primary.implementation_status != "not_implemented"
    display_name = str(presentation["display_name"]) if presentation is not None else primary.label
    description = str(presentation["description"]) if presentation is not None else primary.purpose
    presentation_terms = tuple(str(item) for item in (presentation["path"] if presentation is not None else ()))
    return CapabilityDefinition(
        capability_id=primary.canonical_capability_id,
        internal_code=primary.capability,
        internal_label=primary.label,
        label=primary.label,
        display_name=display_name,
        description=description,
        example=primary.example,
        aliases=aliases,
        bots=tuple(dict.fromkeys(entry.bot for entry in entries)),
        hierarchy=_hierarchy(primary, primary.label),
        fields=tuple(fields),
        variants=tuple(variants),
        validation_rules=rules,
        supported_attachments=tuple(str(item) for item in contract.get("supportedAttachments") or ()),
        attachment_policy=AttachmentPolicy(
            types=tuple(str(item) for item in (contract.get("attachmentPolicy") or {}).get("types") or ()),
            max_count=int((contract.get("attachmentPolicy") or {}).get("maxCount") or 0),
            max_bytes=int((contract.get("attachmentPolicy") or {}).get("maxBytes") or 0),
        ),
        status=primary.implementation_status,
        enabled=enabled,
        visibility=primary.visibility,
        risk_level=primary.risk_level,
        effect=effect,
        confirmation_policy=confirmation,
        handler=primary.handler,
        consumes=primary.consumes,
        produces=primary.produces,
        writes_to=primary.writes_to,
        source_system=primary.source_system,
        ssot_refs=primary.ssot_refs,
        input_contract_source=str(contract.get("source") or ""),
        search_keywords=tuple(dict.fromkeys((*[str(item) for item in contract.get("searchKeywords") or () if item], display_name, *presentation_terms))),
        provenance=f"tag_capabilities.py:{primary.canonical_capability_id}+capability_input_contracts.py:{primary.canonical_capability_id}",
        display_order=order,
    )


def _camel_payload(value: Any) -> Any:
    if isinstance(value, HierarchyDefinition):
        payload = {item.name: getattr(value, item.name) for item in fields(value)}
        payload["path_ids"] = value.path_ids
        payload["path_names"] = value.path_names
        return _camel_payload(payload)
    if is_dataclass(value):
        return _camel_payload({item.name: getattr(value, item.name) for item in fields(value)})
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            parts = str(key).split("_")
            camel = parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])
            result[camel] = _camel_payload(item)
        return result
    if isinstance(value, (tuple, list)):
        return [_camel_payload(item) for item in value]
    return value


class CapabilityRegistry:
    def __init__(self, definitions: Iterable[CapabilityDefinition]) -> None:
        items = tuple(definitions)
        by_id: dict[str, CapabilityDefinition] = {}
        by_path: dict[tuple[str, ...], CapabilityDefinition] = {}
        by_alias: dict[str, CapabilityDefinition] = {}
        for definition in items:
            if definition.capability_id in by_id:
                raise CapabilityRegistryError(f"duplicate capability id {definition.capability_id}")
            path = definition.hierarchy.path_ids
            if path in by_path:
                raise CapabilityRegistryError(f"duplicate capability path {'/'.join(path)}")
            by_id[definition.capability_id] = definition
            by_path[path] = definition
            for alias in (definition.label, *definition.aliases):
                current = by_alias.get(alias)
                if current is not None and current.capability_id != definition.capability_id:
                    raise CapabilityRegistryError(f"duplicate capability alias {alias}")
                by_alias[alias] = definition
        self._definitions = tuple(sorted(items, key=lambda item: item.display_order))
        self._by_id = MappingProxyType(by_id)
        self._by_path = MappingProxyType(by_path)
        self._by_alias = MappingProxyType(by_alias)
        self.catalog_version = prefixed_digest([_camel_payload(item) for item in self._definitions], allow_nan=True)

    @classmethod
    def compile_all(cls) -> "CapabilityRegistry":
        grouped: dict[str, list[TagCapability]] = {}
        for capability in TAG_CAPABILITIES:
            if capability.canonical_capability_id == "system_help":
                continue
            grouped.setdefault(capability.canonical_capability_id, []).append(capability)
        return cls(_compile_definition(entries, order) for order, entries in enumerate(grouped.values()))

    @property
    def definitions(self) -> tuple[CapabilityDefinition, ...]:
        return self._definitions

    def get(self, capability_id: str) -> CapabilityDefinition | None:
        return self._by_id.get(capability_id)

    def resolve_alias(self, alias: str) -> CapabilityDefinition | None:
        return self._by_alias.get(alias)

    def resolve_path(self, path: Iterable[str]) -> CapabilityDefinition | None:
        return self._by_path.get(tuple(path))

    def validation_issues(
        self,
        capability_id: str,
        variant_id: str,
        params: Mapping[str, Any],
    ) -> tuple[dict[str, str], ...]:
        definition = self.get(capability_id)
        if definition is None or not definition.enabled:
            return ({"code": "capability_not_found", "ruleType": "capability", "message": "能力不存在或当前不可执行。"},)
        variant = next((item for item in definition.variants if item.variant_id == variant_id), None)
        if variant is None:
            return ({"code": "variant_not_found", "ruleType": "variant", "message": "具体操作不存在。"},)
        if not isinstance(params, Mapping):
            return ({"code": "invalid_params", "ruleType": "type", "message": "任务参数必须是对象。"},)
        field_map = {item.key: item for item in definition.fields}
        issues: list[dict[str, str]] = []

        def condition_matches(condition: ConditionDefinition) -> bool:
            actual = variant_id if condition.source == "variant" else params.get(condition.source)
            if condition.operator == "equals":
                return actual == condition.value
            if condition.operator == "not_equals":
                return actual != condition.value
            if condition.operator == "in":
                return isinstance(condition.value, (list, tuple)) and actual in condition.value
            if condition.operator == "exists":
                return (actual not in (None, "", [])) is bool(condition.value)
            return False

        for key in params:
            if key not in field_map:
                issues.append({"code": "unknown_field", "fieldKey": str(key), "ruleType": "field", "message": "字段不属于当前能力。"})
        for key, value in params.items():
            field_definition = field_map.get(str(key))
            if field_definition is None or value is None or value == "" or value == []:
                continue
            valid_type = {
                "string": isinstance(value, str),
                "number": isinstance(value, (int, float)) and not isinstance(value, bool),
                "boolean": isinstance(value, bool),
                "array": isinstance(value, list) and all(isinstance(item, (str, int, float)) and not isinstance(item, bool) for item in value),
                "object": isinstance(value, Mapping),
            }[field_definition.value_type]
            if not valid_type:
                issues.append({"code": "invalid_type", "fieldKey": str(key), "ruleType": "type", "message": f"{field_definition.label}的类型不正确。"})
                continue
            if field_definition.visible_when and not all(condition_matches(item) for item in field_definition.visible_when):
                issues.append({"code": "field_not_visible", "fieldKey": str(key), "ruleType": "condition", "message": f"{field_definition.label}不适用于当前操作。"})
                continue
            if field_definition.enabled_when and not all(condition_matches(item) for item in field_definition.enabled_when):
                issues.append({"code": "field_disabled", "fieldKey": str(key), "ruleType": "condition", "message": f"{field_definition.label}当前不可填写。"})
                continue
            if field_definition.format.name == "uri" and isinstance(value, str):
                parsed = urlparse(value)
                allowed_schemes = set(field_definition.format.url_schemes or ("http", "https"))
                if parsed.scheme not in allowed_schemes or not parsed.netloc:
                    issues.append({"code": "invalid_format", "fieldKey": str(key), "ruleType": "url", "message": f"{field_definition.label}必须是有效链接。"})
            comparable = len(value) if isinstance(value, (str, list)) else value if isinstance(value, (int, float)) else None
            if comparable is not None and field_definition.format.min is not None and comparable < field_definition.format.min:
                issues.append({"code": "below_minimum", "fieldKey": str(key), "ruleType": "format", "message": f"{field_definition.label}低于最小值。"})
            if comparable is not None and field_definition.format.max is not None and comparable > field_definition.format.max:
                issues.append({"code": "above_maximum", "fieldKey": str(key), "ruleType": "format", "message": f"{field_definition.label}超过最大值。"})
            if field_definition.format.pattern and isinstance(value, str) and re.fullmatch(field_definition.format.pattern, value) is None:
                issues.append({"code": "pattern_mismatch", "fieldKey": str(key), "ruleType": "format", "message": f"{field_definition.label}格式不正确。"})
            allowed = variant.field_values.get(str(key)) or tuple(option.value for option in field_definition.options)
            values = value if isinstance(value, list) else [value]
            if allowed and any(str(item) not in allowed for item in values):
                issues.append({"code": "invalid_option", "fieldKey": str(key), "ruleType": "option", "message": f"{field_definition.label}包含未定义选项。"})
        required = set(variant.required_fields) | {item.key for item in definition.fields if item.required}
        for key in sorted(required):
            if params.get(key) in (None, "", []):
                field_definition = field_map[key]
                issues.append({"code": "required", "fieldKey": key, "ruleType": "required", "message": f"{field_definition.label}为必填项。"})
        for group in variant.required_any_of:
            if not any(params.get(key) not in (None, "", []) for key in group):
                labels = "或".join(field_map[key].label for key in group)
                issues.append({"code": "at_least_one", "fieldKey": group[0], "ruleType": "at_least_one", "message": f"{labels}至少填写一项。"})
        for key in variant.forbidden_fields:
            if params.get(key) not in (None, "", []):
                issues.append({"code": "forbidden", "fieldKey": key, "ruleType": "forbidden", "message": f"{field_map[key].label}不适用于当前操作。"})
        return tuple(issues)

    def require_valid_invocation(self, capability_id: str, variant_id: str, params: Mapping[str, Any]) -> CapabilityDefinition:
        issues = self.validation_issues(capability_id, variant_id, params)
        if issues:
            first = issues[0]
            raise CapabilityRegistryError(f"{first['code']}: {first['message']}")
        definition = self.get(capability_id)
        assert definition is not None
        return definition

    def render_chat_body(self, capability_id: str, params: Mapping[str, Any]) -> str:
        definition = self.get(capability_id)
        if definition is None:
            raise CapabilityRegistryError("capability_not_found: 能力不存在。")
        fields_by_key = {item.key: item for item in definition.fields}
        lines: list[str] = []
        for field_definition in sorted(definition.fields, key=lambda item: item.order):
            value = params.get(field_definition.key)
            if value in (None, "", []):
                continue
            rendered = "、".join(str(item) for item in value) if isinstance(value, list) else str(value)
            lines.append(f"{field_definition.source_label}：{rendered}")
        unknown = set(params) - set(fields_by_key)
        if unknown:
            raise CapabilityRegistryError("unknown_field: 字段不属于当前能力。")
        return "\n".join(lines)

    def summary(self, capability_id: str, params: Mapping[str, Any], *, limit: int = 180) -> str:
        body = self.render_chat_body(capability_id, params).replace("\n", " ")
        return body[:limit] + ("…" if len(body) > limit else "")

    def serialize(
        self,
        *,
        visibilities: frozenset[str] = frozenset({"public", "ops", "maintainer"}),
        bots: frozenset[str] | None = None,
    ) -> dict[str, Any]:
        capabilities = []
        for item in self._definitions:
            if item.visibility not in visibilities:
                continue
            if bots is not None and not set(item.bots) & bots:
                continue
            payload = _camel_payload(item)
            payload["requiresConfirmation"] = item.confirmation_policy.stage != "none"
            capabilities.append(payload)
        return {
            "schemaVersion": CATALOG_SCHEMA_VERSION,
            "catalogVersion": self.catalog_version,
            "capabilities": capabilities,
        }


CAPABILITY_REGISTRY = CapabilityRegistry.compile_all()
