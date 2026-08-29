import {
  AlertCircle,
  ArrowRight,
  BadgeCheck,
  BarChart3,
  BookOpen,
  Database,
  ExternalLink,
  FlaskConical,
  ImageOff,
  LoaderCircle,
  LogIn,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Target,
  UserRound,
  WalletCards,
  X,
} from "lucide-react";
import { useEffect, useState, type Dispatch, type ReactNode } from "react";
import {
  BusinessOperationError,
  callBusinessOperation,
} from "../../generatedBusinessPagesContract";
import { useMediaWeb } from "../../MediaWebWorkspace";
import { loginUrl } from "../../mediaWebApi";
import { PageHeading } from "../../ui/ordinaryPagePrimitives";
import { newIdempotencyKey } from "../../ui/ordinaryPagePrimitives";
import {
  creatorRoleDisplayLabel,
  formatFitScore,
  operationalStatusDisplayLabel,
  ownedAccountDataSourceDisplayLabel,
  relationshipRoleDisplayLabel,
  trackStatusDisplayLabel,
} from "../../ui/ordinaryDataLabels";
import { PlatformIdentity } from "../../ui/PlatformIdentity";
import styles from "./TracksPage.module.css";

type TabId = "owned" | "tracks" | "benchmarks";
type RelationshipQueueStatus = "candidate" | "active" | "rejected";
type OwnedAccountFilter = "all" | "active" | "paused" | "disabled";
type TrackFilter = "all" | "active" | "observing";

type TrackSummary = {
  publicTrackId: string;
  name: string;
  description: string;
  parentPublicTrackId: string | null;
  status: string;
  platforms: string[];
  aliases: string[];
  artifactCount: number;
  updatedAt: string;
};

type CreatorSummary = {
  publicCreatorId: string;
  accountName: string;
  platform: string;
  creatorRole: string;
  identityTags: string[];
  expertiseDomains: string[];
  profileUrl: string | null;
  avatarUrl: string | null;
  updatedAt: string;
};

type TrackRelationship = {
  publicRelationshipId: string;
  publicTrackId: string;
  publicCreatorId: string;
  role: string;
  fitScore: number;
  fitReason: string;
  status: string;
  lastEvaluatedAt: string | null;
};

type OwnedAccountSummary = {
  publicAccountId: string;
  platform: string;
  accountName: string;
  operationalStatus: string | null;
  responsiblePerson: string | null;
  teamName: string | null;
  accountPositioning: string | null;
  dataSource: string | null;
  platformAccountId: string | null;
  profileUrl: string | null;
  avatarUrl: string | null;
  publicTrackIds: string[];
  lastSyncedAt: string | null;
  updatedAt: string;
};

type ListResponse<T> = {
  schemaVersion: string;
  revision: number;
  items: T[];
  nextCursor: string | null;
};

type DetailResponse<T> = {
  schemaVersion: string;
  revision: number;
  item: T;
};

type AccountMonitorResponse = {
  schemaVersion: string;
  revision: number;
  status: "available" | "unavailable";
  checkedAt: string | null;
  detail: string | null;
  enabled?: boolean;
  recentPostUrls?: string[];
};

type ResourceState<T> =
  | { kind: "loading" }
  | { kind: "ready"; data: T }
  | { kind: "forbidden"; message: string }
  | { kind: "error"; message: string };

const tabs: Array<{ id: TabId; label: string }> = [
  { id: "owned", label: "自有账号" },
  { id: "tracks", label: "赛道概览" },
  { id: "benchmarks", label: "对标账号" },
];

const relationshipQueues: Array<{ status: RelationshipQueueStatus; label: string }> = [
  { status: "candidate", label: "待确认" },
  { status: "active", label: "已关注" },
  { status: "rejected", label: "已忽略" },
];

const benchmarkRoles = ["标杆账号", "同赛道观察", "合作候选"] as const;

