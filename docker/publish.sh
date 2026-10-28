#!/usr/bin/env bash
# Fertige Images bauen und auf eine Registry schieben (Standard: Docker Hub, poldion/whispernotes).
#
#   docker login                                  # einmalig, mit eigenem Konto
#   bash docker/publish.sh 0.2.0                  # alle Varianten
#   bash docker/publish.sh 0.2.0 cpu              # nur eine: amd | nvidia | cpu
#   IMAGE=ghcr.io/me/whispernotes bash docker/publish.sh 0.2.0
#
# Tags: <version> und latest (AMD: Vulkan + ROCm), <version>-nvidia und nvidia, <version>-cpu und cpu.
# Gebaut wird mit NATIVE=OFF, damit das Image auf jeder x86-64-CPU läuft (lokale Builds nutzen NATIVE=ON).
set -euo pipefail

VERSION="${1:?Version angeben, z. B. 0.2.0}"
ONLY="${2:-all}"
IMAGE="${IMAGE:-poldion/whispernotes}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

publish() {  # Variante, Versions-Tag, Alias-Tag, Build-Argumente …
  local variant="$1" tag="$2" alias="$3"; shift 3
  [[ "$ONLY" == all || "$ONLY" == "$variant" ]] || return 0
  echo "== $variant → $IMAGE:$tag, $IMAGE:$alias"
  docker build -f "$ROOT/docker/Dockerfile" --build-arg NATIVE=OFF "$@" -t "$IMAGE:$tag" -t "$IMAGE:$alias" "$ROOT"
  docker push "$IMAGE:$tag"
  docker push "$IMAGE:$alias"
}

publish amd "$VERSION" latest
publish nvidia "$VERSION-nvidia" nvidia \
  --build-arg GPU=cuda --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu128 \
  --build-arg BUILD_IMAGE=nvidia/cuda:12.8.1-devel-ubuntu24.04 \
  --build-arg RUNTIME_IMAGE=nvidia/cuda:12.8.1-runtime-ubuntu24.04
publish cpu "$VERSION-cpu" cpu \
  --build-arg GPU=cpu --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cpu
