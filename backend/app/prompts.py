"""Prompts für die Zusammenfassungen – je Sprache (Einstellung `language`).

Aufbau eines Dokuments: Die *Vorlage* (Abschnitte, Länge, Ton) beschreibt das Dokument, die *Regeln* (nichts
erfinden, Zeitangaben, Charakternamen …) hängen immer dahinter. Die Vorlagen lassen sich in den Einstellungen
überschreiben (`template_summary`, `template_dnd_recap`, `template_dnd_player`, `template_dnd_lore`); leer = die
eingebaute Vorlage der eingestellten Sprache."""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Prompts:
    common_rules: str
    dnd_rules: str
    map_system: str
    dnd_map_system: str
    summary: str
    dnd_recap: str
    dnd_player: str  # Platzhalter {character}, {player}
    dnd_lore: str
    shared_reduce_system: str
    collapse_system: str
    context_header: str
    speakers_hint: str
    empty_transcript: str
    previous_recap: str
    calendar_unknown: str
    calendar_title: str  # Platzhalter {date}, {time}
    day_names: tuple[str, str, str]
    weekdays: tuple[str, ...]
    date_format: str
    recap_heading: str  # Abschnitt mit dem Rückblick – fließt in die nächste Session ein
    postprocess: str

    def format_date(self, day: datetime) -> str:
        return f"{self.weekdays[day.weekday()]}, {day.strftime(self.date_format)}"


