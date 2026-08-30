type TaskFeedItem = {
  taskId: string;
  capabilityId: string;
  variantId: string;
  params: Record<string, unknown>;
  status?: string;
  terminal: boolean;
  confirmationReceipt?: {
    kind?: string;
    expiresAt?: string;
  } | null;
  createdAt: string;
  updatedAt: string;
};

function hasActiveDeletionConfirmation(
  task: TaskFeedItem,
  nowMs: number,
): boolean {
  if (
    task.capabilityId !== "universal_deletion" ||
    task.variantId !== "confirm" ||
    task.status !== "awaiting_confirmation"
  ) {
    return true;
  }
  if (task.confirmationReceipt?.kind !== "deletion_preview") return false;
  const expiresAt = Date.parse(task.confirmationReceipt.expiresAt ?? "");
  return Number.isFinite(expiresAt) && expiresAt > nowMs;
}

export function shouldSubscribeToTask(
  task: TaskFeedItem,
  nowMs = Date.now(),
): boolean {
  return !task.terminal && hasActiveDeletionConfirmation(task, nowMs);
}

type SettlementTask = TaskFeedItem & {
  settlementStage: string;
  result?: { ok?: boolean } | null;
  accountBinding?: {
    userPublicId: string;
    ownedAccountPublicId: string;
    relationshipRef: string;
    platform: string;
    normalizedAccount: string;
  } | null;
  attempt?: {
    attemptId: string;
    runnerId: string;
    executorId: string;
    status: string;
    attemptNumber: number;
    recoveryOfAttemptId: string | null;
  } | null;
  missingReadbacks?: readonly ("database" | "external" | "web")[];
  receipt?: {
    receiptId: string;
    digest: string;
    status: string;
    createdAt: string;
  } | null;
  // API 边界将 error 保持为宽松记录；呈现层自行收窄字符串字段。
  error?: Record<string, unknown> | null;
};

const stableErrorMessages: Readonly<Record<string, string>> = {
  required_input_missing: "请补充必填的平台、客户自有账号或能力输入。",
  account_relationship_unavailable: "无法确认所选客户账号关系。",
  account_relationship_conflict: "所选客户账号关系存在冲突。",
};

// Independent state machine from statusPresentation.ts's runStatusLabels (settlement
// stages, not creation-run stages) -- keys coincide on a few names but the label wording
// is deliberately different ("已排队" vs "排队中" etc.), see dedup audit LE-07. Do not merge.
const settlementStageLabels: Readonly<Record<string, string>> = {
  submitted: "已提交",
  awaiting_confirmation: "等待你确认",
  queued: "已排队",
  runner_claimed: "开始处理",
  executing: "正在处理",
  database_readback: "正在确认保存结果",
  external_readback: "正在确认任务结果",
  web_readback: "正在同步网页内容",
  multi_system_readback_complete: "结果已确认",
  needs_manual: "需要人工处理",
  failed: "执行失败",
  cancelled: "已取消",
  validating: "正在检查输入",
  generating: "正在生成内容",
  succeeded: "已完成",
  pending_manual: "需要补充信息",
};

const attemptStatusLabels: Readonly<Record<string, string>> = {
  queued: "已排队",
  claimed: "已开始处理",
  running: "处理中",
  succeeded: "已完成",
  failed: "处理失败",
  cancelled: "已取消",
};

const readbackLabels: Readonly<Record<"database" | "external" | "web", string>> = {
  database: "数据库",
  external: "外部系统",
  web: "网页",
};

export type TaskSettlementPresentation = {
  stageLabel: string;
  bindingSummary: string | null;
  attemptSummary: string | null;
  recoverySummary: string | null;
  missingReadbackLabels: string[];
  receiptSummary: string | null;
  errorMessage: string | null;
  complete: boolean;
};

export function stableTaskErrorMessage(code: string, fallback?: string): string {
  if (stableErrorMessages[code]) return stableErrorMessages[code];
  void fallback;
  return "任务未完成，请稍后重试。";
}

export function settlementStageLabel(stage: string): string {
  return settlementStageLabels[stage] ?? "结算状态待读取";
}

export function taskSettlementPresentation(
  task: SettlementTask,
): TaskSettlementPresentation {
  const binding = task.accountBinding;
  const attempt = task.attempt;
  const missingReadbackLabels = (task.missingReadbacks ?? []).map(
    (kind) => readbackLabels[kind],
  );
  const fileBackedComplete = task.status === "succeeded" && task.result?.ok === true;
  const complete = fileBackedComplete || (
    task.settlementStage === "multi_system_readback_complete" &&
    task.receipt?.status === "multi_system_readback_complete"
  );
  return {
    stageLabel: settlementStageLabel(task.settlementStage),
    bindingSummary: binding
      ? `${binding.platform} · ${binding.normalizedAccount}`
      : null,
    attemptSummary: attempt
      ? `第 ${attempt.attemptNumber} 次处理 · ${attemptStatusLabels[attempt.status] ?? "处理中"}`
      : null,
    recoverySummary: attempt?.recoveryOfAttemptId
      ? "已从上一次中断处恢复"
      : null,
    missingReadbackLabels,
    receiptSummary: task.receipt
      ? `${complete ? "结果已确认" : "正在确认结果"} · ${task.receipt.createdAt}`
      : null,
    errorMessage: task.error
      ? stableTaskErrorMessage(
          typeof task.error.code === "string" ? task.error.code : "",
          typeof task.error.message === "string" ? task.error.message : undefined,
        )
      : null,
    complete,
  };
}

function taskTimestamp(task: TaskFeedItem): number {
  const createdAt = Date.parse(task.createdAt);
  if (Number.isFinite(createdAt)) return createdAt;
  const updatedAt = Date.parse(task.updatedAt);
  return Number.isFinite(updatedAt) ? updatedAt : 0;
}

export function latestTaskFeed<T extends TaskFeedItem>(
  tasks: readonly T[],
  nowMs = Date.now(),
): T[] {
  return tasks.filter((task) => {
    if (task.capabilityId !== "universal_deletion") return true;
    if (task.variantId === "preview") return false;
    if (task.variantId === "confirm" && task.status === "awaiting_confirmation")
      return hasActiveDeletionConfirmation(task, nowMs);
    return true;
  }).sort((left, right) => {
    const timestampDifference = taskTimestamp(right) - taskTimestamp(left);
    return timestampDifference || right.taskId.localeCompare(left.taskId);
  });
}
