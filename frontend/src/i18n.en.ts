/** Englische Texte der Oberfläche (Schlüssel = deutscher Text, siehe i18n.ts). Prüfen: npm run check-i18n */
export const EN: Record<string, string> = {
  // Allgemein
  'Lokale Transkription & Zusammenfassung': "Local transcription & summaries",
  'Aufnahmen': "Recordings",
  'DnD-Sessions': "D&D sessions",
  'Einstellungen': "Settings",
  'Abmelden': "Log out",
  'Anmelden': "Log in",
  'Passwort': "Password",
  'Prüfe …': "Checking …",
  'Dashboard-Passwort oder API-Schlüssel dieser WhisperNotes-Installation.':
    "Dashboard password or API key of this WhisperNotes installation.",
  'Abbrechen': "Cancel",
  'Schließen': "Close",
  'Speichern': "Save",
  'Entfernen': "Remove",
  'Bearbeiten': "Edit",
  'Löschen': "Delete",
  'Lade …': "Loading …",
  'auto': "auto",
  'automatisch': "automatic",
  'Standard': "Default",
  'Name': "Name",
  'Netzwerkfehler beim Upload': "Network error during upload",
  'Upload fehlgeschlagen ({status})': "Upload failed ({status})",
  'Laden fehlgeschlagen ({status})': "Loading failed ({status})",

  // Statusleiste
  'Whisper aktiv': "Whisper active",
  'Whisper startet': "Whisper starting",
  'Whisper im Ruhezustand': "Whisper idle",
  'Wrapper offline': "Server offline",
  '{n} wartend': "{n} waiting",
  'Ollama nicht erreichbar': "Ollama unreachable",
  'Ollama: kein Modell geladen': "Ollama: no model loaded",
  'Ollama: kein Modell geladen (Fallback: {model})': "Ollama: no model loaded (fallback: {model})",
  'Fest eingestelltes Modell für Zusammenfassungen ({model})': "Fixed model for summaries ({model})",
  'Für Zusammenfassungen wird das aktuell geladene Ollama-Modell genutzt':
    "Summaries use the Ollama model that is currently loaded",
  'Seit dem Start noch keine Anfrage': "No request since startup",
  'Letzte Anfrage vor {idle} s': "Last request {idle} s ago",
  'Letzte Anfrage vor {idle} s. Abschaltung nach {timeout} s Leerlauf':
    "Last request {idle} s ago. Stops after {timeout} s idle",
  'Bei Überschreitung wird das Audio der ältesten Aufnahmen gelöscht, Transkripte bleiben':
    "When exceeded, the audio of the oldest recordings is deleted; transcripts stay",
  'Kein Speicherlimit gesetzt': "No storage limit set",

  // Upload
  'Audiodatei hierher ziehen oder klicken': "Drop an audio file here or click",
  'MP3, M4A, WAV, OGG, FLAC … Lange Aufnahmen werden automatisch in Abschnitte geteilt.':
    "MP3, M4A, WAV, OGG, FLAC … Long recordings are split into parts automatically.",
  'Sprecher erkennen': "Detect speakers",
  'Anzahl': "Number",
  'Begriffe': "Terms",
  'Namen, Fachbegriffe … (verbessert die Schreibweise)': "Names, technical terms … (improves spelling)",
  'Tipp: Mit bekannter Sprecheranzahl ist die Erkennung deutlich zuverlässiger.':
    "Tip: detection is much more reliable when you know the number of speakers.",
  'Gilt für neue Uploads und „Neu transkribieren“': "Applies to new uploads and \"Re-transcribe\"",
  'Verlauf konnte nicht geladen werden: {error}': "Could not load the history: {error}",
  'Noch keine Aufnahmen. Lade oben eine Datei hoch.': "No recordings yet. Upload a file above.",

  // Job-Karte
  'Wartet': "Queued",
  'Analysiere': "Analysing",
  'Transkribiere': "Transcribing",
  'Sprecher zuordnen': "Assign speakers",
  'Fasse zusammen': "Summarising",
  'Fertig': "Done",
  'Fehler': "Error",
  'Abgebrochen': "Cancelled",
  'Wird abgebrochen …': "Cancelling …",
  '{n} Abschnitte': "{n} parts",
  '{n} Sprecher': "{n} speakers",
  'Stimmen automatisch erkannt': "Voices recognised automatically",
  'Über die gespeicherten Stimmen der Kampagne zugeordnet – falls falsch: „Sprecher benennen“':
    "Assigned using the campaign's saved voices – if wrong: \"Name speakers\"",
  'In Discord gepostet': "Posted in Discord",
  'Audio entfernt': "Audio removed",
  'Wegen des Speicherlimits entfernt, Transkript und Zusammenfassung bleiben':
    "Removed because of the storage limit; transcript and summary stay",
  '„{title}“ aus der Warteschlange nehmen?': "Remove \"{title}\" from the queue?",
  'Verarbeitung von „{title}“ abbrechen? Bisher Transkribiertes wird verworfen.':
    "Cancel processing \"{title}\"? Everything transcribed so far is discarded.",
  '{n} Stimmen erkannt. Ordne sie den Spielern zu, dann wird der Recap mit Namen erstellt.':
    "{n} voices detected. Assign them to the players and the recap is written with names.",
  'wird automatisch erneut versucht.': "will be retried automatically.",
  'Jetzt senden': "Send now",
  'Recap ansehen': "View recap",
  'Zusammenfassung ansehen': "View summary",
  'Transkript ansehen': "View transcript",
  'Recap': "Recap",
  'Zusammenfassung': "Summary",
  'Transkript': "Transcript",
  'Zusammenfassung herunterladen': "Download summary",
  'Transkript herunterladen': "Download transcript",
  'Transkript als Text herunterladen': "Download transcript as text",
  'Notiz in BasaltNotes öffnen': "Open note in BasaltNotes",
  'Spieler-Recaps': "Player recaps",
  'Welt & Lore (DM)': "World & lore (DM)",
  'Sprecher benennen': "Name speakers",
  'Neu zusammenfassen': "Summarise again",
  'Zusammenfassung starten': "Start summary",
  'Aufnahme komplett neu verarbeiten – Transkript und Zusammenfassung werden ersetzt':
    "Process the recording again from scratch – transcript and summary are replaced",
  '„{title}“ neu transkribieren': "Re-transcribe \"{title}\"",
  '? Transkript und Zusammenfassung werden ersetzt': "? Transcript and summary will be replaced",
  ', die Sprecher müssen neu zugeordnet werden.': ", and the speakers have to be assigned again.",
  'Neu transkribieren': "Re-transcribe",
  '„{title}“ endgültig löschen?': "Delete \"{title}\" permanently?",

  // Anzeige
  'Session-Recap': "Session recap",
  'Ab hier abspielen': "Play from here",
  'Kopieren': "Copy",
  'Kopiert ✓': "Copied ✓",
  'Nicht möglich': "Not possible",
  'Zeile anklicken = ab dort abspielen': "Click a line to play from there",
  'mitlaufen': "follow",
  'Audio konnte nicht abgespielt werden – Format vom Browser nicht unterstützt?':
    "Could not play the audio – format not supported by the browser?",

  // Sprecher
  'Lade erkannte Stimmen …': "Loading detected voices …",
  'Hörprobe konnte nicht geladen werden.': "Could not load the audio sample.",
  'Stimmtrennung: {pct} % der geprüften Stellen eindeutig zugeordnet.':
    "Voice separation: {pct} % of the checked passages clearly assigned.",
  'Einige Stimmen sind sich ähnlich – Hörproben genau anhören.':
    "Some voices are similar – listen to the samples carefully.",
  'Die Hörproben sind die für jede Stimme typischsten Stellen, ohne Überlappung mit anderen Sprechern.':
    "The samples are the most typical passages of each voice, without overlap with other speakers.",
  'Die Audiodatei wurde bereits gelöscht – Hörproben sind nicht verfügbar.':
    "The audio file has already been deleted – samples are not available.",
  'Stimme {id}': "Voice {id}",
  '{duration} Redezeit · {n} Beiträge': "{duration} speaking time · {n} turns",
  'Stimme ähnelt {name} ({pct} %)': "Voice resembles {name} ({pct} %)",
  '– nicht zugeordnet –': "– not assigned –",
  'Andere Person …': "Someone else …",
  'Stopp': "Stop",
  'Abspielen': "Play",
  'Übernehmen & Recap erstellen': "Apply & write recap",
  'Übernehmen & neu zusammenfassen': "Apply & summarise again",
  'Nur Transkript aktualisieren': "Only update transcript",
  'Ohne Zuordnung fortfahren': "Continue without assigning",

  // DnD
  'Lade Kampagnen …': "Loading campaigns …",
  'Lege eine Kampagne mit deiner Runde an. Beim Upload einer Session werden die Stimmen erkannt, du ordnest sie den Spielern zu und bekommst einen Session-Recap mit Handlung, NPCs, Beute und offenen Quests.':
    "Create a campaign with your group. When you upload a session, the voices are detected, you assign them to the players and get a session recap with story, NPCs, loot and open quests.",
  'Session {n}': "Session {n}",
  'Kampagne': "Campaign",
  'Neue Kampagne': "New campaign",
  'Noch keine Spieler eingetragen – „Bearbeiten“ ergänzt die Runde.':
    "No players yet – \"Edit\" adds your group.",
  'Stimme bekannt – wird automatisch zugeordnet': "Voice known – assigned automatically",
  'Stimme noch unbekannt': "Voice not known yet",
  'Gespeicherte Stimmen dieser Kampagne vergessen? Die nächste Session fragt wieder nach der Zuordnung.':
    "Forget the saved voices of this campaign? The next session will ask for the assignment again.",
  'Stimmen vergessen': "Forget voices",
  'Alle Stimmen sind bekannt – neue Sessions werden ohne Rückfrage zugeordnet.':
    "All voices are known – new sessions are assigned without asking.",
  'Nach der ersten Zuordnung merkt sich die Kampagne die Stimmen (🎙). Gefragt wird nur noch, wenn jemand neu dazukommt oder eine Stimme nicht eindeutig passt.':
    "After the first assignment the campaign remembers the voices (🎙). You are only asked again when someone new joins or a voice is not a clear match.",
  'Session': "Session",
  'Stimmen': "Voices",
  'Session-Aufnahme hierher ziehen oder klicken': "Drop a session recording here or click",
  'Stimmen werden erkannt und danach den Spielern zugeordnet.':
    "Voices are detected and then assigned to the players.",
  'Sessions': "Sessions",
  'Noch keine Sessions in dieser Kampagne.': "No sessions in this campaign yet.",

  // Kampagne bearbeiten
  'Kampagne bearbeiten': "Edit campaign",
  'z. B. Fluch des Strahd': "e.g. Curse of Strahd",
  'Runde': "Group",
  'Spieler:in': "Player",
  'Charakter': "Character",
  'Spieler': "Player",
  'Person hinzufügen': "Add person",
  'Die Anzahl der Personen wird als Sprecheranzahl für die Erkennung genutzt.':
    "The number of people is used as the number of speakers for detection.",
  'Glossar': "Glossary",
  'Orte, NPCs, Götter, Zauber … durch Komma getrennt': "Places, NPCs, gods, spells … separated by commas",
  'Hilft Whisper bei der Schreibweise von Fantasy-Namen und dem Recap bei der Einordnung. Übliche D&D-Begriffe (Attribute, Fertigkeiten, Initiative, Rüstungsklasse …) sind automatisch dabei – hier nur Eigenes eintragen. Kurz halten: Whisper berücksichtigt nur rund 500 Zeichen, Namen haben Vorrang.':
    "Helps Whisper spell fantasy names and the recap put them in context. Common D&D terms (abilities, skills, initiative, armor class …) are included automatically – only add your own here. Keep it short: Whisper only considers about 500 characters, names come first.",
  'Recap in Discord posten': "Post recap in Discord",
  '– nicht posten –': "– do not post –",
  'Channel {id} (aktuell nicht gemeldet)': "Channel {id} (not reported right now)",
  'Fertige Session-Recaps postet der WhisperNotes-Bot automatisch in diesen Channel.':
    "The WhisperNotes bot posts finished session recaps to this channel automatically.",
  'Noch keine Channels bekannt – sobald der Discord-Bot läuft, meldet er seine Channels hierher.':
    "No channels known yet – once the Discord bot is running, it reports its channels here.",
  'BasaltNotes-Vault': "BasaltNotes vault",
  '{vault} (in BasaltNotes nicht gefunden)': "{vault} (not found in BasaltNotes)",
  'Vaults nicht abrufbar: {error}': "Could not fetch vaults: {error}",
  'Hierhin gehen die Recaps dieser Kampagne; die Namen aus diesem Wiki verbessern die Erkennung.':
    "The recaps of this campaign go here; the names from this wiki improve recognition.",
  'Kampagne „{name}“ löschen? Die Sessions bleiben unter „Aufnahmen“ erhalten.':
    "Delete campaign \"{name}\"? The sessions stay under \"Recordings\".",
  'Kampagne löschen': "Delete campaign",

  // Einstellungen
  'Verbindung prüfen': "Test connection",
  'Ollama prüfen': "Test Ollama",
  'gesetzt': "set",
  'nicht gesetzt': "not set",
  'leer': "empty",
  'an': "on",
  'aus': "off",
  'Lade Einstellungen …': "Loading settings …",
  'Grundlage sind die Werte aus der Konfiguration (.env bzw. Umgebung). Was du hier änderst, wird zusätzlich gespeichert und hat Vorrang; „Zurücksetzen“ stellt wieder den Wert aus der Konfiguration her. Änderungen gelten sofort, sofern nicht anders angegeben.':
    "The values from the configuration (.env or environment) are the basis. What you change here is saved on top and takes precedence; \"Reset\" restores the configured value. Changes apply immediately unless stated otherwise.",
  'Erst speichern': "Save first",
  '{n} Einstellung(en) gespeichert': "{n} setting(s) saved",
  '„{label}“ zurückgesetzt': "\"{label}\" reset",
  '„{label}“ entfernt': "\"{label}\" removed",
  'Verwerfen': "Discard",
  'Speichere …': "Saving …",
  '{n} Änderung(en) speichern': "Save {n} change(s)",
  'Gespeichert': "Saved",
  '•••••••• (gesetzt – neu eingeben zum Ändern)': "•••••••• (set – enter a new one to change)",
  'Eingebaute Vorlage:': "Built-in template:",
  'Eingebaute Vorlage zum Bearbeiten übernehmen': "Copy the built-in template to edit it",
  'Eingebaute Vorlage verwenden': "Use the built-in template",
  'Im Dashboard geändert': "Changed in the dashboard",
  'geändert': "changed",
  'Wert aus der Konfiguration: {value}': "Configured value: {value}",
  'Zurücksetzen': "Reset",
  'gilt {when}': "applies {when}",
}
