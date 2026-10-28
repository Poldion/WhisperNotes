#!/usr/bin/env bash
# WhisperNotes – Einrichtung/Update auf dem M1 Mac Mini. Idempotent: nach jedem `git pull` erneut ausführen.
#
#   ./deploy/setup_mac.sh
#
# Optionale Umgebungsvariablen:
#   WHISPER_DIR=~/whisper.cpp              Ort des whisper.cpp-Checkouts
#   WHISPER_MODEL_NAME=large-v3-turbo-q5_0 Standardmodell für download-ggml-model.sh
#   WHISPER_EXTRA_MODELS="large-v3-q5_0"   weitere Modelle zur Auswahl im Dashboard ("" = keine)
#   INSTALL_LAUNCHD=1                      LaunchAgent (Autostart) installieren/neu laden
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WHISPER_DIR="${WHISPER_DIR:-$HOME/whisper.cpp}"
MODEL_NAME="${WHISPER_MODEL_NAME:-large-v3-turbo-q5_0}"
EXTRA_MODELS="${WHISPER_EXTRA_MODELS-large-v3-q5_0}"
INSTALL_LAUNCHD="${INSTALL_LAUNCHD:-1}"
LABEL="com.whispernotes"

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

[[ "$(uname -s)" == "Darwin" ]] || { echo "Dieses Skript ist für macOS gedacht."; exit 1; }
command -v brew >/dev/null || { echo "Homebrew fehlt: https://brew.sh"; exit 1; }
BREW_PREFIX="$(brew --prefix)"

step "Homebrew-Pakete"
for pkg in cmake ffmpeg uv node git; do
  brew list --formula "$pkg" >/dev/null 2>&1 || brew install "$pkg"
done

step "whisper.cpp (Metal) bauen"
if [[ ! -d "$WHISPER_DIR/.git" ]]; then
  git clone https://github.com/ggml-org/whisper.cpp "$WHISPER_DIR"
else
  git -C "$WHISPER_DIR" pull --ff-only || echo "Hinweis: whisper.cpp konnte nicht aktualisiert werden, baue vorhandenen Stand."
fi
cmake -S "$WHISPER_DIR" -B "$WHISPER_DIR/build" -DCMAKE_BUILD_TYPE=Release -DGGML_METAL=ON
cmake --build "$WHISPER_DIR/build" -j --config Release --target whisper-server

MODEL_FILE="$WHISPER_DIR/models/ggml-$MODEL_NAME.bin"
# Alle Modelle im Ordner erscheinen im Dashboard zur Auswahl (Standard = WHISPER_MODEL aus backend/.env)
for name in $MODEL_NAME $EXTRA_MODELS; do
  if [[ ! -f "$WHISPER_DIR/models/ggml-$name.bin" ]]; then
    step "Whisper-Modell $name herunterladen"
    sh "$WHISPER_DIR/models/download-ggml-model.sh" "$name"
  fi
done

step "Modelle für Sprachaktivitätserkennung und Sprechererkennung"
MODELS_DIR="$REPO_DIR/backend/models"
SHERPA="https://github.com/k2-fsa/sherpa-onnx/releases/download"
mkdir -p "$MODELS_DIR"
if [[ ! -f "$MODELS_DIR/silero_vad.onnx" ]]; then  # VAD vor Whisper (backend/app/vad.py)
  curl -fL -o "$MODELS_DIR/silero_vad.onnx" "$SHERPA/asr-models/silero_vad.onnx"
fi
if [[ ! -f "$MODELS_DIR/sherpa-onnx-pyannote-segmentation-3-0/model.onnx" ]]; then
  curl -fL "$SHERPA/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2" | tar -xj -C "$MODELS_DIR"
fi
if [[ ! -f "$MODELS_DIR/wespeaker_en_voxceleb_resnet34_LM.onnx" ]]; then
  curl -fL -o "$MODELS_DIR/wespeaker_en_voxceleb_resnet34_LM.onnx"     "$SHERPA/speaker-recongition-models/wespeaker_en_voxceleb_resnet34_LM.onnx"
fi
if [[ ! -f "$MODELS_DIR/0-four-speakers-zh.wav" ]]; then  # Testaudio für den Diarisierungs-Test
  curl -fL -o "$MODELS_DIR/0-four-speakers-zh.wav" "$SHERPA/speaker-segmentation-models/0-four-speakers-zh.wav"
fi
# Nur auf Wunsch (WITH_REVERB=1 bash deploy/setup_mac.sh): reverb für tools/diarize_benchmark.py –
# Rev-Lizenz, nur private/nicht-kommerzielle Nutzung
if [[ "${WITH_REVERB:-0}" == "1" && ! -f "$MODELS_DIR/sherpa-onnx-reverb-diarization-v1/model.onnx" ]]; then
  curl -fL "$SHERPA/speaker-segmentation-models/sherpa-onnx-reverb-diarization-v1.tar.bz2" | tar -xj -C "$MODELS_DIR"
fi
for model in "wespeaker_en_voxceleb_CAM++_LM.onnx" "3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx"; do
  if [[ ! -f "$MODELS_DIR/$model" ]]; then
    curl -fL -o "$MODELS_DIR/$model" "$SHERPA/speaker-recongition-models/${model//+/%2B}"
  fi
