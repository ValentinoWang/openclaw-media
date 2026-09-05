import fs from "node:fs";
import path from "node:path";
import ts from "typescript";
import { CANONICAL_PERSISTENT_RAIL_PAGES } from "./mediaPageStructureManifest";

const projectRoot = path.resolve(import.meta.dirname, "../..");
const mediaRoot = path.join(projectRoot, "src/media");
const pagesRoot = path.join(mediaRoot, "pages");
const mediaStyles = fs.readFileSync(path.join(mediaRoot, "media.css"), "utf8");

const canonicalRailPages = [...CANONICAL_PERSISTENT_RAIL_PAGES].sort();

function requireContract(
  condition: unknown,
  message: string,
): asserts condition {
  if (!condition) throw new Error(message);
}

function sourceFiles(root: string): string[] {
  return fs.readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const entryPath = path.join(root, entry.name);
    if (entry.isDirectory()) return sourceFiles(entryPath);
    return /\.(?:tsx|css)$/.test(entry.name) && !entry.name.includes(".before-")
      ? [entryPath]
      : [];
  });
}

function hasJsxAttribute(
  node: ts.JsxAttributes,
  name: string,
  value?: string,
): boolean {
  return node.properties.some((property) => {
    if (!ts.isJsxAttribute(property) || property.name.text !== name)
      return false;
    if (value === undefined) return true;
    return (
      property.initializer !== undefined &&
      ts.isStringLiteral(property.initializer) &&
      property.initializer.text === value
    );
  });
}

