import { createContext, type ReactNode, useContext, useEffect, useState } from 'react'
import { fetchWhisperModels, type WhisperModel } from './api'
import { t } from './i18n'

const STORAGE_KEY = 'whispernotes.whisperModel'

interface WhisperModels {
  models: WhisperModel[]
  /** Gewähltes Modell (Dateiname); '' = Standardmodell */
  selected: string
  select: (id: string) => void
  /** Anzeigename eines Modells (Dateiname; null = Standardmodell) */
  labelOf: (id: string | null) => string
}

const Context = createContext<WhisperModels>({ models: [], selected: '', select: () => {}, labelOf: () => '' })

const shortLabel = (label: string) => label.replace(/-q\d_\d$/, '')

function remembered(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) ?? ''
  } catch {
    return ''
  }
}

/** Liste der Whisper-Modelle und die (im Browser gemerkte) Auswahl für Upload und Neu-Transkribieren. */
export function WhisperModelProvider({ children }: { children: ReactNode }) {
  const [models, setModels] = useState<WhisperModel[]>([])
  const [selected, setSelected] = useState(remembered)

  useEffect(() => {
    fetchWhisperModels()
      .then(setModels)
      .catch(() => setModels([]))
  }, [])

  const select = (id: string) => {
    setSelected(id)
    try {
      localStorage.setItem(STORAGE_KEY, id)
    } catch {
      /* privater Modus o. Ä. */
    }
  }

  // Gemerktes Modell gibt es nicht mehr → Standard
  const valid = models.some((m) => m.id === selected && !m.default) ? selected : ''
  const labelOf = (id: string | null) =>
    shortLabel(models.find((m) => (id ? m.id === id : m.default))?.label ?? id ?? '')

  return <Context.Provider value={{ models, selected: valid, select, labelOf }}>{children}</Context.Provider>
}

export const useWhisperModels = () => useContext(Context)

/** Auswahlfeld – nur sichtbar, wenn mehr als ein Modell installiert ist. */
export function WhisperModelSelect() {
  const { models, selected, select } = useWhisperModels()
  if (models.length < 2) return null
  return (
    <label className="inline-field" title={t('Gilt für neue Uploads und „Neu transkribieren“')}>
      Whisper
      <select value={selected} onChange={(e) => select(e.target.value)}>
        {models.map((m) => (
          <option key={m.id} value={m.default ? '' : m.id}>
            {shortLabel(m.label)}
            {m.hint ? ` – ${m.hint}` : ''}
          </option>
        ))}
      </select>
    </label>
  )
}
