import fs from "node:fs";
import path from "node:path";

const projectRoot = path.resolve(import.meta.dirname, "../..");
const mediaRoot = path.join(projectRoot, "src/media");
const mediaAppSource = fs.readFileSync(path.join(mediaRoot, "MediaApp.tsx"), "utf8");
const mediaStyles = fs.readFileSync(path.join(mediaRoot, "media.css"), "utf8");

function requireContract(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

requireContract(
  mediaAppSource.includes("CircleHelp") &&
    mediaAppSource.includes('className="topbar-help"') &&
    mediaAppSource.includes('aria-label="使用帮助"'),
  "ordinary global toolbar must preserve the top-right help entry",
);
requireContract(
  mediaAppSource.includes("pageHelpGuide") &&
    mediaAppSource.includes('role="dialog"') &&
    mediaAppSource.includes('className="help-markdown"') &&
    mediaAppSource.includes("发布准备") &&
    mediaAppSource.includes("Media Agent") &&
    mediaAppSource.includes("用量与套餐"),
  "top-right help entry must render route-specific markdown-friendly guides",
);
requireContract(
  mediaAppSource.includes("<h2>适用条件</h2>") &&
    mediaAppSource.includes("确认目标 Mac 在线并且设备标识与实际机器一致") &&
    mediaAppSource.includes("任务完成后核对最终产物摘要"),
  "Media Agent guide must place applicability before the ordered operating steps",
);
requireContract(
  /\.topbar-help\s*\{[\s\S]*?flex:\s*0 0 48px;[\s\S]*?\}/.test(mediaStyles),
  "top-right help entry must keep a stable 48px icon-button width",
);

console.log("qa:media-topbar-help-contract: PASS");