function validateRailStructure(file: string): number {
  const source = fs.readFileSync(file, "utf8");
  const tree = ts.createSourceFile(
    file,
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  let railCount = 0;
  let preludeCount = 0;
  let firstPreludePosition = Number.POSITIVE_INFINITY;
  let firstRailPosition = Number.POSITIVE_INFINITY;

  function renderedChildren(
    children: ts.NodeArray<ts.JsxChild>,
  ): Array<ts.JsxElement | ts.JsxSelfClosingElement> {
    const result: Array<ts.JsxElement | ts.JsxSelfClosingElement> = [];
    const collect = (node: ts.Node) => {
      if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) {
        result.push(node);
        return;
      }
      if (ts.isJsxExpression(node) && node.expression) collect(node.expression);
      else if (ts.isConditionalExpression(node)) {
        collect(node.whenTrue);
        collect(node.whenFalse);
      } else if (
        ts.isBinaryExpression(node) &&
        node.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken
      ) {
        collect(node.right);
      } else if (ts.isParenthesizedExpression(node)) collect(node.expression);
    };
    children.forEach(collect);
    return result;
  }

  function elementAttributes(
    node: ts.JsxElement | ts.JsxSelfClosingElement,
  ): ts.JsxAttributes {
    return ts.isJsxElement(node)
      ? node.openingElement.attributes
      : node.attributes;
  }

  function elementTag(node: ts.JsxElement | ts.JsxSelfClosingElement): string {
    const tag = ts.isJsxElement(node)
      ? node.openingElement.tagName
      : node.tagName;
    return tag.getText(tree);
  }

  function componentOwnsAttribute(
    componentName: string,
    attribute: string,
  ): boolean {
    let owns = false;
    const inspectComponent = (node: ts.Node) => {
      const namedFunction =
        ts.isFunctionDeclaration(node) && node.name?.text === componentName;
      const namedVariable =
        ts.isVariableDeclaration(node) &&
        ts.isIdentifier(node.name) &&
        node.name.text === componentName;
      if (namedFunction || namedVariable) {
        const inspectJsx = (candidate: ts.Node) => {
          if (
            (ts.isJsxElement(candidate) ||
              ts.isJsxSelfClosingElement(candidate)) &&
            hasJsxAttribute(elementAttributes(candidate), attribute)
          )
            owns = true;
          ts.forEachChild(candidate, inspectJsx);
        };
        inspectJsx(node);
      }
      if (!owns) ts.forEachChild(node, inspectComponent);
    };
    inspectComponent(tree);
    return owns;
  }

  function renderedChildOwnsAttribute(
    node: ts.JsxElement | ts.JsxSelfClosingElement,
    attribute: string,
  ): boolean {
    if (hasJsxAttribute(elementAttributes(node), attribute)) return true;
    const tag = elementTag(node);
    return /^[A-Z]/.test(tag) && componentOwnsAttribute(tag, attribute);
  }

  function visit(node: ts.Node) {
    if (
      ts.isJsxElement(node) &&
      hasJsxAttribute(
        node.openingElement.attributes,
        "data-page-layout",
        "persistent-rail",
      )
    ) {
      railCount += 1;
      const directChildGroups = node.children.map((child) =>
        renderedChildren(ts.factory.createNodeArray([child])),
      );
      const primaryChildren = directChildGroups.filter((group) =>
        group.some((child) =>
          renderedChildOwnsAttribute(child, "data-page-primary"),
        ),
      );
      const inspectorChildren = directChildGroups.filter((group) =>
        group.some((child) =>
          renderedChildOwnsAttribute(child, "data-page-inspector"),
        ),
      );
      requireContract(
        primaryChildren.length === 1,
        `${path.relative(projectRoot, file)}: rail requires a direct data-page-primary child`,
      );
      requireContract(
        inspectorChildren.length === 1,
        `${path.relative(projectRoot, file)}: rail requires a direct data-page-inspector child`,
      );
      firstRailPosition = Math.min(firstRailPosition, node.getStart(tree));
    }
    ts.forEachChild(node, visit);
  }

  function validatePreludePlacement(
    node: ts.Node,
    insideRail = false,
    insidePrimary = false,
  ) {
    let nextInsideRail = insideRail;
    let nextInsidePrimary = insidePrimary;
    if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) {
      const attributes = elementAttributes(node);
      nextInsideRail =
        insideRail ||
        hasJsxAttribute(attributes, "data-page-layout", "persistent-rail");
      nextInsidePrimary =
        insidePrimary || hasJsxAttribute(attributes, "data-page-primary");
      if (hasJsxAttribute(attributes, "data-page-prelude")) {
        preludeCount += 1;
        firstPreludePosition = Math.min(
          firstPreludePosition,
          node.getStart(tree),
        );
        requireContract(
          !insideRail,
          `${path.relative(projectRoot, file)}: data-page-prelude must not be inside persistent rail`,
        );
        requireContract(
          !insidePrimary,
          `${path.relative(projectRoot, file)}: data-page-prelude must not be inside data-page-primary`,
        );
      }
    }
    ts.forEachChild(node, (child) =>
      validatePreludePlacement(child, nextInsideRail, nextInsidePrimary),
    );
  }

  visit(tree);
  validatePreludePlacement(tree);
  requireContract(
    preludeCount >= 1,
    `${path.relative(projectRoot, file)}: canonical rail page requires data-page-prelude`,
  );
  requireContract(
    firstPreludePosition < firstRailPosition,
    `${path.relative(projectRoot, file)}: data-page-prelude must be declared before persistent rail`,
  );
  return railCount;
}

