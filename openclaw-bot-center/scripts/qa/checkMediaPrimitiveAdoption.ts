import ts from 'typescript'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import {
  CANONICAL_MEDIA_PAGE_SURFACES,
  CANONICAL_RENDERER_EXEMPTIONS,
  CANONICAL_ROUTE_EXEMPTIONS,
  MEDIA_PRIMITIVES,
  type MediaPrimitive,
  type MediaSurfaceSpec,
} from './mediaPageStructureManifest'

export const PRIMITIVES = MEDIA_PRIMITIVES
export type Primitive = MediaPrimitive
export type SurfaceSpec = MediaSurfaceSpec

type RouteRoot = { ownership?: string; accent?: string; accentExpression?: string; hasPrelude: boolean }
type Markers = Record<Primitive, boolean> & { prelude: boolean; routeRoots: readonly RouteRoot[] }
export type PrimitiveSummary = { eligible: number; adopted: number; percentage: number; exempt: readonly string[] }
export type AdoptionReport = {
  surfaces: number
  results: readonly (SurfaceSpec & { adopted: readonly Primitive[]; missing: readonly string[]; parsed: boolean })[]
  primitives: Readonly<Record<Primitive, PrimitiveSummary>>
  familyCoverage: Readonly<Record<'admin' | 'ordinary', Readonly<Record<'mg-btn' | 'mg-tabs', number>>>>
  violations: readonly string[]
}

const root = resolve(import.meta.dirname, '../..')
const mediaRoot = resolve(root, 'src/media')
export const surfaces: readonly SurfaceSpec[] = CANONICAL_MEDIA_PAGE_SURFACES

function classToken(value: string, token: string) {
  return new RegExp(`(?:^|[^A-Za-z0-9_-])${token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?=$|[^A-Za-z0-9_-])`).test(value)
}

function stringLiterals(initializer: ts.Expression | undefined): readonly string[] {
  if (!initializer) return []
  const values: string[] = []
  const visit = (node: ts.Node) => {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) values.push(node.text)
    ts.forEachChild(node, visit)
  }
  visit(initializer)
  return values
}

function hasClassToken(initializer: ts.Expression | undefined, token: string) {
  return stringLiterals(initializer).some((value) => classToken(value, token))
}

function localCssModuleClassNames(initializer: ts.Expression | undefined): readonly string[] {
  if (!initializer) return []
  const names: string[] = []
  const visit = (node: ts.Node) => {
    if (ts.isPropertyAccessExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'styles') names.push(node.name.text)
    ts.forEachChild(node, visit)
  }
  visit(initializer)
  return names
}

function jsxAttribute(node: ts.JsxOpeningElement | ts.JsxSelfClosingElement, name: string): ts.JsxAttribute | undefined {
  for (const prop of node.attributes.properties) {
    if (ts.isJsxAttribute(prop) && ts.isIdentifier(prop.name) && prop.name.text === name) return prop
  }
  return undefined
}

function jsxStringAttribute(node: ts.JsxOpeningElement | ts.JsxSelfClosingElement, name: string): string | undefined {
  const initializer = jsxAttribute(node, name)?.initializer
  return initializer && ts.isStringLiteral(initializer) ? initializer.text : undefined
}

function jsxExpressionIdentifierAttribute(node: ts.JsxOpeningElement | ts.JsxSelfClosingElement, name: string): string | undefined {
  const initializer = jsxAttribute(node, name)?.initializer
  return initializer && ts.isJsxExpression(initializer) && initializer.expression && ts.isIdentifier(initializer.expression)
    ? initializer.expression.text
    : undefined
}

function collectLocalBindings(source: ts.SourceFile): ReadonlyMap<string, ts.Node> {
  const bindings = new Map<string, ts.Node>()
  const visit = (node: ts.Node) => {
    if (ts.isFunctionDeclaration(node) && node.name) bindings.set(node.name.text, node)
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) bindings.set(node.name.text, node.initializer)
    ts.forEachChild(node, visit)
  }
  visit(source)
  return bindings
}

type ImportedBinding = { importedName: string; moduleSpecifier: string }

function collectImportedBindings(source: ts.SourceFile): ReadonlyMap<string, ImportedBinding> {
  const bindings = new Map<string, ImportedBinding>()
  for (const statement of source.statements) {
    if (!ts.isImportDeclaration(statement) || !statement.importClause) continue
    if (!ts.isStringLiteral(statement.moduleSpecifier)) continue
    const clause = statement.importClause
    const moduleSpecifier = statement.moduleSpecifier.text
    if (clause.name) bindings.set(clause.name.text, { importedName: 'default', moduleSpecifier })
    if (clause.namedBindings && ts.isNamespaceImport(clause.namedBindings)) bindings.set(clause.namedBindings.name.text, { importedName: '*', moduleSpecifier })
    if (clause.namedBindings && ts.isNamedImports(clause.namedBindings)) {
      for (const element of clause.namedBindings.elements) bindings.set(element.name.text, { importedName: element.propertyName?.text ?? element.name.text, moduleSpecifier })
    }
  }
  return bindings
}

