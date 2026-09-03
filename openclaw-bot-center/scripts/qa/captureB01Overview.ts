import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { chromium, type Page, type Route } from "playwright";

const baseUrl = process.env.B01_QA_URL ?? "http://127.0.0.1:5187/openclaw/media";
const outputDir = resolve(process.env.B01_QA_OUTPUT ?? "/home/ubuntu/media-business-api-evidence/5-5-2-5/B01/screenshots");
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

async function capture(viewport: "desktop" | "mobile"): Promise<void> {
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
    await page.getByText("总览服务暂不可用。").waitFor();
    if ((await page.locator("[data-page-prelude] strong").first().innerText()) !== "—") {
      throw new Error("dashboard failure rendered as zero");
    }
  } else if (mode === "empty") {
    await page.getByText("当前租户没有可汇总的内容事实", { exact: false }).waitFor();
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

await capture("desktop");
await capture("mobile");
console.log(`B01 screenshot QA passed: ${label}/${mode}`);
