"""Stimmprofile je Kampagne: Wiedererkennen der Spielenden über Sessions hinweg.

Die Sprechererkennung liefert je erkannter Stimme einen Stimmabdruck (Zentroid der CAM++-Embeddings, siehe
diarize_worker.analyze_clusters). Ordnet man die Stimmen einer Session den Spielenden zu, merkt sich die
Kampagne diese Abdrücke – je Person die der letzten Sessions, gemittelt zu einem Profil. In der nächsten
Session werden die Stimmen mit den Profilen abgeglichen; passen alle eindeutig, entfällt die Zuordnung.

Ablage: data/voices/<kampagne>.json
    {"model": "<Stimmmodell>", "players": {"anna": {"<job-id>": [0.01, …], …}, …}}
Schlüssel ist der Name der Person (klein geschrieben) – ändert sich der Charakter, bleibt die Stimme bekannt."""

import itertools
import json
import re
import shutil
from pathlib import Path

import numpy as np

MAX_SESSIONS = 10  # so viele Sessions fließen je Person ins Profil ein


def player_key(name: str) -> str:
    return name.strip().lower()


def _normalize(vector) -> np.ndarray:
    v = np.asarray(vector, dtype=np.float32)
    return v / (np.linalg.norm(v) or 1.0)


class VoiceStore:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, campaign_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{12}", campaign_id):
            raise ValueError("ungültige Kampagnen-ID")
        return self.root / f"{campaign_id}.json"

    def _load(self, campaign_id: str) -> dict:
        path = self._path(campaign_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"model": None, "players": {}}

    def _save(self, campaign_id: str, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(campaign_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        shutil.move(tmp, path)

    def profiles(self, campaign_id: str, model: str) -> dict[str, np.ndarray]:
        """Profil je Person (Schlüssel aus `player_key`). Profile eines anderen Stimmmodells sind nicht
        vergleichbar und werden ignoriert."""
        data = self._load(campaign_id)
        if data.get("model") != model:
            return {}
        return {key: _normalize(np.mean([_normalize(v) for v in sessions.values()], axis=0))
                for key, sessions in data.get("players", {}).items() if sessions}

    def known_players(self, campaign_id: str, model: str) -> list[str]:
        return sorted(self.profiles(campaign_id, model))

    def learn(self, campaign_id: str, job_id: str, model: str, voices: dict[str, list[list[float]]]) -> None:
        """Abdrücke einer Session übernehmen (`voices`: Person → Abdrücke ihrer Stimmen in dieser Session).
        Frühere Beiträge derselben Session werden ersetzt – eine korrigierte Zuordnung überschreibt also
        die vorherige."""
        data = self._load(campaign_id)
        if data.get("model") != model:
            data = {"model": model, "players": {}}  # anderes Stimmmodell → neu anfangen
        players = data.setdefault("players", {})
        for sessions in players.values():
            sessions.pop(job_id, None)
        for key, vectors in voices.items():
            if not vectors:
                continue
            mean = _normalize(np.mean([_normalize(v) for v in vectors], axis=0))
            sessions = players.setdefault(key, {})
            sessions[job_id] = [round(float(x), 5) for x in mean]
            while len(sessions) > MAX_SESSIONS:  # älteste Session (Einfügereihenfolge) fällt heraus
                sessions.pop(next(iter(sessions)))
        data["players"] = {k: v for k, v in players.items() if v}
        self._save(campaign_id, data)

    def delete(self, campaign_id: str) -> None:
        self._path(campaign_id).unlink(missing_ok=True)


def match_speakers(voices: dict[str, list[float]], profiles: dict[str, np.ndarray]
                   ) -> list[tuple[str, str, float]]:
    """Beste Zuordnung Stimme → Person (jede Person höchstens einmal), maximiert die Summe der Ähnlichkeiten.
    Rückgabe: [(Stimme, Person, Kosinus-Ähnlichkeit), …] für alle Stimmen, die eine Person bekommen."""
    labels = sorted(voices)
    people = sorted(profiles)
    if not labels or not people:
        return []
    sim = np.array([[float(_normalize(voices[label]) @ profiles[p]) for p in people] for label in labels])
    best: tuple[float, tuple] = (-np.inf, ())
    if max(len(labels), len(people)) > 8:  # große Runden: gierig statt alle Permutationen
        pairs, used_l, used_p = [], set(), set()
        for i, j in sorted(np.ndindex(sim.shape), key=lambda ij: -sim[ij]):
            if i not in used_l and j not in used_p:
                pairs.append((i, j))
                used_l.add(i)
                used_p.add(j)
        best = (0.0, tuple(pairs))
    elif len(labels) <= len(people):
        for perm in itertools.permutations(range(len(people)), len(labels)):
            score = sum(sim[i, j] for i, j in enumerate(perm))
            if score > best[0]:
                best = (score, tuple(enumerate(perm)))
    else:  # mehr Stimmen als Personen: jede Person bekommt ihre beste Stimme
        for perm in itertools.permutations(range(len(labels)), len(people)):
            score = sum(sim[i, j] for j, i in enumerate(perm))
            if score > best[0]:
                best = (score, tuple((i, j) for j, i in enumerate(perm)))
    return [(labels[i], people[j], round(float(sim[i, j]), 3)) for i, j in best[1]]


def runner_up_gap(voice: list[float], person: str, profiles: dict[str, np.ndarray]) -> float:
    """Wie viel ähnlicher ist die Stimme der zugeordneten Person als der nächstbesten? Klein = verwechselbar."""
    v = _normalize(voice)
    others = [float(v @ p) for key, p in profiles.items() if key != person]
    return float(v @ profiles[person]) - max(others, default=-1.0)
