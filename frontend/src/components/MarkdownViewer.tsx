import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { type MouseEvent, useEffect, useMemo, useRef, useState } from 'react'
import { downloadUrl, extraDocLabel, type ExtraDoc, type Job } from '../api'
import { t } from '../i18n'
import { formatTime, useTranscriptAudio } from './TranscriptAudio'

export type DocKind = 'summary' | 'transcript' | ExtraDoc

interface Props {
  job: Job
  initial: DocKind
  onClose: () => void
}

const docUrl = (job: Job, kind: DocKind) =>
  kind === 'summary'
    ? downloadUrl.summary(job.id)
    : kind === 'transcript'
      ? downloadUrl.transcript(job.id, 'md')
      : downloadUrl.document(job.id, kind)

/** Zeilen mit Zeitstempel ("**[00:12:34] Name:** …", "## [00:05:00]") anklickbar machen. */
const markTimestamps = (html: string) =>
  html.replace(/<(p|h2)>(<strong>)?\[(\d{2}):(\d{2}):(\d{2})\]/g, (_m, tag: string, strong = '', h, m, sec) =>
    `<${tag} class="tline" data-t="${Number(h) * 3600 + Number(m) * 60 + Number(sec)}" title="${t('Ab hier abspielen')}">` +
    `${strong}[${h}:${m}:${sec}]`)

/** Zeigt Transkript bzw. Zusammenfassung formatiert im Browser an. */
export default function MarkdownViewer({ job, initial, onClose }: Props) {
  const [kind, setKind] = useState<DocKind>(initial)
  const [texts, setTexts] = useState<Partial<Record<DocKind, string>>>({})
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState<'ok' | 'fail' | null>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const body = useRef<HTMLDivElement>(null)
  const [follow, setFollow] = useState(true)
  const canPlay = kind === 'transcript' && !job.audio_deleted
  const player = useTranscriptAudio(job)

  const summaryLabel = job.kind === 'dnd' ? t('Session-Recap') : t('Zusammenfassung')
  const available: DocKind[] = [
    ...(job.has_summary ? ['summary' as const] : []),
    ...(job.extra_docs ?? []),
    ...(job.has_transcript ? ['transcript' as const] : []),
  ]
  const labelOf = (k: DocKind) =>
    k === 'summary' ? summaryLabel : k === 'transcript' ? t('Transkript') : extraDocLabel(k)

  // Laden (einmal pro Dokument, danach aus dem Zwischenspeicher)
  useEffect(() => {
    if (texts[kind] !== undefined) return
    setError(null)
    fetch(docUrl(job, kind))
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(t('Laden fehlgeschlagen ({status})', { status: r.status })))))
      .then((text) => setTexts((prev) => ({ ...prev, [kind]: text })))
      .catch((e: Error) => setError(e.message))
  }, [job, kind, texts])

  // Esc schließt, Hintergrund scrollt nicht mit
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeButton.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
    }
  }, [onClose])

  // Block statt Pfeil-Ausdruck: scrollTo liefert in neueren Browsern ein Promise, das React sonst
  // für eine Aufräumfunktion hält und beim nächsten Wechsel aufruft (→ Absturz).
  useEffect(() => {
    body.current?.scrollTo({ top: 0 })
  }, [kind])

  const html = useMemo(() => {
    const text = texts[kind]
    if (text === undefined) return null
    const html = DOMPurify.sanitize(marked.parse(text, { gfm: true, breaks: false, async: false }))
    return kind === 'transcript' && !job.audio_deleted ? markTimestamps(html) : html
  }, [texts, kind, job.audio_deleted])

  // Aktuell gesprochene Zeile hervorheben und (wenn gewünscht) mitlaufen
  const current = useRef<HTMLElement | null>(null)
  useEffect(() => {
    const lines = body.current?.querySelectorAll<HTMLElement>('.tline')
    let line: HTMLElement | null = null
    if (lines && player.position !== null && canPlay) {
      for (const el of lines) {
        if (Number(el.dataset.t) <= player.position + 0.5) line = el
        else break
      }
    }
    if (line === current.current) return
    current.current?.classList.remove('playing')
    line?.classList.add('playing')
    current.current = line
    if (line && follow && player.playing) line.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [player.position, player.playing, follow, canPlay, html])

  const onArticleClick = (e: MouseEvent<HTMLElement>) => {
    const line = (e.target as HTMLElement).closest<HTMLElement>('.tline')
    if (!line || !canPlay || window.getSelection()?.toString()) return // Text markieren bleibt möglich
    player.playFrom(Number(line.dataset.t))
  }

  const copy = async () => {
    const text = texts[kind]
    if (!text) return
    setCopied((await copyText(text)) ? 'ok' : 'fail')
    setTimeout(() => setCopied(null), 1800)
  }

  return (
    <div className="viewer-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="viewer" role="dialog" aria-modal="true" aria-label={job.title ?? job.filename}>
        <header className="viewer-head">
          <div className="viewer-tabs" role="tablist">
            {available.map((k) => (
              <button key={k} role="tab" aria-selected={kind === k} className={kind === k ? 'active' : ''}
                onClick={() => setKind(k)}>
                {labelOf(k)}
              </button>
            ))}
          </div>
          <div className="viewer-actions">
            <button className="btn ghost small" onClick={copy} disabled={!texts[kind]}>
              {copied === 'ok' ? t('Kopiert ✓') : copied === 'fail' ? t('Nicht möglich') : t('Kopieren')}
            </button>
            <a className="btn ghost small" href={docUrl(job, kind)} download>
              Download .md
            </a>
            <button ref={closeButton} className="btn ghost small" onClick={onClose} aria-label={t('Schließen')}>
              ✕
            </button>
          </div>
        </header>
        {canPlay && (
          <div className="viewer-player">
            {player.element}
            <span className="hint">
              {player.position !== null ? formatTime(player.position) : t('Zeile anklicken = ab dort abspielen')}
            </span>
            <label className="hint follow">
              <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> {t('mitlaufen')}
            </label>
            {player.error && <span className="error-text">{player.error}</span>}
          </div>
        )}
        <div className="viewer-body" ref={body}>
          {error && <p className="error-text">{error}</p>}
          {!error && html === null && <p className="hint">{t('Lade …')}</p>}
          {html !== null && <article className="markdown" onClick={onArticleClick} dangerouslySetInnerHTML={{ __html: html }} />}
        </div>
      </div>
    </div>
  )
}

/** navigator.clipboard gibt es nur über HTTPS/localhost – im LAN (http://<IP>) per Fallback kopieren. */
async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      /* z. B. verweigerte Berechtigung → Fallback */
    }
  }
  const area = document.createElement('textarea')
  area.value = text
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  const ok = document.execCommand('copy')
  area.remove()
  return ok
}
