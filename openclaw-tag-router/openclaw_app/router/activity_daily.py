from __future__ import annotations

from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

from common.llm_client import is_model_capacity_failure, model_capacity_failure_detail

from .tag_router_common import *


DAILY_TASK_EXTRACTION_PROMPT = """你是 OpenClaw Daily 的自然语言事项抽取器。系统整体依赖你理解语义；下游代码只做 JSON 校验、置信度判断和写入，不会再用规则猜自然语言时间。

只输出一个 JSON object，不要 Markdown，不要解释。

输入 JSON 会提供：
- now：当前时间，ISO-8601
- timezone：时区
- expected_type：调用入口，可能是「待办」或「日程」；这是用户已经确认的类型边界，不得跨类型改判
- text/raw_text：用户原文
- recent_conversation_context：最近对话上下文，可用于消解“上一条/这个/那个”，但当前 text 优先级最高

语义抽取规则：
- 先判断用户真正想记录的事项，而不是字面套模板；忽略“我收到了这条”“帮我记一下”“这条待办是”等外层转述。
- expected_type="待办" 时 type 必须输出「待办」；即使正文提到出行、会议、上课或地点，也不得改成日程。
- expected_type="日程" 时 type 必须输出「日程」；日程必须具有可落到日历上的完整日期和时间。
- 「截止」「报名截止」「统计截止」「ddl/deadline」「前完成」「之前完成」「前提交」表示待办截止时间，type=待办。
- 「到某地参加/旁听/上课/会议/面试/活动」表示日程时间，type=日程。
- 允许处理同类说法：报名截止、材料提交、课程旁听、机器人汇报、面试、会议、出行、上课、活动提醒；遇到没见过但语义相同的表达，按语义归类，不要因为关键词不完全一致而失败。
- 中文日期时间必须转成绝对 ISO-8601，包含时区；例如“5 月 31 日中午 12:00”在 now 为 2026 年时输出 2026-05-31T12:00:00+08:00。
- 没有年份时，优先使用 now 所在年份；如果该日期已经过去，再用下一年。
- “中午 12:00”就是 12:00；“下午 3 点”是 15:00；“晚上 8 点”是 20:00。
- recent_conversation_context 只能用来补“上一条/这个/那个/同上”这类明确指代；不能覆盖当前 text 中的明确日期、时间、地点或事项。

校验约束：
- due_at 必须来自用户原文或明确上下文，且必须是绝对 ISO-8601 时间。
- 不允许把无法解析的时间默认成今天 14:00，也不允许编造地点、标题或提醒时间。
- 只有日期、没有具体时刻时，不得补成 23:59、00:00 或其他默认时刻；due_at 置空。
- 如果日期或具体时间缺失，due_at 置空，confidence 不得高于 0.6，并在 missing_fields 写缺什么。
- 如果原文没有明确提醒时间，remind_at 可以置空；系统会按 type 使用默认提醒规则。
- title 要短，像飞书提醒标题，不要机械包含“我收到了这条”。

输出 JSON 字段：
{
  "type": "待办|日程|提醒|资料|unknown",
  "title": "简短标题",
  "due_at": "ISO-8601 或空字符串",
  "remind_at": "ISO-8601 或空字符串",
  "confidence": 0.0,
  "missing_fields": ["..."],
  "evidence": "引用原文中支持该解析的关键片段",
  "reason": "一句话说明解析依据或失败原因"
}

示例：
输入 text="我收到了这条毕业典礼报名待办：第一批统计截止到 5 月 31 日中午 12:00。"，now="2026-05-29T10:00:00+08:00"
输出 {"type":"待办","title":"毕业典礼报名第一批统计截止","due_at":"2026-05-31T12:00:00+08:00","remind_at":"","confidence":0.92,"missing_fields":[],"evidence":"第一批统计截止到 5 月 31 日中午 12:00","reason":"原文明确说明报名统计截止时间"}

输入 text="2026-06-01 18:00 前完成关于租房的小红书帖子"，now="2026-05-30T22:00:00+08:00"
输出 {"type":"待办","title":"完成租房小红书帖子","due_at":"2026-06-01T18:00:00+08:00","remind_at":"","confidence":0.9,"missing_fields":[],"evidence":"2026-06-01 18:00 前完成关于租房的小红书帖子","reason":"原文明确说明需要在 2026-06-01 18:00 前完成该帖子"}

输入 text="思尧，明天下午去 C 楼教室吧。《机器人与仿生学》上课时间：5 月 29 日13:30，上课地点：深圳学思楼C3-202教室。"，now="2026-05-29T10:48:00+08:00"
输出 {"type":"日程","title":"旁听机器人仿真汇报","due_at":"2026-05-29T13:30:00+08:00","remind_at":"","confidence":0.92,"missing_fields":[],"evidence":"上课时间：5 月 29 日13:30，上课地点：深圳学思楼C3-202教室","reason":"原文明确说明上课/旁听时间和地点"}
"""

DAILY_TODO_INTAKE_PROMPT = """你是 OpenClaw Daily 的待办入口分流器。系统依赖你判断【待办】正文应该写 Obsidian checklist，还是创建飞书提醒。Python 只做 JSON 校验、日期路径计算、Markdown 结构保留、Markdown 写入和 Feishu record id 绑定，不会用关键词或规则补业务语义。

只输出一个 JSON object，不要 Markdown，不要解释。

输入 JSON 会提供：
- now：当前时间，ISO-8601
- timezone：时区
- text/raw_text：用户原文
- recent_conversation_context：最近对话上下文，可用于消解明确指代；当前 text 优先级最高

- mode="checklist_only"：普通购物、整理、检查、执行清单；没有明确到点提醒或具体时刻要求，且不需要保留父子层级时使用。输出 flat items。待办没有日期或时间也必须正常创建。
- mode="structured_checklist"：原文明显是一个任务组/目标下面拆出多件可执行子事项，且父子关系值得保留时使用。输出 checklist_tree，系统会写飞书父记录/子记录，并在 Obsidian 用缩进 checkbox 表达。
- mode="reminder_backed"：用户明确要求提醒/到点通知，或者原文明示了完整日期和具体时刻的截止、执行、前完成/前提交事项。只有日期但没有具体时刻、且没有提醒诉求时，不使用此模式。
- mode="pending_manual"：仅当正文为空、内容自相矛盾，或 LLM 无法产生任何可执行待办文本时使用。不得因为正文属于其他 Bot 的业务领域而使用。
- 不要强迫所有待办都有父子结构；只有需要拆、且拆出来比平铺更清楚时，才使用 structured_checklist。
- 判断优先级：先确认是否存在可执行待办；存在就必须创建 checklist_only 或 structured_checklist。时间只决定是否升级为 reminder_backed，不能决定待办是否创建。
- “完成、准备、筹备、整理、规划、跟进”表达的是待办动作；即使包含“上海行程、出行、会议材料、上课资料”等词，也不得据此改成日程。
- 仅日期的“某日前完成/提交/截止”保留为 checklist，Obsidian 日期解析器会选择目标周记；不得为了写提醒补成 23:59。
- 只有可落到具体时刻的提醒或截止才使用 reminder_backed；时间信息不足但用户明确要求提醒时仍使用 reminder_backed，由下一阶段请求补时间。
- 如果用户原文已经写成 Markdown checkbox 且存在缩进子项，例如 `- [ ] 父主题` 下有 `  - [ ] 子任务`，必须使用 structured_checklist，并按原缩进保留父子层级；不要把显式父子清单扁平化成 checklist_only。
- `【待办】` 是用户已经做出的入口决策。你只能决定 checklist_only、structured_checklist 或 reminder_backed，不能把它改路由到 media、knowledge 或其他 Bot。即使正文要求素材入库、研究、视频拆解、口播创作、脚本改写或分镜制作，也只把这些动作整理成待办，不在本轮执行。
- 如果 `【待办】` 正文里提到“查看/看一下/判断/能否学习/能否复现/是否跟自己有关”，并附带 OpenClaw 视频知识、自媒体知识、知识库记录、Base、表格、文档标题、平台链接、原链接、来源平台、内容类型或分类字段，只把这些内容整理成一条或多条待办事项；不要打开或读取知识库/Base/表格/文档，不要请求飞书用户授权，不要改判为知识、学习、调研或自媒体知识入口。
- checklist_only 的 items 是较少、可执行、可完成的平铺单元；每个 item 不超过 28 个汉字。
- structured_checklist 的父节点表达任务组或目标，例如“购买”“整理房间”“准备出行”；子节点表达可执行动作，例如“购买杠铃杆”“确认证件”“收拾充电器”。
- checklist_tree 最多 12 个父节点；每个父节点最多 8 个子节点；每个 text 不超过 28 个汉字。
- 不要为 checklist_only 或 structured_checklist 编造提醒时间；不要把仅有日期但无提醒诉求的普通清单强行变成提醒。
- 如果用户写了日期，例如 20260628 或 2026-06-28，它只影响 Obsidian 目标日期；不必放入每个 item。

输出 JSON 字段：
{
  "mode": "checklist_only|structured_checklist|reminder_backed|pending_manual",
  "items": ["平铺待办项"],
  "checklist_tree": [
    {"text": "父单元", "children": [{"text": "子单元", "children": []}]}
  ],
  "confidence": 0.0,
  "missing_fields": ["..."],
  "evidence": "引用原文中支持该判断的关键片段",
  "reason": "一句话说明判断依据或失败原因"
}

示例：
输入 text="购买\\n1. 整理\\n2. 杠铃杆\\n3. 起泡器"
输出 {"mode":"structured_checklist","items":[],"checklist_tree":[{"text":"购买","children":[{"text":"整理购买清单","children":[]},{"text":"购买杠铃杆","children":[]},{"text":"购买起泡器","children":[]}]}],"confidence":0.95,"missing_fields":[],"evidence":"购买；1. 整理；2. 杠铃杆；3. 起泡器","reason":"原文是购买任务组下面列出多个子事项，需要保留父子层级"}

输入 text="- [ ] 按目标样式做设计\\n  - [ ] 给出第二份 HTML protocol\\n  - [ ] 进行视觉迭代"
输出 {"mode":"structured_checklist","items":[],"checklist_tree":[{"text":"按目标样式做设计","children":[{"text":"给出第二份 HTML protocol","children":[]},{"text":"进行视觉迭代","children":[]}]}],"confidence":0.95,"missing_fields":[],"evidence":"- [ ] 按目标样式做设计；  - [ ] 给出第二份 HTML protocol；  - [ ] 进行视觉迭代","reason":"原文显式使用缩进 checkbox 表达父子待办，需要保留父主题和子任务"}

输入 text="今天买杠铃杆、起泡器、垃圾袋"
输出 {"mode":"checklist_only","items":["购买杠铃杆","购买起泡器","购买垃圾袋"],"checklist_tree":[],"confidence":0.9,"missing_fields":[],"evidence":"买杠铃杆、起泡器、垃圾袋","reason":"原文是平铺购物清单，没有必要建立父子记录"}

输入 text="完成自媒体创作工作流和筹备上海行程"
输出 {"mode":"checklist_only","items":["完成自媒体创作工作流","筹备上海行程"],"checklist_tree":[],"confidence":0.94,"missing_fields":[],"evidence":"完成自媒体创作工作流；筹备上海行程","reason":"原文包含两个可执行待办，但没有提醒或具体时刻要求，应直接创建普通待办"}

输入 text="2026-07-20 前完成上海行程筹备"
输出 {"mode":"checklist_only","items":["完成上海行程筹备"],"checklist_tree":[],"confidence":0.92,"missing_fields":[],"evidence":"2026-07-20 前完成上海行程筹备","reason":"原文只有截止日期，没有具体时刻或提醒诉求，保留为日期型普通待办"}

输入 text="20260628 18:00 前买杠铃杆，提前 30 分钟提醒"
输出 {"mode":"reminder_backed","items":[],"checklist_tree":[],"confidence":0.95,"missing_fields":[],"evidence":"20260628 18:00 前；提前 30 分钟提醒","reason":"原文明确要求截止时间和提醒"}

输入 text="同济大学陈小杨有 AI4Math 的资源，可以用来做博主宣传做 vibecoding 的素材。"
输出 {"mode":"checklist_only","items":["跟进陈小杨 AI4Math 资源，用于博主宣传和 vibecoding 素材"],"checklist_tree":[],"confidence":0.9,"missing_fields":[],"evidence":"同济大学陈小杨有 AI4Math 的资源；博主宣传；vibecoding 的素材","reason":"用户显式使用【待办】，原文是一条可跟进事项，且没有截止或提醒诉求"}

输入 text="根据这个视频拆解出一个 WAIC 的视频口播，然后尝试把一个口碑脚本改写成分镜脚本\nhttps://www.xiaohongshu.com/example"
输出 {"mode":"structured_checklist","items":[],"checklist_tree":[{"text":"制作 WAIC 视频脚本","children":[{"text":"拆解参考视频并产出口播","children":[]},{"text":"将口碑脚本改写为分镜","children":[]}]}],"confidence":0.94,"missing_fields":[],"evidence":"拆解出 WAIC 视频口播；把口碑脚本改写成分镜脚本","reason":"用户显式使用【待办】，两个动作属于同一视频脚本制作目标下的执行步骤"}

输入 text="查看做题家清北光环为何难穿越创业泥潭否 跟自己有关\n做题家清北光环为何难穿越创业泥潭\n原链接\nhttp://xhslink.com/o/16704LMMFPp\n来源平台\n小红书\n内容类型\n图文\n一级分类\n财经/投资\n二级分类\n投资认知"
输出 {"mode":"checklist_only","items":["查看清北光环创业泥潭是否相关"],"checklist_tree":[],"confidence":0.9,"missing_fields":[],"evidence":"查看做题家清北光环为何难穿越创业泥潭否 跟自己有关；原链接 http://xhslink.com/o/16704LMMFPp","reason":"用户显式使用【待办】，正文是查看并判断某条知识记录是否相关，没有提醒、截止或读取知识库诉求"}
"""

DAILY_TODO_HIERARCHY_REVIEW_PROMPT = """你是 OpenClaw Daily 的待办父子层级复核器。上游 LLM 已把【待办】正文拆成多个平铺 items；你只判断这些 items 是否其实属于同一个父主题/目标下的子任务。

只输出一个 JSON object，不要 Markdown，不要解释。

复核规则：
- 如果 items 是同一个项目/目标的一组步骤，必须输出 mode="structured_checklist"，用第一项或更准确的概括作为父节点，后续执行项作为 children。
- 如果第一项本身是总目标，后续项是交付物、协议、复核、迭代、检查、确认、发布等执行步骤，保留第一项为父节点。
- 如果 items 只是并列购物、并列物品、互不依赖的零散事项，保持 mode="checklist_only"。
- 不要编造提醒时间、截止时间或 Feishu 字段；本复核只决定 checklist_only 还是 structured_checklist。
- 如果无法确认父子层级，保持 checklist_only。

输入 JSON 会提供：
- now/timezone
- text/raw_text：用户原文
- items：上游平铺待办项
- original_reason：上游判断理由

输出 JSON 字段：
{
  "mode": "checklist_only|structured_checklist",
  "items": ["平铺待办项，若保持 checklist_only 才填写"],
  "checklist_tree": [
    {"text": "父主题/目标", "children": [{"text": "子任务", "children": []}]}
  ],
  "confidence": 0.0,
  "missing_fields": [],
  "evidence": "引用原文或 items 中支持判断的关键片段",
  "reason": "一句话说明"
}

示例：
输入 text="按照目标样式做设计，给出第二份html protocol，视觉迭代", items=["按目标样式做设计","给出第二份 HTML protocol","进行视觉迭代"]
输出 {"mode":"structured_checklist","items":[],"checklist_tree":[{"text":"按目标样式做设计","children":[{"text":"给出第二份 HTML protocol","children":[]},{"text":"进行视觉迭代","children":[]}]}],"confidence":0.92,"missing_fields":[],"evidence":"按照目标样式做设计；给出第二份html protocol；视觉迭代","reason":"第一项是设计目标，后两项是围绕该目标的交付和迭代步骤，需要父子待办"}

示例：
输入 text="今天买杠铃杆、起泡器、垃圾袋", items=["购买杠铃杆","购买起泡器","购买垃圾袋"]
输出 {"mode":"checklist_only","items":["购买杠铃杆","购买起泡器","购买垃圾袋"],"checklist_tree":[],"confidence":0.9,"missing_fields":[],"evidence":"买杠铃杆、起泡器、垃圾袋","reason":"三个 items 是并列购物项，不需要父子层级"}
"""