function TracksPage() {
  const { runtimeState, session, tasks, openWorkspace } = useMediaWeb();
  const [activeTab, setActiveTab] = useState<TabId>("owned");
  const [accountSearch, setAccountSearch] = useState("");
  const [trackSearch, setTrackSearch] = useState("");
  const [creatorSearch, setCreatorSearch] = useState("");
  const [selectedTrackId, setSelectedTrackId] = useState<string | null>(null);
  const [selectedCreatorId, setSelectedCreatorId] = useState<string | null>(null);
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);
  const [ownedTrackFilter, setOwnedTrackFilter] = useState<string | null>(null);
  const [benchmarkTrackFilter, setBenchmarkTrackFilter] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [trackState, setTrackState] = useState<ResourceState<ListResponse<TrackSummary>>>({
    kind: "loading",
  });
  const [creatorState, setCreatorState] = useState<ResourceState<ListResponse<CreatorSummary>>>({
    kind: "loading",
  });
  const [relationshipState, setRelationshipState] = useState<
    ResourceState<ListResponse<TrackRelationship>>
  >({ kind: "loading" });
  const [accountState, setAccountState] = useState<
    ResourceState<ListResponse<OwnedAccountSummary>>
  >({ kind: "loading" });
  const [creatorDetailState, setCreatorDetailState] = useState<
    ResourceState<DetailResponse<CreatorSummary>> | null
  >(null);
  const [accountDetailState, setAccountDetailState] = useState<
    ResourceState<DetailResponse<OwnedAccountSummary>> | null
  >(null);
  const [accountMonitorState, setAccountMonitorState] = useState<
    ResourceState<AccountMonitorResponse> | null
  >(null);
  const taskRefreshKey = tasks
    .filter(
      (task) =>
        task.terminal &&
        task.result?.ok &&
        ["creator_profile_upsert", "external_research_brief"].includes(
          task.capabilityId,
        ),
    )
    .map((task) => `${task.taskId}:${task.updatedAt}`)
    .sort()
    .join("|");
  useEffect(() => {
    if (runtimeState !== "authenticated" || !session) return;
    const controller = new AbortController();
    setTrackState({ kind: "loading" });
    setCreatorState({ kind: "loading" });
    setRelationshipState({ kind: "loading" });
    setAccountState({ kind: "loading" });

    loadList<TrackSummary>(
      "listTracks",
      "赛道列表",
      { cursor: undefined, pageSize: 20, search: trackSearch || undefined },
      controller.signal,
      setTrackState,
    );
    loadList<CreatorSummary>(
      "listCreators",
      "博主档案",
      { cursor: undefined, pageSize: 20, search: creatorSearch || undefined },
      controller.signal,
      setCreatorState,
    );
    loadList<TrackRelationship>(
      "listTrackRelationships",
      "账号归属",
      { cursor: undefined, pageSize: 20 },
      controller.signal,
      setRelationshipState,
    );
    loadList<OwnedAccountSummary>(
      "listOwnedAccounts",
      "自有账号",
      { cursor: undefined, pageSize: 20 },
      controller.signal,
      setAccountState,
    );

    return () => controller.abort();
  }, [creatorSearch, refreshToken, runtimeState, session, taskRefreshKey, trackSearch]);

  useEffect(() => {
    if (!selectedCreatorId || runtimeState !== "authenticated" || !session) {
      setCreatorDetailState(null);
      return;
    }
    const controller = new AbortController();
    setCreatorDetailState({ kind: "loading" });
    callBusinessOperation<DetailResponse<CreatorSummary>>("getCreator", {
      path: { publicCreatorId: selectedCreatorId },
      signal: controller.signal,
    })
      .then((data) => setCreatorDetailState({ kind: "ready", data }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setCreatorDetailState(toResourceError(error, "博主档案详情"));
      });
    return () => controller.abort();
  }, [runtimeState, selectedCreatorId, session]);

  useEffect(() => {
    if (!selectedAccountId || runtimeState !== "authenticated" || !session) {
      setAccountDetailState(null);
      return;
    }
    const controller = new AbortController();
    setAccountDetailState({ kind: "loading" });
    callBusinessOperation<DetailResponse<OwnedAccountSummary>>("getOwnedAccount", {
      path: { publicAccountId: selectedAccountId },
      signal: controller.signal,
    })
      .then((data) => setAccountDetailState({ kind: "ready", data }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setAccountDetailState(toResourceError(error, "自有账号详情"));
        }
      });
    return () => controller.abort();
  }, [runtimeState, selectedAccountId, session]);

  useEffect(() => {
    if (!selectedAccountId || runtimeState !== "authenticated" || !session) {
      setAccountMonitorState(null);
      return;
    }
    const controller = new AbortController();
    setAccountMonitorState({ kind: "loading" });
    callBusinessOperation<AccountMonitorResponse>("getAccountMonitor", {
      path: { publicAccountId: selectedAccountId },
      signal: controller.signal,
    })
      .then((data) => setAccountMonitorState({ kind: "ready", data }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setAccountMonitorState(toMonitorResourceError(error));
        }
      });
    return () => controller.abort();
  }, [runtimeState, selectedAccountId, session]);

  const resources: Array<{ label: string; state: ResourceState<unknown> }> = [
    { label: "赛道列表", state: trackState },
    { label: "博主档案", state: creatorState },
    { label: "账号归属", state: relationshipState },
    { label: "自有账号", state: accountState },
  ];
  const hasReadyResource = resources.some((resource) => resource.state.kind === "ready");
  const hasFailedResource = resources.some(
    (resource) => resource.state.kind === "forbidden" || resource.state.kind === "error",
  );
  const pageState = !hasReadyResource && hasFailedResource
    ? "error"
    : hasReadyResource && hasFailedResource
      ? "partial"
      : resources.every((resource) => resource.state.kind === "loading")
        ? "loading"
        : "ready";

  if (runtimeState === "checking") {
    return (
      <main className={["fidelity-page", styles.page].join(" ")} data-page-state="loading">
        <SurfaceState kind="loading" title="正在确认访问权限" detail="页面数据将在身份确认后读取。" />
      </main>
    );
  }

  if (runtimeState === "unauthenticated" || !session) {
    return (
      <main className={["fidelity-page", styles.page].join(" ")} data-page-state="forbidden">
        <SurfaceState
          kind="forbidden"
          title="需要登录才能查看"
          detail="此页面只展示当前账户可读的赛道账号和运营资料。"
          action={
            <a className={styles.loginLink} href={loginUrl()}>
              <LogIn size={15} aria-hidden="true" />
              登录并查看
            </a>
          }
        />
      </main>
    );
  }

  if (runtimeState === "unavailable") {
    return (
      <main className={["fidelity-page", styles.page].join(" ")} data-page-state="error">
        <SurfaceState
          kind="error"
          title="暂时无法读取页面数据"
          detail="当前身份服务尚未就绪，请稍后再试。"
        />
      </main>
    );
  }

  const primaryActionAvailable = activeTab === "benchmarks";
  const openRelationshipPreview = (relationship: TrackRelationship) =>
    openWorkspace({
      capabilityId: "track_creator_membership_query",
      variantId: "preview",
      params: {
        action: "关系预览",
        id: relationship.publicTrackId,
        id_869e433eadc3: relationship.publicCreatorId,
        field_c47b54e84e79: relationship.role,
        field_76a17ec0d96f: relationship.fitScore,
        field_f93c8842699c: relationship.fitReason,
      },
    });

  return (
    <main className={["fidelity-page", styles.page].join(" ")} data-page-state={pageState}>
      <div className={styles.headingRow} data-page-prelude>
        <PageHeading
          title="账号与赛道"
          description="管理自有账号、了解赛道运营情况，并持续跟踪值得研究的对标账号。"
        />
        <div className={`page-heading-actions ${styles.headingActions}`}>
          <button
            className={styles.secondaryAction}
            type="button"
            onClick={() => setRefreshToken((value) => value + 1)}
            title="刷新账号与赛道数据"
          >
            <RefreshCw size={16} aria-hidden="true" />
            刷新
          </button>
          {primaryActionAvailable ? (
            <button
              className={styles.primaryAction}
              type="button"
              title="从公开主页添加对标账号候选"
              data-capability-action="creator_profile_upsert"
              onClick={() => {
                openWorkspace({
                  capabilityId: "creator_profile_upsert",
                  variantId: "url_candidate",
                });
              }}
            >
              <Plus size={16} aria-hidden="true" />
              添加对标账号
            </button>
          ) : null}
        </div>
      </div>

      <nav className={styles.tabList} aria-label="账号与赛道视图" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={[
              styles.tabButton,
              activeTab === tab.id ? styles.tabButtonActive : "",
            ].join(" ")}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls={tab.id + "-tabpanel"}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {pageState === "partial" ? (
        <ProjectionDegradationNotice
          resources={resources}
          onRetry={() => setRefreshToken((value) => value + 1)}
        />
      ) : null}

      <div className={styles.workspace} data-page-layout="persistent-rail">
        <div className={styles.primaryColumn} data-page-primary data-primary-flow>
          {activeTab === "owned" ? (
            <OwnedAccountsTab
              state={accountState}
              trackState={trackState}
              selectedAccountId={selectedAccountId}
              trackFilter={ownedTrackFilter}
              search={accountSearch}
              onSearch={setAccountSearch}
              onSelect={setSelectedAccountId}
              onClearTrackFilter={() => setOwnedTrackFilter(null)}
            />
          ) : activeTab === "tracks" ? (
            <TracksOverviewTab
              state={trackState}
              accountState={accountState}
              relationshipState={relationshipState}
              selectedTrackId={selectedTrackId}
              search={trackSearch}
              onSearch={setTrackSearch}
              onSelect={setSelectedTrackId}
            />
          ) : (
            <BenchmarkAccountsTab
              state={relationshipState}
              accountState={accountState}
              trackState={trackState}
              creatorState={creatorState}
              selectedCreatorId={selectedCreatorId}
              trackFilter={benchmarkTrackFilter}
              search={creatorSearch}
              onSearch={setCreatorSearch}
              onSelectCreator={setSelectedCreatorId}
              onClearTrackFilter={() => setBenchmarkTrackFilter(null)}
            />
          )}
        </div>

        {activeTab === "owned" ? (
          <OwnedAccountInspector
            selectedAccountId={selectedAccountId}
            state={accountDetailState}
            monitorState={accountMonitorState}
            session={session}
            trackState={trackState}
          />
        ) : activeTab === "tracks" ? (
          <TrackInspector
            selectedTrackId={selectedTrackId}
            trackState={trackState}
            accountState={accountState}
            relationshipState={relationshipState}
            creatorState={creatorState}
            onResearch={(track) =>
              openWorkspace({
                capabilityId: "external_research_brief",
                variantId: "default",
                params: { track: track.name },
              })
            }
            onShowOwned={(trackId) => {
              setOwnedTrackFilter(trackId);
              setActiveTab("owned");
            }}
            onShowBenchmarks={(trackId) => {
              setBenchmarkTrackFilter(trackId);
              setActiveTab("benchmarks");
            }}
          />
        ) : (
          <BenchmarkInspector
            selectedCreatorId={selectedCreatorId}
            state={creatorDetailState}
            relationshipState={relationshipState}
            trackState={trackState}
            trackFilter={benchmarkTrackFilter}
            onPreviewRelationship={openRelationshipPreview}
            onCapture={(creator) => {
              if (!creator.profileUrl) return;
              openWorkspace({
                capabilityId: "creator_profile_upsert",
                variantId: "url_candidate",
                params: {
                  profile_url: creator.profileUrl,
                  account_name: creator.accountName,
                  platform: creator.platform,
                },
              });
            }}
          />
        )}
      </div>
    </main>
  );
}

