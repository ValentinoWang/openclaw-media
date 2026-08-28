import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, join } from "node:path";

const AUDIO_EXTENSIONS = new Set([
  ".aac", ".amr", ".caf", ".flac", ".m4a", ".m4v", ".mov",
  ".mp3", ".mp4", ".ogg", ".opus", ".wav", ".webm",
]);
const DEFAULT_RETENTION_MS = 7 * 24 * 60 * 60 * 1000;
const TRANSCRIPTION_QUEUE_ROOT_ENV = "OPENCLAW_TRANSCRIPTION_QUEUE_ROOT";

function nowIso(now) {
  return new Date(now).toISOString();
}

function cleanString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function defaultQueueRoot() {
  return cleanString(process.env[TRANSCRIPTION_QUEUE_ROOT_ENV])
    || join(homedir(), ".openclaw", "workspace", "openclaw-tag-router", "transcription-queue");
}

function scopeFrom(event, context) {
  const metadata = event?.metadata && typeof event.metadata === "object" ? event.metadata : {};
  const accountId = cleanString(context?.accountId ?? event?.accountId) || "unknown";
  const conversationId = cleanString(
    context?.sessionKey
      ?? event?.sessionKey
      ?? context?.conversationId
      ?? metadata.originatingTo
      ?? metadata.to
      ?? event?.from,
  );
  const senderId = cleanString(event?.senderId ?? context?.senderId ?? metadata.senderId ?? event?.from);
  if (!conversationId || !senderId) return null;
  return { account_id: accountId, conversation_id: conversationId, sender_id: senderId };
}

function stateKey(scope) {
  return createHash("sha256")
    .update(`${scope.account_id}\n${scope.conversation_id}\n${scope.sender_id}`)
    .digest("hex");
}

function mediaPaths(event) {
  const metadata = event?.metadata && typeof event.metadata === "object" ? event.metadata : {};
  const paths = Array.isArray(metadata.mediaPaths)
    ? metadata.mediaPaths
    : cleanString(metadata.mediaPath)
      ? [metadata.mediaPath]
      : [];
  const types = Array.isArray(metadata.mediaTypes)
    ? metadata.mediaTypes
    : cleanString(metadata.mediaType)
      ? [metadata.mediaType]
      : [];
  return paths
    .map((path, index) => ({
      path: cleanString(path),
      media_type: cleanString(types[index] ?? types[0]),
    }))
    .filter((item) => item.path && isAudio(item.path, item.media_type));
}

function isAudio(path, mediaType) {
  if (cleanString(mediaType).toLowerCase().startsWith("audio/")) return true;
  const lower = path.toLowerCase();
  return [...AUDIO_EXTENSIONS].some((extension) => lower.endsWith(extension));
}

function originalFilename(content, path, index, total) {
  const matches = [...String(content ?? "").matchAll(/<media:[^>]+>\s*\(([^)]+)\)/g)];
  const value = matches[index]?.[1]
    || (total === 1 ? matches[0]?.[1] : "")
    || basename(path).replace(/---[0-9a-f]{8}-[0-9a-f-]{27,}$/i, "")
    || `录音${index + 1}`;
  return String(value).replace(/[\r\n\t`]+/g, " ").trim().slice(0, 180);
}

function parseTranscriptionCommand(content) {
  const match = String(content ?? "").trim().match(/^【转写】([\s\S]*)$/);
  if (!match) return null;
  const body = match[1].trim();
  const confirmation = body.match(/^确认(?:\s+([A-Za-z0-9_-]+))?\s*$/);
  if (confirmation) return { action: "confirm", batch_id: cleanString(confirmation[1]) };
  const cancellation = body.match(/^取消(?:\s+([A-Za-z0-9_-]+))?\s*$/);
  if (cancellation) return { action: "cancel", batch_id: cleanString(cancellation[1]) };
  return { action: "prepare", request_text: String(content ?? "").trim() };
}

function activeItems(state) {
  return state.items.filter((item) => item.status === "pending" && existsSync(item.path));
}

function createBatchId(scope, items, requestText, now) {
  const digest = createHash("sha256")
    .update(JSON.stringify([scope, items.map((item) => item.id), requestText, now, process.hrtime.bigint().toString()]))
    .digest("hex")
    .slice(0, 10);
  return `tx-${digest}`;
}

function createAutomaticBatchId(scope, items, messageId) {
  const digest = createHash("sha256")
    .update(JSON.stringify([scope, messageId, items.map((item) => item.id)]))
    .digest("hex")
    .slice(0, 10);
  return `tx-${digest}`;
}

function isKnowledgeAccount(scope) {
  return cleanString(scope?.account_id).toLowerCase().replace(/^feishu[-_]/, "") === "knowledge";
}

function confirmationReply(batch, items, { refreshed = false } = {}) {
  const lines = [
    refreshed ? "转写批次已更新，请重新确认" : "转写待确认",
    `批次：${batch.id}`,
    `录音数量：${items.length}`,
    "录音名称：",
    ...items.map((item, index) => `${index + 1}. ${item.display_name}`),
    "",
    `确认开始：\`【转写】确认 ${batch.id}\``,
    `取消本批：\`【转写】取消 ${batch.id}\``,
  ];
  if (refreshed) {
    lines.splice(1, 0, "原因：确认后录音列表发生了变化，旧批次不会执行。", "");
  }
  return lines.join("\n");
}

