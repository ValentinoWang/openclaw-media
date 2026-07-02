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
    TagCapability("灵感", "inspiration", "handle_灵感", "归档碎片想法和未来可展开的内容线", "详文写入 Obsidian `灵感/归档/`，周记 `# 灵感` 凝练宏观总结、5句内摘要和详情链接", "【灵感】用零基础音乐实验验证 AI 成长档案能否迁移到表达维度"),
    TagCapability("灵感>vlog", "vlog_inspiration", "handle_灵感_vlog", "按 vlog 创作入口整理灵感和附件素材", "保存原始表达、最近上下文、附件时序索引；大文件上传 iCloud Drive，服务器只保留索引和临时缓存", "【灵感>vlog】今天散步想到一个开头：先拍路灯，再讲为什么普通人需要自己的AI工作流", "Media bot"),
    TagCapability("待办", "reminder", "handle_待办", "创建 Obsidian 待办清单或飞书提醒", "普通清单写入 Obsidian 周记当天 checklist；知识记录、素材记录或链接查看诉求也只整理成待办，不打开 Base/表格/文档、不请求飞书用户授权；有明确时间/提醒/截止时写入提醒与日程多维表格，并在 Obsidian 留带飞书记录ID的镜像 checkbox", "【待办】查看某条自媒体知识是否跟自己有关\n原链接：https://xhslink.com/xxxxx", "Daily bot"),
    TagCapability("日程", "calendar", "handle_日程", "创建飞书日历事件", "写入飞书日历，同时写入提醒与日程多维表格", "【日程】明天下午 3 点给客户回电话", "Daily bot"),
    TagCapability("待办-开发", "development_request", "handle_待办_开发", "创建正式开发任务并进入 Codex 追溯闭环", "生成正式开发任务卡，写入 Obsidian checklist 与飞书多维表格结构化台账；checklist 勾选后由 Mac 侧 Codex high 后置梳理", "【待办-开发】\n机器：VM-0-14-ubuntu\n地址：ubuntu@106.52.146.37\n任务：修复 Knowledge bot 归档后 Mac 不同步的问题\n验收：Mac 能看到新周记条目", "Daily bot"),
    TagCapability("今日", "daily_digest", "handle_今日", "查看今日提醒、日程、待办和开发任务", "读取本地归档生成轻量今日执行清单，不打开多维表格", "【今日】", "Daily bot"),
    TagCapability("周记", "weekly_self_model", "handle_周记", "整理每周周记和 Daily 能力使用记录", "读取 Obsidian 周记指定小节和 Daily 本地能力归档，生成自我模型候选草稿，不写入飞书", "【周记】 或 【周记】20260525-20260531", "Daily bot"),
    TagCapability("开发-完成", "development_status_update", "handle_开发_完成", "标记开发需求完成", "按任务ID或关键词把开发需求卡更新为已完成", "【开发-完成】修复 Knowledge bot 归档后 Mac 不同步的问题", "Daily bot"),
    TagCapability("开发-验证", "development_status_update", "handle_开发_验证", "标记开发需求进入待验证", "按任务ID或关键词把开发需求卡更新为待验证", "【开发-验证】修复 Knowledge bot 归档后 Mac 不同步的问题", "Daily bot"),
    TagCapability("活动", "activity", "handle_活动", "保存并压缩平台活动 Brief", "写入“近期活动”多维表格；需要长期 Markdown 时沉淀到 /home/ubuntu/obsidian-自媒体/02_选题活动/", "【活动】小红书活动信息 / Brief链接...", "Media bot"),
    TagCapability("补充", "document_supplement", "handle_补充", "补充并合并已有飞书文档", "读取被回复或正文指定的飞书文档，将用户补充文字合并进原文并覆盖写回同一文档", "【补充】这段需要并入上面文档的执行规则里"),
    TagCapability("内容素材", "content_material", "handle_内容素材", "保存素材、链接、选题", "调用 content-flow 后写入 OpenClaw 内容素材；长期素材卡按内容沉淀到 /home/ubuntu/obsidian-自媒体/05_素材与爆款库/", "【内容素材】https://xhslink.com/xxxxx", "Media bot"),
    TagCapability("拆解", "viral_deconstruction", "handle_拆解", "逐镜头拆解短视频/图文素材", "调用 selfmedia.deconstruct.viral_content 生成爆款拆解文档并写入拆解记录；同款拆解/结构库 Markdown 写入 /home/ubuntu/obsidian-自媒体/05_素材与爆款库/同款拆解/ 或 结构库/", "【拆解】https://v.douyin.com/xxxxx 重点看开头钩子和转场", "Media bot"),
    TagCapability("创作", "selfmedia_creation", "handle_creation", "按平台生成创作初稿", "读取活动、素材/拆解、创作模式和商务机会，创建创作文档到创作任务池，并写入 03_CreationRuns_创作运行可读运行索引；云端默认不写项目 Markdown，本地素材、项目包、Storyboard 和 EDL 由 Mac 侧素材流程接力生成", "【创作】项目=20260520_400米比赛_第一视角 平台=抖音 类型=视频 主体=第一视角挑战400米进53秒", "Media bot"),
    TagCapability("创作>小红书", "selfmedia_creation", "handle_creation", "小红书创作入口", "按明确类型生成小红书图文或视频稿件，匹配活动、爆款拆解和创作模式后创建创作任务池子文档，并写入 03_CreationRuns_创作运行可读运行索引；云端默认不写项目 Markdown，本地素材和项目文件由 Mac 侧处理", "【创作>小红书】赛道=职场成长 类型=图文/视频 主体=25岁女生如何提升表达力 发布时间=今晚8点", "Media bot"),
    TagCapability("创作>抖音", "selfmedia_creation", "handle_creation", "抖音创作入口", "按明确类型生成抖音图文或视频稿件，匹配活动、爆款拆解和创作模式后创建创作任务池子文档，并写入 03_CreationRuns_创作运行可读运行索引；云端默认不写项目 Markdown，本地素材和项目文件由 Mac 侧处理", "【创作>抖音】类型=图文/视频 赛道=体育 主体=毕业季田径比赛 发布时间=今晚8点", "Media bot"),
    TagCapability("创作-拍摄执行", "selfmedia_shooting_execution", "handle_shooting_execution", "把明确主题、场景、人物、参考和素材约束转换成拍摄执行单", "生成路线、镜头、人员、场地、B方案、现场 checklist、交付物清单；写入创作任务池子文档和 03_CreationRuns_创作运行可读运行索引", "【创作-拍摄执行】平台=抖音 类型=视频 主体=毕业季田径比赛 场地=操场 人物=我和同学 参考链接=https://...", "Media bot"),
    TagCapability("创作咨询", "selfmedia_creation_consultation", "handle_创作咨询", "基于现有数据表回答创作决策问题", "读取爆款内容积累表、近期活动、商务候选、账号记忆和复盘，输出创作建议，不新建文档", "【创作咨询】平台=小红书 账号=主账号 我最近适合做什么选题？", "Media bot"),
    TagCapability("创作-灵感", "selfmedia_creation_inspiration", "handle_创作灵感", "把照片/视频/文字整理成可再创作灵感", "读取附件视觉证据和文字，使用 direct Codex Responses 抽取可校验 JSON 文本，再生成 SourceAsset / MaterialDeconstruction 候选和运行索引；校验失败不写表；成功后写入创作任务池子文档和 03_CreationRuns_创作运行可读运行索引；云端默认不写项目 Markdown；只有存在本地素材绑定线索或 Mac 回写结果时，才创建或推进 Mac 素材匹配任务", "【创作-灵感】平台=抖音 目标=先写项目包和初稿脚本；如需 Mac 素材匹配，再补批次说明路径或本地素材路径", "Media bot"),
    TagCapability("素材创作", "selfmedia_material_creation", "handle_material_creation", "根据上传图片/视频做定位分析并生成初稿", "读取飞书附件，抽帧/识图后按明确平台和类型创建创作任务池子文档，并写入 03_CreationRuns_创作运行可读运行索引；云端默认不写项目 Markdown，本地素材和项目文件由 Mac 侧处理", "【素材创作】平台=抖音 类型=图文/视频 账号=主账号 发布时间=今晚8点", "Media bot"),
    TagCapability("素材创作>小红书", "selfmedia_material_creation", "handle_material_creation", "小红书平台素材创作入口", "根据上传图片/视频生成定位分析、小红书图文或视频初稿，创建创作任务池子文档，并写入 03_CreationRuns_创作运行可读运行索引；云端默认不写项目 Markdown，本地素材和项目文件由 Mac 侧处理", "【素材创作>小红书】类型=图文/视频 账号=主账号 发布时间=今晚8点", "Media bot"),
    TagCapability("素材创作>抖音", "selfmedia_material_creation", "handle_material_creation", "抖音平台素材创作入口", "根据上传图片/视频生成定位分析、抖音图文或视频脚本与发布文案，创建创作任务池子文档，并写入 03_CreationRuns_创作运行可读运行索引；云端默认不写项目 Markdown，本地素材和项目文件由 Mac 侧处理", "【素材创作>抖音】类型=图文/视频 账号=主账号 发布时间=明天12点", "Media bot"),
    TagCapability("数据复盘", "selfmedia_data_review", "handle_数据复盘", "根据后台数据截图做作品复盘", "复用飞书附件 batch，识别抖音/小红书后台截图数据，整理复盘结论和关键指标，写入数据复盘表、复盘文档和媒体账号记忆；正文带项目时同步写入项目内 10_review.md 并按状态机推进", "【数据复盘】平台=小红书 账号=主账号 项目=20260520_400米比赛_第一视角 复盘节点=24小时", "Media bot"),
    TagCapability("自媒体-认知", "selfmedia_cognition_accumulation", "handle_selfmedia_cognition", "沉淀或纠正自媒体认知", "由 OpenClaw 判断赛道和主旨，写入自媒体认知池子文档；同标题文档会整合覆盖更新", "【自媒体-认知】我以前以为低粉爆款说明账号方向对了，但现在看只能说明单条内容成立", "Media bot"),
    TagCapability("创作检查", "selfmedia_checklist_lookup", "handle_创作检查", "查看创作相关检查清单", "根据正文场景返回可审阅的 checklist 云文档链接，不新建文档、不写入版本", "【创作检查】作品发布前看哪个清单？", "Media bot"),
    TagCapability("作品验收", "selfmedia_work_acceptance", "handle_作品验收", "逐项对照创作要求验收作品", "读取作品内容和创作要求，逐项判定满足、不满足或不确定，并给出证据、缺口和修改建议；正文带项目且验收通过时按状态机推进项目状态", "【作品验收】项目=20260520_400米比赛_第一视角 目标状态=final_ready 成片路径=/Users/.../Final.mp4 创作要求：... 作品内容：...", "Media bot"),
    TagCapability("润色", "style_polish", "handle_style_polish", "自媒体语言风格与网感润色 canonical 入口", "读取账号记忆、平台机制和 CreativePattern 契约后诊断、改写、评分；显式润色只写 media_vault/style_polish_runs，不默认写 CreationRun", "【润色】\n平台：抖音\n内容类型：标题/正文/封面文案\n目标：更有网感但不要编造事实\n原文：我想说明训练不是靠鸡血，而是靠复盘和稳定执行。", "Media bot"),
    TagCapability("网感", "style_polish", "handle_style_polish", "润色 alias：更强平台化表达、钩子、冲突和评论触发", "归一到 style_polish；读取既有 SSOT，不新增事实，不自动晋升 CreativePattern", "【网感】\n平台：小红书\n原文：这个训练方法其实适合没时间的人。", "Media bot"),
    TagCapability("文案优化", "style_polish", "handle_style_polish", "润色 alias：优化标题、正文、封面文案或评论回复", "归一到 style_polish；版本落 media_vault/style_polish_runs，Feishu 只允许摘要和链接", "【文案优化】\n平台：抖音\n原文：我想把跑步复盘讲得更像短视频。", "Media bot"),
    TagCapability("改标题", "style_polish", "handle_style_polish", "润色 alias：只改标题或封面短句", "归一到 style_polish；保留 must_keep 事实和 avoid 边界，不造数据或身份", "【改标题】\n平台：小红书\n必须保留：清华、短跑\n原文：清华学生为什么还要练短跑", "Media bot"),
    TagCapability("去AI味", "style_polish", "handle_style_polish", "润色 alias：降低书面腔、模板腔和 AI 腔", "归一到 style_polish；只做表达层处理，不生成新事实或新账号人格", "【去AI味】\n平台：抖音\n原文：在当今时代，训练和复盘具有重要意义。", "Media bot"),
    TagCapability("小红书文案", "style_polish", "handle_style_polish", "润色 alias：面向小红书的标题、正文、封面文案优化", "归一到 style_polish；平台依据来自 config/platform_mechanisms/xiaohongshu.json", "【小红书文案】\n内容类型：图文标题\n原文：普通人怎么建立自己的内容复盘系统", "Media bot"),
    TagCapability("抖音文案", "style_polish", "handle_style_polish", "润色 alias：面向抖音的标题、正文、封面文案优化", "归一到 style_polish；平台依据来自 config/platform_mechanisms/douyin.json", "【抖音文案】\n内容类型：视频开头\n原文：我今天想讲一个关于训练复盘的反直觉想法", "Media bot"),
    TagCapability("拆解-再创", "recreation_task_card", "handle_再创作", "把素材复用或改编方向整理成再创作任务卡", "默认按简略深度处理；提取素材来源、再创作意图、转化目标、可迁移点、建议产物和待补充信息，并同步到创作任务池子文档和 03_CreationRuns_创作运行可读运行索引；正文明确写详细、完整拆解、Storyboard 或 EDL 时按详细深度处理；正文明确立项/初稿目标时创建 Content OS 项目包；正文带本地素材批次ID时派发 openclaw_queue_dispatch YAML，由 Mac 侧读取本地批次并回写素材结果", "【拆解-再创】爆款视频链接：https://... 模式：轻量反抄 / BGM 卡点 本地素材批次ID：20260627_清华毕业典礼", "Media bot"),
    TagCapability("拆解-再创-简略", "recreation_task_card_brief", "handle_再创作", "轻量反抄 / BGM 卡点再创作入口", "复用拆解包 partial 出口，只生成轻量剪辑卡、BGM/节奏参考、素材填空建议、标题/封面候选和发布文案初稿；不写完整 02A/02B，不生成完整 Storyboard/EDL；正文带本地素材批次ID时派发 openclaw_queue_dispatch YAML", "【拆解-再创-简略】爆款视频链接：https://... 模仿重点：BGM / 卡点 / 情绪氛围 本地素材批次ID：YYYYMMDD_事件名", "Media bot"),
    TagCapability("拆解-再创-详细", "recreation_task_card_detailed", "handle_再创作", "完整拆解与深度再创作入口", "复用完整拆解流程，生成完整拆解摘要、可迁移结构、避抄说明、自己的发布脚本、视频分镜/图文脚本、素材需求清单、标题封面和发布文案；存在本地素材批次ID或项目任务时派发 Mac 队列任务", "【拆解-再创-详细】爆款视频链接：https://... 目标：完整拆解 + 生成自己的发布脚本 + 素材匹配准备 本地素材批次ID：YYYYMMDD_事件名", "Media bot"),
    TagCapability("删除", "universal_deletion", "handle_删除", "按明确 ID 预览或确认删除任意能力产生的运行产物", "逐项列出并删除 archive/inbox、json、markdown、转写中间产物、创作运行记录、文档或本地文件；未确认只预览", "【删除】20260412-030515-qq-灵感-0056"),
    TagCapability("去补丁", "document_recompose", "handle_去补丁", "把带补充记录的飞书文档重整为一份完整正文", "读取指定文档，调用 LLM 合并补充内容并覆盖写回同一文档，不新建 v1/v2", "【去补丁】https://tcnwueberajc.feishu.cn/wiki/xxxx", "Media bot"),
    TagCapability("自媒体知识", "selfmedia_knowledge", "handle_自媒体知识", "按自媒体知识链路处理图文/视频链接", "根据链接内容自动识别图文或视频；图文提取图片、文案和结构化分析，视频沿用下载/转写/分析链路，完成后写入自媒体知识表", "【自媒体知识】https://xhslink.com/xxxxx", "Knowledge bot"),
    TagCapability("转写", "transcription", "handle_转写", "从上传录音文件提取逐字稿", "写入 Obsidian 会议纪要和原字稿；周记只留宏观总结、5句内摘要和链接", "【转写】（先连续上传一条或多条录音文件）", "Media bot"),
    TagCapability("转写-文字", "transcription_text", "handle_转写_文字", "整理已有语音转文字稿", "合并正文或文字附件，写入 Obsidian 会议纪要和原字稿；周记只留宏观总结、5句内摘要和链接", "【转写-文字】\n主题：会议主题\n文字稿：已经由语音转文字得到的文本", "Media bot"),
    TagCapability("商务>ID", "id_business", "handle_id_business", "提取达人主页和商务信息", "调用商务账号脚本，写入商务账号多维表格", "【商务>ID】小红书/抖音主页分享链接 + 品牌商务信息", "Media bot"),
    TagCapability("博主", "creator_profile_lookup", "handle_博主", "列出或查询已归档博主", "读取 06_CreatorProfiles_达人账号档案，返回外部系统唯一ID、账号名称、作者ID、主页链接、结构化身份信息、当前指标和档案链接", "【博主】小王 或 【博主】平台：抖音 关键词：清华", "Media bot"),
    TagCapability("博主-入库", "creator_profile_upsert", "handle_博主_入库", "维护博主账号身份字段", "统一 CreatorProfile v2 入库工作流：支持手工字段 upsert；支持平台+平台ID 自动补全生成 candidate-only；用户用 run_id 确认后才写入 06_CreatorProfiles_达人账号档案，并在确认写入成功后写 H02_AccountMetricSnapshot_账号指标快照", "【博主-入库】\n平台：抖音\n平台ID：22654404058\nID类型：抖音号\n链接：https://v.douyin.com/SJjgn_2KjYs/\n模式：自动补全", "Media bot"),
    TagCapability("归档", "knowledge_delegate", "delegate:knowledge", "通用知识入口", "转交 knowledge Bot 处理", "【归档】2025-12-03 学习/知识相关内容...", "Knowledge bot"),
    TagCapability("补全", "knowledge_delegate", "delegate:knowledge", "通用知识补全入口", "转交 knowledge Bot 补齐内容", "【补全】2025-12-03 一段已转写文字...", "Knowledge bot"),
    TagCapability("认知", "knowledge_delegate", "delegate:knowledge", "通用认知沉淀入口", "详文写 `认知/`，周记 `# 认知` 留宏观总结、5句摘要和链接；默认不写飞书", "【认知】短期反馈不能代表长期能力", "Knowledge bot"),
    TagCapability("学习", "knowledge_delegate", "delegate:knowledge", "通用学习入口", "转交 knowledge Bot 沉淀学习资料", "【学习】API", "Knowledge bot"),
    TagCapability("学习-整理", "knowledge_delegate", "delegate:knowledge", "通用学习整理入口", "转交 knowledge Bot，强制按整理类沉淀学习资料", "【学习-整理】一段课程笔记或 AI 回答...", "Knowledge bot"),
    TagCapability("调研", "research_delegate", "delegate:knowledge", "通用调研入口", "转交 knowledge Bot 处理", "【调研】某个主题或行业问题", "Knowledge bot"),
    TagCapability("复杂调研", "research_delegate", "delegate:knowledge", "复杂调研入口", "转交 knowledge Bot，使用更高思考等级", "【复杂调研】某个行业或竞品问题", "Knowledge bot"),
    TagCapability("深度调研", "research_delegate", "delegate:knowledge", "深度调研入口", "转交 knowledge Bot，使用更高思考等级", "【深度调研】一个需要系统分析的问题", "Knowledge bot"),
    TagCapability("研究", "research_delegate", "delegate:knowledge", "通用研究入口", "转交 knowledge Bot 处理", "【研究】某个论文/技术/市场主题", "Knowledge bot"),
    TagCapability("社交", "social_archive", "handle_社交", "处理社交对象档案", "生成/更新本地人物档案并同步 Obsidian；异性关系可同步一人一份飞书云文档；不写飞书多维表格", "【社交】对象：美汁源 这批截图生成交互档案", "Social bot"),
    TagCapability("人脉", "contact_archive", "handle_人脉", "处理无性关系/合作人脉档案", "生成/更新人脉档案，只写本地与 Obsidian；不写飞书云文档，不写飞书多维表格", "【人脉】对象：张三 微信备注：张总-AI教育 记录今天聊到的需求和下次跟进", "Social bot"),
    TagCapability("复盘", "generic_archive", "handle_generic", "记录项目/内容/账号复盘", "本地归档，可同步飞书", "【复盘】今天小红书选题测试，教育类话题点击更高"),
    TagCapability("整理", "summary", "handle_整理", "汇总最近记录", "生成最近记录摘要", "【整理】最近10条内容素材"),
    TagCapability("说明", "system", "handle_说明", "唯一 Bot 能力说明入口", "返回当前 Bot 可用的完整标签能力、输入格式和边界；`【A】`、`【A-B】` 与 `【A>B】` 同组展示", "【说明】"),
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
