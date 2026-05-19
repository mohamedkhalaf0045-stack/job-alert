#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
#  Job Alert — Ubuntu / Linux setup script
#  Run once after cloning the repo:  bash linux/setup.sh
#
#  All credentials (Supabase, Telegram, LinkedIn cookie) are read
#  from settings.json that ships with the repo — no manual config
#  needed after cloning.
# ─────────────────────────────────────────────────────────────────

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_DIR="$REPO_ROOT/linux"
CONFIG_DIR="$HOME/.config/job-alert"
LOG_DIR="$HOME/.local/share/job-alert"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
DESKTOP_DIR="$HOME/.local/share/applications"

GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
NC="\033[0m"

info()    { echo -e "${GREEN}[✓]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*"; exit 1; }
section() { echo -e "\n${YELLOW}── $* ──${NC}"; }

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║   Job Alert — Linux Setup            ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# ── 1. Python check ──────────────────────────────────────────
section "Python"
PYTHON=$(command -v python3 || true)
if [ -z "$PYTHON" ]; then
    error "Python 3 not found. Install with: sudo apt install python3 python3-pip"
fi
PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]; }; then
    error "Python 3.9+ required. Found: $PY_VER"
fi
info "Python $PY_VER found at $PYTHON"

# ── 2. Tkinter check ─────────────────────────────────────────
section "Tkinter"
if ! "$PYTHON" -c "import tkinter" 2>/dev/null; then
    warn "tkinter not found. Installing..."
    sudo apt-get install -y python3-tk 2>/dev/null || \
        error "Could not install python3-tk. Run: sudo apt install python3-tk"
fi
info "tkinter available"

# ── 3. Python packages ───────────────────────────────────────
section "Python packages"
pip3 install --quiet --upgrade requests supabase python-dotenv pypdf 2>/dev/null || \
    pip install --quiet --upgrade requests supabase python-dotenv pypdf
info "requests, supabase, python-dotenv, pypdf installed"

# ── 4. Create directories ────────────────────────────────────
section "Directories"
mkdir -p "$CONFIG_DIR" "$LOG_DIR" "$SYSTEMD_USER_DIR" "$DESKTOP_DIR"
touch "$LOG_DIR/job-alert.log"
info "Config dir: $CONFIG_DIR"
info "Log dir:    $LOG_DIR"

# ── 5. Load credentials from settings.json ───────────────────
section "Credentials"
SETTINGS_SRC=""
if [ -f "$REPO_ROOT/settings.json" ]; then
    SETTINGS_SRC="$REPO_ROOT/settings.json"
fi

if [ -n "$SETTINGS_SRC" ]; then
    # Copy settings.json to config dir (overwrite if older)
    cp "$SETTINGS_SRC" "$CONFIG_DIR/settings.json"
    info "Loaded all credentials from settings.json"

    # Generate settings.env for the systemd service (reads SUPABASE_URL etc.)
    "$PYTHON" - <<'PYEOF'
import json, os, sys
from pathlib import Path

config_dir = Path(os.environ['HOME']) / '.config' / 'job-alert'
settings_file = config_dir / 'settings.json'

try:
    s = json.loads(settings_file.read_text(encoding='utf-8'))
except Exception as e:
    print(f"  WARNING: could not parse settings.json: {e}")
    sys.exit(0)

kw = s.get('Keywords', [])
if isinstance(kw, list):
    kw = ','.join(str(k) for k in kw)

env_path = config_dir / 'settings.env'
env_path.write_text(
    f"SUPABASE_URL={s.get('SupabaseUrl', '')}\n"
    f"SUPABASE_KEY={s.get('SupabaseKey', '')}\n"
    f"TELEGRAM_BOT_TOKEN={s.get('TelegramBotToken', '')}\n"
    f"TELEGRAM_CHAT_ID={s.get('TelegramChatId', '')}\n"
    f"LINKEDIN_COOKIE={s.get('LinkedInCookie', '')}\n"
    f"KEYWORDS={kw}\n"
    f"LOCATION={s.get('Location', '')}\n"
    f"OLLAMA_URL={s.get('OllamaUrl', 'http://localhost:11434')}\n",
    encoding='utf-8',
)

# Mask credentials in summary output
def mask(v):
    v = str(v)
    return v[:6] + '***' if len(v) > 6 else '***'

