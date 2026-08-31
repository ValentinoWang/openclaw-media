"""Schema-v2 node, release, and execution model for the phase-2 Media C/B SSOT."""

from __future__ import annotations


def node(
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
    worker_level: str = "LW",
    consumes_decision: bool = False,
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
        "worker_level": worker_level,
        "consumes_decision": consumes_decision,
    }


SPECS: dict[str, dict[str, object]] = {
    "A": node(
        "media.stage2.charter", "A", "charter", "governance", "ACCEPTED",
        "第二阶段章程", "产品负责人、交付负责人", "用户指令、三阶段编排文本和第一阶段 SSOT",
        "冻结个人内容闭环、C/B 人工智能上下文和文档路由范围", "第二阶段唯一开发编排边界",
        "阶段边界、候选身份和排除项检查", "只生成第二阶段，不改写第一阶段也不创建第三阶段",
        "章程、证据目标和完成口径一致", "维护第二阶段章程；不修改产品代码。",
        write_authority="authoritative-contract", acceptance_authority="user and planning authority",
    ),
    "A1": node(
        "media.stage2.source-baseline", "A", "fact-discovery", "source-facts", "ACCEPTED",
        "输入与跨阶段基线", "规划者、实施者", "事实审计、三阶段编排文本、第一阶段机器源和进度",
        "复算校验值，核对已验收底座、未完成断点和三个跨阶段门禁", "可复现的非 Git 来源基线",
        "输入文件校验值复算与权威路径存在性", "第一阶段 C1、C3、DC2 均未接受",
        "后续节点只消费列明来源和跨阶段投影", "只读复核输入文件并登记证据。",
        write_authority="evidence-only",
    ),
    "K": node(
        "media.stage2.product-decisions", "A", "decision-acceptance", "product-contract", "ACCEPTED",
        "第二阶段产品决定", "个人创作者、组织创作者、产品负责人", "用户确认的三阶段思路与事实审计",
        "接受服务端上下文、个人 Web 正文、组织飞书正文、第二阶段独占写入路由和失败关闭边界；确认页面权限不进入现有会话信封，改由独立只读入口状态接口承载；确认字体自托管、中文切片和字重收敛策略；确认 11 个顶层导航页加 1 条运行详情深链，共 12 条普通路由条目全部向个人人格开放，并按个人数据作用域与个人正文权威执行。", "已接受决定记录第 4 版",
        "决定覆盖、合同不变性、C/B 互斥、路由负例和弱网字体验收", "记录实现事实与正式接受状态的证据分层；组织 Binding、飞书写入和组织成员能力不得因个人路由开放而泄漏",
        "全部交付节点引用同一决定版本；实现待执行，不冒领验收", "维护已接受决定记录；不得把推荐重新降级为待决。",
        write_authority="authoritative-contract", acceptance_authority="user",
    ),
    "F1": node(
        "media.stage2.gate.stage1-identity", "A", "validation", "cross-stage", "BLOCKED",
        "第一阶段身份汇合投影", "共享合同与个人支线", "第一阶段 C1 机器状态、候选身份和 I9 旧写入器关闭回执",
        "零写入核对 C1 的正式状态、会话、个人工作区、授权负例和人工智能文档能力失败关闭身份", "身份汇合跨阶段收据",
        "上游机器源、主视图、进度、I9 回执和候选哈希核对", "只有第一阶段 C1 ACCEPTED 且 I9 属于同一候选时才可接受本投影",
        "接受后只解锁共享合同和个人内容支线", "zero-write 投影第一阶段 C1；不修改上游状态。",
        write_authority="evidence-only", acceptance_authority="cross-stage projection owner", worker_level="L3",
    ),
    "F2": node(
        "media.stage2.gate.stage1-provision", "A", "validation", "cross-stage", "BLOCKED",
        "第一阶段组织开通汇合投影", "组织文档支线", "第一阶段 C3 状态、Binding 合同和候选身份",
        "零写入核对 C3 的正式状态和当前会话解析活跃组织绑定的能力", "组织开通跨阶段收据",
        "上游机器源、Binding 回执和候选哈希核对", "只有第一阶段 C3 ACCEPTED 才可接受本投影",
        "接受后只解锁组织资料、按 Binding 写入和飞书回读支线", "zero-write 投影第一阶段 C3；不修改上游状态。",
        write_authority="evidence-only", acceptance_authority="cross-stage projection owner", worker_level="L3",
    ),
    "F3": node(
        "media.stage2.gate.stage1-final", "A", "validation", "cross-stage", "BLOCKED",
        "第一阶段必需交付终验投影", "候选和发布负责人", "第一阶段 DC2 状态、发布身份和真实外部系统证据",
        "零写入核对发布增量 1A 与 1B 是否完成独立终验", "第一阶段必需交付跨阶段收据",
        "上游 DC2、两个发布增量、外部系统和分层恢复证据核对", "只有第一阶段 DC2 ACCEPTED 才可接受本投影",
        "本投影接受前禁止组装第二阶段唯一候选", "zero-write 投影第一阶段 DC2；不修改、不部署。",
        write_authority="evidence-only", acceptance_authority="independent acceptance owner", worker_level="L3",
    ),
    "B": node(
        "media.stage2.contract-assembly", "A", "contract-assembly", "shared-contracts", "BLOCKED",
        "第二阶段共享合同汇编", "产品、前后端和验收负责人", "F1 接受的会话底座和 K 第 4 版决定",
        "冻结人工智能执行上下文、资料路由、写入路由、成果登记、回读、能力副作用和独立入口状态接口合同；保持 parseMediaSessionEnvelope 的严格响应结构不变", "共享接口冻结身份",
        "OpenAPI、类型、错误码、状态机、入口状态独立接口和保护测试红灯", "不接受前端伪造租户、Binding、正文权威或路由授权",
        "C/B 两支只消费同一共享合同", "F1 接受后汇编共享合同；不启动组织外部写入。",
        write_authority="authoritative-contract", consumes_decision=True,
    ),
    "S1": node(
        "media.stage2.ai-execution-context", "B", "contract-compile", "shared-ai", "BLOCKED",
        "服务端人工智能执行上下文", "所有人工智能能力", "B 合同、服务端会话、成员关系、Binding 和能力编号",
        "生成可信的租户、工作区、正文权威、成员角色、Binding 和能力组合结果；为入口状态投影提供服务端事实", "AIExecutionContext 第 3 版",
        "字段来源、缺失、撤销、伪造和组织 A/B 负例", "上下文全部由服务端事实生成",
        "前端提交的保留字段被稳定拒绝", "实现 AIExecutionContext 唯一构建路径。", consumes_decision=True,
    ),
    "S2": node(
        "media.stage2.context-routing", "B", "implementation", "shared-ai", "BLOCKED",
        "C/B 资料上下文路由", "创作和咨询能力", "S1 执行上下文、租户资料和资料所有者登记",
        "按个人或组织工作区选择可用资料，关闭近期活动全表读取等跨租户断点", "ContextBuilder 路由和来源收据",
        "个人/组织正例、资料所有者、跨租户、缺失和重复资料负例", "01_ 近期活动与其他资料使用同等租户边界",
        "每个上下文项都可回读来源和租户归属", "实现统一 ContextBuilder 路由和跨租户门禁。", consumes_decision=True,
    ),
    "S3": node(
        "media.stage2.writer-routing", "B", "contract-compile", "shared-writer", "BLOCKED",
        "第二阶段唯一文档写入路由", "所有文档型能力", "F2 接受的阶段边界、S1 执行上下文、B 正文权威合同和第一阶段 I9 失败关闭回执",
        "从第一阶段统一能力不可用状态原子切换到唯一服务端路由；个人文档写入内部 Web 成果，组织文档写入活跃 Binding 的飞书 Docx", "WriterRouter 第 2 版",
        "能力矩阵、关闭态接管、正反路由、第一阶段 I7 零人工智能写入、只读能力零副作用和缺失 Binding 负例", "不允许第一阶段或能力实现绕过统一路由自选文档容器",
        "第二阶段独占 Writer；切换后删除旧关闭处理之外的旧 Writer、全局凭据回退和双权威", "编译第二阶段唯一 WriterRouter、关闭态接管和能力副作用合同。", consumes_decision=True,
    ),
    "S4": node(
        "media.stage2.artifact-record-readback", "B", "implementation", "shared-artifact", "BLOCKED",
        "成果登记与回读状态机", "个人和组织成果消费者", "S3 写入结果、文档成果模型、修订和飞书镜像合同",
        "用幂等收据登记容器、正文权威、远端绑定、修订或回读版本，部分成功进入待处置", "ArtifactRecorder 和 ReadbackVerifier",
        "写入失败、登记失败、回读失败、重放、并发和版本冲突测试", "任一必要步骤失败都不得返回发布成功",
        "部分外部成功有可幂等续接和审计收据", "实现成果登记、回读和失败关闭状态机。", consumes_decision=True,
    ),
    "S5": node(
        "media.stage2.capability-side-effects", "B", "implementation", "shared-capability", "BLOCKED",
        "能力目录与副作用授权", "能力维护者和调用者", "现有能力注册表、S1 执行上下文和 S3 写入合同",
        "为每个能力声明可读资料、是否产生文档、允许容器和必需回读，由服务端强制", "能力副作用注册表",
        "公开/运维/维护能力、只读咨询、写文档、未登记和越权负例", "只读能力不产生文档或远端副作用",
        "全部文档型能力均通过统一写入路由", "实现能力副作用注册和服务端守卫。", consumes_decision=True,
    ),
    "T1": node(
        "media.stage2.shared-acceptance-harness", "B", "acceptance-design", "shared-contracts", "BLOCKED",
        "共享 OpenAPI 与端到端验收 Harness", "开发、QA、安全和发布负责人", "B 冻结合同和 K 第 4 版决定",
        "维护请求合同、上下文类型、入口状态接口、错误码、审计、C/B 正负例、真实会话矩阵和同收据端到端合同", "保护测试和验收矩阵",
        "合同漂移、会话信封加字段、入口状态越权、前端夹带权威字段、跨租户、错容器、写入回读失败和字体弱网回退红灯", "每个稳定失败类都有红绿门禁",
        "Harness 不成为运行时分支或第二事实源", "建立共享合同和端到端 Harness；不实现业务支线。", consumes_decision=True,
    ),
    "C1": node(
        "media.stage2.personal-source-scope", "B", "implementation", "personal-content", "BLOCKED",
        "个人资料与账号范围", "个人创作者", "F1 个人工作区、B 合同、个人素材、账号、复盘和记忆",
        "建立个人专属资料范围、来源收据和缺失处置", "个人资料投影与范围合同",
        "个人正例、空资料、他人、组织资料和删除后刷新负例", "个人工作区不读取任何组织共享资料",
        "所有资料可回读租户和来源归属", "实现个人资料范围和隔离门禁。", consumes_decision=True,
    ),
    "C2": node(
        "media.stage2.personal-research-brief", "B", "implementation", "personal-content", "BLOCKED",
        "个人研究简报", "个人创作者", "C1 个人资料和账号范围",
        "将素材、拆解、账号记忆和来源引用汇编为可回读研究简报", "个人研究简报成果",
        "来源引用、缺失素材、重复来源、租户边界和确定性重建测试", "研究结论和来源引用可分离复核",
        "简报只写个人成果范围并屏蔽组织资料", "实现个人研究简报和来源门禁。", consumes_decision=True,
    ),
    "C3": node(
        "media.stage2.personal-decision-brief", "B", "implementation", "personal-content", "BLOCKED",
        "个人决策简报", "个人创作者", "C1 个人资料、用户选择和平台约束",
        "保存选题、目标、取舍、风险和人工确认记录", "个人决策简报成果",
        "没有人工选择、过期约束、重放、租户隔离和风险字段测试", "模型建议不伪装为用户决定",
        "决策记录具有人工确认和来源身份", "实现个人决策简报和确认收据。", consumes_decision=True,
    ),
    "C4": node(
        "media.stage2.personal-context-builder", "B", "implementation", "personal-ai", "BLOCKED",
        "个人创作上下文", "个人创作任务", "S2 资料路由、C2 研究简报和 C3 决策简报",
        "组合个人资料、研究、决策、账号和平台约束，不带入组织 Binding 或品牌共享资料", "PersonalContextBuilder 结果",
        "上下文完整性、来源身份、租户隔离、伪造正文权威和重放测试", "个人任务只使用 personal_web/internal 上下文",
        "服务端上下文收据可复现且不含组织秘密", "实现 PersonalContextBuilder 和跨模式负例。", consumes_decision=True,
    ),
    "C5": node(
        "media.stage2.personal-internal-writer", "B", "implementation", "personal-writer", "BLOCKED",
        "个人内部成果写入", "个人创作任务", "C4 个人上下文、S3 写入路由、S4 成果登记和 S5 副作用合同",
        "创建 personal_web/internal 文档成果、首个正文修订和人工智能运行收据", "InternalArtifactWriter 和个人成果收据",
        "幂等、重放、写入失败、登记失败、错容器和全局飞书零写入测试", "个人路径不得创建任何全局飞书文档",
        "成果、正文、运行和来源收据可同收据回读", "实现个人内部 Writer 并退役个人飞书写入。", consumes_decision=True,
    ),
    "C6": node(
        "media.stage2.personal-web-revision", "B", "implementation", "personal-editor", "BLOCKED",
        "个人 Web 编辑与修订", "个人创作者", "C5 个人成果和 Revision 11 已验收的 Web 正文工作区",
        "打开、编辑、保存、冲突检测、幂等重放并生成新修订", "Web 编辑界面和修订链",
        "键盘、移动端、冲突、断网恢复、无权限、组织成果负例和写后回读", "Web 是个人正文的唯一编辑权威",
        "每次保存都有内容校验值、基线版本和回读证据", "实现个人 Web 编辑和修订闭环。", consumes_decision=True,
    ),
    "C7": node(
        "media.stage2.personal-version-export", "B", "implementation", "personal-publish", "BLOCKED",
        "个人平台版本与发布包", "个人创作者", "C6 已回读修订、平台目标和发布包合同",
        "选择已回读修订生成平台版本、发布文案、分镜或口播和导出清单", "平台版本和发布包成果",
        "修订身份、重建一致性、平台字段、过期基线和失败不可发布测试", "发布包只引用已回读的个人正文版本",
        "导出成果、来源修订和平台目标可追溯", "实现平台版本和发布包生成。", consumes_decision=True,
    ),
    "C8": node(
        "media.stage2.personal-e2e", "C", "convergence", "personal-content", "BLOCKED",
        "个人内容生产汇合", "个人创作者", "C1 到 C7、S 共享汇合和 T1 验收合同",
        "汇合素材、研究、决策、人工智能创作、内部成果、Web 修订、平台版本和发布包", "个人端到端候选",
        "联合合同、浏览器、数据库、重放、跨租户和全局飞书零写入测试", "个人全链在同一候选上可重现",
        "个人候选可独立验收，但不替代组织支线和第二阶段完成", "汇合个人内容支线并冻结子候选。",
        write_authority="shared-generated", consumes_decision=True,
    ),
    "O1": node(
        "media.stage2.organization-source-scope", "B", "implementation", "organization-content", "BLOCKED",
        "组织资料与品牌约束", "组织创作成员", "F2 活跃组织绑定、B 合同、组织素材、活动、商务和品牌资料",
        "按当前组织限定资料、品牌规则、组织账号和可用成员上下文", "组织资料和品牌约束收据",
        "组织 A/B、个人资料、撤销 Binding、来源所有者和近期活动隔离测试", "组织 A 不得读取组织 B 或个人资料",
        "资料收据可回读当前组织和活跃 Binding", "实现组织资料和品牌约束路由。", consumes_decision=True,
    ),
    "O2": node(
        "media.stage2.organization-lark-writer", "B", "implementation", "organization-writer", "BLOCKED",
        "按组织绑定写入飞书", "组织创作任务", "O1 组织资料、S2 资料路由、S3 写入路由、S5 副作用合同和当前活跃 Binding",
        "使用当前组织的应用凭据世代、Wiki 空间和父节点创建飞书 Docx", "LarkArtifactWriter 和远端写入收据",
        "组织 A/B 凭据、父节点、撤销、轮换、配额、重试和全局凭据零调用测试", "组织 A 不得使用组织 B 或部署级凭据",
        "写入收据绑定租户、Binding、凭据世代、远端文档和时间", "实现按当前 Binding 的 LarkArtifactWriter 并删除全局 Writer 消费。", consumes_decision=True,
    ),
    "O3": node(
        "media.stage2.organization-artifact-binding", "B", "implementation", "organization-artifact", "BLOCKED",
        "组织成果与远端文档绑定", "组织成员和 Web 成果层", "O2 远端写入收据和 S4 成果登记状态机",
        "创建 organization_lark/lark 文档成果、飞书绑定、同步批次和可信打开动作", "组织成果绑定收据",
        "重放、重复远端文档、错租户、错 Binding、登记失败和内部 Web 正文零写入测试", "组织路径不创建可编辑的内部 Web 正文",
        "成果、Binding、远端文档和写入收据一一对应", "实现组织成果和飞书文档幂等绑定。", consumes_decision=True,
    ),
    "O4": node(
        "media.stage2.organization-readback", "B", "implementation", "organization-readback", "BLOCKED",
        "组织飞书写后回读", "组织成员和 Web 读者", "O3 成果绑定、远端版本和 S4 回读合同",
        "从同一 Binding 回读飞书正文、版本和修改时间，追加只读镜像并验证可信打开链接", "组织只读镜像和回读收据",
        "错 Binding、错文档、空正文、超时、版本倒退、不可信链接和部分成功测试", "未完成回读时不得向用户标记发布成功",
        "Web 预览只消费飞书回读镜像，不编辑组织正文", "实现同 Binding 飞书回读和 Web 只读镜像。", consumes_decision=True,
    ),
    "O5": node(
        "media.stage2.organization-edit-readback", "B", "validation", "organization-readback", "BLOCKED",
        "飞书编辑后再回读", "组织创作成员", "O4 首次回读成果、可信飞书打开动作和隔离验收身份",
        "在飞书修改同一文档，再次回读并证明 Web 镜像跟随远端新版本", "飞书编辑和再回读同收据证据",
        "真实 Docx 编辑、版本变化、Web 只读、错账号、错组织和编辑冲突测试", "飞书是组织正文的唯一编辑权威",
        "编辑前后远端版本、Web 镜像和候选身份完整", "在隔离组织执行真实飞书编辑和再回读。",
        write_authority="evidence-only", acceptance_authority="runtime acceptance owner", worker_level="L3", consumes_decision=True,
    ),
    "O6": node(
        "media.stage2.organization-e2e", "C", "convergence", "organization-content", "BLOCKED",
        "组织文档生产汇合", "组织创作成员", "O1 到 O5、S 共享汇合和 T1 验收合同",
        "汇合组织资料、人工智能创作、当前 Binding 写入、成果绑定、Web 回读、飞书编辑和再回读", "组织端到端候选",
        "联合合同、真实飞书、数据库、跨组织、错凭据、错容器和失败关闭测试", "组织全链在同一租户、Binding、文档和候选上闭环",
        "组织候选不冒领第三阶段完整角色和审批能力", "汇合组织文档支线并冻结子候选。",
        write_authority="shared-generated", consumes_decision=True,
    ),
    "S": node(
        "media.stage2.shared-convergence", "C", "convergence", "shared-contracts", "BLOCKED",
        "共享人工智能和文档路由汇合", "C/B 两类产品支线", "S1 到 S5 和 T1 的已接受输出",
        "核对上下文、资料、写入、成果、回读、能力目录和 OpenAPI 的唯一组合同", "共享路由不可变子候选",
        "合同生成、能力矩阵、错容器、失败状态、跨租户和禁止旧 Writer 检查", "所有文档能力只有一个路由入口",
        "接受后可独立支持已解锁的个人或组织支线", "汇合共享合同和实现；不组装最终候选。",
        write_authority="shared-generated", consumes_decision=True,
    ),
    "C": node(
        "media.stage2.unique-candidate", "C", "convergence", "release-candidate", "BLOCKED",
        "第二阶段唯一候选", "个人和组织创作用户", "C8 个人子候选、O6 组织子候选和 F3 上游最终验收收据",
        "以 F3 绑定的第一阶段 DC2 候选为晋升基线，按 M1 协议重放全部已接受补丁，再核对接口、数据、生成物、外部资源、清理清单和恢复点", "哈希绑定的第二阶段候选",
        "两次确定性重建、补丁清单、资源清单、晋升基线冲突、跨支线冲突和上游身份复算", "只有一个候选，且不包含旧 Writer、双写权威或隐式回退路径",
        "候选冻结后任何修改都必须重建身份并重跑 D 阶段", "汇合第二阶段唯一候选；不部署、不重启。",
        write_authority="shared-generated", consumes_decision=True,
    ),
    "DA": node(
        "media.stage2.static-release-acceptance", "D", "validation", "release", "BLOCKED",
        "第二阶段静态与合同验收", "发布负责人", "C 的不可变候选",
        "使用静态验证配置，只读候选并在临时目录和临时数据库运行构建、类型、OpenAPI、迁移、能力注册、跨租户、密钥、生成漂移和清理门禁", "静态验收证据包",
        "受影响门禁、旧 Writer 源码搜索和候选哈希复算", "所有门禁对同一候选通过",
        "禁止修改候选、生产数据库和外部系统；失败返回所属节点修复并重建候选", "对唯一候选执行静态、合同和清理验收。",
        write_authority="evidence-only", consumes_decision=True,
    ),
    "DB": node(
        "media.stage2.external-system-acceptance", "D", "validation", "release", "BLOCKED",
        "真实个人与组织端到端验收", "个人创作者、组织创作成员", "DA 接受候选、批准发布窗口和隔离验收身份",
        "原子切换代码发布身份，再按数据库恢复合同和飞书幂等补偿合同执行两条全链、负例与恢复观察", "生产与飞书同收据证据",
        "真实浏览器、数据库、人工智能任务、飞书 Docx、编辑、回读和跨组织负例", "目标证据达到 physical-device/external-system",
        "发布、账号、租户、Binding、成果、设备和时间身份完整", "在批准窗口执行分层恢复可验证的推广和真实外部系统验收。",
        write_authority="evidence-only", acceptance_authority="runtime acceptance owner", worker_level="L3", consumes_decision=True,
    ),
    "DC": node(
        "media.stage2.independent-release-decision", "D", "release-decision", "release", "BLOCKED",
        "第二阶段独立终验与发布决定", "产品负责人、个人和组织用户", "DB 同收据证据、原始要求、已接受决定和清理清单",
        "零写入核对范围、候选、生产、飞书、C/B 互斥、失败关闭、回滚和第三阶段排除项", "独立 ACCEPTED 或拒绝结论",
        "哈希、时间、身份、证据等级、无旧 Writer 和无范围冒领核对", "所有第二阶段完成条件成立且无第三阶段能力冒领",
        "仅 DC ACCEPTED 可宣告第二阶段完成", "zero-write 独立终验；不得修复、部署或改变状态。",
        write_authority="evidence-only", acceptance_authority="independent acceptance owner", worker_level="L3", consumes_decision=True,
    ),
}


