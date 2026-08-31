# 第二阶段节点合同与验收

## 完整节点合同

| Task ID | Business target | User | Inputs | Processing | Outputs | Tests | Acceptance | Completion definition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 第二阶段章程 | 产品负责人、交付负责人 | 用户指令、三阶段编排文本和第一阶段 SSOT | 冻结个人内容闭环、C/B 人工智能上下文和文档路由范围 | 第二阶段唯一开发编排边界 | 阶段边界、候选身份和排除项检查 | 只生成第二阶段，不改写第一阶段也不创建第三阶段 | 章程、证据目标和完成口径一致 |
| A1 | 输入与跨阶段基线 | 规划者、实施者 | 事实审计、三阶段编排文本、第一阶段机器源和进度 | 复算校验值，核对已验收底座、未完成断点和三个跨阶段门禁 | 可复现的非 Git 来源基线 | 输入文件校验值复算与权威路径存在性 | 第一阶段 C1、C3、DC2 均未接受 | 后续节点只消费列明来源和跨阶段投影 |
| K | 第二阶段产品决定 | 个人创作者、组织创作者、产品负责人 | 用户确认的三阶段思路与事实审计 | 接受服务端上下文、个人 Web 正文、组织飞书正文、第二阶段独占写入路由和失败关闭边界；确认 routeGrants 保留在严格会话信封中，仅用作服务端与客户端路由清单漂移检测，且会话合同必须升至 v3；确认登录入口状态接口只作登录前探针，不能泄露工作台授权；确认字体自托管、中文切片和字重收敛策略；确认普通和轨道路由全部向个人人格开放，并按个人数据作用域与个人正文权威执行。 | 已接受决定记录第 5 版 | 决定覆盖、合同不变性、C/B 互斥、路由负例和弱网字体验收 | 记录实现事实与正式接受状态的证据分层；组织 Binding、飞书写入和组织成员能力不得因个人路由开放而泄漏 | 全部交付节点引用同一决定版本；实现待执行，不冒领验收 |
| F1 | 第一阶段身份汇合投影 | 共享合同与个人支线 | 第一阶段 C1 机器状态、候选身份和 I9 旧写入器关闭回执 | 零写入核对 C1 的正式状态、会话、个人工作区、授权负例和人工智能文档能力失败关闭身份 | 身份汇合跨阶段收据 | 上游机器源、主视图、进度、I9 回执和候选哈希核对 | 只有第一阶段 C1 ACCEPTED 且 I9 属于同一候选时才可接受本投影 | 接受后只解锁共享合同和个人内容支线 |
| F2 | 第一阶段组织开通汇合投影 | 组织文档支线 | 第一阶段 C3 状态、Binding 合同和候选身份 | 零写入核对 C3 的正式状态和当前会话解析活跃组织绑定的能力 | 组织开通跨阶段收据 | 上游机器源、Binding 回执和候选哈希核对 | 只有第一阶段 C3 ACCEPTED 才可接受本投影 | 接受后只解锁组织资料、按 Binding 写入和飞书回读支线 |
| F3 | 第一阶段必需交付终验投影 | 候选和发布负责人 | 第一阶段 DC2 状态、发布身份和真实外部系统证据 | 零写入核对发布增量 1A 与 1B 是否完成独立终验 | 第一阶段必需交付跨阶段收据 | 上游 DC2、两个发布增量、外部系统和分层恢复证据核对 | 只有第一阶段 DC2 ACCEPTED 才可接受本投影 | 本投影接受前禁止组装第二阶段唯一候选 |
| B | 第二阶段共享合同汇编 | 产品、前后端和验收负责人 | F1 接受的会话底座和 K 第 5 版决定 | 冻结人工智能执行上下文、资料路由、写入路由、成果登记、回读、能力副作用、会话合同 v3 和登录入口状态接口合同；routeGrants 必须维持服务端生成与客户端独立推导后逐项比对的失败关闭语义 | 共享接口冻结身份 | OpenAPI、类型、错误码、状态机、入口状态独立接口和保护测试红灯 | 不接受前端伪造租户、Binding、正文权威或路由授权 | C/B 两支只消费同一共享合同 |
| S1 | 服务端人工智能执行上下文 | 所有人工智能能力 | B 合同、服务端会话、成员关系、Binding 和能力编号 | 生成可信的租户、工作区、正文权威、成员角色、Binding 和能力组合结果；为入口状态投影提供服务端事实 | AIExecutionContext 第 3 版 | 字段来源、缺失、撤销、伪造和组织 A/B 负例 | 上下文全部由服务端事实生成 | 前端提交的保留字段被稳定拒绝 |
| S2 | C/B 资料上下文路由 | 创作和咨询能力 | S1 执行上下文、租户资料和资料所有者登记 | 按个人或组织工作区选择可用资料，关闭近期活动全表读取等跨租户断点 | ContextBuilder 路由和来源收据 | 个人/组织正例、资料所有者、跨租户、缺失和重复资料负例 | 01_ 近期活动与其他资料使用同等租户边界 | 每个上下文项都可回读来源和租户归属 |
| S3 | 第二阶段唯一文档写入路由 | 所有文档型能力 | F2 接受的阶段边界、S1 执行上下文、B 正文权威合同和第一阶段 I9 失败关闭回执 | 从第一阶段统一能力不可用状态原子切换到唯一服务端路由；个人文档写入内部 Web 成果，组织文档写入活跃 Binding 的飞书 Docx | WriterRouter 第 2 版 | 能力矩阵、关闭态接管、正反路由、第一阶段 I7 零人工智能写入、只读能力零副作用和缺失 Binding 负例 | 不允许第一阶段或能力实现绕过统一路由自选文档容器 | 第二阶段独占 Writer；切换后删除旧关闭处理之外的旧 Writer、全局凭据回退和双权威 |
| S4 | 成果登记与回读状态机 | 个人和组织成果消费者 | S3 写入结果、文档成果模型、修订和飞书镜像合同 | 用幂等收据登记容器、正文权威、远端绑定、修订或回读版本，部分成功进入待处置 | ArtifactRecorder 和 ReadbackVerifier | 写入失败、登记失败、回读失败、重放、并发和版本冲突测试 | 任一必要步骤失败都不得返回发布成功 | 部分外部成功有可幂等续接和审计收据 |
| S5 | 能力目录与副作用授权 | 能力维护者和调用者 | 现有能力注册表、S1 执行上下文和 S3 写入合同 | 为每个能力声明可读资料、是否产生文档、允许容器和必需回读，由服务端强制 | 能力副作用注册表 | 公开/运维/维护能力、只读咨询、写文档、未登记和越权负例 | 只读能力不产生文档或远端副作用 | 全部文档型能力均通过统一写入路由 |
| T1 | 共享 OpenAPI 与端到端验收 Harness | 开发、QA、安全和发布负责人 | B 冻结合同和 K 第 5 版决定 | 维护请求合同、上下文类型、入口状态接口、错误码、审计、C/B 正负例、真实会话矩阵和同收据端到端合同 | 保护测试和验收矩阵 | 合同漂移、会话信封加字段、入口状态越权、前端夹带权威字段、跨租户、错容器、写入回读失败和字体弱网回退红灯 | 每个稳定失败类都有红绿门禁 | Harness 不成为运行时分支或第二事实源 |
| C1 | 个人资料与账号范围 | 个人创作者 | F1 个人工作区、B 合同、个人素材、账号、复盘和记忆 | 建立个人专属资料范围、来源收据和缺失处置 | 个人资料投影与范围合同 | 个人正例、空资料、他人、组织资料和删除后刷新负例 | 个人工作区不读取任何组织共享资料 | 所有资料可回读租户和来源归属 |
| C2 | 个人研究简报 | 个人创作者 | C1 个人资料和账号范围 | 将素材、拆解、账号记忆和来源引用汇编为可回读研究简报 | 个人研究简报成果 | 来源引用、缺失素材、重复来源、租户边界和确定性重建测试 | 研究结论和来源引用可分离复核 | 简报只写个人成果范围并屏蔽组织资料 |
| C3 | 个人决策简报 | 个人创作者 | C1 个人资料、用户选择和平台约束 | 保存选题、目标、取舍、风险和人工确认记录 | 个人决策简报成果 | 没有人工选择、过期约束、重放、租户隔离和风险字段测试 | 模型建议不伪装为用户决定 | 决策记录具有人工确认和来源身份 |
| C4 | 个人创作上下文 | 个人创作任务 | S2 资料路由、C2 研究简报和 C3 决策简报 | 组合个人资料、研究、决策、账号和平台约束，不带入组织 Binding 或品牌共享资料 | PersonalContextBuilder 结果 | 上下文完整性、来源身份、租户隔离、伪造正文权威和重放测试 | 个人任务只使用 personal_web/internal 上下文 | 服务端上下文收据可复现且不含组织秘密 |
| C5 | 个人内部成果写入 | 个人创作任务 | C4 个人上下文、S3 写入路由、S4 成果登记和 S5 副作用合同 | 创建 personal_web/internal 文档成果、首个正文修订和人工智能运行收据 | InternalArtifactWriter 和个人成果收据 | 幂等、重放、写入失败、登记失败、错容器和全局飞书零写入测试 | 个人路径不得创建任何全局飞书文档 | 成果、正文、运行和来源收据可同收据回读 |
| C6 | 个人 Web 编辑与修订 | 个人创作者 | C5 个人成果和 Revision 11 已验收的 Web 正文工作区 | 打开、编辑、保存、冲突检测、幂等重放并生成新修订 | Web 编辑界面和修订链 | 键盘、移动端、冲突、断网恢复、无权限、组织成果负例和写后回读 | Web 是个人正文的唯一编辑权威 | 每次保存都有内容校验值、基线版本和回读证据 |
| C7 | 个人平台版本与发布包 | 个人创作者 | C6 已回读修订、平台目标和发布包合同 | 选择已回读修订生成平台版本、发布文案、分镜或口播和导出清单 | 平台版本和发布包成果 | 修订身份、重建一致性、平台字段、过期基线和失败不可发布测试 | 发布包只引用已回读的个人正文版本 | 导出成果、来源修订和平台目标可追溯 |
| C8 | 个人内容生产汇合 | 个人创作者 | C1 到 C7、S 共享汇合和 T1 验收合同 | 汇合素材、研究、决策、人工智能创作、内部成果、Web 修订、平台版本和发布包 | 个人端到端候选 | 联合合同、浏览器、数据库、重放、跨租户和全局飞书零写入测试 | 个人全链在同一候选上可重现 | 个人候选可独立验收，但不替代组织支线和第二阶段完成 |
| O1 | 组织资料与品牌约束 | 组织创作成员 | F2 活跃组织绑定、B 合同、组织素材、活动、商务和品牌资料 | 按当前组织限定资料、品牌规则、组织账号和可用成员上下文 | 组织资料和品牌约束收据 | 组织 A/B、个人资料、撤销 Binding、来源所有者和近期活动隔离测试 | 组织 A 不得读取组织 B 或个人资料 | 资料收据可回读当前组织和活跃 Binding |
| O2 | 按组织绑定写入飞书 | 组织创作任务 | O1 组织资料、S2 资料路由、S3 写入路由、S5 副作用合同和当前活跃 Binding | 使用当前组织的应用凭据世代、Wiki 空间和父节点创建飞书 Docx | LarkArtifactWriter 和远端写入收据 | 组织 A/B 凭据、父节点、撤销、轮换、配额、重试和全局凭据零调用测试 | 组织 A 不得使用组织 B 或部署级凭据 | 写入收据绑定租户、Binding、凭据世代、远端文档和时间 |
| O3 | 组织成果与远端文档绑定 | 组织成员和 Web 成果层 | O2 远端写入收据和 S4 成果登记状态机 | 创建 organization_lark/lark 文档成果、飞书绑定、同步批次和可信打开动作 | 组织成果绑定收据 | 重放、重复远端文档、错租户、错 Binding、登记失败和内部 Web 正文零写入测试 | 组织路径不创建可编辑的内部 Web 正文 | 成果、Binding、远端文档和写入收据一一对应 |
| O4 | 组织飞书写后回读 | 组织成员和 Web 读者 | O3 成果绑定、远端版本和 S4 回读合同 | 从同一 Binding 回读飞书正文、版本和修改时间，追加只读镜像并验证可信打开链接 | 组织只读镜像和回读收据 | 错 Binding、错文档、空正文、超时、版本倒退、不可信链接和部分成功测试 | 未完成回读时不得向用户标记发布成功 | Web 预览只消费飞书回读镜像，不编辑组织正文 |
| O5 | 飞书编辑后再回读 | 组织创作成员 | O4 首次回读成果、可信飞书打开动作和隔离验收身份 | 在飞书修改同一文档，再次回读并证明 Web 镜像跟随远端新版本 | 飞书编辑和再回读同收据证据 | 真实 Docx 编辑、版本变化、Web 只读、错账号、错组织和编辑冲突测试 | 飞书是组织正文的唯一编辑权威 | 编辑前后远端版本、Web 镜像和候选身份完整 |
| O6 | 组织文档生产汇合 | 组织创作成员 | O1 到 O5、S 共享汇合和 T1 验收合同 | 汇合组织资料、人工智能创作、当前 Binding 写入、成果绑定、Web 回读、飞书编辑和再回读 | 组织端到端候选 | 联合合同、真实飞书、数据库、跨组织、错凭据、错容器和失败关闭测试 | 组织全链在同一租户、Binding、文档和候选上闭环 | 组织候选不冒领第三阶段完整角色和审批能力 |
| S | 共享人工智能和文档路由汇合 | C/B 两类产品支线 | S1 到 S5 和 T1 的已接受输出 | 核对上下文、资料、写入、成果、回读、能力目录和 OpenAPI 的唯一组合同 | 共享路由不可变子候选 | 合同生成、能力矩阵、错容器、失败状态、跨租户和禁止旧 Writer 检查 | 所有文档能力只有一个路由入口 | 接受后可独立支持已解锁的个人或组织支线 |
| C | 第二阶段唯一候选 | 个人和组织创作用户 | C8 个人子候选、O6 组织子候选和 F3 上游最终验收收据 | 以 F3 绑定的第一阶段 DC2 候选为晋升基线，按 M1 协议重放全部已接受补丁，再核对接口、数据、生成物、外部资源、清理清单和恢复点 | 哈希绑定的第二阶段候选 | 两次确定性重建、补丁清单、资源清单、晋升基线冲突、跨支线冲突和上游身份复算 | 只有一个候选，且不包含旧 Writer、双写权威或隐式回退路径 | 候选冻结后任何修改都必须重建身份并重跑 D 阶段 |
| DA | 第二阶段静态与合同验收 | 发布负责人 | C 的不可变候选 | 使用静态验证配置，只读候选并在临时目录和临时数据库运行构建、类型、OpenAPI、迁移、能力注册、跨租户、密钥、生成漂移和清理门禁 | 静态验收证据包 | 受影响门禁、旧 Writer 源码搜索和候选哈希复算 | 所有门禁对同一候选通过 | 禁止修改候选、生产数据库和外部系统；失败返回所属节点修复并重建候选 |
| DB | 真实个人与组织端到端验收 | 个人创作者、组织创作成员 | DA 接受候选、批准发布窗口和隔离验收身份 | 原子切换代码发布身份，再按数据库恢复合同和飞书幂等补偿合同执行两条全链、负例与恢复观察 | 生产与飞书同收据证据 | 真实浏览器、数据库、人工智能任务、飞书 Docx、编辑、回读和跨组织负例 | 目标证据达到 physical-device/external-system | 发布、账号、租户、Binding、成果、设备和时间身份完整 |
| DC | 第二阶段独立终验与发布决定 | 产品负责人、个人和组织用户 | DB 同收据证据、原始要求、已接受决定和清理清单 | 零写入核对范围、候选、生产、飞书、C/B 互斥、失败关闭、回滚和第三阶段排除项 | 独立 ACCEPTED 或拒绝结论 | 哈希、时间、身份、证据等级、无旧 Writer 和无范围冒领核对 | 所有第二阶段完成条件成立且无第三阶段能力冒领 | 仅 DC ACCEPTED 可宣告第二阶段完成 |

