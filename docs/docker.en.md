# Running with Docker (Linux)

🇬🇧 English · 🇩🇪 [Deutsch](docker.md)

WhisperNotes runs as a container on any Linux machine with an x86-64 CPU, fastest with a graphics card. There are three
variants:

| Variant | Whisper (whisper.cpp) | Speaker detection (pyannote) | Compose files |
|---|---|---|---|
| **AMD** (default) | Vulkan (Mesa/RADV, no ROCm needed) | PyTorch with ROCm | `compose.yml` |
| **NVIDIA** | CUDA | PyTorch with CUDA | `compose.yml` + `compose.nvidia.yml` |
| **CPU only** | CPU | PyTorch on the CPU | `compose.yml` + `compose.cpu.yml` |

Ollama for the summaries can run in the same Compose project (profile `ollama`) or already exist elsewhere. The Discord
bot is optional (profile `discord`).

---

## 1. Requirements

- **Docker** with the Compose plugin. Add your own user to the `docker` group.
- **AMD:** a recent kernel, at least 6.15 for Ryzen AI Max (“Strix Halo”, Radeon 8060S). Check with
  `ls -l /dev/dri /dev/kfd` and `getent group video render`. The group IDs go into `docker/.env`.
  A test on the host: `vulkaninfo --summary` should show the GPU with “RADV”.
- **NVIDIA:** driver and [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/).
  `docker run --rm --gpus all ubuntu nvidia-smi` must show the card.
- **Memory:** Whisper large-v3-turbo needs ~2 GB, pyannote ~1 GB, the language model 5–70 GB depending on its size.
  The models add ~3 GB in the data folder.

## 2. Installation

```bash
git clone https://github.com/Poldion/WhisperNotes.git && cd WhisperNotes
cp docker/.env.example docker/.env                           # group IDs (AMD), port, data folder
cp docker/whispernotes.env.example docker/whispernotes.env   # language, Ollama, HF_TOKEN …
cp docker/discord.env.example docker/discord.env             # only with the Discord bot

# AMD
docker compose -f docker/compose.yml up -d --build
# NVIDIA
docker compose -f docker/compose.yml -f docker/compose.nvidia.yml up -d --build
# CPU only
docker compose -f docker/compose.yml -f docker/compose.cpu.yml up -d --build

# Additionally with Ollama and the Discord bot: --profile ollama --profile discord
docker compose -f docker/compose.yml logs -f whispernotes   # the first start downloads ~2.5 GB of models
```

Then open `http://<machine>:8000/dashboard/`. Data and models are stored in `docker/data/` (volume `/data`).
The directory belongs to the user with UID 1000. Create it yourself before the first start (`mkdir docker/data`),
otherwise Docker creates it as root.

**Ready-made image instead of building:** set e.g. `WN_IMAGE=poldion/whispernotes:latest` in `docker/.env` (or
`:nvidia` or `:cpu`) and start without `--build`. Self-built images are optimised for the machine's CPU
(`NATIVE=ON`) and therefore a little faster.

**Load an Ollama model** (with profile `ollama`): `docker compose -f docker/compose.yml exec ollama ollama pull gemma3:12b`.
WhisperNotes uses the currently loaded model or the one selected under “Settings → Summary”.

**Speaker detection with pyannote:** needs a Hugging Face token. First accept the terms of use of
[pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1).
The token goes into `whispernotes.env` as `HF_TOKEN` or into the settings. Without a token set
`DIARIZATION_ENGINE=sherpa`. sherpa-onnx runs on the CPU and needs no account.

## 3. Checking that the GPU is used

- **Whisper:** after the first transcription
  `grep -iE "vulkan|cuda" docker/data/app/logs/whisper-server.log`. The graphics card should show up there.
  If nothing is listed, Whisper runs on the CPU. That works but is much slower. In that case check the devices
  (`/dev/dri`) or the NVIDIA toolkit.
