import assert from "node:assert/strict";
import { mkdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, type Page, type Route } from "playwright";
import { createServer, type ViteDevServer } from "vite";
import react from "@vitejs/plugin-react";

const mediaBase = "/openclaw/media";
const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
// An explicit B01_QA_URL points this at an already-running deployment (base URL
// including the /openclaw/media prefix, e.g. for a manual/staging walkthrough);
// otherwise this gate hosts the real app itself via a local, in-process Vite
// dev server so it has no external dependency.
const externalBaseUrl = process.env.B01_QA_URL?.replace(/\/$/, "") ?? null;
const outputDir = resolve(process.env.B01_QA_OUTPUT ?? "/tmp/openclaw-media-b01-overview/screenshots");
const label = process.env.B01_QA_LABEL ?? "candidate";
const mode = process.env.B01_QA_MODE ?? "full";

mkdirSync(outputDir, { recursive: true });

const session = {
  schemaVersion: "media_web_business_pages_v2",
  revision: 1,
  session: {
    publicUserId: "11111111-1111-4111-8111-111111111111",
    organizationName: null,
    workspaceMode: "personal_web",
    editorMode: "web_edit",
    bodyAuthority: "internal",
    memberRole: "owner",
    organizationConnection: "not_applicable",
    installationConnection: "not_applicable",
    role: "ordinary",
    maintainer: false,
    csrfToken: "b01-qa-csrf",
    expiresAt: "2026-08-08T00:00:00+00:00",
    // Must match mediaWebApi.ts's exactRouteGrants.personal item-for-item
    // (mediaWebSessionSchema rejects a session whose grants don't match
    // exactly), or the real app falls back to "workspace unavailable".
    routeGrants: ["/today", "/studio", "/campaigns", "/business", "/desk", "/overview", "/assets", "/tracks", "/decisions", "/publishing", "/reviews", "/media-agent", "/archives", "/usage-billing", "/invites", "/workspace"],
    schemaVersion: "media_web_business_pages_v2",
  },
};

const emptyCatalog = {
  schemaVersion: "capability_catalog_v3",
  catalogVersion: `sha256:${"0".repeat(64)}`,
  capabilities: [],
};

const dashboard = {
  schemaVersion: "media_web_business_pages_v2",
  revision: 12,
  summary: {
    counts: {
      contentProjects: mode === "empty" ? 0 : 12,
      runs: mode === "empty" ? 0 : 7,
      assets: mode === "empty" ? 0 : 48,
      tracks: mode === "empty" ? 0 : 5,
      creators: mode === "empty" ? 0 : 23,
      publishedPosts: mode === "empty" ? 0 : 9,
      reviews: mode === "empty" ? 0 : 4,
    },
    contentProjectStages: ["research", "assets", "decision", "creation", "publishing", "review"].map((stage, index) => ({
      stage,
      count: mode === "empty" ? 0 : index + 1,
    })),
    pendingDecisions: mode === "empty" ? 0 : 3,
    pendingPublishing: mode === "empty" ? 0 : 2,
    pendingReviews: mode === "empty" ? 0 : 1,
    taskSummary: { queued: 0, running: 0, needsAttention: 0, failed: 0 },
    coverage: { known: mode === "empty" ? 0 : 108, unknown: 0, unavailable: 0 },
    generatedAt: "2026-08-05T08:00:00+00:00",
    revision: 12,
  },
};

const project = {
  publicProjectId: "project_b01_acceptance",
  title: "跨平台增长项目：这是用于验证窄屏长标题不会溢出的真实项目名称",
  workspaceMode: "personal_web",
  stage: "creation",
  status: "active",
  artifactCounts: { creation_document: 2, decision_brief: 1 },
  updatedAt: "2026-08-05T08:00:00+00:00",
};

const artifact = {
  publicArtifactId: "artifact_b01_acceptance",
  publicProjectId: project.publicProjectId,
  artifactType: "creation_document",
  bodyAuthority: "internal",
  currentRevision: 3,
  syncStatus: "not_applicable",
  updatedAt: "2026-08-05T08:00:00+00:00",
  allowedActions: ["view", "regenerate"],
};

