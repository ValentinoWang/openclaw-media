import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { chromium, request, type Browser } from "playwright";

const origin = (process.env.MEDIA_QA_ORIGIN ?? "https://mediapilot.cloud").replace(/\/$/, "");
const storageState = process.env.MEDIA_QA_STORAGE_STATE;
const outputRoot = resolve(
  process.env.MEDIA_QA_OUTPUT ?? "/home/ubuntu/qa-evidence/overview-artifact-names-production",
);
const projectTitle = "创作任务池";

assert.ok(storageState, "MEDIA_QA_STORAGE_STATE is required");
mkdirSync(outputRoot, { recursive: true });

type ArtifactProjection = {
  publicArtifactId: string;
  artifactType: string;
  displayName: string | null;
  bodyAuthority: string;
};

const api = await request.newContext({
  baseURL: origin,
  extraHTTPHeaders: { Accept: "application/json" },
  storageState,
});

let artifacts: ArtifactProjection[] = [];
try {
  const projectsResponse = await api.get("/openclaw/media/api/content-projects?pageSize=100");
  assert.equal(projectsResponse.status(), 200, "production projects API must return 200");
  const projects = (await projectsResponse.json()) as {
    items?: Array<{ publicProjectId?: unknown; title?: unknown }>;
  };
  const project = (projects.items ?? []).find((item) => item.title === projectTitle);
  assert.ok(project, `${projectTitle} must be visible to the ordinary QA role`);
  assert.equal(typeof project.publicProjectId, "string");

  const artifactsResponse = await api.get(
    `/openclaw/media/api/content-projects/${encodeURIComponent(project.publicProjectId)}/artifacts?pageSize=20`,
  );
  assert.equal(artifactsResponse.status(), 200, "production artifacts API must return 200");
  const payload = (await artifactsResponse.json()) as { items?: ArtifactProjection[] };
  artifacts = payload.items ?? [];
} finally {
  await api.dispose();
}

assert.ok(artifacts.length >= 2, `${projectTitle} must expose at least two artifacts`);
assert.ok(
  artifacts.every((artifact) => Object.hasOwn(artifact, "displayName")),
  "every production artifact must project displayName",
);
const apiNames = artifacts.map((artifact) => artifact.displayName?.trim() ?? "");
assert.ok(apiNames.every(Boolean), "every visible production artifact must have a concrete displayName");
assert.equal(new Set(apiNames).size, apiNames.length, "production artifact names must be unique");
const apiTypes = new Set(artifacts.map((artifact) => artifact.artifactType));
assert.ok(apiTypes.has("creation_document"), "production fixture must include a creation document");
assert.ok(apiTypes.has("asset_digest"), "production fixture must include an asset digest");

type ViewportReport = {
  viewport: "desktop" | "mobile";
  artifactCount: number;
  names: string[];
  detailLabels: string[];
  iconLabels: string[];
  distinctIconShapes: number;
  documentOverflowX: number;
  rowOverflowCount: number;
  consoleErrors: string[];
  pageErrors: string[];
  mutations: string[];
  pageScreenshot: string;
  panelScreenshot: string;
};

