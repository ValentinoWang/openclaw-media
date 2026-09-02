"""Hand written demo seed for the platform governance (admin) surface.

Scope is exactly the admin operationIds listed below — nothing else. Every
value here is a *partial* override: `generate_demo_dataset.py` instantiates
the full OpenAPI response shape and deep-merges these dicts on top, then
validates the result field-by-field against
`contracts/media_web_business_pages.openapi.yaml`. Fields left unset are
filled in by the generator with contract-valid placeholders, so only the
business-meaningful content lives here.

Covered operationId:
    getAdminDashboard, listAdminTenants, getAdminTenant, listAdminTenantRuns,
    getAdminBillingSummary, getAdminUpstreams, getAdminPlatformCookies,
    getAdminRegistrationPolicy, listAdminAdmissionBatches,
    listAdminAffiliateUsers

Narrative: five content studios / MCNs run the platform's demo tenancy.
潮汐文化传媒 is suspended for overdue billing, 拾光工作室 is a brand new
tenant still waiting on admission review, and the platform's own operations
are shown mid-incident — one upstream account unhealthy, the 小红书 cookie
missing, a credential rotation that just failed, and a manual balance grant
issued to make up for it. Every count below is derived from the concrete
records in this module, not picked independently.
"""
from typing import Any
from datetime import datetime, timedelta

_DEMO_NOW = datetime.fromisoformat("2026-09-02T10:00:00+08:00")


def ago(days: int = 0, hours: int = 0, minutes: int = 0) -> str:
    """ISO-8601 timestamp offset from demo-now (2026-09-02T10:00:00+08:00).

    Pass negative values to land in the future relative to demo-now — used
    for admission-code expiries that have not happened yet, so "past" and
    "future" read the same way through one helper.
    """
    return (_DEMO_NOW - timedelta(days=days, hours=hours, minutes=minutes)).isoformat()


# --------------------------------------------------------------------------
# Tenants — reused between the list page and the per-tenant detail/runs pages
# so the two views can never disagree with each other.
# --------------------------------------------------------------------------

_TENANT_GUANGHE: dict[str, Any] = {
    "publicTenantId": "tenant_guanghe_studio",
    "status": "active",
    "userCount": 12,
    "runCount": 86,
    "assetCount": 340,
    "archiveCount": 58,
    "usageCharge": "1280.50",
    "lastActiveAt": ago(hours=2),
}

_TENANT_CHENGYE: dict[str, Any] = {
    "publicTenantId": "tenant_chengye_mcn",
    "status": "active",
    "userCount": 34,
    "runCount": 210,
    "assetCount": 960,
    "archiveCount": 145,
    "usageCharge": "5460.00",
    "lastActiveAt": ago(hours=1),
}

_TENANT_XIAOMAN: dict[str, Any] = {
    "publicTenantId": "tenant_xiaoman_studio",
    "status": "active",
    "userCount": 3,
    "runCount": 28,
    "assetCount": 64,
    "archiveCount": 9,
    "usageCharge": "186.20",
    "lastActiveAt": ago(hours=5),
}

_TENANT_CHAOXI: dict[str, Any] = {
    "publicTenantId": "tenant_chaoxi_media",
    "status": "suspended",
    "userCount": 8,
    "runCount": 15,
    "assetCount": 40,
    "archiveCount": 6,
    "usageCharge": "42.00",
    "lastActiveAt": ago(days=18),
}

_TENANT_SHIGUANG: dict[str, Any] = {
    "publicTenantId": "tenant_shiguang_studio",
    "status": "pending_review",
    "userCount": 1,
    "runCount": 0,
    "assetCount": 0,
    "archiveCount": 0,
    "usageCharge": "0.00",
    "lastActiveAt": None,
}

_ADMIN_TENANTS: list[dict[str, Any]] = [
    _TENANT_GUANGHE,
    _TENANT_CHENGYE,
    _TENANT_XIAOMAN,
    _TENANT_CHAOXI,
    _TENANT_SHIGUANG,
]

# --------------------------------------------------------------------------
# Per-tenant audited runs (listAdminTenantRuns). Status vocabulary matches
# the production run-status labels in src/media/statusPresentation.ts so the
# admin run table renders the same pills as the ordinary runs page.
# --------------------------------------------------------------------------