function importedPrimitive(
  tag: string | undefined,
  imported: ReadonlyMap<string, ImportedBinding>,
  localBindings: ReadonlyMap<string, ts.Node>,
  expectedNames: readonly string[],
  expectedModule: string,
  fileName: string,
) {
  if (!tag || localBindings.has(tag)) return false
  const binding = imported.get(tag)
  if (!binding || !expectedNames.includes(binding.importedName)) return false
  const fileDirectory = resolve(mediaRoot, fileName, '..')
  return resolve(fileDirectory, binding.moduleSpecifier) === resolve(mediaRoot, expectedModule)
}

function isFunctionLike(node: ts.Node): node is ts.FunctionLikeDeclaration {
  return ts.isFunctionLike(node)
}

function isRenderBinding(node: ts.Node): boolean {
  return isFunctionLike(node) || ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)
}

function isInlineRenderCallback(node: ts.Node): boolean {
  const parent = node.parent
  if (ts.isCallExpression(parent)) return true
  return ts.isJsxExpression(parent) && ts.isJsxAttribute(parent.parent) && ts.isIdentifier(parent.parent.name) && parent.parent.name.text === 'render'
}

function defaultRenderBinding(source: ts.SourceFile, bindings: ReadonlyMap<string, ts.Node>): ts.Node | undefined {
  for (const statement of source.statements) {
    if (ts.isFunctionDeclaration(statement) && statement.name && statement.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.DefaultKeyword)) return statement
    if (ts.isExportAssignment(statement) && !statement.isExportEquals) {
      return ts.isIdentifier(statement.expression) ? bindings.get(statement.expression.text) : statement.expression
    }
  }
  return undefined
}

function looksLikeRenderHelper(name: string): boolean {
  return /^(?:render|build|compose|create|make)[A-Z]/.test(name) || /^[A-Z]/.test(name)
}

const BUILTIN_CALLS = new Set(['Array', 'BigInt', 'Boolean', 'Date', 'Error', 'Number', 'Object', 'String', 'URL'])

function hasPreludeInSubtree(node: ts.Node, bindings: ReadonlyMap<string, ts.Node>, seenBindings = new Set<string>()): boolean {
  let found = false
  const visit = (current: ts.Node) => {
    if (found) return
    if (current !== node && isFunctionLike(current)) {
      if (!isInlineRenderCallback(current)) return
    }
    if (ts.isJsxOpeningElement(current) || ts.isJsxSelfClosingElement(current)) {
      if (jsxAttribute(current, 'data-page-prelude')) {
        found = true
        return
      }
      const tagName = ts.isIdentifier(current.tagName) ? current.tagName.text : undefined
      const binding = tagName ? bindings.get(tagName) : undefined
      if (tagName && binding && !seenBindings.has(tagName)) {
        const nextSeenBindings = new Set(seenBindings)
        nextSeenBindings.add(tagName)
        if (hasPreludeInSubtree(binding, bindings, nextSeenBindings)) {
          found = true
          return
        }
      }
    }
    if (ts.isCallExpression(current) && ts.isIdentifier(current.expression)) {
      const binding = bindings.get(current.expression.text)
      if (binding && !seenBindings.has(current.expression.text)) {
        const nextSeenBindings = new Set(seenBindings)
        nextSeenBindings.add(current.expression.text)
        if (hasPreludeInSubtree(binding, bindings, nextSeenBindings)) {
          found = true
          return
        }
      }
    }
    if (ts.isJsxExpression(current) && current.expression && ts.isIdentifier(current.expression)) {
      const binding = bindings.get(current.expression.text)
      if (binding && !seenBindings.has(current.expression.text)) {
        const nextSeenBindings = new Set(seenBindings)
        nextSeenBindings.add(current.expression.text)
        if (hasPreludeInSubtree(binding, bindings, nextSeenBindings)) {
          found = true
          return
        }
      }
    }
    ts.forEachChild(current, visit)
  }
  visit(node)
  return found
}

