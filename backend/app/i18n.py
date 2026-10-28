"""Übersetzung der Statusmeldungen und Dokumentköpfe (Einstellung `language`).

Wie gettext: Der deutsche Text ist der Schlüssel, `EN` enthält die Übersetzungen. Platzhalter im str.format-Stil.
Fehlt eine Übersetzung, bleibt der deutsche Text stehen. Die Prompts selbst stehen in prompts.py."""

EN: dict[str, str] = {
    # Status von Jobs
    "In Warteschlange": "Queued",
    "Abgebrochen": "Cancelled",
    "Wird abgebrochen …": "Cancelling …",
    "Zusammenfassung in Warteschlange": "Summary queued",
    "Neu transkribieren in Warteschlange": "Re-transcription queued",
    "Fertig": "Done",
    "Fertig (ohne Zusammenfassung)": "Done (without summary)",
    "Fehler": "Error",
    "Analysiere Audiodatei": "Analysing audio file",
    "Analysiere Spuren": "Analysing tracks",
    "Transkribiere {n} Spuren": "Transcribing {n} tracks",
    "Transkribiere {name} · Abschnitt {done}/{total}": "Transcribing {name} · part {done}/{total}",
    "Transkript fertig": "Transcript ready",
    "Transkribiere Abschnitt {i}/{n}": "Transcribing part {i}/{n}",
    "Transkript fertig, warte auf Sprechererkennung": "Transcript ready, waiting for speaker detection",
    "Führe Abschnitte zusammen": "Merging parts",
    "Sprechererkennung": "Speaker detection",
    "Sprechererkennung: lade Audio": "Speaker detection: loading audio",
    "Sprechererkennung: analysiere Sprecherwechsel": "Speaker detection: finding speaker changes",
    "Sprechererkennung: Stimmprofile": "Speaker detection: voice profiles",
    "Sprechererkennung: wähle Hörproben": "Speaker detection: picking audio samples",
    "Stimmen automatisch erkannt": "Voices recognised automatically",
    "{n} Sprecher erkannt – bitte zuordnen": "{n} speakers detected – please assign them",
    "Ermittle aktives Ollama-Modell": "Looking up the active Ollama model",
    "Zusammenfassung mit {model}": "Summarising with {model}",
    "Zusammenfassung wird erstellt": "Writing summary",
    "Map {i}/{n}": "Notes {i}/{n}",
    "Verdichte Stichpunkte (Runde {n})": "Condensing notes (round {n})",
    "Reduce: {label}": "Writing: {label}",
    "Abschnitt {i} von {n}:": "Section {i} of {n}:",
    "Gesamtzusammenfassung": "Summary",
    "Recap": "Recap",
    "Recap {character}": "Recap {character}",
    "Welt & Lore": "World & lore",
    # Dokumentköpfe
    "# Zusammenfassung: {title}": "# Summary: {title}",
    "# Session-Recap: {title}": "# Session recap: {title}",
    "# Spieler-Recaps: {title}": "# Player recaps: {title}",
    "# Welt & Lore (für den DM): {title}": "# World & lore (for the DM): {title}",
    "# Transkript: {title}": "# Transcript: {title}",
    "> Aufnahme vom {date}, {time} Uhr · erstellt am {created} mit Ollama-Modell {model}":
        "> Recorded on {date}, {time} · created on {created} with Ollama model {model}",
    ", Kontext {n} Tokens": ", context {n} tokens",
    "- Aufgenommen: {date}, {time} Uhr": "- Recorded: {date}, {time}",
    "- Erstellt: {date}": "- Created: {date}",
    "- Dauer: {duration}": "- Duration: {duration}",
    "- Abschnitte: {n}": "- Parts: {n}",
    "- Sprecher: {names}": "- Speakers: {names}",
    # Fehler
    "Kein Ollama-Modell geladen. Bitte ein Modell in Ollama laden (z. B. `ollama run <modell>`) und die "
    "Zusammenfassung erneut starten.":
        "No Ollama model loaded. Load a model in Ollama (e.g. `ollama run <model>`) and start the summary again.",
}

