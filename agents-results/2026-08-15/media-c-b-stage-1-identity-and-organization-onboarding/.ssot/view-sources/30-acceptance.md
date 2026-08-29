# 第一阶段节点合同与验收

## 完整节点合同

| Task ID | Business target | User | Inputs | Processing | Outputs | Tests | Acceptance | Completion definition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 第一阶段第 4 版章程 | 产品与交付负责人 | 原审计、三阶段拆分、两轮结构审查和六项用户决定 | 冻结两个发布增量、认证分流、即时成员接入、发布切换和证据边界 | 第一阶段第 4 版编排边界 | 范围、候选、决定和阶段互斥检查 | 第一阶段形成 1A 和 1B 两个独立候选 | 六项决定全部进入机器权威，个人认证合同关闭待决状态，即时成员接入纳入 1B |
| A1 | 输入、外部权威与运行器基线 | 规划者和实施者 | 审计、三份附件、Revision 11 权威和当前源码事实 | 复算校验值，核对正式状态、非 Git 条件、认证底层能力和运行器能力 | 可复现的来源与能力基线 | 路径、校验值、状态、接口与 wrapper 内容核对 | Revision 11 仅由 canonical 管理；五类运行配置尚未被证明 | 后续只消费列明权威且不虚构隔离能力 |
| K | 已接受的稳定产品决定 | 产品负责人、个人和组织用户 | 已确认三阶段边界、事实审计与六项局部决定 | 保留可信服务端授权、多工作区、MediaClaw B 身份、Pilot 优先和最小撤销 | 稳定决定记录第 2 版 | 决定覆盖、互斥和来源核对 | 只冻结已有明确证据的决定 | 六项局部决定由 K1 到 K6 独立承载并保持可局部失效 |
| K1 | 个人第一版认证方式 | 个人创作者 | 用户决定、个人工作区目标和现有平台账号能力 | 个人使用平台独立认证，不要求飞书；交付文档以云端内部成果为唯一保存和预览入口 | 个人认证决定第 1 版 | 飞书零依赖、云端成果归属、显式账号关联和跨认证负例 | 个人路径不调用飞书且不自动按邮箱或姓名合并身份 | 解锁 I1 与 I2；第二阶段个人文档继续写入云端内部成果 |
| K2 | 发布控制边界 | 发布、安全和支持负责人 | 用户的全量开放决定和单一路径要求 | 发布后直接向全部合格用户开放；只保留发布前门禁、全局紧急停止和外部写入停止 | 发布控制决定第 1 版 | 全量切换、停止开关、旧路径清除和无租户分批负例 | 不保留白名单、灰度、长期功能开关或双路径 | 解锁两个候选晋升 |
| K3 | 第一版成员接入方式 | 组织负责人和成员 | 用户的即时建立决定、飞书授权结果和现有成员身份表 | 成员第一次完成服务端飞书授权时即时建立；唯一外部成员字段使用 open_id | 成员接入决定第 1 版 | 服务端来源、唯一约束、幂等、跨租户、缺失和歧义存量测试 | 前端不得提交或覆盖 open_id，完整目录同步不进入 1B 完成门 | 解锁 P9 即时成员接入；Stage 1C 只保留目录成熟化交接 |
| K4 | 近期活动的数据归属 | 个人和组织用户 | 用户决定、现有全表读取事实与租户模型 | 近期活动属于租户私有数据；补齐归属、迁移存量并由服务端强制过滤 | 数据归属决定第 2 版 | 读取、写入、证据回填、冲突隔离、无证据隐藏和跨租户负例 | 可证明归属则回填；冲突进入隔离待处置；完全无证据则对所有租户不可见 | 解锁 I6 的近期活动合同 |
| K5 | 组织资源解析是否包含人工智能写入 | 个人和组织创作者 | 用户确认推荐方案、两阶段边界与当前全局飞书 Writer 事实 | I7 只含资源发现、只读镜像、同步补水和可信打开；第一阶段独立发布时关闭现有全局 Writer，第二阶段再由唯一 WriterRouter 接管 | 阶段所有权决定第 2 版 | 页面隐藏、API 稳定拒绝、旧全局 Writer 不可达和第二阶段引用核对 | 第一阶段不得创建或更新人工智能文档，也不得保留可调用的全局凭据写入路径 | 解锁 I7 和 I9；第二阶段只从关闭态切换到唯一 WriterRouter |
| K6 | 个人平台认证具体合同 | 个人创作者和账号支持人员 | K1 已接受方向、当前用户名密码与注册服务事实、旧 Media 密码接口隔离要求 | 冻结用户名或已验证邮箱加密码登录、二十四小时单次邮箱验证、三十分钟单次找回、八小时服务端不透明会话、安全 Cookie、跨站请求保护、存量账号和客服边界 | 个人认证具体决定第 1 版 | 注册待验证、验证链接重发撤销、登录枚举防护、找回链接过期与重放、密码策略、来源与账号双重限流、会话固定与撤销、跨站请求保护、旧接口不可达和显式身份关联检查 | 注册和验证成功均不自动登录；重置密码后撤销全部旧会话和未使用找回令牌；新合同不恢复旧 Media 密码接口，不按邮箱或姓名自动合并身份 | 解除 I1、I2 与 IL1 的决定阻塞；它们仍等待各自其他硬依赖 |
| B | 新功能共享合同汇编 | 产品、前后端和验收负责人 | A1 基线与 K 稳定决定；K1 到 K6 由各自消费节点直接引用 | 冻结不依赖局部选择的共享会话、工作区、Binding、Provision、错误和证据合同 | 1A 与 1B 的共享合同身份 | schema、OpenAPI、状态机和决定引用检查 | 不消费 R11，也不把局部决定扩散成全局失效 | 形成隔离开发基线且不改写 Revision 11 |
| GA1 | 运行环境人工初始化 | 执行环境负责人 | A1 能力基线和五类最小权限配置合同 | 由人工或运维建立实现、静态验证、外部测试、生产发布和独立只读五类配置；不启动 Codex worker | 五类配置定位与权限声明回执 | 配置存在、owner、最小权限、凭据隔离和禁止能力检查 | 每类配置都有可定位身份，且人工初始化本身不依赖任一配置 | 解除 G1 的运行层自举死锁 |
| G1 | 五类运行配置只读验证门 | 实施、验收、安全和发布负责人 | GA1 人工登记的五类配置 | 只读检查实现、静态验证、外部测试、生产发布和独立只读配置，并执行失败关闭负例 | 五类配置能力回执 | 最小写入根、临时数据库、凭据隔离、只读禁止写、外部身份和生产授权负例 | 五种配置均有真实启动命令、能力边界和失败关闭证据 | G1 不创建或修复配置；现有 danger-full-access wrapper 不构成隔离证明 |
| E11 | 第 11 次修订独立终验外部门 | 候选晋升负责人 | canonical D3A 状态与候选回执 | 只读投影 canonical D3A 是否正式接受，并绑定其候选身份和证据校验值 | E11 外部门回执 | 权威路径、状态、候选身份、校验值和零写入检查 | 只有 canonical D3A ACCEPTED 才投影为 ACCEPTED | 成为 CA 与 CB 的真实机器硬依赖，但不接管 R1-R4 |
| M1 | 无 Git 候选汇合协议 | 实施与候选汇合负责人 | B 合同、G1 运行配置和非 Git 开发基线 | 分别登记 development_base 与 promotion_base，实现节点补丁清单、文件 ownership、应用顺序、冲突检测和候选重建 | 可执行候选重建工具与清单 schema | 旧开发基线重放、同文件冲突、过期基线、漏补丁、顺序漂移、路径安全、未声明文件、目录覆盖、输入不变和两次确定性重建测试 | CA 必须以 E11 候选为 promotion_base，CB 必须以 DC1 候选为 promotion_base；冲突、过期、遗漏或不安全输入均失败关闭 | 工具、闭合清单 schema、隔离 fixture、32 项冻结测试和一次结构化主线程证据回执 |
| MA1 | Release 1A 迁移所有者 | 数据库和身份实施负责人 | B、M1、K4 与当前账号、会话、工作区和近期活动 schema | 独占 1A 迁移编号，建立 Session/Workspace 前向 schema，迁移 ordinary 旧值并处置近期活动租户归属 | Release 1A 前向迁移与回读合同 | 升级、重复执行、旧值、归属回填、冲突隔离、无证据隐藏和恢复测试 | 可证明归属则回填；冲突进入 quarantine/NEEDS_ATTENTION；完全无证据则对所有租户不可见 | I3 与 I6 只消费 MA1 已接受 schema，不自行创建迁移 |
| T1 | 共享合同与验收 Harness | 开发、QA、安全和发布负责人 | B 合同、G1、M1、K6 个人认证合同与其他稳定决定 | 维护 OpenAPI、schema、注册验证、登录、找回、会话、跨租户、外部回读和发布验收门禁 | 保护测试与人工验收矩阵 | 账号或邮箱枚举、待验证和停用状态、验证或找回令牌重放、旧链接、过期、双重限流、会话固定、重置后旧会话、跨站请求、伪造权威、跨租户、失败关闭和证据身份负例 | 每个稳定失败类有红绿门禁 | Harness 不成为运行时分支或第二事实源 |
| I1 | 统一登录、注册与找回入口 | 个人和组织创作者 | B 合同、K1 方向、K6 具体合同、平台账号认证和 Media 独立飞书认证 | 登录首页先选择个人或组织；个人分支提供用户名或已验证邮箱登录、自助注册、重发验证邮件和忘记密码，组织分支只进入飞书授权 | 可访问且边界明确的统一认证界面 | 键盘、移动端、表单校验、待验证与停用状态、链接失效、统一提示、跨认证和安全返回路径测试 | 个人分支不调用飞书，组织分支不暴露平台注册或密码找回，所有返回地址必须是站内允许目标 | 与 I2 独立开发，在 I3 前汇合 |
| I2 | 个人认证生命周期与组织意图绑定 | 所有登录用户 | B 合同、K1 方向、K6 具体合同、平台账号与会话、邮件发送能力、飞书授权状态和代码交换校验 | 实现待验证注册、二十四小时单次邮箱验证、用户名或已验证邮箱登录、三十分钟单次找回、八小时会话、会话轮换与撤销；组织流另行绑定随机数、过期、回调和一次性消费 | 个人认证生命周期与可验证的组织意图收据 | 重复账号、账号或邮箱枚举、未验证邮箱、停用账号、篡改、重放、过期、旧链接、双重限流、会话固定、重置后旧会话、跨站请求、错回调、跨认证和并发负例 | 浏览器不能自行激活账号、选择租户或改变认证权威；找回请求不泄露账号是否存在，注册和验证不自动登录，密码重置后所有旧会话和未使用找回令牌失效 | 个人与组织身份不得按邮箱或姓名自动合并 |
| IL1 | 显式身份关联 | 同时使用个人与组织工作区的用户 | 已登录平台账号、K6 具体认证合同、飞书 OAuth 结果和 I2 可信意图 | 用户主动发起绑定、完成飞书 OAuth、二次确认并把服务端 open_id 绑定到当前 user_id | ExplicitIdentityLink 与审计回执 | 邮箱或姓名自动匹配拒绝、重放、错账号、跨组织、重复绑定、撤销和并发测试 | 只有当前已认证用户的显式操作可建立关联 | 支持同一 user_id 拥有个人工作区并加入多个组织 |
| I3 | 会话与工作区解析 | 多工作区用户 | I1、I2、IL1、MA1、可信身份、Membership 和 Binding | 生成 SessionPrincipal v2 与 WorkspaceResolutionResult，消费 MA1 schema 并支持一个用户多归属 | 可信会话和工作区候选集合 | 多组织、无成员、重复 Binding、ordinary 旧值和刷新恢复测试 | 不持久化永久 user_type | 服务端是工作区、正文权威和成员角色唯一来源 |
| I4 | 个人工作区壳 | 个人创作者 | I3 的 personal_web 会话和 K1 云端成果边界 | 按服务端解析进入个人导航和云端成果入口，不在第一阶段交付内容生产 | PersonalWorkspaceShell | 刷新、空状态、云端预览入口、无权限和移动端测试 | 个人路径不进入组织资源或飞书文档 | 为第二阶段个人云端成果支线提供稳定入口 |
| I5 | 组织工作区壳 | 组织负责人和成员 | I3 的 organization_lark 会话 | 按成员与 Binding 状态展示工作台、安装恢复或注意状态 | OrganizationWorkspaceShell | 角色、空 Binding、停用、误导文案和移动端测试 | 页面不从前端 tenantId 或平台管理员推断权限 | 组织壳只展示服务端真实状态 |
| I6 | 服务端授权守卫 | 所有租户用户 | I3 会话、K4 租户私有决定、Membership、Binding 和现有 API | 统一资源范围守卫；消费 MA1 的近期活动归属结果并由服务端强制过滤 | 服务端授权与审计日志 | 伪造 tenantId、跨组织、隔离存量、完全无证据存量、平台管理员越权和撤销后访问负例 | 近期活动与其他私有资料使用同一租户边界 | 稳定拒绝越权且不泄露资源存在性；无证据记录对所有租户不可见 |
| I7 | 按组织绑定解析只读资源 | 组织用户和同步任务 | I3、I5、I6、K5 和当前 Binding | 只解析组织资源发现、Web 只读镜像、sync/hydrate 和可信打开动作 | BindingResourceResolver | 组织 A/B 资源、缓存、轮换、撤销和可信链接负例 | 本节点不接入任何人工智能 Writer | 缺失或撤销在外部调用前失败关闭 |
| I9 | 第一阶段人工智能写入关闭 | 个人和组织创作者 | K5、T1、当前全局 Writer 页面与 API 路径 | 隐藏第一阶段所有人工智能文档入口，并让页面绕过、直接 API 和旧任务重放统一失败关闭 | 稳定关闭态与错误合同 | 页面不可见、API 直调、旧链接、旧任务、全局凭据调用计数和跨租户负例 | 统一返回 capability_unavailable_until_writer_migration，且外部写入调用数为零 | Release 1A 独立发布后不存在可调用的全局 Writer；第二阶段由唯一 WriterRouter 接管 |
| I8 | 既有 Binding 试点闭环 | 已绑定组织成员 | I5 到 I7、I9、T1 和隔离 Pilot Binding | 登录、命中 Binding、进入工作台、发现资源、只读镜像、可信打开和刷新回读 | 同收据 Pilot 外部证据 | 真实外部正例、跨组织负例、撤销和刷新恢复 | 同一组织、Binding、资源和候选闭环 | 不调用人工智能 Writer，不把 Pilot 脚本变长期入口 |
| C1 | 身份与工作区汇合 | 个人和组织用户 | IL1、I3 到 I6 与 I9 的候选输出 | 汇合唯一会话、显式身份关联、两种工作区壳、授权守卫和 Writer 关闭态 | 身份工作区子候选 | 联合合同、角色矩阵和浏览器回归 | 个人与组织可信分流及负例通过 | 接受后可移交第二阶段个人支线 |
| C2 | 既有组织 Pilot 汇合 | 组织 Pilot 用户 | I8 同收据证据 | 核对身份、Binding、只读资源与打开动作未跨租户 | Pilot 子候选 | 独立证据复核和候选身份核对 | Pilot 正负例绑定同一候选 | 接受后解锁自助组织接入 |
| CA | Release 1A 候选汇合 | 个人、既有组织用户和发布负责人 | E11、C1、C2、T1、M1 与 K2 | 由 M1 确定性脚本把全部 1A patch 重放到 E11 绑定的 promotion_base | 哈希绑定的 Release 1A 候选 | 两次确定性重建、补丁清单、冲突、受影响测试和 E11 硬边复算 | R11 只在候选晋升时成为硬门；不得继续使用 development_base 直接晋升 | 候选冻结后修改必须重建并重跑 DA1 |
| DA1 | Release 1A 静态与合同验收 | 发布负责人 | CA 不可变候选 | 用静态验证配置在可写临时目录和临时数据库运行构建、合同、迁移、跨租户、密钥和清理门禁 | Release 1A 静态证据包 | 受影响门禁和候选哈希复算 | 全部门禁对同一候选通过 | 禁止修改候选、生产数据库和外部系统；失败返回所属节点并重建候选 |
| DB1 | Release 1A 生产与外部验收 | 个人和既有组织用户 | DA1 候选、批准窗口和生产发布配置 | 原子切换代码身份；按前向迁移恢复合同处理数据库；执行 Pilot 外部回读 | Release 1A 生产同收据证据 | 真实浏览器、数据库、Binding、外部资源、停止开关和恢复演练 | 不声称跨数据库与飞书原子回滚 | 外部动作只用幂等、回读、补偿和 NEEDS_ATTENTION |
| DC1 | Release 1A 独立终验 | 产品负责人、个人和既有组织用户 | DB1 同收据证据与原始合同 | 用真正只读配置核对范围、候选、生产、跨租户和恢复语义 | Release 1A 独立结论 | 哈希、身份、时间、证据等级和零写入核对 | 全部 1A 完成条件成立 | 接受后成为 Release 1B 的不可变基线 |
| MB1 | Release 1B 迁移所有者 | 数据库和组织接入实施负责人 | C2、M1、Provision 与即时成员约束 | 独占 1B 迁移编号，建立 installation、provision run、step receipt、Binding 世代和 JIT 成员身份约束 | Release 1B 前向迁移与回读合同 | 升级、重复执行、唯一约束、旧 Binding、并发即时成员和恢复测试 | 1B 迁移不占用或改写 MA1 的 1A 编号范围 | P1、P3、P9 和 P10 只消费 MB1 已接受 schema |
| P1 | 组织接入数据与状态机 | 组织管理员和支持人员 | C2 Pilot 模型、B 合同和 MB1 已接受 schema | 在 MB1 schema 上实现安装、授权、Binding、任务、步骤、回执、幂等和状态迁移 | Provision 模型 | 迁移、唯一约束、非法跳转、重试和恢复测试 | 覆盖 ACTIVE、NEEDS_ATTENTION、DISABLED 和 REVOKED | 旧 Binding 不被静默解释为已激活 |
| P2 | 飞书安装事件生命周期 | 新组织管理员 | P1 状态机和飞书事件合同 | 验签、解密、去重安装、启用、停用和卸载事件 | 事件服务与幂等回执 | 伪造、重放、乱序、重复和密文错误测试 | 事件只影响匹配安装身份 | 秘密不进入日志、命令行或前端 |
| P3 | 管理员确认与 owner 创建 | 飞书组织管理员 | P2 安装身份、MB1 schema 和 Media 用户身份 | 确认管理员资格和授权范围，原子创建 tenant、owner、Binding，并建立 owner 的 tenant_member_identity(binding_id, open_id) | 管理员授权、owner 与外部身份回执 | 非管理员、越权、过期、重复、跨组织、owner 重登和唯一约束测试 | 只有匹配组织管理员可确认；唯一约束至少为 (binding_id, open_id) | tenant、owner、Binding 与 owner 飞书外部身份一致可审计 |
| P5 | 组织资源初始化 | 组织负责人 | P3 Binding、I7 资源解析和飞书资源合同 | 幂等创建或发现 Wiki、父节点、应用目录和可信打开信息 | 资源步骤和 Binding 更新 | 已有资源、重复、配额、错凭据、部分成功和重试测试 | 每项资源都回读并绑定当前安装 | 不使用部署级全局父节点或凭据 |
| P6 | 可续接组织接入编排 | 组织管理员和支持人员 | P1、P2、P3、P5 与 T1 | 按租约、幂等键、检查点、退避和补偿推进 ACTIVE 或 NEEDS_ATTENTION | 持久化 Provision runner 与步骤回执 | 崩溃、租约过期、重复事件、部分外部成功、并发和恢复测试 | 刷新或重启后从回读步骤续接 | 飞书动作不宣称跨系统原子事务 |
| P7 | 接入状态与恢复页面 | 组织管理员和支持人员 | P6 状态、步骤、错误和恢复动作 | 显示真实进度、失败步骤、可重试动作和 NEEDS_ATTENTION | 状态与恢复界面 | 刷新、并发重试、越权、敏感信息和移动端测试 | 部分成功不得显示为 ACTIVE | 操作绑定当前安装、角色和幂等动作 |
| P8 | 最小停用与撤销 | 组织管理员、安全和支持负责人 | P6 活跃安装、I7 缓存和生命周期事件 | 停用 Binding、撤销凭据、冻结外部写入和成员访问并保留审计 | DISABLED 或 REVOKED 回执 | 停用、卸载、旧 worker、缓存凭据、重放和审计保留测试 | 撤销后不能再访问或写入 | 复杂删除和迁移仍留第三阶段 |
| P9 | 成员首次授权即时建立 | 首次进入组织工作区的普通成员 | K3、I2、P3、MB1、T1、服务端飞书 tenant_key 与 open_id | 用活跃 Binding 定位租户，并以服务端授权结果中的 open_id 幂等创建或复用用户、成员关系和外部身份 | 即时成员接入服务与回执 | 前端伪造、重复回调、owner 已存在、跨租户、撤销 Binding、缺失 open_id、歧义存量和并发首次登录测试 | 唯一外部成员字段是服务端 open_id，数据库唯一约束至少为 (binding_id, open_id) | 只处理尚不存在的普通成员；不按邮箱或姓名自动合并，不依赖完整目录同步 |
| P10 | 最小成员失效 | 组织负责人、离职成员和安全支持人员 | I3、P3、P9、T1 与组织成员状态 | 组织访问租约最长 15 分钟；刷新时复核外部身份和成员状态；owner 可手动停用单个成员并立即撤销其现有组织会话 | 成员停用服务与会话撤销回执 | 过期刷新、外部身份失效、owner 停用、现有会话、并发请求、恢复和跨组织负例 | disabled 成员的已有会话立即失效，且不能通过旧 token 刷新 | 不依赖完整目录同步即可满足第一版离职安全底线 |
| C3 | Release 1B 组织接入汇合 | 新组织管理员和普通成员 | P7、P8、P9、P10 与真实接入证据 | 核对安装、确认、owner 外部身份、Binding、资源、ACTIVE、成员即时建立、单成员失效、恢复和撤销 | Provision 子候选 | 联合状态机、外部系统、open_id、会话失效、跨安装和补偿测试 | 新组织 owner 可自助接入，普通成员可首次授权进入且可被安全停用 | 完整目录同步不是本节点依赖 |
| CB | Release 1B 候选汇合 | 新组织管理员和发布负责人 | DC1、E11、C3、T1、M1 与 K2 | 由 M1 确定性脚本以 DC1 候选为 promotion_base 重放全部 1B patch | 哈希绑定的 Release 1B 候选 | 两次确定性重建、补丁清单、冲突、迁移顺序和 E11 硬边复算 | 不得绕过 DC1、E11 或带入 Stage 1C 目录成熟化 | 候选冻结后修改必须重建并重跑 DA2 |
| DA2 | Release 1B 静态与合同验收 | 发布负责人 | CB 不可变候选 | 用静态验证配置在可写临时目录和临时数据库运行构建、状态机、迁移、跨租户、密钥和清理门禁 | Release 1B 静态证据包 | 受影响门禁、补偿合同和候选哈希复算 | 全部门禁对同一候选通过 | 禁止修改候选、生产数据库和外部系统；失败返回所属节点并重建候选 |
| DB2 | Release 1B 生产与飞书验收 | 新组织管理员和普通成员 | DA2 候选、批准窗口和生产发布配置 | 原子切换代码身份；数据库前向迁移并按恢复合同处理；飞书步骤幂等执行、回读和补偿 | Release 1B 生产同收据证据 | 安装、管理员确认、资源、成员首次授权、恢复、撤销、停止开关和 NEEDS_ATTENTION | 不声称跨系统原子回滚 | 每个外部步骤都有回读、补偿和人工处置状态 |
| DC2 | Release 1B 独立终验 | 产品负责人、新组织管理员和组织用户 | DB2 同收据证据与 DC1 基线 | 用真正只读配置核对范围、候选、生产、飞书、补偿和排除项 | Release 1B 独立结论 | 哈希、身份、时间、证据等级和零写入核对 | 1A 与 1B 必需完成条件全部成立 | 仅 DC2 ACCEPTED 可宣告第一宏观阶段必需交付完成 |
| DA | 第一宏观阶段静态汇总投影 | 规划、发布和审计负责人 | DC1 与 DC2 的已接受结论 | 零写入核对两个发布增量的候选身份、版本、证据索引和排除项 | 宏观阶段静态汇总记录 | 上游状态、候选校验值、版本元组和证据引用一致性检查 | 只汇总既有结论，不重跑或阻塞 1A、1B 发布 | 结构兼容投影不成为新的发布完成门 |
| DB | 第一宏观阶段回归汇总投影 | 规划、发布和审计负责人 | DA 静态汇总记录 | 零写入核对 1A 与 1B 证据之间没有候选、租户、恢复或清理语义冲突 | 宏观阶段回归汇总记录 | 跨发布身份、证据复用、恢复边界和清理清单一致性检查 | 不产生新的生产或外部系统动作 | 只形成后置汇总，不改变两个发布增量的验收结论 |
| DC | 第一宏观阶段完成状态投影 | 产品、规划和审计负责人 | DB 回归汇总记录 | 零写入确认 1A 与 1B 已分别终验，并登记完整目录成熟化仍属后续可选发布 | 宏观阶段完成状态投影 | 状态、证据等级、排除项和无新增业务门检查 | 不得把本投影解释为第三个发布候选 | 只兼容统一阶段报告，不阻塞或替代 DC1、DC2 |

