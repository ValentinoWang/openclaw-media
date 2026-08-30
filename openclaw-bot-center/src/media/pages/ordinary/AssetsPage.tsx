import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertCircle,
  Database,
  FileText,
  ImageOff,
  Lightbulb,
  LoaderCircle,
  LogIn,
  Plus,
  RotateCcw,
  Search,
  SearchX,
  Trash2,
  X,
} from "lucide-react";
import {
  useMediaWeb,
  type PreparedDeletionIntent,
} from "../../MediaWebWorkspace";
import {
  BusinessOperationError,
  callBusinessOperation,
} from "../../generatedBusinessPagesContract";
import {
  CursorPagination,
  formatDate,
  PageHeading,
  useCursorTrail,
} from "../../ui/ordinaryPagePrimitives";
import {
  mediaTypeDisplayLabel,
  materialStatusDisplayLabel,
  qualityDisplayLabel,
} from "../../ui/ordinaryDataLabels";
import { PlatformIdentity } from "../../ui/PlatformIdentity";
import { platformDisplayLabel } from "../../ui/platformRegistry";
import type { StructuredPrefill } from "../../task-launch/taskDraft";
import styles from "./AssetsPage.module.css";

type Scalar = string | number | boolean | null;
type ProjectedValue = Scalar | ProjectedValue[] | { [key: string]: ProjectedValue };
type StringValueMap = Record<string, ProjectedValue>;

type AssetSummary = {
  publicAssetId: string;
  title: string;
  mediaType: string;
  thumbnail: StringValueMap;
  materialStatus?: string | null;
  platform: string;
  sourceLabel: string;
  platformHashtags: string[];
  trackNames: string[];
  qualityStatus: string;
  createdAt: string;
  usageCount: number;
};

type EvidenceRef = {
  kind: string;
  label: string;
  publicUrl: string | null;
  capturedAt: string | null;
  qualityStatus: string;
};

type AssetDetail = {
  summary: AssetSummary;
  evidenceRefs: EvidenceRef[];
  previewDescriptor: StringValueMap;
  deconstructions: StringValueMap[];
  creativePatterns: StringValueMap[];
  usageRefs: string[];
  revision: number;
};

type AssetListResponse = {
  schemaVersion: string;
  revision: number;
  items: AssetSummary[];
  nextCursor: string | null;
};

type AssetResponse = {
  schemaVersion: string;
  revision: number;
  item: AssetDetail;
};

type AssetTabId = "assets" | "deconstruction" | "creation" | "usage";
type RelationTabId = Exclude<AssetTabId, "assets">;
type DateFilter = "all" | "7d" | "30d";
type LoadState<T> =
  | { status: "waiting" }
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "permission"; message: string }
  | { status: "notFound"; message: string }
  | { status: "error"; message: string };
type AssetListState = Exclude<
  LoadState<AssetListResponse>,
  { status: "notFound"; message: string }
>;
type DeletionDialogState = {
  phase: "preparing" | "ready" | "deleting" | "cancelling" | "error";
  targetIds: string[];
  targetLabels: string[];
  intent: PreparedDeletionIntent | null;
  message: string;
};

const tabs: Array<{ id: AssetTabId; label: string }> = [
  { id: "assets", label: "灵感与素材" },
  { id: "deconstruction", label: "内容拆解" },
  { id: "creation", label: "创作模式" },
  { id: "usage", label: "使用记录" },
];

const relationTabMeta: Record<
  RelationTabId,
  { label: string; emptyTitle: string; emptyDetail: string }
