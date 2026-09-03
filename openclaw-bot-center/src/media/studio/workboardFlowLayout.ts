import { WORKBOARD_FLOW_LANES, WORKBOARD_FLOW_NODES, type WorkboardFlowLane, type WorkboardFlowNode } from './workboardPresentation'

// ---- /today 全流程图的几何：六列 × 四条泳道，viewBox 固定，容器变窄时横向滚动而不是缩字 ----
// 这些常量与下面的路径计算被 WorkboardFlowDiagram 和排版门禁
// （scripts/qa/checkWorkboardFlowLayout.ts）共用：门禁按同一套坐标验算节点与连线标签
// 有没有互相压住，所以改了这里就等于改了门禁的输入，不会出现「图变了但门禁还在量旧图」。
export const NODE_W = 128
export const NODE_H = 46
export const COLUMN_X = [20, 206, 392, 578, 764, 950] as const
export const LANE_Y: Record<WorkboardFlowLane, number> = { content: 56, shared: 140, local: 224, commercial: 308 }
export const LANE_PAD = 9
export const VIEW_W = 1104
export const VIEW_H = 404

/** 节点内文字的左内缩与两侧留白：标题和副文都必须排得下。 */
export const NODE_TEXT_INSET = 11
export const NODE_TEXT_RIGHT_INSET = 10
export const NODE_LABEL_FONT_SIZE = 12.5
export const NODE_CAPTION_FONT_SIZE = 11
export const EDGE_LABEL_FONT_SIZE = 10.5

export type Box = { x: number; y: number; cx: number; cy: number; right: number; bottom: number; lane: WorkboardFlowLane }
export type Rect = { x: number; y: number; right: number; bottom: number }

export function nodeBox(node: WorkboardFlowNode): Box {
  const x = COLUMN_X[node.column - 1]!
  const y = LANE_Y[node.lane]
  return { x, y, cx: x + NODE_W / 2, cy: y + NODE_H / 2, right: x + NODE_W, bottom: y + NODE_H, lane: node.lane }
}

export const NODE_BOXES: ReadonlyMap<string, Box> = new Map(WORKBOARD_FLOW_NODES.map((node) => [node.id, nodeBox(node)]))

export function laneBandRect(lane: WorkboardFlowLane): Rect {
  return { x: 8, y: LANE_Y[lane] - LANE_PAD, right: VIEW_W - 8, bottom: LANE_Y[lane] + NODE_H + LANE_PAD }
}

export const LANE_BANDS: readonly { lane: WorkboardFlowLane; rect: Rect }[] = WORKBOARD_FLOW_LANES.map((lane) => ({ lane: lane.id, rect: laneBandRect(lane.id) }))

export type EdgeGeometry = { d: string; label: [number, number]; anchor: 'start' | 'middle' | 'end' }

/** 连线标签只允许落在这几条基线上：泳道带之间的空白，以及画布上下两条外圈留白。
 *  逐条边各自算 y，标签就会高高低低、还常常压在泳道底色上；固定基线让它们对齐成
 *  一条条横向的「标签走廊」，也保证每个标签都在白底而不是彩色带子上。 */
export const LABEL_BASELINES: readonly number[] = [
  LANE_Y.content - LANE_PAD - 3,
  (LANE_Y.content + NODE_H + LANE_PAD + (LANE_Y.shared - LANE_PAD)) / 2 + 5,
  (LANE_Y.shared + NODE_H + LANE_PAD + (LANE_Y.local - LANE_PAD)) / 2 + 5,
  (LANE_Y.local + NODE_H + LANE_PAD + (LANE_Y.commercial - LANE_PAD)) / 2 + 5,
  LANE_Y.commercial + NODE_H + LANE_PAD + 15,
]

/** 把标签基线吸附到最近的一条走廊。 */
export function snapLabelBaseline(y: number): number {
  let best = LABEL_BASELINES[0]!
  for (const baseline of LABEL_BASELINES) {
    if (Math.abs(baseline - y) < Math.abs(best - y)) best = baseline
  }
  return best
}

/** 每条边的路径、标签位置与对齐方式。合流边汇入创作节点左侧的不同高度，送审/返修是一对平行竖线，
 *  本机线与合流之间走同列竖线，回流走外圈；交付绕过本机线走正交路径。 */
export function edgeGeometry(from: Box, to: Box, fromId: string, toId: string, kind: string): EdgeGeometry {
  const geometry = rawEdgeGeometry(from, to, fromId, toId, kind)
  return { ...geometry, label: [geometry.label[0], snapLabelBaseline(geometry.label[1])] }
}

