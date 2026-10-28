import { useCallback, useEffect, useRef, useState } from 'react'
import {
  deleteJob,
  fetchJobs,
  isTerminal,
  resummarize,
  retranscribe,
  exportBasalt,
  cancelJob,
  saveSpeakers,
  subscribeJob,
  uploadFile,
  type Job,
  type UploadOptions,
} from './api'

export interface PendingUpload {
  key: string
  name: string
  fraction: number
  scope: string // "standard" oder die Kampagnen-ID, damit jeder Tab nur seine Uploads zeigt
  error?: string
}

/** Gemeinsamer Zustand aller Jobs inkl. Live-Fortschritt per SSE. */
export function useJobs() {
  const [jobs, setJobs] = useState<Record<string, Job>>({})
  const [uploads, setUploads] = useState<PendingUpload[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const subscriptions = useRef(new Map<string, () => void>())
  const uploadCounter = useRef(0)

  const upsert = useCallback((job: Job) => setJobs((prev) => ({ ...prev, [job.id]: job })), [])

  const watch = useCallback(
    (job: Job) => {
      if (isTerminal(job) || subscriptions.current.has(job.id)) return
      const close = subscribeJob(job.id, (update) => {
        upsert(update)
        if (isTerminal(update)) {
          subscriptions.current.get(job.id)?.()
          subscriptions.current.delete(job.id)
        }
      })
      subscriptions.current.set(job.id, close)
    },
    [upsert],
  )

  const reload = useCallback(
    () =>
      fetchJobs()
        .then((list) => {
          setJobs(Object.fromEntries(list.map((j) => [j.id, j])))
          list.forEach(watch)
          setLoadError(null)
        })
        .catch((e: Error) => setLoadError(e.message)),
    [watch],
  )

  useEffect(() => {
    reload()
    const subs = subscriptions.current
    return () => {
      subs.forEach((close) => close())
      subs.clear()
    }
  }, [reload])

  const upload = (files: File[], options: UploadOptions = {}) => {
    const scope = options.kind === 'dnd' ? (options.campaignId ?? 'dnd') : 'standard'
    files.forEach((file) => {
      // Kein crypto.randomUUID: das gibt es nur in sicheren Kontexten (HTTPS/localhost), nicht unter http://<LAN-IP>.
      const key = `${file.name}-${++uploadCounter.current}`
      setUploads((u) => [...u, { key, name: file.name, fraction: 0, scope }])
      const update = (patch: Partial<PendingUpload>) =>
        setUploads((u) => u.map((p) => (p.key === key ? { ...p, ...patch } : p)))
      uploadFile(file, (fraction) => update({ fraction }), options)
        .then((job) => {
          setUploads((u) => u.filter((p) => p.key !== key))
          upsert(job)
          watch(job)
        })
        .catch((e: Error) => update({ error: e.message }))
    })
  }

  const dismissUpload = (key: string) => setUploads((u) => u.filter((p) => p.key !== key))

  const cancel = async (id: string) => {
    const job = await cancelJob(id)
    // Laufende Jobs: Die Antwort zeigt noch den Stand *vor* dem Abbruch ("Wird abgebrochen …"); der
    // endgültige Status kommt per Live-Update – oft schon vor dieser Antwort. Nicht überschreiben!
    // Wartende Jobs sind sofort abgebrochen und kommen direkt mit ihrem Endstatus zurück.
    if (isTerminal(job)) upsert(job)
  }

  const restartTranscription = async (id: string, whisperModel?: string) => {
    const job = await retranscribe(id, whisperModel)
    upsert(job)
    watch(job)
  }

  const sendToBasalt = async (id: string) => {
    upsert(await exportBasalt(id))
  }

  const restartSummary = async (id: string) => {
    const job = await resummarize(id)
    upsert(job)
    watch(job)
  }

  const assignSpeakers = async (id: string, names: Record<string, string>, summarize: boolean) => {
    const job = await saveSpeakers(id, names, summarize)
    upsert(job)
    watch(job)
  }

  const remove = async (id: string) => {
    await deleteJob(id)
    setJobs(({ [id]: _removed, ...rest }) => rest)
  }

  const sorted = Object.values(jobs).sort((a, b) => b.created_at.localeCompare(a.created_at))

  return {
    jobs: sorted, uploads, loadError, upload, dismissUpload, restartSummary, restartTranscription, sendToBasalt, cancel,
    assignSpeakers, remove, reload,
  }
}

export type JobsApi = ReturnType<typeof useJobs>
