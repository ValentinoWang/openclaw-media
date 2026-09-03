import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { WORKBOARD_FLOW_EDGES, WORKBOARD_FLOW_LANES, WORKBOARD_FLOW_NODES } from '../../src/media/studio/workboardPresentation'
import {
  EDGE_LABEL_FONT_SIZE,
  LANE_BANDS,
  NODE_BOXES,
  NODE_CAPTION_FONT_SIZE,
  NODE_LABEL_FONT_SIZE,
  NODE_TEXT_INSET,
  NODE_TEXT_RIGHT_INSET,
  LABEL_BASELINES,
  NODE_W,
  VIEW_RECT,
  edgeGeometry,
  estimateTextWidth,
  rectContains,
  rectsOverlap,
  textRect,
  type Rect,
} from '../../src/media/studio/workboardFlowLayout'

// /today 全流程图的排版门禁。SVG 里没有自动布局，节点和标签的坐标全是算出来的，
// 所以一条连线改了走向就可能把标签压到方块或另一条标签上——而且这种破相在类型检查和
// 单元测试里都看不出来。这里用组件同一套坐标验算：
//   1. 节点之间不重叠，且都落在自己的泳道带里；
//   2. 节点里的标题和副文排得下，不会溢出方块；
//   3. 连线标签不盖住任何节点，也不互相重叠，且都在画布内；
//   4. 连线标签有同底色描边（压在泳道底色或另一条线上时仍然读得清）。

/** 成对求重叠：门禁的核心判据，自测用它验证「真压上了会被抓到」。 */
function overlappingPairs<T>(items: readonly { key: string; rect: Rect; value?: T }[]): string[] {
  const found: string[] = []
  for (let i = 0; i < items.length; i += 1) {
    for (let j = i + 1; j < items.length; j += 1) {
      const a = items[i]!
      const b = items[j]!
      if (rectsOverlap(a.rect, b.rect)) found.push(`${a.key} 与 ${b.key} 重叠`)
    }
  }
  return found
}

if (process.argv.includes('--self-test')) {
  const clear = [
    { key: 'a', rect: { x: 0, y: 0, right: 10, bottom: 10 } },
    { key: 'b', rect: { x: 20, y: 0, right: 30, bottom: 10 } },
  ]
  const clashing = [
    { key: 'a', rect: { x: 0, y: 0, right: 10, bottom: 10 } },
    { key: 'b', rect: { x: 9, y: 9, right: 30, bottom: 20 } },
  ]
  if (overlappingPairs(clear).length) throw new Error('self-test failed: 不相交的两块被判成重叠')
  if (overlappingPairs(clashing).length !== 1) throw new Error('self-test failed: 真正压在一起的两块没有被抓到')
  const boxed = { x: 0, y: 0, right: 100, bottom: 100 }
  if (!rectContains(boxed, { x: 10, y: 10, right: 20, bottom: 20 })) throw new Error('self-test failed: 完全在内的矩形被判成越界')
  if (rectContains(boxed, { x: 90, y: 10, right: 120, bottom: 20 })) throw new Error('self-test failed: 越界的矩形被放过')
  if (estimateTextWidth('复盘', 10) <= estimateTextWidth('ab', 10)) throw new Error('self-test failed: 中文字宽必须大于同字数的 ASCII')
  const wide = textRect('返修', [100, 50], 'start', 10)
  const ended = textRect('返修', [100, 50], 'end', 10)
  if (wide.x !== 100 || ended.right !== 100) throw new Error('self-test failed: 标签对齐方式没有反映在包围盒上')
  console.log('workboard flow layout self-test: PASS')
  process.exit(0)
}

const failures: string[] = []
const nodeRects = new Map<string, Rect>()
for (const node of WORKBOARD_FLOW_NODES) {
  const box = NODE_BOXES.get(node.id)!
  nodeRects.set(node.id, { x: box.x, y: box.y, right: box.right, bottom: box.bottom })
}

// 1. 节点彼此不重叠，并且待在自己的泳道带内。
failures.push(...overlappingPairs([...nodeRects].map(([key, rect]) => ({ key: `节点 ${key}`, rect }))))
for (const node of WORKBOARD_FLOW_NODES) {
  const rect = nodeRects.get(node.id)!
  const band = LANE_BANDS.find((item) => item.lane === node.lane)
  assert.ok(band, `${node.id} 的泳道 ${node.lane} 必须有对应的泳道带`)
  if (!rectContains(band.rect, rect)) failures.push(`节点 ${node.id} 超出了 ${node.lane} 泳道带`)
  if (!rectContains(VIEW_RECT, rect)) failures.push(`节点 ${node.id} 超出画布`)
}
assert.equal(LANE_BANDS.length, WORKBOARD_FLOW_LANES.length, '每条泳道都要有一条泳道带')