> = {
  deconstruction: {
    label: "内容拆解",
    emptyTitle: "暂无内容拆解记录",
    emptyDetail: "素材详情里还没有可展示的内容拆解关联记录。",
  },
  creation: {
    label: "创作模式",
    emptyTitle: "暂无创作模式记录",
    emptyDetail: "素材详情里还没有可展示的创作模式关联记录。",
  },
  usage: {
    label: "使用记录",
    emptyTitle: "暂无使用记录",
    emptyDetail: "素材详情里还没有可展示的使用记录关联。",

  },
};
function AssetsPage() {
  const {
    openWorkspace,
    runtimeState,
    prepareDeletionIntent,
    executeDeletionIntent,
    cancelDeletionIntent,
  } = useMediaWeb();
  const cursorTrail = useCursorTrail();
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [focusedId, setFocusedId] = useState<string>();
  const [activeTab, setActiveTab] = useState<AssetTabId>("assets");
  const [search, setSearch] = useState("");
  const [platformFilter, setPlatformFilter] = useState("all");
  const [trackFilter, setTrackFilter] = useState("all");
  const [qualityFilter, setQualityFilter] = useState("all");
  const [dateFilter, setDateFilter] = useState<DateFilter>("all");
  const [retryToken, setRetryToken] = useState(0);
  const [detailRetryToken, setDetailRetryToken] = useState(0);
  const [deletionDialog, setDeletionDialog] = useState<DeletionDialogState | null>(null);
  const deletionAttempt = useRef(0);
  const { cursor } = cursorTrail;
  const authenticated = runtimeState === "authenticated";
  const listState = useAssetProjection(
    cursor,
    search,
    authenticated,
    retryToken,
  );
  const pageItems = useMemo(
    () => (listState.status === "ready" ? listState.data.items : []),
    [listState],
  );
  const visibleItems = useMemo(
    () =>
      pageItems.filter((asset) => {
        const matchesPlatform =
          platformFilter === "all" || asset.platform === platformFilter;
        const matchesTrack =
          trackFilter === "all" || asset.trackNames.includes(trackFilter);
        const matchesQuality =
          qualityFilter === "all" || asset.qualityStatus === qualityFilter;
        return (
          matchesPlatform &&
          matchesTrack &&
          matchesQuality &&
          isWithinDateFilter(asset.createdAt, dateFilter)
        );
      }),
    [dateFilter, pageItems, platformFilter, qualityFilter, trackFilter],
  );
  const focusedAsset = pageItems.find(
    (asset) => asset.publicAssetId === focusedId,
  );
  const selectedAssets = useMemo(
    () => pageItems.filter((asset) => selectedIds.includes(asset.publicAssetId)),
    [pageItems, selectedIds],
  );
  const detailState = useAssetDetail(
    focusedId,
    authenticated,
    detailRetryToken,
  );

  useEffect(() => {
    setSelectedIds([]);
    setFocusedId(undefined);
  }, [cursor, retryToken, search]);

  useEffect(() => {
    if (
      focusedId &&
      !pageItems.some((asset) => asset.publicAssetId === focusedId)
    ) {
      setFocusedId(undefined);
    }
  }, [focusedId, pageItems]);

  function toggleAsset(publicAssetId: string) {
    setSelectedIds((current) =>
      current.includes(publicAssetId)
        ? current.filter((item) => item !== publicAssetId)
        : [...current, publicAssetId],
    );
  }

  function openCapability(prefill: StructuredPrefill) {
    if (!authenticated) return;
    openWorkspace(prefill);
  }

  async function requestDeletion(ids: string[]) {
    const uniqueIds = [...new Set(ids)].filter(Boolean);
    if (!uniqueIds.length || !authenticated) return;
    const targetLabels = uniqueIds.map((id) => {
      const asset = pageItems.find((item) => item.publicAssetId === id);
      return asset ? `${asset.title}（${id}）` : id;
    });
    const attempt = ++deletionAttempt.current;
    setDeletionDialog({
      phase: "preparing",
      targetIds: uniqueIds,
      targetLabels,
      intent: null,
      message: "",
    });
    try {
      const intent = await prepareDeletionIntent(uniqueIds);
      if (attempt !== deletionAttempt.current) {
        await cancelDeletionIntent(intent.taskId);
        return;
      }
      setDeletionDialog({
        phase: "ready",
        targetIds: uniqueIds,
        targetLabels,
        intent,
        message: "",
      });
    } catch {
      if (attempt !== deletionAttempt.current) return;
      setDeletionDialog({
        phase: "error",
        targetIds: uniqueIds,
        targetLabels,
        intent: null,
        message: "暂时无法检查删除影响，素材没有被删除。",
      });
    }
  }

  async function closeDeletionDialog() {
    const current = deletionDialog;
    if (!current || current.phase === "deleting" || current.phase === "cancelling") return;
    ++deletionAttempt.current;
    if (!current.intent) {
      setDeletionDialog(null);
      return;
    }
    setDeletionDialog({ ...current, phase: "cancelling", message: "" });
    try {
      await cancelDeletionIntent(current.intent.taskId);
      setDeletionDialog(null);
    } catch {
      setDeletionDialog({
        ...current,
        phase: "error",
        message: "暂时无法取消本次删除，请稍后再试。",
      });
    }
  }

  async function retryDeletion() {
    const current = deletionDialog;
    if (!current) return;
    if (current.intent) {
      setDeletionDialog({ ...current, phase: "cancelling", message: "" });
      try {
        await cancelDeletionIntent(current.intent.taskId);
      } catch {
        setDeletionDialog({
          ...current,
          phase: "error",
          message: "旧的删除请求暂时无法关闭，请稍后再试。",
        });
        return;
      }
    }
    await requestDeletion(current.targetIds);
  }

  async function confirmDeletion() {
    const current = deletionDialog;
    if (!current?.intent || current.phase !== "ready") return;
    const expiresAt = Date.parse(current.intent.expiresAt);
    if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
      await retryDeletion();
      return;
    }
    setDeletionDialog({ ...current, phase: "deleting", message: "" });
    try {
      await executeDeletionIntent(current.intent.taskId);
      ++deletionAttempt.current;
      setDeletionDialog(null);
      setSelectedIds([]);
      setFocusedId(undefined);
      setRetryToken((value) => value + 1);
    } catch {
      setDeletionDialog({
        ...current,
        phase: "error",
        message: "删除没有完成，素材仍然保留。请重新检查后再试。",
      });
    }
  }

  function changeSearch(value: string) {
    setSearch(value);
    cursorTrail.reset();
    setFocusedId(undefined);
  }

  function resetFilters() {
    changeSearch("");
    setPlatformFilter("all");
    setTrackFilter("all");
    setQualityFilter("all");
    setDateFilter("all");
  }

  return (
    <main className={["fidelity-page", styles.page].join(" ")}>
      <div data-page-prelude>
        <div className={styles.headingRow}>
          <PageHeading
            title="素材与灵感"
            description="从灵感、来源和拆解证据进入选题与创作。"
          />
          <div className="page-heading-actions"><button
            className={styles.primaryAction}
            type="button"
            disabled={!authenticated}
            onClick={() => openCapability({
              capabilityId: "source_asset_intake",
              variantId: "default",
            })}
            title={authenticated ? undefined : "登录后登记素材"}
          >
            <Plus size={16} aria-hidden="true" />
            登记素材
          </button></div>
        </div>

        <nav
          className={styles.tabList}
          aria-label="素材工作区视图"
          tabIndex={0}
        >
          {tabs.map((tab) => (
            <button
              key={tab.id}
              id={tab.id + "-tab"}
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
      </div>
      <SelectionSummary
        state={listState}
        pageItems={pageItems}
        selectedAssets={selectedAssets}
        selectedIds={selectedIds}
        onClearSelection={() => setSelectedIds([])}
        onRequestDeletion={(ids) => void requestDeletion(ids)}
      />
      <div className={styles.assetsLayout} data-page-layout="persistent-rail">
        <div className={styles.primaryColumn} data-page-primary>
          <div className={styles.workspace}>
            {activeTab === "assets" ? (
              <AssetWorkspace
                state={listState}
                items={visibleItems}
                pageItems={pageItems}
                canPrevious={cursorTrail.canPrevious}
                page={cursorTrail.page}
                focusedId={focusedId}
                selectedIds={selectedIds}
                search={search}
                platformFilter={platformFilter}
                trackFilter={trackFilter}
                qualityFilter={qualityFilter}
                dateFilter={dateFilter}
                onSearch={changeSearch}
                onPlatformFilter={setPlatformFilter}
                onTrackFilter={setTrackFilter}
                onQualityFilter={setQualityFilter}
                onDateFilter={setDateFilter}
                onReset={resetFilters}
                onToggle={toggleAsset}
                onFocus={(asset) => setFocusedId(asset.publicAssetId)}
                onRetry={() => setRetryToken((value) => value + 1)}
                onPrevious={cursorTrail.previous}
                onNext={cursorTrail.next}
              />
            ) : (
              <AssetTabPanel
                tab={activeTab}
                asset={focusedAsset}
                state={detailState}
                onRetry={() => setDetailRetryToken((value) => value + 1)}
              />
            )}
          </div>
        </div>
        <AssetInspector
          asset={focusedAsset}
          state={detailState}
          onClose={() => setFocusedId(undefined)}
          onRetry={() => setDetailRetryToken((value) => value + 1)}
          onOpenCapability={openCapability}
          onRequestDeletion={(ids) => void requestDeletion(ids)}
        />
      </div>
      {deletionDialog ? (
        <DeletionDialog
          state={deletionDialog}
          onCancel={() => void closeDeletionDialog()}
          onRetry={() => void retryDeletion()}
          onConfirm={() => void confirmDeletion()}
        />
      ) : null}
    </main>
  );
}

function AssetWorkspace({
  state,
  items,
  pageItems,
  canPrevious,
  page,
  focusedId,
  selectedIds,
  search,
  platformFilter,
  trackFilter,
  qualityFilter,
  dateFilter,
  onSearch,
  onPlatformFilter,
  onTrackFilter,
  onQualityFilter,
  onDateFilter,
  onReset,
  onToggle,
  onFocus,
  onRetry,
  onPrevious,
  onNext,
}: {
  state: AssetListState;
  items: AssetSummary[];
  pageItems: AssetSummary[];
  canPrevious: boolean;
  page: number;
  focusedId?: string;
  selectedIds: string[];
  search: string;
  platformFilter: string;
  trackFilter: string;
  qualityFilter: string;
  dateFilter: DateFilter;
  onSearch: (value: string) => void;
  onPlatformFilter: (value: string) => void;
  onTrackFilter: (value: string) => void;
  onQualityFilter: (value: string) => void;
  onDateFilter: (value: DateFilter) => void;
  onReset: () => void;
  onToggle: (id: string) => void;
  onFocus: (asset: AssetSummary) => void;
  onRetry: () => void;
  onPrevious: () => void;
  onNext: (cursor: string) => void;
}) {
  const platformOptions = uniqueValues(pageItems.map((asset) => asset.platform));
  const trackOptions = uniqueValues(
    pageItems.flatMap((asset) => asset.trackNames),
  );
  const qualityOptions = uniqueValues(
    pageItems.map((asset) => asset.qualityStatus),
  );

  return (
    <section
      className={styles.mainPanel}
      id="assets-tabpanel"
      role="tabpanel"
      aria-labelledby="assets-tab"
        aria-label="灵感与素材主列表"
        data-page-terminal-surface="primary"
      data-assets-tab-panel="assets"
      >
        <FilterBar
          search={search}
          platformFilter={platformFilter}
          trackFilter={trackFilter}
          qualityFilter={qualityFilter}
          dateFilter={dateFilter}
          platformOptions={platformOptions}
          trackOptions={trackOptions}
          qualityOptions={qualityOptions}
          onSearch={onSearch}
          onPlatformFilter={onPlatformFilter}
          onTrackFilter={onTrackFilter}
          onQualityFilter={onQualityFilter}
          onDateFilter={onDateFilter}
          onReset={onReset}
        />
        <div className={styles.filterNote}>
          <AlertCircle size={14} aria-hidden="true" />
          <span>
            搜索会在素材库中进行；平台、赛道、质量和时间筛选作用于当前已读取页。
          </span>
        </div>

        {state.status === "waiting" ? (
          <ProjectionSurface
            kind="loading"
            title="正在确认访问权限"
            detail="页面数据将在身份确认后读取。"
          />
        ) : state.status === "loading" ? (
          <ProjectionSurface
            kind="loading"
            title="正在读取素材"
            detail="只读取当前账户租户可见的素材摘要。"
          />
        ) : state.status === "permission" ? (
          <ProjectionSurface
            kind="permission"
            title="需要登录才能查看"
            detail="素材页面只展示当前账户有权查看的素材。"
          />
        ) : state.status === "error" ? (
          <ProjectionSurface
            kind="error"
            title="暂时无法读取素材"
            detail={state.message}
            onRetry={onRetry}
          />
        ) : (
          <>
            {pageItems.length === 0 ? (
              <ProjectionSurface
                kind="empty"
                title={search ? "没有匹配的素材" : "当前账户没有可查看的素材"}
                detail={
                  search
                    ? "没有找到匹配的素材；调整搜索词后重新读取。"
                    : "暂时没有素材记录；页面不会用样例封面或相邻业务数据填充。"
                }
              />
            ) : items.length === 0 ? (
              <ProjectionSurface
                kind="filtered"
                title="没有符合当前筛选的素材"
                detail="调整筛选条件后，页面会继续显示当前已读取的素材。"
              />
            ) : (
              <div
                className={styles.assetGrid}
                role="list"
                aria-label="素材网格"
                tabIndex={0}
              >
                {items.map((asset) => (
                  <AssetCard
                    key={asset.publicAssetId}
                    asset={asset}
                    focused={focusedId === asset.publicAssetId}
                    selected={selectedIds.includes(asset.publicAssetId)}
                    onFocus={onFocus}
                    onToggle={onToggle}
                  />
                ))}
              </div>
            )}
            <CursorPagination
              page={page}
              canPrevious={canPrevious}
              canNext={!!state.data.nextCursor}
              onPrevious={onPrevious}
              onNext={() => {
                if (state.data.nextCursor) onNext(state.data.nextCursor);
              }}
            />
          </>
        )}
      </section>
  );
}

function SelectionSummary({
  state,
  pageItems,
  selectedAssets,
  selectedIds,
  onClearSelection,
  onRequestDeletion,
}: {
  state: AssetListState;
  pageItems: AssetSummary[];
  selectedAssets: AssetSummary[];
  selectedIds: string[];
  onClearSelection: () => void;
  onRequestDeletion: (ids: string[]) => void;
}) {
  const revisionLabel =
    state.status === "ready" ? "r" + state.data.revision : "未读取";
  const selectedLabel = selectedAssets.length
    ? selectedAssets
        .map((asset) => asset.publicAssetId + " · " + asset.title)
        .join("、")
    : "未选择素材";

  return (
    <section
      className={styles.selectionBar}
      aria-label="素材选择状态"
      data-page-selection-summary
    >
      <div className={styles.selectionSummary}>
        <span>当前页 {pageItems.length} 项</span>
        <span className={styles.selectionDivider}>·</span>
        <strong>{selectedIds.length}</strong>
        <span>项已选择</span>
        <span className={styles.selectionRevision} data-list-revision={state.status === "ready" ? state.data.revision : undefined}>
          列表修订号 {revisionLabel}
        </span>
        <span
          className={styles.selectionNames}
          title={selectedLabel}
          data-selected-assets
        >
          {selectedLabel}
        </span>
      </div>
      <div className={styles.selectionActions}>
        <button
          className={styles.quietAction}
          type="button"
          disabled={!selectedIds.length}
          onClick={onClearSelection}
        >
          <RotateCcw size={14} aria-hidden="true" />
          清除选择
        </button>
        <button
          className={styles.dangerAction}
          type="button"
          disabled={!selectedIds.length}
          onClick={() => onRequestDeletion(selectedIds)}
        >
          <Trash2 size={14} aria-hidden="true" />
          删除素材
        </button>
      </div>
    </section>
  );
}

function DeletionDialog({
  state,
  onCancel,
  onRetry,
  onConfirm,
}: {
  state: DeletionDialogState;
  onCancel: () => void;
  onRetry: () => void;
  onConfirm: () => void;
}) {
  const busy = ["preparing", "deleting", "cancelling"].includes(state.phase);
  return (
    <div className={styles.dialogLayer}>
      <button
        className={styles.dialogScrim}
        type="button"
        aria-label="关闭删除素材对话框"
        disabled={busy}
        onClick={onCancel}
      />
      <section
        className={styles.deletionDialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="asset-deletion-title"
      >
        <header className={styles.dialogHeader}>
          <span className={styles.dialogDangerIcon}>
            <Trash2 size={19} aria-hidden="true" />
          </span>
          <div>
            <h2 id="asset-deletion-title">删除素材</h2>
            <p>确认后将永久删除当前选择的素材。</p>
          </div>
        </header>
        <div className={styles.dialogBody}>
          {state.phase === "preparing" ? (
            <div className={styles.dialogStatus} aria-live="polite">
              <LoaderCircle className={styles.spin} size={20} aria-hidden="true" />
              <div>
                <strong>正在检查删除影响</strong>
                <span>检查完成后才能确认删除。</span>
              </div>
            </div>
          ) : state.intent ? (
            <>
              <strong className={styles.impactSummary}>
                将删除 {state.intent.targetCount} 个素材，涉及 {state.intent.entityCount} 项数据。
              </strong>
              <ul className={styles.deletionTargets}>
                {state.targetLabels.map((label) => <li key={label}>{label}</li>)}
              </ul>
            </>
          ) : null}
          {state.phase === "deleting" || state.phase === "cancelling" ? (
            <div className={styles.dialogStatus} aria-live="polite">
              <LoaderCircle className={styles.spin} size={20} aria-hidden="true" />
              <strong>{state.phase === "deleting" ? "正在删除素材" : "正在取消删除"}</strong>
            </div>
          ) : null}
          {state.message ? (
            <p className={styles.dialogError} role="alert">{state.message}</p>
          ) : null}
        </div>
        <footer className={styles.dialogActions}>
          {state.phase === "error" ? (
            <button className={styles.dialogSecondary} type="button" onClick={onRetry}>
              <RotateCcw size={15} aria-hidden="true" />
              重新检查
            </button>
          ) : null}
          <button
            className={styles.dialogSecondary}
            type="button"
            disabled={busy}
            autoFocus={state.phase === "ready"}
            onClick={onCancel}
          >
            取消
          </button>
          <button
            className={styles.dialogDanger}
            type="button"
            disabled={state.phase !== "ready"}
            onClick={onConfirm}
          >
            <Trash2 size={15} aria-hidden="true" />
            确认删除
          </button>
        </footer>
      </section>
    </div>
  );
}

function AssetTabPanel({
  tab,
  asset,
  state,
  onRetry,
}: {
  tab: RelationTabId;
  asset?: AssetSummary;
  state: LoadState<AssetResponse>;
  onRetry: () => void;
}) {
  const meta = relationTabMeta[tab];
  const detailRevision =
    state.status === "ready" ? "修订号 r" + state.data.revision : "详情修订号 未读取";
  const caption = asset
    ? asset.publicAssetId + " · " + asset.title + " · " + detailRevision
    : "选择一个素材后查看真实关联记录。";
  let body: ReactNode;

  if (!asset) {
    body = <TabSelectionSurface label={meta.label} />;
  } else if (state.status === "waiting" || state.status === "loading") {
    body = (
      <div className={styles.tabPanelBody}>
        <ProjectionSurface
          kind="loading"
          title="正在读取素材详情"
          detail="当前视图展示所选素材详情中的关联记录。"
        />
      </div>
    );
  } else if (state.status === "permission") {
    body = (
      <div className={styles.tabPanelBody}>
        <ProjectionSurface
          kind="permission"
          title="没有详情读取权限"
          detail={state.message}
        />
      </div>
    );
  } else if (state.status === "notFound") {
    body = (
      <div className={styles.tabPanelBody}>
        <ProjectionSurface
          kind="notFound"
          title="素材不存在或已不可见"
          detail={state.message}
        />
      </div>
    );
  } else if (state.status === "error") {
    body = (
      <div className={styles.tabPanelBody}>
        <ProjectionSurface
          kind="error"
          title="暂时无法读取详情"
          detail={state.message}
          onRetry={onRetry}
        />
      </div>
    );
  } else {
    const detail = state.data.item;
    const content =
      tab === "deconstruction" ? (
        detail.deconstructions.length ? (
          <RelationList
            title="内容拆解记录"
            items={detail.deconstructions}
          />
        ) : (
          <ProjectionSurface
            kind="empty"
            title={meta.emptyTitle}
            detail={meta.emptyDetail}
          />
        )
      ) : tab === "creation" ? (
        detail.creativePatterns.length ? (
          <RelationList
            title="创作模式记录"
            items={detail.creativePatterns}
          />
        ) : (
          <ProjectionSurface
            kind="empty"
            title={meta.emptyTitle}
            detail={meta.emptyDetail}
          />
        )
      ) : detail.usageRefs.length ? (
        <UsageReferenceList items={detail.usageRefs} />
      ) : (
        <ProjectionSurface
          kind="empty"
          title={meta.emptyTitle}
          detail={meta.emptyDetail}
        />
      );
    body = (
      <div
        className={styles.tabPanelBody}
        tabIndex={0}
        aria-label={meta.label + "内容"}
        data-detail-revision={detail.revision}
      >
        {content}
      </div>
    );
  }

  return (
    <section
      className={styles.tabPanel}
      id={tab + "-tabpanel"}
      role="tabpanel"
      aria-labelledby={tab + "-tab"}
      aria-label={meta.label}
      data-page-terminal-surface="primary"
      data-assets-tab-panel={tab}
    >
      <header className={styles.tabPanelHeader}>
        <div>
          <h2>{meta.label}</h2>
          <p>{caption}</p>
        </div>
      </header>
      {body}
    </section>
  );
}

function TabSelectionSurface({ label }: { label: string }) {
  return (
    <div className={styles.tabPanelEmpty} role="status">
      <span className={styles.surfaceIcon}>
        <Database size={22} aria-hidden="true" />
      </span>
      <strong>选择素材后查看{label}</strong>
      <p>当前视图只展示素材详情中的关联记录。</p>
    </div>
  );
}

function UsageReferenceList({ items }: { items: string[] }) {
  return (
    <div className={styles.relationBlock}>
      <strong>使用记录关联</strong>
      <ul className={styles.refList}>
        {items.map((id) => (
          <li key={id}>{id}</li>
        ))}
      </ul>
    </div>
  );
}

function FilterBar({
  search,
  platformFilter,
  trackFilter,
  qualityFilter,
  dateFilter,
  platformOptions,
  trackOptions,
  qualityOptions,
  onSearch,
  onPlatformFilter,
  onTrackFilter,
  onQualityFilter,
  onDateFilter,
  onReset,
}: {
  search: string;
  platformFilter: string;
  trackFilter: string;
  qualityFilter: string;
  dateFilter: DateFilter;
  platformOptions: string[];
  trackOptions: string[];
  qualityOptions: string[];
  onSearch: (value: string) => void;
  onPlatformFilter: (value: string) => void;
  onTrackFilter: (value: string) => void;
  onQualityFilter: (value: string) => void;
  onDateFilter: (value: DateFilter) => void;
  onReset: () => void;
}) {
  return (
    <div className={styles.filterBar}>
      <label className={[styles.filterField, styles.searchField].join(" ")}>
        <span className={styles.srOnly}>搜索素材</span>
        <Search size={16} aria-hidden="true" />
        <input
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          placeholder="搜索编号、标题或来源"
          aria-label="搜索编号、标题或来源"
        />
      </label>
      <FilterSelect
        label="平台"
        value={platformFilter}
        options={platformOptions}
        onChange={onPlatformFilter}
        formatOption={platformDisplayLabel}
      />
      <FilterSelect
        label="赛道"
        value={trackFilter}
        options={trackOptions}
        onChange={onTrackFilter}
      />
      <FilterSelect
        label="质量"
        value={qualityFilter}
        options={qualityOptions}
        onChange={onQualityFilter}
        formatOption={qualityLabel}
      />
      <label className={styles.filterField}>
        <span>时间</span>
        <select
          value={dateFilter}
          onChange={(event) => onDateFilter(event.target.value as DateFilter)}
          aria-label="按创建时间筛选"
        >
          <option value="all">全部时间</option>
          <option value="7d">最近 7 天</option>
          <option value="30d">最近 30 天</option>
        </select>
      </label>
      <button
        className={styles.resetButton}
        type="button"
        disabled={
          !search &&
          platformFilter === "all" &&
          trackFilter === "all" &&
          qualityFilter === "all" &&
          dateFilter === "all"
        }
        onClick={onReset}
      >
        <RotateCcw size={14} aria-hidden="true" />
        重置
      </button>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
  formatOption = (option) => option,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  formatOption?: (option: string) => string;
}) {
  return (
    <label className={styles.filterField}>
      <span>{label}</span>
      <select
        value={value}
        disabled={!options.length}
        onChange={(event) => onChange(event.target.value)}
        aria-label={`按${label}筛选`}
      >
        <option value="all">{options.length ? `全部${label}` : "当前页未提供"}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {formatOption(option)}
          </option>
        ))}
      </select>
    </label>
  );
}

