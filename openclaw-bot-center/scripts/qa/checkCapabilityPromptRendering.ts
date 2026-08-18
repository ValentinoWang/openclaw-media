import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { dashboardSchema } from '../../src/schemas/dashboardSchema'

const defaultBaseUrl = 'http://106.52.146.37/openclaw/bots/'
const baseUrl = ensureTrailingSlash(process.env.BOT_CENTER_BASE_URL ?? defaultBaseUrl)
const requiredDataReviewPromptText = '你是 Media bot 的自媒体作品数据复盘分析器'
const forbiddenGenericPromptText = '送入 LLM 的静态提示词模板'
const forbiddenKnowledgeBundleText = 'Knowledge bot AGENTS.md'
const dataReviewPromptMustNotLeakTo = new Set(['selfmedia-cognition', 'cognition', 'retrospective'])
const screenshotDir = process.env.BOT_CENTER_QA_SCREENSHOT_DIR?.trim()
const authCookie = process.env.BOT_CENTER_AUTH_COOKIE?.trim()
const capabilityQaId = process.env.BOT_CENTER_QA_CAPABILITY_ID?.trim()
const reportProgress = process.env.BOT_CENTER_QA_PROGRESS === '1'

function ensureTrailingSlash(value: string) {
  return value.endsWith('/') ? value : `${value}/`
}

function fail(errors: string[]) {
  console.error(errors.map((error) => `- ${error}`).join('\n'))
  process.exit(1)
}

async function loadDashboardData() {
  let lastError: unknown
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await fetch(new URL(`data/openclaw-bot-center.generated.json?qa_attempt=${attempt}`, baseUrl), {
        headers: authCookie ? { Cookie: authCookie } : undefined,
      })
      if (!response.ok) {
        throw new Error(`failed to fetch dashboard data: ${response.status} ${response.statusText}`)
      }
      const parsed = dashboardSchema.safeParse(await response.json())
      if (!parsed.success) {
        throw new Error(`dashboard data failed schema validation: ${parsed.error.message}`)
      }
      return parsed.data
    } catch (error) {
      lastError = error
      if (attempt < 2) await new Promise((resolve) => setTimeout(resolve, 500 * (attempt + 1)))
    }
  }
  throw lastError
}

function newQaPage(browser: import('playwright').Browser, viewport: { width: number; height: number }) {
  return browser.newPage({
    viewport,
    extraHTTPHeaders: authCookie ? { Cookie: authCookie } : undefined,
  })
}

async function openMaintainerCapabilityPage(
  page: import('playwright').Page,
  url: string,
  expectedNodeCount: number,
) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 })
    } catch (error) {
      if (attempt < 2) continue
      throw error
    }
    if (await page.locator('.execution-graph-view:visible').count() === 0) {
      const maintainerButton = page.getByRole('button', { name: '维护' })
      try {
        await maintainerButton.waitFor({ state: 'visible', timeout: 15000 })
        await maintainerButton.click()
      } catch {
        if (attempt < 2) continue
        throw new Error(`maintainer view unavailable at ${url}: ${(await page.locator('body').innerText()).slice(0, 1600)}`)
      }
    }
    try {
      await page.waitForSelector('.execution-node-body pre:visible', { timeout: 15000 })
    } catch (error) {
      if (attempt < 2) continue
      throw error
    }
    const renderedNodeCount = await page.locator('.execution-graph-view button:visible').count()
    if (renderedNodeCount === expectedNodeCount || attempt === 2) return
  }
}

async function waitForRenderedEdges(page: import('playwright').Page, expectedEdgeCount: number) {
  await page.waitForFunction(
    (count) => document.querySelector('.execution-graph-canvas')?.getAttribute('data-layout-ready') === 'true'
      && document.querySelectorAll('.execution-graph-edge').length === count,
    expectedEdgeCount,
    { timeout: 5000 },
  )
}

