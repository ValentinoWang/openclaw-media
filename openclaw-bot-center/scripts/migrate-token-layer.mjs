#!/usr/bin/env node
/**
 * 结构性改动（幂等，可重复执行）：
 *   1. main.tsx 按 token 层 -> media.css -> primitives -> studio 皮肤的顺序导入
 *   2. mediaStudioTheme.css 删除 :root —— 它此前覆盖了 media.css 的 19/25 个 token
 *   3. media.css 的 :root 收敛到 checkMediaDesignSystemContract.ts 断言的三个尺寸 token
 */
import fs from 'node:fs'
import path from 'node:path'

const MEDIA = path.resolve(import.meta.dirname, '../src/media')
const done = []

/* 1. main.tsx */
{
  const p = path.join(MEDIA, 'main.tsx')
  let s = fs.readFileSync(p, 'utf8')
  if (!s.includes('mediaDesignTokens.css')) {
    const old = "import './media.css'\nimport './mediaStudioTheme.css'"
    if (!s.includes(old)) throw new Error('main.tsx: import block not found')
    s = s.replace(old, [
      "import './mediaDesignTokens.css'",
      "import './media.css'",
      "import './mediaPrimitives.css'",
      "import './mediaStudioTheme.css'",
    ].join('\n'))
    fs.writeFileSync(p, s)
    done.push('main.tsx import order')
  }
}

/* 2. mediaStudioTheme.css */
{
  const p = path.join(MEDIA, 'mediaStudioTheme.css')
  let s = fs.readFileSync(p, 'utf8')
  const m = s.match(/^:root \{[\s\S]*?\n\}\n\n/)
  if (m) {
    if (!m[0].includes('--mg-primary')) throw new Error('studio theme: unexpected :root')
    s = '/* MediaClaw Studio 壳层皮肤\n'
      + '   token 已全部迁到 mediaDesignTokens.css —— 此文件不再定义 :root，\n'
      + '   避免与 media.css 争夺同一批变量（改造前 25 个 token 有 19 个被静默覆盖）。 */\n\n'
      + s.slice(m[0].length)
    fs.writeFileSync(p, s)
    done.push(`mediaStudioTheme.css :root removed (${m[0].split(';').length - 1} decls)`)
  }
}

/* 3. media.css */
{
  const p = path.join(MEDIA, 'media.css')
  let s = fs.readFileSync(p, 'utf8')
  const m = s.match(/^:root \{[^}]*\}\n/)
  if (m && m[0].includes('--mg-primary')) {
    const n = m[0].split(';').length - 1
    s = ':root {\n'
      + '  /* 仅保留 checkMediaDesignSystemContract.ts 断言的组件尺寸 token。\n'
      + '     颜色 / 字阶 / 圆角 / 阴影一律由 mediaDesignTokens.css 提供；\n'
      + '     此处若再声明颜色，会覆盖先导入的 token 层。 */\n'
      + '  --mg-control-height-sm: 36px;\n'
      + '  --mg-control-height-md: 44px;\n'
      + '  --mg-panel-heading-height: 54px;\n'
      + '}\n'
      + s.slice(m[0].length)
    fs.writeFileSync(p, s)
    done.push(`media.css :root trimmed ${n} -> 3 decls`)
  }
}

console.log(done.length ? done.map((d) => '✓ ' + d).join('\n') : '✓ already applied (no-op)')
