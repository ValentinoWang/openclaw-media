import { spawn } from "node:child_process";
import { createHmac, timingSafeEqual } from "node:crypto";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { createTranscriptionQueue } from "./transcription-queue.js";
import { createTranscriptionJobQueue } from "./transcription-job-queue.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const BRIDGE_PATH = join(__dirname, "bridge.py");
const BOT_CENTER_DATA_PATH = String(process.env.OPENCLAW_BOT_CENTER_DATA_PATH || "/home/ubuntu/openclaw-bot-center/public/data/openclaw-bot-center.generated.json").trim();
const DEFAULT_BRIDGE_TIMEOUT_MS = Number.parseInt(process.env.OPENCLAW_TAG_ROUTER_BRIDGE_TIMEOUT_MS || "", 10) || 270 * 1000;
const BRIDGE_OUTPUT_LIMIT = 6000;

class BridgeProcessError extends Error {
  constructor(message, details = {}) {
    super(message);
    this.name = "BridgeProcessError";
    this.details = details;
    this.statusCode = details.timeout ? 504 : 502;
  }
}

function json(res, statusCode, body) {
  const payload = JSON.stringify(body);
  res.statusCode = statusCode;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Content-Length", Buffer.byteLength(payload, "utf8"));
  res.end(payload);
}

async function readJson(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  return Buffer.concat(chunks);
}

function parseJsonBuffer(buffer) {
  const raw = buffer.toString("utf8").trim();
  return raw ? JSON.parse(raw) : {};
}

function normalizeRouteBase(value) {
  const trimmed = String(value || "").trim();
  if (!trimmed) return "/api/channels/openclaw-tag-router";
  return trimmed.startsWith("/") ? trimmed.replace(/\/+$/, "") : `/${trimmed.replace(/\/+$/, "")}`;
}