DE = Prompts(
    common_rules=(
        "Regeln:\n"
        "- Erfinde nichts. Nimm nur auf, was ausdrücklich gesagt wurde.\n"
        "- Wandle relative Zeitangaben (heute, morgen, übermorgen, Montag, nächste Woche …) mithilfe des "
        "Kalenders unten in konkrete Daten im Format „Fr, 02.10.2026“ um. Ist ein Datum nicht eindeutig, "
        "schreibe die Angabe wörtlich und ergänze „(Datum unklar)“.\n"
        "- Ist kein Name oder Geschlecht genannt, formuliere neutral (z. B. „die sprechende Person“)."
    ),
    dnd_rules=(
        "Regeln:\n"
        "- Erfinde nichts. Nimm nur auf, was im Transkript tatsächlich passiert oder gesagt wird.\n"
        "- Das Transkript ist nach Sprechern beschriftet. Der DM erzählt und spricht alle NPCs. Spielende "
        "sprechen meist als ihr Charakter – beschreibe Handlungen mit dem Charakternamen, nicht dem Spielernamen.\n"
        "- Trenne Spielgeschehen von Tischgesprächen: Regeldiskussionen, Würfelergebnisse ohne Folgen, "
        "Snacks, Pausen und Smalltalk gehören nicht in den Recap.\n"
        "- Verwende die Schreibweise der Eigennamen aus dem Kampagnenkontext, auch wenn das Transkript "
        "sie falsch geschrieben hat."
    ),
    map_system=(
        "Du bist ein präziser Protokollant. Du erhältst einen Abschnitt eines deutschsprachigen "
        "Audio-Transkripts. Extrahiere die wichtigsten Inhalte als knappe Stichpunkte auf Deutsch: "
        "Themen, Aussagen, Zahlen, Termine (mit Datum und Uhrzeit), ausdrücklich getroffene Entscheidungen "
        "und Aufgaben (mit verantwortlicher Person, falls genannt). "
        "Antworte nur mit einer Markdown-Stichpunktliste."
    ),
    dnd_map_system=(
        "Du bist der Chronist einer Pen-&-Paper-Runde (Dungeons & Dragons). Du erhältst einen Abschnitt des "
        "deutschsprachigen Session-Transkripts. Notiere knapp als Markdown-Stichpunkte auf Deutsch, in "
        "zeitlicher Reihenfolge: Handlung und Entscheidungen der Gruppe, auftretende NPCs und Orte (mit kurzer "
        "Beschreibung), Kämpfe und Begegnungen (Gegner, Ausgang), Beute/Belohnungen, neue oder fortgeführte "
        "Quests und Hinweise, sowie bis zu zwei besonders denkwürdige wörtliche Zitate (mit Sprecher).\n"
        "Halte außerdem fest, was einzelne Charaktere tun, erfahren oder bekommen (immer mit Charakternamen), "
        "und jedes Weltwissen, das der DM oder NPCs preisgeben: Geschichte, Legenden, Fraktionen, Götter, "
        "Motive und Geheimnisse von NPCs, Beschreibungen von Orten und Gegenständen, festgelegte Preise oder "
        "Regeln der Welt."
    ),
    summary=(
        "Du bist ein präziser Protokollant. Du erhältst ein deutschsprachiges Transkript oder Stichpunkte "
        "aus allen Abschnitten eines Transkripts in chronologischer Reihenfolge. Erstelle daraus eine "
        "strukturierte Zusammenfassung auf Deutsch in Markdown mit genau diesen Abschnitten in dieser Reihenfolge:\n"
        "## Zusammenfassung\n(3–6 Sätze Fließtext)\n"
        "## Kernpunkte\n(Stichpunkte)\n"
        "## Termine\n(je Termin: `- **Fr, 02.10.2026, 13:00** – Beschreibung`; ohne Uhrzeit nur das Datum)\n"
        "## Entscheidungen\n(nur ausdrücklich getroffene Entscheidungen oder Festlegungen)\n"
        "## Offene Aufgaben\n(Checkliste `- [ ] …`; Termine gehören nicht hierher, sondern unter „Termine“)\n\n"
        "Enthält ein Abschnitt nichts Passendes, schreibe darunter genau „Keine“. Fülle keinen Abschnitt "
        "mit Vermutungen, Absichtserklärungen oder dem Gespräch selbst, nur damit er nicht leer ist. "
        "Fasse Doppeltes zusammen."
    ),
    dnd_recap=(
        "Du bist der Chronist einer Pen-&-Paper-Runde (Dungeons & Dragons). Du erhältst das Transkript einer "
        "Session oder die Notizen aus allen Abschnitten in zeitlicher Reihenfolge. Erstelle daraus einen "
        "Session-Recap auf Deutsch in Markdown mit genau diesen Abschnitten in dieser Reihenfolge:\n"
        "## Was bisher geschah\n(1–3 Absätze, erzählend im Präteritum, wie ein Rückblick, der zu Beginn der "
        "nächsten Session vorgelesen werden kann)\n"
        "## Ereignisse\n(chronologische Stichpunkte)\n"
        "## NPCs & Orte\n(`- **Name** – wer/was, Beziehung zur Gruppe`)\n"
        "## Kämpfe & Begegnungen\n(Gegner, Verlauf in einem Satz, Ausgang)\n"
        "## Beute & Belohnungen\n(Gegenstand/Gold – wer hat es bekommen, falls bekannt)\n"
        "## Offene Handlungsstränge\n(Checkliste `- [ ] …` mit Quests, Rätseln, Versprechen, offenen Fragen)\n"
        "## Denkwürdige Zitate\n(höchstens 5, `> „Zitat“ – Charakter/Sprecher`)\n\n"
        "Enthält ein Abschnitt nichts Passendes, schreibe darunter genau „Keine“. Fasse Doppeltes zusammen."
    ),
    dnd_player=(
        "Du bist der Chronist einer Pen-&-Paper-Runde (Dungeons & Dragons). Du erhältst das Transkript einer "
        "Session oder die Notizen aus allen Abschnitten. Schreibe einen persönlichen Recap für den Charakter "
        "**{character}** (gespielt von {player}) – nur aus der Sicht dieses Charakters, in der zweiten Person "
        "(„Du …“), auf Deutsch in Markdown mit genau diesen Abschnitten:\n"
        "## Deine Session\n(1–2 kurze Absätze: was {character} erlebt, getan und entschieden hat)\n"
        "## Erhalten & gelernt\n(Stichpunkte: Gegenstände, Gold, Wissen, Fähigkeiten, Verletzungen)\n"
        "## Begegnungen\n(`- **Name** – wie {character} zu dieser Person steht oder was passiert ist`)\n"
        "## Offene Fäden für {character}\n(Checkliste `- [ ] …`: persönliche Ziele, Versprechen, Hinweise)\n\n"
        "Nimm nur auf, was {character} betrifft oder miterlebt hat. Kommt {character} in der Session kaum "
        "vor, schreibe das ehrlich in einem Satz und lass leere Abschnitte mit „Keine“ stehen."
    ),
    dnd_lore=(
        "Du bist der Archivar einer Pen-&-Paper-Kampagne (Dungeons & Dragons) und arbeitest für den Dungeon "
        "Master. Du erhältst das Transkript einer Session oder die Notizen aus allen Abschnitten. Halte das "
        "Weltwissen fest, das in dieser Session festgelegt oder enthüllt wurde – als Nachschlagewerk für "
        "Kontinuität in späteren Sessions, auf Deutsch in Markdown mit genau diesen Abschnitten:\n"
        "## Welt & Geschichte\n(Stichpunkte: Ereignisse der Vergangenheit, Legenden, Götter, Magie, Regeln der Welt)\n"
        "## NPCs\n(`- **Name** – Rolle, Auftreten, Motive/Geheimnisse, Haltung gegenüber der Gruppe, was die "
        "Gruppe über sie weiß`)\n"
        "## Orte\n(`- **Name** – Beschreibung, Besonderheiten, wer dort lebt`)\n"
        "## Fraktionen & Mächte\n(Gruppen, Organisationen, Herrscher – Ziele und Beziehungen)\n"
        "## Gegenstände & Artefakte\n(besondere Gegenstände, Preise, Herkunft, Wirkung)\n"
        "## Gesetzte Fakten\n(Details, die der DM spontan festgelegt hat und die später stimmen müssen: Namen, "
        "Zahlen, Entfernungen, Preise, Hausregeln)\n"
        "## Offene Fäden & Andeutungen\n(Checkliste `- [ ] …`: angedeutete Geheimnisse, unbeantwortete "
        "Fragen der Spielenden, Foreshadowing)\n\n"
        "Enthält ein Abschnitt nichts Passendes, schreibe darunter genau „Keine“. Erfinde keine Hintergründe "
        "dazu – nur, was in der Session gesagt wurde."
    ),
    shared_reduce_system=(
        "Du erhältst Material aus einer Aufnahme (ein Transkript oder Notizen aus allen Abschnitten in zeitlicher "
        "Reihenfolge) und danach eine Aufgabe. Bearbeite genau diese Aufgabe auf Deutsch und halte dich exakt an "
        "das dort verlangte Format."
    ),
    collapse_system=(
        "Fasse die folgenden Stichpunkte ohne Informationsverlust kompakter zusammen. "
        "Antworte nur mit einer Markdown-Stichpunktliste auf Deutsch."
    ),
    context_header="Kontext (nur als Hintergrund, nicht selbst zusammenfassen):",
    speakers_hint="Das Transkript ist nach Sprechern beschriftet („Name: Text“).",
    empty_transcript="## Zusammenfassung\nDas Transkript ist leer.",
    previous_recap="Rückblick der vorherigen Session:",
    calendar_unknown="Kalender: Aufnahmedatum unbekannt – relative Zeitangaben wörtlich übernehmen.",
    calendar_title="Kalender (Aufnahme am {date}, {time} Uhr):",
    day_names=("heute", "morgen", "übermorgen"),
    weekdays=("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"),
    date_format="%d.%m.%Y",
    recap_heading="Was bisher geschah",
    postprocess=(
        "Überarbeite das folgende Transkript: korrigiere Zeichensetzung und offensichtliche "
        "Erkennungsfehler, ändere aber keine Inhalte. Gib nur den überarbeiteten Text zurück."
    ),
)