function TracksOverviewTab({
  state,
  accountState,
  relationshipState,
  selectedTrackId,
  search,
  onSearch,
  onSelect,
}: {
  state: ResourceState<ListResponse<TrackSummary>>;
  accountState: ResourceState<ListResponse<OwnedAccountSummary>>;
  relationshipState: ResourceState<ListResponse<TrackRelationship>>;
  selectedTrackId: string | null;
  search: string;
  onSearch: (value: string) => void;
  onSelect: (id: string) => void;
}) {
  const [activeFilter, setActiveFilter] = useState<TrackFilter>("all");
  const tracks = state.kind === "ready" ? state.data.items : [];
  const accounts = accountState.kind === "ready" ? accountState.data.items : [];
  const relationships = relationshipState.kind === "ready" ? relationshipState.data.items : [];
  const ownedAccountIds = new Set(accounts.map((account) => account.publicAccountId));
  const filterOptions: Array<{ id: TrackFilter; label: string; count: number }> = [
    { id: "all", label: "全部", count: tracks.length },
    {
      id: "active",
      label: "重点运营",
      count: tracks.filter((track) => normalizedStatus(track.status) === "active").length,
    },
    {
      id: "observing",
      label: "观察中",
      count: tracks.filter((track) => ["draft", "paused"].includes(normalizedStatus(track.status))).length,
    },
  ];
  const visibleTracks = tracks.filter((track) => {
    if (activeFilter === "active") return normalizedStatus(track.status) === "active";
    if (activeFilter === "observing") {
      return ["draft", "paused"].includes(normalizedStatus(track.status));
    }
    return true;
  });

  return (
    <section
      className={styles.tabContent}
      id="tracks-tabpanel"
      role="tabpanel"
      aria-label="赛道概览"
      data-page-terminal-surface="primary"
    >
      <DataPanel title="赛道概览" detail={`${visibleTracks.length} 个赛道`} icon={<Target size={17} aria-hidden="true" />}>
        <div className={styles.toolbarRow}>
          <SearchBox label="搜索赛道" value={search} onChange={onSearch} />
          <SegmentedFilter
            label="赛道状态"
            options={filterOptions}
            value={activeFilter}
            onChange={setActiveFilter}
          />
        </div>
        <ListState state={state} emptyTitle="暂无赛道" emptyDetail="当前租户还没有可读的赛道登记。" />
        {state.kind === "ready" && visibleTracks.length === 0 ? (
          <SurfaceState kind="empty" title="没有符合条件的赛道" detail="调整状态筛选或搜索条件后再试。" />
        ) : null}
        {state.kind === "ready" && visibleTracks.length > 0 ? (
          <div className={[styles.itemList, styles.primaryList].join(" ")} data-page-list="tracks">
            {visibleTracks.map((track) => {
              const trackAccounts = accounts.filter((account) =>
                account.publicTrackIds.includes(track.publicTrackId),
              );
              const trackRelationships = relationships.filter(
                (relationship) =>
                  relationship.publicTrackId === track.publicTrackId &&
                  normalizedStatus(relationship.status) !== "rejected" &&
                  !ownedAccountIds.has(relationship.publicCreatorId),
              );
              const benchmarkCount = new Set(
                trackRelationships.map((relationship) => relationship.publicCreatorId),
              ).size;
              const roleCounts = benchmarkRoles.map((role) => ({
                role,
                count: trackRelationships.filter(
                  (relationship) => relationshipRoleDisplayLabel(relationship.role) === role,
                ).length,
              }));
              return (
              <button
                key={track.publicTrackId}
                className={[
                  styles.overviewItem,
                  selectedTrackId === track.publicTrackId ? styles.itemButtonActive : "",
                ].join(" ")}
                type="button"
                onClick={() => onSelect(track.publicTrackId)}
              >
                <span className={styles.itemHeadline}>
                  <span className={styles.itemTitle}>{track.name}</span>
                  <StatusBadge tone={normalizedStatus(track.status) === "active" ? "success" : "neutral"}>
                    {normalizedStatus(track.status) === "active" ? "重点运营" : trackStatusDisplayLabel(track.status)}
                  </StatusBadge>
                </span>
                <span className={styles.itemDescription} data-long-content>{track.description || "赛道定位未记录"}</span>
                <span className={styles.layoutSummary}>
                  <strong>自有账号 {trackAccounts.length}</strong>
                  <span>对标账号 {benchmarkCount}</span>
                </span>
                <span className={styles.roleSummary}>
                  {roleCounts.map(({ role, count }) => (
                    <span key={role}>{role.replace("账号", "")} {count}</span>
                  ))}
                </span>
                <span className={[styles.itemMeta, styles.itemMetaRow].join(" ")}>
                  {track.platforms.length ? (
                    <span className={styles.platformList} aria-label="适用平台">
                      {track.platforms.map((platform, index) => (
                        <PlatformIdentity
                          key={`${platform}-${index}`}
                          platform={platform}
                          size="sm"
                        />
                      ))}
                    </span>
                  ) : <span>重点平台未记录</span>}
                  <span className={styles.metaSeparator} aria-hidden="true">·</span>
                  <span>{track.artifactCount} 个研究成果</span>
                </span>
              </button>
              );
            })}
          </div>
        ) : null}
      </DataPanel>
    </section>
  );
}

function OwnedAccountsTab({
  state,
  trackState,
  selectedAccountId,
  trackFilter,
  search,
  onSearch,
  onSelect,
  onClearTrackFilter,
}: {
  state: ResourceState<ListResponse<OwnedAccountSummary>>;
  trackState: ResourceState<ListResponse<TrackSummary>>;
  selectedAccountId: string | null;
  trackFilter: string | null;
  search: string;
  onSearch: (value: string) => void;
  onSelect: (id: string) => void;
  onClearTrackFilter: () => void;
}) {
  const [activeFilter, setActiveFilter] = useState<OwnedAccountFilter>("all");
  const accounts = state.kind === "ready" ? state.data.items : [];
  const tracks = trackState.kind === "ready" ? trackState.data.items : [];
  const trackById = new Map(tracks.map((track) => [track.publicTrackId, track]));
  const normalizedSearch = search.trim().toLowerCase();
  const filterOptions: Array<{ id: OwnedAccountFilter; label: string; count: number }> = [
    { id: "all", label: "全部", count: accounts.length },
    { id: "active", label: "运营中", count: accounts.filter((account) => hasOperationalStatus(account, "active")).length },
    { id: "paused", label: "暂停运营", count: accounts.filter((account) => hasOperationalStatus(account, "paused")).length },
    { id: "disabled", label: "已停用", count: accounts.filter((account) => hasOperationalStatus(account, "disabled")).length },
  ];
  const visibleAccounts = accounts.filter((account) => {
    if (activeFilter !== "all" && !hasOperationalStatus(account, activeFilter)) return false;
    if (trackFilter && !account.publicTrackIds.includes(trackFilter)) return false;
    if (!normalizedSearch) return true;
    return [account.accountName, account.platform]
      .some((value) => value.toLowerCase().includes(normalizedSearch));
  });
  const filteredTrack = trackFilter ? trackById.get(trackFilter) ?? null : null;

  return (
    <section
      className={styles.tabContent}
      id="owned-tabpanel"
      role="tabpanel"
      aria-label="自有账号"
      data-page-terminal-surface="primary"
    >
      <DataPanel title="自有账号" detail={`${visibleAccounts.length} 个账号`} icon={<WalletCards size={17} aria-hidden="true" />}>
        <div className={styles.toolbarRow}>
          <SearchBox label="搜索当前页账号" value={search} onChange={onSearch} />
          <SegmentedFilter
            label="账号状态"
            options={filterOptions}
            value={activeFilter}
            onChange={setActiveFilter}
          />
        </div>
        {filteredTrack ? (
          <ContextFilter label={`赛道：${filteredTrack.name}`} onClear={onClearTrackFilter} />
        ) : null}
        <ListState state={state} emptyTitle="暂无自有账号" emptyDetail="登记账号身份、责任人和运营定位后，自有账号会显示在这里。" />
        {state.kind === "ready" && accounts.length > 0 && visibleAccounts.length === 0 ? (
          <SurfaceState kind="empty" title="没有符合条件的账号" detail="调整状态、赛道或搜索条件后再试。" />
        ) : null}
        {state.kind === "ready" && visibleAccounts.length > 0 ? (
          <div className={[styles.itemList, styles.primaryList].join(" ")} data-page-list="owned-accounts">
            {visibleAccounts.map((account) => {
              const accountTracks = account.publicTrackIds
                .map((trackId) => trackById.get(trackId)?.name)
                .filter((name): name is string => Boolean(name));
              const statusTone = operationalStatusTone(account.operationalStatus);
              return (
              <button
                key={account.publicAccountId}
                className={[
                  styles.accountListItem,
                  selectedAccountId === account.publicAccountId ? styles.itemButtonActive : "",
                ].join(" ")}
                type="button"
                onClick={() => onSelect(account.publicAccountId)}
              >
                <span className={styles.accountIdentity}>
                  <AccountAvatar account={account} size="list" />
                  <span className={styles.accountIdentityCopy}>
                    <span className={styles.itemHeadline}>
                      <span className={styles.itemTitle}>{account.accountName}</span>
                      <StatusBadge tone={statusTone}>
                        {operationalStatusDisplayLabel(account.operationalStatus)}
                      </StatusBadge>
                    </span>
                    <span className={[styles.itemMeta, styles.itemMetaRow].join(" ")}>
                      <PlatformIdentity platform={account.platform} size="sm" />
                      <span className={styles.metaSeparator} aria-hidden="true">·</span>
                      <span>{account.platformAccountId ? `平台账号 ${account.platformAccountId}` : "平台账号未记录"}</span>
                    </span>
                  </span>
                </span>
                <span className={styles.itemDescription}>负责人：{account.responsiblePerson ?? "未记录"}</span>
                <span className={styles.accountOperationalRow}>
                  <span className={operationalStatusTextClass(account.operationalStatus)}>
                    {hasOperationalStatus(account, "active")
                      ? <BadgeCheck size={14} aria-hidden="true" />
                      : <AlertCircle size={14} aria-hidden="true" />}
                    {operationalStatusDisplayLabel(account.operationalStatus)}
                  </span>
                  <span>{accountTracks.join(" / ") || "运营赛道未记录"}</span>
                </span>
                <span className={styles.itemFoot}>
                  {account.lastSyncedAt ? `数据更新于 ${formatRelativeTime(account.lastSyncedAt)}` : "暂无运营数据"}
                </span>
              </button>
              );
            })}
          </div>
        ) : null}
      </DataPanel>
    </section>
  );
}

