import {
  layoutExecutionGraph,
  MAX_OVERVIEW_JUNCTION_WIDTH,
  recommendedExecutionNodeWidth,
  type ExecutionGraphLayout,
} from '../../src/lib/executionGraphLayout'

type Fixture = {
  name: string
  nodes: string[]
  edges: Array<{ from: string; to: string; label?: string }>
  widths: number[]
}

const fixtures: Fixture[] = [
  {
    name: 'single-chain',
    nodes: ['entry', 'parse', 'execute', 'reply'],
    edges: [
      { from: 'entry', to: 'parse' },
      { from: 'parse', to: 'execute' },
      { from: 'execute', to: 'reply' },
    ],
    widths: [280, 390, 1100],
  },
  {
    name: 'split-merge',
    nodes: ['entry', 'decision', 'pass', 'manual', 'reply'],
    edges: [
      { from: 'entry', to: 'decision' },
      { from: 'decision', to: 'pass', label: '校验通过' },
      { from: 'decision', to: 'manual', label: '需要人工确认' },
      { from: 'pass', to: 'reply' },
      { from: 'manual', to: 'reply' },
    ],
    widths: [280, 390, 1100],
  },
  {
    name: 'asymmetric-nested',
    nodes: ['entry', 'decision', 'quick', 'inspect', 'retry', 'manual', 'merge', 'reply'],
    edges: [
      { from: 'entry', to: 'decision' },
      { from: 'decision', to: 'quick', label: '直接通过' },
      { from: 'decision', to: 'inspect', label: '继续检查' },
      { from: 'inspect', to: 'retry', label: '可以修订' },
      { from: 'inspect', to: 'manual', label: '证据不足' },
      { from: 'quick', to: 'merge' },
      { from: 'retry', to: 'merge' },
      { from: 'manual', to: 'merge' },
      { from: 'merge', to: 'reply' },
    ],
    widths: [358, 1100],
  },
  {
    name: 'multi-branch-long-label',
    nodes: ['entry', 'decision', 'first', 'second', 'third', 'merge', 'reply'],
    edges: [
      { from: 'entry', to: 'decision' },
      { from: 'decision', to: 'first', label: '结构和证据均已满足发布条件' },
      { from: 'decision', to: 'second', label: '需要补充一项可公开证据' },
      { from: 'decision', to: 'third', label: '必须转交人工完成最终判断' },
      { from: 'first', to: 'merge' },
      { from: 'second', to: 'merge' },
      { from: 'third', to: 'merge' },
      { from: 'merge', to: 'reply' },
    ],
    widths: [358, 1366],
  },
  {
    name: 'wide-fanout-overview',
    nodes: ['entry', 'decision', 'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'merge', 'reply'],
    edges: [
      { from: 'entry', to: 'decision' },
      ...['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'].map((target) => ({ from: 'decision', to: target })),
      ...['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'].map((from) => ({ from, to: 'merge' })),
      { from: 'merge', to: 'reply' },
    ],
    widths: [291, 423],
  },
]

const errors: string[] = []

for (const fixture of fixtures) {
  for (const viewportWidth of fixture.widths) {
    const nodeWidth = recommendedExecutionNodeWidth(viewportWidth, fixture.nodes.map((id) => ({ id })), fixture.edges)
    if (fixture.name === 'wide-fanout-overview' && viewportWidth === 291 && nodeWidth >= 48) {
      errors.push(`${fixture.name}/${viewportWidth}: expected accessible overview density, got node width ${nodeWidth}`)
    }
    const incoming = new Map<string, number>()
    const outgoing = new Map<string, number>()
    for (const edge of fixture.edges) {
      incoming.set(edge.to, (incoming.get(edge.to) ?? 0) + 1)
      outgoing.set(edge.from, (outgoing.get(edge.from) ?? 0) + 1)
    }
    const nodes = fixture.nodes.map((id, index) => {
      const connectionCount = Math.max(incoming.get(id) ?? 0, outgoing.get(id) ?? 0)
      const width = nodeWidth < 48 && connectionCount > 4
        ? Math.min(MAX_OVERVIEW_JUNCTION_WIDTH, nodeWidth + (connectionCount - 4) * 8)
        : nodeWidth
      return {
        id,
        index,
        width,
        height: 78 + (index % 3) * 18,
      }
    })
    const edges = fixture.edges.map((edge, index) => ({
      from: edge.from,
      to: edge.to,
      index,
    }))
    const layout = layoutExecutionGraph(nodes, edges)
    const repeated = layoutExecutionGraph(nodes, edges)

    if (JSON.stringify(layout) !== JSON.stringify(repeated)) {
      errors.push(`${fixture.name}/${viewportWidth}: layout is not deterministic`)
    }
    if (layout.nodes.length !== nodes.length || layout.edges.length !== edges.length) {
      errors.push(`${fixture.name}/${viewportWidth}: node/edge parity failed`)
    }
    checkNodeOverlap(fixture.name, viewportWidth, layout, errors)
    checkPorts(fixture.name, viewportWidth, layout, errors)
    const labeledEdgeIndexes = new Set(fixture.edges.flatMap((edge, index) => edge.label ? [index] : []))
    checkNodeAndLabelCrossings(fixture.name, viewportWidth, layout, labeledEdgeIndexes, errors)
    checkEdgeCrossings(fixture.name, viewportWidth, layout, errors)
    if (viewportWidth <= 390 && layout.width > viewportWidth + 1) {
      errors.push(`${fixture.name}/${viewportWidth}: layout width ${layout.width} exceeds viewport`)
    }
  }
}

if (errors.length) {
  console.error(errors.map((error) => `- ${error}`).join('\n'))
  process.exit(1)
}

console.log(`Execution graph layout QA passed for ${fixtures.length} synthetic fixtures`)

function checkNodeOverlap(name: string, width: number, layout: ExecutionGraphLayout, output: string[]) {
  for (let leftIndex = 0; leftIndex < layout.nodes.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < layout.nodes.length; rightIndex += 1) {
      const left = nodeRect(layout.nodes[leftIndex])
      const right = nodeRect(layout.nodes[rightIndex])
      if (rectanglesOverlap(left, right, 2)) {
        output.push(`${name}/${width}: nodes ${layout.nodes[leftIndex].id} and ${layout.nodes[rightIndex].id} overlap`)
      }
    }
  }
}

