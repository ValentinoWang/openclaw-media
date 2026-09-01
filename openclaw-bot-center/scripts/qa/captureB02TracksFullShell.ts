import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { chromium, type Locator, type Page, type Request, type Route } from "playwright";
import { createServer, type ViteDevServer } from "vite";
import react from "@vitejs/plugin-react";
import {
  operations,
  type GeneratedOperation,
  type OperationId,
} from "../../src/media/generatedBusinessPagesContract";

const tuple = "5/5/2/5";
const mediaBase = "/openclaw/media";
const apiRoot = mediaBase + "/api";
const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const runId =
  process.env.B02_RUN_ID ??
  new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
const evidenceRoot =
  process.env.B02_EVIDENCE_ROOT ??
  "/home/ubuntu/media-business-api-evidence/5-5-2-5/B02";
const runDir = join(evidenceRoot, "full-shell-" + runId);
const baseUrl = "http://127.0.0.1:18052";
const ownedAvatarUrl = "https://cdn.example.test/b02-owned-avatar.png";
const ownedAvatarPng = readFileSync(resolve(frontendRoot, "src/assets/hero.png"));
const externalTargetUrl = process.env.B02_TARGET_URL ?? null;
const pageUrl = externalTargetUrl ?? baseUrl + mediaBase + "/tracks";
const viewports = [
  { width: 1920, height: 1088 },
  { width: 390, height: 844 },
] as const;
const scenarios = [
  ["loading", "loading"],
  ["empty", "ready"],
  ["populated", "ready"],
  ["partial", "partial"],
  ["error", "error"],
  ["permission", "error"],
] as const;

type ScenarioName = (typeof scenarios)[number][0];
type RequestRecord = {
  method: string;
  url: string;
  path: string;
  operationId: OperationId | null;
  status: number | null;
  failure: string | null;
};

async function waitForValue<T>(
  read: () => Promise<T>,
  matches: (value: T) => boolean,
  label: string,
  timeoutMs = 10000,
): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  let value = await read();
  while (!matches(value)) {
    if (Date.now() >= deadline) {
      throw new Error("Timed out waiting for " + label + ": " + String(value));
    }
    await delay(50);
    value = await read();
  }
  return value;
}

async function assertVisible(locator: Locator, label: string) {
  await waitForValue(() => locator.isVisible(), (value) => value, label);
}

async function assertCount(locator: Locator, expected: number, label: string) {
  await waitForValue(() => locator.count(), (value) => value === expected, label);
}

async function assertAttribute(
  locator: Locator,
  name: string,
  expected: string,
  label: string,
) {
  await waitForValue(
    () => locator.getAttribute(name),
    (value) => value === expected,
    label,
  );
}

async function assertContainsText(locator: Locator, expected: string, label: string) {
  await waitForValue(
    () => locator.textContent(),
    (value) => value?.includes(expected) === true,
    label,
  );
}

async function assertMediaShell(
  page: Page,
  consoleErrors: string[],
  pageErrors: string[],
) {
  try {
    await assertCount(page.locator(".media-shell"), 1, "the real MediaStudioApp shell");
  } catch (error) {
    const diagnostic = await page.evaluate(() => ({
      rootHtml: document.getElementById("root")?.innerHTML.slice(0, 4000) ?? "",
      bodyText: document.body.innerText.slice(0, 2000),
      scripts: Array.from(document.scripts).map((script) => script.src),
    }));
    throw new Error(
      JSON.stringify({
        assertion: error instanceof Error ? error.message : String(error),
        url: page.url(),
        diagnostic,
        consoleErrors,
        pageErrors,
      }),
    );
  }
}

const operationEntries = Object.entries(operations) as Array<
  [OperationId, GeneratedOperation]
>;
const b02Operations = new Set<OperationId>([
  "listTracks",
  "listCreators",
  "getCreator",
  "listTrackRelationships",
  "listOwnedAccounts",
  "getOwnedAccount",
  "getAccountTrackStrategy",
]);

