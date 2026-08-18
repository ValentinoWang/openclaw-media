import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { chromium, type BrowserContext, type Page } from "playwright";

const baseUrl = (
  process.env.MEDIA_WEB_QA_URL ?? "http://127.0.0.1/openclaw/media"
).replace(/\/$/, "");
const outputDir = resolve(
  process.env.MEDIA_WEB_QA_OUTPUT ??
    "/home/ubuntu/obsidian-日记/公共开发集/public/2026-07-29/sub2api-openclaw-multitenant-billing/browser-evidence",
);
const cookies = {
  userA:
    process.env.MEDIA_WEB_QA_USER_A_COOKIE ??
    process.env.MEDIA_WEB_QA_COOKIE ??
    "",
  userB: process.env.MEDIA_WEB_QA_USER_B_COOKIE ?? "",
  admin: process.env.MEDIA_WEB_QA_ADMIN_COOKIE ?? "",
};
const runId = process.env.MEDIA_WEB_QA_RUN_ID ?? "";
const userASentinel = process.env.MEDIA_WEB_QA_USER_A_SENTINEL ?? "";
const targetTenantId = process.env.MEDIA_WEB_QA_TARGET_TENANT_ID ?? "";

type Evidence = {
  ok: boolean;
  checks: string[];
  failures: string[];
  apiRequests: Record<string, string[]>;
};

const evidence: Evidence = {
  ok: false,
  checks: [],
  failures: [],
  apiRequests: {},
};
mkdirSync(outputDir, { recursive: true });

function require(condition: boolean, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function apiPath(url: string): string | null {
  const parsed = new URL(url);
  const marker = "/openclaw/media/api/";
  const index = parsed.pathname.indexOf(marker);
  return index === -1
    ? null
    : `${parsed.pathname.slice(index + marker.length - 1)}${parsed.search}`;
}

function observe(page: Page, label: string): string[] {
  const requests: string[] = [];
  evidence.apiRequests[label] = requests;
  page.on("request", (request) => {
    const path = apiPath(request.url());
    if (path) requests.push(`${request.method()} ${path}`);
  });
  page.on("response", (response) => {
    const path = apiPath(response.url());
    if (!path || response.status() < 400) return;
    if (
      label === "unauthenticated" &&
      path === "/session" &&
      response.status() === 401
    )
      return;
    evidence.failures.push(
      `${label} received HTTP ${response.status()} from ${path}`,
    );
  });
  page.on("pageerror", (error) =>
    evidence.failures.push(`${label} page error: ${error.message}`),
  );
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      !message.text().startsWith("Failed to load resource:")
    ) {
      evidence.failures.push(`${label} console error: ${message.text()}`);
    }
  });
  return requests;
}

function parseCookieHeader(
  header: string,
): Array<{ name: string; value: string }> {
  require(header.trim() !== "", "authenticated QA cookies are required");
  return header
    .split(";")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const separator = part.indexOf("=");
      require(separator > 0, "invalid QA cookie header");
      return {
        name: part.slice(0, separator),
        value: part.slice(separator + 1),
      };
    });
}

async function installCookies(context: BrowserContext, header: string) {
  const base = new URL(baseUrl);
  await context.addCookies(
    parseCookieHeader(header).map((cookie) => ({
      ...cookie,
      domain: base.hostname,
      path: "/openclaw/",
      httpOnly: true,
      secure: base.protocol === "https:",
      sameSite: "Lax" as const,
    })),
  );
}

async function assertNoOverflow(page: Page, label: string) {
  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  require(overflow <= 1, `${label} has ${overflow}px horizontal overflow`);
}

async function assertNoSensitivePresentation(
  page: Page,
  label: string,
  allowUpstreamName = false,
) {
  const text = await page.locator("body").innerText();
  const lower = text.toLowerCase();
  for (const token of [
    "/home/",
    "traceback",
    "stack trace",
    "access_token",
    "api_key",
    "secret://",
    "secret_ref",
    "raw_prompt",
    "raw_response",
    "record_id",
    "tenant-key-ref",
    "模型 Key",
  ]) {
    require(!lower.includes(
      token,
    ), `${label} renders forbidden token ${token}`);
  }
  if (!allowUpstreamName)
    require(!lower.includes(
      "sub2api",
    ), `${label} renders the upstream provider name`);
  require(!/https?:\/\/[^\s]+\/base\//i.test(
    text,
  ), `${label} renders a Feishu Base URL`);
  require(!/https?:\/\/[^\s]+\/(?:bitable|table|view)\//i.test(
    text,
  ), `${label} renders a Feishu table/view URL`);
}

