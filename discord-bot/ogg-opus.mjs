// Minimaler Ogg-Opus-Writer (RFC 3533 + RFC 7845): verpackt rohe Opus-Pakete, wie Discord sie liefert,
// in eine abspielbare .ogg-Datei – ohne Dekodieren und ohne native Bibliothek.

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let r = i << 24;
    for (let j = 0; j < 8; j++) r = r & 0x80000000 ? (r << 1) ^ 0x04c11db7 : r << 1;
    table[i] = r >>> 0;
  }
  return table;
})();

/** Ogg-CRC32: Polynom 0x04C11DB7, Startwert 0, ohne Spiegelung und ohne Endverknüpfung. */
export function oggCrc(buf) {
  let crc = 0;
  for (const byte of buf) crc = ((crc << 8) ^ CRC_TABLE[((crc >>> 24) ^ byte) & 0xff]) >>> 0;
  return crc >>> 0;
}

const SAMPLES_PER_PACKET = 960; // Discord: 20 ms bei 48 kHz

export class OggOpusWriter {
  /**
   * @param {import('node:stream').Writable} out  Ziel, z. B. fs.createWriteStream
   * @param {{channels?: number, serial?: number, packetsPerPage?: number}} [opts]
   */
  constructor(out, { channels = 2, serial = (Math.random() * 0xffffffff) >>> 0, packetsPerPage = 50 } = {}) {
    this.out = out;
    this.serial = serial;
    this.sequence = 0;
    this.granule = 0n;
    this.pending = [];
    this.packetsPerPage = packetsPerPage;
    this.closed = false;

    const head = Buffer.alloc(19);
    head.write('OpusHead', 0, 'ascii');
    head.writeUInt8(1, 8); // Version
    head.writeUInt8(channels, 9);
    head.writeUInt16LE(312, 10); // Pre-skip: Verzögerung des libopus-Encoders (Discord nutzt libopus)
    head.writeUInt32LE(48000, 12); // ursprüngliche Abtastrate
    head.writeInt16LE(0, 16); // Ausgangsverstärkung
    head.writeUInt8(0, 18); // Kanal-Mapping 0 (mono/stereo)
    this.#writePage([head], 0n, 0x02); // BOS

    const vendor = Buffer.from('WhisperNotes', 'utf8');
    const tags = Buffer.alloc(8 + 4 + vendor.length + 4);
    tags.write('OpusTags', 0, 'ascii');
    tags.writeUInt32LE(vendor.length, 8);
    vendor.copy(tags, 12);
    tags.writeUInt32LE(0, 12 + vendor.length); // keine Kommentare
    this.#writePage([tags], 0n, 0x00);
  }

  /** Ein Opus-Paket (20 ms) anhängen. */
  write(packet) {
    if (this.closed) return;
    this.pending.push(packet);
    this.granule += BigInt(SAMPLES_PER_PACKET);
    if (this.pending.length >= this.packetsPerPage) this.#flush(0x00);
  }

  /** Letzte Seite mit EOS-Markierung schreiben und das Ziel schließen. */
  end() {
    if (this.closed) return;
    this.closed = true;
    this.#flush(0x04, true);
    this.out.end();
  }

  #flush(flags, force = false) {
    if (!this.pending.length && !force) return;
    this.#writePage(this.pending, this.granule, flags);
    this.pending = [];
  }

  #writePage(packets, granule, flags) {
    const lacing = [];
    for (const p of packets) {
      let len = p.length;
      while (len >= 255) {
        lacing.push(255);
        len -= 255;
      }
      lacing.push(len); // 0 oder Rest schließt das Paket ab
    }
    if (lacing.length > 255) throw new Error('Ogg-Seite zu groß – packetsPerPage verkleinern');
    const header = Buffer.alloc(27 + lacing.length);
    header.write('OggS', 0, 'ascii');
    header.writeUInt8(0, 4); // Version
    header.writeUInt8(flags, 5);
    header.writeBigUInt64LE(granule, 6);
    header.writeUInt32LE(this.serial, 14);
    header.writeUInt32LE(this.sequence++, 18);
    header.writeUInt32LE(0, 22); // CRC, wird unten eingesetzt
    header.writeUInt8(lacing.length, 26);
    Buffer.from(lacing).copy(header, 27);
    const page = Buffer.concat([header, ...packets]);
    page.writeUInt32LE(oggCrc(page), 22);
    this.out.write(page);
  }
}