const sourceFiles: Record<string, string> = {
  tracksPage: resolve(frontendRoot, "src/media/pages/ordinary/TracksPage.tsx"),
  tracksCss: resolve(
    frontendRoot,
    "src/media/pages/ordinary/TracksPage.module.css",
  ),
  tracksService:
    "/home/ubuntu/selfmedia-tools/openclaw-tag-router/openclaw_app/services/media_business/tracks.py",
  tracksTest:
    "/home/ubuntu/selfmedia-tools/openclaw-tag-router/tests/test_media_business_tracks.py",
  tracksMigration:
    "/home/ubuntu/selfmedia-tools/openclaw-tag-router/openclaw_app/migrations/014_b02_tracks.sql",
  generatedClient: resolve(
    frontendRoot,
    "src/media/generatedBusinessPagesContract.ts",
  ),
  fullShellHelper: resolve(
    frontendRoot,
    "scripts/qa/captureB02TracksFullShell.ts",
  ),
};

const track = {
  publicTrackId: "track_b02_001",
  name: "力量训练",
  description: "显式登记的长内容赛道，用于验证真实页面的长文本边界。".repeat(10),
  parentPublicTrackId: null,
  status: "active",
  platforms: ["xiaohongshu", "douyin"],
  aliases: ["力量", "训练"],
  artifactCount: 4,
  updatedAt: "2026-08-05T02:02:03Z",
};
const creator = {
  publicCreatorId: "creator_b02_001",
  accountName: "长内容博主",
  platform: "xiaohongshu",
  creatorRole: "external_creator",
  identityTags: ["训练", "生活方式"],
  expertiseDomains: ["strength", "wellness"],
  profileUrl: "https://example.test/creator/creator_b02_001",
  updatedAt: "2026-08-05T02:02:03Z",
};
const creators = Array.from({ length: 8 }, (_, index) => ({
  ...creator,
  publicCreatorId: `creator_b02_${String(index + 1).padStart(3, "0")}`,
  accountName: `长内容账号 ${index + 1}`,
}));
const relationship = {
  publicRelationshipId: "rel_b02_001",
  publicTrackId: track.publicTrackId,
  publicCreatorId: creator.publicCreatorId,
  role: "标杆账号",
  fitScore: 91,
  fitReason: "正式 TrackCreatorMembership 关系说明。".repeat(20),
  status: "active",
  lastEvaluatedAt: "2026-08-05T02:02:03Z",
};
const relationships = Array.from({ length: 8 }, (_, index) => ({
  ...relationship,
  publicRelationshipId: `rel_b02_${String(index + 1).padStart(3, "0")}`,
  publicCreatorId: `creator_b02_${String(index + 1).padStart(3, "0")}`,
  fitScore: 91 - index,
}));
const account = {
  // The same explicit identity can be present in the historical relationship
  // source; the owned-account projection must win for the current UI domain.
  publicAccountId: "creator_b02_001",
  platform: "xiaohongshu",
  accountName: "我的自有账号",
  operationalStatus: "active",
  responsiblePerson: "王思尧",
  teamName: "内容运营组",
  accountPositioning: "面向大学生的校园运动与训练内容账号。",
  dataSource: "feishu_creator_profile",
  platformAccountId: "@qinghua-runner",
  profileUrl: null,
  avatarUrl: ownedAvatarUrl,
  publicTrackIds: [track.publicTrackId],
  lastSyncedAt: "2026-08-05T02:02:03Z",
  updatedAt: "2026-08-05T02:02:03Z",
};
const strategy = {
  publicStrategyId: "strategy_b02_001",
  publicAccountId: account.publicAccountId,
  targetPublicTrackIds: [track.publicTrackId],
  evidenceRefs: [{
    kind: "review",
    label: "人工审核证据",
    publicUrl: "https://example.test/evidence/strategy_b02_001",
    capturedAt: "2026-08-05T02:02:03Z",
    qualityStatus: "verified",
  }],
  recommendations: ["保持每周两次长内容输出。".repeat(20)],
  humanStatus: "pending",
  revision: 3,
  updatedAt: "2026-08-05T02:02:03Z",
};

