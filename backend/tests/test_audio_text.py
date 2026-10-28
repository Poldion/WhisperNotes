from app.audio import is_whisper_ready_wav, needs_seekable_input, plan_chunks
from app.textutil import format_timestamp, merge_chunks, merge_overlap, split_text

from .conftest import make_wav


def test_wav_detection():
    assert is_whisper_ready_wav(make_wav())
    assert not is_whisper_ready_wav(make_wav(rate=44100))
    assert not is_whisper_ready_wav(make_wav(channels=2))
    assert not is_whisper_ready_wav(b"OggS" + b"\x00" * 100)
    assert not is_whisper_ready_wav(b"")


def test_seekable_detection():
    assert needs_seekable_input(b"", "memo.M4A")
    assert needs_seekable_input(b"\x00\x00\x00\x20ftypM4A ", None)
    assert not needs_seekable_input(b"OggS", "voice.ogg")


def test_plan_chunks_short_file_is_single_chunk():
    assert plan_chunks(200, 300, 10) == [(0.0, 200)]
    assert plan_chunks(320, 300, 10) == [(0.0, 320)]  # kurzer Rest wird angehängt
    assert plan_chunks(0, 300, 10) == []


def test_plan_chunks_overlap_and_coverage():
    chunks = plan_chunks(1800, 300, 10)
    assert chunks[0] == (0.0, 300.0)
    for (s1, l1), (s2, _) in zip(chunks, chunks[1:]):
        assert s2 == s1 + 290           # Schrittweite = Chunk - Überlappung
        assert s1 + l1 - s2 == 10       # 10 s Überlappung
    last_start, last_len = chunks[-1]
    assert last_start + last_len == 1800
    assert last_len >= 30


def test_merge_overlap_removes_duplicate_words():
    prev = "Wir besprechen heute das Budget für das nächste Quartal und die Planung"
    cur = "Quartal und die Planung der neuen Räume beginnt im Mai"
    a, b = merge_overlap(prev, cur)
    assert a == "Wir besprechen heute das Budget für das nächste"
    assert b == cur
    assert f"{a} {b}".count("Planung") == 1


def test_merge_overlap_drops_garbled_edges_and_ignores_punctuation():
    prev = "Das ist der erste Teil. Und dann sagte er, dass wir morgen anfan"
    cur = "gen sagte er dass wir morgen anfangen werden. Gut."
    a, b = merge_overlap(prev, cur)
    assert a == "Das ist der erste Teil. Und dann"
    assert b == "sagte er dass wir morgen anfangen werden. Gut."


def test_merge_without_match_keeps_everything():
    assert merge_overlap("eins zwei drei", "vier fünf sechs") == ("eins zwei drei", "vier fünf sechs")
    assert merge_chunks(["a b c d", "x y z"]) == ["a b c d", "x y z"]


def test_split_text_respects_limit():
    text = " ".join(f"Satz Nummer {i} ist hier." for i in range(500))
    parts = split_text(text, 500)
    assert len(parts) > 1
    assert all(len(p) <= 500 for p in parts)
    assert " ".join(parts) == text
    assert split_text("kurz", 500) == ["kurz"]
    assert split_text("   ", 500) == []


def test_format_timestamp():
    assert format_timestamp(0) == "00:00:00"
    assert format_timestamp(3725) == "01:02:05"
