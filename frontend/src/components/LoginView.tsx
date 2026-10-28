import { type FormEvent, useState } from 'react'
import { Brand } from '../App'
import { login } from '../api'
import { t } from '../i18n'

/** Anmeldung, wenn in den Einstellungen ein API-Schlüssel oder Dashboard-Passwort gesetzt ist. */
export default function LoginView({ onLogin }: { onLogin: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(password)
      onLogin()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page login-page">
      <header className="topbar">
        <Brand />
      </header>
      <form className="login-card" onSubmit={submit}>
        <h2>{t('Anmelden')}</h2>
        <p className="hint">{t('Dashboard-Passwort oder API-Schlüssel dieser WhisperNotes-Installation.')}</p>
        <input type="password" autoComplete="current-password" autoFocus value={password}
          aria-label={t('Passwort')} placeholder={t('Passwort')} onChange={(e) => setPassword(e.target.value)} />
        {error && <p className="error-text">{error}</p>}
        <button className="btn primary" type="submit" disabled={busy || !password}>
          {busy ? t('Prüfe …') : t('Anmelden')}
        </button>
      </form>
    </div>
  )
}
