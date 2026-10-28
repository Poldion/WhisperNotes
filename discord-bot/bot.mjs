// WhisperNotes-Discord-Bot
//
//   /aufnahme start [titel]  – nimmt den Voice-Channel auf (jede Person als eigene Spur)
//   /aufnahme stop           – beendet die Aufnahme und schickt sie an WhisperNotes
//   /aufnahme status         – zeigt, ob gerade aufgenommen wird
//
// Fertige Zusammenfassungen postet der Bot in den Channel, in dem die Aufnahme gestartet wurde.
// DnD-Recaps landen in dem Channel, der in der Kampagne im Dashboard ausgewählt ist.
//
// Start (im Ordner discord-bot/): npm start  ·  Konfiguration: discord-bot/.env (siehe .env.example)

import { rm } from 'node:fs/promises';
import { join } from 'node:path';
import {
  AttachmentBuilder,
  ChannelType,
  Client,
  EmbedBuilder,
  Events,
  GatewayIntentBits,
  MessageFlags,
  PermissionFlagsBits,
  SlashCommandBuilder,
} from 'discord.js';
import { RecordingSession } from './recorder.mjs';
import { fileStem, formatDuration, summaryToEmbedText } from './summary-format.mjs';
import { WrapperClient } from './wrapper.mjs';

const env = process.env;
const TOKEN = env.DISCORD_TOKEN;
const WRAPPER_URL = env.WHISPERNOTES_URL || 'http://127.0.0.1:8000';
// Link zum Dashboard in den Posts – nur, wenn es für alle im Discord erreichbar ist (sonst leer lassen)
const DASHBOARD_URL = (env.DASHBOARD_URL || '').trim();
const RECORDINGS_DIR = env.RECORDINGS_DIR || join(import.meta.dirname, 'recordings');
const MAX_SECONDS = Number(env.MAX_RECORDING_HOURS || 6) * 3600;
const EMPTY_STOP_SECONDS = Number(env.EMPTY_CHANNEL_STOP_SECONDS || 60);
const KEEP_RECORDINGS = /^(1|true|yes)$/i.test(env.KEEP_RECORDINGS || '');
const POLL_SECONDS = 30;

if (!TOKEN) {
  console.error('DISCORD_TOKEN fehlt – in discord-bot/.env eintragen (siehe .env.example).');
  process.exit(1);
}

const wrapper = new WrapperClient(WRAPPER_URL, (env.WHISPERNOTES_API_KEY || '').trim());
const sessions = new Map(); // guildId → RecordingSession
const log = (...args) => console.log(new Date().toISOString(), ...args);

const command = new SlashCommandBuilder()
  .setName('aufnahme')
  .setDescription('Gespräch im Voice-Channel aufnehmen und von WhisperNotes zusammenfassen lassen')
  .addSubcommand((s) =>
    s
      .setName('start')
      .setDescription('Aufnahme im Voice-Channel starten, in dem du gerade bist')
      .addStringOption((o) => o.setName('titel').setDescription('Titel der Aufnahme').setMaxLength(100)),
  )
  .addSubcommand((s) => s.setName('stop').setDescription('Aufnahme beenden und verarbeiten lassen'))
  .addSubcommand((s) => s.setName('status').setDescription('Zeigt, ob gerade aufgenommen wird'));

const client = new Client({ intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates] });

client.once(Events.ClientReady, async (c) => {
  for (const guild of c.guilds.cache.values()) await registerCommands(guild);
  log(`Eingeloggt als ${c.user.tag} auf ${c.guilds.cache.size} Server(n); WhisperNotes: ${WRAPPER_URL}`);
  await pushChannels();
  setInterval(pushChannels, 10 * 60 * 1000);
  setInterval(postPending, POLL_SECONDS * 1000);
  setInterval(checkSessions, 15 * 1000);
  postPending();
});

client.on(Events.GuildCreate, async (guild) => {
  await registerCommands(guild);
  await pushChannels();
});
// Channel-Liste fürs Dashboard aktuell halten: neu, gelöscht, umbenannt oder Rechte geändert
// (z. B. Bot nachträglich in einen privaten Channel gelassen). Mehrere Ereignisse kurz hintereinander
// werden zu einer Meldung zusammengefasst.
let pushTimer = null;
function schedulePush() {
  clearTimeout(pushTimer);
  pushTimer = setTimeout(pushChannels, 2000);
}
client.on(Events.ChannelCreate, schedulePush);
client.on(Events.ChannelDelete, schedulePush);
client.on(Events.ChannelUpdate, schedulePush);
client.on(Events.GuildRoleUpdate, schedulePush);
client.on(Events.GuildMemberUpdate, (_, member) => {
  if (member.id === client.user?.id) schedulePush(); // Rollen des Bots geändert
});

async function registerCommands(guild) {
  // Pro Server registriert wirkt sofort (globale Befehle können bis zu einer Stunde brauchen)
  await guild.commands.set([command.toJSON()]).catch((e) => log(`Befehle für ${guild.name}:`, e.message));
}

// ------------------------------------------------------------------ Befehle

