import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  realpathSync,
  writeFileSync,
} from "node:fs";
import { createServer as createHttpServer, type Server } from "node:http";
import { extname, join, relative, resolve, sep } from "node:path";
import { chromium, type Browser, type Page, type Route } from "playwright";
import {
  operations,
  type GeneratedOperation,
  type OperationId,
} from "../../src/media/generatedBusinessPagesContract";
import {
  PLATFORM_REGISTRY,
  type PlatformKey,
} from "../../src/media/ui/platformRegistry";

const versionTuple = "3/7/3/11";
const ssotRelativePath =
  "agents-results/2026-08-09/media-platform-brand-icon-registry-ssot/ssot-development-paths.md";
const mediaBase = "/openclaw/media";
const apiRoot = `${mediaBase}/api`;
const projectRoot = resolve(".");
const qaSourcePath = resolve(
  projectRoot,
  "scripts/qa/checkMediaPlatformBrandIcons.ts",
);
const qaSource = readFileSync(qaSourcePath, "utf8");
const directPageEvaluateCalls =
  qaSource.match(/page\.evaluate(?:<[^>]+>)?\s*\(/g) ?? [];
assert.equal(
  directPageEvaluateCalls.length,
  1,
  "Browser code must cross the Playwright boundary through raw expressions",
);
const unsupportedSvgRasterizer = ["create", "Image", "Bitmap"].join("");
assert.equal(
  qaSource.includes(unsupportedSvgRasterizer),
  false,
  "SVG pixel checks must use the Chromium-compatible image decode path",
);
const strictOptionalEvidenceVisibility = [
  "page.locator(spec.",
  "emptyEvidenceLocator",
  ").isVisible()",
].join("");
const firstOnlyOptionalEvidenceVisibility = [
  "page.locator(spec.",
  "emptyEvidenceLocator",
  ").first().isVisible()",
].join("");
assert.equal(
  qaSource.includes(strictOptionalEvidenceVisibility),
  false,
  "Optional evidence locators must not use strict single-element visibility",
);
assert.equal(
  qaSource.includes(firstOnlyOptionalEvidenceVisibility),
  false,
  "Optional evidence locators must not check only the first match",
);
for (const marker of [
  ["async function assert", "AllMatchesVisible"].join(""),
  ["assert(match", "Count > 0,"].join(""),
  ["matches.map((match) => match.", "isVisible())"].join(""),
  ["visibility.every(", "Boolean)"].join(""),
]) {
  assert(
    qaSource.includes(marker),
    `Optional evidence visibility contract is missing: ${marker}`,
  );
}
for (const marker of [
  "const runDetailCases =",
  "runDetailCases.find(",
  "for (const { run, phase } of runDetailCases)",
  "name: run.title",
]) {
  assert(
    qaSource.includes(marker),
    `Run-detail fixture SSOT contract is missing: ${marker}`,
  );
}
const splitRunDetailTitleExpectation = ["? runKnown", ".title"].join("");
assert(
  !qaSource.includes(splitRunDetailTitleExpectation),
  "Run-detail heading expectation must not diverge from the mocked fixture",
);
const incorrectPublishingNamedList = [
  'getByRole("list", ',
  '{ name: "发布包列表" })',
].join("");
assert(
  !qaSource.includes(incorrectPublishingNamedList),
  "Publishing QA must not bind the region name to the inner list role",
);
assert(
  /const\s+publishingListRegion\s*=\s*page\.getByRole\(\s*"region",\s*\{\s*name:\s*"发布包列表"\s*,?\s*\}\s*\)/m.test(
    qaSource,
  ),
  "Publishing QA must wait on the named list region",
);
assert(
  /publishingListRegion\s*\.getByRole\(\s*"listitem"\s*\)/m.test(qaSource),
  "Publishing list-item selection must stay inside the named region",
);
const ssotPath = resolve(projectRoot, ssotRelativePath);
const ssotSha256 = sha256(readFileSync(ssotPath));
const manifestInput = process.env.MEDIA_PLATFORM_ICONS_QA_MANIFEST;
assert(manifestInput, "D2 requires MEDIA_PLATFORM_ICONS_QA_MANIFEST from D1");
const candidateManifestPath = realpathSync(resolve(manifestInput));
assert.equal(
  normalizedPath(relative(projectRoot, candidateManifestPath)),
  "agents-results/2026-08-09/media-platform-brand-icon-registry-ssot/evidence/platform-icons/D1/candidate-manifest.json",
  "D2 manifest must be the explicit D1 candidate-manifest.json",
);
const viewports = [
  { name: "desktop-1440x900", width: 1440, height: 900 },
  { name: "mobile-390x844", width: 390, height: 844 },
] as const;
const stableRunId = "run_20260621_190713_57e1";

type RouteId =
  | "tracks"
  | "assets"
  | "decisions"
  | "runs"
  | "run-detail"
  | "publishing"
  | "reviews"
  | "admin-access";

type Role = "ordinary" | "admin";

type RouteSpec = {
  id: RouteId;
  role: Role;
  path: string;
  expectedKeys: readonly string[];
  emptyEvidenceLocator?: string;
};

type ApiResponseEvidence = {
  method: string;
  path: string;
  status: number;
  contentType: string;
  jsonParsed: boolean;
  htmlShell: boolean;
  bodyStart: string;
};

type IdentityMeasurement = {
  phase: string;
  key: string | null;
  label: string;
  source: string | null;
  iconBeforeLabel: boolean;
  iconVisuallyBeforeLabel: boolean;
  iconWidth: number;
  iconHeight: number;
  svgShapeCount: number;
  svgContentLength: number;
  paintedPixelCount: number;
  overlapArea: number;
  iconClipArea: number;
  labelClipArea: number;
};

type CaseResult = {
  routeId: RouteId;
  role: Role;
  route: string;
  viewport: string;
  identities: IdentityMeasurement[];
  observedKeys: string[];
  documentOverflow: number;
  bodyOverflow: number;
  emptyEvidenceMatched: boolean | null;
  apiRequests: string[];
  apiResponses: ApiResponseEvidence[];
  unexpectedApiRequests: string[];
  unexpectedNetworkRequests: string[];
  failedRequests: string[];
  httpFailures: string[];
  consoleErrors: string[];
  pageErrors: string[];
  screenshot: string;
  screenshotSha256: string;
  requests: string[];
};

type CandidateRecord = { path: string; bytes: number; sha256: string };
type CandidateManifest = {
  schemaVersion: "media_platform_icons_candidate_manifest_v1";
  versionTuple: string;
  ssotPath: string;
  ssotSha256: string;
  candidateRealpath: string;
  files: CandidateRecord[];
  filesSha256: string;
  buildCommand: string;
  completedAt: string;
};

const routeSpecs: readonly RouteSpec[] = [
  {
    id: "tracks",
    role: "ordinary",
    path: "/tracks",
    expectedKeys: [
      "douyin",
      "xiaohongshu",
      "kuaishou",
      "bilibili",
      "wechat",
      "weibo",
      "zhihu",
      "web",
      "unknown",
    ],
    emptyEvidenceLocator: '[aria-label="适用平台"] >> text=未声明平台',
  },
  {
    id: "assets",
    role: "ordinary",
    path: "/assets",
    expectedKeys: ["xiaohongshu", "douyin", "unknown"],
    emptyEvidenceLocator:
      '[data-assets-tab-panel="assets"] [data-platform-identity][data-platform-key="unknown"] [data-platform-label]',
  },
  {
    id: "decisions",
    role: "ordinary",
    path: "/decisions",
    expectedKeys: ["douyin", "xiaohongshu"],
  },
  {
    id: "runs",
    role: "ordinary",
    path: "/runs",
    expectedKeys: ["xiaohongshu", "douyin", "unknown"],
  },
  {
    id: "run-detail",
    role: "ordinary",
    path: `/runs/${stableRunId}`,
    expectedKeys: ["douyin", "unknown"],
  },
  {
    id: "publishing",
    role: "ordinary",
    path: "/publishing",
    expectedKeys: ["bilibili"],
  },
  {
    id: "reviews",
    role: "ordinary",
    path: "/reviews",
    expectedKeys: ["douyin", "xiaohongshu", "web", "unknown"],
    emptyEvidenceLocator: '[aria-label="发布复盘"] >> text=其他平台',
  },
  {
    id: "admin-access",
    role: "admin",
    path: "/admin/access",
    expectedKeys: ["xiaohongshu", "douyin"],
  },
] as const;

const operationEntries = Object.entries(operations) as Array<
  [OperationId, GeneratedOperation]
>;

function sha256(value: Buffer | string): string {
  return createHash("sha256").update(value).digest("hex");
}

function normalizedPath(value: string): string {
  return value.split(sep).join("/");
}

function candidateManifest(root: string) {
  const files: string[] = [];
  const visit = (directory: string) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const absolutePath = join(directory, entry.name);
      assert.equal(
        lstatSync(absolutePath).isSymbolicLink(),
        false,
        `D1 candidate contains a symbolic link: ${absolutePath}`,
      );
      if (entry.isDirectory()) visit(absolutePath);
      else if (entry.isFile()) files.push(absolutePath);
    }
  };
  visit(root);
  const records = files
    .map((file) => ({
      path: normalizedPath(relative(root, file)),
      sha256: sha256(readFileSync(file)),
      bytes: lstatSync(file).size,
    }))
    .sort((left, right) => left.path.localeCompare(right.path));
  const manifestText =
    records
      .map((record) => `${record.sha256}  ${record.bytes}  ${record.path}`)
      .join("\n") + "\n";
  return { records, manifestText, sha256: sha256(manifestText) };
}

