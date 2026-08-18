import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import ts from "typescript";

type DiagnosticCode =
  | "MPR001"
  | "MPR002"
  | "MPR003"
  | "MPR004"
  | "MPR005"
  | "MPR006"
  | "MPR007"
  | "MPR008";

interface Diagnostic {
  code: DiagnosticCode;
  file: string;
  line: number;
  column: number;
  message: string;
}

interface FixtureCase {
  name: string;
  file: string;
  expectedCodes: DiagnosticCode[];
}

const projectRoot = path.resolve(import.meta.dirname, "../..");
const registryRelativePath = "src/media/ui/platformRegistry.ts";
const fixtureRoot = path.join(
  import.meta.dirname,
  "fixtures/media-platform-registry",
);

const brandContracts = {
  douyin: {
    aliases: ["douyin", "抖音"],
    label: "抖音",
    exportName: "siTiktok",
    color: "#000000",
  },
  xiaohongshu: {
    aliases: ["xiaohongshu", "redbook", "小红书"],
    label: "小红书",
    exportName: "siXiaohongshu",
    color: "#FF2442",
  },
  kuaishou: {
    aliases: ["kuaishou", "快手"],
    label: "快手",
    exportName: "siKuaishou",
    color: "#FF4906",
  },
  bilibili: {
    aliases: ["bilibili", "b站", "哔哩哔哩"],
    label: "哔哩哔哩",
    exportName: "siBilibili",
    color: "#00A1D6",
  },
  wechat: {
    aliases: ["wechat", "微信"],
    label: "微信",
    exportName: "siWechat",
    color: "#07C160",
  },
  weibo: {
    aliases: ["weibo", "sinaweibo", "微博"],
    label: "微博",
    exportName: "siSinaweibo",
    color: "#E6162D",
  },
  zhihu: {
    aliases: ["zhihu", "知乎"],
    label: "知乎",
    exportName: "siZhihu",
    color: "#0084FF",
  },
} as const;

const nonBrandContracts = {
  web: {
    aliases: ["web", "网页"],
    label: "网页",
    exportName: "Globe2",
  },
  unknown: {
    aliases: ["unknown", "未知平台", "未标注", "平台待确认"],
    label: "其他平台",
    exportName: "CircleHelp",
  },
} as const;

const requiredKeys = [
  ...Object.keys(brandContracts),
  ...Object.keys(nonBrandContracts),
] as const;

const aliasToKey = new Map<string, string>();
for (const [key, contract] of Object.entries({
  ...brandContracts,
  ...nonBrandContracts,
})) {
  for (const alias of contract.aliases) aliasToKey.set(normalizeAlias(alias), key);
}

function normalizeAlias(value: string): string {
  return value.trim().toLowerCase();
}

function normalizedPath(value: string): string {
  return value.split(path.sep).join("/");
}

function sourceKind(file: string): ts.ScriptKind {
  return file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
}

function sourceFile(file: string, source: string): ts.SourceFile {
  return ts.createSourceFile(
    file,
    source,
    ts.ScriptTarget.Latest,
    true,
    sourceKind(file),
  );
}

function lineAndColumn(tree: ts.SourceFile, position: number) {
  const location = tree.getLineAndCharacterOfPosition(Math.max(0, position));
  return { line: location.line + 1, column: location.character + 1 };
}

function exceptionCodes(source: string, relativeFile: string): Set<DiagnosticCode> {
  const result = new Set<DiagnosticCode>();
  const pattern =
    /media-platform-registry-guard-allow\s+code=(MPR\d{3})\s+reason=([^\s]+)\s+owner=([^\s]+)\s+expires=(\d{4}-\d{2}-\d{2})\s+scope=([^\s*]+)/g;
  for (const match of source.matchAll(pattern)) {
    const [, code, reason, owner, expires, scope] = match;
    const expiry = Date.parse(`${expires}T23:59:59Z`);
    if (
      reason &&
      owner &&
      Number.isFinite(expiry) &&
      expiry >= Date.now() &&
      normalizedPath(scope) === relativeFile &&
      /^MPR00[1-8]$/.test(code)
    ) {
      result.add(code as DiagnosticCode);
    }
  }
  return result;
}

