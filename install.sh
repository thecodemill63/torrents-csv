#!/usr/bin/env bash
# install.sh — interactive installer for torrents-csv.
# Works on macOS and Linux. No prior configuration assumed.
#
# Usage:
#   git clone <repo> && cd torrents-csv && bash install.sh
set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────
B='\033[1;34m'; G='\033[1;32m'; R='\033[1;31m'; Y='\033[1;33m'; N='\033[0m'
info()  { printf "${B}>>>${N} %s\n" "$*"; }
ok()    { printf "${G}  OK${N}  %s\n" "$*"; }
warn()  { printf "${Y}  !!${N}  %s\n" "$*"; }
fail()  { printf "${R} FAIL${N} %s\n" "$*"; exit 1; }
prompt(){ printf "${B}  ?${N} %s " "$*"; read -r REPLY; }
prompt_silent() {
    # Prompt for a password without echoing input to the terminal.
    printf "${B}  ?${N} %s " "$1"
    stty -echo 2>/dev/null || true
    read -r "$2"
    stty echo 2>/dev/null || true
    printf "\n"
    printf "${G}  OK${N}  %s set\n" "$3"
}

# ── Detect OS ────────────────────────────────────────────────────────────
OS="linux"
if [ "$(uname)" = "Darwin" ]; then OS="mac"; fi
info "Detected OS: $OS"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
info "Repo directory: $HERE"

# ── Check for required tools ─────────────────────────────────────────────
info "Checking required tools..."

check_tool() {
    if command -v "$1" >/dev/null 2>&1; then
        ok "$1 found: $(command -v "$1")"
        return 0
    else
        warn "$1 not found"
        return 1
    fi
}

has_python=0
has_pip=0
has_qbt=0
has_systemd=0
has_brew=0
has_nix=0

if check_tool python3; then has_python=1; fi
if check_tool curl; then ok "curl found"; else fail "curl is required (install it first)"; fi
if check_tool git; then ok "git found"; else fail "git is required"; fi
check_tool pip3 && has_pip=1 || true
check_tool qbittorrent && has_qbt=1 || true
check_tool qbittorrent-nox && has_qbt=1 || true
if [ "$OS" = "linux" ] && systemctl --user --version >/dev/null 2>&1; then has_systemd=1; ok "systemd found"; fi
check_tool brew && has_brew=1 || true
check_tool nix-shell && has_nix=1 || true

# ── Install missing tools ────────────────────────────────────────────────
if [ "$has_python" -eq 0 ]; then
    info "Python 3 is required. Installing..."
    if [ "$OS" = "mac" ]; then
        if [ "$has_brew" -eq 0 ]; then fail "Install Homebrew first: https://brew.sh"; fi
        brew install python3 || fail "failed to install python3"
    else
        fail "Install python3 first: sudo apt install python3  (or your distro's equivalent)"
    fi
    has_python=1
fi

# Install Django
if [ "$has_nix" -eq 1 ]; then
    ok "Nix detected — Django will be provided via shell.nix at runtime"
elif [ "$has_pip" -eq 1 ]; then
    info "Installing Django..."
    pip3 install --user django >/dev/null 2>&1 || pip3 install django >/dev/null 2>&1 || fail "failed to install Django"
    ok "Django installed"
else
    info "pip3 not found, installing pip..."
    if [ "$OS" = "mac" ]; then
        python3 -m ensurepip --upgrade || fail "failed to bootstrap pip"
    else
        fail "Install python3-pip first: sudo apt install python3-pip  (or your distro's equivalent)"
    fi
    pip3 install --user django || fail "failed to install Django"
    ok "Django installed"
fi