_RUNS_GUANGHE: list[dict[str, Any]] = [
    {
        "publicRunId": "run_ghe_camping_gear",
        "title": "夏日露营装备测评脚本",
        "platform": "小红书",
        "contentType": "图文",
        "trackName": "露营装备",
        "entrypoint": "Web 工作台",
        "status": "succeeded",
        "availableSections": ["sources", "decisions", "outputs"],
        "publicProjectId": "proj_ghe_camping",
        "createdAt": ago(days=3),
        "updatedAt": ago(days=2),
    },
    {
        "publicRunId": "run_ghe_night_timelapse",
        "title": "城市夜景延时拍摄教学",
        "platform": "抖音",
        "contentType": "短视频",
        "trackName": "摄影教学",
        "entrypoint": "飞书标签",
        "status": "rendering",
        "availableSections": ["sources", "decisions"],
        "publicProjectId": "proj_ghe_night",
        "createdAt": ago(hours=10),
        "updatedAt": ago(hours=1),
    },
    {
        "publicRunId": "run_ghe_autumn_outfit",
        "title": "秋季穿搭素材拆解",
        "platform": "小红书",
        "contentType": "图文",
        "trackName": "穿搭灵感",
        "entrypoint": "Web 工作台",
        "status": "failed",
        "availableSections": ["sources"],
        "publicProjectId": None,
        "createdAt": ago(days=1),
        "updatedAt": ago(hours=6),
    },
]

_RUNS_CHENGYE: list[dict[str, Any]] = [
    {
        "publicRunId": "run_mcn_q3_review",
        "title": "签约达人 Q3 复盘报告",
        "platform": None,
        "contentType": None,
        "trackName": "达人运营",
        "entrypoint": "Web 工作台",
        "status": "succeeded",
        "availableSections": ["sources", "decisions", "outputs"],
        "publicProjectId": "proj_mcn_q3review",
        "createdAt": ago(days=5),
        "updatedAt": ago(days=4),
    },
    {
        "publicRunId": "run_mcn_beauty_topics",
        "title": "美妆赛道选题库更新",
        "platform": "小红书",
        "contentType": "图文",
        "trackName": "美妆赛道",
        "entrypoint": "Web 工作台",
        "status": "awaiting_confirmation",
        "availableSections": ["sources", "decisions"],
        "publicProjectId": "proj_mcn_beauty",
        "createdAt": ago(hours=14),
        "updatedAt": ago(hours=2),
    },
    {
        "publicRunId": "run_mcn_travel_deal",
        "title": "旅拍达人商单交付脚本",
        "platform": "抖音",
        "contentType": "短视频",
        "trackName": "旅拍商单",
        "entrypoint": "飞书标签",
        "status": "blocked",
        "availableSections": ["sources"],
        "publicProjectId": "proj_mcn_travel_deal",
        "createdAt": ago(days=2),
        "updatedAt": ago(hours=3),
    },
    {
        "publicRunId": "run_mcn_pet_breakdown",
        "title": "宠物赛道爆款拆解",
        "platform": "抖音",
        "contentType": "短视频",
        "trackName": "宠物赛道",
        "entrypoint": "Web 工作台",
        "status": "succeeded",
        "availableSections": ["sources", "decisions", "outputs"],
        "publicProjectId": "proj_mcn_pet",
        "createdAt": ago(days=7),
        "updatedAt": ago(days=6),
    },
]

_RUNS_XIAOMAN: list[dict[str, Any]] = [
    {
        "publicRunId": "run_xm_citywalk_oct",
        "title": "国庆城市漫步选题脚本",
        "platform": "小红书",
        "contentType": "图文",
        "trackName": "城市漫步",
        "entrypoint": "Web 工作台",
        "status": "succeeded",
        "availableSections": ["sources", "decisions", "outputs"],
        "publicProjectId": "proj_xm_citywalk_oct",
        "createdAt": ago(days=4),
        "updatedAt": ago(days=3),
    },
    {
        "publicRunId": "run_xm_lens_unbox",
        "title": "器材测评：新镜头开箱脚本",
        "platform": "B站",
        "contentType": "短视频",
        "trackName": "相机测评",
        "entrypoint": "Web 工作台",
        "status": "pending_manual",
        "availableSections": ["sources", "decisions"],
        "publicProjectId": "proj_xm_lens_unbox",
        "createdAt": ago(hours=30),
        "updatedAt": ago(hours=4),
    },
]