function readCandidateManifest(): {
  manifest: CandidateManifest;
  candidateRoot: string;
  snapshot: ReturnType<typeof candidateManifest>;
} {
  const parsed = JSON.parse(
    readFileSync(candidateManifestPath, "utf8"),
  ) as Partial<CandidateManifest>;
  assert.equal(
    parsed.schemaVersion,
    "media_platform_icons_candidate_manifest_v1",
    "D1 candidate manifest schema is invalid",
  );
  assert.equal(
    parsed.versionTuple,
    versionTuple,
    "D1 candidate manifest version tuple is stale",
  );
  assert.equal(
    parsed.ssotPath,
    ssotPath,
    "D1 candidate manifest SSOT path is not authoritative",
  );
  assert.equal(
    parsed.ssotSha256,
    ssotSha256,
    "D1 candidate manifest SSOT hash is stale",
  );
  assert.equal(
    parsed.buildCommand,
    "npm run build:media",
    "D1 candidate manifest build command is not frozen",
  );
  assert(
    typeof parsed.completedAt === "string" && parsed.completedAt.length > 0,
    "D1 candidate manifest is missing build completion time",
  );
  assert(
    typeof parsed.candidateRealpath === "string",
    "D1 candidate manifest is missing candidate realpath",
  );
  const candidateRoot = realpathSync(parsed.candidateRealpath);
  assert.equal(
    normalizedPath(relative(projectRoot, candidateRoot)),
    "dist-media",
    "D2 must serve the D1 dist-media candidate",
  );
  assert.equal(
    parsed.candidateRealpath,
    candidateRoot,
    "D1 candidate realpath is not canonical",
  );
  assert(Array.isArray(parsed.files), "D1 candidate manifest is missing files");
  assert.equal(
    typeof parsed.filesSha256,
    "string",
    "D1 candidate manifest is missing files SHA-256",
  );
  const snapshot = candidateManifest(candidateRoot);
  const files = parsed.files as CandidateRecord[];
  assert.deepEqual(
    files,
    snapshot.records,
    "D1 candidate files do not match the manifest before execution",
  );
  assert.equal(
    parsed.filesSha256,
    snapshot.sha256,
    "D1 candidate aggregate SHA-256 is stale",
  );
  return { manifest: parsed as CandidateManifest, candidateRoot, snapshot };
}

function operationIdFor(method: string, path: string): OperationId | null {
  const actual = path.replace(/\/+$/, "").split("/").filter(Boolean);
  for (const [id, operation] of operationEntries) {
    const template = operation.path.split("/").filter(Boolean);
    if (operation.method !== method || template.length !== actual.length)
      continue;
    if (
      template.every(
        (part, index) => part.startsWith("{") || part === actual[index],
      )
    ) {
      return id;
    }
  }
  return null;
}

function listResponse(items: unknown[], revision = 1) {
  return {
    schemaVersion: "media_web_business_pages_v2",
    revision,
    items,
    nextCursor: null,
  };
}

const track = {
  publicTrackId: "track_d2_all_platforms",
  name: "全平台内容赛道",
  description: "D2 候选构建平台注册表验收。",
  parentPublicTrackId: null,
  status: "active",
  platforms: [
    "douyin",
    "xiaohongshu",
    "kuaishou",
    "bilibili",
    "wechat",
    "weibo",
    "zhihu",
    "web",
    "unregistered-platform",
  ],
  aliases: ["全平台"],
  artifactCount: 9,
  updatedAt: "2026-08-09T05:00:00Z",
};
const emptyTrack = {
  ...track,
  publicTrackId: "track_d2_empty",
  name: "空平台赛道",
  platforms: [],
};
const creator = {
  publicCreatorId: "creator_d2",
  accountName: "平台身份达人",
  platform: "xiaohongshu",
  creatorRole: "creator",
  identityTags: ["训练"],
  expertiseDomains: ["strength"],
  profileUrl: "https://example.test/creator/d2",
  avatarUrl: null,
  updatedAt: "2026-08-09T05:00:00Z",
};
const relationship = {
  publicRelationshipId: "relationship_d2",
  publicTrackId: track.publicTrackId,
  publicCreatorId: creator.publicCreatorId,
  role: "标杆账号",
  fitScore: 96,
  fitReason: "人工确认的赛道关系。",
  status: "active",
  lastEvaluatedAt: "2026-08-09T05:00:00Z",
};
const account = {
  publicAccountId: "account_d2",
  platform: "douyin",
  accountName: "自有运营账号",
  operationalStatus: "active",
  responsiblePerson: "平台运营负责人",
  teamName: "内容运营组",
  accountPositioning: "校园运动内容账号",
  dataSource: "feishu_creator_profile",
  profileUrl: "https://example.test/account/d2",
  publicTrackIds: [track.publicTrackId],
  lastSyncedAt: "2026-08-09T05:00:00Z",
  updatedAt: "2026-08-09T05:00:00Z",
};
const strategy = {
  publicStrategyId: "strategy_d2",
  publicAccountId: account.publicAccountId,
  targetPublicTrackIds: [track.publicTrackId],
  evidenceRefs: [],
  recommendations: ["保持平台注册表原始值。"],
  humanStatus: "pending",
  revision: 1,
  updatedAt: "2026-08-09T05:00:00Z",
};

