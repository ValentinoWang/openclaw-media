import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { request } from "playwright";

const origin = (process.env.MEDIA_QA_ORIGIN ?? "http://106.52.146.37").replace(/\/$/, "");
const storageState = process.env.MEDIA_QA_STORAGE_STATE;
if (!storageState) {
  throw new Error("MEDIA_QA_STORAGE_STATE must point to an authenticated Playwright storage-state file");
}
if (!existsSync(storageState)) {
  throw new Error(`MEDIA_QA_STORAGE_STATE does not exist: ${storageState}`);
}

const runId = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
const outputRoot = resolve(
  process.env.MEDIA_QA_OUTPUT ?? `/home/ubuntu/qa-evidence/media-api-audit-${runId}`,
);
mkdirSync(outputRoot, { recursive: true });

const context = await request.newContext({
  baseURL: origin,
  extraHTTPHeaders: { Accept: "application/json" },
  storageState,
});

type AuditResult = {
  wave: number;
  path: string;
  status: number;
  durationMs: number;
  contentType: string;
};

const results: AuditResult[] = [];
try {
  const projectsResponse = await context.get("/openclaw/media/api/content-projects?pageSize=20");
  if (!projectsResponse.ok()) {
    throw new Error(`project preflight failed: ${projectsResponse.status()}`);
  }
  const projects = (await projectsResponse.json()) as {
    items?: Array<{ publicProjectId?: unknown }>;
  };
  const projectId = projects.items?.[0]?.publicProjectId;
  if (typeof projectId !== "string" || !projectId) {
    throw new Error("project preflight returned no public project id");
  }

  const paths = [
    "/openclaw/media/api/session",
    "/openclaw/media/api/dashboard",
    "/openclaw/media/api/content-projects?pageSize=20",
    `/openclaw/media/api/content-projects/${encodeURIComponent(projectId)}/artifacts?pageSize=20`,
    "/openclaw/media/api/tracks?pageSize=20",
    "/openclaw/media/api/creators?pageSize=20",
    "/openclaw/media/api/assets?pageSize=30",
    "/openclaw/media/api/decisions?pageSize=20",
    "/openclaw/media/api/runs?pageSize=30&search=",
    "/openclaw/media/api/publishing/packages?pageSize=30",
    "/openclaw/media/api/reviews?pageSize=50",
    "/openclaw/media/api/billing/usage-summary",
  ] as const;

  for (let wave = 1; wave <= 20; wave += 1) {
    const waveResults = await Promise.all(
      paths.map(async (path): Promise<AuditResult> => {
        const startedAt = Date.now();
        const response = await context.get(path);
        const contentType = response.headers()["content-type"] ?? "";
        const result = {
          wave,
          path,
          status: response.status(),
          durationMs: Date.now() - startedAt,
          contentType,
        };
        if (!response.ok()) {
          throw new Error(`wave ${wave} ${path} failed: ${response.status()}`);
        }
        if (!contentType.includes("application/json")) {
          throw new Error(`wave ${wave} ${path} returned ${contentType || "no content type"}`);
        }
        await response.json();
        return result;
      }),
    );
    results.push(...waveResults);
  }
} finally {
  await context.dispose();
}

const report = {
  origin,
  runId,
  requests: results.length,
  failures: results.filter((result) => result.status < 200 || result.status >= 300).length,
  maxDurationMs: Math.max(...results.map((result) => result.durationMs)),
  results,
};
writeFileSync(resolve(outputRoot, "report.json"), JSON.stringify(report, null, 2) + "\n");
if (report.requests !== 240 || report.failures !== 0) {
  throw new Error(`API audit failed: ${JSON.stringify({ requests: report.requests, failures: report.failures })}`);
}
console.log(JSON.stringify({ outputRoot, requests: report.requests, failures: report.failures, maxDurationMs: report.maxDurationMs }, null, 2));
