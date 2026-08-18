import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const source = readFileSync(
  resolve(root, "src/media/pages/ordinary/OverviewPage.tsx"),
  "utf8",
);

const failures: string[] = [];

function requireContract(condition: boolean, message: string): void {
  if (!condition) failures.push(message);
}

for (const operation of [
  "getDashboard",
  "listContentProjects",
  "listProjectArtifacts",
  "createProjectSummary",
  "listMediaCapabilities",
  "listMediaTasks",
]) {
  requireContract(
    source.includes(`\"${operation}\"`),
    `B01 is missing the frozen ${operation} operation`,
  );
}

requireContract(
  !source.includes('"confirmMediaTask"') &&
    source.includes("查看影响并确认") &&
    source.includes("重新生成删除预览") &&
    source.includes("取消删除"),
  "B01 must route confirmations to task review instead of approving inline",
);

requireContract(
  !source.includes('to: "/media-agent"') && !source.includes('to: "/archives"'),
  "B01 must not link to excluded W1 pages",
);
requireContract(
  !source.includes("Record<string, unknown>"),
  "B01 must not read business payloads through Record<string, unknown>",
);
requireContract(
  source.includes('status: "ready"; data: T') &&
    source.includes('status: "timeout"; message: string') &&
    source.includes('status: "error"; message: string'),
  "B01 load state must keep success, timeout, and failure distinct",
);
requireContract(
  source.includes("isEmptyDashboard(state.data.summary)") &&
    source.includes('state.status !== "ready"'),
  "B01 empty data and failed requests must render through different branches",
);
requireContract(
  source.includes("未使用默认值") && source.includes("displayNumber(value)"),
  "B01 must disclose request failure instead of presenting fallback zeroes",
);
requireContract(
  source.includes('data-page-layout="persistent-rail"') &&
    source.includes("OverviewPage.module.css"),
  "B01 must retain the responsive persistent-rail page contract",
);

if (failures.length > 0) {
  throw new Error(`B01 overview contract failed:\n${failures.join("\n")}`);
}

if (process.env.B01_OVERVIEW_CONTRACT_SELF_TEST === "1") {
  const invalid = source.replaceAll('status: "error"; message: string', 'status: "ready"; data: T');
  if (
    invalid.includes('status: "ready"; data: T') &&
    invalid.includes('status: "timeout"; message: string') &&
    invalid.includes('status: "error"; message: string')
  ) {
    throw new Error("B01 overview contract negative fixture was not detected");
  }
  console.log("B01 overview contract negative fixture passed.");
}

console.log("B01 overview contract checks passed.");