async function persistentValues(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const values: string[] = [];
    for (const storage of [localStorage, sessionStorage]) {
      for (let index = 0; index < storage.length; index += 1) {
        const key = storage.key(index);
        if (key) values.push(`${key}=${storage.getItem(key) ?? ""}`);
      }
    }
    return values;
  });
}

function countRequests(requests: string[], pattern: RegExp): number {
  return requests.filter((request) => pattern.test(request)).length;
}

async function unauthenticatedCheck(
  browser: Awaited<ReturnType<typeof chromium.launch>>,
) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();
  const requests = observe(page, "unauthenticated");
  await page.goto(`${baseUrl}/overview`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "需要登录" }).waitFor();
  require(requests.length === 1 &&
    requests[0] ===
      "GET /session", `unauthenticated shell fetched business data: ${requests.join(", ")}`);
  await assertNoSensitivePresentation(page, "unauthenticated shell");
  evidence.checks.push("unauthenticated shell only requests session");
  await context.close();
}

async function registrationPolicyCheck(
  browser: Awaited<ReturnType<typeof chromium.launch>>,
) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();
  const policyResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/openclaw/auth/registration-policy",
  );
  await page.goto(new URL("/openclaw/media/register", baseUrl).toString(), {
    waitUntil: "networkidle",
  });
  const response = await policyResponse;
  require(response.ok(), `registration policy returned HTTP ${response.status()}`);
  const payload = (await response.json()) as {
    registrationPolicyMode?: string;
  };
  require(payload.registrationPolicyMode === "controlled" ||
    payload.registrationPolicyMode ===
      "open", "registration policy mode is invalid");
  const admission = await page.locator("#admission-field").evaluate((field) => ({
    hidden: (field as HTMLElement).hidden,
    required: (field.querySelector("input") as HTMLInputElement).required,
  }));
  const controlled = payload.registrationPolicyMode === "controlled";
  require(admission.hidden === !controlled,
    `admission field visibility does not match ${payload.registrationPolicyMode} policy`);
  require(admission.required === controlled,
    `admission field requirement does not match ${payload.registrationPolicyMode} policy`);
  evidence.checks.push(
    "registration page matches the canonical controlled/open policy",
  );
  await context.close();
}

async function exerciseJobDetail(page: Page, requests: string[]) {
  if (!runId) return;
  await page.goto(`${baseUrl}/runs/${encodeURIComponent(runId)}`, {
    waitUntil: "networkidle",
  });
  await page.getByRole("heading", { name: /创作与交付.*运行详情/ }).waitFor();
  require(countRequests(requests, new RegExp(`GET /jobs/${runId}$`)) ===
    1, "run detail did not issue exactly one base request");
  require(countRequests(requests, new RegExp(`GET /runs/${runId}`)) === 0,
    "run detail consumed the retired runs endpoint");
  evidence.checks.push("LocalAgentJob detail loads once through /jobs");
}

