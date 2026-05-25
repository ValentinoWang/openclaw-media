import { spawn } from "node:child_process";
import { createHmac, timingSafeEqual } from "node:crypto";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const BRIDGE_PATH = join(__dirname, "bridge.py");

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

function normalizeExactPath(value, fallback) {
  const trimmed = String(value || "").trim();
  if (!trimmed) return fallback;
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
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
    qqWebhookPath: String(pluginConfig.qqWebhookPath || "").trim()
      ? normalizeExactPath(pluginConfig.qqWebhookPath, "")
      : "",
    qqWebhookSecret: String(pluginConfig.qqWebhookSecret || ""),
  };
}

function runBridge(config, mode, payload) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      config.pythonBin,
      [BRIDGE_PATH, mode, config.dataRoot, config.settingsPath],
      { stdio: ["pipe", "pipe", "pipe"] },
    );
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(stderr.trim() || `bridge exited with code ${code}`));
        return;
      }
      try {
        resolve(JSON.parse(stdout || "{}"));
      } catch (error) {
        reject(new Error(`invalid bridge output: ${error instanceof Error ? error.message : String(error)}`));
      }
    });
    child.stdin.end(JSON.stringify(payload));
  });
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
        legacyWebhookPath: config.qqWebhookPath,
        legacyWebhookEnabled: Boolean(config.qqWebhookPath),
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
        json(res, 200, result);
        return true;
      }
      if (suffix === "/qqbot/event") {
        const result = await runBridge(config, "qqbot", payload);
        json(res, 200, result);
        return true;
      }
      json(res, 404, { ok: false, error: "not_found" });
      return true;
    } catch (error) {
      json(res, 500, { ok: false, error: error instanceof Error ? error.message : String(error) });
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
      json(res, 200, result);
      return true;
    } catch (error) {
      json(res, 500, { ok: false, error: error instanceof Error ? error.message : String(error) });
      return true;
    }
  };
}

export default {
  id: "openclaw-tag-router",
  name: "OpenClaw Tag Router",
  description: "Tag-driven ingest bridge for Feishu messages",
  configSchema: {
    type: "object",
    additionalProperties: false,
    properties: {
      enabled: { type: "boolean", default: true },
      routeBase: { type: "string", default: "/api/channels/openclaw-tag-router" },
      pythonBin: { type: "string", default: "python3" },
      dataRoot: { type: "string", default: "/home/ubuntu/.openclaw/workspace/openclaw-tag-router" },
      settingsPath: { type: "string", default: "/home/ubuntu/.openclaw/extensions/openclaw-tag-router/config/settings.yaml" },
      qqWebhookPath: { type: "string", default: "" },
      qqWebhookSecret: { type: "string", default: "" },
    },
  },
  register(api) {
    const config = resolvePluginConfig(api);
    if (!config.enabled) return;
    api.registerHttpRoute({
      path: config.routeBase,
      auth: "gateway",
      match: "prefix",
      handler: buildHandler(api),
    });
    api.logger.info?.(`[openclaw-tag-router] route registered at ${config.routeBase}`);
    if (config.qqWebhookPath) {
      api.registerHttpRoute({
        path: config.qqWebhookPath,
        auth: "plugin",
        match: "exact",
        handler: buildQQWebhookHandler(api),
      });
      api.logger.info?.(`[openclaw-tag-router] legacy webhook registered at ${config.qqWebhookPath}`);
    }
  },
};
