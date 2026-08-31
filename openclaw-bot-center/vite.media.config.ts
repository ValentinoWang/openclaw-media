import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'
import { copyFileSync, cpSync, existsSync, renameSync } from 'node:fs'

export default defineConfig({
  base: '/openclaw/media/',
  publicDir: false,
  resolve: {
    alias: {
      '/mediaDesignTokens.css': resolve(__dirname, 'src/media/mediaDesignTokens.css'),
    },
  },
  plugins: [
    react(),
    {
      name: 'media-index-name',
      closeBundle() {
        // 构建失败时 vite 仍会触发 closeBundle；此时 dist-media 不存在，
        // 这里的 copy/rename 会抛 ENOENT 并把真实构建错误顶掉。先行短路。
        if (!existsSync(resolve(__dirname, 'dist-media'))) return
        const source = resolve(__dirname, 'dist-media/index.media.html')
        if (existsSync(source)) renameSync(source, resolve(__dirname, 'dist-media/index.html'))
        const loginSource = resolve(__dirname, 'dist-media/media.login.html')
        if (existsSync(loginSource)) renameSync(loginSource, resolve(__dirname, 'dist-media/login.html'))
        const registerSource = resolve(__dirname, 'dist-media/media.register.html')
        if (existsSync(registerSource)) renameSync(registerSource, resolve(__dirname, 'dist-media/register.html'))
        for (const [sourceName, targetName] of [
          ['media.verify.html', 'verify.html'],
          ['media.recover.html', 'recover.html'],
          ['media.reset.html', 'reset.html'],
        ]) {
          const candidates = [
            resolve(__dirname, `dist-media/${sourceName}`),
            resolve(__dirname, `dist-media/src/${sourceName}`),
          ]
          const source = candidates.find((candidate) => existsSync(candidate))
          if (source) renameSync(source, resolve(__dirname, `dist-media/${targetName}`))
        }
        const authScriptSource = resolve(__dirname, 'media.login.js')
        if (existsSync(authScriptSource)) copyFileSync(authScriptSource, resolve(__dirname, 'dist-media/media.login.js'))
        const authCssSource = resolve(__dirname, 'src/media.auth.css')
        if (existsSync(authCssSource)) copyFileSync(authCssSource, resolve(__dirname, 'dist-media/media.auth.css'))
        const tokenCssSource = resolve(__dirname, 'src/media/mediaDesignTokens.css')
        if (!existsSync(tokenCssSource)) throw new Error('missing mediaDesignTokens.css source')
        copyFileSync(tokenCssSource, resolve(__dirname, 'dist-media/mediaDesignTokens.css'))
        const fontCssSource = resolve(__dirname, 'src/media/mediaFonts.css')
        const fontDirectory = resolve(__dirname, 'src/media/fonts')
        if (!existsSync(fontCssSource) || !existsSync(fontDirectory)) throw new Error('missing local media font source')
        copyFileSync(fontCssSource, resolve(__dirname, 'dist-media/mediaFonts.css'))
        cpSync(fontDirectory, resolve(__dirname, 'dist-media/fonts'), { recursive: true })
      },
    },
  ],
  build: {
    outDir: 'dist-media',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: resolve(__dirname, 'index.media.html'),
        login: resolve(__dirname, 'media.login.html'),
        'media.login': resolve(__dirname, 'media.login.js'),
        register: resolve(__dirname, 'media.register.html'),
        verify: resolve(__dirname, 'src/media.verify.html'),
        recover: resolve(__dirname, 'src/media.recover.html'),
        reset: resolve(__dirname, 'src/media.reset.html'),
      },
    },
  },
})