## 首席执行官验收走查表

这张表把第一阶段的正式验收翻译为可现场演示的业务流程。产品页面是首席执行官可以直接看到并操作的入口；发布验收记录是由发布负责人打开、供首席执行官核对的受控证据入口，不把它包装成普通用户页面。每一项只有在“应该看到的结果”和“必须拒绝的情况”都得到同一版本、同一环境的证据支持时才可通过。

当前已存在代码发布与运行稳定性回执，但第一阶段仍未正式接受：真实邮件、飞书、认证浏览器/设备、数据库恢复、独立终验和第 11 次修订外部门尚未全部关闭。因此，本表描述的是首席执行官应要求演示的验收目标，不是已全部上线或已全部通过的声明。

| 顺序 | 首席执行官进入的页面或验收入口 | 在页面上完成什么 | 应该看到的业务结果 | 系统必须拒绝的情况 | 对应节点 |
| --- | --- | --- | --- | --- | --- |
| 1 | 登录首页的“个人创作者 / 组织成员”选择，以及认证安全验收记录 | 由验收负责人用真实浏览器分别进入两条登录路径，并演示错误密码、错误组织和跨组织访问的处理 | 两种身份各自进入正确的登录流程；错误提示一致、不过度暴露账号或组织信息；个人与组织之间不会串数据 | 任何错误租户、错误角色、伪造会话或跨组织访问都不能进入工作区；不能只用本地测试报告代替正式验收 | `T1` |
| 2 | 个人工作区、组织工作区，以及历史收藏或旧链接指向的旧人工智能写作入口 | 从当前页面、旧链接、旧接口和旧任务记录分别尝试打开或继续写作 | 页面中不再出现第一阶段的人工智能文档写作入口；系统明确告知该能力尚未迁移，且不会新建或修改任何文档 | 绕过页面直接调用旧接口、使用旧链接或重放旧任务，都不得写入云端文档或飞书资源 | `I9` |
| 3 | 登录首页、创建个人账号、验证邮箱、找回密码、设置新密码页面和个人工作区 | 用一个真实可收信的账号完成注册、验证邮箱、登录、找回密码、重置密码、退出登录和刷新会话 | 账号验证后才可登录个人工作区；重置密码后旧设备会话失效，使用新密码才能再次进入；全程使用真实浏览器和邮件，不使用模拟数据 | 注册或验证后自动登录、过期或已使用链接再次生效、未验证账号找回成功、退出后的旧会话仍可进入，均必须失败 | `I1`、`I2` |
| 4 | 已登录后的“关联飞书成员”入口 | 当前平台账号主动发起飞书授权，确认所关联的具体成员，并演示解除关联 | 页面清楚显示“哪个平台账号关联到哪个飞书成员”；关联和解除均有可追溯记录 | 仅因姓名或邮箱相同就自动合并账号、把授权结果关联到错误账号或错误组织、重放旧授权，都必须失败 | `IL1` |
| 5 | 登录首页，以及同一用户的个人工作区和组织工作区 | 用同一用户分别通过个人登录和组织飞书授权进入系统；再尝试进入不属于自己的组织或以不匹配角色访问 | 个人入口只显示个人云端成果；组织入口只显示该组织的协作资源；两种工作区清楚分开 | 个人会话进入组织资源、组织会话进入个人空间、错误组织或错误角色获得内容，均必须被拒绝 | `I3`、`C1` |
| 6 | 个人工作区首页与账号安全入口 | 验证邮箱后首次进入个人工作区；刷新页面读取既有内容；尝试绕过删除保护；退出或撤销会话后再次刷新 | 个人工作区只为该个人账号建立一次，云端成果可安全读取；撤销后不能继续使用旧会话；关键内容不会被无确认或无权限地删除 | 重复建立个人工作区、无权限删除、删除保护被绕过、会话撤销后仍可读取个人资料，均必须失败 | `I4`、`I5`、`I6` |
| 7 | 组织工作区中的资源列表、只读预览和“可信打开”入口 | 以已绑定组织成员身份查看资源列表，打开只读镜像，再从可信入口打开原资源；随后撤销组织绑定并重试 | 只看到当前组织自己的资源；预览为只读；撤销前后状态清楚可见 | 组织 A 读取组织 B 的资源、未绑定成员查看资源、撤销后继续打开或继续访问缓存资源，均必须失败 | `I7`、`I8` |
| 8 | 同一个待发布版本中的个人登录流程和既有组织试点工作区 | 由独立验收人用同一版本号依次走完个人身份流程与既有组织试点流程，并核对两条流程的证据 | 个人用户和既有组织用户都能在同一待发布版本中完成各自闭环；独立验收人给出明确结论 | 用不同版本、不同环境或仅单条流程的证据拼接成“已汇合”，不得通过 | `C1`、`C2` |
| 9 | 发布验收记录、服务健康检查和恢复演示入口（非普通用户页面） | 发布负责人演示数据库升级后的业务回读、服务健康、固定版本发布、恢复步骤和回滚/前向修复演练 | 首席执行官能核对“发布的是哪一版、服务是否健康、数据是否正确、出现问题如何恢复”；生产行为与验收记录一致 | 只展示本地测试、不提供数据库回读或恢复证据、发布版本不可追溯、健康检查失败仍宣告发布，均不得通过 | `MA1`、`CA`、`DA1`、`DB1`、`DC1` |
| 10 | 第 11 次修订的只读终验记录 | 核对原规范中 `D3A` 的正式结论，并比对它与本次待发布版本的唯一版本校验值 | 只有原规范的独立终验已正式接受，且两个版本身份完全对应时，后续发布才可继续 | `D3A` 未正式接受、证据不完整、版本校验值不一致，或尝试在本阶段改写原规范结论，都必须阻止发布 | `E11` |
| 11 | 飞书安装页、组织接入向导、管理员确认页、接入状态与恢复页、成员首次进入页和撤销入口 | 用真实飞书组织完成安装；由组织管理员确认；建立组织负责人和绑定关系；初始化资源；让普通成员首次授权进入；再演示恢复与撤销 | 新组织可自行完成接入，管理员看到真实进度和异常说明；资源初始化完成后，普通成员首次进入即建立自己的组织身份；撤销后访问被关闭 | 非管理员确认、伪造成员身份、跨组织复用、重复或乱序事件被当成成功、撤销后仍可访问，均必须被拒绝或进入待人工处理状态 | `P1`-`P10`、`C3` |
| 12 | 发布验收记录、飞书组织接入全流程和独立终验记录（非普通用户页面） | 在同一固定版本上复核组织接入的静态检查、真实飞书演示、生产发布、恢复与独立终验 | 首席执行官能看到新组织从安装到成员进入、撤销和恢复的完整闭环已在同一版本中通过；发布后所有合格用户走唯一新路径 | 绕过第一批发布终验、跳过真实飞书回读、把跨数据库与飞书的恢复说成一次原子回滚，或以目录同步缺失为由掩盖接入失败，均不得通过 | `CB`、`DA2`、`DB2`、`DC2` |

