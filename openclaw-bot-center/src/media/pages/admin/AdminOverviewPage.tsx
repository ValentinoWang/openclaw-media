import {
  AlertCircle,
  Activity,
  Building2,
  Clock3,
  RefreshCw,
  ShieldCheck,
  UserRound,
  UserRoundPlus,
  WalletCards,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import {
  BusinessOperationError,
  callBusinessOperation,
} from "../../generatedBusinessPagesContract";
import { useMediaWeb } from "../../MediaWebWorkspace";
import { isMissingEntitlementError } from "../../businessErrorPresentation";
import { isPublicId } from "../../identifiers";
import { Metric } from "../../ui/Metric";
import { describeBusinessError } from "../../ui/businessOperationError";
import { ECHO_INVALID, formatShortDateTime } from "../../ui/datetime";
import { SurfaceState } from "../../ui/SurfaceState";
import styles from "./AdminOverviewPage.module.css";

type ServiceHealthStatus = "healthy" | "degraded" | "unavailable" | "unknown";
type AdminActionStatus =
  | "succeeded" | "failed" | "recorded" | "pending"
  | "unknown_reconcile" | "cancelled" | "degraded" | "unknown";
type AdminActionTargetType =
  | "platform" | "user" | "tenant" | "billing" | "admission" | "session" | "unknown";

type AdminDashboardResponse = {
  schemaVersion: string;
  revision: number;
  summary: AdminOverview;
};

type AdminOverview = {
  counts: {
    tenants: number;
    users: number;
    pendingAdmission: number;
    abnormalRuns: number;
  };
  governanceTodos: string[];
  serviceHealth: Array<{
    service: string;
    status: ServiceHealthStatus;
    checkedAt: string;
  }>;
  auditSummary24h: {
    actionCount: number;
    failedCount: number;
    from: string;
    to: string;
  };
  recentActions: Array<{
    publicActionId: string;
    // 合同里 action / targetType / status 都是自由字符串,不是枚举——真实后端可以
    // 在任何时候发一个前端从没见过的取值。曾经这里把 targetType/status 收窄成
    // 闭合联合类型,并在 isAdminAction 里按固定 Set 校验成员资格:后端一旦发一个
    // 不在 Set 里的取值,整条 recentActions 数组的 `.every(isAdminAction)` 就会
    // 失败,导致整个平台总览直接报错、不渲染。这三个字段改回 string,校验只认
    // 「非空字符串」这个形状,未知取值交给下面的 actionLabel/actionTargetTypeLabel/
    // actionStatusLabel 逐条兜底成中文「未知」,而不是让一整页因为一条审计记录
    // 陪葬。
    action: string;
    targetType: string;
    reasonSummary: string;
    status: string;
    createdAt: string;
  }>;
  generatedAt: string;
  revision: number;
};

type DashboardState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: AdminDashboardResponse }
  | { status: "forbidden"; message: string }
  | { status: "error"; message: string };

const HEALTH_STATUSES = new Set<ServiceHealthStatus>([
  "healthy",
  "degraded",
  "unavailable",
  "unknown",
]);

const HEALTH_LABELS: Record<ServiceHealthStatus, string> = {
  healthy: "正常",
  degraded: "降级",
  unavailable: "不可用",
  unknown: "未知",
};

const ACTION_STATUSES = new Set<AdminActionStatus>([
  "succeeded",
  "failed",
  "recorded",
  "pending",
  "unknown_reconcile",
  "cancelled",
  "degraded",
  "unknown",
]);

const ACTION_TARGET_TYPES = new Set<AdminActionTargetType>([
  "platform",
  "user",
  "tenant",
  "billing",
  "admission",
  "session",
  "unknown",
]);

const ACTION_TARGET_TYPE_LABELS: Record<AdminActionTargetType, string> = {
  platform: "平台",
  user: "用户",
  tenant: "租户",
  billing: "计费",
  admission: "准入",
  session: "会话",
  unknown: "未知",
};

const ACTION_STATUS_LABELS: Record<AdminActionStatus, string> = {
  succeeded: "成功",
  failed: "失败",
  recorded: "已记录",
  pending: "处理中",
  unknown_reconcile: "待核验",
  cancelled: "已取消",
  degraded: "降级",
  unknown: "未知",
};

/** `action` 是自由字符串(如 `tenant.suspend`),不是枚举——不可能穷举,只能给
 *  已经在本产品里出现过的取值配一句中文说明。后端发一个没配过的取值时,
 *  不能把原始机器名当正文吐给用户,统一显示成「其他管理操作」,原始值仍然
 *  留在 title 里供排查(见下方 JSX)。 */