// 2. 节点里的文字排得下。副文是数据驱动的，按四位数的最坏情况估。
const innerWidth = NODE_W - NODE_TEXT_INSET - NODE_TEXT_RIGHT_INSET
for (const node of WORKBOARD_FLOW_NODES) {
  const labelWidth = estimateTextWidth(node.label, NODE_LABEL_FONT_SIZE)
  if (labelWidth > innerWidth) failures.push(`节点标题「${node.label}」需要 ${labelWidth.toFixed(1)}px，方块只有 ${innerWidth}px`)
  const caption = node.facts[0] ? `8888 ${node.facts[0].label}` : node.hint ?? node.pathLabel
  const captionWidth = estimateTextWidth(caption, NODE_CAPTION_FONT_SIZE)
  if (captionWidth > innerWidth) failures.push(`节点副文「${caption}」需要 ${captionWidth.toFixed(1)}px，方块只有 ${innerWidth}px`)
}

// 3. 连线标签不压节点、不互相压，且在画布内。
const labelRects: { edge: string; text: string; rect: Rect; baseline: number }[] = []
for (const edge of WORKBOARD_FLOW_EDGES) {
  if (!edge.label) continue
  const from = NODE_BOXES.get(edge.from)!
  const to = NODE_BOXES.get(edge.to)!
  const geometry = edgeGeometry(from, to, edge.from, edge.to, edge.kind)
  const rect = textRect(edge.label, geometry.label, geometry.anchor, EDGE_LABEL_FONT_SIZE)
  labelRects.push({ edge: `${edge.from}->${edge.to}`, text: edge.label, rect, baseline: geometry.label[1] })
}
for (const label of labelRects) {
  if (!rectContains(VIEW_RECT, label.rect)) failures.push(`连线标签「${label.text}」(${label.edge}) 超出画布`)
  // 统一基线：标签只能停在泳道带之间的空白走廊里，不许压在彩色泳道底色上。
  if (!LABEL_BASELINES.includes(label.baseline)) {
    failures.push(`连线标签「${label.text}」(${label.edge}) 的基线 ${label.baseline} 不在允许的标签走廊 ${LABEL_BASELINES.join(' / ')} 上`)
  }
  for (const band of LANE_BANDS) {
    if (rectsOverlap(label.rect, band.rect)) failures.push(`连线标签「${label.text}」(${label.edge}) 压在 ${band.lane} 泳道带上，应该落在带子之间的空白里`)
  }
  for (const [nodeId, rect] of nodeRects) {
    if (rectsOverlap(label.rect, rect)) failures.push(`连线标签「${label.text}」(${label.edge}) 压在节点 ${nodeId} 上`)
  }
}
failures.push(...overlappingPairs(labelRects.map((label) => ({ key: `连线标签「${label.text}」`, rect: label.rect }))))

// 4. 压在泳道底色或另一条线上的文字必须有同底色描边衬底。
const styles = readFileSync(resolve('src/media/studio/WorkboardFlowDiagram.module.css'), 'utf8')
for (const selector of ['.edge text', '.laneBand text']) {
  const block = new RegExp(`\\${selector.replace(/\s/g, '\\s')}\\s*\\{([^}]*)\\}`).exec(styles)?.[1] ?? ''
  if (!/paint-order:\s*stroke/.test(block)) failures.push(`${selector} 必须用 paint-order: stroke 做衬底`)
  if (!/stroke:\s*var\(--mg-surface\)/.test(block)) failures.push(`${selector} 的衬底必须用 --mg-surface，深色模式才跟着换`)
}

// 5. 任何断点都不许把图藏掉：窄屏要横向滚动，而不是 display:none 让流程图消失。
for (const block of styles.match(/[^{}]+\{[^{}]*\}/g) ?? []) {
  const [selector = '', declarations = ''] = block.split('{', 2)
  if (!/display:\s*none/.test(declarations)) continue
  if (/\.chart\b/.test(selector)) failures.push(`不能隐藏流程图容器 .chart（${selector.trim().replace(/\s+/g, ' ')}）——窄屏应横向滚动`)
  if (/\.svg\b/.test(selector)) failures.push(`不能隐藏流程图本身 .svg（${selector.trim().replace(/\s+/g, ' ')}）——窄屏应横向滚动`)
}
const chartBlock = /\.chart\s*\{([^}]*)\}/.exec(styles)?.[1] ?? ''
if (!/overflow-x:\s*auto/.test(chartBlock)) failures.push('.chart 必须 overflow-x: auto，窄屏才滚得动')
const svgBlock = /\.svg\s*\{([^}]*)\}/.exec(styles)?.[1] ?? ''
if (!/min-width:\s*\d/.test(svgBlock)) failures.push('.svg 必须有 min-width，窄屏才不会把图压扁')

if (failures.length) {
  throw new Error(`workboard flow layout failed:\n- ${failures.join('\n- ')}`)
}

console.log(`workboard flow layout: PASS nodes=${WORKBOARD_FLOW_NODES.length} lanes=${WORKBOARD_FLOW_LANES.length} labels=${labelRects.length} overlaps=0`)