function rawEdgeGeometry(from: Box, to: Box, fromId: string, toId: string, kind: string): EdgeGeometry {
  if (kind === 'loop') {
    if (to.y < from.y) {
      const top = 30
      return { d: `M${from.cx},${from.y} V${top} H${to.cx} V${to.y}`, label: [(from.cx + to.cx) / 2, top + 14], anchor: 'middle' }
    }
    const bottom = VIEW_H - 20
    return { d: `M${from.cx},${from.bottom} V${bottom} H${to.cx} V${to.bottom}`, label: [(from.cx + to.cx) / 2, bottom - 6], anchor: 'middle' }
  }
  // 送审 / 返修：一对平行竖线，从合流穿过本机线在第 4 列的空位落到商务线。
  if (fromId === 'creation' && toId === 'acceptance') {
    const x = from.cx - 20
    return { d: `M${x},${from.bottom} V${to.y}`, label: [x - 7, from.bottom + 14], anchor: 'end' }
  }
  if (fromId === 'acceptance' && toId === 'creation') {
    const x = from.cx + 20
    return { d: `M${x},${from.y} V${to.bottom}`, label: [x + 7, to.bottom + 14], anchor: 'start' }
  }
  // 本机线与合流之间的同列竖线：素材摘要回传、成片回传。
  if (fromId === 'local_intake' || fromId === 'local_edit') {
    return { d: `M${from.cx},${from.y} V${to.bottom}`, label: [from.cx + 8, to.bottom + 14], anchor: 'start' }
  }
  if (toId === 'local_edit') {
    return {
      d: `M${from.right},${from.cy + 13} C${from.right + 34},${from.cy + 13} ${to.x - 34},${to.cy} ${to.x},${to.cy}`,
      label: [from.right + 12, from.bottom + 30],
      anchor: 'start',
    }
  }
  // 交付：从品牌审核正交绕过本机线，进入发布交付的左侧（成片回传走它的底边）。
  if (fromId === 'acceptance' && toId === 'publishing') {
    return { d: `M${from.right},${from.cy} H${to.x - 12} V${to.cy + 13} H${to.x}`, label: [from.right + 8, from.cy - 8], anchor: 'start' }
  }
  if (toId === 'creation') {
    const targetY = fromId === 'decision' ? to.cy - 13 : fromId === 'brief' ? to.cy + 13 : to.cy
    if (from.lane === to.lane) return { d: `M${from.right},${from.cy} H${to.x}`, label: [(from.right + to.x) / 2, from.cy - 8], anchor: 'middle' }
    const startY = from.y > to.y ? from.y : from.bottom
    // 上方来的（选题）把标签靠到创作节点这一侧，避免和同一条走廊里的「素材汇入」撞上。
    const label: [number, number] = from.y < to.y ? [to.x - 8, (startY + targetY) / 2 + 4] : [from.cx + 12, (startY + targetY) / 2 + 4]
    return { d: `M${from.cx},${startY} C${from.cx},${targetY} ${from.cx + 36},${targetY} ${to.x},${targetY}`, label, anchor: from.y < to.y ? 'end' : 'start' }
  }
  const y = fromId === 'creation' && toId === 'publishing' ? from.cy - 13 : from.cy
  return { d: `M${from.right},${y} H${to.x}`, label: [(from.right + to.x) / 2, y - 8], anchor: 'middle' }
}

/** SVG 里量不到文字宽度，这里按字宽估算：CJK 与全角标点算 1em，ASCII 算 0.56em，空格 0.28em。
 *  估得略宽是有意的——门禁宁可早一步报重叠，也不要放过真正压在一起的标签。 */
export function estimateTextWidth(text: string, fontSize: number): number {
  let width = 0
  for (const character of text) {
    const code = character.codePointAt(0) ?? 0
    if (code > 0x2e80) width += fontSize
    else if (character === ' ') width += fontSize * 0.28
    else width += fontSize * 0.56
  }
  return width
}

/** 文字包围盒：SVG 的 y 是基线，往上算字高、往下留一点下沉部分。 */
export function textRect(text: string, position: readonly [number, number], anchor: EdgeGeometry['anchor'], fontSize: number): Rect {
  const width = estimateTextWidth(text, fontSize)
  const [x, baseline] = position
  const left = anchor === 'start' ? x : anchor === 'end' ? x - width : x - width / 2
  return { x: left, y: baseline - fontSize * 0.82, right: left + width, bottom: baseline + fontSize * 0.22 }
}

export function rectsOverlap(a: Rect, b: Rect): boolean {
  return a.x < b.right && b.x < a.right && a.y < b.bottom && b.y < a.bottom
}

export function rectContains(outer: Rect, inner: Rect): boolean {
  return inner.x >= outer.x && inner.y >= outer.y && inner.right <= outer.right && inner.bottom <= outer.bottom
}

export const VIEW_RECT: Rect = { x: 0, y: 0, right: VIEW_W, bottom: VIEW_H }
