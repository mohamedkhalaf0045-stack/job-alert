#!/bin/bash
# Oracle Cloud Free Tier — one-time setup script
# Run as: bash oracle-vm-setup.sh
# Then: edit ~/.job-alert-env with your secrets, then test with: bash ~/run-worker.sh
set -e

REPO_URL="https://github.com/$(git -C ~ remote get-url origin 2>/dev/null | sed 's|.*github.com[:/]||;s|\.git||')" 2>/dev/null || REPO_URL=""
REPO_DIR="$HOME/job-alert"
ENV_FILE="$HOME/.job-alert-env"
CRON_LOG="$HOME/worker.log"

echo "=== 1. System packages ==="
sudo apt-get update -qq
sudo apt-get install -y python3.12 python3.12-venv python3-pip git curl unzip

echo "=== 2. Clone repo ==="
if [ -d "$REPO_DIR/.git" ]; then
  echo "Repo exists, pulling latest..."
  git -C "$REPO_DIR" pull --ff-only
else
  echo "Cloning repo..."
  echo "Enter your GitHub repo URL (e.g. https://github.com/youruser/yourrepo.git):"
  read -r REPO_URL
  git clone "$REPO_URL" "$REPO_DIR"
fi

echo "=== 3. Python virtualenv ==="
python3.12 -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$REPO_DIR/.venv/bin/pip" install --quiet -r "$REPO_DIR/cloud/requirements.txt"

# NOTE: Playwright Chromium is intentionally skipped — datacenter IPs are
# blocked by Indeed anyway. Set SEARCH_INDEED=false in your .env file.
echo "=== 4. Playwright browsers (for LinkedIn) ==="
"$REPO_DIR/.venv/bin/playwright" install chromium --with-deps

echo "=== 5. Create .env file (if not exists) ==="
if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" << 'ENVEOF'
# Job Alert Worker — secrets
# Copy values from your GitHub Actions secrets

KEYWORDS=
LOCATION=UAE
SUPABASE_URL=
SUPABASE_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
MAX_HOURS=72
LINKEDIN_COOKIE=

# Feature flags
SEARCH_LINKEDIN=true
SEARCH_INDEED=false       # datacenter IPs blocked by Indeed — keep false
SEARCH_ADZUNA=true
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
SEARCH_WEB=false
TAVILY_API_KEY=
BRAVE_API_KEY=
GOOGLE_API_KEY=
GOOGLE_CX=
BING_API_KEY=
SEARCH_GMAIL=false
GMAIL_EMAIL=
GMAIL_APP_PASSWORD=
HIDE_APPLIED=true
ENVEOF
  echo ""
  echo ">>> EDIT $ENV_FILE with your secrets before continuing <<<"
  echo "    nano $ENV_FILE"
  echo ""
else
  echo ".env already exists, skipping."
fi

echo "=== 6. Create run-worker.sh ==="
cat > "$HOME/run-worker.sh" << RUNEOF
#!/bin/bash
set -a
source "$ENV_FILE"
set +a
cd "$REPO_DIR"
"$REPO_DIR/.venv/bin/python" cloud/worker.py >> "$CRON_LOG" 2>&1
RUNEOF
chmod +x "$HOME/run-worker.sh"

echo "=== 7. Install cron job (every 5 minutes) ==="
CRON_LINE="*/5 * * * * $HOME/run-worker.sh"
# Only add if not already present
( crontab -l 2>/dev/null | grep -v "run-worker.sh"; echo "$CRON_LINE" ) | crontab -
echo "Cron installed."

echo ""
echo "=== DONE ==="
echo ""
echo "Next steps:"
echo "  1. Edit secrets:  nano $ENV_FILE"
echo "  2. Test manually: bash $HOME/run-worker.sh"
echo "  3. Check logs:    tail -f $CRON_LOG"
echo "  4. Verify cron:   crontab -l"
echo ""
echo "The worker will run every 5 minutes automatically once .env is filled in."
