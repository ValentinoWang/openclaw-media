import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, extname, resolve } from 'node:path'
import postcss, { type Declaration } from 'postcss'
import ts from 'typescript'
import { CANONICAL_MEDIA_PAGE_SURFACES, type HeroActionsContract } from './mediaPageStructureManifest'

const projectRoot = resolve(import.meta.dirname, '../..')
type FoundationViolation = 'gradient functions' | 'decorative .mg-hero pseudo-element' | 'nonzero .mg-eyebrow letter spacing'

const gradientFunctionPattern = /\b[a-z-]*gradient\s*\(/i
const heroPseudoElementPattern = /\.mg-hero[^{}]*::?(?:before|after)\b[^{}]*\{/i
const eyebrowRulePattern = /\.mg-eyebrow[^{}]*\{([^{}]*)\}/gi
const letterSpacingPattern = /\bletter-spacing\s*:\s*([^;}]+)/i
const zeroLetterSpacingPattern = /^-?(?:0+\.?0*|\.0+)(?:[a-z%]+)?(?:\s*!important)?$/i
const allowedFontWeights = new Set(['400', '500', '600', '700'])
const allowedTrackingValues = new Set(['var(--mg-track-tight)', 'var(--mg-track-normal)', 'var(--mg-track-wide)'])
const trackingTokens = [...allowedTrackingValues].map((value) => value.slice(4, -1))
const legacyMetricTones = ['mint', 'violet', 'amber', 'blue'] as const
type LegacyMetricTone = (typeof legacyMetricTones)[number]

type MetricToneViolation = {
  fileName: string
  line: number
  tone: LegacyMetricTone
}

function isZeroLetterSpacing(value: string): boolean {
  return zeroLetterSpacingPattern.test(value.trim())
}

function decodeCssEscapes(value: string): string {
  return value.replace(/\\([0-9a-f]{1,6})(?:\r\n|[\t\n\f\r ])?|\\([^\r\n\f0-9a-f])/giu, (_, hex: string | undefined, escaped: string | undefined) => {
    if (hex) {
      const codePoint = Number.parseInt(hex, 16)
      return codePoint === 0 || codePoint > 0x10ffff ? '\uFFFD' : String.fromCodePoint(codePoint)
    }
    return escaped ?? ''
  })
}

function normalizedProperty(declaration: Declaration): string {
  return decodeCssEscapes(declaration.prop).toLowerCase()
}

function parseCss(sourceText: string): postcss.Root {
  return postcss.parse(sourceText, { from: undefined })
}

function declarationValue(declaration: Declaration): string {
  return `${declaration.value.trim()}${declaration.important ? ' !important' : ''}`
}

function findFoundationViolations(primitiveCss: string): FoundationViolation[] {
  const violations: FoundationViolation[] = []
  if (gradientFunctionPattern.test(primitiveCss)) violations.push('gradient functions')
  if (heroPseudoElementPattern.test(primitiveCss)) violations.push('decorative .mg-hero pseudo-element')

  for (const match of primitiveCss.matchAll(eyebrowRulePattern)) {
    const declaration = match[1].match(letterSpacingPattern)
    if (declaration && !isZeroLetterSpacing(declaration[1])) {
      violations.push('nonzero .mg-eyebrow letter spacing')
      break
    }
  }

  return violations
}

function assertFoundationClean(primitiveCss: string, sourceName: string): void {
  const violations = findFoundationViolations(primitiveCss)
  if (violations.length) {
    throw new Error(`media primitive enhancement failed in ${sourceName}: ${violations.join(', ')}`)
  }
}

type StaticBindings = ReadonlyMap<string, ts.Expression>

function staticStringValues(expression: ts.Expression | undefined, bindings: StaticBindings = new Map(), seen = new Set<string>()): readonly string[] {
  if (!expression) return []
  if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) return [expression.text]
  if (ts.isParenthesizedExpression(expression)) return staticStringValues(expression.expression, bindings, seen)
  if (ts.isIdentifier(expression)) {
    if (seen.has(expression.text)) return []
    const value = bindings.get(expression.text)
    return value ? staticStringValues(value, bindings, new Set(seen).add(expression.text)) : []
  }
  if (ts.isArrayLiteralExpression(expression)) return expression.elements.flatMap((item) => ts.isSpreadElement(item) ? staticStringValues(item.expression, bindings, seen) : staticStringValues(item, bindings, seen))
  if (ts.isObjectLiteralExpression(expression)) {
    return expression.properties.flatMap((property) => {
      if (ts.isSpreadAssignment(property)) return staticStringValues(property.expression, bindings, seen)
      if (!ts.isPropertyAssignment(property)) return []
      const key = ts.isIdentifier(property.name) || ts.isStringLiteral(property.name) ? property.name.text : undefined
      if (key && (property.initializer.kind === ts.SyntaxKind.TrueKeyword || property.initializer.kind === ts.SyntaxKind.FalseKeyword)) {
        return property.initializer.kind === ts.SyntaxKind.TrueKeyword ? [key] : []
      }
      const value = staticStringValues(property.initializer, bindings, seen)
      return key && value.length ? value : []
    })
  }
  if (ts.isCallExpression(expression) && ts.isIdentifier(expression.expression) && isClassNameHelper(expression.expression.text, bindings)) {
    return expression.arguments.flatMap((argument) => staticStringValues(argument, bindings, seen))
  }
  if (ts.isCallExpression(expression) && ts.isPropertyAccessExpression(expression.expression) && expression.expression.name.text === 'join') {
    return staticStringValues(expression.expression.expression, bindings, seen)
  }
  if (ts.isConditionalExpression(expression)) return [...staticStringValues(expression.whenTrue, bindings, seen), ...staticStringValues(expression.whenFalse, bindings, seen)]
  if (ts.isBinaryExpression(expression) && expression.operatorToken.kind === ts.SyntaxKind.PlusToken) {
    return [...staticStringValues(expression.left, bindings, seen), ...staticStringValues(expression.right, bindings, seen)]
  }
  if (ts.isTemplateExpression(expression)) {
    return [expression.head.text, ...expression.templateSpans.flatMap((span) => [...staticStringValues(span.expression, bindings, seen), span.literal.text])]
  }
  return []
}