async function checkRenderedGraphGeometry(
  page: import('playwright').Page,
  graph: Awaited<ReturnType<typeof loadDashboardData>>['capabilities'][number]['executionGraph'],
  context: string,
  errors: string[],
) {
  const findings = await page.locator('.execution-graph-canvas').evaluate((canvasElement, edges) => {
    const canvas = canvasElement as HTMLElement
    const canvasRect = canvas.getBoundingClientRect()
    const nodeElements = [...canvas.querySelectorAll<HTMLElement>('[data-execution-node-id]')]
    const nodeRects = new Map(nodeElements.map((element) => {
      const rect = element.getBoundingClientRect()
      return [element.dataset.executionNodeId ?? '', {
        left: rect.left - canvasRect.left,
        top: rect.top - canvasRect.top,
        right: rect.right - canvasRect.left,
        bottom: rect.bottom - canvasRect.top,
      }]
    }))
    const edgeSamples = new Map<string, Array<{ x: number; y: number; offset: number; total: number }>>()
    const result: string[] = []
    for (const edge of edges) {
      const path = canvas.querySelector<SVGPathElement>(
        `.execution-graph-edge[data-edge-from="${CSS.escape(edge.from)}"][data-edge-to="${CSS.escape(edge.to)}"] > path`,
      )
      if (!path) {
        result.push(`missing path ${edge.from} -> ${edge.to}`)
        continue
      }
      const total = path.getTotalLength()
      const samples: Array<{ x: number; y: number; offset: number; total: number }> = []
      for (let offset = 0; offset <= total; offset += 6) {
        const point = path.getPointAtLength(Math.min(offset, total))
        samples.push({ x: point.x, y: point.y, offset, total })
      }
      if (!samples.length || samples[samples.length - 1].offset < total) {
        const point = path.getPointAtLength(total)
        samples.push({ x: point.x, y: point.y, offset: total, total })
      }
      edgeSamples.set(`${edge.from}\u0000${edge.to}`, samples)
      for (const [nodeId, rect] of nodeRects) {
        if (nodeId === edge.from || nodeId === edge.to) continue
        if (samples.some((point) => point.x > rect.left && point.x < rect.right && point.y > rect.top && point.y < rect.bottom)) {
          result.push(`edge ${edge.from} -> ${edge.to} crosses unrelated node ${nodeId}`)
        }
      }
    }

    const rectangles = [...nodeRects.entries()]
    for (let leftIndex = 0; leftIndex < rectangles.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < rectangles.length; rightIndex += 1) {
        const [leftId, left] = rectangles[leftIndex]
        const [rightId, right] = rectangles[rightIndex]
        if (left.left < right.right - 1 && left.right > right.left + 1 && left.top < right.bottom - 1 && left.bottom > right.top + 1) {
          result.push(`nodes ${leftId} and ${rightId} overlap`)
        }
      }
    }

    for (let leftIndex = 0; leftIndex < edges.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < edges.length; rightIndex += 1) {
        const leftEdge = edges[leftIndex]
        const rightEdge = edges[rightIndex]
        const leftSamples = edgeSamples.get(`${leftEdge.from}\u0000${leftEdge.to}`) ?? []
        const rightSamples = edgeSamples.get(`${rightEdge.from}\u0000${rightEdge.to}`) ?? []
        let run = 0
        let maxRun = 0
        for (const leftPoint of leftSamples) {
          if (leftPoint.offset < 30 || leftPoint.total - leftPoint.offset < 30) {
            run = 0
            continue
          }
          const overlaps = rightSamples.some((rightPoint) =>
            rightPoint.offset >= 30
            && rightPoint.total - rightPoint.offset >= 30
            && Math.hypot(leftPoint.x - rightPoint.x, leftPoint.y - rightPoint.y) < 2.5,
          )
          run = overlaps ? run + 1 : 0
          maxRun = Math.max(maxRun, run)
        }
        if (maxRun * 6 > 24) {
          result.push(`edges ${leftEdge.from} -> ${leftEdge.to} and ${rightEdge.from} -> ${rightEdge.to} overlap for too long`)
        }
        const sharesEndpoint = leftEdge.from === rightEdge.from || leftEdge.from === rightEdge.to
          || leftEdge.to === rightEdge.from || leftEdge.to === rightEdge.to
        if (!sharesEndpoint) {
          let crosses = false
          for (let leftPointIndex = 1; leftPointIndex < leftSamples.length && !crosses; leftPointIndex += 1) {
            for (let rightPointIndex = 1; rightPointIndex < rightSamples.length; rightPointIndex += 1) {
              const firstStart = leftSamples[leftPointIndex - 1]
              const firstEnd = leftSamples[leftPointIndex]
              const secondStart = rightSamples[rightPointIndex - 1]
              const secondEnd = rightSamples[rightPointIndex]
              const one = (firstEnd.x - firstStart.x) * (secondStart.y - firstStart.y)
                - (firstEnd.y - firstStart.y) * (secondStart.x - firstStart.x)
              const two = (firstEnd.x - firstStart.x) * (secondEnd.y - firstStart.y)
                - (firstEnd.y - firstStart.y) * (secondEnd.x - firstStart.x)
              const three = (secondEnd.x - secondStart.x) * (firstStart.y - secondStart.y)
                - (secondEnd.y - secondStart.y) * (firstStart.x - secondStart.x)
              const four = (secondEnd.x - secondStart.x) * (firstEnd.y - secondStart.y)
                - (secondEnd.y - secondStart.y) * (firstEnd.x - secondStart.x)
              if (one * two < -0.01 && three * four < -0.01) {
                crosses = true
                break
              }
            }
          }
          if (crosses) {
            result.push(`rendered edges ${leftEdge.from} -> ${leftEdge.to} and ${rightEdge.from} -> ${rightEdge.to} cross`)
          }
        }
      }
    }

    const outgoing = new Map<string, typeof edges>()
    const incoming = new Map<string, typeof edges>()
    for (const edge of edges) {
      outgoing.set(edge.from, [...(outgoing.get(edge.from) ?? []), edge])
      incoming.set(edge.to, [...(incoming.get(edge.to) ?? []), edge])
    }
    for (const [nodeId, siblings] of [...outgoing, ...incoming]) {
      if (siblings.length < 2) continue
      const useStart = outgoing.get(nodeId) === siblings
      const points = siblings.map((edge) => {
        const samples = edgeSamples.get(`${edge.from}\u0000${edge.to}`) ?? []
        return useStart ? samples[0] : samples[samples.length - 1]
      }).filter(Boolean)
      for (let index = 0; index < points.length; index += 1) {
        for (let siblingIndex = index + 1; siblingIndex < points.length; siblingIndex += 1) {
          if (Math.hypot(points[index].x - points[siblingIndex].x, points[index].y - points[siblingIndex].y) < 4) {
            result.push(`${useStart ? 'outgoing' : 'incoming'} edges at ${nodeId} reuse the same port`)
          }
        }
      }
    }

    const labelBoxes = [...canvas.querySelectorAll<SVGGElement>('.execution-edge-label')].map((label) => ({
      name: label.dataset.edgeLabel ?? '',
      box: label.getBBox(),
    }))
    for (const { box: labelBox } of labelBoxes) {
      for (const [nodeId, rect] of nodeRects) {
        if (labelBox.x < rect.right && labelBox.x + labelBox.width > rect.left
          && labelBox.y < rect.bottom && labelBox.y + labelBox.height > rect.top) {
          result.push(`edge label overlaps node ${nodeId}`)
        }
      }
    }
    for (let leftIndex = 0; leftIndex < labelBoxes.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < labelBoxes.length; rightIndex += 1) {
        const left = labelBoxes[leftIndex]
        const right = labelBoxes[rightIndex]
        if (left.box.x < right.box.x + right.box.width && left.box.x + left.box.width > right.box.x
          && left.box.y < right.box.y + right.box.height && left.box.y + left.box.height > right.box.y) {
          result.push(`edge labels ${left.name} and ${right.name} overlap`)
        }
      }
    }
    return result
  }, graph.edges)
  for (const finding of findings) errors.push(`${context}: ${finding}`)
}