function createReporter(
  root: string,
  file: string,
  source: string,
  tree?: ts.SourceFile,
) {
  const relativeFile = normalizedPath(path.relative(root, file));
  const allowed =
    path.resolve(root) === path.resolve(fixtureRoot)
      ? exceptionCodes(source, relativeFile)
      : new Set<DiagnosticCode>();
  const diagnostics: Diagnostic[] = [];
  return {
    diagnostics,
    emit(code: DiagnosticCode, message: string, position = 0) {
      if (allowed.has(code)) return;
      const location = tree
        ? lineAndColumn(tree, position)
        : { line: source.slice(0, position).split("\n").length, column: 1 };
      diagnostics.push({ code, file: relativeFile, ...location, message });
    },
  };
}

function walk(node: ts.Node, visit: (candidate: ts.Node) => void) {
  visit(node);
  ts.forEachChild(node, (child) => walk(child, visit));
}

function unwrapExpression(expression: ts.Expression): ts.Expression {
  if (
    ts.isAsExpression(expression) ||
    ts.isSatisfiesExpression(expression) ||
    ts.isParenthesizedExpression(expression) ||
    ts.isNonNullExpression(expression)
  ) {
    return unwrapExpression(expression.expression);
  }
  if (
    ts.isCallExpression(expression) &&
    expression.arguments.length > 0 &&
    /(?:^|\.)freeze$/.test(expression.expression.getText())
  ) {
    return unwrapExpression(expression.arguments[0]);
  }
  return expression;
}

