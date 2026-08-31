// Canonical loading/no-permission/empty/error surface panel (cluster FE-03). Structural
// baseline is TracksPage.tsx's `SurfaceState` (icon + title + detail + optional action,
// `data-state` attribute, aria-busy while loading) -- but per the audit's correction the
// `kind` union is widened past TracksPage's own four values to also cover PublishingPage's
// distinct `permission` variant (an unauthenticated visitor, rendered with a login CTA)
// alongside TracksPage's `forbidden` (an authenticated account lacking the entitlement, no
// CTA) rather than collapsing the two, plus DecisionsPage's `notFound`.
//
// Styling lives in mediaPrimitives.css's `.mg-state` family (global stylesheet, loaded once
// via main.tsx) rather than any page's CSS Module, precisely so this shared component isn't
// reaching into a page-private stylesheet it can't import.
//
// `PageGate` is a second, deliberately separate export for the *page-level* variant
// (DecisionsPage's `PageGate`, PersonalWorkspaceShellPage/OrganizationWorkspaceShellPage's
// shell states) that renders a `<main>` wrapper instead of an inline panel -- the audit
// flags folding that into `SurfaceState` as a risk, since a panel-only component forced
// into page-chrome duty would need an opt-out prop on every other caller.
import type { LucideIcon } from "lucide-react";
import { AlertCircle, Database, LoaderCircle, LogIn, SearchX, ShieldAlert } from "lucide-react";
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { loginUrl } from "../mediaWebApi";
import type { LoadState } from "./loadState";

export type SurfaceStateKind = "loading" | "permission" | "forbidden" | "error" | "empty" | "notFound";

const SURFACE_ICONS: Record<SurfaceStateKind, LucideIcon> = {
  loading: LoaderCircle,
  permission: LogIn,
  forbidden: ShieldAlert,
  error: AlertCircle,
  empty: Database,
  notFound: SearchX,
};

export function SurfaceState({
  kind,
  title,
  detail,
  action,
  density = "normal",
}: {
  kind: SurfaceStateKind;
  title: string;
  detail: string;
  action?: ReactNode;
  /** `compact` for an inline/embedded panel (ArchivesPage/UsageBillingPage's smaller variant). */
  density?: "normal" | "compact";
}) {
  const Icon = SURFACE_ICONS[kind];
  // PublishingPage's `permission` branch renders a login CTA and ignores any caller-supplied
  // action; every other kind falls back to whatever `action` the caller passed (or none).
  const resolvedAction =
    kind === "permission" && action === undefined ? (
      <a className="mg-state-action" href={loginUrl()}>
        <LogIn size={15} aria-hidden="true" />
        登录并查看
      </a>
    ) : (
      action
    );
  return (
    <div
      className="mg-state"
      data-density={density}
      data-state={kind}
      role={kind === "error" ? "alert" : "status"}
      aria-busy={kind === "loading"}
    >
      <span className="mg-state-icon">
        <Icon className={kind === "loading" ? "spin" : ""} size={density === "compact" ? 18 : 21} aria-hidden="true" />
      </span>
      <strong>{title}</strong>
      <p>{detail}</p>
      {resolvedAction}
    </div>
  );
}

/**
 * Page-level counterpart to `SurfaceState` -- wraps in a `<main>` instead of an inline
 * panel, for a shell page that occupies the whole route (DecisionsPage's `PageGate`;
 * PersonalWorkspaceShellPage/OrganizationWorkspaceShellPage's shell states).
 */
type PageGateDataAttributes = {
  [attribute: `data-${string}`]: string | boolean | undefined;
};

type PageGateRootProps = Pick<ComponentPropsWithoutRef<"main">, "className"> & PageGateDataAttributes;

type PageGateGateProps = Pick<ComponentPropsWithoutRef<"div">, "className" | "role" | "aria-busy"> & PageGateDataAttributes;

export function PageGate({
  title,
  detail,
  action,
  loading = false,
  "data-component": dataComponent,
  rootProps,
  gateProps,
}: {
  title: string;
  detail?: string;
  action?: ReactNode;
  loading?: boolean;
  /** Optional semantic marker for the gate region; omitted callers keep the original DOM. */
  "data-component"?: "mg-state";
  /** Optional route-root class/data metadata; omitted callers keep the original root DOM. */
  rootProps?: PageGateRootProps;
  /** Optional gate-region class/ARIA/data metadata, including a page-prelude marker. */
  gateProps?: PageGateGateProps;
}) {
  const { className: rootClassName, ...rootAttributes } = rootProps ?? {};
  const { className: gateClassName, ...gateAttributes } = gateProps ?? {};
  return (
    <main className={rootClassName ? `fidelity-page ${rootClassName}` : "fidelity-page"} {...rootAttributes}>
      <div
        className={gateClassName ? `detail-gate ${gateClassName}` : "detail-gate"}
        {...gateAttributes}
        data-component={dataComponent ?? gateAttributes["data-component"]}
      >
        {loading ? <LoaderCircle className="spin" size={24} aria-hidden="true" /> : <Database size={24} aria-hidden="true" />}
        <h1>{title}</h1>
        {detail ? <p>{detail}</p> : null}
        {action}
      </div>
    </main>
  );
}

/**
 * Dispatches a FE-04 `LoadState<T>` directly to `SurfaceState`, covering the "branch on
 * `state.status` and render a matching panel" pattern shared by TracksPage's `ListState`,
 * DecisionsPage's `StatePanel`, UsageBillingPage's `ResourceState`, and
 * PersonalWorkspaceShellPage's `PersonalListState`. Renders nothing for `idle`. For `ready`,
 * pass `isEmpty` to redirect a zero-length payload (e.g. `data.items.length === 0`) to the
 * `empty` panel instead of calling `render` -- otherwise `render` is called directly.
 */
export function ResourceStateView<T, E = string>({
  state,
  subject,
  loadingDetail,
  emptyTitle = "暂无内容",
  emptyDetail = "",
  describeError,
  isEmpty,
  density,
  render,
}: {
  state: LoadState<T, E>;
  subject: string;
  loadingDetail?: string;
  emptyTitle?: string;
  emptyDetail?: string;
  describeError?: (error: E) => string;
  isEmpty?: (data: T) => boolean;
  density?: "normal" | "compact";
  render: (data: T) => ReactNode;
}): ReactNode {
  const message = (error: E) => (describeError ? describeError(error) : String(error));
  if (state.status === "idle") return null;
  if (state.status === "loading") {
    return (
      <SurfaceState
        kind="loading"
        title={`正在读取${subject}`}
        detail={loadingDetail ?? `正在读取当前账户可见的${subject}。`}
        density={density}
      />
    );
  }
  if (state.status === "permission") {
    return <SurfaceState kind="permission" title="暂无查看权限" detail={message(state.error)} density={density} />;
  }
  if (state.status === "notFound") {
    return <SurfaceState kind="notFound" title="记录不存在" detail={message(state.error)} density={density} />;
  }
  if (state.status === "error") {
    return <SurfaceState kind="error" title={`${subject}读取失败`} detail={message(state.error)} density={density} />;
  }
  if (state.status === "empty") {
    return <SurfaceState kind="empty" title={emptyTitle} detail={emptyDetail} density={density} />;
  }
  if (isEmpty && isEmpty(state.data)) {
    return <SurfaceState kind="empty" title={emptyTitle} detail={emptyDetail} density={density} />;
  }
  return render(state.data);
}
