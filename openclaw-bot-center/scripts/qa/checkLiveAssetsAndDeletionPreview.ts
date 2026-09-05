import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { chromium, type Request } from "playwright";

const origin = process.env.MEDIA_QA_ORIGIN ?? "https://mediapilot.cloud";
const storageState = process.env.MEDIA_QA_STORAGE_STATE;
const username = process.env.MEDIA_QA_USERNAME;
const password = process.env.MEDIA_QA_PASSWORD;
assert.ok(storageState || (username && password), "storage state or QA credentials are required");
const outputRoot = resolve(
  process.env.MEDIA_QA_OUTPUT ?? "./agents-results/qa/media-assets-backwash",
);
mkdirSync(outputRoot, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  ...(storageState ? { storageState } : {}),
  viewport: { width: 1440, height: 1000 },
});
const page = await context.newPage();
const mutationRequests: Array<{ url: string; method: string; body: unknown }> = [];
page.on("request", (request) => {
  if (request.method() === "GET") return;
  let body: unknown = null;
  try {
    body = request.postDataJSON();
  } catch {
    body = null;
  }
  mutationRequests.push({ url: request.url(), method: request.method(), body });
});

try {
  let assetsResponse = await context.request.get(
    `${origin}/openclaw/media/api/assets?pageSize=50`,
  );
  if (assetsResponse.status() === 401 && username && password) {
    const loginResponse = await context.request.post(`${origin}/openclaw/auth/login`, {
      data: { username, password },
      headers: { Accept: "application/json" },
    });
    assert.equal(loginResponse.status(), 200, "QA login must succeed");
    assetsResponse = await context.request.get(
      `${origin}/openclaw/media/api/assets?pageSize=50`,
    );
  }
  assert.equal(assetsResponse.status(), 200, "assets API must be authenticated and available");
  const assetsPayload = (await assetsResponse.json()) as {
    items?: Array<{ publicAssetId?: string; thumbnail?: { status?: string; url?: string } }>;
  };
  const items = assetsPayload.items ?? [];
  assert.ok(items.length > 0, "production tenant must expose backwashed assets");
  const verifiableItems = items.filter((item) => item.thumbnail?.status !== "unavailable");
  assert.equal(
    verifiableItems.filter((item) => item.thumbnail?.status === "available" && item.thumbnail.url).length,
    verifiableItems.length,
    "every verifiable production asset must expose an evidence-backed thumbnail",
  );

  await page.goto(`${origin}/openclaw/media/assets`, { waitUntil: "domcontentloaded" });
  await page.locator(".media-shell").waitFor({ state: "visible" });
  await page.locator('[data-assets-tab-panel="assets"]').waitFor({ state: "visible" });
  const desktopOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  assert.ok(desktopOverflow <= 1, `desktop horizontal overflow: ${desktopOverflow}px`);
  const assetCards = page.locator('[data-assets-tab-panel="assets"] [role="listitem"]');
  await assetCards.first().waitFor({ state: "visible", timeout: 30_000 });
  assert.ok((await assetCards.count()) > 0, "asset cards must render");

  const thumbnails = page.locator('img[alt$="缩略图"]');
  const thumbnailCount = await thumbnails.count();
  for (let index = 0; index < thumbnailCount; index += 1) {
    await thumbnails.nth(index).scrollIntoViewIfNeeded();
    await thumbnails.nth(index).evaluate((image: HTMLImageElement) => {
      if (image.complete) return;
      return new Promise<void>((resolve, reject) => {
        image.addEventListener("load", () => resolve(), { once: true });
        image.addEventListener("error", () => reject(new Error("thumbnail decode failed")), { once: true });
      });
    });
    assert.ok(
      await thumbnails.nth(index).evaluate((image: HTMLImageElement) => image.naturalWidth > 0),
      `thumbnail ${index + 1} must decode`,
    );
  }

  await page.getByRole("button", { name: /^查看素材 / }).first().click();
  const deleteButton = page.locator('section[aria-label="删除影响"]').getByRole("button", { name: "删除素材" });
  await deleteButton.waitFor({ state: "visible" });
  let previewRequest: Request | null = null;
  const requestPromise = page.waitForRequest((request) => {
    if (request.method() !== "POST" || !request.url().endsWith("/openclaw/media/api/tasks")) return false;
    const body = request.postDataJSON() as { capabilityId?: string; variantId?: string };
    return body.capabilityId === "universal_deletion" && body.variantId === "preview";
  });
  const responsePromise = page.waitForResponse(
    (response) => response.request().method() === "POST" && response.url().endsWith("/openclaw/media/api/tasks"),
  );
  await deleteButton.click();
  await page.getByRole("heading", { name: "删除素材", exact: true }).waitFor({ state: "visible" });
  assert.equal(
    await page.getByText("让 AI 帮你拆解需求", { exact: true }).count(),
    0,
    "delete action must bypass AI decomposition",
  );

  previewRequest = await requestPromise;
  const previewResponse = await responsePromise;
  if (previewResponse.status() !== 202) {
    console.error(`deletion preview response ${previewResponse.status()}: ${await previewResponse.text()}`);
  }
  assert.equal(previewResponse.status(), 202, "first deletion preview request must create one task");
  const firstTask = (await previewResponse.json()) as { taskId?: string };
  assert.ok(firstTask.taskId, "preview response must contain taskId");

  const previewBody = previewRequest.postDataJSON() as Record<string, unknown>;
  assert.equal(previewBody.capabilityId, "universal_deletion");
  assert.equal(previewBody.variantId, "preview");
  assert.equal(previewBody.confirmationReceipt, null);
  const requestHeaders = previewRequest.headers();
  const sessionPayload = await (await context.request.get(`${origin}/openclaw/media/api/session`)).json() as { session?: { csrfToken?: string } };
  const replayResponse = await context.request.post(
    `${origin}/openclaw/media/api/tasks`,
    {
      data: previewBody,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "Idempotency-Key": String(requestHeaders["idempotency-key"] ?? ""),
        "X-OpenClaw-CSRF": String(requestHeaders["x-openclaw-csrf"] ?? sessionPayload.session?.csrfToken ?? ""),
        Origin: origin,
        Referer: `${origin}/openclaw/media/assets`,
        Cookie: (await context.cookies()).map((cookie) => `${cookie.name}=${cookie.value}`).join("; "),
      },
    },
  );
  if (replayResponse.status() !== 200) console.error(`replay response ${replayResponse.status()}: ${await replayResponse.text()}`);
  assert.equal(replayResponse.status(), 200, "same preview request must replay idempotently");
  const replayTask = (await replayResponse.json()) as { taskId?: string };
  assert.equal(replayTask.taskId, firstTask.taskId, "replay must return the original task");

  await page.screenshot({ path: `${outputRoot}/desktop-assets-delete-preview.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${origin}/openclaw/media/assets`, { waitUntil: "domcontentloaded" });
  const mobileOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  assert.ok(mobileOverflow <= 1, `mobile horizontal overflow: ${mobileOverflow}px`);
  await page.screenshot({ path: `${outputRoot}/mobile-assets.png`, fullPage: true });

  assert.equal(
    mutationRequests.some((entry) =>
      (entry.body as { variantId?: string } | null)?.variantId === "confirm" ||
      /\/delete(?:\/|$)/.test(new URL(entry.url).pathname),
    ),
    false,
    "QA must not send deletion confirmation or deletion execution requests",
  );
  const report = {
    assets: items.length,
    unavailableAssets: items.length - verifiableItems.length,
    availableThumbnails: items.filter(
      (item) => item.thumbnail?.status === "available" && item.thumbnail.url,
    ).length,
    decodedThumbnailsOnPage: thumbnailCount,
    desktopOverflow,
    mobileOverflow,
    previewTaskId: firstTask.taskId,
    replayStatus: replayResponse.status(),
    confirmRequests: 0,
  };
  writeFileSync(`${outputRoot}/report.json`, JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify({ outputRoot, ...report }, null, 2));
} finally {
  await context.close();
  await browser.close();
}