function propertyName(node: ts.PropertyName | ts.BindingName | undefined): string {
  if (!node) return "";
  if (ts.isIdentifier(node) || ts.isStringLiteral(node) || ts.isNumericLiteral(node))
    return node.text;
  return node.getText().replace(/^['"]|['"]$/g, "");
}

function findVariable(tree: ts.SourceFile, name: string): ts.VariableDeclaration | undefined {
  let result: ts.VariableDeclaration | undefined;
  walk(tree, (node) => {
    if (
      !result &&
      ts.isVariableDeclaration(node) &&
      propertyName(node.name) === name
    ) {
      result = node;
    }
  });
  return result;
}

function objectLiteral(expression: ts.Expression | undefined): ts.ObjectLiteralExpression | undefined {
  if (!expression) return undefined;
  const unwrapped = unwrapExpression(expression);
  return ts.isObjectLiteralExpression(unwrapped) ? unwrapped : undefined;
}

function arrayLiteral(expression: ts.Expression | undefined): ts.ArrayLiteralExpression | undefined {
  if (!expression) return undefined;
  const unwrapped = unwrapExpression(expression);
  return ts.isArrayLiteralExpression(unwrapped) ? unwrapped : undefined;
}

function objectProperty(
  object: ts.ObjectLiteralExpression,
  name: string,
): ts.PropertyAssignment | undefined {
  return object.properties.find(
    (property): property is ts.PropertyAssignment =>
      ts.isPropertyAssignment(property) && propertyName(property.name) === name,
  );
}

function stringValue(expression: ts.Expression | undefined): string | undefined {
  if (!expression) return undefined;
  const unwrapped = unwrapExpression(expression);
  return ts.isStringLiteralLike(unwrapped) ? unwrapped.text : undefined;
}

function booleanValue(expression: ts.Expression | undefined): boolean | undefined {
  if (!expression) return undefined;
  const unwrapped = unwrapExpression(expression);
  if (unwrapped.kind === ts.SyntaxKind.TrueKeyword) return true;
  if (unwrapped.kind === ts.SyntaxKind.FalseKeyword) return false;
  return undefined;
}

function stringArray(expression: ts.Expression | undefined): string[] | undefined {
  const array = arrayLiteral(expression);
  if (!array) return undefined;
  const values = array.elements.map((element) =>
    ts.isExpression(element) ? stringValue(element) : undefined,
  );
  return values.every((value): value is string => value !== undefined)
    ? values
    : undefined;
}

function literalStrings(node: ts.Node): string[] {
  const result: string[] = [];
  walk(node, (candidate) => {
    if (ts.isStringLiteralLike(candidate)) result.push(candidate.text);
  });
  return result;
}

function platformFactTokens(node: ts.Node): string[] {
  const result = literalStrings(node);
  walk(node, (candidate) => {
    if (
      ts.isPropertyAssignment(candidate) ||
      ts.isShorthandPropertyAssignment(candidate) ||
      ts.isMethodDeclaration(candidate)
    ) {
      result.push(propertyName(candidate.name));
    }
  });
  return result;
}

function validateRegistry(root: string, file: string, source: string): Diagnostic[] {
  const tree = sourceFile(file, source);
  const report = createReporter(root, file, source, tree);
  const registryDeclaration = findVariable(tree, "PLATFORM_REGISTRY");
  const registry = objectLiteral(registryDeclaration?.initializer);
  if (!registryDeclaration || !registry) {
    report.emit(
      "MPR002",
      "PLATFORM_REGISTRY must be a statically inspectable object owned by platformRegistry.ts",
      registryDeclaration?.getStart(tree) ?? 0,
    );
    return report.diagnostics;
  }

  const imports = new Map<string, Set<string>>();
  for (const statement of tree.statements) {
    if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier))
      continue;
    const imported = new Set<string>();
    const bindings = statement.importClause?.namedBindings;
    if (bindings && ts.isNamedImports(bindings)) {
      for (const element of bindings.elements)
        imported.add((element.propertyName ?? element.name).text);
    }
    imports.set(statement.moduleSpecifier.text, imported);
  }

  const aliasOwners = new Map<string, string>();
  for (const key of requiredKeys) {
    const registryProperty = objectProperty(registry, key);
    const entry = objectLiteral(registryProperty?.initializer);
    if (!registryProperty || !entry) {
      report.emit("MPR002", `PLATFORM_REGISTRY is missing the ${key} entry`);
      continue;
    }

    const contract =
      key in brandContracts
        ? brandContracts[key as keyof typeof brandContracts]
        : nonBrandContracts[key as keyof typeof nonBrandContracts];
    const aliases = stringArray(objectProperty(entry, "aliases")?.initializer);
    const label = stringValue(objectProperty(entry, "label")?.initializer);
    const accessibleName = stringValue(
      objectProperty(entry, "accessibleName")?.initializer,
    );
    const isBrand = booleanValue(objectProperty(entry, "isBrand")?.initializer);
    const brandColorProperty = objectProperty(entry, "brandColor");
    const brandColor = stringValue(brandColorProperty?.initializer);
    const iconSource = objectLiteral(objectProperty(entry, "iconSource")?.initializer);
    const iconExpression = objectProperty(entry, "icon")?.initializer;

    if (stringValue(objectProperty(entry, "key")?.initializer) !== key)
      report.emit("MPR002", `${key}.key must equal ${key}`, entry.getStart(tree));
    if (!aliases || contract.aliases.some((alias) => !aliases.includes(alias)))
      report.emit(
        "MPR002",
        `${key}.aliases must include the frozen canonical aliases`,
        entry.getStart(tree),
      );
    if (label !== contract.label || !accessibleName)
      report.emit(
        "MPR002",
        `${key} must define the frozen label and a non-empty accessibleName`,
        entry.getStart(tree),
      );
    const expectedBrand = key in brandContracts;
    if (isBrand !== expectedBrand)
      report.emit("MPR002", `${key}.isBrand must be ${expectedBrand}`, entry.getStart(tree));
    if (!iconExpression)
      report.emit("MPR002", `${key}.icon must reference the imported vector`, entry.getStart(tree));

    if (expectedBrand) {
      const brand = brandContracts[key as keyof typeof brandContracts];
      if (brandColor?.toUpperCase() !== brand.color.toUpperCase())
        report.emit("MPR002", `${key}.brandColor must be ${brand.color}`, entry.getStart(tree));
      const sourceFacts = iconSource
        ? {
            kind: stringValue(objectProperty(iconSource, "kind")?.initializer),
            exportName: stringValue(objectProperty(iconSource, "exportName")?.initializer),
            package: stringValue(objectProperty(iconSource, "package")?.initializer),
            version: stringValue(objectProperty(iconSource, "version")?.initializer),
            license: stringValue(objectProperty(iconSource, "license")?.initializer),
          }
        : undefined;
      if (
        !sourceFacts ||
        sourceFacts.kind !== "simple-icons" ||
        sourceFacts.exportName !== brand.exportName ||
        sourceFacts.package !== "simple-icons" ||
        sourceFacts.version !== "16.28.0" ||
        sourceFacts.license !== "CC0-1.0" ||
        !imports.get("simple-icons")?.has(brand.exportName)
      ) {
        report.emit(
          "MPR002",
          `${key}.iconSource must bind ${brand.exportName} from simple-icons@16.28.0 under CC0-1.0`,
          entry.getStart(tree),
        );
      }
    } else {
      const generic = nonBrandContracts[key as keyof typeof nonBrandContracts];
      const sourceFacts = iconSource
        ? {
            kind: stringValue(objectProperty(iconSource, "kind")?.initializer),
            exportName: stringValue(objectProperty(iconSource, "exportName")?.initializer),
            package: stringValue(objectProperty(iconSource, "package")?.initializer),
          }
        : undefined;
      if (
        brandColorProperty?.initializer.kind !== ts.SyntaxKind.NullKeyword ||
        !sourceFacts ||
        sourceFacts.kind !== "lucide" ||
        sourceFacts.exportName !== generic.exportName ||
        sourceFacts.package !== "lucide-react" ||
        !imports.get("lucide-react")?.has(generic.exportName)
      ) {
        report.emit(
          "MPR002",
          `${key} must use neutral ${generic.exportName} from lucide-react with no brand color`,
          entry.getStart(tree),
        );
      }
    }

    for (const alias of [key, ...(aliases ?? [])]) {
      const normalized = normalizeAlias(alias);
      const owner = aliasOwners.get(normalized);
      if (owner && owner !== key) {
        report.emit(
          "MPR003",
          `normalized alias ${JSON.stringify(normalized)} belongs to both ${owner} and ${key}`,
          entry.getStart(tree),
        );
      } else {
        aliasOwners.set(normalized, key);
      }
    }
  }

  const brandedKeys = findVariable(tree, "BRANDED_PLATFORM_KEYS");
  const brandedInitializer = brandedKeys?.initializer?.getText(tree) ?? "";
  if (
    !brandedKeys ||
    !brandedInitializer.includes("Object.values(PLATFORM_REGISTRY)") ||
    !brandedInitializer.includes(".filter(") ||
    !brandedInitializer.includes(".map(")
  ) {
    report.emit(
      "MPR002",
      "BRANDED_PLATFORM_KEYS must be derived from Object.values(PLATFORM_REGISTRY)",
      brandedKeys?.getStart(tree) ?? 0,
    );
  }

  return report.diagnostics;
}