function branchFixtureData(data: Awaited<ReturnType<typeof loadDashboardData>>) {
  const fixture = structuredClone(data)
  const capability = fixture.capabilities.find((item) => item.id === 'creation')
    ?? fixture.capabilities.find((item) => item.executionGraph.nodes.some((node) => node.nodeType === 'actual_llm_prompt'))
  if (!capability) throw new Error('branch fixture requires a capability with an actual LLM prompt')
  const original = capability.executionGraph.nodes
  const actualPrompt = original.find((node) => node.nodeType === 'actual_llm_prompt')
  const entry = original.find((node) => node.nodeType === 'entry') ?? original[0]
  const quality = original.find((node) => node.nodeType === 'quality_check') ?? original.at(-2)!
  const reply = original.find((node) => node.nodeType === 'reply') ?? original.at(-1)!
  if (!actualPrompt) throw new Error('branch fixture actual prompt node is unavailable')
  capability.executionGraph = {
    ...capability.executionGraph,
    id: `${capability.id}-branch-fixture-execution-graph`,
    title: '条件分支渲染 fixture',
    summary: '用于验证 executionGraph.edges 的真实分支、合流和条件标签。',
    nodes: [
      { ...entry, id: 'fixture-entry', title: '接收能力输入' },
      { ...actualPrompt, id: 'fixture-prompt', title: '运行源码定义的 LLM prompt' },
      { ...quality, id: 'fixture-pass', title: '后置校验通过' },
      { ...quality, id: 'fixture-manual', title: '转人工确认', terminalState: 'pending_manual' },
      { ...reply, id: 'fixture-reply', title: '返回明确结果' },
    ],
    edges: [
      { from: 'fixture-entry', to: 'fixture-prompt' },
      { from: 'fixture-prompt', to: 'fixture-pass', label: '校验通过' },
      { from: 'fixture-prompt', to: 'fixture-manual', label: '证据不足' },
      { from: 'fixture-pass', to: 'fixture-reply' },
      { from: 'fixture-manual', to: 'fixture-reply' },
    ],
  }
  const parsed = dashboardSchema.safeParse(fixture)
  if (!parsed.success) throw new Error(`branch fixture failed dashboard schema: ${parsed.error.message}`)
  return { fixture: parsed.data, capabilityId: capability.id }
}

function complexBranchFixtureData(data: Awaited<ReturnType<typeof loadDashboardData>>) {
  const fixture = structuredClone(data)
  const capability = fixture.capabilities.find((item) => item.id === 'creation')
    ?? fixture.capabilities.find((item) => item.executionGraph.nodes.some((node) => node.nodeType === 'actual_llm_prompt'))
  if (!capability) throw new Error('complex branch fixture requires a capability with an actual LLM prompt')
  const original = capability.executionGraph.nodes
  const entry = original.find((node) => node.nodeType === 'entry') ?? original[0]
  const actualPrompt = original.find((node) => node.nodeType === 'actual_llm_prompt')
  const quality = original.find((node) => node.nodeType === 'quality_check') ?? original.at(-2)!
  const reply = original.find((node) => node.nodeType === 'reply') ?? original.at(-1)!
  if (!actualPrompt) throw new Error('complex branch fixture actual prompt node is unavailable')
  const qualityNode = (id: string, title: string) => ({ ...quality, id, title })
  capability.executionGraph = {
    ...capability.executionGraph,
    id: `${capability.id}-complex-branch-fixture-execution-graph`,
    title: '复杂分叉与汇合验证',
    summary: '验证三分支、长短不等路径、嵌套分叉、长条件和再次汇合。',
    nodes: [
      { ...entry, id: 'complex-entry', title: '接收能力输入' },
      { ...actualPrompt, id: 'complex-decision', title: '生成结构化处理结果' },
      qualityNode('complex-fast', '直接进入汇合'),
      qualityNode('complex-manual', '补充人工证据'),
      qualityNode('complex-nested', '进入嵌套判断'),
      qualityNode('complex-manual-review', '复核补充证据'),
      qualityNode('complex-nested-a', '执行嵌套路径甲'),
      qualityNode('complex-nested-b', '执行嵌套路径乙'),
      qualityNode('complex-merge', '汇总全部可用结果'),
      { ...reply, id: 'complex-reply', title: '返回最终结果' },
    ],
    edges: [
      { from: 'complex-entry', to: 'complex-decision' },
      { from: 'complex-decision', to: 'complex-fast', label: '结构完整且可以继续执行' },
      { from: 'complex-decision', to: 'complex-manual', label: '关键证据不足，需要人工补充确认' },
      { from: 'complex-decision', to: 'complex-nested', label: '进入补充校验分支' },
      { from: 'complex-fast', to: 'complex-merge' },
      { from: 'complex-manual', to: 'complex-manual-review' },
      { from: 'complex-manual-review', to: 'complex-merge' },
      { from: 'complex-nested', to: 'complex-nested-a', label: '条件甲' },
      { from: 'complex-nested', to: 'complex-nested-b', label: '条件乙' },
      { from: 'complex-nested-a', to: 'complex-merge' },
      { from: 'complex-nested-b', to: 'complex-merge' },
      { from: 'complex-merge', to: 'complex-reply' },
    ],
  }
  const parsed = dashboardSchema.safeParse(fixture)
  if (!parsed.success) throw new Error(`complex branch fixture failed dashboard schema: ${parsed.error.message}`)
  return { fixture: parsed.data, capabilityId: capability.id }
}

