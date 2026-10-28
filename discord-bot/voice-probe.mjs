// Machbarkeitstest: Kann der Bot unter Discords Ende-zu-Ende-Verschlüsselung (DAVE) Sprache empfangen?
//
//   /testaufnahme [sekunden]  – Bot kommt in deinen Voice-Channel, nimmt jede Person als eigene
//                               Ogg/Opus-Datei auf und meldet danach, was angekommen ist.
//
// Start (im Ordner discord-bot/):  npm install && npm run probe
// Konfiguration in discord-bot/.env: DISCORD_TOKEN=…

import { createWriteStream, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import {
  EndBehaviorType,
  VoiceConnectionStatus,
  entersState,
  generateDependencyReport,
  joinVoiceChannel,
} from '@discordjs/voice';
import { Client, Events, GatewayIntentBits, MessageFlags, SlashCommandBuilder } from 'discord.js';
import { OggOpusWriter } from './ogg-opus.mjs';

const TOKEN = process.env.DISCORD_TOKEN;
const OUT_DIR = process.env.RECORDINGS_DIR ?? join(import.meta.dirname, 'recordings');
const MAX_SECONDS = 600;

if (!TOKEN) {
  console.error('DISCORD_TOKEN fehlt – in discord-bot/.env eintragen (siehe .env.example).');
  process.exit(1);
}

console.log(generateDependencyReport());

const command = new SlashCommandBuilder()
  .setName('testaufnahme')
  .setDescription('Testet die Sprachaufnahme: nimmt jede Person im Voice-Channel als eigene Datei auf')
  .addIntegerOption((o) =>
    o.setName('sekunden').setDescription('Dauer (10–600, Standard 60)').setMinValue(10).setMaxValue(MAX_SECONDS),
  );

const client = new Client({ intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates] });

client.once(Events.ClientReady, async (c) => {
  // Befehl pro Server registrieren – das wirkt sofort (globale Befehle können dauern)
  for (const guild of c.guilds.cache.values()) {
    await guild.commands.set([command.toJSON()]).catch((e) => console.error(`Befehl in ${guild.name}:`, e.message));
  }
  console.log(`Eingeloggt als ${c.user.tag} – /testaufnahme ist auf ${c.guilds.cache.size} Server(n) verfügbar.`);
});

client.on(Events.GuildCreate, (guild) => guild.commands.set([command.toJSON()]).catch(() => {}));

client.on(Events.InteractionCreate, async (interaction) => {
  if (!interaction.isChatInputCommand() || interaction.commandName !== 'testaufnahme') return;
  const member = await interaction.guild.members.fetch(interaction.user.id);
  const channel = member.voice.channel;
  if (!channel) {
    await interaction.reply({ content: 'Geh zuerst in einen Voice-Channel.', flags: MessageFlags.Ephemeral });
    return;
  }
  const seconds = interaction.options.getInteger('sekunden') ?? 60;
  await interaction.reply(
    `🔴 **Testaufnahme läuft** in **${channel.name}** für ${seconds} s. ` +
      'Alle Anwesenden werden aufgenommen – bitte ein wenig durcheinander und nacheinander sprechen.',
  );
  try {
    const report = await record(channel, seconds);
    await interaction.followUp(report);
  } catch (e) {
    console.error(e);
    await interaction.followUp(`❌ Testaufnahme fehlgeschlagen: ${e.message}`);
  }
});

async function record(channel, seconds) {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const dir = join(OUT_DIR, `test-${stamp}`);
  mkdirSync(dir, { recursive: true });

  const debugLog = createWriteStream(join(dir, 'voice-debug.log'));
  const stats = new Map(); // userId → { name, segments, packets, bytes }
  let decryptProblems = 0;

  const connection = joinVoiceChannel({
    channelId: channel.id,
    guildId: channel.guild.id,
    adapterCreator: channel.guild.voiceAdapterCreator,
    selfDeaf: false, // sonst empfängt der Bot nichts
    selfMute: true,
    debug: true, // DAVE-Einstellungen bleiben bewusst auf den Standardwerten
  });
  connection.on('debug', (msg) => {
    debugLog.write(`${new Date().toISOString()} ${msg}\n`);
    if (/decrypt/i.test(msg) && /fail|error/i.test(msg)) decryptProblems += 1;
  });
  connection.on('stateChange', (a, b) => debugLog.write(`${new Date().toISOString()} state ${a.status} -> ${b.status}\n`));

  await entersState(connection, VoiceConnectionStatus.Ready, 30_000);
  const startedAt = Date.now();
  const active = new Set();

  connection.receiver.speaking.on('start', (userId) => {
    if (active.has(userId)) return;
    active.add(userId);
    const member = channel.guild.members.cache.get(userId);
    const name = member?.displayName ?? userId;
    const entry = stats.get(userId) ?? { name, segments: 0, packets: 0, bytes: 0 };
    stats.set(userId, entry);
    entry.segments += 1;

    // Ein Abschnitt pro Redebeitrag; Dateiname enthält den Versatz in ms ab Aufnahmestart
    const offset = String(Date.now() - startedAt).padStart(8, '0');
    const file = join(dir, `${safe(name)}_${userId}_${offset}.ogg`);
    const opus = connection.receiver.subscribe(userId, { end: { behavior: EndBehaviorType.AfterSilence, duration: 800 } });
    const ogg = new OggOpusWriter(createWriteStream(file), { channels: 2 });
    opus.on('data', (packet) => {
      entry.packets += 1;
      entry.bytes += packet.length;
      ogg.write(packet);
    });
    const finish = () => {
      ogg.end();
      active.delete(userId);
    };
    opus.once('end', finish);
    opus.once('close', finish);
    opus.once('error', (e) => {
      debugLog.write(`${new Date().toISOString()} Empfang ${name}: ${e.message}\n`);
      finish();
    });
  });

  await new Promise((resolve) => setTimeout(resolve, seconds * 1000));
  const reconnects = connection.state.status !== VoiceConnectionStatus.Ready ? ` (Status am Ende: ${connection.state.status})` : '';
  connection.destroy();
  await new Promise((resolve) => setTimeout(resolve, 1000)); // letzte Dateien schließen
  debugLog.end();

  if (stats.size === 0) {
    return (
      `⚠️ **Nichts empfangen.** Niemand wurde als sprechend erkannt${reconnects}. ` +
      `Das spricht für ein DAVE-Problem beim Empfang. Debug-Log: \`${join(dir, 'voice-debug.log')}\``
    );
  }
  const lines = [...stats.values()].map((s) => {
    const audio = (s.packets * 0.02).toFixed(1); // ein Opus-Paket = 20 ms
    return `• **${s.name}**: ${audio} s Audio in ${s.segments} Abschnitten (${s.packets} Pakete)`;
  });
  const verdict =
    decryptProblems === 0
      ? '✅ Keine Entschlüsselungsfehler gemeldet.'
      : `⚠️ ${decryptProblems} Entschlüsselungs-Meldungen im Debug-Log.`;
  return [`**Testaufnahme beendet** (${seconds} s)${reconnects}`, ...lines, verdict, `Dateien: \`${dir}\``].join('\n');
}

function safe(name) {
  return name.replace(/[^\p{L}\p{N}_-]+/gu, '_').slice(0, 40) || 'unbekannt';
}

process.on('SIGINT', () => {
  client.destroy();
  process.exit(0);
});

client.login(TOKEN);
