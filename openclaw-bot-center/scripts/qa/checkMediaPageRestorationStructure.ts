import * as fs from "node:fs";
import * as path from "node:path";
import { CANONICAL_PERSISTENT_RAIL_SOURCE_FILES } from "./mediaPageStructureManifest";

type PageContract = {
  owner: string;
  file: string;
  importPath: string;
};

type SourceFixture = {
  mediaStudioApp: string;
  mediaWebWorkspace: string;
  mediaRoleIa: string;
  pages: Map<string, string>;
};

const MEDIA_STUDIO_APP_FILE = "src/media/MediaStudioApp.tsx";
const MEDIA_WEB_WORKSPACE_FILE = "src/media/MediaWebWorkspace.tsx";
const MEDIA_ROLE_IA_FILE = "src/media/mediaRoleIa.ts";
const ADMIN_OVERVIEW_PAGE_FILE = "src/media/pages/admin/AdminOverviewPage.tsx";
const RETIRED_MEDIA_PROCESSING_LABEL = "媒体处理";
const ORDINARY_NAV_GROUP_EXPORT = "ordinaryMediaNavGroups";
const ORDINARY_NAV_GROUP_LABELS = [
  "工作台",
  "内容运营",
  "本机协作",
  "账户",
] as const;
const PERSISTENT_RAIL_PAGE_FILES = CANONICAL_PERSISTENT_RAIL_SOURCE_FILES;

const PAGE_COMPONENTS: readonly PageContract[] = [
  {
    owner: "OverviewPage",
    file: "src/media/pages/ordinary/OverviewPage.tsx",
    importPath: "./pages/ordinary/OverviewPage",
  },
  {
    owner: "TracksPage",
    file: "src/media/pages/ordinary/TracksPage.tsx",
    importPath: "./pages/ordinary/TracksPage",
  },
  {
    owner: "AssetsPage",
    file: "src/media/pages/ordinary/AssetsPage.tsx",
    importPath: "./pages/ordinary/AssetsPage",
  },
  {
    owner: "DecisionsPage",
    file: "src/media/pages/ordinary/DecisionsPage.tsx",
    importPath: "./pages/ordinary/DecisionsPage",
  },
  {
    owner: "RunsPage",
    file: "src/media/pages/ordinary/RunsPage.tsx",
    importPath: "./pages/ordinary/RunsPage",
  },
  {
    owner: "PublishingPage",
    file: "src/media/pages/ordinary/PublishingPage.tsx",
    importPath: "./pages/ordinary/PublishingPage",
  },
  {
    owner: "ReviewsPage",
    file: "src/media/pages/ordinary/ReviewsPage.tsx",
    importPath: "./pages/ordinary/ReviewsPage",
  },
  {
    owner: "MediaAgentPage",
    file: "src/media/pages/ordinary/MediaAgentPage.tsx",
    importPath: "./pages/ordinary/MediaAgentPage",
  },
  {
    owner: "ArchivesPage",
    file: "src/media/pages/ordinary/ArchivesPage.tsx",
    importPath: "./pages/ordinary/ArchivesPage",
  },
  {
    owner: "UsageBillingPage",
    file: "src/media/pages/ordinary/UsageBillingPage.tsx",
    importPath: "./pages/ordinary/UsageBillingPage",
  },
  {
    owner: "InvitesPage",
    file: "src/media/pages/ordinary/InvitesPage.tsx",
    importPath: "./pages/ordinary/InvitesPage",
  },
  {
    owner: "AdminOverviewPage",
    file: ADMIN_OVERVIEW_PAGE_FILE,
    importPath: "./pages/admin/AdminOverviewPage",
  },
  {
    owner: "AdminAccessPage",
    file: "src/media/pages/admin/AdminAccessPage.tsx",
    importPath: "./pages/admin/AdminAccessPage",
  },
  {
    owner: "AdminTenantsPage",
    file: "src/media/pages/admin/AdminTenantsPage.tsx",
    importPath: "./pages/admin/AdminTenantsPage",
  },
  {
    owner: "AdminBillingPage",
    file: "src/media/pages/admin/AdminBillingPage.tsx",
    importPath: "./pages/admin/AdminBillingPage",
  },
  {
    owner: "AdminUpstreamsPage",
    file: "src/media/pages/admin/AdminUpstreamsPage.tsx",
    importPath: "./pages/admin/AdminUpstreamsPage",
  },
];

