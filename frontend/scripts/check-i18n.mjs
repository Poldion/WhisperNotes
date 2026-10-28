// Findet Texte in t('…'), die in src/i18n.en.ts fehlen, und Übersetzungen, die niemand mehr nutzt.
//   node scripts/check-i18n.mjs          → Exit 1 bei fehlenden Übersetzungen
//   node scripts/check-i18n.mjs --list   → fehlende Texte als JSON (Vorlage zum Ergänzen)
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const SRC = new URL('../src/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')

function files(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? files(join(dir, e.name)) : /\.tsx?$/.test(e.name) ? [join(dir, e.name)] : [])
}

const used = new Set()
// t('…') bzw. tr('…') mit einfachem Anführungszeichen; \' ist im Text nicht vorgesehen
const call = /\bt(?:r)?\(\s*'((?:[^'\\]|\\.)*)'/g
for (const file of files(SRC)) {
  if (file.endsWith('i18n.en.ts')) continue
  for (const m of readFileSync(file, 'utf8').matchAll(call)) used.add(m[1])
}

const dict = readFileSync(join(SRC, 'i18n.en.ts'), 'utf8')
const keys = new Set([...dict.matchAll(/^\s*'((?:[^'\\]|\\.)*)':/gm)].map((m) => m[1]))

const missing = [...used].filter((k) => !keys.has(k)).sort()
const unused = [...keys].filter((k) => !used.has(k)).sort()

if (process.argv.includes('--list')) {
  console.log(JSON.stringify(missing, null, 2))
} else {
  if (unused.length) console.warn(`Nicht mehr genutzt (${unused.length}):\n  ${unused.join('\n  ')}`)
  if (missing.length) {
    console.error(`Ohne Übersetzung (${missing.length}):\n  ${missing.join('\n  ')}`)
    process.exit(1)
  }
  console.log(`i18n: ${used.size} Texte, alle übersetzt`)
}
