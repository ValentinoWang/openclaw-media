import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, type Page, type Route } from "playwright";
import react from "@vitejs/plugin-react";
import { createServer } from "vite";

const mediaBase = "/openclaw/media";
const apiRoot = `${mediaBase}/api`;
const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const projectId = "project_personal_readonly_0001";
const artifactId = "artifact_personal_readonly_0001";
const externalTargetUrl = process.env.DELETION_INTENT_TARGET_URL?.trim() || null;
const outputDir =
  process.env.DELETION_INTENT_QA_OUTPUT ??
  "/tmp/openclaw-media-stage1-personal-readonly-20260818";

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
    routeGrants: ["/overview", "/assets", "/workspace"],
    csrfToken: "personal-readonly-csrf",
    expiresAt: "2099-01-01T00:00:00Z",
    schemaVersion: "media_web_business_pages_v2",
  },
} as const;

const project = {
  publicProjectId: projectId,
  title: "个人交付项目",
  workspaceMode: "personal_web",
  stage: "delivery",
  status: "active",
  artifactCounts: { project_summary: 1 },
  updatedAt: "2026-08-18T01:00:00Z",
};

const artifact = {
  publicArtifactId: artifactId,
  publicProjectId: projectId,
  artifactType: "project_summary",
  displayName: "阶段一云端成果",
  bodyAuthority: "internal",
  currentRevision: 1,
  syncStatus: "not_applicable",
  updatedAt: "2026-08-18T01:05:00Z",
  allowedActions: ["read", "preview"],
};

const documentBody = {
  schemaVersion: "media_web_business_pages_v2",
  revision: 1,
  data: {
    artifact: {
      publicArtifactId: artifactId,
      publicProjectId: projectId,
      artifactKind: "project_summary",
      workspaceMode: "personal_web",
      bodyAuthority: "internal",
      currentRevision: 1,
      updatedAt: "2026-08-18T01:05:00Z",
    },
    revision: {
      publicArtifactId: artifactId,
      artifactKind: "project_summary",
      bodyAuthority: "internal",
      revision: 1,
      baseRevision: null,
      state: "ready",
      bodyChecksum: `sha256:${"a".repeat(64)}`,
      remoteDocumentVersion: null,
      body: {
        schemaVersion: "media.document.body.v1",
        blocks: [
          {
            id: "block_personal_readonly_0001",
            type: "paragraph",
            attrs: {},
            content: [{ type: "text", text: "只读云端正文已加载", marks: [] }],
          },
        ],
      },
      createdAt: "2026-08-18T01:05:00Z",
      updatedAt: "2026-08-18T01:05:00Z",
    },
  },
};

async function fulfill(route: Route, status: number, body: unknown) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function apiPath(route: Route): string {
  return new URL(route.request().url()).pathname.slice(apiRoot.length);
}

async function assertPersonalOrdinaryRoute(
  page: Page,
  sourceRoute: string,
  expectedPathname: string,
  heading: string,
) {
  await page.goto(sourceRoute, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: heading, exact: true }).waitFor();
  assert.equal(new URL(page.url()).pathname, `${mediaBase}${expectedPathname}`);
  assert.equal(await page.getByRole("heading", { name: "云端成果", exact: true }).count(), 0);
}

async function assertPersonalReadonlyShell(page: Page, workspaceRoute: string) {
  await page.goto(workspaceRoute, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "云端成果", exact: true }).waitFor();
  await page.getByText("个人交付项目", { exact: true }).waitFor();
  await page.getByText("阶段一云端成果", { exact: true }).waitFor();
  assert.match(new URL(page.url()).pathname, /\/openclaw\/media\/workspace$/);
  assert.equal(await page.getByRole("heading", { name: "素材与灵感", exact: true }).count(), 0);
  assert.equal(await page.getByRole("button", { name: "删除素材", exact: true }).count(), 0);
  assert.equal(await page.getByText("内容产物删除", { exact: true }).count(), 0);
}