## 第一阶段正式验收矩阵

| Acceptance area | Required positive path | Required negative path | Owning nodes | Completion evidence |
| --- | --- | --- | --- | --- |
| Revision 11 外部门 | E11 只在 canonical D3A ACCEPTED 且候选回执绑定校验值时接受 | 本包不得调度 R1-R4 或写 canonical 证据 | E11 到 CA/CB 的机器硬边 | canonical D3A 状态和候选身份只读回执 |
| 运行配置与无 Git 汇合 | 五类配置通过负例且候选可确定性重建 | danger-full-access 文字合同、目录 overlay 或冲突覆盖必须拒绝 | GA1/G1/M1 | 配置能力回执、patch manifest 与重建哈希 |
| 个人注册与邮箱验证 | 提交唯一用户名、唯一邮箱和合格密码后进入待验证状态；最新验证链接在二十四小时内单次激活账号并幂等建立个人工作区 | 重复邮箱、重复用户名、过期链接、旧链接、重放、并发激活、弱密码或注册后直接取得完整会话必须拒绝 | K6/I1/I2/T1 | 真实浏览器、受控邮件投递、账号状态、令牌摘要和个人工作区读回 |
| 个人登录与会话 | 有效账号使用用户名或已验证邮箱加密码登录；服务端轮换会话并签发八小时安全 Cookie | 待验证或停用账号、错误凭据、会话固定、跨站请求、个人流程调用飞书、进入组织资源或前端租户编号授权必须拒绝 | K1/K6/I1-I4/T1/C1 | 真实浏览器、服务端会话、安全 Cookie、跨站请求保护与飞书零调用读回 |
| 个人找回与密码重置 | 找回请求始终统一应答；有效且邮箱已验证的账号收到三十分钟单次最新链接；重置后返回登录入口 | 账号枚举、未验证邮箱投递、过期、旧链接、重放、限流绕过、旧会话或旧找回令牌继续有效必须拒绝 | K6/I1/I2/T1/C1 | 受控邮件、令牌摘要、密码凭据版本、全部会话与找回令牌撤销读回 |
| 存量账号与客服边界 | 既有账号从新个人入口使用用户名登录，完成邮箱验证后才可用邮箱登录或找回；客服只能重发标准邮件或撤销会话 | 旧邮箱自动变成已验证、客服读密码或生成临时密码、绕过验证、恢复旧 Media 密码接口或按邮箱姓名合并身份必须拒绝 | K6/I1/I2/IL1/T1 | 存量迁移夹具、客服权限负例、旧接口 `404` 与身份关联审计回执 |
| 既有组织 Pilot | 选择组织、命中 Binding、组织工作台、只读镜像、可信打开和回读 | 组织 A 不得解析组织 B 资源，也不得调用 Writer | I5-I8/C2 | 同一 Binding、资源和候选的真实飞书收据 |
| Release 1A | CA 静态通过、生产推广、Pilot 外部通过和独立终验 | 没有 canonical D3A、K2 或恢复合同必须拒绝 | CA/DA1/DB1/DC1 | 哈希绑定的生产与外部同收据证据 |
| 新组织 Provision | 安装、管理员确认、tenant/owner/Binding、资源、普通成员首次授权和 ACTIVE | 非管理员、重放、乱序、跨安装、伪造 open_id 和中断均失败关闭或续接 | P1-P3/P5-P9/C3 | 隔离飞书组织全流程与成员首次进入收据 |
| 成员即时建立 | 从服务端飞书授权结果取得 open_id，并幂等创建或复用成员关系 | 前端 open_id、邮箱或姓名合并、跨租户复用、歧义存量和撤销 Binding 必须拒绝 | K3/I2/P3/P9/C3 | 同一 tenant_key、open_id、Binding 与候选的服务端回执 |
| 最小撤销 | 停用、撤销凭据、冻结写入和成员访问、保留审计 | 撤销后缓存凭据或旧 worker 不得继续写 | P8/C3 | REVOKED 读回和写入拒绝 |
| 安全 | Session、Membership、Binding 与服务端 open_id 一致时访问 | 伪造 tenantId/open_id、个人调组织、A 调 B、平台 admin 越权均拒绝 | I2/I6/I7/P9/T1 | 服务端负例、秘密扫描和审计日志 |
| Release 1B | CB 静态通过、生产推广、飞书接入通过和独立终验 | 跨系统原子回滚声称、目录同步硬依赖或绕过 DC1 必须拒绝 | CB/DA2/DB2/DC2 | 哈希绑定的生产与飞书同收据证据 |
| 目录成熟化 | 按 Stage 1C 交接另建独立发布合同后实现 | 目录成熟化缺失不得阻塞 P9、CA、CB 或 DC2 | K3 与 Stage 1C 交接 | 未来独立发布证据 |

