#!/usr/bin/env bash
# Start des WhisperNotes-Containers: fehlende Modelle ins Volume laden, dann den Server starten.
#
#   WHISPER_MODELS="large-v3-turbo-q5_0 large-v3-q5_0"   Whisper-Modelle (Namen wie bei download-ggml-model.sh)
#   DOWNLOAD_DIARIZATION_MODELS=1                         sherpa-onnx/CAM++ (Hörproben, Stimmprofile) und Silero-VAD
set -euo pipefail

MODELS=/data/models
HF="https://huggingface.co/ggerganov/whisper.cpp/resolve/main"
SHERPA="https://github.com/k2-fsa/sherpa-onnx/releases/download"
mkdir -p "$MODELS/whisper" "${DATA_DIR:-/data/app}" "${HF_HOME:-/data/hf-cache}" "${MIOPEN_CUSTOM_CACHE_DIR:-/data/miopen/cache}"

fetch() {  # URL → Ziel, nur wenn es fehlt; erst in eine temporäre Datei (kein halbes Modell nach Abbruch)
  local url="$1" target="$2"
  [[ -s "$target" ]] && return 0
  echo "Lade $(basename "$target") …"
  curl -fL --retry 3 -o "$target.part" "$url"
  mv "$target.part" "$target"
}

for name in ${WHISPER_MODELS:-large-v3-turbo-q5_0 large-v3-q5_0}; do
  fetch "$HF/ggml-$name.bin" "$MODELS/whisper/ggml-$name.bin"
done

if [[ "${DOWNLOAD_DIARIZATION_MODELS:-1}" == "1" ]]; then
  fetch "$SHERPA/asr-models/silero_vad.onnx" "$MODELS/silero_vad.onnx"
  fetch "$SHERPA/speaker-recongition-models/wespeaker_en_voxceleb_CAM%2B%2B_LM.onnx" \
        "$MODELS/wespeaker_en_voxceleb_CAM++_LM.onnx"
  # Segmentierung für sherpa: Standard pyannote segmentation-3.0 (MIT). Wer in DIARIZATION_SEGMENTATION_MODEL
  # reverb einträgt (Rev-Lizenz, nur nicht-kommerziell), bekommt dieses Paket geladen.
  seg="${DIARIZATION_SEGMENTATION_MODEL:-$MODELS/sherpa-onnx-pyannote-segmentation-3-0/model.onnx}"
  if [[ ! -s "$seg" ]]; then
    pkg="$(basename "$(dirname "$seg")")"
    echo "Lade $pkg …"
    curl -fL --retry 3 "$SHERPA/speaker-segmentation-models/$pkg.tar.bz2" | tar -xj -C "$(dirname "$(dirname "$seg")")"
  fi
fi

exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
