# syntax=docker/dockerfile:1.7
# WhisperNotes als Container für Linux x86-64 – mit AMD-GPU (Vulkan + ROCm), NVIDIA-GPU (CUDA) oder nur CPU.
# Gebaut wird über docker/compose.yml (bzw. compose.nvidia.yml / compose.cpu.yml), Details: docs/docker.md
#
#   docker compose -f docker/compose.yml build
#
# Build-Argumente:
#   GPU=vulkan|cuda|cpu   whisper.cpp-Backend. Vulkan läuft auf AMD (RADV/Mesa) und Intel ohne ROCm im Container.
#   PYANNOTE=1|0          pyannote.audio (PyTorch) für die bessere Sprechererkennung mitinstallieren
#   TORCH_INDEX=…         PyTorch-Quelle: AMD-Builds mit ROCm für gfx1151 (Standard),
#                         https://download.pytorch.org/whl/cu128 (NVIDIA) oder https://download.pytorch.org/whl/cpu
#   BUILD_IMAGE / RUNTIME_IMAGE   Basis für Build und Laufzeit (CUDA braucht die nvidia/cuda-Images)
#   CUDA_ARCHS=…          NVIDIA-Architekturen, für die whisper.cpp übersetzt wird (z. B. 86 = RTX 30xx, 89 = RTX 40xx)
#   WHISPER_CPP_REF=…     whisper.cpp-Version (Tag)
#   NATIVE=ON|OFF         für die CPU des Build-Rechners optimieren (ON = schneller, Image nur dort lauffähig;
#                         für veröffentlichte Images OFF)

ARG WHISPER_CPP_REF=v1.9.5
ARG GPU=vulkan
ARG NATIVE=ON
ARG PYANNOTE=1
ARG TORCH_INDEX=https://repo.amd.com/rocm/whl/gfx1151/
ARG BUILD_IMAGE=debian:trixie-slim
ARG RUNTIME_IMAGE=debian:trixie-slim
ARG CUDA_ARCHS="75;80;86;89;90;120"

# ---------------------------------------------------------------- Dashboard
FROM node:22-bookworm-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- whisper.cpp (whisper-server)
FROM ${BUILD_IMAGE} AS whisper
ARG WHISPER_CPP_REF
ARG GPU
ARG NATIVE
ARG CUDA_ARCHS
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends build-essential cmake git ca-certificates \
 && if [ "$GPU" = "vulkan" ]; then apt-get install -y --no-install-recommends libvulkan-dev glslc spirv-headers; fi \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "$WHISPER_CPP_REF" https://github.com/ggml-org/whisper.cpp /src/whisper.cpp
WORKDIR /src/whisper.cpp
# CUDA: Beim Bauen gibt es keine GPU – gegen die Stub-Bibliothek linken, zur Laufzeit liefert der Treiber libcuda.
RUN set -e; \
    extra=""; \
    [ "$GPU" = "vulkan" ] && extra="-DGGML_VULKAN=ON"; \
    [ "$GPU" = "cuda" ] && extra="-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=$CUDA_ARCHS \
      -DCMAKE_EXE_LINKER_FLAGS=-L/usr/local/cuda/lib64/stubs"; \
    cmake -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DWHISPER_BUILD_TESTS=OFF \
          -DGGML_NATIVE="$NATIVE" $extra; \
    cmake --build build -j "$(nproc)" --config Release --target whisper-server; \
    install -m 755 build/bin/whisper-server /usr/local/bin/whisper-server

# ---------------------------------------------------------------- Laufzeit
FROM ${RUNTIME_IMAGE} AS runtime
LABEL org.opencontainers.image.title="WhisperNotes" \
      org.opencontainers.image.source="https://github.com/Poldion/WhisperNotes" \
      org.opencontainers.image.licenses="MIT"
ARG GPU
ARG PYANNOTE
ARG TORCH_INDEX

# ffmpeg: Audio · Mesa/RADV: Vulkan-Treiber für die Radeon (Debian trixie: Mesa 25, kann RDNA 3.5)
# libstdc++-dev (nur ROCm): MIOpen übersetzt GPU-Kernel zur Laufzeit und braucht dafür die C++-Header
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ffmpeg curl ca-certificates libgomp1 libatomic1 bzip2 \
 && if [ "$GPU" = "vulkan" ]; then apt-get install -y --no-install-recommends libvulkan1 mesa-vulkan-drivers; fi \
 && case "$TORCH_INDEX" in *rocm*) apt-get install -y --no-install-recommends libstdc++-14-dev ;; esac \
 && rm -rf /var/lib/apt/lists/*

# Python bringt uv mit (gleich auf Debian- und CUDA-Basisimages), installiert in eine venv unter /opt/venv
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_INSTALL_DIR=/opt/python VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH
RUN uv venv --python 3.12 /opt/venv

WORKDIR /app/backend
COPY backend/pyproject.toml ./
# PyTorch zuerst aus dem gewählten Index (sonst käme der große CUDA-Build von PyPI), dann der Rest.
# Download-Cache (BuildKit): PyTorch mit ROCm/CUDA ist mehrere GB groß – nicht bei jedem Build neu laden.
RUN --mount=type=cache,target=/root/.cache/uv set -e; \
    if [ "$PYANNOTE" = "1" ]; then \
      uv pip install --index-url "$TORCH_INDEX" torch torchaudio; \
      uv pip install -r pyproject.toml --extra pyannote; \
    else \
      uv pip install -r pyproject.toml; \
    fi

COPY backend/app ./app
COPY --from=frontend /src/frontend/dist /app/frontend/dist
COPY --from=whisper /usr/local/bin/whisper-server /usr/local/bin/whisper-server
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN (getent passwd 1000 >/dev/null && userdel --remove "$(getent passwd 1000 | cut -d: -f1)" || true) \
 && useradd --create-home --uid 1000 whispernotes && mkdir -p /data && chown whispernotes /data
USER whispernotes

# Alle Daten und Modelle liegen im Volume /data (Modelle lädt der Container beim ersten Start)
ENV DATA_DIR=/data/app \
    HF_HOME=/data/hf-cache \
    WHISPER_COMMAND=/usr/local/bin/whisper-server \
    WHISPER_MODELS_DIR=/data/models/whisper \
    WHISPER_MODEL=/data/models/whisper/ggml-large-v3-turbo-q5_0.bin \
    WHISPER_THREADS=8 \
    DIARIZATION_SEGMENTATION_MODEL=/data/models/sherpa-onnx-pyannote-segmentation-3-0/model.onnx \
    DIARIZATION_EMBEDDING_MODEL=/data/models/wespeaker_en_voxceleb_CAM++_LM.onnx \
    DIARIZATION_THREADS=8 \
    VAD_MODEL=/data/models/silero_vad.onnx \
    MIOPEN_USER_DB_PATH=/data/miopen \
    MIOPEN_CUSTOM_CACHE_DIR=/data/miopen/cache

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s CMD curl -fsS http://127.0.0.1:8000/health >/dev/null || exit 1
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