# Install qBittorrent if missing
if [ "$has_qbt" -eq 0 ]; then
    info "qBittorrent not found. Installing..."
    if [ "$OS" = "mac" ]; then
        if [ "$has_brew" -eq 0 ]; then
            warn "Homebrew not found — cannot auto-install qBittorrent"
            warn "Install Homebrew (https://brew.sh) then re-run, or install qBittorrent manually from https://www.qbittorrent.org"
        else
            brew install --cask qbittorrent || warn "failed to install qBittorrent via brew"
            has_qbt=1
        fi
    elif [ "$has_nix" -eq 1 ]; then
        warn "On NixOS, install qBittorrent via your system config:"
        warn "  Add 'qbittorrent' to environment.systemPackages and rebuild"
        warn "  Or run:  nix-shell -p qbittorrent --run qbittorrent"
    else
        info "Attempting to install qBittorrent via package manager..."
        if command -v apt >/dev/null 2>&1; then
            sudo apt update && sudo apt install -y qbittorrent || warn "failed to install via apt"
            has_qbt=1
        elif command -v dnf >/dev/null 2>&1; then
            sudo dnf install -y qbittorrent || warn "failed to install via dnf"
            has_qbt=1
        elif command -v pacman >/dev/null 2>&1; then
            sudo pacman -S --noconfirm qbittorrent || warn "failed to install via pacman"
            has_qbt=1
        elif command -v zypper >/dev/null 2>&1; then
            sudo zypper install -y qbittorrent || warn "failed to install via zypper"
            has_qbt=1
        else
            warn "Unknown package manager. Install qBittorrent manually from https://www.qbittorrent.org"
        fi
    fi
    # Re-check
    if command -v qbittorrent >/dev/null 2>&1 || command -v qbittorrent-nox >/dev/null 2>&1; then
        ok "qBittorrent installed"
        has_qbt=1
    else
        warn "qBittorrent could not be installed automatically."
        warn "The download feature will not work until you install it manually."
        warn "Get it from: https://www.qbittorrent.org/download"
        warn "You can still use the search UI — just skip the qBittorrent config below."
    fi
fi

# ── Interactive configuration ────────────────────────────────────────────
# Load config file if it exists — pre-fills all prompts with user values.
# File locations checked (first match wins):
#   ~/.config/torrents-ui/torrents-csv.conf
#   ~/.torrents-csv.conf
#   ./torrents-csv.conf  (in the repo/install dir)
CONFIG_FILE=""
for f in \
    "$HOME/.config/torrents-ui/torrents-csv.conf" \
    "$HOME/.torrents-csv.conf" \
    "$HERE/torrents-csv.conf"; do
    if [ -f "$f" ]; then
        CONFIG_FILE="$f"
        break
    fi
done

if [ -n "$CONFIG_FILE" ]; then
    info "Loading config from $CONFIG_FILE"
    # shellcheck source=/dev/null
    source "$CONFIG_FILE"
    ok "config loaded — prompts will use these values as defaults"
    echo ""
else
    info "No config file found. You'll be prompted for everything interactively."
    info "Tip: after install, edit ~/.config/torrents-ui/torrents-csv.conf to tune values."
    echo ""
fi

# All config variables with built-in defaults. Config file overrides defaults.
INSTALL_DIR="${INSTALL_DIR:-$HOME/torrents-csv}"
UI_PORT="${UI_PORT:-8888}"
TV_ROOT="${TV_ROOT:-$HOME/media/TV}"
MOVIES_ROOT="${MOVIES_ROOT:-$HOME/media/Movies}"
QBT_URL="${QBT_URL:-http://localhost:8081}"
QBT_USER="${QBT_USER:-admin}"
QBT_PASS="${QBT_PASS:-}"
SYNC_INTERVAL="${SYNC_INTERVAL:-daily}"

# Install directory
prompt INSTALL_DIR "Where to store the data? [$INSTALL_DIR]"
INSTALL_DIR="${REPLY:-$INSTALL_DIR}"
info "Data directory: $INSTALL_DIR"

# Create directory structure
for sub in bin downloads state logs; do
    mkdir -p "$INSTALL_DIR/$sub"
done
ok "Directory structure created"

# UI port
prompt UI_PORT "Port for the web UI? [$UI_PORT]"
UI_PORT="${REPLY:-$UI_PORT}"
# Check if port is already in use
if command -v ss >/dev/null 2>&1; then
    if ss -tlnp 2>/dev/null | grep -q ":$UI_PORT\b"; then
        warn "port $UI_PORT appears to be in use — the UI may fail to start"
    else
        ok "port $UI_PORT is free"
    fi
