import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, type Locator, type Page, type Route } from "playwright";
import react from "@vitejs/plugin-react";
import { createServer } from "vite";

const mediaBase = "/openclaw/media";
const apiRoot = `${mediaBase}/api`;
const billingPath = `${mediaBase}/admin/billing`;
const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const outputRoot = resolve(
  process.env.ADMIN_BILLING_VISUAL_QA_OUTPUT ??
    "/tmp/openclaw-admin-billing-visual-runtime",
);

const viewports = [
  { width: 1440, height: 1000 },
  { width: 1280, height: 900 },
  { width: 1024, height: 768 },
  { width: 390, height: 844 },
] as const;

const adminSession = {
  publicUserId: "11111111-1111-4111-8111-111111111111",
  organizationName: null,
  memberRole: "owner" as const,
  organizationConnection: "not_applicable" as const,
  installationConnection: "not_applicable" as const,
  workspaceMode: "personal_web" as const,
  editorMode: "web_edit" as const,
  bodyAuthority: "internal" as const,
  role: "admin" as const,
  maintainer: true,
  routeGrants: ["/admin/overview", "/admin/access", "/admin/tenants", "/admin/billing", "/admin/upstreams"],
  csrfToken: "admin-billing-visual-runtime-csrf",
  expiresAt: "2099-01-01T00:00:00+00:00",
  schemaVersion: "media_web_business_pages_v2" as const,
};

const billingSummary = {
  schemaVersion: "media_web_business_pages_v2" as const,
  revision: 42,
  summary: {
    plans: [
      {
        planCode: "creator-pro",
        name: "创作专业版",
        status: "active",
        textQuota: 120_000,
        imageQuota: 600,
        price: "299.00",
        currency: "CNY",
      },
      {
        planCode: "creator-starter",
        name: "创作基础版",
        status: "active",
        textQuota: 30_000,
        imageQuota: 100,
        price: "99.00",
        currency: "CNY",
      },
    ],
    productMappings: [
      {
        mappingId: "mapping_creator_pro",
        planCode: "creator-pro",
        externalProductId: "liandong_creator_pro_2026",
        purchaseUrl: "https://shop.lian-dong.cn/buy/creator-pro",
        status: "active",
        createdAt: "2026-08-30T08:30:00+08:00",
      },
    ],
    redemptionBatches: [
      {
        batchId: "batch_creator_pro_20260830",
        planCode: "creator-pro",
        status: "active",
        codeCount: 100,
        redeemedCount: 36,
        createdAt: "2026-08-30T09:00:00+08:00",
      },
    ],
    fulfillments: [
      {
        fulfillmentId: "fulfillment_20260830_001",
        publicTenantId: "tenant_public_20260830",
        planCode: "creator-pro",
        creditedAmount: "299.00000000",
        status: "completed",
        createdAt: "2026-08-30T10:00:00+08:00",
      },
    ],
    grants: [
      {
        ledgerEntryId: "ledger_grant_20260830_001",
        publicTenantId: "tenant_public_20260830",
        username: "billing-operator@example.test",
        amount: "50.00000000",
        reason: "运行时视觉验收固定数据",
        createdAt: "2026-08-30T11:00:00+08:00",
      },
    ],
    ledgerRevision: 42,
  },
};

type Viewport = (typeof viewports)[number];

type RuntimeResult = {
  label: string;
  viewport: Viewport;
  requests: string[];
  fontRequests: string[];
  screenshot: string;
  layout: {
    documentWidth: number;
    viewportWidth: number;
    primary: { left: number; right: number; top: number; bottom: number };
    inspector: { left: number; right: number; top: number; bottom: number };
  };
};

