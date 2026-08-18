import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const page = readFileSync(resolve(root, "src/media/pages/ordinary/AssetsPage.tsx"), "utf8");
const labels = readFileSync(resolve(root, "src/media/ui/ordinaryDataLabels.ts"), "utf8");
const css = readFileSync(resolve(root, "src/media/pages/ordinary/AssetsPage.module.css"), "utf8");
const workspace = readFileSync(resolve(root, "src/media/MediaWebWorkspace.tsx"), "utf8");
const workspacePrefill = readFileSync(resolve(root, "src/media/task-launch/workspacePrefill.ts"), "utf8");
const review = readFileSync(resolve(root, "src/media/task-launch/TaskReview.tsx"), "utf8");

const checks: Array<[string, boolean]> = [
  ["AssetSummary accepts thumbnail descriptor", /thumbnail: StringValueMap/.test(page)],
  ["AssetSummary exposes platform hashtags", /platformHashtags: string\[\]/.test(page) && !/\n\s*tags: string\[\]/.test(page)],
  ["cards render only non-empty platform hashtags", /asset\.platformHashtags\.length \?/.test(page) && /asset\.platformHashtags\.slice\(0, 2\)/.test(page) && !/asset\.tags/.test(page)],
  ["hashtag presentation is explicitly named", /平台话题标签/.test(page) && !/\["标签",/.test(page)],
  ["platform hashtags display with one leading hash", /function formatPlatformHashtag\(value: string\)/.test(page) && /normalized\.startsWith\("#"\) \? normalized : `#\$\{normalized\}`/.test(page) && /formatPlatformHashtag\(hashtag\)/.test(page) && /platformHashtags\.map\(formatPlatformHashtag\)/.test(page)],
  ["track values stay separate from platform hashtags", /\["赛道", summary\.trackNames/.test(page) && !/platformHashtags.*trackNames|trackNames.*platformHashtags/.test(page)],
  ["AssetSummary accepts nullable materialStatus", /materialStatus\?: string \| null/.test(page)],
  ["cards render thumbnail descriptor URL", /stringValue\(asset\.thumbnail\.url\)/.test(page) && /src=\{thumbnailUrl\}/.test(page)],
  ["cards have image error fallback", /onError=\{\(\) => setThumbnailFailed\(true\)\}/.test(page)],
  ["card fallback distinguishes missing and failed thumbnails", /缩略图暂不可用/.test(page) && /缩略图未提供/.test(page)],
  ["detail keeps previewDescriptor", /detail\.previewDescriptor\.url/.test(page)],
  ["material status has dedicated helper", /export function materialStatusDisplayLabel/.test(labels) && /materialStatusDisplayLabel/.test(page)],
  ["cards keep evidence quality separate from material status", /<span>\{qualityLabel\(asset\.qualityStatus\)\}<\/span>\s*<span>\{materialStatusLabel\(asset\.materialStatus\)\}<\/span>/.test(page)],
  ["media aliases include Chinese values", /图片: "图片"/.test(labels) && /视频: "视频"/.test(labels) && /链接: "链接"/.test(labels)],
  ["thumbnail CSS fills the stable media frame", /\.assetMedia img/.test(css) && /object-fit: cover/.test(css)],
  ["missing semantic fields are reported honestly", /<FieldNotRecorded key="tracks" \/>/.test(page) && /平台话题标签/.test(page) && !/<FieldNotRecorded key="tags" \/>/.test(page) && /未记录/.test(page) && !/字段未开放/.test(page)],
  ["asset deletion uses one user-intent label", />\s*删除素材\s*</.test(page) && !/>\s*【删除】\s*</.test(page)],
  ["deletion preparation sends only selected target IDs", /prepareDeletionIntent\(uniqueIds\)/.test(page) && !/variantId: "preview"/.test(page) && !/action: "预览删除"/.test(page)],
  ["the full deletion flow bypasses AI capability selection", /workspacePrefillAction\(catalog, prefill\)/.test(workspace) && /prefill\.capabilityId === 'universal_deletion' \? 'prefillReview' : 'prefill'/.test(workspacePrefill) && !/prefill\.capabilityId === 'universal_deletion'\s*&&\s*prefill\.variantId === 'preview'/s.test(workspacePrefill)],
  ["deletion review states that it is non-destructive", /生成删除预览/.test(review) && /不会删除素材或关联记录/.test(review)],
];

const failures = checks.filter(([, passed]) => !passed).map(([name]) => name);
if (failures.length) {
  console.error(`Assets presentation QA failed (${failures.length}/${checks.length})`);
  for (const failure of failures) console.error(`- ${failure}`);
  process.exitCode = 1;
} else {
  console.log(`Assets presentation QA passed (${checks.length}/${checks.length})`);
}