elif command -v lsof >/dev/null 2>&1; then
    if lsof -i :"$UI_PORT" >/dev/null 2>&1; then
        warn "port $UI_PORT appears to be in use — the UI may fail to start"
    else
        ok "port $UI_PORT is free"
    fi
fi
ok "UI port: $UI_PORT (http://127.0.0.1:$UI_PORT)"

# TV root
prompt TV_ROOT "Where are your TV shows stored? [$TV_ROOT]"
TV_ROOT="${REPLY:-$TV_ROOT}"
mkdir -p "$TV_ROOT" 2>/dev/null || warn "could not create $TV_ROOT (may need sudo later)"
ok "TV root: $TV_ROOT"

# Movies root
prompt MOVIES_ROOT "Where are your movies stored? [$MOVIES_ROOT]"
MOVIES_ROOT="${REPLY:-$MOVIES_ROOT}"
mkdir -p "$MOVIES_ROOT" 2>/dev/null || warn "could not create $MOVIES_ROOT"
ok "Movies root: $MOVIES_ROOT"

# qBittorrent WebUI config (skip if qBt wasn't installed)
if [ "$has_qbt" -eq 1 ]; then
    echo ""
    info "qBittorrent WebUI configuration."
    info "You need qBittorrent running with WebUI enabled."
    info "  To enable: qBittorrent → Tools → Preferences → Web UI → Enable"
    echo ""

    DEFAULT_QBT_URL="http://localhost:8081"
    prompt QBT_URL "qBittorrent WebUI URL? [$QBT_URL]"
    QBT_URL="${REPLY:-$QBT_URL}"

    prompt QBT_USER "qBittorrent WebUI username? [$QBT_USER]"
    QBT_USER="${REPLY:-$QBT_USER}"

    # If password was already in config, skip the prompt entirely
    if [ -n "$QBT_PASS" ]; then
        ok "qBittorrent password loaded from config"
    else
        prompt_silent "qBittorrent WebUI password?" QBT_PASS "password"
    fi

    # Test qBt connection
    info "Testing qBittorrent connection..."
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -m 5 -X POST "$QBT_URL/api/v2/auth/login" -d "username=$QBT_USER&password=$QBT_PASS" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "204" ]; then
        ok "qBittorrent connection successful"
    elif [ "$HTTP_CODE" = "403" ]; then
        warn "qBittorrent returned 403 (may be banned or credentials wrong)"
        warn "You can fix this later in qBittorrent → Preferences → Web UI"
    else
        warn "qBittorrent not reachable at $QBT_URL (HTTP $HTTP_CODE)"
        warn "Make sure qBittorrent is running with WebUI enabled. You can fix this later."
    fi
else
    warn "Skipping qBittorrent config (not installed)."
    warn "Re-run the installer after installing qBittorrent to enable downloads."
    QBT_URL="http://localhost:8081"
    QBT_USER="admin"
    QBT_PASS=""
fi

# Generate Django secret key
DJANGO_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
ok "Generated Django secret key"

# ── Write config files ────────────────────────────────────────────────────
echo ""
info "Writing configuration files..."

# qBt config
QBT_CONFIG_DIR="$HOME/.config/torrents-ui"
mkdir -p "$QBT_CONFIG_DIR"
cat > "$QBT_CONFIG_DIR/qbt.json" <<QBTJSON
{
  "api_url": "$QBT_URL",
  "username": "$QBT_USER",
  "password": "$QBT_PASS",
  "categories": {
    "Movie": "$MOVIES_ROOT",
    "TV Show": "$TV_ROOT"
  }
}
QBTJSON
chmod 600 "$QBT_CONFIG_DIR/qbt.json"
ok "qBittorrent config → $QBT_CONFIG_DIR/qbt.json"

# Write the user-facing config file (for re-running installer or tuning)
USER_CONFIG_DIR="$HOME/.config/torrents-ui"
mkdir -p "$USER_CONFIG_DIR"
cat > "$USER_CONFIG_DIR/torrents-csv.conf" <<CONF
# torrents-csv configuration — edit and re-run install.sh to apply changes.
# Lines starting with # are comments. Uncomment and edit to override.