_RUNS_CHAOXI: list[dict[str, Any]] = [
    {
        "publicRunId": "run_cx_holiday_teaser",
        "title": "国庆预热选题脚本",
        "platform": "抖音",
        "contentType": "短视频",
        "trackName": "节日营销",
        "entrypoint": "Web 工作台",
        "status": "succeeded",
        "availableSections": ["sources", "decisions", "outputs"],
        "publicProjectId": "proj_cx_holiday",
        "createdAt": ago(days=20),
        "updatedAt": ago(days=19),
    },
    {
        "publicRunId": "run_cx_brand_partner",
        "title": "联名品牌植入脚本",
        "platform": "小红书",
        "contentType": "图文",
        "trackName": "品牌合作",
        "entrypoint": "Web 工作台",
        "status": "cancelled",
        "availableSections": ["sources"],
        "publicProjectId": None,
        "createdAt": ago(days=19),
        "updatedAt": ago(days=18),
    },
]

_RUNS_SHIGUANG: list[dict[str, Any]] = []

# --------------------------------------------------------------------------
# Dashboard (getAdminDashboard). Every count is derived from the records
# below rather than picked independently:
#   counts.tenants          = len(_ADMIN_TENANTS)                     = 5
#   counts.users             = sum(t["userCount"] for t in tenants)    = 58
#   counts.pendingAdmission  = unused codes on active, unexpired
#                              admission batches (see _ADMISSION_BATCHES)
#                              15 (autumn2026) + 0 (mcn_seats, exhausted)
#                              + 7 (referral_pilot)                    = 22
#   counts.abnormalRuns      = runs across all tenants with a
#                              failed/blocked/pending_manual/cancelled
#                              status                                  = 4
# --------------------------------------------------------------------------

_DASHBOARD_SUMMARY: dict[str, Any] = {
    "counts": {
        "tenants": 5,
        "users": 58,
        "pendingAdmission": 22,
        "abnormalRuns": 4,
    },
    "governanceTodos": [
        "潮汐文化传媒因账单逾期被暂停，等待财务确认到账后恢复服务",
        "小红书 Cookie 校验失败，需要重新配置后再次校验",
        "拾光工作室的准入申请（老带新内测批次）待审核通过",
        "2026 秋季达人招募批次仍有 15 个名额未使用，可评估是否加大推广",
    ],
    "serviceHealth": [
        {"service": "内容生成队列", "status": "healthy", "checkedAt": ago(minutes=5)},
        {"service": "上游账号池", "status": "degraded", "checkedAt": ago(minutes=12)},
        {"service": "计费账本服务", "status": "healthy", "checkedAt": ago(minutes=5)},
        {"service": "小红书 Cookie 同步", "status": "unavailable", "checkedAt": ago(hours=4)},
    ],
    "auditSummary24h": {
        "actionCount": 38,
        "failedCount": 1,
        "from": ago(hours=24),
        "to": ago(),
    },
    "recentActions": [
        {
            "publicActionId": "action_rotate_upstream_cred",
            "action": "upstream_credential.rotate",
            "targetType": "platform",
            "reasonSummary": "小红书 Cookie 校验失败，尝试轮换凭据但仍处于异常状态",
            "status": "failed",
            "createdAt": ago(hours=1),
        },
        {
            "publicActionId": "action_close_open_reg",
            "action": "registration_policy.update",
            "targetType": "platform",
            "reasonSummary": "监测到批量刷量注册，临时切换为仅邀请制",
            "status": "succeeded",
            "createdAt": ago(hours=3),
        },
        {
            "publicActionId": "action_reissue_balance",
            "action": "billing_grant.create",
            "targetType": "billing",
            "reasonSummary": "补偿计费对账延迟导致潮汐文化传媒出现的余额缺口",
            "status": "succeeded",
            "createdAt": ago(hours=6),
        },
        {
            "publicActionId": "action_disable_admission_batch",
            "action": "admission_batch.disable",
            "targetType": "admission",
            "reasonSummary": "2025 冬季内测批次早已超期未清理，人工停用",
            "status": "succeeded",
            "createdAt": ago(days=1, hours=2),
        },
        {
            "publicActionId": "action_suspend_tenant",
            "action": "tenant.suspend",
            "targetType": "tenant",
            "reasonSummary": "潮汐文化传媒账单逾期 15 天，暂停服务并通知财务对接人",
            "status": "succeeded",
            "createdAt": ago(days=18),
        },
    ],
    "generatedAt": ago(),
}

# --------------------------------------------------------------------------
# Billing (getAdminBillingSummary). productMappings / fulfillments / grants
# are StringValueMap (free-form) per the contract, so most keys are
# business-readable Chinese labels rather than a fixed schema. Fulfillments
# additionally carry the canonical English fields (fulfillmentId, status,
# planCode, creditedAmount, publicTenantId) that AdminBillingPage.tsx keys
# its 履约编号 column and recover/refund row actions off — without those a
# fulfillment has no selectable id and the two action buttons stay disabled.
# --------------------------------------------------------------------------

