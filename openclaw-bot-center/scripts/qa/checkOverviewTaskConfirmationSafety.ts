import { chromium, type Page, type Route } from "playwright";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const baseUrl = (
  process.env.OVERVIEW_CONFIRMATION_QA_URL ??
  "http://127.0.0.1:5188/openclaw/media/index.media.html"
).replace(/\/$/, "");
const outputDir = process.env.OVERVIEW_CONFIRMATION_QA_OUTPUT_DIR?.trim();

const session = {
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
    csrfToken: "overview-confirmation-qa-csrf",
    expiresAt: "2099-01-01T00:00:00Z",
    schemaVersion: "media_web_business_pages_v2",
  },
};

const field = (key: string, label: string, options: string[] = []) => ({
  key,
  sourceLabel: label,
  label,
  inputType: options.length ? "select" : "text",
  valueType: "string",
  format: { name: "", min: null, max: null, pattern: "", urlSchemes: [] },
  required: false,
  defaultValue: null,
  options: options.map((value) => ({ value, label: value, aliases: [], source: "qa" })),
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
  catalogVersion: `sha256:${"b".repeat(64)}`,
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

const deletionTask = {
  schemaVersion: "media_web_task_v3",
  taskId: "mwt_overview_confirmation_0001",
  requestId: "mreq_overview_confirmation_0001",
  modelCalls: [],
  capabilityId: "universal_deletion",
  capabilityPath: ["内容治理", "通用删除"],
  variantId: "confirm",
  params: { id: "asset_item_20260620_cff58f08", action: "确认删除" },
  confirmationReceipt: {
    kind: "deletion_preview",
    previewTaskId: "mwt_overview_preview_0001",
    targetIds: ["asset_item_20260620_cff58f08"],
    targetCount: 1,
    entityCount: 3,
    planDigest: `sha256:${"a".repeat(64)}`,
    expiresAt: "2099-01-01T00:00:00Z",
  },
  status: "awaiting_confirmation",
  terminal: false,
  progress: 0,
  summary: "目标ID：asset_item_20260620_cff58f08 动作：确认删除",
  createdAt: "2026-08-09T03:16:09Z",
  updatedAt: "2026-08-09T03:16:09Z",
  confirmation: {
    state: "required",
    required: true,
    note: "",
    decidedAt: "",
  },
  result: null,
  error: null,
  eventCursor: 1,
};

async function fulfill(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function installApi(page: Page, mutations: string[]) {
  await page.route("**/openclaw/media/api/**", async (route) => {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const apiPath = requestUrl.pathname.replace(/^\/openclaw\/media\/api/, "");
    if (request.method() !== "GET") mutations.push(`${request.method()} ${apiPath}`);
    if (apiPath === "/session") return fulfill(route, session);
    if (apiPath === "/capabilities") {
      return fulfill(route, catalog);
    }
    if (apiPath === "/dashboard") {
      return fulfill(route, {
        schemaVersion: "media_web_business_pages_v2",
        revision: 1,
        summary: {
          counts: {
            contentProjects: 0,
            runs: 0,
            assets: 1,
            tracks: 0,
            creators: 0,
            publishedPosts: 0,
            reviews: 0,
          },
          contentProjectStages: [],
          pendingDecisions: 0,
          pendingPublishing: 0,
          pendingReviews: 0,
          taskSummary: { queued: 0, running: 0, needsAttention: 1, failed: 0 },
          coverage: { known: 1, unknown: 0, unavailable: 0 },
          generatedAt: "2026-08-09T03:16:09Z",
          revision: 1,
        },
      });
    }
    if (apiPath === "/content-projects") {
      return fulfill(route, {
        schemaVersion: "media_web_business_pages_v2",
        revision: 1,
        items: [],
        nextCursor: null,
      });
    }
    if (apiPath === "/tasks") {
      return fulfill(route, {
        schemaVersion: "media_web_task_v3",
        revision: 1,
        items: [deletionTask],
        tasks: [deletionTask],
        nextCursor: null,
      });
    }
    return fulfill(
      route,
      { error: { code: "unexpected_qa_request", message: `${request.method()} ${apiPath}` } },
      500,
    );
  });
}

function requireCondition(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const mutations: string[] = [];
const pageErrors: string[] = [];
page.on("pageerror", (error) => pageErrors.push(error.message));

try {
  await installApi(page, mutations);
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "运营总览" }).waitFor({ timeout: 10_000 });

  const card = page.locator('[data-confirmation-kind="deletion_preview"]');
  await card.getByText("删除素材资产", { exact: true }).waitFor();
  await card.getByText("等待确认", { exact: true }).waitFor();
  await card.getByText("1 个删除目标，涉及 3 项数据", { exact: true }).waitFor();
  await card.getByText("asset_item_20260620_cff58f08", { exact: true }).waitFor();
  requireCondition(
    (await card.getByRole("button", { name: "查看影响并确认" }).count()) === 1,
    "the destructive task must route to a review surface",
  );
  requireCondition(
    (await card.getByRole("button", { name: "确认执行" }).count()) === 0,
    "the Overview card must not execute a destructive task inline",
  );
  requireCondition(
    (await card.locator("input").count()) === 0,
    "the Overview card must not render a prefilled confirmation reason",
  );

  const desktopGeometry = await card.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    let visibleTop = rect.top;
    let visibleBottom = rect.bottom;
    let ancestor = element.parentElement;
    while (ancestor) {
      const style = getComputedStyle(ancestor);
      if (["auto", "scroll", "hidden", "clip"].includes(style.overflowY)) {
        const ancestorRect = ancestor.getBoundingClientRect();
        visibleTop = Math.max(visibleTop, ancestorRect.top);
        visibleBottom = Math.min(visibleBottom, ancestorRect.bottom);
      }
      ancestor = ancestor.parentElement;
    }
    return {
      left: rect.left,
      right: rect.right,
      height: rect.height,
      visibleHeight: Math.max(0, visibleBottom - visibleTop),
      viewport: document.documentElement.clientWidth,
    };
  });
  requireCondition(
    desktopGeometry.left >= 0 && desktopGeometry.right <= desktopGeometry.viewport + 0.5,
    "the confirmation card must remain inside the desktop viewport",
  );
  requireCondition(
    desktopGeometry.height >= 140 && desktopGeometry.height <= 300,
    `the desktop confirmation card must show its complete content without stretching, received ${desktopGeometry.height}px`,
  );
  requireCondition(
    desktopGeometry.visibleHeight >= desktopGeometry.height - 1,
    `the desktop confirmation card must not be clipped by an ancestor, visible ${desktopGeometry.visibleHeight}px of ${desktopGeometry.height}px`,
  );

  if (outputDir) {
    await mkdir(outputDir, { recursive: true });
    await card.screenshot({ path: path.join(outputDir, "confirmation-card-desktop.png") });
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await card.scrollIntoViewIfNeeded();
  const mobileGeometry = await card.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return {
      left: rect.left,
      right: rect.right,
      height: rect.height,
      viewport: document.documentElement.clientWidth,
    };
  });
  requireCondition(
    mobileGeometry.left >= 0 && mobileGeometry.right <= mobileGeometry.viewport + 0.5,
    "the confirmation card must remain inside the mobile viewport",
  );
  requireCondition(
    mobileGeometry.height >= 180 && mobileGeometry.height <= 320,
    `the mobile confirmation card must stay compact and complete, received ${mobileGeometry.height}px`,
  );
  if (outputDir) {
    await card.screenshot({ path: path.join(outputDir, "confirmation-card-mobile.png") });
  }

  await card.getByRole("button", { name: "查看影响并确认" }).click();
  const drawer = page.getByRole("complementary", { name: "Media 任务工作区" });
  await drawer.waitFor({ state: "visible" });
  const confirmationItem = drawer.locator(
    '[data-task-id="mwt_overview_confirmation_0001"]',
  );
  await confirmationItem.getByText("删除影响", { exact: true }).waitFor();
  await confirmationItem.getByText("1 个删除目标，涉及 3 项数据", { exact: true }).waitFor();
  await confirmationItem.getByText("asset_item_20260620_cff58f08", { exact: true }).waitFor();
  requireCondition(
    (await confirmationItem.getByRole("button", { name: "取消删除" }).count()) === 1,
    "the review surface must expose the user's cancellation action",
  );
  requireCondition(
    (await confirmationItem.getByRole("button", { name: "确认删除" }).count()) === 1,
    "the review surface must name the destructive approval action",
  );
  requireCondition(
    await confirmationItem.evaluate((element) => document.activeElement === element),
    "opening confirmation detail must focus the requested task",
  );
  requireCondition(
    mutations.length === 0,
    `opening confirmation detail must not mutate state: ${mutations.join(" | ")}`,
  );
  requireCondition(pageErrors.length === 0, `page errors: ${pageErrors.join(" | ")}`);
} finally {
  await browser.close();
}

console.log("Overview task confirmation safety QA passed.");