# Where the data lives (DB, downloads, state, logs)
INSTALL_DIR="$INSTALL_DIR"

# Port for the Django web UI
UI_PORT=$UI_PORT

# TV shows directory (for the folder picker)
TV_ROOT="$TV_ROOT"

# Movies directory (for Movie downloads)
MOVIES_ROOT="$MOVIES_ROOT"

# qBittorrent WebUI connection
QBT_URL="$QBT_URL"
QBT_USER="$QBT_USER"
QBT_PASS="$QBT_PASS"

# Sync interval: daily or hourly
SYNC_INTERVAL="$SYNC_INTERVAL"
CONF
chmod 600 "$USER_CONFIG_DIR/torrents-csv.conf"
ok "Config file → $USER_CONFIG_DIR/torrents-csv.conf"
ok "  Edit this file and re-run install.sh to reconfigure without re-prompting"

# ── Copy code into install dir ───────────────────────────────────────────
info "Copying code to $INSTALL_DIR..."

# Copy sync.py
cp "$HERE/bin/sync.py" "$INSTALL_DIR/bin/sync.py"
chmod +x "$INSTALL_DIR/bin/sync.py"
ok "sync.py copied"

# Copy UI (only if the repo has a ui/ dir with manage.py)
if [ -f "$HERE/ui/manage.py" ]; then
    # Copy the ui dir but exclude runtime junk
    mkdir -p "$INSTALL_DIR/ui"
    cp -r "$HERE/ui/torrentsearch" "$INSTALL_DIR/ui/"
    cp -r "$HERE/ui/torrents" "$INSTALL_DIR/ui/"
    cp "$HERE/ui/manage.py" "$INSTALL_DIR/ui/"
    cp "$HERE/ui/start.sh" "$INSTALL_DIR/ui/" 2>/dev/null || true
    cp "$HERE/ui/shell.nix" "$INSTALL_DIR/ui/" 2>/dev/null || true
    # Remove __pycache__ if any
    find "$INSTALL_DIR/ui" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    ok "UI code copied"
else
    warn "No ui/ directory in repo — skipping UI install"
fi

# ── Run initial sync ─────────────────────────────────────────────────────
echo ""
info "Running initial data sync (downloads ~175 MB from Codeberg)..."
info "This takes 10-30 seconds depending on your connection."
echo ""
if TORRENTS_CSV_DIR="$INSTALL_DIR" python3 "$INSTALL_DIR/bin/sync.py" 2>&1 | sed 's/^/    /'; then
    ok "Initial sync complete"
else
    warn "Initial sync failed — you can re-run it later with:"
    warn "  TORRENTS_CSV_DIR=$INSTALL_DIR python3 $INSTALL_DIR/bin/sync.py"
fi

# ── Set up scheduled sync (systemd on Linux, launchd on Mac) ─────────────
echo ""
info "Setting up scheduled daily sync..."

if [ "$OS" = "linux" ] && [ "$has_systemd" -eq 1 ]; then
    # systemd user service for sync
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$HOME/.config/systemd/user/torrents-csv-sync.service" <<SVCSYNC
[Unit]
Description=Sync torrents-csv data from Codeberg
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
Environment=TORRENTS_CSV_DIR=$INSTALL_DIR
ExecStart=$(command -v python3) $INSTALL_DIR/bin/sync.py
TimeoutStartSec=30min
Nice=10
SVCSYNC
    cat > "$HOME/.config/systemd/user/torrents-csv-sync.timer" <<TMRSYNC
[Unit]
Description=Torrents-csv sync timer

[Timer]
OnBootSec=2min
$([ "$SYNC_INTERVAL" = "hourly" ] && echo "OnUnitActiveSec=1h" || echo "OnUnitActiveSec=24h")
Persistent=true
AccuracySec=1min