const ACTION_NAME_LABELS: Record<string, string> = {
  "upstream_credential.rotate": "轮换上游凭据",
  "registration_policy.update": "更新注册策略",
  "billing_grant.create": "发放计费余额",
  "admission_batch.disable": "停用准入批次",
  "tenant.suspend": "暂停租户",
};

function actionLabel(action: string): string {
  return ACTION_NAME_LABELS[action] ?? "其他管理操作";
}

/** targetType/status 查表命中时按已知取值翻译;命中不了(后端发了一个前端
 *  还没配置过的自由字符串)一律落到中文「未知」,不把原始取值渲染出来,也
 *  不留一个空白徽标。 */
function actionTargetTypeLabel(targetType: string): string {
  return ACTION_TARGET_TYPES.has(targetType as AdminActionTargetType)
    ? ACTION_TARGET_TYPE_LABELS[targetType as AdminActionTargetType]
    : "未知";
}

function actionStatusLabel(status: string): string {
  return ACTION_STATUSES.has(status as AdminActionStatus)
    ? ACTION_STATUS_LABELS[status as AdminActionStatus]
    : "未知";
}

export default function AdminOverviewPage() {
  const { runtimeState, session } = useMediaWeb();
  const [refreshToken, setRefreshToken] = useState(0);
  const [dashboardState, setDashboardState] = useState<DashboardState>({
    status: "idle",
  });
  const permitted = runtimeState === "authenticated" && session?.role === "admin";

  useEffect(() => {
    if (!permitted) {
      setDashboardState({ status: "idle" });
      return;
    }

    const controller = new AbortController();
    let active = true;
    setDashboardState({ status: "loading" });

    void callBusinessOperation<AdminDashboardResponse>("getAdminDashboard", {
      signal: controller.signal,
    })
      .then((payload) => {
        if (!active) return;
        setDashboardState({
          status: "ready",
          data: parseDashboardResponse(payload),
        });
      })
      .catch((error: unknown) => {
        if (!active || controller.signal.aborted) return;
        if (isMissingEntitlementError(error)) {
          setDashboardState({
            status: "forbidden",
            message: "当前会话无权查看平台治理数据。",
          });
          return;
        }
        setDashboardState({ status: "error", message: describeError(error) });
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [permitted, refreshToken]);

  const retry = () => setRefreshToken((value) => value + 1);
  const dashboard = dashboardState.status === "ready" ? dashboardState.data : null;
  const requestLoading = permitted && dashboardState.status === "loading";

  return (
    <main
      className={`fidelity-page ${styles["admin-overview-page"]}`}
      data-accent="desk"
      data-page-ownership="governance"
    >
      <header
        className={`mg-hero ${styles["admin-overview-header"]}`}
        data-component="mg-hero"
        data-page-prelude
      >
        <div>
          <span className="mg-eyebrow" data-component="mg-eyebrow">
            平台治理控制台
          </span>
          <h1>平台总览</h1>
          <p>治理租户准入、资源边界、计费与上游服务。</p>
        </div>
        <button
          className="mg-btn mg-btn-ghost"
          type="button"
          onClick={retry}
          disabled={!permitted || requestLoading}
          aria-label="刷新平台总览"
          title="刷新平台总览"
        >
          <RefreshCw
            size={16}
            className={requestLoading ? "spin" : undefined}
            aria-hidden="true"
          />
          刷新
        </button>
      </header>

      {runtimeState === "checking" ? (
        <SurfaceState
          kind="loading"
          title="正在确认平台权限"
          detail="平台治理数据将在身份确认后读取。"
        />
      ) : null}
      {runtimeState === "unauthenticated" ? (
        <SurfaceState
          kind="permission"
          title="当前会话未登录"
          detail="当前会话未登录，平台治理数据不会加载。"
          action={null}
        />
      ) : null}
      {runtimeState === "unavailable" ? (
        <SurfaceState
          kind="error"
          title="平台总览服务不可用"
          detail="当前会话服务不可用，平台治理数据不会加载。"
        />
      ) : null}
      {runtimeState === "authenticated" && !permitted ? (
        <SurfaceState
          kind="forbidden"
          title="暂无查看权限"
          detail="当前会话无权查看平台治理数据。"
        />
      ) : null}
      {permitted && dashboardState.status === "loading" ? (
        <SurfaceState
          kind="loading"
          title="正在读取平台治理数据"
          detail="正在读取当前账户可见的平台治理数据。"
        />
      ) : null}
      {permitted && dashboardState.status === "forbidden" ? (
        <SurfaceState
          kind="forbidden"
          title="暂无查看权限"
          detail={dashboardState.message}
        />
      ) : null}
      {permitted && dashboardState.status === "error" ? (
        <SurfaceState
          kind="error"
          title="平台总览读取失败"
          detail={dashboardState.message}
          action={
            <button className="mg-state-action" type="button" onClick={retry}>
              <RefreshCw size={14} aria-hidden="true" />
              重试
            </button>
          }
        />
      ) : null}

      {dashboard ? <DashboardContent data={dashboard} /> : null}
    </main>
  );
}

function DashboardContent({ data }: { data: AdminDashboardResponse }) {
  const { summary } = data;
  const healthMessage = getHealthMessage(summary.serviceHealth);
  const metrics = [
    { label: "活跃租户", value: summary.counts.tenants, icon: Building2 },
    { label: "已注册用户", value: summary.counts.users, icon: UserRound },
    { label: "待处理准入", value: summary.counts.pendingAdmission, icon: UserRoundPlus },
    { label: "异常运行", value: summary.counts.abnormalRuns, icon: Activity },
  ];

  return (
    <>
      <section
        className={`mg-metric-grid ${styles["admin-metric-grid"]}`}
        aria-label="平台指标"
        data-component="mg-metric-grid"
      >
        {metrics.map(({ icon: Icon, ...metric }) => (
          <Metric
            variant="card"
            className={`mg-metric ${styles["admin-metric"]}`}
            icon={<Icon size={17} aria-hidden="true" />}
            label={metric.label}
            value={metric.value}
            detail="平台聚合读数"
            key={metric.label}
          />
        ))}
      </section>
      <div
        className={styles["admin-overview-grid"]}
        data-page-layout="persistent-rail"
      >
        <div className={styles["admin-primary-column"]} data-page-primary>
          <section
            className={`mg-panel ${styles["admin-panel"]} ${styles["admin-governance-panel"]}`}
            data-component="mg-panel"
          >
            <PanelHeading
              title="治理待办"
              detail="准入、注册策略与运行状态的当前聚合。"
              icon={Clock3}
            />
            {summary.governanceTodos.length ? (
              <div
                className={styles["admin-governance-list"]}
                role="region"
                tabIndex={0}
                aria-label="治理待办列表"
              >
                <ol className={styles["admin-governance-items"]}>
                  {summary.governanceTodos.map((item, index) => (
                    <li className={styles["admin-governance-item"]} key={`${item}-${index}`}>
                      <span className="mg-badge" data-tone="accent" aria-hidden="true">
                        {index + 1}
                      </span>
                      <p>{item}</p>
                    </li>
                  ))}
                </ol>
              </div>
            ) : (
              <SurfaceState
                kind="empty"
                title="暂无治理待办。"
                detail=""
                density="compact"
              />
            )}
          </section>
          <section
            className={`mg-panel ${styles["admin-panel"]} ${styles["admin-operations-panel"]}`}
            data-page-terminal-surface="primary"
            data-component="mg-panel"
          >
            <PanelHeading
              title="最近管理操作"
              detail="仅展示已脱敏的近 24 小时审计摘要。"
              icon={AlertCircle}
            />
            {summary.recentActions.length ? (
              <div
                className={styles["admin-actions-list"]}
                role="region"
                tabIndex={0}
                aria-label="最近管理操作列表"
              >
                {summary.recentActions.map((action) => (
                  <article
                    className={styles["admin-action-row"]}
                    key={action.publicActionId}
                  >
                    <div className={styles["admin-action-main"]}>
                      {/* 正文是翻译过的中文操作名;title 保留原始机器取值供排查——
                          正文与 title 不再是同一个值的截断,所以这里不用 mg-id
                          （它的契约是"完整值放 title、正文是同一个值的截断"）。 */}
                      <strong title={action.action}>{actionLabel(action.action)}</strong>
                      <span>{action.reasonSummary}</span>
                    </div>
                    <div className={styles["admin-action-meta"]}>
                      <span>{actionTargetTypeLabel(action.targetType)}</span>
                      <span
                        className={`mg-badge ${styles["admin-action-status"]}`}
                        data-tone={actionStatusTone(action.status)}
                      >
                        {actionStatusLabel(action.status)}
                      </span>
                      <time dateTime={action.createdAt}>
                        {formatDateTime(action.createdAt)}
                      </time>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <SurfaceState
                kind="empty"
                title="近 24 小时没有可展示的管理操作。"
                detail=""
                density="compact"
              />
            )}
          </section>
        </div>
        <aside className={styles["admin-side-column"]} data-page-inspector>
          <section
            className={`mg-panel ${styles["admin-panel"]} ${styles["admin-boundary-panel"]}`}
            data-component="mg-panel"
          >
            <PanelHeading title="平台边界" icon={ShieldCheck} />
            <ul>
              <li>管理员不默认读取租户内容</li>
              <li>跨租户读取需明确目标</li>
              <li>所有写操作记录审计原因</li>
            </ul>
          </section>
          <section
            className={`mg-panel ${styles["admin-panel"]} ${styles["admin-services-panel"]}`}
            data-component="mg-panel"
          >
            <PanelHeading
              title="服务健康"
              detail={healthMessage}
              icon={WalletCards}
            />
            {summary.serviceHealth.length ? (
              <div
                className={styles["admin-service-readout"]}
                aria-label="服务健康读数"
              >
                {summary.serviceHealth.map((service) => (
                  <div key={service.service}>
                    <span>{service.service}</span>
                    <span
                      className={`mg-badge ${styles["admin-service-status"]}`}
                      data-tone={healthStatusTone(service.status)}
                      title={`检查时间：${formatDateTime(service.checkedAt)}`}
                    >
                      {/* HEALTH_LABELS 是按 ServiceHealthStatus 四个枚举值穷尽的表,
                          isServiceHealth 也已经按合同的 enum 校验过成员资格,这里理论
                          上不会落空——但直接裸查表在可见文本位置会被当作「后端加一个
                          没登记的取值就会渲染成空白格子」的隐患抓住,补一个中文兜底
                          做二次防护，成本为零。 */}
                      {HEALTH_LABELS[service.status] ?? "未知"}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <SurfaceState
                kind="empty"
                title="服务健康读数未返回。"
                detail=""
                density="compact"
              />
            )}
          </section>
          <section
            className={`mg-panel ${styles["admin-panel"]} ${styles["admin-audit-panel"]}`}
            data-page-terminal-surface="inspector"
            data-component="mg-panel"
          >
            <PanelHeading
              title="审计事实（近 24 小时）"
              detail={`生成于 ${formatDateTime(summary.generatedAt)} · 修订 ${summary.revision}`}
              icon={AlertCircle}
            />
            <div
              className={styles["admin-audit-readout"]}
              aria-label="审计事实读数"
            >
              <div>
                <span>操作总数</span>
                <strong>{summary.auditSummary24h.actionCount}</strong>
              </div>
              <div>
                <span>失败操作</span>
                <strong>{summary.auditSummary24h.failedCount}</strong>
              </div>
              <div className={styles["admin-audit-window"]}>
                <span>统计窗口</span>
                <small>
                  {formatDateTime(summary.auditSummary24h.from)} 至 {formatDateTime(summary.auditSummary24h.to)}
                </small>
              </div>
            </div>
          </section>
        </aside>
      </div>
    </>
  );
}

function PanelHeading({
  title,
  detail,
  icon: Icon,
}: {
  title: string;
  detail?: string;
  icon: LucideIcon;
}) {
  return (
    <header
      className={`mg-panel-head ${styles["admin-panel-heading"]}`}
      data-component="mg-panel-head"
    >
      <div>
        <h2>{title}</h2>
        {detail ? <p>{detail}</p> : null}
      </div>
      <Icon size={18} aria-hidden="true" />
    </header>
  );
}

function getHealthMessage(
  services: AdminOverview["serviceHealth"],
): string {
  const incidents = services.filter((service) => service.status !== "healthy");
  if (!services.length) return "未返回服务健康读数。";
  if (!incidents.length) return "全部服务已返回正常读数。";
  return `${incidents.length} 项服务读数需要关注，页面保留已返回事实。`;
}

type BadgeTone = "success" | "warning" | "danger";

function actionStatusTone(status: string): BadgeTone | undefined {
  if (status === "succeeded" || status === "recorded") return "success";
  if (status === "failed") return "danger";
  if (status === "degraded") return "warning";
  // 未知取值落到 undefined:徽标不带 data-tone,渲染成中性灰的默认样式，
  // 而不是空白或崩溃——已经是安全的兜底。
  return undefined;
}

function healthStatusTone(status: ServiceHealthStatus): BadgeTone | undefined {
  if (status === "healthy") return "success";
  if (status === "degraded") return "warning";
  if (status === "unavailable") return "danger";
  return undefined;
}

function describeError(error: unknown): string {
  const fallback =
    error instanceof BusinessOperationError
      ? error.message || "平台总览请求失败。"
      : error instanceof Error && error.message
        ? error.message
        : "平台总览请求失败，请重试。";
  return describeBusinessError(error, {
    fallback,
    unauthorized: "当前会话已失效，请重新登录。",
    unavailable: "平台总览服务暂时不可用，请稍后重试。",
  });
}

function parseDashboardResponse(value: unknown): AdminDashboardResponse {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["schemaVersion", "revision", "summary"]) ||
    value.schemaVersion !== "media_web_business_pages_v2"
  ) {
    throw new Error("平台总览返回的数据版本不受支持。");
  }
  if (!isNonNegativeInteger(value.revision) || !isRecord(value.summary)) {
    throw new Error("平台总览返回的数据不完整。");
  }
  const summary = value.summary;
  if (
    !hasExactKeys(summary, ["counts", "governanceTodos", "serviceHealth", "auditSummary24h", "recentActions", "generatedAt", "revision"]) ||
    !isNonNegativeInteger(summary.revision) ||
    !isDateTimeString(summary.generatedAt) ||
    !isRecord(summary.counts) ||
    !isRecord(summary.auditSummary24h) ||
    !Array.isArray(summary.governanceTodos) ||
    !summary.governanceTodos.every(isString) ||
    !Array.isArray(summary.serviceHealth) ||
    !summary.serviceHealth.every(isServiceHealth) ||
    !Array.isArray(summary.recentActions) ||
    !summary.recentActions.every(isAdminAction)
  ) {
    throw new Error("平台总览返回的数据不完整。");
  }
  const counts = summary.counts;
  const audit = summary.auditSummary24h;
  if (
    !hasExactKeys(counts, ["tenants", "users", "pendingAdmission", "abnormalRuns"]) ||
    !hasExactKeys(audit, ["actionCount", "failedCount", "from", "to"]) ||
    !isNonNegativeInteger(counts.tenants) ||
    !isNonNegativeInteger(counts.users) ||
    !isNonNegativeInteger(counts.pendingAdmission) ||
    !isNonNegativeInteger(counts.abnormalRuns) ||
    !isNonNegativeInteger(audit.actionCount) ||
    !isNonNegativeInteger(audit.failedCount) ||
    !isDateTimeString(audit.from) ||
    !isDateTimeString(audit.to)
  ) {
    throw new Error("平台总览返回的数据不完整。");
  }
  if (
    audit.failedCount > audit.actionCount ||
    Date.parse(audit.from) > Date.parse(audit.to)
  ) {
    throw new Error("平台总览返回的审计事实不一致。");
  }
  return value as AdminDashboardResponse;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isNonEmptyString(value: unknown): value is string {
  return isString(value) && value.trim().length > 0;
}

function isDateTimeString(value: unknown): value is string {
  return isNonEmptyString(value) && !Number.isNaN(Date.parse(value));
}


function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isServiceHealth(value: unknown): value is AdminOverview["serviceHealth"][number] {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["service", "status", "checkedAt"]) &&
    isNonEmptyString(value.service) &&
    isString(value.status) &&
    HEALTH_STATUSES.has(value.status as ServiceHealthStatus) &&
    isDateTimeString(value.checkedAt)
  );
}

function isAdminAction(value: unknown): value is AdminOverview["recentActions"][number] {
  // action/targetType/status 只按「非空字符串」校验形状,不再要求命中一个固定
  // Set——那个 Set 是前端本地维护的,会先于后端的真实取值范围过时。校验只负责
  // 拒绝结构不对的数据;取值是否认识、认不出时怎么显示,交给 actionLabel /
  // actionTargetTypeLabel / actionStatusLabel 逐条兜底（见上方）,不让一条没
  // 见过的审计记录把整个平台总览拖垮成一片报错。
  return (
    isRecord(value) &&
    hasExactKeys(value, ["publicActionId", "action", "targetType", "reasonSummary", "status", "createdAt"]) &&
    isNonEmptyString(value.publicActionId) &&
    isPublicId(value.publicActionId) &&
    isNonEmptyString(value.action) &&
    isNonEmptyString(value.targetType) &&
    isNonEmptyString(value.reasonSummary) &&
    isNonEmptyString(value.status) &&
    isDateTimeString(value.createdAt)
  );
}

function formatDateTime(value: string): string {
  return formatShortDateTime(value, { empty: ECHO_INVALID, invalid: ECHO_INVALID });
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === expected.length && expected.every((key) => Object.prototype.hasOwnProperty.call(value, key));
}
