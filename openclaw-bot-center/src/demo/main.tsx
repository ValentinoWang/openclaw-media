/** 演示站入口：与 `src/media/main.tsx` 渲染同一个 MediaStudioApp，区别只有三点——
 *  先装上浏览器内假后端，站点根路径先给一张封面页，再挂一个演示导航控制台。 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import DemoShell from './DemoShell'
import { installDemoBackend } from './demoBackend'
import '../media/mediaDesignTokens.css'
import '../media/media.css'
import '../media/mediaPrimitives.css'
import '../media/mediaStudioTheme.css'

installDemoBackend()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <DemoShell />
  </StrictMode>,
)
