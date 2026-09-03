import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  writeFileSync,
} from "node:fs";
import { basename, resolve } from "node:path";
import { chromium, type BrowserContext, type Page } from "playwright";
import {
  adminMediaNav,
  ordinaryMediaNav,
  retiredMediaNavLabels,
} from "../../src/media/mediaRoleIa";

const baseUrl = (
  process.env.MEDIA_ROLE_QA_URL ?? "http://127.0.0.1/openclaw/media"
).replace(/\/$/, "");
const outputDir = resolve(
  process.env.MEDIA_ROLE_QA_OUTPUT ?? "/home/ubuntu/media-role-qa",
);
const servedRoot = resolve(
  process.env.MEDIA_ROLE_QA_SERVED_ROOT ?? "/var/www/openclaw/media",
);
const collectRailBottomFailures =
  process.env.MEDIA_ROLE_QA_COLLECT_RAIL_BOTTOMS === "1";
const allowLegacyTerminalSurfaces =
  process.env.MEDIA_ROLE_QA_ALLOW_LEGACY_TERMINAL_SURFACES === "1";
const cookieHeaders = {
  ordinary:
    process.env.MEDIA_WEB_QA_USER_A_COOKIE ??
    process.env.MEDIA_WEB_QA_COOKIE ??
    "",
  admin: process.env.MEDIA_WEB_QA_ADMIN_COOKIE ?? "",
};

type Role = keyof typeof cookieHeaders;
type Result = {
  role: Role;
  path: string;
  label: string;
  screenshot: string;
  sha256: string;
  apiRequests: string[];
  viewportFit: {
    horizontalOverflow: number;
    verticalOverflow: number;
  };
};
type ServedRelease = {
  servedRoot: string;
  releasePath: string;
  releaseId: string;
  entrypointSha256: string;
  manifestSha256: string | null;
};
type ClippedContentObservation = {
  surface: string;
  overflowX: string;
  overflowY: string;
  paddingBox: {
    top: number;
    right: number;
    bottom: number;
    left: number;
  };
  terminalY: { element: string; top: number; bottom: number };
  terminalX: { element: string; left: number; right: number };
  clientHeight: number;
  clientWidth: number;
  scrollHeight: number;
  scrollWidth: number;
  tabIndex: number;
  accessibleName: string;
  scrollStateMarker: string | null;
};
const results: Result[] = [];
const failures: string[] = [];
const ordinaryNavGroups = ["工作台", "内容运营", "本机协作", "账户"] as const;
const bottomLandmarks: Partial<Record<string, string>> = {
  "/overview": "需要处理",
  "/archives": "WAV",
  "/reviews": "复盘状态",
  "/usage-billing": "最近兑换记录",
  "/admin/overview": "最近管理操作",
};
const persistentRailPaths = new Set([
  "/overview",
  "/tracks",
  "/assets",
  "/runs",
  "/publishing",
  "/decisions",
  "/archives",
  "/reviews",
  "/usage-billing",
  "/invites",
  "/admin/overview",
  "/admin/access",
  "/admin/tenants",
  "/admin/billing",
  "/admin/upstreams",
]);
const minimumRailWidths: Partial<Record<string, number>> = {
  "/publishing": 560,
  "/reviews": 480,
  "/usage-billing": 480,
  "/invites": 500,
  "/admin/access": 400,
  "/admin/tenants": 390,
  "/admin/billing": 400,
  "/admin/upstreams": 400,
};
const railTopTolerance: Partial<Record<string, number>> = {
  "/publishing": 18,
};
const fullyVisibleItemCounts: Partial<Record<string, number>> = {
  "/archives": 3,
  "/reviews": 2,
};

function sha256File(path: string) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function inspectServedRelease(): ServedRelease {
  const releasePath = realpathSync(servedRoot);
  const entrypoint = resolve(releasePath, "index.html");
  const manifest = resolve(releasePath, ".manifest.sha256");
  return {
    servedRoot,
    releasePath,
    releaseId: basename(releasePath),
    entrypointSha256: sha256File(entrypoint),
    manifestSha256: existsSync(manifest) ? sha256File(manifest) : null,
  };
}

function requireContract(
  condition: boolean,
  message: string,
): asserts condition {
  if (!condition) throw new Error(message);
}

function requireOrCollectRailContract(condition: boolean, message: string) {
  if (condition) return true;
  if (collectRailBottomFailures) {
    failures.push(message);
    return false;
  }
  throw new Error(message);
}

function evaluateClippedContentGeometry(
  observations: readonly ClippedContentObservation[],
) {
  const tolerance = 1;
  const violations: string[] = [];
  for (const observation of observations) {
    const hasAccessibleFocusableScroll =
      observation.tabIndex >= 0 && observation.accessibleName !== "";
    const verticalScrollOverflow =
      observation.scrollHeight - observation.clientHeight;
    const verticalTerminalOverflow =
      observation.terminalY.bottom - observation.paddingBox.bottom;
    let reportedVerticalTerminal = false;
    if (["hidden", "clip"].includes(observation.overflowY)) {
      if (verticalTerminalOverflow > tolerance) {
        violations.push(
          `${observation.surface} clips terminal content ${observation.terminalY.element} by ${verticalTerminalOverflow.toFixed(1)}px below its padding box (overflow-y: ${observation.overflowY})`,
        );
        reportedVerticalTerminal = true;
      }
    } else if (
      ["auto", "scroll"].includes(observation.overflowY) &&
      verticalTerminalOverflow > tolerance &&
      !(verticalScrollOverflow > tolerance && hasAccessibleFocusableScroll)
    ) {
      violations.push(
        `${observation.surface} lets terminal content ${observation.terminalY.element} extend ${verticalTerminalOverflow.toFixed(1)}px below its padding box without an accessible, keyboard-focusable internal scroll region (overflow-y: ${observation.overflowY})`,
      );
      reportedVerticalTerminal = true;
    }
    if (
      ["auto", "scroll"].includes(observation.overflowY) &&
      verticalScrollOverflow > tolerance &&
      !hasAccessibleFocusableScroll &&
      !reportedVerticalTerminal
    ) {
      violations.push(
        `${observation.surface} has ${verticalScrollOverflow.toFixed(1)}px vertical scroll overflow without both keyboard focus and an accessible name`,
      );
    }

    const horizontalScrollOverflow =
      observation.scrollWidth - observation.clientWidth;
    const horizontalTerminalOverflow =
      observation.terminalX.right - observation.paddingBox.right;
    let reportedHorizontalTerminal = false;
    if (["hidden", "clip"].includes(observation.overflowX)) {
      if (horizontalTerminalOverflow > tolerance) {
        violations.push(
          `${observation.surface} clips terminal content ${observation.terminalX.element} by ${horizontalTerminalOverflow.toFixed(1)}px beyond its padding box (overflow-x: ${observation.overflowX})`,
        );
        reportedHorizontalTerminal = true;
      }
    } else if (
      ["auto", "scroll"].includes(observation.overflowX) &&
      horizontalTerminalOverflow > tolerance &&
      !(horizontalScrollOverflow > tolerance && hasAccessibleFocusableScroll)
    ) {
      violations.push(
        `${observation.surface} lets terminal content ${observation.terminalX.element} extend ${horizontalTerminalOverflow.toFixed(1)}px beyond its padding box without an accessible, keyboard-focusable internal scroll region (overflow-x: ${observation.overflowX})`,
      );
      reportedHorizontalTerminal = true;
    }
    if (
      ["auto", "scroll"].includes(observation.overflowX) &&
      horizontalScrollOverflow > tolerance &&
      !hasAccessibleFocusableScroll &&
      !reportedHorizontalTerminal
    ) {
      violations.push(
        `${observation.surface} has ${horizontalScrollOverflow.toFixed(1)}px horizontal scroll overflow without both keyboard focus and an accessible name`,
      );
    }
  }
  return violations;
}