const FORBIDDEN_PAGE_SUBSTITUTIONS = [
  {
    file: "src/media/pages/ordinary/TracksPage.tsx",
    token: "loadTenantDashboard",
    message: "TracksPage.tsx contains forbidden token loadTenantDashboard",
  },
  {
    file: "src/media/pages/ordinary/ArchivesPage.tsx",
    token: "loadAssetSummaries",
    message: "ArchivesPage.tsx contains forbidden token loadAssetSummaries",
  },
  {
    file: "src/media/pages/ordinary/ReviewsPage.tsx",
    token: "loadUsage",
    message: "ReviewsPage.tsx contains forbidden token loadUsage",
  },
] as const;

const ADMIN_OVERVIEW_DASHBOARD_DELEGATION =
  /<AdminPage\b[^>]*\binitialModule\s*=\s*(?:"dashboard"|'dashboard'|\{\s*["']dashboard["']\s*\})[^>]*\/?>/;
const ADMIN_OVERVIEW_TARGET_TYPES = [
  "platform",
  "user",
  "tenant",
  "billing",
  "admission",
  "session",
  "unknown",
] as const;

function findMissingPageViolations(fixture: SourceFixture): string[] {
  return PAGE_COMPONENTS.filter((page) => !fixture.pages.has(page.file)).map(
    (page) => "missing page component: " + page.file,
  );
}

function findMediaStudioAppViolations(fixture: SourceFixture): string[] {
  const violations: string[] = [];
  for (const page of PAGE_COMPONENTS) {
    const escapedImportPath = page.importPath.replace(/\./g, "\\.");
    const directDefaultImport = new RegExp(
      `\\bimport\\s+${page.owner}\\s+from\\s+['"]${escapedImportPath}['"]`,
    );
    if (!directDefaultImport.test(fixture.mediaStudioApp)) {
      violations.push(
        "MediaStudioApp.tsx missing direct default import for " + page.owner,
      );
    }

    const inlineDefinition = new RegExp(
      `^\\s*(?:(?:export)\\s+(?:default\\s+)?)?(?:function|class|const|let|var)\\s+${page.owner}\\b`,
      "m",
    );
    if (inlineDefinition.test(fixture.mediaStudioApp)) {
      violations.push(
        "MediaStudioApp.tsx first-level page owner defined inline: " + page.owner,
      );
    }
  }
  return violations;
}

function findPageSubstitutionViolations(fixture: SourceFixture): string[] {
  const violations: string[] = [];
  for (const check of FORBIDDEN_PAGE_SUBSTITUTIONS) {
    const source = fixture.pages.get(check.file);
    if (source !== undefined && source.includes(check.token)) {
      violations.push(check.message);
    }
  }
  return violations;
}

function findAdminOverviewViolation(fixture: SourceFixture): string[] {
  const source = fixture.pages.get(ADMIN_OVERVIEW_PAGE_FILE);
  if (source === undefined) return [];
  const violations: string[] = [];
  if (ADMIN_OVERVIEW_DASHBOARD_DELEGATION.test(source)) {
    violations.push(
      'AdminOverviewPage.tsx delegates to AdminPage with initialModule="dashboard"',
    );
  }
  for (const token of [
    "loadTenantDashboard",
    "loadAdminBillingSummary",
    "loadAdminUpstreamSummary",
    "loadAdminReconciliation",
  ]) {
    if (source.includes(token))
      violations.push(
        `AdminOverviewPage.tsx reads forbidden adjacent data through ${token}`,
      );
  }
  for (const token of [
    "admin-primary-column",
    "admin-side-column",
    "审计事实（近 24 小时）",
  ]) {
    if (!source.includes(token))
      violations.push(
        `AdminOverviewPage.tsx missing stable blocked-state structure: ${token}`,
      );
  }
  return violations;
}

function findAdminOverviewResponseIntegrityViolations(
  fixture: SourceFixture,
): string[] {
  const source = fixture.pages.get(ADMIN_OVERVIEW_PAGE_FILE);
  if (source === undefined) return [];
  const violations: string[] = [];
  const labelMap = source.match(
    /const\s+ACTION_TARGET_TYPE_LABELS\s*:\s*Record<AdminActionTargetType,\s*string>\s*=\s*\{([\s\S]*?)\};/,
  );
  if (labelMap === null) {
    violations.push(
      "AdminOverviewPage.tsx missing explicit targetType display-label map",
    );
  } else {
    for (const targetType of ADMIN_OVERVIEW_TARGET_TYPES) {
      if (!new RegExp(`\\b${targetType}:\\s*["'][^"']+["']`).test(labelMap[1])) {
        violations.push(
          `AdminOverviewPage.tsx targetType display-label map missing ${targetType}`,
        );
      }
    }
  }
  if (/\{\s*action\.targetType\s*\}/.test(source)) {
    violations.push(
      "AdminOverviewPage.tsx exposes raw targetType enum in the action row",
    );
  }
  if (!/ACTION_TARGET_TYPE_LABELS\s*\[\s*action\.targetType\s*\]/.test(source)) {
    violations.push(
      "AdminOverviewPage.tsx does not render targetType through its display-label map",
    );
  }
  if (!/audit\.failedCount\s*>\s*audit\.actionCount/.test(source)) {
    violations.push(
      "AdminOverviewPage.tsx does not reject impossible audit failed counts",
    );
  }
  if (
    !/Date\.parse\s*\(\s*audit\.from\s*\)\s*>\s*Date\.parse\s*\(\s*audit\.to\s*\)/.test(
      source,
    )
  ) {
    violations.push(
      "AdminOverviewPage.tsx does not reject reversed audit windows",
    );
  }
  if (!/ACTION_TARGET_TYPES\.has\s*\(\s*value\.targetType/.test(source)) {
    violations.push(
      "AdminOverviewPage.tsx no longer rejects unknown targetType values",
    );
  }
  return violations;
}

function findAdminBootstrapViolation(fixture: SourceFixture): string[] {
  const source = fixture.mediaWebWorkspace;
  const guard =
    /if\s*\(\s*value\.role\s*===\s*["']admin["']\s*\)\s*return\b/;
  const guardIndex = source.search(guard);
  const capabilityCallIndex = source.indexOf("void loadMediaCapabilities()");
  const taskCallIndex = source.indexOf("void loadMediaTasks()");
  if (guardIndex === -1)
    return [
      "MediaWebWorkspace.tsx does not stop administrator business bootstrap after /session",
    ];
  if (
    (capabilityCallIndex !== -1 && guardIndex > capabilityCallIndex) ||
    (taskCallIndex !== -1 && guardIndex > taskCallIndex)
  ) {
    return [
      "MediaWebWorkspace.tsx administrator guard runs after a business bootstrap request",
    ];
  }
  return [];
}

function findPersistentRailViolations(fixture: SourceFixture): string[] {
  const violations: string[] = [];
  for (const file of PERSISTENT_RAIL_PAGE_FILES) {
    const source = fixture.pages.get(file);
    if (source === undefined) continue;
    for (const token of [
      "data-page-layout",
      "data-page-primary",
      "data-page-inspector",
    ]) {
      if (!source.includes(token))
        violations.push(`${file} missing persistent rail token ${token}`);
    }
  }
  for (const file of [
    "src/media/pages/ordinary/TracksPage.tsx",
    "src/media/pages/ordinary/DecisionsPage.tsx",
  ]) {
    const source = fixture.pages.get(file);
    if (source !== undefined && !source.includes("data-primary-flow")) {
      violations.push(
        `${file} does not constrain its lower flow to the primary column`,
      );
    }
  }
  return violations;
}

function findCssModuleUsageViolations(fixture: SourceFixture): string[] {
  const violations: string[] = [];
  const sideEffectModuleImport = /import\s+['"][^'"]+\.module\.css['"]/;
  for (const [file, source] of fixture.pages) {
    if (sideEffectModuleImport.test(source)) {
      violations.push(file + " side-effect imports a CSS Module");
    }
  }
  return violations;
}

function findOrdinaryNavGroupViolations(fixture: SourceFixture): string[] {
  const violations: string[] = [];
  if (
    !fixture.mediaRoleIa.includes("export const " + ORDINARY_NAV_GROUP_EXPORT)
  ) {
    violations.push(
      "mediaRoleIa.ts does not export " + ORDINARY_NAV_GROUP_EXPORT,
    );
    return violations;
  }
  let previousIndex = -1;
  for (const label of ORDINARY_NAV_GROUP_LABELS) {
    const index = fixture.mediaRoleIa.indexOf(`label: '${label}'`);
    if (index === -1) {
      violations.push(
        "mediaRoleIa.ts missing ordinary navigation group: " + label,
      );
    } else if (index <= previousIndex) {
      violations.push(
        "mediaRoleIa.ts ordinary navigation group order drifted at: " + label,
      );
    }
    previousIndex = index;
  }
  return violations;
}

function findRetiredLabelViolation(fixture: SourceFixture): string[] {
  const activeNavigation = fixture.mediaRoleIa.split(
    "export const retiredMediaNavLabels",
  )[0];
  if (activeNavigation.includes(RETIRED_MEDIA_PROCESSING_LABEL)) {
    return [
      "mediaRoleIa.ts active navigation contains retired Chinese label: " +
        RETIRED_MEDIA_PROCESSING_LABEL,
    ];
  }
  return [];
}

function inspectFixture(fixture: SourceFixture): string[] {
  return [
    ...findMissingPageViolations(fixture),
    ...findMediaStudioAppViolations(fixture),
    ...findPageSubstitutionViolations(fixture),
    ...findAdminOverviewViolation(fixture),
    ...findAdminOverviewResponseIntegrityViolations(fixture),
    ...findAdminBootstrapViolation(fixture),
    ...findPersistentRailViolations(fixture),
    ...findCssModuleUsageViolations(fixture),
    ...findOrdinaryNavGroupViolations(fixture),
    ...findRetiredLabelViolation(fixture),
  ];
}

function makeGreenFixture(): SourceFixture {
  const pages = new Map<string, string>();
  for (const page of PAGE_COMPONENTS) {
    const rail = PERSISTENT_RAIL_PAGE_FILES.includes(
      page.file as (typeof PERSISTENT_RAIL_PAGE_FILES)[number],
    )
      ? "<div data-page-layout><div data-page-primary /><aside data-page-inspector /></div>"
      : "";
    const flow = ["TracksPage", "DecisionsPage"].includes(page.owner)
      ? "<section data-primary-flow />"
      : "";
    const admin =
      page.file === ADMIN_OVERVIEW_PAGE_FILE
        ? `
const ACTION_TARGET_TYPE_LABELS: Record<AdminActionTargetType, string> = {
  platform: "平台",
  user: "用户",
  tenant: "租户",
  billing: "计费",
  admission: "准入",
  session: "会话",
  unknown: "未知",
};
if (audit.failedCount > audit.actionCount || Date.parse(audit.from) > Date.parse(audit.to)) throw new Error("invalid audit facts");
if (ACTION_TARGET_TYPES.has(value.targetType as AdminActionTargetType)) return;
<div className="admin-primary-column admin-side-column">审计事实（近 24 小时）</div>
<span>{ACTION_TARGET_TYPE_LABELS[action.targetType]}</span>`
        : "";
    pages.set(
      page.file,
      `export default function ${page.owner}() { return <>${rail}${flow}${admin}</> }\n`,
    );
  }
  return {
    mediaStudioApp: PAGE_COMPONENTS.map(
      (page) => "import " + page.owner + ' from "' + page.importPath + '"',
    ).join("\n"),
    mediaWebWorkspace:
      "if (value.role === 'admin') return\nvoid loadMediaCapabilities()\nvoid loadMediaTasks()\n",
    mediaRoleIa: `export const ${ORDINARY_NAV_GROUP_EXPORT} = [\n${ORDINARY_NAV_GROUP_LABELS.map((label) => `  { label: '${label}' },`).join("\n")}\n]\nexport const ordinaryMediaNav = []\n`,
    pages,
  };
}

function assertHasViolation(
  violations: readonly string[],
  expected: string,
  testName: string,
): void {
  if (!violations.some((violation) => violation.includes(expected))) {
    throw new Error(
      "B-GATE self-test failed: " + testName + " did not fail as expected",
    );
  }
}

function assertGreen(fixture: SourceFixture): void {
  const violations = inspectFixture(fixture);
  if (violations.length > 0) {
    throw new Error(
      "B-GATE self-test failed: legal green fixture produced " +
        violations.join(" | "),
    );
  }
}

function runSelfTests(): void {
  if (PAGE_COMPONENTS.length !== 16) {
    throw new Error(
      "B-GATE self-test failed: expected exactly 16 page components",
    );
  }

  assertGreen(makeGreenFixture());

  const missingPage = makeGreenFixture();
  missingPage.pages.delete(PAGE_COMPONENTS[0].file);
  assertHasViolation(
    inspectFixture(missingPage),
    "missing page component: " + PAGE_COMPONENTS[0].file,
    "missing page",
  );

  const missingImport = makeGreenFixture();
  missingImport.mediaStudioApp = missingImport.mediaStudioApp
    .split("\n")
    .filter((line) => !line.includes("import OverviewPage "))
    .join("\n");
  assertHasViolation(
    inspectFixture(missingImport),
    "missing direct default import for OverviewPage",
    "missing direct import",
  );

  const inlinePage = makeGreenFixture();
  inlinePage.mediaStudioApp += "\nfunction OverviewPage() { return null }\n";
  assertHasViolation(
    inspectFixture(inlinePage),
    "first-level page owner defined inline: OverviewPage",
    "inline page definition",
  );

  const tracksSubstitution = makeGreenFixture();
  tracksSubstitution.pages.set(
    "src/media/pages/ordinary/TracksPage.tsx",
    "loadTenantDashboard",
  );
  assertHasViolation(
    inspectFixture(tracksSubstitution),
    "TracksPage.tsx contains forbidden token loadTenantDashboard",
    "Tracks substitution",
  );

  const archivesSubstitution = makeGreenFixture();
  archivesSubstitution.pages.set(
    "src/media/pages/ordinary/ArchivesPage.tsx",
    "loadAssetSummaries",
  );
  assertHasViolation(
    inspectFixture(archivesSubstitution),
    "ArchivesPage.tsx contains forbidden token loadAssetSummaries",
    "Archives substitution",
  );

  const reviewsSubstitution = makeGreenFixture();
  reviewsSubstitution.pages.set(
    "src/media/pages/ordinary/ReviewsPage.tsx",
    "loadUsage",
  );
  assertHasViolation(
    inspectFixture(reviewsSubstitution),
    "ReviewsPage.tsx contains forbidden token loadUsage",
    "Reviews substitution",
  );

  const adminDelegation = makeGreenFixture();
  adminDelegation.pages.set(
    ADMIN_OVERVIEW_PAGE_FILE,
    '<AdminPage initialModule="dashboard" /><div data-page-layout><div data-page-primary /><aside data-page-inspector /></div><div className="admin-primary-column admin-side-column">审计事实（近 24 小时）</div>',
  );
  assertHasViolation(
    inspectFixture(adminDelegation),
    "AdminOverviewPage.tsx delegates to AdminPage",
    "admin delegation",
  );

  const impossibleFailedCount = makeGreenFixture();
  impossibleFailedCount.pages.set(
    ADMIN_OVERVIEW_PAGE_FILE,
    impossibleFailedCount.pages
      .get(ADMIN_OVERVIEW_PAGE_FILE)!
      .replace("audit.failedCount > audit.actionCount", "audit.failedCount < audit.actionCount"),
  );
  assertHasViolation(
    inspectFixture(impossibleFailedCount),
    "does not reject impossible audit failed counts",
    "admin overview impossible failed count",
  );

  const reversedAuditWindow = makeGreenFixture();
  reversedAuditWindow.pages.set(
    ADMIN_OVERVIEW_PAGE_FILE,
    reversedAuditWindow.pages
      .get(ADMIN_OVERVIEW_PAGE_FILE)!
      .replace(
        "Date.parse(audit.from) > Date.parse(audit.to)",
        "Date.parse(audit.from) < Date.parse(audit.to)",
      ),
  );
  assertHasViolation(
    inspectFixture(reversedAuditWindow),
    "does not reject reversed audit windows",
    "admin overview reversed audit window",
  );

  const rawTargetEnum = makeGreenFixture();
  rawTargetEnum.pages.set(
    ADMIN_OVERVIEW_PAGE_FILE,
    rawTargetEnum.pages
      .get(ADMIN_OVERVIEW_PAGE_FILE)!
      .replace(
        "ACTION_TARGET_TYPE_LABELS[action.targetType]",
        "action.targetType",
      ),
  );
  assertHasViolation(
    inspectFixture(rawTargetEnum),
    "exposes raw targetType enum",
    "admin overview raw target enum presentation",
  );

  const sideEffectCssModule = makeGreenFixture();
  sideEffectCssModule.pages.set(
    ADMIN_OVERVIEW_PAGE_FILE,
    "import './AdminOverviewPage.module.css'\n<div data-page-layout><div data-page-primary /><aside data-page-inspector /></div><div className=\"admin-primary-column admin-side-column\">审计事实（近 24 小时）</div>",
  );
  assertHasViolation(
    inspectFixture(sideEffectCssModule),
    "side-effect imports a CSS Module",
    "side-effect CSS Module import",
  );

  const adminBootstrap = makeGreenFixture();
  adminBootstrap.mediaWebWorkspace =
    "void loadMediaCapabilities()\nvoid loadMediaTasks()\n";
  assertHasViolation(
    inspectFixture(adminBootstrap),
    "does not stop administrator business bootstrap",
    "administrator business bootstrap",
  );

  const doubleQuotedAdminGuard = makeGreenFixture();
  doubleQuotedAdminGuard.mediaWebWorkspace =
    'if (value.role === "admin") return\nvoid loadMediaCapabilities()\nvoid loadMediaTasks()\n';
  assertGreen(doubleQuotedAdminGuard);

  const lateAdminGuard = makeGreenFixture();
  lateAdminGuard.mediaWebWorkspace =
    "void loadMediaCapabilities()\nvoid loadMediaTasks()\nif (value.role === 'admin') return\n";
  assertHasViolation(
    inspectFixture(lateAdminGuard),
    "administrator guard runs after a business bootstrap request",
    "late administrator business bootstrap guard",
  );

  const missingRail = makeGreenFixture();
  missingRail.pages.set(
    "src/media/pages/ordinary/OverviewPage.tsx",
    "export default function OverviewPage() { return null }",
  );
  assertHasViolation(
    inspectFixture(missingRail),
    "missing persistent rail token data-page-layout",
    "persistent rail",
  );

  const missingNavGroup = makeGreenFixture();
  missingNavGroup.mediaRoleIa = missingNavGroup.mediaRoleIa.replace(
    "  { label: '本机协作' },\n",
    "",
  );
  assertHasViolation(
    inspectFixture(missingNavGroup),
    "missing ordinary navigation group: 本机协作",
    "missing ordinary navigation group",
  );

  const retiredLabel = makeGreenFixture();
  retiredLabel.mediaRoleIa =
    'const label = "' + RETIRED_MEDIA_PROCESSING_LABEL + '"';
  assertHasViolation(
    inspectFixture(retiredLabel),
    "active navigation contains retired Chinese label",
    "retired label",
  );
}

function readIfPresent(repoRoot: string, relativePath: string): string {
  const absolutePath = path.join(repoRoot, relativePath);
  return fs.existsSync(absolutePath)
    ? fs.readFileSync(absolutePath, "utf8")
    : "";
}

function loadRealFixture(repoRoot: string): SourceFixture {
  const pages = new Map<string, string>();
  for (const page of PAGE_COMPONENTS) {
    const absolutePath = path.join(repoRoot, page.file);
    if (fs.existsSync(absolutePath)) {
      pages.set(page.file, fs.readFileSync(absolutePath, "utf8"));
    }
  }
  return {
    mediaStudioApp: readIfPresent(repoRoot, MEDIA_STUDIO_APP_FILE),
    mediaWebWorkspace: readIfPresent(repoRoot, MEDIA_WEB_WORKSPACE_FILE),
    mediaRoleIa: readIfPresent(repoRoot, MEDIA_ROLE_IA_FILE),
    pages,
  };
}

runSelfTests();
console.log("B-GATE self-test: PASS");

const realViolations = inspectFixture(
  loadRealFixture(path.resolve(process.cwd())),
);
if (realViolations.length === 0) {
  console.log("B-GATE real-source: GREEN");
} else {
  console.log("B-GATE real-source: RED");
  for (const violation of realViolations) {
    console.log("VIOLATION " + violation);
  }
  console.log("B-GATE real-source violations: " + realViolations.length);
  process.exitCode = 1;
}
