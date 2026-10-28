import { t } from './i18n'

export type JobStatus =
  | 'queued'
  | 'slicing'
  | 'transcribing'
  | 'awaiting_speakers'
  | 'summarizing'
  | 'done'
  | 'error'
  | 'cancelled'

export interface Job {
  id: string
  filename: string
  created_at: string
  status: JobStatus
  progress: number
  message: string
  duration_seconds: number | null
  chunks_total: number
  chunks_done: number
  has_transcript: boolean
  has_summary: boolean
  ollama_model: string | null
  error: string | null
  warning: string | null
  finished_at: string | null
  audio_bytes: number
  audio_deleted: boolean
  recorded_at: string | null
  kind: 'standard' | 'dnd'
  campaign_id: string | null
  title: string | null
  session_title: string | null
  glossary: string
  diarize: boolean
  num_speakers: number | null
  diarization_progress: number | null
  diarization_phase: 'decode' | 'segment' | 'embed' | null
  has_speakers: boolean
  speaker_count: number
  speakers: Record<string, string>
  source: string
  source_label: string | null
  multitrack: boolean
  whisper_model: string | null
  /** Zusatzdokumente einer DnD-Session: Recaps je Spieler, Weltwissen für den DM */
  extra_docs: ExtraDoc[]
  /** Sprecher über die Stimmprofile der Kampagne erkannt */
  speakers_auto: boolean
  /** Export nach BasaltNotes: null = aus */
  basalt_status: 'pending' | 'done' | 'error' | null
  basalt_note_url: string | null
  basalt_error: string | null
  discord_channel_id: string | null
  discord_posted_at: string | null
}

export interface DiscordChannel {
  id: string
  name: string
  guild: string
}

export interface Health {
  wrapper: string
  whisper: 'active' | 'starting' | 'inactive'
  seconds_since_last_request: number | null
  active_requests: number
  queue_depth: number
  idle_timeout_seconds: number
  ollama: {
    reachable: boolean
    active_model: string | null
    configured_model?: string | null
    loaded_models: string[]
    fallback_model: string | null
  }
  storage: {
    audio_bytes: number
    limit_bytes: number | null
  }
}

export interface Player {
  name: string
  character: string
  role: 'dm' | 'player'
}

export interface CampaignInput {
  name: string
  players: Player[]
  glossary: string
  discord_channel_id: string | null
  /** BasaltNotes-Vault (leer = Standard aus den Einstellungen) */
  basalt_vault?: string | null
}

export interface Campaign extends CampaignInput {
  id: string
  created_at: string
  /** Namen der Personen, deren Stimme die Kampagne schon kennt */
  voice_profiles?: string[]
}

export interface SpeakerSample {
  start: number
  end: number
  text: string
}

export interface SpeakerInfo {
  speakers: {
    id: string
    name: string
    seconds: number
    utterances: number
    samples: SpeakerSample[]
    /** Vorschlag aus den Stimmprofilen der Kampagne */
    suggested?: string
    similarity?: number
  }[]
  players: (Player & { display: string })[]
  purity: number | null
  audio_available: boolean
}

export interface UploadOptions {
  kind?: 'standard' | 'dnd'
  campaignId?: string
  sessionTitle?: string
  diarize?: boolean
  numSpeakers?: number | null
  glossary?: string
  whisperModel?: string
}

export type ExtraDoc = 'players' | 'lore'

export const extraDocLabel = (doc: ExtraDoc) => (doc === 'players' ? t('Spieler-Recaps') : t('Welt & Lore (DM)'))

export interface WhisperModel {
  id: string
  label: string
  hint: string
  default: boolean
  size_mb: number | null
  loaded: boolean
}

/** Jobs, an denen gerade nichts verarbeitet wird (Fortschritts-Abo kann enden). */
export const isTerminal = (job: Job) =>
  job.status === 'done' || job.status === 'error' || job.status === 'awaiting_speakers' ||
  job.status === 'cancelled'

export const playerDisplay = (p: Player) =>
  p.role === 'dm' ? `${p.name} (DM)` : p.character ? `${p.name} (${p.character})` : p.name

async function errorMessage(resp: Response): Promise<string> {
  try {
    const body = await resp.json()
    const detail = body?.error?.message ?? body?.detail
    if (Array.isArray(detail)) return detail.map((d) => d.msg ?? String(d)).join('; ')
    return detail ?? resp.statusText
  } catch {
    return resp.statusText
  }
}