const assets = [
  {
    publicAssetId: "asset-d2-redbook",
    title: "小红书夏季训练灵感",
    mediaType: "video",
    thumbnail: {},
    materialStatus: "ready",
    platform: "redbook",
    sourceLabel: "D2 浏览器夹具",
    tags: ["夏训"],
    trackNames: ["运动训练"],
    qualityStatus: "verified",
    createdAt: "2026-08-09T01:00:00Z",
    usageCount: 3,
  },
  {
    publicAssetId: "asset-d2-unknown",
    title: "待确认来源的训练灵感",
    mediaType: "link",
    thumbnail: {},
    materialStatus: "pending",
    platform: "mystery-channel",
    sourceLabel: "D2 浏览器夹具",
    tags: ["待确认"],
    trackNames: ["运动训练"],
    qualityStatus: "pending",
    createdAt: "2026-08-08T01:00:00Z",
    usageCount: 1,
  },
  {
    publicAssetId: "asset-d2-empty",
    title: "未填写平台的图片素材",
    mediaType: "image",
    thumbnail: {},
    materialStatus: "pending",
    platform: "",
    sourceLabel: "D2 浏览器夹具",
    tags: ["空值"],
    trackNames: ["运动训练"],
    qualityStatus: "pending",
    createdAt: "2026-08-07T01:00:00Z",
    usageCount: 0,
  },
  {
    publicAssetId: "asset-d2-douyin",
    title: "抖音力量训练灵感",
    mediaType: "image",
    thumbnail: {},
    materialStatus: "pending",
    platform: "douyin",
    sourceLabel: "D2 浏览器夹具",
    tags: ["力量"],
    trackNames: ["运动训练"],
    qualityStatus: "pending",
    createdAt: "2026-08-06T01:00:00Z",
    usageCount: 1,
  },
];

const decision = {
  publicDecisionId: "decision-d2-douyin",
  candidateTitle: "抖音夏季新品短视频选题",
  candidateType: "activity",
  platform: "douyin",
  trackName: "智能运动装备",
  decisionStatus: "recommended",
  evidenceCount: 6,
  humanConfirmedAt: null,
  updatedAt: "2026-08-09T02:30:00Z",
};

const runKnown = {
  publicRunId: "run_d2_known",
  title: "小红书力量训练创作运行",
  platform: "xiaohongshu",
  contentType: "video",
  trackName: "力量训练",
  entrypoint: "selfmedia_creation",
  status: "running",
  availableSections: ["decisions"],
  publicProjectId: "project_d2_known",
  createdAt: "2026-08-09T01:00:00Z",
  updatedAt: "2026-08-09T02:00:00Z",
  revision: 5,
};
const runUnknown = {
  ...runKnown,
  publicRunId: "run_d2_unknown",
  title: "新平台创作运行",
  platform: "future-network",
  publicProjectId: "project_d2_unknown",
  status: "pending",
  revision: 3,
};
const runMissing = {
  ...runKnown,
  publicRunId: "run_d2_missing",
  title: "尚未登记平台的创作运行",
  platform: null,
  publicProjectId: null,
  availableSections: [],
  status: "completed",
  revision: 2,
};
const runs = [runKnown, runUnknown, runMissing];
const runDetailKnown = {
  ...runKnown,
  publicRunId: stableRunId,
  title: "品牌平台图标运行详情布局验证",
  platform: "douyin",
  contentType: "long_video",
  trackName: "跨平台内容增长",
  entrypoint: "用于验证摘要排版且不会挤压相邻平台图标的创作入口",
  status: "completed",
  availableSections: ["sources", "decisions", "outputs"],
  publicProjectId: "project-run-detail-d2",
  createdAt: "2026-08-09T07:30:00Z",
  updatedAt: "2026-08-09T08:00:00Z",
  revision: 5,
};
const runDetailCases = [
  { run: runDetailKnown, phase: "run-detail-known" },
  { run: runUnknown, phase: "run-detail-unknown" },
  { run: runMissing, phase: "run-detail-empty" },
] as const;
assert.equal(
  new Set(runDetailCases.map(({ run }) => run.publicRunId)).size,
  runDetailCases.length,
  "Run-detail fixture IDs must be unique",
);
assert(
  runDetailCases.some(({ run }) => run.publicRunId === stableRunId),
  "Run-detail fixtures must include the stable route fixture",
);
const opportunities = [
  {
    publicOpportunityId: "opportunity_d2_known",
    brand: "品牌甲",
    product: "训练装备",
    platform: "douyin",
    contentType: "video",
    validFrom: "2026-08-01T00:00:00Z",
    validUntil: "2026-08-31T00:00:00Z",
    authorizationScope: "public",
    status: "active",
  },
  {
    publicOpportunityId: "opportunity_d2_unknown",
    brand: "品牌乙",
    product: "新平台合作",
    platform: "future-network",
    contentType: "article",
    validFrom: null,
    validUntil: null,
    authorizationScope: "private",
    status: "pending",
  },
  {
    publicOpportunityId: "opportunity_d2_missing",
    brand: "品牌丙",
    product: "待登记平台合作",
    platform: "",
    contentType: "video",
    validFrom: null,
    validUntil: null,
    authorizationScope: "non_exclusive",
    status: "active",
  },
];

const publishingPackage = {
  publicPackageId: "publishing-package-d2",
  publicRunId: "run-publishing-d2",
  platform: "bilibili",
  contentFields: {
    title: "D2 平台身份发布测试",
    body: "使用冻结候选验证平台图标和名称。",
  },
  ruleChecks: [{ key: "publication_boundary", status: "pass" }],
  artifactDescriptor: {
    publicArtifactId: "artifact-d2",
    publicProjectId: "project-d2",
    artifactType: "document",
    bodyAuthority: "local",
    currentRevision: 4,
    syncStatus: "synced",
    updatedAt: "2026-08-09T02:00:00Z",
    allowedActions: ["read"],
  },
  humanChecks: [
    { key: "content", checked: true, status: "complete" },
    { key: "publication", checked: true, status: "complete" },
  ],
  status: "ready",
  revision: 9,
};

const reviews = [
  {
    publicReviewId: "review-douyin",
    publicPostId: "post-douyin",
    postTitle: null,
    documentUrl: null,
    platform: "douyin",
    snapshot24h: "snapshot-douyin-24h",
    snapshot7d: "snapshot-douyin-7d",
    evidenceQuality: "verified",
    modelSuggestion: "保持前三秒的信息密度。",
    humanDecision: null,
    status: "pending",
    revision: 3,
  },
  {
    publicReviewId: "review-xiaohongshu",
    publicPostId: "post-xiaohongshu",
    postTitle: "小红书合作复盘",
    documentUrl: null,
    platform: "xiaohongshu",
    snapshot24h: "snapshot-xiaohongshu-24h",
    snapshot7d: null,
    evidenceQuality: "partial",
    modelSuggestion: "补齐收藏率证据。",
    humanDecision: "继续验证",
    status: "confirmed",
    revision: 5,
  },
  {
    publicReviewId: "review-web",
    publicPostId: "post-web",
    postTitle: "网页渠道复盘",
    documentUrl: null,
    platform: "web",
    snapshot24h: null,
    snapshot7d: null,
    evidenceQuality: "unverified",
    modelSuggestion: null,
    humanDecision: null,
    status: "pending",
    revision: 1,
  },
  {
    publicReviewId: "review-unknown",
    publicPostId: "post-unknown",
    postTitle: null,
    documentUrl: null,
    platform: "mystery-channel",
    snapshot24h: null,
    snapshot7d: null,
    evidenceQuality: "unavailable",
    modelSuggestion: null,
    humanDecision: null,
    status: "pending",
    revision: 1,
  },
  {
    publicReviewId: "review-empty",
    publicPostId: "post-empty",
    postTitle: null,
    documentUrl: null,
    platform: "",
    snapshot24h: null,
    snapshot7d: null,
    evidenceQuality: "unavailable",
    modelSuggestion: null,
    humanDecision: null,
    status: "pending",
    revision: 1,
  },
];

