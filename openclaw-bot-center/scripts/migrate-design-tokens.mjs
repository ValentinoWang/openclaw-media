#!/usr/bin/env node
/**
 * 一次性迁移：把 src/media 下的散装 CSS 值收敛到 mediaDesignTokens.css 的 token。
 *
 *   node scripts/migrate-design-tokens.mjs --dry    # 只报告
 *   node scripts/migrate-design-tokens.mjs          # 写盘
 *
 * 幂等：已经是 var(--mg-*) 的值不会被再次处理。
 *
 * 三个必须小心的地方（都在本脚本里显式处理）：
 *   1. box-shadow: 0 0 0 Npx …  是焦点环，不是高度层级，必须原样保留。
 *   2. color: white 叠在饱和 accent 上，两个主题下都应保持亮色，不要换成 --mg-surface。
 *      只有 background / border 里的白才需要跟随主题。
 *   3. media.css 的 :root 受 checkMediaDesignSystemContract.ts 字面量断言保护。
 */
import fs from 'node:fs'
import path from 'node:path'

const DRY = process.argv.includes('--dry')
const MEDIA = path.resolve(import.meta.dirname, '../src/media')
const SKIP = new Set(['mediaDesignTokens.css', 'mediaPrimitives.css'])

/* ---------- 字阶 ---------- */
const fontToken = (px) =>
  px < 10.1 ? '--mg-text-2xs'
  : px < 11.3 ? '--mg-text-xs'
  : px < 12.6 ? '--mg-text-sm'
  : px < 14.2 ? '--mg-text-md'
  : px < 17.5 ? '--mg-text-lg'
  : px < 24.9 ? '--mg-text-xl'
  : px < 31.3 ? '--mg-text-2xl'
  : '--mg-text-3xl'

/* ---------- 圆角 ---------- */
const radiusToken = (px) =>
  px <= 4 ? '--mg-r-xs'
  : px <= 7 ? '--mg-r-sm'
  : px <= 13 ? '--mg-r-md'
  : px <= 18 ? '--mg-r-lg'
  : '--mg-r-xl'

/* ---------- 阴影 ----------
   把颜色函数整体挖掉，剩下的才是 offset-x / offset-y / blur / spread。 */
function shadowToken(value) {
  const geometry = value.replace(/(?:rgba?|hsla?|oklch|color-mix|var)\([^)]*\)/g, ' ')
  const nums = [...geometry.matchAll(/(-?[\d.]+)(?:px)?/g)]
    .map((m) => Number(m[1]))
    .filter((n) => !Number.isNaN(n))
  const [x = 0, y = 0, blur = 0] = nums
  // 焦点环 / 描边：无偏移无模糊，只有 spread
  if (x === 0 && y === 0 && blur === 0) return null
  const reach = Math.max(Math.abs(blur), Math.abs(y))
  return reach <= 4 ? '--mg-e1' : reach <= 16 ? '--mg-e2' : reach <= 34 ? '--mg-e3' : '--mg-e4'
}

