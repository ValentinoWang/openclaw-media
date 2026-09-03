import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'
import { cpSync, copyFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { demoStaticRoutes } from './src/demo/demoRoutes.ts'
import { renderDemoIndex } from './scripts/demo/renderDemoIndex.ts'
import { writeDemoAuthPages } from './scripts/demo/buildDemoAuthPages.ts'

/** 演示站部署基址。默认与生产 `/openclaw/media/` 同级，换位置时用
 *  `MEDIA_DEMO_BASE=/your/path/ npm run build:demo` 重新构建即可。 */
const base = process.env.MEDIA_DEMO_BASE ?? '/openclaw/media-demo/'
const outDir = 'dist-demo'
/** 后处理要写到**实际**的产物目录：命令行的 `--outDir` 会覆盖上面的默认值，
 *  而重命名首页、拷字体与令牌、生成每条路由的静态页这些步骤如果继续按默认值写，
 *  就会写进共用的 dist-demo，把别人的产物改坏（并行验证时踩过这个坑）。
 *  真实值在 configResolved 里拿。 */
let resolvedOutDir = resolve(__dirname, outDir)

export default defineConfig({
  base,
  publicDir: false,
  resolve: {
    alias: {
      '/mediaDesignTokens.css': resolve(__dirname, 'src/media/mediaDesignTokens.css'),
    },
  },
  plugins: [
    react(),
    {
      name: 'media-demo-static-pages',
      configResolved(config) {
        resolvedOutDir = resolve(config.root, config.build.outDir)
      },
      closeBundle() {
        const root = resolvedOutDir
        // 构建失败时 vite 仍会触发 closeBundle，此时产物目录不存在。
        if (!existsSync(root)) return

        const built = resolve(root, 'index.demo.html')
        const indexPath = resolve(root, 'index.html')
        if (existsSync(built)) renameSync(built, indexPath)

        const tokenCss = resolve(__dirname, 'src/media/mediaDesignTokens.css')
        const fontCss = resolve(__dirname, 'src/media/mediaFonts.css')
        const fontDirectory = resolve(__dirname, 'src/media/fonts')
        if (!existsSync(tokenCss) || !existsSync(fontCss) || !existsSync(fontDirectory)) {
          throw new Error('missing media design token or local font source')
        }
        copyFileSync(tokenCss, resolve(root, 'mediaDesignTokens.css'))
        copyFileSync(fontCss, resolve(root, 'mediaFonts.css'))
        cpSync(fontDirectory, resolve(root, 'fonts'), { recursive: true })

        // 每个路由落一个真实 HTML 文件：没有 SPA 回退的静态服务器也能直接打开深链接。
        const shell = readFileSync(indexPath, 'utf8')
        for (const route of demoStaticRoutes) {
          const directory = resolve(root, route.replace(/^\//, ''))
          mkdirSync(directory, { recursive: true })
          writeFileSync(resolve(directory, 'index.html'), shell, 'utf8')
        }
        writeFileSync(resolve(root, '404.html'), shell, 'utf8')

        // 登录/注册等认证页也复刻进来，但只保留页面结构：提交一律被拦截。
        writeDemoAuthPages({ root, base })

        // 纯静态的站点导航页：不依赖 JavaScript，可作为演示站的对外入口。
        writeFileSync(
          resolve(root, 'pages.html'),
          renderDemoIndex({ base, generatedAt: new Date().toISOString() }),
          'utf8',
        )
      },
    },
  ],
  build: {
    outDir,
    emptyOutDir: true,
    rollupOptions: {
      input: { index: resolve(__dirname, 'index.demo.html') },
    },
  },
})