const configurationScript =
  "/home/ubuntu/selfmedia-tools/integrations/platform_auth/cookies/save_platform_cookie_secret.py";
const adminPlatformItems = [
  {
    platform: "xiaohongshu",
    configured: false,
    updatedAt: null,
    validationStatus: "missing",
    errorCode: null,
    configurationScript,
    safeCommand: `python3 ${configurationScript} --platform xiaohongshu`,
  },
  {
    platform: "douyin",
    configured: true,
    updatedAt: "2026-08-09T01:30:00Z",
    validationStatus: "valid",
    errorCode: null,
    configurationScript,
    safeCommand: `python3 ${configurationScript} --platform douyin`,
  },
];

function fixtureFor(
  spec: RouteSpec,
  operationId: OperationId,
  path: string,
): unknown {
  if (operationId === "getMediaSession") {
    return {
      schemaVersion: "media_web_business_pages_v2",
      revision: 1,
      session: {
        publicUserId:
          spec.role === "admin"
            ? "88888888-8888-4888-8888-888888888888"
            : "22222222-2222-4222-8222-222222222222",
        organizationName: null,
        workspaceMode: "personal_web",
        editorMode: "web_edit",
        bodyAuthority: "internal",
        memberRole: "owner",
        organizationConnection: "not_applicable",
        installationConnection: "not_applicable",
        role: spec.role,
        maintainer: false,
        csrfToken: `d2-${spec.id}-fixture-csrf`,
        expiresAt: "2099-01-01T00:00:00Z",
        schemaVersion: "media_web_business_pages_v2",
      },
    };
  }
  if (operationId === "listMediaCapabilities") {
    return {
      schemaVersion: "media_capability_catalog_v1",
      version: `d2-${spec.id}`,
      capabilities: [],
    };
  }
  if (operationId === "listMediaTasks") return { tasks: [] };

  if (spec.id === "tracks") {
    switch (operationId) {
      case "listTracks":
        return listResponse([track, emptyTrack]);
      case "listCreators":
        return listResponse([creator]);
      case "listTrackRelationships":
        return listResponse([relationship]);
      case "listOwnedAccounts":
        return listResponse([account]);
      case "getCreator":
        return {
          schemaVersion: "media_web_business_pages_v2",
          revision: 1,
          item: creator,
        };
      case "getOwnedAccount":
        return {
          schemaVersion: "media_web_business_pages_v2",
          revision: 1,
          item: account,
        };
      case "getAccountTrackStrategy":
        return {
          schemaVersion: "media_web_business_pages_v2",
          revision: 1,
          strategy,
        };
      default:
        break;
    }
  }

  if (spec.id === "assets") {
    if (operationId === "listAssets") return listResponse(assets, 11);
    if (operationId === "getAsset") {
      const publicAssetId = decodeURIComponent(path.split("/").at(-1) ?? "");
      const summary = assets.find(
        (item) => item.publicAssetId === publicAssetId,
      );
      assert(summary, `Unknown D2 asset fixture: ${publicAssetId}`);
      return {
        schemaVersion: "media_web_business_pages_v2",
        revision: 12,
        item: {
          summary,
          evidenceRefs: [],
          previewDescriptor: {},
          deconstructions: [],
          creativePatterns: [],
          usageRefs: [],
          revision: 4,
        },
      };
    }
  }

  if (spec.id === "decisions") {
    if (operationId === "listDecisions") return listResponse([decision], 11);
    if (operationId === "getDecision") {
      return {
        schemaVersion: "media_web_business_pages_v2",
        revision: 11,
        decision,
      };
    }
    if (operationId === "listDecisionSignals") {
      return listResponse(
        [
          {
            publicSignalId: "signal-d2-redbook",
            kind: "hotlist",
            platform: "xiaohongshu",
            title: "小红书户外训练装备趋势",
            rank: 4,
            sourceUrl: "https://example.test/d2-source",
            capturedAt: "2026-08-09T02:10:00Z",
            qualityStatus: "verified",
          },
        ],
        8,
      );
    }
  }

  if (spec.id === "runs") {
    if (operationId === "listRuns") return listResponse(runs, 5);
    if (operationId === "listBusinessOpportunities")
      return listResponse(opportunities, 5);
    if (operationId === "getRun") {
      const publicRunId = decodeURIComponent(path.split("/").at(-1) ?? "");
      const run = runs.find((item) => item.publicRunId === publicRunId);
      assert(run, `Unknown D2 run fixture: ${publicRunId}`);
      return {
        schemaVersion: "media_web_business_pages_v2",
        revision: run.revision,
        run,
      };
    }
    if (operationId === "getRunDecisions") {
      const publicRunId = decodeURIComponent(path.split("/").at(-2) ?? "");
      return {
        schemaVersion: "media_web_business_pages_v2",
        revision: 5,
        section: {
          publicRunId,
          decisionItems: [
            {
              ...decision,
              publicDecisionId: "run-decision-known",
              platform: "xiaohongshu",
            },
            {
              ...decision,
              publicDecisionId: "run-decision-unknown",
              platform: "future-network",
            },
            {
              ...decision,
              publicDecisionId: "run-decision-empty",
              platform: "",
            },
          ],
          humanState: "pending",
          revision: 5,
        },
      };
    }
    if (operationId === "getRunSources") {
      return {
        schemaVersion: "media_web_business_pages_v2",
        revision: 5,
        section: {
          publicRunId: runKnown.publicRunId,
          sourceKinds: ["asset"],
          items: [{ platform: "future-network" }, { platform: "" }],
          evidenceRefs: [],
          revision: 5,
        },
      };
    }
    if (operationId === "getRunOutputs") {
      return {
        schemaVersion: "media_web_business_pages_v2",
        revision: 5,
        section: { publicRunId: runKnown.publicRunId, items: [], revision: 5 },
      };
    }
  }

  if (spec.id === "run-detail") {
    if (operationId === "getDashboard") {
      return {
        schemaVersion: "media_web_business_pages_v2",
        revision: 1,
        summary: {
          counts: {
            contentProjects: 0,
            runs: 1,
            assets: 0,
            tracks: 0,
            creators: 0,
            publishedPosts: 0,
            reviews: 0,
          },
          contentProjectStages: [],
          pendingDecisions: 0,
          pendingPublishing: 0,
          pendingReviews: 0,
          taskSummary: { queued: 0, running: 0, needsAttention: 0, failed: 0 },
          coverage: { known: 1, unknown: 0, unavailable: 0 },
          generatedAt: "2026-08-09T08:00:00Z",
          revision: 1,
        },
      };
    }
    if (operationId === "listContentProjects") return listResponse([]);
    if (operationId === "getRun") {
      const requestedRunId = decodeURIComponent(path.split("/").at(-1) ?? "");
      const runCase = runDetailCases.find(
        ({ run }) => run.publicRunId === requestedRunId,
      );
      assert(runCase, `Unknown D2 run-detail fixture: ${requestedRunId}`);
      return {
        schemaVersion: "media_web_business_pages_v2",
        revision: 5,
        run: runCase.run,
      };
    }
  }

  if (spec.id === "publishing") {
    if (operationId === "listPublishingPackages")
      return listResponse([publishingPackage], 9);
    if (operationId === "getPublishingPackage") {
      return {
        schemaVersion: "media_web_business_pages_v2",
        revision: 9,
        package: publishingPackage,
      };
    }
    if (operationId === "createPublishedPost") {
      return {
        schemaVersion: "media_web_business_pages_v2",
        revision: 1,
        publishedPost: {
          publicPostId: "post-d2-receipt",
          publicPackageId: publishingPackage.publicPackageId,
          platform: publishingPackage.platform,
          publishedUrl: "https://example.test/d2-published",
          publishedAt: "2026-08-09T10:00:00.000Z",
          recordedBy: "human",
          evidenceQuality: "verified",
        },
      };
    }
    if (operationId === "getPublishedPost") {
      return {
        schemaVersion: "media_web_business_pages_v2",
        revision: 1,
        publishedPost: {
          publicPostId: "post-d2-receipt",
          publicPackageId: publishingPackage.publicPackageId,
          platform: publishingPackage.platform,
          publishedUrl: "https://example.test/d2-published",
          publishedAt: "2026-08-09T10:00:00.000Z",
          recordedBy: "human",
          evidenceQuality: "verified",
        },
      };
    }
  }

  if (spec.id === "reviews") {
    if (operationId === "getReviewsSummary") {
      return {
        schemaVersion: "media_web_business_pages_v2",
        revision: 1,
        summary: {
          reviewCount: reviews.length,
          pending24h: 2,
          pending7d: 3,
          confirmedCount: 1,
          evidenceCoverage: 0.75,
          generatedAt: "2026-08-09T00:00:00Z",
        },
      };
    }
    if (operationId === "listReviews") return listResponse(reviews);
    if (
      operationId === "listContentMetrics" ||
      operationId === "listAccountMetrics"
    ) {
      return listResponse([]);
    }
  }

  if (spec.id === "admin-access") {
    if (operationId === "listAdminAffiliateUsers") return listResponse([], 7);
    if (operationId === "listAdminAdmissionBatches") return listResponse([], 5);
    if (operationId === "getAdminRegistrationPolicy") {
      return {
        schemaVersion: "media_web_business_pages_v2",
        revision: 3,
        policy: {
          mode: "invite_only",
          revision: 3,
          updatedAt: "2026-08-09T01:00:00Z",
        },
      };
    }
    if (operationId === "getAdminPlatformCookies") {
      return {
        schemaVersion: "media_web_business_pages_v2",
        platforms: adminPlatformItems,
      };
    }
  }

  throw new Error(
    `Unhandled D2 operation ${operationId} for ${spec.id}: ${path}`,
  );
}