## 第二阶段正式验收矩阵

| Acceptance area | Required positive path | Required negative path | Owning nodes | Completion evidence |
| --- | --- | --- | --- | --- |
| 跨阶段身份输入 | 第一阶段 C1 正式接受并投影 F1 | 上游状态、哈希或候选不一致必须保持阻塞 | F1/B | 第一阶段机器源与候选同身份回执 |
| 共享人工智能上下文 | 服务端生成租户、工作区、正文权威、Binding 和能力范围 | 前端夹带权威字段、跨租户资料和近期活动全表读取均拒绝 | S1-S5/T1/S | 合同、数据库、能力矩阵和负例同候选证据 |
| 个人内容闭环 | 个人资料、研究、决策、创作、内部成果、Web 修订、平台版本和发布包 | 组织资料、组织 Binding 和任何飞书写入必须为零 | C1-C8 | 真实个人账号、浏览器、成果、修订和任务同收据 |
| 跨阶段组织输入 | 第一阶段 C3 正式接受并投影 F2 | 缺失、撤销或错组织 Binding 必须保持阻塞 | F2/O1 | 第一阶段机器源、Binding 和候选同身份回执 |
| 组织飞书闭环 | 组织资料、当前 Binding 写入、成果绑定、Web 回读、飞书编辑和再回读 | 错组织、全局凭据、内部可编辑正文和回读失败均拒绝成功 | O1-O6 | 真实飞书 Docx、Binding、远端版本和 Web 镜像同收据 |
| 失败关闭 | 写入、登记和必要回读全部成功后才标记发布成功 | 部分成功、重放、并发和版本倒退进入可处置状态 | S4/C5/O2/O3/O4 | 状态机、幂等键、失败收据和续接回读 |
| 候选组装 | 个人、组织、共享子候选与第一阶段 DC2 投影一致 | F3 未接受、旧 Writer 存活或子候选身份不同均禁止组装 | F3/C | 唯一候选哈希、资源清单和清理门禁 |
| 发布 | 同一候选静态通过、代码身份原子切换、真实两支端到端通过、分层恢复验证和独立终验 | 第三阶段能力冒领、恢复合同缺失或任何强制负例失败均拒绝 | DA/DB/DC | 哈希绑定的生产、浏览器、数据库、人工智能任务和飞书证据 |

