import { type ReactElement, useCallback, useEffect, useRef, useState } from 'react'
import { audioUrl, clipUrl, type Job } from '../api'
import { t as tr } from '../i18n'

/** Mehrspur-Aufnahmen haben keine Gesamtdatei: Der Server mischt die Spuren in Stücken dieser Länge. */
const PIECE_SECONDS = 60
/** Etwas vor dem Zeitstempel starten – Wortzeiten sind an Übergängen leicht ungenau. */
const LEAD_IN = 0.5

export const formatTime = (t: number) => {
  const s = Math.max(0, Math.floor(t))
  return [Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60].map((n) => String(n).padStart(2, '0')).join(':')
}

export interface TranscriptAudio {
  /** Abspielen ab Sekunde `t` der Aufnahme. */
  playFrom: (t: number) => void
  /** Aktuelle Position in der Aufnahme (s) oder null, solange nichts geladen ist. */
  position: number | null
  playing: boolean
  error: string | null
  element: ReactElement
}

/** Audio zum Transkript: Einzelaufnahmen als Originaldatei (Springen per Range-Request), Mehrspur-Aufnahmen
 *  als nacheinander geladene, serverseitig gemischte Stücke. */
export function useTranscriptAudio(job: Job): TranscriptAudio {
  const audio = useRef<HTMLAudioElement>(null)
  const offset = useRef(0) // Mehrspur: Beginn des geladenen Stücks in der Aufnahme
  const [position, setPosition] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadPiece = useCallback(
    (start: number) => {
      const a = audio.current
      if (!a) return
      offset.current = start
      a.src = clipUrl(job.id, start, start + PIECE_SECONDS)
      a.play().catch(() => setPlaying(false))
    },
    [job.id],
  )

  const playFrom = useCallback(
    (t: number) => {
      const a = audio.current
      if (!a) return
      setError(null)
      const start = Math.max(0, t - LEAD_IN)
      if (job.multitrack) {
        loadPiece(start)
        return
      }
      a.currentTime = start
      a.play().catch(() => setPlaying(false))
    },
    [job.id, job.multitrack, loadPiece],
  )

  useEffect(() => {
    const a = audio.current
    if (!a) return
    const update = () => setPosition(offset.current + a.currentTime)
    const onPlay = () => setPlaying(true)
    const onPause = () => setPlaying(false)
    const onEnded = () => {
      const next = offset.current + PIECE_SECONDS
      if (job.multitrack && next < (job.duration_seconds ?? 0)) loadPiece(next)
      else setPlaying(false)
    }
    const onError = () => {
      setPlaying(false)
      if (a.getAttribute('src')) setError(tr('Audio konnte nicht abgespielt werden – Format vom Browser nicht unterstützt?'))
    }
    a.addEventListener('timeupdate', update)
    a.addEventListener('seeked', update)
    a.addEventListener('play', onPlay)
    a.addEventListener('pause', onPause)
    a.addEventListener('ended', onEnded)
    a.addEventListener('error', onError)
    return () => {
      a.removeEventListener('timeupdate', update)
      a.removeEventListener('seeked', update)
      a.removeEventListener('play', onPlay)
      a.removeEventListener('pause', onPause)
      a.removeEventListener('ended', onEnded)
      a.removeEventListener('error', onError)
      a.pause()
    }
  }, [job.multitrack, job.duration_seconds, loadPiece])

  // Einzelaufnahmen: Datei gleich verknüpfen, damit die Steuerleiste Länge und Suchleiste zeigt.
  // Mehrspur: erstes Stück verknüpfen (geladen wird erst beim Abspielen).
  const element = job.multitrack ? (
    <audio ref={audio} controls preload="none" src={clipUrl(job.id, 0, PIECE_SECONDS)} />
  ) : (
    <audio ref={audio} controls preload="metadata" src={audioUrl(job.id)} />
  )
  return { playFrom, position, playing, error, element }
}