print(f"  Supabase URL:   {s.get('SupabaseUrl', '(not set)')}")
print(f"  Supabase Key:   {mask(s.get('SupabaseKey', ''))}")
print(f"  Telegram token: {mask(s.get('TelegramBotToken', ''))}")
print(f"  Telegram chat:  {s.get('TelegramChatId', '(not set)')}")
print(f"  LinkedIn cookie:{mask(s.get('LinkedInCookie', ''))}")
print(f"  Keywords:       {kw[:60]}{'...' if len(kw)>60 else ''}")
print(f"  Location:       {s.get('Location', '(not set)')}")
PYEOF
    info "settings.env generated — systemd service is pre-configured"
else
    warn "No settings.json found in repo root."
    warn "Open the GUI → Settings tab → fill in credentials → Save & Sync."
fi

# ── 6. Systemd service + timer ───────────────────────────────
section "Systemd worker service"
SERVICE_SRC="$SCRIPT_DIR/systemd/job-alert-worker.service"
TIMER_SRC="$SCRIPT_DIR/systemd/job-alert-worker.timer"

# Patch ExecStart paths with actual repo root + python path
sed "s|%REPO_ROOT%|$REPO_ROOT|g; s|%PYTHON%|$PYTHON|g" \
    "$SERVICE_SRC" > "$SYSTEMD_USER_DIR/job-alert-worker.service"

cp "$TIMER_SRC" "$SYSTEMD_USER_DIR/job-alert-worker.timer"

if systemctl --user daemon-reload 2>/dev/null; then
    systemctl --user enable  job-alert-worker.timer 2>/dev/null || true
    systemctl --user restart job-alert-worker.timer 2>/dev/null || true
    info "Systemd timer enabled and started — worker scans every 5 minutes"
    info "Status: systemctl --user status job-alert-worker.timer"
else
    warn "Could not start systemd timer (no user session bus?)."
    warn "Run manually: python3 $REPO_ROOT/cloud/worker.py"
fi

# ── 7. Desktop launcher ──────────────────────────────────────
section "Desktop launcher"
sed "s|%REPO_ROOT%|$REPO_ROOT|g; s|%PYTHON%|$PYTHON|g" \
    "$SCRIPT_DIR/job-alert.desktop" > "$DESKTOP_DIR/job-alert.desktop"
chmod +x "$DESKTOP_DIR/job-alert.desktop"
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi
info "Desktop launcher created — find 'Job Alert' in your app menu"

# ── 8. Ollama (AI scoring — optional) ───────────────────────
section "Ollama (AI scoring — optional)"
if command -v ollama &>/dev/null; then
    info "Ollama already installed"
    # Pull model if not already downloaded
    if ! ollama list 2>/dev/null | grep -q "llama3.1"; then
        info "Pulling llama3.1 model (4.7 GB — runs in background)..."
        ollama pull llama3.1 &
        echo "  Check progress: ollama list"
    else
        info "llama3.1 model already downloaded"
    fi
else
    echo ""
    echo "  Ollama scores jobs 1–10 and generates cover letters using your GPU/CPU."
    echo "  Jobs are still collected and sent to Telegram without it (no AI score)."
    echo ""
    read -r -p "  Install Ollama now? [y/N] " INSTALL_OLLAMA
    if [[ "$INSTALL_OLLAMA" =~ ^[Yy]$ ]]; then
        curl -fsSL https://ollama.ai/install.sh | sh
        info "Ollama installed. Pulling llama3.1 model (4.7 GB)..."
        ollama pull llama3.1 &
        echo "  (Downloading in background — check with: ollama list)"
    else
        warn "Skipping Ollama — install later with:"
        warn "  curl -fsSL https://ollama.ai/install.sh | sh && ollama pull llama3.1"
    fi
fi

# ── Done ─────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║   Setup complete — ready to use!             ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════════╝${NC}"
echo ""
echo "  Launch the GUI:"
echo "    python3 $SCRIPT_DIR/gui.py"
echo ""
echo "  Or find 'Job Alert' in your GNOME/KDE app launcher."
echo ""
echo "  The background scanner is already running."
echo "  First Telegram alert will arrive within 5 minutes."
echo ""
echo "  View live scan log:"
echo "    tail -f $LOG_DIR/job-alert.log"
echo ""