## Harness 门禁抽象

| Task ID | Failure type | Project invariant | Detection | Control location | Gate evidence | New guard/QA | MCP usage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | 来源、决定或状态被错误改写 | 只生成第二阶段，不改写第一阶段也不创建第三阶段 | 阶段边界、候选身份和排除项检查 | docs and contract | EV-A-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| A1 | 来源、决定或状态被错误改写 | 第一阶段 C1、C3、DC2 均未接受 | 输入文件校验值复算与权威路径存在性 | docs and contract | EV-A1-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| K | 来源、决定或状态被错误改写 | 记录实现事实与正式接受状态的证据分层；组织 Binding、飞书写入和组织成员能力不得因个人路由开放而泄漏 | 决定覆盖、合同不变性、C/B 互斥、路由负例和弱网字体验收 | docs and contract | EV-K-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| F1 | 证据身份不全、越级接受或验收写入候选 | 只有第一阶段 C1 ACCEPTED 且 I9 属于同一候选时才可接受本投影 | 上游机器源、主视图、进度、I9 回执和候选哈希核对 | scripts/qa and evidence contract | EV-F1-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| F2 | 证据身份不全、越级接受或验收写入候选 | 只有第一阶段 C3 ACCEPTED 才可接受本投影 | 上游机器源、Binding 回执和候选哈希核对 | scripts/qa and evidence contract | EV-F2-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| F3 | 证据身份不全、越级接受或验收写入候选 | 只有第一阶段 DC2 ACCEPTED 才可接受本投影 | 上游 DC2、两个发布增量、外部系统和分层恢复证据核对 | scripts/qa and evidence contract | EV-F3-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| B | 合同漂移、字段伪造或副作用未声明 | 不接受前端伪造租户、Binding、正文权威或路由授权 | OpenAPI、类型、错误码、状态机、入口状态独立接口和保护测试红灯 | contract and scripts/quality | EV-B-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| S1 | 合同漂移、字段伪造或副作用未声明 | 上下文全部由服务端事实生成 | 字段来源、缺失、撤销、伪造和组织 A/B 负例 | contract and scripts/quality | EV-S1-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| S2 | 租户、正文权威、版本或失败状态不符合节点合同 | 01_ 近期活动与其他资料使用同等租户边界 | 个人/组织正例、资料所有者、跨租户、缺失和重复资料负例 | scripts/quality and scripts/qa | EV-S2-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| S3 | 合同漂移、字段伪造或副作用未声明 | 不允许第一阶段或能力实现绕过统一路由自选文档容器 | 能力矩阵、关闭态接管、正反路由、第一阶段 I7 零人工智能写入、只读能力零副作用和缺失 Binding 负例 | contract and scripts/quality | EV-S3-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| S4 | 租户、正文权威、版本或失败状态不符合节点合同 | 任一必要步骤失败都不得返回发布成功 | 写入失败、登记失败、回读失败、重放、并发和版本冲突测试 | scripts/quality and scripts/qa | EV-S4-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| S5 | 租户、正文权威、版本或失败状态不符合节点合同 | 只读能力不产生文档或远端副作用 | 公开/运维/维护能力、只读咨询、写文档、未登记和越权负例 | scripts/quality and scripts/qa | EV-S5-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| T1 | 合同漂移、字段伪造或副作用未声明 | 每个稳定失败类都有红绿门禁 | 合同漂移、会话信封加字段、入口状态越权、前端夹带权威字段、跨租户、错容器、写入回读失败和字体弱网回退红灯 | contract and scripts/quality | EV-T1-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| C1 | 租户、正文权威、版本或失败状态不符合节点合同 | 个人工作区不读取任何组织共享资料 | 个人正例、空资料、他人、组织资料和删除后刷新负例 | scripts/quality and scripts/qa | EV-C1-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| C2 | 租户、正文权威、版本或失败状态不符合节点合同 | 研究结论和来源引用可分离复核 | 来源引用、缺失素材、重复来源、租户边界和确定性重建测试 | scripts/quality and scripts/qa | EV-C2-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| C3 | 租户、正文权威、版本或失败状态不符合节点合同 | 模型建议不伪装为用户决定 | 没有人工选择、过期约束、重放、租户隔离和风险字段测试 | scripts/quality and scripts/qa | EV-C3-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| C4 | 租户、正文权威、版本或失败状态不符合节点合同 | 个人任务只使用 personal_web/internal 上下文 | 上下文完整性、来源身份、租户隔离、伪造正文权威和重放测试 | scripts/quality and scripts/qa | EV-C4-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| C5 | 租户、正文权威、版本或失败状态不符合节点合同 | 个人路径不得创建任何全局飞书文档 | 幂等、重放、写入失败、登记失败、错容器和全局飞书零写入测试 | scripts/quality and scripts/qa | EV-C5-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| C6 | 租户、正文权威、版本或失败状态不符合节点合同 | Web 是个人正文的唯一编辑权威 | 键盘、移动端、冲突、断网恢复、无权限、组织成果负例和写后回读 | scripts/quality and scripts/qa | EV-C6-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| C7 | 租户、正文权威、版本或失败状态不符合节点合同 | 发布包只引用已回读的个人正文版本 | 修订身份、重建一致性、平台字段、过期基线和失败不可发布测试 | scripts/quality and scripts/qa | EV-C7-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| C8 | 子候选身份不一致、依赖缺失或汇合后仍有双路径 | 个人全链在同一候选上可重现 | 联合合同、浏览器、数据库、重放、跨租户和全局飞书零写入测试 | scripts/quality and contract | EV-C8-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| O1 | 租户、正文权威、版本或失败状态不符合节点合同 | 组织 A 不得读取组织 B 或个人资料 | 组织 A/B、个人资料、撤销 Binding、来源所有者和近期活动隔离测试 | scripts/quality and scripts/qa | EV-O1-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| O2 | 租户、正文权威、版本或失败状态不符合节点合同 | 组织 A 不得使用组织 B 或部署级凭据 | 组织 A/B 凭据、父节点、撤销、轮换、配额、重试和全局凭据零调用测试 | scripts/quality and scripts/qa | EV-O2-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| O3 | 租户、正文权威、版本或失败状态不符合节点合同 | 组织路径不创建可编辑的内部 Web 正文 | 重放、重复远端文档、错租户、错 Binding、登记失败和内部 Web 正文零写入测试 | scripts/quality and scripts/qa | EV-O3-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| O4 | 租户、正文权威、版本或失败状态不符合节点合同 | 未完成回读时不得向用户标记发布成功 | 错 Binding、错文档、空正文、超时、版本倒退、不可信链接和部分成功测试 | scripts/quality and scripts/qa | EV-O4-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| O5 | 证据身份不全、越级接受或验收写入候选 | 飞书是组织正文的唯一编辑权威 | 真实 Docx 编辑、版本变化、Web 只读、错账号、错组织和编辑冲突测试 | scripts/qa and evidence contract | EV-O5-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| O6 | 子候选身份不一致、依赖缺失或汇合后仍有双路径 | 组织全链在同一租户、Binding、文档和候选上闭环 | 联合合同、真实飞书、数据库、跨组织、错凭据、错容器和失败关闭测试 | scripts/quality and contract | EV-O6-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| S | 子候选身份不一致、依赖缺失或汇合后仍有双路径 | 所有文档能力只有一个路由入口 | 合同生成、能力矩阵、错容器、失败状态、跨租户和禁止旧 Writer 检查 | scripts/quality and contract | EV-S-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| C | 子候选身份不一致、依赖缺失或汇合后仍有双路径 | 只有一个候选，且不包含旧 Writer、双写权威或隐式回退路径 | 两次确定性重建、补丁清单、资源清单、晋升基线冲突、跨支线冲突和上游身份复算 | scripts/quality and contract | EV-C-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| DA | 证据身份不全、越级接受或验收写入候选 | 所有门禁对同一候选通过 | 受影响门禁、旧 Writer 源码搜索和候选哈希复算 | scripts/qa and evidence contract | EV-DA-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| DB | 证据身份不全、越级接受或验收写入候选 | 目标证据达到 physical-device/external-system | 真实浏览器、数据库、人工智能任务、飞书 Docx、编辑、回读和跨组织负例 | scripts/qa and evidence contract | EV-DB-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |
| DC | 证据身份不全、越级接受或验收写入候选 | 所有第二阶段完成条件成立且无第三阶段能力冒领 | 哈希、时间、身份、证据等级、无旧 Writer 和无范围冒领核对 | scripts/qa and evidence contract | EV-DC-CURRENT plus scoped red/green result | required before ACCEPTED | MCP unavailable; manually classified by Harness fields |