_BILLING_SUMMARY: dict[str, Any] = {
    "plans": [
        {
            "planCode": "starter",
            "name": "入门版",
            "status": "active",
            "textQuota": 200,
            "imageQuota": 100,
            "price": "99.00",
            "currency": "CNY",
        },
        {
            "planCode": "studio",
            "name": "工作室版",
            "status": "active",
            "textQuota": 1000,
            "imageQuota": 600,
            "price": "399.00",
            "currency": "CNY",
        },
        {
            "planCode": "mcn",
            "name": "MCN 旗舰版",
            "status": "active",
            "textQuota": 5000,
            "imageQuota": 3000,
            "price": "1299.00",
            "currency": "CNY",
        },
        {
            "planCode": "legacy_trial",
            "name": "早期内测版",
            "status": "retired",
            "textQuota": 50,
            "imageQuota": 20,
            "price": "0.00",
            "currency": "CNY",
        },
    ],
    "productMappings": [
        {
            "渠道": "微信支付",
            "外部商品号": "wxpay_studio_399",
            "映射套餐": "工作室版",
            "状态": "已启用",
            "更新人": "运营-阿岚",
            "更新时间": ago(days=5),
        },
        {
            "渠道": "支付宝",
            "外部商品号": "alipay_mcn_1299",
            "映射套餐": "MCN 旗舰版",
            "状态": "已启用",
            "更新人": "运营-阿岚",
            "更新时间": ago(days=12),
        },
        {
            "渠道": "App Store 内购",
            "外部商品号": "ios_starter_99",
            "映射套餐": "入门版",
            "状态": "待复核",
            "更新人": "运营-小圆",
            "更新时间": ago(hours=20),
        },
    ],
    "redemptionBatches": [
        {
            "batchId": "redeem_studio_q3",
            "planCode": "studio",
            "status": "active",
            "codeCount": 100,
            "redeemedCount": 67,
            "createdAt": ago(days=25),
        },
        {
            "batchId": "redeem_mcn_partner",
            "planCode": "mcn",
            "status": "completed",
            "codeCount": 30,
            "redeemedCount": 30,
            "createdAt": ago(days=40),
        },
        {
            "batchId": "redeem_starter_trial",
            "planCode": "starter",
            "status": "closed",
            "codeCount": 200,
            "redeemedCount": 143,
            "createdAt": ago(days=70),
        },
    ],
    "fulfillments": [
        {
            "fulfillmentId": "ff_20260828_0091",
            "publicTenantId": "tenant_guanghe_studio",
            "planCode": "studio",
            "creditedAmount": "399.00000000",
            "status": "completed",
            "createdAt": ago(days=5),
            "兑单号": "ff_20260828_0091",
            "租户": "光合内容工作室",
            "套餐": "工作室版",
            "金额": "399.00",
            "币种": "CNY",
            "状态": "已完成",
            "支付渠道": "微信支付",
            "处理人": "系统自动",
            "完成时间": ago(days=5),
        },
        {
            # 卡在上游回调超时、尚未到账 —— 演示「恢复履约」的目标记录。
            "fulfillmentId": "ff_20260830_0104",
            "publicTenantId": "tenant_chaoxi_media",
            "planCode": "starter",
            "creditedAmount": "0.00000000",
            "status": "pending",
            "createdAt": ago(days=3),
            "兑单号": "ff_20260830_0104",
            "租户": "潮汐文化传媒",
            "套餐": "入门版",
            "金额": "99.00",
            "币种": "CNY",
            "状态": "待人工处理",
            "支付渠道": "微信支付",
            "失败原因": "上游回调超时",
            "创建时间": ago(days=3),
        },
        {
            "fulfillmentId": "ff_20260815_0053",
            "publicTenantId": "tenant_chengye_mcn",
            "planCode": "mcn",
            "creditedAmount": "1299.00000000",
            "status": "refunded",
            "createdAt": ago(days=15),
            "兑单号": "ff_20260815_0053",
            "租户": "城野 MCN",
            "套餐": "MCN 旗舰版",
            "金额": "1299.00",
            "币种": "CNY",
            "状态": "已退款",
            "支付渠道": "支付宝",
            "退款原因": "客户重复下单",
            "处理人": "运营-阿岚",
            "退款时间": ago(days=15),
        },
    ],
    "grants": [
        {
            "发放单号": "grant_20260830_01",
            "租户": "潮汐文化传媒",
            "文本额度": 500,
            "图片额度": 200,
            "原因": "补偿计费对账延迟导致的余额缺口",
            "操作人": "运营-阿岚",
            "发放时间": ago(hours=6),
        },
        {
            "发放单号": "grant_20260812_02",
            "租户": "小满个人工作室",
            "文本额度": 200,
            "图片额度": 0,
            "原因": "内测反馈奖励",
            "操作人": "运营-小圆",
            "发放时间": ago(days=21),
        },
    ],
}