function applyClippedContentContract(
  violations: readonly string[],
  role: Role,
  path: string,
  collect = collectRailBottomFailures,
  failureTarget = failures,
) {
  if (violations.length === 0) return true;
  const message = `${role} ${path} clipped-content geometry failed: ${violations.join(" | ")}`;
  if (collect) {
    failureTarget.push(message);
    return false;
  }
  throw new Error(message);
}

function runClippedContentGeometrySelfTests() {
  const observation = (
    overrides: Partial<ClippedContentObservation>,
  ): ClippedContentObservation => ({
    surface: "section.fixture",
    overflowX: "visible",
    overflowY: "hidden",
    paddingBox: { top: 0, right: 200, bottom: 100, left: 0 },
    terminalY: { element: "p:last-child", top: 80, bottom: 100 },
    terminalX: { element: "p:last-child", left: 0, right: 200 },
    clientHeight: 100,
    clientWidth: 200,
    scrollHeight: 100,
    scrollWidth: 200,
    tabIndex: -1,
    accessibleName: "",
    scrollStateMarker: null,
    ...overrides,
  });
  const clippedFixture = evaluateClippedContentGeometry([
    observation({
      surface: "section.red-clipped",
      terminalY: { element: "p:last-child", top: 86, bottom: 106 },
    }),
  ]);
  requireContract(
    clippedFixture.length === 1 && clippedFixture[0]?.includes("6.0px"),
    `clipped-content self-test failed to reject hidden overflow: ${clippedFixture.join(" | ")}`,
  );
  const missedChildTerminalFixture = evaluateClippedContentGeometry([
    observation({
      surface: "section.red-child-terminal",
      overflowY: "auto",
      terminalY: {
        element: "p.card-summary > #text",
        top: 86,
        bottom: 106,
      },
      scrollHeight: 106,
      accessibleName: "Summary card",
    }),
  ]);
  requireContract(
    missedChildTerminalFixture.length === 1 &&
      missedChildTerminalFixture[0]?.includes("6.0px"),
    `clipped-content self-test failed to reject child copy beyond its card padding box: ${missedChildTerminalFixture.join(" | ")}`,
  );
  const inaccessibleScrollFixture = evaluateClippedContentGeometry([
    observation({
      surface: "section.red-scroll",
      overflowY: "auto",
      scrollHeight: 140,
    }),
  ]);
  requireContract(
    inaccessibleScrollFixture.length === 1 &&
      inaccessibleScrollFixture[0]?.includes("40.0px"),
    `clipped-content self-test failed to reject inaccessible scrolling: ${inaccessibleScrollFixture.join(" | ")}`,
  );
  const greenFixtures = evaluateClippedContentGeometry([
    observation({ surface: "section.green-contained" }),
    observation({
      surface: "section.green-accessible-focusable",
      overflowY: "auto",
      terminalY: { element: "button:last-child", top: 120, bottom: 140 },
      scrollHeight: 140,
      tabIndex: 0,
      accessibleName: "Audit records",
    }),
    observation({
      surface: "section.green-horizontal-scroll",
      overflowX: "auto",
      terminalX: { element: "button:last-child", left: 210, right: 240 },
      scrollWidth: 240,
      tabIndex: 0,
      accessibleName: "Card actions",
    }),
    observation({
      surface: "section.green-state",
      overflowY: "auto",
      terminalY: { element: "p:last-child", top: 120, bottom: 140 },
      scrollHeight: 140,
      tabIndex: 0,
      accessibleName: "Status history",
      scrollStateMarker: "data-scroll-state",
    }),
  ]);
  requireContract(
    greenFixtures.length === 0,
    `clipped-content self-test rejected valid geometry: ${greenFixtures.join(" | ")}`,
  );
  const collectedFailures: string[] = [];
  requireContract(
    !applyClippedContentContract(
      clippedFixture,
      "ordinary",
      "/collect-fixture",
      true,
      collectedFailures,
    ) &&
      collectedFailures.length === 1 &&
      collectedFailures[0]?.includes("section.red-clipped"),
    "clipped-content self-test failed to collect and continue",
  );
  let failFastMessage = "";
  try {
    applyClippedContentContract(
      clippedFixture,
      "ordinary",
      "/fail-fast-fixture",
      false,
      [],
    );
  } catch (error) {
    failFastMessage = error instanceof Error ? error.message : String(error);
  }
  requireContract(
    failFastMessage.includes("section.red-clipped"),
    "clipped-content self-test failed to preserve default fail-fast behavior",
  );
  const greenFailureTarget: string[] = [];
  requireContract(
    applyClippedContentContract(
      greenFixtures,
      "ordinary",
      "/green-fixture",
      true,
      greenFailureTarget,
    ) && greenFailureTarget.length === 0,
    "clipped-content self-test collected a green fixture",
  );
  console.log(
    `Clipped-content geometry self-test RED detected: ${clippedFixture[0]} | ${missedChildTerminalFixture[0]} | ${inaccessibleScrollFixture[0]}`,
  );
  console.log(
    "Clipped-content geometry self-test PASS: 3 red fixtures rejected; 4 green fixtures accepted; collect and fail-fast policies verified",
  );
}

function parseCookieHeader(
  header: string,
): Array<{ name: string; value: string }> {
  requireContract(
    header.trim() !== "",
    "ordinary and administrator QA cookies are required",
  );
  return header
    .split(";")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const separator = part.indexOf("=");
      requireContract(separator > 0, "invalid QA cookie header");
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

function watchPage(page: Page, role: Role, path: string) {
  page.on("pageerror", (error) =>
    failures.push(`${role} ${path} page error: ${error.message}`),
  );
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      !message.text().startsWith("Failed to load resource:")
    ) {
      failures.push(`${role} ${path} console error: ${message.text()}`);
    }
  });
}