## 当前证据身份

| Evidence ID | Task ID | Evidence level | Source revision | Artifact hashes | Environment | Runtime release | Actor role | Account/tenant | Device/browser | Mock/fixture | Observed at | Acceptance contract |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EV-A-CURRENT | A | source | user-request-and-structure-review-2026-08-15 | a293eb32e09589ae2e60fd07362f20ce296b70725f55ad9368c6bc63e673f8b8, 3ffc4363c735a1ca2bed7b393e48516b4aa9a5494b1f9b30f952e8eff65ab6f5 | current Codex task and two local attachments | n/a | user and planning authority | n/a | n/a | false | 2026-08-15T20:37:42+08:00 | Phase-1 SSOT restructuring charter v4 |
| EV-A1-CURRENT | A1 | source | audit-and-canonical-hash-baseline-2026-08-15 | d5dad457861e413ff3963da568870be907495de50c33486810fa3dbdc0d92f98, 0f621ee97d66fb3ec4be7b8be7bc306fda4a269f81382ad232afb1187c16ac47, a30bdf105e5b2b8367ff19603e19a28ad787e9743fef033e10a270a65d53d5db, 97000cc86e80993997153e0fb193ee877daea85c5695a60cf1645bf40596d471 | local source files; non-Git project root | n/a | main orchestrator read-only | n/a | n/a | false | 2026-08-15T20:37:42+08:00 | Phase-1 source and runner baseline v4 |
| EV-K-CURRENT | K | source | user-approved-three-stage-plan-2026-08-15 | a293eb32e09589ae2e60fd07362f20ce296b70725f55ad9368c6bc63e673f8b8, d5dad457861e413ff3963da568870be907495de50c33486810fa3dbdc0d92f98, 3ffc4363c735a1ca2bed7b393e48516b4aa9a5494b1f9b30f952e8eff65ab6f5 | current Codex task | n/a | user and product decision authority | n/a | n/a | false | 2026-08-15T20:37:42+08:00 | Phase-1 stable product decisions v2 under plan v4 |
| EV-K1-CURRENT | K1 | source | user-six-decisions-2026-08-15 | a293eb32e09589ae2e60fd07362f20ce296b70725f55ad9368c6bc63e673f8b8, 3ffc4363c735a1ca2bed7b393e48516b4aa9a5494b1f9b30f952e8eff65ab6f5, 97000cc86e80993997153e0fb193ee877daea85c5695a60cf1645bf40596d471 | current Codex task; user decision message | n/a | user and product decision authority | n/a | n/a | false | 2026-08-15 | 个人路径不调用飞书且不自动按邮箱或姓名合并身份 |
| EV-K2-CURRENT | K2 | source | user-six-decisions-2026-08-15 | a293eb32e09589ae2e60fd07362f20ce296b70725f55ad9368c6bc63e673f8b8, 3ffc4363c735a1ca2bed7b393e48516b4aa9a5494b1f9b30f952e8eff65ab6f5, 97000cc86e80993997153e0fb193ee877daea85c5695a60cf1645bf40596d471 | current Codex task; user decision message | n/a | user and product decision authority | n/a | n/a | false | 2026-08-15 | 不保留白名单、灰度、长期功能开关或双路径 |
| EV-K3-CURRENT | K3 | source | user-six-decisions-2026-08-15 | a293eb32e09589ae2e60fd07362f20ce296b70725f55ad9368c6bc63e673f8b8, 3ffc4363c735a1ca2bed7b393e48516b4aa9a5494b1f9b30f952e8eff65ab6f5, 97000cc86e80993997153e0fb193ee877daea85c5695a60cf1645bf40596d471 | current Codex task; user decision message | n/a | user and product decision authority | n/a | n/a | false | 2026-08-15 | 前端不得提交或覆盖 open_id，完整目录同步不进入 1B 完成门 |
| EV-K4-CURRENT | K4 | source | user-six-decisions-2026-08-15 | a293eb32e09589ae2e60fd07362f20ce296b70725f55ad9368c6bc63e673f8b8, 3ffc4363c735a1ca2bed7b393e48516b4aa9a5494b1f9b30f952e8eff65ab6f5, 97000cc86e80993997153e0fb193ee877daea85c5695a60cf1645bf40596d471 | current Codex task; user decision message | n/a | user and product decision authority | n/a | n/a | false | 2026-08-15 | 可证明归属则回填；冲突进入隔离待处置；完全无证据则对所有租户不可见 |
| EV-K5-CURRENT | K5 | source | user-six-decisions-2026-08-15 | a293eb32e09589ae2e60fd07362f20ce296b70725f55ad9368c6bc63e673f8b8, 3ffc4363c735a1ca2bed7b393e48516b4aa9a5494b1f9b30f952e8eff65ab6f5, 97000cc86e80993997153e0fb193ee877daea85c5695a60cf1645bf40596d471 | current Codex task; user decision message | n/a | user and product decision authority | n/a | n/a | false | 2026-08-15 | 第一阶段不得创建或更新人工智能文档，也不得保留可调用的全局凭据写入路径 |
| EV-K6-CURRENT | K6 | source | user-decision-k6-2026-08-16 | a293eb32e09589ae2e60fd07362f20ce296b70725f55ad9368c6bc63e673f8b8, 3ffc4363c735a1ca2bed7b393e48516b4aa9a5494b1f9b30f952e8eff65ab6f5, 97000cc86e80993997153e0fb193ee877daea85c5695a60cf1645bf40596d471 | current Codex task; user decision message | n/a | user and product decision authority | n/a | n/a | false | 2026-08-16 | 注册和验证成功均不自动登录；重置密码后撤销全部旧会话和未使用找回令牌；新合同不恢复旧 Media 密码接口，不按邮箱或姓名自动合并身份 |
| EV-B-CURRENT | B | local-runtime | sha256:a5e34064d554fe6a11b93f608b23202e737b40eac9dcedc4388c18dc952710be | sha256:6d325c6736389b7dde8eb1e5ef0c91e166d4a68578d05324dad3cadf294af9d0, sha256:c1fbb5b6655ff2f4bb6f90152a8ab6705d77f6d2744744014f99e0d9dafa01a8, sha256:52f6f4f8ec3e4d4ac4111b455424aa6ac52f00427146defc7eb09b37e22b8bea, sha256:e70fdecba336c7e42ae5e9a1004e9187fea29c3fe03d90e0d6dd9f77bf42fd0a | local macOS non-Git merge-candidate-v4 backend with existing Python virtualenv | n/a | Luna worker with supervisor acceptance | n/a | n/a | false | 2026-08-16T07:59:05Z | B-retry-2 frozen contract validation; 7 passed |
| EV-GA1-CURRENT | GA1 | source | sha256:ad3af167b07dd0287ea1f22dd3f90d893d7cffee16aea5082303d7e7b331e0ed | sha256:30f15c7c9999b9d2100906aaf364e38412adeec60fb7a43263f6de6f363b5bb7, sha256:8094d5a1acaae50f67e72cf679ee2b6666e4132e623ac018350156a9b5397707 | local runner profile registry and absolute launchers | n/a | execution environment owner | n/a | n/a | false | 2026-08-16T15:10:35+08:00 | 每类配置都有可定位身份，且人工初始化本身不依赖任一配置 |
| EV-G1-CURRENT | G1 | local-runtime | sha256:ad3af167b07dd0287ea1f22dd3f90d893d7cffee16aea5082303d7e7b331e0ed | sha256:30f15c7c9999b9d2100906aaf364e38412adeec60fb7a43263f6de6f363b5bb7, sha256:a9ee7f1b32c33755eda946df8cc9ed7e6edd181742defd955777766dd52ea8c9 | local runner profile capability probes | n/a | outer orchestrator deterministic verification | n/a | n/a | true | 2026-08-16T07:36:47.577035+00:00 | 五种配置均有真实启动命令、能力边界和失败关闭证据 |
| EV-E11-CURRENT | E11 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 只有 canonical D3A ACCEPTED 才投影为 ACCEPTED |
| EV-M1-CURRENT | M1 | local-runtime | stage1-no-git-rebuild-v4 | sha256:4c0cfef4e24625dfb671fe4736a04725432d41a4243d0be1f04d5303135a42a2, sha256:ad8aa24bf7481da33b26bf05e7dad37dec4ba2e9b4b2dbbf0cd9c73a1a94e7ce, sha256:11c13d6197b1fa61735f6d81ee8f78e92e38a2dd2ab1d9b48d0498aaded9cc09, sha256:05b724f6d4b252705a8ae4d6899ec8eae4867ff3b09f4543b12cef5e9269115b, sha256:dece265db4b42a0ddba574932c2916aaa1efa5604b45f0243cb648e5265c4eb0 | local non-Git project root with existing merge-candidate-v4 Python virtualenv | n/a | main orchestrator deterministic local execution | n/a | n/a | true | 2026-08-16T18:08:43+08:00 | M1-remediation-1 frozen validation; 32 passed |
| EV-MA1-CURRENT | MA1 | local-runtime | stage1-ma1-migration-isolated-root-2026-08-17 | sha256:61e739379c9e81d3d1a5bb7239e3695d1d709e2109eb1fd816b078bacc6da475, sha256:6dd8c8034b8a3546c56bc53ac3454843f147ac35a3619037fa2d051de1efd5cd, sha256:1d8dc2dc6516bef8007d4f2903c28495bb29cab7cfb1ca8a38658f8321051de0, sha256:dc2dea9a677fb77f0db3c8c31f27aff04cefbfeac43e658fc402831510125943, sha256:8056704a4c314bd0965767d65fe0499f9b90e66820289be1581d8d7f33bcc28a | local macOS isolated stage1-ma1-migration root with existing Python virtualenv | n/a | main orchestrator deterministic local execution | n/a | n/a | true | 2026-08-17T00:47:00+08:00 | MA1 frozen validation receipt EV-MA1-RERUN-20260817; 27 passed, 3 subtests passed |
| EV-T1-CURRENT | T1 | local-runtime | stage1-t1-auth-routes-locked-2026-08-17 | sha256:775ddfa6fcfb5e04a931dfa5e03dfd08891365fc4491c16d8a6e49ede1c58611, sha256:13219785db38866e00387d4ce09553ef05c34ab21b5c6a4fbf9709f583d73009, sha256:6fa14dc5655ac77bd1a78bad0a132ff8ed81ac2fca8aafb2d5bb69448086f236, sha256:80759c80b90339095a255c5c1d6a831e4fbcd74e3e598fcd7a1ec8fe57d64e8d, sha256:da89e5418b471a255f0dc20e08085f7470f18875aefe1bb57453bca106019fac, sha256:d149a683ee0ef2825e5151005d0679f0d883e62b5810aeede637a5c87e7e1e6d | local macOS isolated stage1-t1 root with existing Python virtualenv | n/a | main orchestrator deterministic rerun | n/a | n/a | true | 2026-08-17T00:01:14+08:00 | 共享路由验收合同（T1-AUTH-ROUTES）运行 20260817T031500Z-local-final-f4a5b6；T1 15 passed；路由一致性 GREEN；保护基线 LOCKED；正式接受待完成 |
| EV-I1-CURRENT | I1 | local-runtime | stage1-i1-isolated-root-2026-08-17 | sha256:7ace5ecb3b9a14d8bcf4cd7c86bebfc8892857a31b8edfd929a3c3f00041b12d, sha256:1ed4259a8ab4f492a1d323c4c4867f061843c0d4b1fb4bb2ea02533c9836f6e2, sha256:12d4309211434786d403d7c987633d9a85bbe49632a3cdbd4e9e5325d570a1c6, sha256:84d20bf30aa862c6efb90a56baf04bab3e0db96c4c2fb3249c162c1a5b1eba5d, sha256:b2126f3786da69e7fc113504c89667a9d4308d41776399957531e98f415cfa8e, sha256:864097f80bcf2273971491f84ea92252a82df9fc79c8ec12947e56a94bfe725c, sha256:a428cd86b19fbd0f89bb72460d441fa27ca066bd45a591845d03e3e2cf32aa4b, sha256:45dffceaada3e9f9111ce2dfa5ed047e20fb5e7655710313951a7ccbe9407d4c, sha256:4410457643280b3ac967bcd06971e2300e1499ed15edb2c6677fd38d103ac728, sha256:d26f6c48108286e5647535994536066fa9f6db0d029aa8b1ff2d355b3ca28c9a, sha256:5b61cf52ae421e1dbe1d37d34c7c43ca3c492224aa28758c4ae40eb265d24206, sha256:2d2a10a68bee189af24811ce4f314d60ae7af7450f61afb4f37ba8c849036c41, sha256:f3dd4e9e3671ff2d774938b96bfacf083bdfaad454ee19d8effc9d5b96541dd7, sha256:54a342e69719f97a20bf5968e8ca8aaf5e4384d13abe347569d6491e7f48ab09 | local macOS isolated stage1-i1 root with existing Node dependencies | n/a | main orchestrator deterministic local execution | n/a | n/a | true | 2026-08-17T00:47:00+08:00 | I1 frozen validation receipt EV-I1-RERUN-20260817; stage1_identity_entry=PASS; build:media passed |
| EV-I2-CURRENT | I2 | local-runtime | stage1-i2-auth-routes-locked-2026-08-17 | sha256:ca419df8c77318d4ce15d873add236248be26147225363ed29e5731cb8d09013, sha256:759cdd8c311e19e47cc291f9c97b22be7892a314d1f7b62bc186476c246a24bf, sha256:6805c5fba5492916bc079bce87e4ed4c1633ab0c649f37d8fc0bf81a4353438f, sha256:d149a683ee0ef2825e5151005d0679f0d883e62b5810aeede637a5c87e7e1e6d, sha256:1330937b7f5501fd1c05140118a20ae7f789eb3d74ee474d9828c3c647a8785d | local macOS isolated stage1-i2 root with existing Python virtualenv | n/a | main orchestrator deterministic rerun | n/a | n/a | true | 2026-08-17T00:01:14+08:00 | 共享路由验收合同（T1-AUTH-ROUTES）运行 20260817T031500Z-local-final-f4a5b6；I2 20 passed, 16 skipped；保护基线 LOCKED；正式接受待完成 |
| EV-IL1-CURRENT | IL1 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 只有当前已认证用户的显式操作可建立关联 |
| EV-I3-CURRENT | I3 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 不持久化永久 user_type |
| EV-I4-CURRENT | I4 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 个人路径不进入组织资源或飞书文档 |
| EV-I5-CURRENT | I5 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 页面不从前端 tenantId 或平台管理员推断权限 |
| EV-I6-CURRENT | I6 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 近期活动与其他私有资料使用同一租户边界 |
| EV-I7-CURRENT | I7 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 本节点不接入任何人工智能 Writer |
| EV-I9-CURRENT | I9 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 统一返回 capability_unavailable_until_writer_migration，且外部写入调用数为零 |
| EV-I8-CURRENT | I8 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 同一组织、Binding、资源和候选闭环 |
| EV-C1-CURRENT | C1 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 个人与组织可信分流及负例通过 |
| EV-C2-CURRENT | C2 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | Pilot 正负例绑定同一候选 |
| EV-CA-CURRENT | CA | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | R11 只在候选晋升时成为硬门；不得继续使用 development_base 直接晋升 |
| EV-DA1-CURRENT | DA1 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 全部门禁对同一候选通过 |
| EV-DB1-CURRENT | DB1 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 不声称跨数据库与飞书原子回滚 |
| EV-DC1-CURRENT | DC1 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 全部 1A 完成条件成立 |
| EV-MB1-CURRENT | MB1 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 1B 迁移不占用或改写 MA1 的 1A 编号范围 |
| EV-P1-CURRENT | P1 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 覆盖 ACTIVE、NEEDS_ATTENTION、DISABLED 和 REVOKED |
| EV-P2-CURRENT | P2 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 事件只影响匹配安装身份 |
| EV-P3-CURRENT | P3 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 只有匹配组织管理员可确认；唯一约束至少为 (binding_id, open_id) |
| EV-P5-CURRENT | P5 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 每项资源都回读并绑定当前安装 |
| EV-P6-CURRENT | P6 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 刷新或重启后从回读步骤续接 |
| EV-P7-CURRENT | P7 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 部分成功不得显示为 ACTIVE |
| EV-P8-CURRENT | P8 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 撤销后不能再访问或写入 |
| EV-P9-CURRENT | P9 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 唯一外部成员字段是服务端 open_id，数据库唯一约束至少为 (binding_id, open_id) |
| EV-P10-CURRENT | P10 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | disabled 成员的已有会话立即失效，且不能通过旧 token 刷新 |
| EV-C3-CURRENT | C3 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 新组织 owner 可自助接入，普通成员可首次授权进入且可被安全停用 |
| EV-CB-CURRENT | CB | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 不得绕过 DC1、E11 或带入 Stage 1C 目录成熟化 |
| EV-DA2-CURRENT | DA2 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 全部门禁对同一候选通过 |
| EV-DB2-CURRENT | DB2 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 不声称跨系统原子回滚 |
| EV-DC2-CURRENT | DC2 | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 1A 与 1B 必需完成条件全部成立 |
| EV-DA-CURRENT | DA | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 只汇总既有结论，不重跑或阻塞 1A、1B 发布 |
| EV-DB-CURRENT | DB | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 不产生新的生产或外部系统动作 |
| EV-DC-CURRENT | DC | source | phase1-plan-v4 | pending | planned isolated candidate | n/a | pending assigned worker | n/a | n/a | pending | pending | 不得把本投影解释为第三个发布候选 |
| EV-MPE2E-C5-R3-SHARED-LOCAL | A1 | local-runtime | sha256:f1ac786573e76aa40a0d69a10aab6dba5bd6a345596242d93f37773b59f45bcb | sha256:420b4ac3c9a064a21c2511d3b71750bedc3fed1b5a2f85ace236d5930cefccb0, sha256:a5e34064d554fe6a11b93f608b23202e737b40eac9dcedc4388c18dc952710be, sha256:134106d20f47b98b9600777490f5d22d48d32c4f6421c23a8fc11aaf3726569e, sha256:3f6028f577dc6674eb2afa3e48238ad503b042bb60436b737778a31a95bcd241 | local macOS candidate with disposable PostgreSQL 16 and contract fixtures | n/a | main orchestrator deterministic revalidation | local fixtures only | n/a | true | 2026-08-16T00:49:11+08:00 | 当前共享本地候选按租户、当前用户、平台、账号和有效正式关系唯一匹配客户自有账号，并在非目标工作区、错误角色、无效维护者或成员时于入队前失败关闭；不证明：第一阶段显式身份关联完整流程、SessionPrincipal v2、WorkspaceResolutionResult、身份候选汇合、部署或生产验收 |