# Node IDs are stable labels. This list is the only topology source.
EDGES: list[tuple[str, str, str]] = [
    ("A", "A1", "specific-output"),
    ("A1", "K", "specific-output"),
    ("A1", "F1", "specific-output"),
    ("A1", "F2", "specific-output"),
    ("A1", "F3", "specific-output"),
    ("K", "B", "specific-output"),
    ("F1", "B", "specific-output"),
    ("B", "S1", "specific-output"),
    ("S1", "S2", "specific-output"),
    ("S1", "S3", "specific-output"),
    ("F2", "S3", "specific-output"),
    ("S1", "S5", "specific-output"),
    ("S3", "S4", "specific-output"),
    ("S3", "S5", "specific-output"),
    ("B", "T1", "specific-output"),
    ("S1", "S", "specific-output"),
    ("S2", "S", "specific-output"),
    ("S3", "S", "specific-output"),
    ("S4", "S", "specific-output"),
    ("S5", "S", "specific-output"),
    ("T1", "S", "specific-output"),
    ("B", "C1", "specific-output"),
    ("F1", "C1", "specific-output"),
    ("C1", "C2", "specific-output"),
    ("C1", "C3", "specific-output"),
    ("C2", "C4", "specific-output"),
    ("C3", "C4", "specific-output"),
    ("S2", "C4", "specific-output"),
    ("C4", "C5", "specific-output"),
    ("S3", "C5", "specific-output"),
    ("S4", "C5", "specific-output"),
    ("S5", "C5", "specific-output"),
    ("C5", "C6", "specific-output"),
    ("C6", "C7", "specific-output"),
    ("C7", "C8", "specific-output"),
    ("S", "C8", "specific-output"),
    ("T1", "C8", "specific-output"),
    ("B", "O1", "specific-output"),
    ("F2", "O1", "specific-output"),
    ("O1", "O2", "specific-output"),
    ("S2", "O2", "specific-output"),
    ("S3", "O2", "specific-output"),
    ("S5", "O2", "specific-output"),
    ("O2", "O3", "specific-output"),
    ("S4", "O3", "specific-output"),
    ("O3", "O4", "specific-output"),
    ("O4", "O5", "specific-output"),
    ("O5", "O6", "specific-output"),
    ("S", "O6", "specific-output"),
    ("T1", "O6", "specific-output"),
    ("C8", "C", "specific-output"),
    ("O6", "C", "specific-output"),
    ("F3", "C", "specific-output"),
    ("C", "DA", "global-completeness"),
    ("DA", "DB", "global-completeness"),
    ("DB", "DC", "global-completeness"),
]


