import { chromium, type Page, type Route } from "playwright";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const baseUrl = (process.env.OVERVIEW_INTERACTION_QA_URL ?? "http://127.0.0.1:5188/openclaw/media/index.media.html").replace(/\/$/, "");
const outputDir = process.env.OVERVIEW_INTERACTION_QA_OUTPUT_DIR?.trim();

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
    csrfToken: "overview-interaction-qa-csrf",
    expiresAt: "2026-08-08T00:00:00+00:00",
    schemaVersion: "media_web_business_pages_v2",
  },
};

const projects = [
  { publicProjectId: "project_overview_alpha", title: "桌面项目选择回归验证 Alpha", workspaceMode: "personal_web", stage: "creation", status: "active", artifactCounts: { creation_document: 1 }, updatedAt: "2026-08-05T08:00:00+00:00" },
  { publicProjectId: "project_overview_beta", title: "桌面项目选择回归验证 Beta", workspaceMode: "personal_web", stage: "review", status: "active", artifactCounts: { creation_document: 1 }, updatedAt: "2026-08-06T08:00:00+00:00" },
];

const creationDocumentName = "面向新手的完整创作任务名称：从选题判断到脚本交付的超长桌面与移动端布局验证";
const assetDigestName = "秋季训练内容参考素材清单";

const artifacts = {
  [projects[0].publicProjectId]: [
    { publicArtifactId: "artifact_overview_alpha", publicProjectId: projects[0].publicProjectId, artifactType: "creation_document", displayName: "Alpha 创作文档", bodyAuthority: "internal", currentRevision: 3, syncStatus: "not_applicable", updatedAt: "2026-08-05T08:00:00+00:00", allowedActions: ["view"] },
  ],
  [projects[1].publicProjectId]: [
    { publicArtifactId: "artifact_overview_beta", publicProjectId: projects[1].publicProjectId, artifactType: "creation_document", displayName: creationDocumentName, bodyAuthority: "lark", currentRevision: 4, syncStatus: "synced", updatedAt: "2026-08-06T08:00:00+00:00", allowedActions: ["view", "open_lark", "regenerate"], organizationDocumentUrl: "https://example.feishu.cn/wiki/overviewBetaDocument" },
    { publicArtifactId: "artifact_overview_beta_assets", publicProjectId: projects[1].publicProjectId, artifactType: "asset_digest", displayName: assetDigestName, bodyAuthority: "internal", currentRevision: 2, syncStatus: "not_applicable", updatedAt: "2026-08-05T09:00:00+00:00", allowedActions: ["view"] },
  ],
} as const;

async function fulfill(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installApi(page: Page) {
  await page.route("**/openclaw/media/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/openclaw\/media\/api/, "");
    console.log(`mock ${request.method()} ${path}`);
    if (path === "/session") return fulfill(route, session);
    if (path === "/capabilities") return fulfill(route, { schemaVersion: "capability_catalog_v3", catalogVersion: `sha256:${"0".repeat(64)}`, capabilities: [] });
    if (path === "/dashboard") return fulfill(route, {
      schemaVersion: "media_web_business_pages_v2", revision: 12,
      summary: {
        counts: { contentProjects: 2, runs: 7, assets: 48, tracks: 5, creators: 23, publishedPosts: 9, reviews: 4 },
        contentProjectStages: ["research", "assets", "decision", "creation", "publishing", "review"].map((stage, index) => ({ stage, count: index + 1 })),
        pendingDecisions: 3, pendingPublishing: 2, pendingReviews: 1,
        taskSummary: { queued: 0, running: 0, needsAttention: 0, failed: 0 }, coverage: { known: 108, unknown: 0, unavailable: 0 }, generatedAt: "2026-08-06T08:00:00+00:00", revision: 12,
      },
    });
    if (path === "/content-projects") return fulfill(route, { schemaVersion: "media_web_business_pages_v2", revision: 12, items: projects, nextCursor: null });
    const artifactMatch = path.match(/^\/content-projects\/([^/]+)\/artifacts$/);
    if (artifactMatch) return fulfill(route, { schemaVersion: "media_web_business_pages_v2", revision: 12, items: artifacts[artifactMatch[1] as keyof typeof artifacts] ?? [], nextCursor: null });
    const bodyMatch = path.match(/^\/documents\/([^/]+)\/body$/);
    if (bodyMatch) return fulfill(route, {
      schemaVersion: "media_web_business_pages_v2", revision: 1,
      data: {
        artifact: { publicArtifactId: bodyMatch[1], artifactKind: "creation_document", workspaceMode: "organization_lark", bodyAuthority: "lark", currentRevision: 1, updatedAt: "2026-08-06T08:00:00+00:00" },
        revision: { publicArtifactId: bodyMatch[1], artifactKind: "creation_document", bodyAuthority: "lark", revision: 1, baseRevision: null, state: "ready", bodyChecksum: "overview-interaction-body", remoteDocumentVersion: "42", body: { schemaVersion: "media.document.body.v1", blocks: [{ id: "overview-interaction-heading", type: "heading_1", attrs: {}, content: [{ type: "text", text: `网页正文 ${bodyMatch[1]}`, marks: [] }] }] }, createdAt: "2026-08-06T08:00:00+00:00", updatedAt: "2026-08-06T08:00:00+00:00" },
      },
    });
    if (path === "/tasks") return fulfill(route, { schemaVersion: "media_web_business_pages_v2", revision: 0, items: [], nextCursor: null, tasks: [] });
    return fulfill(route, { error: { code: "unexpected_qa_request", message: `${request.method()} ${path}` } }, 500);
  });
}

