# Betrieb mit Docker (Linux)

WhisperNotes läuft als Container auf jedem Linux-Rechner mit x86-64-CPU. Am schnellsten mit Grafikkarte. Es gibt drei
Varianten:

| Variante | Whisper (whisper.cpp) | Sprechererkennung (pyannote) | Compose-Dateien |
|---|---|---|---|
| **AMD** (Standard) | Vulkan (Mesa/RADV, kein ROCm nötig) | PyTorch mit ROCm | `compose.yml` |
| **NVIDIA** | CUDA | PyTorch mit CUDA | `compose.yml` + `compose.nvidia.yml` |
| **Nur CPU** | CPU | PyTorch auf der CPU | `compose.yml` + `compose.cpu.yml` |

Ollama für die Zusammenfassungen kann im selben Compose-Projekt laufen (Profil `ollama`) oder schon anders vorhanden
sein. Der Discord-Bot ist optional (Profil `discord`).

---

## 1. Voraussetzungen

- **Docker** mit Compose-Plugin. Den eigenen Benutzer in die Gruppe `docker` aufnehmen.
- **AMD:** aktueller Kernel, für Ryzen AI Max („Strix Halo“, Radeon 8060S) mindestens 6.15. Prüfen mit
  `ls -l /dev/dri /dev/kfd` und `getent group video render`. Die Gruppen-IDs gehören nach `docker/.env`.
  Ein Test auf dem Host: `vulkaninfo --summary` sollte die GPU mit „RADV“ zeigen.
- **NVIDIA:** Treiber und [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/).
  `docker run --rm --gpus all ubuntu nvidia-smi` muss die Karte zeigen.
- **Speicher:** Whisper large-v3-turbo braucht ~2 GB, pyannote ~1 GB, das Sprachmodell je nach Größe 5–70 GB.
  Für die Modelle kommen ~3 GB im Datenordner dazu.

## 2. Installation

```bash
git clone https://github.com/Poldion/WhisperNotes.git && cd WhisperNotes
cp docker/.env.example docker/.env                           # Gruppen-IDs (AMD), Port, Datenordner
cp docker/whispernotes.env.example docker/whispernotes.env   # Sprache, Ollama, HF_TOKEN …
cp docker/discord.env.example docker/discord.env             # nur mit Discord-Bot

# AMD
docker compose -f docker/compose.yml up -d --build
# NVIDIA
docker compose -f docker/compose.yml -f docker/compose.nvidia.yml up -d --build
# nur CPU
docker compose -f docker/compose.yml -f docker/compose.cpu.yml up -d --build

# Mit Ollama und Discord-Bot zusätzlich: --profile ollama --profile discord
docker compose -f docker/compose.yml logs -f whispernotes   # der erste Start lädt ~2,5 GB Modelle
```

Danach `http://<rechner>:8000/dashboard/` öffnen. Daten und Modelle liegen in `docker/data/` (Volume `/data`).
Das Verzeichnis gehört dem Benutzer mit der UID 1000. Lege es vor dem ersten Start selbst an (`mkdir docker/data`),
sonst legt Docker es als root an.

**Fertiges Image statt selbst bauen:** in `docker/.env` z. B. `WN_IMAGE=poldion/whispernotes:latest` setzen (bzw.
`:nvidia` oder `:cpu`) und ohne `--build` starten. Selbst gebaute Images sind für die CPU des Rechners optimiert
(`NATIVE=ON`) und deshalb etwas schneller.

**Ollama-Modell laden** (mit Profil `ollama`): `docker compose -f docker/compose.yml exec ollama ollama pull gemma3:12b`.
WhisperNotes nimmt das gerade geladene Modell oder das unter „Einstellungen → Zusammenfassung“ gewählte.