本阶段当前登记证据的最高等级为本地运行级（`local-runtime`）：B、G1、M1、T1 与 I2 只证明本地合同、运行配置门禁、认证生命周期和无 Git 候选重建协议。共享上游候选证据只作为显式身份关联节点（`IL1`）、会话与工作区解析节点（`I3`）、身份与工作区汇合节点（`C1`）的相关证据，不改变这些节点的阻塞状态。目标真实设备或外部系统级（`physical-device/external-system`）只能由 DB1/DC1 与 DB2/DC2 对各自不可变候选的真实浏览器、数据库、飞书、账号、租户、组织绑定（Binding）和时间证据达到。

## 清除清单

| Scope | Type | Old or temporary item | Action | May remain | Evidence |
| --- | --- | --- | --- | --- | --- |
| Revision 11 候选 | external immutable candidate | 新登录、Provision 或 Writer 混入 | 禁止；本包只读 D3A 状态 | 否 | E11 到 CA/CB 的机器硬边 |
| 身份模型 | legacy field | 永久单一 user_type 与 ordinary 工作区写入 | 迁移后删除消费路径并加负例 | 仅迁移读取可短期存在 | I3/DA1 |
| 认证 | legacy interface | Media 密码登录、改密或 OPC 回调复用 | 保持隔离并加入门禁 | 否 | I2/DA1 |
| 组织凭据 | implicit fallback | 部署级全局 app/secret/space/parent 运行路径 | I7 只读资源改用 Binding；Writer 由第二阶段清除 | 仅未触达 Writer 的旧路径等待第二阶段 | I7/I8/Stage2 |
| Pilot | migration helper | 硬编码组织、账号、初始口令和单页脚本 | 只作来源参考；P6 接管后退役 | 只可保留不可执行历史证据 | C2/C3 |
| 应用命名 | duplicate authority | Company OS 与 MediaClaw B 重叠名称 | 统一到 MediaClaw B | 否 | B/P2/DA1 |
| 发布控制 | runtime authority | 长期双授权、双 Writer、全局凭据回退、租户白名单、灰度、长期功能开关和隐式回退 | 发布前门禁通过后全量单路径切换 | 只保留全局紧急停止和外部写入停止 | K2/CA/CB |
| 执行临时项 | temporary | prompt、PID/session 句柄、隔离端口 | 进程退出证据登记后清理 | 日志、return、ledger 与 Codex transcript 保留 | cleanup ledger |

## 禁止路径检查

候选不得包含长期双授权、全局凭据回退、双写入器（Writer）权威、租户白名单、灰度、长期功能开关、双路径或隐式回退。数据库使用前向迁移与恢复合同；飞书动作使用幂等、回读、补偿和待人工处置状态（NEEDS_ATTENTION）。发布前门禁、全局紧急停止和外部写入停止只是切换与止损机制，不得成为第二业务权威。

## 最终完成声明

发布增量 1A 只有独立终验节点 DC1 已接受（ACCEPTED）才完成。第一宏观阶段的必需交付只有在 DC1 与 DC2 均已接受（ACCEPTED）时完成；第一阶段后续目录成熟化（Stage 1C）明确不计入该完成门。第二阶段支线提前启动不能替代 1A 或 1B 的任何验收节点。
