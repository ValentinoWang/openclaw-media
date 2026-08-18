import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import MediaApp from './MediaApp'
import './media.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MediaApp />
  </StrictMode>,
)
