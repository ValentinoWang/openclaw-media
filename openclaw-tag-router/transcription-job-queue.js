import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";

function cleanString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function nowIso(now) {
  return new Date(now).toISOString();
}

function jobIdForBatch(batchId) {
  return `tr-${String(batchId || "").replace(/^tx-/, "")}`;
}

function startedReply(job) {
  const attachments = job.payload.metadata.transcription_attachments || [];
  return [
    "转写任务已入队",
    `任务ID：${job.id}`,
    `批次：${job.batch_id}`,
    `录音数量：${attachments.length}`,
    "状态：已持久化进入后台队列；完成或失败后当前 Bot 会主动通知。",
  ].join("\n");
}

export class TranscriptionJobQueue {
  constructor({ dataRoot, now = () => Date.now(), sequence = () => process.hrtime.bigint().toString(), logger } = {}) {
    this.root = join(dataRoot || "/home/ubuntu/.openclaw/workspace/openclaw-tag-router", "transcription-jobs");
    this.now = now;
    this.sequence = sequence;
    this.logger = logger;
  }

  enqueue(action, event, context) {
    const jobId = jobIdForBatch(action.batch_id);
    const existing = this.read(jobId);
    if (existing) return { job: existing, created: false, text: startedReply(existing) };

    const createdAtMs = this.now();
    const createdAt = nowIso(createdAtMs);
    const accountId = cleanString(context?.accountId ?? event?.accountId) || "daily";
    const senderId = cleanString(event?.senderId ?? context?.senderId ?? action.scope?.sender_id);
    const conversationId = cleanString(context?.conversationId ?? action.scope?.conversation_id);
    const sourceMessageId = cleanString(action?.metadata?.source_message_id ?? event?.messageId ?? event?.metadata?.messageId);
    const jobDir = join(this.root, jobId);
    const progressPath = join(jobDir, "stage-events.jsonl");
    const job = {
      version: 1,
      id: jobId,
      batch_id: action.batch_id,
      state: "queued",
      notification_state: "pending",
      attempts: 0,
      created_at: createdAt,
      enqueue_order: `${String(createdAtMs).padStart(16, "0")}-${String(this.sequence()).padStart(24, "0")}`,
      updated_at: createdAt,
      account_id: accountId,
      source_message_id: sourceMessageId,
      sender_id: senderId,
      conversation_id: conversationId,
      session_key: cleanString(context?.sessionKey ?? action.scope?.conversation_id),
      target: `user:${senderId}`,
      progress_path: progressPath,
      payload: {
        text: action.request_text,
        source: "feishu",
        chat_type: event?.isGroup === true ? "group" : "private",
        metadata: {
          ...(action.metadata || {}),
          account_id: accountId,
          source_sender_id: senderId,
          source_conversation_id: conversationId,
          source_message_id: sourceMessageId,
          transcription_job_id: jobId,
          transcription_progress_path: progressPath,
          transcription_defer_source_delete: true,
        },
      },
      notifications: {},
    };
    mkdirSync(jobDir, { recursive: true });
    this.#write(job);
    this.logger?.info?.(`[openclaw-tag-router] queued asynchronous transcription job id=${jobId}`);
    return { job, created: true, text: startedReply(job) };
  }

  read(jobId) {
    try {
      const payload = JSON.parse(readFileSync(join(this.root, jobId, "job.json"), "utf8"));
      return payload?.version === 1 ? payload : null;
    } catch {
      return null;
    }
  }

  reply(jobId) {
    const job = this.read(jobId);
    return job ? startedReply(job) : `转写任务不存在\n任务ID：${jobId}`;
  }

  #write(job) {
    const path = join(this.root, job.id, "job.json");
    const temporary = `${path}.${process.pid}.tmp`;
    writeFileSync(temporary, `${JSON.stringify(job, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
    renameSync(temporary, path);
  }
}

export function createTranscriptionJobQueue(options) {
  return new TranscriptionJobQueue(options);
}
