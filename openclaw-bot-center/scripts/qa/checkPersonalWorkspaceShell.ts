import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "../..");
const personal = readFileSync(path.join(root, "src/media/PersonalWorkspaceShellPage.tsx"), "utf8");
const workspace = readFileSync(path.join(root, "src/media/WorkspaceShellPage.tsx"), "utf8");
const app = readFileSync(path.join(root, "src/media/MediaApp.tsx"), "utf8");
const styles = readFileSync(path.join(root, "src/media/media.css"), "utf8");

function requireText(source: string, token: string, message: string): void {
  assert.ok(source.includes(token), message);
}

requireText(personal, 'session?.workspaceMode === "personal_web"', "personal shell must consume the server workspace mode");
requireText(personal, 'session.bodyAuthority === "internal"', "personal shell must require internal body authority");
requireText(personal, 'callBusinessOperation<PersonalProjectResponse>("listContentProjects"', "personal shell must read server content projects");
requireText(personal, 'callBusinessOperation<PersonalArtifactResponse>("listProjectArtifacts"', "personal shell must read server project artifacts");
requireText(personal, 'callBusinessOperation<PersonalDocumentResponse>("getDocumentBody"', "personal shell must provide a cloud document preview read");
requireText(personal, 'to={`/workspace/preview/${artifact.publicArtifactId}`}', "personal artifacts must expose a cloud preview entry");
requireText(app, 'const isPersonal = session?.workspaceMode === \'personal_web\'', "MediaApp must branch on the server-resolved personal session");
requireText(app, 'path: \'/workspace\', label: \'个人云端成果\'', "personal navigation must be declared explicitly");
requireText(app, 'element={isPersonal ? <PersonalWorkspaceShellPage /> : <Navigate to="/workspace" replace />}', "preview routing must be personal-session guarded");
requireText(workspace, 'return <PersonalWorkspaceShellPage />', "shared workspace route must delegate personal sessions to the personal shell");
requireText(personal, 'className="topbar-command personal-task-status-command"', "personal shell must retain a read-only task-status affordance for the shared shell regression fixture");
requireText(personal, 'className="task-drawer personal-task-status-drawer"', "personal task status must use a read-only drawer surface");
requireText(personal, "尚未提交网页任务", "personal task status must not imply submitted work");

for (const forbidden of [
  "createProjectSummary",
  "createArtifactRevision",
  "createMediaTask",
  "uploadMediaFile",
  "saveDocumentDraft",
  "createDocumentExport",
  "larkDocumentUrl",
  "organizationDocumentUrl",
  "openWorkspace",
  "submitDraft",
]) {
  assert.equal(personal.includes(forbidden), false, `personal shell exposes forbidden write or organization token: ${forbidden}`);
}
assert.doesNotMatch(personal, /\b(?:AI\s+Writer|Writer)\b/iu, "personal shell must not expose a Writer action");
assert.doesNotMatch(personal, /Feishu|飞书|localStorage|sessionStorage|tenantId/u, "personal shell must not use Feishu controls, browser storage, or tenant URL authority");

for (const status of ["loading", "empty", "missingEntitlement", "unauthorized", "notFound"]) {
  requireText(personal, `status: "${status}"`, `personal shell must model ${status} explicitly`);
}
requireText(personal, "重新读取", "personal shell must provide a refresh/retry action");
requireText(styles, ".personal-workspace-grid", "personal workspace layout styles are missing");
requireText(styles, ".personal-preview-link", "personal cloud preview link styles are missing");
requireText(styles, ".personal-state", "personal state styles are missing");
requireText(styles, ".personal-project-item:focus-visible", "personal project keyboard focus styles are missing");
requireText(styles, "@media (max-width: 700px)", "personal shell must retain mobile CSS coverage");

console.log("personal workspace shell QA passed");