/* ---------- 各 Studio 页的 accent 映射（含渐变色标）---------- */
const ACCENT_MAPS = {
  'studio/CampaignsPage.module.css': {
    '#5b4bb5': 'var(--accent-base)', '#4e419d': 'var(--accent-ink)', '#5144a9': 'var(--accent-ink)',
    '#efecff': 'var(--accent-soft)', '#f3f0ff': 'var(--accent-soft)', '#f1edff': 'var(--accent-soft)',
    '#e6e0ff': 'var(--accent-soft)', '#f9f7ff': 'var(--mg-bg)',
    '#ded9fa': 'var(--accent-line)', '#d5cff5': 'var(--accent-line)', '#d8d2f3': 'var(--accent-line)',
    '#8c7be1': 'color-mix(in srgb, var(--accent-base) 68%, var(--mg-surface))',
    '#b2abc9': 'var(--mg-muted)',
  },
  'studio/BusinessPage.module.css': {
    '#ad6426': 'var(--accent-base)', '#95551f': 'var(--accent-ink)',
    '#fff0df': 'var(--accent-soft)', '#fff7ef': 'var(--accent-soft)', '#ffe8ce': 'var(--accent-soft)',
    '#fffaf5': 'var(--mg-bg)',
    '#f0dcc6': 'var(--accent-line)', '#efd4ba': 'var(--accent-line)',
    '#c5a98d': 'var(--mg-muted)',
  },
  'studio/DeskPage.module.css': {
    '#376da9': 'var(--accent-base)', '#2f6198': 'var(--accent-ink)',
    '#eaf2fc': 'var(--accent-soft)', '#f2f7fd': 'var(--accent-soft)', '#dceafa': 'var(--accent-soft)',
    '#f7fbff': 'var(--mg-bg)',
    '#cfdeef': 'var(--accent-line)', '#cbdced': 'var(--accent-line)', '#7aa3d0': 'var(--accent-line)',
    '#9aafc5': 'var(--mg-muted)',
    '#9c6036': 'var(--mg-accent-business-base)', '#fff0e6': 'var(--mg-accent-business-soft)',
    '#7962bd': 'var(--mg-accent-campaign-base)', '#f0ecff': 'var(--mg-accent-campaign-soft)',
    '#208661': 'var(--mg-accent-studio-base)',   '#e3f5ec': 'var(--mg-accent-studio-soft)',
  },
  'studio/WorkboardPage.module.css': {
    '#6b5bc7': 'var(--mg-accent-campaign-base)', '#5144a9': 'var(--mg-accent-campaign-ink)',
    '#f0edff': 'var(--mg-accent-campaign-soft)',
    '#fbfcf8': 'var(--mg-bg)', '#f0f7f2': 'var(--accent-soft)',
  },
}

/* ---------- 全局语义色 ---------- */
const SEMANTIC = {
  '#173029': 'var(--mg-sidebar)', '#17241f': 'var(--mg-ink)', '#3f4f47': 'var(--mg-ink-soft)',
  '#68756e': 'var(--mg-muted)', '#68756f': 'var(--mg-muted)',
  '#239b69': 'var(--mg-primary)', '#126344': 'var(--mg-primary-dark)', '#dff4e8': 'var(--mg-primary-soft)',
  '#0e573c': 'var(--mg-primary-dark)', '#07553b': 'var(--mg-primary-dark)',
  '#f4f6f1': 'var(--mg-bg)', '#f4f7f5': 'var(--mg-bg)',
  '#dde5de': 'var(--mg-border)', '#cbd7ce': 'var(--mg-border-strong)',
  '#a96d18': 'var(--mg-warning)', '#fff0d2': 'var(--mg-warning-soft)', '#b77700': 'var(--mg-warning)',
  '#bd5147': 'var(--mg-danger)', '#fde9e6': 'var(--mg-danger-soft)',
  '#4179b8': 'var(--mg-blue)', '#e8f1fb': 'var(--mg-blue-soft)',
}

/** 把 background / border 里的白换成跟随主题的 surface；color 里的白保持不动。 */
function themeWhites(value) {
  return value
    .replace(/rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*(\.?\d+)\s*\)/g,
      (_, a) => `color-mix(in srgb, var(--mg-surface) ${Math.round(parseFloat(a) * 100)}%, transparent)`)
    .replace(/\bwhite\b/g, 'var(--mg-surface)')
    .replace(/#ffffff\b/gi, 'var(--mg-surface)')
    .replace(/#fff\b(?![0-9a-f])/gi, 'var(--mg-surface)')
}

const walk = (dir) => fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
  const p = path.join(dir, e.name)
  if (e.isDirectory()) return walk(p)
  return e.name.endsWith('.css') && !SKIP.has(e.name) ? [p] : []
})

