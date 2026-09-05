import { existsSync } from "node:fs";
import { chromium, type Browser, type BrowserContext, type Page } from "playwright";

const baseUrl = (
  process.env.MEDIA_CREATOR_UX_QA_URL ??
  process.env.MEDIA_ROLE_QA_URL ??
  "https://mediapilot.cloud/openclaw/media"
).replace(/\/$/, "");
const timeoutMs = Number(process.env.MEDIA_CREATOR_UX_QA_TIMEOUT_MS ?? 20_000);
const ordinaryStorageState = firstEnv(
  "MEDIA_CREATOR_UX_QA_ORDINARY_STORAGE_STATE",
  "MEDIA_WEB_QA_ORDINARY_STORAGE_STATE",
  "MEDIA_WEB_QA_USER_STORAGE_STATE",
);
const adminStorageState = firstEnv(
  "MEDIA_CREATOR_UX_QA_ADMIN_STORAGE_STATE",
  "MEDIA_WEB_QA_ADMIN_STORAGE_STATE",
);
const ordinaryCookieHeader = firstEnv(
  "MEDIA_CREATOR_UX_QA_ORDINARY_COOKIE",
  "MEDIA_WEB_QA_USER_A_COOKIE",
  "MEDIA_WEB_QA_COOKIE",
);
const adminCookieHeader = firstEnv(
  "MEDIA_CREATOR_UX_QA_ADMIN_COOKIE",
  "MEDIA_WEB_QA_ADMIN_COOKIE",
);

function firstEnv(...names: string[]): string {
  for (const name of names) {
    const value = process.env[name]?.trim();
    if (value) return value;
  }
  return "";
}

