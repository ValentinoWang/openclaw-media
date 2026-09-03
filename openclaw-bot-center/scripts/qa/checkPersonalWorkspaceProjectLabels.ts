import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const page = readFileSync(resolve(root, "src/media/PersonalWorkspaceShellPage.tsx"), "utf8");
const projectListMarker = '<div className="personal-project-list" role="list" aria-label="个人云端项目">';
const artifactPanelMarker = '<section className="section-panel personal-artifact-panel';
const projectListStart = page.indexOf(projectListMarker);
const artifactPanelStart = page.indexOf(artifactPanelMarker);

assert.notEqual(projectListStart, -1, "personal project list rendering is missing");
assert.notEqual(artifactPanelStart, -1, "personal artifact panel boundary is missing");

const projectList = page.slice(projectListStart, artifactPanelStart);

assert.match(
  page,
  /import\s*\{\s*projectStageDisplayLabel,\s*projectStatusDisplayLabel\s*\}\s*from\s*"\.\/ui\/displayLabels";/,
  "personal workspace must import the project display-label helpers",
);
assert.match(
  projectList,
  /\{projectStageDisplayLabel\(project\.stage\)\}\s*·\s*\{projectStatusDisplayLabel\(project\.status\)\}/,
  "personal project metadata must render display-label helpers",
);
assert.doesNotMatch(
  projectList,
  /\{project\.stage\}\s*·\s*\{project\.status\}/,
  "personal project metadata must not render raw backend enums",
);

console.log("personal workspace project-label QA passed");