function checkPorts(name: string, width: number, layout: ExecutionGraphLayout, output: string[]) {
  for (const key of ['from', 'to'] as const) {
    const groups = new Map<string, typeof layout.edges>()
    for (const edge of layout.edges) groups.set(edge[key], [...(groups.get(edge[key]) ?? []), edge])
    for (const [nodeId, edges] of groups) {
      if (edges.length < 2) continue
      const ports = edges.map((edge) => key === 'from' ? edge.points[0].x : edge.points.at(-1)!.x)
      if (new Set(ports).size !== ports.length) {
        output.push(`${name}/${width}: ${key} node ${nodeId} does not use distinct sibling ports`)
      }
      const sortedPorts = [...ports].sort((left, right) => left - right)
      for (let index = 1; index < sortedPorts.length; index += 1) {
        if (sortedPorts[index] - sortedPorts[index - 1] < 4) {
          output.push(`${name}/${width}: ${key} node ${nodeId} sibling ports are less than 4px apart`)
          break
        }
      }
    }
  }
}

function checkNodeAndLabelCrossings(
  name: string,
  width: number,
  layout: ExecutionGraphLayout,
  labeledEdgeIndexes: Set<number>,
  output: string[],
) {
  const nodes = new Map(layout.nodes.map((node) => [node.id, nodeRect(node)]))
  for (const edge of layout.edges) {
    const samples = samplePolyline(edge.points, 4).slice(2, -2)
    for (const [nodeId, rect] of nodes) {
      if (nodeId === edge.from || nodeId === edge.to) continue
      if (samples.some((point) => pointInRect(point, rect, 1))) {
        output.push(`${name}/${width}: edge ${edge.from}->${edge.to} crosses unrelated node ${nodeId}`)
        break
      }
    }
    if (!labeledEdgeIndexes.has(edge.index) || edge.labelX === undefined || edge.labelY === undefined || edge.labelWidth === undefined) continue
    const labelRect = {
      left: edge.labelX - edge.labelWidth / 2,
      right: edge.labelX + edge.labelWidth / 2,
      top: edge.labelY - 11,
      bottom: edge.labelY + 11,
    }
    for (const [nodeId, rect] of nodes) {
      if (rectanglesOverlap(labelRect, rect, 1)) {
        output.push(`${name}/${width}: edge label ${edge.from}->${edge.to} overlaps node ${nodeId}`)
        break
      }
    }
  }
  const labels = layout.edges.filter((edge) => labeledEdgeIndexes.has(edge.index)
    &&
    edge.labelX !== undefined && edge.labelY !== undefined && edge.labelWidth !== undefined,
  )
  for (let leftIndex = 0; leftIndex < labels.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < labels.length; rightIndex += 1) {
      const left = labels[leftIndex]
      const right = labels[rightIndex]
      const leftRect = { left: left.labelX! - left.labelWidth! / 2, right: left.labelX! + left.labelWidth! / 2, top: left.labelY! - 11, bottom: left.labelY! + 11 }
      const rightRect = { left: right.labelX! - right.labelWidth! / 2, right: right.labelX! + right.labelWidth! / 2, top: right.labelY! - 11, bottom: right.labelY! + 11 }
      if (rectanglesOverlap(leftRect, rightRect, 1)) {
        output.push(`${name}/${width}: edge labels ${left.from}->${left.to} and ${right.from}->${right.to} overlap`)
      }
    }
  }
}

