import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "../..");
const page = fs.readFileSync(
  path.join(root, "src/media/pages/ordinary/OverviewPage.tsx"),
  "utf8",
);
const styles = fs.readFileSync(
  path.join(root, "src/media/pages/ordinary/OverviewPage.module.css"),
  "utf8",
);
const renderer = fs.readFileSync(
  path.join(root, "src/media/pages/ordinary/CanonicalDocumentRenderer.tsx"),
  "utf8",
);
const rendererStyles = fs.readFileSync(
  path.join(root, "src/media/pages/ordinary/CanonicalDocumentRenderer.module.css"),
  "utf8",
);

function requirePreview(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

requirePreview(
  page.includes('callBusinessOperation<DocumentBodyResponse>("getDocumentBody"'),
  "document preview must read the declared canonical document-body operation",
);
requirePreview(
  page.includes("onSelectArtifact={setSelectedArtifactId}"),
  "artifact selection must drive document-body retrieval",
);
requirePreview(
  page.includes('href={documentUrl}') && page.includes("打开组织文档"),
  "Feishu-backed documents must retain their organization-document entry point",
);
requirePreview(
  page.includes("selectedArtifact?.publicArtifactId ?? null") &&
    page.includes('onClick={() => onSelectArtifact(isSelected ? null : artifact.publicArtifactId)}'),
  "all listed artifacts, including Lark-authority artifacts with a canonical mirror, must be selectable for web body preview",
);
requirePreview(
  !/selectedArtifact\?\.bodyAuthority\s*===\s*["']internal["']/u.test(page) &&
    !/artifact\.bodyAuthority\s*===\s*["']internal["']/u.test(page),
  "web preview must not be gated by internal body authority",
);
requirePreview(
  page.includes("网页正文暂不可读取") &&
    page.includes("打开组织文档") &&
    page.includes("重新读取"),
  "unreadable document previews must provide a Chinese document empty state and retry action",
);
requirePreview(
  page.includes("onRetry={onRetry}") && page.includes("documentRetryToken"),
  "document preview retry must re-request only the selected document body",
);
requirePreview(
  page.includes('parsed.protocol !== "https:"') &&
    page.includes('parsed.hostname.endsWith(".feishu.cn")') &&
    page.includes('!["wiki", "docx", "doc", "docs"].includes(parts[0].toLowerCase())'),
  "organization-document links must remain constrained to HTTPS Feishu document URLs",
);
requirePreview(
  page.includes("CanonicalDocumentRenderer") &&
    renderer.includes("function DocumentBlockView") &&
    renderer.includes('case "table"') &&
    renderer.includes('case "bullet_list"') &&
    renderer.includes('case "todo_item"'),
  "canonical document blocks must render as typed web content",
);
requirePreview(
  !page.includes("dangerouslySetInnerHTML") && !renderer.includes("dangerouslySetInnerHTML"),
  "document preview must not inject document content as untrusted HTML",
);
requirePreview(
  /^\.documentPreview\s*\{/m.test(styles) &&
    /^\.documentBody\s*\{/m.test(rendererStyles) &&
    /^\.tableWrap\s*\{/m.test(rendererStyles),
  "document preview styles are incomplete",
);

console.log("organization document preview: PASS");