function requireCondition(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
try {
  await installApi(page);
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "运营总览" }).waitFor({ timeout: 10_000 });
  const betaProject = page.getByRole("button", { name: /桌面项目选择回归验证 Beta/ });
  await betaProject.click();
  requireCondition((await betaProject.getAttribute("aria-pressed")) === "true", "selected Overview project must expose aria-pressed=true");
  const artifactRow = page.locator('[data-artifact-row="artifact_overview_beta"]');
  const assetDigestRow = page.locator('[data-artifact-row="artifact_overview_beta_assets"]');
  await artifactRow.scrollIntoViewIfNeeded();
  await assetDigestRow.waitFor({ state: "visible" });
  const creationPresentation = await artifactRow.evaluate((button) => {
    const item = button.closest<HTMLElement>("article");
    const title = item?.querySelector<HTMLElement>("[data-artifact-name]") ?? null;
    const detail = item?.querySelector<HTMLElement>("[data-artifact-detail]") ?? null;
    const icon = item?.querySelector<SVGElement>("[data-artifact-icon] svg") ?? null;
    const identity = item?.querySelector<HTMLElement>("[data-artifact-identity]") ?? null;
    if (!title || !detail || !icon || !identity) return null;
    const titleRect = title.getBoundingClientRect();
    const identityRect = identity.getBoundingClientRect();
    return {
      title: title.textContent?.trim(),
      detail: detail.textContent?.trim(),
      iconShape: icon.innerHTML,
      titleRight: titleRect.right,
      identityRight: identityRect.right,
      titleHeight: titleRect.height,
      titleLineHeight: Number.parseFloat(getComputedStyle(title).lineHeight),
    };
  });
  const assetPresentation = await assetDigestRow.evaluate((button) => {
    const item = button.closest<HTMLElement>("article");
    const title = item?.querySelector<HTMLElement>("[data-artifact-name]") ?? null;
    const detail = item?.querySelector<HTMLElement>("[data-artifact-detail]") ?? null;
    const icon = item?.querySelector<SVGElement>("[data-artifact-icon] svg") ?? null;
    const identity = item?.querySelector<HTMLElement>("[data-artifact-identity]") ?? null;
    if (!title || !detail || !icon || !identity) return null;
    const titleRect = title.getBoundingClientRect();
    const identityRect = identity.getBoundingClientRect();
    return {
      title: title.textContent?.trim(),
      detail: detail.textContent?.trim(),
      iconShape: icon.innerHTML,
      titleRight: titleRect.right,
      identityRight: identityRect.right,
      titleHeight: titleRect.height,
      titleLineHeight: Number.parseFloat(getComputedStyle(title).lineHeight),
    };
  });
  const artifactPresentation = { creation: creationPresentation, assets: assetPresentation };
  requireCondition(artifactPresentation.creation && artifactPresentation.assets, "artifact names, details, and global icons must be rendered");
  requireCondition(artifactPresentation.creation.title === creationDocumentName, "creation document must show its concrete document name");
  requireCondition(artifactPresentation.assets.title === assetDigestName, "asset digest must show its concrete task name");
  requireCondition(artifactPresentation.creation.detail?.includes("创作文档"), "creation document type must remain visible as secondary metadata");
  requireCondition(artifactPresentation.assets.detail?.includes("素材摘要"), "asset digest type must remain visible as secondary metadata");
  requireCondition(artifactPresentation.creation.iconShape !== artifactPresentation.assets.iconShape, "different artifact types must use different global icon shapes");
  requireCondition(artifactPresentation.creation.titleRight <= artifactPresentation.creation.identityRight + 0.5, "long artifact name must remain inside the desktop identity column");
  requireCondition(artifactPresentation.creation.titleHeight <= artifactPresentation.creation.titleLineHeight * 2 + 1, "long artifact name must be clamped to two desktop lines");
  const geometry = await page.evaluate(() => {
    const primary = document.querySelector<HTMLElement>("[data-page-primary]");
    const row = document.querySelector<HTMLElement>('[data-artifact-row="artifact_overview_beta"]');
    if (!primary || !row) return null;
    return { primaryScrollRange: primary.scrollHeight - primary.clientHeight, rowTag: row.tagName };
  });
  requireCondition(geometry, "Overview interaction fixture did not render the primary rail or selected artifact");
  requireCondition(geometry.primaryScrollRange > 1, "Overview primary rail must scroll its lower interactive panels on desktop");
  requireCondition(geometry.rowTag === "BUTTON", `artifact preview action must be a real button, received ${geometry.rowTag}`);
  const artifactButton = artifactRow;
  await artifactButton.click();
  const preview = page.getByRole("region", { name: "文档正文预览" });
  await preview.waitFor({ state: "visible", timeout: 10_000 });
  const previewPlacement = await artifactButton.evaluate((button) => {
    const item = button.closest<HTMLElement>("article");
    const adjacentPreview = item?.nextElementSibling as HTMLElement | null;
    if (!item || !adjacentPreview) return null;
    const itemRect = item.getBoundingClientRect();
    const previewRect = adjacentPreview.getBoundingClientRect();
    return {
      expanded: button.getAttribute("aria-expanded"),
      previewLabel: adjacentPreview.getAttribute("aria-label"),
      itemBottom: itemRect.bottom,
      previewTop: previewRect.top,
      viewportHeight: window.innerHeight,
    };
  });
  requireCondition(previewPlacement, "selected artifact must render an adjacent preview region");
  requireCondition(previewPlacement.expanded === "true", "selected artifact preview action must expose aria-expanded=true");
  requireCondition(previewPlacement.previewLabel === "文档正文预览", "selected artifact preview must immediately follow its artifact row");
  requireCondition(Math.abs(previewPlacement.previewTop - previewPlacement.itemBottom) <= 1, "artifact preview must open directly below the selected artifact row");
  requireCondition(previewPlacement.previewTop < previewPlacement.viewportHeight, `artifact preview must begin inside the current viewport after the action is clicked: ${JSON.stringify(previewPlacement)}`);
  const organizationDocumentLink = artifactButton.locator("xpath=ancestor::article").getByRole("link", { name: "打开组织文档" });
  await organizationDocumentLink.waitFor({ state: "visible" });
  const desktopLayout = await artifactRow.evaluate((button) => {
    const item = button.closest<HTMLElement>("article");
    const identity = item?.querySelector<HTMLElement>("[data-artifact-identity]") ?? null;
    const meta = item?.querySelector<HTMLElement>("[data-artifact-meta]") ?? null;
    const actions = item?.querySelector<HTMLElement>("[data-artifact-actions]") ?? null;
    const externalLink = actions?.querySelector<HTMLElement>('a[href*="feishu.cn"]') ?? null;
    if (!item || !identity || !meta || !actions || !externalLink) return null;
    const itemRect = item.getBoundingClientRect();
    const identityRect = identity.getBoundingClientRect();
    const metaRect = meta.getBoundingClientRect();
    const actionsRect = actions.getBoundingClientRect();
    const buttonRect = button.getBoundingClientRect();
    const linkRect = externalLink.getBoundingClientRect();
    return {
      itemBackground: getComputedStyle(item).backgroundColor,
      itemHeight: itemRect.height,
      itemWidth: itemRect.width,
      gridColumns: getComputedStyle(item).gridTemplateColumns,
      itemRight: itemRect.right,
      identityRight: identityRect.right,
      metaLeft: metaRect.left,
      metaRight: metaRect.right,
      actionsLeft: actionsRect.left,
      buttonTop: buttonRect.top,
      linkTop: linkRect.top,
      linkRight: linkRect.right,
      buttonHeight: buttonRect.height,
      linkHeight: linkRect.height,
      linkColor: getComputedStyle(externalLink).color,
      linkBorderWidths: [
        getComputedStyle(externalLink).borderTopWidth,
        getComputedStyle(externalLink).borderRightWidth,
        getComputedStyle(externalLink).borderBottomWidth,
        getComputedStyle(externalLink).borderLeftWidth,
      ],
    };
  });
  requireCondition(desktopLayout, "organization document artifact must expose its metadata and external action");
  requireCondition(desktopLayout.identityRight <= desktopLayout.metaLeft + 0.5, "artifact identity and sync metadata must occupy separate desktop columns");
  requireCondition(desktopLayout.metaRight <= desktopLayout.actionsLeft + 0.5, "artifact actions must follow the sync metadata column");
  requireCondition(Math.abs(desktopLayout.buttonTop - desktopLayout.linkTop) <= 1, "artifact actions must align in one desktop action group");
  if (outputDir) {
    await mkdir(outputDir, { recursive: true });
    await page.getByRole("list", { name: "项目产物列表" }).screenshot({ path: path.join(outputDir, "artifact-layout-1440.png") });
  }
  requireCondition(desktopLayout.itemHeight <= 100, `artifact row must stay compact on desktop: ${JSON.stringify(desktopLayout)}`);
  requireCondition(new Set(desktopLayout.linkBorderWidths).size === 1, "organization document action must use a complete button border rather than a vertical divider");
  requireCondition(desktopLayout.linkColor === "rgb(255, 255, 255)", `organization document action must retain readable primary-button text: ${JSON.stringify(desktopLayout)}`);
  requireCondition(desktopLayout.itemBackground !== "rgba(0, 0, 0, 0)", "selected artifact background must cover the complete record, including the external action");
  requireCondition(desktopLayout.linkRight <= desktopLayout.itemRight + 0.5, "organization document action must remain inside the artifact record");
  requireCondition(await page.getByText("查看 · 打开机构云文档 · 重新生成", { exact: true }).count() === 0, "artifact row must not repeat actionable commands as passive text");
  await preview.getByRole("heading", { name: "网页正文 artifact_overview_beta", level: 1 }).waitFor({ timeout: 10_000 });
  await artifactButton.focus();
  await page.keyboard.press("Enter");
  await preview.waitFor({ state: "hidden", timeout: 10_000 });
  await page.setViewportSize({ width: 1024, height: 768 });
  await artifactRow.scrollIntoViewIfNeeded();
  const tabletLayout = await artifactRow.evaluate((button) => {
    const item = button.closest<HTMLElement>("article");
    const actions = item?.querySelector<HTMLElement>("[data-artifact-actions]") ?? null;
    const externalLink = actions?.querySelector<HTMLElement>('a[href*="feishu.cn"]') ?? null;
    const hero = document.querySelector<HTMLElement>("[data-page-prelude] .mg-hero");
    if (!item || !actions || !externalLink || !hero) return null;
    const itemRect = item.getBoundingClientRect();
    const actionsRect = actions.getBoundingClientRect();
    const buttonRect = button.getBoundingClientRect();
    const linkRect = externalLink.getBoundingClientRect();
    const heroRect = hero.getBoundingClientRect();
    return {
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
      itemLeft: itemRect.left,
      itemRight: itemRect.right,
      actionsTop: actionsRect.top,
      buttonRight: buttonRect.right,
      linkRight: linkRect.right,
      heroHeight: heroRect.height,
    };
  });
  requireCondition(tabletLayout, "tablet Overview artifact layout did not render");
  requireCondition(tabletLayout.documentWidth <= tabletLayout.viewportWidth + 1, `tablet Overview must not horizontally overflow: ${JSON.stringify(tabletLayout)}`);
  requireCondition(tabletLayout.itemLeft >= -0.5 && tabletLayout.itemRight <= tabletLayout.viewportWidth + 0.5, "tablet artifact record must stay inside its viewport");
  requireCondition(tabletLayout.buttonRight <= tabletLayout.itemRight + 0.5 && tabletLayout.linkRight <= tabletLayout.itemRight + 0.5, "tablet artifact actions must stay inside their record");
  requireCondition(tabletLayout.heroHeight <= 140, `tablet hero must remain compact: ${JSON.stringify(tabletLayout)}`);
  if (outputDir) {
    await page.getByRole("list", { name: "项目产物列表" }).screenshot({ path: path.join(outputDir, "artifact-layout-1024.png") });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await artifactRow.scrollIntoViewIfNeeded();
  const mobileLayout = await artifactRow.evaluate((button) => {
    const item = button.closest<HTMLElement>("article");
    const identity = item?.querySelector<HTMLElement>("[data-artifact-identity]") ?? null;
    const meta = item?.querySelector<HTMLElement>("[data-artifact-meta]") ?? null;
    const actions = item?.querySelector<HTMLElement>("[data-artifact-actions]") ?? null;
    const externalLink = actions?.querySelector<HTMLElement>('a[href*="feishu.cn"]') ?? null;
    if (!item || !identity || !meta || !actions || !externalLink) return null;
    const itemRect = item.getBoundingClientRect();
    const identityRect = identity.getBoundingClientRect();
    const metaRect = meta.getBoundingClientRect();
    const actionsRect = actions.getBoundingClientRect();
    const buttonRect = button.getBoundingClientRect();
    const linkRect = externalLink.getBoundingClientRect();
    return {
      itemLeft: itemRect.left,
      itemRight: itemRect.right,
      identityBottom: identityRect.bottom,
      metaTop: metaRect.top,
      metaBottom: metaRect.bottom,
      actionsTop: actionsRect.top,
      buttonLeft: buttonRect.left,
      buttonRight: buttonRect.right,
      linkLeft: linkRect.left,
      linkRight: linkRect.right,
      viewportWidth: document.documentElement.clientWidth,
    };
  });
  requireCondition(mobileLayout, "mobile artifact layout did not render both actions");
  requireCondition(mobileLayout.itemLeft >= 0 && mobileLayout.itemRight <= mobileLayout.viewportWidth + 0.5, "artifact record must not overflow the mobile viewport");
  requireCondition(mobileLayout.identityBottom <= mobileLayout.metaTop + 0.5, "mobile artifact metadata must follow the identity block");
  requireCondition(mobileLayout.metaBottom <= mobileLayout.actionsTop + 0.5, "mobile artifact actions must follow the metadata block");
  requireCondition(mobileLayout.buttonLeft >= mobileLayout.itemLeft - 0.5 && mobileLayout.buttonRight <= mobileLayout.itemRight + 0.5, "preview action must stay within the mobile artifact record");
  requireCondition(mobileLayout.linkLeft >= mobileLayout.itemLeft - 0.5 && mobileLayout.linkRight <= mobileLayout.itemRight + 0.5, "organization document action must stay within the mobile artifact record");
  const mobileHero = await page.locator("[data-page-prelude] .mg-hero").evaluate((hero) => ({
    height: hero.getBoundingClientRect().height,
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
  }));
  requireCondition(mobileHero.documentWidth <= mobileHero.viewportWidth + 1, `mobile Overview must not horizontally overflow: ${JSON.stringify(mobileHero)}`);
  requireCondition(mobileHero.height <= 140, `mobile hero must remain compact: ${JSON.stringify(mobileHero)}`);
  const mobileTitleLayout = await artifactRow.evaluate((button) => {
    const item = button.closest<HTMLElement>("article");
    const identity = item?.querySelector<HTMLElement>("[data-artifact-identity]") ?? null;
    const title = item?.querySelector<HTMLElement>("[data-artifact-name]") ?? null;
    if (!identity || !title) return null;
    const identityRect = identity.getBoundingClientRect();
    const titleRect = title.getBoundingClientRect();
    return {
      titleRight: titleRect.right,
      identityRight: identityRect.right,
      titleHeight: titleRect.height,
      titleLineHeight: Number.parseFloat(getComputedStyle(title).lineHeight),
    };
  });
  requireCondition(mobileTitleLayout, "mobile artifact name must remain visible");
  requireCondition(mobileTitleLayout.titleRight <= mobileTitleLayout.identityRight + 0.5, "long artifact name must remain inside the mobile identity block");
  requireCondition(mobileTitleLayout.titleHeight <= mobileTitleLayout.titleLineHeight * 2 + 1, "long artifact name must be clamped to two mobile lines");
  if (outputDir) {
    await artifactRow.click();
    await page.getByRole("region", { name: "文档正文预览" }).waitFor({ state: "visible" });
    await page.getByRole("list", { name: "项目产物列表" }).screenshot({ path: path.join(outputDir, "artifact-layout-mobile.png") });
  }
  requireCondition(pageErrors.length === 0, `Overview emitted page errors: ${pageErrors.join(" | ")}`);
} finally {
  await browser.close();
}

console.log("Overview desktop interaction QA passed.");