function AssetCard({
  asset,
  focused,
  selected,
  onFocus,
  onToggle,
}: {
  asset: AssetSummary;
  focused: boolean;
  selected: boolean;
  onFocus: (asset: AssetSummary) => void;
  onToggle: (id: string) => void;
}) {
  const date = formatAssetDate(asset.createdAt);
  const [thumbnailFailed, setThumbnailFailed] = useState(false);
  const thumbnailUrl = stringValue(asset.thumbnail.url);
  const showThumbnail = Boolean(thumbnailUrl) && !thumbnailFailed;
  useEffect(() => {
    setThumbnailFailed(false);
  }, [thumbnailUrl]);
  return (
    <article
      className={[
        styles.assetCard,
        focused ? styles.assetCardFocused : "",
        selected ? styles.assetCardSelected : "",
      ].join(" ")}
      role="listitem"
    >
      <div className={styles.cardMediaFrame}>
        <button
          className={styles.cardOpen}
          type="button"
          onClick={() => onFocus(asset)}
          aria-label={`查看素材 ${asset.title}`}
        >
          <span className={styles.assetMedia}>
            {showThumbnail ? (
              <img
                src={thumbnailUrl}
                alt={`${asset.title} 缩略图`}
                loading="lazy"
                onError={() => setThumbnailFailed(true)}
              />
            ) : (
              <>
                <ImageOff size={22} aria-hidden="true" />
                <span>{thumbnailUrl ? "缩略图暂不可用" : "缩略图未提供"}</span>
              </>
            )}
          </span>
        </button>
        <label className={styles.cardCheckbox}>
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggle(asset.publicAssetId)}
          />
          <span className={styles.srOnly}>选择素材 {asset.publicAssetId}</span>
        </label>
      </div>
      <div className={styles.cardBody}>
        <button
          className={styles.cardId}
          type="button"
          onClick={() => onFocus(asset)}
          title={asset.publicAssetId}
        >
          {asset.publicAssetId}
        </button>
        <strong className={styles.cardTitle} title={asset.title}>
          {asset.title}
        </strong>
        <div className={styles.cardIdentityMeta}>
          <PlatformIdentity
            className={styles.cardPlatformIdentity}
            platform={asset.platform}
            size="sm"
          />
          <span
            className={styles.cardMediaType}
            title={mediaTypeDisplayLabel(asset.mediaType)}
          >
            {mediaTypeDisplayLabel(asset.mediaType)}
          </span>
          <span>{qualityLabel(asset.qualityStatus)}</span>
          <span>{materialStatusLabel(asset.materialStatus)}</span>
        </div>
        {asset.platformHashtags.length ? (
          <div className={styles.cardTags} aria-label="平台话题标签">
            <span className={styles.srOnly}>平台话题标签</span>
            {asset.platformHashtags.slice(0, 2).map((hashtag) => (
              <span className={styles.tag} key={hashtag}>
                {formatPlatformHashtag(hashtag)}
              </span>
            ))}
            {asset.platformHashtags.length > 2 ? (
              <span className={styles.tag}>+{asset.platformHashtags.length - 2}</span>
            ) : null}
          </div>
        ) : null}
        <div className={styles.cardMeta}>
          <span title={asset.sourceLabel}>{asset.sourceLabel}</span>
          <span>{asset.usageCount} 次使用</span>
        </div>
        <time className={styles.cardDate} dateTime={date.dateTime}>
          {date.label}
        </time>
      </div>
    </article>
  );
}

