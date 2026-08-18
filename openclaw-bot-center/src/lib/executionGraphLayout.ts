import dagreImport from '@dagrejs/dagre'

type DagreApi = Pick<typeof import('@dagrejs/dagre'), 'graphlib' | 'layout'>

const dagre = ((dagreImport as unknown as { default?: DagreApi }).default ?? dagreImport) as DagreApi

export type ExecutionLayoutNodeInput = {
  id: string
  width: number
  height: number
  index: number
}

export type ExecutionLayoutEdgeInput = {
  from: string
  to: string
  index: number
}

export type ExecutionGraphLayoutNode = ExecutionLayoutNodeInput & {
  x: number
  y: number
  rank: number
}

export type ExecutionGraphLayoutEdge = ExecutionLayoutEdgeInput & {
  points: Array<{ x: number; y: number }>
  path: string
  labelX?: number
  labelY?: number
  labelWidth?: number
}

export type ExecutionGraphLayout = {
  width: number
  height: number
  nodes: ExecutionGraphLayoutNode[]
  edges: ExecutionGraphLayoutEdge[]
}

const GRAPH_MARGIN = 16
const NODE_SEPARATION = 24
const EDGE_SEPARATION = 18
const RANK_SEPARATION = 104
const MIN_OVERVIEW_NODE_WIDTH = 24
const PREFERRED_NODE_WIDTH = 248
const PORT_INSET = 24
const PORT_STEM = 18
export const MAX_OVERVIEW_JUNCTION_WIDTH = 40
const OVERVIEW_MARGIN = 4
const OVERVIEW_SEPARATION = 8

export function recommendedExecutionNodeWidth(
  availableWidth: number,
  nodes: Array<{ id: string }>,
  edges: Array<{ from: string; to: string }>,
) {
  const naturalLayerSize = Math.max(
    maximumLayerSize(nodes, edges),
    maximumBranchWidth(nodes, edges),
    dagreColumnPressure(nodes, edges),
  )
  const usableWidth = Math.max(MIN_OVERVIEW_NODE_WIDTH, availableWidth - GRAPH_MARGIN * 2)
  if (naturalLayerSize <= 1) return Math.min(PREFERRED_NODE_WIDTH, usableWidth)
  const fittedWidth = (usableWidth - NODE_SEPARATION * (naturalLayerSize - 1)) / naturalLayerSize
  if (fittedWidth >= 72) return Math.min(PREFERRED_NODE_WIDTH, fittedWidth)
  const overviewWidth = (availableWidth - OVERVIEW_MARGIN * 2 - OVERVIEW_SEPARATION * (naturalLayerSize - 1)) / naturalLayerSize
  return Math.max(MIN_OVERVIEW_NODE_WIDTH, overviewWidth)
}

