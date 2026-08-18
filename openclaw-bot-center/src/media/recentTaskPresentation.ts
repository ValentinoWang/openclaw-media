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
  error?: { code: string; message: string; action: string } | null;
};

const stableErrorMessages: Readonly<Record<string, string>> = {
  required_input_missing: "请补充必填的平台、客户自有账号或能力输入。",
  account_relationship_unavailable: "无法确认所选客户账号关系。",
  account_relationship_conflict: "所选客户账号关系存在冲突。",
};

const settlementStageLabels: Readonly<Record<string, string>> = {
  submitted: "已提交，等待确认",
  queued: "已排队",
  runner_claimed: "执行器已领取",
  executing: "正在执行",
  database_readback: "等待数据库读回",
  external_readback: "等待外部系统读回",
  web_readback: "等待网页读回",
  multi_system_readback_complete: "多系统读回完成",
  needs_manual: "需要人工处理",
  failed: "执行失败",
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
  relationshipRef: string | null;
  attemptSummary: string | null;
  executorSummary: string | null;
  recoverySummary: string | null;
  missingReadbackLabels: string[];
  receiptSummary: string | null;
  receiptId: string | null;
  errorMessage: string | null;
  complete: boolean;
};

export function stableTaskErrorMessage(code: string, fallback?: string): string {
  return stableErrorMessages[code] ?? (fallback?.trim() || "任务未完成，请稍后重试。");
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
  const complete =
    task.settlementStage === "multi_system_readback_complete" &&
    task.receipt?.status === "multi_system_readback_complete";
  return {
    stageLabel: settlementStageLabel(task.settlementStage),
    bindingSummary: binding
      ? `${binding.platform} · ${binding.normalizedAccount}`
      : null,
    relationshipRef: binding?.relationshipRef ?? null,
    attemptSummary: attempt
      ? `第 ${attempt.attemptNumber} 次执行 · ${attempt.status}`
      : null,
    executorSummary: attempt
      ? `runner ${attempt.runnerId} · executor ${attempt.executorId}`
      : null,
    recoverySummary: attempt?.recoveryOfAttemptId
      ? `从执行尝试 ${attempt.recoveryOfAttemptId} 恢复`
      : attempt
        ? "本次执行不是租约恢复尝试"
        : null,
    missingReadbackLabels,
    receiptSummary: task.receipt
      ? `${complete ? "最终收据已生成" : "收据尚未完成"} · ${task.receipt.createdAt}`
      : null,
    receiptId: task.receipt?.receiptId ?? null,
    errorMessage: task.error
      ? stableTaskErrorMessage(task.error.code, task.error.message)
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
