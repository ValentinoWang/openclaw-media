import { chromium, type Browser, type Page } from "playwright";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const baseUrl = (
  process.env.OVERVIEW_CONFIRMATION_PRODUCTION_URL ??
  "http://127.0.0.1/openclaw/media"
).replace(/\/$/, "");
const cookieHeader = process.env.OVERVIEW_CONFIRMATION_PRODUCTION_COOKIE?.trim() ?? "";
const targetId = process.env.OVERVIEW_CONFIRMATION_PRODUCTION_TARGET?.trim() ?? "";
const taskId = process.env.OVERVIEW_CONFIRMATION_PRODUCTION_TASK_ID?.trim() ?? "";
const outputDir = process.env.OVERVIEW_CONFIRMATION_PRODUCTION_OUTPUT?.trim() ?? "";

function requireCondition(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function parseCookieHeader(header: string) {
  return header.split(";").map((part) => part.trim()).filter(Boolean).map((part) => {
    const separator = part.indexOf("=");
    requireCondition(separator > 0, "production authentication input is invalid");
    return { name: part.slice(0, separator), value: part.slice(separator + 1) };
  });
}

async function verifyViewport(
  browser: Browser,
  label: "desktop" | "mobile",
  viewport: { width: number; height: number },
) {
  const context = await browser.newContext({ viewport });
  const origin = new URL(baseUrl);
  await context.addCookies(parseCookieHeader(cookieHeader).map((cookie) => ({
    ...cookie,
    domain: origin.hostname,
    path: "/openclaw/",
    httpOnly: true,
    secure: origin.protocol === "https:",
    sameSite: "Lax" as const,
  })));
  const page = await context.newPage();
  const mutations: string[] = [];
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  page.on("request", (request) => {
    if (["POST", "PUT", "PATCH", "DELETE"].includes(request.method())) {
      mutations.push(`${request.method()} ${new URL(request.url()).pathname}`);
    }
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  try {
    await page.goto(`${baseUrl}/overview`, { waitUntil: "domcontentloaded", timeout: 20_000 });
    await page.getByRole("heading", { name: "运营总览", exact: true }).waitFor({ timeout: 20_000 });
    const card = page.locator('[data-confirmation-kind="deletion_preview"]').filter({ hasText: targetId });
    requireCondition(
      (await card.count()) === 0,
      `${label}: expired deletion confirmation is still visible in Overview`,
    );
    if (outputDir) {
      await mkdir(outputDir, { recursive: true });
      await page.screenshot({
        path: path.join(outputDir, `production-expired-hidden-${label}.png`),
        fullPage: false,
      });
    }

    await page.locator(".topbar-command").click();
    const drawer = page.getByRole("complementary", { name: "Media 任务工作区" });
    const taskItem = drawer.locator(`[data-task-id="${taskId}"]`);
    await drawer.waitFor({ timeout: 20_000 });
    requireCondition(
      (await taskItem.count()) === 0,
      `${label}: expired deletion confirmation is still visible in the task drawer`,
    );
    if (outputDir) {
      await drawer.screenshot({
        path: path.join(outputDir, `production-task-feed-${label}.png`),
      });
    }
    requireCondition(
      mutations.length === 0,
      `${label}: read-only production confirmation audit emitted mutations: ${mutations.join(" | ")}`,
    );
    requireCondition(pageErrors.length === 0, `${label}: page errors: ${pageErrors.join(" | ")}`);
    requireCondition(consoleErrors.length === 0, `${label}: console errors: ${consoleErrors.join(" | ")}`);
    return {
      label,
      overviewVisible: false,
      taskDrawerVisible: false,
      mutations: mutations.length,
    };
  } finally {
    await context.close();
  }
}

requireCondition(cookieHeader !== "", "production authentication input is missing");
requireCondition(targetId !== "", "production target identity is missing");
requireCondition(taskId !== "", "production task identity is missing");
const browser = await chromium.launch({ headless: true });
try {
  const results = [];
  results.push(await verifyViewport(browser, "desktop", { width: 1440, height: 1000 }));
  results.push(await verifyViewport(browser, "mobile", { width: 390, height: 844 }));
  console.log(JSON.stringify({ ok: true, results }));
} finally {
  await browser.close();
}