function AssetInspector({
  asset,
  state,
  onClose,
  onRetry,
  onOpenCapability,
  onRequestDeletion,
}: {
  asset?: AssetSummary;
  state: LoadState<AssetResponse>;
  onClose: () => void;
  onRetry: () => void;
  onOpenCapability: (prefill: StructuredPrefill) => void;
  onRequestDeletion: (ids: string[]) => void;
}) {
  return (
    <div className={styles.inspectorColumn} data-page-inspector>
      <aside
        className={styles.inspector}
        aria-label="素材详情"
        data-page-terminal-surface="inspector"
      >
        <header className={styles.inspectorHeader}>
          <div>
            <h2>素材详情</h2>
            <span>{asset ? "当前选择" : "未选择素材"}</span>
          </div>
          <button
            className={styles.closeButton}
            type="button"
            onClick={onClose}
            aria-label="关闭素材详情"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </header>
        {!asset ? (
          <div className={styles.inspectorEmpty}>
            <Database size={22} aria-hidden="true" />
            <strong>选择一个素材</strong>
            <p>选择后读取详情、预览、证据和关联记录。</p>
          </div>
        ) : state.status === "waiting" || state.status === "loading" ? (
          <InspectorSurface
            kind="loading"
            title="正在读取素材详情"
            detail="详情只展示当前账户可查看的内容。"
          />
        ) : state.status === "permission" ? (
          <InspectorSurface
            kind="permission"
            title="没有详情读取权限"
            detail={state.message}
          />
        ) : state.status === "notFound" ? (
          <InspectorSurface
            kind="notFound"
            title="素材不存在或已不可见"
            detail={state.message}
          />
        ) : state.status === "error" ? (
          <InspectorSurface
            kind="error"
            title="暂时无法读取详情"
            detail={state.message}
            onRetry={onRetry}
          />
        ) : (
          <AssetDetailBody
            detail={state.data.item}
            onOpenCapability={onOpenCapability}
            onRequestDeletion={onRequestDeletion}
          />
        )}
      </aside>
    </div>
  );
}

