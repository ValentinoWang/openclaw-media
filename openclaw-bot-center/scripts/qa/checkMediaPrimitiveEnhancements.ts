import { readdirSync, readFileSync, statSync } from 'node:fs'
import { resolve } from 'node:path'
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
  if (ts.isArrayLiteralExpression(expression)) return expression.elements.flatMap((item) => ts.isSpreadElement(item) ? [] : staticStringValues(item, bindings, seen))
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
  const withoutFontFaces = sourceText.replace(/@font-face\s*\{[^}]*\}/giu, '')
  return [...withoutFontFaces.matchAll(/\bfont-weight\s*:\s*([^;}]+)/giu)]
    .map((match) => match[1].trim())
    .filter((value) => {
      const canonical = value.match(/^(400|500|600|700)(?:\s*!important)?$/iu)
      return !canonical || !allowedFontWeights.has(canonical[1])
    })
}

export function findUnsupportedLetterSpacing(sourceText: string): readonly string[] {
  return [...sourceText.matchAll(/\bletter-spacing\s*:\s*([^;}]+)/giu)]
    .map((match) => match[1].trim())
    .filter((value) => !isZeroLetterSpacing(value) && !allowedTrackingValues.has(value))
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
      ...findUnsupportedLetterSpacing(source).map((spacing) => `${relativeName}: letter-spacing ${spacing}`),
    ]
  })
  if (violations.length) throw new Error(`media typography contract failed: ${violations.join(', ')}`)
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

export function findHeroActionContractViolations(sourceText: string, contract: HeroActionsContract, fileName = 'fixture.tsx'): readonly string[] {
  const source = ts.createSourceFile(fileName, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const bindings = collectBindings(source)
  const regions: Array<{ line: number; primary: number; secondary: number }> = []
  const visit = (node: ts.Node) => {
    if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) {
      const opening = ts.isJsxElement(node) ? node.openingElement : node
      if (classTokens(opening, bindings).includes('mg-hero-actions')) {
        let primary = 0
        let secondary = 0
        const count = (child: ts.Node) => {
          if ((ts.isJsxOpeningElement(child) || ts.isJsxSelfClosingElement(child)) && child !== opening) {
            const tokens = classTokens(child, bindings)
            if (tokens.includes('mg-btn-primary')) primary += 1
            if (tokens.includes('mg-btn-soft') || tokens.includes('mg-btn-ghost')) secondary += 1
          }
          if (ts.isJsxExpression(child) && child.expression && ts.isIdentifier(child.expression)) {
            const bound = bindings.get(child.expression.text)
            if (bound) count(bound)
          }
          ts.forEachChild(child, count)
        }
        count(node)
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
  const violations = CANONICAL_MEDIA_PAGE_SURFACES.flatMap((surface) => {
    if (!surface.heroActions) return [`${surface.id}: hero action contract is missing`]
    if (surface.heroActions.mode === 'exempt' && !surface.heroActions.reason.trim()) return [`${surface.id}: hero action exemption reason is empty`]
    const fileName = resolve(projectRoot, 'src/media', surface.source)
    return findHeroActionContractViolations(readFileSync(fileName, 'utf8'), surface.heroActions, surface.source)
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
  for (const token of ['tight', 'normal', 'wide']) requireRule(`--mg-track-${token}: 0;`)
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
  for (const value of ['.11em', '1px', 'var(--other-track)']) {
    if (findUnsupportedLetterSpacing(`.title { letter-spacing: ${value}; }`).join(',') !== value) {
      throw new Error(`media primitive enhancement self-test failed: unsupported letter spacing ${value} was accepted`)
    }
  }
  if (findUnsupportedLetterSpacing('.a { letter-spacing: 0 !important; } .b { letter-spacing: var(--mg-track-wide); }').length) {
    throw new Error('media primitive enhancement self-test failed: canonical letter spacing was rejected')
  }

  const requiredHero: HeroActionsContract = { mode: 'required' }
  const validHero = `const primary = ['mg-btn', 'mg-btn-primary'].join(' '); const Page = () => <div className={['mg-hero-actions', styles.actions].join(' ')}><button className={primary}>Go</button><button className="mg-btn mg-btn-ghost">More</button></div>`
  if (findHeroActionContractViolations(validHero, requiredHero).length) throw new Error('media primitive enhancement self-test failed: valid hero action region was rejected')
  const invalidHeroes = [
    'const Page = () => <div><button className="mg-btn mg-btn-primary">Go</button></div>',
    'const Page = () => <div className="mg-hero-actions"><button className="mg-btn mg-btn-primary">A</button><button className="mg-btn mg-btn-primary">B</button></div>',
    'const Page = () => <div className="mg-hero-actions"><button className="mg-btn mg-btn-primary">A</button><button className="mg-btn mg-btn-ghost">1</button><button className="mg-btn mg-btn-soft">2</button><button className="mg-btn mg-btn-ghost">3</button></div>',
    'const classes = makeClasses("mg-hero-actions"); const Page = () => <div className={classes}><button className="mg-btn mg-btn-primary">A</button></div>',
  ]
  for (const fixture of invalidHeroes) {
    if (!findHeroActionContractViolations(fixture, requiredHero).length) throw new Error('media primitive enhancement self-test failed: invalid hero action fixture was accepted')
  }

  console.log('media primitive enhancement self-test passed: good CSS and canonical Metric tones accepted; gradients, hero pseudo-elements, nonzero eyebrow tracking, and legacy Metric tones rejected')
}

if (process.argv.includes('--self-test')) runSelfTest()
else runProjectCheck()
