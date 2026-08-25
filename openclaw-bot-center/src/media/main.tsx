import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import MediaStudioApp from './MediaStudioApp'
import './media.css'
import './mediaStudioTheme.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MediaStudioApp />
  </StrictMode>,
)
