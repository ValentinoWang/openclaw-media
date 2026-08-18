import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'
import { copyFileSync, existsSync, renameSync } from 'node:fs'

export default defineConfig({
  base: '/openclaw/media/',
  publicDir: false,
  plugins: [
    react(),
    {
      name: 'media-index-name',
      closeBundle() {
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
        'media.auth': resolve(__dirname, 'src/media.auth.css'),
        register: resolve(__dirname, 'media.register.html'),
        verify: resolve(__dirname, 'src/media.verify.html'),
        recover: resolve(__dirname, 'src/media.recover.html'),
        reset: resolve(__dirname, 'src/media.reset.html'),
      },
    },
  },
})
