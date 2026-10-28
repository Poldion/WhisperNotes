# Third-party software and models

The code of this repository is licensed under the [MIT License](LICENSE). It uses the third-party components below.
None of them are included in the repository; they are fetched from their official sources during setup
(`deploy/setup_mac.sh`, `docker/entrypoint.sh`) or by the package managers.

## Runtime software

| Component | License | Used for |
|---|---|---|
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | MIT | Transcription (`whisper-server`) |
| [FFmpeg](https://ffmpeg.org/) | LGPL-2.1+ (GPL depending on the build) | Converting and splitting audio; called as a system program, not linked |
| [FastAPI](https://github.com/fastapi/fastapi), [Pydantic](https://github.com/pydantic/pydantic), pydantic-settings | MIT | Backend |
| [Uvicorn](https://github.com/encode/uvicorn), [HTTPX](https://github.com/encode/httpx) | BSD-3-Clause | Backend |
| [python-multipart](https://github.com/Kludex/python-multipart) | Apache-2.0 | Backend |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | Apache-2.0 | Speaker detection, voice activity detection |
| [NumPy](https://github.com/numpy/numpy) | BSD-3-Clause | Backend |
| [pyannote.audio](https://github.com/pyannote/pyannote-audio) (optional) | MIT | Alternative speaker detection |
| [PyTorch](https://github.com/pytorch/pytorch) (optional, with pyannote) | BSD-3-Clause | Alternative speaker detection |
| [React](https://github.com/facebook/react) | MIT | Dashboard |
| [marked](https://github.com/markedjs/marked) | MIT | Dashboard |
| [DOMPurify](https://github.com/cure53/DOMPurify) | MPL-2.0 or Apache-2.0 | Dashboard |
| [discord.js](https://github.com/discordjs/discord.js), [@discordjs/voice](https://github.com/discordjs/discord.js) | Apache-2.0 | Discord bot |
| [libsodium-wrappers](https://github.com/jedisct1/libsodium.js) | ISC | Discord bot |

All other npm dependencies use permissive licenses (MIT, ISC, Apache-2.0, BSD, 0BSD). `caniuse-lite` (CC-BY-4.0) is
only used while building the dashboard.

## Models

The license on the model card of the source always applies. This list is a guide, not legal advice.

| Model | Source | License (according to the source) | Note |
|---|---|---|---|
| Whisper `large-v3-turbo` and others (ggml) | [ggerganov/whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp) | MIT (OpenAI Whisper) | |
| Silero VAD | sherpa-onnx releases ([snakers4/silero-vad](https://github.com/snakers4/silero-vad)) | MIT | |
| pyannote segmentation-3.0 (default segmentation) | sherpa-onnx releases ([pyannote](https://huggingface.co/pyannote/segmentation-3.0)) | MIT | |
| reverb-diarization-v1 (optional, opt-in only) | sherpa-onnx releases ([Revai](https://huggingface.co/Revai/reverb-diarization-v1)) | Rev's own license | **Non-commercial use only according to Rev** – only downloaded if you set it in `DIARIZATION_SEGMENTATION_MODEL` (macOS: `WITH_REVERB=1 bash deploy/setup_mac.sh`) |
| WeSpeaker ResNet34 / CAM++ (VoxCeleb) | sherpa-onnx releases ([wenet-e2e/wespeaker](https://github.com/wenet-e2e/wespeaker)) | CC-BY-4.0 (models), Apache-2.0 (code) | Attribution |
| 3D-Speaker ERes2Net | sherpa-onnx releases ([modelscope/3D-Speaker](https://github.com/modelscope/3D-Speaker)) | Apache-2.0 | |
| pyannote speaker-diarization-community-1 (optional) | [Hugging Face](https://huggingface.co/pyannote/speaker-diarization-community-1) | CC-BY-4.0 | Accept the conditions on Hugging Face |
| Language models for summaries | via Ollama / OllamaProxy | per model | |

The test audio `0-four-speakers-zh.wav` comes from the sherpa-onnx releases and is only downloaded for a test.

## Images and trademarks

The screenshots in `docs/bilder/` show made-up demo data. Dungeons & Dragons is a trademark of Wizards of the Coast;
WhisperNotes is not affiliated with Wizards of the Coast.
