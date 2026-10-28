"""Zusammenführen von Whisper-Wortzeitstempeln und Sprecherwechseln (Diarisierung) zu Redebeiträgen."""

import bisect
import math
import re
from dataclasses import asdict, dataclass

_SPECIAL = re.compile(r"^\s*(\[[^\]]*\]|<\|[^|]*\|>)\s*$")  # [_BEG_], <|endoftext|> …


@dataclass
class Turn:
    start: float
    end: float
    speaker: int


@dataclass
class Word:
    start: float
    end: float
    text: str  # wie von Whisper geliefert, meist mit führendem Leerzeichen

    @property
    def mid(self) -> float:
        return (self.start + self.end) / 2


@dataclass
class Utterance:
    start: float
    end: float
    speaker: str  # "1", "2", … (Reihenfolge des ersten Auftretens)
    text: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Utterance":
        return cls(float(data["start"]), float(data["end"]), str(data["speaker"]), data["text"])


def words_from_whisper(payload: dict, offset: float) -> list[Word]:
    """Ganze Wörter aus einer `verbose_json`-Antwort von whisper-server, verschoben um den Chunk-Start.

    Whisper liefert Tokens (" N" + "iemand"); sie werden hier zu Wörtern zusammengesetzt, damit die
    Sprecherzuordnung nie mitten im Wort wechselt. Geräusch-Marker wie "*lacht*" oder "[Musik]" fallen
    weg. Fehlen Wortzeitstempel, wird das ganze Segment als ein "Wort" behandelt."""
    words: list[Word] = []
    for seg in payload.get("segments") or []:
        seg_words = seg.get("words") or []
        if seg_words:
            tokens = [Word(offset + float(t["start"]), offset + float(t["end"]), str(t.get("word", "")))
                      for t in seg_words]
            tokens = [t for t in tokens if t.text.strip() and not _SPECIAL.match(t.text)]
            words += drop_noise_markers(merge_tokens(tokens))
        else:
            text = _NOISE_IN_TEXT.sub("", str(seg.get("text", "")))
            if text.strip():
                words.append(Word(offset + float(seg["start"]), offset + float(seg["end"]), text))
    words.sort(key=lambda w: w.start)
    return words


def merge_tokens(tokens: list[Word]) -> list[Word]:
    """Tokens zu Wörtern: Ein neues Wort beginnt mit einem Token mit führendem Leerzeichen, das Buchstaben
    oder Ziffern enthält (oder einen Marker öffnet). Fortsetzungen ("iemand") und Satzzeichen (".", " ?") hängen am vorigen Wort.
    Hat kein Token ein führendes Leerzeichen (andere Quelle), bleibt jedes Token ein Wort."""
    if not any(t.text[:1].isspace() for t in tokens):
        return list(tokens)
    words: list[Word] = []
    for t in tokens:
        starts_word = t.text[:1].isspace() and (any(c.isalnum() for c in t.text)
                                                or t.text.strip()[:1] in _NOISE_OPEN)  # " *" von " *lacht*"
        if words and not starts_word:
            last = words[-1]
            words[-1] = Word(last.start, max(last.end, t.end), last.text + t.text.strip())
        else:
            words.append(Word(t.start, t.end, t.text))
    return words


_NOISE_IN_TEXT = re.compile(r"\s*(\*[^*]{1,40}\*|\[[^\]]{1,40}\]|\([^)]{1,40}\))")
def strip_noise(text: str) -> str:
    """Geräusch-Marker aus Fließtext entfernen (Pfad ohne Wortzeitstempel)."""
    return re.sub(r"\s+", " ", _NOISE_IN_TEXT.sub("", text)).strip()


_NOISE_OPEN = {"*": "*", "[": "]", "(": ")"}


def drop_noise_markers(words: list[Word], max_words: int = 4) -> list[Word]:
    """Geräusch-Marker ("*lacht*", "*lacht laut*", "[Musik]", "(Gelächter)") entfernen – sie sind keine
    Sprache, zerstückeln aber die Beiträge. Ein Marker reicht vom öffnenden bis zum schließenden Zeichen
    über höchstens `max_words` Wörter; ohne Abschluss bleibt alles stehen."""
    result: list[Word] = []
    i = 0
    while i < len(words):
        text = words[i].text.strip()
        close = _NOISE_OPEN.get(text[:1])
        end = None
        if close:
            for j in range(i, min(i + max_words, len(words))):
                tail = words[j].text.strip().rstrip(".,!?…:;")
                if tail.endswith(close) and (j > i or len(tail) > 1):
                    end = j
                    break
        if end is None:
            result.append(words[i])
            i += 1
        else:
            i = end + 1
    return result