function AccountAvatar({
  account,
  size,
}: {
  account: Pick<OwnedAccountSummary, "publicAccountId" | "accountName" | "avatarUrl">;
  size: "list" | "detail";
}) {
  const [avatarFailed, setAvatarFailed] = useState(false);

  useEffect(() => {
    setAvatarFailed(false);
  }, [account.publicAccountId, account.avatarUrl]);

  const showImage = Boolean(account.avatarUrl) && !avatarFailed;
  return (
    <span
      className={[styles.avatar, size === "list" ? styles.accountListAvatar : ""].join(" ")}
      data-account-avatar
      data-avatar-size={size}
      data-avatar-state={showImage ? "image" : avatarFailed ? "fallback" : "empty"}
    >
      {showImage ? (
        <img
          className={styles.avatarImage}
          src={account.avatarUrl ?? undefined}
          alt={`${account.accountName}头像`}
          referrerPolicy="no-referrer"
          data-account-avatar-image
          onError={() => setAvatarFailed(true)}
        />
      ) : <UserRound size={size === "list" ? 17 : 23} aria-hidden="true" />}
    </span>
  );
}

function BenchmarkAccountsTab({
  state,
  accountState,
  trackState,
  creatorState,
  selectedCreatorId,
  trackFilter,
  search,
  onSearch,
  onSelectCreator,
  onClearTrackFilter,
}: {
  state: ResourceState<ListResponse<TrackRelationship>>;
  accountState: ResourceState<ListResponse<OwnedAccountSummary>>;
  trackState: ResourceState<ListResponse<TrackSummary>>;
  creatorState: ResourceState<ListResponse<CreatorSummary>>;
  selectedCreatorId: string | null;
  trackFilter: string | null;
  search: string;
  onSearch: (value: string) => void;
  onSelectCreator: (id: string) => void;
  onClearTrackFilter: () => void;
}) {
  const [activeQueue, setActiveQueue] = useState<RelationshipQueueStatus>("candidate");
  const relationships = state.kind === "ready" ? state.data.items : [];
  const ownedAccountIds = accountState.kind === "ready"
    ? new Set(accountState.data.items.map((account) => account.publicAccountId))
    : null;
  const tracks = trackState.kind === "ready" ? trackState.data.items : [];
  const creators = creatorState.kind === "ready" ? creatorState.data.items : [];
  const trackById = new Map(tracks.map((track) => [track.publicTrackId, track]));
  const creatorById = new Map(creators.map((creator) => [creator.publicCreatorId, creator]));
  const scopedRelationships = relationships.filter((relationship) => !ownedAccountIds?.has(relationship.publicCreatorId));
  const filteredRelationships = trackFilter
    ? scopedRelationships.filter((relationship) => relationship.publicTrackId === trackFilter)
    : scopedRelationships;
  const relationshipsByCreator = new Map<string, TrackRelationship[]>();
  for (const relationship of filteredRelationships) {
    const existing = relationshipsByCreator.get(relationship.publicCreatorId) ?? [];
    relationshipsByCreator.set(relationship.publicCreatorId, [...existing, relationship]);
  }
  const benchmarkAccounts = Array.from(relationshipsByCreator, ([publicCreatorId, items]) => ({
    publicCreatorId,
    creator: creatorById.get(publicCreatorId) ?? null,
    relationships: items,
    status: benchmarkManagementStatus(items),
  }));
  const queueCounts = relationshipQueues.reduce<Record<RelationshipQueueStatus, number>>(
    (counts, queue) => ({
      ...counts,
      [queue.status]: benchmarkAccounts.filter((item) => item.status === queue.status).length,
    }),
    { candidate: 0, active: 0, rejected: 0 },
  );
  const normalizedSearch = search.trim().toLowerCase();
  const visibleAccounts = benchmarkAccounts.filter((item) => {
    if (item.status !== activeQueue) return false;
    if (!normalizedSearch) return true;
    const relationshipText = item.relationships.flatMap((relationship) => [
      trackById.get(relationship.publicTrackId)?.name ?? "",
      relationshipRoleDisplayLabel(relationship.role),
    ]);
    return [item.creator?.accountName ?? "", item.creator?.platform ?? "", ...relationshipText]
      .some((value) => value.toLowerCase().includes(normalizedSearch));
  });
  const invalidStatusCount = filteredRelationships.filter(
    (relationship) => !isRelationshipQueueStatus(relationship.status),
  ).length;
  const activeQueueLabel = relationshipQueues.find((queue) => queue.status === activeQueue)?.label ?? "待确认";
  const filteredTrack = trackFilter ? trackById.get(trackFilter) ?? null : null;

  return (
    <section
      className={styles.tabContent}
      id="benchmarks-tabpanel"
      role="tabpanel"
      aria-label="对标账号"
      data-page-terminal-surface="primary"
    >
      <DataPanel
        title="对标账号"
        detail={`${queueCounts[activeQueue]} 个${activeQueueLabel}账号`}
        icon={<UserRound size={17} aria-hidden="true" />}
      >
        <div className={styles.toolbarRow}>
          <SearchBox label="搜索对标账号" value={search} onChange={onSearch} />
          <SegmentedFilter
            label="关注状态"
            options={relationshipQueues.map((queue) => ({ ...queue, id: queue.status, count: queueCounts[queue.status] }))}
            value={activeQueue}
            onChange={setActiveQueue}
          />
        </div>
        {filteredTrack ? (
          <ContextFilter label={`赛道：${filteredTrack.name}`} onClear={onClearTrackFilter} />
        ) : null}
        {invalidStatusCount > 0 ? (
          <div className={styles.statusWarning} role="status">
            有 {invalidStatusCount} 条关系记录的管理状态待确认，请检查数据源。
          </div>
        ) : null}
        {state.kind !== "ready" ? (
          <ListState
            state={state}
            emptyTitle="暂无账号记录"
            emptyDetail="当前还没有可管理的赛道账号。"
          />
        ) : visibleAccounts.length === 0 ? (
          <SurfaceState
            kind="empty"
            title={`暂无${activeQueueLabel}账号`}
            detail="调整关注状态、赛道或搜索条件后再试。"
          />
        ) : (
          <div
            className={[styles.relationshipList, styles.relationshipListFill].join(" ")}
            data-page-list="benchmark-accounts"
            id="benchmark-queue-panel"
            role="tabpanel"
            aria-label={`${activeQueueLabel}账号`}
          >
            {visibleAccounts.map((item) => (
              <BenchmarkAccountItem
                key={item.publicCreatorId}
                creator={item.creator}
                relationships={item.relationships}
                trackById={trackById}
                selected={selectedCreatorId === item.publicCreatorId}
                onSelect={() => onSelectCreator(item.publicCreatorId)}
              />
            ))}
          </div>
        )}
      </DataPanel>
    </section>
  );
}

function BenchmarkAccountItem({
  creator,
  relationships,
  trackById,
  selected,
  onSelect,
}: {
  creator: CreatorSummary | null;
  relationships: TrackRelationship[];
  trackById: Map<string, TrackSummary>;
  selected: boolean;
  onSelect: () => void;
}) {
  const accountName = creator?.accountName ?? "未找到账号";
  const identityInitial = creator?.accountName.trim().slice(0, 1) || "?";
  const bestScore = relationships.reduce(
    (current, relationship) => Math.max(current, relationship.fitScore),
    Number.NEGATIVE_INFINITY,
  );

  return (
    <button
      className={[styles.benchmarkItem, selected ? styles.relationshipItemActive : ""].join(" ")}
      type="button"
      onClick={onSelect}
      aria-label={`查看${accountName}对标账号详情`}
    >
      <span className={styles.relationshipIdentity}>
        <span className={styles.identityMark} aria-hidden="true">{identityInitial}</span>
        <span className={styles.identityCopy}>
          <strong>{accountName}</strong>
          <span className={styles.profilePlatformRow}>
            <PlatformIdentity platform={creator?.platform} size="sm" />
            <span className={styles.metaSeparator} aria-hidden="true">·</span>
            <span>粉丝数未记录</span>
          </span>
        </span>
      </span>
      <span className={styles.benchmarkRelations}>
        {relationships.slice(0, 3).map((relationship) => (
          <span key={relationship.publicRelationshipId}>
            <strong>{trackById.get(relationship.publicTrackId)?.name ?? "赛道待同步"}</strong>
            <StatusBadge tone="accent">{relationshipRoleDisplayLabel(relationship.role)}</StatusBadge>
          </span>
        ))}
      </span>
      <span className={styles.scoreRow}>
        <span>{Number.isFinite(bestScore) ? `最高${formatFitScore(bestScore)}` : "匹配度未记录"}</span>
        <span>{creator ? creator.expertiseDomains.join(" / ") || "内容定位未记录" : "档案待同步"}</span>
      </span>
      <span className={styles.itemFoot}>
        {relationships.length} 个关联赛道
        <ArrowRight size={14} aria-hidden="true" />
      </span>
    </button>
  );
}

