#!/usr/bin/env bash
# WhisperNotes neu starten – egal ob als LaunchAgent oder LaunchDaemon (install_daemon.sh) eingerichtet.
#
#   bash deploy/restart.sh
#
# Beim Daemon ohne sudo: Der Prozess läuft als dein Benutzer, darf also von dir beendet werden; launchd
# startet ihn wegen KeepAlive sofort neu.
set -euo pipefail

LABEL="com.whispernotes"

if [[ -f "/Library/LaunchDaemons/$LABEL.plist" ]]; then
  old="$(pgrep -f "uvicorn app.main:app" || true)"
  [[ -n "$old" ]] && kill -TERM $old 2>/dev/null || true
  for _ in $(seq 1 60); do  # warten, bis der alte Prozess wirklich weg ist (beendet auch whisper-server)
    alive=0
    for pid in $old; do kill -0 "$pid" 2>/dev/null && alive=1; done
    [[ $alive == 0 ]] && break
    sleep 0.5
  done
else
  launchctl kickstart -k "gui/$(id -u)/$LABEL"
fi

for _ in $(seq 1 60); do
  curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fsS http://127.0.0.1:8000/health && echo || {
  echo "WhisperNotes antwortet nicht – siehe ~/Library/Logs/whispernotes/wrapper.log"
  exit 1
}