function listResponse<T>(items: T[], revision = 7) {
  return {
    schemaVersion: "media_web_business_pages_v2",
    revision,
    items,
    nextCursor: null,
  };
}
function fixture(operationId: OperationId, empty: boolean): unknown {
  if (empty) return listResponse([]);
  switch (operationId) {
    case "listTracks": return listResponse([track]);
    case "listCreators": return listResponse(creators);
    case "listTrackRelationships": return listResponse(relationships);
    case "listOwnedAccounts": return listResponse([account]);
    case "getCreator":
      return { schemaVersion: "media_web_business_pages_v2", revision: 2, item: creator };
    case "getOwnedAccount":
      return { schemaVersion: "media_web_business_pages_v2", revision: 1, item: account };
    case "getAccountTrackStrategy":
      return { schemaVersion: "media_web_business_pages_v2", revision: 3, strategy };
    default: throw new Error("Unexpected B02 fixture operation " + operationId);
  }
}
function errorBody(code: string, message: string) {
  return { error: { code, message, field: null } };
}
function apiPath(url: string): string {
  const pathname = new URL(url).pathname;
  return pathname.startsWith(apiRoot) ? pathname.slice(apiRoot.length) || "/" : pathname;
}
function operationIdFor(method: string, path: string): OperationId | null {
  const actual = path.replace(/\/+$/, "").split("/").filter(Boolean);
  for (const [id, operation] of operationEntries) {
    const template = operation.path.split("/").filter(Boolean);
    if (operation.method !== method || template.length !== actual.length) continue;
    if (template.every((part, index) => part.startsWith("{") || part === actual[index])) {
      return id;
    }
  }
  return null;
}
async function json(route: Route, status: number, body: unknown, delayMs = 0) {
  if (delayMs) await delay(delayMs);
  try {
    await route.fulfill({
      status,
      contentType: "application/json",
      headers: { "Cache-Control": "no-store" },
      body: JSON.stringify(body),
    });
  } catch {
    // StrictMode may abort its first development-only request.
  }
}
function installTelemetry(
  page: Page,
  records: Map<Request, RequestRecord>,
  consoleErrors: string[],
  pageErrors: string[],
) {
  page.on("request", (request) => {
    if (!request.url().includes(apiRoot)) return;
    const path = apiPath(request.url());
    records.set(request, {
      method: request.method(),
      url: request.url(),
      path,
      operationId: operationIdFor(request.method(), path),
      status: null,
      failure: null,
    });
  });
  page.on("response", (response) => {
    const record = records.get(response.request());
    if (record) record.status = response.status();
  });
  page.on("requestfailed", (request) => {
    const record = records.get(request);
    if (record) record.failure = request.failure()?.errorText ?? "request_failed";
  });
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
}
async function installFixtures(page: Page, scenario: ScenarioName) {
  await page.route(ownedAvatarUrl, async (route) => {
    await route.fulfill({ status: 200, contentType: "image/png", body: ownedAvatarPng });
  });
  await page.route("**" + apiRoot + "/**", async (route) => {
    const request = route.request();
    const path = apiPath(request.url());
    const operationId = operationIdFor(request.method(), path);
    if (request.method() !== "GET") {
      await json(route, 405, errorBody("method_not_allowed", "Evidence is read-only."));
      return;
    }
    if (path === "/session") {
      await json(route, 200, {
        schemaVersion: "media_web_business_pages_v2",
        revision: 1,
        session: {
          publicUserId: "22222222-2222-4222-8222-222222222222",
          organizationName: null,
          workspaceMode: "personal_web",
          editorMode: "web_edit",
          bodyAuthority: "internal",
          memberRole: "owner",
          organizationConnection: "not_applicable",
          installationConnection: "not_applicable",
          role: "ordinary",
          maintainer: false,
          csrfToken: "b02-full-shell-fixture-csrf",
          expiresAt: "2026-08-08T00:00:00+00:00",
          schemaVersion: "media_web_business_pages_v2",
        },
      });
      return;
    }
    if (path === "/capabilities") {
      await json(route, 200, {
        schemaVersion: "media_capability_catalog_v1",
        version: "b02-full-shell-fixture",
        capabilities: [],
      });
      return;
    }
    if (path === "/tasks") {
      await json(route, 200, { tasks: [] });
      return;
    }
    if (!operationId || !b02Operations.has(operationId)) {
      await json(route, 404, errorBody("unhandled_fixture", "Unexpected operation."));
      return;
    }
    if (scenario === "loading") {
      await json(route, 200, listResponse([]), 1500);
      return;
    }
    if (scenario === "permission") {
      await json(route, 403, errorBody("forbidden", "当前会话没有该业务投影的读取权限。"));
      return;
    }
    if (scenario === "error") {
      await json(route, 500, errorBody("internal_error", "业务投影暂时不可用。"));
      return;
    }
    if (scenario === "partial" && operationId === "listTrackRelationships") {
      await json(route, 503, errorBody("internal_error", "关系投影暂时不可用。"));
      return;
    }
    await json(route, 200, fixture(operationId, scenario === "empty"));
  });
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
        name: "b02-real-media-index",
        configureServer(viteServer) {
          viteServer.middlewares.use(async (request, response, next) => {
            const path = new URL(request.url ?? "/", "http://127.0.0.1").pathname;
            if (
              path !== mediaBase &&
              path !== mediaBase + "/" &&
              path !== mediaBase + "/tracks"
            ) {
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
    server: { host: "127.0.0.1", port: 18052, strictPort: true },
  });
  await server.listen();
  return server;
}
async function goto(page: Page) {
  let last: unknown = null;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      await page.goto(pageUrl, { waitUntil: "domcontentloaded", timeout: 4000 });
      return;
    } catch (error) {
      last = error;
      await delay(250);
    }
  }
  throw last instanceof Error ? last : new Error("Media full shell did not start.");
}
async function fit(page: Page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    const body = document.body;
    const internalScrollers = Array.from(
      document.querySelectorAll("[data-page-list], [data-long-content], [data-page-inspector]"),
    ).map((element) => {
      const node = element as HTMLElement;
      const style = getComputedStyle(node);
      return {
        marker:
          node.getAttribute("data-page-list") ??
          node.getAttribute("data-long-content") ??
          node.getAttribute("data-page-inspector") ??
          node.tagName.toLowerCase(),
        clientWidth: node.clientWidth,
        scrollWidth: node.scrollWidth,
        clientHeight: node.clientHeight,
        scrollHeight: node.scrollHeight,
        overflowX: style.overflowX,
        overflowY: style.overflowY,
        scrollable: node.scrollWidth > node.clientWidth || node.scrollHeight > node.clientHeight,
      };
    });
    return {
      innerWidth: window.innerWidth,
      innerHeight: window.innerHeight,
      horizontalOverflow: Math.max(0, root.scrollWidth - root.clientWidth),
      verticalOverflow: Math.max(0, root.scrollHeight - root.clientHeight),
      bodyHorizontalOverflow: Math.max(0, body.scrollWidth - root.clientWidth),
      internalScrollers,
    };
  });
}
async function assertRelationshipLayout(page: Page, mobile: boolean) {
  const layout = await page.evaluate(() => {
    const list = document.querySelector<HTMLElement>(
      '[role="tabpanel"][aria-label="对标账号"] [data-page-list="benchmark-accounts"]',
    );
    const panelBody = list?.parentElement;
    if (!list || !panelBody) return null;
    const listRect = list.getBoundingClientRect();
    const bodyRect = panelBody.getBoundingClientRect();
    const style = getComputedStyle(list);
    const bodyStyle = getComputedStyle(panelBody);
    const paddingBottom = Number.parseFloat(bodyStyle.paddingBottom) || 0;
    return {
      itemCount: list.children.length,
      clientHeight: list.clientHeight,
      scrollHeight: list.scrollHeight,
      overflowY: style.overflowY,
      maxHeight: style.maxHeight,
      unusedBodySpace: Math.max(
        0,
        bodyRect.bottom - paddingBottom - listRect.bottom,
      ),
    };
  });
  if (!layout) throw new Error("relationship layout was not rendered");
  const expectedRelationshipCount = relationships.filter(
    (item) => item.publicCreatorId !== account.publicAccountId,
  ).length;
  if (layout.itemCount !== expectedRelationshipCount) {
    throw new Error("relationship fixture count mismatch: " + JSON.stringify(layout));
  }
  if (mobile) {
    if (layout.scrollHeight > layout.clientHeight + 1) {
      throw new Error("mobile relationship list is clipped: " + JSON.stringify(layout));
    }
  } else {
    if (layout.scrollHeight <= layout.clientHeight) {
      throw new Error("desktop relationship list is not the scroll owner: " + JSON.stringify(layout));
    }
    if (layout.overflowY !== "auto") {
      throw new Error("desktop relationship list overflow changed: " + JSON.stringify(layout));
    }
    if (layout.unusedBodySpace > 2) {
      throw new Error("desktop relationship panel has unused vertical space: " + JSON.stringify(layout));
    }
  }
  return layout;
}
function expectedIds(name: ScenarioName): OperationId[] {
  const ids: OperationId[] = [
    "listTracks",
    "listCreators",
    "listTrackRelationships",
    "listOwnedAccounts",
  ];
  return name === "populated"
    ? [...ids, "getOwnedAccount", "getCreator"]
    : ids;
}
async function capture(
  browser: Awaited<ReturnType<typeof chromium.launch>>,
  name: ScenarioName,
  pageState: string,
  viewport: { width: number; height: number },
) {
  const mobile = viewport.width === 390;
  const context = await browser.newContext({
    viewport,
    deviceScaleFactor: 1,
    isMobile: mobile,
    hasTouch: mobile,
  });
  const page = await context.newPage();
  const records = new Map<Request, RequestRecord>();
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  installTelemetry(page, records, consoleErrors, pageErrors);
  await installFixtures(page, name);
  try {
    await goto(page);
    await assertMediaShell(page, consoleErrors, pageErrors);
    await assertVisible(
      page.getByRole("navigation", { name: "主导航" }),
      "the real MediaStudioApp navigation",
    );
    await assertVisible(
      page.getByRole("link", { name: "账号与赛道", exact: true }),
      "the Tracks route in the real router",
    );
    const main = page.locator("main.fidelity-page");
    await assertAttribute(main, "data-page-state", pageState, "page state " + pageState);
    const capturedPageState = await main.getAttribute("data-page-state");
    if (name === "empty") {
      await assertVisible(
        page.getByText("暂无自有账号", { exact: true }),
        "the empty owned-account state",
      );
      await assertCount(
        page.getByText("没有符合条件的账号", { exact: true }),
        0,
        "the empty owned-account state must not render a duplicate filter-empty state",
      );
    }
    if (name === "permission") {
      await assertVisible(
        page.getByText("无权查看", { exact: true }).first(),
        "the permission state",
      );
    }
    if (name === "error") {
      await assertVisible(
        page.getByText("读取失败", { exact: true }).first(),
        "the error state",
      );
    }
    if (name === "partial") {
      const notice = page.locator("[data-page-partial]");
      await assertVisible(notice, "the partial state");
      await assertContainsText(
        notice,
        "账号归属暂时无法读取",
        "the named failed projection resource",
      );
      await assertContainsText(
        notice,
        "刷新",
        "the partial-state retry action",
      );
      await assertVisible(
        page.getByRole("tab", { name: "赛道概览", exact: true }),
        "the successful tracks projection beside the failure",
      );
    }
    if (name === "populated") {
      const accountButton = page.locator('[data-page-list="owned-accounts"] button').first();
      await assertVisible(accountButton, "the owned account fixture");
      await assertCount(
        page.getByText(/Handle/i),
        0,
        "internal Handle terminology must not be user-visible",
      );
      await assertContainsText(
        accountButton,
        "平台账号 @qinghua-runner",
        "the owned-account platform identifier",
      );
      await assertCount(
        page.getByText(/platform-b02-001|platformAccountId|publicAccountId/i),
        0,
        "internal account identifiers must not be user-visible",
      );
      await assertContainsText(accountButton, "运营中", "the owned-account operational status");
      await assertContainsText(accountButton, "负责人：王思尧", "the owned-account responsibility");
      const listAvatarImage = accountButton.locator("[data-account-avatar-image]");
      await waitForValue(
        () => listAvatarImage.evaluate((image: HTMLImageElement) => image.naturalWidth),
        (value) => value > 0,
        "the owned-account list avatar image",
      );
      await accountButton.click();
      const accountInspector = page.locator("[data-page-account-detail]");
      await assertContainsText(
        accountInspector,
        "运营状态",
        "the owned-account operations inspector",
      );
      await assertContainsText(
        accountInspector,
        "平台账号",
        "the business-facing platform account label",
      );
      for (const section of ["账号身份", "组织责任", "运营定位", "运营状态", "数据状态"]) {
        await assertContainsText(accountInspector, section, `the owned-account ${section} section`);
      }
      await assertContainsText(accountInspector, "内容运营组", "the owned-account team");
      await assertContainsText(accountInspector, "飞书达人账号档案", "the owned-account data source");
      await assertCount(
        accountInspector.getByText(/等待授权|授权异常|重新授权|授权状态|OAuth/i),
        0,
        "retired authorization semantics must not be visible",
      );
      await assertCount(
        accountInspector.getByText(/账号策略|生成账号策略/),
        0,
        "owned-account strategy placeholders must not be visible",
      );
      for (const placeholderAction of ["同步数据", "编辑资料", "停用"]) {
        await assertCount(
          accountInspector.getByRole("button", { name: placeholderAction, exact: true }),
          0,
          `the unavailable ${placeholderAction} placeholder`,
        );
      }
      const detailAvatar = accountInspector.locator('[data-account-avatar][data-avatar-size="detail"]');
      const detailAvatarImage = detailAvatar.locator("[data-account-avatar-image]");
      await waitForValue(
        () => detailAvatarImage.evaluate((image: HTMLImageElement) => image.naturalWidth),
        (value) => value > 0,
        "the owned-account detail avatar image",
      );
      await page.screenshot({
        path: join(runDir, `owned-populated-${viewport.width}x${viewport.height}.png`),
      });
      const avatarBoundsBefore = await detailAvatar.boundingBox();
      await detailAvatarImage.evaluate((image) => image.dispatchEvent(new Event("error")));
      await assertAttribute(detailAvatar, "data-avatar-state", "fallback", "the broken-avatar fallback");
      const avatarBoundsAfter = await detailAvatar.boundingBox();
      if (
        !avatarBoundsBefore
        || !avatarBoundsAfter
        || avatarBoundsBefore.width !== avatarBoundsAfter.width
        || avatarBoundsBefore.height !== avatarBoundsAfter.height
      ) {
        throw new Error(
          "owned-account avatar fallback changed layout: "
          + JSON.stringify({ avatarBoundsBefore, avatarBoundsAfter }),
        );
      }
      await page.getByRole("tab", { name: "赛道概览", exact: true }).click();
      const trackButton = page.locator('[data-page-list="tracks"] button').first();
      await assertVisible(trackButton, "the track fixture");
      await assertContainsText(
        trackButton,
        "对标账号 7",
        "the track overview benchmark count excluding the owned identity",
      );
      await trackButton.click();
      await assertContainsText(
        page.locator('section[aria-label="赛道详情"]'),
        "平台覆盖",
        "the track layout inspector",
      );
      await assertContainsText(
        page.locator('section[aria-label="赛道详情"]'),
        "对标账号7",
        "the track inspector benchmark count excluding the owned identity",
      );
      await page.getByRole("button", { name: /查看对标账号/ }).click();
      await assertVisible(
        page.getByText(`赛道：${track.name}`, { exact: true }),
        "the benchmark track context filter",
      );
      await page.getByRole("tab", { name: /已关注 7/ }).click();
      await assertCount(
        page.getByText("长内容账号 1", { exact: true }),
        0,
        "an explicitly owned identity must not repeat in the benchmark list",
      );
      const creatorButton = page.locator('[data-page-list="benchmark-accounts"] button').first();
      await assertVisible(creatorButton, "the creator fixture");
      await creatorButton.click();
      await assertContainsText(
        page.locator('section[aria-label="对标账号详情"]'),
        "代表内容 / 资料凭证",
        "the benchmark evidence inspector",
      );
    }
    const screenshot = join(
      runDir,
      name + "-" + viewport.width + "x" + viewport.height + ".png",
    );
    await page.screenshot({ path: screenshot });
    const ids = expectedIds(name);
    await waitForValue(
      async () =>
        ids.filter((id) =>
          Array.from(records.values()).some(
            (record) => record.operationId === id && record.status !== null,
          ),
        ).length,
      (value) => value === ids.length,
      "generated operation responses for " + name,
    );
    const pageFit = await fit(page);
    const relationshipLayout = name === "populated"
      ? await assertRelationshipLayout(page, mobile)
      : null;
    if (pageFit.horizontalOverflow !== 0 || pageFit.bodyHorizontalOverflow !== 0) {
      throw new Error("horizontal overflow: " + JSON.stringify(pageFit));
    }
    if (!mobile && pageFit.verticalOverflow !== 0) {
      throw new Error("desktop vertical overflow: " + JSON.stringify(pageFit));
    }
    if (
      name === "populated" &&
      !mobile &&
      !pageFit.internalScrollers.some((item) => item.scrollable)
    ) {
      throw new Error("populated state has no bounded internal scroller");
    }
    const fatalConsoleErrors = consoleErrors.filter(
      (message) => !message.startsWith("Failed to load resource:"),
    );
    if (fatalConsoleErrors.length || pageErrors.length) {
      throw new Error(JSON.stringify({ consoleErrors, fatalConsoleErrors, pageErrors }));
    }
    const operationIds = Array.from(
      new Set(
        Array.from(records.values())
          .filter((record) => record.operationId !== null)
          .map((record) => record.operationId),
      ),
    );
    return {
      scenario: name,
      viewport,
      pageState: capturedPageState,
      screenshot,
      fit: pageFit,
      relationshipLayout,
      consoleErrors,
      fatalConsoleErrors,
      pageErrors,
      requestTelemetry: Array.from(records.values()),
      generatedOperationIds: operationIds,
    };
  } finally {
    await context.close();
  }
}
async function main() {
  mkdirSync(runDir, { recursive: true });
  const sourceHashes = Object.fromEntries(
    Object.entries(sourceFiles).map(([label, path]) => [
      label,
      createHash("sha256").update(readFileSync(path)).digest("hex"),
    ]),
  );
  const results: Array<Record<string, unknown>> = [];
  const failures: Array<Record<string, unknown>> = [];
  let server: ViteDevServer | null = null;
  let browser: Awaited<ReturnType<typeof chromium.launch>> | null = null;
  let serverStopped = externalTargetUrl !== null;
  try {
    server = externalTargetUrl ? null : await startServer();
    browser = await chromium.launch({ headless: true });
    for (const viewport of viewports) {
      for (const [name, pageState] of scenarios) {
        try {
          results.push(await capture(browser, name, pageState, viewport));
        } catch (error) {
          const failure = {
            scenario: name,
            viewport,
            error: error instanceof Error ? error.stack ?? error.message : String(error),
          };
          failures.push(failure);
          results.push(failure);
        }
      }
    }
  } finally {
    if (browser) await browser.close();
    if (server) {
      await server.close();
      serverStopped = true;
    }
  }
  writeFileSync(
    join(runDir, "source-sha256.txt"),
    Object.entries(sourceHashes).map(([label, hash]) => hash + "  " + label).join("\n") + "\n",
  );
  const report = {
    ok: failures.length === 0,
    versionTuple: tuple,
    node: "B02",
    sourceServer: pageUrl,
    serverMode: externalTargetUrl ? "external-target" : "local-vite",
    harness:
      "index.media.html -> src/media/main.tsx -> MediaStudioApp -> ProductShell -> Routes -> TracksPage",
    fixtureMode: "browser routes only; generated callBusinessOperation paths; no product writes",
    browserSemaphore: 4,
    viewports,
    requiredStates: scenarios.map(([name]) => name),
    serverStarted: server !== null,
    serverStopped,
    sourceHashes,
    results,
    failures,
  };
  writeFileSync(join(runDir, "full-shell-report.json"), JSON.stringify(report, null, 2) + "\n");
  writeFileSync(
    join(runDir, "verification.txt"),
    [
      "B02 real MediaStudioApp full-shell evidence",
      "versionTuple=" + tuple,
      "node=B02",
      "browserSemaphore=4",
      "viewports=1920x1088,390x844",
      "states=loading,empty,populated,partial,error,permission",
      "result=" + (failures.length ? "FAILED" : "VERIFIED"),
      "serverStopped=" + String(serverStopped),
      "report=" + join(runDir, "full-shell-report.json"),
    ].join("\n") + "\n",
  );
  console.log(JSON.stringify({
    ok: failures.length === 0,
    report: join(runDir, "full-shell-report.json"),
    screenshotCount: results.filter((item) => "screenshot" in item).length,
    failures,
  }, null, 2));
  if (failures.length) process.exitCode = 1;
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