client.on(Events.InteractionCreate, async (interaction) => {
  if (!interaction.isChatInputCommand() || interaction.commandName !== 'aufnahme') return;
  const sub = interaction.options.getSubcommand();
  try {
    if (sub === 'start') await startRecording(interaction);
    else if (sub === 'stop') await stopRecording(interaction);
    else await showStatus(interaction);
  } catch (e) {
    log('Fehler bei /aufnahme', sub, e);
    const content = `❌ ${e.message}`;
    if (interaction.deferred || interaction.replied) await interaction.followUp({ content }).catch(() => {});
    else await interaction.reply({ content, flags: MessageFlags.Ephemeral }).catch(() => {});
  }
});

async function startRecording(interaction) {
  const guild = interaction.guild;
  if (sessions.has(guild.id)) {
    const running = sessions.get(guild.id);
    await interaction.reply({
      content: `Es läuft bereits eine Aufnahme in **${running.channel.name}** (${formatDuration(running.elapsedSeconds)}).`,
      flags: MessageFlags.Ephemeral,
    });
    return;
  }
  const member = await guild.members.fetch(interaction.user.id);
  const channel = member.voice.channel;
  if (!channel) {
    await interaction.reply({ content: 'Geh zuerst in einen Voice-Channel.', flags: MessageFlags.Ephemeral });
    return;
  }
  const me = guild.members.me;
  if (!channel.permissionsFor(me)?.has([PermissionFlagsBits.ViewChannel, PermissionFlagsBits.Connect])) {
    await interaction.reply({ content: `Mir fehlt das Recht, **${channel.name}** zu betreten.`, flags: MessageFlags.Ephemeral });
    return;
  }
  await interaction.deferReply();
  const title = interaction.options.getString('titel')?.trim() || `${channel.name} – ${new Date().toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short' })}`;
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const session = new RecordingSession({
    channel,
    textChannelId: interaction.channelId,
    title,
    dir: join(RECORDINGS_DIR, `${guild.id}-${stamp}`),
    log: (msg) => log(`[${guild.name}]`, msg),
  });
  session.onLost = () => finish(session, 'Verbindung verloren');
  await session.start();
  sessions.set(guild.id, session);
  log(`[${guild.name}] Aufnahme gestartet in #${channel.name}: ${title}`);
  await interaction.editReply(
    `🔴 **Aufnahme läuft** in **${channel.name}** – „${title}“\n` +
      'Alle im Channel werden aufgenommen, jede Person als eigene Spur. Wer nicht aufgenommen werden möchte, ' +
      'sagt bitte Bescheid oder verlässt den Channel.\n' +
      `Beenden mit \`/aufnahme stop\` · automatisch nach ${formatDuration(MAX_SECONDS)} oder wenn der Channel leer ist.`,
  );
}

async function stopRecording(interaction) {
  const session = sessions.get(interaction.guild.id);
  if (!session) {
    await interaction.reply({ content: 'Es läuft gerade keine Aufnahme.', flags: MessageFlags.Ephemeral });
    return;
  }
  await interaction.deferReply();
  const message = await finish(session, `beendet von ${interaction.member?.displayName ?? interaction.user.username}`);
  await interaction.editReply(message);
}

async function showStatus(interaction) {
  const session = sessions.get(interaction.guild.id);
  const content = session
    ? `🔴 Aufnahme in **${session.channel.name}** seit ${formatDuration(session.elapsedSeconds)} · ` +
      `${[...session.tracks.values()].filter((t) => t.packets).length} Person(en) mit Audio`
    : 'Gerade läuft keine Aufnahme.';
  await interaction.reply({ content, flags: MessageFlags.Ephemeral });
}

// ------------------------------------------------------------------ Aufnahme beenden & hochladen

/** Aufnahme beenden, hochladen, Statustext liefern. Mehrfachaufrufe (Stop + Auto-Stop) teilen sich ein Ergebnis. */
function finish(session, reason) {
  session.finishing ??= finishOnce(session, reason);
  return session.finishing;
}

async function finishOnce(session, reason) {
  sessions.delete(session.channel.guild.id);
  const { manifest, files } = await session.stop(reason);
  log(`[${session.channel.guild.name}] Aufnahme beendet (${reason}), ${files.length} Spur(en)`);
  if (!files.length) {
    await rm(session.dir, { recursive: true, force: true });
    return '⏹️ Aufnahme beendet – es wurde niemand gehört, daher gibt es nichts zu verarbeiten.';
  }
  const people = files.map((f) => `${f.speaker} (${formatDuration(f.seconds)})`).join(', ');
  try {
    const job = await wrapper.uploadMultitrack(manifest, files, session.textChannelId);
    if (!KEEP_RECORDINGS) await rm(session.dir, { recursive: true, force: true });
    return (
      `⏹️ **Aufnahme beendet** (${reason}) – ${formatDuration(manifest.duration_s)}, ${people}.\n` +
      `WhisperNotes verarbeitet sie jetzt; die Zusammenfassung poste ich hier, sobald sie fertig ist.\n` +
      `-# Job ${job.id}`
    );
  } catch (e) {
    log('Upload fehlgeschlagen:', e.message);
    return (
      `⚠️ Aufnahme beendet (${people}), aber der Upload zu WhisperNotes ist fehlgeschlagen: ${e.message}\n` +
      `Die Spuren liegen auf dem Mac unter \`${session.dir}\`.`
    );
  }
}