function screenshotName(role: Role, path: string) {
  const key = path.replace(/^\//, "").replaceAll("/", "-");
  return `${role}-${key}.png`;
}

async function verifyShellGeometry(page: Page, role: Role, path: string) {
  const geometry = await page.evaluate(() => {
    const sidebar = document.querySelector<HTMLElement>(".media-sidebar");
    const topbar = document.querySelector<HTMLElement>(".media-topbar");
    const content = document.querySelector<HTMLElement>(".media-content");
    if (!sidebar || !topbar || !content) return null;
    const sidebarRect = sidebar.getBoundingClientRect();
    const topbarRect = topbar.getBoundingClientRect();
    const contentRect = content.getBoundingClientRect();
    return {
      sidebarWidth: sidebarRect.width,
      topbarHeight: topbarRect.height,
      contentLeft: contentRect.left,
      contentRight: contentRect.right,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
    };
  });
  requireContract(
    geometry !== null,
    `${role} ${path} shell geometry is unavailable`,
  );
  requireContract(
    geometry.sidebarWidth >= 300 && geometry.sidebarWidth <= 312,
    `${role} ${path} sidebar width is ${geometry.sidebarWidth}px, expected canonical 304-307px`,
  );
  requireContract(
    geometry.topbarHeight >= 84 && geometry.topbarHeight <= 102,
    `${role} ${path} topbar height is ${geometry.topbarHeight}px`,
  );
  requireContract(
    geometry.contentLeft <= geometry.sidebarWidth + 36,
    `${role} ${path} content starts too far from the sidebar at ${geometry.contentLeft}px`,
  );
  requireContract(
    geometry.contentRight >= geometry.viewportWidth - 32,
    `${role} ${path} content stops at ${geometry.contentRight}px before the viewport edge`,
  );

  if (role === "ordinary") {
    requireContract(
      JSON.stringify(
        await page.locator(".media-nav-heading").allTextContents(),
      ) === JSON.stringify(ordinaryNavGroups),
      `${role} ${path} navigation groups drifted`,
    );
    await page.getByRole("search", { name: "全局搜索" }).waitFor();
    await page.getByLabel("任务状态", { exact: true }).waitFor();
    await page.getByLabel("开始日期", { exact: true }).waitFor();
    await page.getByLabel("结束日期", { exact: true }).waitFor();
    await page
      .locator(".media-topbar")
      .getByRole("button", { name: "能力中心", exact: true })
      .waitFor();
    requireContract(
      (await page
        .locator(".sidebar-team")
        .filter({ hasText: "Mediaclaw 团队" })
        .count()) === 1,
      `${role} ${path} footer team identity is missing`,
    );
    requireContract(
      (await page
        .locator(".sidebar-role")
        .filter({ hasText: "普通使用者" })
        .count()) === 1,
      `${role} ${path} footer role is missing`,
    );
    await page.getByRole("button", { name: "账户菜单" }).waitFor();
  } else {
    await page.getByRole("search", { name: "治理搜索" }).waitFor();
    await page.locator(".topbar-scope").waitFor();
    await page.locator(".topbar-target").waitFor();
    await page.getByRole("button", { name: "管理员账户" }).waitFor();
    await page
      .getByRole("link", { name: "返回租户工作台", exact: true })
      .waitFor();
    requireContract(
      (await page
        .locator(".sidebar-role")
        .filter({ hasText: "平台管理员" })
        .count()) === 1,
      `${role} ${path} footer role is missing`,
    );
    requireContract(
      (await page
        .locator(".media-topbar")
        .getByRole("button", { name: "能力中心", exact: true })
        .count()) === 0,
      `${role} ${path} exposes the ordinary new-task command`,
    );
  }

  const landmark = bottomLandmarks[path];
  if (landmark) {
    const locator = page.getByText(landmark, { exact: true }).last();
    await locator.waitFor();
    const box = await locator.boundingBox();
    requireContract(
      box !== null &&
        box.y >= 0 &&
        box.y + box.height <= geometry.viewportHeight - 8,
      `${role} ${path} bottom landmark ${landmark} is clipped below the viewport`,
    );
  }

  if (path === "/admin/overview") {
    requireContract(
      (await page
        .getByLabel("平台指标")
        .evaluate((element) => getComputedStyle(element).display)) === "grid",
      "admin overview CSS Module styles are not applied",
    );
    await page
      .getByRole("heading", { name: "审计事实（近 24 小时）", exact: true })
      .waitFor();
  }
  if (path === "/media-agent") {
    const mainText = await page.locator(".media-content").innerText();
    for (const required of ["Pipeline 目录", "本地运行", "设备与 CLI"]) {
      requireContract(
        mainText.includes(required),
        `ordinary ${path} is missing the required local-control label: ${required}`,
      );
    }
    for (const retired of ["云端能力目录", "能力与任务检查器", "网页任务"]) {
      requireContract(
        !mainText.includes(retired),
        `ordinary ${path} renders retired capability-catalog text: ${retired}`,
      );
    }
    const tabs = page.getByRole("tab");
    requireContract(
      (await tabs.count()) === 3,
      `ordinary ${path} must render exactly three local-control tabs`,
    );
    await page.getByRole("tab", { name: "本地运行", exact: true }).click();
    await page.getByRole("heading", { name: "本地运行", exact: true }).waitFor();
    await page.getByRole("button", { name: "创建本地任务", exact: true }).waitFor();
    await page.getByRole("tab", { name: "设备与 CLI", exact: true }).click();
    await page.getByRole("heading", { name: "设备与 CLI", exact: true }).waitFor();
    await page.getByRole("button", { name: "生成配对码", exact: true }).waitFor();
    await page.getByRole("tab", { name: "Pipeline 目录", exact: true }).click();
    await page.getByRole("heading", { name: "Pipeline 目录", exact: true }).waitFor();
  }

  if (path === "/decisions") {
    const connectorGeometry = await page.evaluate(() => {
      const flow = document.querySelector<HTMLElement>(
        '[aria-label="证据到决策的流程"]',
      );
      const inspector = document.querySelector<HTMLElement>(
        "[data-page-inspector]",
      );
      const items = flow
        ? Array.from(flow.querySelectorAll<HTMLElement>("ol > li"))
        : [];
      if (!flow || !inspector || items.length !== 5) return null;
      const stepRects = items.map((item) =>
        (item.firstElementChild as HTMLElement | null)?.getBoundingClientRect(),
      );
      if (stepRects.some((rect) => rect === undefined)) return null;
      const segments = items.slice(0, -1).map((item, index) => {
        const step = item.firstElementChild as HTMLElement | null;
        const connector = item.lastElementChild as HTMLElement | null;
        const nextStep = items[index + 1]
          ?.firstElementChild as HTMLElement | null;
        if (!step || !connector || !nextStep || step === connector) return null;
        const stepRect = step.getBoundingClientRect();
        const connectorRect = connector.getBoundingClientRect();
        const nextRect = nextStep.getBoundingClientRect();
        return {
          outgoingGap: Math.abs(connectorRect.left - stepRect.right),
          incomingGap: Math.abs(nextRect.left - connectorRect.right),
          centerDelta: Math.abs(
            connectorRect.top +
              connectorRect.height / 2 -
              (stepRect.top + stepRect.height / 2),
          ),
        };
      });
      if (!segments.every((segment) => segment !== null)) return null;
      const resolvedSteps = stepRects as DOMRect[];
      const flowRect = flow.getBoundingClientRect();
      const inspectorRect = inspector.getBoundingClientRect();
      return {
        segments,
        stepTopSpread:
          Math.max(...resolvedSteps.map((rect) => rect.top)) -
          Math.min(...resolvedSteps.map((rect) => rect.top)),
        stepBottomSpread:
          Math.max(...resolvedSteps.map((rect) => rect.bottom)) -
          Math.min(...resolvedSteps.map((rect) => rect.bottom)),
        terminalBottomDelta: Math.abs(flowRect.bottom - inspectorRect.bottom),
      };
    });
    requireContract(
      connectorGeometry !== null && connectorGeometry.segments.length === 4,
      `ordinary ${path} evidence flow connector contract is missing`,
    );
    requireContract(
      connectorGeometry.stepTopSpread <= 2 &&
        connectorGeometry.stepBottomSpread <= 2,
      `ordinary ${path} flow cards are vertically misaligned: top=${connectorGeometry.stepTopSpread}px bottom=${connectorGeometry.stepBottomSpread}px`,
    );
    requireContract(
      connectorGeometry.terminalBottomDelta <= 4,
      `ordinary ${path} terminal flow ends ${connectorGeometry.terminalBottomDelta}px away from the inspector bottom`,
    );
    for (const [index, segment] of connectorGeometry.segments.entries()) {
      requireContract(
        segment.outgoingGap <= 2 &&
          segment.incomingGap <= 2 &&
          segment.centerDelta <= 4,
        `ordinary ${path} flow connector ${index + 1} is detached: outgoing=${segment.outgoingGap}px incoming=${segment.incomingGap}px center=${segment.centerDelta}px`,
      );
    }
  }
}

async function collectClippedContentObservations(page: Page) {
  return page.evaluate<ClippedContentObservation[]>(String.raw`(() => {
    const tolerance = 1;
    const surfaceTags = new Set(["ARTICLE", "ASIDE", "DIV", "MAIN", "SECTION"]);
    const boundedOverflowModes = new Set(["auto", "clip", "hidden", "scroll"]);
    const nonBusinessRoles = new Set(["button", "option", "switch", "tab"]);
    const interactiveOrMediaSelector = [
      "a[href]",
      "button",
      "canvas",
      "details",
      "iframe",
      "img",
      "input",
      "meter",
      "progress",
      "select",
      "summary",
      "textarea",
      "video",
      "audio",
      '[role="button"]',
      '[role="checkbox"]',
      '[role="link"]',
      '[role="radio"]',
      '[role="slider"]',
      '[role="spinbutton"]',
      '[role="switch"]',
      '[role="textbox"]',
    ].join(",");

    const hasVisibleColor = (color) => {
      const normalized = color.trim().toLowerCase();
      if (normalized === "transparent") return false;
      const body = normalized.slice(normalized.indexOf("(") + 1, -1);
      const slashIndex = body.lastIndexOf("/");
      const alphaToken =
        slashIndex >= 0
          ? body.slice(slashIndex + 1).trim()
          : normalized.startsWith("rgba(") || normalized.startsWith("hsla(")
            ? (body.split(",").at(-1)?.trim() ?? "")
            : "";
      if (!alphaToken) return true;
      const alpha = alphaToken.endsWith("%")
        ? Number.parseFloat(alphaToken) / 100
        : Number.parseFloat(alphaToken);
      return !Number.isFinite(alpha) || alpha > 0;
    };
    const hasVisibleBorder = (style) =>
      [
        [style.borderTopStyle, style.borderTopWidth, style.borderTopColor],
        [
          style.borderRightStyle,
          style.borderRightWidth,
          style.borderRightColor,
        ],
        [
          style.borderBottomStyle,
          style.borderBottomWidth,
          style.borderBottomColor,
        ],
        [style.borderLeftStyle, style.borderLeftWidth, style.borderLeftColor],
      ].some(
        ([borderStyle, borderWidth, borderColor]) =>
          borderStyle !== "none" &&
          borderStyle !== "hidden" &&
          Number.parseFloat(borderWidth) > 0 &&
          hasVisibleColor(borderColor),
      );
    const elementLabel = (element) => {
      let label = element.tagName.toLowerCase();
      if (element.id) label += "#" + element.id;
      else {
        const classes = Array.from(element.classList).slice(0, 2);
        if (classes.length > 0) label += "." + classes.join(".");
      }
      for (const attribute of ["data-page-terminal-surface", "role"]) {
        const value = element.getAttribute(attribute);
        if (value) label += "[" + attribute + '=\"' + value + '\"]';
      }
      return label;
    };
    const isVisibleInTree = (element, surface) => {
      for (
        let current = element;
        current && current !== surface;
        current = current.parentElement
      ) {
        const style = getComputedStyle(current);
        const opacity = Number.parseFloat(style.opacity);
        if (
          current.hidden ||
          current.getAttribute("aria-hidden") === "true" ||
          style.display === "none" ||
          style.visibility === "hidden" ||
          style.visibility === "collapse" ||
          style.contentVisibility === "hidden" ||
          style.position === "absolute" ||
          style.position === "fixed" ||
          (Number.isFinite(opacity) && opacity <= 0) ||
          current.closest("svg") !== null
        ) {
          return false;
        }
      }
      return true;
    };
    const isFullyVisibleSurface = (element, rect, style) => {
      const opacity = Number.parseFloat(style.opacity);
      if (
        element.hidden ||
        element.getAttribute("aria-hidden") === "true" ||
        style.display === "none" ||
        style.visibility === "hidden" ||
        style.visibility === "collapse" ||
        style.contentVisibility === "hidden" ||
        style.position === "absolute" ||
        style.position === "fixed" ||
        (Number.isFinite(opacity) && opacity <= 0) ||
        rect.width < 96 ||
        rect.height < 48 ||
        rect.left < -tolerance ||
        rect.top < -tolerance ||
        rect.right > window.innerWidth + tolerance ||
        rect.bottom > window.innerHeight + tolerance
      ) {
        return false;
      }
      for (
        let ancestor = element.parentElement;
        ancestor;
        ancestor = ancestor.parentElement
      ) {
        const ancestorStyle = getComputedStyle(ancestor);
        const ancestorOpacity = Number.parseFloat(ancestorStyle.opacity);
        if (
          ancestor.hidden ||
          ancestor.getAttribute("aria-hidden") === "true" ||
          ancestorStyle.display === "none" ||
          ancestorStyle.visibility === "hidden" ||
          ancestorStyle.visibility === "collapse" ||
          ancestorStyle.contentVisibility === "hidden" ||
          (Number.isFinite(ancestorOpacity) && ancestorOpacity <= 0)
        ) {
          return false;
        }
        const clipsX = ["auto", "clip", "hidden", "scroll"].includes(
          ancestorStyle.overflowX,
        );
        const clipsY = ["auto", "clip", "hidden", "scroll"].includes(
          ancestorStyle.overflowY,
        );
        if (clipsX || clipsY) {
          const ancestorRect = ancestor.getBoundingClientRect();
          if (
            (clipsX &&
              (rect.left < ancestorRect.left - tolerance ||
                rect.right > ancestorRect.right + tolerance)) ||
            (clipsY &&
              (rect.top < ancestorRect.top - tolerance ||
                rect.bottom > ancestorRect.bottom + tolerance))
          ) {
            return false;
          }
        }
      }
      return true;
    };
    const accessibleName = (element) => {
      const directName = element.getAttribute("aria-label")?.trim() ?? "";
      if (directName) return directName;
      const labelledBy = element.getAttribute("aria-labelledby")?.trim() ?? "";
      if (!labelledBy) return "";
      return labelledBy
        .split(/\s+/)
        .map((id) => document.getElementById(id)?.textContent?.trim() ?? "")
        .filter(Boolean)
        .join(" ");
    };
    const hasAccessibleFocusableScroll = (element) =>
      element.tabIndex >= 0 && accessibleName(element) !== "";
    const visibleTerminalRect = (element, rect, surface) => {
      let right = rect.right;
      let bottom = rect.bottom;
      for (
        let ancestor = element;
        ancestor && ancestor !== surface;
        ancestor = ancestor.parentElement
      ) {
        const style = getComputedStyle(ancestor);
        const scrollsX =
          ["auto", "scroll"].includes(style.overflowX) &&
          ancestor.scrollWidth - ancestor.clientWidth > tolerance;
        const scrollsY =
          ["auto", "scroll"].includes(style.overflowY) &&
          ancestor.scrollHeight - ancestor.clientHeight > tolerance;
        if (
          (!scrollsX && !scrollsY) ||
          !hasAccessibleFocusableScroll(ancestor)
        ) {
          continue;
        }
        const ancestorRect = ancestor.getBoundingClientRect();
        if (scrollsX) {
          right = Math.min(
            right,
            ancestorRect.right - Number.parseFloat(style.borderRightWidth),
          );
        }
        if (scrollsY) {
          bottom = Math.min(
            bottom,
            ancestorRect.bottom - Number.parseFloat(style.borderBottomWidth),
          );
        }
      }
      return { top: rect.top, right, bottom, left: rect.left };
    };

    return Array.from(document.querySelectorAll("*")).flatMap(
      (surface) => {
        if (
          !surfaceTags.has(surface.tagName) ||
          nonBusinessRoles.has(surface.getAttribute("role") ?? "")
        ) {
          return [];
        }
        const surfaceRect = surface.getBoundingClientRect();
        const surfaceStyle = getComputedStyle(surface);
        if (
          !isFullyVisibleSurface(surface, surfaceRect, surfaceStyle) ||
          !hasVisibleBorder(surfaceStyle) ||
          (!boundedOverflowModes.has(surfaceStyle.overflowX) &&
            !boundedOverflowModes.has(surfaceStyle.overflowY)) ||
          (!hasVisibleColor(surfaceStyle.backgroundColor) &&
            surfaceStyle.backgroundImage === "none")
        ) {
          return [];
        }
        const meaningfulRects = [];
        for (const descendant of [
          surface,
          ...Array.from(surface.querySelectorAll("*")),
        ]) {
          if (!isVisibleInTree(descendant, surface)) continue;
          const style = getComputedStyle(descendant);
          const rect = descendant.getBoundingClientRect();
          if (rect.width <= 0 || rect.height <= 0) continue;
          if (descendant.matches(interactiveOrMediaSelector)) {
            const terminalRect = visibleTerminalRect(
              descendant,
              rect,
              surface,
            );
            meaningfulRects.push({
              element: elementLabel(descendant),
              top: terminalRect.top,
              right: terminalRect.right,
              bottom: terminalRect.bottom,
              left: terminalRect.left,
            });
          }
          if (
            style.textOverflow === "ellipsis" ||
            (style.webkitLineClamp !== "none" &&
              Number.parseInt(style.webkitLineClamp, 10) > 0)
          ) {
            continue;
          }
          for (const node of Array.from(descendant.childNodes)) {
            if (node.nodeType !== Node.TEXT_NODE || !node.textContent?.trim()) {
              continue;
            }
            const range = document.createRange();
            range.selectNodeContents(node);
            const textRect = range.getBoundingClientRect();
            if (textRect.width <= 0 || textRect.height <= 0) continue;
            const terminalRect = visibleTerminalRect(
              descendant,
              textRect,
              surface,
            );
            meaningfulRects.push({
              element: elementLabel(descendant) + " > #text",
              top: terminalRect.top,
              right: terminalRect.right,
              bottom: terminalRect.bottom,
              left: terminalRect.left,
            });
          }
        }
        if (meaningfulRects.length === 0) return [];
        const terminalY = meaningfulRects.reduce((latest, candidate) =>
          candidate.bottom > latest.bottom ? candidate : latest,
        );
        const terminalX = meaningfulRects.reduce((latest, candidate) =>
          candidate.right > latest.right ? candidate : latest,
        );
        const scrollStateMarker = [
          "data-scroll-state",
          "data-scroll-region",
          "data-scrollable",
        ].find((attribute) => surface.hasAttribute(attribute));
        return [
          {
            surface: elementLabel(surface),
            overflowX: surfaceStyle.overflowX,
            overflowY: surfaceStyle.overflowY,
            paddingBox: {
              top:
                surfaceRect.top +
                Number.parseFloat(surfaceStyle.borderTopWidth),
              right:
                surfaceRect.right -
                Number.parseFloat(surfaceStyle.borderRightWidth),
              bottom:
                surfaceRect.bottom -
                Number.parseFloat(surfaceStyle.borderBottomWidth),
              left:
                surfaceRect.left +
                Number.parseFloat(surfaceStyle.borderLeftWidth),
            },
            terminalY: {
              element: terminalY.element,
              top: terminalY.top,
              bottom: terminalY.bottom,
            },
            terminalX: {
              element: terminalX.element,
              left: terminalX.left,
              right: terminalX.right,
            },
            clientHeight: surface.clientHeight,
            clientWidth: surface.clientWidth,
            scrollHeight: surface.scrollHeight,
            scrollWidth: surface.scrollWidth,
            tabIndex: surface.tabIndex,
            accessibleName: accessibleName(surface),
            scrollStateMarker: scrollStateMarker ?? null,
          },
        ];
      },
    );
  })()`);
}

async function verifyClippedContentGeometry(
  page: Page,
  role: Role,
  path: string,
) {
  const observations = await collectClippedContentObservations(page);
  const violations = evaluateClippedContentGeometry(observations);
  applyClippedContentContract(violations, role, path);
}

async function verifyFullyVisibleItems(page: Page, role: Role, path: string) {
  const items = page.locator("[data-qa-fully-visible-item]");
  const count = await items.count();
  const expectedCount = fullyVisibleItemCounts[path] ?? 0;
  if (expectedCount > 0) {
    requireContract(
      count === expectedCount,
      `${role} ${path} expected ${expectedCount} fully-visible items, found ${count}`,
    );
  }
  if (count === 0) return;

  const violations = await items.evaluateAll((elements) => {
    const tolerance = 1;
    const failures: string[] = [];

    for (const [index, element] of elements.entries()) {
      const item = element as HTMLElement;
      const rect = item.getBoundingClientRect();
      const label =
        item.getAttribute("aria-label") ||
        item.textContent?.replace(/\s+/g, " ").trim().slice(0, 80) ||
        `item ${index + 1}`;
      if (rect.width <= 1 || rect.height <= 1) {
        failures.push(`${label} is not visibly rendered`);
        continue;
      }
      if (
        rect.left < -tolerance ||
        rect.right > innerWidth + tolerance ||
        rect.top < -tolerance ||
        rect.bottom > innerHeight + tolerance
      ) {
        failures.push(`${label} extends outside the viewport`);
      }

      let ancestor = item.parentElement;
      while (ancestor && ancestor !== document.body) {
        const style = getComputedStyle(ancestor);
        const checkX = ["auto", "scroll", "hidden", "clip"].includes(
          style.overflowX,
        );
        const checkY = ["auto", "scroll", "hidden", "clip"].includes(
          style.overflowY,
        );
        if (checkX || checkY) {
          const ancestorRect = ancestor.getBoundingClientRect();
          if (
            (checkX &&
              (rect.left < ancestorRect.left - tolerance ||
                rect.right > ancestorRect.right + tolerance)) ||
            (checkY &&
              (rect.top < ancestorRect.top - tolerance ||
                rect.bottom > ancestorRect.bottom + tolerance))
          ) {
            failures.push(
              `${label} is clipped by ${ancestor.tagName.toLowerCase()}.${ancestor.className}`,
            );
            break;
          }
        }
        ancestor = ancestor.parentElement;
      }

      const content = item.querySelectorAll(
        "strong, small, label, select, button, [role='button']",
      );
      for (const child of content) {
        const childRect = child.getBoundingClientRect();
        if (
          childRect.width > 1 &&
          childRect.height > 1 &&
          (childRect.left < rect.left - tolerance ||
            childRect.right > rect.right + tolerance ||
            childRect.top < rect.top - tolerance ||
            childRect.bottom > rect.bottom + tolerance)
        ) {
          failures.push(`${label} contains content outside its own boundary`);
          break;
        }
      }
    }
    return failures;
  });

  requireContract(
    violations.length === 0,
    `${role} ${path} fully-visible item geometry failed: ${violations.join(" | ")}`,
  );
}

async function runClippedContentGeometryRuntimeProbe() {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({
      viewport: { width: 640, height: 480 },
    });
    await page.setContent(`<!doctype html>
      <style>
        .runtime-probe {
          box-sizing: border-box;
          width: 240px;
          height: 90px;
          overflow: hidden;
          padding: 12px;
          border: 1px solid rgb(30 30 30);
          background: rgb(250 250 250);
          margin-bottom: 12px;
        }
        .runtime-probe p { margin: 0; }
        .tableViewport {
          height: 48px;
          overflow-y: auto;
        }
        .tall-content,
        #true-clipped-runtime-probe p {
          display: flex;
          align-items: flex-end;
        }
        .tall-content { height: 140px; }
        #true-clipped-runtime-probe p { height: 96px; }
      </style>
      <section id="accessible-scroll-runtime-probe" class="runtime-probe">
        <div
          class="tableViewport"
          tabindex="0"
          aria-label="Capability catalog"
          data-scroll-state="more-below"
        >
          <p class="tall-content">Accessible scrolling fixture</p>
        </div>
      </section>
      <section id="inaccessible-scroll-runtime-probe" class="runtime-probe">
        <div class="tableViewport">
          <p class="tall-content">Inaccessible scrolling fixture</p>
        </div>
      </section>
      <section id="true-clipped-runtime-probe" class="runtime-probe">
        <p>True hidden clipping fixture</p>
      </section>`);
    const observations = await collectClippedContentObservations(page);
    requireContract(
      observations.length === 3,
      `clipped-content runtime probe returned unexpected observations: ${JSON.stringify(observations)}`,
    );
    const violations = evaluateClippedContentGeometry(observations);
    requireContract(
      violations.length === 2 &&
        violations.some((violation) =>
          violation.includes("section#inaccessible-scroll-runtime-probe"),
        ) &&
        violations.some((violation) =>
          violation.includes("section#true-clipped-runtime-probe"),
        ) &&
        !violations.some((violation) =>
          violation.includes("section#accessible-scroll-runtime-probe"),
        ),
      `clipped-content runtime probe did not preserve nested-scroll boundaries: ${violations.join(" | ")}`,
    );
    console.log(
      `Clipped-content geometry runtime probe PASS: observations=${observations.length} red=${violations.length} accessible-nested-scroll=accepted`,
    );
    await page.setContent(`<!doctype html>
      <div style="height: 40px; overflow: hidden">
        <div data-qa-fully-visible-item style="height: 60px">
          <strong>Clipped final item</strong>
        </div>
      </div>`);
    let rejectedClippedItem = false;
    try {
      await verifyFullyVisibleItems(page, "ordinary", "/runtime-probe");
    } catch (error) {
      rejectedClippedItem =
        error instanceof Error &&
        error.message.includes("fully-visible item geometry failed");
    }
    requireContract(
      rejectedClippedItem,
      "fully-visible item runtime probe failed to reject a clipped final item",
    );
    await page.setContent(`<!doctype html>
      <div style="height: 80px; overflow: hidden">
        <div data-qa-fully-visible-item style="height: 60px">
          <strong>Visible final item</strong>
        </div>
      </div>`);
    await verifyFullyVisibleItems(page, "ordinary", "/runtime-probe");
    let rejectedMissingItems = false;
    try {
      await verifyFullyVisibleItems(page, "ordinary", "/reviews");
    } catch (error) {
      rejectedMissingItems =
        error instanceof Error &&
        error.message.includes("expected 2 fully-visible items, found 1");
    }
    requireContract(
      rejectedMissingItems,
      "fully-visible item runtime probe failed to reject a missing critical item",
    );
    console.log(
      "Fully-visible item runtime probe PASS: clipped-item=red missing-item=red visible-item=green",
    );
  } finally {
    await browser.close();
  }
}