BATCHES: dict[str, str] = {
    "A1": "source-baseline",
    "F1": "cross-stage-projections", "F2": "cross-stage-projections", "F3": "cross-stage-projections",
    "S1": "shared-context", "S2": "shared-context", "S3": "shared-writer",
    "S4": "shared-writer", "S5": "shared-capability", "T1": "shared-contracts",
    "C1": "personal-foundation", "C2": "personal-briefs", "C3": "personal-briefs",
    "C4": "personal-context", "C5": "personal-writer", "C6": "personal-editor",
    "C7": "personal-publish", "C8": "personal-convergence",
    "O1": "organization-foundation", "O2": "organization-writer", "O3": "organization-artifact",
    "O4": "organization-readback", "O5": "organization-readback", "O6": "organization-convergence",
}


SSOT_SCHEMA_VERSION = 2
PRODUCT_DECISION_VERSION = 5
PLAN_VERSION = 5
DAG_VERSION = 5
INTERFACE_FREEZE_VERSION = 5
NODE_CONTRACT_VERSION = 5

PRIMARY_EXECUTOR_DEFAULT = "lw-terra"
PRIMARY_EXECUTOR_OVERRIDES: dict[str, str] = {}
PRIMARY_EXECUTOR_OPTIONS = {
    "lw-luna": "run-lw-luna.sh",
    "lw-terra": "run-lw-terra.sh",
}


