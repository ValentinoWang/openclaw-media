from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class TagCapability:
    label: str
    capability: str
    handler: str
    purpose: str
    result: str
    example: str
    bot: str = "任意 Bot"


TAG_CAPABILITIES: tuple[TagCapability, ...] = (
    TagCapability("灵感", "inspiration", "handle_灵感", "整理碎片想法为灵感卡", "本地归档并同步飞书：主旨、内容线、素材、观点、知识点、执行清单", "【灵感】以清华AI体育生创业的一天作为主旨，穿插旅程截图、理念和一个AI科技知识点"),
    TagCapability("灵感-vlog", "vlog_inspiration", "handle_灵感_vlog", "按 vlog 创作入口整理灵感和附件素材", "保存原始表达、最近上下文、附件时序索引；大文件上传 iCloud Drive，服务器只保留索引和临时缓存", "【灵感-vlog】今天散步想到一个开头：先拍路灯，再讲为什么普通人需要自己的AI工作流", "Media bot"),
    TagCapability("待办", "reminder", "handle_待办", "创建待办提醒", "写入提醒与日程多维表格，到点由飞书 Bot 私聊提醒", "【待办】明天下午确认拍摄计划", "Daily bot"),
    TagCapability("日程", "calendar", "handle_日程", "创建飞书日历事件", "写入飞书日历，同时写入提醒与日程多维表格", "【日程】明天下午 3 点给客户回电话", "Daily bot"),
    TagCapability("开发", "development_request", "handle_开发", "沉淀开发需求、缺陷和自动化任务", "生成开发需求卡并本地归档；不创建到点提醒，不写入日程", "【开发】修复 Knowledge bot 归档后 Mac 不同步的问题\n验收：Mac 能看到新周记条目", "Daily bot"),
    TagCapability("今日", "daily_digest", "handle_今日", "查看今日提醒、日程、待办和开发任务", "读取本地归档生成轻量今日执行清单，不打开多维表格", "【今日】", "Daily bot"),
    TagCapability("完成", "task_status_update", "handle_完成", "标记本地归档任务完成", "按任务ID或关键词更新本地归档状态；不直接修改飞书多维表格", "【完成】修复 Mac 同步", "Daily bot"),
    TagCapability("延期", "task_status_update", "handle_延期", "标记本地归档任务延期", "按任务ID或关键词更新本地归档状态和本地截止时间；不直接修改飞书多维表格", "【延期】修复 Mac 同步 明天", "Daily bot"),
    TagCapability("取消", "task_status_update", "handle_取消", "标记本地归档任务取消", "按任务ID或关键词更新本地归档状态；不直接修改飞书多维表格", "【取消】修复 Mac 同步", "Daily bot"),
    TagCapability("开发-完成", "development_status_update", "handle_开发_完成", "标记开发需求完成", "按任务ID或关键词把开发需求卡更新为已完成", "【开发-完成】修复 Knowledge bot 归档后 Mac 不同步的问题", "Daily bot"),
    TagCapability("开发-验证", "development_status_update", "handle_开发_验证", "标记开发需求进入待验证", "按任务ID或关键词把开发需求卡更新为待验证", "【开发-验证】修复 Knowledge bot 归档后 Mac 不同步的问题", "Daily bot"),
    TagCapability("活动", "activity", "handle_活动", "保存并压缩平台活动 Brief", "写入“近期活动”多维表格；需要长期 Markdown 时沉淀到 /home/ubuntu/obsidian-media/02_选题活动/", "【活动】小红书活动信息 / Brief链接...", "Media bot"),
    TagCapability("补充", "document_supplement", "handle_补充", "补充并合并已有飞书文档", "读取被回复或正文指定的飞书文档，将用户补充文字合并进原文并覆盖写回同一文档", "【补充】这段需要并入上面文档的执行规则里"),
    TagCapability("内容素材", "content_material", "handle_内容素材", "保存素材、链接、选题", "调用 content-flow 后写入 OpenClaw 内容素材；长期素材卡按内容沉淀到 /home/ubuntu/obsidian-media/05_素材与爆款库/", "【内容素材】https://xhslink.com/xxxxx", "Media bot"),
    TagCapability("拆解", "viral_deconstruction", "handle_拆解", "逐镜头拆解短视频/图文素材", "调用 SelfMedia 03-deconstruct-viral-content 生成爆款拆解文档并写入拆解记录；同款拆解/结构库 Markdown 写入 /home/ubuntu/obsidian-media/05_素材与爆款库/同款拆解/ 或 结构库/", "【拆解】https://v.douyin.com/xxxxx 重点看开头钩子和转场", "Media bot"),
    TagCapability("创作", "selfmedia_creation", "handle_creation", "按平台生成创作初稿", "读取活动表和爆款内容积累表，创建创作文档；正文带项目时同步写入 /home/ubuntu/obsidian-media/08_内容项目/{project_id}/04_script.md 和 09_publish_pack.md", "【创作】项目=20260520_400米比赛_第一视角 平台=抖音 类型=视频 主体=第一视角挑战400米进53秒", "Media bot"),
    TagCapability("创作-小红书", "selfmedia_creation", "handle_creation", "小红书创作入口", "默认图文，匹配活动和爆款拆解后生成小红书稿件；长期脚本按 Obsidian Media 03_脚本生产/ 或 08_内容项目/ 沉淀", "【创作-小红书】赛道=职场成长 类型=图文 主体=25岁女生如何提升表达力 发布时间=今晚8点", "Media bot"),
    TagCapability("创作-抖音", "selfmedia_creation", "handle_creation", "抖音创作入口", "默认视频，匹配活动和爆款拆解后生成抖音稿件；长期脚本按 Obsidian Media 03_脚本生产/ 或 08_内容项目/ 沉淀", "【创作-抖音】赛道=亲子教育 类型=视频 主体=孩子拖延写作业 发布时间=明天12点", "Media bot"),
    TagCapability("创作咨询", "selfmedia_creation_consultation", "handle_创作咨询", "基于现有数据表回答创作决策问题", "读取爆款内容积累表、近期活动、商务候选、账号记忆和复盘，输出创作建议，不新建文档", "【创作咨询】平台=小红书 账号=主账号 我最近适合做什么选题？", "Media bot"),
    TagCapability("创作-灵感", "selfmedia_creation_inspiration", "handle_创作灵感", "把照片/视频/文字整理成可再创作灵感", "读取附件视觉证据和文字，生成创作灵感任务卡、再创作方向和评分，并写入创作灵感表已有字段；正文带 Mac 本地素材路径和立项目标时创建 Content OS 项目包和 Mac task", "【创作-灵感】平台=抖音 本地素材路径=/Users/... 目标=先写项目包和初稿脚本，再交给 Mac 二次改稿", "Media bot"),
    TagCapability("素材创作", "selfmedia_material_creation", "handle_material_creation", "根据上传视频/图文做定位分析并生成初稿", "读取飞书附件，抽帧/识图后创建创作文档、作品档案，可建账号监控记录；长期脚本按 Obsidian Media 03_脚本生产/ 或 08_内容项目/ 沉淀", "【素材创作】平台=小红书 类型=图文 账号=主账号 发布时间=今晚8点", "Media bot"),
    TagCapability("素材创作-小红书", "selfmedia_material_creation", "handle_material_creation", "小红书素材创作入口", "根据上传图片/视频生成定位分析、小红书初稿和复盘档案；长期脚本按 Obsidian Media 03_脚本生产/ 或 08_内容项目/ 沉淀", "【素材创作-小红书】类型=图文 账号=主账号 发布时间=今晚8点", "Media bot"),
    TagCapability("素材创作-抖音", "selfmedia_material_creation", "handle_material_creation", "抖音素材创作入口", "根据上传视频/图片生成定位分析、抖音脚本和复盘档案；长期脚本按 Obsidian Media 03_脚本生产/ 或 08_内容项目/ 沉淀", "【素材创作-抖音】类型=视频 账号=主账号 发布时间=明天12点", "Media bot"),
    TagCapability("数据复盘", "selfmedia_data_review", "handle_数据复盘", "根据后台数据截图做作品复盘", "复用飞书附件 batch，识别抖音/小红书后台截图数据，整理复盘结论和关键指标，写入数据复盘表、复盘文档和媒体账号记忆；正文带项目时同步写入项目内 10_review.md 并按状态机推进", "【数据复盘】平台=小红书 账号=主账号 项目=20260520_400米比赛_第一视角 复盘节点=24小时", "Media bot"),
    TagCapability("自媒体-认知", "selfmedia_cognition_accumulation", "handle_selfmedia_cognition", "沉淀或纠正自媒体认知", "由 OpenClaw 判断赛道和主旨，写入自媒体认知池子文档；同标题文档会整合覆盖更新", "【自媒体-认知】我以前以为低粉爆款说明账号方向对了，但现在看只能说明单条内容成立", "Media bot"),
    TagCapability("创作检查", "selfmedia_checklist_lookup", "handle_创作检查", "查看创作相关检查清单", "根据正文场景返回可审阅的 checklist 云文档链接，不新建文档、不写入版本", "【创作检查】作品发布前看哪个清单？", "Media bot"),
    TagCapability("作品验收", "selfmedia_work_acceptance", "handle_作品验收", "逐项对照创作要求验收作品", "读取作品内容和创作要求，逐项判定满足、不满足或不确定，并给出证据、缺口和修改建议；正文带项目且验收通过时按状态机推进项目状态", "【作品验收】项目=20260520_400米比赛_第一视角 目标状态=final_ready 成片路径=/Users/.../Final.mp4 创作要求：... 作品内容：...", "Media bot"),
    TagCapability("创作-再创", "recreation_task_card", "handle_再创作", "把素材复用或改编方向整理成再创作任务卡", "提取素材来源、再创作意图、转化目标、可迁移点、建议产物和待补充信息，并同步到再创作任务池子文档；正文带项目和 Mac 本地处理目标时写入 /home/ubuntu/obsidian-media/98_Agent任务队列/01_cloud_to_mac_ready/", "【创作-再创】项目=20260520_400米比赛_第一视角 需要 Mac 输出素材匹配、Storyboard 和 EDL", "Media bot"),
    TagCapability("去补丁", "document_recompose", "handle_去补丁", "把带补充记录的飞书文档重整为一份完整正文", "读取指定文档，调用 LLM 合并补充内容并覆盖写回同一文档，不新建 v1/v2", "【去补丁】https://tcnwueberajc.feishu.cn/wiki/xxxx", "Media bot"),
    TagCapability("自媒体知识", "selfmedia_knowledge", "handle_自媒体知识", "按自媒体知识链路处理图文/视频链接", "根据链接内容自动识别图文或视频；图文提取图片、文案和结构化分析，视频沿用下载/转写/分析链路，完成后写入自媒体知识表", "【自媒体知识】https://xhslink.com/xxxxx", "Knowledge bot"),
    TagCapability("转写", "transcription", "handle_转写", "从上传录音文件提取逐字稿", "复用通用附件 batch，先总结内容，再按逐字稿标注说话人，写入 Obsidian 会议纪要", "【转写】（先连续上传一条或多条录音文件）", "Media bot"),
    TagCapability("商务-ID", "id_business", "handle_id_business", "提取达人主页和商务信息", "调用商务账号脚本，写入商务账号多维表格", "【商务-ID】小红书/抖音主页分享链接 + 品牌商务信息", "Media bot"),
    TagCapability("归档", "knowledge_delegate", "delegate:knowledge", "通用知识入口", "转交 knowledge Bot 处理", "【归档】2025-12-03 学习/知识相关内容...", "Knowledge bot"),
    TagCapability("补全", "knowledge_delegate", "delegate:knowledge", "通用知识补全入口", "转交 knowledge Bot 补齐内容", "【补全】2025-12-03 一段已转写文字...", "Knowledge bot"),
    TagCapability("学习", "knowledge_delegate", "delegate:knowledge", "通用学习入口", "转交 knowledge Bot 沉淀学习资料", "【学习】API", "Knowledge bot"),
    TagCapability("学习-整理", "knowledge_delegate", "delegate:knowledge", "通用学习整理入口", "转交 knowledge Bot，强制按整理类沉淀学习资料", "【学习-整理】一段课程笔记或 AI 回答...", "Knowledge bot"),
    TagCapability("调研", "research_delegate", "delegate:knowledge", "通用调研入口", "转交 knowledge Bot 处理", "【调研】某个主题或行业问题", "Knowledge bot"),
    TagCapability("复杂调研", "research_delegate", "delegate:knowledge", "复杂调研入口", "转交 knowledge Bot，使用更高思考等级", "【复杂调研】某个行业或竞品问题", "Knowledge bot"),
    TagCapability("深度调研", "research_delegate", "delegate:knowledge", "深度调研入口", "转交 knowledge Bot，使用更高思考等级", "【深度调研】一个需要系统分析的问题", "Knowledge bot"),
    TagCapability("研究", "research_delegate", "delegate:knowledge", "通用研究入口", "转交 knowledge Bot 处理", "【研究】某个论文/技术/市场主题", "Knowledge bot"),
    TagCapability("社交", "social_archive", "handle_社交", "处理社交对象档案", "生成/更新社交档案，可写入对应飞书表", "【社交】对象：美汁源 这批截图生成交互档案", "Social bot"),
    TagCapability("人脉", "contact_archive", "handle_人脉", "处理无性关系/合作人脉档案", "生成/更新人脉档案，不默认写入社交飞书表", "【人脉】对象：张三 微信备注：张总-AI教育 记录今天聊到的需求和下次跟进", "Social bot"),
    TagCapability("复盘", "generic_archive", "handle_generic", "记录项目/内容/账号复盘", "本地归档，可同步飞书", "【复盘】今天小红书选题测试，教育类话题点击更高"),
    TagCapability("整理", "summary", "handle_整理", "汇总最近记录", "生成最近记录摘要", "【整理】最近10条内容素材"),
    TagCapability("规则", "system", "handle_规则", "更新部分标签规则", "写入规则配置", "【规则】灵感 标签 内容素材,选题,高考季"),
    TagCapability("说明", "system", "handle_说明", "唯一 Bot 能力说明入口", "按当前 Bot 返回基础规则，以及每个能力标签能实现什么和输入格式", "【说明】"),
    TagCapability("最近", "system", "handle_最近", "查询最近归档", "返回最近 N 条记录", "【最近】10"),
    TagCapability("同步", "system", "handle_同步", "补同步未同步记录", "尝试同步最近未同步记录到飞书", "【同步】飞书"),
    TagCapability("状态", "system", "handle_状态", "查询任务状态", "按任务 ID 或最近任务返回状态", "【状态】<任务ID>"),
)

TAG_LABELS: tuple[str, ...] = tuple(capability.label for capability in TAG_CAPABILITIES)
UNIVERSAL_KNOWLEDGE_TAGS: set[str] = {capability.label for capability in TAG_CAPABILITIES if capability.capability == "knowledge_delegate"}
RESEARCH_KNOWLEDGE_TAGS: set[str] = {capability.label for capability in TAG_CAPABILITIES if capability.capability == "research_delegate"}
GENERIC_TAGS: set[str] = {capability.label for capability in TAG_CAPABILITIES if capability.handler == "handle_generic"}
SYSTEM_TAGS: set[str] = {capability.label for capability in TAG_CAPABILITIES if capability.capability == "system"}


def tag_capability_dicts() -> list[dict[str, Any]]:
    return [asdict(capability) for capability in TAG_CAPABILITIES]
