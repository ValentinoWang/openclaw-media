from __future__ import annotations

from dataclasses import dataclass

from .tag_capabilities import TagCapability
from .openclaw_bot_llm import display_openclaw_model, profile_runtime


_GUIDE_RUNTIME = profile_runtime("system_guide")
GUIDE_MODEL = display_openclaw_model(_GUIDE_RUNTIME.model)
GUIDE_THINKING = _GUIDE_RUNTIME.thinking


@dataclass(frozen=True)
class IntakeGuide:
    title: str
    fields: tuple[str, ...]
    notes: tuple[str, ...] = ()
    minimum: tuple[str, ...] = ()


GUIDES: dict[str, IntakeGuide] = {
    "商务-ID": IntakeGuide(
        title="商务-ID",
        fields=(
            "博主IP：",
            "平台：",
            "平台ID：",
            "",
            "主页链接：",
            "账号名称：",
            "作者ID：",
            "粉丝数(k)：",
            "赛道：",
            "标签：",
            "院校背景：",
            "近期代表作品链接：",
            "品牌：",
            "产品：",
            "项目：",
            "档期：",
            "合作流程：",
            "报价信息：",
            "补充说明：",
        ),
        minimum=("博主IP", "平台", "平台ID"),
        notes=(
            "已有脚本会尽量从主页链接、平台ID、账号截图、历史表格和后续轮询派生其他信息。",
            "只知道最少三项也可以直接发；不要为了补齐模板手工编字段。",
        ),
    ),
    "创作": IntakeGuide(
        title="创作",
        fields=("平台：", "账号：", "赛道：", "类型：", "主体：", "发布时间：", "用户补充想法："),
        notes=(
            "可选补充：活动链接 / 参考爆款链接 / 商务目标 / 近期复盘结论。",
            "需要长期 Markdown 时，脚本/分镜/口播写入 /home/ubuntu/obsidian-media/03_脚本生产/ 或 08_内容项目/{项目ID}/04_script.md。",
        ),
    ),
    "创作-小红书": IntakeGuide(
        title="创作-小红书",
        fields=("账号：", "赛道：", "类型：图文 / 视频", "主体：", "发布时间：", "用户补充想法："),
        notes=(
            "可选补充：活动链接 / 参考爆款链接 / 商务目标 / 近期复盘结论。",
            "需要长期 Markdown 时，脚本/图文结构写入 /home/ubuntu/obsidian-media/03_脚本生产/ 或 08_内容项目/{项目ID}/04_script.md。",
        ),
    ),
    "创作-抖音": IntakeGuide(
        title="创作-抖音",
        fields=("账号：", "赛道：", "类型：视频", "主体：", "发布时间：", "用户补充想法："),
        notes=(
            "可选补充：活动链接 / 参考爆款链接 / 商务目标 / 近期复盘结论。",
            "需要长期 Markdown 时，脚本/分镜/口播写入 /home/ubuntu/obsidian-media/03_脚本生产/ 或 08_内容项目/{项目ID}/04_script.md。",
        ),
    ),
    "创作咨询": IntakeGuide(
        title="创作咨询",
        fields=("平台：", "账号：", "问题："),
        notes=("可选补充：赛道 / 当前目标 / 最近表现 / 参考链接。",),
    ),
    "创作-灵感": IntakeGuide(
        title="创作-灵感",
        fields=("灵感描述：", "素材说明：", "想再创作成什么：", "目标平台：", "补充要求："),
        notes=(
            "可以先上传照片/视频/截图，再发送本标签；系统会整理成创作灵感任务卡、给再创作方向和评分，并写入创作灵感表已有字段。",
            "需要长期 Markdown 时，标题文案沉淀到 /home/ubuntu/obsidian-media/05_素材与爆款库/标题文案库/，同款方向沉淀到 05_素材与爆款库/同款拆解/。",
        ),
    ),
    "素材创作": IntakeGuide(
        title="素材创作",
        fields=("平台：", "类型：", "账号：", "发布时间：", "补充要求："),
        notes=(
            "先上传图片或视频，再按模板发一次。",
            "需要长期 Markdown 时，脚本/分镜/口播写入 /home/ubuntu/obsidian-media/03_脚本生产/ 或 08_内容项目/{项目ID}/04_script.md。",
        ),
    ),
    "素材创作-小红书": IntakeGuide(
        title="素材创作-小红书",
        fields=("类型：图文 / 视频", "账号：", "发布时间：", "补充要求："),
        notes=(
            "先上传图片或视频，再按模板发一次。",
            "需要长期 Markdown 时，脚本/图文结构写入 /home/ubuntu/obsidian-media/03_脚本生产/ 或 08_内容项目/{项目ID}/04_script.md。",
        ),
    ),
    "素材创作-抖音": IntakeGuide(
        title="素材创作-抖音",
        fields=("类型：视频", "账号：", "发布时间：", "补充要求："),
        notes=(
            "先上传视频或图片，再按模板发一次。",
            "需要长期 Markdown 时，脚本/分镜/口播写入 /home/ubuntu/obsidian-media/03_脚本生产/ 或 08_内容项目/{项目ID}/04_script.md。",
        ),
    ),
    "内容素材": IntakeGuide(
        title="内容素材",
        fields=("素材链接：", "平台：", "用途：", "补充判断："),
        notes=("需要长期 Markdown 时，BGM、同款拆解、爆款结构、标题文案分别进入 /home/ubuntu/obsidian-media/05_素材与爆款库/ 下的对应目录。",),
    ),
    "拆解": IntakeGuide(
        title="拆解",
        fields=("素材链接：", "平台：", "拆解目标：", "重点关注：", "是否需要再创作："),
        notes=(
            "非空时会调用 SelfMedia 03-deconstruct-viral-content 生成爆款拆解文档；如果只是想记录复用方向，优先用【创作-再创】。",
            "需要长期 Markdown 时，同款拆解写入 /home/ubuntu/obsidian-media/05_素材与爆款库/同款拆解/，爆款结构写入 05_素材与爆款库/结构库/。",
        ),
    ),
    "活动": IntakeGuide(
        title="活动",
        fields=("活动标题：", "平台：", "活动链接 / Brief链接：", "活动正文：", "补充说明："),
        notes=("需要长期 Markdown 时，平台活动/投稿机会写入 /home/ubuntu/obsidian-media/02_选题活动/，热榜观察写入 02_选题活动/热榜观察/。",),
    ),
    "自媒体知识": IntakeGuide(
        title="自媒体知识",
        fields=("链接：", "平台：", "目标人群：", "核心痛点：", "补充问题：", "用途："),
        notes=("小红书图文和短视频都走这个入口；全部文案只保留作品正文和 tags，视频转写或图文 OCR 写入全部内容。",),
    ),
    "转写": IntakeGuide(
        title="转写",
        fields=("录音文件：先连续上传一条或多条", "整理目标：", "补充说明："),
        notes=("如果已经上传录音附件，系统会直接进入转写，不会停在模板。",),
    ),
    "灵感": IntakeGuide(
        title="灵感",
        fields=("灵感内容：", "相关素材 / 链接：", "想保留的判断：", "下一步用途："),
    ),
    "灵感-vlog": IntakeGuide(
        title="灵感-vlog",
        fields=("主题：", "现场想法：", "预计用途：", "时间线说明："),
        notes=("可先上传素材，再按模板补充。",),
    ),
    "复盘": IntakeGuide(
        title="复盘",
        fields=("平台：", "账号：", "作品链接：", "播放/阅读：", "点赞：", "收藏：", "评论：", "分享：", "结论：", "下次动作："),
        notes=(
            "带媒体指标时会同步进入媒体账号记忆，后续创作会读取这份复盘。",
            "需要长期 Markdown 时，发布后复盘写入 /home/ubuntu/obsidian-media/07_复盘与数据/。",
        ),
    ),
    "数据复盘": IntakeGuide(
        title="数据复盘",
        fields=("平台：", "账号：", "项目：", "主题：", "复盘节点：", "作品链接：", "补充目标："),
        notes=(
            "通常先上传抖音/小红书后台数据截图，再按模板补充；非空时会写入数据复盘表、复盘文档和媒体账号记忆。",
            "正文带项目时，会同步写入 /home/ubuntu/obsidian-media/08_内容项目/{project_id}/10_review.md。",
        ),
    ),
    "创作-再创": IntakeGuide(
        title="创作-再创",
        fields=("项目：", "素材链接：", "再创作意图：", "转化目标：", "想保留的点：", "补充说明："),
        notes=("正文带项目和 Mac 本地处理目标时，任务卡写入 /home/ubuntu/obsidian-media/98_Agent任务队列/01_cloud_to_mac_ready/。",),
    ),
    "去补丁": IntakeGuide(
        title="去补丁",
        fields=("目标文档链接：", "补充要求："),
    ),
    "自媒体-认知": IntakeGuide(
        title="自媒体-认知",
        fields=("主题：", "你的原判断：", "纠正后的判断：", "适用范围：", "补充例子："),
    ),
    "创作检查": IntakeGuide(
        title="创作检查",
        fields=("检查场景：", "当前问题：", "相关作品 / 文档链接："),
        notes=("只返回相关 checklist 云文档链接，不创建创作文档。",),
    ),
    "作品验收": IntakeGuide(
        title="作品验收",
        fields=("项目：", "目标状态：", "成片路径：", "创作要求：", "作品内容：", "平台 / 账号：", "重点验收项：", "补充说明："),
        notes=("会逐项判定满足、不满足或不确定；正文带项目、验收通过且状态机证据满足时推进项目状态。",),
    ),
}


def is_media_intake_tag(label: str, capability: TagCapability | None = None) -> bool:
    if label in GUIDES:
        return True
    return bool(capability and capability.bot == "Media bot")


def render_media_intake_prompt(label: str, capability: TagCapability | None = None) -> str:
    guide = GUIDES.get(label)
    if guide:
        title = guide.title
        fields = "\n".join(guide.fields).rstrip()
        notes = list(guide.notes)
        if guide.minimum:
            notes.insert(0, "最少需要：" + "、".join(guide.minimum) + "。")
    else:
        title = label
        fields = capability.example if capability else f"【{label}】"
        notes = [f"用途：{capability.purpose}"] if capability else []

    lines = [
        f"这是 Media bot 的【{title}】使用说明。",
        f"OpenClaw 模式：{GUIDE_MODEL} / {GUIDE_THINKING}。",
        "你按下面格式补充，我再继续执行：",
        "",
        fields,
    ]
    if notes:
        lines.extend(["", *notes])
    return "\n".join(line for line in lines if line is not None).rstrip()