function normalizeExactPath(value, defaultPath) {
  const trimmed = String(value || "").trim();
  if (!trimmed) return defaultPath;
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

function clipOutput(value, limit = BRIDGE_OUTPUT_LIMIT) {
  const text = String(value || "");
  return text.length > limit ? text.slice(-limit) : text;
}

function parseBridgeJson(stdout) {
  try {
    const parsed = JSON.parse(String(stdout || "").trim() || "{}");
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function firstHeaderValue(value) {
  if (Array.isArray(value)) return String(value[0] || "").trim();
  return String(value || "").trim();
}

function safeEqual(a, b) {
  const left = Buffer.from(String(a), "utf8");
  const right = Buffer.from(String(b), "utf8");
  if (left.length !== right.length) return false;
  return timingSafeEqual(left, right);
}

function configuredFeishuAdminIds(value) {
  return new Set(
    String(value || "")
      .split(/[\s,;]+/)
      .map((item) => item.trim())
      .filter((item) => item && item !== "*"),
  );
}

export function resolveFeishuGlobalAdminContext(config, senderId) {
  const principal = String(senderId || "").trim();
  const tenantId = String(config?.globalAdminTenantId || "").trim();
  const allowed = configuredFeishuAdminIds(config?.feishuGlobalAdminIds);
  if (!principal || !/^[1-9][0-9]*$/.test(tenantId) || !allowed.has(principal)) return {};
  return {
    tenant_id: tenantId,
    operator_id: principal,
    is_maintainer: true,
    authorization: {
      principal: `feishu:${principal}`,
      is_maintainer: true,
    },
  };
}

function verifyQQWebhookSecret(req, rawBody, secret) {
  const expected = String(secret || "").trim();
  if (!expected) return true;

  const directHeaders = [
    req.headers["x-openclaw-webhook-secret"],
    req.headers["x-openclaw-tag-router-secret"],
    req.headers["x-qq-webhook-secret"],
  ];
  for (const header of directHeaders) {
    const value = firstHeaderValue(header);
    if (value && safeEqual(value, expected)) return true;
  }

  const authorization = firstHeaderValue(req.headers.authorization);
  if (authorization.startsWith("Bearer ")) {
    const token = authorization.slice("Bearer ".length).trim();
    if (token && safeEqual(token, expected)) return true;
  }

  const signature = firstHeaderValue(req.headers["x-signature"] || req.headers["x-onebot-signature"]);
  if (signature.startsWith("sha1=")) {
    const expectedSignature = `sha1=${createHmac("sha1", expected).update(rawBody).digest("hex")}`;
    if (safeEqual(signature, expectedSignature)) return true;
  }

  return false;
}

function resolvePluginConfig(api) {
  const config = api.runtime?.config?.loadConfig?.() ?? {};
  const pluginEntry = config?.plugins?.entries?.["openclaw-tag-router"] ?? {};
  const pluginConfig = pluginEntry.config ?? {};
  return {
    enabled: pluginEntry.enabled !== false && pluginConfig.enabled !== false,
    routeBase: normalizeRouteBase(pluginConfig.routeBase),
    pythonBin: String(pluginConfig.pythonBin || "python3"),
    dataRoot: String(pluginConfig.dataRoot || "/home/ubuntu/.openclaw/workspace/openclaw-tag-router"),
    settingsPath: String(pluginConfig.settingsPath || "/home/ubuntu/.openclaw/extensions/openclaw-tag-router/config/settings.yaml"),
    bridgeTimeoutMs: Number(pluginConfig.bridgeTimeoutMs || DEFAULT_BRIDGE_TIMEOUT_MS),
    qqWebhookPath: String(pluginConfig.qqWebhookPath || "").trim()
      ? normalizeExactPath(pluginConfig.qqWebhookPath, "")
      : "",
    qqWebhookSecret: String(pluginConfig.qqWebhookSecret || ""),
    globalAdminTenantId: String(process.env.OPENCLAW_GLOBAL_ADMIN_TENANT_ID || "").trim(),
    feishuGlobalAdminIds: String(process.env.OPENCLAW_GLOBAL_ADMIN_FEISHU_OPEN_IDS || "").trim(),
  };
}

function resolveAgentModel(api) {
  const config = api.runtime?.config?.loadConfig?.() ?? {};
  const model = config?.agents?.defaults?.model;
  if (model && typeof model === "object") {
    return String(model.primary || "").trim();
  }
  return String(model || "").trim();
}

function withModelLabel(api, result) {
  if (!result || typeof result !== "object" || typeof result.reply !== "string") {
    return result;
  }
  const reply = result.reply.trimStart();
  if (!reply || reply.startsWith("模型编号：") || reply.startsWith("模型：") || reply.startsWith("Model:")) {
    return result;
  }
  const model = resolveAgentModel(api);
  if (!model) return result;
  return { ...result, reply: `模型：${model}\n\n${result.reply}` };
}

export function runBridge(config, mode, payload) {
  return new Promise((resolve, reject) => {
    const timeoutMs = Math.max(1000, Number(config.bridgeTimeoutMs) || DEFAULT_BRIDGE_TIMEOUT_MS);
    const child = spawn(
      config.pythonBin,
      [BRIDGE_PATH, mode, config.dataRoot, config.settingsPath],
      { stdio: ["pipe", "pipe", "pipe"] },
    );
    let stdout = "";
    let stderr = "";
    let settled = false;
    let timedOut = false;
    const killTimer = { current: null };
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
      killTimer.current = setTimeout(() => {
        if (!settled) child.kill("SIGKILL");
      }, 5000);
      killTimer.current.unref?.();
    }, timeoutMs);
    timer.unref?.();
    const finish = (callback) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (killTimer.current) clearTimeout(killTimer.current);
      callback();
    };
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
    });
    child.on("error", (error) => {
      finish(() => reject(new BridgeProcessError(`bridge spawn failed: ${error.message}`, {
        stdout: clipOutput(stdout),
        stderr: clipOutput(stderr),
      })));
    });
    child.on("close", (code) => {
      finish(() => {
        const parsed = parseBridgeJson(stdout);
        if (timedOut) {
          reject(new BridgeProcessError(`bridge timed out after ${timeoutMs}ms`, {
            timeout: true,
            code,
            stdout: clipOutput(stdout),
            stderr: clipOutput(stderr),
          }));
          return;
        }
        if (code !== 0) {
          if (parsed && typeof parsed.reply === "string" && parsed.reply.trim()) {
            resolve({
              ...parsed,
              ok: parsed.ok === true,
              bridge_error: {
                code,
                stdout: clipOutput(stdout),
                stderr: clipOutput(stderr),
              },
            });
            return;
          }
          reject(new BridgeProcessError(stderr.trim() || `bridge exited with code ${code}`, {
            code,
            stdout: clipOutput(stdout),
            stderr: clipOutput(stderr),
          }));
          return;
        }
        if (parsed) {
          resolve(parsed);
          return;
        }
        reject(new BridgeProcessError("invalid bridge output", {
          code,
          stdout: clipOutput(stdout),
          stderr: clipOutput(stderr),
        }));
      });
    });
    try {
      child.stdin.end(JSON.stringify(payload));
    } catch (error) {
      finish(() => reject(new BridgeProcessError(`bridge stdin failed: ${error instanceof Error ? error.message : String(error)}`, {
        stdout: clipOutput(stdout),
        stderr: clipOutput(stderr),
      })));
    }
  });
}

