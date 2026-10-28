// HTTP-Client für den WhisperNotes-Wrapper.

import { openAsBlob } from 'node:fs';

export class WrapperClient {
  /** `apiKey`: API_KEY von WhisperNotes, falls dort der Zugangsschutz aktiv ist */
  constructor(baseUrl, apiKey = '') {
    this.base = baseUrl.replace(/\/+$/, '');
    this.apiKey = apiKey;
  }

  async #request(path, init = {}) {
    const headers = { ...init.headers };
    if (this.apiKey) headers.Authorization = `Bearer ${this.apiKey}`;
    const resp = await fetch(this.base + path, { ...init, headers });
    if (!resp.ok) {
      let detail = resp.statusText;
      try {
        const body = await resp.json();
        detail = body?.error?.message ?? JSON.stringify(body?.detail ?? body);
      } catch {
        /* keine JSON-Antwort */
      }
      throw new Error(`WhisperNotes ${resp.status}: ${detail}`);
    }
    return resp;
  }

  /** Spuren + Beschreibung hochladen; liefert den angelegten Job. */
  async uploadMultitrack(manifest, files, discordChannelId) {
    const form = new FormData();
    form.append('manifest', JSON.stringify(manifest));
    if (discordChannelId) form.append('discord_channel_id', discordChannelId);
    for (const f of files) form.append('tracks', await openAsBlob(f.path, { type: 'audio/ogg' }), f.name);
    const resp = await this.#request('/api/jobs/multitrack', { method: 'POST', body: form });
    return resp.json();
  }

  async pending() {
    return (await this.#request('/api/discord/pending')).json();
  }

  async summary(jobId) {
    return (await this.#request(`/api/jobs/${jobId}/summary`)).text();
  }

  /** Zusatzdokument einer DnD-Session ("players"); "lore" ist nur für den DM und wird nie gepostet. */
  async document(jobId, name) {
    return (await this.#request(`/api/jobs/${jobId}/documents/${name}`)).text();
  }

  async markPosted(jobId) {
    await this.#request(`/api/discord/posted/${jobId}`, { method: 'POST' });
  }

  async pushChannels(channels) {
    await this.#request('/api/discord/channels', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channels }),
    });
  }
}