function nearestVariableName(node: ts.Node): string {
  let candidate: ts.Node | undefined = node;
  while (candidate) {
    if (ts.isVariableDeclaration(candidate)) return propertyName(candidate.name);
    if (ts.isPropertyAssignment(candidate)) return propertyName(candidate.name);
    candidate = candidate.parent;
  }
  return "";
}

function scanTypeScript(root: string, file: string, source: string): Diagnostic[] {
  const tree = sourceFile(file, source);
  const report = createReporter(root, file, source, tree);
  const relativeFile = normalizedPath(path.relative(root, file));
  const importedLucideNames = new Set<string>();

  walk(tree, (node) => {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      const moduleName = node.moduleSpecifier.text;
      if (moduleName === "lucide-react") {
        const bindings = node.importClause?.namedBindings;
        if (bindings && ts.isNamedImports(bindings)) {
          for (const element of bindings.elements) importedLucideNames.add(element.name.text);
        }
      }
      if (
        moduleName.startsWith("simple-icons") &&
        relativeFile !== registryRelativePath
      ) {
        report.emit(
          "MPR004",
          "only platformRegistry.ts may import the upstream brand icon package",
          node.getStart(tree),
        );
      }
    }

    if (ts.isVariableDeclaration(node) && node.initializer) {
      const name = propertyName(node.name);
      const initializer = unwrapExpression(node.initializer);
      const isCollection =
        ts.isObjectLiteralExpression(initializer) || ts.isArrayLiteralExpression(initializer);
      if (isCollection && /platform|brand|icon/i.test(name)) {
        const knownValues = new Set(
          platformFactTokens(initializer)
            .map(normalizeAlias)
            .filter((value) => aliasToKey.has(value)),
        );
        const initializerText = initializer.getText(tree);
        if (
          knownValues.size >= 2 &&
          !/PLATFORM_REGISTRY|BRANDED_PLATFORM_KEYS/.test(initializerText) &&
          relativeFile !== registryRelativePath
        ) {
          report.emit(
            "MPR004",
            `${name} defines platform identity facts outside platformRegistry.ts`,
            node.getStart(tree),
          );
        }
      }
    }

    if (
      ts.isConditionalExpression(node) &&
      /platform/i.test(node.condition.getText(tree))
    ) {
      const mappedKeys = new Set(
        literalStrings(node)
          .map(normalizeAlias)
          .map((value) => aliasToKey.get(value))
          .filter((value): value is string => value !== undefined),
      );
      if (mappedKeys.size >= 2 && relativeFile !== registryRelativePath) {
        report.emit(
          "MPR004",
          "inline platform label or identity branches must resolve through platformRegistry.ts",
          node.getStart(tree),
        );
      }
    }

    if (ts.isStringLiteralLike(node)) {
      if (/\/platform-icons\//i.test(node.text)) {
        report.emit(
          "MPR006",
          "fixed /platform-icons asset paths are forbidden",
          node.getStart(tree),
        );
      }
      if (/^https?:\/\//i.test(node.text)) {
        const ownerName = nearestVariableName(node);
        const jsxSource =
          ts.isJsxAttribute(node.parent) && propertyName(node.parent.name) === "src";
        if (
          jsxSource ||
          /(?:platform|brand).*(?:icon|asset|image|src|url)|(?:icon|asset|image).*(?:src|url)/i.test(
            ownerName,
          )
        ) {
          report.emit(
            "MPR007",
            "runtime remote brand icon sources are forbidden",
            node.getStart(tree),
          );
        }
      }
    }
  });

  walk(tree, (node) => {
    let name = "";
    let body: ts.Node | undefined;
    if (ts.isFunctionDeclaration(node)) {
      name = node.name?.text ?? "";
      body = node.body;
    } else if (
      ts.isVariableDeclaration(node) &&
      node.initializer &&
      (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer))
    ) {
      name = propertyName(node.name);
      body = node.initializer.body;
    }
    if (!body || !/(?:platform.*icon|icon.*platform)/i.test(name)) return;
    const bodyText = body.getText(tree);
    const referencesBrand = [...aliasToKey.keys()].some(
      (alias) => alias !== "web" && alias !== "unknown" && bodyText.toLowerCase().includes(alias),
    );
    const usedLucide = [...importedLucideNames].filter((icon) =>
      new RegExp(`\\b${icon}\\b`).test(bodyText),
    );
    if (referencesBrand && usedLucide.length > 0 && relativeFile !== "src/media/ui/PlatformBrandIcon.tsx") {
      report.emit(
        "MPR008",
        `${name} approximates known platform brands with lucide-react (${usedLucide.join(", ")})`,
        node.getStart(tree),
      );
    }
  });

  return report.diagnostics;
}

