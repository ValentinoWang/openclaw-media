import assert from "node:assert/strict";
import { mkdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, type Page, type Route } from "playwright";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";

const mediaBase = "/openclaw/media";
const apiRoot = mediaBase + "/api";
const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const outputRoot =
  process.env.TASK_DELETE_QA_OUTPUT ??
  "/tmp/openclaw-media-task-delete-recovery";
const externalOrigin =
  process.env.TASK_DELETE_QA_BASE_URL?.trim().replace(/\/$/, "") ?? "";
const targetId = "asset_item_qa_delete_recovery_0001";
const planDigest = `sha256:${"a".repeat(64)}`;
const catalogVersion = `sha256:${"b".repeat(64)}`;

const field = (key: string, label: string, options: string[] = []) => ({
  key,
  sourceLabel: label,
  label,
  inputType: options.length ? "select" : "text",
  valueType: "string",
  format: { name: "", min: null, max: null, pattern: "", urlSchemes: [] },
  required: false,
  defaultValue: null,
  options: options.map((value) => ({
    value,
    label: value,
    aliases: [],
    source: "qa",
  })),
  placeholder: "",
  helpText: "",
  order: key === "id" ? 1 : 2,
  visibleWhen: [],
  enabledWhen: [],
  semanticOwner: "universal_deletion",
  persistenceOwner: "media_web_tasks",
  provenance: "declared_field_definition",
});

const catalog = {
  schemaVersion: "capability_catalog_v3",
  catalogVersion,
  capabilities: [
    {
      capabilityId: "universal_deletion",
      internalCode: "universal_deletion",
      internalLabel: "内容产物删除",
      label: "内容产物删除",
      displayName: "内容产物删除",
      description: "先预览影响范围，再确认删除。",
      example: "",
      aliases: [],
      bots: ["Media bot"],
      hierarchy: {
        categoryId: "governance",
        categoryName: "治理",
        categoryOrder: 1,
        objectId: "content_asset",
        objectName: "内容产物",
        objectOrder: 1,
        actionId: "delete",
        actionName: "删除",
        actionOrder: 1,
        pathIds: ["governance", "content_asset", "delete"],
        pathNames: ["治理", "内容产物", "删除"],
      },
      fields: [field("id", "目标ID"), field("action", "动作", ["确认删除"])],
      variants: [
        {
          variantId: "preview",
          label: "生成删除预览",
          requiredFields: ["id"],
          requiredAnyOf: [],
          preActions: [],
          controlledInputFields: [],
          forbiddenFields: ["action"],
          fieldValues: {},
        },
        {
          variantId: "confirm",
          label: "确认删除",
          requiredFields: ["id", "action"],
          requiredAnyOf: [],
          preActions: [],
          controlledInputFields: [],
          forbiddenFields: [],
          fieldValues: { action: ["确认删除"] },
        },
      ],
      validationRules: [],
      supportedAttachments: [],
      attachmentPolicy: { types: [], maxCount: 0, maxBytes: 0 },
      status: "implemented",
      enabled: true,
      visibility: "public",
      riskLevel: "destructive",
      effect: "destructive",
      confirmationPolicy: {
        stage: "destructive_preview_apply",
        message: "确认删除",
      },
      handler: "handle_universal_deletion",
      consumes: ["target_id"],
      produces: ["deletion_result"],
      writesTo: ["target"],
      sourceSystem: "media",
      ssotRefs: [],
      inputContractSource: "qa",
      searchKeywords: ["删除"],
      provenance: "qa_fixture",
      displayOrder: 1,
      requiresConfirmation: true,
    },
  ],
};

const receipt = {
  kind: "deletion_preview",
  previewTaskId: "preview_task_20260809",
  targetIds: [targetId],
  targetCount: 1,
  entityCount: 1,
  planDigest,
  expiresAt: "2026-08-10T00:00:00.000Z",
};

function task(overrides: Record<string, unknown> = {}) {
  return {
    schemaVersion: "media_web_task_v3",
    taskId: "task_delete_preview_20260809",
    requestId: "request_delete_preview_20260809",
    modelCalls: [],
    capabilityId: "universal_deletion",
    capabilityPath: ["治理", "内容产物", "删除"],
    variantId: "preview",
    params: { id: targetId },
    status: "succeeded",
    settlementStage: "submitted",
    terminal: true,
    progress: 100,
    summary: "删除预览已完成",
    createdAt: "2026-08-09T02:22:25+08:00",
    updatedAt: "2026-08-09T02:22:26+08:00",
    confirmationReceipt: null,
    confirmation: {
      state: "not_required",
      required: false,
      note: "",
      decidedAt: "",
    },
    result: {
      ok: true,
      status: "completed",
      reply: "影响范围已生成",
      links: [],
      receipt,
    },
    error: null,
    eventCursor: 1,
    accountBinding: null,
    attempt: null,
    readbacks: {},
    missingReadbacks: [],
    receipt: null,
    ...overrides,
  };
}