async function fulfill(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installApi(page: Page): Promise<void> {
  await page.route("**/openclaw/media/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/openclaw\/media\/api/, "");
    if (path === "/session") return fulfill(route, session);
    if (path === "/capabilities") return fulfill(route, emptyCatalog);
    if (path === "/tasks" && url.searchParams.has("limit")) return fulfill(route, { tasks: [] });
    if (path === "/tasks") return fulfill(route, { schemaVersion: "media_web_business_pages_v2", revision: 0, items: [], nextCursor: null });
    if (path === "/dashboard" && mode === "error") {
      return fulfill(route, { error: { code: "upstream_unavailable", message: "总览服务暂不可用。" } }, 503);
    }
    if (path === "/dashboard") return fulfill(route, dashboard);
    if (path === "/content-projects") {
      return fulfill(route, { schemaVersion: "media_web_business_pages_v2", revision: mode === "empty" ? 0 : 12, items: mode === "empty" ? [] : [project], nextCursor: null });
    }
    if (path === `/content-projects/${project.publicProjectId}/artifacts`) {
      return fulfill(route, { schemaVersion: "media_web_business_pages_v2", revision: 12, items: [artifact], nextCursor: null });
    }
    if (path === `/content-projects/${project.publicProjectId}/summaries` && request.method() === "POST") {
      return fulfill(route, { schemaVersion: "media_web_business_pages_v2", revision: 13, item: artifact });
    }
    return fulfill(route, { error: { code: "unexpected_qa_request", message: `${request.method()} ${path}` } }, 500);
  });
}

async function assertNoOverflow(page: Page, viewport: string): Promise<void> {
  const result = await page.evaluate(() => ({
    documentX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    bodyX: document.body.scrollWidth - document.body.clientWidth,
  }));
  if (result.documentX > 1 || result.bodyX > 1) {
    throw new Error(`${viewport} overflow: ${JSON.stringify(result)}`);
  }
}

async function startServer(): Promise<ViteDevServer> {
  const server = await createServer({
    root: frontendRoot,
    configFile: false,
    base: mediaBase + "/",
    publicDir: false,
    appType: "spa",
    plugins: [
      react(),
      {
        name: "b01-real-media-index",
        configureServer(viteServer) {
          viteServer.middlewares.use(async (request, response, next) => {
            const path = new URL(request.url ?? "/", "http://127.0.0.1").pathname;
            if (path !== mediaBase && path !== mediaBase + "/" && path !== mediaBase + "/overview") {
              next();
              return;
            }
            try {
              const html = readFileSync(join(frontendRoot, "index.media.html"), "utf8");
              response.statusCode = 200;
              response.setHeader("Content-Type", "text/html");
              response.end(await viteServer.transformIndexHtml(request.url ?? path, html));
            } catch (error) {
              next(error as Error);
            }
          });
        },
      },
    ],
    // watch: null disables the filesystem watcher: this dev server exists only to
    // serve one fixed bundle for this run's duration, and this repo routinely has
    // other agents editing unrelated files concurrently (including generated
    // dist-demo/ output) — without this, their saves trigger HMR page reloads
    // that could race and destabilize the assertions below.
    server: { host: "127.0.0.1", port: 0, strictPort: false, watch: null },
  });
  await server.listen();
  return server;
}

async function capture(baseUrl: string, viewport: "desktop" | "mobile"): Promise<void> {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: viewport === "desktop" ? { width: 1440, height: 1000 } : { width: 390, height: 844 },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  await installApi(page);
  await page.goto(`${baseUrl}/overview`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "运营总览" }).waitFor();

  if (label === "baseline") {
    await page.waitForTimeout(250);
  } else if (mode === "error") {
    // OverviewPage no longer surfaces the raw server error string; every failed
    // B01 request instead renders a fixed, safe Chinese fallback message (see
    // useB01Dashboard's "总览读取失败。" and the projection-degradation contract
    // that forbids echoing backend error text back to ordinary users).
    await page.getByText("总览读取失败。").first().waitFor();
    if ((await page.locator("[data-page-prelude] strong").first().innerText()) !== "—") {
      throw new Error("dashboard failure rendered as zero");
    }
  } else if (mode === "empty") {
    await page.getByText("还没有可统计的内容", { exact: false }).waitFor();
    await page.getByText("还没有内容项目", { exact: false }).waitFor();
  } else {
    await page.getByText(project.title).first().waitFor();
    if (viewport === "desktop") {
      await page.getByRole("button", { name: "能力中心" }).click();
      await page.getByRole("complementary", { name: "Media 任务工作区" }).waitFor();
      await page.getByRole("button", { name: "关闭任务工作区" }).first().click();
    }
    await page.getByRole("button", { name: "生成摘要" }).click();
    await page.getByText("摘要生成请求已提交。").waitFor();
  }

  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: resolve(outputDir, `${label}-${mode}-${viewport}.png`), fullPage: false });
  await assertNoOverflow(page, viewport);
  await browser.close();
}

async function main() {
  let server: ViteDevServer | null = null;
  try {
    let baseUrl: string;
    if (externalBaseUrl) {
      baseUrl = externalBaseUrl;
    } else {
      server = await startServer();
      const address = server.httpServer?.address();
      assert.ok(address && typeof address !== "string", "Vite QA server did not expose a TCP port");
      baseUrl = `http://127.0.0.1:${address.port}${mediaBase}`;
    }
    await capture(baseUrl, "desktop");
    await capture(baseUrl, "mobile");
  } finally {
    if (server) await server.close();
  }
  console.log(`B01 screenshot QA passed: ${label}/${mode}`);
}

await main();