function AssetDetailBody({
  detail,
  onOpenCapability,
  onRequestDeletion,
}: {
  detail: AssetDetail;
  onOpenCapability: (prefill: StructuredPrefill) => void;
  onRequestDeletion: (ids: string[]) => void;
}) {
  const previewUrl = stringValue(detail.previewDescriptor.url);
  const summary = detail.summary;
  const sourceUrl = detail.evidenceRefs
    .map((ref) => validHttpUrl(ref.publicUrl))
    .find(Boolean) ?? "";
  const evidenceRows = detail.evidenceRefs.length
    ? detail.evidenceRefs.map((ref, index) => [
        `来源证据 ${index + 1}`,
        <span className={styles.evidenceValue} key={`${ref.kind}-${index}`}>
          {ref.publicUrl ? (
            <a href={ref.publicUrl} target="_blank" rel="noreferrer">
              {evidenceKindDisplayLabel(ref.kind)}
            </a>
          ) : (
            evidenceKindDisplayLabel(ref.kind)
          )}
          <small>
            {qualityLabel(ref.qualityStatus)}
            {ref.capturedAt ? ` · ${formatDate(ref.capturedAt)}` : ""}
          </small>
        </span>,
      ] as [string, ReactNode])
    : [["来源证据", <FieldNotRecorded key="evidence" />] as [string, ReactNode]];
  const summaryRows: Array<[string, ReactNode]> = [
    ["媒体类型", mediaTypeDisplayLabel(summary.mediaType)],
    [
      "平台",
      <PlatformIdentity
        key="platform"
        platform={summary.platform}
        size="sm"
      />,
    ],
    ["来源", summary.sourceLabel],
    ["赛道", summary.trackNames.length ? summary.trackNames.join("、") : <FieldNotRecorded key="tracks" />],
    ...(summary.platformHashtags.length
      ? [["平台话题标签", summary.platformHashtags.map(formatPlatformHashtag).join("、")] as [string, ReactNode]]
      : []),
    ["质量", qualityLabel(summary.qualityStatus)],
    ["素材状态", materialStatusLabel(summary.materialStatus)],
    ["使用次数", String(summary.usageCount)],
    ["修订号", String(detail.revision)],
  ];

  return (
    <div className={styles.inspectorBody} tabIndex={0} aria-label="素材详情内容" data-detail-revision={detail.revision}>
      <div className={styles.inspectorPreview}>
        {previewUrl ? (
          <img src={previewUrl} alt={`${summary.title} 缩略图`} />
        ) : (
          <>
            <ImageOff size={25} aria-hidden="true" />
            <span>缩略图未提供</span>
          </>
        )}
      </div>
      <div className={styles.inspectorIdentity}>
        <h3 title={summary.title}>{summary.title}</h3>
        <p>{summary.publicAssetId}</p>
        <time dateTime={formatAssetDate(summary.createdAt).dateTime}>
          {formatAssetDate(summary.createdAt).label}
        </time>
      </div>
      <InspectorSection title="素材摘要">
        <InspectorList rows={summaryRows} />
      </InspectorSection>
      <InspectorSection title="来源证据">
        <InspectorList rows={evidenceRows} />
      </InspectorSection>
      <InspectorSection title="关联记录">
        <RelationList
          title="内容拆解"
          items={detail.deconstructions}
        />
        <RelationList
          title="创作模式"
          items={detail.creativePatterns}
        />
        <div className={styles.usageBlock}>
          <strong>使用记录</strong>
          {detail.usageRefs.length ? (
            <ul className={styles.refList}>
              {detail.usageRefs.map((_, index) => <li key={index}>关联使用记录 {index + 1}</li>)}
            </ul>
          ) : (
            <p>暂无关联使用记录</p>
          )}
        </div>
      </InspectorSection>
      <section className={styles.actionSection} aria-label="素材动作">
        <div className={styles.actionGrid}>
          <button type="button" onClick={() => onOpenCapability({
            capabilityId: "creation_decision_brief",
            variantId: "default",
            params: {
              field_57060c88a36b: `基于素材“${summary.title}”（${summary.publicAssetId}）生成选题 Brief`,
            },
          })}>
            <Lightbulb size={14} aria-hidden="true" />
            生成选题
          </button>
          <button type="button" onClick={() => onOpenCapability({
            capabilityId: "viral_deconstruction",
            variantId: "default",
            params: { field_c29fd750ad50: sourceUrl },
          })}
            disabled={!sourceUrl}
            title={sourceUrl ? "内容拆解" : "该素材未提供可拆解的公开链接"}
          >
            <FileText size={14} aria-hidden="true" />
            内容拆解
          </button>
          <button type="button" onClick={() => onOpenCapability({
            capabilityId: "selfmedia_creation",
            variantId: "default",
            params: { source_asset_id: summary.publicAssetId },
          })}>
            <Lightbulb size={14} aria-hidden="true" />
            进入创作
          </button>
        </div>
        <p className={styles.actionNote}>
          通过现有能力目录打开任务工作区；当前详情只展示已提供的素材信息。
        </p>
      </section>
      <section className={styles.dangerZone} aria-label="删除影响">
        <h4>删除影响</h4>
        <p>
          删除前会检查当前影响；确认后永久删除素材及其相关页面记录，本地媒体文件不会被页面隐式删除。
        </p>
        <button type="button" onClick={() => onRequestDeletion([summary.publicAssetId])}>
          <Trash2 size={15} aria-hidden="true" />
          删除素材
        </button>
      </section>
    </div>
  );
}