const files = sourceFiles(pagesRoot);
const backendLabelLeaks: string[] = [];
for (const file of files.filter((candidate) => candidate.endsWith(".tsx"))) {
  const source = fs.readFileSync(file, "utf8");
  const tree = ts.createSourceFile(
    file,
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const inspect = (node: ts.Node) => {
    const visibleText = ts.isJsxText(node)
      ? node.text
      : ts.isStringLiteralLike(node) && !ts.isLiteralTypeNode(node.parent)
        ? node.text
      : ts.isTemplateExpression(node)
        ? [node.head.text, ...node.templateSpans.map((span) => span.literal.text)].join(" ")
        : "";
    const trimmedText = visibleText.trim();
    const isBareImplementationToken = /^(?:revision|COM\d{2})$/i.test(trimmedText);
    let ancestor: ts.Node | undefined = node.parent;
    let directlyRendered = ts.isJsxText(node);
    while (ancestor && !directlyRendered && !ts.isFunctionLike(ancestor) && !ts.isSourceFile(ancestor)) {
      directlyRendered = ts.isJsxAttribute(ancestor) || ts.isJsxExpression(ancestor);
      ancestor = ancestor.parent;
    }
    const implementationLeak = directlyRendered && /\b(?:revision|COM\d{2}|mediaclaw-cny-\d+|status\s*=)/i.test(visibleText);
    const renderedEnumLeak = directlyRendered && /\b(?:personal_web|organization_lark|research_snapshot|asset_digest|decision_brief|creation_document|publishing_package|review_report|project_summary|not_applicable|open_organization_document|resolve_sync)\b/i.test(visibleText);
    if (!isBareImplementationToken && (implementationLeak || renderedEnumLeak)) {
      const line = tree.getLineAndCharacterOfPosition(node.getStart(tree)).line + 1;
      backendLabelLeaks.push(`${path.relative(projectRoot, file)}:${line}`);
    }
    ts.forEachChild(node, inspect);
  };
  inspect(tree);
}
requireContract(
  backendLabelLeaks.length === 0,
  `Media UI must not expose backend implementation labels: ${backendLabelLeaks.join(", ")}`,
);
const ordinaryOverviewSource = fs.readFileSync(
  path.join(pagesRoot, "ordinary/OverviewPage.tsx"),
  "utf8",
);
for (const requiredFormatter of [
  "projectStageDisplayLabel(project.stage)",
  "projectStatusDisplayLabel(project.status)",
  "workspaceModeDisplayLabel(project.workspaceMode)",
  "artifactTypeDisplayLabel(artifact.artifactType)",
  "bodyAuthorityDisplayLabel(artifact.bodyAuthority)",
  "syncStatusDisplayLabel(artifact.syncStatus)",
]) {
  requireContract(
    ordinaryOverviewSource.includes(requiredFormatter),
    `Overview business values must use display translations: ${requiredFormatter}`,
  );
}
requireContract(
  !ordinaryOverviewSource.includes("artifact.allowedActions") ||
    ordinaryOverviewSource.includes("artifact.allowedActions.map(actionDisplayLabel)"),
  "Overview allowed actions must use display translations when rendered",
);
for (const forbiddenRawRendering of [
  "{project.stage} · {project.status} · {project.workspaceMode}",
  "`${kind}: ${count}`",
  "{artifact.artifactType}",
  "{artifact.bodyAuthority}",
  "{artifact.syncStatus}",
  "artifact.allowedActions.join",
  "project.title} · {project.publicProjectId",
  "variant {task.variantId}",
]) {
  requireContract(
    !ordinaryOverviewSource.includes(forbiddenRawRendering),
    `Overview must not render raw business values: ${forbiddenRawRendering}`,
  );
}
const discoveredRailPages = files
  .filter(
    (file) =>
      file.endsWith(".tsx") &&
      fs
        .readFileSync(file, "utf8")
        .includes('data-page-layout="persistent-rail"'),
  )
  .map((file) => path.relative(pagesRoot, file))
  .sort();

requireContract(
  JSON.stringify(discoveredRailPages) === JSON.stringify(canonicalRailPages),
  `persistent rail page manifest drift:\nexpected=${canonicalRailPages.join(",")}\nactual=${discoveredRailPages.join(",")}`,
);

let railCount = 0;
for (const relative of canonicalRailPages)
  railCount += validateRailStructure(path.join(pagesRoot, relative));
requireContract(
  railCount === canonicalRailPages.length,
  `each canonical page must own exactly one rail: pages=${canonicalRailPages.length} rails=${railCount}`,
);

requireContract(
  /\.fidelity-page:has\(> \[data-page-prelude\]\) \{[\s\S]*?display: flex;[\s\S]*?height: var\(--mg-rail-shell-height, calc\(100dvh - var\(--mg-shell-topbar, 86px\) - var\(--mg-shell-content-inset, 46px\)\)\);[\s\S]*?flex-direction: column;[\s\S]*?\}/.test(
    mediaStyles,
  ),
  "pages with a prelude must use the canonical viewport-bound column layout",
);
requireContract(
  /\.fidelity-page:has\(> \[data-page-prelude\]\) > \[data-page-layout="persistent-rail"\] \{[\s\S]*?height: auto !important;[\s\S]*?flex: var\(--mg-rail-grow, 1 1 auto\);[\s\S]*?\}/.test(
    mediaStyles,
  ),
  "desktop rail must consume the space remaining after the prelude",
);
requireContract(
  /\[data-page-primary\]:has\(> :only-child\) \{[\s\S]*?grid-template-rows: minmax\(0, 1fr\);[\s\S]*?\}/.test(
    mediaStyles,
  ) &&
    /\[data-page-primary\] > :only-child \{[\s\S]*?height: var\(--mg-rail-fill, 100%\);[\s\S]*?\}/.test(
      mediaStyles,
    ),
  "a single primary work surface must fill its paired rail without phantom grid tracks",
);
// --mg-rail-align 是**高度**释放令牌。主栏一旦带 data-primary-flow 就是
// flex-direction: column，那里 align-self 管的是宽度——同一个 start 读进去，面板会从
// 整列宽收成内容宽（/admin/upstreams 曾在 750px 的列里只占 313px）。两条规则必须成对
// 存在，否则每个页面又会各自长出一套 (0,2,2) 的 workaround 去压它。
requireContract(
  /\[data-page-primary\]\[data-primary-flow\] > :only-child \{[^}]*align-self: stretch;[^}]*\}/.test(
    mediaStyles,
  ),
  "a flex-column primary must pin its only child's cross axis to stretch — --mg-rail-align releases height, and in a column flow align-self governs width instead",
);
requireContract(
  /\[data-page-primary\]\[data-primary-flow\] \{[\s\S]*?display: flex;[\s\S]*?flex-direction: column;[\s\S]*?\}/.test(
    mediaStyles,
  ) &&
    /\[data-page-primary\]\[data-primary-flow\] > \[data-page-terminal-surface="primary"\] \{[\s\S]*?flex: var\(--mg-rail-grow, 0 1 auto\);[\s\S]*?min-height: 0;[\s\S]*?\}/.test(
      mediaStyles,
    ),
  "a marked primary flow must let its terminal surface shrink into the remaining rail height without being stretched to fill it",
);
const tracksSource = fs.readFileSync(
  path.join(pagesRoot, "ordinary/TracksPage.tsx"),
  "utf8",
);
const workspaceSource = fs.readFileSync(
  path.join(mediaRoot, "MediaWebWorkspace.tsx"),
  "utf8",
);
const mediaStudioSource = fs.readFileSync(
  path.join(mediaRoot, "MediaStudioApp.tsx"),
  "utf8",
);
const runDetailSource = fs.readFileSync(
  path.join(mediaRoot, "CreationRunDetailPage.tsx"),
  "utf8",
);
const runDetailStylesPath = path.join(
  mediaRoot,
  "CreationRunDetailPage.module.css",
);
requireContract(
  fs.existsSync(runDetailStylesPath),
  "run detail must own a scoped design-system layout module",
);
const runDetailStyles = fs.readFileSync(runDetailStylesPath, "utf8");
requireContract(
  runDetailSource.includes('data-page-prelude') &&
    runDetailSource.includes('data-run-detail-layout="compact"'),
  "run detail must use the canonical page prelude and compact detail layout",
);
requireContract(
  !runDetailSource.includes("<StructuredValue") &&
    !runDetailSource.includes('className="detail-surface"') &&
    !runDetailSource.includes('className="run-summary-grid"'),
  "run detail must not render sparse metadata through the legacy generic table surface",
);
requireContract(
  /\.contentGrid\s*\{[\s\S]*?display:\s*grid;[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1fr\)\s+minmax\(280px,\s*360px\)/.test(
    runDetailStyles,
  ),
  "run detail desktop layout must use a bounded content and metadata grid",
);
requireContract(
  !/min-height:\s*(?:[4-9]\d\d|\d{4,})px/.test(runDetailStyles),
  "run detail must not create fixed tall empty surfaces",
);
requireContract(
  /@media\s*\(max-width:\s*760px\)\s*\{[\s\S]*?\.contentGrid\s*\{[\s\S]*?grid-template-columns:\s*1fr/.test(
    runDetailStyles,
  ),
  "run detail must stack its content grid on mobile",
);
requireContract(
  /@media\s*\(max-width:\s*760px\)\s*\{[\s\S]*?\.page\s*\{[\s\S]*?height:\s*auto\s*!important;[\s\S]*?flex:\s*0\s+0\s+auto;/.test(
    runDetailStyles,
  ),
  "run detail must release the viewport-bound prelude height on mobile",
);
const reviewsStyles = fs.readFileSync(
  path.join(pagesRoot, "ordinary/ReviewsPage.module.css"),
  "utf8",
);
requireContract(
  /\.tabContent \{[^}]*display:\s*flex;[^}]*flex:\s*1 1 auto;[^}]*min-height:\s*0;[^}]*\}/.test(
    reviewsStyles,
  ) &&
    /\.tabContent > \.panel \{[^}]*display:\s*flex;[^}]*min-height:\s*0;[^}]*flex:\s*1 1 auto;[^}]*flex-direction:\s*column;[^}]*\}/.test(
      reviewsStyles,
    ),
  "reviews tab panel must fill the remaining primary-column height",
);
requireContract(
  /const openWorkspace = useCallback\([\s\S]*?setDrawerOpen\(true\)/.test(
    workspaceSource,
  ),
  "task launch entry points must open the contextual side workspace",
);
requireContract(
  !mediaStudioSource.includes('path="/task-workspace"') &&
    /\.task-drawer \{[^}]*width:\s*min\(500px,\s*100%\)/.test(mediaStyles) &&
    workspaceSource.includes("<TaskWorkspaceDrawer />"),
  "task workspace must remain a contextual 500px drawer without a fullscreen route",
);
requireContract(
  /\.required-field-group \.dynamic-fields \{[^}]*grid-template-columns:\s*repeat\(auto-fit,\s*minmax\(190px,\s*1fr\)/.test(
    mediaStyles,
  ),
  "capability-driven required fields must use an adaptive horizontal field row",
);
requireContract(
  tracksSource.includes("data-page-primary data-primary-flow") &&
    tracksSource.includes('data-page-terminal-surface="primary"'),
  "tracks must participate in the shared primary-flow terminal-height contract",
);
requireContract(
  /\[data-page-layout="persistent-rail"\] \{[\s\S]*?align-items: stretch;[\s\S]*?padding-bottom: 0;[\s\S]*?\}/.test(
    mediaStyles,
  ),
  "desktop rail must stretch and use the canonical zero bottom inset",
);
requireContract(
  /\[data-page-layout="persistent-rail"\] > \[data-page-primary\],[\s\S]*?\[data-page-layout="persistent-rail"\] > \[data-page-inspector\] \{[\s\S]*?align-self: var\(--mg-rail-align, stretch\);[\s\S]*?height: var\(--mg-rail-fill, 100%\);[\s\S]*?\}/.test(
    mediaStyles,
  ),
  "desktop rail primary and inspector must use one equal-height contract, read through the release tokens",
);
/* 等高契约给的是**高度上限**，不是必须填满的高度。检视栏被 stretch 拉满之后，
   内容只填了上半截时，剩下的是一块画了边框、铺了底色的空盒子，看着像没加载出来
   （/reviews 的「复盘检查器」把小节头压紧、内容少了 56px，空白反而涨到 144px：
   高度是 100dvh 减出来的，跟内容无关）。所以检视栏读同一组令牌、但默认按内容
   定高，再用 max-height 把上限留住——内容长时仍然吃满一列、在自己内部滚。 */
requireContract(
  /\[data-page-layout="persistent-rail"\] > \[data-page-inspector\] \{[^}]*align-self: var\(--mg-rail-align, start\);[^}]*height: var\(--mg-rail-fill, auto\);[^}]*max-height: 100%;[^}]*overflow-y: auto;[^}]*\}/.test(
    mediaStyles,
  ),
  "the inspector rail must size to its content, keep the equal-height budget as a max-height, and own its overflow-y (page-level .inspector rules lose the source-order tie to .mg-panel)",
);
requireContract(
  /@media \(max-width: 760px\) \{[\s\S]*?--mg-rail-shell-height: auto;[\s\S]*?--mg-rail-grow: 0 0 auto;[\s\S]*?--mg-rail-fill: auto;[\s\S]*?--mg-rail-align: auto;[\s\S]*?\}/.test(
    mediaStyles,
  ),
  "stacked mobile rails must release the desktop contract by setting every rail token",
);
requireContract(
  /--mg-control-height-sm: 36px;[\s\S]*?--mg-control-height-md: 44px;[\s\S]*?--mg-panel-heading-height: 54px;/.test(
    mediaStyles,
  ),
  "shared component dimensions must remain canonical",
);
requireContract(
  mediaStyles.includes("min-height: var(--mg-control-height-md)"),
  "shared primary button must consume the 44px control token",
);
requireContract(
  mediaStyles.includes("min-height: var(--mg-panel-heading-height)"),
  "shared section heading must consume the 54px panel token",
);
requireContract(
  /\.data-table th, \.data-table td \{[^}]*vertical-align: top;[^}]*\}/.test(
    mediaStyles,
  ),
  "shared data table cells must use a top baseline",
);