async function userCheck(browser: Awaited<ReturnType<typeof chromium.launch>>) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  await installCookies(context, cookies.userA);
  const page = await context.newPage();
  const requests = observe(page, "user-a");
  await page.goto(`${baseUrl}/overview`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "运营总览" }).waitFor();
  const navigation = page.getByRole("navigation", { name: "主导航" });
  for (const label of [
    "平台总览",
    "用户与准入",
    "租户资源",
    "计费运营",
    "上游服务",
  ]) {
    require((await navigation
      .getByRole("link", { name: label, exact: true })
      .count()) === 0, `ordinary user sees administrator navigation: ${label}`);
  }
  require(countRequests(requests, /GET \/dashboard$/) ===
    1, "overview did not request one tenant dashboard");
  require(countRequests(requests, /GET \/runs/) ===
    0, "overview eagerly loaded runs");
  require(countRequests(requests, /GET \/admin\//) ===
    0, "ordinary overview called an admin API");
  await assertNoOverflow(page, "user overview desktop");
  await assertNoSensitivePresentation(page, "user overview desktop");

  await navigation
    .getByRole("link", { name: "创作与交付", exact: true })
    .click();
  await page.getByRole("heading", { name: "创作与交付" }).waitFor();
  require(countRequests(requests, /GET \/jobs\?/) ===
    1, "runs list did not request one summary page");
  if (userASentinel) {
    await page.getByText(userASentinel, { exact: true }).first().waitFor();
  }
  await exerciseJobDetail(page, requests);

  await navigation
    .getByRole("link", { name: "用量与套餐", exact: true })
    .click();
  await page.getByRole("heading", { name: "用量与套餐" }).waitFor();
  require(countRequests(requests, /GET \/billing\/plans$/) ===
    1, "billing did not load the canonical plan catalog");
  await page.getByRole("tab", { name: "余额与套餐", exact: true }).click();
  const plansPanel = page.getByRole("tabpanel", { name: "余额与套餐" });
  const planItems = plansPanel.getByRole("article");
  await planItems.first().waitFor();
  require((await planItems.count()) ===
    6, "billing does not render exactly six plans");
  for (const link of await plansPanel
    .getByRole("link", { name: /\u8d2d\u4e70\u5957\u9910/ })
    .all()) {
    require(((await link.getAttribute("href")) ?? "").startsWith(
      "https://",
    ), "purchase link is not HTTPS");
  }
  await page.getByRole("tab", { name: "兑换记录", exact: true }).click();
  const codeInput = page.getByLabel("卡密", { exact: true });
  await codeInput.waitFor();
  const marker = `qa-card-${Date.now()}`;
  await codeInput.fill(marker);
  require(!(await persistentValues(page)).some((value) =>
    value.includes(marker),
  ), "card plaintext entered browser storage");
  require(!page
    .url()
    .includes(marker), "card plaintext entered browser history/URL");
  await codeInput.fill("");
  await assertNoSensitivePresentation(page, "user billing");
  evidence.checks.push(
    "ordinary user routes are tenant-only and card input is memory-only",
  );

  if (cookies.userB) {
    await context.clearCookies();
    await installCookies(context, cookies.userB);
    await page.goto(`${baseUrl}/overview`, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "运营总览" }).waitFor();
    require(countRequests(requests, /GET \/session$/) >=
      2, "identity switch did not re-read the session");
    if (userASentinel) {
      await navigation
        .getByRole("link", { name: "创作与交付", exact: true })
        .click();
      await page.getByRole("heading", { name: "创作与交付" }).waitFor();
      require(!(await page.locator("body").innerText()).includes(
        userASentinel,
      ), "user B renders user A run sentinel after identity switch");
    }
    evidence.checks.push("A to B identity switch re-reads tenant state");
  }
  await page.screenshot({
    path: resolve(outputDir, "desktop-user-billing.png"),
    fullPage: true,
  });
  await context.close();
}