function BenchmarkInspector({
  selectedCreatorId,
  state,
  relationshipState,
  trackState,
  trackFilter,
  onPreviewRelationship,
  onCapture,
}: {
  selectedCreatorId: string | null;
  state: ResourceState<DetailResponse<CreatorSummary>> | null;
  relationshipState: ResourceState<ListResponse<TrackRelationship>>;
  trackState: ResourceState<ListResponse<TrackSummary>>;
  trackFilter: string | null;
  onPreviewRelationship: (relationship: TrackRelationship) => void;
  onCapture: (creator: CreatorSummary) => void;
}) {
  const creator = state?.kind === "ready" ? state.data.item : null;
  const [avatarFailed, setAvatarFailed] = useState(false);
  const tracks = trackState.kind === "ready" ? trackState.data.items : [];
  const trackById = new Map(tracks.map((track) => [track.publicTrackId, track]));
  const relationships = relationshipState.kind === "ready"
    ? relationshipState.data.items.filter(
      (relationship) =>
        relationship.publicCreatorId === selectedCreatorId &&
        (!trackFilter || relationship.publicTrackId === trackFilter),
    )
    : [];

  useEffect(() => {
    setAvatarFailed(false);
  }, [creator?.publicCreatorId, creator?.avatarUrl]);

  return (
    <aside className={styles.inspectorColumn} data-page-inspector>
      <section className={styles.inspectorPanel} data-page-terminal-surface="inspector" aria-label="对标账号详情">
        <PanelHeader title="对标账号详情" detail={selectedCreatorId ? "公开资料与判断" : "未选择"} icon={<UserRound size={17} aria-hidden="true" />} />
        {!selectedCreatorId ? (
          <SurfaceState kind="empty" title="选择一个对标账号" detail="从左侧列表选择后查看内容画像、资料凭证和赛道关系。" />
        ) : state?.kind === "loading" ? (
          <SurfaceState kind="loading" title="正在读取对标账号" detail="正在读取当前租户可见的公开档案。" />
        ) : state?.kind === "forbidden" ? (
          <SurfaceState kind="forbidden" title="无权查看该档案" detail={state.message} />
        ) : state?.kind === "error" ? (
          <SurfaceState kind="error" title="账号资料读取失败" detail={state.message} />
        ) : creator ? (
          <div className={styles.inspectorBody}>
            <div className={styles.profileHeader}>
              <span className={styles.avatar}>
                {creator.avatarUrl && !avatarFailed ? (
                  <img
                    className={styles.avatarImage}
                    src={creator.avatarUrl}
                    alt={`${creator.accountName}头像`}
                    referrerPolicy="no-referrer"
                    onError={() => setAvatarFailed(true)}
                  />
                ) : <UserRound size={23} aria-hidden="true" />}
              </span>
              <div className={styles.profileCopy}>
                <strong>{creator.accountName}</strong>
                <div className={styles.profilePlatformRow}>
                  <PlatformIdentity platform={creator.platform} size="sm" />
                  <span className={styles.metaSeparator} aria-hidden="true">·</span>
                  <span className={styles.profileRoleLabel}>
                    {creatorRoleDisplayLabel(creator.creatorRole)}
                  </span>
                </div>
              </div>
            </div>

            <InspectorSection title="内容定位" icon={<BookOpen size={15} aria-hidden="true" />}>
              <p className={styles.sectionLead}>
                {creator.expertiseDomains.join(" / ") || "内容领域未记录"}
              </p>
              <div className={styles.tagList}>
                {creator.identityTags.length
                  ? creator.identityTags.map((tag) => <span key={tag}>{tag}</span>)
                  : <span>身份标签未记录</span>}
              </div>
            </InspectorSection>

            <InspectorSection title="代表内容 / 资料凭证" icon={<ImageOff size={15} aria-hidden="true" />}>
              <div className={styles.evidenceEmpty}>
                <ImageOff size={20} aria-hidden="true" />
                <div>
                  <strong>暂无截图或代表内容凭证</strong>
                  <span>当前仅提供公开主页；补充证据后再用于运营判断。</span>
                </div>
              </div>
              {creator.profileUrl ? (
                <a className={styles.profileLink} href={creator.profileUrl} target="_blank" rel="noreferrer">
                  <ExternalLink size={14} aria-hidden="true" />
                  查看公开主页
                </a>
              ) : null}
            </InspectorSection>

            <InspectorSection title="为什么值得对标" icon={<Sparkles size={15} aria-hidden="true" />}>
              {relationships.length ? relationships.map((relationship) => (
                <article className={styles.relationshipEvidence} key={relationship.publicRelationshipId}>
                  <div className={styles.relationshipEvidenceHeader}>
                    <strong>{trackById.get(relationship.publicTrackId)?.name ?? "赛道待同步"}</strong>
                    <StatusBadge tone="accent">{relationshipRoleDisplayLabel(relationship.role)}</StatusBadge>
                  </div>
                  <p>{relationship.fitReason || "判断理由未记录"}</p>
                  <div className={styles.relationshipMetrics}>
                    <span>{formatFitScore(relationship.fitScore)}</span>
                    <span>{benchmarkStatusDisplayLabel(relationship.status)}</span>
                    <span>评估于 {formatDate(relationship.lastEvaluatedAt)}</span>
                  </div>
                  <button
                    className={styles.textAction}
                    type="button"
                    data-capability-action="track_creator_membership_query"
                    onClick={() => onPreviewRelationship(relationship)}
                  >
                    查看关系判断
                    <ArrowRight size={13} aria-hidden="true" />
                  </button>
                </article>
              )) : (
                <p className={styles.mutedCopy}>当前筛选下没有可展示的赛道判断。</p>
              )}
            </InspectorSection>

            <InspectorSection title="账号指标" icon={<BarChart3 size={15} aria-hidden="true" />}>
              <div className={styles.metricGrid}>
                <Metric label="粉丝数" value="未记录" />
                <Metric label="互动质量" value="未记录" />
                <Metric label="商务契合度" value="未记录" />
                <Metric label="档案更新" value={formatDate(creator.updatedAt)} />
              </div>
            </InspectorSection>

            <div className={styles.inspectorActions}>
              <button
                className={styles.primaryAction}
                type="button"
                data-capability-action="creator_profile_upsert"
                disabled={!creator.profileUrl}
                title={creator.profileUrl ? "从公开主页生成待确认候选" : "缺少公开主页链接，暂不可采集"}
                onClick={() => onCapture(creator)}
              >
                <Sparkles size={15} aria-hidden="true" />
                一键采集资料
              </button>
            </div>
          </div>
        ) : (
          <SurfaceState kind="empty" title="详情为空" detail="该档案没有可公开的详情记录。" />
        )}
      </section>
    </aside>
  );
}

