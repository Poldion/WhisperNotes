import { useEffect, useState } from 'react'
import { fetchHealth, type Health } from '../api'
import { locale, t } from '../i18n'

const whisperLabel = (state: Health['whisper']) =>
  state === 'active' ? t('Whisper aktiv') : state === 'starting' ? t('Whisper startet') : t('Whisper im Ruhezustand')

export default function HealthBadge() {
  const [health, setHealth] = useState<Health | null>(null)
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    let alive = true
    const poll = () =>
      fetchHealth()
        .then((h) => alive && (setHealth(h), setOffline(false)))
        .catch(() => alive && setOffline(true))
    poll()
    const timer = setInterval(poll, 5000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [])

  if (offline) {
    return (
      <div className="health">
        <span className="pill bad"><i />{t('Wrapper offline')}</span>
      </div>
    )
  }
  if (!health?.ollama) return <div className="health" />

  const { ollama } = health
  const ollamaText = !ollama.reachable
    ? t('Ollama nicht erreichbar')
    : ollama.active_model
      ? `Ollama: ${ollama.active_model}`
      : ollama.fallback_model
        ? t('Ollama: kein Modell geladen (Fallback: {model})', { model: ollama.fallback_model })
        : t('Ollama: kein Modell geladen')
  const ollamaTone = !ollama.reachable ? 'bad' : ollama.active_model ? 'ok' : 'warn'

  return (
    <div className="health">
      <span className={`pill ${health.whisper === 'inactive' ? 'idle' : 'ok'}`} title={whisperTitle(health)}>
        <i />
        {whisperLabel(health.whisper)}
        {health.queue_depth > 0 && <b className="count">{t('{n} wartend', { n: health.queue_depth })}</b>}
      </span>
      <span
        className={`pill ${ollamaTone}`}
        title={
          ollama.configured_model
            ? t('Fest eingestelltes Modell für Zusammenfassungen ({model})', { model: ollama.configured_model })
            : t('Für Zusammenfassungen wird das aktuell geladene Ollama-Modell genutzt')
        }
      >
        <i />
        {ollamaText}
      </span>
      <StoragePill storage={health.storage} />
    </div>
  )
}

function whisperTitle(h: Health) {
  if (h.seconds_since_last_request == null) return t('Seit dem Start noch keine Anfrage')
  const idle = Math.round(h.seconds_since_last_request)
  return h.whisper === 'active'
    ? t('Letzte Anfrage vor {idle} s. Abschaltung nach {timeout} s Leerlauf', { idle, timeout: h.idle_timeout_seconds })
    : t('Letzte Anfrage vor {idle} s', { idle })
}

function StoragePill({ storage }: { storage: Health['storage'] }) {
  const gb = (bytes: number) => (bytes / 1024 ** 3).toLocaleString(locale(), { maximumFractionDigits: 1 })
  const { audio_bytes: used, limit_bytes: limit } = storage
  const tone = limit && used > limit * 0.9 ? 'warn' : 'idle'
  return (
    <span
      className={`pill ${tone}`}
      title={limit ? t('Bei Überschreitung wird das Audio der ältesten Aufnahmen gelöscht, Transkripte bleiben') : t('Kein Speicherlimit gesetzt')}
    >
      <i />
      Audio {gb(used)}{limit ? ` / ${gb(limit)}` : ''} GB
    </span>
  )
}