async function adminCheck(
  browser: Awaited<ReturnType<typeof chromium.launch>>,
) {
  if (!cookies.admin) return;
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  await installCookies(context, cookies.admin);
  const page = await context.newPage();
  const requests = observe(page, "admin");
  await page.goto(`${baseUrl}/admin/overview`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "平台总览" }).waitFor();
  const navigation = page.getByRole("navigation", { name: "主导航" });
  for (const label of [
    "总览",
    "账号与赛道",
    "素材与灵感",
    "选题与决策",
    "创作与交付",
    "发布准备",
    "复盘增长",
    "Media Agent",
    "云端归档",
    "用量与套餐",
    "邀请中心",
  ]) {
    require((await navigation
      .getByRole("link", { name: label, exact: true })
      .count()) === 0, `administrator sees ordinary navigation: ${label}`);
  }
  for (const heading of ["治理待办", "平台边界", "服务健康", "最近管理操作"]) {
    await page.getByRole("heading", { name: heading, exact: true }).waitFor();
  }
  const platformMetrics = page.getByLabel("平台指标");
  require(JSON.stringify(
    await platformMetrics.locator("strong").allTextContents(),
  ) ===
    JSON.stringify([
      "—",
      "—",
      "—",
      "—",
    ]), "admin overview renders fabricated platform metrics");
  const serviceLabels = ["身份服务", "任务服务", "计费服务", "审计服务"];
  const serviceReadouts = await page
    .getByLabel("服务健康读数")
    .locator("> div")
    .allTextContents();
  require(JSON.stringify(
    serviceReadouts.map((value) => value.replace("平台服务健康接口未提供", "")),
  ) ===
    JSON.stringify(
      serviceLabels,
    ), `admin overview service boundary drifted: ${serviceReadouts.join(" | ")}`);
  require(countRequests(requests, /GET \/dashboard$/) ===
    0, "admin overview requested a tenant dashboard");
  require(countRequests(requests, /GET \/admin\//) ===
    0, "admin overview eagerly loaded a downstream administrator module");
  require(countRequests(requests, /GET \/admin\/affiliate-users/) ===
    0, "admin first screen eagerly loaded users");
  require(countRequests(requests, /GET \/admin\/registration-policy$/) ===
    0, "admin first screen eagerly loaded registration policy");
  const overviewBusinessRequests = requests.filter(
    (request) => request !== "GET /session",
  );
  require(overviewBusinessRequests.length ===
    0, `admin overview fetched business data before the platform aggregate contract was frozen: ${overviewBusinessRequests.join(", ")}`);

  await navigation
    .getByRole("link", { name: "用户与准入", exact: true })
    .click();
  await page.getByRole("heading", { name: "用户与准入" }).waitFor();
  require(countRequests(requests, /GET \/admin\/affiliate-users\?/) ===
    1, "access page did not load users once");
  require(countRequests(requests, /GET \/admin\/admission-batches\?/) ===
    1, "access page did not load admission summaries once");
  require(countRequests(requests, /GET \/admin\/registration-policy$/) ===
    1, "access page did not load the registration summary once");
  await page.getByRole("tab", { name: "注册策略", exact: true }).click();
  require(countRequests(requests, /GET \/admin\/registration-policy$/) ===
    1, "registration tab reloaded an existing summary");

  await page.getByRole("tab", { name: "邀请权限", exact: true }).click();
  require(countRequests(requests, /GET \/admin\/affiliate-users\?/) ===
    1, "invitation tab reloaded an existing user page");
  await navigation.getByRole("link", { name: "租户资源", exact: true }).click();
  await page.getByRole("heading", { name: "租户资源" }).waitFor();
  require(countRequests(requests, /GET \/admin\/runs/) ===
    0, "tenant resources loaded without an explicit target tenant");
  if (targetTenantId) {
    await page.getByLabel("目标租户编号", { exact: true }).fill(targetTenantId);
    await page
      .getByRole("button", { name: "读取运行审计", exact: true })
      .click();
    await page
      .getByRole("heading", { name: "审计上下文", exact: true })
      .waitFor();
    await page.waitForLoadState("networkidle");
    require(countRequests(
      requests,
      new RegExp(`GET /admin/runs\\?[^ ]*targetTenantId=${targetTenantId}`),
    ) === 1, "target tenant run summary was not requested exactly once");
  }

  await navigation.getByRole("link", { name: "计费运营", exact: true }).click();
  await page.getByRole("heading", { name: "计费运营" }).waitFor();
  await page
    .getByRole("tablist", { name: "计费写入操作" })
    .getByRole("tab", { name: "管理员赠款", exact: true })
    .waitFor();
  require(countRequests(
    requests,
    /GET \/admin\/billing\/summary\?limit=100$/,
  ) === 1, "billing summary did not load on demand");
  require(countRequests(requests, /\/admin\/redemption\//) ===
    0, "retired admin redemption route was requested");
  await assertNoSensitivePresentation(page, "admin retail billing");

  await navigation.getByRole("link", { name: "上游服务", exact: true }).click();
  await page.getByRole("heading", { name: "上游服务" }).waitFor();
  await page
    .getByRole("heading", { name: "服务健康状态", exact: true })
    .waitFor();
  require(countRequests(
    requests,
    /GET \/admin\/upstream-credential\/health$/,
  ) === 1, "upstream health did not load on demand");
  require(countRequests(
    requests,
    /GET \/admin\/billing\/reconciliation\?limit=100$/,
  ) === 1, "upstream reconciliation did not load on demand");
  await assertNoSensitivePresentation(page, "admin upstream operations", true);

  await assertNoOverflow(page, "admin desktop");
  await assertNoSensitivePresentation(page, "admin desktop", true);
  await page.screenshot({
    path: resolve(outputDir, "desktop-admin.png"),
    fullPage: true,
  });
  evidence.checks.push("admin modules are isolated and load on demand");
  await context.close();
}

async function mobileCheck(
  browser: Awaited<ReturnType<typeof chromium.launch>>,
) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
  });
  await installCookies(context, cookies.userA);
  const page = await context.newPage();
  observe(page, "mobile-user");
  await page.goto(`${baseUrl}/usage-billing`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "用量与套餐" }).waitFor();
  await assertNoOverflow(page, "user billing mobile");
  await assertNoSensitivePresentation(page, "user billing mobile");
  await page.screenshot({
    path: resolve(outputDir, "mobile-user-billing.png"),
    fullPage: true,
  });
  evidence.checks.push("mobile billing has no horizontal overflow");
  await context.close();
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  try {
    await registrationPolicyCheck(browser);
    await unauthenticatedCheck(browser);
    await userCheck(browser);
    await adminCheck(browser);
    await mobileCheck(browser);
  } catch (error) {
    evidence.failures.push(
      error instanceof Error ? error.message : String(error),
    );
  } finally {
    await browser.close();
  }
  evidence.ok = evidence.failures.length === 0;
  writeFileSync(
    resolve(outputDir, "media-web-runtime-summary.json"),
    `${JSON.stringify(evidence, null, 2)}\n`,
  );
  if (!evidence.ok) throw new Error(evidence.failures.join(" | "));
  console.log(
    `Media Web tenant browser QA passed with ${evidence.checks.length} checks`,
  );
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
