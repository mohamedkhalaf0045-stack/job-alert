# Job Alert — Linux / Ubuntu Guide

A full desktop GUI for the Job Alert tool on Ubuntu and other Linux distributions.
Monitors LinkedIn and job boards every 5 minutes, scores jobs with AI, and sends
Telegram alerts for the best matches.

---

## Quick Install (Zero Configuration)

```bash
# 1. Clone the repo  (all credentials are already inside)
git clone https://github.com/mohamedkhalaf0045-stack/job-alert.git
cd job-alert

# 2. Run the one-command installer
bash linux/setup.sh

# 3. Launch
python3 linux/gui.py
```

**No configuration needed.** The repo ships with `settings.json` containing all
credentials (Supabase, Telegram, LinkedIn cookie). `setup.sh` reads them
automatically and sets everything up.

The installer:
- Checks Python 3.9+ and installs `tkinter` if missing
- Installs pip packages: `requests supabase python-dotenv pypdf`
- Reads `settings.json` → generates `settings.env` for the background service
- Creates the systemd timer (starts scanning every 5 minutes **immediately**)
- Optionally installs Ollama (for AI scoring + cover letters)
- Adds a desktop launcher to your GNOME/KDE app menu

---

## Launch the GUI

```bash
python3 linux/gui.py
```

Or find **"Job Alert"** in your GNOME Activities / KDE application launcher.

---

## First-Time Setup

**All credentials are pre-loaded from `settings.json`** — the GUI opens with every
field already filled in. You can go straight to scanning jobs.

If you ever need to update a credential (e.g. refresh the LinkedIn cookie):
1. Open the **Settings** tab — all fields are pre-filled
2. Edit the field you want to change
3. Click **💾 Save & Sync to Cloud**

Settings are saved to `~/.config/job-alert/settings.json` and synced to Supabase
so GitHub Actions and Railway also pick them up automatically.

---

## Tabs

| Tab | What it does |
|-----|-------------|
| ⚙ Settings | Configure all credentials and search parameters |
| 💼 Jobs | Browse jobs from Supabase — filter, mark applied, dismiss |
| 📋 Log | Live output from worker and enricher processes |

---

## Toolbar Buttons

| Button | Action |
|--------|--------|
| ▶ Scan Now | Runs `cloud/worker.py` — fetches new jobs from all sources |
| 🤖 Run Enricher | Runs `cloud/enricher.py` — scores jobs with Ollama AI |
| 📄 Analyze CV | Runs `cloud/cv_analyzer.py` — extracts skills from your CV PDF |
| ⏹ Stop | Kills the running process |

---

## Background Auto-Scan (Every 5 Minutes)

The systemd timer is set up by `linux/setup.sh`. Check its status:

```bash
# Check timer status
systemctl --user status job-alert-worker.timer

# List all timers (see when it last ran and next run)
systemctl --user list-timers

# View recent logs
journalctl --user -u job-alert-worker.service --since "1 hour ago"

# Or view the log file directly
tail -f ~/.local/share/job-alert/job-alert.log
```

Start / stop the timer:
```bash
systemctl --user start job-alert-worker.timer
systemctl --user stop  job-alert-worker.timer
```

---

## AI Scoring (Ollama)

Ollama runs the AI model locally on your machine to score jobs 1–10 and generate
cover letters.

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Download the model (4.7 GB, one-time)
ollama pull llama3.1

# Start Ollama (runs in background)
ollama serve
```

Then click **🤖 Run Enricher** in the GUI, or run manually:

```bash
# Score up to 20 unscored jobs
python3 cloud/enricher.py --limit 20

# Score 50 jobs AND generate cover letters for score ≥ 7
python3 cloud/enricher.py --limit 50 --cover-letter-threshold 7
```

---

## Folder Structure

```
job-alert/
  linux/
    gui.py                   ← This app (run with: python3 linux/gui.py)
    setup.sh                 ← One-command installer
    systemd/
      job-alert-worker.service
      job-alert-worker.timer
    job-alert.desktop        ← GNOME/KDE app launcher entry
  cloud/
    worker.py                ← Job scraper (runs every 5 min via systemd)
    enricher.py              ← AI scoring with Ollama
    cv_analyzer.py           ← CV skills extractor
    db.py                    ← Supabase client
    ...
  README-LINUX.md            ← This file
  README.md                  ← Windows setup guide
```

---

## Settings File

Settings are stored at: `~/.config/job-alert/settings.json`

The file uses the same format as the Windows GUI's `settings.json`, so you can
copy your Windows settings directly if migrating.

---

## Troubleshooting

**GUI won't open: `No module named 'tkinter'`**
```bash
sudo apt install python3-tk
```

**`requests` not found**
```bash
pip3 install requests
```

**Supabase connection error**
- Double-check your Supabase URL format: `https://xxxx.supabase.co` (no trailing slash)
- Make sure you're using the **anon** key, not the service role key

**Ollama timeout / slow scoring**
- AI scoring on CPU takes 3–4 minutes per job — this is normal
- Make sure `ollama serve` is running before clicking Run Enricher
- Check: `curl http://localhost:11434/api/tags`

**LinkedIn jobs not appearing**
- Refresh the LinkedIn cookie (it expires every ~30 days)
- Open LinkedIn in browser → F12 → Application → Cookies → copy new `li_at` value
- Paste into Settings → LinkedIn Cookie → Save

**Timer not running**
```bash
systemctl --user status job-alert-worker.timer
# If inactive:
systemctl --user enable --now job-alert-worker.timer
```