def merge_timed_chunks(chunks: list[tuple[float, float, list[Word]]]) -> list[Word]:
    """Überlappende Chunks (start, länge, wörter) zusammenführen: Jede Überlappung wird in der Mitte
    geteilt – dort liegen die Wörter weit weg von den unzuverlässigen Schnittkanten."""
    result: list[Word] = []
    for i, (start, length, words) in enumerate(chunks):
        lo = 0.0 if i == 0 else (start + chunks[i - 1][0] + chunks[i - 1][1]) / 2
        hi = math.inf if i == len(chunks) - 1 else (chunks[i + 1][0] + start + length) / 2
        result += [w for w in words if lo <= w.mid < hi]
    return result


def assign_speakers(words: list[Word], turns: list[Turn], max_gap: float = 2.0) -> list[int | None]:
    """Sprecher je Wort: der Sprecherabschnitt mit der größten zeitlichen Überlappung, sonst der
    nächstgelegene (bis `max_gap` s), sonst der Sprecher des vorherigen Worts."""
    turns = sorted(turns, key=lambda t: t.start)
    starts = [t.start for t in turns]
    result: list[int | None] = []
    for w in words:
        best, best_overlap = None, 0.0
        # Kandidaten: Abschnitte, die vor dem Wortende beginnen; rückwärts, bis sie sicher vorbei sind
        idx = bisect.bisect_right(starts, w.end)
        for t in reversed(turns[max(0, idx - 8):idx]):
            overlap = min(w.end, t.end) - max(w.start, t.start)
            if overlap > best_overlap:
                best, best_overlap = t.speaker, overlap
        if best is None:
            nearest = min(turns[max(0, idx - 2):idx + 2], default=None,
                          key=lambda t: max(t.start - w.mid, w.mid - t.end, 0))
            if nearest and max(nearest.start - w.mid, w.mid - nearest.end, 0) <= max_gap:
                best = nearest.speaker
        if best is None and result:
            best = result[-1]
        result.append(best)
    # Wörter ganz am Anfang ohne Zuordnung übernehmen den ersten bekannten Sprecher
    first = next((s for s in result if s is not None), None)
    return [s if s is not None else first for s in result]


def smooth_speakers(words: list[Word], speakers: list[int | None], max_seconds: float = 1.0,
                    max_gap: float = 0.3) -> list[int | None]:
    """Kurze Sprecherwechsel mitten im Redefluss glätten: Ein Einschub von höchstens `max_seconds`,
    vor und nach dem derselbe andere Sprecher ohne Pause (≤ `max_gap` s) weiterredet, ist fast immer
    ein Zuordnungsfehler und wird diesem Sprecher zugeschlagen. Echte Einwürfe („Ja!“) haben meist
    eine Pause davor oder danach und bleiben erhalten."""
    if max_seconds <= 0 or len(words) < 3:
        return list(speakers)
    runs: list[tuple[int, int, int | None]] = []  # (erstes Wort, hinter dem letzten Wort, Sprecher)
    start = 0
    for i in range(1, len(words) + 1):
        if i == len(words) or speakers[i] != speakers[start]:
            runs.append((start, i, speakers[start]))
            start = i
    result = list(speakers)
    for k in range(1, len(runs) - 1):
        first, end, speaker = runs[k]
        prev_speaker, next_speaker = runs[k - 1][2], runs[k + 1][2]
        if prev_speaker != next_speaker or prev_speaker == speaker:
            continue
        duration = words[end - 1].end - words[first].start
        gap_before = words[first].start - words[first - 1].end
        gap_after = words[end].start - words[end - 1].end
        if duration <= max_seconds and gap_before <= max_gap and gap_after <= max_gap:
            result[first:end] = [prev_speaker] * (end - first)
    return result


