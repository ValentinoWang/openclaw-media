from __future__ import annotations

from dataclasses import dataclass

from .tag_capabilities import TagCapability
from ..services.capability_input_contracts import get_input_contract


@dataclass(frozen=True)
class IntakeGuide:
    title: str
    fields: tuple[str, ...]
    notes: tuple[str, ...] = ()
    minimum: tuple[str, ...] = ()
    pre_actions: tuple[str, ...] = ()
    copy_fields: tuple[str, ...] = ()
    controlled_input_fields: tuple[str, ...] = ()


MEDIA_INTAKE_GUIDE_LABELS = (
    "策略",
    "素材",
    "调研",
    "热榜",
    "选题",
    "拍摄",
    "检查",
    "发布包",
    "账号",
    "赛道",
    "商务>ID",
    "商单交付",
    "博主-入库",
    "创作",
    "创作>小红书",
    "创作>抖音",
    "创作咨询",
    "创作-拍摄执行",
    "拆解",
    "活动",
    "自媒体知识",
    "转写",
    "转写-文字",
    "灵感",
    "灵感>vlog",
    "复盘",
    "数据复盘",
    "修改",
    "自媒体-认知",
    "创作检查",
    "作品验收",
    "润色",
    "网感",
    "文案优化",
    "改标题",
    "去AI味",
    "小红书文案",
    "抖音文案",
)


def _guide_from_contract(label: str) -> IntakeGuide:
    contract = get_input_contract(label)
    if contract is None or contract.get("inputMode") == "freeform":
        raise RuntimeError(f"【{label}】缺少可生成 Media 输入说明的结构化契约")
    required = list(contract.get("requiredFields") or [])
    required.extend(" / ".join(group) for group in contract.get("requiredAnyOf") or [] if group)
    return IntakeGuide(
        title=label,
        fields=tuple(f"{field}：" for field in contract.get("copyFields") or []),
        minimum=tuple(required),
        pre_actions=tuple(contract.get("preActions") or []),
        copy_fields=tuple(contract.get("copyFields") or []),
        controlled_input_fields=tuple(contract.get("controlledInputFields") or []),
    )


GUIDES: dict[str, IntakeGuide] = {
    label: _guide_from_contract(label)
    for label in MEDIA_INTAKE_GUIDE_LABELS
}
STYLE_POLISH_GUIDE = GUIDES["润色"]


def is_media_intake_tag(label: str, capability: TagCapability | None = None) -> bool:
    if label in GUIDES:
        return True
    return bool(capability and capability.bot == "Media bot")


def render_media_intake_prompt(label: str, capability: TagCapability | None = None) -> str:
    contract = get_input_contract(label)
    if contract and contract.get("inputMode") != "freeform":
        fields = "\n".join(f"{field}：" for field in contract.get("copyFields") or [])
        notes: list[str] = []
        required = list(contract.get("requiredFields") or [])
        required_any = [" / ".join(group) for group in contract.get("requiredAnyOf") or []]
        if required or required_any:
            notes.append("标准输入至少需要：" + "、".join([*required, *required_any]) + "。")
        for variant in contract.get("variants") or []:
            facts = [str(variant.get("description") or variant.get("id") or "输入")]
            if variant.get("requiredFields"):
                facts.append("必填 " + "、".join(variant["requiredFields"]))
            if variant.get("requiredAnyOf"):
                facts.extend("至少一项 " + " / ".join(group) for group in variant["requiredAnyOf"])
            facts.extend(str(action) for action in variant.get("preActions") or [])
            notes.append("输入分支：" + "；".join(facts) + "。")
    else:
        fields = f"【{label}】"
        notes = []

    lines = [
        f"这是 Media bot 的【{label}】使用说明。",
        "输入字段与操作顺序来自同一执行契约：",
        "",
        fields,
    ]
    if notes:
        lines.extend(["", *notes])
    return "\n".join(lines).rstrip()
