// node --test  –  prüft den Ogg-Opus-Writer ohne Discord und ohne Audiobibliothek.
import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import test from 'node:test';
import { OggOpusWriter, oggCrc } from './ogg-opus.mjs';

test('Ogg-CRC entspricht dem Referenzwert', () => {
  assert.equal(oggCrc(Buffer.from('123456789')), 0x89a1897f);
});

test('Seitenstruktur: Header-Pakete, Granule-Position, EOS und gültige Prüfsummen', async () => {
  const out = new PassThrough();
  const chunks = [];
  out.on('data', (c) => chunks.push(c));
  const writer = new OggOpusWriter(out, { channels: 2, serial: 42, packetsPerPage: 4 });
  for (let i = 0; i < 10; i++) writer.write(Buffer.alloc(i === 3 ? 600 : 80, i)); // ein Paket > 255 Byte
  writer.end();
  await new Promise((r) => out.on('end', r));
  const data = Buffer.concat(chunks);

  const pages = [];
  for (let pos = 0; pos < data.length; ) {
    assert.equal(data.toString('ascii', pos, pos + 4), 'OggS');
    const nseg = data[pos + 26];
    const bodyLen = [...data.subarray(pos + 27, pos + 27 + nseg)].reduce((a, b) => a + b, 0);
    const page = Buffer.from(data.subarray(pos, pos + 27 + nseg + bodyLen));
    const stored = page.readUInt32LE(22);
    page.writeUInt32LE(0, 22);
    assert.equal(oggCrc(page), stored, `CRC von Seite ${pages.length}`);
    pages.push({ flags: data[pos + 5], granule: data.readBigUInt64LE(pos + 6), seq: data.readUInt32LE(pos + 18),
      body: data.subarray(pos + 27 + nseg, pos + 27 + nseg + bodyLen) });
    pos += 27 + nseg + bodyLen;
  }
  assert.equal(pages[0].flags, 0x02); // BOS
  assert.equal(pages[0].body.toString('ascii', 0, 8), 'OpusHead');
  assert.equal(pages[1].body.toString('ascii', 0, 8), 'OpusTags');
  assert.deepEqual(pages.map((p) => p.seq), pages.map((_, i) => i));
  const last = pages.at(-1);
  assert.equal(last.flags, 0x04); // EOS
  assert.equal(last.granule, 10n * 960n);
  const audioBytes = pages.slice(2).reduce((a, p) => a + p.body.length, 0);
  assert.equal(audioBytes, 9 * 80 + 600);
});