function requireContract(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function appUrl(path: string): string {
  return `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}

function parseCookieHeader(header: string): Array<{ name: string; value: string }> {
  requireContract(header !== "", "authenticated cookie-header input is missing");
  return header.split(";").map((part) => part.trim()).filter(Boolean).map((part) => {
    const separator = part.indexOf("=");
    requireContract(separator > 0, "authenticated cookie-header input is invalid");
    return { name: part.slice(0, separator), value: part.slice(separator + 1) };
  });
}

async function createContext(
  browser: Browser,
  role: "ordinary" | "admin",
): Promise<BrowserContext> {
  const storageState = role === "admin" ? adminStorageState : ordinaryStorageState;
  const cookieHeader = role === "admin" ? adminCookieHeader : ordinaryCookieHeader;
  if (storageState) {
    requireContract(existsSync(storageState), `${role} storage-state path does not exist`);
    return browser.newContext({ storageState, viewport: { width: 1440, height: 1000 } });
  }
  requireContract(cookieHeader !== "", `${role} authentication input is missing`);
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const base = new URL(baseUrl);
  await context.addCookies(parseCookieHeader(cookieHeader).map((cookie) => ({
    ...cookie,
    domain: base.hostname,
    path: "/openclaw/",
    httpOnly: true,
    secure: base.protocol === "https:",
    sameSite: "Lax" as const,
  })));
  return context;
}

function trackApiRequests(page: Page): string[] {
  const requests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/openclaw/media/api/")) {
      requests.push(`${request.method()} ${url.pathname}${url.search}`);
    }
  });
  return requests;
}

async function gotoPage(page: Page, path: string, heading: string): Promise<void> {
  await page.goto(appUrl(path), { waitUntil: "domcontentloaded", timeout: timeoutMs });
  await page.getByRole("heading", { name: heading, exact: true }).waitFor({ timeout: timeoutMs });
}

async function assertAdminPanel(page: Page, requests: string[]): Promise<void> {
  await gotoPage(page, "/admin/access", "用户与准入");
  const panel = page.locator('[data-admin-cookie-panel]');
  await panel.waitFor({ timeout: timeoutMs });
  await panel.getByRole("button", { name: /复制.*配置命令/ }).first().waitFor({ timeout: timeoutMs });
  const panelText = await panel.innerText();
  for (const expected of [
    "平台会话凭据",
    "抖音",
    "小红书",
    "服务器端配置脚本",
    "save_platform_cookie_secret.py",
    "不会接收、显示或下发 Cookie 内容",
  ]) {
    requireContract(panelText.includes(expected), "admin cookie status UI is incomplete");
  }
  requireContract(requests.includes("GET /openclaw/media/api/admin/platform-cookies"), "admin cookie status API was not requested");
  requireContract(
    !(await page.locator('input, textarea').evaluateAll((elements) =>
      elements.some((element) => /cookie|token|secret|csrf/i.test(`${element.getAttribute("name") ?? ""} ${element.getAttribute("aria-label") ?? ""} ${element.getAttribute("placeholder") ?? ""}`)),
    )),
    "admin cookie UI exposes a credential input",
  );
}

async function assertOrdinaryBoundary(page: Page, requests: string[]): Promise<void> {
  await gotoPage(page, "/tracks", "账号与赛道");
  const tracksText = (await page.locator("body").innerText()).toLowerCase();
  for (const forbidden of ["cookie", "token", "secret", "csrf", "平台会话凭据", "platform-cookies"]) {
    requireContract(!tracksText.includes(forbidden), "ordinary page renders protected credential information");
  }
  requireContract(
    await page.locator('[data-admin-cookie-panel]').count() === 0,
    "ordinary page renders the admin cookie panel",
  );
  requireContract(!requests.some((request) => request.includes("/admin/")), "ordinary page requested an admin API");

  await page.goto(appUrl("/admin/access"), { waitUntil: "domcontentloaded", timeout: timeoutMs });
  await page.getByRole("heading", { name: "无权访问此页面", exact: true }).waitFor({ timeout: timeoutMs });
  requireContract(
    await page.locator('[data-admin-cookie-panel]').count() === 0,
    "ordinary session reached the admin cookie panel",
  );
  const redirectedText = (await page.locator("body").innerText()).toLowerCase();
  for (const forbidden of ["cookie", "token", "secret", "csrf", "平台会话凭据", "platform-cookies"]) {
    requireContract(!redirectedText.includes(forbidden), "ordinary admin redirect renders protected credential information");
  }
  requireContract(!requests.some((request) => request.includes("/admin/")), "ordinary session requested an admin API after redirect");
}

type Creator = {
  publicCreatorId: string;
  accountName: string;
  avatarUrl: string | null;
  profileUrl: string | null;
};

function creatorItems(payload: unknown): Creator[] {
  if (!payload || typeof payload !== "object" || !Array.isArray((payload as { items?: unknown }).items)) {
    throw new Error("creator list response is invalid");
  }
  return (payload as { items: unknown[] }).items.filter((item): item is Creator => {
    if (!item || typeof item !== "object") return false;
    const creator = item as Partial<Creator>;
    return typeof creator.publicCreatorId === "string" && typeof creator.accountName === "string" &&
      (typeof creator.avatarUrl === "string" || creator.avatarUrl === null) &&
      (typeof creator.profileUrl === "string" || creator.profileUrl === null);
  });
}

async function selectCreator(page: Page, creator: Creator): Promise<void> {
  const listCard = page.locator('[data-page-list="benchmark-accounts"] button').filter({ hasText: creator.accountName }).first();
  await listCard.waitFor({ timeout: timeoutMs });
  await listCard.click();
  await page.locator('section[aria-label="对标账号详情"]').waitFor({ timeout: timeoutMs });
}

async function assertCreatorFlow(page: Page): Promise<number> {
  await gotoPage(page, "/tracks", "账号与赛道");
  const response = await page.context().request.get(appUrl("/api/creators?pageSize=50"));
  requireContract(response.ok(), `production creator API request failed: ${response.status()}`);
  const creators = creatorItems(await response.json());
  requireContract(creators.length > 0, "production creator list is empty");
  requireContract(
    creators.some((creator) => creator.accountName === "清华AI小王冲一级"),
    "target Chinese creator is missing from the production API",
  );
  requireContract(
    creators.every((creator) => Boolean(creator.avatarUrl)),
    "production creator data still contains an avatar backfill gap",
  );
  const avatarCreator = creators.find((creator) => Boolean(creator.avatarUrl));
  const captureCreator = creators.find((creator) => Boolean(creator.profileUrl));
  requireContract(Boolean(avatarCreator), "production creator data has no avatar URL to verify");
  requireContract(Boolean(captureCreator), "production creator data has no profile URL to verify capture");

  await page.getByRole("tab", { name: "对标账号", exact: true }).click();
  const followedTab = page.getByRole("tab", { name: /已关注 \d+/ });
  await followedTab.waitFor({ timeout: timeoutMs });
  await followedTab.click();
  await page.locator('[data-page-list="benchmark-accounts"]').waitFor({ timeout: timeoutMs });
  const benchmarkList = page.locator('[data-page-list="benchmark-accounts"]');
  await benchmarkList.waitFor({ timeout: timeoutMs });
  const visibleCreator = creators.find((creator) => creator.accountName !== "清华AI小王冲一级") ?? creators[0];
  await selectCreator(page, visibleCreator!);
  const inspector = page.locator('section[aria-label="对标账号详情"]');
  const avatarImage = inspector.locator('img[class*="avatarImage"]');
  await avatarImage.waitFor({ timeout: timeoutMs });
  const renderedAvatarSrc = await avatarImage.getAttribute("src");
  requireContract(Boolean(renderedAvatarSrc && /^https?:\/\//.test(renderedAvatarSrc)), "creator avatar image source is missing");
  requireContract((await avatarImage.getAttribute("referrerpolicy")) === "no-referrer", "creator avatar image referrer policy is incorrect");

  await avatarImage.evaluate((image) => image.dispatchEvent(new Event("error")));
  await avatarImage.waitFor({ state: "detached", timeout: timeoutMs });
  requireContract(
    await inspector.locator('[class*="avatar"] svg').count() > 0,
    "creator avatar error did not render the fallback icon",
  );

  const captureVisible = captureCreator && await page.locator('[data-page-list="benchmark-accounts"] button')
    .filter({ hasText: captureCreator.accountName }).count();
  if (captureVisible && captureCreator!.publicCreatorId !== visibleCreator!.publicCreatorId) {
    await selectCreator(page, captureCreator!);
  }
  const captureButton = inspector.getByRole("button", { name: "一键采集资料", exact: true });
  await captureButton.waitFor({ timeout: timeoutMs });
  requireContract(await captureButton.isEnabled(), "creator capture action is disabled despite a profile URL");
  await captureButton.click();

  const drawer = page.getByRole("complementary", { name: "Media 任务工作区" });
  await drawer.waitFor({ timeout: timeoutMs });
  const selectedCapability = drawer.locator(
    'button.capability-option.is-selected[data-capability-id="creator_profile_upsert"]',
  );
  await selectedCapability.waitFor({ timeout: timeoutMs });
  const activeVariant = drawer.locator(".variant-control button.active");
  await activeVariant.waitFor({ timeout: timeoutMs });
  requireContract(/主页链接|候选/.test(await activeVariant.innerText()), "capture did not select url_candidate");
  const capturedProfileUrl = await drawer.locator("#task-field-profile_url").inputValue();
  requireContract(/^https?:\/\//.test(capturedProfileUrl), "capture did not prefill a creator profile URL");
  return creators.length;
}

async function run(): Promise<void> {
  requireContract(Number.isFinite(timeoutMs) && timeoutMs >= 1_000, "QA timeout must be at least one second");
  const browser = await chromium.launch({ headless: true });
  let adminContext: BrowserContext | undefined;
  let ordinaryContext: BrowserContext | undefined;
  try {
    adminContext = await createContext(browser, "admin");
    ordinaryContext = await createContext(browser, "ordinary");
    const adminPage = await adminContext.newPage();
    const ordinaryPage = await ordinaryContext.newPage();
    const adminRequests = trackApiRequests(adminPage);
    const ordinaryRequests = trackApiRequests(ordinaryPage);
    await assertAdminPanel(adminPage, adminRequests);
    await assertOrdinaryBoundary(ordinaryPage, ordinaryRequests);
    const creatorCount = await assertCreatorFlow(ordinaryPage);
    console.log(`qa:creator-avatar-cookie-production: PASS admin-status=1 ordinary-boundary=1 avatars=${creatorCount}/${creatorCount} avatar-fallback=1 creator-capture=1`);
  } finally {
    await adminContext?.close();
    await ordinaryContext?.close();
    await browser.close();
  }
}

run().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : "unknown QA failure";
  console.error(`qa:creator-avatar-cookie-production: FAIL ${message}`);
  process.exitCode = 1;
});
