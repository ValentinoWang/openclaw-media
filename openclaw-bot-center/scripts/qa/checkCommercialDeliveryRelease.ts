import fs from "node:fs";
import path from "node:path";

const releaseRoot = path.resolve(process.env.MEDIA_RELEASE_ROOT ?? "dist-media");
const indexPath = path.join(releaseRoot, "index.html");

function requireRelease(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const index = fs.readFileSync(indexPath, "utf8");
const entryPath = index.match(/<script[^>]+src="\/openclaw\/media\/([^"]+\.js)"/u)?.[1];
requireRelease(entryPath, "Media release entry script is missing");
const entryFile = path.join(releaseRoot, entryPath);
requireRelease(fs.existsSync(entryFile), `Media release entry does not exist: ${entryPath}`);
const bundle = fs.readFileSync(entryFile, "utf8");

for (const marker of [
  "商单交付按任务时间展示",
  "当前还没有商单交付",
  "新建商单",
  "/tasks?limit=100",
  "commercial_delivery_draft",
]) {
  requireRelease(bundle.includes(marker), `Media release is missing commercial delivery marker: ${marker}`);
}

console.log(`commercial delivery release gate passed: ${entryPath}`);