async function fulfillJson(
  route: Route,
  status: number,
  body: unknown,
): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json; charset=utf-8",
    headers: { "Cache-Control": "no-store" },
    body: JSON.stringify(body),
  });
}

function contentType(file: string): string {
  switch (extname(file)) {
    case ".css":
      return "text/css; charset=utf-8";
    case ".html":
      return "text/html; charset=utf-8";
    case ".ico":
      return "image/x-icon";
    case ".js":
      return "text/javascript; charset=utf-8";
    case ".json":
      return "application/json; charset=utf-8";
    case ".png":
      return "image/png";
    case ".svg":
      return "image/svg+xml";
    case ".woff":
      return "font/woff";
    case ".woff2":
      return "font/woff2";
    default:
      return "application/octet-stream";
  }
}

async function startCandidateServer(): Promise<{
  server: Server;
  baseUrl: string;
}> {
  const indexPath = join(candidateRoot, "index.html");
  assert(
    existsSync(indexPath),
    `D1 candidate is missing index.html: ${candidateRoot}`,
  );
  const rootPrefix = candidateRoot.endsWith(sep)
    ? candidateRoot
    : candidateRoot + sep;
  const server = createHttpServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    let decodedPath: string;
    try {
      decodedPath = decodeURIComponent(url.pathname);
    } catch {
      response.statusCode = 400;
      response.end("bad path");
      return;
    }
    if (decodedPath !== mediaBase && !decodedPath.startsWith(`${mediaBase}/`)) {
      response.statusCode = 404;
      response.end("not found");
      return;
    }
    const relativePath = decodedPath
      .slice(mediaBase.length)
      .replace(/^\/+/, "");
    const requestedPath =
      relativePath && extname(relativePath)
        ? resolve(candidateRoot, relativePath)
        : indexPath;
    if (requestedPath !== indexPath && !requestedPath.startsWith(rootPrefix)) {
      response.statusCode = 403;
      response.end("forbidden");
      return;
    }
    if (!existsSync(requestedPath) || !lstatSync(requestedPath).isFile()) {
      response.statusCode = 404;
      response.end("not found");
      return;
    }
    response.statusCode = 200;
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("Content-Type", contentType(requestedPath));
    response.end(readFileSync(requestedPath));
  });
  await new Promise<void>((resolveListen, rejectListen) => {
    server.once("error", rejectListen);
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address();
  assert(
    address && typeof address === "object",
    "D2 candidate server did not expose a port",
  );
  return { server, baseUrl: `http://127.0.0.1:${address.port}${mediaBase}` };
}

async function closeServer(server: Server): Promise<void> {
  await new Promise<void>((resolveClose, rejectClose) => {
    server.close((error) => (error ? rejectClose(error) : resolveClose()));
  });
}

async function evaluateBrowserExpression<Result>(
  page: Page,
  expression: string,
): Promise<Result> {
  assert.equal(
    expression.includes("__name"),
    false,
    "Browser expression contains a Node-side transform helper",
  );
  return page.evaluate<Result>(expression);
}

async function collectIdentities(
  page: Page,
  phase: string,
): Promise<IdentityMeasurement[]> {
  const identityCollector = String.raw`async (phaseName) => {
    const overlapArea = (left, right) => {
      const width = Math.max(
        0,
        Math.min(left.right, right.right) - Math.max(left.left, right.left),
      );
      const height = Math.max(
        0,
        Math.min(left.bottom, right.bottom) - Math.max(left.top, right.top),
      );
      return width * height;
    };
    const outsideArea = (inner, outer) =>
      Math.max(0, inner.width * inner.height - overlapArea(inner, outer));
    const paintedPixels = async (svg, icon) => {
      const clone = svg.cloneNode(true);
      clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
      clone.setAttribute("width", "24");
      clone.setAttribute("height", "24");
      clone.style.color = getComputedStyle(icon).color;
      const serialized = new XMLSerializer().serializeToString(clone);
      const image = new Image();
      await new Promise((resolve, reject) => {
        const platform =
          icon.getAttribute("data-platform-key") ?? "unknown";
        const source =
          icon.getAttribute("data-platform-icon-source") ?? "unknown";
        const context = "platform=" + platform + "; source=" + source;
        const timeout = setTimeout(() => {
          image.onload = null;
          image.onerror = null;
          reject(new Error("Platform icon SVG decode timed out: " + context));
        }, 5000);
        image.onload = () => {
          clearTimeout(timeout);
          image.onload = null;
          image.onerror = null;
          resolve(undefined);
        };
        image.onerror = () => {
          clearTimeout(timeout);
          image.onload = null;
          image.onerror = null;
          reject(new Error("Platform icon SVG decode failed: " + context));
        };
        image.src =
          "data:image/svg+xml;charset=utf-8," + encodeURIComponent(serialized);
      });
      const canvas = document.createElement("canvas");
      canvas.width = 24;
      canvas.height = 24;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      if (!context) throw new Error("Platform icon canvas context is unavailable");
      context.clearRect(0, 0, 24, 24);
      context.drawImage(image, 0, 0, 24, 24);
      const pixels = context.getImageData(0, 0, 24, 24).data;
      let count = 0;
      for (let index = 3; index < pixels.length; index += 4) {
        if (pixels[index] > 0) count += 1;
      }
      return count;
    };
    const identities = Array.from(
      document.querySelectorAll("[data-platform-identity]"),
    ).filter((identity) => {
      const style = getComputedStyle(identity);
      const rect = identity.getBoundingClientRect();
      return (
        style.display !== "none" &&
        style.visibility !== "hidden" &&
        rect.width > 0 &&
        rect.height > 0
      );
    });
    return Promise.all(
      identities.map(async (identity) => {
        const icon = identity.querySelector(
          ":scope > [data-platform-icon]",
        );
        const label = identity.querySelector(
          ":scope > [data-platform-label]",
        );
        const svg = icon?.querySelector("svg") ?? null;
        if (!icon || !label || !svg)
          throw new Error("PlatformIdentity DOM contract is incomplete");
        const identityRect = identity.getBoundingClientRect();
        const iconRect = icon.getBoundingClientRect();
        const labelRect = label.getBoundingClientRect();
        const shapes = Array.from(
          svg.querySelectorAll(
            "path,circle,ellipse,line,polyline,polygon,rect",
          ),
        );
        return {
          phase: phaseName,
          key: identity.getAttribute("data-platform-key"),
          label: label.textContent?.trim() ?? "",
          source: icon.getAttribute("data-platform-icon-source"),
          iconBeforeLabel:
            identity.firstElementChild === icon &&
            icon.nextElementSibling === label,
          iconVisuallyBeforeLabel:
            iconRect.left <= labelRect.left &&
            iconRect.right <= labelRect.left + 0.5,
          iconWidth: iconRect.width,
          iconHeight: iconRect.height,
          svgShapeCount: shapes.length,
          svgContentLength: shapes
            .map((shape) => shape.getAttribute("d") ?? shape.outerHTML)
            .join("").length,
          paintedPixelCount: await paintedPixels(svg, icon),
          overlapArea: overlapArea(iconRect, labelRect),
          iconClipArea: outsideArea(iconRect, identityRect),
          labelClipArea: outsideArea(labelRect, identityRect),
        };
      }),
    );
  }`;
  return evaluateBrowserExpression<IdentityMeasurement[]>(
    page,
    `(${identityCollector})(${JSON.stringify(phase)})`,
  );
}

async function collectRoutePhases(
  page: Page,
  spec: RouteSpec,
  baseUrl: string,
): Promise<IdentityMeasurement[]> {
  const collected: IdentityMeasurement[] = [];
  const collect = async (phase: string) => {
    await page
      .locator("[data-platform-identity]:visible")
      .first()
      .waitFor({ state: "visible" });
    collected.push(...(await collectIdentities(page, phase)));
  };

  if (spec.id === "tracks") {
    await page
      .locator('main[data-page-state="ready"]')
      .waitFor({ state: "visible" });
    await page.getByRole("tab", { name: "赛道概览", exact: true }).click();
    await collect("tracks");
    await page.getByRole("tab", { name: "对标账号", exact: true }).click();
    await page.getByRole("tab", { name: /已关注 1/ }).click();
    await collect("benchmarks");
    await page.getByRole("tab", { name: "自有账号", exact: true }).click();
    await collect("owned-accounts");
    await page.getByRole("tab", { name: "赛道概览", exact: true }).click();
    await page.locator('[aria-label="适用平台"] >> text=未声明平台').waitFor({ state: "visible" });
    return collected;
  }

  if (spec.id === "decisions") {
    await page
      .getByRole("heading", { name: "候选选题", exact: true })
      .waitFor();
    await collect("decisions");
    await page
      .getByRole("button", { name: decision.candidateTitle, exact: true })
      .click();
    await page
      .locator("[data-page-inspector] [data-platform-identity]:visible")
      .first()
      .waitFor({ state: "visible" });
    await collect("decision-detail");
    await page.getByRole("tab", { name: "来源信号", exact: true }).click();
    await page
      .getByRole("heading", { name: "来源信号", exact: true })
      .waitFor();
    await collect("signals");
    return collected;
  }

  if (spec.id === "assets") {
    await page.locator("#assets-tabpanel").waitFor({ state: "visible" });
    await collect("assets");
    await page
      .getByRole("button", { name: `查看素材 ${assets[0].title}`, exact: true })
      .click();
    await page
      .locator('[aria-label="素材详情"] [data-detail-revision]')
      .waitFor({ state: "visible" });
    await collect("asset-detail");
    return collected;
  }

  if (spec.id === "runs") {
    await page.getByRole("region", { name: "创作运行表格" }).waitFor();
    await collect("runs");
    await page.getByRole("tab", { name: "商务机会", exact: true }).click();
    await page.getByRole("region", { name: "商务机会表格" }).waitFor();
    await collect("opportunities");
    await page.getByRole("tab", { name: "创作运行", exact: true }).click();
    await page.getByRole("region", { name: "创作运行表格" }).waitFor();
    await page
      .getByRole("button", {
        name: `查看运行 ${runKnown.publicRunId}`,
        exact: true,
      })
      .click();
    await page.getByRole("region", { name: "运行详情内容" }).waitFor();
    await collect("run-inspector");
    await page.getByRole("tab", { name: "决定", exact: true }).click();
    await page
      .locator('[aria-label="运行详情预览"] [data-platform-identity]:visible')
      .first()
      .waitFor({ state: "visible" });
    await collect("run-decisions");
    return collected;
  }

  if (spec.id === "publishing") {
    const publishingListRegion = page.getByRole("region", {
      name: "发布包列表",
    });
    await publishingListRegion.waitFor();
    await collect("publishing");
    await publishingListRegion
      .getByRole("listitem")
      .filter({ hasText: publishingPackage.publicPackageId })
      .click();
    await page
      .locator('[aria-label="发布包详情"] [data-platform-identity]:visible')
      .first()
      .waitFor({ state: "visible" });
    await collect("publishing-detail");
    await page.getByRole("textbox", { name: "平台" }).waitFor();
    assert.equal(
      await page.getByRole("textbox", { name: "平台" }).inputValue(),
      "哔哩哔哩",
      "Publishing platform input did not use the registry label",
    );
    await page
      .getByRole("textbox", { name: "已发布公开链接" })
      .fill("https://example.test/d2-published");
    await page
      .locator('[aria-label="发布包详情"] input[type="datetime-local"]')
      .fill("2026-08-09T10:00");
    await page
      .getByRole("button", { name: "记录人工发布回执", exact: true })
      .click();
    await page.getByText("发布回执已回读", { exact: true }).waitFor();
    await collect("publishing-receipt");
    return collected;
  }

  if (spec.id === "run-detail") {
    for (const { run, phase } of runDetailCases) {
      const runId = run.publicRunId;
      if (runId !== stableRunId) {
        await page.goto(`${baseUrl}/runs/${runId}`, {
          waitUntil: "domcontentloaded",
        });
      }
      await page
        .getByRole("heading", {
          name: run.title,
          exact: true,
        })
        .waitFor();
      if (run.platform === null) {
        await page
          .getByText("发布平台", { exact: true })
          .locator("..")
          .getByText("未记录", { exact: true })
          .waitFor();
      } else {
        await page
          .locator("[data-platform-identity]:visible")
          .first()
          .waitFor({ state: "visible" });
      }
      collected.push(...(await collectIdentities(page, phase)));
    }
    return collected;
  }

  await collect(spec.id);
  return collected;
}

async function assertAllMatchesVisible(
  page: Page,
  selector: string,
  context: string,
): Promise<boolean> {
  const locator = page.locator(selector);
  const matchCount = await locator.count();
  assert(matchCount > 0, `${context} matched no elements through ${selector}`);
  const matches = await locator.all();
  const visibility = await Promise.all(
    matches.map((match) => match.isVisible()),
  );
  assert(
    visibility.every(Boolean),
    `${context} has a hidden match through ${selector}`,
  );
  return true;
}

async function inspectCase(
  browser: Browser,
  baseUrl: string,
  outputRoot: string,
  spec: RouteSpec,
  viewport: (typeof viewports)[number],
): Promise<CaseResult> {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  const apiRequests: string[] = [];
  const requests: string[] = [];
  const apiResponseChecks: Array<Promise<ApiResponseEvidence>> = [];
  const unexpectedApiRequests: string[] = [];
  const unexpectedNetworkRequests: string[] = [];
  const failedRequests: string[] = [];
  const httpFailures: string[] = [];
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];

  page.on("request", (request) => {
    requests.push(`${request.method()} ${request.url()}`);
    const url = new URL(request.url());
    if (
      url.origin !== new URL(baseUrl).origin ||
      (url.pathname !== mediaBase && !url.pathname.startsWith(`${mediaBase}/`))
    ) {
      unexpectedNetworkRequests.push(`${request.method()} ${request.url()}`);
    }
  });
  page.on("requestfailed", (request) => {
    failedRequests.push(
      `${request.method()} ${request.url()} ${request.failure()?.errorText ?? "failed"}`,
    );
  });
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("response", (response) => {
    if (response.status() >= 400)
      httpFailures.push(`${response.status()} ${response.url()}`);
    const url = new URL(response.url());
    if (!url.pathname.startsWith(`${apiRoot}/`)) return;
    apiResponseChecks.push(
      (async () => {
        const contentTypeHeader = response.headers()["content-type"] ?? "";
        let text = "";
        let jsonParsed = false;
        try {
          text = await response.text();
          JSON.parse(text);
          jsonParsed = true;
        } catch {
          jsonParsed = false;
        }
        return {
          method: response.request().method(),
          path: `${url.pathname.slice(apiRoot.length)}${url.search}`,
          status: response.status(),
          contentType: contentTypeHeader,
          jsonParsed,
          htmlShell:
            /text\/html/i.test(contentTypeHeader) ||
            /^\s*(?:<!doctype\s+html|<html)/i.test(text),
          bodyStart: text.trimStart().slice(0, 120),
        };
      })(),
    );
  });

  await page.route(`**${apiRoot}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.slice(apiRoot.length) || "/";
    const requestLabel = `${request.method()} ${path}${url.search}`;
    apiRequests.push(requestLabel);
    const operationId = operationIdFor(request.method(), path);
    if (!operationId) {
      unexpectedApiRequests.push(requestLabel);
      await fulfillJson(route, 501, {
        error: {
          code: "undeclared_d2_operation",
          message: requestLabel,
          field: null,
        },
      });
      return;
    }
    try {
      await fulfillJson(route, 200, fixtureFor(spec, operationId, path));
    } catch (error) {
      unexpectedApiRequests.push(
        `${requestLabel}: ${error instanceof Error ? error.message : String(error)}`,
      );
      await fulfillJson(route, 501, {
        error: {
          code: "unhandled_d2_fixture",
          message: requestLabel,
          field: null,
        },
      });
    }
  });

  try {
    await page.goto(`${baseUrl}${spec.path}`, {
      waitUntil: "domcontentloaded",
    });
    const identities = await collectRoutePhases(page, spec, baseUrl);
    await page.waitForLoadState("networkidle");
    const pageGeometry = await evaluateBrowserExpression<{
      documentOverflow: number;
      bodyOverflow: number;
    }>(
      page,
      String.raw`(() => ({
        documentOverflow: Math.max(
          0,
          document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        ),
        bodyOverflow: Math.max(
          0,
          document.body.scrollWidth - document.body.clientWidth,
        ),
      }))()`,
    );
    const screenshotName = `${spec.id}-${viewport.name}.png`;
    const screenshotPath = join(outputRoot, screenshotName);
    const screenshotBytes = await page.screenshot({
      path: screenshotPath,
      fullPage: true,
    });
    const apiResponses = await Promise.all(apiResponseChecks);
    const observedKeys = Array.from(
      new Set(
        identities
          .map((identity) => identity.key)
          .filter((key): key is string => Boolean(key)),
      ),
    );
    return {
      routeId: spec.id,
      role: spec.role,
      route: `${mediaBase}${spec.path}`,
      viewport: viewport.name,
      identities,
      observedKeys,
      ...pageGeometry,
      emptyEvidenceMatched: spec.emptyEvidenceLocator
        ? await assertAllMatchesVisible(
            page,
            spec.emptyEvidenceLocator,
            `${spec.id}/${viewport.name}`,
          )
        : null,
      apiRequests,
      apiResponses,
      unexpectedApiRequests,
      unexpectedNetworkRequests,
      failedRequests,
      httpFailures,
      consoleErrors,
      pageErrors,
      screenshot: screenshotName,
      screenshotSha256: sha256(screenshotBytes),
      requests,
    };
  } finally {
    await context.close();
  }
}

function verifyCase(spec: RouteSpec, result: CaseResult): void {
  assert(
    result.identities.length > 0,
    `${spec.id}/${result.viewport} rendered no platform identities`,
  );
  for (const expectedKey of spec.expectedKeys) {
    assert(
      result.observedKeys.includes(expectedKey),
      `${spec.id}/${result.viewport} did not render ${expectedKey}: ${result.observedKeys.join(", ")}`,
    );
  }
  if (spec.emptyEvidenceLocator) {
    assert.equal(
      result.emptyEvidenceMatched,
      true,
      `${spec.id}/${result.viewport} did not render empty-value evidence through ${spec.emptyEvidenceLocator}`,
    );
  }
  for (const identity of result.identities) {
    assert(
      identity.key,
      `${spec.id}/${result.viewport}/${identity.phase} has no platform key`,
    );
    assert(
      identity.label,
      `${spec.id}/${result.viewport}/${identity.phase} has no platform label`,
    );
    assert(
      identity.source,
      `${spec.id}/${result.viewport}/${identity.phase} has no icon source`,
    );
    const definition = PLATFORM_REGISTRY[identity.key as PlatformKey];
    assert(
      definition,
      `${spec.id}/${result.viewport}/${identity.phase} used an unregistered platform key ${identity.key}`,
    );
    assert.equal(
      identity.label,
      definition.label,
      `${spec.id}/${result.viewport}/${identity.phase} label diverged from the registry`,
    );
    assert.equal(
      identity.source,
      definition.iconSource.exportName,
      `${spec.id}/${result.viewport}/${identity.phase} icon source diverged from the registry`,
    );
    assert(
      identity.iconBeforeLabel,
      `${spec.id}/${result.viewport}/${identity.phase} icon is not the first child`,
    );
    assert(
      identity.iconVisuallyBeforeLabel,
      `${spec.id}/${result.viewport}/${identity.phase} icon is not visually before the label`,
    );
    assert(
      Math.abs(identity.iconWidth - 20) <= 0.5,
      `${spec.id}/${result.viewport} icon width changed: ${identity.iconWidth}`,
    );
    assert(
      Math.abs(identity.iconHeight - 20) <= 0.5,
      `${spec.id}/${result.viewport} icon height changed: ${identity.iconHeight}`,
    );
    assert(
      identity.svgShapeCount > 0,
      `${spec.id}/${result.viewport} SVG has no shape nodes`,
    );
    assert(
      identity.svgContentLength > 0,
      `${spec.id}/${result.viewport} SVG shape data is empty`,
    );
    assert(
      identity.paintedPixelCount > 0,
      `${spec.id}/${result.viewport} SVG canvas pixels are blank`,
    );
    assert(
      identity.overlapArea <= 0.5,
      `${spec.id}/${result.viewport} icon overlaps label`,
    );
    assert(
      identity.iconClipArea <= 0.5,
      `${spec.id}/${result.viewport} icon is clipped`,
    );
    assert(
      identity.labelClipArea <= 0.5,
      `${spec.id}/${result.viewport} label is clipped`,
    );
  }
  assert(
    result.documentOverflow <= 1,
    `${spec.id}/${result.viewport} document overflow is ${result.documentOverflow}px`,
  );
  assert(
    result.bodyOverflow <= 1,
    `${spec.id}/${result.viewport} body overflow is ${result.bodyOverflow}px`,
  );
  assert.equal(
    result.unexpectedApiRequests.length,
    0,
    `${spec.id}/${result.viewport} made unexpected API requests`,
  );
  assert.equal(
    result.unexpectedNetworkRequests.length,
    0,
    `${spec.id}/${result.viewport} used a non-candidate network source`,
  );
  assert.equal(
    result.failedRequests.length,
    0,
    `${spec.id}/${result.viewport} has failed requests`,
  );
  assert.equal(
    result.httpFailures.length,
    0,
    `${spec.id}/${result.viewport} has HTTP failures`,
  );
  assert.equal(
    result.consoleErrors.length,
    0,
    `${spec.id}/${result.viewport} has console errors`,
  );
  assert.equal(
    result.pageErrors.length,
    0,
    `${spec.id}/${result.viewport} has page errors`,
  );
  assert(
    result.apiResponses.length > 0,
    `${spec.id}/${result.viewport} recorded no API responses`,
  );
  for (const response of result.apiResponses) {
    assert(
      response.status >= 200 && response.status < 300,
      `${spec.id} API ${response.path} returned ${response.status}`,
    );
    assert.match(
      response.contentType,
      /application\/json/i,
      `${spec.id} API ${response.path} is not JSON`,
    );
    assert(
      response.jsonParsed,
      `${spec.id} API ${response.path} body is not parseable JSON`,
    );
    assert.equal(
      response.htmlShell,
      false,
      `${spec.id} API ${response.path} returned an HTML shell`,
    );
  }
}

function evidenceManifest(root: string): string {
  const files: string[] = [];
  const visit = (directory: string) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) visit(path);
      else if (entry.isFile() && entry.name !== "hashes.sha256")
        files.push(path);
    }
  };
  visit(root);
  return (
    files
      .sort((left, right) => left.localeCompare(right))
      .map(
        (file) =>
          `${sha256(readFileSync(file))}  ${normalizedPath(relative(root, file))}`,
      )
      .join("\n") + "\n"
  );
}

const {
  manifest: d1Manifest,
  candidateRoot,
  snapshot: candidateBefore,
} = readCandidateManifest();
const candidateManifestBeforeBytes = readFileSync(candidateManifestPath);
assert(candidateBefore.records.length > 0, "D1 candidate is empty");
assert.equal(
  candidateBefore.records.some((record) =>
    record.path.startsWith("platform-icons/"),
  ),
  false,
  "D1 candidate still contains the retired platform-icons directory",
);
const defaultOutputRoot = join(
  projectRoot,
  "agents-results/2026-08-09/media-platform-brand-icon-registry-ssot/evidence/platform-icons/D2",
  candidateBefore.sha256,
);
const outputRoot = resolve(
  process.env.MEDIA_PLATFORM_ICONS_QA_OUTPUT ?? defaultOutputRoot,
);
assert.equal(
  existsSync(outputRoot),
  false,
  `D2 evidence directory already exists: ${outputRoot}`,
);
mkdirSync(outputRoot, { recursive: true });
writeFileSync(
  join(outputRoot, "candidate-manifest.sha256"),
  candidateBefore.manifestText,
);

let browser: Browser | null = null;
let server: Server | null = null;
const results: CaseResult[] = [];
try {
  const candidateServer = await startCandidateServer();
  server = candidateServer.server;
  browser = await chromium.launch({ headless: true });
  for (const spec of routeSpecs) {
    for (const viewport of viewports) {
      const result = await inspectCase(
        browser,
        candidateServer.baseUrl,
        outputRoot,
        spec,
        viewport,
      );
      results.push(result);
      verifyCase(spec, result);
    }
  }

  const adminResults = results.filter(
    (result) => result.routeId === "admin-access",
  );
  for (const result of adminResults) {
    const panelKeys = result.identities.map((identity) => identity.key);
    assert.deepEqual(
      panelKeys,
      ["xiaohongshu", "douyin"],
      `Admin platform order changed in ${result.viewport}`,
    );
  }
  const ordinaryKeys = new Set(
    results
      .filter((result) => result.role === "ordinary")
      .flatMap((result) => result.observedKeys),
  );
  for (const key of [
    "douyin",
    "xiaohongshu",
    "kuaishou",
    "bilibili",
    "wechat",
    "weibo",
    "zhihu",
    "web",
    "unknown",
  ]) {
    assert(ordinaryKeys.has(key), `D2 ordinary matrix did not cover ${key}`);
  }

  const candidateAfter = candidateManifest(candidateRoot);
  assert.equal(
    candidateAfter.sha256,
    candidateBefore.sha256,
    "D1 candidate changed during D2",
  );
  assert.deepEqual(
    candidateAfter.records,
    candidateBefore.records,
    "D1 candidate manifest changed during D2",
  );
  assert.deepEqual(
    readFileSync(candidateManifestPath),
    candidateManifestBeforeBytes,
    "D1 candidate-manifest.json changed during D2",
  );
  const report = {
    node: "D2",
    versionTuple,
    ssot: { path: ssotPath, sha256: ssotSha256 },
    candidateManifest: {
      path: candidateManifestPath,
      sha256: sha256(readFileSync(candidateManifestPath)),
      filesSha256: d1Manifest.filesSha256,
    },
    candidate: {
      root: candidateRoot,
      manifestSha256: candidateBefore.sha256,
      fileCount: candidateBefore.records.length,
      unchangedAfterRun: true,
    },
    matrix: {
      routeCount: routeSpecs.length,
      viewportCount: viewports.length,
      caseCount: results.length,
      ordinaryKeys: Array.from(ordinaryKeys).sort(),
      adminKeys: ["xiaohongshu", "douyin"],
    },
    results,
  };
  writeFileSync(
    join(outputRoot, "report.json"),
    JSON.stringify(report, null, 2) + "\n",
  );
  writeFileSync(
    join(outputRoot, "hashes.sha256"),
    evidenceManifest(outputRoot),
  );
  console.log(
    `media platform brand icons: PASS (${results.length} cases, candidate ${candidateBefore.sha256})`,
  );
} catch (error) {
  writeFileSync(
    join(outputRoot, "failure.json"),
    JSON.stringify(
      {
        node: "D2",
        versionTuple,
        ssot: { path: ssotPath, sha256: ssotSha256 },
        candidateManifest: candidateManifestPath,
        candidateManifestSha256: sha256(candidateManifestBeforeBytes),
        completedCases: results,
        error:
          error instanceof Error
            ? {
                name: error.name,
                message: error.message,
                stack: error.stack ?? null,
              }
            : { message: String(error) },
      },
      null,
      2,
    ) + "\n",
  );
  throw error;
} finally {
  if (browser) await browser.close();
  if (server) await closeServer(server);
}