function inspectTsx(fileName: string, text: string): { markers: Markers; errors: readonly string[] } {
  const source = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const markers: Markers = { 'mg-panel': false, 'mg-btn': false, 'mg-tabs': false, 'mg-metric-grid': false, 'mg-hero': false, state: false, prelude: false, routeRoots: [] }
  const routeRoots: RouteRoot[] = []
  const bindings = collectLocalBindings(source)
  const imported = collectImportedBindings(source)
  const errors = (source as ts.SourceFile & { parseDiagnostics: readonly ts.Diagnostic[] }).parseDiagnostics.map((diagnostic) => ts.flattenDiagnosticMessageText(diagnostic.messageText, ' '))
  const root = defaultRenderBinding(source, bindings)
  if (!root) errors.push('default export render root is unresolved')
  const pending: ts.Node[] = root ? [root] : []
  const seenNodes = new Set<ts.Node>()
  const unresolved = new Set<string>()
  const enqueue = (name: string) => {
    const binding = bindings.get(name)
    if (binding && isRenderBinding(binding)) {
      if (!seenNodes.has(binding)) pending.push(binding)
      return
    }
    const safeDynamicComponent = name === 'List' || name.endsWith('Icon')
    if (!imported.has(name) && !safeDynamicComponent && looksLikeRenderHelper(name)) unresolved.add(name)
  }
  let hasPreludeMarker = false
  while (pending.length) {
    const renderNode = pending.shift()!
    if (seenNodes.has(renderNode)) continue
    seenNodes.add(renderNode)
    const visit = (node: ts.Node) => {
      if (node !== renderNode && isFunctionLike(node)) {
        if (!isInlineRenderCallback(node)) return
      }
      if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
        const className = jsxAttribute(node, 'className')
        for (const primitive of ['mg-panel', 'mg-btn', 'mg-tabs', 'mg-metric-grid', 'mg-hero'] as const) if (hasClassToken(className?.initializer, primitive)) markers[primitive] = true
        const component = jsxAttribute(node, 'data-component')?.initializer
        const componentValue = component && ts.isStringLiteral(component) ? component.text : undefined
        const localEmptySurface = localCssModuleClassNames(className?.initializer).find((name) => /^(?:emptyState|emptyList|sectionEmpty)$/iu.test(name))
        if (localEmptySurface && componentValue !== 'mg-state') errors.push(`local empty surface styles.${localEmptySurface} must use the shared mg-state primitive`)
        for (const primitive of ['mg-panel', 'mg-btn', 'mg-tabs', 'mg-metric-grid', 'mg-hero'] as const) if (componentValue === primitive) markers[primitive] = true
        if (componentValue === 'mg-state') markers.state = true
        const tag = ts.isIdentifier(node.tagName) ? node.tagName.text : undefined
        if (importedPrimitive(tag, imported, bindings, ['SurfaceState', 'ResourceStateView'], 'ui/SurfaceState', fileName)) markers.state = true
        if (importedPrimitive(tag, imported, bindings, ['Metric'], 'ui/Metric', fileName)) markers['mg-metric-grid'] = true
        if (jsxAttribute(node, 'data-page-prelude')) hasPreludeMarker = true
        if (tag === 'main') {
          const element = ts.isJsxOpeningElement(node) && ts.isJsxElement(node.parent) ? node.parent : node
          routeRoots.push({
            ownership: jsxStringAttribute(node, 'data-page-ownership'),
            accent: jsxStringAttribute(node, 'data-accent'),
            accentExpression: jsxExpressionIdentifierAttribute(node, 'data-accent'),
            hasPrelude: hasPreludeInSubtree(element, bindings),
          })
        }
        if (ts.isIdentifier(node.tagName) && /^[A-Z]/.test(node.tagName.text) && node.tagName.text !== 'Icon' && !node.tagName.text.endsWith('Icon')) enqueue(node.tagName.text)
      }
      if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && !BUILTIN_CALLS.has(node.expression.text)) enqueue(node.expression.text)
      if (ts.isJsxExpression(node) && node.expression && ts.isIdentifier(node.expression)) {
        const binding = bindings.get(node.expression.text)
        if (binding && isRenderBinding(binding)) enqueue(node.expression.text)
      }
      ts.forEachChild(node, visit)
    }
    if (isFunctionLike(renderNode)) {
      if (renderNode.body) visit(renderNode.body)
    } else visit(renderNode)
  }
  for (const name of unresolved) errors.push(`unresolved local render helper: ${name}`)
  markers.prelude = hasPreludeMarker
  markers.routeRoots = routeRoots
  return { markers, errors }
}

function validateManifest(specs: readonly SurfaceSpec[]) {
  if (specs.length !== 24) throw new Error(`media primitive adoption failed: surfaces must equal 24, found ${specs.length}`)
  if (new Set(specs.map((surface) => surface.id)).size !== specs.length) throw new Error('media primitive adoption failed: duplicate surface ID')
  for (const surface of specs) {
    if (!surface.eligible.length) throw new Error(`media primitive adoption failed: ${surface.id} has no primitive eligibility`)
    if (surface.family === 'shared' ? surface.ownership || surface.accent : !(surface.ownership && surface.accent)) throw new Error(`media primitive adoption failed: ${surface.id} has invalid root scope`)
  }
}

type ProductionRoute = { path: string; component?: string; helper?: string }
type RouteExemption = { path: string; reason: string; component?: string; importModule?: string; helper?: string }