let server: Awaited<ReturnType<typeof createServer>> | null = null;
let origin: string;
if (externalTargetUrl) {
  const target = new URL(externalTargetUrl);
  assert.ok(target.protocol === "http:" || target.protocol === "https:");
  origin = target.origin;
} else {
  server = await createServer({
    root: projectRoot,
    base: `${mediaBase}/`,
    configFile: false,
    publicDir: false,
    appType: "spa",
    plugins: [
      react(),
      {
        name: "stage1-personal-readonly-media-index",
        configureServer(viteServer) {
          viteServer.middlewares.use(async (request, response, next) => {
            if (!request.headers.accept?.includes("text/html")) return next();
            try {
              const html = readFileSync(join(projectRoot, "index.media.html"), "utf8");
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
  const address = server.httpServer?.address();
  assert.ok(address && typeof address === "object");
  origin = `http://127.0.0.1:${address.port}`;
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const requests: string[] = [];
const mutations: string[] = [];

await page.route(`**${apiRoot}/**`, async (route) => {
  const request = route.request();
  const path = apiPath(route);
  requests.push(`${request.method()} ${path}`);
  if (request.method() !== "GET") {
    mutations.push(`${request.method()} ${path}`);
    return fulfill(route, 405, {
      error: { code: "stage1_personal_readonly", message: "个人工作区不开放内容写操作。" },
    });
  }
  if (path === "/session") return fulfill(route, 200, session);
  if (path === "/content-projects") return fulfill(route, 200, { items: [project] });
  if (path === `/content-projects/${projectId}/artifacts`) {
    return fulfill(route, 200, { items: [artifact] });
  }
  if (path === `/documents/${artifactId}/body`) return fulfill(route, 200, documentBody);
  if (path === "/capabilities" || path === "/tasks") {
    return fulfill(route, 503, {
      error: { code: "not_available_in_personal_stage1", message: "Stage 1 personal read-only shell" },
    });
  }
  return fulfill(route, 500, {
    error: { code: "unexpected_qa_request", message: `${request.method()} ${path}` },
  });
});

try {
  await mkdir(outputDir, { recursive: true });
  await assertPersonalOrdinaryRoute(
    page,
    `${origin}${mediaBase}/assets`,
    "/assets",
    "素材与灵感",
  );
  await assertPersonalOrdinaryRoute(
    page,
    `${origin}${mediaBase}/overview`,
    "/overview",
    "运营总览",
  );
  await assertPersonalReadonlyShell(page, `${origin}${mediaBase}/workspace`);

  const taskButton = page.getByRole("button", { name: "查看任务状态", exact: true });
  await taskButton.click();
  const drawer = page.getByRole("complementary", { name: "Media 任务工作区" });
  await drawer.getByText("尚未提交网页任务", { exact: true }).waitFor();
  assert.equal(await drawer.getByText("删除预览", { exact: true }).count(), 0);
  await drawer.getByRole("button", { name: "关闭任务状态", exact: true }).click();

  await page.getByRole("link", { name: "查看云端预览", exact: true }).click();
  await page.getByRole("heading", { name: "云端成果预览", exact: true }).waitFor();
  await page.getByText("只读云端正文已加载", { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: /删除/ }).count(), 0);
  await page.screenshot({ path: join(outputDir, "personal-readonly-desktop.png"), fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await assertPersonalOrdinaryRoute(
    page,
    `${origin}${mediaBase}/overview`,
    "/overview",
    "运营总览",
  );
  await assertPersonalReadonlyShell(page, `${origin}${mediaBase}/workspace`);
  const geometry = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    body: document.body.scrollWidth - document.body.clientWidth,
  }));
  assert.ok(
    geometry.document <= 1 && geometry.body <= 1,
    `personal read-only shell overflows mobile: ${JSON.stringify(geometry)}`,
  );
  await page.screenshot({ path: join(outputDir, "personal-readonly-mobile.png"), fullPage: true });

  assert.deepEqual(mutations, []);
  assert.ok(requests.includes("GET /session"));
  assert.ok(requests.includes("GET /content-projects"));
  assert.ok(requests.includes(`GET /content-projects/${projectId}/artifacts`));
  assert.ok(requests.includes(`GET /documents/${artifactId}/body`));
  assert.equal(requests.some((value) => value.startsWith("POST /tasks")), false);
  console.log("Stage 1 personal read-only deletion boundary QA passed");
} finally {
  await context.close();
  await browser.close();
  await server?.close();
}