/** Automatischer Stopp: Channel leer oder Maximaldauer erreicht. */
async function checkSessions() {
  for (const session of [...sessions.values()]) {
    const humans = session.channel.members.filter((m) => !m.user.bot).size;
    session.emptySince = humans ? null : (session.emptySince ?? Date.now());
    let reason = null;
    if (session.emptySince && Date.now() - session.emptySince >= EMPTY_STOP_SECONDS * 1000) reason = 'Channel leer';
    else if (session.elapsedSeconds >= MAX_SECONDS) reason = `Maximaldauer ${formatDuration(MAX_SECONDS)} erreicht`;
    if (!reason) continue;
    const message = await finish(session, reason);
    const text = await client.channels.fetch(session.textChannelId).catch(() => null);
    await text?.send(message).catch((e) => log('Statusmeldung nicht gesendet:', e.message));
  }
}

// ------------------------------------------------------------------ Zusammenfassungen posten

let posting = false;

async function postPending() {
  if (posting) return;
  posting = true;
  try {
    for (const job of await wrapper.pending()) await postSummary(job);
  } catch (e) {
    if (!/fetch failed|ECONNREFUSED/.test(e.message)) log('Abruf fertiger Zusammenfassungen:', e.message);
  } finally {
    posting = false;
  }
}

async function postSummary(job) {
  let channel;
  try {
    channel = await client.channels.fetch(job.discord_channel_id);
  } catch (e) {
    if (e.code === 10003 || e.code === 50001) {
      // Channel gelöscht oder kein Zugriff: nicht endlos erneut versuchen
      log(`Channel ${job.discord_channel_id} für Job ${job.id} nicht erreichbar (${e.code}), überspringe`);
      await wrapper.markPosted(job.id);
    }
    return;
  }
  const markdown = await wrapper.summary(job.id);
  const isDnd = job.kind === 'dnd';
  const embed = new EmbedBuilder()
    .setColor(isDnd ? 0x8b5cf6 : 0x4f46e5)
    .setTitle(`${isDnd ? '🎲 Session-Recap' : '📝 Zusammenfassung'}: ${job.title || job.filename}`.slice(0, 256))
    .setDescription(summaryToEmbedText(markdown))
    .setFooter({ text: [job.source_label, job.ollama_model && `Modell: ${job.ollama_model}`].filter(Boolean).join(' · ') || 'WhisperNotes' });
  if (/^https?:\/\//.test(DASHBOARD_URL)) embed.setURL(DASHBOARD_URL + (isDnd ? '#dnd' : ''));
  const file = new AttachmentBuilder(Buffer.from(markdown, 'utf8'), {
    name: `${fileStem(job.title || job.filename)}_${isDnd ? 'recap' : 'zusammenfassung'}.md`,
  });
  const files = [file];
  // Recaps je Spielercharakter mitschicken – die Lore-Übersicht ist nur für den DM (Spoiler) und bleibt im Dashboard
  if (job.extra_docs?.includes('players')) {
    try {
      const players = await wrapper.document(job.id, 'players');
      files.push(new AttachmentBuilder(Buffer.from(players, 'utf8'), {
        name: `${fileStem(job.title || job.filename)}_spieler-recaps.md`,
      }));
    } catch (e) {
      log(`Spieler-Recaps für Job ${job.id} nicht abrufbar: ${e.message}`);
    }
  }
  await channel.send({ embeds: [embed], files });
  await wrapper.markPosted(job.id);
  log(`Zusammenfassung von Job ${job.id} in #${channel.name} gepostet`);
}

// ------------------------------------------------------------------ Channels an das Dashboard melden

async function pushChannels() {
  const channels = [];
  for (const guild of client.guilds.cache.values()) {
    const me = guild.members.me;
    for (const ch of guild.channels.cache.values()) {
      if (![ChannelType.GuildText, ChannelType.GuildAnnouncement].includes(ch.type)) continue;
      const perms = ch.permissionsFor(me);
      if (!perms?.has([PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages])) continue;
      channels.push({ id: ch.id, name: ch.name, guild: guild.name });
    }
  }
  try {
    await wrapper.pushChannels(channels);
  } catch (e) {
    log('Channel-Liste nicht gemeldet (läuft WhisperNotes?):', e.message);
  }
}

// ------------------------------------------------------------------ Beenden

async function shutdown(signal) {
  log(`${signal} – laufende Aufnahmen werden gesichert`);
  for (const session of [...sessions.values()]) {
    const message = await finish(session, 'Bot wird beendet');
    const text = await client.channels.fetch(session.textChannelId).catch(() => null);
    await text?.send(message).catch(() => {});
  }
  await client.destroy();
  process.exit(0);
}
process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));

client.login(TOKEN);