async function checkBranchFixture(
  browser: import('playwright').Browser,
  data: Awaited<ReturnType<typeof loadDashboardData>>,
  errors: string[],
) {
  const { fixture, capabilityId } = branchFixtureData(data)
  for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
    const page = await newQaPage(browser, viewport)
    await page.route('**/data/openclaw-bot-center.generated.json*', (route) => route.fulfill({ json: fixture }))
    const url = `${baseUrl}?view=maintainer&branchQa=${viewport.width}#/capabilities/detail/${capabilityId}`
    await openMaintainerCapabilityPage(page, url, 5)
    await waitForRenderedEdges(page, 5)
    const maintenanceMetaColumns = await page.locator('.maintenance-meta-grid').evaluate((element) =>
      window.getComputedStyle(element).gridTemplateColumns.split(' ').filter(Boolean).length,
    )
    const expectedMaintenanceMetaColumns = viewport.width <= 560 ? 1 : 4
    if (maintenanceMetaColumns !== expectedMaintenanceMetaColumns) {
      errors.push(
        `branch fixture rendered ${maintenanceMetaColumns} maintenance metadata columns at ${viewport.width}px, `
        + `expected ${expectedMaintenanceMetaColumns}`,
      )
    }
    const branchLayerSize = await page.locator('[data-execution-node-id][data-graph-rank="2"]').count()
    if (branchLayerSize !== 2) errors.push(`branch fixture rendered ${branchLayerSize} nodes in branch rank at ${viewport.width}px`)
    const branchBoxes = await page.locator('[data-execution-node-id][data-graph-rank="2"]').evaluateAll((elements) =>
      elements.map((element) => {
        const rect = element.getBoundingClientRect()
        return { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
      }),
    )
    if (branchBoxes.length === 2
      && Math.abs((branchBoxes[0].y + branchBoxes[0].height / 2) - (branchBoxes[1].y + branchBoxes[1].height / 2)) > 1) {
      errors.push(`branch fixture stacked same-rank outcomes vertically at ${viewport.width}px`)
    }
    if (branchBoxes.length === 2 && Math.abs(branchBoxes[0].x - branchBoxes[1].x) < 1) {
      errors.push(`branch fixture did not separate same-rank outcomes horizontally at ${viewport.width}px`)
    }
    const graphViewport = await page.locator('.execution-graph-canvas-scroll').evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }))
    if (graphViewport.scrollWidth > graphViewport.clientWidth + 1) {
      errors.push(
        `branch fixture requires horizontal graph scrolling at ${viewport.width}px: `
        + `${graphViewport.scrollWidth}px > ${graphViewport.clientWidth}px`,
      )
    }
    for (const label of ['校验通过', '证据不足']) {
      if (await page.locator(`[data-edge-label="${label}"]`).count() !== 1) {
        errors.push(`branch fixture did not render edge label ${label} at ${viewport.width}px`)
      }
    }
    const overflow = await page.locator('.execution-graph-panel').evaluate((element) => element.scrollWidth - element.clientWidth)
    if (overflow > 1) errors.push(`branch fixture overflowed horizontally by ${overflow}px at ${viewport.width}px`)
    await checkRenderedGraphGeometry(page, fixture.capabilities.find((item) => item.id === capabilityId)!.executionGraph, `branch fixture ${viewport.width}px`, errors)
    await page.locator('.execution-graph-panel').evaluate((element) => element.scrollIntoView({ block: 'start' }))
    const graphBox = await page.locator('.execution-graph-panel').boundingBox()
    const topbarBox = await page.locator('.topbar').boundingBox()
    if (graphBox && topbarBox && graphBox.y < topbarBox.y + topbarBox.height - 1) {
      errors.push(`branch fixture scrolled beneath the sticky topbar at ${viewport.width}px`)
    }
    await page.locator('[data-execution-node-id="fixture-manual"]').click()
    if (await page.locator('[data-execution-node-id="fixture-manual"].manual-terminal-node').count() !== 1) {
      errors.push(`branch fixture did not mark the manual terminal node at ${viewport.width}px`)
    }
    if ((await page.locator('.execution-node-detail').getAttribute('data-terminal-kind')) !== 'manual') {
      errors.push(`branch fixture detail did not expose manual terminal state at ${viewport.width}px`)
    }
    if (screenshotDir && viewport.width > 840) {
      mkdirSync(screenshotDir, { recursive: true })
      await page.addStyleTag({ content: '.topbar { position: static !important; }' })
      await page.locator('.execution-graph-panel').screenshot({ path: join(screenshotDir, 'execution-graph-manual-alignment-1366.png') })
    }
    const manualBodyTitle = await page.locator('.execution-node-body-title').innerText()
    if (manualBodyTitle.includes('源码定义的运行提示词')) errors.push('non-LLM branch node was presented as an actual prompt')
    await page.locator('[data-execution-node-id="fixture-prompt"]').click()
    const promptBodyTitle = await page.locator('.execution-node-body-title').innerText()
    if (!promptBodyTitle.includes('源码定义的运行提示词')) errors.push('LLM branch node did not present its source-defined prompt body')
    if (screenshotDir) {
      mkdirSync(screenshotDir, { recursive: true })
      await page.addStyleTag({ content: '.topbar { position: static !important; }' })
      await page.locator('.execution-graph-panel').screenshot({ path: join(screenshotDir, `execution-graph-branch-${viewport.width}.png`) })
    }
    await page.close()
  }
}