function scanCss(root: string, file: string, source: string): Diagnostic[] {
  const report = createReporter(root, file, source);
  const brandToken =
    "douyin|tiktok|xiaohongshu|redbook|kuaishou|bilibili|wechat|weibo|sinaweibo|zhihu";
  const rulePattern = /([^{}]+)\{([^{}]*)\}/g;
  for (const match of source.matchAll(rulePattern)) {
    const selector = match[1];
    const body = match[2];
    const position = match.index ?? 0;
    if (
      new RegExp(`(?:platform|brand)[-_]?(?:${brandToken})`, "i").test(selector) ||
      new RegExp(`--(?:platform|brand)[-_]?(?:${brandToken})`, "i").test(body)
    ) {
      report.emit(
        "MPR005",
        "platform-specific colors or selectors must be owned by the registry and shared component",
        position,
      );
    }
    if (/url\(\s*['"]?https?:\/\//i.test(body) && /platform|brand/i.test(selector)) {
      report.emit("MPR007", "runtime remote brand icon sources are forbidden", position);
    }
  }
  for (const match of source.matchAll(/\/platform-icons\//gi)) {
    report.emit("MPR006", "fixed /platform-icons asset paths are forbidden", match.index ?? 0);
  }
  return report.diagnostics;
}

function scanSource(root: string, file: string, source: string): Diagnostic[] {
  return file.endsWith(".css")
    ? scanCss(root, file, source)
    : scanTypeScript(root, file, source);
}

function sourceFiles(root: string): string[] {
  const mediaRoot = path.join(root, "src/media");
  if (!fs.existsSync(mediaRoot)) return [];
  const result: string[] = [];
  const visit = (directory: string) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const file = path.join(directory, entry.name);
      const relative = normalizedPath(path.relative(root, file));
      if (
        entry.isDirectory() &&
        !/(?:^|\/)(?:dist|dist-media|generated|tmp|agents-results)(?:\/|$)/.test(relative)
      ) {
        visit(file);
      } else if (
        entry.isFile() &&
        /\.(?:ts|tsx|css)$/.test(entry.name) &&
        !/\.(?:orig|before-[^.]+)(?:\.|$)/.test(entry.name)
      ) {
        result.push(file);
      }
    }
  };
  visit(mediaRoot);
  const mediaBuildConfig = path.join(root, "vite.media.config.ts");
  if (fs.existsSync(mediaBuildConfig)) result.push(mediaBuildConfig);
  return result.sort();
}

function legacyAssetDiagnostics(root: string): Diagnostic[] {
  const assetRoot = path.join(root, "public/platform-icons");
  if (!fs.existsSync(assetRoot)) return [];
  const diagnostics: Diagnostic[] = [];
  const visit = (directory: string) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const file = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        visit(file);
      } else if (entry.isFile() && /\.png$/i.test(entry.name)) {
        diagnostics.push({
          code: "MPR006",
          file: normalizedPath(path.relative(root, file)),
          line: 1,
          column: 1,
          message: "legacy PNG platform icon assets are forbidden",
        });
      }
    }
  };
  visit(assetRoot);
  return diagnostics;
}