async function fulfill(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function apiPath(url: string): string {
  return new URL(url).pathname.replace(apiRoot, "") || "/";
}

async function installApi(page: Page, requests: string[]): Promise<void> {
  await page.route(`**${apiRoot}/**`, async (route) => {
    const request = route.request();
    const path = apiPath(request.url());
    requests.push(`${request.method()} ${path}`);
    if (request.method() !== "GET") {
      await fulfill(
        route,
        {
          error: {
            code: "unexpected_write",
            message: `${request.method()} ${path}`,
          },
        },
        500,
      );
      return;
    }
    if (path === "/session") {
      await fulfill(route, {
        schemaVersion: "media_web_business_pages_v2",
        revision: 1,
        session: adminSession,
      });
      return;
    }
    if (path === "/admin/billing/summary") {
      await fulfill(route, billingSummary);
      return;
    }
    await fulfill(
      route,
      {
        error: {
          code: "unexpected_qa_request",
          message: `${request.method()} ${path}`,
        },
      },
      500,
    );
  });
}

async function measureLayout(page: Page, label: string): Promise<RuntimeResult["layout"]> {
  return page.evaluate((runtimeLabel) => {
    const viewportWidth = document.documentElement.clientWidth;
    const documentWidth = document.documentElement.scrollWidth;
    if (documentWidth > viewportWidth + 1) {
      throw new Error(`${runtimeLabel}: document overflow ${documentWidth} > ${viewportWidth}`);
    }
    const requiredSelectors = [
      ".media-shell",
      ".media-topbar",
      ".media-content",
      '[data-page-ownership="governance"]',
      '[data-page-layout="persistent-rail"]',
      "[data-page-primary]",
      "[data-page-inspector]",
    ];
    for (const selector of requiredSelectors) {
      const element = document.querySelector<HTMLElement>(selector);
      if (!element) throw new Error(`${runtimeLabel}: missing ${selector}`);
      const rect = element.getBoundingClientRect();
      if (rect.left < -1 || rect.right > viewportWidth + 1) {
        throw new Error(
          `${runtimeLabel}: ${selector} outside viewport (${rect.left}, ${rect.right}, ${viewportWidth})`,
        );
      }
    }
    const primary = document.querySelector<HTMLElement>("[data-page-primary]");
    const inspector = document.querySelector<HTMLElement>("[data-page-inspector]");
    if (!primary || !inspector) throw new Error(`${runtimeLabel}: persistent rail surfaces missing`);
    const primaryRect = primary.getBoundingClientRect();
    const inspectorRect = inspector.getBoundingClientRect();
    if (
      primaryRect.width <= 0 ||
      primaryRect.height <= 0 ||
      inspectorRect.width <= 0 ||
      inspectorRect.height <= 0
    ) {
      throw new Error(`${runtimeLabel}: persistent rail surface has no visible area`);
    }
    if (viewportWidth >= 1200) {
      if (primaryRect.right > inspectorRect.left + 1 || primaryRect.left >= inspectorRect.left) {
        throw new Error(
          `${runtimeLabel}: desktop persistent rail is not left/right (${primaryRect.left}, ${primaryRect.right}; ${inspectorRect.left}, ${inspectorRect.right})`,
        );
      }
      if (Math.abs(primaryRect.top - inspectorRect.top) > 1) {
        throw new Error(
          `${runtimeLabel}: desktop persistent rail tops differ (${primaryRect.top}, ${inspectorRect.top})`,
        );
      }
    } else if (primaryRect.bottom > inspectorRect.top + 1) {
      throw new Error(
        `${runtimeLabel}: stacked persistent rail overlaps (${primaryRect.bottom}, ${inspectorRect.top})`,
      );
    }
    return {
      documentWidth,
      viewportWidth,
      primary: {
        left: primaryRect.left,
        right: primaryRect.right,
        top: primaryRect.top,
        bottom: primaryRect.bottom,
      },
      inspector: {
        left: inspectorRect.left,
        right: inspectorRect.right,
        top: inspectorRect.top,
        bottom: inspectorRect.bottom,
      },
    };
  }, label);
}

async function assertActiveTabContract(
  page: Page,
  tablist: Locator,
  expectedName: string,
  label: string,
): Promise<Locator> {
  const selectedTabs = tablist.locator('[role="tab"][aria-selected="true"]');
  assert.equal(await selectedTabs.count(), 1, `${label}: tablist must expose one selected tab`);
  const selectedTab = selectedTabs.first();
  assert.equal(
    (await selectedTab.getAttribute("aria-label")) ?? (await selectedTab.textContent())?.trim(),
    expectedName,
    `${label}: unexpected active tab`,
  );
  assert.equal(await selectedTab.getAttribute("tabindex"), "0", `${label}: active tab is not tabbable`);
  assert.equal(
    await tablist.locator('[role="tab"]:not([aria-selected="true"])').evaluateAll((elements) =>
      elements.every((element) => element.getAttribute("tabindex") === "-1"),
    ),
    true,
    `${label}: inactive tabs must be removed from the tab sequence`,
  );

  const tabId = await selectedTab.getAttribute("id");
  const panelId = await selectedTab.getAttribute("aria-controls");
  assert.ok(tabId, `${label}: active tab is missing a stable id`);
  assert.ok(panelId, `${label}: active tab is missing aria-controls`);
  const panel = page.locator(`#${panelId}`);
  await panel.waitFor({ state: "visible" });
  assert.equal(await panel.getAttribute("role"), "tabpanel", `${label}: controlled element is not a tabpanel`);
  assert.equal(
    await panel.getAttribute("aria-labelledby"),
    tabId,
    `${label}: tabpanel does not point back to its active tab`,
  );
  return selectedTab;
}

async function assertTablistIdentifiers(page: Page, tablist: Locator, label: string): Promise<void> {
  const descriptors = await tablist.getByRole("tab").evaluateAll((tabs) =>
    tabs.map((tab) => ({
      id: tab.id,
      controls: tab.getAttribute("aria-controls"),
      selected: tab.getAttribute("aria-selected") === "true",
    })),
  );
  assert.equal(
    descriptors.every(({ id, controls }) => Boolean(id && controls)),
    true,
    `${label}: every tab must have an id and aria-controls`,
  );
  assert.equal(new Set(descriptors.map(({ id }) => id)).size, descriptors.length, `${label}: duplicate tab ids`);
  assert.equal(
    new Set(descriptors.map(({ controls }) => controls)).size,
    descriptors.length,
    `${label}: duplicate aria-controls targets`,
  );
  for (const descriptor of descriptors) {
    assert.ok(descriptor.id && descriptor.controls, `${label}: incomplete tab descriptor`);
    const panel = page.locator(`#${descriptor.controls}`);
    assert.equal(await panel.count(), 1, `${label}: ${descriptor.controls} must resolve to one tabpanel`);
    assert.equal(await panel.getAttribute("role"), "tabpanel", `${label}: ${descriptor.controls} is not a tabpanel`);
    assert.equal(
      await panel.getAttribute("aria-labelledby"),
      descriptor.id,
      `${label}: ${descriptor.controls} does not point back to ${descriptor.id}`,
    );
    assert.equal(
      await panel.isVisible(),
      descriptor.selected,
      `${label}: ${descriptor.controls} visibility does not match aria-selected`,
    );
  }
}

async function pressTabKey(
  page: Page,
  tablist: Locator,
  key: "ArrowLeft" | "ArrowRight" | "Home" | "End",
  expectedName: string,
  label: string,
): Promise<void> {
  const activeTab = tablist.locator('[role="tab"][aria-selected="true"]');
  await activeTab.press(key);
  const nextTab = await assertActiveTabContract(page, tablist, expectedName, label);
  assert.equal(await nextTab.evaluate((element) => element === document.activeElement), true, `${label}: ${key} did not move focus`);
}

async function runViewport(origin: string, viewport: Viewport): Promise<RuntimeResult> {
  const label = `${viewport.width}x${viewport.height}`;
  const screenshot = join(outputRoot, `admin-billing-${label}.png`);
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const requests: string[] = [];
  const fontRequests: string[] = [];
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const requestFailures: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("requestfailed", (request) => {
    requestFailures.push(
      `${request.method()} ${request.url()} ${request.failure()?.errorText ?? "unknown failure"}`,
    );
  });
  try {
    await page.route(/^https:\/\/fonts\.(?:googleapis|gstatic)\.com\//u, async (route) => {
      fontRequests.push(route.request().url());
      await route.fulfill({ status: 200, contentType: "text/css", body: "" });
    });
    await installApi(page, requests);
    await page.goto(`${origin}${billingPath}`, { waitUntil: "domcontentloaded" });

    const pageRoot = page.locator('main[data-page-ownership="governance"]');
    await pageRoot.waitFor({ state: "visible", timeout: 10_000 });
    await page.getByRole("heading", { name: "计费运营", exact: true }).waitFor({ timeout: 10_000 });
    assert.equal(new URL(page.url()).pathname, billingPath, `${label}: billing route drifted`);
    assert.equal(await pageRoot.getAttribute("data-page-ownership"), "governance");

    const dataTabs = page.getByRole("tablist", { name: "计费数据视图" });
    const operationTabs = page.getByRole("tablist", { name: "计费写入操作" });
    await dataTabs.waitFor({ state: "visible", timeout: 10_000 });
    await operationTabs.waitFor({ state: "visible", timeout: 10_000 });
    assert.equal(await dataTabs.getByRole("tab").count(), 5, `${label}: billing data tab count drifted`);
    assert.equal(await operationTabs.getByRole("tab").count(), 5, `${label}: billing operation tab count drifted`);
    await assertTablistIdentifiers(page, dataTabs, `${label}: data tabs`);
    await assertTablistIdentifiers(page, operationTabs, `${label}: operation tabs`);
    await assertActiveTabContract(page, dataTabs, "套餐", `${label}: data tabs initial state`);
    await assertActiveTabContract(page, operationTabs, "编辑映射", `${label}: operation tabs initial state`);

    const mappingTab = dataTabs.getByRole("tab", { name: "商品映射", exact: true });
    await mappingTab.click();
    await assertActiveTabContract(page, dataTabs, "商品映射", `${label}: data tabs click`);
    await page.getByText("liandong_creator_pro_2026", { exact: true }).waitFor({ state: "visible" });
    await pressTabKey(page, dataTabs, "ArrowRight", "卡密批次", `${label}: data tabs ArrowRight`);
    await pressTabKey(page, dataTabs, "End", "管理员赠款", `${label}: data tabs End`);
    await pressTabKey(page, dataTabs, "ArrowLeft", "兑换记录", `${label}: data tabs ArrowLeft`);
    await pressTabKey(page, dataTabs, "Home", "套餐", `${label}: data tabs Home`);
    await pressTabKey(page, dataTabs, "ArrowLeft", "管理员赠款", `${label}: data tabs wrap left`);
    await pressTabKey(page, dataTabs, "ArrowRight", "套餐", `${label}: data tabs wrap right`);
    await mappingTab.click();
    await assertActiveTabContract(page, dataTabs, "商品映射", `${label}: data tabs screenshot state`);

    const batchTab = operationTabs.getByRole("tab", { name: "生成批次", exact: true });
    await batchTab.click();
    await assertActiveTabContract(page, operationTabs, "生成批次", `${label}: operation tabs click`);
    await page.getByRole("heading", { name: "生成卡密批次", exact: true }).waitFor({ state: "visible" });
    await page.getByLabel("卡密数量").waitFor({ state: "visible" });
    await pressTabKey(page, operationTabs, "ArrowRight", "恢复履约", `${label}: operation tabs ArrowRight`);
    await pressTabKey(page, operationTabs, "End", "退款履约", `${label}: operation tabs End`);
    await pressTabKey(page, operationTabs, "ArrowRight", "编辑映射", `${label}: operation tabs wrap right`);
    await pressTabKey(page, operationTabs, "ArrowLeft", "退款履约", `${label}: operation tabs wrap left`);
    await pressTabKey(page, operationTabs, "Home", "编辑映射", `${label}: operation tabs Home`);
    await pressTabKey(page, operationTabs, "ArrowRight", "管理员赠款", `${label}: operation tabs second item`);
    await batchTab.click();
    await assertActiveTabContract(page, operationTabs, "生成批次", `${label}: operation tabs screenshot state`);

    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForFunction(() => window.scrollY === 0);
    const layout = await measureLayout(page, label);
    await page.evaluate(() => document.fonts.ready);
    assert.equal(await page.evaluate(() => document.fonts.status), "loaded", `${label}: fallback fonts did not settle`);
    await page.screenshot({ path: screenshot, fullPage: true });

    assert.deepEqual(
      consoleErrors,
      [],
      `${label}: console errors\n${consoleErrors.join("\n")}\nfailed requests\n${requestFailures.join("\n")}`,
    );
    assert.deepEqual(pageErrors, [], `${label}: page errors\n${pageErrors.join("\n")}`);
    assert.equal(
      requests.every(
        (entry) => entry === "GET /session" || entry === "GET /admin/billing/summary",
      ),
      true,
      `${label}: unexpected API request: ${requests.join(", ")}`,
    );
    assert.equal(
      requests.some((entry) => !entry.startsWith("GET ")),
      false,
      `${label}: write request observed: ${requests.join(", ")}`,
    );
    assert.ok(requests.includes("GET /session"), `${label}: admin session was not requested`);
    assert.ok(
      requests.includes("GET /admin/billing/summary"),
      `${label}: billing summary was not requested`,
    );
    assert.equal(fontRequests.length, 0, `${label}: external Google Fonts request observed`);
    return { label, viewport, requests, fontRequests, screenshot, layout };
  } finally {
    await browser.close();
  }
}

await mkdir(outputRoot, { recursive: true });
const server = await createServer({
  root: projectRoot,
  configFile: false,
  base: `${mediaBase}/`,
  publicDir: false,
  appType: "spa",
  plugins: [
    react(),
    {
      name: "admin-billing-visual-runtime-media-index",
      configureServer(viteServer) {
        viteServer.middlewares.use(async (request, response, next) => {
          if (!request.headers.accept?.includes("text/html")) return next();
          try {
            const html = await readFile(join(projectRoot, "index.media.html"), "utf8");
            response.statusCode = 200;
            response.setHeader("Content-Type", "text/html");
            response.end(
              await viteServer.transformIndexHtml(request.url ?? mediaBase, html),
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
  assert.ok(address && typeof address !== "string", "Vite QA server did not expose a TCP port");
  const origin = `http://127.0.0.1:${address.port}`;
  const results: RuntimeResult[] = [];
  for (const viewport of viewports) results.push(await runViewport(origin, viewport));
  console.log(JSON.stringify({ ok: true, outputRoot, results }, null, 2));
} finally {
  await server.close();
}