async function checkComplexBranchFixture(
  browser: import('playwright').Browser,
  data: Awaited<ReturnType<typeof loadDashboardData>>,
  errors: string[],
) {
  const { fixture, capabilityId } = complexBranchFixtureData(data)
  const graph = fixture.capabilities.find((item) => item.id === capabilityId)!.executionGraph
  for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
    const page = await newQaPage(browser, viewport)
    await page.route('**/data/openclaw-bot-center.generated.json*', (route) => route.fulfill({ json: fixture }))
    const url = `${baseUrl}?view=maintainer&complexQa=${viewport.width}#/capabilities/detail/${capabilityId}`
    await openMaintainerCapabilityPage(page, url, graph.nodes.length)
    await waitForRenderedEdges(page, graph.edges.length)
    if (await page.locator('.execution-graph-view button:visible').count() !== graph.nodes.length) {
      errors.push(`complex fixture did not render every node at ${viewport.width}px`)
    }
    for (const label of ['结构完整且可以继续执行', '关键证据不足，需要人工补充确认', '进入补充校验分支', '条件甲', '条件乙']) {
      if (await page.locator(`[data-edge-label="${label}"]`).count() !== 1) {
        errors.push(`complex fixture did not render edge label ${label} at ${viewport.width}px`)
      }
    }
    const panelOverflow = await page.locator('.execution-graph-panel').evaluate((element) => element.scrollWidth - element.clientWidth)
    if (panelOverflow > 1) errors.push(`complex fixture overflowed its panel by ${panelOverflow}px at ${viewport.width}px`)
    const graphViewportOverflow = await page.locator('.execution-graph-canvas-scroll').evaluate((element) => element.scrollWidth - element.clientWidth)
    if (graphViewportOverflow > 1) errors.push(`complex fixture overflowed its graph viewport by ${graphViewportOverflow}px at ${viewport.width}px`)
    await checkRenderedGraphGeometry(page, graph, `complex fixture ${viewport.width}px`, errors)
    if (screenshotDir) {
      mkdirSync(screenshotDir, { recursive: true })
      await page.addStyleTag({ content: '.topbar { position: static !important; }' })
      await page.locator('.execution-graph-panel').screenshot({ path: join(screenshotDir, `execution-graph-complex-${viewport.width}.png`) })
    }
    await page.close()
  }
}

async function checkAllCapabilitiesMobile(
  browser: import('playwright').Browser,
  data: Awaited<ReturnType<typeof loadDashboardData>>,
  errors: string[],
) {
  let page = await newQaPage(browser, { width: 390, height: 844 })
  const capabilities = capabilityQaId
    ? data.capabilities.filter((capability) => capability.id === capabilityQaId)
    : data.capabilities
  for (let capabilityIndex = 0; capabilityIndex < capabilities.length; capabilityIndex += 1) {
    if (capabilityIndex > 0 && capabilityIndex % 10 === 0) {
      await page.close()
      page = await newQaPage(browser, { width: 390, height: 844 })
    }
    const capability = capabilities[capabilityIndex]
    if (reportProgress) console.log(`mobile ${capability.id}`)
    const url = `${baseUrl}?view=maintainer&mobileQa=${encodeURIComponent(capability.id)}#/capabilities/detail/${capability.id}`
    await openMaintainerCapabilityPage(page, url, capability.executionGraph.nodes.length)
    await waitForRenderedEdges(page, capability.executionGraph.edges.length)
    const renderedNodeCount = await page.locator('.execution-graph-view button:visible').count()
    if (renderedNodeCount !== capability.executionGraph.nodes.length) {
      errors.push(`${capability.id} mobile rendered ${renderedNodeCount} nodes, expected ${capability.executionGraph.nodes.length}`)
    }
    const panelOverflow = await page.locator('.execution-graph-panel').evaluate((element) => element.scrollWidth - element.clientWidth)
    if (panelOverflow > 1) errors.push(`${capability.id} mobile graph panel overflowed by ${panelOverflow}px`)
    const graphViewportMetrics = await page.locator('.execution-graph-canvas-scroll').evaluate((element) => ({
      overflow: element.scrollWidth - element.clientWidth,
      scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
      nodeWidths: [...element.querySelectorAll<HTMLElement>('[data-execution-node-id]')].map((node) => node.getBoundingClientRect().width),
    }))
    if (graphViewportMetrics.overflow > 1) errors.push(`${capability.id} mobile graph viewport overflowed: ${JSON.stringify(graphViewportMetrics)}`)
    const metaColumns = await page.locator('.maintenance-meta-grid').evaluate((element) =>
      window.getComputedStyle(element).gridTemplateColumns.split(' ').filter(Boolean).length,
    )
    if (metaColumns !== 1) errors.push(`${capability.id} mobile maintenance metadata rendered ${metaColumns} columns`)
    const lastNode = page.locator('[data-execution-node-id]:visible').last()
    const lastNodeId = await lastNode.getAttribute('data-execution-node-id')
    await lastNode.click()
    const mobileDetailLayout = await page.locator('.execution-node-detail').evaluate((detail, selectedNodeId) => {
      const canvas = document.querySelector<HTMLElement>('.execution-graph-canvas')
      const style = window.getComputedStyle(detail)
      return {
        alignedNodeId: detail.dataset.alignedNodeId,
        selectedNodeId,
        marginBlockStart: Number.parseFloat(style.marginBlockStart) || 0,
        detailTop: detail.getBoundingClientRect().top,
        canvasBottom: canvas?.getBoundingClientRect().bottom ?? 0,
      }
    }, lastNodeId)
    if (mobileDetailLayout.alignedNodeId !== lastNodeId || Math.abs(mobileDetailLayout.marginBlockStart) > 0.5) {
      errors.push(`${capability.id} mobile detail retained a desktop offset: ${JSON.stringify(mobileDetailLayout)}`)
    }
    if (mobileDetailLayout.detailTop < mobileDetailLayout.canvasBottom - 1) {
      errors.push(`${capability.id} mobile detail overlapped the graph canvas: ${JSON.stringify(mobileDetailLayout)}`)
    }
    await checkRenderedGraphGeometry(page, capability.executionGraph, `${capability.id} mobile`, errors)
    if (screenshotDir && capabilityQaId === capability.id) {
      mkdirSync(screenshotDir, { recursive: true })
      await page.addStyleTag({ content: '.topbar { position: static !important; }' })
      await page.locator('.execution-graph-panel').screenshot({ path: join(screenshotDir, `execution-graph-${capability.id}-390.png`) })
    }
  }
  await page.close()
}

