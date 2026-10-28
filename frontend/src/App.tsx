import { useEffect, useState } from 'react'
import { logout, onUnauthorized } from './api'
import DndView from './components/DndView'
import HealthBadge from './components/HealthBadge'
import LoginView from './components/LoginView'
import RecordingsView from './components/RecordingsView'
import SettingsView from './components/SettingsView'
import { t } from './i18n'
import { useJobs } from './useJobs'
import { WhisperModelProvider } from './whisperModels'

type Tab = 'aufnahmen' | 'dnd' | 'einstellungen'

const tabFromHash = (): Tab =>
  window.location.hash === '#dnd' ? 'dnd' : window.location.hash === '#einstellungen' ? 'einstellungen' : 'aufnahmen'

/** Nach der Anmeldung zurück zu dem Link, mit dem man gekommen ist (z. B. ein Transkript aus BasaltNotes). */
function returnToNext() {
  const next = new URLSearchParams(window.location.search).get('next')
  if (next && next.startsWith('/') && !next.startsWith('//')) window.location.replace(next)
  else window.history.replaceState(null, '', window.location.pathname + window.location.hash)
}

export default function App({ authRequired }: { authRequired: boolean }) {
  const [loggedIn, setLoggedIn] = useState(!authRequired)

  useEffect(() => onUnauthorized(() => setLoggedIn(false)), [])

  if (!loggedIn) {
    return (
      <LoginView
        onLogin={() => {
          setLoggedIn(true)
          returnToNext()
        }}
      />
    )
  }
  return (
    <WhisperModelProvider>
      <Dashboard canLogout={authRequired} onLogout={() => logout().then(() => setLoggedIn(false))} />
    </WhisperModelProvider>
  )
}

function Dashboard({ canLogout, onLogout }: { canLogout: boolean; onLogout: () => void }) {
  const jobsApi = useJobs()
  const [tab, setTab] = useState<Tab>(tabFromHash)

  useEffect(() => {
    const onHash = () => setTab(tabFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const select = (next: Tab) => {
    window.location.hash = next === 'aufnahmen' ? '' : next
    setTab(next)
  }

  return (
    <div className="page">
      <header className="topbar">
        <Brand />
        <HealthBadge />
      </header>

      <nav className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'aufnahmen'} className={tab === 'aufnahmen' ? 'active' : ''}
          onClick={() => select('aufnahmen')}>
          {t('Aufnahmen')}
        </button>
        <button role="tab" aria-selected={tab === 'dnd'} className={tab === 'dnd' ? 'active' : ''}
          onClick={() => select('dnd')}>
          <span aria-hidden>🎲</span> {t('DnD-Sessions')}
        </button>
        <button role="tab" aria-selected={tab === 'einstellungen'}
          className={`tab-end${tab === 'einstellungen' ? ' active' : ''}`} onClick={() => select('einstellungen')}>
          <span aria-hidden>⚙</span> {t('Einstellungen')}
        </button>
        {canLogout && (
          <button className="tab-logout" onClick={onLogout}>
            {t('Abmelden')}
          </button>
        )}
      </nav>

      <main>
        {tab === 'aufnahmen' && <RecordingsView api={jobsApi} />}
        {tab === 'dnd' && <DndView api={jobsApi} />}
        {tab === 'einstellungen' && <SettingsView />}
      </main>
    </div>
  )
}

export function Brand() {
  return (
    <div className="brand">
      <span className="logo" aria-hidden>
        <svg viewBox="0 0 32 32">
          <path d="M9 13v6M13 10v12M17 7v18M21 11v10M25 14v4" />
        </svg>
      </span>
      <div>
        <h1>WhisperNotes</h1>
        <p>{t('Lokale Transkription & Zusammenfassung')}</p>
      </div>
    </div>
  )
}
