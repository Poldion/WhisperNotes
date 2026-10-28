# Funktionsspezifikation: Whisper.cpp FastAPI-Wrapper

Dieses Dokument definiert alle technischen und prozessualen Anforderungen an den Python-basierten API-Wrapper, der als intelligentes Bindeglied zwischen Discord, Home Assistant, lokaler Audio-Hardware, einer Web-UI und dem ressourcenintensiven Whisper-Modell fungiert.

## 1. API-Schnittstellen & Routing
Der Wrapper agiert als HTTP-Server (via FastAPI) und stellt standardisierte Schnittstellen bereit, um maximale Kompatibilität mit bestehenden Systemen zu gewährleisten.

* **OpenAI-Kompatibilitäts-Endpunkt (`POST /v1/audio/transcriptions`):** 
  * Nimmt Audio-Dateien im `multipart/form-data`-Format entgegen.
  * Ignoriert Authentifizierungs-Header (Dummy-API-Keys werden akzeptiert).
  * Erwartet Felder wie `file` (die Audiodatei) und optional `model` (wird systemseitig ignoriert und auf das lokale Modell umgeleitet).
  * Gibt das fertige Transkript im exakten OpenAI-JSON-Format zurück: `{"text": "Transkribierter Text"}`.
* **System-Status-Endpunkt (`GET /health`):**
  * Gibt Auskunft über den aktuellen Status des Wrappers (Online/Offline).
  * Zeigt den aktuellen Status des Whisper-Prozesses (Aktiv/Inaktiv) sowie die Zeit seit dem letzten Request.

## 2. Dynamisches Prozess- & Ressourcenmanagement
Um den Unified Memory des Mac Mini nicht dauerhaft zu blockieren und ausreichend Kapazitäten für Ollama freizuhalten, steuert der Wrapper den Lebenszyklus des Whisper-Servers intelligent.

* **On-Demand Initialisierung (Cold Start):**
  * Prüft bei jedem eingehenden Request, ob der Prozess `whisper-server` bereits läuft.
  * Falls inaktiv: Startet den Prozess via Python `subprocess` asynchron im Hintergrund (unter Einbezug der Metal-Beschleunigung `GGML_METAL=1`).
* **Readiness-Check:**
  * Blockiert eingehende API-Requests so lange (ca. 1-2 Sekunden), bis der lokale Whisper-Server auf seinem internen Port meldet, dass das Modell vollständig in den RAM geladen ist.
* **Idle-Timer & Garbage Collection:**
  * Implementiert eine asynchrone Hintergrundschleife.
  * Aktualisiert bei jedem API-Aufruf einen globalen Zeitstempel (`last_activity`).
  * Sendet nach Überschreiten des konfigurierten Schwellenwerts (z. B. 120 Sekunden Inaktivität) ein `SIGTERM`-Signal an den Whisper-Prozess, um den Arbeitsspeicher (ca. 1,5 GB) sofort wieder freizugeben.

## 3. Proxy-Logik & Datenverarbeitung
Der Wrapper reicht Daten nicht nur durch, sondern bereitet sie für den lokalen Whisper-Server auf.

* **Audio-Pufferung:** Nimmt die von Discord oder Home Assistant eingehenden Audiodaten temporär in den Arbeitsspeicher auf, ohne sie zwingend auf die Festplatte schreiben zu müssen (vermeidet unnötige SSD-Schreibzyklen).
* **Format-Validierung:** Prüft, ob das eingehende Format von `whisper.cpp` unterstützt wird (üblicherweise `.wav` mit 16 kHz). Bei abweichenden Formaten (wie OGG von Home Assistant) wird ein lokaler FFmpeg-Aufruf zur On-the-fly-Konvertierung zwischengeschaltet.
* **Request-Weiterleitung:** Sendet die aufbereiteten Audiodaten via internem HTTP-POST-Request an den lokal laufenden `whisper-server` (localhost:8080).
* **Response-Transformation:** Empfängt die rohen Textausgaben von Whisper und verpackt diese in das von den Clients erwartete JSON-Schema.

## 4. Fehlerbehandlung & Fallbacks
* **Timeout-Handling:** Bricht die Weiterleitung an Whisper ab, falls der Unterprozess blockiert oder abstürzt, und sendet einen sauberen HTTP 500 Fehler an den Client zurück.
* **Concurrency Control (Warteschlange):** Da `whisper.cpp` Anfragen am besten sequenziell abarbeitet, implementiert der Wrapper einen Semaphor oder eine Queue. Zeitgleiche Audio-Chunks werden sauber nacheinander an den Whisper-Prozess durchgereicht.
* **Zombie-Prozess-Prävention:** Stellt sicher, dass beim Beenden des FastAPI-Wrappers auch der angehängte `whisper-server` Unterprozess zwingend beendet wird, um Speicherlecks zu vermeiden.

## 5. Zukünftige Schnittstellen (Modul-Vorbereitung)
* **Hook für NLP-Postprocessing:** Einbau eines optionalen Triggers, der nach erfolgreicher Transkription das Dokument an den lokalen Ollama-Endpunkt weiterreicht.
* **Metadaten-Passthrough:** Möglichkeit, Parameter wie "Sprechername" oder "Zeitstempel" in den Headern der Requests mitzugeben, sodass der Wrapper diese für spätere Logbuch-Formatierungen zwischenspeichern kann.

## 6. Integrierte Weboberfläche (Frontend & Batch-Processing)
Der Wrapper beinhaltet ein webbasiertes Dashboard als zentralen Hub für manuelle Uploads und nachträgliche Auswertungen von längeren Aufnahmen.

* **Bereitstellung des Frontends (Web-UI):**
  * Hosting einer grafischen Benutzeroberfläche direkt über den Wrapper (z. B. `GET /dashboard`).
  * Drag-and-Drop-Feld für den Upload gängiger Audioformate (MP3, M4A, WAV).
  * Echtzeit-Feedback zum Verarbeitungsstatus (Progress Bar).
* **Serverseitiges Audio-Slicing (Pre-Processing):**
  * Automatische Prüfung der Dateilänge nach dem Upload.
  * Zerteilen von großen Dateien in optimale, überschneidende Chunks (z. B. 3 bis 5 Minuten) mittels FFmpeg, damit der RAM-Bedarf von Whisper nicht skaliert.
* **Sequenzielle Transkriptions-Warteschlange:**
  * Übergabe der generierten Audio-Chunks nacheinander an den lokal laufenden `whisper-server`.
  * Zusammenführung der einzelnen Chunk-Ergebnisse zu einem chronologischen Master-Dokument im Hintergrund.
* **KI-Pipeline & Map-Reduce-Integration:**
  * Direkte Anbindung an die lokale Ollama-Instanz.
  * Übergabe des Master-Dokuments an den definierten Map-Reduce-Workflow, sobald die Transkription abgeschlossen ist, um strukturierte Key-Points und eine Summary zu generieren.
* **Download & Export-Management:**
  * Bereitstellung von zwei getrennten Download-Optionen im Dashboard:
    1. Das vollständige Rohtranskript (als `.txt` oder `.md`).
    2. Die strukturierte KI-Zusammenfassung (als `.md` für einfachen Import in Notiz-Apps).