async function verifyPersistentRail(page: Page, role: Role, path: string) {
  if (!persistentRailPaths.has(path)) return;
  const geometry = await page.evaluate(
    ({ role, allowLegacyTerminalSurfaces }) => {
      const layout = document.querySelector<HTMLElement>(
        '[data-page-layout="persistent-rail"]',
      );
      const primary = layout?.querySelector<HTMLElement>("[data-page-primary]");
      const inspector = layout?.querySelector<HTMLElement>(
        "[data-page-inspector]",
      );
      if (!layout || !primary || !inspector) return null;
      const layoutRect = layout.getBoundingClientRect();
      const primaryRect = primary.getBoundingClientRect();
      const inspectorRect = inspector.getBoundingClientRect();
      const flow = primary.querySelector<HTMLElement>("[data-primary-flow]");
      const flowRect = flow?.getBoundingClientRect() ?? null;
      const {
        hasVisibleColor,
        hasVisibleBorder,
        visibleRect,
        isVisibleSurface,
        legacyTerminalSurface,
        markedTerminalSurfaces,
      } = {
        hasVisibleColor(color: string) {
          const normalized = color.trim().toLowerCase();
          if (normalized === "transparent") return false;
          const body = normalized.slice(normalized.indexOf("(") + 1, -1);
          const slashIndex = body.lastIndexOf("/");
          const alphaToken =
            slashIndex >= 0
              ? body.slice(slashIndex + 1).trim()
              : normalized.startsWith("rgba(") || normalized.startsWith("hsla(")
                ? (body.split(",").at(-1)?.trim() ?? "")
                : "";
          if (!alphaToken) return true;
          const alpha = alphaToken.endsWith("%")
            ? Number.parseFloat(alphaToken) / 100
            : Number.parseFloat(alphaToken);
          return !Number.isFinite(alpha) || alpha > 0;
        },
        hasVisibleBorder(element: HTMLElement) {
          const style = getComputedStyle(element);
          return [
            [style.borderTopStyle, style.borderTopWidth, style.borderTopColor],
            [
              style.borderRightStyle,
              style.borderRightWidth,
              style.borderRightColor,
            ],
            [
              style.borderBottomStyle,
              style.borderBottomWidth,
              style.borderBottomColor,
            ],
            [
              style.borderLeftStyle,
              style.borderLeftWidth,
              style.borderLeftColor,
            ],
          ].some(
            ([borderStyle, borderWidth, borderColor]) =>
              borderStyle !== "none" &&
              borderStyle !== "hidden" &&
              Number.parseFloat(borderWidth) > 0 &&
              hasVisibleColor(borderColor),
          );
        },
        visibleRect(element: HTMLElement, rect: DOMRect, columnRect: DOMRect) {
          let left = Math.max(rect.left, columnRect.left, 0);
          let right = Math.min(rect.right, columnRect.right, window.innerWidth);
          let top = Math.max(rect.top, columnRect.top, 0);
          let bottom = Math.min(
            rect.bottom,
            columnRect.bottom,
            window.innerHeight,
          );
          for (
            let ancestor = element.parentElement;
            ancestor;
            ancestor = ancestor.parentElement
          ) {
            const style = getComputedStyle(ancestor);
            const clipsX = ["hidden", "clip", "scroll", "auto"].includes(
              style.overflowX,
            );
            const clipsY = ["hidden", "clip", "scroll", "auto"].includes(
              style.overflowY,
            );
            if (clipsX || clipsY) {
              const ancestorRect = ancestor.getBoundingClientRect();
              if (clipsX) {
                left = Math.max(left, ancestorRect.left);
                right = Math.min(right, ancestorRect.right);
              }
              if (clipsY) {
                top = Math.max(top, ancestorRect.top);
                bottom = Math.min(bottom, ancestorRect.bottom);
              }
            }
          }
          return {
            width: Math.max(0, right - left),
            height: Math.max(0, bottom - top),
          };
        },
        isVisibleSurface(element: HTMLElement, columnRect: DOMRect) {
          if (
            !["ARTICLE", "ASIDE", "DIV", "MAIN", "SECTION"].includes(
              element.tagName,
            ) ||
            element.hidden ||
            element.getAttribute("aria-hidden") === "true" ||
            ["button", "tab", "option", "switch"].includes(
              element.getAttribute("role") ?? "",
            )
          ) {
            return null;
          }
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          const opacity = Number.parseFloat(style.opacity);
          if (
            rect.width < 96 ||
            rect.height < 48 ||
            style.display === "none" ||
            style.visibility === "hidden" ||
            style.visibility === "collapse" ||
            style.contentVisibility === "hidden" ||
            (Number.isFinite(opacity) && opacity <= 0) ||
            !hasVisibleBorder(element) ||
            (!hasVisibleColor(style.backgroundColor) &&
              style.backgroundImage === "none")
          ) {
            return null;
          }
          for (
            let ancestor: HTMLElement | null = element;
            ancestor;
            ancestor = ancestor.parentElement
          ) {
            const ancestorStyle = getComputedStyle(ancestor);
            const ancestorOpacity = Number.parseFloat(ancestorStyle.opacity);
            if (
              ancestor.hidden ||
              ancestorStyle.display === "none" ||
              ancestorStyle.visibility === "hidden" ||
              ancestorStyle.visibility === "collapse" ||
              (Number.isFinite(ancestorOpacity) && ancestorOpacity <= 0)
            ) {
              return null;
            }
          }
          const visible = visibleRect(element, rect, columnRect);
          if (
            visible.width < rect.width - 1 ||
            visible.height < rect.height - 1
          ) {
            return null;
          }
          return {
            bottom: rect.bottom,
            height: rect.height,
            tag: element.tagName.toLowerCase(),
            width: rect.width,
          };
        },
        legacyTerminalSurface(column: HTMLElement, columnRect: DOMRect) {
          const candidates = Array.from(
            column.querySelectorAll<HTMLElement>("*"),
          )
            .map((element) => isVisibleSurface(element, columnRect))
            .filter(
              (
                candidate,
              ): candidate is {
                bottom: number;
                height: number;
                tag: string;
                width: number;
              } => candidate !== null,
            );
          let terminal: (typeof candidates)[number] | null = null;
          for (const candidate of candidates) {
            if (terminal === null || candidate.bottom > terminal.bottom) {
              terminal = candidate;
            }
          }
          return terminal ? [{ ...terminal, valid: true }] : [];
        },
        markedTerminalSurfaces(
          column: HTMLElement,
          columnRect: DOMRect,
          marker: "primary" | "inspector",
        ) {
          const selector = `[data-page-terminal-surface="${marker}"]`;
          const markedElements = [
            ...(column.matches(selector) ? [column] : []),
            ...Array.from(column.querySelectorAll<HTMLElement>(selector)),
          ];
          if (markedElements.length > 0) {
            const candidates = markedElements.map((element) => {
              const rect = element.getBoundingClientRect();
              return {
                bottom: rect.bottom,
                height: rect.height,
                tag: element.tagName.toLowerCase(),
                valid: isVisibleSurface(element, columnRect) !== null,
                width: rect.width,
              };
            });
            const visibleCandidates = candidates.filter(
              (candidate) => candidate.valid,
            );
            const terminalCandidates =
              visibleCandidates.length > 0 ? visibleCandidates : candidates;
            const terminal = terminalCandidates.reduce<
              (typeof terminalCandidates)[number] | null
            >(
              (latest, candidate) =>
                latest === null || candidate.bottom > latest.bottom
                  ? candidate
                  : latest,
              null,
            );
            return terminal ? [terminal] : [];
          }
          if (allowLegacyTerminalSurfaces) {
            return legacyTerminalSurface(column, columnRect);
          }
          return [];
        },
      };
      const terminalSurfaces = {
        primary: markedTerminalSurfaces(primary, primaryRect, "primary"),
        inspector: markedTerminalSurfaces(
          inspector,
          inspectorRect,
          "inspector",
        ),
      };
      return {
        display: getComputedStyle(layout).display,
        layoutWidth: layoutRect.width,
        primary: {
          top: primaryRect.top,
          bottom: primaryRect.bottom,
          left: primaryRect.left,
          right: primaryRect.right,
          width: primaryRect.width,
        },
        inspector: {
          top: inspectorRect.top,
          bottom: inspectorRect.bottom,
          left: inspectorRect.left,
          right: inspectorRect.right,
          width: inspectorRect.width,
        },
        flowRight: flowRect?.right ?? null,
        commonColumnBottom: Math.max(primaryRect.bottom, inspectorRect.bottom),
        terminalSurfaces,
      };
    },
    { role, allowLegacyTerminalSurfaces },
  );
  if (!geometry) {
    requireOrCollectRailContract(
      false,
      `${role} ${path} persistent rail contract is missing`,
    );
    return;
  }
  requireContract(
    geometry.display === "grid",
    `${role} ${path} persistent rail layout is ${geometry.display}, expected grid`,
  );
  requireOrCollectRailContract(
    Math.abs(geometry.primary.top - geometry.inspector.top) <=
      (railTopTolerance[path] ?? 4),
    `${role} ${path} rail starts ${Math.abs(geometry.primary.top - geometry.inspector.top)}px away from the primary column`,
  );
  const railBottomDelta = Math.abs(
    geometry.primary.bottom - geometry.inspector.bottom,
  );
  requireOrCollectRailContract(
    railBottomDelta <= 4,
    `${role} ${path} rail bottoms differ by ${railBottomDelta}px`,
  );
  requireContract(
    geometry.primary.right < geometry.inspector.left,
    `${role} ${path} primary column overlaps or follows the inspector`,
  );
  requireContract(
    geometry.inspector.width >= (minimumRailWidths[path] ?? 350),
    `${role} ${path} inspector width is ${geometry.inspector.width}px, expected at least ${minimumRailWidths[path] ?? 350}px`,
  );
  requireContract(
    geometry.primary.width + geometry.inspector.width >=
      geometry.layoutWidth * 0.94,
    `${role} ${path} columns do not use the available workspace width`,
  );
  if (geometry.flowRight !== null) {
    requireContract(
      geometry.flowRight <= geometry.inspector.left,
      `${role} ${path} primary flow extends under the inspector rail`,
    );
  }
  const terminalSurfaceChecks = [
    { side: "primary" as const, surfaces: geometry.terminalSurfaces.primary },
    {
      side: "inspector" as const,
      surfaces: geometry.terminalSurfaces.inspector,
    },
  ];
  for (const { side, surfaces } of terminalSurfaceChecks) {
    if (
      !requireOrCollectRailContract(
        surfaces.length > 0,
        `${role} ${path} terminal visible bordered surface is missing from the ${side} column; add data-page-terminal-surface="${side}"`,
      )
    ) {
      continue;
    }
    for (const surface of surfaces) {
      if (
        !requireOrCollectRailContract(
          surface.valid,
          `${role} ${path} ${side} terminal surface is not a visible bordered painted surface`,
        )
      ) {
        continue;
      }
      const terminalBottomDelta = Math.abs(
        surface.bottom - geometry.commonColumnBottom,
      );
      requireOrCollectRailContract(
        terminalBottomDelta <= 4,
        `${role} ${path} ${side} terminal surface ends ${terminalBottomDelta}px away from the common column bottom`,
      );
    }
  }

  if (path === "/runs") {
    const prelude = page.locator("[data-page-prelude]");
    for (const label of ["能力", "当前环节", "状态", "本机关联"]) {
      const control = prelude.getByLabel(label, { exact: true });
      await control.waitFor();
      requireContract(
        await control.isDisabled(),
        `ordinary ${path} ${label} filter must remain disabled until its API contract exists`,
      );
    }
    await prelude.getByRole("button", { name: "重置", exact: true }).waitFor();
  }
}