const classNameHelpers = new Set(['cx', 'clsx', 'classNames', 'makeClasses'])

function isClassNameHelper(name: string, bindings: StaticBindings): boolean {
  if (classNameHelpers.has(name)) return true
  const binding = bindings.get(name)
  return Boolean(binding && ts.isIdentifier(binding) && classNameHelpers.has(binding.text))
}

function jsxAttributeStaticStringValues(attribute: ts.JsxAttribute, bindings: StaticBindings = new Map()): readonly string[] {
  const initializer = attribute.initializer
  if (!initializer) return []
  if (ts.isStringLiteral(initializer)) return [initializer.text]
  if (ts.isJsxExpression(initializer)) return staticStringValues(initializer.expression, bindings)
  return []
}

export function findLegacyMetricToneViolations(sourceText: string, fileName = 'fixture.tsx'): readonly MetricToneViolation[] {
  const source = ts.createSourceFile(fileName, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const violations: MetricToneViolation[] = []
  const visit = (node: ts.Node) => {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tagName = ts.isIdentifier(node.tagName) ? node.tagName.text : undefined
      if (tagName === 'Metric') {
        const toneAttribute = node.attributes.properties.find(
          (property): property is ts.JsxAttribute => ts.isJsxAttribute(property) && property.name.text === 'tone',
        )
        for (const value of toneAttribute ? jsxAttributeStaticStringValues(toneAttribute) : []) {
          if ((legacyMetricTones as readonly string[]).includes(value)) {
            violations.push({ fileName, line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1, tone: value as LegacyMetricTone })
          }
        }
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  return violations
}

function findTsxFiles(directory: string): readonly string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = resolve(directory, entry)
    return statSync(path).isDirectory() ? findTsxFiles(path) : path.endsWith('.tsx') ? [path] : []
  })
}

function findCssFiles(directory: string): readonly string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = resolve(directory, entry)
    return statSync(path).isDirectory() ? findCssFiles(path) : path.endsWith('.css') ? [path] : []
  })
}

export function findUnsupportedFontWeights(sourceText: string): readonly string[] {
  const violations: string[] = []
  parseCss(sourceText).walkDecls((declaration) => {
    if (normalizedProperty(declaration) !== 'font-weight') return
    const parent = declaration.parent
    if (parent?.type === 'atrule' && decodeCssEscapes(parent.name).toLowerCase() === 'font-face') return
    const value = declaration.value.trim()
    if (!allowedFontWeights.has(value)) violations.push(declarationValue(declaration))
  })
  return violations
}

export function findUnsupportedLetterSpacing(sourceText: string): readonly string[] {
  const violations: string[] = []
  parseCss(sourceText).walkDecls((declaration) => {
    if (normalizedProperty(declaration) !== 'letter-spacing') return
    const value = declaration.value.trim()
    if (!isZeroLetterSpacing(value) && !allowedTrackingValues.has(value)) violations.push(declarationValue(declaration))
  })
  return violations
}

function splitCssValue(value: string): readonly string[] {
  const tokens: string[] = []
  let token = ''
  let quote = ''
  let depth = 0
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index]!
    if (quote) {
      token += character
      if (character === quote && value[index - 1] !== '\\') quote = ''
    } else if (character === '"' || character === "'") {
      quote = character
      token += character
    } else if (character === '(') {
      depth += 1
      token += character
    } else if (character === ')') {
      depth -= 1
      token += character
    } else if (/\s/u.test(character) && depth === 0) {
      if (token) tokens.push(token)
      token = ''
    } else {
      token += character
    }
  }
  if (token) tokens.push(token)
  return tokens
}

export function findUnsupportedFontShorthands(sourceText: string): readonly string[] {
  const violations: string[] = []
  parseCss(sourceText).walkDecls((declaration) => {
    if (normalizedProperty(declaration) !== 'font') return
    const value = declaration.value.trim()
    if (/^(?:inherit|initial|revert(?:-layer)?|unset)$/iu.test(value)) return
    const tokens = splitCssValue(value)
    const explicitWeight = tokens.find((token) => /^(?:[1-9]\d{0,3}|bold|bolder|lighter)$/iu.test(token))
    if (explicitWeight && !allowedFontWeights.has(explicitWeight)) violations.push(declarationValue(declaration))
  })
  return violations
}

function staticStyleValue(expression: ts.Expression | undefined, bindings: StaticBindings): string | undefined {
  if (!expression) return undefined
  if (ts.isNumericLiteral(expression) || ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) return expression.text
  if (ts.isParenthesizedExpression(expression)) return staticStyleValue(expression.expression, bindings)
  if (ts.isIdentifier(expression)) {
    const bound = bindings.get(expression.text)
    return bound ? staticStyleValue(bound, bindings) : undefined
  }
  return undefined
}

