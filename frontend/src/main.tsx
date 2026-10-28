import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { setLanguage } from './i18n'
import './styles.css'

// Sprache und Anmeldepflicht vor dem ersten Rendern holen (Texte werden beim Rendern übersetzt)
fetch('/health')
  .then((r) => r.json())
  .catch(() => ({}))
  .then((health: { language?: string; auth_required?: boolean }) => {
    setLanguage(health.language)
    createRoot(document.getElementById('root')!).render(
      <StrictMode>
        <App authRequired={health.auth_required === true} />
      </StrictMode>,
    )
  })
