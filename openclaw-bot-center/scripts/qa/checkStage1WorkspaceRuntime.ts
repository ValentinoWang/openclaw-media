import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, type Page, type Route } from "playwright";
import react from "@vitejs/plugin-react";
import { createServer } from "vite";

const mediaBase = "/openclaw/media";
const apiRoot = `${mediaBase}/api`;
const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const outputRoot = resolve(
  process.env.STAGE1_WORKSPACE_RUNTIME_QA_OUTPUT ??
    join(projectRoot, "..", "..", "..", "agents-results", "2026-08-15", "media-c-b-stage-1-identity-and-organization-onboarding", "evidence-stage1-runtime"),
);

const personalProjectId = "stage1_runtime_personal_project";
const personalArtifactId = "stage1_runtime_personal_artifact";

const viewports = [
  { width: 1440, height: 1000 },
  { width: 1280, height: 900 },
  { width: 1024, height: 768 },
  { width: 390, height: 844 },
] as const;

type OrganizationConnection = "connected" | "disabled";
type WorkspaceScenario = "personal" | "organization-active" | "organization-disabled";

const baseSession = {
  publicUserId: "11111111-1111-4111-8111-111111111111",
  role: "ordinary" as const,
  maintainer: false,
  csrfToken: "stage1-runtime-csrf",
  expiresAt: "2099-01-01T00:00:00+00:00",
  schemaVersion: "media_web_business_pages_v2" as const,
};

function sessionFor(scenario: WorkspaceScenario) {
  if (scenario === "personal") {
    return {
      ...baseSession,
      organizationName: null,
      memberRole: "owner" as const,
      organizationConnection: "not_applicable" as const,
      installationConnection: "not_applicable" as const,
      workspaceMode: "personal_web" as const,
      editorMode: "web_edit" as const,
      bodyAuthority: "internal" as const,
      routeGrants: ["/today", "/studio", "/campaigns", "/business", "/desk", "/overview", "/assets", "/tracks", "/decisions", "/publishing", "/reviews", "/media-agent", "/archives", "/usage-billing", "/invites", "/workspace"],
    };
  }
  const organizationConnection: OrganizationConnection = scenario === "organization-active" ? "connected" : "disabled";
  return {
    ...baseSession,
    organizationName: "测试飞书组织",
    memberRole: "member" as const,
    organizationConnection,
    installationConnection: organizationConnection,
    workspaceMode: "organization_lark" as const,
    editorMode: "lark_edit" as const,
    bodyAuthority: "lark" as const,
    routeGrants: ["/organization-workspace", "/tracks"],
  };
}