function normalizeTagRouterEntrypoint(value) {
  let text = String(value ?? "").replace(/[\u200B-\u200D\u2060\uFEFF]/g, "").trim();
  text = text.replace(/^\[message_id:[^\]\n]{1,160}\]\s*/i, "").trimStart();
  text = text.replace(/^[^\n:：]{1,80}[:：]\s*(?=【)/, "").trimStart();
  text = text.replace(/^\[[^\]\n]{8,80}\]\s*/, "").trimStart();
  const mentionBeforeTag = text.match(/^@[\s\S]{1,80}?(?=\s*【)/);
  if (mentionBeforeTag) text = text.slice(mentionBeforeTag[0].length).trimStart();
  return text;
}

export function isTagRouterEntrypoint(value) {
  const raw = String(value ?? "");
  if (/【\s*codex\s*】/i.test(raw)) return true;
  return /^【[^】\n]{1,40}】/.test(normalizeTagRouterEntrypoint(raw));
}

export function containsCodexTrigger(value) {
  return /【\s*codex\s*】/i.test(String(value ?? ""));
}

const MEDIA_WEB_URL = String(process.env.OPENCLAW_MEDIA_WEB_URL || "https://mediapilot.cloud/openclaw/media").trim();

export function isMediaFeishuAccount(value) {
  return String(value ?? "").trim().toLowerCase().replaceAll("_", "-").replace(/^feishu-/, "") === "media";
}

export function isDeepMathFeishuAccount(value) {
  return String(value ?? "").trim().toLowerCase().replaceAll("_", "-").replace(/^feishu-/, "") === "deepmath";
}

function deepMathAttachments(event) {
  const metadata = event?.metadata && typeof event.metadata === "object" ? event.metadata : {};
  const paths = Array.isArray(metadata.mediaPaths) ? metadata.mediaPaths : metadata.mediaPath ? [metadata.mediaPath] : [];
  const types = Array.isArray(metadata.mediaTypes) ? metadata.mediaTypes : metadata.mediaType ? [metadata.mediaType] : [];
  return paths.map((path, index) => ({
    local_path: String(path || "").trim(),
    mime_type: String(types[index] || types[0] || "application/octet-stream").trim(),
    file_name: String(metadata.mediaNames?.[index] || "").trim(),
  })).filter((item) => item.local_path).slice(0, 8);
}

function deepMathBlockedLabelReply() {
  return "[DEEPMATH_LABEL_BLOCKED] DeepMath 当前仅开放【思考】和【说明】入口；普通咨询请直接发送自然语言。";
}

let mediaExclusiveLabelsPromise;

async function loadMediaExclusiveLabels() {
  if (!mediaExclusiveLabelsPromise) {
    mediaExclusiveLabelsPromise = readFile(BOT_CENTER_DATA_PATH, "utf8").then((source) => {
      const payload = JSON.parse(source);
      const labels = new Set();
      for (const item of payload?.capabilities ?? []) {
        const visibleBots = Array.isArray(item?.visibleBots) ? item.visibleBots : [];
        if (item?.primaryBot !== "media" || visibleBots.length !== 1 || visibleBots[0] !== "media") continue;
        for (const alias of item?.aliases ?? []) {
          const label = String(alias ?? "").trim();
          if (label) labels.add(label);
        }
      }
      if (!labels.size) throw new Error("generated capability data contains no Media-exclusive labels");
      return labels;
    }).catch((error) => {
      mediaExclusiveLabelsPromise = undefined;
      throw error;
    });
  }
  return mediaExclusiveLabelsPromise;
}