EN.update({
    # Einstellungsseite (runtime_settings.py) – test_i18n.py prüft, dass hier nichts fehlt
    "Allgemein": "General",
    "Sprache von Dashboard, Statusmeldungen und Zusammenfassungen.":
        "Language of the dashboard, status messages and summaries.",
    "Sprache / Language": "Sprache / Language",
    "Was am Tisch gesprochen wird, stellst du unter Transkription ein":
        "The language spoken in the recordings is set under Transcription",
    "nach dem Neuladen der Seite": "after reloading the page",
    "Deutsch": "Deutsch",
    "English": "English",
    "Zugang": "Access",
    "Schutz für den Betrieb außerhalb des Heimnetzes. Beides leer = ohne Anmeldung.":
        "Protection for running outside your home network. Both empty = no login.",
    "API-Schlüssel": "API key",
    "Für /v1 und /api als „Authorization: Bearer …“ – in Home Assistant als API-Key, beim Discord-Bot als "
    "WHISPERNOTES_API_KEY eintragen":
        "For /v1 and /api as \"Authorization: Bearer …\" – enter it as the API key in Home Assistant and as "
        "WHISPERNOTES_API_KEY for the Discord bot",
    "Dashboard-Passwort": "Dashboard password",
    "Leer = Anmeldung mit dem API-Schlüssel": "Empty = log in with the API key",
    "BasaltNotes": "BasaltNotes",
    "Fertige Zusammenfassungen automatisch in den Eingang von BasaltNotes legen.":
        "Put finished summaries into the BasaltNotes inbox automatically.",
    "Adresse": "Address",
    "z. B. http://nas.local:4400 – leer = Export aus. Auf dem Mac ohne Bildschirm blockiert macOS Geräte im "
    "Heimnetz: dann deploy/basalt_tunnel.sh und http://127.0.0.1:4401":
        "e.g. http://nas.local:4400 – empty = no export. On a headless Mac, macOS blocks devices on the local "
        "network: use deploy/basalt_tunnel.sh and http://127.0.0.1:4401",
    "API-Token": "API token",
    "In BasaltNotes unter Einstellungen → API-Tokens anlegen (Rechte „Eingang“ + „Lesen“).":
        "Create one in BasaltNotes under Settings → API tokens (permissions \"Inbox\" + \"Read\").",
    "Adresse für Links": "Address for links",
    "Nur nötig, wenn BasaltNotes im Browser unter einer anderen Adresse erreichbar ist (z. B. hinter einem "
    "Reverse-Proxy).": "Only needed if the browser reaches BasaltNotes at a different address (e.g. behind a "
                       "reverse proxy).",
    "Vault für DnD-Sessions": "Vault for D&D sessions",
    "Vault für übrige Aufnahmen": "Vault for other recordings",
    "leer = normale Aufnahmen nicht exportieren": "empty = do not export regular recordings",
    "Kurator": "Curator",
    "automatisch einsortieren (Regeln des Vaults)": "sort automatically (vault rules)",
    "alles als Vorschlag zur Freigabe": "everything as a suggestion for review",
    "nur ablegen, nicht einsortieren": "only store, do not sort",
    "Namen aus dem Wiki nutzen": "Use names from the wiki",
    "Namen und Schreibvarianten aus dem Kampagnen-Wiki als Whisper-Glossar und für die Recaps":
        "Names and spellings from the campaign wiki as Whisper glossary and for the recaps",
    "Adresse von WhisperNotes": "WhisperNotes address",
    "Für Links aus BasaltNotes zurück (Transkript, Dashboard), z. B. http://whispernotes.local:8000":
        "For links from BasaltNotes back here (transcript, dashboard), e.g. http://whispernotes.local:8000",
    "Transkription": "Transcription",
    "Whisper und die Erkennung von Sprachpausen.": "Whisper and voice activity detection.",
    "Sprache": "Language",
    "Sprachcode, z. B. de, en": "Language code, e.g. de, en",
    "Modell für die /v1-API": "Model for the /v1 API",
    "Home Assistant & Co. – für kurze Sprachbefehle ist turbo deutlich schneller. Läuft gerade ein Job mit einem "
    "anderen Modell, wird dieses mitbenutzt.":
        "Home Assistant & co. – turbo is much faster for short voice commands. If a job is currently running "
        "with another model, that one is shared.",
    "wie im Dashboard (Standardmodell bzw. gerade geladenes)": "as in the dashboard (default or currently loaded)",
    "CPU-Threads": "CPU threads",
    "beim nächsten Start von Whisper (nach Leerlauf)": "the next time Whisper starts (after idling)",
    "Beenden nach Leerlauf": "Stop after idling for",
    "Whisper gibt danach den Speicher frei": "Whisper then frees its memory",
    "Zeitlimit je Sekunde Audio": "Time limit per second of audio",
    "Rechenzeit, bevor Whisper als hängend gilt (mindestens 180 s je Abschnitt). large-v3 braucht deutlich mehr "
    "als turbo.": "Processing time before Whisper counts as stuck (at least 180 s per part). large-v3 needs much "
                  "more than turbo.",
    "Geräusch-Marker unterdrücken": "Suppress noise markers",
    "*lacht*, [Musik] … nicht als Text ausgeben": "Do not output *laughs*, [music] … as text",
    "D&D-Begriffe ins Glossar": "D&D terms in the glossary",
    "Attribute, Fertigkeiten, Regelbegriffe": "Abilities, skills, rules terms",
    "Sprachpausen erkennen (VAD)": "Detect speech pauses (VAD)",
    "Nur Sprachstellen gehen an Whisper – weniger erfundene Wörter in Stille":
        "Only speech is sent to Whisper – fewer invented words in silence",
    "VAD-Schwelle": "VAD threshold",
    "höher = strenger, leise Einwürfe fallen eher weg": "higher = stricter, quiet interjections are more likely "
                                                         "to be dropped",
    "Mindestlänge einer Pause": "Minimum pause length",
    "Wer spricht wann – und das Wiedererkennen über Sessions.": "Who speaks when – and recognising voices across "
                                                                 "sessions.",
    "Verfahren": "Engine",
    "pyannote (genauer, GPU)": "pyannote (more accurate, GPU)",
    "sherpa-onnx (schneller, CPU)": "sherpa-onnx (faster, CPU)",
    "Hugging-Face-Token": "Hugging Face token",
    "Nur für pyannote nötig": "Only needed for pyannote",
    "pyannote rechnet auf": "pyannote runs on",
    "automatisch (GPU, falls verfügbar)": "automatic (GPU if available)",
    "GPU – NVIDIA/AMD ROCm": "GPU – NVIDIA/AMD ROCm",
    "GPU – Apple (MPS)": "GPU – Apple (MPS)",
    "CPU": "CPU",
    "Trennschwelle (sherpa)": "Clustering threshold (sherpa)",
    "Nur ohne vorgegebene Sprecheranzahl: kleiner = mehr Sprecher":
        "Only without a given number of speakers: lower = more speakers",
    "Kurze Wechsel glätten bis": "Smooth short changes up to",
    "Stimmen automatisch zuordnen": "Assign voices automatically",
    "DnD: bekannte Stimmen der Kampagne ohne Rückfrage zuordnen":
        "D&D: assign known voices of the campaign without asking",
    "Mindest-Ähnlichkeit": "Minimum similarity",
    "Gemessen: gleiche Stimme 0,58–0,85, verschiedene bis 0,39": "Measured: same voice 0.58–0.85, different up "
                                                                  "to 0.39",
    "Mindestabstand zur nächsten Person": "Minimum margin to the next person",
    "Zusammenfassung": "Summary",
    "Ollama und die Dokumente, die nach einer Session entstehen.": "Ollama and the documents created after a "
                                                                    "session.",
    "Ollama-Adresse": "Ollama address",
    "Modell": "Model",
    "Festes Modell für alle Zusammenfassungen; bei „automatisch“ wird das gerade in Ollama geladene Modell genutzt":
        "Fixed model for all summaries; \"automatic\" uses the model currently loaded in Ollama",
    "automatisch (gerade geladenes)": "automatic (currently loaded)",
    "Ersatzmodell": "Fallback model",
    "Nur bei „automatisch“: wird geladen, wenn gerade kein Modell im Speicher aktiv ist":
        "Only with \"automatic\": loaded when no model is currently in memory",
    "keins": "none",
    "Kontextgröße": "Context size",
    "leer = automatisch (Ollama bzw. Proxy)": "empty = automatic (Ollama or proxy)",
    "Zeitlimit je Aufruf": "Time limit per call",
    "Nachdenken erlauben (Thinking)": "Allow thinking",
    "Bei Denk-Modellen wie gemma4 oder qwen3. Aus = deutlich schneller; an kann gründlicher sein, aber bei langen "
    "Sessions sehr lange dauern.": "For thinking models like gemma4 or qwen3. Off = much faster; on can be more "
                                   "thorough but takes very long for long sessions.",
    "Recap je Spielercharakter": "Recap per player character",
    "Welt & Lore für den DM": "World & lore for the DM",
    "Vorlagen": "Templates",
    "Abschnitte, Länge und Ton der Dokumente. Leer = eingebaute Vorlage der eingestellten Sprache. Die Regeln "
    "(nichts erfinden, Zeitangaben, Charakternamen) hängt WhisperNotes immer an. Gilt ab der nächsten "
    "Zusammenfassung.": "Sections, length and tone of the documents. Empty = built-in template for the selected "
                        "language. WhisperNotes always appends the rules (invent nothing, dates, character "
                        "names). Applies from the next summary.",
    "Zusammenfassung (normale Aufnahmen)": "Summary (regular recordings)",
    "Session-Recap (DnD)": "Session recap (D&D)",
    "Die Überschrift des Rückblicks („Was bisher geschah“ bzw. „Previously“) fließt in die nächste Session ein – "
    "beibehalten.": "The heading of the recap (\"Previously\" or \"Was bisher geschah\") is carried into the next "
                    "session – keep it.",
    "Platzhalter {character} und {player}": "Placeholders {character} and {player}",
    "Speicher": "Storage",
    "Audiodateien und Uploads.": "Audio files and uploads.",
    "Speicherlimit für Audio": "Storage limit for audio",
    "Älteste Aufnahmen werden zuerst gelöscht (Transkripte bleiben). 0 = unbegrenzt.":
        "Oldest recordings are deleted first (transcripts stay). 0 = unlimited.",
    "beim nächsten Upload": "with the next upload",
    "Maximale Upload-Größe": "Maximum upload size",
    # Hinweise zu Whisper-Modellen (routes/health.py)
    "schnell, gut": "fast, good",
    "genauer, ca. 2× langsamer": "more accurate, about 2× slower",
    "genau, ca. 2× langsamer": "accurate, about 2× slower",
    "schneller, ungenauer": "faster, less accurate",
    "sehr schnell, deutlich ungenauer": "very fast, much less accurate",
})

EN.update({
    "Passwort falsch.": "Wrong password.",
    "Verbunden – Vaults: {vaults}": "Connected – vaults: {vaults}",
    "keine": "none",
    ". Fehlt: {missing}": ". Missing: {missing}",
    "Ollama erreichbar, aber Modell „{model}“ ist nicht installiert.":
        "Ollama reachable, but model \"{model}\" is not installed.",
    "Ollama erreichbar, aber kein Modell geladen.": "Ollama reachable, but no model loaded.",
    "Verbunden – Modell {model}, Kontext {n} Tokens": "Connected – model {model}, context {n} tokens",
})

LANGUAGES = ("de", "en")


def tr(language: str, text: str, **values) -> str:
    if language == "en":
        text = EN.get(text, text)
    return text.format(**values) if values else text
