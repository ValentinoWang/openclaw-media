import fs from "node:fs";
import path from "node:path";

const file = path.resolve(import.meta.dirname, "../../src/media/pages/ordinary/MediaAgentPage.tsx");
const source = fs.readFileSync(file, "utf8");
const tabBar = source.match(/<nav className=\{styles\.tabBar\}[\s\S]*?<\/nav>/)?.[0] ?? "";
const order = ["设备与客户端", "本地运行", "流程目录"];
if (!order.every((label, index) => tabBar.indexOf(label) >= 0 && (index === 0 || tabBar.indexOf(label) > tabBar.indexOf(order[index - 1])))) {
  throw new Error("Media Agent tabs must be ordered client/device, local run, pipeline catalog");
}
if (!source.includes('useState<Tab>("devices")')) throw new Error("Media Agent must open on the client/device tab");
console.log("qa:media-agent-tab-order: PASS");
