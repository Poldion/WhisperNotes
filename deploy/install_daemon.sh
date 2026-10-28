#!/usr/bin/env bash
# WhisperNotes als LaunchDaemon statt LaunchAgent betreiben (läuft weiter als dein Benutzer).
#
#   sudo bash deploy/install_daemon.sh
#
# Warum: Seit macOS 15 brauchen Programme die Freigabe „Lokales Netzwerk“, um andere Geräte im Heimnetz
# (z. B. BasaltNotes auf dem NAS) zu erreichen. Einem LaunchAgent zeigt macOS dafür oft keine Rückfrage an,
# und ohne Bildschirm lässt sich die Freigabe nicht erteilen. launchd-Daemons sind von dieser Sperre
# ausgenommen (wie per SSH gestartete Prozesse).
#
# Rückweg: sudo bash deploy/install_daemon.sh --uninstall  (danach bash deploy/setup_mac.sh)
set -euo pipefail

LABEL="com.whispernotes"
DAEMON_PLIST="/Library/LaunchDaemons/$LABEL.plist"

[[ "$(uname -s)" == "Darwin" ]] || { echo "Dieses Skript ist für macOS gedacht."; exit 1; }
[[ $EUID -eq 0 ]] || { echo "Bitte mit sudo ausführen: sudo bash $0"; exit 1; }
TARGET_USER="${SUDO_USER:-}"
[[ -n "$TARGET_USER" && "$TARGET_USER" != "root" ]] || { echo "Bitte als normaler Benutzer mit sudo starten (nicht als root)."; exit 1; }

TARGET_UID="$(id -u "$TARGET_USER")"
TARGET_GROUP="$(id -gn "$TARGET_USER")"
TARGET_HOME="$(dscl . -read "/Users/$TARGET_USER" NFSHomeDirectory | awk '{print $2}')"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_PLIST="$TARGET_HOME/Library/LaunchAgents/$LABEL.plist"

wait_gone() {  # bootout arbeitet asynchron
  for _ in $(seq 1 40); do
    launchctl print "$1" >/dev/null 2>&1 || return 0
    sleep 0.5
  done
}

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl bootout "system/$LABEL" 2>/dev/null || true
  wait_gone "system/$LABEL"
  rm -f "$DAEMON_PLIST"
  echo "LaunchDaemon entfernt. Zum Zurückwechseln auf den LaunchAgent: bash deploy/setup_mac.sh (ohne sudo)"
  exit 0
fi

BREW_PREFIX="$(sudo -u "$TARGET_USER" -i bash -lc 'brew --prefix' 2>/dev/null || echo /opt/homebrew)"
UV_BIN="$(sudo -u "$TARGET_USER" -i bash -lc 'command -v uv' 2>/dev/null || true)"
[[ -x "$UV_BIN" ]] || UV_BIN="$BREW_PREFIX/bin/uv"
[[ -x "$UV_BIN" ]] || { echo "uv nicht gefunden – erst bash deploy/setup_mac.sh ausführen."; exit 1; }

echo "==> LaunchAgent von $TARGET_USER beenden"
launchctl bootout "gui/$TARGET_UID/$LABEL" 2>/dev/null || true
wait_gone "gui/$TARGET_UID/$LABEL"
rm -f "$AGENT_PLIST"  # sonst startet er beim nächsten Login wieder (und belegt Port 8000)

echo "==> LaunchDaemon $DAEMON_PLIST (läuft als $TARGET_USER)"
mkdir -p "$TARGET_HOME/Library/Logs/whispernotes"
chown "$TARGET_USER:$TARGET_GROUP" "$TARGET_HOME/Library/Logs/whispernotes"
sed -e "s|__REPO__|$REPO_DIR|g" -e "s|__UV__|$UV_BIN|g" -e "s|__HOME__|$TARGET_HOME|g" -e "s|__BREW__|$BREW_PREFIX|g" \
    "$REPO_DIR/deploy/$LABEL.plist" > "$DAEMON_PLIST.tmp"
# Benutzer, Gruppe und HOME ergänzen (ein Daemon läuft sonst als root ohne HOME)
/usr/libexec/PlistBuddy -c "Add :UserName string $TARGET_USER" "$DAEMON_PLIST.tmp"
/usr/libexec/PlistBuddy -c "Add :GroupName string $TARGET_GROUP" "$DAEMON_PLIST.tmp"
/usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:HOME string $TARGET_HOME" "$DAEMON_PLIST.tmp"
/usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:USER string $TARGET_USER" "$DAEMON_PLIST.tmp"
chown root:wheel "$DAEMON_PLIST.tmp"
chmod 644 "$DAEMON_PLIST.tmp"
mv "$DAEMON_PLIST.tmp" "$DAEMON_PLIST"

launchctl bootout "system/$LABEL" 2>/dev/null || true
wait_gone "system/$LABEL"
launchctl bootstrap system "$DAEMON_PLIST"

echo "==> Warte auf WhisperNotes"
for _ in $(seq 1 40); do
  curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && break
  sleep 0.5
done
if curl -fsS http://127.0.0.1:8000/health; then
  echo
  echo "Fertig. Neustarts ab jetzt ohne sudo: bash deploy/restart.sh"
else
  echo "WhisperNotes antwortet nicht – siehe $TARGET_HOME/Library/Logs/whispernotes/wrapper.log"
  exit 1
fi