function attachmentIntakeReply(items) {
  return [
    "录音已暂存",
    `待转写录音数量：${items.length}`,
    "录音名称：",
    ...items.map((item, index) => `${index + 1}. ${item.display_name}`),
    "",
    "下一步：发送 `【转写】` 查看本批文件并确认开始。",
  ].join("\n");
}

function missingBatchReply(state, action) {
  const current = state.batch;
  if (current?.id) {
    const command = action === "cancel" ? "取消" : "确认";
    return [
      "转写尚未开始",
      "原因：确认指令缺少或使用了错误的批次号。",
      `当前批次：${current.id}`,
      `建议：发送 \`【转写】${command} ${current.id}\`。`,
    ].join("\n");
  }
  return "转写尚未开始\n原因：当前没有待确认批次。\n建议：先上传录音，再发送 `【转写】` 查看并确认文件列表。";
}

export class TranscriptionQueue {
  constructor({ dataRoot, retentionMs = DEFAULT_RETENTION_MS, now = () => Date.now(), logger } = {}) {
    this.root = dataRoot ? join(dataRoot, "transcription-queue") : defaultQueueRoot();
    this.retentionMs = retentionMs;
    this.now = now;
    this.logger = logger;
  }

  record(event, context) {
    const scope = scopeFrom(event, context);
    const media = mediaPaths(event);
    if (!scope || media.length === 0) return 0;

    const state = this.#read(scope);
    const timestamp = this.now();
    const messageId = cleanString(event?.messageId ?? event?.metadata?.messageId);
    let recorded = 0;
    for (const [index, item] of media.entries()) {
      if (!existsSync(item.path)) continue;
      const id = createHash("sha256").update(`${messageId}\n${item.path}`).digest("hex").slice(0, 20);
      if (state.items.some((existing) => existing.id === id)) continue;
      state.items.push({
        id,
        message_id: messageId,
        path: item.path,
        media_type: item.media_type,
        display_name: originalFilename(event?.content, item.path, index, media.length),
        uploaded_at: nowIso(timestamp),
        status: "pending",
      });
      recorded += 1;
    }
    if (recorded > 0) {
      state.revision += 1;
      state.updated_at = nowIso(timestamp);
      this.#write(scope, state);
      this.logger?.info?.(`[openclaw-tag-router] queued ${recorded} transcription attachment(s) account=${scope.account_id}`);
    }
    return recorded;
  }

