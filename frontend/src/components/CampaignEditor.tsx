import { useEffect, useState } from 'react'
import {
  fetchBasaltVaults,
  fetchDiscordChannels,
  type BasaltVaults,
  type Campaign,
  type CampaignInput,
  type DiscordChannel,
  type Player,
} from '../api'
import { t } from '../i18n'

interface Props {
  initial?: Campaign
  onSave: (data: CampaignInput) => Promise<void>
  onCancel?: () => void
  onDelete?: () => Promise<void>
}

const emptyPlayer = (): Player => ({ name: '', character: '', role: 'player' })

export default function CampaignEditor({ initial, onSave, onCancel, onDelete }: Props) {
  const [name, setName] = useState(initial?.name ?? '')
  const [players, setPlayers] = useState<Player[]>(
    initial?.players.length ? initial.players : [{ name: '', character: '', role: 'dm' }, emptyPlayer()],
  )
  const [glossary, setGlossary] = useState(initial?.glossary ?? '')
  const [discordChannel, setDiscordChannel] = useState(initial?.discord_channel_id ?? '')
  const [channels, setChannels] = useState<DiscordChannel[] | null>(null)
  const [vault, setVault] = useState(initial?.basalt_vault ?? '')
  const [vaults, setVaults] = useState<BasaltVaults | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchDiscordChannels()
      .then((data) => setChannels(data.channels))
      .catch(() => setChannels([]))
    fetchBasaltVaults()
      .then(setVaults)
      .catch(() => setVaults(null))
  }, [])

  const setPlayer = (i: number, patch: Partial<Player>) =>
    setPlayers((list) => list.map((p, k) => (k === i ? { ...p, ...patch } : p)))

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  const save = () =>
    run(() =>
      onSave({
        name: name.trim(),
        glossary,
        discord_channel_id: discordChannel || null,
        basalt_vault: vault || null,
        players: players
          .filter((p) => p.name.trim())
          .map((p) => ({ ...p, name: p.name.trim(), character: p.character.trim() })),
      }),
    )

  return (
    <div className="panel">
      <h3>{initial ? t('Kampagne bearbeiten') : t('Neue Kampagne')}</h3>
      <label className="field">
        {t('Name')}
        <input type="text" value={name} autoFocus placeholder={t('z. B. Fluch des Strahd')}
          onChange={(e) => setName(e.target.value)} />
      </label>

      <div className="field">
        {t('Runde')}
        <div className="player-table">
          {players.map((p, i) => (
            <div className="player-row" key={i}>
              <input type="text" placeholder={t('Spieler:in')} value={p.name}
                onChange={(e) => setPlayer(i, { name: e.target.value })} />
              <input type="text" placeholder={p.role === 'dm' ? '–' : t('Charakter')} value={p.character}
                disabled={p.role === 'dm'} onChange={(e) => setPlayer(i, { character: e.target.value })} />
              <select value={p.role} onChange={(e) => setPlayer(i, { role: e.target.value as Player['role'] })}>
                <option value="player">{t('Spieler')}</option>
                <option value="dm">DM</option>
              </select>
              <button className="btn ghost small" aria-label={t('Entfernen')}
                onClick={() => setPlayers((list) => list.filter((_, k) => k !== i))}>
                ✕
              </button>
            </div>
          ))}
        </div>
        <button className="btn ghost small" onClick={() => setPlayers((list) => [...list, emptyPlayer()])}>
          + {t('Person hinzufügen')}
        </button>
        <span className="hint">{t('Die Anzahl der Personen wird als Sprecheranzahl für die Erkennung genutzt.')}</span>
      </div>

      <label className="field">
        {t('Glossar')}
        <textarea rows={3} value={glossary} placeholder={t('Orte, NPCs, Götter, Zauber … durch Komma getrennt')}
          onChange={(e) => setGlossary(e.target.value)} />
        <span className="hint">
          {t('Hilft Whisper bei der Schreibweise von Fantasy-Namen und dem Recap bei der Einordnung. Übliche D&D-Begriffe (Attribute, Fertigkeiten, Initiative, Rüstungsklasse …) sind automatisch dabei – hier nur Eigenes eintragen. Kurz halten: Whisper berücksichtigt nur rund 500 Zeichen, Namen haben Vorrang.')}
        </span>
      </label>

      <label className="field">
        {t('Recap in Discord posten')}
        <select value={discordChannel} onChange={(e) => setDiscordChannel(e.target.value)}
          disabled={channels === null}>
          <option value="">{t('– nicht posten –')}</option>
          {channels?.map((c) => (
            <option key={c.id} value={c.id}>
              #{c.name}{c.guild ? ` (${c.guild})` : ''}
            </option>
          ))}
          {discordChannel && channels && !channels.some((c) => c.id === discordChannel) && (
            <option value={discordChannel}>{t('Channel {id} (aktuell nicht gemeldet)', { id: discordChannel })}</option>
          )}
        </select>
        <span className="hint">
          {channels?.length
            ? t('Fertige Session-Recaps postet der WhisperNotes-Bot automatisch in diesen Channel.')
            : t('Noch keine Channels bekannt – sobald der Discord-Bot läuft, meldet er seine Channels hierher.')}
        </span>
      </label>

      {vaults?.enabled && (
        <label className="field">
          {t('BasaltNotes-Vault')}
          <select value={vault} onChange={(e) => setVault(e.target.value)}>
            <option value="">{t('Standard')}{vaults.default_dnd ? ` (${vaults.default_dnd})` : ''}</option>
            {vaults.vaults.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
                {v.name !== v.id ? ` (${v.id})` : ''}
              </option>
            ))}
            {vault && !vaults.vaults.some((v) => v.id === vault) && (
              <option value={vault}>{t('{vault} (in BasaltNotes nicht gefunden)', { vault })}</option>
            )}
          </select>
          <span className="hint">
            {vaults.error
              ? t('Vaults nicht abrufbar: {error}', { error: vaults.error })
              : t('Hierhin gehen die Recaps dieser Kampagne; die Namen aus diesem Wiki verbessern die Erkennung.')}
          </span>
        </label>
      )}

      {error && <p className="error-text">{error}</p>}
      <div className="actions">
        <div className="downloads">
          <button className="btn primary" disabled={busy || !name.trim()} onClick={save}>
            {t('Speichern')}
          </button>
          {onCancel && (
            <button className="btn ghost" disabled={busy} onClick={onCancel}>
              {t('Abbrechen')}
            </button>
          )}
        </div>
        {onDelete && (
          <button className="btn ghost small danger" disabled={busy}
            onClick={() => confirm(t('Kampagne „{name}“ löschen? Die Sessions bleiben unter „Aufnahmen“ erhalten.', { name: initial?.name ?? '' })) && run(onDelete)}>
            {t('Kampagne löschen')}
          </button>
        )}
      </div>
    </div>
  )
}