DAILY_HIERARCHY_RECORDS_PROMPT = """你是 OpenClaw Daily 的层级结构清洗器。你的任务不是按关键词套模板，而是尽量还原用户原文里的父子层级：父记录承载整体事项/活动/通知，子记录承载可执行的日程、待办或提醒。

只输出一个 JSON object，不要 Markdown，不要解释。

判断规则：
- 如果原文只是单个原子事项，输出 status="single"，不要硬拆父子记录。
- 如果原文包含整体背景 + 多个执行节点，输出 status="hierarchy"。
- expected_type 是用户确认的入口类型，不得把显式待办改成日程，也不得把显式日程改成待办。
- expected_type="待办" 且原文只是项目、目标、准备事项或无精确时间的任务拆解时，输出 status="single"，交给下游 checklist 分流器处理；不要创建需要时间的 Daily 日程层级。
- 只有原文确实是通知/活动安排，并且需要保留的日程、截止等子节点都具有可解析的完整日期时间时，才输出 status="hierarchy"。
- 整体背景可能是活动、课程安排、会议通知、报名说明、项目安排、材料提交链路等，不限于“通知/预通知”几个词。
- 子记录要覆盖原文中真正需要执行或提醒的节点，例如当天参加、报名确认、统计截止、签到、材料提交、面试、会议等。

输入 JSON 会提供：
- now：当前时间，ISO-8601
- timezone：时区
- expected_type：调用入口，可能是「待办」或「日程」
- text/raw_text：用户原文

输出 JSON 字段：
{
  "status": "hierarchy|single|needs_manual",
  "confidence": 0.0,
  "parent": {
    "type": "日程",
    "title": "父记录标题",
    "summary": "清洗后的通知摘要",
    "location_parts": {
      "省份": "省/直辖市，可空",
      "城市": "城市",
      "区域": "区县/片区/大学城等",
      "校区/园区": "校区或园区",
      "场馆": "场馆/会议中心/教学楼",
      "楼栋": "楼栋",
      "楼层": "楼层",
      "房间": "教室/会议室/礼堂",
      "地址补充": "其他必要补充"
    },
    "fields": {
      "地点": "父事项地点，可空",
      "类型说明": "清洗后的父事项说明",
      "来源链接": "父事项对应链接，可空",
      "未填写原因": "无法填写的相关字段及原因"
    }
  },
  "children": [
    {
      "type": "日程|待办|提醒",
      "title": "子记录标题",
      "due_at": "ISO-8601",
      "remind_at": "ISO-8601 或空字符串",
      "location": "地点，可空",
      "location_parts": {
        "省份": "省/直辖市，可空",
        "城市": "城市",
        "区域": "区县/片区/大学城等",
        "校区/园区": "校区或园区",
        "场馆": "场馆/会议中心/教学楼",
        "楼栋": "楼栋",
        "楼层": "楼层",
        "房间": "教室/会议室/礼堂",
        "地址补充": "其他必要补充"
      },
      "source_link": "链接，可空",
      "fields": {
        "事项类型": "典礼当天|报名截止|材料提交|其他",
        "类型说明": "子事项说明",
        "说明": "清洗后的子事项说明",
        "参与方式": "子事项涉及的参与/报名方式，可空",
        "提交要求": "子事项涉及的提交或确认要求，可空",
        "来源链接": "子事项对应链接，可空",
        "未填写原因": "无法填写的相关字段及原因"
      }
    }
  ],
  "missing_fields": ["..."],
  "evidence": "关键原文证据",
  "reason": "一句话说明"
}

清洗规则：
- 父记录只描述整体事项本体，不把某个子节点的截止时间误当成父记录时间。
- 子记录按原文层级拆出所有可执行节点；如果只有一个执行节点且没有整体背景，返回 single。
- 地点必须单独输出：父记录只写内部 `location_parts`，子记录写 `location`；能识别完整地点时，格式尽量补全为“省/直辖市 市 区/片区 具体地点 具体位置信息”。
- 子记录地点不能只输出“综合体育馆”“东大操场”这类裸场馆名；能根据原文或可靠常识确定校区时，必须补全到省/直辖市、市、区县/片区、学校/校区、场馆；不能确定时把 location_parts 加入 missing_fields，不要写裸地点。
- `地点拆解JSON` 这类后端结构字段不能进入 Feishu 表格；父记录和子记录都只写 Daily 可见字段。
- 字段要尽量填完整：父记录只保留 `地点`、`类型说明`、`来源链接`、`未填写原因`；子记录只保留 `地点`、`来源链接`、`类型说明`、`未填写原因`。不要输出活动表字段、可见 JSON 字段、`父记录ID`、`优先级` 或 `详情JSON`。
- 日期时间必须输出绝对 ISO-8601，包含时区。没有年份时用 now 所在年份；若该日期已经过去，再用下一年。
- 字段值要去掉寒暄、emoji、转发口吻和无关修辞；保留可执行事实。
- 不要编造时间、地点或链接。缺关键字段时 status=needs_manual。
- Python 只会校验你返回的结构并按父记录先、子记录后的顺序写入，不会再用规则补语义。

示例：
输入 text="【关于举行我院2026年毕业典礼的预通知】学院拟定于2026年6月26日举行毕业典礼。一、活动时间 2026年6月26日（周五）上午10:00 二、活动地点 深圳大学城国际会议中心千人礼堂。请填写链接报名：https://v.wjx.cn/vm/Q0Rf163.aspx# 注：第一批统计截止到5月31日（周日）中午12：00"
输出 {"status":"hierarchy","confidence":0.94,"parent":{"type":"日程","title":"清华大学深圳国际研究生院2026年毕业典礼","summary":"2026届毕业生参加学院毕业典礼，需通过问卷报名确认。","location_parts":{"省份":"广东省","城市":"深圳市","区域":"大学城","场馆":"深圳大学城国际会议中心","房间":"千人礼堂"},"fields":{"类型说明":"2026届毕业生参加学院毕业典礼，需通过问卷报名确认。","来源链接":"https://v.wjx.cn/vm/Q0Rf163.aspx#","未填写原因":"填写要点：未填写，原因：原文未说明具体问卷题目。"}},"children":[{"type":"日程","title":"参加2026年毕业典礼","due_at":"2026-06-26T10:00:00+08:00","remind_at":"","location":"广东省 深圳市 大学城 深圳大学城国际会议中心 千人礼堂","location_parts":{"省份":"广东省","城市":"深圳市","区域":"大学城","场馆":"深圳大学城国际会议中心","房间":"千人礼堂"},"source_link":"https://v.wjx.cn/vm/Q0Rf163.aspx#","fields":{"事项类型":"典礼当天","说明":"毕业典礼包括暖场表演、师生校友代表发言、院长讲话、毕业合影等环节。"}},{"type":"待办","title":"毕业典礼第一批报名统计截止","due_at":"2026-05-31T12:00:00+08:00","remind_at":"","location":"","location_parts":{},"source_link":"https://v.wjx.cn/vm/Q0Rf163.aspx#","fields":{"事项类型":"报名截止","说明":"完成问卷确认。","未填写原因":"地点：未填写，原因：报名截止事项不涉及线下地点。"}}],"missing_fields":[],"evidence":"活动时间 2026年6月26日上午10:00；活动地点 深圳大学城国际会议中心千人礼堂；第一批统计截止到5月31日中午12:00","reason":"原文包含毕业典礼本体和报名统计截止两个层级节点"}

输入 text="5 月 29 日 13:30，到深圳学思楼 C3-202 教室旁听机器人仿真汇报。"
输出 {"status":"single","confidence":0.9,"parent":{},"children":[],"missing_fields":[],"evidence":"单个旁听日程","reason":"原文只有一个日程节点，没有需要保留的父子层级"}
"""


