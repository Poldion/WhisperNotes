"""Ersatz für whisper.cpp' `whisper-server` zur Entwicklung ohne Mac.

Nimmt dieselben Argumente an (-m, -l, --host, --port, …) und bildet /health und /inference nach.
Umgebungsvariablen:
  MOCK_STARTUP_DELAY    Sekunden "Modell laden" (Standard 1.0, /health liefert solange 503)
  MOCK_INFERENCE_DELAY  Sekunden pro Transkription (Standard 0.2)
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

# Aus backend/ oder direkt aufrufbar
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

STARTUP_DELAY = float(os.environ.get("MOCK_STARTUP_DELAY", "1.0"))
INFERENCE_DELAY = float(os.environ.get("MOCK_INFERENCE_DELAY", "0.2"))

app = FastAPI()
state = {"ready_at": time.monotonic() + STARTUP_DELAY, "in_flight": 0, "max_in_flight": 0, "calls": 0}


@app.get("/health")
async def health():
    if time.monotonic() < state["ready_at"]:
        return JSONResponse({"status": "loading model"}, status_code=503)
    return {"status": "ok"}


@app.get("/stats")
async def stats():
    return state


@app.post("/inference")
async def inference(file: UploadFile = File(...), language: str = Form("de"), response_format: str = Form("json")):
    data = await file.read()
    state["calls"] += 1
    state["in_flight"] += 1
    state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
    try:
        await asyncio.sleep(INFERENCE_DELAY)
    finally:
        state["in_flight"] -= 1
    if response_format == "verbose_json":
        # Ein "Wort" alle 0,5 s über die gesamte Audiolänge (WAV 16 kHz mono 16 bit angenommen)
        duration = max(0.5, (len(data) - 44) / 32000)
        words = [{"word": f" c{state['calls']}w{k}", "start": k * 0.5, "end": k * 0.5 + 0.4, "probability": 0.9}
                 for k in range(int(duration / 0.5))]
        segments = [{"id": i, "start": seg[0]["start"], "end": seg[-1]["end"],
                     "text": "".join(w["word"] for w in seg), "words": seg}
                    for i, seg in enumerate(words[j:j + 10] for j in range(0, len(words), 10))]
        return {"task": "transcribe", "language": language, "duration": duration,
                "text": "".join(s["text"] for s in segments), "segments": segments}
    # Bewusst kurz: gleiche Wortfolgen ab 3 Wörtern würde der Chunk-Merge als Überlappung entfernen.
    return {"text": f" Mock-Transkript Nummer {state['calls']}.\n", "bytes": len(data), "language": language}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args, _unknown = parser.parse_known_args()  # -m, -l, -t usw. werden ignoriert
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
