import { useEffect, useRef, useState } from 'react'
import { clipUrl, fetchSpeakers, type Job, type SpeakerInfo } from '../api'
import { t } from '../i18n'
import { formatDuration } from './JobCard'

interface Props {
  job: Job
  onSave: (names: Record<string, string>, summarize: boolean) => Promise<void>
  onSkip?: () => Promise<void>
  onClose: () => void
}

const OTHER = '__other__'

/** Zuordnung erkannter Stimmen zu Namen, mit Hörproben aus der Originalaufnahme. */
export default function SpeakerPanel({ job, onSave, onSkip, onClose }: Props) {
  const [info, setInfo] = useState<SpeakerInfo | null>(null)
  const [names, setNames] = useState<Record<string, string>>({})
  const [custom, setCustom] = useState<Record<string, boolean>>({})
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [playing, setPlaying] = useState<string | null>(null)
  const audio = useRef<HTMLAudioElement | null>(null)

  useEffect(() => {
    fetchSpeakers(job.id)
      .then((data) => {
        setInfo(data)
        // Leere Zuordnungen mit dem Vorschlag aus den Stimmprofilen vorbelegen
        const initial = Object.fromEntries(data.speakers.map((s) => [s.id, s.name || s.suggested || '']))
        setNames(initial)
        const known = new Set(data.players.map((p) => p.display))
        setCustom(Object.fromEntries(data.speakers.map((s) => [s.id, !!s.name && !known.has(s.name)])))
      })
      .catch((e: Error) => setError(e.message))
    return () => audio.current?.pause()
  }, [job.id])

  const play = (key: string, start: number, end: number) => {
    if (!audio.current) audio.current = new Audio()
    const player = audio.current
    if (playing === key) {
      player.pause()
      setPlaying(null)
      return
    }
    player.src = clipUrl(job.id, start, end)
    player.onended = () => setPlaying(null)
    player.onerror = () => {
      setPlaying(null)
      setError(t('Hörprobe konnte nicht geladen werden.'))
    }
    player.play().then(() => setPlaying(key)).catch(() => setPlaying(null))
  }

  const submit = async (summarize: boolean) => {
    setBusy(true)
    setError(null)
    try {
      await onSave(names, summarize)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const skip = async () => {
    if (!onSkip) return
    setBusy(true)
    try {
      await onSkip()
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  const used = new Set(Object.values(names).filter(Boolean))

  return (
    <div className="speaker-panel">
      <div className="speaker-panel-head">
        <h4>{t('Sprecher zuordnen')}</h4>
        <button className="btn ghost small" onClick={onClose}>
          {t('Abbrechen')}
        </button>
      </div>
      {!info && !error && <p className="hint">{t('Lade erkannte Stimmen …')}</p>}
      {error && <p className="error-text">{error}</p>}
      {info?.purity != null && (
        <p className={info.purity < 0.75 ? 'warn-text' : 'hint'}>
          {t('Stimmtrennung: {pct} % der geprüften Stellen eindeutig zugeordnet.', { pct: Math.round(info.purity * 100) })}
          {info.purity < 0.75 && ' ' + t('Einige Stimmen sind sich ähnlich – Hörproben genau anhören.')}{' '}
          {t('Die Hörproben sind die für jede Stimme typischsten Stellen, ohne Überlappung mit anderen Sprechern.')}
        </p>
      )}
      {info && !info.audio_available && (
        <p className="warn-text">{t('Die Audiodatei wurde bereits gelöscht – Hörproben sind nicht verfügbar.')}</p>
      )}

      {info?.speakers.map((speaker) => {
        const isCustom = custom[speaker.id] || info.players.length === 0
        return (
          <div key={speaker.id} className="speaker-row">
            <div className="speaker-label">
              <strong>{t('Stimme {id}', { id: speaker.id })}</strong>
              <span className="meta">
                {t('{duration} Redezeit · {n} Beiträge', { duration: formatDuration(speaker.seconds), n: speaker.utterances })}
                {speaker.suggested && speaker.similarity != null && (
                  <> · {t('Stimme ähnelt {name} ({pct} %)', { name: speaker.suggested, pct: Math.round(speaker.similarity * 100) })}</>
                )}
              </span>
              {info.players.length > 0 && (
                <select
                  value={isCustom ? OTHER : (names[speaker.id] ?? '')}
                  onChange={(e) => {
                    const value = e.target.value
                    setCustom((c) => ({ ...c, [speaker.id]: value === OTHER }))
                    setNames((n) => ({ ...n, [speaker.id]: value === OTHER ? '' : value }))
                  }}
                >
                  <option value="">{t('– nicht zugeordnet –')}</option>
                  {info.players.map((p) => (
                    <option key={p.display} value={p.display}>
                      {p.display}
                      {used.has(p.display) && names[speaker.id] !== p.display ? ' ✓' : ''}
                    </option>
                  ))}
                  <option value={OTHER}>{t('Andere Person …')}</option>
                </select>
              )}
              {isCustom && (
                <input
                  type="text"
                  placeholder={t('Name')}
                  value={names[speaker.id] ?? ''}
                  onChange={(e) => setNames((n) => ({ ...n, [speaker.id]: e.target.value }))}
                />
              )}
            </div>
            <ul className="samples">
              {speaker.samples.map((sample, i) => {
                const key = `${speaker.id}-${i}`
                return (
                  <li key={key}>
                    <button
                      className={`play${playing === key ? ' on' : ''}`}
                      disabled={!info.audio_available}
                      onClick={() => play(key, sample.start, sample.end)}
                      aria-label={playing === key ? t('Stopp') : t('Abspielen')}
                    >
                      {playing === key ? '■' : '▶'}
                    </button>
                    <span>„{sample.text}“</span>
                  </li>
                )
              })}
            </ul>
          </div>
        )
      })}

      {info && (
        <div className="actions">
          <div className="downloads">
            <button className="btn primary" disabled={busy} onClick={() => submit(true)}>
              {job.kind === 'dnd' ? t('Übernehmen & Recap erstellen') : t('Übernehmen & neu zusammenfassen')}
            </button>
            <button className="btn ghost" disabled={busy} onClick={() => submit(false)}>
              {t('Nur Transkript aktualisieren')}
            </button>
          </div>
          {onSkip && (
            <button className="btn ghost small" disabled={busy} onClick={skip}>
              {t('Ohne Zuordnung fortfahren')}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