function entrypointLabel(value) {
  const match = normalizeTagRouterEntrypoint(value).match(/^【([^】\n]{1,40})】/);
  return String(match?.[1] ?? "").trim();
}

function retiredMediaFeishuReply() {
  return `[MEDIA_FEISHU_COMMAND_RETIRED] Media 命令入口已迁移到 ${MEDIA_WEB_URL}。原因：Media Web 已成为唯一命令通道。详情：本条飞书消息未进入模型、tag-router 或附件队列。建议：请在 Media Web 中发起任务。`;
}

function bridgeReplyOrError(result) {
  const reply = typeof result?.reply === "string" ? result.reply.trim() : "";
  return reply || "[TAG_ROUTER_EMPTY_REPLY] 标签入口未生成可见结果。请稍后重试。";
}

function dispatchTranscriptionAction(action, event, context, transcriptionQueue, transcriptionJobQueue, logger) {
  if (!action || action.kind === "pass") return null;
  if (action.kind === "reply" || (!action.kind && typeof action.text === "string")) {
    return { handled: true, text: action.text };
  }
  if (action.kind === "already_enqueued") {
    return { handled: true, text: transcriptionJobQueue.reply(action.job_id) };
  }
  if (action.kind !== "enqueue") return null;
  try {
    const queued = transcriptionJobQueue.enqueue(action, event, context);
    transcriptionQueue.markEnqueued(action.scope, action.batch_id, queued.job.id);
    return { handled: true, text: queued.text };
  } catch (error) {
    logger?.error?.(
      `[openclaw-tag-router] asynchronous transcription enqueue failed: ${error instanceof Error ? error.message : String(error)}`,
    );
    return {
      handled: true,
      text: "[TRANSCRIPTION_JOB_ENQUEUE_FAILED] 转写任务未创建。原因：后台任务持久化失败。建议：请重新发送原录音或当前确认指令。",
    };
  }
}

