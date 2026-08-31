import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const page = readFileSync(resolve("src/media/pages/ordinary/ReviewsPage.tsx"), "utf8");
const styles = readFileSync(resolve("src/media/pages/ordinary/ReviewsPage.module.css"), "utf8");

assert.match(page, /items:\s*mergeItems\(current\.reviews\.data\.items, value\.items\)/);
assert.match(page, /items:\s*mergeItems\(current\.content\.data\.items, value\.items\)/);
assert.match(page, /items:\s*mergeItems\(current\.account\.data\.items, value\.items\)/);

for (const tab of ["reviews", "content", "account", "growth"]) {
  assert.ok(page.includes(`id={tab.id + "-tab"}`) || page.includes(`aria-labelledby="${tab}-tab"`));
  assert.ok(page.includes(`aria-controls={tab.id + "-tabpanel"}`));
}
assert.match(page, /id="reviews-tabpanel"[^>]*aria-labelledby="reviews-tab"/);
assert.match(page, /id=\{id\}[^>]*aria-labelledby=\{id\.replace\("-tabpanel", "-tab"\)\}/);
assert.match(page, /id="growth-tabpanel"[^>]*aria-labelledby="growth-tab"/);

assert.match(page, /const dialogRef = useRef<HTMLElement>\(null\)/);
assert.match(page, /event\.key === "Escape" && !busyRef\.current/);
assert.match(page, /event\.key === "Tab"/);
assert.match(page, /document\.activeElement === first/);
assert.match(page, /document\.activeElement === last/);
assert.match(page, /previousFocus\?\.focus\(\)/);

const layerPanel = page.match(/function LayerPanel[\s\S]*?\n}\n\nfunction MetricTable/)?.[0] ?? "";
assert.ok(layerPanel, "LayerPanel must remain a dedicated inspector section");
assert.doesNotMatch(layerPanel, /mg-panel/);
assert.match(styles, /\.layerPanel\s*\{[^}]*padding:\s*0\.25rem 0;[^}]*\}/s);
assert.doesNotMatch(styles, /\.loginLink\b/);
assert.doesNotMatch(styles, /\.qualityBadge\b/);
assert.doesNotMatch(styles, /\.sessionState\b|\.resourceState\b|\.emptyState\b/);
assert.match(styles, /\.tabContent > \.panel > :global\(\.mg-state\)/);

console.log("reviews page interaction contract passed");