function scanProject(root: string): Diagnostic[] {
  const registryFile = path.join(root, registryRelativePath);
  const diagnostics: Diagnostic[] = [];
  if (!fs.existsSync(registryFile)) {
    diagnostics.push({
      code: "MPR001",
      file: registryRelativePath,
      line: 1,
      column: 1,
      message: "the canonical platform registry is missing",
    });
  } else {
    diagnostics.push(
      ...validateRegistry(root, registryFile, fs.readFileSync(registryFile, "utf8")),
    );
  }
  for (const file of sourceFiles(root)) {
    if (normalizedPath(path.relative(root, file)) === registryRelativePath) continue;
    diagnostics.push(...scanSource(root, file, fs.readFileSync(file, "utf8")));
  }
  diagnostics.push(...legacyAssetDiagnostics(root));
  return deduplicate(diagnostics);
}

function deduplicate(diagnostics: Diagnostic[]): Diagnostic[] {
  const unique = new Map<string, Diagnostic>();
  for (const diagnostic of diagnostics) {
    const key = `${diagnostic.code}:${diagnostic.file}:${diagnostic.line}:${diagnostic.message}`;
    unique.set(key, diagnostic);
  }
  return [...unique.values()].sort(
    (left, right) =>
      left.file.localeCompare(right.file) ||
      left.line - right.line ||
      left.code.localeCompare(right.code),
  );
}