# --------------------------------------------------------------------------
# Upstreams (getAdminUpstreams) — one unhealthy account, degraded
# credential, a small pending-reconciliation backlog.
# --------------------------------------------------------------------------

_UPSTREAM_SUMMARY: dict[str, Any] = {
    "availableAccountCount": 18,
    "unhealthyAccountCount": 1,
    "credentialHealth": "degraded",
    "pendingReconciliationCount": 4,
    "lastSyncedAt": ago(minutes=12),
}

# --------------------------------------------------------------------------
# Platform cookies (getAdminPlatformCookies) — exactly two platforms per the
# contract (minItems == maxItems == 2). No real credentials, paths, or
# domains: every operator-facing token is a <placeholder>.
# --------------------------------------------------------------------------

_PLATFORM_COOKIES: list[dict[str, Any]] = [
    {
        "platform": "douyin",
        "configured": True,
        "updatedAt": ago(hours=4),
        "validationStatus": "valid",
        "errorCode": None,
        "configurationScript": (
            "1. 管理员使用平台运营账号登录抖音创作者后台完成人工验证\n"
            "2. 由管理员在服务器终端直接粘贴登录态，不落盘、不经过网页\n"
            "3. 在服务器上执行 save_platform_cookie_secret.py，按隐藏输入粘贴登录态\n"
            "4. 执行 <bot_cli> cookies verify --platform douyin 校验凭据是否可用"
        ),
        "safeCommand": "python3 <repo>/scripts/save_platform_cookie_secret.py --platform douyin --prompt",
    },
    {
        "platform": "xiaohongshu",
        "configured": False,
        "updatedAt": None,
        "validationStatus": "missing",
        "errorCode": None,
        "configurationScript": (
            "1. 管理员使用平台运营账号登录小红书创作者中心完成人工验证\n"
            "2. 由管理员在服务器终端直接粘贴登录态，不落盘、不经过网页\n"
            "3. 在服务器上执行 save_platform_cookie_secret.py，按隐藏输入粘贴登录态\n"
            "4. 执行 <bot_cli> cookies verify --platform xiaohongshu 校验凭据是否可用（当前尚未配置，会返回 missing）"
        ),
        "safeCommand": "python3 <repo>/scripts/save_platform_cookie_secret.py --platform xiaohongshu --prompt",
    },
]

# --------------------------------------------------------------------------
# Registration policy (getAdminRegistrationPolicy) — closed to open signup
# right when the "关闭开放注册" audit action fired, which is why new
# tenants (拾光工作室) come in through an admission batch instead.
# --------------------------------------------------------------------------

_REGISTRATION_POLICY: dict[str, Any] = {
    "mode": "invite_only",
    "updatedAt": ago(hours=3),
}

# --------------------------------------------------------------------------
# Admission batches (listAdminAdmissionBatches) — enabled/disabled,
# exhausted/has-balance, and naturally expired all appear:
#   autumn2026     active,   15/50 unused,  expires in the future
#   mcn_seats      active,    0/20 unused (exhausted), expires in the future
#   winter2025     disabled, 59/100 unused but manually shut off
#   summer_trial   active,    8/30 unused but expiresAt is already past
#   referral_pilot active,    7/10 unused,  expires in the future
# --------------------------------------------------------------------------