[Install]
WantedBy=timers.target
TMRSYNC
    systemctl --user daemon-reload
    systemctl --user enable --now torrents-csv-sync.timer
    ok "Sync timer enabled (runs daily)"

    # systemd user service for UI (if we have the UI)
    if [ -f "$INSTALL_DIR/ui/manage.py" ]; then
        # Detect python path (prefer nix-shell if available, else plain python3)
        if [ "$has_nix" -eq 1 ]; then
            EXEC_START="$INSTALL_DIR/ui/start.sh"
            chmod +x "$EXEC_START"
            UI_ENV="Environment=TORRENTS_CSV_DIR=$INSTALL_DIR\nEnvironment=TORRENTS_TV_ROOT=$TV_ROOT\nEnvironment=TORRENTS_UI_PORT=$UI_PORT"
        else
            EXEC_START="$(command -v python3) $INSTALL_DIR/ui/manage.py runserver 127.0.0.1:$UI_PORT --noreload"
            UI_ENV="Environment=TORRENTS_CSV_DIR=$INSTALL_DIR\nEnvironment=TORRENTS_TV_ROOT=$TV_ROOT\nEnvironment=DJANGO_SECRET_KEY=$DJANGO_SECRET"
        fi
        cat > "$HOME/.config/systemd/user/torrents-csv-ui.service" <<SVCUI
[Unit]
Description=Torrents-csv search UI (Django, localhost only)
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
$(printf "Environment=TORRENTS_CSV_DIR=%s" "$INSTALL_DIR")
$(printf "Environment=TORRENTS_TV_ROOT=%s" "$TV_ROOT")
$(printf "Environment=TORRENTS_UI_PORT=%s" "$UI_PORT")
$(printf "Environment=DJANGO_SECRET_KEY=%s" "$DJANGO_SECRET")
WorkingDirectory=$INSTALL_DIR/ui
ExecStart=$EXEC_START
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=default.target
SVCUI
        systemctl --user daemon-reload
        systemctl --user enable --now torrents-csv-ui.service
        ok "UI service enabled on port $UI_PORT"
    fi

    # Enable lingering so user services survive logout
    if command -v loginctl >/dev/null 2>&1; then
        loginctl enable-linger "$USER" 2>/dev/null || warn "could not enable lingering"
    fi

elif [ "$OS" = "mac" ]; then
    # launchd plist for sync
    PLIST_SYNC="$HOME/Library/LaunchAgents/com.torrents-csv.sync.plist"
    cat > "$PLIST_SYNC" <<PLISTSYNC
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.torrents-csv.sync</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(command -v python3)</string>
    <string>$INSTALL_DIR/bin/sync.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>TORRENTS_CSV_DIR</key>
    <string>$INSTALL_DIR</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>4</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$INSTALL_DIR/logs/sync.log</string>
  <key>StandardErrorPath</key>
  <string>$INSTALL_DIR/logs/sync.log</string>
</dict>
</plist>
PLISTSYNC
    launchctl load "$PLIST_SYNC" 2>/dev/null || warn "could not load sync plist"
    ok "Sync scheduled (daily at 4 AM via launchd)"

    # launchd plist for UI
    if [ -f "$INSTALL_DIR/ui/manage.py" ]; then
        PLIST_UI="$HOME/Library/LaunchAgents/com.torrents-csv.ui.plist"
        cat > "$PLIST_UI" <<PLISTUI
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.torrents-csv.ui</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(command -v python3)</string>
    <string>$INSTALL_DIR/ui/manage.py</string>
    <string>runserver</string>
    <string>127.0.0.1:$UI_PORT</string>
    <string>--noreload</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>TORRENTS_CSV_DIR</key>
    <string>$INSTALL_DIR</string>
    <key>TORRENTS_TV_ROOT</key>
    <string>$TV_ROOT</string>
    <key>DJANGO_SECRET_KEY</key>
    <string>$DJANGO_SECRET</string>
  </dict>
  <key>WorkingDirectory</key>
  <string>$INSTALL_DIR/ui</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$INSTALL_DIR/logs/ui.log</string>
  <key>StandardErrorPath</key>
  <string>$INSTALL_DIR/logs/ui.log</string>