function routeComponent(initializer: ts.JsxAttributeValue | undefined): string | undefined {
  if (!initializer || !ts.isJsxExpression(initializer) || !initializer.expression) return undefined
  let component: string | undefined
  const visit = (node: ts.Node) => {
    if (component) return
    if ((ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && ts.isIdentifier(node.tagName) && /^[A-Z]/.test(node.tagName.text)) component = node.tagName.text
    else ts.forEachChild(node, visit)
  }
  visit(initializer.expression)
  return component
}

function routeHelper(initializer: ts.JsxAttributeValue | undefined): string | undefined {
  if (!initializer || !ts.isJsxExpression(initializer) || !initializer.expression || !ts.isCallExpression(initializer.expression)) return undefined
  return ts.isIdentifier(initializer.expression.expression) ? initializer.expression.expression.text : undefined
}

function helperRenderedComponent(helper: string | undefined, bindings: ReadonlyMap<string, ts.Node>): string | undefined {
  if (!helper) return undefined
  const binding = bindings.get(helper)
  if (!binding) return undefined
  let component: string | undefined
  const visit = (node: ts.Node) => {
    if (component) return
    if ((ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && ts.isIdentifier(node.tagName) && /^[A-Z]/.test(node.tagName.text)) component = node.tagName.text
    else ts.forEachChild(node, visit)
  }
  visit(binding)
  return component
}

function collectProductionRoutes(sourceText: string): { routes: readonly ProductionRoute[]; imports: ReadonlyMap<string, ImportedBinding>; errors: readonly string[] } {
  const source = ts.createSourceFile('src/media/MediaStudioApp.tsx', sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const routes: ProductionRoute[] = []
  const bindings = collectLocalBindings(source)
  const root = defaultRenderBinding(source, bindings)
  const errors = (source as ts.SourceFile & { parseDiagnostics: readonly ts.Diagnostic[] }).parseDiagnostics.map((diagnostic) => ts.flattenDiagnosticMessageText(diagnostic.messageText, ' '))
  if (!root) errors.push('default export render root is unresolved')
  const pending: ts.Node[] = root ? [root] : []
  const seenNodes = new Set<ts.Node>()
  const collectRoutes = (node: ts.Node) => {
    const visit = (current: ts.Node) => {
      if ((ts.isJsxOpeningElement(current) || ts.isJsxSelfClosingElement(current)) && ts.isIdentifier(current.tagName) && current.tagName.text === 'Route') {
        const path = jsxStringAttribute(current, 'path')
        if (path === undefined) routes.push({ path: '<missing>' })
        else {
          const initializer = jsxAttribute(current, 'element')?.initializer
          const helper = routeHelper(initializer)
          routes.push({ path, helper, component: routeComponent(initializer) ?? (path === '/runs' ? helperRenderedComponent(helper, bindings) : undefined) })
        }
      }
      ts.forEachChild(current, visit)
    }
    visit(node)
  }
  while (pending.length) {
    const renderNode = pending.shift()!
    if (seenNodes.has(renderNode)) continue
    seenNodes.add(renderNode)
    const visit = (node: ts.Node) => {
      if (node !== renderNode && isFunctionLike(node) && !isInlineRenderCallback(node)) return
      if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
        const tag = ts.isIdentifier(node.tagName) ? node.tagName.text : undefined
        if (tag === 'Routes') collectRoutes(ts.isJsxOpeningElement(node) && ts.isJsxElement(node.parent) ? node.parent : node)
        if (tag && bindings.has(tag) && isRenderBinding(bindings.get(tag)!)) pending.push(bindings.get(tag)!)
      }
      if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
        const binding = bindings.get(node.expression.text)
        if (binding && isRenderBinding(binding)) pending.push(binding)
      }
      ts.forEachChild(node, visit)
    }
    if (isFunctionLike(renderNode)) {
      if (renderNode.body) visit(renderNode.body)
    } else visit(renderNode)
  }
  if (!routes.length) errors.push('reachable production <Routes> registry is unresolved')
  return { routes, imports: collectImportedBindings(source), errors }
}

export function validateProductionRouteBindings(sourceText: string, specs: readonly SurfaceSpec[] = surfaces): readonly string[] {
  const failures: string[] = []
  try {
    validateManifest(specs)
  } catch (error) {
    return [error instanceof Error ? error.message : String(error)]
  }
  const { routes, imports, errors } = collectProductionRoutes(sourceText)
  failures.push(...errors.map((error) => `production route registry parse: ${error}`))
  const visualSurfaces = specs.filter((surface) => surface.family !== 'shared')
  const paths = new Map<string, SurfaceSpec>()
  const components = new Map<string, SurfaceSpec>()
  for (const surface of visualSurfaces) {
    if (!surface.route) {
      failures.push(`${surface.id}: routed visual surface has no route mapping`)
      continue
    }
    const sourceModule = `./${surface.source.replace(/\.[^.]+$/, '')}`
    if (surface.route.importModule !== sourceModule) failures.push(`${surface.id}: route import ${surface.route.importModule} must resolve from source ${surface.source}`)
    if (components.has(surface.route.component)) failures.push(`${surface.id}: duplicate route component mapping ${surface.route.component}`)
    components.set(surface.route.component, surface)
    for (const path of surface.route.paths) {
      if (paths.has(path)) failures.push(`${surface.id}: duplicate manifest route mapping ${path}`)
      paths.set(path, surface)
    }
  }
  const rendererSources = new Set<string>(CANONICAL_RENDERER_EXEMPTIONS.map((exemption) => exemption.source))
  for (const sharedSurface of specs.filter((surface) => surface.family === 'shared')) {
    if (sharedSurface.route) failures.push(`${sharedSurface.id}: shared renderer must not declare a production route`)
    if (!rendererSources.has(sharedSurface.source)) failures.push(`${sharedSurface.id}: shared renderer must declare an explicit renderer exemption`)
  }
  const exemptions = new Map<string, RouteExemption>(CANONICAL_ROUTE_EXEMPTIONS.map((exemption): [string, RouteExemption] => [exemption.path, exemption]))
  for (const path of paths.keys()) if (exemptions.has(path)) failures.push(`manifest route ${path} overlaps an explicit route exemption`)
  const seenProductionPaths = new Set<string>()
  for (const route of routes) {
    if (seenProductionPaths.has(route.path)) failures.push(`production route registry has duplicate path ${route.path}`)
    seenProductionPaths.add(route.path)
    const surface = paths.get(route.path)
    const exemption = exemptions.get(route.path)
    if (!surface && !exemption) {
      failures.push(`production route ${route.path} is not mapped to a visual surface or explicit exemption`)
      continue
    }
    if (surface) {
      const expected = surface.route!
      if (route.component !== expected.component) {
        failures.push(`production route ${route.path} renders ${route.component ?? 'no component'} instead of ${expected.component}`)
        continue
      }
      const binding = imports.get(expected.component)
      if (!binding || binding.moduleSpecifier !== expected.importModule) failures.push(`production route ${route.path} component ${expected.component} must import from ${expected.importModule}`)
    } else if (exemption?.component) {
      if (route.component !== exemption.component) failures.push(`route exemption ${route.path} renders ${route.component ?? 'no component'} instead of ${exemption.component}`)
      const binding = imports.get(exemption.component)
      if (!exemption.importModule || !binding || binding.moduleSpecifier !== exemption.importModule) failures.push(`route exemption ${route.path} component ${exemption.component} must import from ${exemption.importModule ?? '<missing module>'}`)
    } else if (exemption && route.component !== undefined) {
      failures.push(`route exemption ${route.path} must not render component ${route.component}`)
    }
    if (exemption?.helper && route.helper !== exemption.helper) failures.push(`route exemption ${route.path} must use helper ${exemption.helper}`)
  }
  for (const [path, surface] of paths) if (!seenProductionPaths.has(path)) failures.push(`${surface.id}: manifest route ${path} is absent from production route registry`)
  for (const exemption of CANONICAL_ROUTE_EXEMPTIONS) if (!seenProductionPaths.has(exemption.path)) failures.push(`route exemption ${exemption.path} is absent from production route registry`)
  return failures
}

export function inspectSurfaceSources(specs: readonly SurfaceSpec[], texts: ReadonlyMap<string, string | undefined>): AdoptionReport {
  validateManifest(specs)
  const results = specs.map((surface) => {
    const text = texts.get(surface.id)
    if (text === undefined) return { ...surface, adopted: [] as Primitive[], missing: ['source'], parsed: false }
    const { markers, errors } = inspectTsx(surface.source, text)
    const adopted = PRIMITIVES.filter((primitive) => markers[primitive])
    const missing = errors.map((error) => `parse:${error}`)
    if (surface.family === 'shared') {
      if (markers.routeRoots.some((routeRoot) => routeRoot.ownership !== undefined || routeRoot.accent !== undefined) || markers.prelude) missing.push('shared renderer must not declare route-root markers')
    } else if (surface.id === 'workspace-router') {
      if (!markers.routeRoots.length) missing.push('route root <main>')
      for (const [index, routeRoot] of markers.routeRoots.entries()) {
        const label = `route root <main>#${index + 1}`
        if (routeRoot.ownership !== 'router') missing.push(`${label} data-page-ownership=router`)
        if (routeRoot.accentExpression !== 'accent' || routeRoot.accent !== undefined) missing.push(`${label} data-accent={accent}`)
        if (routeRoot.hasPrelude) missing.push(`${label} must not declare data-page-prelude`)
      }
    } else {
      if (!markers.routeRoots.length) missing.push('route root <main>')
      for (const [index, routeRoot] of markers.routeRoots.entries()) {
        const label = `route root <main>#${index + 1}`
        if (routeRoot.ownership !== surface.ownership) missing.push(`${label} data-page-ownership=${surface.ownership}`)
        if (routeRoot.accent !== surface.accent) missing.push(`${label} data-accent=${surface.accent}`)
      }
      if (!markers.routeRoots.some((routeRoot) => routeRoot.hasPrelude)) missing.push('data-page-prelude must be inside a route-root <main>')
    }
    if (!adopted.length) missing.push('shared primitive consumer')
    for (const primitive of surface.eligible) if (!markers[primitive]) missing.push(primitive)
    return { ...surface, adopted, missing, parsed: !errors.length }
  })
  const primitives = Object.fromEntries(PRIMITIVES.map((primitive) => {
    const eligible = results.filter((result) => result.eligible.includes(primitive))
    const adopted = eligible.filter((result) => result.adopted.includes(primitive)).length
    return [primitive, { eligible: eligible.length, adopted, percentage: eligible.length ? adopted / eligible.length : 0, exempt: results.filter((result) => !result.eligible.includes(primitive)).map((result) => result.id) }]
  })) as unknown as Record<Primitive, PrimitiveSummary>
  const familyCoverage = Object.fromEntries(['admin', 'ordinary'].map((family) => [family, Object.fromEntries(['mg-btn', 'mg-tabs'].map((primitive) => [primitive, results.some((result) => result.family === family && result.adopted.includes(primitive as Primitive)) ? 1 : 0]))])) as AdoptionReport['familyCoverage']
  const violations = results.flatMap((result) => result.missing.map((missing) => `${result.id}: ${missing}`))
  for (const primitive of PRIMITIVES) {
    const summary = primitives[primitive]
    if (summary.eligible > 0 && summary.percentage < 0.9) violations.push(`${primitive}: ${summary.adopted}/${summary.eligible} eligible surfaces (${(summary.percentage * 100).toFixed(1)}%) is below 90%`)
  }
  for (const family of ['admin', 'ordinary'] as const) for (const primitive of ['mg-btn', 'mg-tabs'] as const) if (!familyCoverage[family][primitive]) violations.push(`${family} family has no ${primitive} consumer`)
  return { surfaces: specs.length, results, primitives, familyCoverage, violations }
}

export function inspectProject(): AdoptionReport {
  const report = inspectSurfaceSources(surfaces, new Map(surfaces.map((surface) => {
    const file = resolve(mediaRoot, surface.source)
    return [surface.id, existsSync(file) ? readFileSync(file, 'utf8') : undefined]
  })))
  const routeFile = resolve(mediaRoot, 'MediaStudioApp.tsx')
  const routeViolations = existsSync(routeFile)
    ? validateProductionRouteBindings(readFileSync(routeFile, 'utf8'))
    : ['production route registry src/media/MediaStudioApp.tsx is missing']
  return { ...report, violations: [...report.violations, ...routeViolations] }
}

export function formatSummary(report: AdoptionReport): string {
  const values = PRIMITIVES.map((primitive) => {
    const summary = report.primitives[primitive]
    return `${primitive}=${summary.adopted}/${summary.eligible} (${(summary.percentage * 100).toFixed(1)}%)`
  })
  return `media primitive adoption: surfaces=${report.surfaces}; ${values.join('; ')}; admin(btn=${report.familyCoverage.admin['mg-btn']},tabs=${report.familyCoverage.admin['mg-tabs']}); ordinary(btn=${report.familyCoverage.ordinary['mg-btn']},tabs=${report.familyCoverage.ordinary['mg-tabs']})`
}

function expectRejected(label: string, specs: readonly SurfaceSpec[], texts: ReadonlyMap<string, string | undefined>) {
  const report = inspectSurfaceSources(specs, texts)
  if (!report.violations.length) throw new Error(`self-test failed: ${label} was accepted`)
}

function expectThrows(label: string, action: () => void) {
  try {
    action()
  } catch {
    return
  }
  throw new Error(`self-test failed: ${label} was accepted`)
}

function expectAccepted(label: string, specs: readonly SurfaceSpec[], texts: ReadonlyMap<string, string | undefined>) {
  const report = inspectSurfaceSources(specs, texts)
  if (report.violations.length) throw new Error(`self-test failed: ${label} was rejected: ${report.violations.join('; ')}`)
}

function fixtures() {
  const asPage = (body: string, imports = '') => `${imports}\nexport default function Fixture() { return (${body}) }`
  const specs: SurfaceSpec[] = Array.from({ length: 24 }, (_, index) => ({
    id: `fixture-${index}`,
    source: `fixture-${index}.tsx`,
    family: index === 0 ? 'admin' : 'ordinary',
    ownership: index === 0 ? 'governance' : 'personal',
    accent: 'studio',
    eligible: index === 0 ? [...PRIMITIVES] : index === 1 ? ['mg-panel', 'mg-btn', 'mg-tabs'] : ['mg-panel'],
  }))
  const texts = new Map(specs.map((spec, index) => [spec.id, asPage(
    `<main data-page-ownership="${spec.ownership}" data-accent="studio"><section data-page-prelude className="mg-hero" /><section className="mg-panel" />${index < 2 ? '<button className="mg-btn" /><nav className="mg-tabs" />' : ''}${index === 0 ? '<SharedMetric /><SharedState />' : ''}</main>`,
    index === 0 ? "import { Metric as SharedMetric } from './ui/Metric'\nimport { ResourceStateView as SharedState } from './ui/SurfaceState'" : '',
  )]))
  return { specs, texts }
}

function routeFixture(extraRoute = '', omittedPath?: string) {
  const imports = surfaces.filter((surface) => surface.route).map((surface) => `import ${surface.route!.component} from '${surface.route!.importModule}'`).join('\n')
  const routes = surfaces.filter((surface) => surface.route).flatMap((surface) => surface.route!.paths.map((path) => `<Route path="${path}" element={ordinaryRoute('${path}', <${surface.route!.component} />, routePolicy)} />`)).filter((route) => !omittedPath || !route.includes(`path="${omittedPath}"`))
  return `import { Navigate } from 'react-router-dom'\n${imports}\nfunction studioAliasRoute(routePolicy) { return guardedRoute('/runs', null, routePolicy) }\nexport default function Fixture() { return (<Routes><Route path="/" element={<Navigate to="/today" />} />${routes.join('')}<Route path="/runs" element={studioAliasRoute(routePolicy)} />${extraRoute}<Route path="*" element={<Navigate to="/today" />} /></Routes>) }`
}

export function runSelfTest() {
  const { specs, texts } = fixtures()
  const asPage = (body: string, imports = '') => `${imports}\nexport default function Fixture() { return (${body}) }`
  const missing = new Map(texts)
  missing.set('fixture-1', asPage('<main data-page-ownership="personal" data-accent="studio"><section data-page-prelude className="mg-hero" /><section className="mg-panel" /><nav className="mg-tabs" /></main>'))
  expectRejected('missing consumer', specs, missing)
  expectThrows('duplicate surface', () => inspectSurfaceSources([...specs.slice(0, 23), specs[0]], texts))
  const malformed = new Map(texts)
  malformed.set('fixture-1', asPage('<main data-page-ownership="personal" data-accent="studio"><section className="mg-panel">'))
  expectRejected('malformed TSX', specs, malformed)
  const illegal = new Map(texts)
  illegal.set('fixture-1', asPage('<main data-page-ownership="personal" data-accent="studio"><section data-page-prelude className="copy-mg-panel" data-component="mg-panel-copy" /><button className="copy-mg-btn" data-component="mg-btn-copy" /><nav className="copy-mg-tabs" data-component="mg-tabs-copy" /></main>'))
  expectRejected('substring marker', specs, illegal)
  const splitMain = new Map(texts)
  splitMain.set('fixture-1', asPage('<><main data-page-ownership="personal"><section data-page-prelude className="mg-hero" /><section className="mg-panel" /><button className="mg-btn" /><nav className="mg-tabs" /></main><main data-accent="studio"><section className="mg-panel" /></main></>'))
  expectRejected('split route-root main markers', specs, splitMain)
  const sameRoot = new Map(texts)
  sameRoot.set('fixture-1', asPage('<main data-page-ownership="personal" data-accent="studio"><section data-page-prelude className="mg-hero" /><section className="mg-panel" /><button className="mg-btn" /><nav className="mg-tabs" /></main>'))
  expectAccepted('same route-root main markers', specs, sameRoot)
  const unrelatedPrelude = new Map(texts)
  unrelatedPrelude.set('fixture-1', asPage('<><div data-page-prelude /><main data-page-ownership="personal" data-accent="studio"><section className="mg-hero" /><section className="mg-panel" /><button className="mg-btn" /><nav className="mg-tabs" /></main></>'))
  expectRejected('unrelated prelude marker', specs, unrelatedPrelude)
  const unusedHelper = new Map(texts)
  unusedHelper.set('fixture-0', asPage('<main data-page-ownership="governance" data-accent="studio"><section data-page-prelude className="mg-hero" /><section className="mg-panel" /><button className="mg-btn" /><nav className="legacy-tabs" /></main>') + '\nfunction UnusedTabs() { return <div className="mg-tabs" /> }')
  expectRejected('unused helper marker', specs, unusedHelper)
  const reachableDocumentPreview = new Map(texts)
  reachableDocumentPreview.set('fixture-1', `export default function Fixture() { return (<main data-page-ownership="personal" data-accent="studio"><section data-page-prelude className="mg-hero" /><section className="mg-panel" /><button className="mg-btn" /><DocumentPreview /></main>) }\nfunction DocumentPreview() { return <div className="mg-tabs" /> }`)
  expectAccepted('reachable local DocumentPreview helper', specs, reachableDocumentPreview)
  const unresolvedDocumentPreview = new Map(texts)
  unresolvedDocumentPreview.set('fixture-1', asPage('<main data-page-ownership="personal" data-accent="studio"><section data-page-prelude className="mg-hero" /><section className="mg-panel" /><button className="mg-btn" /><DocumentPreview /></main>'))
  expectRejected('unresolved local DocumentPreview helper', specs, unresolvedDocumentPreview)
  const localFake = new Map(texts)
  localFake.set('fixture-0', `${asPage('<main data-page-ownership="governance" data-accent="studio"><section data-page-prelude className="mg-hero" /><section className="mg-panel" /><button className="mg-btn" /><nav className="mg-tabs" /><Metric /><SurfaceState /></main>')}\nfunction Metric() { return <div /> }\nfunction SurfaceState() { return <div /> }`)
  expectRejected('same-name local Metric and SurfaceState', specs, localFake)
  const wrongAlias = new Map(texts)
  wrongAlias.set('fixture-0', asPage('<main data-page-ownership="governance" data-accent="studio"><section data-page-prelude className="mg-hero" /><section className="mg-panel" /><button className="mg-btn" /><nav className="mg-tabs" /><SharedMetric /><SharedState /></main>', "import { Metric as SharedMetric } from './otherMetric'\nimport { SurfaceState as SharedState } from './otherState'"))
  expectRejected('wrong-module primitive aliases', specs, wrongAlias)
  for (const className of ['emptyState', 'emptyList', 'sectionEmpty']) {
    const localEmptySurface = new Map(texts)
    localEmptySurface.set('fixture-0', asPage(`<main data-page-ownership="governance" data-accent="studio"><section data-page-prelude className="mg-hero" /><section className="mg-panel" /><button className="mg-btn" /><nav className="mg-tabs" /><SharedMetric /><SharedState /><section className={styles.${className}}>Nothing here</section></main>`, "import { Metric as SharedMetric } from './ui/Metric'\nimport { SurfaceState as SharedState } from './ui/SurfaceState'"))
    expectRejected(`local ${className} surface alongside a shared state marker`, specs, localEmptySurface)
  }
  const localInlineHint = new Map(texts)
  localInlineHint.set('fixture-0', asPage('<main data-page-ownership="governance" data-accent="studio"><section data-page-prelude className="mg-hero" /><section className="mg-panel" /><button className="mg-btn" /><nav className="mg-tabs" /><SharedMetric /><SharedState /><span className={styles.emptyHint}>Optional field absent</span></main>', "import { Metric as SharedMetric } from './ui/Metric'\nimport { SurfaceState as SharedState } from './ui/SurfaceState'"))
  expectAccepted('local inline empty hint is not a resource surface', specs, localInlineHint)
  const routerSpecs = specs.map((spec, index) => index === specs.length - 1
    ? { ...spec, id: 'workspace-router', source: 'WorkspaceShellPage.tsx', ownership: 'router' as const, accent: 'studio' as const, eligible: ['state'] as const }
    : spec)
  const routerTexts = new Map(texts)
  routerTexts.delete('fixture-23')
  routerTexts.set('workspace-router', asPage('<main data-page-ownership="router" data-accent={accent}><SharedState /></main>', "import { ResourceStateView as SharedState } from './ui/SurfaceState'"))
  expectAccepted('workspace router marker', routerSpecs, routerTexts)
  const routerOwnershipDrift = new Map(routerTexts)
  routerOwnershipDrift.set('workspace-router', asPage('<main data-page-ownership="personal" data-accent={accent}><SharedState /></main>', "import { ResourceStateView as SharedState } from './ui/SurfaceState'"))
  expectRejected('workspace router ownership drift', routerSpecs, routerOwnershipDrift)
  const routerAccentDrift = new Map(routerTexts)
  routerAccentDrift.set('workspace-router', asPage('<main data-page-ownership="router" data-accent="studio"><SharedState /></main>', "import { ResourceStateView as SharedState } from './ui/SurfaceState'"))
  expectRejected('workspace router accent drift', routerSpecs, routerAccentDrift)
  const routerPreludeDrift = new Map(routerTexts)
  routerPreludeDrift.set('workspace-router', asPage('<main data-page-ownership="router" data-accent={accent}><div data-page-prelude /><SharedState /></main>', "import { ResourceStateView as SharedState } from './ui/SurfaceState'"))
  expectRejected('workspace router prelude drift', routerSpecs, routerPreludeDrift)
  if (validateProductionRouteBindings(routeFixture()).length) throw new Error('self-test failed: matching production route registry was rejected')
  if (!validateProductionRouteBindings(routeFixture('<Route path="/new-surface" element={<NewPage />} />')).length) throw new Error('self-test failed: unmapped production route was accepted')
  if (!validateProductionRouteBindings(routeFixture().replace('<Route path="/runs" element={studioAliasRoute(routePolicy)} />', '<Route path="/runs" element={<WorkboardPage />} />')).some((failure) => failure.includes('route exemption /runs must not render component WorkboardPage'))) throw new Error('self-test failed: route exemption accepted an arbitrary renderer')
  if (!validateProductionRouteBindings(routeFixture().replace("guardedRoute('/runs', null, routePolicy)", "guardedRoute('/runs', <WorkboardPage />, routePolicy)")).some((failure) => failure.includes('route exemption /runs must not render component WorkboardPage'))) throw new Error('self-test failed: route exemption helper hid an arbitrary renderer')
  if (!validateProductionRouteBindings(routeFixture('', '/today')).length) throw new Error('self-test failed: manifest route absent from registry was accepted')
  const deadRouteFixture = `${routeFixture('', '/today')}\nfunction DeadRouteFixture() { return <Routes><Route path="/today" element={<WorkboardPage />} /></Routes> }`
  if (!validateProductionRouteBindings(deadRouteFixture).some((failure) => failure.includes('manifest route /today is absent'))) throw new Error('self-test failed: dead route fixture forged production reachability')
  console.log('media primitive adoption self-test passed: marker, helper reachability, provenance, and bidirectional route-drift red cases rejected; aliases and matching route registry accepted')
}

function main() {
  if (process.argv.includes('--self-test')) return runSelfTest()
  const report = inspectProject()
  if (process.argv.includes('--json')) console.log(JSON.stringify(report, null, 2))
  else console.log(formatSummary(report))
  if (report.violations.length) {
    for (const violation of report.violations) console.error(`- ${violation}`)
    process.exitCode = 1
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main()
