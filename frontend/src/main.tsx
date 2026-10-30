import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { reloadOnce } from './lib/staleTab'

// A tab open across a deploy asks for chunks that are gone (issue 0061): reload once into
// the new build. When that did not help, the error screen offers the reload instead.
window.addEventListener('vite:preloadError', (event) => {
  if (reloadOnce(window.sessionStorage, import.meta.url, Date.now())) {
    event.preventDefault()
    window.location.reload()
  }
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