def selected_primary_executor(node_id: str) -> str:
    """Return the explicitly configured writable primary for a Stage 2 leaf."""

    return PRIMARY_EXECUTOR_OVERRIDES.get(node_id, PRIMARY_EXECUTOR_DEFAULT)


def selected_primary_wrapper(node_id: str) -> str:
    return PRIMARY_EXECUTOR_OPTIONS[selected_primary_executor(node_id)]


NODE_ROLE_OVERRIDES: dict[str, str] = {
    "A": "charter",
    "S": "convergence",
    "C8": "convergence",
    "O6": "convergence",
    "C": "convergence",
    "F1": "acceptance-gate",
    "F2": "acceptance-gate",
    "F3": "acceptance-gate",
    "O5": "acceptance-gate",
    "DA": "acceptance-gate",
    "DB": "acceptance-gate",
    "DC": "release-decision",
}

EXECUTION_ACTOR_OVERRIDES: dict[str, str] = {
    "A": "human",
    "A1": "orchestrator",
    "K": "human",
    "F1": "external-system",
    "F2": "external-system",
    "F3": "external-system",
    "S": "orchestrator",
    "C8": "orchestrator",
    "O6": "orchestrator",
    "C": "orchestrator",
    "DA": "orchestrator",
    "O5": "human",
    "DB": "human",
    "DC": "human",
}

