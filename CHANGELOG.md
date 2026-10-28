# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.1.0] – 2026-10-28

Initial public release.

### Added

- OpenAI-compatible transcription API (`POST /v1/audio/transcriptions`) around whisper.cpp, with on-demand
  `whisper-server`, a request queue and an optional separate Whisper model for voice commands (Home Assistant)
- Dashboard for long recordings: upload, splitting, live progress, transcript viewer with audio playback,
  map-reduce summaries through Ollama or OllamaProxy, adapted to the model's context size
- Speaker detection with sherpa-onnx (CPU) or pyannote.audio (GPU), naming by audio samples, voice profiles per campaign
- D&D tab: campaigns with party and glossary, session recaps, recaps per player character and world lore for the DM
- Discord bot that records voice channels with one track per person and posts the summaries
- BasaltNotes export and glossary from the campaign wiki
- Interface, status messages and summaries in English and German; editable summary templates
- Optional access protection with an API key and a dashboard password
- Docker images for AMD (Vulkan + ROCm), NVIDIA (CUDA) and CPU only; native setup for macOS (Apple Silicon)

[0.1.0]: https://github.com/Poldion/WhisperNotes/releases/tag/v0.1.0