  intake(event, context) {
    const scope = scopeFrom(event, context);
    const media = mediaPaths(event);
    if (!scope || media.length === 0) return null;
    if (isKnowledgeAccount(scope)) return this.#prepareAutomatic(event, context, scope);
    this.record(event, context);
    const items = activeItems(this.#read(scope));
    if (items.length === 0) return null;
    return { text: attachmentIntakeReply(items) };
  }

  prepare(event, context) {
    const command = parseTranscriptionCommand(event?.content);
    if (!command) return { kind: "pass" };
    const scope = scopeFrom(event, context);
    if (!scope) return { kind: "pass" };
    const state = this.#read(scope);
    const existingBatch = state.batch;
    if (
      command.action === "confirm"
      && command.batch_id
      && existingBatch?.id === command.batch_id
      && existingBatch?.job_id
    ) {
      return {
        kind: "already_enqueued",
        batch_id: existingBatch.id,
        job_id: existingBatch.job_id,
      };
    }
    const items = activeItems(state);
    if (items.length === 0) {
      if (state.batch && state.batch.status !== "queued") {
        state.batch = null;
        state.updated_at = nowIso(this.now());
        this.#write(scope, state);
      }
      return command.action === "prepare"
        ? { kind: "pass" }
        : { kind: "reply", text: missingBatchReply(state, command.action) };
    }

    if (command.action === "prepare") {
      const batch = this.#newBatch(scope, state, items, command.request_text);
      this.#write(scope, state);
      return { kind: "reply", text: confirmationReply(batch, items) };
    }

    const batch = state.batch;
    if (!command.batch_id || !batch || command.batch_id !== batch.id) {
      return { kind: "reply", text: missingBatchReply(state, command.action) };
    }

    if (batch.revision !== state.revision) {
      const refreshed = this.#newBatch(scope, state, items, batch.request_text);
      this.#write(scope, state);
      return { kind: "reply", text: confirmationReply(refreshed, items, { refreshed: true }) };
    }

    const batchItems = batch.item_ids
      .map((id) => items.find((item) => item.id === id))
      .filter(Boolean);
    if (batchItems.length !== batch.item_ids.length) {
      const refreshed = this.#newBatch(scope, state, items, batch.request_text);
      this.#write(scope, state);
      return { kind: "reply", text: confirmationReply(refreshed, items, { refreshed: true }) };
    }

    if (command.action === "cancel") {
      for (const item of batchItems) item.status = "cancelled";
      state.batch = null;
      state.updated_at = nowIso(this.now());
      this.#write(scope, state);
      return {
        kind: "reply",
        text: [
          "已取消本批转写",
          `批次：${batch.id}`,
          ...batchItems.map((item, index) => `${index + 1}. ${item.display_name}`),
        ].join("\n"),
      };
    }

    return this.#enqueueAction(scope, batch, batchItems);
  }

  markEnqueued(scope, batchId, jobId) {
    if (!scope || !batchId || !jobId) return;
    const state = this.#read(scope);
    const batch = state.batch;
    if (!batch || batch.id !== batchId) return;
    for (const item of state.items) {
      if (!batch.item_ids.includes(item.id)) continue;
      item.status = "queued";
      item.job_id = jobId;
      item.queued_at = nowIso(this.now());
    }
    batch.status = "queued";
    batch.job_id = jobId;
    batch.queued_at = nowIso(this.now());
    state.updated_at = nowIso(this.now());
    this.#write(scope, state);
  }

  #prepareAutomatic(event, context, scope) {
    const messageId = cleanString(event?.messageId ?? event?.metadata?.messageId);
    if (!messageId) {
      return {
        kind: "reply",
        text: "[TRANSCRIPTION_MESSAGE_ID_MISSING] 转写任务未创建。原因：当前录音缺少可持久化的飞书 message ID。建议：请重新发送原录音。",
      };
    }
    this.record(event, context);
    const state = this.#read(scope);
    const messageItems = state.items.filter((item) => item.message_id === messageId && existsSync(item.path));
    const existingJobIds = [...new Set(
      messageItems
        .filter((item) => item.status === "queued" && cleanString(item.job_id))
        .map((item) => cleanString(item.job_id)),
    )];
    if (existingJobIds.length === 1 && messageItems.every((item) => item.status === "queued")) {
      return { kind: "already_enqueued", job_id: existingJobIds[0] };
    }
    const items = messageItems.filter((item) => item.status === "pending");
    if (items.length === 0) {
      return {
        kind: "reply",
        text: "[TRANSCRIPTION_ATTACHMENT_STATE_INVALID] 转写任务未创建。原因：录音状态无法与独立任务对应。建议：请重新发送原录音。",
      };
    }
    const command = parseTranscriptionCommand(event?.content);
    const requestText = command?.action === "prepare" ? command.request_text : "【转写】";
    const createdAt = nowIso(this.now());
    const batch = {
      id: createAutomaticBatchId(scope, items, messageId),
      revision: state.revision,
      item_ids: items.map((item) => item.id),
      request_text: requestText,
      source_message_id: messageId,
      created_at: createdAt,
      status: "ready",
      automatic: true,
    };
    state.batch = batch;
    state.updated_at = createdAt;
    this.#write(scope, state);
    return this.#enqueueAction(scope, batch, items);
  }

  #enqueueAction(scope, batch, items) {
    return {
      kind: "enqueue",
      scope,
      batch_id: batch.id,
      request_text: batch.request_text,
      metadata: {
        source_message_id: batch.source_message_id || "",
        downloaded_paths: items.map((item) => item.path),
        transcription_batch_id: batch.id,
        transcription_batch_confirmed: true,
        transcription_automatic: batch.automatic === true,
        transcription_attachments: items.map((item) => ({
          path: item.path,
          name: item.display_name,
          message_id: item.message_id,
        })),
      },
    };
  }

  #newBatch(scope, state, items, requestText) {
    const timestamp = this.now();
    const batch = {
      id: createBatchId(scope, items, requestText, timestamp),
      revision: state.revision,
      item_ids: items.map((item) => item.id),
      request_text: requestText,
      created_at: nowIso(timestamp),
      status: "ready",
    };
    state.batch = batch;
    state.updated_at = batch.created_at;
    return batch;
  }

  #path(scope) {
    return join(this.root, `${stateKey(scope)}.json`);
  }

  #read(scope) {
    const path = this.#path(scope);
    let state = null;
    try {
      state = JSON.parse(readFileSync(path, "utf8"));
    } catch {
      state = null;
    }
    if (!state || state.version !== 1 || !Array.isArray(state.items)) {
      state = {
        version: 1,
        scope,
        revision: 0,
        updated_at: nowIso(this.now()),
        items: [],
        batch: null,
      };
    }
    const cutoff = this.now() - this.retentionMs;
    state.items = state.items.filter((item) => {
      const uploadedAt = Date.parse(item.uploaded_at || "");
      if (item.status === "pending") return existsSync(item.path);
      return Number.isFinite(uploadedAt) && uploadedAt >= cutoff;
    });
    return state;
  }

  #write(scope, state) {
    const path = this.#path(scope);
    mkdirSync(dirname(path), { recursive: true });
    const temporary = `${path}.${process.pid}.tmp`;
    writeFileSync(temporary, `${JSON.stringify(state, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
    renameSync(temporary, path);
  }
}

export function createTranscriptionQueue(options) {
  return new TranscriptionQueue(options);
}
