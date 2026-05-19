#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
#  Job Alert — Ubuntu / Linux setup script
#  Run once after cloning the repo:  bash linux/setup.sh
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
pip3 install --quiet --upgrade requests supabase python-dotenv 2>/dev/null || \
    pip install --quiet --upgrade requests supabase python-dotenv
info "requests, supabase, python-dotenv installed"

# ── 4. Create directories ────────────────────────────────────
section "Directories"
mkdir -p "$CONFIG_DIR" "$LOG_DIR" "$SYSTEMD_USER_DIR" "$DESKTOP_DIR"
info "Created: $CONFIG_DIR"
info "Created: $LOG_DIR"
touch "$LOG_DIR/job-alert.log"

# ── 5. Systemd service + timer ───────────────────────────────
section "Systemd worker service"
SERVICE_SRC="$SCRIPT_DIR/systemd/job-alert-worker.service"
TIMER_SRC="$SCRIPT_DIR/systemd/job-alert-worker.timer"

# Patch ExecStart to use the actual repo path
sed "s|%REPO_ROOT%|$REPO_ROOT|g; s|%PYTHON%|$PYTHON|g" \
    "$SERVICE_SRC" > "$SYSTEMD_USER_DIR/job-alert-worker.service"

cp "$TIMER_SRC" "$SYSTEMD_USER_DIR/job-alert-worker.timer"

if systemctl --user daemon-reload 2>/dev/null; then
    systemctl --user enable job-alert-worker.timer 2>/dev/null || true
    info "Systemd timer enabled — worker will run every 5 minutes"
    info "Check status: systemctl --user status job-alert-worker.timer"
else
    warn "Could not enable systemd timer (no systemd session?). You can run the worker manually."
fi

# ── 6. Desktop launcher ──────────────────────────────────────
section "Desktop launcher"
sed "s|%REPO_ROOT%|$REPO_ROOT|g; s|%PYTHON%|$PYTHON|g" \
    "$SCRIPT_DIR/job-alert.desktop" > "$DESKTOP_DIR/job-alert.desktop"
chmod +x "$DESKTOP_DIR/job-alert.desktop"
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi
info "Desktop launcher created: $DESKTOP_DIR/job-alert.desktop"

# ── 7. Ollama (optional) ─────────────────────────────────────
section "Ollama (AI scoring — optional)"
if command -v ollama &>/dev/null; then
    info "Ollama already installed"
else
    echo ""
    echo "  Ollama is needed for AI job scoring and cover letter generation."
    echo "  Without it, jobs are still collected and sent to Telegram (no AI score)."
    echo ""
    read -r -p "  Install Ollama now? [y/N] " INSTALL_OLLAMA
    if [[ "$INSTALL_OLLAMA" =~ ^[Yy]$ ]]; then
        curl -fsSL https://ollama.ai/install.sh | sh
        echo ""
        info "Ollama installed. Downloading llama3.1 model (4.7 GB)..."
        warn "This will take a few minutes on first run."
        ollama pull llama3.1 &
        OLLAMA_PID=$!
        echo "  (Running in background as PID $OLLAMA_PID)"
        echo "  You can check progress with: ollama list"
    else
        warn "Skipping Ollama. Jobs will be collected without AI scoring."
        warn "Install later: curl -fsSL https://ollama.ai/install.sh | sh && ollama pull llama3.1"
    fi
fi

# ── 8. Settings file ─────────────────────────────────────────
section "Settings"
if [ -f "$CONFIG_DIR/settings.json" ]; then
    info "Settings file already exists: $CONFIG_DIR/settings.json"
elif [ -f "$REPO_ROOT/settings.json" ]; then
    cp "$REPO_ROOT/settings.json" "$CONFIG_DIR/settings.json"
    info "Copied settings from repo root to $CONFIG_DIR/settings.json"
else
    info "No existing settings found — open the GUI to configure."
fi

# ── Done ─────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║   Setup complete!                    ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════╝${NC}"
echo ""
echo "  Launch the GUI:"
echo "    python3 $SCRIPT_DIR/gui.py"
echo ""
echo "  Or find 'Job Alert' in your application launcher (GNOME/KDE)."
echo ""
echo "  First-time setup:"
echo "    1. Open Settings tab"
echo "    2. Paste your Supabase URL + Key"
echo "    3. Paste your Telegram Bot Token + Chat ID"
echo "    4. Paste your LinkedIn Cookie (li_at)"
echo "    5. Click [Save & Sync to Cloud]"
echo ""
echo "  Auto-scan every 5 min (background):"
echo "    systemctl --user start job-alert-worker.timer"
echo "    systemctl --user status job-alert-worker.timer"
echo ""
