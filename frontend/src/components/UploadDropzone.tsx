import { useRef, useState, type DragEvent } from 'react'
import { t } from '../i18n'

const ACCEPT = '.mp3,.m4a,.wav,.ogg,.opus,.flac,.webm,.mp4,.aac,.m4b,audio/*'

interface Props {
  onFiles: (files: File[]) => void
  title?: string
  hint?: string
}

export default function UploadDropzone({ onFiles, title, hint }: Props) {
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLInputElement>(null)

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length) onFiles(files)
  }

  return (
    <div
      className={`dropzone${dragging ? ' dragging' : ''}`}
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      onClick={() => input.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && input.current?.click()}
    >
      <svg className="drop-icon" viewBox="0 0 24 24" aria-hidden>
        <path d="M12 16V4m0 0-4 4m4-4 4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
      </svg>
      <p className="drop-title">{title ?? t('Audiodatei hierher ziehen oder klicken')}</p>
      <p className="drop-hint">{hint ?? t('MP3, M4A, WAV, OGG, FLAC … Lange Aufnahmen werden automatisch in Abschnitte geteilt.')}</p>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          if (files.length) onFiles(files)
          e.target.value = ''
        }}
      />
    </div>
  )
}
