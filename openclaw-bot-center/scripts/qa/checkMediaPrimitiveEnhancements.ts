import { readdirSync, readFileSync, statSync } from 'node:fs'
import { resolve } from 'node:path'
import ts from 'typescript'

const projectRoot = resolve(import.meta.dirname, '../..')
type FoundationViolation = 'gradient functions' | 'decorative .mg-hero pseudo-element' | 'nonzero .mg-eyebrow letter spacing'

const gradientFunctionPattern = /\b[a-z-]*gradient\s*\(/i
const heroPseudoElementPattern = /\.mg-hero[^{}]*::?(?:before|after)\b[^{}]*\{/i
const eyebrowRulePattern = /\.mg-eyebrow[^{}]*\{([^{}]*)\}/gi
const letterSpacingPattern = /\bletter-spacing\s*:\s*([^;}]+)/i
const zeroLetterSpacingPattern = /^-?(?:0+\.?0*|\.0+)(?:[a-z%]+)?(?:\s*!important)?$/i
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

function staticStringValues(expression: ts.Expression | undefined): readonly string[] {
  if (!expression) return []
  if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) return [expression.text]
  if (ts.isParenthesizedExpression(expression)) return staticStringValues(expression.expression)
  return []
}

function jsxAttributeStaticStringValues(attribute: ts.JsxAttribute): readonly string[] {
  const initializer = attribute.initializer
  if (!initializer) return []
  if (ts.isStringLiteral(initializer)) return [initializer.text]
  if (ts.isJsxExpression(initializer)) return staticStringValues(initializer.expression)
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

function assertHeroActionContracts(): void {
  const violations: string[] = []
  for (const fileName of findTsxFiles(resolve(projectRoot, 'src/media'))) {
    const sourceText = readFileSync(fileName, 'utf8')
    const source = ts.createSourceFile(fileName, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
    const visit = (node: ts.Node) => {
      if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) {
        const opening = ts.isJsxElement(node) ? node.openingElement : node
        const classText = opening.attributes.properties
          .filter((property): property is ts.JsxAttribute => ts.isJsxAttribute(property) && property.name.text === 'className')
          .flatMap((property) => jsxAttributeStaticStringValues(property))
          .join(' ')
        if (classText.split(/\s+/).includes('mg-hero-actions')) {
          const end = ts.isJsxElement(node) ? node.getEnd() : node.getEnd()
          const block = sourceText.slice(node.getStart(source), end)
          const primaryCount = (block.match(/mg-btn-primary/g) ?? []).length
          const secondaryCount = (block.match(/mg-btn-secondary/g) ?? []).length
          if (primaryCount !== 1 || secondaryCount > 2) {
            violations.push(`${fileName}:${source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1} primary=${primaryCount} secondary=${secondaryCount}`)
          }
        }
      }
      ts.forEachChild(node, visit)
    }
    visit(source)
  }
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

  console.log('media primitive enhancement self-test passed: good CSS and canonical Metric tones accepted; gradients, hero pseudo-elements, nonzero eyebrow tracking, and legacy Metric tones rejected')
}

if (process.argv.includes('--self-test')) runSelfTest()
else runProjectCheck()