function OwnedAccountInspector({
  selectedAccountId,
  state,
  monitorState,
  session,
  trackState,
}: {
  selectedAccountId: string | null;
  state: ResourceState<DetailResponse<OwnedAccountSummary>> | null;
  monitorState: ResourceState<AccountMonitorResponse> | null;
  session: NonNullable<ReturnType<typeof useMediaWeb>["session"]>;
  trackState: ResourceState<ListResponse<TrackSummary>>;
}) {
  const account = state?.kind === "ready" ? state.data.item : null;
  const tracks = trackState.kind === "ready" ? trackState.data.items : [];
  const trackById = new Map(tracks.map((track) => [track.publicTrackId, track]));
  const accountTracks = account?.publicTrackIds
    .map((trackId) => trackById.get(trackId))
    .filter((track): track is TrackSummary => Boolean(track)) ?? [];
  const statusTone = operationalStatusTone(account?.operationalStatus ?? null);

  return (
    <aside className={styles.inspectorColumn} data-page-inspector>
      <section className={styles.inspectorPanel} data-page-terminal-surface="inspector" aria-label="账号详情" data-page-account-detail>
        <PanelHeader title="账号详情" detail={selectedAccountId ? "自有账号台账" : "未选择"} icon={<WalletCards size={16} aria-hidden="true" />} />
        {!selectedAccountId ? (
          <SurfaceState kind="empty" title="选择一个自有账号" detail="从左侧列表选择后查看账号身份、责任人、运营定位和数据状态。" />
        ) : state?.kind === "loading" ? (
          <SurfaceState kind="loading" title="正在读取账号" detail="正在读取自有账号台账资料。" />
        ) : state?.kind === "forbidden" ? (
          <SurfaceState kind="forbidden" title="无权查看账号" detail={state.message} />
        ) : state?.kind === "error" ? (
          <SurfaceState kind="error" title="账号详情读取失败" detail={state.message} />
        ) : account ? (
          <div className={styles.inspectorBody}>
            <div className={styles.profileHeader}>
              <AccountAvatar account={account} size="detail" />
              <div className={styles.profileCopy}>
                <strong>{account.accountName}</strong>
                <div className={styles.profilePlatformRow}>
                  <PlatformIdentity platform={account.platform} size="sm" />
                  <StatusBadge tone={statusTone}>{operationalStatusDisplayLabel(account.operationalStatus)}</StatusBadge>
                </div>
              </div>
            </div>

            <InspectorSection title="账号身份" icon={<WalletCards size={15} aria-hidden="true" />}>
              <Field label="账号名" value={account.accountName} />
              <Field label="平台账号" value={account.platformAccountId ?? "未记录"} />
              <Field label="主页" value={account.profileUrl ?? "未提供"} longContent />
            </InspectorSection>

            <InspectorSection title="组织责任" icon={<UserRound size={15} aria-hidden="true" />}>
              <Field label="负责人" value={account.responsiblePerson ?? "未记录"} />
              <Field label="所属团队" value={account.teamName ?? "未记录"} />
            </InspectorSection>

            <InspectorSection title="运营定位" icon={<Target size={15} aria-hidden="true" />}>
              <Field label="账号定位" value={account.accountPositioning ?? "未记录"} longContent />
              <Field label="主赛道" value="未记录" />
              <Field label="次赛道" value="未记录" />
              <div className={styles.tagList}>
                {accountTracks.length
                  ? accountTracks.map((track) => <span key={track.publicTrackId}>{track.name}</span>)
                  : <span>尚未关联赛道</span>}
              </div>
              <p className={styles.mutedCopy}>
                {accountTracks.length ? "以上为已关联赛道，当前资料尚未区分主次。" : "当前资料尚未记录运营赛道。"}
              </p>
            </InspectorSection>

            <InspectorSection title="运营状态" icon={<BadgeCheck size={15} aria-hidden="true" />}>
              <Field label="当前状态" value={operationalStatusDisplayLabel(account.operationalStatus)} />
            </InspectorSection>

            <InspectorSection title="数据状态" icon={<Database size={15} aria-hidden="true" />}>
              <Field label="账号数据" value={account.lastSyncedAt ? "已有运营数据" : "暂无运营数据"} />
              <Field label="数据更新时间" value={account.lastSyncedAt ? formatDate(account.lastSyncedAt) : "暂无"} />
              <Field label="资料来源" value={ownedAccountDataSourceDisplayLabel(account.dataSource)} />
              <Field label="台账更新时间" value={formatDate(account.updatedAt)} />
            </InspectorSection>

            <AccountMonitorSection state={monitorState} accountId={account.publicAccountId} session={session} />
          </div>
        ) : (
          <SurfaceState kind="empty" title="详情为空" detail="该账号没有可展示的详情记录。" />
        )}
      </section>
    </aside>
  );
}

const H00_MONITOR_URL = "https://tcnwueberajc.feishu.cn/base/OmjkbgBkwa2JEysEN8uc5PMhnTb?table=tblc65xqnUjSw9Ah";
const H00_MONITOR_FIELDS = [
  "账号名称",
  "平台",
  "近期作品链接",
  "启用",
  "最近运行时间",
  "最近状态",
  "最近作品数",
  "最近总互动",
  "最近错误",
  "最近日报摘要",
];

function AccountMonitorSection({
  state,
  accountId,
  session,
}: {
  state: ResourceState<AccountMonitorResponse> | null;
  accountId: string;
  session: NonNullable<ReturnType<typeof useMediaWeb>["session"]>;
}) {
  const [editing, setEditing] = useState(false);
  const [enabled, setEnabled] = useState(true);
  const [urlText, setUrlText] = useState("");
  const [actionState, setActionState] = useState<"idle" | "saving" | "polling" | "error">("idle");
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const urls = extractHttpUrls(urlText);
  const submittedUrls = state?.kind === "ready" ? state.data.recentPostUrls ?? [] : [];

  useEffect(() => {
    if (state?.kind !== "ready") return;
    setEnabled(state.data.enabled ?? true);
    setUrlText((state.data.recentPostUrls ?? []).join("\n"));
  }, [state]);

  const saveAndPoll = async () => {
    setActionState("saving");
    setActionMessage(null);
    try {
      const saved = await callBusinessOperation<AccountMonitorResponse>("updateAccountMonitor", {
        path: { publicAccountId: accountId },
        body: { recentPostUrls: urls, enabled },
        csrfToken: session.csrfToken,
        idempotencyKey: newIdempotencyKey("account-monitor-save"),
      });
      setActionState("polling");
      const polled = await callBusinessOperation<AccountMonitorResponse>("pollAccountMonitor", {
        path: { publicAccountId: accountId },
        body: {},
        csrfToken: session.csrfToken,
        idempotencyKey: newIdempotencyKey("account-monitor-poll"),
      });
      setActionMessage(polled.detail || saved.detail || (polled.status === "available" ? "轮询完成，但未返回作品结果。" : "账号监控暂不可用。"));
      setActionState("idle");
      setEditing(false);
    } catch (error: unknown) {
      setActionState("error");
      setActionMessage(toMonitorActionError(error));
    }
  };

  return (
    <InspectorSection title="账号监控" icon={<RefreshCw size={15} aria-hidden="true" />}>
      {state?.kind === "loading" || state === null ? (
        <SurfaceState kind="loading" title="正在读取监控状态" detail="正在确认 H00 账号监控适配器是否可用。" />
      ) : state.kind === "forbidden" ? (
        <SurfaceState kind="forbidden" title="无权查看监控状态" detail={state.message} />
      ) : state.kind === "error" ? (
        <SurfaceState kind="error" title="监控状态读取失败" detail={state.message} />
      ) : state.data.status === "unavailable" ? (
        <SurfaceState
          kind="error"
          title="账号监控暂不可用"
          detail={state.data.detail || "当前运行环境未安装或未配置 H00 账号监控适配器；页面不会将其显示为已成功监控。"}
        />
      ) : (
        <div className={styles.monitorContent} data-monitor-state="available">
          <StatusBadge tone="success">监控适配器可用</StatusBadge>
          <Field label="最近检查" value={formatDate(state.data.checkedAt)} />
          {state.data.detail ? <p className={styles.mutedCopy}>{state.data.detail}</p> : null}
        </div>
      )}
      {editing ? (
        <div className={styles.monitorEditor} data-monitor-editor>
          <label className={styles.monitorEditorLabel}>
            <span>近期作品链接</span>
            <textarea value={urlText} onChange={(event) => setUrlText(event.target.value)} rows={4} placeholder="粘贴作品链接，可混合文本，系统仅提取 HTTP(S) 链接" />
          </label>
          <label className={styles.monitorToggle}><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />启用账号监控</label>
          <p className={styles.mutedCopy}>已提取 {urls.length} 条通用链接{submittedUrls.length ? `；上次保存 ${submittedUrls.length} 条` : ""}。</p>
          <div className={styles.monitorEditorActions}>
            <button className={styles.primaryAction} type="button" disabled={actionState === "saving" || actionState === "polling"} onClick={() => void saveAndPoll()}>{actionState === "saving" ? "正在保存" : actionState === "polling" ? "正在轮询" : "保存并立即轮询"}</button>
            <button className={styles.secondaryAction} type="button" disabled={actionState === "saving" || actionState === "polling"} onClick={() => setEditing(false)}>取消</button>
          </div>
        </div>
      ) : (
        <button className={styles.secondaryAction} type="button" onClick={() => setEditing(true)}>编辑监控</button>
      )}
      {actionMessage ? <p className={styles.monitorActionMessage} role="status">{actionMessage}</p> : null}
      <div className={styles.monitorReference} data-monitor-reference>
        <div className={styles.monitorReferenceHeader}>
          <strong>H00 账号监控表</strong>
          <a href={H00_MONITOR_URL} target="_blank" rel="noreferrer">打开外链</a>
        </div>
        <p className={styles.mutedCopy}>外链用于维护账号和近期作品链接；以下字段由轮询任务读写。</p>
        <div className={styles.monitorFields} aria-label="H00 账号监控字段">
          {H00_MONITOR_FIELDS.map((field) => <span key={field}>{field}</span>)}
        </div>
      </div>
    </InspectorSection>
  );
}

