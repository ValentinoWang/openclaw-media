import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 能力中心主应用（src/main.tsx）。仓库整合时入口层（index.html / vite.config.ts）
// 未随源码迁入，此处按 vite.media.config.ts 的同款约定补齐：
// 部署在 /openclaw/ 下（media 壳层的「返回租户工作台」链接即指向这里）。
export default defineConfig({
  base: '/openclaw/',
  plugins: [react(), tailwindcss()],
  build: { outDir: 'dist', emptyOutDir: true },
})