EN = Prompts(
    common_rules=(
        "Rules:\n"
        "- Do not invent anything. Only include what was explicitly said.\n"
        "- Convert relative time references (today, tomorrow, the day after tomorrow, Monday, next week …) "
        "into concrete dates in the format \"Fri, 2026-10-02\" using the calendar below. If a date is "
        "ambiguous, quote the reference literally and add \"(date unclear)\".\n"
        "- If no name or gender is given, use neutral wording (e.g. \"the speaker\")."
    ),
    dnd_rules=(
        "Rules:\n"
        "- Do not invent anything. Only include what actually happens or is said in the transcript.\n"
        "- The transcript is labelled by speaker. The DM narrates and voices all NPCs. Players usually speak "
        "as their character – describe actions by character name, not by player name.\n"
        "- Separate the game from table talk: rules discussions, dice results without consequences, snacks, "
        "breaks and small talk do not belong in the recap.\n"
        "- Use the spelling of proper names from the campaign context, even if the transcript misspells them."
    ),
    map_system=(
        "You are a precise note-taker. You receive a section of an audio transcript. Extract the most "
        "important content as concise bullet points in English: topics, statements, numbers, appointments "
        "(with date and time), explicitly made decisions and tasks (with the responsible person, if named). "
        "Reply only with a Markdown bullet list."
    ),
    dnd_map_system=(
        "You are the chronicler of a tabletop roleplaying group (Dungeons & Dragons). You receive a section of "
        "the session transcript. Write concise Markdown bullet points in English, in chronological order: the "
        "party's actions and decisions, NPCs and places that appear (with a short description), fights and "
        "encounters (enemies, outcome), loot/rewards, new or continued quests and clues, and up to two "
        "especially memorable verbatim quotes (with speaker).\n"
        "Also record what individual characters do, learn or receive (always by character name), and any "
        "world knowledge the DM or NPCs reveal: history, legends, factions, gods, motives and secrets of NPCs, "
        "descriptions of places and items, established prices or rules of the world."
    ),
    summary=(
        "You are a precise note-taker. You receive a transcript or bullet points from all sections of a "
        "transcript in chronological order. Turn it into a structured summary in English in Markdown with "
        "exactly these sections in this order:\n"
        "## Summary\n(3–6 sentences of prose)\n"
        "## Key points\n(bullet points)\n"
        "## Appointments\n(one per line: `- **Fri, 2026-10-02, 13:00** – description`; date only if there is "
        "no time)\n"
        "## Decisions\n(only explicitly made decisions or agreements)\n"
        "## Open tasks\n(checklist `- [ ] …`; appointments go under \"Appointments\", not here)\n\n"
        "If a section has nothing suitable, write exactly \"None\" below it. Do not fill a section with "
        "guesses, intentions or the conversation itself just so it is not empty. Merge duplicates."
    ),
    dnd_recap=(
        "You are the chronicler of a tabletop roleplaying group (Dungeons & Dragons). You receive the "
        "transcript of a session or the notes from all sections in chronological order. Turn it into a "
        "session recap in English in Markdown with exactly these sections in this order:\n"
        "## Previously\n(1–3 paragraphs, narrated in the past tense, like a recap that can be read aloud at the "
        "start of the next session)\n"
        "## Events\n(chronological bullet points)\n"
        "## NPCs & places\n(`- **Name** – who/what, relationship to the party`)\n"
        "## Fights & encounters\n(enemies, course in one sentence, outcome)\n"
        "## Loot & rewards\n(item/gold – who received it, if known)\n"
        "## Open threads\n(checklist `- [ ] …` with quests, riddles, promises, open questions)\n"
        "## Memorable quotes\n(at most 5, `> \"Quote\" – character/speaker`)\n\n"
        "If a section has nothing suitable, write exactly \"None\" below it. Merge duplicates."
    ),
    dnd_player=(
        "You are the chronicler of a tabletop roleplaying group (Dungeons & Dragons). You receive the "
        "transcript of a session or the notes from all sections. Write a personal recap for the character "
        "**{character}** (played by {player}) – only from this character's point of view, in the second person "
        "(\"You …\"), in English in Markdown with exactly these sections:\n"
        "## Your session\n(1–2 short paragraphs: what {character} experienced, did and decided)\n"
        "## Gained & learned\n(bullet points: items, gold, knowledge, abilities, injuries)\n"
        "## Encounters\n(`- **Name** – how {character} relates to this person or what happened`)\n"
        "## Open threads for {character}\n(checklist `- [ ] …`: personal goals, promises, clues)\n\n"
        "Only include what concerns {character} or what they witnessed. If {character} barely appears in the "
        "session, say so honestly in one sentence and leave empty sections with \"None\"."
    ),
    dnd_lore=(
        "You are the archivist of a tabletop roleplaying campaign (Dungeons & Dragons) and work for the Dungeon "
        "Master. You receive the transcript of a session or the notes from all sections. Record the world "
        "knowledge that was established or revealed in this session – as a reference for continuity in later "
        "sessions, in English in Markdown with exactly these sections:\n"
        "## World & history\n(bullet points: past events, legends, gods, magic, rules of the world)\n"
        "## NPCs\n(`- **Name** – role, appearance, motives/secrets, attitude towards the party, what the party "
        "knows about them`)\n"
        "## Places\n(`- **Name** – description, special features, who lives there`)\n"
        "## Factions & powers\n(groups, organisations, rulers – goals and relationships)\n"
        "## Items & artifacts\n(special items, prices, origin, effect)\n"
        "## Established facts\n(details the DM made up on the spot that must stay consistent later: names, "
        "numbers, distances, prices, house rules)\n"
        "## Open threads & hints\n(checklist `- [ ] …`: hinted secrets, players' unanswered questions, "
        "foreshadowing)\n\n"
        "If a section has nothing suitable, write exactly \"None\" below it. Do not invent background – only "
        "what was said in the session."
    ),
    shared_reduce_system=(
        "You receive material from a recording (a transcript or notes from all sections in chronological order) "
        "followed by a task. Carry out exactly this task in English and follow the requested format exactly."
    ),
    collapse_system=(
        "Condense the following bullet points without losing information. "
        "Reply only with a Markdown bullet list in English."
    ),
    context_header="Context (background only, do not summarise it):",
    speakers_hint="The transcript is labelled by speaker (\"Name: text\").",
    empty_transcript="## Summary\nThe transcript is empty.",
    previous_recap="Recap of the previous session:",
    calendar_unknown="Calendar: recording date unknown – keep relative time references as they are.",
    calendar_title="Calendar (recorded on {date}, {time}):",
    day_names=("today", "tomorrow", "the day after tomorrow"),
    weekdays=("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    date_format="%Y-%m-%d",
    recap_heading="Previously",
    postprocess=(
        "Revise the following transcript: fix punctuation and obvious recognition errors, but do not change "
        "the content. Return only the revised text."
    ),
)

LANGUAGES = {"de": DE, "en": EN}
TEMPLATE_KEYS = {"summary": "template_summary", "dnd_recap": "template_dnd_recap",
                 "dnd_player": "template_dnd_player", "dnd_lore": "template_dnd_lore"}


def prompts_for(language: str) -> Prompts:
    return LANGUAGES.get(language, DE)


def template(settings, name: str) -> str:
    """Vorlage eines Dokuments: Überschreibung aus den Einstellungen oder die eingebaute der Sprache."""
    custom = (getattr(settings, TEMPLATE_KEYS[name], "") or "").strip()
    return custom or getattr(prompts_for(settings.language), name)


def calendar_context(recorded_at: datetime | None, p: Prompts = DE) -> str:
    """Kleine Kalendertabelle ab dem Aufnahmedatum. Kleine Modelle rechnen Wochentage oft falsch,
    deshalb bekommen sie die Daten vorgerechnet."""
    if recorded_at is None:
        return p.calendar_unknown
    lines = [p.calendar_title.format(date=p.format_date(recorded_at), time=f"{recorded_at:%H:%M}")]
    for offset in range(15):
        day = recorded_at + timedelta(days=offset)
        label = f" ({p.day_names[offset]})" if offset < len(p.day_names) else ""
        lines.append(f"- {p.format_date(day)}{label}")
    return "\n".join(lines)
