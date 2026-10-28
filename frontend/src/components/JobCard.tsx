import { useState } from 'react'
import { downloadUrl, extraDocLabel, isTerminal, type Job } from '../api'
import { locale, t } from '../i18n'
import type { JobsApi } from '../useJobs'
import { useWhisperModels } from '../whisperModels'
import MarkdownViewer, { type DocKind } from './MarkdownViewer'
import SpeakerPanel from './SpeakerPanel'

const statusLabel = (status: Job['status']) =>
  ({
    queued: t('Wartet'),
    slicing: t('Analysiere'),
    transcribing: t('Transkribiere'),
    awaiting_speakers: t('Sprecher zuordnen'),
    summarizing: t('Fasse zusammen'),
    done: t('Fertig'),
    error: t('Fehler'),
    cancelled: t('Abgebrochen'),
  })[status]

export default function JobCard({ job, api }: { job: Job; api: JobsApi }) {
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [showSpeakers, setShowSpeakers] = useState(false)
  const [viewing, setViewing] = useState<DocKind | null>(null)
  const whisper = useWhisperModels()
  const chooseModel = whisper.models.length > 1
  const running = !isTerminal(job)
  const awaiting = job.status === 'awaiting_speakers'
  const isDnd = job.kind === 'dnd'

  const act = async (fn: () => Promise<void>) => {
    setBusy(true)
    setActionError(null)
    try {
      await fn()
    } catch (e) {
      setActionError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const heading = isDnd ? (job.session_title ?? job.filename) : (job.title ?? job.filename)
  const speakerNames = Object.values(job.speakers)

  return (
    <article className={`job ${job.status}`}>
      <div className="job-head">
        <div className="job-title">
          <h3 title={job.filename}>{heading}</h3>
          <p className="meta">
            {formatDate(job.recorded_at ?? job.created_at)}
            {job.duration_seconds != null && <> · {formatDuration(job.duration_seconds)}</>}
            {job.chunks_total > 1 && <> · {t('{n} Abschnitte', { n: job.chunks_total })}</>}
            {job.has_speakers && (
              <> · {speakerNames.length ? speakerNames.join(', ') : t('{n} Sprecher', { n: job.speaker_count })}</>
            )}
            {job.speakers_auto && (
              <span title={t('Über die gespeicherten Stimmen der Kampagne zugeordnet – falls falsch: „Sprecher benennen“')}>
                {' '}· {t('Stimmen automatisch erkannt')}
              </span>
            )}
            {chooseModel && job.has_transcript && <> · Whisper {whisper.labelOf(job.whisper_model)}</>}
            {job.ollama_model && <> · {job.ollama_model}</>}
            {job.source_label && (
              <>
                {' · '}
                <span className="source-badge" title={job.discord_posted_at ? t('In Discord gepostet') : undefined}>
                  {job.source_label}
                  {job.discord_posted_at ? ' ✓' : ''}
                </span>
              </>
            )}
            {job.audio_deleted && (
              <> · <span title={t('Wegen des Speicherlimits entfernt, Transkript und Zusammenfassung bleiben')}>{t('Audio entfernt')}</span></>
            )}
          </p>
        </div>
        <span className={`status ${job.status}`}>{statusLabel(job.status)}</span>
      </div>

      {running && (
        <div className="progress">
          <div className="bar">
            <div style={{ width: `${job.progress}%` }} />
          </div>
          <div className="progress-text">
            <span>{job.message}</span>
            <span className="progress-right">
              <span className="pct">{Math.round(job.progress)} %</span>
              <button
                className="btn ghost small danger"
                disabled={busy || job.message === t('Wird abgebrochen …')}
                onClick={() =>
                  confirm(
                    job.status === 'queued'
                      ? t('„{title}“ aus der Warteschlange nehmen?', { title: heading })
                      : t('Verarbeitung von „{title}“ abbrechen? Bisher Transkribiertes wird verworfen.', { title: heading }),
                  ) && act(() => api.cancel(job.id))
                }
              >
                {t('Abbrechen')}
              </button>
            </span>
          </div>
        </div>
      )}

      {awaiting && !showSpeakers && (
        <div className="callout">
          <span>
            {t('{n} Stimmen erkannt. Ordne sie den Spielern zu, dann wird der Recap mit Namen erstellt.', { n: job.speaker_count })}
          </span>
          <button className="btn primary small" onClick={() => setShowSpeakers(true)}>
            {t('Sprecher zuordnen')}
          </button>
        </div>
      )}

      {job.status === 'error' && job.error && <p className="error-text">{job.error}</p>}
      {job.basalt_status === 'error' && (
        <p className="warn-text">
          BasaltNotes: {job.basalt_error} – {t('wird automatisch erneut versucht.')}{' '}
          <button className="link-button" disabled={busy} onClick={() => act(() => api.sendToBasalt(job.id))}>
            {t('Jetzt senden')}
          </button>
        </p>
      )}
      {job.warning && <p className="warn-text">{job.warning}</p>}
      {actionError && <p className="error-text">{actionError}</p>}

      {showSpeakers && (
        <SpeakerPanel
          job={job}
          onSave={async (names, summarize) => {
            await api.assignSpeakers(job.id, names, summarize)
            setShowSpeakers(false)
          }}
          onSkip={
            awaiting
              ? async () => {
                  await api.restartSummary(job.id)
                  setShowSpeakers(false)
                }
              : undefined
          }
          onClose={() => setShowSpeakers(false)}
        />
      )}

      {!running && !showSpeakers && (
        <div className="actions">
          <div className="downloads">
            {job.has_summary && (
              <button className="btn primary" onClick={() => setViewing('summary')}>
                {isDnd ? t('Recap ansehen') : t('Zusammenfassung ansehen')}
              </button>
            )}
            {job.has_transcript && (
              <button className="btn" onClick={() => setViewing('transcript')}>
                {t('Transkript ansehen')}
              </button>
            )}
            {(job.has_summary || job.has_transcript) && (
              <span className="download-links">
                {job.has_summary && (
                  <a href={downloadUrl.summary(job.id)} download title={t('Zusammenfassung herunterladen')}>
                    {isDnd ? t('Recap') : t('Zusammenfassung')} .md
                  </a>
                )}
                {job.basalt_status === 'done' && job.basalt_note_url && (
                  <a href={job.basalt_note_url} target="_blank" rel="noreferrer" title={t('Notiz in BasaltNotes öffnen')}>
                    BasaltNotes ↗
                  </a>
                )}
                {(job.extra_docs ?? []).map((doc) => (
                  <a key={doc} href={downloadUrl.document(job.id, doc)} download>
                    {extraDocLabel(doc)} .md
                  </a>
                ))}
                {job.has_transcript && (
                  <>
                    <a href={downloadUrl.transcript(job.id, 'md')} download title={t('Transkript herunterladen')}>
                      {t('Transkript')} .md
                    </a>
                    <a href={downloadUrl.transcript(job.id, 'txt')} download title={t('Transkript als Text herunterladen')}>
                      .txt
                    </a>
                  </>
                )}
              </span>
            )}
          </div>
          <div className="secondary-actions">
            {job.has_speakers && !awaiting && (
              <button className="btn ghost small" disabled={busy} onClick={() => setShowSpeakers(true)}>
                {t('Sprecher benennen')}
              </button>
            )}
            {job.has_transcript && !awaiting && (
              <button className="btn ghost small" disabled={busy} onClick={() => act(() => api.restartSummary(job.id))}>
                {job.has_summary ? t('Neu zusammenfassen') : t('Zusammenfassung starten')}
              </button>
            )}
            {!job.audio_deleted && (
              <button
                className="btn ghost small"
                disabled={busy}
                title={t('Aufnahme komplett neu verarbeiten – Transkript und Zusammenfassung werden ersetzt')}
                onClick={() =>
                  confirm(
                    t('„{title}“ neu transkribieren', { title: heading }) +
                      (chooseModel ? ` (Whisper ${whisper.labelOf(whisper.selected || null)})` : '') +
                      t('? Transkript und Zusammenfassung werden ersetzt') +
                      (job.has_speakers && !job.multitrack ? t(', die Sprecher müssen neu zugeordnet werden.') : '.'),
                  ) && act(() => api.restartTranscription(job.id, chooseModel ? whisper.selected : undefined))
                }
              >
                {t('Neu transkribieren')}
              </button>
            )}
            <button
              className="btn ghost small danger"
              disabled={busy}
              onClick={() => confirm(t('„{title}“ endgültig löschen?', { title: heading })) && act(() => api.remove(job.id))}
            >
              {t('Löschen')}
            </button>
          </div>
        </div>
      )}
      {viewing && <MarkdownViewer job={job} initial={viewing} onClose={() => setViewing(null)} />}
    </article>
  )
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString(locale(), { dateStyle: 'medium', timeStyle: 'short' })
}

export function formatDuration(seconds: number) {
  const s = Math.round(seconds)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const rest = String(s % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${rest} h` : `${m}:${rest} min`
}
