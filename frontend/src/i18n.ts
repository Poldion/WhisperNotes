/** Übersetzung der Oberfläche – wie gettext: Der deutsche Text ist der Schlüssel, `EN` enthält die
 *  Übersetzungen. Die Sprache kommt vom Server (Einstellungen → Allgemein) und gilt nach dem Neuladen.
 *  `npm run check-i18n` meldet Texte ohne Übersetzung. */
import { EN } from './i18n.en'

export type Language = 'de' | 'en'

let current: Language = 'de'

export function setLanguage(language: string | undefined) {
  current = language === 'en' ? 'en' : 'de'
  document.documentElement.lang = current
}

export const language = () => current

/** Gebietsschema für Datums- und Zahlenformate */
export const locale = () => (current === 'en' ? 'en-GB' : 'de-DE')

export function t(text: string, values?: Record<string, string | number>): string {
  let out = current === 'en' ? (EN[text] ?? text) : text
  if (values) for (const [key, value] of Object.entries(values)) out = out.split(`{${key}}`).join(String(value))
  return out
}