const stats = { font: 0, radius: 0, shadow: 0, ring: 0, color: 0, white: 0 }
const perFile = []

for (const file of walk(MEDIA)) {
  const rel = path.relative(MEDIA, file).replace(/\\/g, '/')
  const before = fs.readFileSync(file, 'utf8')
  let s = before
  const local = { font: 0, radius: 0, shadow: 0, ring: 0, color: 0, white: 0 }

  // media.css 的 :root 必须保持字面量
  let guard = ''
  if (rel === 'media.css') {
    const m = s.match(/^:root \{[\s\S]*?\n\}\n/)
    if (m) { guard = m[0]; s = s.slice(m[0].length) }
  }

  // --- 字号 ---
  s = s.replace(/font-size:\s*(\d*\.?\d+)(rem|px)\b/g, (full, n, unit) => {
    const px = unit === 'rem' ? Number(n) * 16 : Number(n)
    if (px >= 44) return full
    local.font++
    return `font-size: var(${fontToken(px)})`
  })
  s = s.replace(/font-size:\s*clamp\([^)]*\)/g, () => { local.font++; return 'font-size: var(--mg-text-3xl)' })

  // --- 圆角（单值）---
  s = s.replace(/border-radius:\s*(\d+)px\b(?![^;}]*\d+px)/g, (full, px) => {
    const n = Number(px)
    if (n === 0) return full
    if (n >= 900) { local.radius++; return 'border-radius: var(--mg-r-full)' }
    local.radius++
    return `border-radius: var(${radiusToken(n)})`
  })

  // --- 阴影 ---
  s = s.replace(/box-shadow:\s*([^;}]+)/g, (full, value) => {
    if (/var\(--mg-e|inset|none/.test(value)) return full
    const token = shadowToken(value)
    if (!token) { local.ring++; return full }   // 焦点环，保留
    local.shadow++
    return `box-shadow: var(${token})`
  })

  // --- 页面 accent 色 ---
  for (const [hex, token] of Object.entries(ACCENT_MAPS[rel] ?? {})) {
    const re = new RegExp(hex + '\\b', 'gi')
    const hits = (s.match(re) || []).length
    if (hits) { s = s.replace(re, token); local.color += hits }
  }
  // --- 全局语义色 ---
  for (const [hex, token] of Object.entries(SEMANTIC)) {
    const re = new RegExp(hex + '\\b', 'gi')
    const hits = (s.match(re) || []).length
    if (hits) { s = s.replace(re, token); local.color += hits }
  }

  // --- background / border 里的白 -> 跟随主题 ---
  s = s.replace(/((?:background|border|border-color|border-top|border-bottom|border-left|border-right|outline)\s*:\s*)([^;}]+)/g,
    (full, prop, value) => {
      const next = themeWhites(value)
      if (next === value) return full
      local.white++
      return prop + next
    })

  s = guard + s
  if (s !== before) {
    for (const k of Object.keys(local)) stats[k] += local[k]
    perFile.push([rel, local])
    if (!DRY) fs.writeFileSync(file, s)
  }
}

perFile.sort((a, b) => Object.values(b[1]).reduce((x, y) => x + y, 0) - Object.values(a[1]).reduce((x, y) => x + y, 0))
console.log(`${DRY ? '[DRY RUN] ' : ''}files changed: ${perFile.length}`)
console.log(`  font-size   -> token : ${stats.font}`)
console.log(`  radius      -> token : ${stats.radius}`)
console.log(`  box-shadow  -> token : ${stats.shadow}   (focus rings preserved: ${stats.ring})`)
console.log(`  hex color   -> token : ${stats.color}`)
console.log(`  themed white decls   : ${stats.white}`)
console.log('\ntop files:')
for (const [rel, l] of perFile.slice(0, 12)) {
  console.log(`  ${rel.padEnd(46)} f=${l.font} r=${l.radius} sh=${l.shadow} ring=${l.ring} c=${l.color} w=${l.white}`)
}