export function createFeishuTagRouterBeforeDispatchHandler(
  config,
  {
    logger,
    bridgeRunner = runBridge,
    transcriptionQueue = createTranscriptionQueue({ ...config, logger }),
    transcriptionJobQueue = createTranscriptionJobQueue({ ...config, logger }),
    mediaExclusiveLabelsLoader = loadMediaExclusiveLabels,
  } = {},
) {
  return async (event, context) => {
    if (event?.channel !== "feishu") return;
    const accountId = String(event.accountId ?? context?.accountId ?? "").trim();
    if (isMediaFeishuAccount(accountId)) {
      logger?.info?.("[openclaw-tag-router] retired Media Feishu command blocked before dispatch");
      return { handled: true, text: retiredMediaFeishuReply() };
    }
    const isDeepMath = isDeepMathFeishuAccount(accountId);
    if (!isDeepMath) {
      const transcriptionIntake = transcriptionQueue.intake(event, context);
      const transcriptionIntakeResult = dispatchTranscriptionAction(
        transcriptionIntake,
        event,
        context,
        transcriptionQueue,
        transcriptionJobQueue,
        logger,
      );
      if (transcriptionIntakeResult) {
        logger?.info?.(`[openclaw-tag-router] transcription attachment handled before model dispatch account=${accountId || "unknown"}`);
        return transcriptionIntakeResult;
      }
    }
    if (!isTagRouterEntrypoint(event.content)) return;
    const label = entrypointLabel(event.content);
    const isCodex = containsCodexTrigger(event.content);
    if (isDeepMath && !isCodex && !["思考", "说明"].includes(label)) {
      logger?.info?.(`[openclaw-tag-router] DeepMath non-allowlisted label blocked label=${label || "unknown"}`);
      return { handled: true, text: deepMathBlockedLabelReply() };
    }
    const isDeepMathThinking = isDeepMath && label === "思考";
    if (!isDeepMath) try {
      const mediaExclusiveLabels = await mediaExclusiveLabelsLoader();
      if (mediaExclusiveLabels.has(entrypointLabel(event.content))) {
        logger?.info?.("[openclaw-tag-router] cross-account Media Feishu command blocked before dispatch");
        return { handled: true, text: retiredMediaFeishuReply() };
      }
    } catch (error) {
      logger?.error?.(`[openclaw-tag-router] capability channel policy unavailable: ${error instanceof Error ? error.message : String(error)}`);
      return {
        handled: true,
        text: "[MEDIA_CHANNEL_POLICY_UNAVAILABLE] 标签通道策略暂不可用。原因：能力目录读取失败。建议：请稍后重试；Media 任务请使用 Media Web。",
      };
    }

    const transcriptionAction = transcriptionQueue.prepare(event, context);
    const transcriptionResult = dispatchTranscriptionAction(
      transcriptionAction,
      event,
      context,
      transcriptionQueue,
      transcriptionJobQueue,
      logger,
    );
    if (transcriptionResult) return transcriptionResult;
    const routedText = String(event.content ?? "");
    const senderId = String(event.senderId ?? context?.senderId ?? "").trim();
    const payload = {
      text: routedText,
      source: "feishu",
      chat_type: event.isGroup === true ? "group" : "private",
      metadata: {
        ...(accountId ? { account_id: accountId } : {}),
        ...((event.messageId ?? context?.messageId) ? { source_message_id: String(event.messageId ?? context.messageId) } : {}),
        ...(senderId ? { source_sender_id: senderId } : {}),
        ...(context?.conversationId ? { source_conversation_id: String(context.conversationId) } : {}),
        ...(isDeepMathThinking ? { attachments: deepMathAttachments(event) } : {}),
        ...resolveFeishuGlobalAdminContext(config, senderId),
      },
    };

    try {
      const result = await bridgeRunner(config, "ingest", payload);
      logger?.info?.(
        `[openclaw-tag-router] Feishu tag-router handled before model dispatch account=${accountId || "unknown"} status=${String(result?.status || "unknown")}`,
      );
      return { handled: true, text: bridgeReplyOrError(result) };
    } catch (error) {
      logger?.error?.(
        `[openclaw-tag-router] Feishu tag-router before-dispatch failed account=${accountId || "unknown"}: ${error instanceof Error ? error.message : String(error)}`,
      );
      logger?.info?.(
        `[openclaw-tag-router] Feishu tag-router handled before model dispatch account=${accountId || "unknown"} status=bridge_error`,
      );
      if (error?.details?.timeout === true) {
        return {
          handled: true,
          text: "[TAG_ROUTER_TIMEOUT] 标签任务处理超过 270 秒，已停止本次执行，未继续写入。请稍后重试；若链接已失效，请重新从平台分享有效链接。",
        };
      }
      return {
        handled: true,
        text: "[TAG_ROUTER_UNAVAILABLE] 标签入口暂时不可用。请稍后重试。",
      };
    }
  };
}

function buildHandler(api) {
  return async (req, res) => {
    const config = resolvePluginConfig(api);
    if (!config.enabled) {
      json(res, 503, { ok: false, error: "plugin_disabled" });
      return true;
    }

    const url = new URL(req.url ?? "/", "http://localhost");
    const pathname = url.pathname;
    const suffix = pathname.slice(config.routeBase.length) || "/";

    if (req.method === "GET" && suffix === "/healthz") {
      json(res, 200, { ok: true, plugin: "openclaw-tag-router" });
      return true;
    }

    if (req.method === "GET" && suffix === "/readyz") {
      let settingsExists = false;
      try {
        await readFile(config.settingsPath, "utf8");
        settingsExists = true;
      } catch {
        settingsExists = false;
      }
      json(res, 200, {
        ok: true,
        plugin: "openclaw-tag-router",
        routeBase: config.routeBase,
        dataRoot: config.dataRoot,
        settingsPath: config.settingsPath,
        settingsExists,
        qqWebhookPath: config.qqWebhookPath,
        qqWebhookEnabled: Boolean(config.qqWebhookPath),
      });
      return true;
    }

    if (req.method !== "POST") {
      json(res, 405, { ok: false, error: "method_not_allowed" });
      return true;
    }

    try {
      const rawBody = await readJson(req);
      const payload = parseJsonBuffer(rawBody);
      if (suffix === "/ingest") {
        const result = await runBridge(config, "ingest", payload);
        json(res, 200, withModelLabel(api, result));
        return true;
      }
      if (suffix === "/qqbot/event") {
        const result = await runBridge(config, "qqbot", payload);
        json(res, 200, withModelLabel(api, result));
        return true;
      }
      json(res, 404, { ok: false, error: "not_found" });
      return true;
    } catch (error) {
      const statusCode = error instanceof BridgeProcessError ? error.statusCode : 500;
      const bridge = error instanceof BridgeProcessError ? error.details : undefined;
      json(res, statusCode, { ok: false, error: error instanceof Error ? error.message : String(error), ...(bridge ? { bridge } : {}) });
      return true;
    }
  };
}