async function json(route: Route, status: number, body: unknown) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function installApi(page: Page) {
  const submissions: Array<{ key: string; body: Record<string, unknown> }> = [];
  let confirmations = 0;
  let taskReads = 0;
  await page.route(`**${apiRoot}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.slice(apiRoot.length);
    if (path === "/session") {
      return json(route, 200, {
        schemaVersion: "media_web_business_pages_v2",
        revision: 1,
        session: {
          publicUserId: "11111111-1111-4111-8111-111111111111",
          tenantId: "22222222-2222-4222-8222-222222222222",
          organizationName: null,
          workspaceMode: "personal_web",
          editorMode: "web_edit",
          bodyAuthority: "internal",
          memberRole: "owner",
          organizationConnection: "not_applicable",
          installationConnection: "not_applicable",
          role: "ordinary",
          maintainer: false,
          csrfToken: "task-delete-qa-csrf",
          expiresAt: "2026-08-10T00:00:00+00:00",
          schemaVersion: "media_web_business_pages_v2",
        },
      });
    }
    if (path === "/capabilities") return json(route, 200, catalog);
    if (path === "/tasks" && request.method() === "GET") {
      return json(route, 200, { tasks: [task()] });
    }
    if (path === "/tasks" && request.method() === "POST") {
      const body = request.postDataJSON() as Record<string, unknown>;
      submissions.push({
        key: request.headers()["idempotency-key"] ?? "",
        body,
      });
      if (submissions.length === 1) {
        return json(route, 409, {
          error: {
            code: "idempotency_conflict",
            message: "幂等键已绑定其他任务请求。",
          },
        });
      }
      return json(
        route,
        202,
        task({
          taskId: "task_delete_confirm_20260809",
          requestId: "request_delete_confirm_20260809",
          variantId: "confirm",
          params: body.params,
          status: "awaiting_confirmation",
          terminal: false,
          progress: 0,
          summary: "删除请求等待确认",
          confirmationReceipt: receipt,
          confirmation: {
            state: "required",
            required: true,
            note: "",
            decidedAt: "",
          },
          result: null,
          createdAt: "2026-08-09T03:00:00+08:00",
          updatedAt: "2026-08-09T03:00:00+08:00",
        }),
      );
    }
    if (
      path === "/tasks/task_delete_confirm_20260809/confirm" &&
      request.method() === "POST"
    ) {
      confirmations += 1;
      assert.equal(request.postDataJSON().decision, "approve");
      return json(
        route,
        200,
        task({
          taskId: "task_delete_confirm_20260809",
          requestId: "request_delete_confirm_20260809",
          variantId: "confirm",
          params: { id: targetId, action: "确认删除" },
          status: "queued",
          terminal: false,
          progress: 0,
          summary: "删除任务已进入执行队列",
          confirmationReceipt: receipt,
          confirmation: {
            state: "approved",
            required: true,
            note: "",
            decidedAt: "2026-08-09T03:00:01+08:00",
          },
          result: null,
          createdAt: "2026-08-09T03:00:00+08:00",
          updatedAt: "2026-08-09T03:00:01+08:00",
          eventCursor: 2,
        }),
      );
    }
    if (path === "/tasks/task_delete_confirm_20260809/events") {
      await new Promise((resolve) => setTimeout(resolve, 400));
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        headers: { "Cache-Control": "no-cache" },
        body: "event: task.result\ndata: {}\n\n",
      });
    }
    if (
      path === "/tasks/task_delete_confirm_20260809" &&
      request.method() === "GET"
    ) {
      taskReads += 1;
      return json(
        route,
        200,
        task({
          taskId: "task_delete_confirm_20260809",
          requestId: "request_delete_confirm_20260809",
          variantId: "confirm",
          params: { id: targetId, action: "确认删除" },
          status: "succeeded",
          terminal: true,
          progress: 100,
          summary: "删除已完成",
          confirmationReceipt: receipt,
          confirmation: {
            state: "approved",
            required: true,
            note: "",
            decidedAt: "2026-08-09T03:00:01+08:00",
          },
          result: {
            ok: true,
            status: "completed",
            reply: "目标及其关联数据已删除。",
            links: [],
            receipt: null,
          },
          createdAt: "2026-08-09T03:00:00+08:00",
          updatedAt: "2026-08-09T03:00:02+08:00",
          eventCursor: 3,
        }),
      );
    }
    return json(route, 503, {
      error: { code: "qa_unavailable", message: "QA fixture" },
    });
  });
  return {
    submissions,
    confirmationCount: () => confirmations,
    taskReadCount: () => taskReads,
  };
}

async function capture(
  origin: string,
  viewport: { width: number; height: number },
  label: string,
) {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const api = await installApi(page);
  try {
    await page.goto(`${origin}${mediaBase}/overview`, {
      waitUntil: "domcontentloaded",
    });
    await page.locator(".media-shell").waitFor();
    const launchButton = page.locator(".topbar-command");
    await launchButton.waitFor({ state: "visible" });
    await launchButton.click();
    const drawer = page.getByRole("complementary", {
      name: "Media 任务工作区",
    });
    await drawer.waitFor();
    const technicalPreview = drawer.locator(
      '[data-task-id="task_delete_preview_20260809"]',
    );
    assert.equal(
      await technicalPreview.count(),
      0,
      "technical deletion previews must not appear in the user task feed",
    );
    assert.equal(
      await drawer.getByText("删除预览", { exact: true }).count(),
      0,
    );
    assert.equal(
      await drawer.getByText(targetId, { exact: true }).count(),
      0,
    );
    await drawer.getByText("尚未提交网页任务", { exact: true }).waitFor();
    await page.screenshot({
      path: join(outputRoot, `hidden-technical-preview-${label}.png`),
      fullPage: false,
    });
    const overflow = await page.evaluate(() => ({
      document:
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
      body: document.body.scrollWidth - document.body.clientWidth,
    }));
    assert.ok(
      overflow.document <= 1 && overflow.body <= 1,
      `${label} overflow: ${JSON.stringify(overflow)}`,
    );
    assert.equal(api.submissions.length, 0);
    assert.equal(api.confirmationCount(), 0);
    assert.equal(api.taskReadCount(), 0);
    return {
      label,
      technicalPreviewVisible: false,
      mutations: 0,
      overflow,
    };
  } finally {
    await context.close();
    await browser.close();
  }
}

async function main() {
  mkdirSync(outputRoot, { recursive: true });
  if (externalOrigin) {
    const url = new URL(externalOrigin);
    assert.ok(
      url.protocol === "http:" || url.protocol === "https:",
      "TASK_DELETE_QA_BASE_URL must use http or https",
    );
    const results = [];
    results.push(
      await capture(
        url.origin,
        { width: 1440, height: 1000 },
        "deployed-desktop",
      ),
    );
    results.push(
      await capture(url.origin, { width: 390, height: 844 }, "deployed-mobile"),
    );
    console.log(
      JSON.stringify(
        { ok: true, target: url.origin, outputRoot, results },
        null,
        2,
      ),
    );
    return;
  }
  const server = await createServer({
    root: projectRoot,
    configFile: false,
    base: mediaBase + "/",
    publicDir: false,
    appType: "spa",
    plugins: [
      react(),
      {
        name: "task-delete-real-media-index",
        configureServer(viteServer) {
          viteServer.middlewares.use(async (request, response, next) => {
            if (!request.headers.accept?.includes("text/html")) return next();
            try {
              const html = readFileSync(
                join(projectRoot, "index.media.html"),
                "utf8",
              );
              response.statusCode = 200;
              response.setHeader("Content-Type", "text/html");
              response.end(
                await viteServer.transformIndexHtml(
                  request.url ?? mediaBase,
                  html,
                ),
              );
            } catch (error) {
              next(error as Error);
            }
          });
        },
      },
    ],
    server: { host: "127.0.0.1", port: 0, strictPort: false },
  });
  await server.listen();
  try {
    const address = server.httpServer?.address();
    assert.ok(
      address && typeof address !== "string",
      "Vite QA server did not expose a TCP port",
    );
    const origin = `http://127.0.0.1:${address.port}`;
    const results = [];
    results.push(
      await capture(origin, { width: 1440, height: 1000 }, "desktop"),
    );
    results.push(await capture(origin, { width: 390, height: 844 }, "mobile"));
    console.log(JSON.stringify({ ok: true, outputRoot, results }, null, 2));
  } finally {
    await server.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