export function findInlineTypographyViolations(sourceText: string, fileName = 'fixture.tsx'): readonly string[] {
  const source = ts.createSourceFile(fileName, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const bindings = collectBindings(source)
  const violations: string[] = []
  const inspectObject = (object: ts.ObjectLiteralExpression, seen = new Set<ts.ObjectLiteralExpression>()) => {
    if (seen.has(object)) return
    seen.add(object)
    for (const property of object.properties) {
      if (ts.isSpreadAssignment(property) && ts.isIdentifier(property.expression)) {
        const bound = bindings.get(property.expression.text)
        if (bound && ts.isObjectLiteralExpression(bound)) inspectObject(bound, seen)
        continue
      }
      if (!ts.isPropertyAssignment(property)) continue
      const name = ts.isIdentifier(property.name) || ts.isStringLiteral(property.name) || ts.isNumericLiteral(property.name) ? property.name.text : undefined
      if (name !== 'fontWeight' && name !== 'letterSpacing') continue
      const value = staticStyleValue(property.initializer, bindings)
      const valid = name === 'fontWeight'
        ? value !== undefined && allowedFontWeights.has(value)
        : value !== undefined && (isZeroLetterSpacing(value) || allowedTrackingValues.has(value))
      if (!valid) violations.push(`${fileName}:${source.getLineAndCharacterOfPosition(property.getStart(source)).line + 1} ${name}=${value ?? '<dynamic>'}`)
    }
  }
  const visit = (node: ts.Node) => {
    if (ts.isJsxAttribute(node) && ts.isIdentifier(node.name) && node.name.text === 'style' && node.initializer && ts.isJsxExpression(node.initializer)) {
      const expression = node.initializer.expression
      if (expression && ts.isObjectLiteralExpression(expression)) inspectObject(expression)
      if (expression && ts.isIdentifier(expression)) {
        const bound = bindings.get(expression.text)
        if (bound && ts.isObjectLiteralExpression(bound)) inspectObject(bound)
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  return violations
}

export function findTypographyTokenViolations(sourceText: string): readonly string[] {
  const definitions = new Map<string, string[]>()
  for (const token of [...trackingTokens, '--mg-text-4xl']) definitions.set(token, [])
  parseCss(sourceText).walkDecls((declaration) => {
    const property = normalizedProperty(declaration)
    if (definitions.has(property)) definitions.get(property)!.push(declaration.value.trim())
  })
  const violations: string[] = []
  for (const token of trackingTokens) {
    const values = definitions.get(token)!
    if (values.length !== 1 || !isZeroLetterSpacing(values[0] ?? '')) violations.push(`${token} must have exactly one zero definition`)
  }
  const displayValues = definitions.get('--mg-text-4xl')!
  if (displayValues.length !== 1) {
    violations.push('--mg-text-4xl must have exactly one definition')
  } else {
    const match = displayValues[0]!.match(/^clamp\(\s*([\d.]+)(px|rem)\s*,[\s\S]*,\s*([\d.]+)(px|rem)\s*\)$/iu)
    const toPixels = (amount: string, unit: string) => Number(amount) * (unit.toLowerCase() === 'rem' ? 16 : 1)
    if (!match || toPixels(match[1]!, match[2]!) !== 42 || toPixels(match[3]!, match[4]!) !== 72) {
      violations.push('--mg-text-4xl must use clamp with a 42px minimum and 72px maximum')
    }
  }
  return violations
}

/** 指标卡的两条布局契约。两条都是真实事故的根因：
 *  1. 原语一旦用命名网格区域（grid-area: icon/body），页面只覆写
 *     grid-template-columns 而没跟着声明同名区域时，图标和正文会一起掉进隐式
 *     区域互相重叠——/campaigns、/business、运行详情侧栏都这么坏过；
 *  2. 指标网格若按视口断点排列，放进详情侧栏这类窄容器仍是多列，
 *     每张卡被挤到几十像素宽，正文被迫一行一个字。 */
export function findMetricLayoutViolations(sourceText: string): readonly string[] {
  const violations: string[] = []
  parseCss(sourceText).walkRules((rule) => {
    if (!/\.mg-metric(?![\w-])|\.mg-metric-(?:icon|body|spark)\b/.test(rule.selector)) return
    rule.walkDecls((declaration) => {
      const property = normalizedProperty(declaration)
      if (property === 'grid-area' || property === 'grid-template-areas') {
        violations.push(`${rule.selector} 不能用 ${property}：页面覆写列数时会让图标与正文重叠`)
      }
    })
  })
  // 三个「列数由容器决定」的网格原语共用同一条判据：写死列数的那一刻，它在窄栏里
  // 挤压、在宽面板里稀疏就成了必然，页面只能各自再补一套断点。
  for (const name of ['.mg-metric-grid', '.mg-facts'] as const) {
    const rule = new RegExp(`\\${name}\\s*\\{([^}]*)\\}`).exec(sourceText)?.[1]
    if (rule === undefined) {
      violations.push(`找不到 ${name} 规则，解析逻辑需要更新`)
    } else if (!/repeat\(\s*auto-(?:fit|fill)/.test(rule)) {
      violations.push(`${name} 必须用 repeat(auto-fit/auto-fill, minmax(...))：按容器自适应，窄容器里才不会把内容挤压、宽容器里才不会留大片空白`)
    }
  }
  const metaRule = /\.mg-meta\s*\{([^}]*)\}/.exec(sourceText)?.[1]
  if (metaRule === undefined) {
    violations.push('找不到 .mg-meta 规则，解析逻辑需要更新')
  } else if (!/flex-wrap:\s*wrap/.test(metaRule)) {
    violations.push('.mg-meta 必须能折行（flex-wrap: wrap）：它的用处就是让一串短事实排成一行、放不下再折，写死不折行就会在窄栏里溢出')
  }
  return violations
}

/** 原语必须给页面留「不靠特异性」的开关。
 *
 *  页面样式和原语的类选择器特异性同为 (0,1,0)，而原语在打包后的样式表里更靠后，
 *  同分靠源序决胜负——页面写 `.somePanel { overflow-y: auto }` 打不过
 *  `.mg-panel { overflow: hidden }`，于是「以为开了内部滚动、其实算出来是 hidden」，
 *  视口一矮内容就被永久裁掉、连滚都滚不出来。检视栏、/invites 的成员表、
 *  /media-agent 的配对表单都栽过这个坑。开关必须是自定义属性（沿继承链传递、
 *  不参与特异性），这条判定把机制本身钉住。
 *
 *  徽标同理：它是内容尺寸的小药丸，一旦成为 grid item 就会被块化、
 *  `flex: 0 0 auto` 失效，父级 align-items/justify-items 的默认值 normal 等于
 *  stretch。stretch 只在尺寸是 auto 时生效，所以两个方向都要钉成 fit-content。 */
export function findPrimitiveEscapeHatchViolations(rawSource: string): readonly string[] {
  const violations: string[] = []
  // 先去注释再按 { } 切规则：注释里解释「页面写 .somePanel { overflow-y: auto }
  // 打不过原语」时带着花括号，[^}]* 会在注释里的那个 } 上收工，把规则体截断——
  // 这条判定第一次跑就被自己的注释绊倒过。
  const sourceText = rawSource.replace(/\/\*[\s\S]*?\*\//g, ' ')
  const panelRule = /\.mg-panel\s*\{([^}]*)\}/.exec(sourceText)?.[1]
  if (panelRule === undefined) {
    violations.push('找不到 .mg-panel 规则，解析逻辑需要更新')
  } else if (!/overflow:\s*var\(--mg-panel-overflow\s*,/.test(panelRule)) {
    violations.push('.mg-panel 的 overflow 必须读 var(--mg-panel-overflow, …)：页面写同名类覆写不了它（同特异性、原语更靠后），只能靠自定义属性开内部滚动')
  }
  const badgeRule = /\.mg-badge\s*\{([^}]*)\}/.exec(sourceText)?.[1]
  if (badgeRule === undefined) {
    violations.push('找不到 .mg-badge 规则，解析逻辑需要更新')
  } else {
    if (!/width:\s*fit-content/.test(badgeRule)) violations.push('.mg-badge 必须写 width: fit-content：成为 grid item 后 justify-items 的默认值等于 stretch，会把徽标横向拉成整条轨道')
    if (!/height:\s*fit-content/.test(badgeRule)) violations.push('.mg-badge 必须写 height: fit-content：成为 grid/flex 子项后 align-items 的默认值等于 stretch，会把徽标纵向拉成整格高')
  }
  return violations
}

function assertMediaTypographyIsCanonical(): void {
  const files = [
    ...findCssFiles(resolve(projectRoot, 'src/media')),
    resolve(projectRoot, 'src/media.auth.css'),
    resolve(projectRoot, 'media.auth.css'),
  ]
  const violations = files.flatMap((fileName) => {
    const relativeName = fileName.slice(projectRoot.length + 1)
    const source = readFileSync(fileName, 'utf8')
    return [
      ...findUnsupportedFontWeights(source).map((weight) => `${relativeName}: font-weight ${weight}`),
      ...findUnsupportedFontShorthands(source).map((font) => `${relativeName}: font ${font}`),
      ...findUnsupportedLetterSpacing(source).map((spacing) => `${relativeName}: letter-spacing ${spacing}`),
    ]
  })
  if (violations.length) throw new Error(`media typography contract failed: ${violations.join(', ')}`)

  const identifierRule = /\.mg-id\s*\{([^}]*)\}/.exec(readFileSync(resolve(projectRoot, 'src/media/mediaPrimitives.css'), 'utf8'))?.[1]
  if (identifierRule === undefined) throw new Error('media metric layout contract failed: 缺少 .mg-id 标识符原语')
  if (!/white-space:\s*nowrap/.test(identifierRule) || !/text-overflow:\s*ellipsis/.test(identifierRule)) {
    throw new Error('media metric layout contract failed: .mg-id 必须单行省略，不能让整串标识符被拦腰截断')
  }

  const metricViolations = findMetricLayoutViolations(readFileSync(resolve(projectRoot, 'src/media/mediaPrimitives.css'), 'utf8'))
  if (metricViolations.length) throw new Error(`media metric layout contract failed: ${metricViolations.join(', ')}`)

  const escapeHatchViolations = findPrimitiveEscapeHatchViolations(readFileSync(resolve(projectRoot, 'src/media/mediaPrimitives.css'), 'utf8'))
  if (escapeHatchViolations.length) throw new Error(`media primitive escape hatch contract failed: ${escapeHatchViolations.join(', ')}`)

  const inlineViolations = findTsxFiles(resolve(projectRoot, 'src/media')).flatMap((fileName) => {
    const relativeName = fileName.slice(projectRoot.length + 1)
    return findInlineTypographyViolations(readFileSync(fileName, 'utf8'), relativeName)
  })
  if (inlineViolations.length) throw new Error(`media inline typography contract failed: ${inlineViolations.join(', ')}`)
}

function assertMetricConsumersUseCanonicalTones(): void {
  const violations = findTsxFiles(resolve(projectRoot, 'src/media')).flatMap((fileName) => {
    const relativeName = fileName.slice(projectRoot.length + 1)
    return findLegacyMetricToneViolations(readFileSync(fileName, 'utf8'), relativeName)
  })
  if (violations.length) {
    const details = violations.map(({ fileName, line, tone }) => `${fileName}:${line} tone="${tone}"`).join(', ')
    throw new Error(`media primitive enhancement failed: legacy Metric tones found: ${details}`)
  }
}

function collectBindings(source: ts.SourceFile): StaticBindings {
  const bindings = new Map<string, ts.Expression>()
  const visit = (node: ts.Node) => {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) bindings.set(node.name.text, node.initializer)
    if (ts.isImportSpecifier(node)) {
      const importedName = node.propertyName?.text ?? node.name.text
      if (classNameHelpers.has(importedName)) bindings.set(node.name.text, ts.factory.createIdentifier(importedName))
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  return bindings
}

function classTokens(node: ts.JsxOpeningLikeElement, bindings: StaticBindings): readonly string[] {
  return node.attributes.properties
    .filter((property): property is ts.JsxAttribute => ts.isJsxAttribute(property) && property.name.text === 'className')
    .flatMap((property) => jsxAttributeStaticStringValues(property, bindings))
    .flatMap((value) => value.split(/\s+/).filter(Boolean))
}

type ResolvedComponent = { source: ts.SourceFile; exportedName: string }

function componentDefinitions(source: ts.SourceFile): ReadonlyMap<string, ts.Node> {
  const definitions = new Map<string, ts.Node>()
  const visit = (node: ts.Node) => {
    if (ts.isFunctionDeclaration(node) && node.name) definitions.set(node.name.text, node)
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer && (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer))) definitions.set(node.name.text, node.initializer)
    ts.forEachChild(node, visit)
  }
  visit(source)
  return definitions
}

function resolveImportedComponent(source: ts.SourceFile, name: string, fromFile: string): ResolvedComponent | undefined {
  for (const statement of source.statements) {
    if (!ts.isImportDeclaration(statement) || !statement.moduleSpecifier || !ts.isStringLiteral(statement.moduleSpecifier)) continue
    const clause = statement.importClause
    if (!clause) continue
    const defaultImport = clause.name?.text === name
    const namedImport = clause.namedBindings && ts.isNamedImports(clause.namedBindings)
      ? clause.namedBindings.elements.find((element) => element.name.text === name)
      : undefined
    if (!defaultImport && !namedImport) continue
    const exportedName = defaultImport ? 'default' : namedImport!.propertyName?.text ?? namedImport!.name.text
    const raw = statement.moduleSpecifier.text
    if (!raw.startsWith('.')) continue
    const base = resolve(dirname(fromFile), raw)
    for (const candidate of [base, `${base}.tsx`, `${base}.ts`, resolve(base, 'index.tsx'), resolve(base, 'index.ts')]) {
      try { return { source: ts.createSourceFile(candidate, readFileSync(candidate, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX), exportedName } } catch { /* unresolved import */ }
    }
  }
  return undefined
}

export function findHeroActionContractViolations(sourceText: string, contract: HeroActionsContract, fileName = 'fixture.tsx', importedSources = new Map<string, string>()): readonly string[] {
  const source = ts.createSourceFile(fileName, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const bindings = collectBindings(source)
  const bindingCache = new Map<ts.SourceFile, StaticBindings>([[source, bindings]])
  const bindingsFor = (file: ts.SourceFile) => {
    const existing = bindingCache.get(file)
    if (existing) return existing
    const next = collectBindings(file)
    bindingCache.set(file, next)
    return next
  }
  const resolvedSources = new Map<string, ts.SourceFile>()
  for (const [name, text] of importedSources) resolvedSources.set(name, ts.createSourceFile(name, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX))
  const regions: Array<{ line: number; primary: number; secondary: number }> = []
  const componentNodes = new Set<ts.Node>()
  const inspectComponent = (name: string, file: ts.SourceFile, depth: number, count: (node: ts.Node, file: ts.SourceFile) => void) => {
    if (depth > 8) return
    const injected = resolvedSources.get(name)
    const imported = injected ? { source: injected, exportedName: name } : resolveImportedComponent(file, name, file.fileName)
    if (imported) {
      const importedDefinition = componentDefinitions(imported.source).get(imported.exportedName) ?? componentDefinitions(imported.source).get(name)
      if (importedDefinition && !componentNodes.has(importedDefinition)) {
        componentNodes.add(importedDefinition)
        if (ts.isFunctionLike(importedDefinition) && importedDefinition.body) count(importedDefinition.body, imported.source)
      }
      return
    }
    const defs = componentDefinitions(file)
    const definition = defs.get(name)
    if (definition && !componentNodes.has(definition)) {
      componentNodes.add(definition)
      if (ts.isFunctionLike(definition)) {
        if (definition.body) count(definition.body, file)
      }
    }
  }
  const visit = (node: ts.Node) => {
    if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) {
      const opening = ts.isJsxElement(node) ? node.openingElement : node
      if (classTokens(opening, bindings).includes('mg-hero-actions')) {
        let primary = 0
        let secondary = 0
        const count = (child: ts.Node, currentFile: ts.SourceFile = source) => {
          if ((ts.isJsxOpeningElement(child) || ts.isJsxSelfClosingElement(child)) && child !== opening) {
            const tokens = classTokens(child, bindingsFor(currentFile))
            if (tokens.includes('mg-btn-primary')) primary += 1
            if (tokens.includes('mg-btn-soft') || tokens.includes('mg-btn-ghost')) secondary += 1
            const childName = ts.isIdentifier(child.tagName) ? child.tagName.text : undefined
            if (childName && /^[A-Z]/u.test(childName)) inspectComponent(childName, currentFile, 1, count)
          }
          if (ts.isJsxExpression(child) && child.expression && ts.isIdentifier(child.expression)) {
            const bound = bindingsFor(currentFile).get(child.expression.text)
            if (bound) count(bound, currentFile)
          }
          ts.forEachChild(child, (nested) => count(nested, currentFile))
        }
        count(node, source)
        regions.push({ line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1, primary, secondary })
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  const violations: string[] = []
  if (contract.mode === 'required' && regions.length !== 1) violations.push(`${fileName}: expected exactly one mg-hero-actions region, found ${regions.length}`)
  if (contract.mode === 'exempt' && regions.length !== 0) violations.push(`${fileName}: exempt surface contains ${regions.length} mg-hero-actions region(s)`)
  for (const region of regions) if (region.primary !== 1 || region.secondary > 2) violations.push(`${fileName}:${region.line} primary=${region.primary} secondary=${region.secondary}`)
  return violations
}

function assertHeroActionContracts(): void {
  const seenSources = new Set<string>()
  const violations = CANONICAL_MEDIA_PAGE_SURFACES.flatMap((surface) => {
    const bindingViolations: string[] = []
    if (seenSources.has(surface.source)) bindingViolations.push(`${surface.id}: duplicate manifest source ${surface.source}`)
    seenSources.add(surface.source)
    if (!surface.heroActions) return [`${surface.id}: hero action contract is missing`]
    if (surface.heroActions.mode === 'exempt' && !surface.heroActions.reason.trim()) return [`${surface.id}: hero action exemption reason is empty`]
    const fileName = resolve(projectRoot, 'src/media', surface.source)
    if (!fileName.endsWith('.tsx')) bindingViolations.push(`${surface.id}: manifest source must be TSX`)
    let sourceText: string
    try {
      sourceText = readFileSync(fileName, 'utf8')
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [...bindingViolations, `${surface.id}: manifest source is missing: ${surface.source}`]
      throw error
    }
    return [...bindingViolations, ...findHeroActionContractViolations(sourceText, surface.heroActions, fileName)]
  })
  if (violations.length) throw new Error(`media hero action contract failed: ${violations.join(', ')}`)
}

function runProjectCheck(): void {
  const primitiveCss = readFileSync(resolve(projectRoot, 'src/media/mediaPrimitives.css'), 'utf8')
  assertFoundationClean(primitiveCss, 'src/media/mediaPrimitives.css')

  const css = [
    primitiveCss,
    readFileSync(resolve(projectRoot, 'src/media/mediaDesignTokens.css'), 'utf8'),
    readFileSync(resolve(projectRoot, 'src/media/mediaStudioTheme.css'), 'utf8'),
  ].join('\n')
  const requireRule = (rule: string) => {
    if (!css.includes(rule)) throw new Error(`media primitive enhancement failed: missing ${rule}`)
  }

  for (const accent of ['studio', 'campaign', 'business', 'desk', 'agent', 'archive']) requireRule(`[data-accent='${accent}']`)
  for (const tone of ['good', 'warn', 'info']) requireRule(`[data-tone='${tone}']`)
  for (const selector of ['.mg-badge', ".mg-tab[data-variant='pill']", '.mg-btn:hover', '.mg-state-art', 'prefers-reduced-motion']) requireRule(selector)
  assertMetricConsumersUseCanonicalTones()
  assertHeroActionContracts()
  const tokenViolations = findTypographyTokenViolations(readFileSync(resolve(projectRoot, 'src/media/mediaDesignTokens.css'), 'utf8'))
  if (tokenViolations.length) throw new Error(`media typography token contract failed: ${tokenViolations.join(', ')}`)
  assertMediaTypographyIsCanonical()
  console.log('media primitive enhancement QA passed: accents, tones, tabs, button hover, state art, reduced motion')
}

function runSelfTest(): void {
  const goodCss = `
    .mg-hero { background: var(--mg-surface); }
    .mg-eyebrow { letter-spacing: 0; }
    .mg-pipeline-step[data-state='current']::before {
      background: color-mix(in srgb, var(--accent-base) 58%, var(--mg-border));
    }
  `
  assertFoundationClean(goodCss, 'in-memory good CSS')

  const badCss: ReadonlyArray<{ label: FoundationViolation; css: string }> = [
    {
      label: 'gradient functions',
      css: '.mg-hero { background: linear-gradient(140deg, var(--mg-surface), var(--mg-bg)); }',
    },
    {
      label: 'decorative .mg-hero pseudo-element',
      css: ".mg-hero::after { content: ''; background: var(--accent-soft); }",
    },
    {
      label: 'nonzero .mg-eyebrow letter spacing',
      css: '.mg-eyebrow { letter-spacing: .11em; }',
    },
  ]

  for (const fixture of badCss) {
    if (!findFoundationViolations(fixture.css).includes(fixture.label)) {
      throw new Error(`media primitive enhancement self-test failed: ${fixture.label} was accepted`)
    }
  }

  const legacyMetricFixture = '<section><Metric tone="mint" /><Metric tone={\'amber\'} /></section>'
  if (!findLegacyMetricToneViolations(legacyMetricFixture).length) {
    throw new Error('media primitive enhancement self-test failed: legacy Metric tone was accepted')
  }

  const unrelatedTextFixture = `
    // <Metric tone="mint" />
    const copy = 'Metric tone="violet"'
    const TrendBar = () => <TrendBar tone="blue" />
    const Good = () => <Metric tone="accent" />
  `
  if (findLegacyMetricToneViolations(unrelatedTextFixture).length) {
    throw new Error('media primitive enhancement self-test failed: unrelated text was rejected')
  }

  for (const value of ['850', '850 !important', '850.0', 'var(--weight)', 'bolder']) {
    if (findUnsupportedFontWeights(`.title { font-weight: ${value}; }`).join(',') !== value) {
      throw new Error(`media primitive enhancement self-test failed: unsupported font weight ${value} was accepted`)
    }
  }
  if (findUnsupportedFontWeights('@font-face { font-weight: 100 900; } .title { font-weight: 700; }').length) {
    throw new Error('media primitive enhancement self-test failed: variable range or canonical font weight was rejected')
  }

  // 容器自适应契约的自测。这三条曾经被错误地嵌在上面那个 if 的花括号里，
  // 等于从来没跑过——自测本身也要能被自测发现。
  const compliantPrimitives = [
    '.mg-metric-grid { grid-template-columns: repeat(auto-fit, minmax(184px, 1fr)); }',
    '.mg-facts { grid-template-columns: repeat(auto-fit, minmax(232px, 1fr)); }',
    '.mg-meta { display: flex; flex-wrap: wrap; }',
  ].join('\n')
  if (findMetricLayoutViolations(`${compliantPrimitives}\n.mg-metric-icon { display: grid; }`).length) {
    throw new Error('media primitive enhancement self-test failed: 合规的容器自适应布局被判为违规')
  }
  if (!findMetricLayoutViolations(`${compliantPrimitives}\n.mg-metric-icon { grid-area: icon; }`).some((line) => line.includes('grid-area'))) {
    throw new Error('media primitive enhancement self-test failed: 命名网格区域没有被抓到')
  }
  if (!findMetricLayoutViolations(compliantPrimitives.replace('repeat(auto-fit, minmax(184px, 1fr))', 'repeat(4, minmax(0, 1fr))')).some((line) => line.includes('.mg-metric-grid'))) {
    throw new Error('media primitive enhancement self-test failed: 固定列数的指标网格没有被抓到')
  }
  if (!findMetricLayoutViolations(compliantPrimitives.replace('repeat(auto-fit, minmax(232px, 1fr))', 'repeat(2, minmax(0, 1fr))')).some((line) => line.includes('.mg-facts'))) {
    throw new Error('media primitive enhancement self-test failed: 固定列数的事实网格没有被抓到')
  }
  if (!findMetricLayoutViolations(compliantPrimitives.replace('flex-wrap: wrap;', '')).some((line) => line.includes('.mg-meta'))) {
    throw new Error('media primitive enhancement self-test failed: 不折行的计数行没有被抓到')
  }
  // 原语逃生开关的自测：合规的写法不许报，缺开关的写法必须报。
  const compliantHatches = [
    '.mg-panel { overflow: var(--mg-panel-overflow, hidden); min-width: 0; }',
    '.mg-badge { display: inline-flex; width: fit-content; height: fit-content; min-height: 28px; }',
  ].join('\n')
  if (findPrimitiveEscapeHatchViolations(compliantHatches).length) {
    throw new Error('media primitive enhancement self-test failed: 合规的原语逃生开关被判为违规')
  }
  if (!findPrimitiveEscapeHatchViolations(compliantHatches.replace('overflow: var(--mg-panel-overflow, hidden)', 'overflow: hidden')).some((line) => line.includes('.mg-panel'))) {
    throw new Error('media primitive enhancement self-test failed: 写死的面板 overflow 没有被抓到')
  }
  if (!findPrimitiveEscapeHatchViolations(compliantHatches.replace('height: fit-content; ', '')).some((line) => line.includes('height: fit-content'))) {
    throw new Error('media primitive enhancement self-test failed: 会被纵向拉伸的徽标没有被抓到')
  }
  if (!findPrimitiveEscapeHatchViolations(compliantHatches.replace('width: fit-content; ', '')).some((line) => line.includes('width: fit-content'))) {
    throw new Error('media primitive enhancement self-test failed: 会被横向拉伸的徽标没有被抓到')
  }
  if (!findUnsupportedFontWeights(String.raw`.title { font\2d weight: 850; }`).length) {
    throw new Error('media primitive enhancement self-test failed: escaped font-weight was accepted')
  }
  if (!findUnsupportedFontShorthands('.title { font: italic 850 1rem/1.4 sans-serif; }').length) {
    throw new Error('media primitive enhancement self-test failed: unsupported font shorthand was accepted')
  }
  if (findUnsupportedFontShorthands('.a { font: inherit; } .b { font: italic 700 1rem/1.4 sans-serif; } .c { font: 0.75rem/1.5 monospace; }').length) {
    throw new Error('media primitive enhancement self-test failed: canonical font shorthand was rejected')
  }
  for (const value of ['.11em', '1px', 'var(--other-track)']) {
    if (findUnsupportedLetterSpacing(`.title { letter-spacing: ${value}; }`).join(',') !== value) {
      throw new Error(`media primitive enhancement self-test failed: unsupported letter spacing ${value} was accepted`)
    }
  }
  if (findUnsupportedLetterSpacing('.a { letter-spacing: 0 !important; } .b { letter-spacing: var(--mg-track-wide); }').length) {
    throw new Error('media primitive enhancement self-test failed: canonical letter spacing was rejected')
  }
  if (!findUnsupportedLetterSpacing(String.raw`.title { letter\2d spacing: .11em; }`).length) {
    throw new Error('media primitive enhancement self-test failed: escaped letter-spacing was accepted')
  }
  const validTokens = ':root { --mg-track-tight: 0; --mg-track-normal: 0px; --mg-track-wide: 0; --mg-text-4xl: clamp(42px, 5vw, 72px); }'
  if (findTypographyTokenViolations(validTokens).length) throw new Error('media primitive enhancement self-test failed: valid typography tokens were rejected')
  for (const fixture of [
    ':root { --mg-track-tight: 0; --mg-track-tight: 0; --mg-track-normal: 0; --mg-track-wide: 0; --mg-text-4xl: clamp(42px, 5vw, 72px); }',
    ':root { --mg-track-tight: 0; --mg-track-normal: 1px; --mg-track-wide: 0; --mg-text-4xl: clamp(42px, 5vw, 72px); }',
    ':root { --mg-track-tight: 0; --mg-track-normal: 0; --mg-track-wide: 0; --mg-text-4xl: clamp(41px, 5vw, 73px); }',
  ]) if (!findTypographyTokenViolations(fixture).length) throw new Error('media primitive enhancement self-test failed: invalid typography token fixture was accepted')

  const inlineFixture = `const Page = () => <div style={{ fontWeight: 850, letterSpacing: '.1em' }} />`
  if (findInlineTypographyViolations(inlineFixture).length !== 2) throw new Error('media primitive enhancement self-test failed: invalid inline typography was accepted')
  const inlineGood = `const weight = 700; const styles = { fontWeight: weight, letterSpacing: 0 }; const Page = () => <div style={styles} />`
  if (findInlineTypographyViolations(inlineGood).length) throw new Error('media primitive enhancement self-test failed: canonical inline typography was rejected')

  const requiredHero: HeroActionsContract = { mode: 'required' }
  const validHero = `const primary = ['mg-btn', 'mg-btn-primary'].join(' '); const Page = () => <div className={['mg-hero-actions', styles.actions].join(' ')}><button className={primary}>Go</button><button className="mg-btn mg-btn-ghost">More</button></div>`
  if (findHeroActionContractViolations(validHero, requiredHero).length) throw new Error('media primitive enhancement self-test failed: valid hero action region was rejected')
  const exemptHero: HeroActionsContract = { mode: 'exempt', reason: 'fixture has no hero action region' }
  if (findHeroActionContractViolations('const Page = () => <div className="mg-hero"><h1>Read only</h1></div>', exemptHero).length) throw new Error('media primitive enhancement self-test failed: manifest exempt hero was rejected')
  if (!findHeroActionContractViolations(validHero, exemptHero).length) throw new Error('media primitive enhancement self-test failed: manifest exempt hero binding was bypassed')
  const invalidHeroes = [
    'const Page = () => <div><button className="mg-btn mg-btn-primary">Go</button></div>',
    'const Page = () => <div className="mg-hero-actions"><button className="mg-btn mg-btn-primary">A</button><button className="mg-btn mg-btn-primary">B</button></div>',
    'const Page = () => <div className="mg-hero-actions"><button className="mg-btn mg-btn-primary">A</button><button className="mg-btn mg-btn-ghost">1</button><button className="mg-btn mg-btn-soft">2</button><button className="mg-btn mg-btn-ghost">3</button></div>',
    'const classes = makeClasses("mg-hero-actions"); const Page = () => <div className={classes}><button className="mg-btn mg-btn-primary">A</button><button className="mg-btn mg-btn-primary">B</button></div>',
    'const MorePrimary = () => <button className={cx("mg-btn", "mg-btn-primary")}>P</button>; const Page = () => <div className="mg-hero-actions"><button className="mg-btn mg-btn-primary">A</button><MorePrimary /></div>',
    'const MoreActions = () => <><button className="mg-btn mg-btn-soft">S1</button><button className="mg-btn mg-btn-ghost">S2</button><button className="mg-btn mg-btn-ghost">S3</button></>; const Page = () => <div className="mg-hero-actions"><button className="mg-btn mg-btn-primary">A</button><MoreActions /></div>',
  ]
  for (const [index, fixture] of invalidHeroes.entries()) {
    if (!findHeroActionContractViolations(fixture, requiredHero).length) throw new Error(`media primitive enhancement self-test failed: invalid hero fixture ${index} was accepted`)
  }
  const importedHero = 'import { MorePrimary } from "./MorePrimary"; const Page = () => <div className="mg-hero-actions"><button className="mg-btn mg-btn-primary">A</button><MorePrimary /></div>'
  const importedSources = new Map([['MorePrimary', 'export const MorePrimary = () => <button className={makeClasses("mg-btn", "mg-btn-primary")}>P</button>']])
  if (!findHeroActionContractViolations(importedHero, requiredHero, 'fixture.tsx', importedSources).length) {
    throw new Error('media primitive enhancement self-test failed: imported primary component bypassed the hero action contract')
  }

  console.log('media primitive enhancement self-test passed: good CSS and canonical Metric tones accepted; gradients, hero pseudo-elements, nonzero eyebrow tracking, and legacy Metric tones rejected')
}

if (process.argv.includes('--self-test')) runSelfTest()
else runProjectCheck()