class ActivityDailyMixin:
    def handle_活动(self, message: Message) -> TaskResult:
        activity_body, source_extractions = self._activity_body_with_source_extractions(message.body)
        ai_clean = self.content_flow_client.clean_activity_brief(
            activity_body,
            created_at=message.created_at.isoformat(timespec="seconds"),
            source_hint=message.source,
        )
        if ai_clean.get("status") == "done":
            activity = self._activity_from_ai_clean(activity_body, ai_clean)
        else:
            return self._activity_ai_clean_failure(message, ai_clean)
        self._mark_unread_external_activity_docs(activity)
        task_id = make_record_id(message.created_at, message.source, message.entry_tag)
        parse_status = activity.get("parse_status") or ("待人工补充" if activity.get("manual_needed") else "已解析")
        if parse_status == "已解析" and "待读取" in activity.get("source_status", ""):
            parse_status = "飞书文档待读取"
        source_links = self._activity_render_links(activity.get("links", []))
        split_links = self._activity_split_link_fields(activity.get("links", []))
        missing_info = "、".join(activity.get("missing_info") or [])
        extra = {
            "platform": activity["platform"],
            "main_topic": activity["main_topic"],
            "activity_time": activity["activity_time"],
            "brief_summary": activity.get("brief_summary", ""),
            "participation_method": activity.get("participation_method", ""),
            "participation_form": activity.get("participation_form", ""),
            "filling_points": activity.get("filling_points", ""),
            "submission_requirements": activity.get("submission_requirements", ""),
            "boost_date": activity.get("boost_date", ""),
            "source_status": activity.get("source_status", ""),
            "manual_needed": bool(activity.get("manual_needed")),
            "tags": ["素材", "活动", activity["platform"]],
            "source_extractions": source_extractions,
        }
        reminder = self.reminder_service.add(
            kind="活动",
            title=activity["title"],
            text=self._format_activity_record(activity, message.body),
            due_at=None,
            remind_at=None,
            source=message.source,
            ref_id=task_id,
            local_path="",
            extra_fields=self._activity_record_extra_fields(activity, source_links, split_links, parse_status, missing_info),
        )
        bitable_url = ((reminder.get("data") or {}).get("table_url") or self._configured_bitable_url("活动")) if reminder.get("ok") else self._configured_bitable_url("活动")
        record_id = (reminder.get("data") or {}).get("record_id") or task_id
        child_results = self._create_activity_direction_children(message, activity, record_id, task_id, source_links, split_links, parse_status, missing_info) if reminder.get("ok") else []
        boost_schedule = self._create_activity_boost_schedule(message, activity, record_id)
        failed_children = [item for item in child_results if not item.get("result", {}).get("ok")]

        reply_lines = [
            "活动已写入多维表格",
            f"标题：{activity['title']}",
            f"记录ID：{record_id}",
            f"平台：{activity['platform']}",
            f"时间：{activity['activity_time'] or '未提取到'}",
            f"主话题：{activity['main_topic'] or '未提取到'}",
            f"参与方式：{activity.get('participation_method') or '未提取到'}",
            f"参与形式：{activity.get('participation_form') or '未提取到'}",
            f"填写要点：{activity.get('filling_points') or '未提取到'}",
            f"冲榜日期：{activity.get('boost_date')}" if activity.get("boost_date") else "",
            "冲榜提醒：已创建提前一天日程" if boost_schedule.get("ok") else "",
            f"解析：{activity.get('source_status') or parse_status}",
            self._activity_source_extraction_reply(source_extractions),
            f"待补：{missing_info}" if missing_info else "",
            f"方向：{len(activity['directions'])} 个",
            f"方向子记录：已创建 {len(child_results) - len(failed_children)}/{len(child_results)} 条" if child_results else "",
            f"多维表格：{bitable_url}" if bitable_url else "",
        ]
        if activity.get("manual_needed"):
            reply_lines.append("文档正文暂未自动读取到；可以复制活动 Brief 正文后重新发 `【活动】`，我会合并提取并覆盖写入关键字段。")
        reply = "\n".join(line for line in reply_lines if line).strip()
        ok = bool(reminder.get("ok"))
        if failed_children:
            ok = False
        if not ok and reminder.get("error"):
            reply += f"\n错误：{reminder.get('error')}"
        return TaskResult(ok=ok, status="archived" if ok else ("partial_failed" if reminder.get("ok") else "pending_manual"), reply=reply, task_id=record_id, local_path="", feishu_doc="", extra={**extra, "child_results": child_results})

    def _activity_record_extra_fields(
        self,
        activity: dict[str, Any],
        source_links: str,
        split_links: dict[str, str],
        parse_status: str,
        missing_info: str,
        *,
        parent_record_id: str = "",
        direction_title: str = "",
    ) -> dict[str, Any]:
        directions = [direction_title] if direction_title else activity.get("directions", [])
        subtopic_directions = "\n".join(f"- {item}" for item in directions if str(item).strip())
        brief_summary = str(activity.get("brief_summary") or "").strip()
        if direction_title:
            brief_summary = "\n".join(line for line in [f"创作方向：{direction_title}", brief_summary] if line)
        fields: dict[str, Any] = {
            "类型": "活动",
            "主状态": activity.get("status", "进行中"),
            "平台名称": self._activity_platform_value(activity.get("platform", "")),
            "活动Brief": brief_summary,
            "填写要点": activity.get("filling_points", ""),
            "参与方式": activity.get("participation_method", ""),
            "参与形式": activity.get("participation_form", ""),
            "提交要求": activity.get("submission_requirements", ""),
            "子话题方向": subtopic_directions,
            "活动开始时间": activity.get("activity_time_start", ""),
            "活动结束时间": activity.get("activity_time_end", ""),
            "冲榜日期": "" if parent_record_id else activity.get("boost_date", ""),
            "活动奖励": activity.get("reward", ""),
            "主话题": activity.get("main_topic", ""),
            "活动级别": activity.get("level", ""),
            "Brief链接": source_links,
            **split_links,
            "解析状态": parse_status,
            "需人工补充": missing_info,
        }
        if parent_record_id:
            fields["父记录"] = parent_record_id
            fields["类型说明"] = "创作方向子记录"
        return fields

    def _create_activity_direction_children(
        self,
        message: Message,
        activity: dict[str, Any],
        parent_record_id: str,
        parent_ref_id: str,
        source_links: str,
        split_links: dict[str, str],
        parse_status: str,
        missing_info: str,
    ) -> list[dict[str, Any]]:
        directions = [str(item).strip() for item in activity.get("directions", []) if str(item).strip()]
        if len(directions) <= 1:
            return []
        results: list[dict[str, Any]] = []
        for index, direction in enumerate(directions, start=1):
            result = self.reminder_service.add(
                kind="活动",
                title=direction,
                text="\n".join(
                    line
                    for line in [
                        f"父活动记录ID：{parent_record_id}",
                        f"父标题：{activity.get('title', '')}",
                        f"创作方向：{direction}",
                        f"主话题：{activity.get('main_topic', '')}" if activity.get("main_topic") else "",
                        f"参与方式：{activity.get('participation_method', '')}" if activity.get("participation_method") else "",
                    ]
                    if line
                ),
                due_at=None,
                remind_at=None,
                source=message.source,
                ref_id=f"{parent_ref_id}-direction-{index}",
                local_path="",
                extra_fields=self._activity_record_extra_fields(
                    activity,
                    source_links,
                    split_links,
                    parse_status,
                    missing_info,
                    parent_record_id=parent_record_id,
                    direction_title=direction,
                ),
            )
            results.append({"direction": direction, "result": result})
        return results

    def _parse_activity_date(self, value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        tz = ZoneInfo(self.timezone)
        if re.match(r"^\d{4}-\d{2}-\d{2}$", text.replace("/", "-")):
            text = f"{text.replace('/', '-')}T09:00:00"
        try:
            parsed = datetime.fromisoformat(text.replace("/", "-").replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz).replace(hour=9, minute=0, second=0, microsecond=0)

    def _create_activity_boost_schedule(self, message: Message, activity: dict[str, Any], record_id: str) -> dict[str, Any]:
        boost_at = self._parse_activity_date(activity.get("boost_date"))
        if boost_at is None:
            return {}
        schedule_at = (boost_at - timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        text = "\n".join(
            line
            for line in [
                f"活动：{activity.get('title', '')}",
                f"冲榜日期：{activity.get('boost_date', '')}",
                f"活动记录ID：{record_id}",
                f"主话题：{activity.get('main_topic', '')}" if activity.get("main_topic") else "",
                f"参与方式：{activity.get('participation_method', '')}" if activity.get("participation_method") else "",
            ]
            if line
        )
        return self.reminder_service.add(
            kind="日程",
            title=f"冲榜提醒：{activity.get('title') or '活动'}",
            text=text,
            due_at=schedule_at,
            remind_at=schedule_at,
            source=message.source,
            ref_id=f"{record_id}-boost",
            local_path="",
        )

    def _activity_body_with_source_extractions(self, body: str) -> tuple[str, list[dict[str, Any]]]:
        text = (body or "").strip()
        if not text or not hasattr(self.content_flow_client, "analyze"):
            return text, []
        source_urls = self._activity_extractable_source_urls(text)
        if not source_urls:
            return text, []
        extracted_sections: list[str] = []
        extractions: list[dict[str, Any]] = []
        for url in source_urls[:2]:
            decision = self._activity_source_url_decision(url)
            action = str(decision.get("action") or "ignore")
            source_kind = str(decision.get("kind") or "unknown")
            if action == "skip":
                extractions.append(
                    {
                        "url": url,
                        "source_kind": source_kind,
                        "status": "skipped",
                        "extracted": False,
                        "reason": str(decision.get("reason") or "非正文链接"),
                    }
                )
                continue
            if action != "analyze":
                continue
            try:
                payload = self._activity_analyze_source_url(url)
            except Exception as exc:
                extractions.append({"url": url, "source_kind": source_kind, "status": "pending_manual", "reason": str(exc)})
                continue
            section = self._activity_source_extraction_section(url, payload if isinstance(payload, dict) else {})
            status = str((payload or {}).get("status") or "unknown") if isinstance(payload, dict) else "unknown"
            item = {
                "url": url,
                "source_kind": source_kind,
                "status": status,
                "media_dir": str((payload or {}).get("media_dir") or "") if isinstance(payload, dict) else "",
                "analysis_path": str((payload or {}).get("analysis_path") or "") if isinstance(payload, dict) else "",
            }
            if section:
                extracted_sections.append(section)
                item["extracted"] = True
            else:
                item["extracted"] = False
                if isinstance(payload, dict) and payload.get("reason"):
                    item["reason"] = str(payload.get("reason") or "")
            extractions.append(item)
        if not extracted_sections:
            return text, extractions
        enriched = "\n\n".join([text, "【链接内容提取】", *extracted_sections]).strip()
        return enriched, extractions

    def _activity_analyze_source_url(self, url: str) -> dict[str, Any]:
        poll_attempts = self._activity_source_analysis_poll_attempts()
        try:
            return self.content_flow_client.analyze(url, poll_attempts=poll_attempts)
        except TypeError:
            return self.content_flow_client.analyze(url)

    def _activity_source_analysis_poll_attempts(self) -> int:
        max_seconds_raw = os.getenv("SELFMEDIA_ACTIVITY_SOURCE_ANALYSIS_MAX_SECONDS", "180").strip()
        try:
            max_seconds = max(1.0, float(max_seconds_raw))
        except ValueError:
            max_seconds = 180.0
        try:
            interval = max(0.1, float(getattr(self.content_flow_client, "poll_interval_seconds", 0.5) or 0.5))
        except (TypeError, ValueError):
            interval = 0.5
        base_attempts = int(getattr(self.content_flow_client, "poll_attempts", 0) or 0)
        return max(base_attempts, int(max_seconds / interval))

    @staticmethod
    def _activity_source_url_decision(url: str) -> dict[str, str]:
        try:
            parsed = urlparse(url)
        except ValueError:
            return {"action": "ignore", "kind": "invalid_url", "reason": "链接格式不可解析"}
        host = (parsed.hostname or "").lower()
        path = parsed.path.lower()
        if host == "fe.xiaohongshu.com" and path.startswith("/ditto/"):
            return {
                "action": "skip",
                "kind": "xiaohongshu_publish_entry",
                "reason": "已跳过：小红书发布入口/模板页，不是笔记正文链接",
            }
        if host in {"xhslink.com", "xhslink.cn"} or host.endswith((".xhslink.com", ".xhslink.cn")):
            return {"action": "analyze", "kind": "xiaohongshu_shortlink", "reason": ""}
        if host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com"):
            return {"action": "analyze", "kind": "xiaohongshu_page", "reason": ""}
        return {"action": "ignore", "kind": "unsupported_url", "reason": "非小红书源链接"}

    @staticmethod
    def _activity_extractable_source_urls(text: str) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        for match in re.finditer(r"https?://[^\s<>'\"，。；、）)\]】]+", text or ""):
            url = match.group(0).rstrip("，。；、.）)]】")
            decision = ActivityDailyMixin._activity_source_url_decision(url)
            if decision.get("action") == "ignore":
                continue
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
        return urls

    def _activity_source_extraction_section(self, url: str, payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict) or payload.get("status") != "done":
            return ""
        analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
        platform = str(analysis.get("platform") or "").strip()
        if not platform and hasattr(self.content_flow_client, "_platform_from_url"):
            platform = str(self.content_flow_client._platform_from_url(url) or "").strip()
        image_ocr = str(analysis.get("image_ocr") or payload.get("image_ocr") or "").strip()
        screenshot_ocr = ""
        if not image_ocr:
            screenshot_ocr = self._activity_ocr_interaction_screenshot(payload, analysis)
        parts: list[tuple[str, Any]] = [
            ("来源链接", url),
            ("平台", platform),
            ("标题", analysis.get("title")),
            ("摘要", analysis.get("summary")),
            ("标签", analysis.get("tags")),
            ("平台文案", analysis.get("work_copy") or payload.get("caption") or analysis.get("caption")),
            ("完整内容", analysis.get("full_content")),
            ("图片OCR", image_ocr),
            ("截图OCR", screenshot_ocr),
        ]
        lines: list[str] = [f"链接：{url}"]
        for label, value in parts[1:]:
            rendered = self._activity_render_extracted_value(value)
            if rendered:
                lines.append(f"{label}：{rendered}")
        if len(lines) <= 1:
            return ""
        return self._activity_clip_text("\n".join(lines), 12000)

    def _activity_ocr_interaction_screenshot(self, payload: dict[str, Any], analysis: dict[str, Any]) -> str:
        screenshot_path = str(payload.get("interaction_screenshot_path") or analysis.get("interaction_screenshot_path") or "").strip()
        if not screenshot_path:
            return ""
        path = Path(screenshot_path)
        if not path.is_file() or path.stat().st_size <= 0:
            return ""
        ocr_path = path.with_name("activity-screenshot-ocr.txt")
        cached = self._activity_read_text_file(ocr_path)
        if cached:
            return cached
        try:
            proc = subprocess.run(
                ["tesseract", str(path), "stdout", "-l", "chi_sim+eng", "--psm", "6"],
                text=True,
                capture_output=True,
                timeout=45,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        text = self._activity_clean_ocr_text(proc.stdout)
        if text:
            try:
                ocr_path.write_text(text + "\n", encoding="utf-8")
            except OSError:
                pass
        return text

    @staticmethod
    def _activity_read_text_file(path: Path) -> str:
        if not path.is_file() or path.stat().st_size <= 0:
            return ""
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    @staticmethod
    def _activity_clean_ocr_text(text: str) -> str:
        lines: list[str] = []
        previous = ""
        for raw_line in (text or "").replace("\f", "\n").splitlines():
            line = " ".join(raw_line.split()).strip()
            if not line or line == previous:
                continue
            previous = line
            lines.append(line)
        return "\n".join(lines).strip()

    @staticmethod
    def _activity_render_extracted_value(value: Any) -> str:
        if value in (None, "", [], {}):
            return ""
        if isinstance(value, list):
            items = []
            for item in value:
                if isinstance(item, (dict, list)):
                    rendered = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                else:
                    rendered = str(item).strip()
                if rendered:
                    items.append(rendered)
            return "\n".join(f"- {item}" for item in items[:20])
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return str(value).strip()

    @staticmethod
    def _activity_clip_text(text: str, limit: int) -> str:
        value = str(text or "").strip()
        if len(value) <= limit:
            return value
        return value[:limit].rstrip() + "\n...[已截断]"

    @staticmethod
    def _activity_source_extraction_reply(extractions: list[dict[str, Any]]) -> str:
        if not extractions:
            return ""
        ok_count = sum(1 for item in extractions if item.get("extracted"))
        if ok_count:
            return f"链接提取：已提取 {ok_count}/{len(extractions)} 个小红书链接"
        skipped_count = sum(1 for item in extractions if item.get("status") == "skipped")
        reasons = [str(item.get("reason") or item.get("status") or "未提取").strip() for item in extractions if item]
        if skipped_count == len(extractions):
            return f"链接提取：已跳过 {skipped_count}/{len(extractions)} 个小红书链接（{reasons[0] if reasons else '非正文链接'}）"
        return f"链接提取：未提取到正文（{reasons[0] if reasons else '无可用结果'}）"

    def _activity_ai_clean_failure(self, message: Message, ai_clean: dict[str, Any]) -> TaskResult:
        reason = str(ai_clean.get("reason") or "AI 清洗未返回结构化结果").strip()
        entry = self.archive_service.save_archive(
            message,
            "活动 Brief 待 AI 清洗",
            [
                ("原始内容", message.body),
                ("处理状态", f"pending_manual\n原因：{reason}"),
                ("要求", "活动 Brief 字段必须由 LLM 清洗产生；本入口不会使用确定性抽取或关键词规则写表。"),
            ],
            {
                "status": "pending_manual",
                "tags": ["活动", "AI清洗失败"],
                "postprocess_status": "pending_manual",
                "postprocess_reason": reason,
            },
        )
        reply = "\n".join(
            [
                "活动没有写入多维表格：AI 清洗失败。",
                f"原因：{reason}",
                "已保留本地记录，但不会用规则生成活动字段。",
                f"本地路径：{entry.local_path}",
            ]
        )
        return TaskResult(
            ok=False,
            status="activity_ai_clean_pending_manual",
            reply=reply,
            task_id=entry.frontmatter["id"],
            local_path=entry.local_path,
            feishu_doc="",
            extra={"postprocess": ai_clean},
        )

    def _extract_activity_parent_id(self, text: str) -> str:
        match = re.search(r"(?:父记录|原记录ID|记录ID|record[_ ]?id)\s*[=:：]\s*([A-Za-z0-9_-]{6,64})", text or "", flags=re.IGNORECASE)
        return match.group(1).strip() if match else ""

    def _infer_activity_parent_id(self, message: Message) -> str:
        metadata = message.metadata or {}
        parent_message_ids = {
            str(metadata.get("parent_id") or "").strip(),
            str(metadata.get("root_id") or "").strip(),
        }
        parent_message_ids.discard("")
        context = self._conversation_context(message)
        items = context.get("items") if isinstance(context.get("items"), list) else []
        if parent_message_ids:
            for item in reversed(items):
                if not isinstance(item, dict):
                    continue
                ids = {
                    str(item.get("message_id") or "").strip(),
                    str(item.get("bot_reply_message_id") or "").strip(),
                }
                if parent_message_ids & ids:
                    found = self._extract_activity_record_id_from_text(
                        "\n".join(
                            str(item.get(key) or "")
                            for key in ("bot_reply", "text")
                        )
                    )
                    if found:
                        return found
        for item in reversed(items):
            if not isinstance(item, dict):
                continue
            found = self._extract_activity_record_id_from_text(
                "\n".join(
                    str(item.get(key) or "")
                    for key in ("bot_reply", "text")
                )
            )
            if found:
                return found
        return self._extract_activity_record_id_from_text(self._conversation_context_prompt(message))

    def _extract_activity_record_id_from_text(self, text: str) -> str:
        patterns = (
            r"(?:活动记录ID|记录ID|record[_ ]?id)\s*[=:：]\s*(recv[A-Za-z0-9_-]{6,64})",
            r"\b(recv[A-Za-z0-9_-]{6,64})\b",
        )
        for pattern in patterns:
            match = re.search(pattern, text or "", flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ""

    def _strip_activity_parent_marker(self, text: str) -> str:
        return re.sub(r"^\s*(?:父记录|原记录ID|记录ID|record[_ ]?id)\s*[=:：]\s*[A-Za-z0-9_-]{6,64}\s*", "", text or "", flags=re.IGNORECASE)

    def _activity_platform_value(self, platform: str) -> list[str]:
        value = str(platform or "").strip()
        return [value] if value else []

    def _mark_unread_external_activity_docs(self, activity: dict[str, Any]) -> None:
        links = activity.get("links") if isinstance(activity.get("links"), list) else []
        unread = []
        for item in links:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip().lower()
            if "doc.weixin.qq.com/" in url or "docs.qq.com/" in url:
                unread.append(str(item.get("label") or "腾讯文档").strip() or "腾讯文档")
        if not unread:
            return
        note = "微信/腾讯文档链接未自动读取，已按消息文本解析"
        status = str(activity.get("source_status") or "").strip()
        activity["source_status"] = f"{status}；{note}" if status else note
        missing = activity.get("missing_info")
        if not isinstance(missing, list):
            missing = []
        missing_note = "微信/腾讯文档链接未读取"
        if missing_note not in missing:
            missing.append(missing_note)
        activity["missing_info"] = missing
        activity["manual_needed"] = True
        if str(activity.get("parse_status") or "已解析").strip() == "已解析":
            activity["parse_status"] = "待人工补充"

    @classmethod
    def _activity_render_links(cls, links: Any) -> str:
        normalized = cls._activity_normalize_link_items(links)
        return "\n".join(f"{item['label']}：{item['url']}" for item in normalized)

    @classmethod
    def _activity_split_link_fields(cls, links: Any) -> dict[str, str]:
        fields: dict[str, list[str]] = {}
        for item in cls._activity_normalize_link_items(links):
            field_name = cls._activity_link_field_name(item["label"], item["url"])
            if not field_name:
                continue
            fields.setdefault(field_name, []).append(f"{item['label']}：{item['url']}")
        return {field: "\n".join(values) for field, values in fields.items()}

    @staticmethod
    def _activity_link_field_name(label: str, url: str) -> str:
        text = f"{label} {url}".lower()
        if "douyin.com/note" in text or any(keyword in text for keyword in ("爆款", "示范", "范式", "参考")):
            return "爆款示范链接"
        if any(keyword in text for keyword in ("返稿", "报名", "报名表", "表单", "sheets", "forms", "wjx")):
            return "返稿链接"
        if any(keyword in text for keyword in ("活动文档", "文档", "详情", "规则", "brief", "wiki", "docx")):
            return "活动文档链接"
        return ""

    @classmethod
    def _activity_fields_with_split_links(cls, fields: dict[str, Any]) -> dict[str, Any]:
        result = dict(fields)
        split_links = cls._activity_split_link_fields(result.get("Brief链接", ""))
        for name, value in split_links.items():
            result.setdefault(name, value)
        return result

    @staticmethod
    def _activity_canonical_link_url(url: str) -> str:
        cleaned = str(url or "").strip().rstrip("，。；、.）)]】")
        text_fragment = re.search(r"(?:[#?&](?::~:)?text=)([^\s]+)", cleaned)
        if text_fragment:
            decoded = unquote(text_fragment.group(1)).strip().rstrip("，。；、.）)]】")
            nested = re.search(r"https?://\S+", decoded)
            if nested:
                cleaned = nested.group(0).rstrip("，。；、.）)]】")
        return cleaned

    @staticmethod
    def _activity_normalize_link_items(links: Any) -> list[dict[str, str]]:
        if isinstance(links, str):
            raw_items = []
            for line in links.splitlines():
                line = line.strip(" -\t")
                if not line:
                    continue
                match = re.search(r"(https?://\S+)", line)
                if not match:
                    continue
                url = ActivityDailyMixin._activity_canonical_link_url(match.group(1))
                label = line[: match.start()].rstrip("：: -\t") or "来源链接"
                raw_items.append({"label": label, "url": url})
        elif isinstance(links, list):
            raw_items = links
        else:
            raw_items = []
        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in raw_items:
            if isinstance(item, dict):
                label = str(item.get("label") or "来源链接").strip() or "来源链接"
                url = ActivityDailyMixin._activity_canonical_link_url(str(item.get("url") or ""))
            else:
                text = str(item or "").strip()
                match = re.search(r"(https?://\S+)", text)
                if not match:
                    continue
                url = ActivityDailyMixin._activity_canonical_link_url(match.group(1))
                label = text[: match.start()].rstrip("：: -\t") or "来源链接"
            if not url:
                continue
            if url in seen:
                continue
            seen.add(url)
            normalized.append({"label": label, "url": url})
        return normalized

    def handle_日程(self, message: Message) -> TaskResult:
        hierarchy_result = self._maybe_handle_daily_hierarchy_records(message, "日程")
        if hierarchy_result is not None:
            return hierarchy_result
        extracted = self._extract_daily_task_with_llm(message, "日程")
        if not extracted.get("ok"):
            return self._daily_task_parse_failure(message, extracted, "日程")
        due_at = extracted["due_at"]
        remind_at = extracted.get("remind_at") or self._default_daily_remind_at("日程", due_at)
        display_time = format_display_time(due_at)
        reminder_time = format_display_time(remind_at)
        extra = {
            "due_at": display_time,
            "remind_at": reminder_time,
            "calendar_provider": "feishu",
            "llm_confidence": extracted.get("confidence", 0),
            "llm_evidence": extracted.get("evidence", ""),
        }
        sections = [
            ("原始内容", message.raw_text),
            (
                "LLM解析结果",
                f"- 日程时间：{display_time}\n"
                f"- 提醒/出发时间：{reminder_time}\n"
                f"- 置信度：{extracted.get('confidence', 0)}\n"
                f"- 证据：{extracted.get('evidence', '')}",
            ),
            ("执行状态", "- 飞书日历：待创建\n- 多维表格：待写入")
        ]
        entry = self.archive_service.save_archive(message, f"日程：{extracted['title']}", sections, extra)
        reminder = self.reminder_service.add(
            kind="日程",
            title=extracted["title"],
            text=message.body,
            due_at=due_at,
            remind_at=remind_at,
            source=message.source,
            ref_id=entry.frontmatter["id"],
            local_path=entry.local_path,
        )
        fs = {"doc": ""}
        if reminder.get("ok"):
            calendar = (reminder.get("data") or {}).get("calendar") or {}
            extra["feishu_reminder"] = "created"
            if calendar.get("ok"):
                extra["feishu_calendar_event"] = calendar.get("event_id", "")
                table_url = (reminder.get("data") or {}).get("table_url") or self._configured_bitable_url("日程")
                reply = f"已创建飞书日历事件\n时间：{display_time}\n提醒时间：{reminder_time}\n多维表格：{table_url or '已写入'}\niPhone：飞书日历/提醒会通知"
                if calendar.get("app_link"):
                    reply += f"\n日历链接：{calendar.get('app_link')}"
            else:
                reason = calendar.get("error") or calendar.get("reason") or "unknown"
                table_url = (reminder.get("data") or {}).get("table_url") or self._configured_bitable_url("日程")
                reply = f"已写入多维表格\n多维表格：{table_url or '已写入'}\n但飞书日历事件创建失败\n时间：{display_time}\n提醒时间：{reminder_time}\n原因：{reason}"
            ok = True
            status = "archived"
        else:
            reply = "日程已本地归档，但飞书日历/提醒写入失败"
            if reminder.get("error"):
                reply += f"\n错误：{reminder.get('error')}"
            ok = False
            status = "pending_manual"
        return TaskResult(ok=ok, status=status, reply=reply, task_id=entry.frontmatter["id"], local_path=entry.local_path, feishu_doc=fs.get("doc", ""), extra=extra)

    def handle_待办(self, message: Message) -> TaskResult:
        hierarchy_result = self._maybe_handle_daily_hierarchy_records(message, "待办")
        if hierarchy_result is not None:
            return hierarchy_result
        todo_intake = self._extract_todo_intake_with_llm(message)
        if not todo_intake.get("ok"):
            return self._todo_intake_failure(message, todo_intake)
        explicit_checklist_tree = self._extract_explicit_markdown_checklist_tree(message.body)
        if explicit_checklist_tree and todo_intake.get("mode") in {"checklist_only", "structured_checklist"}:
            reason = str(todo_intake.get("reason") or "").strip()
            todo_intake = {
                **todo_intake,
                "mode": "structured_checklist",
                "items": [],
                "checklist_tree": explicit_checklist_tree,
                "reason": (f"{reason}；" if reason else "") + "用户原文包含缩进 checkbox，按显式层级保留父子待办。",
            }
        if todo_intake.get("mode") == "checklist_only":
            todo_intake = self._maybe_promote_todo_intake_hierarchy(message, todo_intake)
        if todo_intake.get("mode") == "checklist_only":
            try:
                checklist_items = self._todo_items_with_explicit_links(todo_intake["items"], message.body)
                checklist = self.obsidian_daily_checklist_service.append_checklist(
                    text=message.body,
                    now=message.created_at,
                    checklist_tree=[{"text": item, "children": []} for item in checklist_items],
                )
            except ValueError as exc:
                return self._todo_intake_failure(
                    message,
                    {
                        "error_code": "DAILY_TODO_OBSIDIAN_WRITE_FAILED",
                        "reason": f"Obsidian checklist 写入失败：{exc}",
                        "missing_fields": ["obsidian_write"],
                    },
                )
            sections = [
                ("原始内容", message.raw_text),
                ("LLM清单分流", json.dumps({key: todo_intake.get(key) for key in ("mode", "items", "confidence", "evidence", "reason")}, ensure_ascii=False, indent=2, default=str)),
                ("Obsidian清单", "\n".join(checklist.markdown_lines)),
            ]
            entry = self.archive_service.save_archive(
                message,
                f"待办清单：{checklist.target_date:%Y%m%d}",
                sections,
                {
                    "obsidian_path": checklist.path,
                    "target_date": f"{checklist.target_date:%Y-%m-%d}",
                    "feishu_synced": False,
                    "sync_mode": "obsidian_checklist_only",
                    "llm_confidence": todo_intake.get("confidence", 0),
                    "llm_evidence": todo_intake.get("evidence", ""),
                },
            )
            reply = "\n".join(
                [
                    "已写入 Obsidian 周记 # 待办",
                    f"日期：{checklist.target_date:%Y-%m-%d}",
                    f"路径：{checklist.path}",
                    "",
                    "新增：",
                    *checklist.markdown_lines,
                ]
            )
            return TaskResult(ok=True, status="obsidian_checklist_archived", reply=reply, task_id=entry.frontmatter["id"], local_path=entry.local_path, extra={"obsidian_path": checklist.path})
        if todo_intake.get("mode") == "structured_checklist":
            return self._write_todo_structured_checklist(message, todo_intake)
        extracted = self._extract_daily_task_with_llm(message, "待办")
        if not extracted.get("ok"):
            return self._daily_task_parse_failure(message, extracted, "待办")
        due_at = extracted["due_at"]
        remind_at = extracted.get("remind_at") or self._default_daily_remind_at("待办", due_at)
        sections = [
            ("原始内容", message.raw_text),
            (
                "LLM解析结果",
                f"- 截止/事项时间：{format_display_time(due_at)}\n"
                f"- 提醒时间：{format_display_time(remind_at)}\n"
                f"- 置信度：{extracted.get('confidence', 0)}\n"
                f"- 证据：{extracted.get('evidence', '')}",
            ),
        ]
        entry = self.archive_service.save_archive(
            message,
            f"待办：{extracted['title']}",
            sections,
            {
                "due_at": format_display_time(due_at),
                "remind_at": format_display_time(remind_at),
                "llm_confidence": extracted.get("confidence", 0),
                "llm_evidence": extracted.get("evidence", ""),
            },
        )
        reminder = self.reminder_service.add(
            kind="待办",
            title=extracted["title"],
            text=message.body,
            due_at=due_at,
            remind_at=remind_at,
            source=message.source,
            ref_id=entry.frontmatter["id"],
            local_path=entry.local_path,
        )
        fs = {"doc": ""}
        extra: dict[str, Any] = {}
        if reminder.get("ok"):
            table_url = (reminder.get("data") or {}).get("table_url") or self._configured_bitable_url("待办")
            record_id = str((reminder.get("data") or {}).get("record_id") or "").strip()
            checklist_path = ""
            if record_id:
                checklist = self.obsidian_daily_checklist_service.append_checklist(
                    text=message.body,
                    now=message.created_at,
                    checklist_tree=[{"text": extracted["title"], "children": []}],
                    feishu_record=record_id,
                )
                checklist_path = checklist.path
            reply = (
                "已创建飞书待办提醒，并写入 Obsidian 周记 # 待办\n"
                f"事项时间：{format_display_time(due_at)}\n"
                f"提醒时间：{format_display_time(remind_at)}\n"
                f"多维表格：{table_url or '已写入'}\n"
                f"Obsidian：{checklist_path or '未写入'}\n"
                "iPhone：提前 30 分钟由飞书 Bot 私聊提醒"
            )
            ok = True
            status = "archived"
            extra = {"feishu_record_id": record_id, "obsidian_path": checklist_path}
        else:
            checklist = self.obsidian_daily_checklist_service.append_checklist(
                text=message.body,
                now=message.created_at,
                checklist_tree=[{"text": extracted["title"], "children": []}],
            )
            reply = (
                "待办已本地归档，并写入 Obsidian 周记 # 待办；飞书提醒写入失败\n"
                f"本地路径：{entry.local_path}\n"
                f"Obsidian：{checklist.path}"
            )
            if reminder.get("error"):
                reply += f"\n错误：{reminder.get('error')}"
            ok = True
            status = "archived_with_feishu_warning"
            extra = {"feishu_warning": reminder, "obsidian_path": checklist.path}
        return TaskResult(ok=ok, status=status, reply=reply, task_id=entry.frontmatter["id"], local_path=entry.local_path, feishu_doc=fs.get("doc", ""), extra=extra)

    def _write_todo_structured_checklist(self, message: Message, todo_intake: dict[str, Any]) -> TaskResult:
        checklist_tree = todo_intake["checklist_tree"]
        obsidian_checklist_tree = self._todo_tree_with_explicit_links(checklist_tree, message.body)
        try:
            checklist = self.obsidian_daily_checklist_service.append_checklist(
                text=message.body,
                now=message.created_at,
                checklist_tree=obsidian_checklist_tree,
            )
        except ValueError as exc:
            return self._todo_intake_failure(
                message,
                {
                    "error_code": "DAILY_TODO_OBSIDIAN_WRITE_FAILED",
                    "reason": f"Obsidian checklist 写入失败：{exc}",
                    "missing_fields": ["obsidian_write"],
                },
            )

        sections = [
            ("原始内容", message.raw_text),
            ("LLM结构清单分流", json.dumps({key: todo_intake.get(key) for key in ("mode", "checklist_tree", "confidence", "evidence", "reason")}, ensure_ascii=False, indent=2, default=str)),
            ("Obsidian清单", "\n".join(checklist.markdown_lines)),
        ]
        entry = self.archive_service.save_archive(
            message,
            f"待办结构清单：{checklist.target_date:%Y%m%d}",
            sections,
            {
                "record_kind": "todo_structured_checklist",
                "obsidian_path": checklist.path,
                "target_date": f"{checklist.target_date:%Y-%m-%d}",
                "feishu_synced": False,
                "sync_mode": "feishu_parent_child_and_obsidian_checklist",
                "feishu_sync_status": "attempted_after_archive",
                "llm_confidence": todo_intake.get("confidence", 0),
                "llm_evidence": todo_intake.get("evidence", ""),
            },
        )

        record_entries: list[dict[str, Any]] = []

        def write_node(node: dict[str, Any], *, parent_record_id: str = "", ref_suffix: str = "", depth: int = 0) -> None:
            title = str(node.get("text") or "").strip()
            children = node.get("children")
            child_nodes = children if isinstance(children, list) else []
            if not title:
                return
            extra_fields: dict[str, Any] = {
                "类型说明": "待办子记录" if parent_record_id else "待办父记录",
                "未填写原因": "截止/提醒时间：未填写，原因：原文是结构化待办清单，没有明确截止或提醒时间。",
            }
            if parent_record_id:
                extra_fields["父记录"] = parent_record_id
            result = self.reminder_service.add(
                kind="待办",
                title=title,
                text="\n".join(
                    line
                    for line in [
                        f"父待办记录ID：{parent_record_id}" if parent_record_id else "",
                        f"原始待办：{message.body}",
                    ]
                    if line
                ),
                due_at=None,
                remind_at=None,
                source=message.source,
                ref_id=f"{entry.frontmatter['id']}-{ref_suffix}",
                local_path=entry.local_path,
                extra_fields=extra_fields,
                omit_management_fields=True,
            )
            record_id = str((result.get("data") or {}).get("record_id") or "").strip()
            record_entries.append({"title": title, "depth": depth, "result": result, "record_id": record_id, "parent_record_id": parent_record_id})
            if not result.get("ok"):
                return
            effective_parent_id = record_id or f"{entry.frontmatter['id']}-{ref_suffix}"
            for index, child in enumerate(child_nodes, start=1):
                write_node(child, parent_record_id=effective_parent_id, ref_suffix=f"{ref_suffix}-{index}", depth=depth + 1)

        for index, root in enumerate(checklist_tree, start=1):
            write_node(root, ref_suffix=str(index))

        failed_records = [item for item in record_entries if not item["result"].get("ok")]
        table_url = next((str((item["result"].get("data") or {}).get("table_url") or "").strip() for item in record_entries if item["result"].get("ok")), "") or self._configured_bitable_url("待办")
        record_lines = []
        for item in record_entries:
            prefix = "已创建" if item["result"].get("ok") else "创建失败"
            indent = "  " * int(item["depth"])
            record_id = item["record_id"] or "无记录ID"
            error = str(item["result"].get("error") or "").strip()
            error_suffix = f"｜错误：{error[-500:]}" if error and not item["result"].get("ok") else ""
            record_lines.append(f"{indent}- {prefix}：{item['title']}（{record_id}）{error_suffix}")

        first_record_id = next((item["record_id"] for item in record_entries if item.get("record_id")), entry.frontmatter["id"])
        ok = bool(record_entries) and not failed_records
        archive_updates: dict[str, Any] = {
            "feishu_synced": ok,
            "feishu_sync_status": "succeeded" if ok else "failed",
            "feishu_bitable_url": table_url,
            "feishu_record_ids": [item["record_id"] for item in record_entries if item.get("record_id")],
        }
        if ok:
            archive_updates["feishu_parent_record_id"] = first_record_id
        else:
            archive_updates["feishu_failed_record_ids"] = [
                item["record_id"] or item["parent_record_id"]
                for item in failed_records
                if item["record_id"] or item["parent_record_id"]
            ]
        entry = self.archive_service.update_frontmatter(entry.local_path, archive_updates)
        headline = "已创建飞书父子待办，并写入 Obsidian 缩进清单" if ok else "飞书父子待办创建失败；已写入 Obsidian 缩进清单"
        reply_lines = [
            headline,
            f"日期：{checklist.target_date:%Y-%m-%d}",
            f"Obsidian：{checklist.path}",
            "飞书记录：",
            *record_lines,
            f"多维表格：{table_url or '未写入'}",
        ]
        if failed_records:
            reply_lines.append("说明：飞书失败时表格里不会出现对应记录；以上错误是底层写入返回。")
        reply = "\n".join(reply_lines)
        warning = "飞书父子待办记录创建失败；Obsidian 缩进清单已写入，需稍后重试飞书同步。" if failed_records else ""
        return TaskResult(
            ok=True,
            status="structured_checklist_archived" if ok else "structured_checklist_archived_with_feishu_warning",
            reply=reply,
            task_id=first_record_id,
            local_path=entry.local_path,
            feishu_doc="",
            extra={"todo_intake": todo_intake, "obsidian_path": checklist.path, "feishu_records": record_entries, **({"warning": warning} if warning else {})},
        )

    @staticmethod
    def _todo_items_with_explicit_links(items: list[str], text: str) -> list[str]:
        urls = ActivityDailyMixin._extract_explicit_urls(text)
        if not urls:
            return items
        extra_links = " ".join(f"[原链接{i + 2}]({url})" for i, url in enumerate(urls[1:3]))
        updated: list[str] = []
        for item in items:
            item_text = str(item or "").strip()
            if not item_text:
                continue
            if any(url in item_text for url in urls):
                updated.append(item_text)
            else:
                linked_item = f"[{ActivityDailyMixin._markdown_link_label(item_text)}]({urls[0]})"
                updated.append(f"{linked_item} {extra_links}".strip())
        return updated

    @staticmethod
    def _todo_tree_with_explicit_links(checklist_tree: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
        urls = ActivityDailyMixin._extract_explicit_urls(text)
        if not urls or not checklist_tree:
            return checklist_tree
        copied = json.loads(json.dumps(checklist_tree, ensure_ascii=False))
        root_text = str(copied[0].get("text") or "").strip()
        if root_text and not any(url in root_text for url in urls):
            extra_links = " ".join(f"[原链接{i + 2}]({url})" for i, url in enumerate(urls[1:3]))
            copied[0]["text"] = f"[{ActivityDailyMixin._markdown_link_label(root_text)}]({urls[0]}) {extra_links}".strip()
        return copied

    @staticmethod
    def _extract_explicit_urls(text: str) -> list[str]:
        urls: list[str] = []
        for match in re.finditer(r"https?://[^\s<>\]\)\"'，。；、]+", str(text or "")):
            url = match.group(0).rstrip(".,;:!?，。；：！？")
            if url and url not in urls:
                urls.append(url)
        return urls

    @staticmethod
    def _markdown_link_label(text: str) -> str:
        return str(text or "").replace("[", "\\[").replace("]", "\\]")

    @classmethod
    def _extract_explicit_markdown_checklist_tree(cls, text: str) -> list[dict[str, Any]]:
        rows: list[tuple[int, str]] = []
        for line in str(text or "").splitlines():
            match = re.match(r"^(?P<indent>[ \t]*)[-*]\s+\[[ xX]\]\s+(?P<text>.+?)\s*$", line)
            if not match:
                continue
            item_text = re.sub(r"\s+", " ", match.group("text")).strip()
            if not item_text:
                continue
            indent = len(match.group("indent").replace("\t", "  "))
            rows.append((indent, item_text))
        if not rows:
            return []

        roots: list[dict[str, Any]] = []
        stack: list[tuple[int, dict[str, Any]]] = []
        for indent, item_text in rows:
            node = {"text": item_text, "children": []}
            while stack and indent <= stack[-1][0]:
                stack.pop()
            if stack:
                stack[-1][1].setdefault("children", []).append(node)
            else:
                roots.append(node)
            stack.append((indent, node))

        normalized = cls._normalize_todo_checklist_tree(roots)
        return normalized if any(root.get("children") for root in normalized) else []

    def _maybe_handle_daily_hierarchy_records(self, message: Message, expected_type: str) -> TaskResult | None:
        if not self._should_attempt_hierarchy_extraction(message):
            return None
        extracted = self._extract_hierarchy_records_with_llm(message, expected_type)
        if extracted.get("single"):
            return None
        if not extracted.get("ok"):
            reason = str(extracted.get("reason") or "LLM未能清洗出父子层级").strip()
            missing = "、".join(extracted.get("missing_fields") or []) or "父子层级字段"
            reply = (
                "层级结构没有创建：系统解析错误。\n"
                f"缺少/不确定：{missing}\n"
                f"原因：{reason}\n"
                "这不是用户信息缺失；需要修正清洗器后重试。"
            )
            return TaskResult(ok=False, status="parser_error", reply=reply, task_id="", local_path="", feishu_doc="", extra={"hierarchy_parse": extracted})
        return self._write_daily_hierarchy_records(message, extracted)

    def _should_attempt_hierarchy_extraction(self, message: Message) -> bool:
        text = message.body or message.raw_text
        compact = re.sub(r"\s+", "", text)
        if len(compact) < 120:
            return False
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        score = 0
        if len(lines) >= 4:
            score += 2
        section_markers = re.findall(r"(?:^|[。\n；;])\s*(?:[一二三四五六七八九十]+|[0-9]+)\s*[、.．]", text)
        if re.search(r"(?m)^\s*(?:[一二三四五六七八九十]+|[0-9]+)\s*[、.．]", text) or len(section_markers) >= 2:
            score += 2
        if re.search(r"(?m)^【[^】]{4,80}】", text):
            score += 1
        if len(re.findall(r"https?://", text)) >= 1:
            score += 1
        if text.count("：") + text.count(":") >= 4:
            score += 1
        if len(list(self._EXPLICIT_CN_DATETIME_RE.finditer(text))) >= 2:
            score += 1
        return score >= 2

    def _write_daily_hierarchy_records(self, message: Message, extracted: dict[str, Any]) -> TaskResult:
        parent = extracted["parent"]
        children = extracted["children"]
        sections = [
            ("原始内容", message.raw_text),
            ("父记录", json.dumps(parent, ensure_ascii=False, indent=2, default=str)),
            ("子记录", json.dumps(children, ensure_ascii=False, indent=2, default=str)),
        ]
        entry = self.archive_service.save_archive(
            message,
            f"层级：{parent['title']}",
            sections,
            {
                "record_kind": "daily_hierarchy_parent_children",
                "llm_confidence": extracted.get("confidence", 0),
                "llm_evidence": extracted.get("evidence", ""),
            },
        )
        parent_due_at, parent_remind_at = self._hierarchy_parent_times(children)
        parent_result = self.reminder_service.add(
            kind="日程",
            title=parent["title"],
            text=parent["summary"] or message.body,
            due_at=parent_due_at,
            remind_at=parent_remind_at,
            source=message.source,
            ref_id=entry.frontmatter["id"],
            local_path=entry.local_path,
            extra_fields=self._daily_hierarchy_parent_extra_fields(parent),
        )
        if not parent_result.get("ok"):
            reply = "父记录创建失败"
            if parent_result.get("error"):
                reply += f"\n错误：{parent_result.get('error')}"
            return TaskResult(ok=False, status="parent_record_failed", reply=reply, task_id=entry.frontmatter["id"], local_path=entry.local_path, feishu_doc="", extra={"hierarchy_parse": extracted})

        parent_record_id = str((parent_result.get("data") or {}).get("record_id") or entry.frontmatter["id"])
        child_results: list[dict[str, Any]] = []
        for index, child in enumerate(children, start=1):
            child_type = child["type"]
            due_at = child["due_at"]
            remind_at = child.get("remind_at") or self._default_daily_remind_at(child_type, due_at)
            extra_fields = self._hierarchy_child_extra_fields(parent_record_id, child)
            result = self.reminder_service.add(
                kind=child_type,
                title=child["title"],
                text=child.get("description") or child["title"],
                due_at=due_at,
                remind_at=remind_at,
                source=message.source,
                ref_id=f"{entry.frontmatter['id']}-{index}",
                local_path=entry.local_path,
                extra_fields=extra_fields,
                omit_management_fields=True,
            )
            child_results.append({"child": child, "result": result})

        failed_children = [item for item in child_results if not item["result"].get("ok")]
        table_url = (parent_result.get("data") or {}).get("table_url") or self._configured_bitable_url("日程")
        child_lines = []
        for item in child_results:
            child = item["child"]
            result = item["result"]
            prefix = "已创建" if result.get("ok") else "创建失败"
            child_lines.append(f"- {prefix} {child['type']}：{child['title']}｜{format_display_time(child['due_at'])}")
        reply = "\n".join(
            [
                "已拆出层级结构",
                f"父记录：{parent['title']}（{parent_record_id}）",
                "子记录：",
                *child_lines,
                f"多维表格：{table_url or '已写入'}",
            ]
        )
        ok = not failed_children
        return TaskResult(
            ok=ok,
            status="archived" if ok else "partial_failed",
            reply=reply,
            task_id=parent_record_id,
            local_path=entry.local_path,
            feishu_doc="",
            extra={"hierarchy_parse": extracted, "child_results": child_results},
        )

    def _extract_hierarchy_records_with_llm(self, message: Message, expected_type: str) -> dict[str, Any]:
        user_content = json.dumps(
            {
                "now": message.created_at.astimezone(ZoneInfo(self.timezone)).isoformat(timespec="seconds"),
                "timezone": self.timezone,
                "expected_type": expected_type,
                "text": message.body,
                "raw_text": message.raw_text,
                "recent_conversation_context": self._conversation_context_prompt(message),
            },
            ensure_ascii=False,
            indent=2,
        )
        try:
            result = self.content_flow_client._call_profile_provider_json(
                "daily_hierarchy_records_extraction",
                DAILY_HIERARCHY_RECORDS_PROMPT,
                user_content,
                "Daily层级结构清洗",
            )
        except Exception as exc:
            return {"ok": False, "reason": f"LLM清洗异常：{exc}", "missing_fields": ["llm_result"]}
        return self._normalize_hierarchy_records(result)

    def _normalize_hierarchy_records(self, result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"ok": False, "reason": "LLM未返回对象", "missing_fields": ["llm_result"]}
        status = str(result.get("status") or "").strip().lower()
        if status == "single":
            return {
                "ok": False,
                "single": True,
                "confidence": self._float_confidence(result.get("confidence")),
                "evidence": str(result.get("evidence") or "").strip(),
                "reason": str(result.get("reason") or "LLM判断为单条事项").strip(),
            }
        if status == "done":
            status = "hierarchy"
        if status != "hierarchy":
            return {
                "ok": False,
                "reason": str(result.get("reason") or "LLM清洗未完成"),
                "missing_fields": [str(item) for item in result.get("missing_fields") or ["hierarchy_records"]],
            }
        confidence = self._float_confidence(result.get("confidence"))
        parent_raw = result.get("parent") if isinstance(result.get("parent"), dict) else {}
        children_raw = result.get("children") if isinstance(result.get("children"), list) else []
        missing_fields = [str(item).strip() for item in result.get("missing_fields") or [] if str(item).strip()]
        parent = self._normalize_hierarchy_parent(parent_raw)
        if not parent["title"]:
            missing_fields.append("parent.title")
        children = []
        for item in children_raw:
            if isinstance(item, dict):
                child = self._normalize_hierarchy_child(item)
                children.append(child)
        if not children:
            missing_fields.append("children")
        for index, child in enumerate(children, start=1):
            if child["type"] not in {"日程", "待办", "提醒"}:
                missing_fields.append(f"children[{index}].type")
            if not child["title"]:
                missing_fields.append(f"children[{index}].title")
            if not child["due_at"]:
                missing_fields.append(f"children[{index}].due_at")
            if child["location"] and not self._location_has_area_prefix(child["location"]):
                missing_fields.append(f"children[{index}].location_parts")
        if confidence < 0.75:
            return {
                "ok": False,
                "reason": str(result.get("reason") or "LLM置信度不足"),
                "confidence": confidence,
                "missing_fields": sorted(set(missing_fields or ["confidence"])),
                "evidence": str(result.get("evidence") or "").strip(),
            }
        if missing_fields:
            return {
                "ok": False,
                "reason": str(result.get("reason") or "缺少父子层级必要字段"),
                "confidence": confidence,
                "missing_fields": sorted(set(missing_fields)),
                "evidence": str(result.get("evidence") or "").strip(),
            }
        return {
            "ok": True,
            "confidence": confidence,
            "parent": parent,
            "children": children,
            "evidence": str(result.get("evidence") or "").strip(),
            "reason": str(result.get("reason") or "").strip(),
        }

    def _normalize_hierarchy_parent(self, parent: dict[str, Any]) -> dict[str, Any]:
        fields_raw = parent.get("fields") if isinstance(parent.get("fields"), dict) else {}
        fields = self._clean_hierarchy_fields(
            fields_raw,
            allowed={
                "地点",
                "类型说明",
                "说明",
                "来源链接",
                "未填写原因",
            },
        )
        location_parts = self._clean_location_parts(
            parent.get("location_parts")
            or parent.get("地点拆解JSON")
            or fields_raw.get("地点拆解JSON")
            or fields_raw.get("地点拆解")
        )
        location = self._format_location_for_feishu(str(parent.get("location") or fields_raw.get("地点") or ""), location_parts)
        if location:
            fields["地点"] = location
        if missing_reason := self._clean_missing_reasons(parent.get("missing_reasons") or fields_raw.get("未填写原因")):
            fields["未填写原因"] = missing_reason
        summary = str(parent.get("summary") or "").strip()
        if summary:
            fields["类型说明"] = summary
        return {
            "type": "日程",
            "title": self._clean_hierarchy_title(parent.get("title")),
            "summary": summary,
            "fields": fields,
        }

    def _normalize_hierarchy_child(self, child: dict[str, Any]) -> dict[str, Any]:
        due_at = self._parse_llm_datetime(child.get("due_at"))
        remind_at = self._parse_llm_datetime(child.get("remind_at"))
        fields_raw = child.get("fields") if isinstance(child.get("fields"), dict) else {}
        location = str(child.get("location") or fields_raw.get("地点") or "").strip()
        location_parts = self._clean_location_parts(
            child.get("location_parts")
            or child.get("地点拆解JSON")
            or fields_raw.get("地点拆解JSON")
            or fields_raw.get("地点拆解")
        )
        location = self._format_location_for_feishu(location, location_parts)
        return {
            "type": str(child.get("type") or "").strip(),
            "title": self._clean_hierarchy_title(child.get("title")),
            "due_at": due_at,
            "remind_at": remind_at,
            "location": location,
            "location_parts": location_parts,
            "source_link": self._first_hierarchy_url(child.get("source_link")),
            "description": str(fields_raw.get("说明") or fields_raw.get("类型说明") or child.get("description") or "").strip(),
            "missing_reason": self._clean_missing_reasons(child.get("missing_reasons") or fields_raw.get("未填写原因")),
            "fields": self._clean_hierarchy_fields(
                fields_raw,
                allowed={"事项类型", "类型说明", "说明", "参与方式", "提交要求", "来源链接", "未填写原因"},
            ),
        }

    @staticmethod
    def _clean_hierarchy_title(value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip(" #【】[]()（）\n\t")
        text = re.sub(r"^(关于举行|关于|举行)", "", text).strip()
        return text[:80]

    @staticmethod
    def _clean_hierarchy_fields(fields: dict[str, Any], *, allowed: set[str]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for key, value in fields.items():
            name = str(key or "").strip()
            if name not in allowed:
                continue
            if isinstance(value, (dict, list)):
                cleaned[name] = value
                continue
            text = re.sub(r"\s+", " ", str(value or "")).strip(" \n\t[玫瑰]")
            if text:
                cleaned[name] = text
        return cleaned

    @staticmethod
    def _first_hierarchy_url(*values: Any) -> str:
        for value in values:
            match = re.search(r"https?://[^\s<>\"]+", str(value or ""))
            if match:
                return match.group(0).rstrip("，。；;、,.!?！？)]）】》\"'")
        return ""

    def _hierarchy_parent_times(self, children: list[dict[str, Any]]) -> tuple[datetime, datetime]:
        schedule_children = [child for child in children if child.get("type") == "日程" and child.get("due_at")]
        timing_children = schedule_children or [child for child in children if child.get("due_at")]
        due_times = [child["due_at"] for child in timing_children]
        due_at = min(due_times)
        remind_times = [
            child.get("remind_at") or self._default_daily_remind_at(child["type"], child["due_at"])
            for child in timing_children
            if child.get("due_at")
        ]
        remind_at = min(remind_times) if remind_times else due_at
        return due_at, remind_at

    @staticmethod
    def _daily_hierarchy_parent_extra_fields(parent: dict[str, Any]) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        for name in ("地点", "类型说明", "来源链接", "未填写原因"):
            value = (parent.get("fields") or {}).get(name)
            if value not in (None, ""):
                extra[name] = value
        return extra

    @staticmethod
    def _hierarchy_child_extra_fields(parent_record_id: str, child: dict[str, Any]) -> dict[str, Any]:
        extra: dict[str, Any] = {
            "父记录": parent_record_id,
        }
        if child.get("location"):
            extra["地点"] = child["location"]
        if child.get("source_link"):
            extra["来源链接"] = child["source_link"]
        if child.get("description"):
            extra["类型说明"] = child["description"]
        if child.get("missing_reason"):
            extra["未填写原因"] = child["missing_reason"]
        return extra

    @staticmethod
    def _clean_location_parts(value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        cleaned: dict[str, str] = {}
        for key, raw_value in value.items():
            name = str(key or "").strip()
            if not name:
                continue
            text = re.sub(r"\s+", " ", str(raw_value or "")).strip()
            if text:
                cleaned[name] = text
        return cleaned

    @staticmethod
    def _format_location_for_feishu(location: str, parts: dict[str, str]) -> str:
        if not parts:
            return ActivityDailyMixin._normalize_formatted_location_text(re.sub(r"\s+", " ", location or "").strip())
        city = parts.get("城市", "")
        province = parts.get("省份") or parts.get("省") or ActivityDailyMixin._province_for_city(city)
        ordered = [
            ActivityDailyMixin._normalize_province_part(province),
            ActivityDailyMixin._normalize_location_part(city, "市"),
            ActivityDailyMixin._normalize_location_part(parts.get("区域", ""), ""),
            parts.get("校区/园区", ""),
            parts.get("场馆", ""),
            parts.get("楼栋", ""),
            parts.get("楼层", ""),
            parts.get("房间", ""),
            parts.get("地址补充", ""),
        ]
        segments: list[str] = []
        for raw in ordered:
            text = re.sub(r"\s+", " ", str(raw or "")).strip()
            if text and text not in segments:
                segments.append(text)
        clean_location = re.sub(r"\s+", " ", location or "").strip()
        specific_parts = [parts.get(name, "") for name in ("区域", "校区/园区", "场馆", "楼栋", "楼层", "房间", "地址补充")]
        compact_location = re.sub(r"\s+", "", clean_location)
        compact_segments = "".join(re.sub(r"\s+", "", item) for item in segments)
        has_specific_overlap = any(
            str(item or "").strip() and re.sub(r"\s+", "", str(item).strip()) in compact_location
            for item in specific_parts
        )
        has_location_overlap = bool(compact_location and compact_segments and (compact_location in compact_segments or compact_segments in compact_location))
        if clean_location and not has_specific_overlap and not has_location_overlap and not any(clean_location == item or clean_location in item for item in segments):
            segments.append(clean_location)
        return ActivityDailyMixin._normalize_formatted_location_text(" ".join(segments).strip())

    @staticmethod
    def _location_has_area_prefix(value: str) -> bool:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text:
            return True
        has_direct_city = bool(re.search(r"(?:北京|上海|天津|重庆)市", text))
        has_city = has_direct_city or bool(re.search(r"[\u4e00-\u9fff]{2,12}市", text))
        has_province = has_direct_city or bool(re.search(r"[\u4e00-\u9fff]{2,12}(?:省|自治区|特别行政区)", text))
        has_area = bool(re.search(r"[\u4e00-\u9fff]{1,12}(?:区|县|大学城|校区|园区)", text))
        return has_city and (has_province or has_area)

    @staticmethod
    def _normalize_formatted_location_text(value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        replacements = {
            "广东 深圳市": "广东省 深圳市",
            "广东 广州": "广东省 广州市",
            "广东省 广州 ": "广东省 广州市 ",
            "广东 深圳": "广东省 深圳市",
            "广东省 深圳 ": "广东省 深圳市 ",
            "广东 珠海": "广东省 珠海市",
            "广东省 珠海 ": "广东省 珠海市 ",
            "广东省 深圳市 教室 学思楼": "广东省 深圳市 学思楼",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        text = text.replace("深圳市市", "深圳市").replace("广州市市", "广州市").replace("珠海市市", "珠海市")
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _normalize_location_part(value: str, suffix: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text or not suffix or text.endswith(("省", "市", "区", "县", "州", "盟")):
            return text
        return f"{text}{suffix}"

    @staticmethod
    def _normalize_province_part(value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text or text.endswith(("省", "市", "自治区", "特别行政区")):
            return text
        return f"{text}省"

    @staticmethod
    def _province_for_city(city: str) -> str:
        compact = re.sub(r"\s+", "", str(city or "")).removesuffix("市")
        return {
            "深圳": "广东省",
            "广州": "广东省",
            "珠海": "广东省",
            "北京": "北京市",
            "上海": "上海市",
            "天津": "天津市",
            "重庆": "重庆市",
        }.get(compact, "")

    @staticmethod
    def _clean_missing_reasons(value: Any) -> str:
        if isinstance(value, dict):
            lines = []
            for key, raw in value.items():
                field = str(key or "").strip()
                reason = re.sub(r"\s+", " ", str(raw or "")).strip()
                if field and reason:
                    lines.append(f"{field}：未填写，原因：{reason}")
            return "；".join(lines)
        if isinstance(value, list):
            return "；".join(re.sub(r"\s+", " ", str(item or "")).strip() for item in value if str(item or "").strip())
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def _extract_daily_task_with_llm(self, message: Message, expected_type: str) -> dict[str, Any]:
        user_content = json.dumps(
            {
                "now": message.created_at.astimezone(ZoneInfo(self.timezone)).isoformat(timespec="seconds"),
                "timezone": self.timezone,
                "expected_type": expected_type,
                "text": message.body,
                "raw_text": message.raw_text,
                "recent_conversation_context": self._conversation_context_prompt(message),
            },
            ensure_ascii=False,
            indent=2,
        )
        try:
            result = self.content_flow_client._call_profile_provider_json(
                "daily_task_extraction",
                DAILY_TASK_EXTRACTION_PROMPT,
                user_content,
                "日程待办自然语言抽取",
            )
        except Exception as exc:
            return {"ok": False, "reason": f"LLM抽取异常：{exc}", "missing_fields": ["llm_result"]}
        return self._normalize_daily_task_extraction(result, expected_type, message)

    def _extract_todo_intake_with_llm(self, message: Message) -> dict[str, Any]:
        user_content = json.dumps(
            {
                "now": message.created_at.astimezone(ZoneInfo(self.timezone)).isoformat(timespec="seconds"),
                "timezone": self.timezone,
                "text": message.body,
                "raw_text": message.raw_text,
                "recent_conversation_context": self._conversation_context_prompt(message),
            },
            ensure_ascii=False,
            indent=2,
        )
        try:
            result = self.content_flow_client._call_profile_provider_json(
                "daily_task_extraction",
                DAILY_TODO_INTAKE_PROMPT,
                user_content,
                "待办清单与提醒分流",
            )
        except Exception as exc:
            if is_model_capacity_failure(exc):
                return {
                    "ok": False,
                    "error_code": "DAILY_LLM_MODEL_AT_CAPACITY",
                    "reason": "模型当前容量已满，待办未创建、未落盘。",
                    "detail": model_capacity_failure_detail(exc),
                    "suggested_action": "请稍后直接重试原消息。",
                    "missing_fields": ["llm_result"],
                }
            return {"ok": False, "reason": f"LLM分流异常：{exc}", "missing_fields": ["llm_result"]}
        return self._normalize_todo_intake(result)

    def _normalize_todo_intake(self, result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"ok": False, "reason": "LLM未返回对象", "missing_fields": ["llm_result"]}
        if result.get("status") not in {"done", "", None}:
            normalized_failure = {
                "ok": False,
                "reason": str(result.get("reason") or "LLM分流未完成"),
                "missing_fields": ["llm_result"],
            }
            for field in ("error_code", "detail", "suggested_action"):
                value = str(result.get(field) or "").strip()
                if value:
                    normalized_failure[field] = value
            return normalized_failure
        mode = str(result.get("mode") or "").strip()
        confidence = self._float_confidence(result.get("confidence"))
        missing_fields = [str(item).strip() for item in result.get("missing_fields") or [] if str(item).strip()]
        if mode not in {"checklist_only", "structured_checklist", "reminder_backed", "pending_manual"}:
            missing_fields.append("mode")
        if confidence < 0.75:
            return {
                "ok": False,
                "reason": str(result.get("reason") or "LLM分流置信度不足"),
                "confidence": confidence,
                "missing_fields": sorted(set(missing_fields or ["confidence"])),
                "evidence": str(result.get("evidence") or "").strip(),
            }
        if mode == "pending_manual":
            return {
                "ok": False,
                "reason": str(result.get("reason") or "LLM无法判断待办分流"),
                "confidence": confidence,
                "missing_fields": sorted(set(missing_fields or ["mode"])),
                "evidence": str(result.get("evidence") or "").strip(),
            }
        items = self._normalize_todo_items(result.get("items"))
        checklist_tree = self._normalize_todo_checklist_tree(result.get("checklist_tree"))
        if mode == "checklist_only" and not items:
            missing_fields.append("items")
        if mode == "structured_checklist" and not checklist_tree:
            missing_fields.append("checklist_tree")
        if missing_fields:
            return {
                "ok": False,
                "reason": str(result.get("reason") or "待办分流缺少必要字段"),
                "confidence": confidence,
                "missing_fields": sorted(set(missing_fields)),
                "evidence": str(result.get("evidence") or "").strip(),
            }
        return {
            "ok": True,
            "mode": mode,
            "items": items,
            "checklist_tree": checklist_tree,
            "confidence": confidence,
            "evidence": str(result.get("evidence") or "").strip(),
            "reason": str(result.get("reason") or "").strip(),
        }

    def _maybe_promote_todo_intake_hierarchy(self, message: Message, todo_intake: dict[str, Any]) -> dict[str, Any]:
        items = [str(item or "").strip() for item in todo_intake.get("items") or [] if str(item or "").strip()]
        if len(items) < 2:
            return todo_intake
        user_content = json.dumps(
            {
                "now": message.created_at.astimezone(ZoneInfo(self.timezone)).isoformat(timespec="seconds"),
                "timezone": self.timezone,
                "text": message.body,
                "raw_text": message.raw_text,
                "items": items,
                "original_reason": str(todo_intake.get("reason") or "").strip(),
            },
            ensure_ascii=False,
            indent=2,
        )
        try:
            reviewed = self.content_flow_client._call_profile_provider_json(
                "daily_task_extraction",
                DAILY_TODO_HIERARCHY_REVIEW_PROMPT,
                user_content,
                "待办父子层级复核",
            )
        except Exception:
            return todo_intake
        normalized = self._normalize_todo_intake(reviewed)
        if not normalized.get("ok") or normalized.get("mode") != "structured_checklist":
            return todo_intake
        reason = str(todo_intake.get("reason") or "").strip()
        review_reason = str(normalized.get("reason") or "").strip()
        return {
            **normalized,
            "reason": (f"{reason}；" if reason else "") + (f"层级复核：{review_reason}" if review_reason else "层级复核：应保留父子待办。"),
        }

    @staticmethod
    def _normalize_todo_items(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        items: list[str] = []
        for item in value[:24]:
            text = re.sub(r"\s+", " ", str(item or "")).strip()
            if text:
                items.append(text[:80])
        return items

    @classmethod
    def _normalize_todo_checklist_tree(cls, value: object) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        for node in value[:12]:
            if not isinstance(node, dict):
                continue
            text = re.sub(r"\s+", " ", str(node.get("text") or "")).strip()
            if not text:
                continue
            children = node.get("children")
            child_nodes = cls._normalize_todo_checklist_tree(children if isinstance(children, list) else [])[:8]
            normalized.append({"text": text[:80], "children": child_nodes})
        return normalized

    def _todo_intake_failure(self, message: Message, result: dict[str, Any]) -> TaskResult:
        error_code = str(result.get("error_code") or "DAILY_TODO_INTAKE_PENDING_MANUAL").strip()
        missing = "、".join(result.get("missing_fields") or []) or "待办分流"
        reason = str(result.get("reason") or "LLM未能判断待办分流").strip()
        detail = str(result.get("detail") or "").strip()
        suggested_action = str(result.get("suggested_action") or "").strip()
        if error_code == "DAILY_LLM_MODEL_AT_CAPACITY":
            reply = (
                f"错误代码：{error_code}\n"
                "状态：待办未创建、未落盘\n"
                f"原因：{reason}\n"
                f"详情：{detail or 'Selected model is at capacity. Please try a different model.'}\n"
                f"建议：{suggested_action or '请稍后直接重试原消息。'}"
            )
        else:
            reply = (
                f"错误代码：{error_code}\n"
                "状态：待办未创建、未落盘\n"
                f"缺少/不确定：{missing}\n"
                f"原因：{reason}\n"
                "建议：可直接重试原消息；若再次出现，可用该错误代码排查。"
            )
        extra = {"todo_intake": result, "error_code": error_code, "persisted": False}
        if detail:
            extra["detail"] = detail
        if suggested_action:
            extra["suggested_action"] = suggested_action
        return TaskResult(
            ok=False,
            status="pending_manual",
            reply=reply,
            task_id="",
            local_path="",
            feishu_doc="",
            extra=extra,
        )

    def _normalize_daily_task_extraction(self, result: dict[str, Any], expected_type: str, message: Message | None = None) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"ok": False, "reason": "LLM未返回对象", "missing_fields": ["llm_result"]}
        if result.get("status") not in {"done", "", None}:
            return {
                "ok": False,
                "reason": str(result.get("reason") or "LLM抽取未完成"),
                "missing_fields": ["llm_result"],
            }
        confidence = self._float_confidence(result.get("confidence"))
        missing_fields = [str(item).strip() for item in result.get("missing_fields") or [] if str(item).strip()]
        due_at = self._parse_llm_datetime(result.get("due_at"))
        remind_at = self._parse_llm_datetime(result.get("remind_at"))
        title = str(result.get("title") or "").strip()
        explicit_due = self._extract_explicit_datetime_from_message(message) if message else None
        if not due_at and explicit_due:
            _, explicit_evidence = explicit_due
            return {
                "ok": False,
                "reason": "系统解析错误：原文包含明确日期时间，但 LLM 清洗结果漏掉 due_at",
                "confidence": confidence,
                "missing_fields": sorted(set(missing_fields or ["due_at"])),
                "evidence": explicit_evidence,
                "parse_error_kind": "llm_missed_explicit_time",
            }
        if not title:
            missing_fields.append("title")
        if not due_at:
            missing_fields.append("due_at")
        if confidence < 0.75:
            return {
                "ok": False,
                "reason": str(result.get("reason") or "LLM置信度不足"),
                "confidence": confidence,
                "missing_fields": sorted(set(missing_fields or ["confidence"])),
                "evidence": str(result.get("evidence") or "").strip(),
            }
        if missing_fields:
            return {
                "ok": False,
                "reason": str(result.get("reason") or "缺少必要字段"),
                "confidence": confidence,
                "missing_fields": sorted(set(missing_fields)),
                "evidence": str(result.get("evidence") or "").strip(),
            }
        return {
            "ok": True,
            "type": expected_type,
            "title": title[:60],
            "due_at": due_at,
            "remind_at": remind_at,
            "confidence": confidence,
            "evidence": str(result.get("evidence") or "").strip(),
            "reason": str(result.get("reason") or "").strip(),
        }

    def _parse_llm_datetime(self, value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        if re.match(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}", text):
            text = text.replace(" ", "T", 1)
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        tz = ZoneInfo(self.timezone)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)

    _EXPLICIT_CN_DATETIME_RE = re.compile(
        r"(?:(?P<year>\d{4})\s*年\s*)?"
        r"(?P<month>0?[1-9]|1[0-2])\s*月\s*"
        r"(?P<day>0?[1-9]|[12]\d|3[01])\s*(?:日|号)?"
        r"[^\d\n]{0,12}"
        r"(?:(?P<ampm>凌晨|早上|上午|中午|下午|晚上)\s*)?"
        r"(?P<hour>[01]?\d|2[0-3])\s*"
        r"(?:(?:[:：]\s*(?P<minute>[0-5]?\d))|(?:点\s*(?P<minute2>[0-5]?\d)?\s*(?:分)?))"
    )
    _EXPLICIT_NUMERIC_DATETIME_RE = re.compile(
        r"(?P<year>20\d{2})\s*[-/]\s*"
        r"(?P<month>0?[1-9]|1[0-2])\s*[-/]\s*"
        r"(?P<day>0?[1-9]|[12]\d|3[01])"
        r"(?:[ T　]+)"
        r"(?P<hour>[01]?\d|2[0-3])\s*[:：]\s*(?P<minute>[0-5]\d)"
    )

    @staticmethod
    def _datetime_from_numeric_match(match: re.Match[str], tz: ZoneInfo) -> datetime | None:
        try:
            return datetime(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
                int(match.group("hour")),
                int(match.group("minute")),
                tzinfo=tz,
            )
        except (TypeError, ValueError):
            return None

    def _extract_explicit_datetime_from_message(self, message: Message | None) -> tuple[datetime, str] | None:
        if message is None:
            return None
        text = "\n".join(part for part in [message.body, message.raw_text] if part)
        tz = ZoneInfo(self.timezone)
        now = message.created_at.astimezone(tz)
        for match in self._EXPLICIT_NUMERIC_DATETIME_RE.finditer(text):
            parsed = self._datetime_from_numeric_match(match, tz)
            if parsed is None:
                continue
            evidence = re.sub(r"\s+", " ", match.group(0)).strip()
            return parsed, evidence
        for match in self._EXPLICIT_CN_DATETIME_RE.finditer(text):
            parsed = self._datetime_from_cn_match(match, now, tz)
            if parsed is None:
                continue
            evidence = re.sub(r"\s+", " ", match.group(0)).strip()
            return parsed, evidence
        return None

    @staticmethod
    def _datetime_from_cn_match(match: re.Match[str], now: datetime, tz: ZoneInfo) -> datetime | None:
        try:
            year_text = match.group("year")
            year = int(year_text) if year_text else now.year
            month = int(match.group("month"))
            day = int(match.group("day"))
            hour = int(match.group("hour"))
            minute = int(match.group("minute") or match.group("minute2") or 0)
        except (TypeError, ValueError):
            return None
        ampm = match.group("ampm") or ""
        if ampm in {"下午", "晚上"} and hour < 12:
            hour += 12
        elif ampm == "中午" and hour < 11:
            hour += 12
        elif ampm in {"凌晨", "早上", "上午"} and hour == 12:
            hour = 0
        try:
            parsed = datetime(year, month, day, hour, minute, tzinfo=tz)
        except ValueError:
            return None
        if not year_text and parsed < now:
            try:
                parsed = parsed.replace(year=parsed.year + 1)
            except ValueError:
                return None
        return parsed

    @staticmethod
    def _float_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, confidence))

    @staticmethod
    def _default_daily_remind_at(kind: str, due_at: datetime) -> datetime:
        return due_at - (timedelta(hours=1) if kind == "日程" else timedelta(minutes=30))

    def _daily_task_parse_failure(self, message: Message, extracted: dict[str, Any], kind: str) -> TaskResult:
        if extracted.get("parse_error_kind") == "llm_missed_explicit_time":
            evidence = str(extracted.get("evidence") or "").strip()
            reply = (
                f"{kind}没有创建：系统解析错误。\n"
                f"原文已经包含明确时间：{evidence or '已检测到明确日期时间'}\n"
                "LLM 清洗结果漏掉 due_at；这不是用户信息缺失，不需要补时间。"
            )
            return TaskResult(ok=False, status="parser_error", reply=reply, task_id="", local_path="", feishu_doc="", extra={"llm_parse": extracted})
        missing = "、".join(extracted.get("missing_fields") or []) or "时间"
        reason = str(extracted.get("reason") or "LLM没有可靠解析出完整时间").strip()
        reply = (
            f"{kind}没有创建：我没能可靠解析这条的完整时间。\n"
            f"缺少/不确定：{missing}\n"
            f"原因：{reason}\n"
            "请补一句明确时间，例如：`时间=2026-05-31 12:00`。"
        )
        return TaskResult(ok=False, status="pending_time_confirmation", reply=reply, task_id="", local_path="", feishu_doc="", extra={"llm_parse": extracted})

    def _write_todo_structured_checklist(self, message: Message, todo_intake: dict[str, Any]) -> TaskResult:
        checklist_tree = todo_intake["checklist_tree"]
        try:
            checklist = self.obsidian_daily_checklist_service.append_checklist(
                text=message.body,
                now=message.created_at,
                checklist_tree=checklist_tree,
            )
        except ValueError as exc:
            return self._todo_intake_failure(message, {"reason": f"Obsidian checklist 写入参数无效：{exc}", "missing_fields": ["checklist_tree"]})

        sections = [
            ("原始内容", message.raw_text),
            ("LLM结构清单分流", json.dumps({key: todo_intake.get(key) for key in ("mode", "checklist_tree", "confidence", "evidence", "reason")}, ensure_ascii=False, indent=2, default=str)),
            ("Obsidian清单", "\n".join(checklist.markdown_lines)),
        ]
        entry = self.archive_service.save_archive(
            message,
            f"待办结构清单：{checklist.target_date:%Y%m%d}",
            sections,
            {
                "record_kind": "todo_structured_checklist",
                "obsidian_path": checklist.path,
                "target_date": f"{checklist.target_date:%Y-%m-%d}",
                "feishu_synced": False,
                "sync_mode": "feishu_parent_child_and_obsidian_checklist",
                "feishu_sync_status": "attempted_after_archive",
                "llm_confidence": todo_intake.get("confidence", 0),
                "llm_evidence": todo_intake.get("evidence", ""),
            },
        )

        record_entries: list[dict[str, Any]] = []

        def write_node(node: dict[str, Any], *, parent_record_id: str = "", ref_suffix: str = "", depth: int = 0) -> None:
            title = str(node.get("text") or "").strip()
            children = node.get("children")
            child_nodes = children if isinstance(children, list) else []
            if not title:
                return
            extra_fields: dict[str, Any] = {
                "类型说明": "待办子记录" if parent_record_id else "待办父记录",
                "未填写原因": "截止/提醒时间：未填写，原因：原文是结构化待办清单，没有明确截止或提醒时间。",
            }
            if parent_record_id:
                extra_fields["父记录"] = parent_record_id
            result = self.reminder_service.add(
                kind="待办",
                title=title,
                text="\n".join(
                    line
                    for line in [
                        f"父待办记录ID：{parent_record_id}" if parent_record_id else "",
                        f"原始待办：{message.body}",
                    ]
                    if line
                ),
                due_at=None,
                remind_at=None,
                source=message.source,
                ref_id=f"{entry.frontmatter['id']}-{ref_suffix}",
                local_path=entry.local_path,
                extra_fields=extra_fields,
                omit_management_fields=True,
            )
            record_id = str((result.get("data") or {}).get("record_id") or "").strip()
            record_entries.append({"title": title, "depth": depth, "result": result, "record_id": record_id, "parent_record_id": parent_record_id})
            if not result.get("ok"):
                return
            effective_parent_id = record_id or f"{entry.frontmatter['id']}-{ref_suffix}"
            for index, child in enumerate(child_nodes, start=1):
                write_node(child, parent_record_id=effective_parent_id, ref_suffix=f"{ref_suffix}-{index}", depth=depth + 1)

        for index, root in enumerate(checklist_tree, start=1):
            write_node(root, ref_suffix=str(index))

        failed_records = [item for item in record_entries if not item["result"].get("ok")]
        table_url = next((str((item["result"].get("data") or {}).get("table_url") or "").strip() for item in record_entries if item["result"].get("ok")), "") or self._configured_bitable_url("待办")
        record_lines = []
        for item in record_entries:
            prefix = "已创建" if item["result"].get("ok") else "创建失败"
            indent = "  " * int(item["depth"])
            record_id = item["record_id"] or "无记录ID"
            error = str(item["result"].get("error") or "").strip()
            error_suffix = f"｜错误：{error[-500:]}" if error and not item["result"].get("ok") else ""
            record_lines.append(f"{indent}- {prefix}：{item['title']}（{record_id}）{error_suffix}")

        first_record_id = next((item["record_id"] for item in record_entries if item.get("record_id")), entry.frontmatter["id"])
        ok = bool(record_entries) and not failed_records
        headline = "已创建飞书父子待办，并写入 Obsidian 缩进清单" if ok else "飞书父子待办创建失败；已写入 Obsidian 缩进清单"
        reply_lines = [
            headline,
            f"日期：{checklist.target_date:%Y-%m-%d}",
            f"Obsidian：{checklist.path}",
            "飞书记录：",
            *record_lines,
            f"多维表格：{table_url or '未写入'}",
        ]
        if failed_records:
            reply_lines.append("说明：飞书失败时表格里不会出现对应记录；以上错误是底层写入返回。")
        reply = "\n".join(reply_lines)
        return TaskResult(
            ok=ok,
            status="structured_checklist_archived" if ok else "partial_failed",
            reply=reply,
            task_id=first_record_id,
            local_path=entry.local_path,
            feishu_doc="",
            extra={"todo_intake": todo_intake, "obsidian_path": checklist.path, "feishu_records": record_entries},
        )

    @staticmethod
    def _todo_items_with_explicit_links(items: list[str], text: str) -> list[str]:
        urls = ActivityDailyMixin._extract_explicit_urls(text)
        if not urls:
            return items
        extra_links = " ".join(f"[原链接{i + 2}]({url})" for i, url in enumerate(urls[1:3]))
        updated: list[str] = []
        for item in items:
            item_text = str(item or "").strip()
            if not item_text:
                continue
            if any(url in item_text for url in urls):
                updated.append(item_text)
            else:
                linked_item = f"[{ActivityDailyMixin._markdown_link_label(item_text)}]({urls[0]})"
                updated.append(f"{linked_item} {extra_links}".strip())
        return updated

    @staticmethod
    def _extract_explicit_urls(text: str) -> list[str]:
        urls: list[str] = []
        for match in re.finditer(r"https?://[^\s<>\]\)\"'，。；、]+", str(text or "")):
            url = match.group(0).rstrip(".,;:!?，。；：！？")
            if url and url not in urls:
                urls.append(url)
        return urls

    @staticmethod
    def _markdown_link_label(text: str) -> str:
        return str(text or "").replace("[", "\\[").replace("]", "\\]")

    def _maybe_handle_daily_hierarchy_records(self, message: Message, expected_type: str) -> TaskResult | None:
        if not self._should_attempt_hierarchy_extraction(message):
            return None
        extracted = self._extract_hierarchy_records_with_llm(message, expected_type)
        if extracted.get("single"):
            return None
        if not extracted.get("ok"):
            reason = str(extracted.get("reason") or "LLM未能清洗出父子层级").strip()
            missing = "、".join(extracted.get("missing_fields") or []) or "父子层级字段"
            reply = (
                "层级结构没有创建：系统解析错误。\n"
                f"缺少/不确定：{missing}\n"
                f"原因：{reason}\n"
                "这不是用户信息缺失；需要修正清洗器后重试。"
            )
            return TaskResult(ok=False, status="parser_error", reply=reply, task_id="", local_path="", feishu_doc="", extra={"hierarchy_parse": extracted})
        return self._write_daily_hierarchy_records(message, extracted)

    def _should_attempt_hierarchy_extraction(self, message: Message) -> bool:
        text = message.body or message.raw_text
        compact = re.sub(r"\s+", "", text)
        if len(compact) < 120:
            return False
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        score = 0
        if len(lines) >= 4:
            score += 2
        section_markers = re.findall(r"(?:^|[。\n；;])\s*(?:[一二三四五六七八九十]+|[0-9]+)\s*[、.．]", text)
        if re.search(r"(?m)^\s*(?:[一二三四五六七八九十]+|[0-9]+)\s*[、.．]", text) or len(section_markers) >= 2:
            score += 2
        if re.search(r"(?m)^【[^】]{4,80}】", text):
            score += 1
        if len(re.findall(r"https?://", text)) >= 1:
            score += 1
        if text.count("：") + text.count(":") >= 4:
            score += 1
        if len(list(self._EXPLICIT_CN_DATETIME_RE.finditer(text))) >= 2:
            score += 1
        return score >= 2

    def _write_daily_hierarchy_records(self, message: Message, extracted: dict[str, Any]) -> TaskResult:
        parent = extracted["parent"]
        children = extracted["children"]
        sections = [
            ("原始内容", message.raw_text),
            ("父记录", json.dumps(parent, ensure_ascii=False, indent=2, default=str)),
            ("子记录", json.dumps(children, ensure_ascii=False, indent=2, default=str)),
        ]
        entry = self.archive_service.save_archive(
            message,
            f"层级：{parent['title']}",
            sections,
            {
                "record_kind": "daily_hierarchy_parent_children",
                "llm_confidence": extracted.get("confidence", 0),
                "llm_evidence": extracted.get("evidence", ""),
            },
        )
        parent_due_at, parent_remind_at = self._hierarchy_parent_times(children)
        parent_result = self.reminder_service.add(
            kind="日程",
            title=parent["title"],
            text=parent["summary"] or message.body,
            due_at=parent_due_at,
            remind_at=parent_remind_at,
            source=message.source,
            ref_id=entry.frontmatter["id"],
            local_path=entry.local_path,
            extra_fields=self._daily_hierarchy_parent_extra_fields(parent),
        )
        if not parent_result.get("ok"):
            reply = "父记录创建失败"
            if parent_result.get("error"):
                reply += f"\n错误：{parent_result.get('error')}"
            return TaskResult(ok=False, status="parent_record_failed", reply=reply, task_id=entry.frontmatter["id"], local_path=entry.local_path, feishu_doc="", extra={"hierarchy_parse": extracted})

        parent_record_id = str((parent_result.get("data") or {}).get("record_id") or entry.frontmatter["id"])
        child_results: list[dict[str, Any]] = []
        for index, child in enumerate(children, start=1):
            child_type = child["type"]
            due_at = child["due_at"]
            remind_at = child.get("remind_at") or self._default_daily_remind_at(child_type, due_at)
            extra_fields = self._hierarchy_child_extra_fields(parent_record_id, child)
            result = self.reminder_service.add(
                kind=child_type,
                title=child["title"],
                text=child.get("description") or child["title"],
                due_at=due_at,
                remind_at=remind_at,
                source=message.source,
                ref_id=f"{entry.frontmatter['id']}-{index}",
                local_path=entry.local_path,
                extra_fields=extra_fields,
                omit_management_fields=True,
            )
            child_results.append({"child": child, "result": result})

        failed_children = [item for item in child_results if not item["result"].get("ok")]
        table_url = (parent_result.get("data") or {}).get("table_url") or self._configured_bitable_url("日程")
        child_lines = []
        for item in child_results:
            child = item["child"]
            result = item["result"]
            prefix = "已创建" if result.get("ok") else "创建失败"
            child_lines.append(f"- {prefix} {child['type']}：{child['title']}｜{format_display_time(child['due_at'])}")
        reply = "\n".join(
            [
                "已拆出层级结构",
                f"父记录：{parent['title']}（{parent_record_id}）",
                "子记录：",
                *child_lines,
                f"多维表格：{table_url or '已写入'}",
            ]
        )
        ok = not failed_children
        return TaskResult(
            ok=ok,
            status="archived" if ok else "partial_failed",
            reply=reply,
            task_id=parent_record_id,
            local_path=entry.local_path,
            feishu_doc="",
            extra={"hierarchy_parse": extracted, "child_results": child_results},
        )

    def _extract_hierarchy_records_with_llm(self, message: Message, expected_type: str) -> dict[str, Any]:
        user_content = json.dumps(
            {
                "now": message.created_at.astimezone(ZoneInfo(self.timezone)).isoformat(timespec="seconds"),
                "timezone": self.timezone,
                "expected_type": expected_type,
                "text": message.body,
                "raw_text": message.raw_text,
                "recent_conversation_context": self._conversation_context_prompt(message),
            },
            ensure_ascii=False,
            indent=2,
        )
        try:
            result = self.content_flow_client._call_profile_provider_json(
                "daily_hierarchy_records_extraction",
                DAILY_HIERARCHY_RECORDS_PROMPT,
                user_content,
                "Daily层级结构清洗",
            )
        except Exception as exc:
            return {"ok": False, "reason": f"LLM清洗异常：{exc}", "missing_fields": ["llm_result"]}
        return self._normalize_hierarchy_records(result)

    def _normalize_hierarchy_records(self, result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"ok": False, "reason": "LLM未返回对象", "missing_fields": ["llm_result"]}
        status = str(result.get("status") or "").strip().lower()
        if status == "single":
            return {
                "ok": False,
                "single": True,
                "confidence": self._float_confidence(result.get("confidence")),
                "evidence": str(result.get("evidence") or "").strip(),
                "reason": str(result.get("reason") or "LLM判断为单条事项").strip(),
            }
        if status == "done":
            status = "hierarchy"
        if status != "hierarchy":
            return {
                "ok": False,
                "reason": str(result.get("reason") or "LLM清洗未完成"),
                "missing_fields": [str(item) for item in result.get("missing_fields") or ["hierarchy_records"]],
            }
        confidence = self._float_confidence(result.get("confidence"))
        parent_raw = result.get("parent") if isinstance(result.get("parent"), dict) else {}
        children_raw = result.get("children") if isinstance(result.get("children"), list) else []
        missing_fields = [str(item).strip() for item in result.get("missing_fields") or [] if str(item).strip()]
        parent = self._normalize_hierarchy_parent(parent_raw)
        if not parent["title"]:
            missing_fields.append("parent.title")
        children = []
        for item in children_raw:
            if isinstance(item, dict):
                child = self._normalize_hierarchy_child(item)
                children.append(child)
        if not children:
            missing_fields.append("children")
        for index, child in enumerate(children, start=1):
            if child["type"] not in {"日程", "待办", "提醒"}:
                missing_fields.append(f"children[{index}].type")
            if not child["title"]:
                missing_fields.append(f"children[{index}].title")
            if not child["due_at"]:
                missing_fields.append(f"children[{index}].due_at")
            if child["location"] and not self._location_has_area_prefix(child["location"]):
                missing_fields.append(f"children[{index}].location_parts")
        if confidence < 0.75:
            return {
                "ok": False,
                "reason": str(result.get("reason") or "LLM置信度不足"),
                "confidence": confidence,
                "missing_fields": sorted(set(missing_fields or ["confidence"])),
                "evidence": str(result.get("evidence") or "").strip(),
            }
        if missing_fields:
            return {
                "ok": False,
                "reason": str(result.get("reason") or "缺少父子层级必要字段"),
                "confidence": confidence,
                "missing_fields": sorted(set(missing_fields)),
                "evidence": str(result.get("evidence") or "").strip(),
            }
        return {
            "ok": True,
            "confidence": confidence,
            "parent": parent,
            "children": children,
            "evidence": str(result.get("evidence") or "").strip(),
            "reason": str(result.get("reason") or "").strip(),
        }

    def _normalize_hierarchy_parent(self, parent: dict[str, Any]) -> dict[str, Any]:
        fields_raw = parent.get("fields") if isinstance(parent.get("fields"), dict) else {}
        fields = self._clean_hierarchy_fields(
            fields_raw,
            allowed={
                "地点",
                "类型说明",
                "说明",
                "来源链接",
                "未填写原因",
            },
        )
        location_parts = self._clean_location_parts(
            parent.get("location_parts")
            or parent.get("地点拆解JSON")
            or fields_raw.get("地点拆解JSON")
            or fields_raw.get("地点拆解")
        )
        location = self._format_location_for_feishu(str(parent.get("location") or fields_raw.get("地点") or ""), location_parts)
        if location:
            fields["地点"] = location
        if missing_reason := self._clean_missing_reasons(parent.get("missing_reasons") or fields_raw.get("未填写原因")):
            fields["未填写原因"] = missing_reason
        summary = str(parent.get("summary") or "").strip()
        if summary:
            fields["类型说明"] = summary
        return {
            "type": "日程",
            "title": self._clean_hierarchy_title(parent.get("title")),
            "summary": summary,
            "fields": fields,
        }

    def _normalize_hierarchy_child(self, child: dict[str, Any]) -> dict[str, Any]:
        due_at = self._parse_llm_datetime(child.get("due_at"))
        remind_at = self._parse_llm_datetime(child.get("remind_at"))
        fields_raw = child.get("fields") if isinstance(child.get("fields"), dict) else {}
        location = str(child.get("location") or fields_raw.get("地点") or "").strip()
        location_parts = self._clean_location_parts(
            child.get("location_parts")
            or child.get("地点拆解JSON")
            or fields_raw.get("地点拆解JSON")
            or fields_raw.get("地点拆解")
        )
        location = self._format_location_for_feishu(location, location_parts)
        return {
            "type": str(child.get("type") or "").strip(),
            "title": self._clean_hierarchy_title(child.get("title")),
            "due_at": due_at,
            "remind_at": remind_at,
            "location": location,
            "location_parts": location_parts,
            "source_link": self._first_hierarchy_url(child.get("source_link")),
            "description": str(fields_raw.get("说明") or fields_raw.get("类型说明") or child.get("description") or "").strip(),
            "missing_reason": self._clean_missing_reasons(child.get("missing_reasons") or fields_raw.get("未填写原因")),
            "fields": self._clean_hierarchy_fields(
                fields_raw,
                allowed={"事项类型", "类型说明", "说明", "参与方式", "提交要求", "来源链接", "未填写原因"},
            ),
        }

    @staticmethod
    def _clean_hierarchy_title(value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip(" #【】[]()（）\n\t")
        text = re.sub(r"^(关于举行|关于|举行)", "", text).strip()
        return text[:80]

    @staticmethod
    def _clean_hierarchy_fields(fields: dict[str, Any], *, allowed: set[str]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for key, value in fields.items():
            name = str(key or "").strip()
            if name not in allowed:
                continue
            if isinstance(value, (dict, list)):
                cleaned[name] = value
                continue
            text = re.sub(r"\s+", " ", str(value or "")).strip(" \n\t[玫瑰]")
            if text:
                cleaned[name] = text
        return cleaned

    @staticmethod
    def _first_hierarchy_url(*values: Any) -> str:
        for value in values:
            match = re.search(r"https?://[^\s<>\"]+", str(value or ""))
            if match:
                return match.group(0).rstrip("，。；;、,.!?！？)]）】》\"'")
        return ""

    def _hierarchy_parent_times(self, children: list[dict[str, Any]]) -> tuple[datetime, datetime]:
        schedule_children = [child for child in children if child.get("type") == "日程" and child.get("due_at")]
        timing_children = schedule_children or [child for child in children if child.get("due_at")]
        due_times = [child["due_at"] for child in timing_children]
        due_at = min(due_times)
        remind_times = [
            child.get("remind_at") or self._default_daily_remind_at(child["type"], child["due_at"])
            for child in timing_children
            if child.get("due_at")
        ]
        remind_at = min(remind_times) if remind_times else due_at
        return due_at, remind_at

    @staticmethod
    def _daily_hierarchy_parent_extra_fields(parent: dict[str, Any]) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        for name in ("地点", "类型说明", "来源链接", "未填写原因"):
            value = (parent.get("fields") or {}).get(name)
            if value not in (None, ""):
                extra[name] = value
        return extra

    @staticmethod
    def _hierarchy_child_extra_fields(parent_record_id: str, child: dict[str, Any]) -> dict[str, Any]:
        extra: dict[str, Any] = {
            "父记录": parent_record_id,
        }
        if child.get("location"):
            extra["地点"] = child["location"]
        if child.get("source_link"):
            extra["来源链接"] = child["source_link"]
        if child.get("description"):
            extra["类型说明"] = child["description"]
        if child.get("missing_reason"):
            extra["未填写原因"] = child["missing_reason"]
        return extra

    @staticmethod
    def _clean_location_parts(value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        cleaned: dict[str, str] = {}
        for key, raw_value in value.items():
            name = str(key or "").strip()
            if not name:
                continue
            text = re.sub(r"\s+", " ", str(raw_value or "")).strip()
            if text:
                cleaned[name] = text
        return cleaned

    @staticmethod
    def _format_location_for_feishu(location: str, parts: dict[str, str]) -> str:
        if not parts:
            return ActivityDailyMixin._normalize_formatted_location_text(re.sub(r"\s+", " ", location or "").strip())
        city = parts.get("城市", "")
        province = parts.get("省份") or parts.get("省") or ActivityDailyMixin._province_for_city(city)
        ordered = [
            ActivityDailyMixin._normalize_province_part(province),
            ActivityDailyMixin._normalize_location_part(city, "市"),
            ActivityDailyMixin._normalize_location_part(parts.get("区域", ""), ""),
            parts.get("校区/园区", ""),
            parts.get("场馆", ""),
            parts.get("楼栋", ""),
            parts.get("楼层", ""),
            parts.get("房间", ""),
            parts.get("地址补充", ""),
        ]
        segments: list[str] = []
        for raw in ordered:
            text = re.sub(r"\s+", " ", str(raw or "")).strip()
            if text and text not in segments:
                segments.append(text)
        clean_location = re.sub(r"\s+", " ", location or "").strip()
        specific_parts = [parts.get(name, "") for name in ("区域", "校区/园区", "场馆", "楼栋", "楼层", "房间", "地址补充")]
        compact_location = re.sub(r"\s+", "", clean_location)
        compact_segments = "".join(re.sub(r"\s+", "", item) for item in segments)
        has_specific_overlap = any(
            str(item or "").strip() and re.sub(r"\s+", "", str(item).strip()) in compact_location
            for item in specific_parts
        )
        has_location_overlap = bool(compact_location and compact_segments and (compact_location in compact_segments or compact_segments in compact_location))
        if clean_location and not has_specific_overlap and not has_location_overlap and not any(clean_location == item or clean_location in item for item in segments):
            segments.append(clean_location)
        return ActivityDailyMixin._normalize_formatted_location_text(" ".join(segments).strip())

    @staticmethod
    def _location_has_area_prefix(value: str) -> bool:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text:
            return True
        has_direct_city = bool(re.search(r"(?:北京|上海|天津|重庆)市", text))
        has_city = has_direct_city or bool(re.search(r"[\u4e00-\u9fff]{2,12}市", text))
        has_province = has_direct_city or bool(re.search(r"[\u4e00-\u9fff]{2,12}(?:省|自治区|特别行政区)", text))
        has_area = bool(re.search(r"[\u4e00-\u9fff]{1,12}(?:区|县|大学城|校区|园区)", text))
        return has_city and (has_province or has_area)

    @staticmethod
    def _normalize_formatted_location_text(value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        replacements = {
            "广东 深圳市": "广东省 深圳市",
            "广东 广州": "广东省 广州市",
            "广东省 广州 ": "广东省 广州市 ",
            "广东 深圳": "广东省 深圳市",
            "广东省 深圳 ": "广东省 深圳市 ",
            "广东 珠海": "广东省 珠海市",
            "广东省 珠海 ": "广东省 珠海市 ",
            "广东省 深圳市 教室 学思楼": "广东省 深圳市 学思楼",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        text = text.replace("深圳市市", "深圳市").replace("广州市市", "广州市").replace("珠海市市", "珠海市")
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _normalize_location_part(value: str, suffix: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text or not suffix or text.endswith(("省", "市", "区", "县", "州", "盟")):
            return text
        return f"{text}{suffix}"

    @staticmethod
    def _normalize_province_part(value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text or text.endswith(("省", "市", "自治区", "特别行政区")):
            return text
        return f"{text}省"

    @staticmethod
    def _province_for_city(city: str) -> str:
        compact = re.sub(r"\s+", "", str(city or "")).removesuffix("市")
        return {
            "深圳": "广东省",
            "广州": "广东省",
            "珠海": "广东省",
            "北京": "北京市",
            "上海": "上海市",
            "天津": "天津市",
            "重庆": "重庆市",
        }.get(compact, "")

    @staticmethod
    def _clean_missing_reasons(value: Any) -> str:
        if isinstance(value, dict):
            lines = []
            for key, raw in value.items():
                field = str(key or "").strip()
                reason = re.sub(r"\s+", " ", str(raw or "")).strip()
                if field and reason:
                    lines.append(f"{field}：未填写，原因：{reason}")
            return "；".join(lines)
        if isinstance(value, list):
            return "；".join(re.sub(r"\s+", " ", str(item or "")).strip() for item in value if str(item or "").strip())
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def _extract_daily_task_with_llm(self, message: Message, expected_type: str) -> dict[str, Any]:
        user_content = json.dumps(
            {
                "now": message.created_at.astimezone(ZoneInfo(self.timezone)).isoformat(timespec="seconds"),
                "timezone": self.timezone,
                "expected_type": expected_type,
                "text": message.body,
                "raw_text": message.raw_text,
                "recent_conversation_context": self._conversation_context_prompt(message),
            },
            ensure_ascii=False,
            indent=2,
        )
        try:
            result = self.content_flow_client._call_profile_provider_json(
                "daily_task_extraction",
                DAILY_TASK_EXTRACTION_PROMPT,
                user_content,
                "日程待办自然语言抽取",
            )
        except Exception as exc:
            return {"ok": False, "reason": f"LLM抽取异常：{exc}", "missing_fields": ["llm_result"]}
        return self._normalize_daily_task_extraction(result, expected_type, message)

    def _extract_todo_intake_with_llm(self, message: Message) -> dict[str, Any]:
        user_content = json.dumps(
            {
                "now": message.created_at.astimezone(ZoneInfo(self.timezone)).isoformat(timespec="seconds"),
                "timezone": self.timezone,
                "text": message.body,
                "raw_text": message.raw_text,
                "recent_conversation_context": self._conversation_context_prompt(message),
            },
            ensure_ascii=False,
            indent=2,
        )
        try:
            result = self.content_flow_client._call_profile_provider_json(
                "daily_task_extraction",
                DAILY_TODO_INTAKE_PROMPT,
                user_content,
                "待办清单与提醒分流",
            )
        except Exception as exc:
            return {"ok": False, "reason": f"LLM分流异常：{exc}", "missing_fields": ["llm_result"]}
        return self._normalize_todo_intake(result)

    def _normalize_todo_intake(self, result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"ok": False, "reason": "LLM未返回对象", "missing_fields": ["llm_result"]}
        if result.get("status") not in {"done", "", None}:
            return {
                "ok": False,
                "reason": str(result.get("reason") or "LLM分流未完成"),
                "missing_fields": ["llm_result"],
            }
        mode = str(result.get("mode") or "").strip()
        confidence = self._float_confidence(result.get("confidence"))
        missing_fields = [str(item).strip() for item in result.get("missing_fields") or [] if str(item).strip()]
        if mode not in {"checklist_only", "structured_checklist", "reminder_backed", "pending_manual"}:
            missing_fields.append("mode")
        if confidence < 0.75:
            return {
                "ok": False,
                "reason": str(result.get("reason") or "LLM分流置信度不足"),
                "confidence": confidence,
                "missing_fields": sorted(set(missing_fields or ["confidence"])),
                "evidence": str(result.get("evidence") or "").strip(),
            }
        if mode == "pending_manual":
            return {
                "ok": False,
                "reason": str(result.get("reason") or "LLM无法判断待办分流"),
                "confidence": confidence,
                "missing_fields": sorted(set(missing_fields or ["mode"])),
                "evidence": str(result.get("evidence") or "").strip(),
            }
        items = self._normalize_todo_items(result.get("items"))
        checklist_tree = self._normalize_todo_checklist_tree(result.get("checklist_tree"))
        if mode == "checklist_only" and not items:
            missing_fields.append("items")
        if mode == "structured_checklist" and not checklist_tree:
            missing_fields.append("checklist_tree")
        if missing_fields:
            return {
                "ok": False,
                "reason": str(result.get("reason") or "待办分流缺少必要字段"),
                "confidence": confidence,
                "missing_fields": sorted(set(missing_fields)),
                "evidence": str(result.get("evidence") or "").strip(),
            }
        return {
            "ok": True,
            "mode": mode,
            "items": items,
            "checklist_tree": checklist_tree,
            "confidence": confidence,
            "evidence": str(result.get("evidence") or "").strip(),
            "reason": str(result.get("reason") or "").strip(),
        }

    @staticmethod
    def _normalize_todo_items(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        items: list[str] = []
        for item in value[:24]:
            text = re.sub(r"\s+", " ", str(item or "")).strip()
            if text:
                items.append(text[:80])
        return items

    @classmethod
    def _normalize_todo_checklist_tree(cls, value: object) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        for node in value[:12]:
            if not isinstance(node, dict):
                continue
            text = re.sub(r"\s+", " ", str(node.get("text") or "")).strip()
            if not text:
                continue
            children = node.get("children")
            child_nodes = cls._normalize_todo_checklist_tree(children if isinstance(children, list) else [])[:8]
            normalized.append({"text": text[:80], "children": child_nodes})
        return normalized

    def _todo_intake_failure(self, message: Message, result: dict[str, Any]) -> TaskResult:
        missing = "、".join(result.get("missing_fields") or []) or "待办分流"
        reason = str(result.get("reason") or "LLM未能判断待办分流").strip()
        reply = (
            "待办没有创建：系统未能判断应写 Obsidian 清单还是飞书提醒。\n"
            f"缺少/不确定：{missing}\n"
            f"原因：{reason}"
        )
        return TaskResult(ok=False, status="pending_manual", reply=reply, task_id="", local_path="", feishu_doc="", extra={"todo_intake": result})

    def _normalize_daily_task_extraction(self, result: dict[str, Any], expected_type: str, message: Message | None = None) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"ok": False, "reason": "LLM未返回对象", "missing_fields": ["llm_result"]}
        if result.get("status") not in {"done", "", None}:
            return {
                "ok": False,
                "reason": str(result.get("reason") or "LLM抽取未完成"),
                "missing_fields": ["llm_result"],
            }
        confidence = self._float_confidence(result.get("confidence"))
        missing_fields = [str(item).strip() for item in result.get("missing_fields") or [] if str(item).strip()]
        due_at = self._parse_llm_datetime(result.get("due_at"))
        remind_at = self._parse_llm_datetime(result.get("remind_at"))
        title = str(result.get("title") or "").strip()
        explicit_due = self._extract_explicit_datetime_from_message(message) if message else None
        if not due_at and explicit_due:
            _, explicit_evidence = explicit_due
            return {
                "ok": False,
                "reason": "系统解析错误：原文包含明确日期时间，但 LLM 清洗结果漏掉 due_at",
                "confidence": confidence,
                "missing_fields": sorted(set(missing_fields or ["due_at"])),
                "evidence": explicit_evidence,
                "parse_error_kind": "llm_missed_explicit_time",
            }
        if not title:
            missing_fields.append("title")
        if not due_at:
            missing_fields.append("due_at")
        if confidence < 0.75:
            return {
                "ok": False,
                "reason": str(result.get("reason") or "LLM置信度不足"),
                "confidence": confidence,
                "missing_fields": sorted(set(missing_fields or ["confidence"])),
                "evidence": str(result.get("evidence") or "").strip(),
            }
        if missing_fields:
            return {
                "ok": False,
                "reason": str(result.get("reason") or "缺少必要字段"),
                "confidence": confidence,
                "missing_fields": sorted(set(missing_fields)),
                "evidence": str(result.get("evidence") or "").strip(),
            }
        return {
            "ok": True,
            "type": str(result.get("type") or expected_type).strip() or expected_type,
            "title": title[:60],
            "due_at": due_at,
            "remind_at": remind_at,
            "confidence": confidence,
            "evidence": str(result.get("evidence") or "").strip(),
            "reason": str(result.get("reason") or "").strip(),
        }

    def _parse_llm_datetime(self, value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        if re.match(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}", text):
            text = text.replace(" ", "T", 1)
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        tz = ZoneInfo(self.timezone)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)

    _EXPLICIT_CN_DATETIME_RE = re.compile(
        r"(?:(?P<year>\d{4})\s*年\s*)?"
        r"(?P<month>0?[1-9]|1[0-2])\s*月\s*"
        r"(?P<day>0?[1-9]|[12]\d|3[01])\s*(?:日|号)?"
        r"[^\d\n]{0,12}"
        r"(?:(?P<ampm>凌晨|早上|上午|中午|下午|晚上)\s*)?"
        r"(?P<hour>[01]?\d|2[0-3])\s*"
        r"(?:(?:[:：]\s*(?P<minute>[0-5]?\d))|(?:点\s*(?P<minute2>[0-5]?\d)?\s*(?:分)?))"
    )
    _EXPLICIT_NUMERIC_DATETIME_RE = re.compile(
        r"(?P<year>20\d{2})\s*[-/]\s*"
        r"(?P<month>0?[1-9]|1[0-2])\s*[-/]\s*"
        r"(?P<day>0?[1-9]|[12]\d|3[01])"
        r"(?:[ T　]+)"
        r"(?P<hour>[01]?\d|2[0-3])\s*[:：]\s*(?P<minute>[0-5]\d)"
    )

    @staticmethod
    def _datetime_from_numeric_match(match: re.Match[str], tz: ZoneInfo) -> datetime | None:
        try:
            return datetime(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
                int(match.group("hour")),
                int(match.group("minute")),
                tzinfo=tz,
            )
        except (TypeError, ValueError):
            return None

    def _extract_explicit_datetime_from_message(self, message: Message | None) -> tuple[datetime, str] | None:
        if message is None:
            return None
        text = "\n".join(part for part in [message.body, message.raw_text] if part)
        tz = ZoneInfo(self.timezone)
        now = message.created_at.astimezone(tz)
        for match in self._EXPLICIT_NUMERIC_DATETIME_RE.finditer(text):
            parsed = self._datetime_from_numeric_match(match, tz)
            if parsed is None:
                continue
            evidence = re.sub(r"\s+", " ", match.group(0)).strip()
            return parsed, evidence
        for match in self._EXPLICIT_CN_DATETIME_RE.finditer(text):
            parsed = self._datetime_from_cn_match(match, now, tz)
            if parsed is None:
                continue
            evidence = re.sub(r"\s+", " ", match.group(0)).strip()
            return parsed, evidence
        return None

    @staticmethod
    def _datetime_from_cn_match(match: re.Match[str], now: datetime, tz: ZoneInfo) -> datetime | None:
        try:
            year_text = match.group("year")
            year = int(year_text) if year_text else now.year
            month = int(match.group("month"))
            day = int(match.group("day"))
            hour = int(match.group("hour"))
            minute = int(match.group("minute") or match.group("minute2") or 0)
        except (TypeError, ValueError):
            return None
        ampm = match.group("ampm") or ""
        if ampm in {"下午", "晚上"} and hour < 12:
            hour += 12
        elif ampm == "中午" and hour < 11:
            hour += 12
        elif ampm in {"凌晨", "早上", "上午"} and hour == 12:
            hour = 0
        try:
            parsed = datetime(year, month, day, hour, minute, tzinfo=tz)
        except ValueError:
            return None
        if not year_text and parsed < now:
            try:
                parsed = parsed.replace(year=parsed.year + 1)
            except ValueError:
                return None
        return parsed

    @staticmethod
    def _float_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, confidence))

    @staticmethod
    def _default_daily_remind_at(kind: str, due_at: datetime) -> datetime:
        return due_at - (timedelta(hours=1) if kind == "日程" else timedelta(minutes=30))

    def _daily_task_parse_failure(self, message: Message, extracted: dict[str, Any], kind: str) -> TaskResult:
        if extracted.get("parse_error_kind") == "llm_missed_explicit_time":
            evidence = str(extracted.get("evidence") or "").strip()
            reply = (
                f"{kind}没有创建：系统解析错误。\n"
                f"原文已经包含明确时间：{evidence or '已检测到明确日期时间'}\n"
                "LLM 清洗结果漏掉 due_at；这不是用户信息缺失，不需要补时间。"
            )
            return TaskResult(ok=False, status="parser_error", reply=reply, task_id="", local_path="", feishu_doc="", extra={"llm_parse": extracted})
        missing = "、".join(extracted.get("missing_fields") or []) or "时间"
        reason = str(extracted.get("reason") or "LLM没有可靠解析出完整时间").strip()
        reply = (
            f"{kind}没有创建：我没能可靠解析这条的完整时间。\n"
            f"缺少/不确定：{missing}\n"
            f"原因：{reason}\n"
            "请补一句明确时间，例如：`时间=2026-05-31 12:00`。"
        )
        return TaskResult(ok=False, status="pending_time_confirmation", reply=reply, task_id="", local_path="", feishu_doc="", extra={"llm_parse": extracted})

    def _activity_from_ai_clean(self, body: str, clean: dict[str, Any]) -> dict[str, Any]:
        links = []
        for item in clean.get("source_links") or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            links.append({"label": str(item.get("label") or "来源链接").strip() or "来源链接", "url": url})
        directions = [str(item).strip() for item in clean.get("subtopic_directions") or [] if str(item).strip()]
        missing_info = [str(item).strip() for item in clean.get("missing_info") or [] if str(item).strip()]
        first_line = next((line.strip().lstrip("#📢 ").strip() for line in body.splitlines() if line.strip()), "")
        return {
            "title": str(clean.get("title") or first_line or "未命名活动").strip(),
            "platform": str(clean.get("platform") or "未识别").strip(),
            "level": str(clean.get("activity_level") or "").strip(),
            "main_topic": str(clean.get("main_topic") or "").strip(),
            "activity_time": str(clean.get("activity_time") or "").strip(),
            "activity_time_start": str(clean.get("activity_time_start") or "").strip(),
            "activity_time_end": str(clean.get("activity_time_end") or "").strip(),
            "boost_date": str(clean.get("boost_date") or "").strip(),
            "reward": str(clean.get("reward") or "").strip(),
            "directions": directions,
            "links": links,
            "brief_summary": str(clean.get("brief_summary") or "").strip(),
            "participation_method": str(clean.get("participation_method") or "").strip(),
            "participation_form": str(clean.get("participation_form") or "").strip(),
            "filling_points": str(clean.get("filling_points") or "").strip(),
            "submission_requirements": str(clean.get("submission_requirements") or "").strip(),
            "status": str(clean.get("activity_status") or "进行中").strip() or "进行中",
            "parse_status": str(clean.get("parse_status") or "已解析").strip() or "已解析",
            "source_status": f"AI清洗完成：{clean.get('postprocess_provider') or 'provider'}",
            "manual_needed": str(clean.get("parse_status") or "") == "待人工补充",
            "missing_info": missing_info,
        }

    def _extract_activity(self, body: str, brief: dict[str, Any] | None = None) -> dict[str, Any]:
        brief = brief or {}
        fields = brief.get("fields") if isinstance(brief.get("fields"), dict) else {}
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        title = str(fields.get("title") or (lines[0].lstrip("#📢 ").strip() if lines else "未命名活动")).strip()
        platform = str(fields.get("platform") or "").strip()
        if not platform or platform == "未识别":
            platform = "小红书" if "小红书" in body else "未识别"
        level_match = re.search(r"([A-Z]{1,3})级", body)
        main_topic_match = re.search(r"(#[\w\u4e00-\u9fff]+)", body)
        activity_time = str(fields.get("activity_time") or self._extract_labeled_text(body, "活动时间")).strip()
        reward = str(fields.get("reward") or self._extract_labeled_text(body, "活动奖励")).strip()
        links = []
        seen_urls: set[str] = set()
        for label, url in re.findall(r"([^：:\n]*?)[:：]\s*(https?://\S+)", body):
            clean_url = url.strip().rstrip("，。；、.）)]】")
            if clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)
            links.append({"label": label.strip("🔗🧩 ") or "链接", "url": clean_url})
        for item in fields.get("source_links") or []:
            if not isinstance(item, dict):
                continue
            clean_url = str(item.get("url") or "").strip()
            if not clean_url or clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)
            links.append({"label": str(item.get("label") or "来源链接"), "url": clean_url})
        directions = []
        for line in lines:
            if not line.startswith("#"):
                continue
            topic, _, desc = line.partition("：")
            directions.append(f"{topic.strip()}：{desc.strip()}" if desc else topic.strip())
        for item in fields.get("directions") or []:
            if isinstance(item, str) and item.strip() and item.strip() not in directions:
                directions.append(item.strip())
        return {
            "title": title,
            "platform": platform,
            "level": str(fields.get("level") or (level_match.group(1) if level_match else "")),
            "main_topic": str(fields.get("main_topic") or (main_topic_match.group(1) if main_topic_match else "")),
            "activity_time": activity_time,
            "reward": reward,
            "directions": directions,
            "links": links,
            "brief_summary": str(fields.get("brief_summary") or "").strip(),
            "participation_method": str(fields.get("participation_method") or "").strip(),
            "participation_form": str(fields.get("participation_form") or "").strip(),
            "filling_points": str(fields.get("filling_points") or "").strip(),
            "submission_requirements": str(fields.get("submission_requirements") or "").strip(),
            "source_status": str(fields.get("source_status") or brief.get("source_status") or "").strip(),
            "manual_needed": bool(fields.get("manual_needed") or brief.get("manual_needed")),
            "missing_info": fields.get("missing_info") if isinstance(fields.get("missing_info"), list) else [],
        }

    def _format_activity_record(self, activity: dict[str, Any], raw_body: str) -> str:
        lines = [
            self._format_activity_summary(activity),
            "",
            "活动 Brief：",
            activity.get("brief_summary") or "未提取到",
            "",
            "参与方式：",
            activity.get("participation_method") or "未提取到",
            "",
            "参与形式：",
            activity.get("participation_form") or "未提取到",
            "",
            "填写要点：",
            activity.get("filling_points") or "未提取到",
            "",
            "提交要求：",
            activity.get("submission_requirements") or "未提取到",
            "",
            "创作方向：",
            "\n".join(f"- {item}" for item in activity["directions"]) or "未提取到",
            "",
            "链接：",
            "\n".join(f"- {item['label']}：{item['url']}" for item in activity["links"]) or "未提取到",
            "",
            "解析状态：",
            activity.get("source_status") or "未记录",
            "",
            "待人工补充：",
            "、".join(activity.get("missing_info") or []) or "无",
            "",
            "原始内容：",
            raw_body.strip(),
        ]
        return "\n".join(lines).strip()

    def _format_activity_summary(self, activity: dict[str, Any]) -> str:
        return "\n".join(
            line
            for line in [
                f"- 标题：{activity['title']}",
                f"- 平台：{activity['platform']}",
                f"- 活动级别：{activity['level']}" if activity.get("level") else "",
                f"- 主话题：{activity['main_topic']}" if activity.get("main_topic") else "",
                f"- 活动时间：{activity['activity_time']}" if activity.get("activity_time") else "",
                f"- 活动奖励：{activity['reward']}" if activity.get("reward") else "",
            ]
            if line
        )
