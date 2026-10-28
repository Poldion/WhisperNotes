import { useState } from 'react'
import { t } from '../i18n'
import type { JobsApi } from '../useJobs'
import { useWhisperModels, WhisperModelSelect } from '../whisperModels'
import JobCard from './JobCard'
import UploadDropzone from './UploadDropzone'
import UploadList from './UploadList'

export default function RecordingsView({ api }: { api: JobsApi }) {
  const [diarize, setDiarize] = useState(false)
  const [numSpeakers, setNumSpeakers] = useState('')
  const [glossary, setGlossary] = useState('')
  const { selected: whisperModel } = useWhisperModels()

  const jobs = api.jobs.filter((j) => j.kind !== 'dnd')
  const uploads = api.uploads.filter((u) => u.scope === 'standard')

  return (
    <>
      <UploadDropzone
        onFiles={(files) =>
          api.upload(files, { diarize, numSpeakers: diarize ? Number(numSpeakers) || null : null, glossary, whisperModel })
        }
      />
      <div className="options">
        <label className="check">
          <input type="checkbox" checked={diarize} onChange={(e) => setDiarize(e.target.checked)} />
          {t('Sprecher erkennen')}
        </label>
        {diarize && (
          <label className="inline-field">
            {t('Anzahl')}
            <input type="number" min={1} max={20} placeholder={t('auto')} value={numSpeakers}
              onChange={(e) => setNumSpeakers(e.target.value)} />
          </label>
        )}
        <label className="inline-field grow">
          {t('Begriffe')}
          <input type="text" placeholder={t('Namen, Fachbegriffe … (verbessert die Schreibweise)')} value={glossary}
            onChange={(e) => setGlossary(e.target.value)} />
        </label>
        <WhisperModelSelect />
      </div>
      {diarize && !numSpeakers && (
        <p className="hint">{t('Tipp: Mit bekannter Sprecheranzahl ist die Erkennung deutlich zuverlässiger.')}</p>
      )}

      <UploadList uploads={uploads} onDismiss={api.dismissUpload} />

      <section>
        <h2 className="section-title">{t('Aufnahmen')}</h2>
        {api.loadError && <p className="error-text">{t('Verlauf konnte nicht geladen werden: {error}', { error: api.loadError })}</p>}
        {jobs.length === 0 && !api.loadError ? (
          <p className="empty">{t('Noch keine Aufnahmen. Lade oben eine Datei hoch.')}</p>
        ) : (
          <div className="job-list">
            {jobs.map((job) => (
              <JobCard key={job.id} job={job} api={api} />
            ))}
          </div>
        )}
      </section>
    </>
  )
}
