"""Textwerkzeuge: Zusammenführen überlappender Chunk-Transkripte und Aufteilen für die Map-Phase."""

import re

_NORMALIZE = re.compile(r"[^\w]+", re.UNICODE)


def _norm(word: str) -> str:
    return _NORMALIZE.sub("", word.lower())


def merge_overlap(prev: str, cur: str, window: int = 40, min_match: int = 3) -> tuple[str, str]:
    """Entfernt die doppelt transkribierte Überlappung zwischen zwei aufeinanderfolgenden Chunks.

    Gesucht wird die längste gemeinsame Wortfolge zwischen dem Ende von `prev` und dem Anfang
    von `cur`. `prev` wird vor dieser Folge abgeschnitten, `cur` beginnt mit ihr. Dadurch fallen
    auch die an den Schnittkanten meist verstümmelten Wörter weg."""
    prev_words, cur_words = prev.split(), cur.split()
    tail_offset = max(0, len(prev_words) - window)
    tail = [_norm(w) for w in prev_words[tail_offset:]]
    head = [_norm(w) for w in cur_words[:window]]

    best_len = best_i = best_j = 0
    # Längster gemeinsamer Teilstring auf Wortebene (DP, window² ist klein).
    lengths = [[0] * (len(head) + 1) for _ in range(len(tail) + 1)]
    for i in range(1, len(tail) + 1):
        for j in range(1, len(head) + 1):
            if tail[i - 1] and tail[i - 1] == head[j - 1]:
                lengths[i][j] = lengths[i - 1][j - 1] + 1
                if lengths[i][j] > best_len:
                    best_len, best_i, best_j = lengths[i][j], i, j

    if best_len < min_match:
        return prev, cur
    prev_cut = tail_offset + best_i - best_len
    cur_cut = best_j - best_len
    return " ".join(prev_words[:prev_cut]), " ".join(cur_words[cur_cut:])


def merge_chunks(texts: list[str]) -> list[str]:
    """Bereinigt eine Liste von Chunk-Transkripten paarweise um ihre Überlappungen."""
    result = [t.strip() for t in texts]
    for k in range(1, len(result)):
        result[k - 1], result[k] = merge_overlap(result[k - 1], result[k])
    return result


def split_text(text: str, max_chars: int) -> list[str]:
    """Teilt Text an Absatz- bzw. Satzgrenzen in Stücke von höchstens ca. `max_chars` Zeichen."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    if "\n" in text:
        # Zeilen (z. B. "Sprecher: Text") bleiben zusammen; nur überlange Zeilen werden weiter geteilt.
        parts: list[str] = []
        current = ""
        for line in (ln.strip() for ln in text.splitlines()):
            if not line:
                continue
            pieces = split_text(line, max_chars) if len(line) > max_chars else [line]
            for piece in pieces:
                if current and len(current) + 1 + len(piece) > max_chars:
                    parts.append(current)
                    current = piece
                else:
                    current = f"{current}\n{piece}" if current else piece
        if current:
            parts.append(current)
        return parts
    sentences = re.split(r"(?<=[.!?])\s+", text)
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > max_chars:  # überlange "Sätze" hart teilen
            if current:
                parts.append(current)
                current = ""
            parts.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if current and len(current) + 1 + len(sentence) > max_chars:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def format_timestamp(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def collapse_repeats(items: list, key=lambda x: x, max_n: int = 30) -> list:
    """Whisper-Halluzinationsschleifen entfernen: Folgt dieselbe Wortfolge (1–`max_n` Wörter) mehrfach
    direkt auf sich selbst, bleibt nur ihr erstes Vorkommen. Ab 3 Wörtern genügt eine Wiederholung
    zweimal hintereinander nicht – erst ab dreimal; einzelne Wörter und Wortpaare erst ab fünfmal
    („ja, ja, ja“ oder „nein nein“ sind echte Sprache). `key` liefert den Vergleichstext je Element."""
    keys = [_norm(key(x)) for x in items]
    result = []
    i = 0
    while i < len(items):
        skip_to = None
        for n in range(1, max_n + 1):
            if i + 2 * n > len(items):
                break
            pattern = keys[i:i + n]
            if not all(pattern):
                continue
            reps = 1
            while keys[i + reps * n:i + (reps + 1) * n] == pattern:
                reps += 1
            if reps >= (5 if n <= 2 else 3):
                skip_to = i + reps * n
                break
        if skip_to is None:
            result.append(items[i])
            i += 1
        else:
            result += items[i:i + n]
            i = skip_to
    return result


def collapse_text_repeats(text: str) -> str:
    """`collapse_repeats` für Fließtext (Pfad ohne Sprechererkennung)."""
    return " ".join(collapse_repeats(text.split()))