export function layoutExecutionGraph(
  nodes: ExecutionLayoutNodeInput[],
  edges: ExecutionLayoutEdgeInput[],
): ExecutionGraphLayout {
  if (!nodes.length) return { width: 0, height: 0, nodes: [], edges: [] }

  const nodeIds = new Set(nodes.map((node) => node.id))
  for (const edge of edges) {
    if (!nodeIds.has(edge.from) || !nodeIds.has(edge.to)) {
      throw new Error(`execution graph layout edge has unknown endpoint: ${edge.from} -> ${edge.to}`)
    }
  }

  const graph = new dagre.graphlib.Graph({ directed: true, multigraph: false, compound: false })
  const minimumNodeWidth = Math.min(...nodes.map((node) => node.width))
  const overviewLayout = minimumNodeWidth < 104
  const compactLayout = minimumNodeWidth < 110
  const edgeLabelReservation = Math.min(172, Math.max(24, minimumNodeWidth - 8))
  graph.setGraph({
    rankdir: 'TB',
    ranker: 'network-simplex',
    nodesep: overviewLayout ? 4 : compactLayout ? 12 : NODE_SEPARATION,
    edgesep: overviewLayout ? 6 : compactLayout ? 10 : EDGE_SEPARATION,
    ranksep: RANK_SEPARATION,
    marginx: overviewLayout ? OVERVIEW_MARGIN : GRAPH_MARGIN,
    marginy: GRAPH_MARGIN,
  })
  graph.setDefaultEdgeLabel(() => ({}))

  for (const node of [...nodes].sort((left, right) => left.index - right.index)) {
    graph.setNode(node.id, { width: node.width, height: node.height })
  }
  for (const edge of [...edges].sort((left, right) => left.index - right.index)) {
    graph.setEdge(edge.from, edge.to, {
      minlen: 1,
      weight: 1,
      width: 0,
      height: 0,
      labelpos: 'c',
    })
  }

  dagre.layout(graph)

  const ranks = executionGraphRanks(nodes, edges)
  const laidOutNodes = nodes.map((node) => {
    const result = graph.node(node.id)
    if (!result) throw new Error(`execution graph layout omitted node ${node.id}`)
    return {
      ...node,
      x: roundCoordinate(result.x),
      y: roundCoordinate(result.y),
      rank: ranks.get(node.id) ?? 0,
    }
  })
  const nodesById = new Map(laidOutNodes.map((node) => [node.id, node]))
  const outgoing = groupEdges(edges, (edge) => edge.from)
  const incoming = groupEdges(edges, (edge) => edge.to)

  const laidOutEdges = edges.map((edge) => {
    const result = graph.edge(edge.from, edge.to)
    if (!result?.points?.length) {
      throw new Error(`execution graph layout omitted edge ${edge.from} -> ${edge.to}`)
    }
    const source = nodesById.get(edge.from)!
    const target = nodesById.get(edge.to)!
    const sourceSiblings = [...(outgoing.get(edge.from) ?? [])].sort((left, right) => {
      const targetDifference = nodesById.get(left.to)!.x - nodesById.get(right.to)!.x
      return targetDifference || left.index - right.index
    })
    const targetSiblings = [...(incoming.get(edge.to) ?? [])].sort((left, right) => {
      const sourceDifference = nodesById.get(left.from)!.x - nodesById.get(right.from)!.x
      return sourceDifference || left.index - right.index
    })
    const sourceOffset = portOffset(source.width, sourceSiblings, edge)
    const targetOffset = portOffset(target.width, targetSiblings, edge)
    const start = { x: source.x + sourceOffset, y: source.y + source.height / 2 }
    const end = { x: target.x + targetOffset, y: target.y - target.height / 2 }
    const innerPoints = result.points.slice(1, -1)
    const points = compactPoints([
      start,
      { x: start.x, y: start.y + PORT_STEM },
      ...innerPoints,
      { x: end.x, y: end.y - PORT_STEM },
      end,
    ]).map((point) => ({ x: roundCoordinate(point.x), y: roundCoordinate(point.y) }))
    const labelIndex = sourceSiblings.findIndex((candidate) => candidate.index === edge.index)
    const labelYOffset = (labelIndex - (sourceSiblings.length - 1) / 2) * 26
    const baseLabelPoint = pointAlongPolyline(points, 0.45)
    const nearestSiblingTargetTop = Math.min(...sourceSiblings.map((sibling) => {
      const siblingTarget = nodesById.get(sibling.to)!
      return siblingTarget.y - siblingTarget.height / 2
    }))
    const labelPoint = {
      x: baseLabelPoint.x,
      y: (start.y + nearestSiblingTargetTop) / 2 + labelYOffset,
    }
    return {
      ...edge,
      points,
      path: executionEdgePath(points),
      labelX: labelPoint ? roundCoordinate(labelPoint.x) : undefined,
      labelY: labelPoint ? roundCoordinate(labelPoint.y) : undefined,
      labelWidth: edgeLabelReservation,
    }
  })

  const graphSize = graph.graph()
  return {
    width: Math.ceil(graphSize.width ?? 0),
    height: Math.ceil(graphSize.height ?? 0),
    nodes: laidOutNodes,
    edges: laidOutEdges,
  }
}

