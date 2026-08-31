import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const file = path.resolve(import.meta.dirname, "../../src/media/pages/ordinary/MediaAgentPage.tsx");
const source = fs.readFileSync(file, "utf8");
const order = ["设备与客户端", "本地运行", "流程目录"];

type JsxNode = ts.JsxElement | ts.JsxSelfClosingElement;

function requireContract(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function tagName(node: JsxNode): string {
  const tag = ts.isJsxElement(node) ? node.openingElement.tagName : node.tagName;
  return tag.getText();
}

function attributes(node: JsxNode): ts.JsxAttributes {
  return ts.isJsxElement(node) ? node.openingElement.attributes : node.attributes;
}

function attribute(node: JsxNode, name: string): ts.JsxAttribute | undefined {
  return attributes(node).properties.find(
    (property): property is ts.JsxAttribute => ts.isJsxAttribute(property) && property.name.text === name,
  );
}

function attributeText(node: JsxNode, name: string): string {
  const value = attribute(node, name)?.initializer;
  return value && ts.isStringLiteral(value) ? value.text : "";
}

function attributeInitializerText(node: JsxNode, name: string): string {
  return attribute(node, name)?.initializer?.getText() ?? "";
}

function jsxNodes(node: ts.Node): JsxNode[] {
  const result: JsxNode[] = [];
  function visit(current: ts.Node): void {
    if (ts.isJsxElement(current) || ts.isJsxSelfClosingElement(current)) result.push(current);
    current.forEachChild(visit);
  }
  visit(node);
  return result;
}

function nodeText(node: ts.Node): string {
  return node.getText();
}

function namedFunction(sourceFile: ts.SourceFile, name: string): ts.FunctionDeclaration | undefined {
  return sourceFile.statements.find(
    (node): node is ts.FunctionDeclaration => ts.isFunctionDeclaration(node) && node.name?.text === name,
  );
}

function canonicalTabs(sourceFile: ts.SourceFile): Array<{ id: string; label: string }> | null {
  const declaration = sourceFile.statements
    .filter(ts.isVariableStatement)
    .flatMap((statement) => statement.declarationList.declarations)
    .find((item) => ts.isIdentifier(item.name) && item.name.text === "TABS");
  if (!declaration?.initializer || !ts.isArrayLiteralExpression(declaration.initializer)) return null;
  const tabs: Array<{ id: string; label: string }> = [];
  for (const element of declaration.initializer.elements) {
    if (!ts.isObjectLiteralExpression(element)) return null;
    const properties = new Map(element.properties.filter(ts.isPropertyAssignment).map((property) => [property.name.getText(), property.initializer]));
    const id = properties.get("id");
    const label = properties.get("label");
    if (!id || !label || !ts.isStringLiteral(id) || !ts.isStringLiteral(label)) return null;
    tabs.push({ id: id.text, label: label.text });
  }
  return tabs;
}

function containsCall(node: ts.Node, calleeText: string): boolean {
  let found = false;
  function visit(current: ts.Node): void {
    if (ts.isCallExpression(current) && current.expression.getText() === calleeText) found = true;
    if (!found) current.forEachChild(visit);
  }
  visit(node);
  return found;
}

function comparedEventKeys(node: ts.Node): Set<string> {
  const keys = new Set<string>();
  function visit(current: ts.Node): void {
    if (ts.isBinaryExpression(current) && current.operatorToken.kind === ts.SyntaxKind.EqualsEqualsEqualsToken) {
      const [left, right] = [current.left, current.right];
      if (left.getText() === "event.key" && ts.isStringLiteral(right)) keys.add(right.text);
      if (right.getText() === "event.key" && ts.isStringLiteral(left)) keys.add(left.text);
    }
    current.forEachChild(visit);
  }
  visit(node);
  return keys;
}

function visibleJsxText(node: ts.Node): string {
  let result = "";
  function visit(current: ts.Node): void {
    if (ts.isJsxText(current)) result += current.getText();
    current.forEachChild(visit);
  }
  visit(node);
  return result.replace(/\s+/g, " ").trim();
}

function mediaAgentFunction(sourceFile: ts.SourceFile): ts.FunctionDeclaration {
  let result: ts.FunctionDeclaration | undefined;
  sourceFile.forEachChild((node) => {
    if (ts.isFunctionDeclaration(node) && node.name?.text === "MediaAgentPage") result = node;
  });
  requireContract(result, "MediaAgentPage function is missing");
  return result;
}

function isEmptyCondition(expression: ts.Expression): boolean {
  return ts.isBinaryExpression(expression)
    && expression.operatorToken.kind === ts.SyntaxKind.EqualsEqualsEqualsToken
    && ts.isIdentifier(expression.left)
    && expression.left.text === "state"
    && ts.isStringLiteral(expression.right)
    && expression.right.text === "empty";
}

function emptyReturn(sourceFile: ts.SourceFile): ts.ReturnStatement {
  const fn = mediaAgentFunction(sourceFile);
  let result: ts.ReturnStatement | undefined;
  function visit(node: ts.Node): void {
    if (result) return;
    if (ts.isIfStatement(node) && isEmptyCondition(node.expression) && ts.isReturnStatement(node.thenStatement)) {
      result = node.thenStatement;
      return;
    }
    node.forEachChild(visit);
  }
  fn.forEachChild(visit);
  requireContract(result, 'Media Agent must have an explicit state === "empty" return branch');
  return result;
}

function checkEmptyBranch(sourceText: string, fileName: string): string[] {
  const sourceFile = ts.createSourceFile(fileName, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const errors = sourceFile.parseDiagnostics.map((diagnostic) => ts.flattenDiagnosticMessageText(diagnostic.messageText, " "));
  if (errors.length) return errors;
  let empty: ts.ReturnStatement;
  try {
    empty = emptyReturn(sourceFile);
  } catch (error) {
    return [error instanceof Error ? error.message : String(error)];
  }
  const rendered = empty.expression ? jsxNodes(empty.expression) : [];
  const tags = new Set(rendered.map(tagName));
  if (!rendered.some((node) => tagName(node) === "SurfaceState" && attributeText(node, "kind") === "empty")) {
    errors.push("empty branch must render an empty SurfaceState");
  }
  if (!rendered.some((node) => tagName(node) === "DevicesTab" && attributeInitializerText(node, "onPair").includes("requestPairCode"))) {
    errors.push("empty branch must retain the authenticated device pairing surface");
  }
  const emptyTabLabels = rendered.filter((node) => tagName(node) === "TabButton").map(visibleJsxText).join(" ");
  if (tags.has("PipelineTab") || tags.has("RunTab") || emptyTabLabels.includes("本地运行") || emptyTabLabels.includes("流程目录")) {
    errors.push("empty branch must not expose pipeline or local-run controls");
  }
  return errors;
}

function checkReadyTabs(sourceText: string, fileName: string): string[] {
  const sourceFile = ts.createSourceFile(fileName, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const errors = sourceFile.parseDiagnostics.map((diagnostic) => ts.flattenDiagnosticMessageText(diagnostic.messageText, " "));
  const navs = jsxNodes(sourceFile).filter((node) => tagName(node) === "nav" && attributeText(node, "role") === "tablist");
  const readyNav = navs.find((node) => order.every((label) => nodeText(node).includes(label)) || nodeText(node).includes("TABS.map"));
  if (!readyNav) {
    errors.push("Media Agent ready-state tablist must contain all three tabs");
    return errors;
  }
  if (!nodeText(readyNav).includes("styles.tabBar")) errors.push("Media Agent tablist must use the tabBar style class");
  const readyText = nodeText(readyNav);
  const registry = canonicalTabs(sourceFile);
  if (!registry || registry.map((item) => item.label).join("|") !== order.join("|")) {
    errors.push("Media Agent tabs must be ordered client/device, local run, pipeline catalog");
  }
  const usesRegistry = containsCall(readyNav, "TABS.map");
  if (!usesRegistry) errors.push("Media Agent ready-state tablist must render the canonical TABS registry");
  const tabButtonFunction = namedFunction(sourceFile, "TabButton");
  const tabButton = tabButtonFunction ? jsxNodes(tabButtonFunction).find((node) => tagName(node) === "button") : undefined;
  const dynamicTabContract = !!tabButton
    && attributeInitializerText(tabButton, "id") === "{`media-agent-tab-${tab}`}"
    && attributeInitializerText(tabButton, "aria-controls") === "{`media-agent-panel-${tab}`}";
  for (const [tabId, panelId] of [
    ["media-agent-tab-devices", "media-agent-panel-devices"],
    ["media-agent-tab-run", "media-agent-panel-run"],
    ["media-agent-tab-pipelines", "media-agent-panel-pipelines"],
  ] as const) {
    const tab = (usesRegistry && dynamicTabContract) || (readyText.includes(`id="${tabId}"`) && readyText.includes(`controls="${panelId}"`));
    if (!tab) errors.push(`Media Agent tab ${tabId} must control ${panelId}`);
    const panel = jsxNodes(sourceFile).find((node) => tagName(node) === "TabPanel" && attributeText(node, "id") === panelId && attributeText(node, "labelledBy") === tabId);
    if (!panel) errors.push(`Media Agent panel ${panelId} must be labelled by ${tabId}`);
  }
  if (!sourceText.includes('useState<Tab>("devices")')) errors.push("Media Agent must open on the client/device tab");
  if (!registry) errors.push("Media Agent tabs must have a canonical ordered registry");
  const keyHandler = namedFunction(sourceFile, "handleTabKeyDown");
  const keys = keyHandler ? comparedEventKeys(keyHandler) : new Set<string>();
  if (!keys.has("ArrowRight") || !keys.has("ArrowLeft")) errors.push("Media Agent tabs must support horizontal keyboard navigation");
  if (!keys.has("Home") || !keys.has("End")) errors.push("Media Agent tabs must support Home/End keyboard navigation");
  if (!tabButton || attributeInitializerText(tabButton, "tabIndex") !== "{active ? 0 : -1}") errors.push("Media Agent tabs must use roving tabindex");
  if (!keyHandler || !containsCall(keyHandler, "event.preventDefault") || !containsCall(keyHandler, "requestAnimationFrame") || !containsCall(keyHandler, "document.getElementById") || !nodeText(keyHandler).includes("?.focus()")) errors.push("Media Agent keyboard navigation must prevent scrolling and move focus to the selected tab");
  const panelFunction = namedFunction(sourceFile, "TabPanel");
  const panel = panelFunction ? jsxNodes(panelFunction).find((node) => tagName(node) === "section") : undefined;
  const panelContract = !!panel && attributeText(panel, "role") === "tabpanel" && attributeInitializerText(panel, "aria-labelledby") === "{labelledBy}";
  const tabControlContract = !!tabButton && attributeInitializerText(tabButton, "aria-controls") === "{`media-agent-panel-${tab}`}";
  if (!panelContract || !tabControlContract) {
    errors.push("Media Agent tab panels must expose role=tabpanel and aria-labelledby");
  }
  return errors;
}

function inspect(sourceText: string, fileName: string): string[] {
  return [...checkEmptyBranch(sourceText, fileName), ...checkReadyTabs(sourceText, fileName)];
}

function runSelfTest(): void {
  const green = `
    function MediaAgentPage() {
      if (state === "empty") return <PageFrame>
        {/* PipelineTab and 本地运行 here would be unrelated comments only. */}
        <SurfaceState kind="empty" />
        <nav className={styles.tabBar} role="tablist"><TabButton id="media-agent-tab-devices" controls="media-agent-panel-devices">设备与客户端</TabButton></nav>
        <TabPanel id="media-agent-panel-devices" labelledBy="media-agent-tab-devices"><DevicesTab onPair={() => void requestPairCode()} /></TabPanel>
      </PageFrame>;
      return <PageFrame><nav className={styles.tabBar} role="tablist"><TabButton id="media-agent-tab-devices" controls="media-agent-panel-devices">设备与客户端</TabButton><TabButton id="media-agent-tab-run" controls="media-agent-panel-run">本地运行</TabButton><TabButton id="media-agent-tab-pipelines" controls="media-agent-panel-pipelines">流程目录</TabButton></nav><TabPanel id="media-agent-panel-devices" labelledBy="media-agent-tab-devices" /><TabPanel id="media-agent-panel-run" labelledBy="media-agent-tab-run" /><TabPanel id="media-agent-panel-pipelines" labelledBy="media-agent-tab-pipelines" /></PageFrame>;
    }
  `;
  requireContract(checkEmptyBranch(green, "green.tsx").length === 0, "Media Agent empty-state green fixture was rejected");
  const red = green.replace('<DevicesTab onPair={() => void requestPairCode()} />', '<><DevicesTab onPair={() => void requestPairCode()} /><RunTab /></>');
  requireContract(checkEmptyBranch(red, "red.tsx").some((error) => error.includes("pipeline or local-run controls")), "Media Agent empty-state red fixture was accepted");
  requireContract(checkReadyTabs(source.replace('event.key === "ArrowRight"', 'event.key === "PageDown"'), "missing-arrow.tsx").some((error) => error.includes("horizontal keyboard")), "Media Agent missing-arrow red fixture was accepted");
  requireContract(checkReadyTabs(source.replace('tabIndex={active ? 0 : -1}', 'tabIndex={0}'), "missing-roving-tabindex.tsx").some((error) => error.includes("roving tabindex")), "Media Agent fixed-tabindex red fixture was accepted");
  requireContract(checkReadyTabs(source.replace("?.focus()", "?.blur()"), "missing-focus.tsx").some((error) => error.includes("move focus")), "Media Agent missing-focus red fixture was accepted");
  requireContract(checkReadyTabs(source.replace("{TABS.map((item)", "{[...TABS].map((item)"), "noncanonical-render.tsx").length > 0, "Media Agent noncanonical-render red fixture was accepted");
  console.log("qa:media-agent-tab-order:self-test: PASS");
}

if (process.argv.includes("--self-test")) {
  runSelfTest();
} else {
  const errors = inspect(source, file);
  requireContract(errors.length === 0, errors.join(" | "));
  console.log("qa:media-agent-tab-order: PASS");
}
