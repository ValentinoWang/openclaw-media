import { mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { chromium } from "playwright";

const origin = (process.env.MEDIA_QA_ORIGIN ?? "https://mediapilot.cloud").replace(/\/$/, "");
const username = process.env.MEDIA_QA_USERNAME ?? "wsy_9523";
const password = process.env.MEDIA_QA_PASSWORD;
const storageState = process.env.MEDIA_QA_STORAGE_STATE;
if (!password && !storageState) {
  throw new Error("MEDIA_QA_PASSWORD or MEDIA_QA_STORAGE_STATE is required");
}
const expectedOwnedAccountCount = process.env.MEDIA_QA_EXPECT_OWNED_ACCOUNT_COUNT
  ? Number(process.env.MEDIA_QA_EXPECT_OWNED_ACCOUNT_COUNT)
  : null;
const expectedOwnedAccountName = process.env.MEDIA_QA_EXPECT_OWNED_ACCOUNT_NAME?.trim() || null;
const expectedOwnedAccountPlatforms = (process.env.MEDIA_QA_EXPECT_OWNED_ACCOUNT_PLATFORMS ?? "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean)
  .sort();

const runId = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
const outputRoot = resolve(
  process.env.MEDIA_QA_OUTPUT ?? `/home/ubuntu/qa-evidence/media-projection-final-${runId}`,
);
mkdirSync(outputRoot, { recursive: true });

const allRoutes = [
  "overview",
  "tracks",
  "assets",
  "decisions",
  "runs",
  "publishing",
  "reviews",
  "media-agent",
  "archives",
  "usage-billing",
  "invites",
] as const;
type RouteName = (typeof allRoutes)[number];
const requestedRoutes = (process.env.MEDIA_QA_ROUTES ?? "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);
const unknownRoutes = requestedRoutes.filter(
  (value): value is string => !allRoutes.includes(value as RouteName),
);
if (unknownRoutes.length > 0) {
  throw new Error(`MEDIA_QA_ROUTES contains unsupported routes: ${unknownRoutes.join(", ")}`);
}
const routes: readonly RouteName[] = requestedRoutes.length > 0
  ? requestedRoutes as RouteName[]
  : allRoutes;
const viewports = [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "mobile", width: 390, height: 844 },
] as const;
const forbiddenText = [
  /部分业务投影/u,
  /业务投影暂时不可用/u,
  /run availableSections is invalid/iu,
  /decision public id is invalid/iu,
  /\b(?:organization_lark|personal_web|not_applicable|pending_manual)\b/iu,
  /\b(?:primary_creator|external_creator|quality_status|body_authority|sync_status)\b/iu,
  /\b(?:Handle|platformAccountId|publicAccountId)\b/iu,
  /待授权|等待授权|授权异常|重新授权|授权状态|OAuth/iu,
  /账号策略|生成账号策略/iu,
];

type OwnedAccountReadback = {
  viewport: string;
  count: number;
  accountNames: string[];
  platforms: string[];
  avatarsPresent: number;
  detailScreenshot: string;
};

type PageResult = {
  viewport: string;
  route: string;
  title: string;
  apiFailures: Array<{ status: number; url: string }>;
  expectedApiDegradations: Array<{ status: number; url: string; reason: string }>;
  apiRequests: Array<{
    method: string;
    url: string;
    status: number | null;
    durationMs: number;
    failure: string | null;
  }>;
  consoleErrors: string[];
  pageErrors: string[];
  forbiddenMatches: string[];
  horizontalOverflow: number;
  screenshot: string;
};

const results: PageResult[] = [];
const ownedAccountReadbacks: OwnedAccountReadback[] = [];
const browser = await chromium.launch({ headless: true });
try {
  for (const viewport of viewports) {
    const context = await browser.newContext({
      viewport: { width: viewport.width, height: viewport.height },
      deviceScaleFactor: 1,
      ...(storageState ? { storageState } : {}),
    });
    if (!storageState) {
      const login = await context.request.post(`${origin}/openclaw/auth/login`, {
        data: { username, password },
        headers: { Accept: "application/json" },
      });
      if (!login.ok()) throw new Error(`login failed: ${login.status()}`);
    }

    for (const routeName of routes) {
      const page = await context.newPage();
      const apiFailures: Array<{ status: number; url: string }> = [];
      const expectedApiDegradations: Array<{ status: number; url: string; reason: string }> = [];
      const apiRequests: PageResult["apiRequests"] = [];
      const apiStartedAt = new Map<string, number>();
      const consoleErrors: string[] = [];
      const pageErrors: string[] = [];
      page.on("request", (request) => {
        if (request.url().includes("/openclaw/media/api/")) {
          apiStartedAt.set(request.url(), Date.now());
        }
      });
      page.on("response", (response) => {
        if (!response.url().includes("/openclaw/media/api/")) return;
        const request = response.request();
        apiRequests.push({
          method: request.method(),
          url: response.url(),
          status: response.status(),
          durationMs: Date.now() - (apiStartedAt.get(response.url()) ?? Date.now()),
          failure: null,
        });
        if (response.status() >= 400) {
          const monitorUnavailable = response.status() === 503
            && /\/openclaw\/media\/api\/owned-accounts\/[^/]+\/monitor$/u.test(new URL(response.url()).pathname);
          if (monitorUnavailable) {
            expectedApiDegradations.push({
              status: response.status(),
              url: response.url(),
              reason: "monitor_unavailable is the documented fail-closed response when the H00 adapter is unavailable",
            });
          } else {
            apiFailures.push({ status: response.status(), url: response.url() });
          }
        }
      });
      page.on("requestfailed", (request) => {
        if (!request.url().includes("/openclaw/media/api/")) return;
        apiRequests.push({
          method: request.method(),
          url: request.url(),
          status: null,
          durationMs: Date.now() - (apiStartedAt.get(request.url()) ?? Date.now()),
          failure: request.failure()?.errorText ?? "unknown request failure",
        });
      });
      page.on("console", (entry) => {
        if (entry.type() === "error") consoleErrors.push(entry.text());
      });
      page.on("pageerror", (error) => pageErrors.push(error.message));

      await page.goto(`${origin}/openclaw/media/${routeName}`, { waitUntil: "domcontentloaded" });
      await page.locator(".media-shell").waitFor({ state: "visible", timeout: 30000 });
      await page.waitForLoadState("networkidle", { timeout: 30000 });

      const bodyText = await page.locator("body").innerText();
      const forbiddenMatches = forbiddenText
        .flatMap((pattern) => bodyText.match(pattern) ?? [])
        .filter((value, index, values) => values.indexOf(value) === index);
      const title = (await page.getByRole("heading", { level: 1 }).first().textContent())?.trim() ?? "";
      const horizontalOverflow = await page.evaluate(() =>
        Math.max(
          document.documentElement.scrollWidth - document.documentElement.clientWidth,
          document.body.scrollWidth - document.body.clientWidth,
        ),
      );
      const screenshot = join(outputRoot, `${viewport.name}-${routeName}.png`);
      await page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" });

      writeFileSync(
        join(outputRoot, `${viewport.name}-${routeName}.diagnostic.json`),
        JSON.stringify({ apiRequests, apiFailures, consoleErrors, pageErrors }, null, 2) + "\n",
      );

      if (!title || !/[\u3400-\u9fff]/u.test(bodyText)) {
        throw new Error(`${viewport.name}/${routeName} did not render a Chinese product page`);
      }
      if (routeName === "overview") {
        const organizationLinks = page.getByRole("link", { name: "打开组织文档" });
        if ((await organizationLinks.count()) < 1) {
          throw new Error(`${viewport.name}/overview has no organization document link`);
        }
        const href = await organizationLinks.first().getAttribute("href");
        if (!href?.startsWith("https://tcnwueberajc.feishu.cn/wiki/")) {
          throw new Error(`${viewport.name}/overview organization document target is invalid`);
        }
        if ((await page.getByText("查看网页内容", { exact: true }).count()) !== 0) {
          throw new Error(`${viewport.name}/overview exposes a Web body action for a Lark document`);
        }
      }
      if (routeName === "tracks") {
        const ownedAccountsResponse = await context.request.get(
          `${origin}/openclaw/media/api/owned-accounts?pageSize=20`,
          { headers: { Accept: "application/json" } },
        );
        if (!ownedAccountsResponse.ok()) {
          throw new Error(`${viewport.name}/tracks owned-account readback failed: ${ownedAccountsResponse.status()}`);
        }
        const ownedAccountsPayload = (await ownedAccountsResponse.json()) as { items?: unknown };
        if (!Array.isArray(ownedAccountsPayload.items) || ownedAccountsPayload.items.length === 0) {
          throw new Error(`${viewport.name}/tracks production owned-account ledger is empty`);
        }
        const requiredLedgerFields = [
          "operationalStatus",
          "responsiblePerson",
          "teamName",
          "accountPositioning",
          "dataSource",
          "avatarUrl",
        ] as const;
        const accountNames: string[] = [];
        const platforms: string[] = [];
        let avatarsPresent = 0;
        for (const [index, rawAccount] of ownedAccountsPayload.items.entries()) {
          if (!rawAccount || typeof rawAccount !== "object") {
            throw new Error(`${viewport.name}/tracks owned-account item ${index} is not an object`);
          }
          const account = rawAccount as Record<string, unknown>;
          for (const field of requiredLedgerFields) {
            if (!Object.prototype.hasOwnProperty.call(account, field)) {
              throw new Error(`${viewport.name}/tracks owned-account item ${index} lacks ${field}`);
            }
          }
          if (Object.prototype.hasOwnProperty.call(account, "authorizationStatus")) {
            throw new Error(`${viewport.name}/tracks still exposes retired authorizationStatus`);
          }
          if (typeof account.accountName !== "string" || !account.accountName.trim()) {
            throw new Error(`${viewport.name}/tracks owned-account item ${index} lacks accountName`);
          }
          if (typeof account.platform !== "string" || !account.platform.trim()) {
            throw new Error(`${viewport.name}/tracks owned-account item ${index} lacks platform`);
          }
          if (typeof account.avatarUrl !== "string" || !account.avatarUrl.trim()) {
            throw new Error(`${viewport.name}/tracks owned-account item ${index} lacks avatarUrl`);
          }
          accountNames.push(account.accountName);
          platforms.push(account.platform);
          avatarsPresent += 1;
        }
        if (expectedOwnedAccountCount !== null && accountNames.length !== expectedOwnedAccountCount) {
          throw new Error(`${viewport.name}/tracks expected ${expectedOwnedAccountCount} owned accounts, received ${accountNames.length}`);
        }
        if (expectedOwnedAccountName && accountNames.some((name) => name !== expectedOwnedAccountName)) {
          throw new Error(`${viewport.name}/tracks owned-account name readback differs from the expected ledger`);
        }
        if (
          expectedOwnedAccountPlatforms.length > 0
          && JSON.stringify([...platforms].sort()) !== JSON.stringify(expectedOwnedAccountPlatforms)
        ) {
          throw new Error(`${viewport.name}/tracks owned-account platform readback differs from the expected ledger`);
        }

        const accountRows = page.locator('[data-page-list="owned-accounts"] button');
        if ((await accountRows.count()) !== accountNames.length) {
          throw new Error(`${viewport.name}/tracks rendered account count differs from the API readback`);
        }
        const avatarImages = accountRows.locator("[data-account-avatar-image]");
        if ((await avatarImages.count()) !== avatarsPresent) {
          throw new Error(`${viewport.name}/tracks did not render every owned-account avatar`);
        }
        for (let index = 0; index < avatarsPresent; index += 1) {
          await avatarImages.nth(index).waitFor({ state: "visible", timeout: 30_000 });
          const naturalWidth = await avatarImages.nth(index).evaluate(
            (image: HTMLImageElement) => image.naturalWidth,
          );
          if (naturalWidth <= 0) {
            throw new Error(`${viewport.name}/tracks owned-account avatar ${index} did not decode`);
          }
        }
        await accountRows.first().click();
        const accountDetail = page.locator("[data-page-account-detail]");
        await accountDetail.waitFor({ state: "visible", timeout: 30_000 });
        await accountDetail.getByText("账号身份", { exact: true }).waitFor({
          state: "visible",
          timeout: 30_000,
        });
        const detailText = await accountDetail.innerText();
        for (const section of ["账号身份", "组织责任", "运营定位", "运营状态", "数据状态"]) {
          if (!detailText.includes(section)) {
            throw new Error(`${viewport.name}/tracks owned-account detail lacks ${section}`);
          }
        }
        const detailForbiddenMatches = forbiddenText
          .flatMap((pattern) => detailText.match(pattern) ?? [])
          .filter((value, index, values) => values.indexOf(value) === index);
        if (detailForbiddenMatches.length > 0) {
          throw new Error(`${viewport.name}/tracks owned-account detail exposes retired or internal copy`);
        }
        for (const unavailableAction of ["同步数据", "编辑资料", "停用"]) {
          if ((await accountDetail.getByRole("button", { name: unavailableAction, exact: true }).count()) > 0) {
            throw new Error(`${viewport.name}/tracks exposes unavailable ${unavailableAction} action`);
          }
        }
        const detailAvatar = accountDetail.locator("[data-account-avatar-image]");
        await detailAvatar.waitFor({ state: "visible", timeout: 30_000 });
        if (await detailAvatar.evaluate((image: HTMLImageElement) => image.naturalWidth) <= 0) {
          throw new Error(`${viewport.name}/tracks owned-account detail avatar did not decode`);
        }
        const detailScreenshot = join(outputRoot, `${viewport.name}-tracks-selected.png`);
        await page.screenshot({ path: detailScreenshot, fullPage: true, animations: "disabled" });
        ownedAccountReadbacks.push({
          viewport: viewport.name,
          count: accountNames.length,
          accountNames: [...new Set(accountNames)].sort(),
          platforms: [...new Set(platforms)].sort(),
          avatarsPresent,
          detailScreenshot,
        });
      }
      const actionableConsoleErrors = consoleErrors.filter(
        (message) => !(
          expectedApiDegradations.length > 0
          && message.includes("Failed to load resource: the server responded with a status of 503")
        ),
      );
      if (apiFailures.length || actionableConsoleErrors.length || pageErrors.length || forbiddenMatches.length) {
        throw new Error(
          `${viewport.name}/${routeName} runtime failure: ${JSON.stringify({
            apiFailures,
            expectedApiDegradations,
            consoleErrors,
            actionableConsoleErrors,
            pageErrors,
            forbiddenMatches,
          })}`,
        );
      }
      if (horizontalOverflow > 1) {
        throw new Error(`${viewport.name}/${routeName} horizontal overflow: ${horizontalOverflow}px`);
      }

      results.push({
        viewport: viewport.name,
        route: routeName,
        title,
        apiFailures,
        apiRequests,
        consoleErrors,
        pageErrors,
        forbiddenMatches,
        horizontalOverflow,
        screenshot,
      });
      await page.close();
    }
    await context.close();
  }
} finally {
  await browser.close();
}

const report = {
  origin,
  runId,
  pages: results.length,
  viewports: viewports.map(({ name, width, height }) => ({ name, width, height })),
  ownedAccountReadbacks,
  results,
};
writeFileSync(join(outputRoot, "report.json"), JSON.stringify(report, null, 2) + "\n");
console.log(JSON.stringify({ outputRoot, pages: results.length }, null, 2));