export function executionEdgePath(points: Array<{ x: number; y: number }>) {
  if (!points.length) return ''
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`
  let path = `M ${points[0].x} ${points[0].y}`
  for (let index = 1; index < points.length - 1; index += 1) {
    const point = points[index]
    const next = points[index + 1]
    const midpoint = { x: (point.x + next.x) / 2, y: (point.y + next.y) / 2 }
    path += ` Q ${point.x} ${point.y}, ${roundCoordinate(midpoint.x)} ${roundCoordinate(midpoint.y)}`
  }
  const last = points[points.length - 1]
  return `${path} L ${last.x} ${last.y}`
}

function maximumLayerSize(
  nodes: Array<{ id: string }>,
  edges: Array<{ from: string; to: string }>,
) {
  const ranks = executionGraphRanks(nodes, edges)
  const counts = new Map<number, number>()
  for (const node of nodes) {
    const rank = ranks.get(node.id) ?? 0
    counts.set(rank, (counts.get(rank) ?? 0) + 1)
  }
  return Math.max(1, ...counts.values())
}

function dagreColumnPressure(
  nodes: Array<{ id: string }>,
  edges: Array<{ from: string; to: string }>,
) {
  const probe = new dagre.graphlib.Graph({ directed: true, multigraph: false, compound: false })
  probe.setGraph({ rankdir: 'TB', ranker: 'network-simplex', nodesep: 1, edgesep: 1, ranksep: 1, marginx: 0, marginy: 0 })
  probe.setDefaultEdgeLabel(() => ({}))
  for (const node of nodes) probe.setNode(node.id, { width: 1, height: 1 })
  for (const edge of edges) probe.setEdge(edge.from, edge.to, { minlen: 1, weight: 1, width: 0, height: 0 })
  dagre.layout(probe)
  return Math.max(1, Math.round(((probe.graph().width ?? 1) + 1) / 2))
}

function maximumBranchWidth(
  nodes: Array<{ id: string }>,
  edges: Array<{ from: string; to: string }>,
) {
  const incomingCount = new Map(nodes.map((node) => [node.id, 0]))
  const outgoing = groupEdges(edges, (edge) => edge.from)
  for (const edge of edges) incomingCount.set(edge.to, (incomingCount.get(edge.to) ?? 0) + 1)
  const memo = new Map<string, number>()
  const branchWidth = (nodeId: string, root = false): number => {
    if (!root && (incomingCount.get(nodeId) ?? 0) > 1) return 1
    const cached = memo.get(nodeId)
    if (cached !== undefined) return cached
    const children = outgoing.get(nodeId) ?? []
    const width = children.length > 1
      ? children.reduce((sum, edge) => sum + branchWidth(edge.to), 0)
      : children.length === 1 ? branchWidth(children[0].to) : 1
    memo.set(nodeId, width)
    return width
  }
  return Math.max(1, ...nodes.map((node) => branchWidth(node.id, true)))
}

function executionGraphRanks(
  nodes: Array<{ id: string }>,
  edges: Array<{ from: string; to: string }>,
) {
  const indegree = new Map(nodes.map((node) => [node.id, 0]))
  const outgoing = groupEdges(edges, (edge) => edge.from)
  const ranks = new Map(nodes.map((node) => [node.id, 0]))
  for (const edge of edges) indegree.set(edge.to, (indegree.get(edge.to) ?? 0) + 1)
  const queue = nodes.filter((node) => (indegree.get(node.id) ?? 0) === 0).map((node) => node.id)
  let visited = 0
  while (queue.length) {
    const nodeId = queue.shift()!
    visited += 1
    for (const edge of outgoing.get(nodeId) ?? []) {
      ranks.set(edge.to, Math.max(ranks.get(edge.to) ?? 0, (ranks.get(nodeId) ?? 0) + 1))
      const nextIndegree = (indegree.get(edge.to) ?? 0) - 1
      indegree.set(edge.to, nextIndegree)
      if (nextIndegree === 0) queue.push(edge.to)
    }
  }
  if (visited !== nodes.length) throw new Error('execution graph layout requires an acyclic graph')
  return ranks
}

function groupEdges<T>(edges: T[], key: (edge: T) => string) {
  const groups = new Map<string, T[]>()
  for (const edge of edges) groups.set(key(edge), [...(groups.get(key(edge)) ?? []), edge])
  return groups
}

function portOffset(width: number, siblings: ExecutionLayoutEdgeInput[], edge: ExecutionLayoutEdgeInput) {
  if (siblings.length <= 1) return 0
  const index = siblings.findIndex((candidate) => candidate.index === edge.index)
  if (index < 0) throw new Error(`execution graph layout could not allocate port for edge ${edge.index}`)
  const inset = width < 48
    ? 2
    : Math.min(PORT_INSET, Math.max(6, width * 0.15))
  const usableWidth = Math.max(0, width - inset * 2)
  const spacing = Math.min(28, usableWidth / Math.max(1, siblings.length - 1))
  return (index - (siblings.length - 1) / 2) * spacing
}

function compactPoints(points: Array<{ x: number; y: number }>) {
  const compacted: Array<{ x: number; y: number }> = []
  for (const point of points) {
    const previous = compacted[compacted.length - 1]
    if (previous && Math.abs(previous.x - point.x) < 0.5 && Math.abs(previous.y - point.y) < 0.5) continue
    compacted.push(point)
  }
  return compacted
}

function pointAlongPolyline(points: Array<{ x: number; y: number }>, fraction: number) {
  if (points.length < 2) return points[0] ?? { x: 0, y: 0 }
  const segments = points.slice(1).map((point, index) => {
    const previous = points[index]
    return { from: previous, to: point, length: Math.hypot(point.x - previous.x, point.y - previous.y) }
  })
  const totalLength = segments.reduce((sum, segment) => sum + segment.length, 0)
  let remaining = totalLength * fraction
  for (const segment of segments) {
    if (remaining <= segment.length) {
      const ratio = segment.length ? remaining / segment.length : 0
      return {
        x: segment.from.x + (segment.to.x - segment.from.x) * ratio,
        y: segment.from.y + (segment.to.y - segment.from.y) * ratio,
      }
    }
    remaining -= segment.length
  }
  return points[points.length - 1]
}

function roundCoordinate(value: number) {
  return Math.round(value * 2) / 2
}