function buildQQWebhookHandler(api) {
  return async (req, res) => {
    api.logger.info?.(`[openclaw-tag-router] qq webhook hit: ${req.method ?? "GET"} ${req.url ?? ""}`);
    const config = resolvePluginConfig(api);
    if (!config.enabled) {
      json(res, 503, { ok: false, error: "plugin_disabled" });
      return true;
    }

    if (req.method === "GET") {
      json(res, 200, {
        ok: true,
        plugin: "openclaw-tag-router",
        qqWebhookPath: config.qqWebhookPath,
        qqWebhookSecretConfigured: Boolean(config.qqWebhookSecret),
      });
      return true;
    }

    if (req.method !== "POST") {
      json(res, 405, { ok: false, error: "method_not_allowed" });
      return true;
    }

    try {
      const rawBody = await readJson(req);
      if (!verifyQQWebhookSecret(req, rawBody, config.qqWebhookSecret)) {
        json(res, 401, { ok: false, error: "invalid_webhook_secret" });
        return true;
      }
      const payload = parseJsonBuffer(rawBody);
      const result = await runBridge(config, "qqbot", payload);
      json(res, 200, withModelLabel(api, result));
      return true;
    } catch (error) {
      const statusCode = error instanceof BridgeProcessError ? error.statusCode : 500;
      const bridge = error instanceof BridgeProcessError ? error.details : undefined;
      json(res, statusCode, { ok: false, error: error instanceof Error ? error.message : String(error), ...(bridge ? { bridge } : {}) });
      return true;
    }
  };
}

export default {
  id: "openclaw-tag-router",
  name: "OpenClaw Tag Router",
  description: "Canonical tag ingress for non-Media Feishu channels and Web-owned Media runtime",
  configSchema: {
    type: "object",
    additionalProperties: false,
    properties: {
      enabled: { type: "boolean", default: true },
      routeBase: { type: "string", default: "/api/channels/openclaw-tag-router" },
      pythonBin: { type: "string", default: "python3" },
      dataRoot: { type: "string", default: "/home/ubuntu/.openclaw/workspace/openclaw-tag-router" },
      settingsPath: { type: "string", default: "/home/ubuntu/.openclaw/extensions/openclaw-tag-router/config/settings.yaml" },
      bridgeTimeoutMs: { type: "number", default: 270000 },
      qqWebhookPath: { type: "string", default: "" },
      qqWebhookSecret: { type: "string", default: "" },
    },
  },
  register(api) {
    const config = resolvePluginConfig(api);
    if (!config.enabled) return;
    const transcriptionQueue = createTranscriptionQueue({ ...config, logger: api.logger });
    const transcriptionJobQueue = createTranscriptionJobQueue({ ...config, logger: api.logger });
    api.on(
      "before_dispatch",
      createFeishuTagRouterBeforeDispatchHandler(
        config,
        { logger: api.logger, transcriptionQueue, transcriptionJobQueue },
      ),
      { priority: 1000 },
    );
    api.registerHttpRoute({
      path: config.routeBase,
      auth: "gateway",
      match: "prefix",
      handler: buildHandler(api),
    });
    api.logger.info?.(`[openclaw-tag-router] canonical non-Media Feishu attachment and tag-router before-dispatch hook registered; Media commands are Web-only`);
    api.logger.info?.(`[openclaw-tag-router] route registered at ${config.routeBase}`);
    if (config.qqWebhookPath) {
      api.registerHttpRoute({
        path: config.qqWebhookPath,
        auth: "plugin",
        match: "exact",
        handler: buildQQWebhookHandler(api),
      });
      api.logger.info?.(`[openclaw-tag-router] qq webhook registered at ${config.qqWebhookPath}`);
    }
  },
};
