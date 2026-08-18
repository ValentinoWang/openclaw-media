import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { delimiter, dirname, resolve } from "node:path";

type RegistryCapability = {
  capabilityId: string;
  enabled: boolean;
  variants: Array<{ variantId: string }>;
  fields: Array<{ key: string }>;
};

const mediaApp = readFileSync("src/media/MediaApp.tsx", "utf8");
const mediaWorkspace = readFileSync("src/media/MediaWebWorkspace.tsx", "utf8");
const assets = readFileSync("src/media/pages/ordinary/AssetsPage.tsx", "utf8");
const tracks = readFileSync("src/media/pages/ordinary/TracksPage.tsx", "utf8");
const runs = readFileSync("src/media/pages/ordinary/RunsPage.tsx", "utf8");
const routedOrdinaryModules = [...mediaApp.matchAll(/from ['"]\.\/pages\/ordinary\/([^'"]+)['"]/g)]
  .map((match) => match[1]);
assert.ok(routedOrdinaryModules.length > 0, "MediaApp must declare routed ordinary-page modules");
for (const requiredModule of ["AssetsPage", "TracksPage", "RunsPage"]) {
  assert.ok(routedOrdinaryModules.includes(requiredModule), `${requiredModule} must remain in the routed-page scan scope`);
}
const ordinaryPages = routedOrdinaryModules
  .map((moduleName) => readFileSync(`src/media/pages/ordinary/${moduleName}.tsx`, "utf8"))
  .join("\n");

for (const obsoleteId of [
  "media-source-asset",
  "media-topic-decision",
  "deconstruction",
  "creation",
]) {
  const launchedAsCapability = new RegExp(
    `(?:capabilityId:\\s*|(?:onOpenCapability|openCapability)\\(\\s*)[\"']${obsoleteId}[\"']`,
  );
  assert.ok(
    !launchedAsCapability.test(ordinaryPages),
    `ordinary Media pages must not launch obsolete capability id ${obsoleteId}`,
  );
}

assert.match(assets, /\{ id: "(?:deconstruction|creation)", label:/, "ordinary tab ids are valid near misses, not capability launches");

const registryRoot = process.env.OPENCLAW_TAG_ROUTER_ROOT
  ?? resolve(process.cwd(), "../backend");
const registryCatalog = JSON.parse(execFileSync(
  "python3",
  [
    "-c",
    "import json; from openclaw_app.services.capability_registry import CAPABILITY_REGISTRY; print(json.dumps(CAPABILITY_REGISTRY.serialize()))",
  ],
  {
    cwd: registryRoot,
    encoding: "utf8",
    maxBuffer: 10 * 1024 * 1024,
    env: {
      ...process.env,
      PYTHONPATH: [dirname(registryRoot), registryRoot, process.env.PYTHONPATH]
        .filter(Boolean)
        .join(delimiter),
    },
  },
)) as { capabilities: RegistryCapability[] };

function assertCatalogContract(
  capabilityId: string,
  variantId: string,
  paramKeys: string[],
  expectedEnabled = true,
) {
  const capability = registryCatalog.capabilities.find((item) => item.capabilityId === capabilityId);
  assert.ok(capability, `contextual capability ${capabilityId} must exist in the backend registry`);
  assert.equal(capability.enabled, expectedEnabled, `${capabilityId} enabled state must match its contextual UI contract`);
  assert.ok(
    capability.variants.some((variant) => variant.variantId === variantId),
    `${capabilityId} must declare contextual variant ${variantId}`,
  );
  const fieldKeys = new Set(capability.fields.map((field) => field.key));
  for (const key of paramKeys) {
    assert.ok(fieldKeys.has(key), `${capabilityId} must declare contextual field ${key}`);
  }
}

for (const [capabilityId, variantId, paramKeys] of [
  ["source_asset_intake", "default", []],
  ["creation_decision_brief", "default", ["field_57060c88a36b"]],
  ["viral_deconstruction", "default", ["field_c29fd750ad50"]],
  ["selfmedia_creation", "default", ["source_asset_id"]],
  ["commercial_delivery_draft", "default", []],
  ["external_research_brief", "default", ["track"]],
  ["creator_profile_upsert", "url_candidate", []],
  ["universal_deletion", "preview", ["id"]],
] as const) {
  assertCatalogContract(capabilityId, variantId, [...paramKeys]);
}
assertCatalogContract(
  "account_track_strategy",
  "default",
  ["field_311bb313fdec", "platform", "track"],
  false,
);

assert.match(
  assets,
  /openCapability\(\{\s*capabilityId:\s*"source_asset_intake",\s*variantId:\s*"default"/s,
  "asset registration must launch the canonical source_asset_intake capability",
);
assert.match(
  assets,
  /disabled=\{!sourceUrl\}/,
  "deconstruction must not launch when the selected asset has no valid public URL",
);
assert.match(
  assets,
  /capabilityId:\s*"creation_decision_brief"[\s\S]*?field_57060c88a36b:\s*`基于素材/s,
  "topic generation must carry selected-asset context into the decision goal",
);
assert.match(
  assets,
  /capabilityId:\s*"viral_deconstruction"[\s\S]*?field_c29fd750ad50:\s*sourceUrl/s,
  "deconstruction must pass the selected asset's public evidence URL when available",
);
assert.match(
  assets,
  /capabilityId:\s*"selfmedia_creation"[\s\S]*?source_asset_id:\s*summary\.publicAssetId/s,
  "creation must pass the selected source asset id",
);

assert.match(
  runs,
  /activeView === "deliveries"[\s\S]*?commercial_delivery_draft[\s\S]*?:\s*\{\s*capabilityId:\s*"selfmedia_creation",\s*variantId:\s*"default"\s*\}/s,
  "the new creation action must preselect selfmedia_creation",
);
assert.ok(
  !/openWorkspace\(\{\s*capabilityId:\s*"commercial_delivery_draft"\s*\}\)/s.test(runs),
  "commercial delivery actions must not rely on first-variant fallback",
);

assert.match(
  mediaWorkspace,
  /pendingWorkspacePrefill\.current\s*=\s*prefill\s*\?\?\s*null/,
  "workspace requests made before catalog load must be retained",
);
assert.match(
  mediaWorkspace,
  /dispatch\(workspacePrefillAction\([\s\S]*?pendingWorkspacePrefill\.current[\s\S]*?pendingWorkspacePrefill\.current\s*=\s*undefined/s,
  "a retained workspace request must be applied and cleared after catalog load",
);

assert.ok(
  !/account_track_strategy|strategyCapabilityEnabled|生成账号策略|账号策略 ·/.test(tracks),
  "the owned-account ledger must not render strategy placeholders or launch actions",
);

console.log("contextual capability launch contract passed");
