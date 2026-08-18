import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { chromium, type BrowserContext, type ConsoleMessage, type Page, type Response } from "playwright";

const baseUrl = (process.env.D2_OVERVIEW_QA_URL ?? process.env.MEDIA_ROLE_QA_URL ?? "http://127.0.0.1/openclaw/media").replace(/\/$/, "");
const outputDir = resolve(process.env.D2_OVERVIEW_QA_OUTPUT ?? "/home/ubuntu/media-d2-overview-qa");
const cookieHeader = process.env.D2_OVERVIEW_QA_COOKIE ?? process.env.MEDIA_WEB_QA_USER_A_COOKIE ?? process.env.MEDIA_WEB_QA_COOKIE ?? "";
const requiredTypes = (process.env.D2_OVERVIEW_QA_REQUIRED_ARTIFACT_TYPES ?? "research_snapshot,asset_digest,decision_brief,creation_document,review_report").split(",").map((v) => v.trim()).filter(Boolean);
const fixturePath = resolve(process.env.D2_OVERVIEW_QA_FIXTURES ?? "");
const viewports = [{ name: "desktop", width: 1920, height: 1088 }, { name: "mobile", width: 390, height: 844 }] as const;
type Artifact = { publicArtifactId: string; publicProjectId: string; artifactType: string; bodyAuthority: string };
type Candidate = { artifact: Artifact; projectTitle: string; artifactIndex: number };
type Fixture = { artifactKind: string; publicProjectId: string; publicArtifactId: string; expectedRevision: number; expectedBodyChecksum: string };
type Api = { method: string; path: string; status: number; artifactTypes?: string[]; artifactId?: string; contentChecksum?: string; contentType?: string };
type ResourceManifest = { id: string; type: string; publicResourceId: string; contentChecksum: string };
type DomManifest = { blockCount: number; blockTypes: string[]; blocks: Array<{ id: string | null; type: string | null; tag: string; textLength: number }>; resources: ResourceManifest[] };
type Capture = { artifactType: string; artifactId: string; viewport: string; screenshot: string; sha256: string; documentScreenshot: string; documentSha256: string; documentContainer: { tag: string; className: string; childCount: number; blockCount: number }; expectedRevision: number; observedRevision: number; expectedBodyChecksum: string; observedBodyChecksum: string; overflow: { documentX: number; bodyX: number; previewX: number }; manifest: unknown; api: Api[] };
const blockers: Array<{ code: string; detail: string }> = [], failures: string[] = [], observations: Api[] = [], captures: Capture[] = [];
const projectTitles = new Map<string, string>(), artifactLists = new Map<string, Artifact[]>();

function loadFixtures(): Fixture[] {
  assertGate(process.env.D2_OVERVIEW_QA_FIXTURES?.trim(), "set D2_OVERVIEW_QA_FIXTURES to the revision-pinned five-document manifest");
  const value = JSON.parse(readFileSync(fixturePath, "utf8")) as { fixtures?: Fixture[] };
  assertGate(Array.isArray(value.fixtures) && value.fixtures.length === 5, "fixture manifest must contain five documents");
  const fixtures = value.fixtures;
  assertGate(new Set(fixtures.map((item) => item.artifactKind)).size === 5, "fixture artifact kinds must be unique");
  for (const item of fixtures) {
    assertGate(requiredTypes.includes(item.artifactKind), "unexpected fixture artifact kind: " + item.artifactKind);
    assertGate(Boolean(item.publicProjectId && item.publicArtifactId), item.artifactKind + " fixture identity is missing");
    assertGate(Number.isInteger(item.expectedRevision) && item.expectedRevision > 0, item.artifactKind + " expected revision is invalid");
    assertGate(/^[0-9a-f]{64}$/.test(item.expectedBodyChecksum), item.artifactKind + " expected checksum is invalid");
  }
  return fixtures;
}
const fixtures = loadFixtures();
const fixtureByType = new Map(fixtures.map((item) => [item.artifactKind, item]));

