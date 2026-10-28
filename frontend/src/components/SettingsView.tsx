import { useEffect, useMemo, useState } from 'react'
import {
  fetchSettings,
  saveSettings,
  testConnection,
  type SettingField,
  type SettingGroup,
} from '../api'
import { t } from '../i18n'

type Draft = Record<string, string | boolean>

const TESTS: Record<string, { target: 'basalt' | 'ollama'; label: () => string }> = {
  basalt: { target: 'basalt', label: () => t('Verbindung prüfen') },
  llm: { target: 'ollama', label: () => t('Ollama prüfen') },
}

/** Darstellung eines Werts im Eingabefeld (Zahlen/Text als String, leer = null). */
const asInput = (field: SettingField): string | boolean =>
  field.kind === 'bool' ? Boolean(field.value) : field.value == null ? '' : String(field.value)

const shownBase = (field: SettingField) => {
  if (field.kind === 'secret') return field.base_is_set ? t('gesetzt') : t('nicht gesetzt')
  if (field.kind === 'select') {
    const match = field.options.find((o) => o.value === String(field.base ?? ''))
    if (match) return match.label
  }
  if (field.base === null || field.base === '') return t('leer')
  return field.kind === 'bool' ? (field.base ? t('an') : t('aus')) : String(field.base)
}