def consolidate_sentences(words: list[Word], speakers: list[int | None], pause: float = 1.0,
                          max_seconds: float = 20.0, dominance: float = 2.0) -> list[int | None]:
    """Ein Satz, ein Sprecher. Whispers Wortzeiten liegen an Sprecherwechseln oft etwas zu früh, deshalb
    landet der Anfang eines Satzes beim vorherigen Sprecher ("Lieber zauber | ich ihm den Mund zu.").
    Wechselt der Sprecher innerhalb eines Satzes, bekommt ihn daher der Sprecher, der ihn beendet – außer
    ein anderer hat deutlich länger gesprochen (`dominance`-fach, mindestens 2 s), dann der mit der meisten
    Redezeit. Echte Wechsel bleiben erhalten: Pausen über `pause` s trennen den Satz in Teile, und Sätze über
    `max_seconds` (Whisper hat keinen Punkt gesetzt) werden nicht angefasst.
    Erwartet ganze Wörter (siehe `words_from_whisper`)."""
    result = list(speakers)
    start = 0
    for i, word in enumerate(words):
        last = i == len(words) - 1
        ends = last or _ends_sentence(word.text.strip()) or words[i + 1].start - word.end > pause
        if not ends:
            continue
        part = range(start, i + 1)
        start = i + 1
        if len({result[k] for k in part}) < 2 or words[part[-1]].end - words[part[0]].start > max_seconds:
            continue
        talk: dict[int | None, float] = {}
        for k in part:
            talk[result[k]] = talk.get(result[k], 0.0) + words[k].end - words[k].start
        finisher = result[part[-1]]
        top = max(talk, key=talk.get)
        winner = top if talk[top] >= max(2.0, dominance * talk[finisher]) else finisher
        for k in part:
            result[k] = winner
    return result


def join_words(words: list[Word]) -> str:
    """Whisper-Tokens tragen das Leerzeichen am Wortanfang selbst (" Ho" + "ffentlich" = "Hoffentlich").
    Sobald irgendein Token so ein Leerzeichen hat, werden sie daher direkt aneinandergehängt. Nur wenn
    gar keines eines hat (Quelle ohne Token-Leerzeichen), wird mit " " verbunden."""
    if not words:
        return ""
    if any(w.text[:1].isspace() for w in words):
        text = "".join(w.text for w in words)
    else:
        text = " ".join(w.text.strip() for w in words)
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"\s+([.,!?…:;])", r"\1", text).strip()  # kein Leerzeichen vor Satzzeichen


def merge_speaker_tracks(tracks: list[list[Word]], max_pause: float = 6.0,
                         max_length: float = 60.0) -> tuple[list[Utterance], dict[int, str]]:
    """Getrennte Spuren (eine Liste Wörter je Person, Zeiten schon in Echtzeit) zu einem Transkript mischen.

    Jede Spur wird zuerst für sich in Sätze gruppiert und erst danach nach Startzeit sortiert. Getrennt
    wird an Satzenden und erst an längeren Pausen (`max_pause`) – eine kurze Denkpause mitten im Satz
    zerlegt ihn nicht, denn in einer eigenen Spur ist ohnehin klar, wer spricht.
    So bleiben Sätze auch dann am Stück, wenn mehrere gleichzeitig reden. Würde man stattdessen alle
    Wörter gemeinsam sortieren, wechselte der Sprecher bei Überlappung Wort für Wort – oder sogar mitten
    im Wort, weil Whisper Zeitstempel je Token liefert. Rückgabe: Beiträge mit Nummern "1", "2", … in
    der Reihenfolge des ersten Auftretens, und die Zuordnung Spur-Index → Nummer."""
    all_utts: list[tuple[int, Utterance]] = []
    for idx, words in enumerate(tracks):
        ordered = sorted(words, key=lambda w: w.start)
        for u in build_utterances(ordered, [idx] * len(ordered), max_pause=max_pause, max_length=max_length,
                                  labels={idx: str(idx)}):
            all_utts.append((idx, u))
    all_utts.sort(key=lambda item: (item[1].start, item[0]))
    labels: dict[int, str] = {}
    result = []
    for idx, u in all_utts:
        u.speaker = labels.setdefault(idx, str(len(labels) + 1))
        result.append(u)
    return result, labels


_SENTENCE_END = re.compile(r"[.!?…]+[\"'»«“”„)\]]*$")
# Punkte, die keinen Satz beenden: Abkürzungen (klein geschrieben, ohne Punkt verglichen)
_ABBREVIATIONS = {
    "z", "b", "d", "h", "u", "a", "o", "ä", "s", "bzw", "ca", "dr", "prof", "nr", "vgl", "usw", "etc",
    "evtl", "ggf", "inkl", "bspw", "zb", "dh", "mio", "mrd", "std", "min", "sek", "st", "str", "tel", "abs",
}


