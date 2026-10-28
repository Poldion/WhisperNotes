// node --test  –  Recorder-Buchführung und Discord-Formatierung, ohne Discord-Verbindung.
import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import test from 'node:test';
import { PRE_SKIP, SpeakerTrack, safeName } from './recorder.mjs';
import { fileStem, formatDuration, summaryToEmbedText } from './summary-format.mjs';

function fakeTrack() {
  let clock = 1_000_000;
  const track = new SpeakerTrack({
    id: '42', name: 'Pold', file: 'Pold_42.ogg', path: 'x', startedAt: clock,
    now: () => clock, createStream: () => new PassThrough(),
  });
  track.stream.resume(); // Daten verwerfen, sonst staut sich der Stream
  return { track, advance: (ms) => (clock += ms) };
}

test('Segmente: Echtzeit-Versatz, Paketindex und neuer Beitrag bei Pausen', async () => {
  const { track, advance } = fakeTrack();
  advance(1_000); // spricht ab 1 s
  for (let i = 0; i < 50; i++) { track.addPacket(Buffer.alloc(40)); advance(20); } // 1 s Audio
  advance(400); // Pause > 250 ms mitten im Empfang → neuer Beitrag
  for (let i = 0; i < 25; i++) { track.addPacket(Buffer.alloc(40)); advance(20); }
  track.endSegment(); // Stille erkannt
  advance(5_000);
  for (let i = 0; i < 10; i++) { track.addPacket(Buffer.alloc(40)); advance(20); }
  await track.finish();

  const m = track.toManifest();
  assert.equal(m.pre_skip, PRE_SKIP);
  assert.deepEqual(m.segments, [
    { offset_ms: 1000, packet_start: 0, packets: 50 },
    { offset_ms: 2400, packet_start: 50, packets: 25 },
    { offset_ms: 7900, packet_start: 75, packets: 10 },
  ]);
  assert.equal(track.seconds, 1.7);
});

test('kurze Jitter-Lücken unter 250 ms bleiben im selben Beitrag', async () => {
  const { track, advance } = fakeTrack();
  for (let i = 0; i < 10; i++) { track.addPacket(Buffer.alloc(40)); advance(i === 4 ? 200 : 20); }
  await track.finish();
  assert.equal(track.toManifest().segments.length, 1);
});

test('Dateinamen sind sicher', () => {
  assert.equal(safeName('Pold 🎲 / ../x'), 'Pold_x');
  assert.equal(safeName(''), 'unbekannt');
  assert.equal(fileStem('Montag: Runde #3'), 'Montag_Runde_3');
});

test('Zusammenfassung für Discord: Kopf weg, Überschriften fett, gekürzt an Zeilengrenze', () => {
  const md = '# Zusammenfassung: Runde\n\n> Aufnahme vom Mi …\n\n## Zusammenfassung\nText.\n\n## Kernpunkte\n- a\n- b\n';
  assert.equal(summaryToEmbedText(md), '**Zusammenfassung**\nText.\n\n**Kernpunkte**\n- a\n- b');
  const items = Array.from({ length: 400 }, (_, i) => `- Punkt Nummer ${i}`);
  const out = summaryToEmbedText('## Punkte\n' + items.join('\n'));
  assert.ok(out.length <= 4096);
  assert.match(out, /angehängten Datei/);
  const lastKept = out.split('\n').at(-3);
  assert.ok(items.includes(lastKept), `abgeschnittene Zeile: ${lastKept}`); // an einer Zeilengrenze gekürzt
});

test('Dauer lesbar', () => {
  assert.equal(formatDuration(75), '1:15 min');
  assert.equal(formatDuration(3 * 3600 + 5 * 60), '3:05 h');
});