function checkEdgeCrossings(name: string, width: number, layout: ExecutionGraphLayout, output: string[]) {
  for (let leftIndex = 0; leftIndex < layout.edges.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < layout.edges.length; rightIndex += 1) {
      const left = layout.edges[leftIndex]
      const right = layout.edges[rightIndex]
      if (left.from === right.from || left.from === right.to || left.to === right.from || left.to === right.to) continue
      if (polylinesCross(left.points, right.points)) {
        output.push(`${name}/${width}: unrelated edges ${left.from}->${left.to} and ${right.from}->${right.to} cross`)
      }
    }
  }
}

type Rect = { left: number; right: number; top: number; bottom: number }
type Point = { x: number; y: number }

function nodeRect(node: ExecutionGraphLayout['nodes'][number]): Rect {
  return {
    left: node.x - node.width / 2,
    right: node.x + node.width / 2,
    top: node.y - node.height / 2,
    bottom: node.y + node.height / 2,
  }
}

function rectanglesOverlap(left: Rect, right: Rect, gap = 0) {
  return left.left < right.right + gap && left.right + gap > right.left
    && left.top < right.bottom + gap && left.bottom + gap > right.top
}

function pointInRect(point: Point, rect: Rect, inset = 0) {
  return point.x > rect.left + inset && point.x < rect.right - inset
    && point.y > rect.top + inset && point.y < rect.bottom - inset
}

function samplePolyline(points: Point[], step: number) {
  const samples: Point[] = []
  for (let index = 1; index < points.length; index += 1) {
    const from = points[index - 1]
    const to = points[index]
    const distance = Math.hypot(to.x - from.x, to.y - from.y)
    const count = Math.max(1, Math.ceil(distance / step))
    for (let offset = 0; offset <= count; offset += 1) {
      const ratio = offset / count
      samples.push({ x: from.x + (to.x - from.x) * ratio, y: from.y + (to.y - from.y) * ratio })
    }
  }
  return samples
}

function polylinesCross(left: Point[], right: Point[]) {
  for (let leftIndex = 1; leftIndex < left.length; leftIndex += 1) {
    for (let rightIndex = 1; rightIndex < right.length; rightIndex += 1) {
      if (segmentsCross(left[leftIndex - 1], left[leftIndex], right[rightIndex - 1], right[rightIndex])) return true
    }
  }
  return false
}

function segmentsCross(a: Point, b: Point, c: Point, d: Point) {
  const orientation = (first: Point, second: Point, third: Point) =>
    (second.x - first.x) * (third.y - first.y) - (second.y - first.y) * (third.x - first.x)
  const one = orientation(a, b, c)
  const two = orientation(a, b, d)
  const three = orientation(c, d, a)
  const four = orientation(c, d, b)
  return one * two < -0.01 && three * four < -0.01
}