def _ends_sentence(word: str) -> bool:
    """Endet dieses (ganze) Wort einen Satz? "Kind." ja, "16." (Ordinalzahl), "z." oder "bzw." nein."""
    if not _SENTENCE_END.search(word):
        return False
    core = _SENTENCE_END.sub("", word).strip("\"'»«“”„([").lower()
    if not core:
        return True  # reines Satzzeichen-Token, z. B. "." oder "?"
    if word.rstrip("\"'»«“”)]").endswith(("!", "?", "…", "...")):
        return True
    return not (core.isdigit() or core in _ABBREVIATIONS or (len(core) == 1 and core.isalpha()))


def build_utterances(words: list[Word], speakers: list[int | None],
                     max_pause: float = 5.0, max_length: float = 90.0,
                     labels: dict[int | None, str] | None = None,
                     split_sentences: bool = True) -> list[Utterance]:
    """Aufeinanderfolgende Wörter desselben Sprechers zu Redebeiträgen gruppieren – getrennt bei
    Sprecherwechsel, Pausen über `max_pause` s, nach `max_length` s und (Standard) an Satzenden.
    Sprecher werden in der Reihenfolge ihres ersten Auftretens als "1", "2", … nummeriert; wer die
    Zuordnung Roh-ID → Nummer braucht, übergibt ein leeres Dict als `labels`."""
    labels = {} if labels is None else labels
    utterances: list[Utterance] = []
    group: list[Word] = []
    group_speaker: int | None = None
    current_word = ""       # Whisper liefert Tokens; ein Wort beginnt mit einem Token mit Leerzeichen
    sentence_done = False   # das letzte vollständige Wort beendete einen Satz

    def flush() -> None:
        if group:
            label = labels.setdefault(group_speaker, str(len(labels) + 1))
            text = join_words(group)
            if text:
                utterances.append(Utterance(group[0].start, group[-1].end, label, text))

    for word, speaker in zip(words, speakers):
        # Ein Wort beginnt mit einem Token mit führendem Leerzeichen – außer bei reinen Satzzeichen (" .")
        starts_word = (word.text[:1].isspace() and any(c.isalnum() for c in word.text)) or not current_word
        # Pausen, Längengrenze und Satzenden trennen nur vor einem Wortanfang – Fortsetzungs-Tokens
        # ("iger" nach "Grusel", ein einzelnes ".") bleiben immer am Wort, auch wenn ihr Zeitstempel
        # (Whisper ist an Übergängen ungenau) hinter einer Pause liegt.
        if group and (speaker != group_speaker
                      or (starts_word and word.start - group[-1].end > max_pause)
                      or (starts_word and word.end - group[0].start > max_length)
                      or (split_sentences and sentence_done and starts_word)):
            flush()
            group = []
        if not group:
            group_speaker = speaker
            current_word = ""
        group.append(word)
        current_word = word.text.strip() if starts_word else current_word + word.text.strip()
        sentence_done = _ends_sentence(current_word)
    flush()
    return utterances


def group_for_display(utterances: list[Utterance], max_gap: float = 3.0) -> list[Utterance]:
    """Für die Anzeige: aufeinanderfolgende Sätze derselben Person (ohne Zwischenruf, Pause ≤ `max_gap` s)
    wieder zu einem Absatz zusammenfassen. Die Satz-Trennung bleibt in utterances.json erhalten."""
    grouped: list[Utterance] = []
    for u in utterances:
        last = grouped[-1] if grouped else None
        if last and last.speaker == u.speaker and u.start - last.end <= max_gap:
            grouped[-1] = Utterance(last.start, max(last.end, u.end), last.speaker, f"{last.text} {u.text}")
        else:
            grouped.append(Utterance(u.start, u.end, u.speaker, u.text))
    return grouped


def text_between(utterances: list[Utterance], start: float, end: float, max_chars: int = 220) -> str:
    """Text der Redebeiträge, die den Zeitraum überlappen (für die Anzeige zur Hörprobe)."""
    text = " ".join(u.text for u in utterances if u.end > start and u.start < end)
    return text if len(text) <= max_chars else text[:max_chars - 1] + "…"