- **pyannote:**
  `docker compose -f docker/compose.yml exec whispernotes python -c "import torch; print(torch.cuda.is_available())"`.
  ROCm also reports itself as `cuda` here. `PYANNOTE_DEVICE=auto` picks the GPU automatically.

## 4. Performance (measured on AMD Ryzen AI Max+ 395, 128 GB)

Recording: 28:48 min D&D session from a conference microphone, four people.

| Step | CPU | GPU |
|---|---|---|
| Speaker detection pyannote community-1 | 594 s | 59 s (ROCm) |
| 5 documents (recap, 3 player recaps, lore) with gemma4:26b | – | 55 s |

Without a GPU, speaker detection is the bottleneck for long sessions. Your own measurements are welcome via pull request.

## 5. Build options

In `docker/.env` (see the comments in `docker/Dockerfile`):

| Variable | Default | Meaning |
|---|---|---|
| `WN_PYANNOTE` | `1` | `0` = without PyTorch/pyannote (image ~2 GB instead of ~10 GB, sherpa-onnx only) |
| `WN_TORCH_INDEX` | ROCm for gfx1151 | Other AMD GPU: enter the matching ROCm index from pytorch.org |
| `WN_CUDA_ARCHS` | `75;80;86;89;90;120` | NVIDIA: only your own generation saves build time (`86` RTX 30xx, `89` RTX 40xx) |
| `WN_PORT` / `WN_DATA` | `8000` / `./data` | port and data folder |

**AMD GPUs other than gfx1151:** the default index only contains PyTorch builds for Ryzen AI Max. For other Radeon
cards enter e.g. `https://download.pytorch.org/whl/rocm6.4` in `WN_TORCH_INDEX`. Check beforehand that your GPU is
supported there. Whisper via Vulkan works independently of this.

**Ryzen AI Max – GPU memory:** the iGPU shares the RAM. To let Ollama use more than half of it, a larger GTT limit via
kernel parameters helps, e.g. for ~110 GB with 128 GB RAM:
`amdgpu.gttsize=112640 ttm.pages_limit=28835840 ttm.page_pool_size=28835840`. Check the values for your device.

## 6. Known limits

- None of the components uses the NPU of the Ryzen AI processors.
- ROCm for gfx1151 is still young. If the Ollama image does not detect the GPU,
  `HSA_OVERRIDE_GFX_VERSION=11.5.1` in `compose.yml` helps.
- The Discord bot uses native modules for Discord's end-to-end encryption (DAVE). It is tested on Linux x86-64 and
  macOS arm64.

---

## Appendix: moving from a macOS installation

An existing installation without Docker (e.g. on a Mac mini with `deploy/setup_mac.sh`) keeps its data in
`~/WhisperNotes/backend/data/`. That includes jobs, campaigns, voice profiles and settings.

```bash
# on the new machine, stop WhisperNotes first:
docker compose -f docker/compose.yml stop whispernotes
rsync -a --info=progress2 <user>@<mac>:WhisperNotes/backend/data/ docker/data/app/
docker compose -f docker/compose.yml start whispernotes
```

Then check under **Settings**:

- **BasaltNotes → Address:** on the Mac this is often the SSH tunnel `http://127.0.0.1:4401`. On Linux the real address
  belongs here, no tunnel is needed.
- Adjust the **WhisperNotes address** and the **Ollama address** to the new machine.

Voice profiles stay valid (same CAM++ model). The Whisper models of the jobs keep their names. The copied audio files
can be transcribed again on the faster hardware. For the Discord bot copy `DISCORD_TOKEN` into `docker/discord.env` and
stop the bot on the Mac, otherwise two bots answer:

```bash
launchctl bootout gui/$(id -u)/com.whispernotes.discord
sudo launchctl bootout system/com.whispernotes            # WhisperNotes itself (LaunchDaemon)
launchctl bootout gui/$(id -u)/com.whispernotes.basalt-tunnel
```