done

step "Backend (uv sync)"
cd "$REPO_DIR/backend"
if [[ ! -f .env ]]; then
  sed -e "s|^WHISPER_COMMAND=.*|WHISPER_COMMAND=$WHISPER_DIR/build/bin/whisper-server|" \
      -e "s|^WHISPER_MODEL=.*|WHISPER_MODEL=$MODEL_FILE|" \
      -e "s|^FFMPEG_BINARY=.*|FFMPEG_BINARY=$BREW_PREFIX/bin/ffmpeg|" \
      -e "s|^FFPROBE_BINARY=.*|FFPROBE_BINARY=$BREW_PREFIX/bin/ffprobe|" \
      .env.example > .env
  echo "backend/.env aus .env.example erzeugt – bei Bedarf anpassen."
fi
# pyannote (PyTorch, ~1–2 GB) nur installieren, wenn ein HuggingFace-Token eingetragen ist
if grep -qE '^HF_TOKEN=.+' .env; then
  echo "HF_TOKEN gefunden – installiere die pyannote-Erweiterung"
  uv sync --extra pyannote
else
  uv sync
fi

step "Tests"
# --no-sync: ein normales `uv run` würde die optionale pyannote-Erweiterung wieder entfernen
uv run --no-sync pytest -q

step "Frontend bauen"
cd "$REPO_DIR/frontend"
npm ci --no-fund --no-audit || npm install --no-fund --no-audit
npm run build

if ! curl -fsS "$(grep -E "^OLLAMA_URL=" "$REPO_DIR/backend/.env" | cut -d= -f2-)/api/version" >/dev/null 2>&1; then
  echo -e "\n\033[1;33mHinweis:\033[0m Ollama ist nicht erreichbar. Zusammenfassungen funktionieren erst, wenn Ollama läuft"
  echo "und ein Modell geladen ist (z. B. \`ollama run qwen2.5:7b\`)."
fi

# LaunchAgent aus deploy/<label>.plist installieren und (neu) starten.
install_agent() {
  local label="$1"
  local plist="$HOME/Library/LaunchAgents/$label.plist"
  local service="gui/$(id -u)/$label"
  mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs/whispernotes"
  sed -e "s|__REPO__|$REPO_DIR|g" -e "s|__UV__|$(command -v uv)|g" -e "s|__NODE__|$(command -v node)|g" \
      -e "s|__HOME__|$HOME|g" -e "s|__BREW__|$BREW_PREFIX|g" \
      "$REPO_DIR/deploy/$label.plist" > "$plist"
  if launchctl print "$service" >/dev/null 2>&1; then
    launchctl bootout "$service" 2>/dev/null || true
    # bootout arbeitet asynchron – warten, bis der alte Dienst wirklich weg ist (sonst "Bootstrap failed: 5")
    for _ in $(seq 1 40); do
      launchctl print "$service" >/dev/null 2>&1 || break
      sleep 0.5
    done
  fi
  if ! launchctl bootstrap "gui/$(id -u)" "$plist"; then
    echo "bootstrap fehlgeschlagen – versuche Neustart des geladenen Dienstes"
    launchctl kickstart -k "$service"
  fi
}

if [[ -f "/Library/LaunchDaemons/$LABEL.plist" ]]; then
  # Als LaunchDaemon eingerichtet (deploy/install_daemon.sh) → keinen LaunchAgent anlegen, nur neu starten
  step "WhisperNotes neu starten (LaunchDaemon)"
  bash "$REPO_DIR/deploy/restart.sh" || echo "Wrapper antwortet nicht – siehe ~/Library/Logs/whispernotes/wrapper.log"
elif [[ "$INSTALL_LAUNCHD" == "1" ]]; then
  step "LaunchAgent $LABEL"
  install_agent "$LABEL"
  for _ in $(seq 1 20); do  # bis zu 10 s auf den Wrapper warten
    curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && break
    sleep 0.5
  done
  curl -fsS http://127.0.0.1:8000/health && echo || echo "Wrapper antwortet nicht – siehe ~/Library/Logs/whispernotes/wrapper.log"
fi

BOT_DIR="$REPO_DIR/discord-bot"
if [[ -f "$BOT_DIR/.env" ]] && grep -qE '^DISCORD_TOKEN=.+' "$BOT_DIR/.env"; then
  step "Discord-Bot"
  cd "$BOT_DIR"
  npm ci --no-fund --no-audit || npm install --no-fund --no-audit
  npm test
  if [[ "$INSTALL_LAUNCHD" == "1" ]]; then
    install_agent "$LABEL.discord"
    echo "Bot läuft als LaunchAgent $LABEL.discord – Log: ~/Library/Logs/whispernotes/discord-bot.log"
  fi
else
  echo -e "\nDiscord-Bot nicht eingerichtet (discord-bot/.env mit DISCORD_TOKEN fehlt) – siehe README."
fi

step "Fertig"
echo "Dashboard: http://$(scutil --get LocalHostName 2>/dev/null || hostname).local:8000/dashboard/"
echo "OpenAI-kompatible API: http://<mac-mini>:8000/v1/audio/transcriptions"