async function fulfill(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function apiPath(url: string): string {
  return new URL(url).pathname.replace(apiRoot, "") || "/";
}

async function assertWorkspaceDispatch(
  page: Page,
  scenario: WorkspaceScenario,
  label: string,
  methods: string[],
  consoleErrors: string[],
): Promise<void> {
  const expected = scenario === "personal"
    ? { ownership: "personal", mode: "personal_web" }
    : { ownership: "organization", mode: "organization_lark" };
  await page.waitForFunction(({ ownership, mode }) => {
    const expectedRoot = document.querySelector(
      `[data-page-ownership="${ownership}"][data-workspace-mode="${mode}"]`,
    );
    const terminalHeading = [...document.querySelectorAll("h1")].some((heading) =>
      ["工作台暂时不可用", "无权访问此页面"].includes(heading.textContent?.trim() ?? ""),
    );
    return Boolean(expectedRoot || terminalHeading);
  }, expected, { timeout: 10_000 });

  const diagnostics = await page.evaluate(() => ({
    headings: [...document.querySelectorAll("h1")].map((heading) => heading.textContent?.trim()).filter(Boolean),
    markers: [...document.querySelectorAll<HTMLElement>("[data-page-ownership]")].map((element) => ({
      ownership: element.dataset.pageOwnership ?? null,
      workspaceMode: element.dataset.workspaceMode ?? null,
    })),
  }));
  const expectedRoot = page.locator(
    `[data-page-ownership="${expected.ownership}"][data-workspace-mode="${expected.mode}"]`,
  );
  if (await expectedRoot.count() !== 1) {
    const screenshotPath = join(outputRoot, `${label}-workspace-dispatch-failure.png`);
    await page.screenshot({ path: screenshotPath, fullPage: true });
    assert.fail(
      `${label}: session did not dispatch to the ${expected.ownership} workspace; ` +
        `verify exact routeGrants and WorkspaceShell ownership markers. ` +
        `url=${page.url()} headings=${JSON.stringify(diagnostics.headings)} ` +
        `markers=${JSON.stringify(diagnostics.markers)} requests=${JSON.stringify(methods)} ` +
        `consoleErrors=${JSON.stringify(consoleErrors)} screenshot=${screenshotPath}`,
    );
  }
  assert.equal(
    await page.locator('[data-page-ownership="router"]').count(),
    0,
    `${label}: authenticated workspace stopped at the WorkspaceShell fallback marker`,
  );
}

function assertNoComponentOverflow(page: Page, label: string): Promise<void> {
  return page.evaluate((scenarioLabel) => {
    const documentWidth = document.documentElement.scrollWidth;
    const viewportWidth = document.documentElement.clientWidth;
    if (documentWidth > viewportWidth + 1) {
      throw new Error(`${scenarioLabel}: document overflow ${documentWidth} > ${viewportWidth}`);
    }
    const selectors = [
      ".media-shell",
      ".media-topbar",
      ".media-content",
      ".personal-workspace-page",
      ".organization-workspace-page",
      ".personal-workspace-grid",
      ".organization-shell-grid",
    ];
    for (const selector of selectors) {
      for (const element of document.querySelectorAll<HTMLElement>(selector)) {
        const rect = element.getBoundingClientRect();
        if (rect.left < -1 || rect.right > viewportWidth + 1) {
          throw new Error(`${scenarioLabel}: ${selector} outside viewport (${rect.left}, ${rect.right}, ${viewportWidth})`);
        }
      }
    }
  }, label);
}

async function installApi(page: Page, scenario: WorkspaceScenario, methods: string[]): Promise<void> {
  await page.route(`**${apiRoot}/**`, async (route) => {
    const request = route.request();
    const path = apiPath(request.url());
    methods.push(`${request.method()} ${path}`);
    if (request.method() !== "GET") {
      await fulfill(route, { error: { code: "unexpected_write", message: `${request.method()} ${path}` } }, 500);
      return;
    }
    if (path === "/session") {
      await fulfill(route, { schemaVersion: "media_web_business_pages_v2", revision: 1, session: sessionFor(scenario) });
      return;
    }
    if (path === "/capabilities") {
      await fulfill(route, {
        schemaVersion: "capability_catalog_v3",
        catalogVersion: `sha256:${"0".repeat(64)}`,
        capabilities: [],
      });
      return;
    }
    if (path === "/tasks") {
      await fulfill(route, {
        schemaVersion: "media_web_business_pages_v2",
        revision: 0,
        items: [],
        nextCursor: null,
        tasks: [],
      });
      return;
    }
    if (path === "/content-projects") {
      await fulfill(route, {
        schemaVersion: "media_web_business_pages_v2",
        revision: 1,
        items: scenario === "personal" ? [{
          publicProjectId: personalProjectId,
          title: "第一阶段云端交付验证项目",
          workspaceMode: "personal_web",
          stage: "review",
          status: "active",
          artifactCounts: { creation_document: 1 },
          updatedAt: "2099-01-01T00:00:00+00:00",
        }] : [],
        nextCursor: null,
      });
      return;
    }
    if (path === `/content-projects/${personalProjectId}/artifacts`) {
      await fulfill(route, {
        schemaVersion: "media_web_business_pages_v2",
        revision: 1,
        items: [{
          publicArtifactId: personalArtifactId,
          publicProjectId: personalProjectId,
          artifactType: "creation_document",
          displayName: "第一阶段个人云端成果",
          bodyAuthority: "internal",
          currentRevision: 1,
          syncStatus: "not_applicable",
          updatedAt: "2099-01-01T00:00:00+00:00",
          allowedActions: ["view"],
        }],
        nextCursor: null,
      });
      return;
    }
    if (path === `/documents/${personalArtifactId}/body`) {
      await fulfill(route, {
        schemaVersion: "media_web_business_pages_v2",
        revision: 1,
        data: {
          artifact: { workspaceMode: "personal_web", bodyAuthority: "internal", artifactKind: "creation_document" },
          revision: {
            body: {
              blocks: [{
                id: "stage1-runtime-heading",
                type: "heading_1",
                attrs: {},
                content: [{ type: "text", text: "第一阶段云端成果正文", marks: [] }],
              }],
            },
          },
        },
      });
      return;
    }
    await fulfill(route, { error: { code: "unexpected_qa_request", message: `${request.method()} ${path}` } }, 500);
  });
}

async function runScenario(origin: string, scenario: WorkspaceScenario, viewport: { width: number; height: number }, label: string) {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const methods: string[] = [];
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const requestFailures: string[] = [];
  const externalFontRequests: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("requestfailed", (request) => {
    requestFailures.push(`${request.method()} ${request.url()} ${request.failure()?.errorText ?? "unknown failure"}`);
  });
  try {
    await page.route(/^https:\/\/fonts\.(?:googleapis|gstatic)\.com\//u, async (route) => {
      externalFontRequests.push(route.request().url());
      await route.fulfill({ status: 200, contentType: "text/css", body: "" });
    });
    await installApi(page, scenario, methods);
    const path = scenario === "personal" ? `${mediaBase}/workspace` : `${mediaBase}/organization-workspace`;
    await page.goto(`${origin}${path}`, { waitUntil: "domcontentloaded" });
    assert.equal(new URL(page.url()).pathname, path, `${label}: workspace route drifted`);
    await assertWorkspaceDispatch(page, scenario, label, methods, consoleErrors);
    if (scenario === "personal") {
      await page.getByRole("heading", { name: "云端成果", exact: true }).waitFor({ timeout: 10_000 });
      await page.getByText("第一阶段云端交付验证项目", { exact: true }).waitFor({ timeout: 10_000 });
      await page.getByRole("heading", { name: "云端交付与预览", exact: true }).waitFor({ timeout: 10_000 });
      await page.getByRole("link", { name: "查看云端预览" }).click();
      await page.getByRole("heading", { name: "云端成果预览", exact: true }).waitFor({ timeout: 10_000 });
      await page.getByText("第一阶段云端成果正文", { exact: true }).waitFor({ timeout: 10_000 });
      assert.equal(new URL(page.url()).pathname, `${mediaBase}/workspace/preview/${personalArtifactId}`);
      assert.equal(await page.locator(".personal-workspace-page").getAttribute("data-workspace-mode"), "personal_web");
      assert.equal(await page.getByRole("link", { name: /查看云端预览/ }).count(), 0);
      assert.equal(await page.getByRole("button", { name: /写入|发布|外部/ }).count(), 0);
      const taskStatusButton = page.getByRole("button", { name: "查看任务状态", exact: true });
      await taskStatusButton.waitFor({ state: "visible", timeout: 10_000 });
      assert.equal(
        await taskStatusButton.locator("span").evaluate((element) => getComputedStyle(element).display !== "none"),
        true,
        `${label}: personal task-status label is visually hidden`,
      );
    } else {
      await page.getByRole("heading", { name: "组织资源工作台", exact: true }).waitFor({ timeout: 10_000 });
      const expectedConnection = scenario === "organization-active" ? "connected" : "disabled";
      const expectedLabel = scenario === "organization-active" ? "已连接" : "已停用";
      const pageRoot = page.locator(".organization-workspace-page");
      await pageRoot.waitFor({ state: "visible", timeout: 10_000 });
      assert.equal(await pageRoot.getAttribute("data-workspace-mode"), "organization_lark");
      assert.equal(await pageRoot.getAttribute("data-organization-connection"), expectedConnection);
      await page.getByText("测试飞书组织", { exact: true }).first().waitFor({ timeout: 10_000 });
      await page.getByLabel("组织工作区状态和资源入口").getByText("组织成员", { exact: true }).waitFor({ timeout: 10_000 });
      await page.getByText(expectedLabel, { exact: true }).first().waitFor({ timeout: 10_000 });
      const visibleText = await page.locator("body").innerText();
      for (const internalValue of ["Binding 状态", "ACTIVE", "DISABLED", "NEEDS_ATTENTION"]) {
        assert.equal(visibleText.includes(internalValue), false, `${label}: leaked internal value ${internalValue}`);
      }
      assert.equal(await page.getByRole("button", { name: /写入|发布|外部/ }).count(), 0);
      if (scenario === "organization-disabled") {
        assert.equal(await page.getByText(/资源入口保持关闭并等待安装恢复。/).count(), 1);
        assert.equal(await page.getByText("已连接", { exact: true }).count(), 0);
      }
    }
    await assertResponsiveShell(page, label, viewport);
    await assertNoComponentOverflow(page, label);
    await page.evaluate(() => document.fonts.ready);
    assert.equal(await page.evaluate(() => document.fonts.status), "loaded", `${label}: fallback fonts did not settle`);
    await page.screenshot({ path: join(outputRoot, `${label}.png`), fullPage: true });
    assert.deepEqual(
      consoleErrors,
      [],
      `${label}: console errors\n${consoleErrors.join("\n")}\nfailed requests\n${requestFailures.join("\n")}`,
    );
    assert.deepEqual(pageErrors, [], `${label}: page errors\n${pageErrors.join("\n")}`);
    assert.equal(methods.some((entry) => !entry.startsWith("GET ")), false, `${label}: external write request observed: ${methods.join(", ")}`);
    assert.ok(methods.includes("GET /capabilities"), `${label}: ordinary shell did not load capabilities`);
    assert.ok(methods.includes("GET /tasks"), `${label}: ordinary shell did not load tasks`);
    assert.equal(externalFontRequests.length, 0, `${label}: external Google Fonts request observed`);
    return { label, viewport, requests: methods };
  } finally {
    await browser.close();
  }
}