async function verifyPage(page: Page, role: Role, path: string, label: string) {
  const apiRequests: string[] = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname.includes("/openclaw/media/api/"))
      apiRequests.push(`${request.method()} ${pathname}`);
  });
  await page.goto(`${baseUrl}${path}`, { waitUntil: "networkidle" });
  if (role === "ordinary" && ["/runs", "/decisions", "/publishing"].includes(path)) {
    requireContract(
      apiRequests.some((request) => request.includes("/openclaw/media/api/jobs")),
      `${role} ${path} did not consume the canonical jobs endpoint`,
    );
    requireContract(
      !apiRequests.some((request) => request.includes("/openclaw/media/api/runs")),
      `${role} ${path} consumed the retired runs endpoint`,
    );
  }
  await page.locator(".media-shell").waitFor();
  const filename = screenshotName(role, path);
  const screenshot = resolve(outputDir, filename);
  await page.screenshot({ path: screenshot });
  const expected = role === "admin" ? adminMediaNav : ordinaryMediaNav;
  const forbidden = role === "admin" ? ordinaryMediaNav : adminMediaNav;
  const links = page.locator(".media-nav a");
  const labels = await links.allTextContents();
  requireContract(
    JSON.stringify(labels) ===
      JSON.stringify(expected.map((item) => item.label)),
    `${role} ${path} sidebar order drifted: ${labels.join(" | ")}`,
  );
  requireContract(
    (await links.filter({ hasText: label }).count()) === 1,
    `${role} ${path} does not contain exactly one target navigation item`,
  );
  requireContract(
    (await page.locator(".media-nav a.active").count()) === 1,
    `${role} ${path} does not have exactly one active navigation item`,
  );
  requireContract(
    (await page.locator(".media-nav a.active").innerText()).trim() === label,
    `${role} ${path} active navigation is not ${label}`,
  );
  for (const item of forbidden)
    requireContract(
      (await page
        .getByRole("link", { name: item.label, exact: true })
        .count()) === 0,
      `${role} ${path} exposes forbidden navigation ${item.label}`,
    );
  for (const retired of retiredMediaNavLabels) {
    requireContract(
      (await page.getByText(retired, { exact: true }).count()) === 0,
      `${role} ${path} renders retired label ${retired}`,
    );
  }
  await verifyShellGeometry(page, role, path);
  await verifyPersistentRail(page, role, path);
  await verifyFullyVisibleItems(page, role, path);
  await verifyClippedContentGeometry(page, role, path);
  if (path === "/admin/overview") {
    const businessRequests = apiRequests.filter(
      (request) => !request.endsWith("/session"),
    );
    requireContract(
      businessRequests.length === 0,
      `admin ${path} issued business requests before the aggregate API contract was frozen: ${businessRequests.join(" | ")}`,
    );
  }
  const viewportFit = await page.evaluate(() => ({
    horizontalOverflow:
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
    verticalOverflow:
      document.documentElement.scrollHeight -
      document.documentElement.clientHeight,
  }));
  requireContract(
    viewportFit.horizontalOverflow <= 1,
    `${role} ${path} has ${viewportFit.horizontalOverflow}px horizontal overflow`,
  );
  requireContract(
    viewportFit.verticalOverflow <= 1,
    `${role} ${path} has ${viewportFit.verticalOverflow}px page-level vertical overflow; data-heavy regions must scroll internally`,
  );
  results.push({
    role,
    path,
    label,
    screenshot,
    sha256: createHash("sha256").update(readFileSync(screenshot)).digest("hex"),
    apiRequests,
    viewportFit,
  });
}