// Abgelaufene Anmeldung o. Ä.: App zeigt wieder die Anmeldeseite
const unauthorized = new Set<() => void>()
export function onUnauthorized(listener: () => void) {
  unauthorized.add(listener)
  return () => {
    unauthorized.delete(listener)
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init)
  if (resp.status === 401 && !url.startsWith('/api/auth/')) unauthorized.forEach((listener) => listener())
  if (!resp.ok) throw new Error(await errorMessage(resp))
  return resp.status === 204 ? (undefined as T) : resp.json()
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const fetchHealth = () => request<Health>('/health')
export const login = (password: string) => request<void>('/api/auth/login', json('POST', { password }))
export const logout = () => request<void>('/api/auth/logout', { method: 'POST' })
export const fetchJobs = () => request<Job[]>('/api/jobs')
export const deleteJob = (id: string) => request<void>(`/api/jobs/${id}`, { method: 'DELETE' })
export const resummarize = (id: string) => request<Job>(`/api/jobs/${id}/summarize`, { method: 'POST' })
export const cancelJob = (id: string) => request<Job>(`/api/jobs/${id}/cancel`, { method: 'POST' })
/** `whisperModel`: Dateiname, '' = Standardmodell, undefined = bisheriges Modell des Jobs */
export const retranscribe = (id: string, whisperModel?: string) =>
  request<Job>(`/api/jobs/${id}/retranscribe`, json('POST', whisperModel === undefined ? {} : { whisper_model: whisperModel }))

export const exportBasalt = (id: string) => request<Job>(`/api/jobs/${id}/basalt`, { method: 'POST' })

export const fetchWhisperModels = () =>
  request<{ models: WhisperModel[] }>('/api/whisper/models').then((r) => r.models)

export const fetchSpeakers = (id: string) => request<SpeakerInfo>(`/api/jobs/${id}/speakers`)
export const saveSpeakers = (id: string, names: Record<string, string>, summarize: boolean) =>
  request<Job>(`/api/jobs/${id}/speakers`, json('PUT', { names, summarize }))
export const audioUrl = (id: string) => `/api/jobs/${id}/audio`
export const clipUrl = (id: string, start: number, end: number) =>
  `/api/jobs/${id}/clip?start=${start.toFixed(2)}&end=${end.toFixed(2)}`

export const fetchCampaigns = () => request<Campaign[]>('/api/campaigns')
export const createCampaign = (data: CampaignInput) => request<Campaign>('/api/campaigns', json('POST', data))
export const updateCampaign = (id: string, data: CampaignInput) =>
  request<Campaign>(`/api/campaigns/${id}`, json('PUT', data))
export const deleteCampaign = (id: string) => request<void>(`/api/campaigns/${id}`, { method: 'DELETE' })
export const resetVoices = (id: string) => request<void>(`/api/campaigns/${id}/voices`, { method: 'DELETE' })

/** Text-Channels, die der Discord-Bot zuletzt gemeldet hat (leer, solange der Bot nie lief). */
export const fetchDiscordChannels = () =>
  request<{ updated_at: string | null; channels: DiscordChannel[] }>('/api/discord/channels')

export const downloadUrl = {
  transcript: (id: string, format: 'md' | 'txt') => `/api/jobs/${id}/transcript?format=${format}`,
  summary: (id: string) => `/api/jobs/${id}/summary`,
  document: (id: string, name: ExtraDoc) => `/api/jobs/${id}/documents/${name}`,
}

/** Upload per XHR, weil fetch keinen Upload-Fortschritt liefert. */
export function uploadFile(file: File, onProgress: (fraction: number) => void, options: UploadOptions = {}): Promise<Job> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/jobs')
    xhr.responseType = 'json'
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as Job)
      else {
        if (xhr.status === 401) unauthorized.forEach((listener) => listener())
        reject(new Error(xhr.response?.error?.message ?? t('Upload fehlgeschlagen ({status})', { status: xhr.status })))
      }
    }
    xhr.onerror = () => reject(new Error(t('Netzwerkfehler beim Upload')))
    const form = new FormData()
    form.append('file', file)
    // Änderungsdatum der Datei als Näherung für das Aufnahmedatum (Metadaten der Datei haben Vorrang)
    if (file.lastModified) form.append('recorded_at', new Date(file.lastModified).toISOString())
    form.append('kind', options.kind ?? 'standard')
    if (options.campaignId) form.append('campaign_id', options.campaignId)
    if (options.sessionTitle) form.append('session_title', options.sessionTitle)
    if (options.diarize) form.append('diarize', 'true')
    if (options.numSpeakers) form.append('num_speakers', String(options.numSpeakers))
    if (options.glossary) form.append('glossary', options.glossary)
    if (options.whisperModel) form.append('whisper_model', options.whisperModel)
    xhr.send(form)
  })
}

/** Abonniert den Fortschritt eines Jobs per Server-Sent Events. */
export function subscribeJob(id: string, onUpdate: (job: Job) => void): () => void {
  const source = new EventSource(`/api/jobs/${id}/events`)
  source.onmessage = (e) => {
    const job = JSON.parse(e.data) as Job
    onUpdate(job)
    if (isTerminal(job)) source.close()
  }
  return () => source.close()
}

export interface SettingField {
  key: string
  label: string
  help: string
  kind: 'text' | 'number' | 'bool' | 'select' | 'secret' | 'url' | 'textarea'
  options: { value: string; label: string }[]
  min: number | null
  max: number | null
  step: number | null
  unit: string
  applies: string
  nullable: boolean
  overridden: boolean
  value: string | number | boolean | null
  base?: string | number | boolean | null
  is_set?: boolean
  base_is_set?: boolean
  /** textarea (Vorlagen): eingebaute Vorlage der eingestellten Sprache */
  placeholder?: string
}

export interface SettingGroup {
  id: string
  label: string
  description: string
  fields: SettingField[]
}

export interface BasaltVaults {
  enabled: boolean
  default_dnd: string | null
  vaults: { id: string; name: string }[]
  error: string | null
}
export const fetchBasaltVaults = () => request<BasaltVaults>('/api/settings/basalt/vaults')

export const fetchSettings = () => request<{ groups: SettingGroup[] }>('/api/settings')
/** `null` = auf .env/Standard zurücksetzen */
export const saveSettings = (values: Record<string, unknown>) =>
  request<{ groups: SettingGroup[]; changed: string[] }>('/api/settings', json('PUT', { values }))
export const testConnection = (target: 'basalt' | 'ollama') =>
  request<{ ok: boolean; message: string }>(`/api/settings/test/${target}`, { method: 'POST' })
