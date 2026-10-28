# WhisperNotes

FastAPI-Wrapper um [whisper.cpp](https://github.com/ggml-org/whisper.cpp) – nativ auf macOS (Apple Silicon, Metal)
oder als Docker-Container unter Linux mit AMD-, NVIDIA- oder ohne GPU ([docker.md](docker.md)).
Ursprüngliche Spezifikation: [spezifikation.md](spezifikation.md).

- **OpenAI-kompatibel:** `POST /v1/audio/transcriptions` für Discord, Home Assistant & Co. (beliebiger API-Key)
- **On-Demand:** `whisper-server` startet beim ersten Request (Metal) und wird nach 120 s Leerlauf beendet
- **Sequenziell:** parallele Requests werden eingereiht; Batch-Jobs geben zwischen ihren Chunks Vorrang an Live-Requests
- **Dashboard** (`/dashboard/`): Upload langer Aufnahmen → 5-Minuten-Chunks → Master-Transkript → Map-Reduce-Zusammenfassung
- **Ollama:** in den Einstellungen kann ein festes Modell aus den installierten Modellen (`/api/tags`) gewählt werden, oder standardmäßig immer das **aktuell geladene** Modell (`/api/ps`) genutzt werden
- **Sprechererkennung** (optional): standardmäßig [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
  (pyannote-Segmentierung 3.0 + CAM++, CPU, parallel zu Whisper), alternativ
  [pyannote.audio](https://github.com/pyannote/pyannote-audio) community-1 (`DIARIZATION_ENGINE=pyannote`,
  braucht `HF_TOKEN`). Erkannte Stimmen werden im Dashboard per Hörprobe Namen zugeordnet;
  `tools/diarize_benchmark.py` vergleicht Engines und Modelle an einer echten Aufnahme
- **DnD-Tab:** Kampagnen mit Runde (Spieler/Charaktere/DM) und Glossar; Sessions werden mit Sprechern
  transkribiert und nach der Zuordnung als Session-Recap zusammengefasst (Handlung, NPCs & Orte, Kämpfe, Beute,
  offene Handlungsstränge, Zitate). Der Rückblick der vorherigen Session fließt als Kontext ein.

## Installation auf dem Mac

```bash
git clone <repo-url> ~/WhisperNotes && cd ~/WhisperNotes
bash deploy/setup_mac.sh
```

Das Skript installiert per Homebrew `cmake ffmpeg uv node`, baut `whisper-server` mit Metal, lädt
`ggml-large-v3-turbo-q5_0.bin`, erzeugt `backend/.env`, führt die Tests aus, baut das Dashboard und
richtet den LaunchAgent `com.whispernotes` ein (Autostart, Logs unter `~/Library/Logs/whispernotes/`).

**Update:** `git pull && bash deploy/setup_mac.sh`

Dienst steuern:

```bash
launchctl kickstart -k gui/$(id -u)/com.whispernotes
```

## Clients anbinden

| Client | Einstellung |
|---|---|
| Home Assistant | z. B. HACS-Integration „OpenAI Whisper Speech-to-Text API“: URL `http://<host>:8000/v1`, Modell `whisper-1`, API-Key = `API_KEY` (ohne Zugangsschutz beliebig) |
| Eigene Skripte | `openai`-SDK mit `base_url="http://<host>:8000/v1"`, `api_key="<API_KEY oder beliebig>"` |

Für kurze Sprachbefehle lohnt ein eigenes, schnelles Modell für die API: Einstellungen → Transkription →
„Modell für die /v1-API“ (bzw. `API_WHISPER_MODEL`).

Optionale Header pro Request:

| Header | Wirkung |
|---|---|
| `X-Speaker-Name`, `X-Recorded-At`, `X-Session-Id`, `X-Source` | werden mit dem Text in `<Datenordner>/logbook/JJJJ-MM-TT.jsonl` gespeichert |
| `X-Postprocess: true` | Text zusätzlich über Ollama nachbearbeiten → `<Datenordner>/postprocessed/` |

Ergebnisse der Dashboard-Jobs liegen unter `<Datenordner>/jobs/<id>/`.

## Datenordner

Aufnahmen, Transkripte, Kampagnen, Stimmprofile und die im Dashboard geänderten Einstellungen (`settings.json`)
liegen im Datenordner `DATA_DIR`. Standard:

| System | Ort |
|---|---|
| Docker | `/data/app` im Volume (`docker/data/app`) |
| macOS | `~/Library/Application Support/WhisperNotes` |
| Linux | `~/.local/share/whispernotes` (bzw. `$XDG_DATA_HOME`) |
| Windows | `%LOCALAPPDATA%\WhisperNotes` |

Ältere Installationen hatten ihn in `backend/data`. Existiert dieser Ordner, wird er weiter genutzt.

## Zugang

Ohne weitere Einstellung ist WhisperNotes offen. Das ist fürs Heimnetz gedacht. Für den Betrieb dahinter
(Reverse-Proxy, VPN, Internet) gibt es zwei Einstellungen, im Dashboard unter **Einstellungen → Zugang** oder per
Umgebung:

| Variable | Wirkung |
|---|---|
| `API_KEY` | `/v1/*` und `/api/*` verlangen `Authorization: Bearer <API_KEY>` – Home Assistant (API-Key), Discord-Bot (`WHISPERNOTES_API_KEY`), Skripte |
| `DASHBOARD_PASSWORD` | Anmeldung im Dashboard; leer = Anmeldung mit dem API-Schlüssel |

Die Anmeldung ist ein signiertes Cookie (30 Tage). Ändert sich Passwort oder Schlüssel, sind alle Anmeldungen
ungültig. `/health` bleibt offen, verrät ohne Anmeldung aber nur Sprache und Anmeldepflicht. Links aus BasaltNotes
führen ohne Anmeldung zur Anmeldeseite und danach zum Dokument. Für den Betrieb im Internet gehört HTTPS davor
(Reverse-Proxy).

## Sprache und Vorlagen

`LANGUAGE` (`de` oder `en`, Einstellungen → Allgemein) gilt für Dashboard, Statusmeldungen und Zusammenfassungen.
Was in den Aufnahmen gesprochen wird, legt `WHISPER_LANGUAGE` fest. Bei `en` nutzt das D&D-Glossar die englischen
Regelbegriffe.

Die Vorlagen der Dokumente (Zusammenfassung, Session-Recap, Recap je Spielercharakter, Welt & Lore) lassen sich unter
**Einstellungen → Vorlagen** anpassen: Abschnitte, Länge, Ton. Leer heißt, dass die eingebaute Vorlage der Sprache
gilt (`backend/app/prompts.py`). Die Regeln hängt WhisperNotes immer an: nichts erfinden, Zeitangaben auflösen,
Charakternamen statt Spielernamen. Beim Session-Recap sollte die Überschrift „Was bisher geschah“ bzw. „Previously“
bleiben. Ihr Abschnitt fließt als Rückblick in die nächste Session ein.

## API-Überblick

| Methode | Pfad | Zweck |
|---|---|---|
| POST | `/v1/audio/transcriptions` | Transkription (`file`, optional `language`, `prompt`, `response_format=json\|text\|verbose_json`) |
| GET | `/health` | Wrapper-, Whisper- und Ollama-Status inkl. `ollama_active_model` (ohne Anmeldung nur `language`, `auth_required`) |
| POST | `/api/auth/login` · `/api/auth/logout` | Dashboard-Anmeldung (`{"password": …}`), setzt bzw. löscht das Cookie |
| POST | `/api/jobs` | Datei für das Batch-Processing hochladen |
| GET | `/api/jobs/{id}/events` | Fortschritt als Server-Sent Events |
| GET | `/api/jobs/{id}/transcript?format=md\|txt` | Rohtranskript |
| GET | `/api/jobs/{id}/summary` | KI-Zusammenfassung (Markdown) |
| POST | `/api/jobs/{id}/summarize` | Zusammenfassung erneut erzeugen (z. B. nachdem ein Modell geladen wurde) |

## Discord-Bot

Der Bot (`discord-bot/bot.mjs`) nimmt Gespräche in Voice-Channels auf – **jede Person als eigene Spur** – und
schickt sie als normale Aufnahme an WhisperNotes. Die Sprecher stehen damit fest (keine Sprechererkennung
nötig), die Namen kommen aus Discord. Die fertige Zusammenfassung erscheint im Dashboard und wird zusätzlich in
den Discord-Channel gepostet, in dem die Aufnahme gestartet wurde. DnD-Recaps landen in dem Channel, der in der
Kampagne ausgewählt ist.

| Befehl | Wirkung |
|---|---|
| `/aufnahme start [titel]` | Aufnahme im eigenen Voice-Channel starten |
| `/aufnahme stop` | beenden und verarbeiten lassen (automatisch, wenn der Channel leer ist oder nach 6 h) |
| `/aufnahme status` | läuft gerade eine Aufnahme? |

Einrichtung:

1. [Discord Developer Portal](https://discord.com/developers/applications) → *New Application* → *Bot* →
   *Reset Token* (Token kopieren). Bot mit den Scopes `bot` und `applications.commands` sowie den Rechten
   *View Channels*, *Send Messages*, *Embed Links*, *Attach Files* und *Connect* einladen
   (`permissions=1099776`).
2. Docker: `docker/discord.env` anlegen und mit `--profile discord` starten (siehe [docker.md](docker.md)).
   Auf dem Mac (Node ≥ 22.12): `discord-bot/.env` aus `.env.example` anlegen, `DISCORD_TOKEN` (und bei
   Zugangsschutz `WHISPERNOTES_API_KEY`) eintragen,
   dann `bash deploy/setup_mac.sh` – der Bot läuft danach als LaunchAgent
   `com.whispernotes.discord` (Log: `~/Library/Logs/whispernotes/discord-bot.log`).

Aufgenommen wird unter Discords Ende-zu-Ende-Verschlüsselung (DAVE, Pflicht seit März 2026) mit
`@discordjs/voice`; `npm run probe` (`/testaufnahme`) prüft das bei Problemen isoliert.
Gespräche nur mit Einverständnis aller Anwesenden aufnehmen – der Bot kündigt jede Aufnahme im Channel an.

## Entwicklung unter Windows

Ohne Mac wird `whisper-server` durch `backend/tools/mock_whisper_server.py` ersetzt:

```bash
pip install uv && cd backend && uv sync
```

```bash
cd backend && uv run pytest -q
```

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000 --env-file .env.dev
```

Frontend mit Hot-Reload (Proxy auf Port 8000): `cd frontend && npm install && npm run dev`, dann
`http://localhost:5173/dashboard/`. Für Dashboard-Jobs wird lokal `ffmpeg`/`ffprobe` im PATH benötigt.

## Wichtige Einstellungen (`backend/.env`)

| Variable | Standard | Bedeutung |
|---|---|---|
| `IDLE_TIMEOUT` | 120 | Sekunden Leerlauf bis `whisper-server` beendet wird |
| `INFERENCE_TIMEOUT` | 180 | max. Sekunden pro Request/Chunk, danach Prozess-Kill und HTTP 500 |
| `CHUNK_SECONDS` / `CHUNK_OVERLAP_SECONDS` | 300 / 10 | Slicing langer Dateien |
| `AUDIO_STORAGE_MAX_GB` | 10 | Speicherlimit für Audio-Uploads; älteste Audiodateien werden gelöscht, Transkripte bleiben. `0` = unbegrenzt |
| `OLLAMA_MODEL` | – | festes Modell für Zusammenfassungen; leer = automatisch das aktuell geladene Modell |
| `OLLAMA_FALLBACK_MODEL` | – | nur bei „automatisch“ genutzt, wenn in Ollama gerade kein Modell geladen ist |
| `LOGBOOK_MODE` | metadata | `off`, `metadata` (nur Requests mit Metadaten-Headern) oder `all` |
| `LANGUAGE` | de | Sprache von Dashboard, Meldungen und Zusammenfassungen (`de`, `en`) |
| `API_KEY` / `DASHBOARD_PASSWORD` | – | Zugangsschutz, siehe [Zugang](#zugang) |
| `DATA_DIR` | je System | siehe [Datenordner](#datenordner) |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama oder ein Proxy davor |

Vollständige Liste: [backend/.env.example](../backend/.env.example), [backend/app/config.py](../backend/app/config.py).
