#!/usr/bin/env bash
# SSH-Tunnel zu BasaltNotes (oder einem anderen Dienst im Heimnetz) einrichten – ohne sudo.
#
#   bash deploy/basalt_tunnel.sh nas.local 4400             # Ziel-Host und -Port (lokal: 127.0.0.1:4401)
#   bash deploy/basalt_tunnel.sh --remove                   # wieder entfernen
#
# Warum: macOS (ab 15) sperrt Programmen ohne Freigabe „Lokales Netzwerk“ den Zugriff auf andere Geräte im
# Heimnetz – auch dem Python von WhisperNotes, und auch Programmen, die es startet (curl) oder die launchd
# startet (nc). Ohne Bildschirm lässt sich die Freigabe nicht erteilen. Verbindungen, die der SSH-Dienst
# herstellt, sind nicht betroffen: Ein LaunchAgent hält deshalb
# `ssh -N -L 127.0.0.1:<lokal>:<host>:<port> <ich>@127.0.0.1` offen, und WhisperNotes spricht nur localhost an.
#
# Der Schlüssel ~/.ssh/whispernotes_tunnel darf ausschließlich zu <host>:<port> weiterleiten
# (authorized_keys: restrict,port-forwarding,permitopen=…,command=/usr/bin/false) – keine Anmeldung, keine Befehle.
# Voraussetzung: Entfernte Anmeldung (SSH) ist auf dem Mac eingeschaltet.
set -euo pipefail

LABEL="com.whispernotes.basalt-tunnel"
KEY="$HOME/.ssh/whispernotes_tunnel"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SERVICE="gui/$(id -u)/$LABEL"
AUTH="$HOME/.ssh/authorized_keys"

stop_agent() {
  launchctl bootout "$SERVICE" 2>/dev/null || true
  for _ in $(seq 1 20); do launchctl print "$SERVICE" >/dev/null 2>&1 || break; sleep 0.5; done
}

if [[ "${1:-}" == "--remove" ]]; then
  stop_agent
  rm -f "$PLIST"
  [[ -f "$AUTH" ]] && sed -i '' '/whispernotes-tunnel$/d' "$AUTH"
  rm -f "$KEY" "$KEY.pub"
  echo "Tunnel entfernt. In den WhisperNotes-Einstellungen wieder die direkte BasaltNotes-Adresse eintragen."
  exit 0
fi

HOST="${1:?Ziel-Host angeben, z. B. nas.local}"
PORT="${2:-4400}"
LOCAL_PORT="${3:-4401}"

mkdir -p "$HOME/.ssh" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs/whispernotes"
chmod 700 "$HOME/.ssh"
[[ -f "$KEY" ]] || ssh-keygen -q -t ed25519 -N "" -f "$KEY" -C whispernotes-tunnel
chmod 600 "$KEY"
touch "$AUTH" && chmod 600 "$AUTH"
[[ -f "$AUTH.bak-whispernotes" ]] || cp "$AUTH" "$AUTH.bak-whispernotes"
# Eintrag (neu) schreiben – bei geändertem Ziel wird der alte ersetzt
sed -i '' '/whispernotes-tunnel$/d' "$AUTH"
echo "restrict,port-forwarding,permitopen=\"$HOST:$PORT\",command=\"/usr/bin/false\" $(cat "$KEY.pub")" >> "$AUTH"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/ssh</string><string>-N</string>
    <string>-i</string><string>$KEY</string>
    <string>-o</string><string>IdentitiesOnly=yes</string>
    <string>-o</string><string>BatchMode=yes</string>
    <string>-o</string><string>ExitOnForwardFailure=yes</string>
    <string>-o</string><string>ServerAliveInterval=30</string>
    <string>-o</string><string>StrictHostKeyChecking=accept-new</string>
    <string>-L</string><string>127.0.0.1:$LOCAL_PORT:$HOST:$PORT</string>
    <string>$(id -un)@127.0.0.1</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/whispernotes/basalt-tunnel.log</string>
</dict>
</plist>
EOF

stop_agent
launchctl bootstrap "gui/$(id -u)" "$PLIST"
for _ in $(seq 1 20); do
  nc -z 127.0.0.1 "$LOCAL_PORT" 2>/dev/null && break
  sleep 0.5
done
if nc -z 127.0.0.1 "$LOCAL_PORT" 2>/dev/null; then
  echo "Tunnel läuft: http://127.0.0.1:$LOCAL_PORT → http://$HOST:$PORT"
  echo "In WhisperNotes → Einstellungen → BasaltNotes: Adresse http://127.0.0.1:$LOCAL_PORT,"
  echo "Adresse für Links http://$HOST:$PORT"
else
  echo "Tunnel nicht erreichbar – siehe ~/Library/Logs/whispernotes/basalt-tunnel.log"
  exit 1
fi
