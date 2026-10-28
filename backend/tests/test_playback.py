import io
import json
import wave

import numpy as np
from fastapi.testclient import TestClient

from app import jobs as jobs_module
from app.main import create_app

from app.multitrack import PCM_RATE, Segment, TrackSpeaker, clip_spans, mix_spans

from .conftest import make_wav
from .test_multitrack import MANIFEST


def speaker(segments):
    return TrackSpeaker(id="1", name="A", file="a.ogg", pre_skip=0, segments=segments)


def test_clip_spans_maps_real_time_window_to_compact_track():
    # Beitrag 1: Echtzeit 10–11 s, kompakt Pakete 0–49; Beitrag 2: Echtzeit 20–21 s, kompakt Pakete 50–99
    sp = speaker([Segment(offset_ms=10_000, packet_start=0, packets=50),
                  Segment(offset_ms=20_000, packet_start=50, packets=50)])
    assert clip_spans(sp, 10.5, 10.0) == [(0, 8000, 8000), (152000, 16000, 8000)]
    assert clip_spans(sp, 12.0, 5.0) == []


def test_mix_spans_places_and_sums_tracks():
    ones = (np.ones(PCM_RATE, dtype="<i2") * 1000).tobytes()
    pcm = mix_spans(1.0, [([(0, 100, 4)], 100, ones), ([(2, 0, 4)], 0, ones)])
    out = np.frombuffer(pcm, dtype="<i2")
    assert len(out) == PCM_RATE
    assert list(out[:7]) == [1000, 1000, 2000, 2000, 1000, 1000, 0]


def test_audio_endpoint_serves_original_with_ranges(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/jobs/unbekannt/audio").status_code == 404
        job = client.post("/api/jobs", files={"file": ("a.wav", make_wav(2.0), "audio/wav")}).json()
        resp = client.get(f"/api/jobs/{job['id']}/audio", headers={"Range": "bytes=0-99"})
        assert resp.status_code == 206 and len(resp.content) == 100
        assert resp.headers["content-type"].startswith("audio/wav")


def test_multitrack_clip_mixes_all_tracks(settings, monkeypatch):
    calls = []

    async def decode_range(path, start, length, settings):
        calls.append((path.name, round(start, 3)))
        return (np.ones(round(length * PCM_RATE), dtype="<i2") * 100).tobytes()

    monkeypatch.setattr(jobs_module, "decode_pcm16_range", decode_range)
    with TestClient(create_app(settings)) as client:
        job = client.post("/api/jobs/multitrack", data={"manifest": json.dumps(MANIFEST)},
                          files=[("tracks", ("alice.ogg", b"OggS", "audio/ogg")),
                                 ("tracks", ("bob.ogg", b"OggS", "audio/ogg"))]).json()
        assert client.get(f"/api/jobs/{job['id']}/audio").status_code == 409
        # 4–8 s: Alice spricht bis 5 s, Bob ab 6 s
        resp = client.get(f"/api/jobs/{job['id']}/clip?start=4&end=8")
        assert resp.status_code == 200
        with wave.open(io.BytesIO(resp.content)) as w:
            samples = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
        assert len(samples) == 4 * PCM_RATE
        assert samples[0] == 100 and samples[int(1.5 * PCM_RATE)] == 0 and samples[int(2.5 * PCM_RATE)] == 100
        assert sorted(calls) == [("alice.ogg", 4.0), ("bob.ogg", 0.0)]