/** Einstellungen des Servers: Werte aus .env bilden die Grundlage, Änderungen hier überschreiben sie. */
export default function SettingsView() {
  const [groups, setGroups] = useState<SettingGroup[] | null>(null)
  const [draft, setDraft] = useState<Draft>({})
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [tests, setTests] = useState<Record<string, { ok: boolean; message: string } | 'running'>>({})

  useEffect(() => {
    fetchSettings()
      .then((data) => setGroups(data.groups))
      .catch((e: Error) => setError(e.message))
  }, [])

  const fields = useMemo(() => Object.fromEntries((groups ?? []).flatMap((g) => g.fields.map((f) => [f.key, f]))), [groups])
  const dirty = Object.keys(draft).filter((key) => {
    const field = fields[key]
    return field && (field.kind === 'secret' ? draft[key] !== '' : draft[key] !== asInput(field))
  })

  const set = (key: string, value: string | boolean) => {
    setSaved(null)
    setDraft((d) => ({ ...d, [key]: value }))
  }

  const apply = async (values: Record<string, unknown>, done: string) => {
    setBusy(true)
    setError(null)
    try {
      const data = await saveSettings(values)
      // Neue Sprache: Oberfläche neu laden, damit alle Texte wechseln
      if (data.changed.includes('language')) {
        window.location.reload()
        return
      }
      setGroups(data.groups)
      setDraft({})
      setSaved(done)
      setTests({})
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const save = () =>
    apply(Object.fromEntries(dirty.map((key) => [key, draft[key]])),
      t('{n} Einstellung(en) gespeichert', { n: dirty.length }))

  const runTest = async (group: string) => {
    setTests((prev) => ({ ...prev, [group]: 'running' }))
    try {
      const result = await testConnection(TESTS[group].target)
      setTests((prev) => ({ ...prev, [group]: result }))
      if (group === 'llm' && result.ok) {
        fetchSettings().then((data) => setGroups(data.groups)).catch(() => {})
      }
    } catch (e) {
      setTests((prev) => ({ ...prev, [group]: { ok: false, message: (e as Error).message } }))
    }
  }

  if (!groups) return error ? <p className="error-text">{error}</p> : <p className="hint">{t('Lade Einstellungen …')}</p>

  return (
    <div className="settings">
      <p className="hint settings-intro">
        {t('Grundlage sind die Werte aus der Konfiguration (.env bzw. Umgebung). Was du hier änderst, wird zusätzlich gespeichert und hat Vorrang; „Zurücksetzen“ stellt wieder den Wert aus der Konfiguration her. Änderungen gelten sofort, sofern nicht anders angegeben.')}
      </p>

      {groups.map((group) => {
        const test = tests[group.id]
        const groupDirty = group.fields.some((f) => dirty.includes(f.key))
        return (
          <section key={group.id} className="panel settings-group">
            <header className="settings-head">
              <div>
                <h2>{group.label}</h2>
                <p className="hint">{group.description}</p>
              </div>
              {TESTS[group.id] && (
                <button className="btn ghost small" disabled={busy || test === 'running' || groupDirty}
                  title={groupDirty ? t('Erst speichern') : undefined} onClick={() => runTest(group.id)}>
                  {test === 'running' ? t('Prüfe …') : TESTS[group.id].label()}
                </button>
              )}
            </header>
            {test && test !== 'running' && (
              <p className={test.ok ? 'ok-text' : 'error-text'}>{test.ok ? '✓ ' : ''}{test.message}</p>
            )}

            <div className="settings-fields">
              {group.fields.map((field) => (
                <SettingInput key={field.key} field={field} value={draft[field.key] ?? asInput(field)}
                  changed={dirty.includes(field.key)} busy={busy} onChange={(v) => set(field.key, v)}
                  onReset={() => apply({ [field.key]: null }, t('„{label}“ zurückgesetzt', { label: field.label }))}
                  onClear={() => apply({ [field.key]: '' }, t('„{label}“ entfernt', { label: field.label }))} />
              ))}
            </div>
          </section>
        )
      })}

      <div className="settings-save">
        {error && <span className="error-text">{error}</span>}
        {saved && !dirty.length && <span className="ok-text">✓ {saved}</span>}
        {dirty.length > 0 && (
          <button className="btn ghost" disabled={busy} onClick={() => setDraft({})}>
            {t('Verwerfen')}
          </button>
        )}
        <button className="btn primary" disabled={busy || !dirty.length} onClick={save}>
          {busy ? t('Speichere …') : dirty.length ? t('{n} Änderung(en) speichern', { n: dirty.length }) : t('Gespeichert')}
        </button>
      </div>
    </div>
  )
}

interface InputProps {
  field: SettingField
  value: string | boolean
  changed: boolean
  busy: boolean
  onChange: (value: string | boolean) => void
  onReset: () => void
  onClear: () => void
}

function SettingInput({ field, value, changed, busy, onChange, onReset, onClear }: InputProps) {
  const id = `setting-${field.key}`
  const wide = field.kind === 'textarea'
  let control
  if (field.kind === 'bool') {
    control = (
      <label className="check">
        <input id={id} type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        {value ? t('an') : t('aus')}
      </label>
    )
  } else if (field.kind === 'select') {
    control = (
      <select id={id} value={String(value)} onChange={(e) => onChange(e.target.value)}>
        {field.options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    )
  } else if (field.kind === 'secret') {
    control = (
      <input id={id} type="password" autoComplete="new-password" value={String(value)}
        placeholder={field.is_set ? t('•••••••• (gesetzt – neu eingeben zum Ändern)') : t('nicht gesetzt')}
        onChange={(e) => onChange(e.target.value)} />
    )
  } else if (field.kind === 'textarea') {
    control = (
      <>
        <textarea id={id} rows={value ? 12 : 4} value={String(value)} spellCheck={false}
          placeholder={field.placeholder ? `${t('Eingebaute Vorlage:')}\n\n${field.placeholder}` : undefined}
          onChange={(e) => onChange(e.target.value)} />
        {!value && field.placeholder && (
          <button className="link-button" disabled={busy} onClick={() => onChange(field.placeholder ?? '')}>
            {t('Eingebaute Vorlage zum Bearbeiten übernehmen')}
          </button>
        )}
      </>
    )
  } else {
    control = (
      <span className="settings-number">
        <input id={id} type={field.kind === 'number' ? 'number' : field.kind === 'url' ? 'url' : 'text'}
          value={String(value)} min={field.min ?? undefined} max={field.max ?? undefined}
          step={field.step ?? undefined} placeholder={field.nullable ? t('automatisch') : undefined}
          onChange={(e) => onChange(e.target.value)} />
        {field.unit && <span className="hint">{field.unit}</span>}
      </span>
    )
  }

  return (
    <div className={`setting${changed ? ' changed' : ''}${wide ? ' wide' : ''}`}>
      <label className="setting-label" htmlFor={id}>
        {field.label}
        {field.overridden && <span className="setting-badge" title={t('Im Dashboard geändert')}>{t('geändert')}</span>}
      </label>
      <div className="setting-control">
        {control}
        {field.overridden && (
          <button className="link-button" disabled={busy} onClick={onReset}
            title={wide ? undefined : t('Wert aus der Konfiguration: {value}', { value: shownBase(field) })}>
            {wide ? t('Eingebaute Vorlage verwenden') : t('Zurücksetzen')}
          </button>
        )}
        {field.kind === 'secret' && field.is_set && (
          <button className="link-button" disabled={busy} onClick={onClear}>
            {t('Entfernen')}
          </button>
        )}
      </div>
      {(field.help || field.applies) && (
        <span className="hint">
          {field.help}
          {field.help && field.applies ? ' · ' : ''}
          {field.applies && t('gilt {when}', { when: field.applies })}
        </span>
      )}
    </div>
  )
}
