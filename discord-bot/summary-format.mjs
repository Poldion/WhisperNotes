// Zusammenfassung (Markdown aus dem Wrapper) für einen Discord-Post aufbereiten.

const EMBED_LIMIT = 4096;

/**
 * Entfernt Titel und Metazeile (stehen schon im Embed), macht aus "## Abschnitt" fette Zwischenzeilen
 * und kürzt auf das Discord-Limit – an einer Zeilengrenze, mit Hinweis auf die angehängte Datei.
 */
export function summaryToEmbedText(markdown, limit = EMBED_LIMIT - 96) {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n');
  const body = [];
  let skippingHeader = true;
  for (const line of lines) {
    if (skippingHeader && (line.startsWith('# ') || line.startsWith('> ') || !line.trim())) continue;
    skippingHeader = false;
    const heading = line.match(/^#{2,6}\s+(.*)$/);
    body.push(heading ? `**${heading[1].trim()}**` : line);
  }
  let text = body.join('\n').replace(/\n{3,}/g, '\n\n').trim();
  if (text.length > limit) {
    const cut = text.lastIndexOf('\n', limit);
    text = `${text.slice(0, cut > limit * 0.6 ? cut : limit).trimEnd()}\n\n… _(vollständig in der angehängten Datei)_`;
  }
  return text || '_(leer)_';
}

export function fileStem(title) {
  return String(title || 'zusammenfassung').replace(/[^\p{L}\p{N}_-]+/gu, '_').replace(/^_+|_+$/g, '') || 'zusammenfassung';
}

export function formatDuration(seconds) {
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}:${String(m).padStart(2, '0')} h` : `${m}:${String(s % 60).padStart(2, '0')} min`;
}