</dict>
</plist>
PLISTUI
        launchctl load "$PLIST_UI" 2>/dev/null || warn "could not load UI plist"
        ok "UI service started on port $UI_PORT"
    fi
else
    warn "No service manager detected. You'll need to set up a cron job manually:"
    warn "  0 4 * * * TORRENTS_CSV_DIR=$INSTALL_DIR $(command -v python3) $INSTALL_DIR/bin/sync.py"
    warn "And run the UI manually:"
    warn "  TORRENTS_CSV_DIR=$INSTALL_DIR $(command -v python3) $INSTALL_DIR/ui/manage.py runserver 127.0.0.1:$UI_PORT"
fi

# ── Final summary ────────────────────────────────────────────────────────
echo ""
info "Installation complete!"
echo ""
printf "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}\n"
printf "  Data directory:    ${B}%s${N}\n" "$INSTALL_DIR"
printf "  TV root:           ${B}%s${N}\n" "$TV_ROOT"
printf "  Movies root:       ${B}%s${N}\n" "$MOVIES_ROOT"
printf "  Sync schedule:     ${B}daily${N}\n"
printf "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}\n"
echo ""
printf "${B}  Port allocation:${N}\n"
echo "  ┌────────────────────────┬──────────┬──────────────────────────────────┐"
printf "  │ Service                │ Port     │ Purpose                          │\n"
printf "  ├────────────────────────┼──────────┼──────────────────────────────────┤\n"
printf "  │ Django web UI          │ %-8s │ Search + download interface      │\n" "$UI_PORT"
if [ "$has_qbt" -eq 1 ]; then
    # Extract port from QBT_URL
    QBT_PORT=$(echo "$QBT_URL" | sed 's|.*:||; s|/.*||')
    printf "  │ qBittorrent WebUI      │ %-8s │ Torrent management + download    │\n" "$QBT_PORT"
fi
printf "  │ Upstream data (fetch)  │ 443      │ HTTPS to codeberg.org            │\n"
printf "  └────────────────────────┴──────────┴──────────────────────────────────┘"
echo ""
echo ""
printf "${B}  URLs:${N}\n"
printf "  Web UI:            ${B}http://127.0.0.1:%s/${N}\n" "$UI_PORT"
if [ "$has_qbt" -eq 1 ]; then
    printf "  qBittorrent:       ${B}%s${N}\n" "$QBT_URL"
fi
echo ""
printf "  Open the UI:       ${B}open http://127.0.0.1:%s/${N}  (mac)\n" "$UI_PORT"
printf "                      ${B}xdg-open http://127.0.0.1:%s/${N}  (linux)\n" "$UI_PORT"
echo ""
printf "  Re-run sync now:   ${B}TORRENTS_CSV_DIR=%s python3 %s/bin/sync.py${N}\n" "$INSTALL_DIR" "$INSTALL_DIR"
echo ""
printf "  Config files:\n"
if [ "$has_qbt" -eq 1 ]; then
    printf "    qBittorrent:     ${B}%s/qbt.json${N}\n" "$QBT_CONFIG_DIR"
fi
if [ "$OS" = "linux" ] && [ "$has_systemd" -eq 1 ]; then
    printf "    Services:        ${B}~/.config/systemd/user/torrents-csv-*${N}\n"
elif [ "$OS" = "mac" ]; then
    printf "    Services:        ${B}~/Library/LaunchAgents/com.torrents-csv.*${N}\n"
fi
printf "    Data/DB:         ${B}%s/torrents.db${N}\n" "$INSTALL_DIR"
printf "    Logs:            ${B}%s/logs/${N}\n" "$INSTALL_DIR"
echo ""

# Verify UI is reachable
if [ -f "$INSTALL_DIR/ui/manage.py" ]; then
    info "Verifying UI is reachable..."
    sleep 3
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -m 5 "http://127.0.0.1:$UI_PORT/" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        ok "UI is live at http://127.0.0.1:$UI_PORT/"
    else
        warn "UI not yet responding (HTTP $HTTP_CODE) — it may need a few more seconds to start"
        warn "Check logs at $INSTALL_DIR/logs/"
    fi
fi

echo ""
info "Done. Happy torrenting!"