async function verifyRole(
  role: Role,
  routes: readonly { path: string; label: string }[],
) {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1088 },
    deviceScaleFactor: 1,
  });
  await installCookies(context, cookieHeaders[role]);
  try {
    for (const route of routes) {
      const page = await context.newPage();
      watchPage(page, role, route.path);
      await verifyPage(page, role, route.path, route.label);
      await page.close();
    }
  } finally {
    await context.close();
    await browser.close();
  }
}

async function main() {
  mkdirSync(outputDir, { recursive: true });
  let servedBefore: ServedRelease | null = null;
  let servedAfter: ServedRelease | null = null;
  try {
    servedBefore = inspectServedRelease();
    await verifyRole("ordinary", ordinaryMediaNav);
    await verifyRole("admin", adminMediaNav);
  } catch (error) {
    failures.push(error instanceof Error ? error.message : String(error));
  }
  try {
    servedAfter = inspectServedRelease();
    requireContract(
      servedBefore !== null &&
        servedBefore.releasePath === servedAfter.releasePath &&
        servedBefore.entrypointSha256 === servedAfter.entrypointSha256 &&
        servedBefore.manifestSha256 === servedAfter.manifestSha256,
      "served media release changed while role screenshots were captured",
    );
  } catch (error) {
    failures.push(error instanceof Error ? error.message : String(error));
  }
  const report = {
    ok: failures.length === 0 && results.length === 16,
    baseUrl,
    servedRelease: servedAfter,
    viewport: { width: 1920, height: 1088 },
    expected: 16,
    captured: results.length,
    results,
    failures,
  };
  const reportPath = resolve(outputDir, "report.json");
  writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);
  writeFileSync(
    resolve(outputDir, "served-release.json"),
    `${JSON.stringify(
      {
        capturedAt: new Date().toISOString(),
        stable:
          servedBefore !== null &&
          servedAfter !== null &&
          servedBefore.releasePath === servedAfter.releasePath &&
          servedBefore.entrypointSha256 === servedAfter.entrypointSha256 &&
          servedBefore.manifestSha256 === servedAfter.manifestSha256,
        before: servedBefore,
        after: servedAfter,
        report: "report.json",
        reportSha256: sha256File(reportPath),
      },
      null,
      2,
    )}\n`,
  );
  if (!report.ok)
    throw new Error(
      failures.join(" | ") || `captured ${results.length}/16 pages`,
    );
  console.log(`Media role screenshot QA passed: ${results.length}/16 pages`);
}

if (process.env.MEDIA_ROLE_QA_GEOMETRY_SELF_TEST === "1") {
  runClippedContentGeometrySelfTests();
} else if (process.env.MEDIA_ROLE_QA_GEOMETRY_RUNTIME_PROBE === "1") {
  runClippedContentGeometryRuntimeProbe().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  });
} else {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  });
}
