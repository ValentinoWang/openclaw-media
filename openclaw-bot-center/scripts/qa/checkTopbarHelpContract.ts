import fs from "node:fs";
import path from "node:path";

const projectRoot = path.resolve(import.meta.dirname, "../..");
const mediaRoot = path.join(projectRoot, "src/media");
const mediaStudioSource = fs.readFileSync(path.join(mediaRoot, "MediaStudioApp.tsx"), "utf8");
const mediaStyles = fs.readFileSync(path.join(mediaRoot, "media.css"), "utf8");

function requireContract(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

requireContract(
  mediaStudioSource.includes('className="studio-topbar"') &&
    mediaStudioSource.includes('className="studio-topbar-actions"') &&
    mediaStudioSource.includes('className="topbar-command"') &&
    mediaStudioSource.includes('aria-label="新建任务"'),
  "MediaStudioApp must preserve the current topbar task entry",
);
requireContract(
  /\.topbar-command\s*\{/.test(mediaStyles) || /\.studio-command-button\s*\{/.test(mediaStyles),
  "current topbar command styles are missing",
);

console.log("qa:media-topbar-contract: PASS");