门禁用于在开发和验收阶段发现稳定失败类，不得成为运行时回退、兼容路径、灰度分流或第二事实来源。

## 当前证据身份

| Evidence ID | Task ID | Evidence level | Source revision | Artifact hashes | Environment | Runtime release | Actor role | Account/tenant | Device/browser | Mock/fixture | Observed at | Acceptance contract |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EV-A-CURRENT | A | source | user-request-stage2-structure-v2-2026-08-15 | a293eb32e09589ae2e60fd07362f20ce296b70725f55ad9368c6bc63e673f8b8, 3ffc4363c735a1ca2bed7b393e48516b4aa9a5494b1f9b30f952e8eff65ab6f5, 97000cc86e80993997153e0fb193ee877daea85c5695a60cf1645bf40596d471 | current Codex task and three local attachments | n/a | user and planning authority | n/a | n/a | false | 2026-08-15T20:37:42+08:00 | Phase-2 SSOT creation charter v2 |
| EV-A1-CURRENT | A1 | source | audit-stage1-hash-baseline-2026-08-15 | d5dad457861e413ff3963da568870be907495de50c33486810fa3dbdc0d92f98, 3ffc4363c735a1ca2bed7b393e48516b4aa9a5494b1f9b30f952e8eff65ab6f5, 97000cc86e80993997153e0fb193ee877daea85c5695a60cf1645bf40596d471, 558b40b11c399fd6f5d8b9e766562a07e7ecd8968c83df9a07a60496112659e6, 02c1cac2205c0115e3a3d34883175650238ad9d4f2f4a5ae837143222e45447c, 98baf1460664fedad729aeccd3f384d05c297c464ed689964caf628f1681f2cf, 76c4b2b2584333f3ceb3f43731ecbb749f75317018ead39f11729dff165f87d9, d99c5697e2bb4a1c7853e2d3695852eda11a8726301b2cd6cfc805e87f3a6a28, 26bf849657405fed887785e52665b97f2a5ae248e0591f7365f8d72e31c5f450, 7b3ebfc4653099da67694396ec3374ff697b8dd50b19fc9575cac31b271488b5, e8160365df3008a9c7124abe419255821890aa9e57f997a220cb77b99d38b448 | local source files; non-Git project root | n/a | main orchestrator read-only | n/a | n/a | false | 2026-08-15T20:37:42+08:00 | Phase-2 source baseline and cross-stage handoff v3 |
| EV-K-CURRENT | K | source | user-approved-three-stage-plan-2026-08-15 | a293eb32e09589ae2e60fd07362f20ce296b70725f55ad9368c6bc63e673f8b8, 3ffc4363c735a1ca2bed7b393e48516b4aa9a5494b1f9b30f952e8eff65ab6f5, d5dad457861e413ff3963da568870be907495de50c33486810fa3dbdc0d92f98 | current Codex task | n/a | user and product decision authority | n/a | n/a | false | 2026-08-15T20:37:42+08:00 | Phase-2 product decisions v2 |
| EV-F1-CURRENT | F1 | source | stage1-projection-pending | 98baf1460664fedad729aeccd3f384d05c297c464ed689964caf628f1681f2cf, 26bf849657405fed887785e52665b97f2a5ae248e0591f7365f8d72e31c5f450, 76c4b2b2584333f3ceb3f43731ecbb749f75317018ead39f11729dff165f87d9, d99c5697e2bb4a1c7853e2d3695852eda11a8726301b2cd6cfc805e87f3a6a28 | stage1 machine source; zero-write projection | n/a | pending upstream acceptance owner | n/a | n/a | pending | pending | 只有第一阶段 C1 ACCEPTED 且 I9 属于同一候选时才可接受本投影 |
| EV-F2-CURRENT | F2 | source | stage1-projection-pending | 98baf1460664fedad729aeccd3f384d05c297c464ed689964caf628f1681f2cf, 7b3ebfc4653099da67694396ec3374ff697b8dd50b19fc9575cac31b271488b5 | stage1 machine source; zero-write projection | n/a | pending upstream acceptance owner | n/a | n/a | pending | pending | 只有第一阶段 C3 ACCEPTED 才可接受本投影 |
| EV-F3-CURRENT | F3 | source | stage1-projection-pending | 98baf1460664fedad729aeccd3f384d05c297c464ed689964caf628f1681f2cf, e8160365df3008a9c7124abe419255821890aa9e57f997a220cb77b99d38b448 | stage1 machine source; zero-write projection | n/a | pending upstream acceptance owner | n/a | n/a | pending | pending | 只有第一阶段 DC2 ACCEPTED 才可接受本投影 |
| EV-B-CURRENT | B | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 不接受前端伪造租户、Binding、正文权威或路由授权 |
| EV-S1-CURRENT | S1 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 上下文全部由服务端事实生成 |
| EV-S2-CURRENT | S2 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 01_ 近期活动与其他资料使用同等租户边界 |
| EV-S3-CURRENT | S3 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 不允许第一阶段或能力实现绕过统一路由自选文档容器 |
| EV-S4-CURRENT | S4 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 任一必要步骤失败都不得返回发布成功 |
| EV-S5-CURRENT | S5 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 只读能力不产生文档或远端副作用 |
| EV-T1-CURRENT | T1 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 每个稳定失败类都有红绿门禁 |
| EV-C1-CURRENT | C1 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 个人工作区不读取任何组织共享资料 |
| EV-C2-CURRENT | C2 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 研究结论和来源引用可分离复核 |
| EV-C3-CURRENT | C3 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 模型建议不伪装为用户决定 |
| EV-C4-CURRENT | C4 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 个人任务只使用 personal_web/internal 上下文 |
| EV-C5-CURRENT | C5 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 个人路径不得创建任何全局飞书文档 |
| EV-C6-CURRENT | C6 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | Web 是个人正文的唯一编辑权威 |
| EV-C7-CURRENT | C7 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 发布包只引用已回读的个人正文版本 |
| EV-C8-CURRENT | C8 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 个人全链在同一候选上可重现 |
| EV-O1-CURRENT | O1 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 组织 A 不得读取组织 B 或个人资料 |
| EV-O2-CURRENT | O2 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 组织 A 不得使用组织 B 或部署级凭据 |
| EV-O3-CURRENT | O3 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 组织路径不创建可编辑的内部 Web 正文 |
| EV-O4-CURRENT | O4 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 未完成回读时不得向用户标记发布成功 |
| EV-O5-CURRENT | O5 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 飞书是组织正文的唯一编辑权威 |
| EV-O6-CURRENT | O6 | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 组织全链在同一租户、Binding、文档和候选上闭环 |
| EV-S-CURRENT | S | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 所有文档能力只有一个路由入口 |
| EV-C-CURRENT | C | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 只有一个候选，且不包含旧 Writer、双写权威或隐式回退路径 |
| EV-DA-CURRENT | DA | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 所有门禁对同一候选通过 |
| EV-DB-CURRENT | DB | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 目标证据达到 physical-device/external-system |
| EV-DC-CURRENT | DC | source | phase2-plan-v2 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 所有第二阶段完成条件成立且无第三阶段能力冒领 |