_ADMISSION_BATCHES: list[dict[str, Any]] = [
    {
        "batchId": "batch_admit_autumn2026",
        "name": "2026 秋季达人招募批次",
        "status": "active",
        "codeCount": 50,
        "usedCount": 35,
        "expiresAt": ago(days=-45),
        "createdAt": ago(days=10),
    },
    {
        "batchId": "batch_admit_mcn_seats",
        "name": "城野 MCN 团队席位批次",
        "status": "active",
        "codeCount": 20,
        "usedCount": 20,
        "expiresAt": ago(days=-90),
        "createdAt": ago(days=30),
    },
    {
        "batchId": "batch_admit_winter2025",
        "name": "2025 冬季内测批次",
        "status": "disabled",
        "codeCount": 100,
        "usedCount": 41,
        "expiresAt": None,
        "createdAt": ago(days=280),
    },
    {
        "batchId": "batch_admit_summer_trial",
        "name": "2026 夏季体验批次",
        "status": "active",
        "codeCount": 30,
        "usedCount": 22,
        "expiresAt": ago(days=20),
        "createdAt": ago(days=70),
    },
    {
        "batchId": "batch_admit_referral_pilot",
        "name": "老带新内测批次",
        "status": "active",
        "codeCount": 10,
        "usedCount": 3,
        "expiresAt": ago(days=-14),
        "createdAt": ago(days=6),
    },
]

# --------------------------------------------------------------------------
# Affiliate users (listAdminAffiliateUsers) — enabled/disabled and
# exhausted/has-balance both appear.
# --------------------------------------------------------------------------

_AFFILIATE_USERS: list[dict[str, Any]] = [
    {
        "publicUserId": "user_aff_guanghe_lin",
        "displayName": "林知一（光合内容工作室）",
        "affiliateEnabled": True,
        "invitationQuota": 20,
        "usedQuota": 14,
        "status": "active",
        "updatedAt": ago(days=2),
    },
    {
        "publicUserId": "user_aff_chengye_han",
        "displayName": "韩明（城野 MCN）",
        "affiliateEnabled": True,
        "invitationQuota": 50,
        "usedQuota": 50,
        "status": "active",
        "updatedAt": ago(days=8),
    },
    {
        "publicUserId": "user_aff_xiaoman_studio",
        "displayName": "小满（小满个人工作室）",
        "affiliateEnabled": True,
        "invitationQuota": 10,
        "usedQuota": 3,
        "status": "active",
        "updatedAt": ago(days=15),
    },
    {
        "publicUserId": "user_aff_chaoxi_zhou",
        "displayName": "周敏（潮汐文化传媒）",
        "affiliateEnabled": False,
        "invitationQuota": 15,
        "usedQuota": 6,
        "status": "disabled",
        "updatedAt": ago(days=18),
    },
    {
        "publicUserId": "user_aff_shiguang_he",
        "displayName": "何蔚（拾光工作室）",
        "affiliateEnabled": True,
        "invitationQuota": 5,
        "usedQuota": 0,
        "status": "pending_review",
        "updatedAt": ago(hours=20),
    },
]


# --------------------------------------------------------------------------
# Exports
# --------------------------------------------------------------------------

ADMIN_SEED: dict[str, Any] = {
    "getAdminDashboard": {"summary": _DASHBOARD_SUMMARY},
    "listAdminTenants": {"items": _ADMIN_TENANTS},
    "getAdminTenant": {"tenant": _TENANT_GUANGHE},
    "listAdminTenantRuns": {"items": _RUNS_GUANGHE},
    "getAdminBillingSummary": {"summary": _BILLING_SUMMARY},
    "getAdminUpstreams": {"summary": _UPSTREAM_SUMMARY},
    "getAdminPlatformCookies": {"platforms": _PLATFORM_COOKIES},
    "getAdminRegistrationPolicy": {"policy": _REGISTRATION_POLICY},
    "listAdminAdmissionBatches": {"items": _ADMISSION_BATCHES},
    "listAdminAffiliateUsers": {"items": _AFFILIATE_USERS},
}

ADMIN_PARAMETER_PAYLOADS: dict[str, dict[str, Any]] = {
    "getAdminTenant": {
        "tenant_guanghe_studio": {"tenant": _TENANT_GUANGHE},
        "tenant_chengye_mcn": {"tenant": _TENANT_CHENGYE},
        "tenant_xiaoman_studio": {"tenant": _TENANT_XIAOMAN},
        "tenant_chaoxi_media": {"tenant": _TENANT_CHAOXI},
        "tenant_shiguang_studio": {"tenant": _TENANT_SHIGUANG},
    },
    "listAdminTenantRuns": {
        "tenant_guanghe_studio": {"items": _RUNS_GUANGHE},
        "tenant_chengye_mcn": {"items": _RUNS_CHENGYE},
        "tenant_xiaoman_studio": {"items": _RUNS_XIAOMAN},
        "tenant_chaoxi_media": {"items": _RUNS_CHAOXI},
        "tenant_shiguang_studio": {"items": _RUNS_SHIGUANG},
    },
}

ADMIN_LIST_SIZES: dict[str, int] = {}