TRANSPORT_OVERRIDES: dict[str, str] = {
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

PROJECTION_SOURCE_NODES: dict[str, list[str]] = {
    "F1": ["stage1:C1", "stage1:I9"],
    "F2": ["stage1:C3"],
    "F3": ["stage1:DC2"],
}

PROJECTION_RULES: dict[str, str] = {
    "F1": "仅当第一阶段 C1 与同候选 I9 均为 ACCEPTED 时投影为 ACCEPTED，否则保持 BLOCKED。",
    "F2": "仅当第一阶段 C3 为 ACCEPTED 且候选身份匹配时投影为 ACCEPTED，否则保持 BLOCKED。",
    "F3": "仅当第一阶段 DC2 为 ACCEPTED 且发布身份匹配时投影为 ACCEPTED，否则保持 BLOCKED。",
}

DETERMINISTIC_COMMANDS: dict[str, str] = {
    "DA": "python3 -m pytest -q",
}

SIDE_EFFECT_OVERRIDES: dict[str, str] = {
    "O2": "reversible",
    "O3": "reversible",
    "O4": "reversible",
    "O5": "reversible",
    "DB": "reversible",
}

CANDIDATE_IDENTITY_POLICY_OVERRIDES: dict[str, str] = {
    "F1": "consumes",
    "F2": "consumes",
    "F3": "must-match",
    "S": "freezes",
    "C8": "freezes",
    "O5": "must-match",
    "O6": "freezes",
    "C": "freezes",
    "DA": "must-match",
    "DB": "must-match",
    "DC": "must-match",
}

RELEASE_SLICE_BY_NODE: dict[str, str] = {node_id: "REL-2" for node_id in SPECS}

WAVE_BY_NODE: dict[str, str] = {
    "A": "W-2-0",
    "A1": "W-2-1",
    **{node_id: "W-2-2" for node_id in ("K", "F1", "F2", "F3")},
    "B": "W-2-3",
    **{node_id: "W-2-4" for node_id in ("S1", "T1", "C1", "O1")},
    **{node_id: "W-2-5" for node_id in ("S2", "S3", "C2", "C3")},
    **{node_id: "W-2-6" for node_id in ("S4", "S5", "C4")},
    **{node_id: "W-2-7" for node_id in ("S", "C5", "O2")},
    **{node_id: "W-2-8" for node_id in ("O3", "C6")},
    **{node_id: "W-2-9" for node_id in ("O4", "C7")},
    **{node_id: "W-2-10" for node_id in ("O5", "C8")},
    "O6": "W-2-11",
    "C": "W-2-12",
    "DA": "W-2-13",
    "DB": "W-2-14",
    "DC": "W-2-15",
}