function validHttpUrl(value: string | null): string {
  if (!value) return "";
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? value : "";
  } catch {
    return "";
  }
}

function RelationList({
  title,
  items,
}: {
  title: string;
  items: StringValueMap[];
}) {
  return (
    <div className={styles.relationBlock}>
      <strong>{title}</strong>
      {items.length ? (
        <div className={styles.relationList}>
          {items.map((_, index) => (
            <article className={styles.relationItem} key={`${title}-${index}`}>
              <h5>关联记录 {index + 1}</h5>
              <p>已返回关联记录，详细字段暂未开放展示。</p>
            </article>
          ))}
        </div>
      ) : (
        <p>暂无关联记录</p>
      )}
    </div>
  );
}

function InspectorSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className={styles.inspectorSection}>
      <h4>{title}</h4>
      {children}
    </section>
  );
}

function InspectorList({ rows }: { rows: Array<[string, ReactNode]> }) {
  return (
    <dl className={styles.inspectorList}>
      {rows.map(([label, value], index) => (
        <div key={`${label}-${index}`}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function FieldNotRecorded() {
  return <span className={styles.fieldUnavailable}>未记录</span>;
}

function ProjectionSurface({
  kind,
  title,
  detail,
  onRetry,
}: {
  kind: "loading" | "permission" | "error" | "empty" | "filtered" | "notFound";
  title: string;
  detail: string;
  onRetry?: () => void;
}) {
  const icon =
    kind === "loading" ? (
      <LoaderCircle className={styles.spin} size={22} aria-hidden="true" />
    ) : kind === "permission" ? (
      <LogIn size={22} aria-hidden="true" />
    ) : kind === "filtered" || kind === "notFound" ? (
      <SearchX size={22} aria-hidden="true" />
    ) : kind === "empty" ? (
      <Database size={22} aria-hidden="true" />
    ) : (
      <AlertCircle size={22} aria-hidden="true" />
    );
  return (
    <section
      className={styles.projectionSurface}
      role="status"
      aria-busy={kind === "loading"}
    >
      <span className={styles.surfaceIcon}>{icon}</span>
      <strong>{title}</strong>
      <p>{detail}</p>
      {kind === "error" && onRetry ? (
        <button className={styles.surfaceRetry} type="button" onClick={onRetry}>
          <RotateCcw size={14} aria-hidden="true" />
          重新读取
        </button>
      ) : null}
    </section>
  );
}

function InspectorSurface({
  kind,
  title,
  detail,
  onRetry,
}: {
  kind: "loading" | "permission" | "error" | "notFound";
  title: string;
  detail: string;
  onRetry?: () => void;
}) {
  return (
    <div className={styles.inspectorState}>
      <ProjectionSurface kind={kind} title={title} detail={detail} onRetry={onRetry} />
    </div>
  );
}


function useAssetProjection(
  cursor: string | undefined,
  search: string,
  enabled: boolean,
  retryToken: number,
): AssetListState {
  const [state, setState] = useState<AssetListState>({
    status: "waiting",
  });
  useEffect(() => {
    if (!enabled) {
      setState({ status: "waiting" });
      return;
    }
    const controller = new AbortController();
    let active = true;
    setState({ status: "loading" });
    callBusinessOperation<AssetListResponse>("listAssets", {
      query: {
        cursor,
        pageSize: 30,
        search: search.trim() || undefined,
      },
      signal: controller.signal,
    })
      .then((data) => {
        if (active) setState({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (!active || controller.signal.aborted) return;
        if (error instanceof BusinessOperationError && (error.status === 401 || error.status === 403)) {
          setState({ status: "permission", message: "当前账户没有素材读取权限。" });
          return;
        }
        setState({
          status: "error",
          message: "素材暂时无法读取。请点击“重新读取”重试。",
        });
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [cursor, enabled, retryToken, search]);
  return state;
}

function useAssetDetail(
  publicAssetId: string | undefined,
  enabled: boolean,
  retryToken: number,
): LoadState<AssetResponse> {
  const [state, setState] = useState<LoadState<AssetResponse>>({
    status: "waiting",
  });
  useEffect(() => {
    if (!enabled || !publicAssetId) {
      setState({ status: "waiting" });
      return;
    }
    const controller = new AbortController();
    let active = true;
    setState({ status: "loading" });
    callBusinessOperation<AssetResponse>("getAsset", {
      path: { publicAssetId },
      signal: controller.signal,
    })
      .then((data) => {
        if (active) setState({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (!active || controller.signal.aborted) return;
        if (error instanceof BusinessOperationError) {
          if (error.status === 401 || error.status === 403) {
            setState({ status: "permission", message: "当前账户没有素材详情读取权限。" });
            return;
          }
          if (error.status === 404 || error.code === "resource_not_found") {
            setState({ status: "notFound", message: "该素材不存在，或已不再对当前账户可见。" });
            return;
          }
        }
        setState({
          status: "error",
          message: "素材详情暂时无法读取。请点击“重新读取”重试。",
        });
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [enabled, publicAssetId, retryToken]);
  return state;
}

function uniqueValues(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b, "zh-CN"),
  );
}

function qualityLabel(value: string): string {
  return qualityDisplayLabel(value);
}

function materialStatusLabel(value: string | null | undefined): string {
  return materialStatusDisplayLabel(value);
}

function evidenceKindDisplayLabel(value: string): string {
  return ({ source: "来源链接", citation: "引用来源", reference: "参考来源" }[value.toLowerCase()] ?? "来源证据");
}

function formatAssetDate(value: string): { label: string; dateTime?: string } {
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp)
    ? { label: formatDate(value), dateTime: new Date(timestamp).toISOString() }
    : { label: "创建时间未提供" };
}

function isWithinDateFilter(value: string, filter: DateFilter): boolean {
  if (filter === "all") return true;
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return false;
  const age = Date.now() - timestamp;
  const days = filter === "7d" ? 7 : 30;
  return age >= 0 && age <= days * 24 * 60 * 60 * 1000;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function formatPlatformHashtag(value: string): string {
  const normalized = value.trim();
  return normalized.startsWith("#") ? normalized : `#${normalized}`;
}

export default AssetsPage;
