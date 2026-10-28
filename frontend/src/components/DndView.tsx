import { useEffect, useState } from 'react'
import {
  createCampaign,
  deleteCampaign,
  fetchCampaigns,
  playerDisplay,
  resetVoices,
  updateCampaign,
  type Campaign,
} from '../api'
import { t } from '../i18n'
import type { JobsApi } from '../useJobs'
import { useWhisperModels, WhisperModelSelect } from '../whisperModels'
import CampaignEditor from './CampaignEditor'
import JobCard from './JobCard'
import UploadDropzone from './UploadDropzone'
import UploadList from './UploadList'

const STORAGE_KEY = 'whispernotes.campaign'

function rememberedCampaign(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function remember(id: string | null) {
  try {
    if (id) localStorage.setItem(STORAGE_KEY, id)
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* privater Modus o. Ä. */
  }
}

export default function DndView({ api }: { api: JobsApi }) {
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(rememberedCampaign)
  const [editing, setEditing] = useState<'new' | 'edit' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sessionTitle, setSessionTitle] = useState('')
  const [numSpeakers, setNumSpeakers] = useState('')
  const { selected: whisperModel } = useWhisperModels()

  // Neu laden, wenn sich bei Sessions Status oder Sprecher ändern – dann können neue Stimmprofile dazugekommen sein
  const sessionsKey = api.jobs
    .filter((j) => j.kind === 'dnd')
    .map((j) => `${j.id}:${j.status}:${Object.values(j.speakers).join('|')}`)
    .join(',')
  useEffect(() => {
    fetchCampaigns()
      .then(setCampaigns)
      .catch((e: Error) => setError(e.message))
  }, [sessionsKey])

  const selected = campaigns?.find((c) => c.id === selectedId) ?? campaigns?.[0] ?? null

  useEffect(() => {
    setNumSpeakers(selected?.players.length ? String(selected.players.length) : '')
    setSessionTitle('')
  }, [selected?.id, selected?.players.length])

  const choose = (id: string | null) => {
    setSelectedId(id)
    remember(id)
  }

  if (campaigns === null) {
    return error ? <p className="error-text">{error}</p> : <p className="hint">{t('Lade Kampagnen …')}</p>
  }

  if (editing || campaigns.length === 0) {
    const isEdit = editing === 'edit' && selected
    return (
      <>
        {campaigns.length === 0 && !editing && (
          <div className="intro">
            <h2>{t('DnD-Sessions')}</h2>
            <p>
              {t('Lege eine Kampagne mit deiner Runde an. Beim Upload einer Session werden die Stimmen erkannt, du ordnest sie den Spielern zu und bekommst einen Session-Recap mit Handlung, NPCs, Beute und offenen Quests.')}
            </p>
          </div>
        )}
        <CampaignEditor
          initial={isEdit ? selected : undefined}
          onCancel={campaigns.length > 0 ? () => setEditing(null) : undefined}
          onSave={async (data) => {
            const saved = isEdit ? await updateCampaign(selected.id, data) : await createCampaign(data)
            setCampaigns((list) => [...(list ?? []).filter((c) => c.id !== saved.id), saved]
              .sort((a, b) => a.name.localeCompare(b.name)))
            choose(saved.id)
            setEditing(null)
          }}
          onDelete={
            isEdit
              ? async () => {
                  await deleteCampaign(selected.id)
                  setCampaigns((list) => (list ?? []).filter((c) => c.id !== selected.id))
                  choose(null)
                  setEditing(null)
                  await api.reload()
                }
              : undefined
          }
        />
      </>
    )
  }

  if (!selected) return null
  const sessions = api.jobs.filter((j) => j.campaign_id === selected.id)
  const uploads = api.uploads.filter((u) => u.scope === selected.id)
  const nextSession = t('Session {n}', { n: sessions.length + 1 })

  return (
    <>
      <div className="campaign-bar">
        <select value={selected.id} onChange={(e) => choose(e.target.value)} aria-label={t('Kampagne')}>
          {campaigns.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <button className="btn ghost small" onClick={() => setEditing('edit')}>
          {t('Bearbeiten')}
        </button>
        <button className="btn ghost small" onClick={() => setEditing('new')}>
          + {t('Neue Kampagne')}
        </button>
      </div>

      <div className="party">
        {selected.players.length === 0 ? (
          <span className="hint">{t('Noch keine Spieler eingetragen – „Bearbeiten“ ergänzt die Runde.')}</span>
        ) : (
          selected.players.map((p) => {
            const known = selected.voice_profiles?.includes(p.name)
            return (
              <span key={p.name + p.character} className={`chip${p.role === 'dm' ? ' dm' : ''}`}
                title={known ? t('Stimme bekannt – wird automatisch zugeordnet') : t('Stimme noch unbekannt')}>
                {known ? '🎙 ' : ''}
                {playerDisplay(p)}
              </span>
            )
          })
        )}
        {!!selected.voice_profiles?.length && (
          <button className="btn ghost small" onClick={async () => {
            if (!confirm(t('Gespeicherte Stimmen dieser Kampagne vergessen? Die nächste Session fragt wieder nach der Zuordnung.'))) return
            await resetVoices(selected.id)
            setCampaigns((list) => (list ?? []).map((c) => (c.id === selected.id ? { ...c, voice_profiles: [] } : c)))
          }}>
            {t('Stimmen vergessen')}
          </button>
        )}
      </div>
      {selected.players.length > 0 && (
        <p className="hint">
          {selected.voice_profiles?.length === selected.players.length
            ? t('Alle Stimmen sind bekannt – neue Sessions werden ohne Rückfrage zugeordnet.')
            : t('Nach der ersten Zuordnung merkt sich die Kampagne die Stimmen (🎙). Gefragt wird nur noch, wenn jemand neu dazukommt oder eine Stimme nicht eindeutig passt.')}
        </p>
      )}

      <div className="options">
        <label className="inline-field grow">
          {t('Session')}
          <input type="text" placeholder={nextSession} value={sessionTitle}
            onChange={(e) => setSessionTitle(e.target.value)} />
        </label>
        <label className="inline-field">
          {t('Stimmen')}
          <input type="number" min={1} max={20} placeholder={t('auto')} value={numSpeakers}
            onChange={(e) => setNumSpeakers(e.target.value)} />
        </label>
        <WhisperModelSelect />
      </div>
      <UploadDropzone
        title={t('Session-Aufnahme hierher ziehen oder klicken')}
        hint={t('Stimmen werden erkannt und danach den Spielern zugeordnet.')}
        onFiles={(files) => {
          api.upload(files, {
            kind: 'dnd',
            campaignId: selected.id,
            sessionTitle: sessionTitle.trim() || undefined,
            numSpeakers: Number(numSpeakers) || null,
            whisperModel,
          })
          setSessionTitle('')
        }}
      />

      <UploadList uploads={uploads} onDismiss={api.dismissUpload} />

      <section>
        <h2 className="section-title">{t('Sessions')}</h2>
        {sessions.length === 0 ? (
          <p className="empty">{t('Noch keine Sessions in dieser Kampagne.')}</p>
        ) : (
          <div className="job-list">
            {sessions.map((job) => (
              <JobCard key={job.id} job={job} api={api} />
            ))}
          </div>
        )}
      </section>
    </>
  )
}