async function assertResponsiveShell(
  page: Page,
  label: string,
  viewport: { width: number; height: number },
): Promise<void> {
  const sidebar = page.locator(".studio-sidebar");
  const menuButton = page.getByRole("button", { name: "打开导航", exact: true });
  if (viewport.width <= 1120) {
    await menuButton.waitFor({ state: "visible", timeout: 10_000 });
    const closedRect = await sidebar.boundingBox();
    assert.ok(closedRect, `${label}: responsive sidebar has no layout box`);
    assert.ok(
      closedRect.x + closedRect.width <= 1,
      `${label}: responsive sidebar remains visible while closed (${closedRect.x}, ${closedRect.width})`,
    );

    await menuButton.click();
    await page.waitForFunction(() => {
      const element = document.querySelector<HTMLElement>(".studio-sidebar");
      if (!element) return false;
      const rect = element.getBoundingClientRect();
      return rect.left >= -1 && rect.right > 0;
    });
    const navigation = page.locator(".studio-navigation");
    const lastLink = navigation.locator(".studio-nav-link").last();
    await lastLink.scrollIntoViewIfNeeded();
    const [navigationRect, lastLinkRect] = await Promise.all([navigation.boundingBox(), lastLink.boundingBox()]);
    assert.ok(navigationRect && lastLinkRect, `${label}: responsive navigation is missing its final route`);
    assert.ok(
      lastLinkRect.y >= navigationRect.y - 1 &&
        lastLinkRect.y + lastLinkRect.height <= navigationRect.y + navigationRect.height + 1,
      `${label}: final navigation route is clipped by the fixed sidebar footer ` +
        `(nav ${navigationRect.y}-${navigationRect.y + navigationRect.height}, ` +
        `route ${lastLinkRect.y}-${lastLinkRect.y + lastLinkRect.height})`,
    );
    await page.locator(".sidebar-scrim").click({ position: { x: viewport.width - 2, y: 10 } });
    await page.waitForFunction(() => {
      const element = document.querySelector<HTMLElement>(".studio-sidebar");
      if (!element) return false;
      const rect = element.getBoundingClientRect();
      return rect.right <= 1;
    });
  } else {
    assert.equal(await menuButton.isVisible(), false, `${label}: desktop shell unexpectedly exposes the drawer trigger`);
    const desktopRect = await sidebar.boundingBox();
    assert.ok(desktopRect && desktopRect.x >= -1, `${label}: desktop sidebar is outside the viewport`);
  }

  const capabilityButton = page.getByRole("button", { name: "能力中心", exact: true });
  if (await capabilityButton.count()) {
    await capabilityButton.waitFor({ state: "visible", timeout: 10_000 });
    const capabilityButtonRect = await capabilityButton.boundingBox();
    assert.ok(capabilityButtonRect && capabilityButtonRect.height <= 48, `${label}: capability launcher command wrapped vertically`);
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
      name: "stage1-runtime-media-index",
      configureServer(viteServer) {
        viteServer.middlewares.use(async (request, response, next) => {
          if (!request.headers.accept?.includes("text/html")) return next();
          try {
            const html = await readFile(join(projectRoot, "index.media.html"), "utf8");
            response.statusCode = 200;
            response.setHeader("Content-Type", "text/html");
            response.end(await viteServer.transformIndexHtml(request.url ?? mediaBase, html));
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
  const results = [];
  for (const viewport of viewports) {
    const viewportLabel = `${viewport.width}x${viewport.height}`;
    results.push(await runScenario(origin, "personal", viewport, `personal-${viewportLabel}`));
    results.push(await runScenario(origin, "organization-active", viewport, `organization-active-${viewportLabel}`));
    results.push(await runScenario(origin, "organization-disabled", viewport, `organization-disabled-${viewportLabel}`));
  }
  console.log(JSON.stringify({ ok: true, outputRoot, results }, null, 2));
} finally {
  await server.close();
}