当前最高已证明等级是 `source`。目标 `physical-device/external-system` 只能由 DB 和 DC 对同一不可变候选的真实浏览器、数据库、人工智能任务、个人成果、飞书文档、账号、租户、Binding、设备和时间证据达到。

## 清除清单

| Scope | Type | Old or temporary item | Action | May remain | Evidence |
| --- | --- | --- | --- | --- | --- |
| 人工智能上下文 | client authority | 前端 tenant、Binding、正文权威或角色作为授权输入 | 服务端重建并稳定拒绝保留字段 | 否 | S1/T1/DA |
| 资料读取 | cross-tenant query | 01_近期活动全表读取及其他未限定资料查询 | 切到统一 ContextBuilder 租户范围并加负例 | 否 | S2/O1/DA |
| 个人正文 | legacy writer | 个人任务写入全局飞书或组织飞书 | C5 切到 personal_web/internal 后删除消费 | 否 | C5/C8/DA |
| 组织正文 | fallback | 部署级全局 app/secret/space/parent 与旧 Writer | O2 切到当前 Binding 世代解析后删除 | 否 | O2/O6/DA |
| 跨阶段写入所有权 | duplicate authority | 第一阶段 I7 创建、更新或路由人工智能文档 | S3 接受前核对 I7 仅保留资源发现、只读镜像、同步补水和可信打开 | 否 | F2/S3/DA |
| 组织 Web | duplicate authority | 可编辑内部 Web 正文或 Web/飞书双写 | 只保留飞书回读镜像和可信打开动作 | 否 | O3/O4/O5 |
| 成果状态 | false success | 写入成功但登记或回读失败仍标记发布成功 | 进入待处置并提供幂等续接 | 否 | S4/C5/O3/O4 |
| 能力调用 | bypass | 文档型能力自选容器或只读能力产生副作用 | 统一经过 WriterRouter 和副作用注册表 | 否 | S3/S5/T1 |
| 发布控制 | runtime alternate path | 长期双 Writer、旧新上下文权威、隐式回退或备用凭据 | 保留唯一候选；代码原子切换、数据库按合同恢复、飞书幂等补偿 | 只允许不改变权威的白名单、发布门、紧急停止、只读降级和外部写入停止 | C/DA/DB |
| 执行临时项 | temporary | prompt、PID/session 句柄、隔离端口和临时飞书文档 | 退出证据登记后按节点合同清理或审计保留 | 日志、return、ledger 与 Codex transcript 保留 | cleanup ledger |

## 禁止路径检查

第二阶段候选不得包含长期兼容接口、隐式回退、双写、旧新 Writer 并行、运行时备用凭据或把 Harness 门禁当成业务分支。前向数据库迁移可以保留必要的存储过渡；租户白名单、发布门、紧急停止、只读降级和外部写入停止开关可以保留，但不能改变唯一服务端上下文入口、唯一写入路由或正文权威。任何消费者不能在同一候选切换时，必须停在 C 之前修订迁移合同，不能用长期双路径绕过。

## 最终完成声明

只有 F1、F2、F3 三个跨阶段投影，共享汇合 S、个人汇合 C8、组织汇合 O6、唯一候选 C、静态验收 DA、真实外部系统验收 DB 和独立终验 DC 全部 ACCEPTED，才可声明第二阶段完成。任何第三阶段功能、模拟证据或单支线成功都不能替代该边界。
