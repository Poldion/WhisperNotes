import { t } from '../i18n'
import type { PendingUpload } from '../useJobs'

interface Props {
  uploads: PendingUpload[]
  onDismiss: (key: string) => void
}

export default function UploadList({ uploads, onDismiss }: Props) {
  if (uploads.length === 0) return null
  return (
    <section className="uploads">
      {uploads.map((u) => (
        <div key={u.key} className={`upload-row${u.error ? ' failed' : ''}`}>
          <span className="upload-name">{u.name}</span>
          {u.error ? (
            <>
              <span className="error-text">{u.error}</span>
              <button className="btn ghost small" onClick={() => onDismiss(u.key)}>
                {t('Schließen')}
              </button>
            </>
          ) : (
            <>
              <div className="bar upload">
                <div style={{ width: `${u.fraction * 100}%` }} />
              </div>
              <span className="pct">{Math.round(u.fraction * 100)} %</span>
            </>
          )}
        </div>
      ))}
    </section>
  )
}