async function main() {
  const data = await loadDashboardData()
  const errors: string[] = []
  const browser = await chromium.launch({ headless: true })
  let page = await newQaPage(browser, { width: 1366, height: 900 })

  const capabilities = capabilityQaId
    ? data.capabilities.filter((capability) => capability.id === capabilityQaId)
    : data.capabilities
  const desktopCapabilities = process.env.BOT_CENTER_BRANCH_QA_ONLY === '1' ? [] : capabilities
  for (let capabilityIndex = 0; capabilityIndex < desktopCapabilities.length; capabilityIndex += 1) {
    if (capabilityIndex > 0 && capabilityIndex % 10 === 0) {
      await page.close()
      page = await newQaPage(browser, { width: 1366, height: 900 })
    }
    const capability = desktopCapabilities[capabilityIndex]
    if (reportProgress) console.log(`desktop ${capability.id}`)
    const url = `${baseUrl}?qa=${Date.now()}#/capabilities/detail/${capability.id}`
    await openMaintainerCapabilityPage(page, url, capability.executionGraph.nodes.length)
    await waitForRenderedEdges(page, capability.executionGraph.edges.length)

    const mainText = await page.locator('main').innerText()
    const graphNodeButtons = await page.locator('.execution-graph-view button:visible').count()
    const renderedEdges = await page.locator('.execution-graph-edge').count()
    const graphViewportMetrics = await page.locator('.execution-graph-canvas-scroll').evaluate((element) => ({
      overflow: element.scrollWidth - element.clientWidth,
      scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
      nodeWidths: [...element.querySelectorAll<HTMLElement>('[data-execution-node-id]')].map((node) => node.getBoundingClientRect().width),
    }))
    if (graphViewportMetrics.overflow > 1) errors.push(`${capability.id} desktop graph viewport overflowed: ${JSON.stringify(graphViewportMetrics)}`)
    const graphColumns = await page.locator('.execution-graph-debug-layout').evaluate((element) => {
      const style = window.getComputedStyle(element)
      return style.gridTemplateColumns.split(' ').filter(Boolean).length
    })
    await checkRenderedGraphGeometry(page, capability.executionGraph, `${capability.id} desktop`, errors)

    if (!mainText.includes('执行链路与 Prompt 契约')) {
      errors.push(`${capability.id} did not render execution graph debug section`)
    }
    for (const removedExplanation of ['源码定义的 LLM 提示词', '能力中心自动拼出的边界说明', '图来源', '通用翻译器 + 复杂能力 facts adapter']) {
      if (mainText.includes(removedExplanation)) {
        errors.push(`${capability.id} rendered removed execution-graph explanation: ${removedExplanation}`)
      }
    }
    if (mainText.includes('当前未接入单次运行 prompt trace')) {
      errors.push(`${capability.id} rendered the retired runtime prompt trace notice`)
    }
    if (await page.locator('.operator-capability-panel:visible').count() !== 1) {
      errors.push(`${capability.id} maintainer mode did not retain the ordinary capability view above maintenance details`)
    }
    if (await page.locator('.maintenance-details[open]:visible').count() !== 1) {
      errors.push(`${capability.id} maintainer mode did not open the unified bottom maintenance disclosure`)
    }
    const maintenanceDetails = page.locator('.maintenance-details')
    const maintenanceMeta = maintenanceDetails.locator('.maintenance-meta-grid')
    const maintenanceMetaText = await maintenanceMeta.innerText()
    for (const forbiddenLabel of ['能力 ID', 'Canonical Capability', '数据来源']) {
      if (await maintenanceMeta.locator('dt', { hasText: forbiddenLabel }).count() > 0) {
        errors.push(`${capability.id} exposed forbidden maintainer metadata label ${forbiddenLabel}`)
      }
    }
    for (const forbiddenValue of [capability.id, capability.canonicalCapabilityId, data.meta.source, capability.primaryBot]) {
      if (forbiddenValue && maintenanceMetaText.includes(forbiddenValue)) {
        errors.push(`${capability.id} exposed forbidden maintainer metadata value ${forbiddenValue}`)
      }
    }
    const removedMaintenanceHeadings = await maintenanceDetails.locator('h2').allTextContents()
    for (const removedHeading of ['Bot 可见性', '所在流程节点', '相关能力']) {
      if (removedMaintenanceHeadings.some((heading) => heading.trim() === removedHeading)) {
        errors.push(`${capability.id} restored removed maintenance section ${removedHeading}`)
      }
    }
    if (await maintenanceDetails.locator('.maintenance-meta-grid dt', { hasText: '可见 Bot' }).count() > 0) {
      errors.push(`${capability.id} restored visible Bot metadata in capability maintenance details`)
    }
    const autoGeneratedGraph = maintenanceDetails.locator('[data-auto-generated-graph="true"]')
    if (await autoGeneratedGraph.count() !== 1) {
      errors.push(`${capability.id} did not expose one auto-generated execution graph surface`)
    } else {
      const outgoingCounts = new Map<string, number>()
      for (const edge of capability.executionGraph.edges) {
        outgoingCounts.set(edge.from, (outgoingCounts.get(edge.from) ?? 0) + 1)
      }
      const expectedBranchCount = [...outgoingCounts.values()].filter((count) => count > 1).length
      const graphSummary = await autoGeneratedGraph.locator('summary').innerText()
      if (!graphSummary.includes('自动生成') || !graphSummary.includes(`${expectedBranchCount} 处分叉`)) {
        errors.push(`${capability.id} did not render the generated branch count ${expectedBranchCount}`)
      }
    }
    const maintenanceMetaColumns = await page.locator('.maintenance-meta-grid').evaluate((element) =>
      window.getComputedStyle(element).gridTemplateColumns.split(' ').filter(Boolean).length,
    )
    if (maintenanceMetaColumns < 4) {
      errors.push(`${capability.id} maintenance metadata did not use the compact desktop grid`)
    }
    if (graphNodeButtons !== capability.executionGraph.nodes.length) {
      errors.push(
        `${capability.id} rendered ${graphNodeButtons} execution graph node buttons, expected ${capability.executionGraph.nodes.length}`,
      )
    }
    if (renderedEdges !== capability.executionGraph.edges.length) {
      errors.push(`${capability.id} rendered ${renderedEdges} edges, expected ${capability.executionGraph.edges.length}`)
    }
    for (const edge of capability.executionGraph.edges) {
      const rendered = page.locator(`.execution-graph-edge[data-edge-from="${edge.from}"][data-edge-to="${edge.to}"]`)
      if (await rendered.count() !== 1) {
        errors.push(`${capability.id} did not render edge ${edge.from} -> ${edge.to}`)
      } else if (!(await rendered.locator('path').getAttribute('d'))?.trim()) {
        errors.push(`${capability.id} rendered edge ${edge.from} -> ${edge.to} without geometry`)
      }
      if (edge.label && await rendered.locator(`[data-edge-label="${edge.label}"]`).count() !== 1) {
        errors.push(`${capability.id} did not render edge label ${edge.label}`)
      }
      const sourceBranchCount = capability.executionGraph.edges.filter((candidate) => candidate.from === edge.from).length
      if (edge.label && sourceBranchCount > 1) {
        const targetLabels = await page
          .locator(`[data-execution-node-id="${edge.to}"] .incoming-condition-badge`)
          .allTextContents()
        if (!targetLabels.some((label) => label.includes(edge.label!))) {
          errors.push(`${capability.id} target node ${edge.to} did not repeat branch condition ${edge.label}`)
        }
      }
    }
    if (graphColumns < 2) {
      errors.push(`${capability.id} execution graph layout did not render desktop 2-column 2:8 frame`)
    }
    const renderedNodeTexts: string[] = []
    for (let index = 0; index < graphNodeButtons; index += 1) {
      const nodeButton = page.locator('.execution-graph-view button:visible').nth(index)
      const nodeId = await nodeButton.getAttribute('data-execution-node-id')
      const node = capability.executionGraph.nodes.find((candidate) => candidate.id === nodeId)
      if (!node) {
        errors.push(`${capability.id} rendered unknown execution node ${nodeId ?? '<missing-id>'}`)
        continue
      }
      await nodeButton.click()
      try {
        await page.waitForFunction((selectedNodeId) => {
          const nodeElement = document.querySelector<HTMLElement>(`[data-execution-node-id="${CSS.escape(selectedNodeId)}"]`)
          const detailElement = document.querySelector<HTMLElement>(`.execution-node-detail[data-aligned-node-id="${CSS.escape(selectedNodeId)}"]`)
          if (!nodeElement || !detailElement) return false
          return Math.abs(nodeElement.getBoundingClientRect().top - detailElement.getBoundingClientRect().top) <= 1.5
        }, node.id, { timeout: 2000 })
      } catch {
        const alignment = await page.evaluate((selectedNodeId) => {
          const nodeElement = document.querySelector<HTMLElement>(`[data-execution-node-id="${CSS.escape(selectedNodeId)}"]`)
          const detailElement = document.querySelector<HTMLElement>(`.execution-node-detail[data-aligned-node-id="${CSS.escape(selectedNodeId)}"]`)
          return nodeElement && detailElement
            ? { nodeTop: nodeElement.getBoundingClientRect().top, detailTop: detailElement.getBoundingClientRect().top }
            : null
        }, node.id)
        errors.push(`${capability.id} node ${node.id} did not vertically align its desktop detail panel: ${JSON.stringify(alignment)}`)
      }
      renderedNodeTexts.push(await page.locator('.execution-node-detail').innerText())
      const promptContract = node.promptContractId
        ? capability.llmPromptContracts.find((contract) => contract.id === node.promptContractId)
        : undefined
      const nodeChromeText = (await page.locator(
        '.execution-node-heading, .execution-node-meta, .execution-node-contract-grid',
      ).allInnerTexts()).join('\n')
      for (const forbiddenNodeValue of [
        node.componentName,
        node.source,
        promptContract?.postValidation?.contractId,
        node.terminalState && !/[\u3400-\u9fff]/.test(node.terminalState) ? node.terminalState : undefined,
      ]) {
        if (forbiddenNodeValue && nodeChromeText.includes(forbiddenNodeValue)) {
          errors.push(`${capability.id} node ${node.id} exposed internal value ${forbiddenNodeValue} outside the body`)
        }
      }
      const body = await page.locator('.execution-node-body pre').innerText()
      if (body.trim().length < 40) {
        errors.push(`${capability.id} rendered an execution node body that is too short at node ${index + 1}`)
      }
      if (promptContract?.postValidation) {
        const validatorContract = page.locator('.execution-node-meta [data-validator-contract]')
        const validatorProfile = page.locator('.execution-node-meta [data-validator-profile]')
        if ((await validatorContract.getAttribute('data-validator-contract')) !== promptContract.postValidation.contractId) {
          errors.push(`${capability.id} node ${node.id} did not render validator contract ${promptContract.postValidation.contractId}`)
        }
        if ((await validatorProfile.getAttribute('data-validator-profile')) !== promptContract.postValidation.profile) {
          errors.push(`${capability.id} node ${node.id} did not render validator profile ${promptContract.postValidation.profile}`)
        }
      }
      if (node.terminalState) {
        const expectedKind = /manual|pending|review/i.test(node.terminalState) ? 'manual' : 'terminal'
        if ((await nodeButton.getAttribute('data-terminal-state')) !== node.terminalState) {
          errors.push(`${capability.id} node ${node.id} did not expose terminalState=${node.terminalState}`)
        }
        if ((await nodeButton.getAttribute('data-terminal-kind')) !== expectedKind) {
          errors.push(`${capability.id} node ${node.id} rendered the wrong terminal kind`)
        }
        if (await nodeButton.locator('.terminal-state-badge').count() !== 1) {
          errors.push(`${capability.id} node ${node.id} did not render a textual terminal badge`)
        }
        if ((await page.locator('.execution-node-detail').getAttribute('data-terminal-state')) !== node.terminalState) {
          errors.push(`${capability.id} node ${node.id} detail did not expose terminalState=${node.terminalState}`)
        }
      }
    }
    const allRenderedText = `${mainText}\n${renderedNodeTexts.join('\n')}`

    for (const misleading of ['真实送入 LLM', '真实 LLM 提示词', '脱敏真实运行提示词', '运行时实际送入模型的 prompt']) {
      if (allRenderedText.includes(misleading)) {
        errors.push(`${capability.id} rendered misleading prompt wording: ${misleading}`)
      }
    }

    for (const contract of capability.llmPromptContracts) {
      if (!allRenderedText.includes(contract.title)) {
        errors.push(`${capability.id} did not render prompt contract title ${contract.id} in its execution graph`)
      }
    }
    if (allRenderedText.includes(forbiddenGenericPromptText)) {
      errors.push(`${capability.id} rendered generated static prompt placeholder text`)
    }
    if (capability.id === 'cognition' && allRenderedText.includes(forbiddenKnowledgeBundleText)) {
      errors.push('cognition page rendered unrelated Knowledge bot global prompt bundle')
    }
    if (capability.id === 'transcription' && !allRenderedText.includes('你是会议逐字稿分片事实提取器')) {
      errors.push('transcription page did not render the real transcription postprocess prompt')
    }
    if (capability.id === 'transcription' && (!allRenderedText.includes('音频/文本转写输入') || !allRenderedText.includes('一致性修订'))) {
      errors.push('transcription page did not render the multi-stage transcription execution graph')
    }
    if (capability.id === 'deconstruction') {
      for (const required of ['下载视频/图文证据', '视觉读取图片/视频帧', '写入 02A 素材源', '写入 02B 素材拆解', '完成校验']) {
        if (!allRenderedText.includes(required)) {
          errors.push(`deconstruction page did not render graph node: ${required}`)
        }
      }
    }
    if (capability.rawLabel === '【删除】') {
      for (const required of ['解析删除目标', '生成删除预览', '确认删除门禁', '执行删除边界']) {
        if (!allRenderedText.includes(required)) {
          errors.push(`${capability.id} delete page did not render graph node: ${required}`)
        }
      }
    }
    if (capability.id === 'data-review' && !allRenderedText.includes(requiredDataReviewPromptText)) {
      errors.push('data-review page did not render the data review LLM prompt body')
    }
    if (dataReviewPromptMustNotLeakTo.has(capability.id) && allRenderedText.includes(requiredDataReviewPromptText)) {
      errors.push(`${capability.id} incorrectly rendered the data review LLM prompt body`)
    }
    for (const selector of ['.prompt-contract-grid', '.prompt-source-line', '.prompt-summary', '.prompt-policy', '.prompt-component-list']) {
      const count = await page.locator(selector).count()
      if (count > 0) {
        errors.push(`${capability.id} rendered deprecated prompt metadata selector ${selector}`)
      }
    }
    if (screenshotDir && capabilityQaId === capability.id) {
      mkdirSync(screenshotDir, { recursive: true })
      await page.addStyleTag({ content: '.topbar { position: static !important; }' })
      await page.locator('.execution-graph-panel').screenshot({ path: join(screenshotDir, `execution-graph-${capability.id}-1366.png`) })
    }
  }

  await checkBranchFixture(browser, data, errors)
  await checkComplexBranchFixture(browser, data, errors)
  if (process.env.BOT_CENTER_BRANCH_QA_ONLY !== '1') {
    await checkAllCapabilitiesMobile(browser, capabilityQaId ? { ...data, capabilities } : data, errors)
  }

  await browser.close()

  if (errors.length > 0) {
    fail(errors)
  }

  console.log(`Prompt rendering QA passed for ${data.capabilities.length} capabilities at ${baseUrl}`)
}

main().catch((error: unknown) => {
  console.error(error)
  process.exit(1)
})