async function verifyViewport(
  browser: Browser,
  viewport: ViewportReport["viewport"],
  dimensions: { width: number; height: number },
): Promise<ViewportReport> {
  const context = await browser.newContext({ viewport: dimensions, storageState });
  const page = await context.newPage();
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const mutations: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("request", (incoming) => {
    if (["POST", "PUT", "PATCH", "DELETE"].includes(incoming.method())) {
      mutations.push(`${incoming.method()} ${new URL(incoming.url()).pathname}`);
    }
  });

  try {
    await page.goto(`${origin}/openclaw/media/overview`, {
      waitUntil: "domcontentloaded",
      timeout: 30_000,
    });
    await page.getByRole("heading", { name: "运营总览", exact: true }).waitFor({ timeout: 30_000 });
    const project = page
      .getByRole("list", { name: "内容项目列表" })
      .getByRole("button")
      .filter({ hasText: projectTitle })
      .first();
    await project.waitFor({ timeout: 30_000 });
    if ((await project.getAttribute("aria-pressed")) !== "true") await project.click();

    const artifactList = page.getByRole("list", { name: "项目产物列表" });
    await artifactList.waitFor({ timeout: 30_000 });
    const rows = artifactList.getByRole("listitem");
    await rows.first().locator("[data-artifact-name]").waitFor({ timeout: 30_000 });
    const artifactCount = await rows.count();
    assert.equal(artifactCount, artifacts.length, `${viewport}: UI and API artifact counts differ`);

    const names: string[] = [];
    const detailLabels: string[] = [];
    const iconLabels: string[] = [];
    const iconShapes = new Map<string, string>();
    let rowOverflowCount = 0;
    for (let index = 0; index < artifactCount; index += 1) {
      const row = rows.nth(index);
      const name = (await row.locator("[data-artifact-name]").innerText()).trim();
      const detail = (await row.locator("[data-artifact-detail]").innerText()).trim();
      const icon = row.locator("[data-artifact-icon]");
      const iconLabel = (await icon.getAttribute("data-artifact-icon")) ?? "";
      const iconShape = await icon.locator("svg").evaluate((svg) => svg.innerHTML);
      const geometry = await row.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        return { left: rect.left, right: rect.right, viewport: document.documentElement.clientWidth };
      });
      if (geometry.left < -0.5 || geometry.right > geometry.viewport + 0.5) rowOverflowCount += 1;
      names.push(name);
      detailLabels.push(detail);
      iconLabels.push(iconLabel);
      if (!iconShapes.has(iconLabel)) iconShapes.set(iconLabel, iconShape);
    }

    assert.deepEqual(new Set(names), new Set(apiNames), `${viewport}: rendered names differ from API names`);
    assert.equal(new Set(names).size, names.length, `${viewport}: rendered artifact names are repeated`);
    assert.ok(
      names.every((name, index) => name !== detailLabels[index].split("·")[0]?.trim()),
      `${viewport}: a type label is still rendered as the artifact name`,
    );
    assert.ok(iconLabels.includes("创作文档"), `${viewport}: creation-document icon is missing`);
    assert.ok(iconLabels.includes("素材摘要"), `${viewport}: asset-digest icon is missing`);
    assert.notEqual(
      iconShapes.get("创作文档"),
      iconShapes.get("素材摘要"),
      `${viewport}: different artifact types render the same icon shape`,
    );
    assert.equal(rowOverflowCount, 0, `${viewport}: artifact rows overflow horizontally`);

    const documentOverflowX = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    assert.ok(documentOverflowX <= 1, `${viewport}: document overflows horizontally`);
    assert.deepEqual(consoleErrors, [], `${viewport}: browser console errors were emitted`);
    assert.deepEqual(pageErrors, [], `${viewport}: page errors were emitted`);
    assert.deepEqual(mutations, [], `${viewport}: read-only QA emitted mutation requests`);

    const pageScreenshot = resolve(outputRoot, `overview-artifact-names-${viewport}.png`);
    const panelScreenshot = resolve(outputRoot, `overview-artifact-panel-${viewport}.png`);
    await page.screenshot({ path: pageScreenshot, fullPage: true });
    const artifactHeading = page.getByRole("heading", { name: "项目产物", exact: true });
    assert.equal(
      await artifactHeading.count(),
      1,
      `${viewport}: focused screenshot target is not the artifact panel`,
    );
    await artifactHeading.scrollIntoViewIfNeeded();
    await page.screenshot({ path: panelScreenshot });
    return {
      viewport,
      artifactCount,
      names,
      detailLabels: [...new Set(detailLabels)],
      iconLabels: [...new Set(iconLabels)],
      distinctIconShapes: new Set(iconShapes.values()).size,
      documentOverflowX,
      rowOverflowCount,
      consoleErrors,
      pageErrors,
      mutations,
      pageScreenshot,
      panelScreenshot,
    };
  } finally {
    await context.close();
  }
}

const browser = await chromium.launch({ headless: true });
let viewports: ViewportReport[];
try {
  viewports = [
    await verifyViewport(browser, "desktop", { width: 1440, height: 1000 }),
    await verifyViewport(browser, "mobile", { width: 390, height: 844 }),
  ];
} finally {
  await browser.close();
}

const report = {
  ok: true,
  origin,
  projectTitle,
  api: {
    artifactCount: artifacts.length,
    uniqueNames: new Set(apiNames).size,
    artifactTypes: [...apiTypes].sort(),
  },
  viewports,
};
writeFileSync(resolve(outputRoot, "report.json"), `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({
  ok: report.ok,
  outputRoot,
  api: report.api,
  viewports: viewports.map((item) => ({
    viewport: item.viewport,
    artifactCount: item.artifactCount,
    distinctIconShapes: item.distinctIconShapes,
    documentOverflowX: item.documentOverflowX,
    rowOverflowCount: item.rowOverflowCount,
    consoleErrors: item.consoleErrors.length,
    pageErrors: item.pageErrors.length,
    mutations: item.mutations.length,
  })),
}, null, 2));
