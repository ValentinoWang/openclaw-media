/** 生产 ↔ 演示站一致性质量门禁：证明有人（尤其是 AI）改了 src/media/** 的生产
 *  业务代码时，没有忘记同步更新 src/demo/** 的静态演示站原型。
 *
 *  全部检查都是纯静态分析（读文件 + 解析 AST/文本 + 比较，不起浏览器），设计
 *  目标是秒级完成，因此被放在 build:media 与 build:demo 的最前面：一旦有人漏
 *  改了演示站，第一时间给出「该改哪个文件、该跑什么命令」的可执行提示，而不
 *  是等到又慢又贵的后续步骤失败。
 *
 *  七类断言全部实现为不触碰真实文件的纯函数（Check* 系列），main() 只负责从
 *  事实源（导入或解析源码）取数据喂给这些纯函数——这样 --self-test 才能用内
 *  存假数据独立证明每一类断言在被破坏时确实会失败，参见 runSelfTest()。 */
import { createHash } from 'node:crypto'
import { readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import ts from 'typescript'
import {
  studioAdminRoutes,
  studioOrdinaryRoutes,
  studioOrganizationRoutes,
  studioPersonalRoutes,
  studioTrackRoutes,
} from '../../src/media/mediaStudioRoutePolicy'
import { demoAuthPages, demoRouteGroups, demoStaticRoutes } from '../../src/demo/demoRoutes'
import { demoPersonas } from '../../src/demo/demoPersonas'
import { demoAuthPageDocuments } from '../../src/demo/generatedDemoAuthPages'
import { AUTH_PAGES, transformAuthPage } from '../demo/buildDemoAuthPages'
import { operations } from '../../src/media/generatedBusinessPagesContract'
import demoDataset from '../../src/demo/generatedDemoDataset.json'
import demoCatalog from '../../src/demo/generatedDemoCatalog.json'

const projectRoot = resolve(import.meta.dirname, '../..')

/** 生产已经声明、但演示站的能力目录里刻意没有收录的 capabilityId。
 *  每一条都必须在这里写明原因，否则视为演示站漏做同步。
 *
 *  - document_edit：这个能力不经过「能力启动器 / CreateMediaTaskRequest」，
 *    而是走文档编辑器的“保存修订”单独接口（createArtifactRevision，参见
 *    合同里 x-canonical-capability-id: [document_edit] 挂在
 *    /artifacts/{publicArtifactId}/revisions 而不是 /tasks 下面）。演示站的
 *    能力目录 generatedDemoCatalog.json 只收录经由任务启动器可发起的能力，
 *    所以 document_edit 不出现在里面是预期行为，不是遗漏。
 */
const CATALOG_EXEMPT_CAPABILITY_IDS: ReadonlySet<string> = new Set(['document_edit'])

type RouteGrantGroup = 'admin' | 'personal' | 'organization'
type ExactRouteGrants = Record<RouteGrantGroup, readonly string[]>

// ---------------------------------------------------------------------------
// 断言 1：静态路由覆盖
// ---------------------------------------------------------------------------

function checkStaticRouteCoverage(productionStaticRoutes: readonly string[], demoRoutes: readonly string[]): string[] {
  const demoSet = new Set(demoRoutes)
  const failures: string[] = []
  for (const route of new Set(productionStaticRoutes)) {
    if (demoSet.has(route)) continue
    failures.push(
      `生产路由 ${route} 没有出现在 src/demo/demoRoutes.ts 的 demoRouteGroups 里，改了路由就要同步演示站页面清单` +
        `（demoStaticRoutes 是从 demoRouteGroups 派生出来的，请在合适的分组里补一条 { path: '${route}', label: ... }）。`,
    )
  }
  return failures
}

// ---------------------------------------------------------------------------
// 断言 2：详情（参数化）路由覆盖 —— 正向 + 反向
// ---------------------------------------------------------------------------

type ProductionRoute = { pattern: string; component: string }

/** 按路径段逐一比较：pattern 里 ":xxx" 段匹配 demoRoute 里任意非空段。 */
function routeMatchesPattern(pattern: string, demoRoute: string): boolean {
  const patternSegments = pattern.split('/')
  const demoSegments = demoRoute.split('/')
  if (patternSegments.length !== demoSegments.length) return false
  return patternSegments.every((segment, index) => {
    const demoSegment = demoSegments[index]
    return segment.startsWith(':') ? demoSegment.length > 0 : segment === demoSegment
  })
}

function groupRoutesByComponent(paramRoutes: readonly ProductionRoute[]): ReadonlyMap<string, readonly ProductionRoute[]> {
  const groups = new Map<string, ProductionRoute[]>()
  for (const route of paramRoutes) {
    const list = groups.get(route.component) ?? []
    list.push(route)
    groups.set(route.component, list)
  }
  return groups
}

/** 正向：每个参数化生产路由（按渲染组件去重——两条路径渲染同一个组件视为同一
 *  个页面的两个入口，例如 /runs/:runId 与 /studio/:runId 都渲染
 *  CreationRunDetailPage，只要其中一个有具体实例就足够了）都必须在
 *  demoStaticRoutes 里有至少一个具体实例。 */
function checkDetailRouteForwardCoverage(paramRoutes: readonly ProductionRoute[], demoRoutes: readonly string[]): string[] {
  const failures: string[] = []
  for (const [component, routes] of groupRoutesByComponent(paramRoutes)) {
    const covered = routes.some((route) => demoRoutes.some((demoRoute) => routeMatchesPattern(route.pattern, demoRoute)))
    if (covered) continue
    const patternList = routes.map((route) => route.pattern).join(' / ')
    failures.push(
      `生产参数化路由 ${patternList}（都渲染 <${component} />）在 src/demo/demoRoutes.ts 的 demoStaticRoutes 里没有任何` +
        `具体实例，请在 demoRouteGroups 的“详情页示例”分组里补一条把参数段换成具体 id 的静态路由。`,
    )
  }
  return failures
}

/** 反向：demoStaticRoutes 里的每一条，都必须能被某个生产 <Route>（静态或参数化）匹配上——
 *  演示站不能有生产里不存在的页面。 */
function checkDemoRoutesMatchProduction(
  demoRoutes: readonly string[],
  productionStaticPaths: readonly string[],
  productionParamRoutes: readonly ProductionRoute[],
  routeGroupLabelByPath: ReadonlyMap<string, string>,
): string[] {
  const staticSet = new Set(productionStaticPaths)
  const failures: string[] = []
  for (const demoRoute of demoRoutes) {
    const matchesStatic = staticSet.has(demoRoute)
    const matchesParam = productionParamRoutes.some((route) => routeMatchesPattern(route.pattern, demoRoute))
    if (matchesStatic || matchesParam) continue
    const groupLabel = routeGroupLabelByPath.get(demoRoute) ?? '未知分组'
    failures.push(
      `src/demo/demoRoutes.ts 的 demoStaticRoutes 里的路由 ${demoRoute}（来自「${groupLabel}」分组）匹配不到 ` +
        `src/media/MediaStudioApp.tsx 里任何生产 <Route>（无论静态还是参数化）。演示站不能有生产里不存在的页面，` +
        `请确认该路由是否已在生产下线/改名，并同步从 demoRouteGroups 里删除或改名。`,
    )
  }
  return failures
}

function firstJsxTagName(node: ts.Node): string | undefined {
  let found: string | undefined
  const visit = (current: ts.Node) => {
    if (found) return
    if (ts.isJsxSelfClosingElement(current)) {
      found = current.tagName.getText()
      return
    }
    if (ts.isJsxElement(current)) {
      found = current.openingElement.tagName.getText()
      return
    }
    ts.forEachChild(current, visit)
  }
  visit(node)
  return found
}

function jsxOpeningOf(node: ts.JsxElement | ts.JsxSelfClosingElement): ts.JsxOpeningElement | ts.JsxSelfClosingElement {
  return ts.isJsxElement(node) ? node.openingElement : node
}

function jsxAttr(opening: ts.JsxOpeningElement | ts.JsxSelfClosingElement, name: string): ts.JsxAttribute | undefined {
  return opening.attributes.properties.find(
    (property): property is ts.JsxAttribute => ts.isJsxAttribute(property) && ts.isIdentifier(property.name) && property.name.text === name,
  )
}

/** 解析 src/media/MediaStudioApp.tsx 源码里所有 <Route path="..."> 的值：
 *  忽略 "/" 与 "*"（不是业务页面），带 ":" 的归入参数化路由并记录其渲染组件，
 *  其余归入静态路由。这是任务允许直接解析源码的两处之一。 */
function parseProductionRoutes(appSource: string): { staticPaths: readonly string[]; paramRoutes: readonly ProductionRoute[] } {
  const sourceFile = ts.createSourceFile('MediaStudioApp.tsx', appSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const staticPaths: string[] = []
  const paramRoutes: ProductionRoute[] = []
  const visit = (node: ts.Node) => {
    if (ts.isJsxSelfClosingElement(node) || ts.isJsxElement(node)) {
      const opening = jsxOpeningOf(node)
      if (ts.isIdentifier(opening.tagName) && opening.tagName.text === 'Route') {
        const pathInitializer = jsxAttr(opening, 'path')?.initializer
        const pathValue = pathInitializer && ts.isStringLiteral(pathInitializer) ? pathInitializer.text : undefined
        if (pathValue && pathValue !== '/' && pathValue !== '*') {
          if (pathValue.includes(':')) {
            const elementInitializer = jsxAttr(opening, 'element')?.initializer
            const elementExpression = elementInitializer && ts.isJsxExpression(elementInitializer) ? elementInitializer.expression : undefined
            const component = (elementExpression && firstJsxTagName(elementExpression)) ?? 'unknown'
            paramRoutes.push({ pattern: pathValue, component })
          } else {
            staticPaths.push(pathValue)
          }
        }
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  return { staticPaths, paramRoutes }
}

// ---------------------------------------------------------------------------
// 断言 3：会话授权一致（exactRouteGrants ↔ demoPersonas.session.routeGrants）
// ---------------------------------------------------------------------------

type PersonaGrantFixture = { id: string; label: string; group: RouteGrantGroup; routeGrants: readonly string[] }

function sameOrderedArray(actual: readonly string[], expected: readonly string[]): boolean {
  return actual.length === expected.length && actual.every((value, index) => value === expected[index])
}

function checkRouteGrantsParity(exactRouteGrants: ExactRouteGrants, personas: readonly PersonaGrantFixture[]): string[] {
  const failures: string[] = []
  for (const persona of personas) {
    const expected = exactRouteGrants[persona.group]
    if (sameOrderedArray(persona.routeGrants, expected)) continue
    failures.push(
      `会话授权不一致：src/demo/demoPersonas.ts 里 persona「${persona.label}」（${persona.id}）的 session.routeGrants ` +
        `与 src/media/mediaWebApi.ts 的 exactRouteGrants.${persona.group} 没有逐项按顺序一致` +
        `（期望 [${expected.join(', ')}]，实际 [${persona.routeGrants.join(', ')}]）。生产的 mediaWebSessionSchema` +
        `.superRefine 就是这么校验的，顺序或成员不一致会导致这个会话在生产代码里直接被 zod 拒绝，请同步修改 ` +
        `src/demo/demoPersonas.ts 里对应 persona 的 routeGrants。`,
    )
  }
  return failures
}

function propertyKeyText(name: ts.PropertyName): string | undefined {
  if (ts.isIdentifier(name) || ts.isStringLiteral(name) || ts.isNumericLiteral(name)) return name.text
  return undefined
}

/** 解析 src/media/mediaWebApi.ts 里的 exactRouteGrants 对象（admin/personal/
 *  organization 三组字符串数组）。这是任务允许直接解析源码的第二处：生产的
 *  zod schema 在这个模块内部用它做逐项同序校验，且它没有被导出，只能读源码。 */
function deriveExactRouteGrants(mediaWebApiSource: string): ExactRouteGrants {
  const sourceFile = ts.createSourceFile('mediaWebApi.ts', mediaWebApiSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  let objectLiteral: ts.ObjectLiteralExpression | undefined
  const visit = (node: ts.Node) => {
    if (objectLiteral) return
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.name.text === 'exactRouteGrants' && node.initializer) {
      const initializer = ts.isAsExpression(node.initializer) ? node.initializer.expression : node.initializer
      if (ts.isObjectLiteralExpression(initializer)) objectLiteral = initializer
      return
    }
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  if (!objectLiteral) throw new Error('src/media/mediaWebApi.ts 里找不到 exactRouteGrants 声明，解析逻辑需要更新')

  const result: Partial<Record<RouteGrantGroup, readonly string[]>> = {}
  for (const property of objectLiteral.properties) {
    if (!ts.isPropertyAssignment(property)) continue
    const key = propertyKeyText(property.name)
    if (key !== 'admin' && key !== 'personal' && key !== 'organization') continue
    if (!ts.isArrayLiteralExpression(property.initializer)) {
      throw new Error(`src/media/mediaWebApi.ts 的 exactRouteGrants.${key} 不再是数组字面量，解析逻辑需要更新`)
    }
    result[key] = property.initializer.elements.map((element) => {
      if (!ts.isStringLiteral(element)) {
        throw new Error(`src/media/mediaWebApi.ts 的 exactRouteGrants.${key} 包含非字符串字面量元素，解析逻辑需要更新`)
      }
      return element.text
    })
  }
  if (!result.admin || !result.personal || !result.organization) {
    throw new Error('src/media/mediaWebApi.ts 的 exactRouteGrants 缺少 admin/personal/organization 中的一组')
  }
  return result as ExactRouteGrants
}

/** 与 src/media/mediaWebApi.ts 里 mediaWebSessionSchema.superRefine 的分组选择逻辑保持一致：
 *  role === 'admin' 用 admin 分组；否则按 workspaceMode 是否为 'personal_web' 二选一。 */
function expectedRouteGrantGroup(session: { role: string; workspaceMode: string }): RouteGrantGroup {
  if (session.role === 'admin') return 'admin'
  return session.workspaceMode === 'personal_web' ? 'personal' : 'organization'
}

// ---------------------------------------------------------------------------
// 断言 4：业务接口覆盖
// ---------------------------------------------------------------------------

function checkOperationCoverage(
  contractOperationIds: readonly string[],
  datasetOperationIds: readonly string[],
  backendOwnedOperationIds: readonly string[],
  nonJsonOperationIds: readonly string[],
): string[] {
  const failures: string[] = []
  const contractSet = new Set(contractOperationIds)
  const covered = new Set([...datasetOperationIds, ...backendOwnedOperationIds, ...nonJsonOperationIds])

  for (const operationId of contractOperationIds) {
    if (covered.has(operationId)) continue
    failures.push(
      `合同新增了接口 ${operationId}，演示站既没有数据集条目（src/demo/generatedDemoDataset.json 的 operations）也没有` +
        `在 backendOwnedOperations 里登记，也不是可以从合同里推导出的非 JSON 二进制响应接口。请重新生成数据集` +
        `（npm run generate:demo-dataset）；如果这是一个需要假后端接管的写操作，请在 scripts/demo/demo_seed.py 的 ` +
        `BACKEND_OWNED_OPERATIONS 里登记它。`,
    )
  }
  for (const operationId of covered) {
    if (contractSet.has(operationId)) continue
    failures.push(
      `src/demo/generatedDemoDataset.json（operations / backendOwnedOperations）或从合同推导出的二进制响应列表里，` +
        `包含了合同 contracts/media_web_business_pages.openapi.yaml 里已经不存在的接口 ${operationId}，说明合同瘦身` +
        `/改名后演示数据集没有同步。请重新生成数据集：npm run generate:demo-dataset。`,
    )
  }
  return failures
}

/** 从合同里推导「响应不是 JSON」的接口：对每个 operationId，只看它的 responses
 *  小节（截止到 requestBody，避免把请求体的 application/json 误当成响应），
 *  如果里面完全没有 application/json，就认为是二进制/非 JSON 响应接口
 *  （目前是 getAssetPreview 与 getDocumentResource）。选择从合同推导而不是写
 *  死清单：这样新增的二进制接口会被自动纳入，不需要有人记得同步维护白名单；
 *  如果这个文本推导将来被证明不可靠（例如合同格式大改），可以退回到显式常量
 *  白名单 BINARY_RESPONSE_OPERATIONS，并在常量旁写明每一条的原因。 */
function deriveNonJsonResponseOperations(contractText: string): readonly string[] {
  const operationMatches = [...contractText.matchAll(/operationId:\s*(\S+)/g)]
  const result: string[] = []
  for (let index = 0; index < operationMatches.length; index += 1) {
    const match = operationMatches[index]
    const start = match.index ?? 0
    const end = index + 1 < operationMatches.length ? (operationMatches[index + 1].index ?? contractText.length) : contractText.length
    const block = contractText.slice(start, end)
    const responsesStart = block.indexOf('responses:')
    if (responsesStart === -1) continue
    const requestBodyStart = block.indexOf('requestBody:', responsesStart)
    const responsesBlock = requestBodyStart === -1 ? block.slice(responsesStart) : block.slice(responsesStart, requestBodyStart)
    if (!responsesBlock.includes('application/json')) result.push(match[1])
  }
  return result
}

// ---------------------------------------------------------------------------
// 断言 5：合同摘要
// ---------------------------------------------------------------------------

function checkContractShaMatches(datasetContractSha256: string, actualContractSha256: string): string[] {
  if (datasetContractSha256 === actualContractSha256) return []
  return [
    `业务合同变了但演示数据集没有重新生成：src/demo/generatedDemoDataset.json 的 contractSha256` +
      `（${datasetContractSha256}）与 contracts/media_web_business_pages.openapi.yaml 的实际 sha256` +
      `（${actualContractSha256}）不一致，跑 npm run generate:demo-dataset。`,
  ]
}

// ---------------------------------------------------------------------------
// 断言 6：能力目录覆盖
// ---------------------------------------------------------------------------

function checkCapabilityCatalogCoverage(
  contractCapabilityIds: readonly string[],
  catalogCapabilityIds: readonly string[],
  exemptCapabilityIds: ReadonlySet<string>,
): string[] {
  const catalogSet = new Set(catalogCapabilityIds)
  const failures: string[] = []
  for (const capabilityId of contractCapabilityIds) {
    if (catalogSet.has(capabilityId) || exemptCapabilityIds.has(capabilityId)) continue
    failures.push(
      `合同 CreateMediaTaskRequest.properties.capabilityId.enum 声明的能力 ${capabilityId} 没有出现在 ` +
        `src/demo/generatedDemoCatalog.json 的 capabilities 列表里，也不在 scripts/qa/checkMediaDemoParity.ts 的 ` +
        `CATALOG_EXEMPT_CAPABILITY_IDS 显式豁免名单里。请重新生成演示能力目录；如果这是生产暂未对外开放的能力，把它` +
        `加进 CATALOG_EXEMPT_CAPABILITY_IDS 并写明理由。`,
    )
  }
  return failures
}

/** 解析合同 components.schemas.CreateMediaTaskRequest.properties.capabilityId.enum
 *  的取值列表（生成产物格式统一为 4 空格缩进 schema 名 / 10 空格缩进枚举项，
 *  没有引入完整 YAML 解析器的必要）。 */
function deriveCapabilityEnumFromContract(contractText: string): readonly string[] {
  const schemaMarker = contractText.indexOf('\n    CreateMediaTaskRequest:')
  if (schemaMarker === -1) throw new Error('合同里找不到 components.schemas.CreateMediaTaskRequest，解析逻辑需要更新')
  const propertyMarker = contractText.indexOf('capabilityId:', schemaMarker)
  if (propertyMarker === -1) throw new Error('CreateMediaTaskRequest 里找不到 capabilityId 属性，解析逻辑需要更新')
  const enumMarker = contractText.indexOf('enum:', propertyMarker)
  if (enumMarker === -1) throw new Error('capabilityId 属性里找不到 enum 列表，解析逻辑需要更新')
  const lines = contractText.slice(enumMarker + 'enum:'.length).split('\n').slice(1)
  const values: string[] = []
  for (const line of lines) {
    const match = /^ {10}- (\S+)$/.exec(line)
    if (!match) break
    values.push(match[1])
  }
  if (values.length === 0) throw new Error('capabilityId 的 enum 解析结果为空，合同格式可能已经漂移，解析逻辑需要更新')
  return values
}

// ---------------------------------------------------------------------------
// 断言 7：认证页覆盖
// ---------------------------------------------------------------------------

/** 认证页有两份产物：dist-demo 下的独立静态文件，和内嵌进 SPA 的自包含 HTML
 *  （单文件分发时唯一够得着的那份）。两者必须来自同一个源文件、同一套改写逻辑，
 *  否则「退出登录后的首页」会在其中一种部署方式下悄悄走样或整个消失。 */
function checkEmbeddedAuthPages(demoAuthPagePaths: readonly string[]): string[] {
  const failures: string[] = []
  const embeddedSlugs = demoAuthPageDocuments.map((page) => page.slug)
  for (const path of demoAuthPagePaths) {
    const slug = path.replace(/^\/|\/$/g, '')
    if (!embeddedSlugs.includes(slug as (typeof embeddedSlugs)[number])) {
      failures.push(`认证页 ${path} 没有内嵌版本，单文件分发时打不开；请运行 npm run generate:demo-auth-pages`)
    }
  }
  for (const page of AUTH_PAGES) {
    const embedded = demoAuthPageDocuments.find((item) => item.slug === page.slug)
    if (!embedded) continue
    // 内嵌版把外链样式内联了，正文结构必须仍然与静态版一致：拿 <body> 比对。
    const fresh = transformAuthPage(readFileSync(page.sourcePath, 'utf8'), '/', page.slug)
    const bodyOf = (html: string) => /<body[^>]*>([\s\S]*)<\/body>/.exec(html)?.[1] ?? ''
    if (bodyOf(fresh) !== bodyOf(embedded.html)) {
      failures.push(`内嵌认证页 ${page.slug} 与 ${page.sourcePath.split('/').pop()} 已经不同步，请运行 npm run generate:demo-auth-pages`)
    }
  }
  return failures
}

function checkAuthPageCoverage(authPageEntryKeys: readonly string[], demoAuthPagePaths: readonly string[]): string[] {
  const demoPathSet = new Set(demoAuthPagePaths)
  const failures: string[] = []
  for (const key of authPageEntryKeys) {
    const expectedPath = `/${key}/`
    if (demoPathSet.has(expectedPath)) continue
    failures.push(
      `vite.media.config.ts 的 rollupOptions.input 声明了认证页入口「${key}」，但 src/demo/demoRoutes.ts 的 ` +
        `demoAuthPages 里没有路径为 ${expectedPath} 的对应条目，请在 demoAuthPages 里补上这一页。`,
    )
  }
  return failures
}

function resolveCallSecondArgumentLiteral(expr: ts.Expression): string | undefined {
  if (!ts.isCallExpression(expr)) return undefined
  const argument = expr.arguments[1]
  return argument && ts.isStringLiteral(argument) ? argument.text : undefined
}

/** 解析 vite.media.config.ts 的 rollupOptions.input：只保留值以 .html 结尾、且
 *  key 不是 'index' 的条目——'index' 是主业务 SPA 壳的入口（不是独立认证页），
 *  其余以 .js 结尾的条目（例如 'media.login' 指向 media.login.js 脚本资源）
 *  自然被 .html 过滤掉，不需要单独硬编码。 */
function deriveAuthPageEntryKeys(viteConfigSource: string): readonly string[] {
  const sourceFile = ts.createSourceFile('vite.media.config.ts', viteConfigSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  let inputObject: ts.ObjectLiteralExpression | undefined
  const visit = (node: ts.Node) => {
    if (inputObject) return
    if (ts.isPropertyAssignment(node) && propertyKeyText(node.name) === 'input' && ts.isObjectLiteralExpression(node.initializer)) {
      inputObject = node.initializer
      return
    }
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  if (!inputObject) throw new Error('vite.media.config.ts 里找不到 rollupOptions.input，解析逻辑需要更新')

  const keys: string[] = []
  for (const property of inputObject.properties) {
    if (!ts.isPropertyAssignment(property)) continue
    const key = propertyKeyText(property.name)
    if (!key || key === 'index') continue
    const value = resolveCallSecondArgumentLiteral(property.initializer)
    if (!value || !value.endsWith('.html')) continue
    keys.push(key)
  }
  return keys
}

// ---------------------------------------------------------------------------
// 真实检查：main()
// ---------------------------------------------------------------------------

type DemoDatasetShape = {
  contractSha256: string
  backendOwnedOperations: readonly string[]
  operations: Record<string, unknown>
}

type DemoCatalogShape = {
  capabilities: ReadonlyArray<{ capabilityId: string }>
}

/** 认证页的路径必须跟着部署基址推导，跳转方式必须是可替换的。
 *
 *  写死 '/openclaw/media/login' 的那一版，演示站里点「退出登录」会整页跳到一个
 *  不存在的路径——静态站是 404，打成单文件之后连一个可跳的文档都没有，用户只看到
 *  not found，连登录页长什么样都看不到，更别提组织成员那条 Feishu 授权分支。 */
export function checkAuthNavigationSeam(
  navigationSource: string,
  mediaSources: ReadonlyArray<{ file: string; source: string }>,
  demoEntrySource: string,
): string[] {
  const failures: string[] = []
  if (!/import\.meta\.env\?\.BASE_URL|import\.meta\.env\.BASE_URL/.test(navigationSource)) {
    failures.push('src/media/mediaNavigation.ts 必须从 import.meta.env.BASE_URL 推导认证页路径，而不是写死部署路径')
  }
  if (!/export function installAuthNavigator/.test(navigationSource)) {
    failures.push('src/media/mediaNavigation.ts 必须导出 installAuthNavigator：演示站要把整页跳转换成站内导航')
  }
  for (const { file, source } of mediaSources) {
    if (/['"`]\/openclaw\/media\/(?:login|register|verify|recover|reset)/.test(source)) {
      failures.push(`${file} 写死了生产认证页路径：改用 mediaNavigation 的 authPageUrl / goToAuthPage，路径要跟着部署基址走`)
    }
  }
  if (!/installAuthNavigator\(/.test(demoEntrySource)) {
    failures.push('src/demo/main.tsx 必须调用 installAuthNavigator：否则演示站里的「退出登录」仍会整页跳到不存在的路径')
  }
  return failures
}

function main(): void {
  const failures: string[] = []

  // 1) 静态路由覆盖
  const productionStaticRoutes = [
    ...studioAdminRoutes,
    ...studioOrdinaryRoutes,
    ...studioTrackRoutes,
    ...studioOrganizationRoutes,
    studioPersonalRoutes[0], // '/workspace'；studioPersonalRoutes[1] 是详情页示例值，由断言 2 处理
  ]
  failures.push(...checkStaticRouteCoverage(productionStaticRoutes, demoStaticRoutes))

  // 2) 详情路由覆盖（正向 + 反向）
  const appSource = readFileSync(resolve(projectRoot, 'src/media/MediaStudioApp.tsx'), 'utf8')
  const { staticPaths: productionStaticPaths, paramRoutes } = parseProductionRoutes(appSource)
  failures.push(...checkDetailRouteForwardCoverage(paramRoutes, demoStaticRoutes))
  const routeGroupLabelByPath = new Map<string, string>()
  for (const group of demoRouteGroups) {
    for (const route of group.routes) routeGroupLabelByPath.set(route.path, group.label)
  }
  failures.push(...checkDemoRoutesMatchProduction(demoStaticRoutes, productionStaticPaths, paramRoutes, routeGroupLabelByPath))

  // 3) 会话授权一致
  const mediaWebApiSource = readFileSync(resolve(projectRoot, 'src/media/mediaWebApi.ts'), 'utf8')
  const exactRouteGrants = deriveExactRouteGrants(mediaWebApiSource)
  const personaFixtures: PersonaGrantFixture[] = demoPersonas.map((persona) => ({
    id: persona.id,
    label: persona.label,
    group: expectedRouteGrantGroup(persona.session),
    routeGrants: persona.session.routeGrants,
  }))
  failures.push(...checkRouteGrantsParity(exactRouteGrants, personaFixtures))

  // 4) & 5) & 6)：都依赖业务合同文本
  const contractPath = resolve(projectRoot, 'contracts/media_web_business_pages.openapi.yaml')
  const contractBuffer = readFileSync(contractPath)
  const contractText = contractBuffer.toString('utf8')
  const dataset = demoDataset as DemoDatasetShape
  const catalog = demoCatalog as DemoCatalogShape

  const nonJsonOperationIds = deriveNonJsonResponseOperations(contractText)
  const contractOperationIds = Object.keys(operations)
  const datasetOperationIds = Object.keys(dataset.operations)
  failures.push(...checkOperationCoverage(contractOperationIds, datasetOperationIds, dataset.backendOwnedOperations, nonJsonOperationIds))

  const actualContractSha256 = createHash('sha256').update(contractBuffer).digest('hex')
  failures.push(...checkContractShaMatches(dataset.contractSha256, actualContractSha256))

  const contractCapabilityIds = deriveCapabilityEnumFromContract(contractText)
  const catalogCapabilityIds = catalog.capabilities.map((capability) => capability.capabilityId)
  failures.push(...checkCapabilityCatalogCoverage(contractCapabilityIds, catalogCapabilityIds, CATALOG_EXEMPT_CAPABILITY_IDS))

  // 7) 认证页覆盖
  const viteConfigSource = readFileSync(resolve(projectRoot, 'vite.media.config.ts'), 'utf8')
  const authPageEntryKeys = deriveAuthPageEntryKeys(viteConfigSource)
  failures.push(...checkAuthPageCoverage(authPageEntryKeys, demoAuthPages.map((page) => page.path)))
  failures.push(...checkEmbeddedAuthPages(demoAuthPages.map((page) => page.path)))

  // 8) 认证页导航接缝
  const mediaSourceFiles = readdirSync(resolve(projectRoot, 'src/media'), { recursive: true, encoding: 'utf8' })
    .filter((entry) => /\.tsx?$/.test(entry) && entry !== 'mediaNavigation.ts')
    .map((entry) => ({ file: `src/media/${entry}`, source: readFileSync(resolve(projectRoot, 'src/media', entry), 'utf8') }))
  failures.push(
    ...checkAuthNavigationSeam(
      readFileSync(resolve(projectRoot, 'src/media/mediaNavigation.ts'), 'utf8'),
      mediaSourceFiles,
      readFileSync(resolve(projectRoot, 'src/demo/main.tsx'), 'utf8'),
    ),
  )

  if (failures.length > 0) {
    console.error(`media demo parity: FAIL 发现 ${failures.length} 处生产/演示站不一致：`)
    failures.forEach((failure, index) => console.error(`${index + 1}. ${failure}`))
    process.exitCode = 1
    return
  }

  console.log(
    'media demo parity: PASS ' +
      `staticRoutes=${new Set(productionStaticRoutes).size} paramRoutePatterns=${paramRoutes.length} ` +
      `operations=${contractOperationIds.length} capabilities=${contractCapabilityIds.length} authPages=${authPageEntryKeys.length} embeddedAuthPages=${demoAuthPageDocuments.length} authNavigation=base-derived`,
  )
}

// ---------------------------------------------------------------------------
// 自检：--self-test 用内存假数据证明每一类断言在被破坏时确实会失败
// ---------------------------------------------------------------------------

function expectEmpty(failures: readonly string[], label: string): void {
  if (failures.length !== 0) throw new Error(`self-test failed: ${label} 不应报错，但得到了 ${failures.length} 条：${failures.join(' | ')}`)
}

function expectFailure(failures: readonly string[], pattern: RegExp, label: string): void {
  if (!failures.some((failure) => pattern.test(failure))) {
    throw new Error(`self-test failed: ${label}（未捕获到期望的红用例，实际输出：${JSON.stringify(failures)}）`)
  }
}

function runSelfTest(): void {
  // 1) 静态路由覆盖
  expectEmpty(checkStaticRouteCoverage(['/a', '/b'], ['/a', '/b', '/c']), '静态路由覆盖 green 用例')
  expectFailure(
    checkStaticRouteCoverage(['/a', '/b', '/demo-parity-probe'], ['/a', '/b']),
    /demo-parity-probe[\s\S]*demoRoutes\.ts/u,
    '缺失生产路由必须被拦下',
  )

  // 2) 详情路由覆盖：正向（同组任一实例即满足）+ 反向（演示站不能多出页面）
  const paramRoutesFixture: readonly ProductionRoute[] = [
    { pattern: '/runs/:runId', component: 'CreationRunDetailPage' },
    { pattern: '/studio/:runId', component: 'CreationRunDetailPage' },
    { pattern: '/workspace/preview/:artifactId', component: 'PersonalWorkspaceShellPage' },
  ]
  expectEmpty(
    checkDetailRouteForwardCoverage(paramRoutesFixture, ['/studio/example-run', '/workspace/preview/example-artifact']),
    '同组任一具体实例应满足正向覆盖',
  )
  expectFailure(
    checkDetailRouteForwardCoverage(paramRoutesFixture, ['/studio/example-run']),
    /PersonalWorkspaceShellPage/u,
    '缺少某个组件的具体实例必须被拦下',
  )
  expectEmpty(
    checkDemoRoutesMatchProduction(['/studio/example-run'], ['/today'], paramRoutesFixture, new Map()),
    '反向覆盖 green 用例',
  )
  expectFailure(
    checkDemoRoutesMatchProduction(['/not-a-real-route'], ['/today'], paramRoutesFixture, new Map([['/not-a-real-route', '测试分组']])),
    /not-a-real-route[\s\S]*测试分组/u,
    '演示站多出生产没有的页面必须被拦下',
  )

  // 3) 会话授权一致
  const grantsFixture: ExactRouteGrants = { admin: ['/a', '/b'], personal: ['/c', '/d'], organization: ['/e'] }
  expectEmpty(
    checkRouteGrantsParity(grantsFixture, [{ id: 'admin-persona', label: '管理员', group: 'admin', routeGrants: ['/a', '/b'] }]),
    '会话授权 green 用例',
  )
  expectFailure(
    checkRouteGrantsParity(grantsFixture, [{ id: 'admin-persona', label: '管理员', group: 'admin', routeGrants: ['/b', '/a'] }]),
    /demoPersonas\.ts/u,
    '顺序颠倒必须被拦下',
  )
  expectFailure(
    checkRouteGrantsParity(grantsFixture, [{ id: 'admin-persona', label: '管理员', group: 'admin', routeGrants: ['/a', '/b', '/extra'] }]),
    /demoPersonas\.ts/u,
    '多出的成员必须被拦下',
  )

  // 4) 业务接口覆盖：合同新增未同步、以及数据集里残留合同已删除的接口
  expectEmpty(checkOperationCoverage(['x', 'y', 'z'], ['x', 'y'], [], ['z']), '接口覆盖 green 用例')
  expectFailure(
    checkOperationCoverage(['x', 'y', 'z', 'w'], ['x', 'y'], [], ['z']),
    /接口 w[\s\S]*demo_seed\.py/u,
    '合同新增接口未同步必须被拦下',
  )
  expectFailure(
    checkOperationCoverage(['x', 'y'], ['x', 'y', 'stale'], [], []),
    /stale[\s\S]*generate:demo-dataset/u,
    '数据集里残留合同已删除的接口必须被拦下',
  )

  // 5) 合同摘要
  expectEmpty(checkContractShaMatches('abc123', 'abc123'), '摘要一致 green 用例')
  expectFailure(checkContractShaMatches('abc123', 'def456'), /generate:demo-dataset/u, '摘要不一致必须被拦下')

  // 6) 能力目录覆盖
  expectEmpty(checkCapabilityCatalogCoverage(['cap_a', 'cap_b'], ['cap_a', 'cap_b'], new Set()), '能力目录 green 用例')
  expectEmpty(
    checkCapabilityCatalogCoverage(['cap_a', 'cap_exempt'], ['cap_a'], new Set(['cap_exempt'])),
    '显式豁免的能力应当放行',
  )
  expectFailure(
    checkCapabilityCatalogCoverage(['cap_a', 'cap_missing'], ['cap_a'], new Set()),
    /cap_missing[\s\S]*CATALOG_EXEMPT_CAPABILITY_IDS/u,
    '未豁免的缺失能力必须被拦下',
  )

  // 7) 认证页覆盖
  expectEmpty(checkAuthPageCoverage(['login', 'register'], ['/login/', '/register/']), '认证页 green 用例')
  expectFailure(
    checkAuthPageCoverage(['login', 'sso'], ['/login/']),
    /sso[\s\S]*demoAuthPages/u,
    '新增认证页入口未同步必须被拦下',
  )

  // 8) 认证页导航接缝
  const goodNavigation = 'export function installAuthNavigator() {}\nconst base = import.meta.env?.BASE_URL ?? "/"'
  const goodEntry = 'installAuthNavigator(demoNavigateTo)'
  expectEmpty(
    checkAuthNavigationSeam(goodNavigation, [{ file: 'src/media/X.tsx', source: 'goToAuthPage("login")' }], goodEntry),
    '合规的认证页导航接缝',
  )
  expectFailure(
    checkAuthNavigationSeam(goodNavigation, [{ file: 'src/media/X.tsx', source: "location.assign('/openclaw/media/login')" }], goodEntry),
    /写死了生产认证页路径/,
    '写死认证页路径',
  )
  expectFailure(
    checkAuthNavigationSeam(goodNavigation, [], 'installDemoBackend()'),
    /必须调用 installAuthNavigator/,
    '演示站没有接管认证页跳转',
  )
  expectFailure(
    checkAuthNavigationSeam('export function installAuthNavigator() {}\nconst base = "/openclaw/media/"', [], goodEntry),
    /必须从 import\.meta\.env\.BASE_URL 推导/,
    '认证页路径没有跟着部署基址',
  )

  console.log('media demo parity self-test: PASS 路由覆盖/详情路由/会话授权/接口覆盖/合同摘要/能力目录/认证页/导航接缝共 8 类断言的红绿用例均符合预期')
}

if (process.argv.includes('--self-test')) {
  runSelfTest()
} else {
  main()
}
