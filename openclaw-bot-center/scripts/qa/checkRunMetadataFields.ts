import fs from "node:fs";
import path from "node:path";

const file = path.resolve(import.meta.dirname, "../../src/media/pages/ordinary/RunsPage.tsx");
const source = fs.readFileSync(file, "utf8");

for (const field of ["platform", "contentType", "trackName"]) {
  const declaration = `readonly ${field}: string | null;`;
  if (!source.includes(declaration)) {
    throw new Error(`RunSummary is missing ${field}`);
  }
  if (source.split(declaration).length !== 2) {
    throw new Error(`RunSummary must declare ${field} exactly once`);
  }
  if (source.includes(`readonly ${field}?:`)) {
    throw new Error(`RunSummary must not retain optional ${field}`);
  }
}
for (const label of ["发布平台", "内容形态", "内容赛道"]) {
  if (!source.includes(`["${label}",`)) throw new Error(`run facts are missing ${label}`);
}
if (!source.includes("<h2>{run.title}</h2>")) {
  throw new Error("run inspector must render the canonical topic title");
}
if (/split\([^)]*\/[^)]*\)/.test(source)) {
  throw new Error("runtime title parsing is forbidden; use structured API fields");
}

console.log("qa:run-metadata-fields: PASS");