function assertGate(value: unknown, message: string): asserts value { if (!value) throw new Error(message); }
function block(code: string, detail: string) { if (!blockers.some((b) => b.code === code && b.detail === detail)) blockers.push({ code, detail }); }
function hashFile(path: string) { return createHash("sha256").update(readFileSync(path)).digest("hex"); }
function parseCookies(header: string) {
  assertGate(header.trim() !== "", "missing ordinary authenticated cookie; set D2_OVERVIEW_QA_COOKIE or MEDIA_WEB_QA_USER_A_COOKIE");
  return header.split(";").map((v) => v.trim()).filter(Boolean).map((v) => {
    const i = v.indexOf("="); assertGate(i > 0, "invalid authenticated Cookie header");
    return { name: v.slice(0, i), value: v.slice(i + 1) };
  });
}
async function installCookies(context: BrowserContext) {
  const url = new URL(baseUrl);
  await context.addCookies(parseCookies(cookieHeader).map((cookie) => ({ ...cookie, domain: url.hostname, path: "/openclaw/", httpOnly: true, secure: url.protocol === "https:", sameSite: "Lax" as const })));
}
function watch(page: Page, local: Api[]) {
  page.on("pageerror", (e) => failures.push("page error: " + e.message));
  page.on("console", (m: ConsoleMessage) => { if (m.type() === "error" && !m.text().startsWith("Failed to load resource:")) failures.push("console error: " + m.text()); });
}
async function inspect(response: Response, local: Api[]) {
  const url = new URL(response.url());
  if (!url.pathname.includes("/openclaw/media/api/")) return;
  const item: Api = { method: response.request().method(), path: url.pathname, status: response.status() };
  if (url.pathname.includes("/document-resources/")) {
    item.contentChecksum = response.headers()["x-content-sha256"];
    item.contentType = response.headers()["content-type"];
  }
  try {
    if (url.pathname === "/openclaw/media/api/content-projects") {
      const body = await response.json() as { items?: Array<{ publicProjectId: string; title: string }> };
      for (const p of body.items ?? []) projectTitles.set(p.publicProjectId, p.title);
    } else if (url.pathname.endsWith("/artifacts")) {
      const body = await response.json() as { items?: Artifact[] };
      item.artifactTypes = (body.items ?? []).map((a) => a.artifactType);
      artifactLists.set(decodeURIComponent(url.pathname.split("/").at(-2) ?? ""), body.items ?? []);
    }
  } catch { item.artifactTypes = []; }
  if (/\/documents\/[^/]+\/body$/.test(url.pathname)) item.artifactId = decodeURIComponent(url.pathname.split("/").at(-2) ?? "");
  local.push(item); observations.push(item);
}
async function openOverview(context: BrowserContext, local: Api[]) {
  context.on("response", (response) => { void inspect(response, local); });
  const page = await context.newPage(); watch(page, local);
  await page.goto(baseUrl + "/overview", { waitUntil: "networkidle" });
  if (await page.locator(".media-shell").count() !== 1) {
    block("overview_unavailable", "authenticated Overview did not render .media-shell; body=" + (await page.locator("body").innerText()).trim().slice(0, 400));
    throw new Error("ordinary Overview shell unavailable");
  }
  await page.getByRole("heading", { name: "运营总览" }).waitFor({ timeout: 10000 });
  return page;
}
async function discover(context: BrowserContext) {
  const local: Api[] = [], page = await openOverview(context, local), projects = page.getByRole("list", { name: "内容项目列表" }).getByRole("button");
  if (!await projects.count()) { block("no_content_projects", "Overview returned no selectable content projects"); return new Map<string, Candidate>(); }
  for (let i = 0; i < await projects.count(); i++) {
    await projects.nth(i).click();
    await page.locator("[aria-label='项目产物列表'], .panelState, .empty").first().waitFor({ timeout: 10000 });
    await page.waitForTimeout(250);
  }
  const found = new Map<string, Candidate>();
  for (const type of requiredTypes) {
    const fixture = fixtureByType.get(type);
    assertGate(fixture, "fixture missing for " + type);
    const artifacts = artifactLists.get(fixture.publicProjectId) ?? [];
    const index = artifacts.findIndex((a) => a.artifactType === type && a.publicArtifactId === fixture.publicArtifactId);
    if (index >= 0) found.set(type, { artifact: artifacts[index], projectTitle: projectTitles.get(fixture.publicProjectId) ?? fixture.publicProjectId, artifactIndex: index });
  }
  for (const type of requiredTypes) if (!found.has(type)) block("required_document_missing", type + " did not match its pinned project/artifact identity");
  if (!artifactLists.size) block("artifact_list_unavailable", "no successful /content-projects/{id}/artifacts response was observed");
  await page.close(); return found;
}
async function capture(candidate: Candidate, viewport: (typeof viewports)[number]) {
  const browser = await chromium.launch({ headless: true }), context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, deviceScaleFactor: 1 });
  const local: Api[] = [];
  try {
    await installCookies(context); const page = await openOverview(context, local);
    try {
      const project = page.getByRole("list", { name: "内容项目列表" }).getByRole("button").filter({ hasText: candidate.projectTitle }).first();
      assertGate(await project.count() === 1, "project for " + candidate.artifact.artifactType + " is not selectable");
      await project.click(); const row = page.locator("[aria-label='项目产物列表'] article").nth(candidate.artifactIndex); await row.waitFor({ timeout: 10000 });
      const button = row.getByRole("button", { name: "查看网页内容" }); assertGate(await button.count() === 1, candidate.artifact.artifactType + " has no web-preview control");
      const body = page.waitForResponse((r) => r.url().includes("/documents/" + encodeURIComponent(candidate.artifact.publicArtifactId) + "/body"), { timeout: 10000 });
      await button.click(); const response = await body.catch(() => null);
      assertGate(response && response.status() === 200, candidate.artifact.artifactType + " document body status " + (response ? response.status() : "no response"));
      const fixture = fixtureByType.get(candidate.artifact.artifactType)!;
      const payload = await response.json() as { revision?: number; data?: { revision?: { revision?: number; bodyChecksum?: string } } };
      const observedRevision = Number(payload.data?.revision?.revision ?? payload.revision);
      const observedBodyChecksum = String(payload.data?.revision?.bodyChecksum ?? "");
      assertGate(observedRevision === fixture.expectedRevision, candidate.artifact.artifactType + " revision drift: " + observedRevision);
      assertGate(observedBodyChecksum === fixture.expectedBodyChecksum, candidate.artifact.artifactType + " body checksum drift");
      const preview = page.locator("section[aria-label='文档正文预览']"); await preview.waitFor({ timeout: 10000 });
      const manifest = await preview.evaluate((el): DomManifest => {
        const blocks = [...el.querySelectorAll<HTMLElement>("[data-block-id][data-block-type]")];
        const resources: ResourceManifest[] = [];
        for (const block of blocks) {
          const unique = new Map<string, ResourceManifest>();
          for (const resource of block.querySelectorAll<HTMLElement>(
            "[data-public-resource-id][data-content-checksum]",
          )) {
            const publicResourceId = resource.dataset.publicResourceId;
            const contentChecksum = resource.dataset.contentChecksum;
            if (!publicResourceId || !contentChecksum) continue;
            unique.set(publicResourceId + ":" + contentChecksum, {
              id: block.dataset.blockId ?? "",
              type: block.dataset.blockType ?? "",
              publicResourceId,
              contentChecksum,
            });
          }
          resources.push(...unique.values());
        }
        return {
          blockCount: blocks.length,
          blockTypes: [...new Set(blocks.map((block) => block.dataset.blockType ?? ""))].sort(),
          blocks: blocks.map((block) => ({
            id: block.dataset.blockId ?? null,
            type: block.dataset.blockType ?? null,
            tag: block.firstElementChild?.tagName.toLowerCase() ?? "none",
            textLength: (block.textContent ?? "").trim().length,
          })),
          resources,
        };
      });
      assertGate(manifest.blockCount > 0, candidate.artifact.artifactType + " returned no canonical document blocks");
      assertGate(manifest.resources.length === 2, candidate.artifact.artifactType + " must render one image and one attachment resource");
      assertGate(new Set(manifest.resources.map((item) => item.type)).size === 2 && manifest.resources.some((item) => item.type === "image") && manifest.resources.some((item) => item.type === "attachment"), candidate.artifact.artifactType + " resource block types are incomplete");
      const images = preview.locator("img[data-public-resource-id][data-content-checksum]");
      assertGate(await images.count() === 1, candidate.artifact.artifactType + " must render one real image element");
      await images.first().scrollIntoViewIfNeeded();
      await images.first().waitFor({ state: "visible", timeout: 10000 });
      await page.waitForFunction((image) => image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0 && image.naturalHeight > 0, await images.first().elementHandle(), { timeout: 10000 });
      const overflow = await page.evaluate(() => { const v = document.querySelector<HTMLElement>("section[aria-label='文档正文预览']"); return { documentX: document.documentElement.scrollWidth - document.documentElement.clientWidth, bodyX: document.body.scrollWidth - document.body.clientWidth, previewX: v ? v.scrollWidth - v.clientWidth : -1 }; });
      assertGate(overflow.documentX <= 1 && overflow.bodyX <= 1 && overflow.previewX <= 1, candidate.artifact.artifactType + " " + viewport.name + " horizontal overflow: " + JSON.stringify(overflow));
      const documentScreenshot = resolve(outputDir, candidate.artifact.artifactType + "-" + viewport.name + "-document.png");
      const documentBody = preview.locator("[data-block-id][data-block-type]").first().locator("xpath=..");
      assertGate(await documentBody.count() === 1, candidate.artifact.artifactType + " canonical document body is ambiguous");
      const documentContainer = await documentBody.evaluate((element) => ({
        tag: element.tagName.toLowerCase(),
        className: element.getAttribute("class") ?? "",
        childCount: element.children.length,
        blockCount: element.querySelectorAll("[data-block-id][data-block-type]").length,
      }));
      const documentMarkup = await documentBody.evaluate(async (element) => {
        const clone = element.cloneNode(true) as HTMLElement;
        const sourceImages = [...element.querySelectorAll<HTMLImageElement>("img")];
        const clonedImages = [...clone.querySelectorAll<HTMLImageElement>("img")];
        for (let index = 0; index < sourceImages.length; index++) {
          const response = await fetch(sourceImages[index].src, { credentials: "same-origin" });
          if (!response.ok) throw new Error("document image clone failed with status " + response.status);
          const blob = await response.blob();
          const dataUrl = await new Promise<string>((resolveData, rejectData) => {
            const reader = new FileReader();
            reader.addEventListener("load", () => resolveData(String(reader.result)), { once: true });
            reader.addEventListener("error", () => rejectData(reader.error ?? new Error("document image clone failed")), { once: true });
            reader.readAsDataURL(blob);
          });
          clonedImages[index].src = dataUrl;
          clonedImages[index].loading = "eager";
        }
        return clone.outerHTML;
      });
      const stylesheetText = await page.evaluate(() => Array.from(document.styleSheets).map((sheet) => {
        try { return Array.from(sheet.cssRules).map((rule) => rule.cssText).join("\n"); }
        catch { return ""; }
      }).join("\n"));
      assertGate(stylesheetText.trim() !== "", candidate.artifact.artifactType + " rendered stylesheet rules are unavailable");
      const documentWidth = Math.ceil(await documentBody.evaluate((element) => element.getBoundingClientRect().width));
      const documentPage = await context.newPage();
      try {
        await documentPage.setContent(
          '<!doctype html><html lang="zh-CN"><head><base href="' + baseUrl + '/"><style>' + stylesheetText + '</style></head><body><main data-d2-document-capture>' + documentMarkup + '</main></body></html>',
          { waitUntil: "networkidle" },
        );
        await documentPage.addStyleTag({ content: 'html,body{margin:0;background:#fff}body{width:' + documentWidth + 'px}main[data-d2-document-capture]{box-sizing:border-box;width:100%;padding:16px}' });
        const documentCapture = documentPage.locator("main[data-d2-document-capture]");
        await documentCapture.locator("[data-block-id][data-block-type]").first().waitFor({ state: "visible", timeout: 10000 });
        const documentImage = documentCapture.locator("img[data-public-resource-id][data-content-checksum]");
        await documentImage.evaluate((image) => image.setAttribute("loading", "eager"));
        await documentImage.scrollIntoViewIfNeeded();
        await documentPage.waitForFunction((image) => image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0 && image.naturalHeight > 0, await documentImage.elementHandle(), { timeout: 10000 });
        await documentCapture.screenshot({ path: documentScreenshot });
      } finally {
        await documentPage.close();
      }
      await page.evaluate(() => window.scrollTo(0, 0));
      const screenshot = resolve(outputDir, candidate.artifact.artifactType + "-" + viewport.name + ".png");
      await page.screenshot({ path: screenshot, fullPage: true });
      const attachment = preview.locator("[data-block-type='attachment'] a");
      assertGate(await attachment.count() === 1, candidate.artifact.artifactType + " must render one authenticated attachment link");
      const attachmentResourceId = manifest.resources.find((item) => item.type === "attachment")!.publicResourceId;
      const attachmentResponse = context.waitForEvent("response", {
        predicate: (event) => new URL(event.url()).pathname === "/openclaw/media/api/document-resources/" + encodeURIComponent(attachmentResourceId),
        timeout: 10000,
      }).catch(() => null);
      const attachmentDownload = page.waitForEvent("download", { timeout: 10000 }).catch(() => null);
      await attachment.click();
      const attachmentDelivery = await Promise.race([attachmentResponse.then((response) => ({ response })), attachmentDownload.then((download) => ({ download }))]);
      assertGate(("response" in attachmentDelivery && attachmentDelivery.response) || ("download" in attachmentDelivery && attachmentDelivery.download), candidate.artifact.artifactType + " attachment click produced neither resource response nor download");
      for (const resource of manifest.resources) {
        const resourcePath = "/openclaw/media/api/document-resources/" + encodeURIComponent(resource.publicResourceId);
        const resourceResponse = local.find((item) => item.path === resourcePath && item.status === 200);
        assertGate(resourceResponse, candidate.artifact.artifactType + " resource did not return 200: " + resource.publicResourceId);
        assertGate(resourceResponse.contentChecksum === resource.contentChecksum, candidate.artifact.artifactType + " resource checksum header drift: " + resource.publicResourceId);
      }
      captures.push({ artifactType: candidate.artifact.artifactType, artifactId: candidate.artifact.publicArtifactId, viewport: viewport.name, screenshot, sha256: hashFile(screenshot), documentScreenshot, documentSha256: hashFile(documentScreenshot), documentContainer, expectedRevision: fixture.expectedRevision, observedRevision, expectedBodyChecksum: fixture.expectedBodyChecksum, observedBodyChecksum, overflow, manifest, api: local });
      await page.close();
    } finally { if (!page.isClosed()) await page.close(); }
  } finally { await context.close(); await browser.close(); }
}
async function main() {
  mkdirSync(outputDir, { recursive: true });
  if (new Set(requiredTypes).size !== 5) block("invalid_required_categories", "D2_OVERVIEW_QA_REQUIRED_ARTIFACT_TYPES must contain exactly five unique values");
  if (!cookieHeader.trim()) block("missing_authenticated_cookie", "set D2_OVERVIEW_QA_COOKIE or MEDIA_WEB_QA_USER_A_COOKIE");
  let found = new Map<string, Candidate>();
  if (!blockers.length) {
    const browser = await chromium.launch({ headless: true }), context = await browser.newContext({ viewport: { width: 1920, height: 1088 }, deviceScaleFactor: 1 });
    try { await installCookies(context); found = await discover(context); } catch (e) { failures.push(e instanceof Error ? e.message : String(e)); } finally { await context.close(); await browser.close(); }
  }
  if (!blockers.length && !failures.length) for (const type of requiredTypes) for (const viewport of viewports) {
    const candidate = found.get(type); if (candidate) try { await capture(candidate, viewport); } catch (e) { failures.push(e instanceof Error ? e.message : String(e)); }
  }
  const expected = requiredTypes.length * viewports.length;
  const report = { ok: !blockers.length && !failures.length && captures.length === expected, baseUrl, fixturePath, requiredArtifactTypes: requiredTypes, expectedCaptures: expected, captured: captures.length, captures, api: observations, blockers, failures };
  const reportPath = resolve(outputDir, "report.json"); writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n");
  if (!report.ok) throw new Error("D2 Overview document QA blocked; report=" + reportPath + "; " + blockers.map((v) => v.detail).concat(failures).join(" | "));
  console.log("D2 Overview document QA passed: " + captures.length + "/" + expected + " captures");
}
main().catch((error) => { console.error(error instanceof Error ? error.message : String(error)); process.exit(1); });
