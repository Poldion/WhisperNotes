// Aufnahme eines Voice-Channels: je Person eine "kompakte" Ogg/Opus-Spur (nur die Redebeiträge,
// lückenlos hintereinander) plus eine Tabelle, wann jeder Beitrag in Echtzeit begann und ab welchem
// Paket er in der Spur steht. Der Wrapper rechnet damit jede Stelle auf die echte Zeit zurück
// (siehe backend/app/multitrack.py).

import { once } from 'node:events';
import { createWriteStream, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { EndBehaviorType, VoiceConnectionStatus, entersState, joinVoiceChannel } from '@discordjs/voice';
import { OggOpusWriter } from './ogg-opus.mjs';

export const PRE_SKIP = 312; // muss zum OggOpusWriter passen
const GAP_MS = 250; // längere Paketlücke = neuer Beitrag (Discord sendet in Pausen keine Pakete)

/** Spur einer Person. `now` und `createStream` sind für Tests austauschbar. */
export class SpeakerTrack {
  constructor({ id, name, file, path, startedAt, now = Date.now, createStream = createWriteStream }) {
    Object.assign(this, { id, name, file, startedAt, now });
    this.stream = createStream(path);
    this.writer = new OggOpusWriter(this.stream, { channels: 2 });
    this.packets = 0;
    this.segments = [];
    this.current = null;
    this.lastPacketAt = 0;
  }

  addPacket(packet) {
    const t = this.now();
    if (this.current && t - this.lastPacketAt > GAP_MS) this.#closeSegment();
    if (!this.current) {
      this.current = { offset_ms: Math.max(0, Math.round(t - this.startedAt)), packet_start: this.packets, packets: 0 };
    }
    this.writer.write(packet);
    this.packets += 1;
    this.current.packets += 1;
    this.lastPacketAt = t;
  }

  /** Ende eines Redebeitrags (Stille erkannt). */
  endSegment() {
    this.#closeSegment();
  }

  async finish() {
    this.#closeSegment();
    this.writer.end();
    await once(this.stream, 'finish');
  }

  get seconds() {
    return this.packets * 0.02;
  }

  toManifest() {
    return { id: this.id, name: this.name, file: this.file, pre_skip: PRE_SKIP, segments: this.segments };
  }

  #closeSegment() {
    if (this.current?.packets) this.segments.push(this.current);
    this.current = null;
  }
}

export function safeName(name) {
  return String(name).replace(/[^\p{L}\p{N}_-]+/gu, '_').slice(0, 40) || 'unbekannt';
}

/** Eine laufende Aufnahme in einem Voice-Channel. */
export class RecordingSession {
  constructor({ channel, textChannelId, title, dir, log = () => {} }) {
    Object.assign(this, { channel, textChannelId, title, dir, log });
    this.tracks = new Map(); // userId → SpeakerTrack
    this.active = new Set(); // userIds mit laufender Empfangs-Subscription
    this.startedAt = 0;
    this.stopped = false;
    this.stopReason = null;
  }

  async start() {
    mkdirSync(this.dir, { recursive: true });
    this.connection = joinVoiceChannel({
      channelId: this.channel.id,
      guildId: this.channel.guild.id,
      adapterCreator: this.channel.guild.voiceAdapterCreator,
      selfDeaf: false, // sonst empfängt der Bot nichts
      selfMute: true,
    });
    await entersState(this.connection, VoiceConnectionStatus.Ready, 30_000);
    this.startedAt = Date.now();

    this.connection.on(VoiceConnectionStatus.Disconnected, async () => {
      try {
        // Kurze Unterbrechung (z. B. Channel-Wechsel/Netz): Discord verbindet selbst neu
        await Promise.race([
          entersState(this.connection, VoiceConnectionStatus.Signalling, 5_000),
          entersState(this.connection, VoiceConnectionStatus.Connecting, 5_000),
        ]);
      } catch {
        this.log('Voice-Verbindung verloren – Aufnahme wird beendet');
        this.onLost?.();
      }
    });

    this.connection.receiver.speaking.on('start', (userId) => this.#subscribe(userId));
  }

  #subscribe(userId) {
    if (this.stopped || this.active.has(userId)) return;
    const member = this.channel.guild.members.cache.get(userId);
    if (member?.user.bot) return;
    this.active.add(userId);
    const track = this.#track(userId, member?.displayName ?? userId);
    const opus = this.connection.receiver.subscribe(userId, {
      end: { behavior: EndBehaviorType.AfterSilence, duration: 800 },
    });
    opus.on('data', (packet) => {
      if (!this.stopped) track.addPacket(packet);
    });
    const done = () => {
      track.endSegment();
      this.active.delete(userId);
    };
    opus.once('end', done);
    opus.once('close', done);
    opus.once('error', (e) => {
      this.log(`Empfangsfehler bei ${track.name}: ${e.message}`);
      done();
    });
  }

  #track(userId, name) {
    let track = this.tracks.get(userId);
    if (!track) {
      const file = `${safeName(name)}_${userId}.ogg`;
      track = new SpeakerTrack({ id: userId, name, file, path: join(this.dir, file), startedAt: this.startedAt });
      this.tracks.set(userId, track);
    }
    return track;
  }

  get elapsedSeconds() {
    return this.startedAt ? (Date.now() - this.startedAt) / 1000 : 0;
  }

  /** Beendet die Aufnahme und liefert Beschreibung (Manifest) + Pfade der Spuren. Mehrfachaufrufe sind sicher. */
  stop(reason = 'manuell') {
    this.stopping ??= this.#stop(reason);
    return this.stopping;
  }

  async #stop(reason) {
    this.stopped = true;
    this.stopReason = reason;
    const duration = this.elapsedSeconds;
    try {
      this.connection?.destroy();
    } catch {
      /* bereits getrennt */
    }
    const tracks = [...this.tracks.values()].filter((t) => t.packets > 0);
    await Promise.all([...this.tracks.values()].map((t) => t.finish()));
    return {
      manifest: {
        version: 1,
        title: this.title,
        source: 'discord',
        source_label: `Discord · #${this.channel.name}`,
        started_at: new Date(this.startedAt).toISOString(),
        duration_s: Math.max(1, Math.round(duration)),
        speakers: tracks.map((t) => t.toManifest()),
      },
      files: tracks.map((t) => ({ name: t.file, path: join(this.dir, t.file), seconds: t.seconds, speaker: t.name })),
    };
  }
}
