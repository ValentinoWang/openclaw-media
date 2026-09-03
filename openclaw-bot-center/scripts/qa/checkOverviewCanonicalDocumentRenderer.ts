import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const workflowPath = resolve(root, "src/media/documentWorkflow.ts");
const rendererPath = resolve(root, "src/media/pages/ordinary/CanonicalDocumentRenderer.tsx");
const stylesPath = resolve(root, "src/media/pages/ordinary/CanonicalDocumentRenderer.module.css");
const overviewPath = resolve(root, "src/media/pages/ordinary/OverviewPage.tsx");

for (const path of [workflowPath, rendererPath, stylesPath, overviewPath]) {
  assert.ok(existsSync(path), `missing canonical renderer asset: ${path}`);
}

const workflow = readFileSync(workflowPath, "utf8");
const renderer = readFileSync(rendererPath, "utf8");
const styles = readFileSync(stylesPath, "utf8");
const overview = readFileSync(overviewPath, "utf8");

for (const token of ["DocumentLinkMark", "heading_9", "DocumentTableBlock", "DocumentDataSnapshotBlock", "DocumentAttachmentBlock"]) {
  assert.match(workflow, new RegExp(`\\b${token}\\b`), `document workflow omits ${token}`);
}

for (const token of [
  "renderInlineRuns",
  "mark.type === \"link\"",
  "title={mark.title ?? undefined}",
  "heading_9",
  "aria-level={9}",
  "data-language={block.attrs.language ?? undefined}",
  "<thead>",
  "headerRowCount",
  "renderList(child)",
  "publicResourceId",
  "contentChecksum",
  "documentResourceHref",
  "displayFields",
]) {
  assert.ok(renderer.includes(token), `canonical renderer omits ${token}`);
}

assert.match(
  renderer,
  /return <div data-block-id=\{block\.id\} data-block-type=\{block\.type\}[^>]*>[\s\S]*?\{renderDocumentBlock\(block\)\}<\/div>;/,
  "every canonical block must be enclosed by stable block metadata",
);
const resourceIdAttributes = renderer.match(/data-public-resource-id=\{block\.attrs\.publicResourceId\}/g) ?? [];
const resourceChecksumAttributes = renderer.match(/data-content-checksum=\{block\.attrs\.contentChecksum\}/g) ?? [];
assert.ok(resourceIdAttributes.length >= 4, "image and attachment elements must expose public resource IDs");
assert.ok(resourceChecksumAttributes.length >= 4, "image and attachment elements must expose content checksums");
assert.match(
  renderer,
  /\/openclaw\/media\/api\/document-resources\/\$\{encodeURIComponent\(value\)\}/,
  "opaque document resources must resolve through the authenticated same-origin resource endpoint",
);
assert.doesNotMatch(
  renderer,
  /<small>资源 \{block\.attrs\.publicResourceId\}/,
  "resource identifiers must remain machine-readable metadata, not visible copy",
);
assert.doesNotMatch(
  renderer,
  /<span>\{block\.attrs\.contentType\} · \{block\.attrs\.contentChecksum\}<\/span>/,
  "resource checksums must remain machine-readable metadata, not visible copy",
);

assert.match(styles, /white-space:\s*pre-wrap/, "renderer must preserve inline spaces and line breaks");
assert.match(overview, /CanonicalDocumentRenderer/, "Overview must use the canonical renderer");
assert.doesNotMatch(overview, /function DocumentBlockView/, "Overview must not retain the lossy local renderer");
// Organization (Lark) artifacts are now previewed in-app from the server-side
// `media_document.lark_read_mirrors` read mirror (see documents.py), so the client
// no longer gates the canonical preview behind `bodyAuthority === "internal"` the
// way an earlier design did. The authoritative, editable copy stays reachable only
// through the external "打开组织文档" link (see getOrganizationDocumentUrl); that
// read/write boundary is enforced server-side and is out of reach of this
// source-text check.

console.log("overview canonical document renderer: PASS");