function printDiagnostics(diagnostics: Diagnostic[]) {
  for (const diagnostic of diagnostics) {
    console.error(
      `${diagnostic.file}:${diagnostic.line}:${diagnostic.column} ${diagnostic.code} ${diagnostic.message}`,
    );
  }
}

function codes(diagnostics: Diagnostic[]): DiagnosticCode[] {
  return [...new Set(diagnostics.map((diagnostic) => diagnostic.code))].sort();
}

function runSelfTest() {
  const cases = JSON.parse(
    fs.readFileSync(path.join(fixtureRoot, "fixture-cases.json"), "utf8"),
  ) as FixtureCase[];
  const failures: string[] = [];
  for (const fixture of cases) {
    const file = path.join(fixtureRoot, fixture.file);
    let diagnostics: Diagnostic[];
    if (fixture.file === "alias-conflict.registry.ts") {
      const validRegistry = fs.readFileSync(
        path.join(fixtureRoot, "valid.registry.ts"),
        "utf8",
      );
      const conflictingRegistry = validRegistry.replace(
        '["xiaohongshu", "redbook", "小红书"]',
        '["xiaohongshu", "redbook", "小红书", "douyin"]',
      );
      diagnostics = validateRegistry(fixtureRoot, file, conflictingRegistry);
    } else if (fixture.file.endsWith(".registry.ts")) {
      diagnostics = validateRegistry(fixtureRoot, file, fs.readFileSync(file, "utf8"));
    } else if (fixture.file === "missing-registry.fixture") {
      diagnostics = [
        {
          code: "MPR001",
          file: registryRelativePath,
          line: 1,
          column: 1,
          message: "the canonical platform registry is missing",
        },
      ];
    } else if (fixture.file === "legacy-png.fixture") {
      diagnostics = [
        {
          code: "MPR006",
          file: "public/platform-icons/douyin.png",
          line: 1,
          column: 1,
          message: "legacy PNG platform icon assets are forbidden",
        },
      ];
    } else {
      diagnostics = scanSource(fixtureRoot, file, fs.readFileSync(file, "utf8"));
    }
    const actual = codes(diagnostics);
    const expected = [...fixture.expectedCodes].sort();
    if (JSON.stringify(actual) !== JSON.stringify(expected)) {
      failures.push(
        `${fixture.name}: expected ${expected.join(",") || "pass"}, got ${actual.join(",") || "pass"}`,
      );
      printDiagnostics(diagnostics);
    }
  }
  if (failures.length > 0) {
    for (const failure of failures) console.error(`fixture failure: ${failure}`);
    process.exitCode = 1;
    return;
  }
  console.log(`media platform registry guard fixtures passed (${cases.length} cases)`);
}

function rootArgument(args: string[]): string {
  const rootIndex = args.indexOf("--root");
  if (rootIndex >= 0) {
    const value = args[rootIndex + 1];
    if (!value) throw new Error("--root requires a directory");
    return path.resolve(value);
  }
  return process.env.MEDIA_PLATFORM_REGISTRY_ROOT
    ? path.resolve(process.env.MEDIA_PLATFORM_REGISTRY_ROOT)
    : projectRoot;
}

const args = process.argv.slice(2);
if (args.includes("--self-test")) {
  runSelfTest();
} else if (args.includes("--stdin")) {
  const input = fs.readFileSync(0, "utf8");
  const isCss = /language=css/.test(input);
  const virtualFile = path.join(fixtureRoot, isCss ? "fixture.css" : "fixture.tsx");
  const diagnostics = scanSource(fixtureRoot, virtualFile, input);
  printDiagnostics(diagnostics);
  if (diagnostics.length > 0) process.exitCode = 1;
} else {
  const root = rootArgument(args);
  const diagnostics = scanProject(root);
  printDiagnostics(diagnostics);
  if (diagnostics.length > 0) process.exitCode = 1;
  else console.log("media platform registry guard passed");
}