const publishingSource = fs.readFileSync(
  path.join(pagesRoot, "ordinary/PublishingPage.tsx"),
  "utf8",
);
const publishingStyles = fs.readFileSync(
  path.join(pagesRoot, "ordinary/PublishingPage.module.css"),
  "utf8",
);
requireContract(
  publishingSource.includes("body = <PublishingWorkspace") &&
    publishingSource.includes("function PublishingWorkspace") &&
    (publishingSource.match(/data-empty-workspace/g)?.length ?? 0) === 1 &&
    publishingSource.includes("? <EmptyPackageList onRefresh={onRefresh} />") &&
    publishingSource.includes(": <PackageList items={listData.items}") &&
    publishingSource.includes("? <EmptyPackageDetail />") &&
    publishingSource.includes(": <Detail state={detail}") &&
    publishingSource.includes("0 条当前账户记录") &&
    publishingSource.includes("等待选择发布包"),
  "publishing must preserve one shared workspace rail with empty list and detail branches",
);
requireContract(
  /\.workspace \{[\s\S]*?grid-template-columns:\s*minmax\(0,\s*3fr\)\s+minmax\(360px,\s*2fr\)/.test(
    publishingStyles,
  ),
  "publishing desktop workspace must preserve the D10 60/40 primary-to-inspector ratio",
);

/* 共享 rail 契约的「松开」机制必须是自定义属性，不是选择器特异性。
   页面各自在 1120px / 900px 就把两栏堆成一列，得整体松开这套契约；如果只能靠
   拼特异性去松，每个页面都会长出一份「把 media.css 的属性选择器抄一遍」或者
   一串 !important 的 workaround——/archives、/assets、/overview、/admin/* 就是
   这么各长一套的，而且抄漏一个断点就再次破相。自定义属性沿继承链传递、不参与
   特异性，页面写一次就够，所以这里把机制本身钉住。 */
const railReleaseConsumers: Array<[RegExp, string]> = [
  [
    /\.fidelity-page:has\(> \[data-page-prelude\]\) \{[^}]*height: var\(--mg-rail-shell-height,/,
    "the prelude shell height must read --mg-rail-shell-height",
  ],
  [
    /\.fidelity-page:has\(> \[data-page-prelude\]\) > \[data-page-layout="persistent-rail"\] \{[^}]*flex: var\(--mg-rail-grow,/,
    "the rail's own flex must read --mg-rail-grow",
  ],
  [
    /\[data-page-primary\] > :only-child \{[^}]*align-self: var\(--mg-rail-align, stretch\); height: var\(--mg-rail-fill, 100%\);/,
    "a primary column's only child must read the rail tokens",
  ],
  [
    /\[data-page-primary\]\[data-primary-flow\] > \[data-page-terminal-surface="primary"\] \{[^}]*flex: var\(--mg-rail-grow,/,
    "the primary-flow terminal surface must read --mg-rail-grow",
  ],
  [
    /\[data-page-layout="persistent-rail"\] > \[data-page-inspector\] \{[^}]*align-self: var\(--mg-rail-align, start\); height: var\(--mg-rail-fill, auto\);/,
    "the content-sized inspector must read the rail tokens too, so stacked mobile releases it with the rest",
  ],
];
for (const [pattern, message] of railReleaseConsumers) {
  requireContract(pattern.test(mediaStyles), `media.css: ${message}`);
}

/* 视口高度契约扣掉的不能是写死的常量：内容壳的上下内边距会随外壳（studio /
   admin）不同，写死就会在其中一种外壳上多出十几像素的滚动条。 */
requireContract(
  /height: var\(--mg-rail-shell-height, calc\(100dvh - var\(--mg-shell-topbar, 86px\) - var\(--mg-shell-content-inset, 46px\)\)\)/.test(
    mediaStyles,
  ) && /\.media-content \{[^}]*--mg-shell-content-inset:/.test(mediaStyles),
  "media.css: the viewport-bound shell must subtract --mg-shell-content-inset, declared next to the content shell's own padding",
);
const studioStyles = fs.readFileSync(
  path.join(mediaRoot, "mediaStudioTheme.css"),
  "utf8",
);
requireContract(
  /\.studio-content \{[\s\S]*?padding: 28px 32px 34px;[\s\S]*?--mg-shell-content-inset: 62px;[\s\S]*?\}/.test(
    studioStyles,
  ),
  "mediaStudioTheme.css: .studio-content must report its own vertical padding through --mg-shell-content-inset",
);

const pageStyleFiles = [
  ...sourceFiles(pagesRoot),
  ...sourceFiles(path.join(mediaRoot, "studio")),
].filter((file) => file.endsWith(".css"));

for (const file of pageStyleFiles) {
  const relative = path.relative(projectRoot, file);
  // 注释里出现这些字样是允许的（就是用来解释机制的），只看真正的声明。
  const source = fs
    .readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "");
  const copiedSelector = /\[data-page-layout|:has\(>\s*\[data-page-prelude\]/.exec(source);
  requireContract(
    copiedSelector === null,
    `${relative}: page styles must not copy the shared persistent-rail selectors (\`${copiedSelector?.[0] ?? ""}\`) to out-specify them — set --mg-rail-shell-height / --mg-rail-grow / --mg-rail-fill / --mg-rail-align on the page element at your own stacking breakpoint instead`,
  );
  const forcedGeometry = /(height|flex|align-self)\s*:[^;{}]*!important/.exec(source);
  requireContract(
    forcedGeometry === null,
    `${relative}: page styles must not force rail geometry with !important (\`${forcedGeometry?.[0]?.trim() ?? ""}\`) — the rail tokens release the shared contract without a specificity fight`,
  );
}

const allStyles = [
  { file: path.join(mediaRoot, "media.css"), source: mediaStyles },
  ...files
    .filter((file) => file.endsWith(".css"))
    .map((file) => ({ file, source: fs.readFileSync(file, "utf8") })),
];

for (const { file, source } of allStyles) {
  const relative = path.relative(projectRoot, file);
  const blocks = source.match(/[^{}]+\{[^{}]*\}/g) ?? [];
  for (const block of blocks) {
    const [selector = "", declarations = ""] = block.split("{", 2);
    if (
      /\b(?:th|td)\b/.test(selector) &&
      /vertical-align:\s*middle/.test(declarations)
    ) {
      throw new Error(
        `${relative}: table cells must not override the shared top baseline`,
      );
    }
  }
}

console.log(
  `qa:media-design-system-contract: PASS railPages=${canonicalRailPages.length} railStructure=prelude-before-paired-direct-children desktopHeight=remaining-space-equal railRelease=custom-properties terminalSurface=single-child-fill primaryFlow=terminal-fill mobileHeight=content tableBaseline=top controls=36/44 panelHeading=54 bottomInset=0`,
);
