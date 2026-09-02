import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'
import { cpSync, copyFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { demoStaticRoutes } from './src/demo/demoRoutes.ts'
import { renderDemoIndex } from './scripts/demo/renderDemoIndex.ts'

/** 演示站部署基址。默认与生产 `/openclaw/media/` 同级，换位置时用
 *  `MEDIA_DEMO_BASE=/your/path/ npm run build:demo` 重新构建即可。 */
const base = process.env.MEDIA_DEMO_BASE ?? '/openclaw/media-demo/'
const outDir = 'dist-demo'

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
      closeBundle() {
        const root = resolve(__dirname, outDir)
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