def speaker_overview(utterances: list[Utterance], samples_per_speaker: int = 3,
                     clip_max: float = 12.0, typical: dict[str, list[list[float]]] | None = None) -> list[dict]:
    """Je Sprecher: Redezeit und einige Hörproben. Liegen `typical` Stellen aus der Sprechererkennung vor
    (die dem Stimm-Durchschnitt ähnlichsten, ohne Überlappung), werden diese genommen, sonst möglichst
    4–12 s lange Beiträge."""
    by_speaker: dict[str, list[Utterance]] = {}
    for u in utterances:
        by_speaker.setdefault(u.speaker, []).append(u)

    def score(u: Utterance) -> float:
        dur = u.end - u.start
        return abs(min(dur, 20) - 8) + (0 if dur >= 3 else 10)

    overview = []
    for label in sorted(by_speaker, key=int):
        items = by_speaker[label]
        ranges = (typical or {}).get(label)
        if ranges:
            samples = [{"start": round(a, 2), "end": round(min(b, a + clip_max), 2),
                        "text": text_between(utterances, a, b)} for a, b in ranges[:samples_per_speaker]]
        else:
            picks = sorted(sorted(items, key=score)[:samples_per_speaker], key=lambda u: u.start)
            samples = [{"start": round(u.start, 2), "end": round(min(u.end, u.start + clip_max), 2),
                        "text": u.text if len(u.text) <= 220 else u.text[:217] + "…"} for u in picks]
        overview.append({
            "id": label,
            "seconds": round(sum(u.end - u.start for u in items), 1),
            "utterances": len(items),
            "samples": samples,
        })
    return overview


# Sätze, die Whisper in Stille und Geräuschen erfindet (gelernt aus Untertiteln von Videos). Sie werden nur
# entfernt, wenn sie allein stehen – ein "Vielen Dank" mitten im Gespräch bleibt.
_HALLUCINATION = re.compile(
    r"^(vielen dank( fürs zuschauen| für ihre aufmerksamkeit| fürs zuhören)?"
    r"|danke( schön)?( fürs zuschauen| fürs zuhören)"
    r"|bis zum nächsten mal"
    r"|tschüss und bis zum nächsten mal"
    r"|(das war'?s|das wars) für heute"
    r"|untertitel(ung)?\b.*"
    r"|.*\bamara org\b.*"
    r"|.*\bswr \d{4}\b.*)$")


def _normalize_phrase(text: str) -> str:
    text = text.lower().replace("für's", "fürs").replace("’", "'")
    return re.sub(r"\s+", " ", re.sub(r"[^\w' ]+", " ", text)).strip()


def drop_hallucinations(words: list[Word], context: list[Word] | None = None, min_gap: float = 1.5,
                        max_words: int = 12) -> list[Word]:
    """Typische Whisper-Erfindungen ("Vielen Dank.", "Untertitel im Auftrag des ZDF …") entfernen, wenn sie
    allein in einer Sprechpause stehen: Im Abstand von `min_gap` s davor und danach spricht niemand.
    `words` sind ganze Wörter oder Whisper-Segmente in Echtzeit. `context` = alle Wörter der Aufnahme
    (bei Mehrspur: aller Spuren), sonst `words` selbst."""
    ordered = sorted(words, key=lambda w: w.start)
    others = sorted(context if context is not None else ordered, key=lambda w: w.start)
    others_start = [w.start for w in others]
    result: list[Word] = []
    i = 0
    while i < len(ordered):
        j = i  # Insel: Wörter ohne Pause ≥ min_gap dazwischen
        while j + 1 < len(ordered) and ordered[j + 1].start - ordered[j].end < min_gap:
            j += 1
        island = ordered[i:j + 1]
        start, end = island[0].start, max(w.end for w in island)
        own = {id(w) for w in island}
        lo = bisect.bisect_left(others_start, start - min_gap - 120)  # lange Wörter/Segmente vorher abdecken
        nearby = any(id(w) not in own and w.end > start - min_gap and w.start < end + min_gap
                     for w in others[lo:bisect.bisect_right(others_start, end + min_gap)])
        invented = (len(island) <= max_words and not nearby
                    and _HALLUCINATION.match(_normalize_phrase(join_words(island))))
        if not invented:
            result += island
        i = j + 1
    return result


def segments_from_whisper(payload: dict, offset: float) -> list[Word]:
    """Whisper-Segmente als grobe "Wörter" (Start, Ende, Text) – für den Pfad ohne Sprechererkennung."""
    return [Word(offset + float(s["start"]), offset + float(s["end"]), " " + str(s.get("text", "")).strip())
            for s in payload.get("segments") or [] if str(s.get("text", "")).strip()]