**Sprechererkennung mit pyannote:** braucht ein Hugging-Face-Token. Vorher müssen die Nutzungsbedingungen von
[pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
akzeptiert sein. Das Token kommt als `HF_TOKEN` in `whispernotes.env` oder in die Einstellungen. Ohne Token
`DIARIZATION_ENGINE=sherpa` setzen. sherpa-onnx rechnet auf der CPU und braucht kein Konto.

## 3. Prüfen, ob die GPU genutzt wird

- **Whisper:** nach der ersten Transkription
  `grep -iE "vulkan|cuda" docker/data/app/logs/whisper-server.log`. Dort sollte die Grafikkarte auftauchen.
  Steht nichts da, rechnet Whisper auf der CPU. Das funktioniert, ist aber deutlich langsamer. Prüfe in diesem Fall
  die Geräte (`/dev/dri`) bzw. das NVIDIA-Toolkit.
- **pyannote:**
  `docker compose -f docker/compose.yml exec whispernotes python -c "import torch; print(torch.cuda.is_available())"`.
  ROCm meldet sich hier ebenfalls als `cuda`. `PYANNOTE_DEVICE=auto` nimmt die GPU automatisch.

## 4. Leistung (gemessen auf AMD Ryzen AI Max+ 395, 128 GB)

Aufnahme: 28:48 min D&D-Session vom Konferenzmikrofon, vier Personen.

| Schritt | CPU | GPU |
|---|---|---|
| Sprechererkennung pyannote community-1 | 594 s | 59 s (ROCm) |
| 5 Dokumente (Recap, 3 Spieler-Recaps, Lore) mit gemma4:26b | – | 55 s |

Ohne GPU ist bei langen Sessions die Sprechererkennung der Engpass. Eigene Messungen gern per Pull Request ergänzen.

## 5. Build-Optionen

In `docker/.env` (siehe Kommentare in `docker/Dockerfile`):

| Variable | Standard | Bedeutung |
|---|---|---|
| `WN_PYANNOTE` | `1` | `0` = ohne PyTorch/pyannote (Image ~2 GB statt ~10 GB, nur sherpa-onnx) |
| `WN_TORCH_INDEX` | ROCm für gfx1151 | Andere AMD-GPU: passenden ROCm-Index von pytorch.org eintragen |
| `WN_CUDA_ARCHS` | `75;80;86;89;90;120` | NVIDIA: nur die eigene Generation spart Bauzeit (`86` RTX 30xx, `89` RTX 40xx) |
| `WN_PORT` / `WN_DATA` | `8000` / `./data` | Port und Datenordner |

**AMD-GPUs außer gfx1151:** Der Standard-Index enthält PyTorch-Builds nur für Ryzen AI Max. Für andere Radeon-Karten in
`WN_TORCH_INDEX` z. B. `https://download.pytorch.org/whl/rocm6.4` eintragen. Prüfe vorher, ob die eigene GPU darin
unterstützt wird. Whisper über Vulkan läuft unabhängig davon.

**Ryzen AI Max – GPU-Speicher:** Die iGPU teilt sich den RAM. Damit Ollama mehr als die Hälfte nutzen darf, hilft ein
größeres GTT-Limit per Kernel-Parameter, z. B. für ~110 GB bei 128 GB RAM:
`amdgpu.gttsize=112640 ttm.pages_limit=28835840 ttm.page_pool_size=28835840`. Die Werte je nach Gerät prüfen.

## 6. Bekannte Grenzen

- Die NPU der Ryzen-AI-Prozessoren nutzt keiner der Bausteine.
- ROCm für gfx1151 ist noch jung. Wenn das Ollama-Image die GPU nicht erkennt, hilft
  `HSA_OVERRIDE_GFX_VERSION=11.5.1` in `compose.yml`.
- Der Discord-Bot nutzt native Module für Discords Ende-zu-Ende-Verschlüsselung (DAVE). Getestet ist er auf Linux
  x86-64 und macOS arm64.

---

## Anhang: Umzug von einer macOS-Installation

Eine bestehende Installation ohne Docker (z. B. auf einem Mac mini mit `deploy/setup_mac.sh`) hat ihre Daten in
`~/WhisperNotes/backend/data/`. Dazu gehören Jobs, Kampagnen, Stimmprofile und Einstellungen.

```bash
# auf dem neuen Rechner, WhisperNotes vorher stoppen:
docker compose -f docker/compose.yml stop whispernotes
rsync -a --info=progress2 <benutzer>@<mac>:WhisperNotes/backend/data/ docker/data/app/
docker compose -f docker/compose.yml start whispernotes
```

Danach unter **Einstellungen** prüfen:

- **BasaltNotes → Adresse:** Auf dem Mac steht dort oft der SSH-Tunnel `http://127.0.0.1:4401`. Unter Linux gehört
  hier die echte Adresse hin, einen Tunnel braucht es nicht.
- **Adresse von WhisperNotes** und **Ollama-Adresse** an den neuen Rechner anpassen.

Stimmprofile bleiben gültig (gleiches CAM++-Modell). Die Whisper-Modelle der Jobs heißen gleich. Die mitkopierten
Audiodateien lassen sich auf der schnelleren Hardware neu transkribieren. Für den Discord-Bot den `DISCORD_TOKEN`
nach `docker/discord.env` übernehmen und den Bot auf dem Mac stoppen, sonst antworten zwei Bots:

```bash
launchctl bootout gui/$(id -u)/com.whispernotes.discord
sudo launchctl bootout system/com.whispernotes            # WhisperNotes selbst (LaunchDaemon)
launchctl bootout gui/$(id -u)/com.whispernotes.basalt-tunnel
```
