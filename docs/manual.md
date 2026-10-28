# WhisperNotes

🇬🇧 English · 🇩🇪 [Deutsch](handbuch.md)

FastAPI wrapper around [whisper.cpp](https://github.com/ggml-org/whisper.cpp) – native on macOS (Apple Silicon, Metal)
or as a Docker container on Linux with an AMD, NVIDIA or no GPU ([docker.en.md](docker.en.md)).
Original specification (German): [spezifikation.md](spezifikation.md).

- **OpenAI-compatible:** `POST /v1/audio/transcriptions` for Discord, Home Assistant and others (any API key)
- **On demand:** `whisper-server` starts with the first request (Metal) and stops after 120 s of idle time
- **Sequential:** parallel requests are queued; batch jobs give live requests priority between their chunks
- **Dashboard** (`/dashboard/`): upload long recordings → 5-minute chunks → master transcript → map-reduce summary
- **Ollama:** in the settings you can pick a fixed model from the installed models (`/api/tags`), or by default always
  use the model that is **currently loaded** (`/api/ps`)
- **Speaker detection** (optional): by default [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
  (pyannote segmentation 3.0 + CAM++, CPU, in parallel to Whisper), alternatively
  [pyannote.audio](https://github.com/pyannote/pyannote-audio) community-1 (`DIARIZATION_ENGINE=pyannote`,
  needs `HF_TOKEN`). Detected voices are assigned to names in the dashboard by listening to samples;
  `tools/diarize_benchmark.py` compares engines and models on a real recording
- **D&D tab:** campaigns with a group (players/characters/DM) and a glossary; sessions are transcribed with speakers
  and, once the voices are assigned, summarised as a session recap (story, NPCs & places, fights, loot, open plot
  threads, quotes). The recap of the previous session is used as context.

## Installation on a Mac

```bash
git clone https://github.com/Poldion/WhisperNotes.git ~/WhisperNotes && cd ~/WhisperNotes
bash deploy/setup_mac.sh
```

The script installs `cmake ffmpeg uv node` via Homebrew, builds `whisper-server` with Metal, downloads
`ggml-large-v3-turbo-q5_0.bin`, creates `backend/.env`, runs the tests, builds the dashboard and sets up the
LaunchAgent `com.whispernotes` (autostart, logs in `~/Library/Logs/whispernotes/`).

**Update:** `git pull && bash deploy/setup_mac.sh`

Restart the service:

```bash
launchctl kickstart -k gui/$(id -u)/com.whispernotes
```

## Connecting clients

| Client | Setting |
|---|---|
| Home Assistant | e.g. the HACS integration “OpenAI Whisper Speech-to-Text API”: URL `http://<host>:8000/v1`, model `whisper-1`, API key = `API_KEY` (anything if access protection is off) |
| Your own scripts | `openai` SDK with `base_url="http://<host>:8000/v1"`, `api_key="<API_KEY or anything>"` |

For short voice commands a separate, fast model for the API is worth it: Settings → Transcription →
“Model for the /v1 API” (or `API_WHISPER_MODEL`).

Optional headers per request:

| Header | Effect |
|---|---|
| `X-Speaker-Name`, `X-Recorded-At`, `X-Session-Id`, `X-Source` | stored together with the text in `<data folder>/logbook/YYYY-MM-DD.jsonl` |
| `X-Postprocess: true` | additionally post-process the text with Ollama → `<data folder>/postprocessed/` |

Results of dashboard jobs are stored in `<data folder>/jobs/<id>/`.

## Data folder

Recordings, transcripts, campaigns, voice profiles and the settings changed in the dashboard (`settings.json`) live in
the data folder `DATA_DIR`. Default:

| System | Location |
|---|---|
| Docker | `/data/app` in the volume (`docker/data/app`) |
| macOS | `~/Library/Application Support/WhisperNotes` |
| Linux | `~/.local/share/whispernotes` (or `$XDG_DATA_HOME`) |
| Windows | `%LOCALAPPDATA%\WhisperNotes` |

Older installations had it in `backend/data`. If that folder exists, it is still used.

## Access

Without further settings WhisperNotes is open. That is meant for a home network. For running it behind a reverse proxy,
a VPN or on the internet there are two settings, in the dashboard under **Settings → Access** or via the environment:

| Variable | Effect |
|---|---|
| `API_KEY` | `/v1/*` and `/api/*` require `Authorization: Bearer <API_KEY>` – Home Assistant (API key), Discord bot (`WHISPERNOTES_API_KEY`), scripts |
| `DASHBOARD_PASSWORD` | sign-in to the dashboard; empty = sign in with the API key |

The sign-in is a signed cookie (30 days). If the password or key changes, all sign-ins become invalid. `/health` stays
open but without sign-in only reveals the language and whether sign-in is required. Links from BasaltNotes lead to the
sign-in page first and then to the document. On the internet, put HTTPS in front (reverse proxy).

## Language and templates

`LANGUAGE` (`de` or `en`, Settings → General) applies to the dashboard, status messages and summaries. What is spoken
in the recordings is set by `WHISPER_LANGUAGE`. With `en` the D&D glossary uses the English rules terms.

The document templates (summary, session recap, recap per player character, world & lore) can be adjusted under
**Settings → Templates**: sections, length, tone. Empty means the built-in template of the language applies
(`backend/app/prompts.py`). WhisperNotes always appends its rules: invent nothing, resolve time references, use
character names instead of player names. In the session recap the heading “Previously” (German: „Was bisher geschah“)
should stay – its section is carried into the next session as a look back.

## API overview

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/audio/transcriptions` | Transcription (`file`, optional `language`, `prompt`, `response_format=json\|text\|verbose_json`) |
| GET | `/health` | Wrapper, Whisper and Ollama status incl. `ollama_active_model` (without sign-in only `language`, `auth_required`) |
| POST | `/api/auth/login` · `/api/auth/logout` | Dashboard sign-in (`{"password": …}`), sets or clears the cookie |
| POST | `/api/jobs` | Upload a file for batch processing |
| GET | `/api/jobs/{id}/events` | Progress as server-sent events |
| GET | `/api/jobs/{id}/transcript?format=md\|txt` | Raw transcript |
| GET | `/api/jobs/{id}/summary` | AI summary (Markdown) |
| POST | `/api/jobs/{id}/summarize` | Create the summary again (e.g. after a model was loaded) |

## Discord bot

The bot (`discord-bot/bot.mjs`) records conversations in voice channels – **every person as a separate track** – and
sends them to WhisperNotes as a normal recording. The speakers are therefore known (no speaker detection needed), the
names come from Discord. The finished summary appears in the dashboard and is also posted to the Discord channel in
which the recording was started. D&D recaps go to the channel selected in the campaign.

The slash commands are currently German:

| Command | Effect |
|---|---|
| `/aufnahme start [titel]` | start recording in your own voice channel |
| `/aufnahme stop` | stop and process it (automatically when the channel is empty or after 6 h) |
| `/aufnahme status` | is a recording running? |

Setup:

1. [Discord Developer Portal](https://discord.com/developers/applications) → *New Application* → *Bot* →
   *Reset Token* (copy the token). Invite the bot with the scopes `bot` and `applications.commands` and the permissions
   *View Channels*, *Send Messages*, *Embed Links*, *Attach Files* and *Connect* (`permissions=1099776`).
2. Docker: create `docker/discord.env` and start with `--profile discord` (see [docker.en.md](docker.en.md)).
   On a Mac (Node ≥ 22.12): create `discord-bot/.env` from `.env.example`, enter `DISCORD_TOKEN` (and
   `WHISPERNOTES_API_KEY` if access protection is on), then run `bash deploy/setup_mac.sh` – the bot then runs as the
   LaunchAgent `com.whispernotes.discord` (log: `~/Library/Logs/whispernotes/discord-bot.log`).

Recording works with Discord's end-to-end encryption (DAVE, mandatory since March 2026) using `@discordjs/voice`;
`npm run probe` (`/testaufnahme`) checks this in isolation if there are problems.
Only record conversations with the consent of everyone present – the bot announces every recording in the channel.

## Development on Windows

Without a Mac, `whisper-server` is replaced by `backend/tools/mock_whisper_server.py`:

```bash
pip install uv && cd backend && uv sync
```

```bash
cd backend && uv run pytest -q
```

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000 --env-file .env.dev
```

Frontend with hot reload (proxy to port 8000): `cd frontend && npm install && npm run dev`, then
`http://localhost:5173/dashboard/`. Dashboard jobs need `ffmpeg`/`ffprobe` in the PATH locally.

## Important settings (`backend/.env`)

| Variable | Default | Meaning |
|---|---|---|
| `IDLE_TIMEOUT` | 120 | seconds of idle time until `whisper-server` is stopped |
| `INFERENCE_TIMEOUT` | 180 | max. seconds per request/chunk, then the process is killed and HTTP 500 returned |
| `CHUNK_SECONDS` / `CHUNK_OVERLAP_SECONDS` | 300 / 10 | slicing of long files |
| `AUDIO_STORAGE_MAX_GB` | 10 | storage limit for audio uploads; the oldest audio files are deleted, transcripts stay. `0` = unlimited |
| `OLLAMA_MODEL` | – | fixed model for summaries; empty = automatically the model that is currently loaded |
| `OLLAMA_FALLBACK_MODEL` | – | only used with “automatic” when no model is loaded in Ollama |
| `LOGBOOK_MODE` | metadata | `off`, `metadata` (only requests with metadata headers) or `all` |
| `LANGUAGE` | de | language of dashboard, messages and summaries (`de`, `en`) |
| `API_KEY` / `DASHBOARD_PASSWORD` | – | access protection, see [Access](#access) |
| `DATA_DIR` | per system | see [Data folder](#data-folder) |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama or a proxy in front of it |

Full list: [backend/.env.example](../backend/.env.example), [backend/app/config.py](../backend/app/config.py).