function extractHttpUrls(value: string): string[] {
  const matches = value.match(/https?:\/\/[^\s<>"'`]+/gi) ?? [];
  return Array.from(new Set(matches.map((url) => url.replace(/[),.;!?]+$/, ""))));
}

function toMonitorActionError(error: unknown): string {
  if (error instanceof BusinessOperationError && error.status === 400) {
    return `链接未通过后端判定：${error.message}`;
  }
  if (error instanceof BusinessOperationError && error.status === 503 && error.code === "monitor_unavailable") {
    return "账号监控适配器暂不可用，保存结果未被显示为成功。";
  }
  return "账号监控保存或轮询失败，请检查链接后重试。";
}

function TrackInspector({
  selectedTrackId,
  trackState,
  accountState,
  relationshipState,
  creatorState,
  onResearch,
  onShowOwned,
  onShowBenchmarks,
}: {
  selectedTrackId: string | null;
  trackState: ResourceState<ListResponse<TrackSummary>>;
  accountState: ResourceState<ListResponse<OwnedAccountSummary>>;
  relationshipState: ResourceState<ListResponse<TrackRelationship>>;
  creatorState: ResourceState<ListResponse<CreatorSummary>>;
  onResearch: (track: TrackSummary) => void;
  onShowOwned: (trackId: string) => void;
  onShowBenchmarks: (trackId: string) => void;
}) {
  const tracks = trackState.kind === "ready" ? trackState.data.items : [];
  const accounts = accountState.kind === "ready" ? accountState.data.items : [];
  const relationships = relationshipState.kind === "ready" ? relationshipState.data.items : [];
  const creators = creatorState.kind === "ready" ? creatorState.data.items : [];
  const ownedAccountIds = new Set(accounts.map((account) => account.publicAccountId));
  const track = tracks.find((item) => item.publicTrackId === selectedTrackId) ?? null;
  const creatorById = new Map(creators.map((creator) => [creator.publicCreatorId, creator]));
  const trackAccounts = track
    ? accounts.filter((account) => account.publicTrackIds.includes(track.publicTrackId))
    : [];
  const trackRelationships = track
    ? relationships.filter(
      (relationship) =>
        relationship.publicTrackId === track.publicTrackId &&
        normalizedStatus(relationship.status) !== "rejected" &&
        !ownedAccountIds.has(relationship.publicCreatorId),
    )
    : [];
  const roleCounts = benchmarkRoles.map((role) => ({
    role,
    count: trackRelationships.filter(
      (relationship) => relationshipRoleDisplayLabel(relationship.role) === role,
    ).length,
  }));
  const platforms = Array.from(new Set([
    ...(track?.platforms ?? []),
    ...trackAccounts.map((account) => account.platform),
    ...trackRelationships.map((relationship) => creatorById.get(relationship.publicCreatorId)?.platform ?? ""),
  ].filter(Boolean)));

  return (
    <aside className={styles.inspectorColumn} data-page-inspector>
      <section className={styles.inspectorPanel} data-page-terminal-surface="inspector" aria-label="赛道详情">
        <PanelHeader title="赛道详情" detail={selectedTrackId ? "定位与账号布局" : "未选择"} icon={<Target size={17} aria-hidden="true" />} />
        {!selectedTrackId ? (
          <SurfaceState kind="empty" title="选择一个赛道" detail="从左侧列表选择后查看赛道定位、账号布局和平台覆盖。" />
        ) : !track ? (
          <SurfaceState kind="loading" title="正在读取赛道" detail="正在读取当前赛道的运营概览。" />
        ) : (
          <div className={styles.inspectorBody}>
            <div className={styles.trackInspectorHeader}>
              <div>
                <strong>{track.name}</strong>
                <StatusBadge tone={normalizedStatus(track.status) === "active" ? "success" : "neutral"}>
                  {normalizedStatus(track.status) === "active" ? "重点运营" : trackStatusDisplayLabel(track.status)}
                </StatusBadge>
              </div>
              <span>更新于 {formatDate(track.updatedAt)}</span>
            </div>

            <InspectorSection title="赛道定位" icon={<BookOpen size={15} aria-hidden="true" />}>
              <p className={styles.sectionLead}>{track.description || "赛道定位未记录"}</p>
              <Field label="目标受众" value="未记录" />
              <Field label="内容支柱" value="未记录" />
              <Field label="关键词与别名" value={track.aliases.join("、") || "未记录"} longContent />
              <div className={styles.platformList} aria-label="重点平台">
                {track.platforms.length
                  ? track.platforms.map((platform, index) => (
                    <PlatformIdentity key={`${platform}-${index}`} platform={platform} size="sm" />
                  ))
                  : <span className={styles.mutedCopy}>重点平台未记录</span>}
              </div>
            </InspectorSection>

            <InspectorSection title="账号布局" icon={<WalletCards size={15} aria-hidden="true" />}>
              <div className={styles.layoutMetrics}>
                <Metric label="自有账号" value={String(trackAccounts.length)} emphasized />
                <Metric
                  label="对标账号"
                  value={String(new Set(trackRelationships.map((relationship) => relationship.publicCreatorId)).size)}
                  emphasized
                />
              </div>
              <div className={styles.roleBreakdown}>
                {roleCounts.map(({ role, count }) => (
                  <div key={role}><span>{role}</span><strong>{count}</strong></div>
                ))}
              </div>
              <div className={styles.linkRows}>
                <button type="button" onClick={() => onShowOwned(track.publicTrackId)}>
                  查看自有账号 <ArrowRight size={14} aria-hidden="true" />
                </button>
                <button type="button" onClick={() => onShowBenchmarks(track.publicTrackId)}>
                  查看对标账号 <ArrowRight size={14} aria-hidden="true" />
                </button>
              </div>
            </InspectorSection>

            <InspectorSection title="平台覆盖" icon={<BarChart3 size={15} aria-hidden="true" />}>
              {platforms.length ? (
                <div className={styles.matrixScroll}>
                  <table className={styles.coverageTable}>
                    <thead>
                      <tr>
                        <th scope="col">账号角色</th>
                        {platforms.map((platform) => (
                          <th scope="col" key={platform}><PlatformIdentity platform={platform} size="sm" /></th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <th scope="row">自有账号</th>
                        {platforms.map((platform) => (
                          <td key={platform}>{trackAccounts.filter((account) => account.platform === platform).length}</td>
                        ))}
                      </tr>
                      {benchmarkRoles.map((role) => (
                        <tr key={role}>
                          <th scope="row">{role}</th>
                          {platforms.map((platform) => (
                            <td key={platform}>{trackRelationships.filter((relationship) =>
                              relationshipRoleDisplayLabel(relationship.role) === role &&
                              creatorById.get(relationship.publicCreatorId)?.platform === platform,
                            ).length}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <p className={styles.mutedCopy}>平台覆盖数据尚未记录。</p>}
            </InspectorSection>

            <div className={styles.inspectorActions}>
              <button
                className={styles.primaryAction}
                type="button"
                data-capability-action="external_research_brief"
                onClick={() => onResearch(track)}
              >
                <FlaskConical size={15} aria-hidden="true" />
                调研此赛道
              </button>
            </div>
          </div>
        )}
      </section>
    </aside>
  );
}

function DataPanel({
  title,
  detail,
  icon,
  children,
}: {
  title: string;
  detail: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={styles.panel}>
      <PanelHeader title={title} detail={detail} icon={icon} />
      <div className={styles.panelBody}>{children}</div>
    </section>
  );
}

function PanelHeader({
  title,
  detail,
  icon,
}: {
  title: string;
  detail: string;
  icon: ReactNode;
}) {
  return (
    <header className={styles.panelHeader}>
      <div className={styles.panelTitle}>
        <span className={styles.panelIcon}>{icon}</span>
        <h2>{title}</h2>
      </div>
      <span className={styles.panelMeta}>{detail}</span>
    </header>
  );
}

function SegmentedFilter<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: Array<{ id: T; label: string; count: number }>;
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className={styles.filterTabs} role="tablist" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.id}
          className={[
            styles.filterTab,
            value === option.id ? styles.filterTabActive : "",
          ].join(" ")}
          type="button"
          role="tab"
          aria-selected={value === option.id}
          onClick={() => onChange(option.id)}
        >
          <span>{option.label}</span>
          <span className={styles.filterCount}>{option.count}</span>
        </button>
      ))}
    </div>
  );
}

function ContextFilter({ label, onClear }: { label: string; onClear: () => void }) {
  return (
    <div className={styles.contextFilter} role="status">
      <Target size={14} aria-hidden="true" />
      <span>{label}</span>
      <button type="button" onClick={onClear} aria-label={`清除筛选：${label}`} title="清除筛选">
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}

function StatusBadge({
  tone,
  children,
}: {
  tone: "success" | "warning" | "neutral" | "accent";
  children: ReactNode;
}) {
  const toneClass = {
    success: styles.statusBadgeSuccess,
    warning: styles.statusBadgeWarning,
    neutral: styles.statusBadgeNeutral,
    accent: styles.statusBadgeAccent,
  }[tone];
  return (
    <span className={[styles.statusBadge, toneClass].join(" ")}>
      {children}
    </span>
  );
}

function InspectorSection({
  title,
  icon,
  children,
}: {
  title: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={styles.inspectorSection}>
      <header>{icon}<h3>{title}</h3></header>
      <div className={styles.inspectorSectionBody}>{children}</div>
    </section>
  );
}

function Metric({
  label,
  value,
  emphasized = false,
}: {
  label: string;
  value: string;
  emphasized?: boolean;
}) {
  return (
    <div className={[styles.metric, emphasized ? styles.metricEmphasized : ""].join(" ")}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SearchBox({
  label,
  value,
  onChange,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <label className={styles.searchBox}>
      <Search size={15} aria-hidden="true" />
      <span className={styles.srOnly}>{label}</span>
      <input
        type="search"
        value={value}
        placeholder={label}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        maxLength={160}
      />
    </label>
  );
}

function ListState<T>({
  state,
  emptyTitle,
  emptyDetail,
}: {
  state: ResourceState<ListResponse<T>>;
  emptyTitle: string;
  emptyDetail: string;
}) {
  if (state.kind === "loading") {
    return <SurfaceState kind="loading" title="正在读取" detail="正在读取当前账户可见的列表内容。" />;
  }
  if (state.kind === "forbidden") {
    return <SurfaceState kind="forbidden" title="无权查看" detail={state.message} />;
  }
  if (state.kind === "error") {
    return <SurfaceState kind="error" title="读取失败" detail={state.message} />;
  }
  if (state.data.items.length === 0) {
    return <SurfaceState kind="empty" title={emptyTitle} detail={emptyDetail} />;
  }
  return null;
}

function normalizedStatus(value: string): string {
  return value.trim().toLowerCase();
}

function hasOperationalStatus(
  account: OwnedAccountSummary,
  status: Exclude<OwnedAccountFilter, "all">,
): boolean {
  return normalizedStatus(account.operationalStatus ?? "") === status;
}

function operationalStatusTone(value: string | null): "success" | "warning" | "neutral" {
  const status = normalizedStatus(value ?? "");
  if (status === "active") return "success";
  if (status === "paused") return "warning";
  return "neutral";
}

function operationalStatusTextClass(value: string | null): string {
  const status = normalizedStatus(value ?? "");
  if (status === "active") return styles.operationalStatusActive;
  if (status === "paused") return styles.operationalStatusPaused;
  return styles.operationalStatusInactive;
}

function isRelationshipQueueStatus(value: string): value is RelationshipQueueStatus {
  return ["candidate", "active", "rejected"].includes(normalizedStatus(value));
}

function benchmarkManagementStatus(relationships: TrackRelationship[]): RelationshipQueueStatus {
  const statuses = relationships.map((relationship) => normalizedStatus(relationship.status));
  if (statuses.includes("active")) return "active";
  if (statuses.includes("candidate")) return "candidate";
  if (statuses.length > 0 && statuses.every((status) => status === "rejected")) return "rejected";
  return "candidate";
}

function benchmarkStatusDisplayLabel(value: string): string {
  const status = normalizedStatus(value);
  if (status === "active") return "已关注";
  if (status === "rejected") return "已忽略";
  if (status === "candidate") return "待确认";
  return "关注状态待确认";
}

function SurfaceState({
  kind,
  title,
  detail,
  action,
}: {
  kind: "loading" | "forbidden" | "error" | "empty";
  title: string;
  detail: string;
  action?: ReactNode;
}) {
  const Icon = kind === "loading" ? LoaderCircle : kind === "empty" ? Database : AlertCircle;
  return (
    <div
      className={styles.surfaceState}
      role="status"
      aria-busy={kind === "loading"}
      data-state={kind}
    >
      <span className={styles.stateIcon}>
        <Icon className={kind === "loading" ? styles.spin : ""} size={21} aria-hidden="true" />
      </span>
      <strong>{title}</strong>
      <p>{detail}</p>
      {action}
    </div>
  );
}

function Field({
  label,
  value,
  longContent = false,
}: {
  label: string;
  value: string;
  longContent?: boolean;
}) {
  return (
    <div className={styles.field}>
      <span className={styles.fieldLabel}>{label}</span>
      <span className={[styles.fieldValue, longContent ? styles.longContent : ""].join(" ")}>
        {value}
      </span>
    </div>
  );
}

function ProjectionDegradationNotice({
  resources,
  onRetry,
}: {
  resources: Array<{ label: string; state: ResourceState<unknown> }>;
  onRetry: () => void;
}) {
  const unavailable = resources.filter(
    (resource) => resource.state.kind === "forbidden" || resource.state.kind === "error",
  );
  return (
    <div className={styles.partialBanner} role="alert" data-page-partial>
      <AlertCircle size={16} aria-hidden="true" />
      <div>
        <strong>以下资源读取失败</strong>
        <ul>
          {unavailable.map((resource) => (
            <li key={resource.label}>
              {resource.state.kind === "forbidden" || resource.state.kind === "error"
                ? resource.state.message
                : ""}
            </li>
          ))}
        </ul>
        <span>已成功返回的资源仍保留在当前页面。</span>
      </div>
      <button type="button" onClick={onRetry}>刷新并重新读取</button>
    </div>
  );
}

function loadList<T>(
  operation: "listTracks" | "listCreators" | "listTrackRelationships" | "listOwnedAccounts",
  subject: string,
  query: Record<string, unknown>,
  signal: AbortSignal,
  setter: Dispatch<ResourceState<ListResponse<T>>>,
) {
  callBusinessOperation<ListResponse<T>>(operation, { query, signal })
    .then((data) => setter({ kind: "ready", data }))
    .catch((error: unknown) => {
      if (!signal.aborted) setter(toResourceError(error, subject));
    });
}

function toResourceError<T>(error: unknown, subject: string): ResourceState<T> {
  if (error instanceof BusinessOperationError && (error.status === 401 || error.status === 403)) {
    return { kind: "forbidden", message: `${subject}暂无查看权限。请确认当前账户权限后刷新。` };
  }
  return { kind: "error", message: `${subject}暂时无法读取。请点击“刷新”重新读取。` };
}

function toMonitorResourceError(error: unknown): ResourceState<AccountMonitorResponse> {
  if (error instanceof BusinessOperationError && (error.status === 401 || error.status === 403)) {
    return { kind: "forbidden", message: "账号监控状态暂无查看权限。请确认当前账户权限后刷新。" };
  }
  if (error instanceof BusinessOperationError && error.status === 503 && error.code === "monitor_unavailable") {
    return {
      kind: "error",
      message: "当前运行环境未安装或未配置 H00 账号监控适配器；页面不会将其显示为已成功监控。",
    };
  }
  return { kind: "error", message: "账号监控状态暂时无法读取。请点击“刷新”重新读取。" };
}

function formatDate(value: string | null): string {
  if (!value) return "未提供";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function formatRelativeTime(value: string | null): string {
  if (!value) return "未记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const elapsedMs = Date.now() - date.getTime();
  if (elapsedMs < 0) return formatDate(value);
  const minutes = Math.floor(elapsedMs / 60_000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} 天前`;
  return formatDate(value);
}

export default TracksPage;
