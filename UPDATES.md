# LinkedIn Job Alert — Complete Project Memory

> **How to use this file:**
> - Read it at the start of every new Claude session before asking for anything
> - Update the "Pending Tasks" section whenever something is done or added
> - This file is the single source of truth for what exists, how it works, and what comes next
>
> Last updated: 2026-05-18

---

## 1. What This Project Is

A personal job-alert system built for **Mohamed Khalaf** — IT Support/System Administrator
job hunting in the **United Arab Emirates**.

It started as a simple PowerShell app that checked LinkedIn every few minutes and popped a
Windows notification. Over time it grew into a full multi-layer system:

```
Layer 1 — Windows desktop app    linkedin-job-alert.ps1
           (GUI, scan, notify)

Layer 2 — Headless background     linkedin-job-worker.ps1
           worker                 (runs 24/7, even when screen locked)

Layer 3 — Cloud scanner           GitHub Actions (free, runs every 5 min)
           (runs when laptop off)  cloud/worker.py

Layer 4 — AI enrichment           cloud/enricher.py  +  Ollama (local, free)
           (scoring + cover        llama3.1:latest  +  nomic-embed-text
            letters + dedup)

Layer 5 — Database                Supabase (free tier, PostgreSQL)
           (central store,         PostgREST REST API
            all layers write here)

Layer 6 — Mobile app              Flutter Android app
           (browse + manage        connects to Supabase directly
            jobs from phone)

Layer 7 — Telegram alerts         Telegram Bot API
           (instant push           cloud sends alerts, local bot answers /commands
            notifications)
```

**The core idea:** GitHub Actions scans LinkedIn/Indeed every 5 minutes (even when the laptop
is off). New jobs land in Supabase. The local Ollama LLM scores each job against the user's
CV. The Flutter phone app shows everything with AI match scores, cover letter drafts, and
deduplication across sources.

---

## 2. Services and Accounts Used

| Service | What it does | Free? | Where to get |
|---------|-------------|-------|--------------|
| **Supabase** | PostgreSQL database, REST API | Yes (free tier) | supabase.com → New project |
| **GitHub Actions** | Cloud scanner, runs every 5 min | Yes (free public repo) | github.com |
| **Telegram Bot** | Push alerts to phone | Yes | Message @BotFather |
| **Ollama** | Local LLM, runs on laptop | Yes (local) | ollama.com |
| **LinkedIn** | Job source (scraped, no API) | Uses cookie | Your browser session |
| **Indeed** | Job source (RSS feed) | Yes | No auth needed |
| **Adzuna** | Job aggregator API | Free tier (50k/month) | developer.adzuna.com |

**Credentials needed (stored in settings.json — never commit this file):**

```json
{
  "SupabaseUrl":       "https://YOUR-PROJECT-ID.supabase.co",
  "SupabaseKey":       "eyJ... (anon/public key)",
  "TelegramBotToken":  "12345:AAAXXX (from @BotFather)",
  "TelegramChatId":    "941885724 (your personal chat ID)",
  "LinkedInCookie":    "li_at=AQE... (from browser DevTools)",
  "GitHubToken":       "ghp_... (personal access token, repo scope)",
  "GitHubRepo":        "yourusername/job-alert",
  "UserProfile":       "C:\\path\\to\\your-cv.pdf",
  "OllamaUrl":         "http://localhost:11434"
}
```

**GitHub Actions secrets (same values, set in repo Settings → Secrets):**
`SUPABASE_URL`, `SUPABASE_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
`LINKEDIN_COOKIE`, `KEYWORDS`, `LOCATION`, `MAX_HOURS`,
`SEARCH_LINKEDIN`, `SEARCH_INDEED`, `SEARCH_ADZUNA`,
`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `GH_PAT`

---

## 3. Repository

**GitHub repo:** `mohamedkhalaf0045-stack/job-alert`
**Local path:** `C:\Users\Mohamed Khalaf\Documents\Codex\2026-05-06\create-a-simple-windows-app-to\`

---

## 4. Full File Map

```
project-root/
│
├── linkedin-job-alert.ps1          Main Windows desktop GUI (112 KB — the big one)
├── linkedin-job-worker.ps1         Headless background worker (runs without GUI)
├── shared-functions.ps1            Shared PowerShell helpers (scraping, Supabase calls)
├── Run-EnrichmentHealthCheck.ps1   Diagnostic script — checks Ollama + enricher health
├── Install-LinkedInJobWorkerTask.ps1  Installs worker as Windows logon scheduled task
├── Stop-LinkedInJobWorker.ps1      Kills the background worker
├── Run-LinkedInJobAlert.bat        Double-click launcher for the GUI
├── Run-LinkedInJobAlert.vbs        Silent launcher (no cmd window)
├── Start-LinkedInJobWorker-Hidden.vbs  Start background worker without cmd window
├── job-database.ps1                Legacy SQLite database helper (pre-Supabase era)
├── indeed_scraper.py               Legacy Indeed scraper (replaced by cloud/indeed.py)
├── telegram_linkedin_ai_assistant.py  Local Telegram bot (answers /status, /cover, etc.)
│
├── settings.json                   [GITIGNORED] All user settings + secrets
├── seen-jobs.json                  [GITIGNORED] Local dedup cache (job IDs seen)
├── jobs.db                         [GITIGNORED] Local SQLite mirror of Supabase
├── worker.log                      [GITIGNORED] Background worker output log
│
├── cloud/
│   ├── worker.py                   GitHub Actions entry point — orchestrates all scrapers
│   ├── db.py                       Supabase REST API client (all DB operations)
│   ├── linkedin.py                 LinkedIn scraper (HTTP, no browser)
│   ├── indeed.py                   Indeed RSS feed scraper
│   ├── adzuna.py                   Adzuna job API client
│   ├── websearch.py                Web deep search (Tavily → Brave → Google → Bing)
│   ├── gmail_scan.py               Gmail IMAP scanner (reads job alert emails)
│   ├── enricher.py                 Local Ollama AI scoring + cover letter drafts
│   ├── dedup.py                    Cross-source duplicate detection (embeddings)
│   ├── preferences.py              Active learning — few-shot from user history
│   ├── digest.py                   Daily 8am top-3 digest to Telegram
│   ├── telegram_notify.py          Telegram message formatting + send functions
│   ├── health_check.py             Checks if scanner is stuck, alerts if so
│   ├── relevance_engine.py         CV-driven 5-tier job relevance classifier (Phase 9)
│   ├── apply_executor.py           Playwright Easy Apply executor (Phase 10)
│   ├── requirements.txt            Python deps: requests==2.32.3, supabase==2.10.0
│   └── migrations/
│       ├── 2026-05-13-multi-criteria.sql   Phase 2 DB columns
│       ├── 2026-05-14-dedup.sql            Phase 3 DB columns
│       └── 2026-05-15-cover-letter.sql     Phase 5 DB column
│
├── mobile/                         Flutter Android/iOS app
│   ├── lib/
│   │   ├── main.dart               App entry — 3-tab shell (Cloud / Jobs / Settings)
│   │   ├── config.dart             Supabase URL + key hardcoded (anon key = safe to commit)
│   │   ├── models/
│   │   │   ├── job.dart            Job data model (all 20+ fields)
│   │   │   ├── app_settings.dart   Settings model (keywords, location, etc.)
│   │   │   └── cloud_status.dart   Cloud scanner status model
│   │   ├── services/
│   │   │   ├── supabase_service.dart   All Supabase REST calls from Flutter
│   │   │   ├── github_service.dart     GitHub Actions trigger + run status + easy-apply dispatch
│   │   │   ├── notification_service.dart  Local Android notifications for app updates
│   │   │   └── update_service.dart     APK self-update via Google Drive
│   │   ├── screens/
│   │   │   ├── dashboard_screen.dart   Tab 1 — cloud scanner status + controls
│   │   │   ├── jobs_screen.dart        Tab 2 — 5-tab list (All/New/Scored/Applied/Saved)
│   │   │   ├── job_detail_screen.dart  Full job detail + AI breakdown + cover letter + Easy Apply
│   │   │   ├── apply_preview_screen.dart  Easy Apply form — pre-filled from CV, editable
│   │   │   └── settings_screen.dart    Tab 3 — edit keywords, location, toggles
│   │   └── widgets/
│   │       ├── job_card.dart       Job row widget with score badge + skills hint + date groups
│   │       └── status_lamp.dart    Green/yellow/red status dot
│   ├── android/
│   │   └── app/
│   │       ├── build.gradle.kts    Android build — namespace: com.khalaf.jobalert
│   │       └── src/main/
│   │           └── kotlin/com/khalaf/jobalert/MainActivity.kt
│   └── pubspec.yaml                Flutter deps: http, url_launcher, intl, etc.
│
├── .github/workflows/
│   ├── job-alert.yml           Main scan — every 5 min, LinkedIn + Indeed + Adzuna
│   ├── daily-digest.yml        Daily 8am UAE digest — top 3 jobs
│   ├── health-check.yml        Every 3h — checks if scanner is stuck
│   ├── build-apk.yml           On tag push — build + sign + release APK
│   └── easy-apply.yml          workflow_dispatch — runs apply_executor.py via Playwright
│
├── UPDATES.md                  THIS FILE — project memory
├── README.md                   Public-facing instructions
└── .gitignore                  Excludes: settings.json, jobs.db, seen-jobs.json, *.log
```

---

## 5. Database Schema (Supabase)

### Table: `jobs`
```sql
CREATE TABLE jobs (
  job_id            TEXT PRIMARY KEY,
  title             TEXT,
  company           TEXT,
  location          TEXT,
  url               TEXT UNIQUE,
  source            TEXT,           -- 'LinkedIn', 'Indeed', 'Adzuna', 'Web', 'Gmail'
  status            TEXT DEFAULT 'new',  -- new | saved | applied | dismissed
  date_posted       TIMESTAMPTZ,
  date_collected    TIMESTAMPTZ,

  -- AI scoring (Phase 2)
  llm_score         SMALLINT,       -- overall 0-10
  llm_summary       TEXT,           -- one-line reasoning sentence
  skills_match      SMALLINT,       -- 0-10
  experience_match  SMALLINT,       -- 0-10
  location_match    SMALLINT,       -- 0-10
  seniority_match   SMALLINT,       -- 0-10
  matched_skills    JSONB,          -- ["Linux", "Active Directory", ...]
  missing_skills    JSONB,          -- ["AWS", "Kubernetes", ...]
  red_flags         JSONB,          -- ["requires Arabic only", ...]

  -- Deduplication (Phase 3)
  embedding         JSONB,          -- 768-dim float vector as JSON array
  duplicate_of_url  TEXT,           -- points to canonical job URL if duplicate
  dedup_checked_at  TIMESTAMPTZ,

  -- Cover letter (Phase 5)
  cover_letter_draft        TEXT,
  cover_letter_generated_at TIMESTAMPTZ
);
```

### Table: `bot_state`
```sql
CREATE TABLE bot_state (
  key   TEXT PRIMARY KEY,
  value TEXT
);
```

Used for key-value storage of:
- `setting_keywords`, `setting_location`, `setting_max_hours` — sync'd from GUI
- `setting_search_linkedin`, `setting_search_indeed`, `setting_search_adzuna`
- `setting_compact_telegram_alerts`
- `profile_cache_text`, `profile_cache_updated_at` — LinkedIn profile 24h cache
- `pref_few_shot_block`, `pref_few_shot_updated_at` — Phase 4 active learning cache

### RLS Policies (must be applied once in Supabase SQL editor)
```sql
-- Allow the anon key (used by worker, Flutter, PowerShell) to read/write everything
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY anon_full_access_jobs
  ON jobs FOR ALL TO anon USING (true) WITH CHECK (true);

ALTER TABLE bot_state ENABLE ROW LEVEL SECURITY;
CREATE POLICY anon_full_access_bot_state
  ON bot_state FOR ALL TO anon USING (true) WITH CHECK (true);
```

> **Critical:** Without these two policies, all writes return HTTP 401 and no data is ever saved.
> This was the root cause of "nothing appears in the app" for the first weeks.

### Migration SQL files (run in order in Supabase SQL editor)
```
cloud/migrations/2026-05-13-multi-criteria.sql   — Phase 2 columns
cloud/migrations/2026-05-14-dedup.sql            — Phase 3 columns + indexes
cloud/migrations/2026-05-15-cover-letter.sql     — Phase 5 column
```

---

## 6. How to Build From Scratch

Follow every step in order. Each section has a checkbox so you can track progress.

---

### Step 1 — Prerequisites (one-time, on your Windows laptop)

- [ ] **Git** — https://git-scm.com/download/win
- [ ] **Python 3.12** — https://python.org/downloads (add to PATH during install)
- [ ] **Ollama** — https://ollama.com/download/windows
  - After install, open PowerShell and run:
    ```powershell
    ollama pull llama3.1:latest
    ollama pull nomic-embed-text
    ollama serve   # keep running in background
    ```
- [ ] **Flutter SDK** — https://docs.flutter.dev/get-started/install/windows
  - Add `flutter\bin` to PATH
  - Run `flutter doctor` and fix any issues shown
- [ ] **Android Studio** (or just the SDK tools) — for Android emulator/device
- [ ] **PowerShell 5.1+** — already on Windows 10/11

---

### Step 2 — Create Supabase Project

1. Go to https://supabase.com → Sign up → New project
2. Choose a name (e.g. `job-alert`), pick a region close to UAE (e.g. `ap-southeast-1`)
3. Save your **Project URL** and **anon public key** (found in Project Settings → API)
4. Go to **SQL Editor** and run this to create the tables:

```sql
-- Main jobs table
CREATE TABLE jobs (
  job_id            TEXT PRIMARY KEY,
  title             TEXT,
  company           TEXT,
  location          TEXT,
  url               TEXT UNIQUE,
  source            TEXT,
  status            TEXT DEFAULT 'new',
  date_posted       TIMESTAMPTZ,
  date_collected    TIMESTAMPTZ,
  llm_score         SMALLINT,
  llm_summary       TEXT,
  skills_match      SMALLINT,
  experience_match  SMALLINT,
  location_match    SMALLINT,
  seniority_match   SMALLINT,
  matched_skills    JSONB DEFAULT '[]'::jsonb,
  missing_skills    JSONB DEFAULT '[]'::jsonb,
  red_flags         JSONB DEFAULT '[]'::jsonb,
  embedding         JSONB,
  duplicate_of_url  TEXT,
  dedup_checked_at  TIMESTAMPTZ,
  cover_letter_draft        TEXT,
  cover_letter_generated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS jobs_status_idx        ON jobs (status);
CREATE INDEX IF NOT EXISTS jobs_skills_match_idx  ON jobs (skills_match DESC);
CREATE INDEX IF NOT EXISTS jobs_company_collected_idx ON jobs (company, date_collected DESC);
CREATE INDEX IF NOT EXISTS jobs_duplicate_of_idx  ON jobs (duplicate_of_url)
  WHERE duplicate_of_url IS NOT NULL;

-- Settings / cache key-value store
CREATE TABLE bot_state (
  key   TEXT PRIMARY KEY,
  value TEXT
);

-- RLS: allow anon key to read and write
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY anon_full_access_jobs
  ON jobs FOR ALL TO anon USING (true) WITH CHECK (true);

ALTER TABLE bot_state ENABLE ROW LEVEL SECURITY;
CREATE POLICY anon_full_access_bot_state
  ON bot_state FOR ALL TO anon USING (true) WITH CHECK (true);
```

---

### Step 3 — Create Telegram Bot

1. Open Telegram → search for `@BotFather` → send `/newbot`
2. Follow prompts → get your **bot token** (looks like `1234567890:AAH...`)
3. Send your bot a message (any text)
4. Get your **chat ID**: open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in browser
   - Find `"chat":{"id":941885724}` — that number is your chat ID

---

### Step 4 — Clone / Set Up the Repository

```powershell
cd C:\Users\Mohamed Khalaf\Documents\Codex
git clone https://github.com/mohamedkhalaf0045-stack/job-alert.git
cd job-alert
```

Create `settings.json` in the project root (never commit this):

```json
{
  "Keywords": ["IT Support", "IT HelpDesk", "System Administrator", "IT Infrastructure"],
  "Location": "United Arab Emirates",
  "IntervalMinutes": 5,
  "TimeFilter": "Last 24 hours",
  "CustomHours": 10,
  "BrowserChoice": "Chrome (Chromium)",
  "LinkedInCookie": "li_at=AQE...",
  "HideAppliedJobs": true,
  "TelegramBotToken": "YOUR_BOT_TOKEN",
  "TelegramChatId": "YOUR_CHAT_ID",
  "SearchLinkedIn": true,
  "SearchIndeed": true,
  "ExcludeKeywords": "intern,fresh",
  "GitHubToken": "ghp_...",
  "GitHubRepo": "mohamedkhalaf0045-stack/job-alert",
  "SupabaseUrl": "https://YOUR-PROJECT-ID.supabase.co",
  "SupabaseKey": "eyJ...",
  "UserProfile": "C:\\path\\to\\your-cv.pdf",
  "MinAiScore": 1,
  "OllamaUrl": "http://localhost:11434",
  "ProfileText": ""
}
```

---

### Step 5 — Install Python Dependencies

```powershell
pip install requests==2.32.3 supabase==2.10.0
```

---

### Step 6 — Configure GitHub Actions Secrets

In the GitHub repo → Settings → Secrets and variables → Actions → New repository secret:

| Secret name | Value |
|-------------|-------|
| `SUPABASE_URL` | your Supabase project URL |
| `SUPABASE_KEY` | your Supabase anon key |
| `TELEGRAM_BOT_TOKEN` | your Telegram bot token |
| `TELEGRAM_CHAT_ID` | your Telegram chat ID |
| `LINKEDIN_COOKIE` | `li_at=AQE...` from browser |
| `KEYWORDS` | `IT Support,IT HelpDesk,System Administrator` |
| `LOCATION` | `United Arab Emirates` |
| `MAX_HOURS` | `24` |
| `SEARCH_LINKEDIN` | `true` |
| `SEARCH_INDEED` | `true` |
| `SEARCH_ADZUNA` | `false` (unless you have Adzuna keys) |
| `GH_PAT` | GitHub personal access token (for health-check to restart workflows) |

To get `LINKEDIN_COOKIE`:
1. Open LinkedIn in Chrome → F12 → Network tab
2. Reload page → click any request to linkedin.com
3. In Request Headers, find `cookie:` → copy the `li_at=...` part only

---

### Step 7 — Set Up Flutter App

```powershell
cd mobile
flutter pub get
```

Edit `lib/config.dart` to put in your Supabase credentials:
```dart
class Config {
  static const supabaseUrl = 'https://YOUR-PROJECT-ID.supabase.co';
  static const supabaseKey = 'eyJ...your-anon-key...';
  static const githubRepo  = 'yourusername/job-alert';
  static const githubToken = String.fromEnvironment('GITHUB_TOKEN', defaultValue: '');
}
```

Build and install on your phone:
```powershell
# Connect phone via USB with USB debugging enabled
flutter run                      # debug mode, connected phone
flutter build apk --release      # release APK
# APK output: build/app/outputs/flutter-apk/app-release.apk
# Copy to phone and install, or use:
adb install build/app/outputs/flutter-apk/app-release.apk
```

---

### Step 8 — Run the Health Check

```powershell
.\Run-EnrichmentHealthCheck.ps1
```

This checks:
1. settings.json exists and has required keys
2. `ollama` binary is in PATH
3. `llama3.1:latest` and `nomic-embed-text` are installed
4. Ollama daemon is reachable at `http://localhost:11434`
5. Python packages are installed
6. End-to-end test: score one real job from Supabase

---

### Step 9 — Launch the Desktop App

```powershell
.\linkedin-job-alert.ps1
```

Or double-click `Run-LinkedInJobAlert.bat`

Click **Start** — it will scan LinkedIn immediately, then every 5 minutes.

---

### Step 10 — Start the Background Worker (optional, runs when screen locked)

```powershell
# Start silently (no window):
.\Start-LinkedInJobWorker-Hidden.vbs

# Or install as logon task (starts automatically on login):
.\Install-LinkedInJobWorkerTask.ps1

# Stop it:
.\Stop-LinkedInJobWorker.ps1
```

---

### Step 11 — Run the AI Enricher (after some jobs accumulate)

```powershell
# Make sure Ollama is running first
ollama serve   # in a separate window if not already running

# Score up to 20 un-scored jobs
python cloud/enricher.py --limit 20 --verbose

# Watch scores appear in Supabase → jobs table → llm_score column
```

---

### Step 12 — Run Deduplication Backfill

```powershell
# Preview first (no changes):
python cloud/dedup.py --reprocess-all --dry-run

# Actually run:
python cloud/dedup.py --reprocess-all
```

---

## 7. Development History (All Commits, Newest First)

| # | Commit | What it does |
|---|--------|-------------|
| 1 | `ef652f9` | Drop stale web-search jobs that slip past freshness filter — final safety net after all other age checks |
| 2 | `6baccf7` | Easy Apply (Phase 10) — Flutter ApplyPreviewScreen pre-fills CV answers, confirm dialog, saves to Supabase, triggers easy-apply.yml via GitHub Actions; cloud/apply_executor.py runs Playwright on LinkedIn |
| 3 | `ac253ef` | Relevance engine: block generic-role false positives (Packaging Coordinator, Accountant, etc.) that matched CV domain terms |
| 4 | `bee1e03` | Flutter: add GitHub PAT setting field; fix "No GitHub token configured" error when triggering workflows |
| 5 | `c5a7b9d` | Restore immediate Telegram alerts (enricher was gating all alerts); add f_TPR time filter to PS1 scraper |
| 6 | `01fdb44` | 3-layer stale job notification guard — max_hours enforced in scraper, pre-DB filter, and Telegram gate |
| 7 | `e9f4db2` | LinkedIn: use geoId=101452733 for accurate UAE results; raise page limit from 25 to 40 |
| 8 | `91a8db4` | Phase 9 — CV-driven relevance engine (cloud/relevance_engine.py): 5-tier classifier replaces all hardcoded regex across worker + enricher; min_score Telegram gate reads setting_llm_min_score from Supabase; Flutter job list gains 5 tabs + date group headers |
| 9 | `d88687e` | Revert geoId — param caused wrong-country results, dropped all UAE jobs |
| 10 | `cec94a0` | LinkedIn: accept jobs with no parseable date when f_TPR filter is active |
| 11 | `a4990d1` | LinkedIn guest API URL: add f_TPR time filter + geoId |
| 12 | `17f37ca` | Flutter: enable core library desugaring to fix flutter_local_notifications Android build |
| 13 | `3108ba3` | Bump Flutter app version to 1.0.2+3 |
| 14 | `b547c09` | Flutter: local Android notification when app update is available — new NotificationService, _updateNotified flag prevents duplicates |
| 15 | `bd23d3f` | UI/UX polish — dashboard "Last run" → "Status" with red error tooltip; Flutter status lamp 64→96px; Windows GUI card drop shadows |
| 16 | `084f025` | Windows GUI: Gmail search controls — checkbox + email + app-password textboxes in Automation card; syncs to Supabase bot_state |
| 17 | `0fda718` | Windows GUI: initialize timer/job vars to null; stop all timers on FormClosing to prevent crashes on exit |
| 18 | `8e5fe28` | Pass max_hours to web search APIs as native freshness filter (not just post-filter) |
| 19 | `7622554` | Filter old/wrong-country jobs before DB insert — covers LinkedIn, Indeed, Adzuna, web search |
| 20 | `cb6f5a3` | Location filter for Gmail and web search — drops jobs outside configured country before Telegram alert |
| 21 | `6b912ef` | PowerShell GUI: right-click "Show AI breakdown" modal + "Copy cover letter" to clipboard |
| 22 | `4af8079` | Flutter: surfaces all Phase 2–5 data (score breakdown, skills chips, cover letter card, duplicate banner) |
| 23 | `ed97268` | Daily 8am Telegram digest of top 3 jobs (GitHub Actions cron) |
| 24 | `21c18a6` | Compact Telegram alerts toggle (2-line format for less noise) |
| 25 | `1b9c765` | Auto-generate cover letter drafts for jobs scoring >= 7 (second Ollama call) |
| 26 | `115bac8` | Active learning: inject user's applied/dismissed history as few-shot examples |
| 27 | `ab4be94` | Enricher skips scoring and Telegram alert for duplicate jobs |
| 28 | `42b7eda` | Cross-source deduplication via nomic-embed-text embeddings (cosine >= 0.92) |
| 29 | `05cb0f8` | Telegram alert format updated with emoji, sub-scores, matched/missing skills |
| 30 | `156fa00` | Multi-criteria LLM scoring: 4 axes + matched/missing/flags + 3 few-shot examples |
| 31 | `6aa4288` | AI lamp in PS status bar (green/yellow/red) + Run-EnrichmentHealthCheck.ps1 |
| 32 | `4e88b05` | Auto-trigger enricher after each worker scan (fire-and-forget, PID guard) |
| 33 | `5a665df` | Enricher: LINKEDIN_COOKIE env var, 24h profile cache, UTF-8 stdout fix |
| 34 | `bf4f70e` | Indeed: switch to RSS feed; GUI settings sync to Supabase |
| 35 | `816bc7c` | Fix 0-jobs scraping: better headers + resilient CSS fallbacks for LinkedIn |
| 36 | `e0b2644` | Hide console window via Win32 at PS script startup |
| 37 | `d9cfecc` | Suppress black PS console when launching GUI |
| 38 | `3d65bb4` | Auto-scan on startup + Telegram status column in job list |
| 39 | `a71e155` | Debug logging for LinkedIn HTML size and li count |
| 40 | `1644e1c` | Per-page progress logging to keep activity log alive |
| 41 | `31d176b` | Fix Gmail parser bugs found during live email test |
| 42 | `158a743` | Send Telegram score alert from enricher after local scoring |
| 43 | `fc8d56d` | Add Gmail job alert scanner (IMAP — reads job alert emails) |
| 44 | `b1e7966` | Fix duplicate Telegram alerts by tracking only newly inserted jobs |
| 45 | `ec7cb53` | Web deep search via Tavily → Brave → Google → Bing cascade (Level 3) |
| 46 | `bc770f5` | Remove Jooble (API defunct) — Adzuna only for aggregators |
| 47 | `079da34` | Add Jooble + Adzuna as Level 3 job aggregators |
| 48 | `01a606e` | Re-enable Indeed via HTTP-only scraping (no Playwright) |
| 49 | `d401405` | Add contents:write permission so workflow can create GitHub Releases |
| 50 | `2d9aee1` | Add MainActivity.kt + Android scaffold with correct package name |
| 51 | `c9039d7` | GitHub Releases APK distribution + signed CI build workflow |
| 52 | `7571849` | Scan every 5 min; skip Playwright install when Indeed disabled |
| 53 | `e2dd5a9` | Health alert timestamps in local timezone |
| 54 | `aa26399` | Fix LinkedIn 429 rate-limiting (slower polling, random delays) |
| 55 | `b71a841` | Cloud worker reads Supabase settings before requiring env vars |
| 56 | `b1afbce` | Flutter: add WidgetsFlutterBinding.ensureInitialized + crash guard |
| 57 | `bb8742d` | Flutter: self-update via Google Drive APK download |
| 58 | `bcba032` | Flutter: timezone auto-detect + local time in job dates |
| 59 | `5e1d3a3` | Fix: encode cutoff timestamp as Z suffix in health_check query |
| 60 | `000b26b` | Pass LinkedIn cookie to enricher for profile URL access |
| 61 | `3fc8d2f` | Show "Settings saved [OK]" feedback in GUI |
| 62 | `4ac5eb4` | Refresh Score column from Supabase after enrichment |
| 63 | `add11fd` | Fix default Ollama model name to llama3.1:latest |
| 64 | `3fb3410` | Add CV PDF + LinkedIn profile URL as scoring profile sources |
| 65 | `14f24ba` | Add LLM job scoring with local Ollama enrichment (Phase 1 baseline) |
| 66 | `8e3f637` | Add health check workflow + Supabase settings override in worker |
| 67 | `d7678ac` | Add /status Telegram command + cloud status lamp in Flutter |
| 68 | `38919b2` | Switch to Supabase REST API (HTTPS) — fixes IPv4/IPv6 issue on Actions |
| 69 | `637799d` | **Initial commit** — LinkedIn job alert app with cloud worker |

---

## 8. Smart AI Enhancement Phases (2026-05-06 → 2026-05-18)

### Phase 1 — Make AI Scoring Actually Work
**Problem:** AI scores never appeared because:
- The headless worker never called the enricher (only the GUI button did)
- LinkedIn profile fetch got a login-wall page → empty profile → useless prompt
- Supabase RLS blocked ALL writes from the anon role (HTTP 401 silently)

**Fix:**
- `linkedin-job-worker.ps1` → added `Invoke-EnricherAsync` — fires enricher after every scan with new jobs
- `cloud/enricher.py` → reads `LINKEDIN_COOKIE` env var; 24h profile cache in bot_state; profile chain: ProfileText → CV PDF → LinkedIn URL → hardcoded default
- Supabase SQL editor → added RLS policies for `anon` role
- New file: `Run-EnrichmentHealthCheck.ps1` — 6-step diagnostic
- `linkedin-job-alert.ps1` → AI lamp in status bar (polls every 30s)

---

### Phase 2 — Multi-Criteria Scoring
**Before:** One number (0–10) and one sentence
**After:** 4 sub-scores + skill lists + red flags

Prompt requests structured JSON:
```json
{
  "skills_match": 8, "experience_match": 7, "location_match": 9, "seniority_match": 6,
  "overall_score": 8, "matched_skills": ["Linux", "AD"], "missing_skills": ["K8s"],
  "red_flags": [], "reasoning": "Strong Linux background, good location fit"
}
```

Prompt includes 3 few-shot examples (strong match / clear miss / borderline) — biggest accuracy improvement for 8B models.

Migration: `cloud/migrations/2026-05-13-multi-criteria.sql`

---

### Phase 3 — Cross-Source Deduplication
**Problem:** Same job posted on LinkedIn + Indeed + Adzuna → 3 Telegram alerts, 3 scoring calls

**Solution:** Embed `title + company + first 200 chars` using `nomic-embed-text` (768-dim vector).
Compare cosine similarity against recent jobs of the same company. If >= 0.92 → mark as duplicate.

Only the canonical (first-seen) job gets scored and alerted. Duplicates are hidden in Flutter.

New file: `cloud/dedup.py`
Migration: `cloud/migrations/2026-05-14-dedup.sql`

---

### Phase 4 — Active Learning from History
**Idea:** Every time you mark a job "applied" (loved it) or "dismissed" (hated it), inject those
as live examples into the scoring prompt. The LLM learns your preferences from your own behavior.

Fetches last 5 applied + 5 dismissed jobs → formats as few-shot block → cached 6h in bot_state.

New file: `cloud/preferences.py`

---

### Phase 5 — Cover Letter Drafts
**For jobs scoring >= 7**, automatically generate a 200-word cover letter draft (second Ollama call).
Stored in `jobs.cover_letter_draft`. Flutter app shows a copy button. PowerShell right-click → "Copy cover letter".

New column: `cover_letter_draft` (via migration `2026-05-15-cover-letter.sql`)

---

### Phase 6 — Polish
- **Compact Telegram alerts** — `CompactTelegramAlerts: true` in settings.json → 2-line alerts instead of full breakdown
- **Daily 8am digest** — GitHub Actions cron at 04:00 UTC (8am Dubai) → sends top 3 jobs by score to Telegram

New files: `cloud/digest.py`, `.github/workflows/daily-digest.yml`

---

### Location Filter (standalone improvement)
**Problem:** Gmail scanner had no location awareness — jobs from Saudi Arabia, Egypt, etc.
appeared in Telegram alerts despite UAE location setting.

**Fix:**
- `cloud/gmail_scan.py` — added `_LOCATION_ALIASES` dict mapping country names to city
  variants (Dubai, Abu Dhabi, Sharjah, etc.); added `_job_location_matches(job_loc, filter)`;
  `scan_gmail()` now accepts a `location` parameter and filters parsed jobs before returning
- `cloud/worker.py` — passes `location=location` to `scan_gmail()`; web search results
  also filtered via `gmail_scan._job_location_matches()` after scraping

---

### CV Intelligence (Phase 7)
**Problem:** The enricher dumped raw PDF text (up to 5000 chars) into every scoring prompt.
LLM had to re-parse the CV on every job — inefficient and imprecise. No structured skills profile.
User had no visibility into what skills the AI extracted from their CV.

**Solution:** One-time AI analysis of the CV stores a structured skills profile permanently in
Supabase `bot_state`. Every subsequent scoring run uses the structured profile instead of
raw PDF text → faster, more accurate `matched_skills` / `missing_skills` lists.

**New file:** `cloud/cv_analyzer.py`
```
extract_cv_text(path)         — PDF → plain text via pypdf (max 6000 chars)
analyze_cv(text, url, model)  — Ollama call with format:"json" → structured dict:
                                 { skills, years_experience, job_titles,
                                   certifications, languages, education, summary }
store_cv_profile(url, key, p) — writes 8 keys to bot_state:
                                 cv_skills, cv_summary, cv_job_titles,
                                 cv_years_experience, cv_certifications,
                                 cv_languages, cv_education, cv_analyzed_at
get_cv_profile(url, key)      — reads back from bot_state; returns None if never analyzed
format_profile_for_prompt(p)  — formats dict as clean scoring prompt block:
                                 "Experience: 5 year(s) as IT Support Engineer
                                  Skills: Windows Server, Active Directory, Linux...
                                  Certifications: CCNA, CompTIA A+"
CLI:  python cloud/cv_analyzer.py --cv path.pdf   # analyze + store
      python cloud/cv_analyzer.py --show           # print current profile
```

**`cloud/enricher.py` changes:**
- `import cv_analyzer` added
- `resolve_profile_with_fallback()` — structured CV profile is now FIRST priority;
  falls back to raw PDF / text / default chain if not found (no regression)
- `ollama_score()` — description cap raised 2000 → 3000 chars
- `--analyze-cv` CLI flag added (calls cv_analyzer, then exits)

**`linkedin-job-alert.ps1` GUI changes (Automation card):**
- `UserProfileBox` width: 400 → 322 px to make room for two buttons
- `Browse PDF...` button repositioned (X=338, W=108)
- New **"Analyze CV"** accent button (X=452, W=112) — runs `cloud/cv_analyzer.py` as
  background job; spinner while running; disables button during analysis
- New **CV status label** (Y=234) — shows "CV: 24 skills extracted | Analyzed 2h ago"
  (green) or "CV: not analyzed yet" (gray) — updated on startup and after every analysis
- New **skills preview TextBox** (Y=256, H=44, read-only) — shows comma-separated
  skills list pulled from `cv_skills` in Supabase; lets user verify AI understood their CV
- **Browse PDF auto-triggers Analyze CV** — so user never needs to click it separately
- `Update-CvStatusLabel` function reads from Supabase REST API; called on startup and
  after each analysis completes
- Status bar, job listings card, log card all moved down 62 px to accommodate the taller
  Automation card; form height grown from 848 → 910 px

No DB schema changes — all new data uses existing `bot_state` table via `db.get_config` / `db.set_config`.

---

### Phase 8 — Gmail GUI + UI Polish + Local Notifications
**Work done around 2026-05-14 (the finishing touches missed from the Phase 7 write-up):**

- **Gmail search controls in Windows GUI** — new checkbox + email + app-password textboxes in the Automation card. Settings sync to Supabase `bot_state` so `cloud/worker.py` picks them up without a restart.
- **Windows GUI fixes** — timer/job variables initialised to null; all timers properly stopped on `FormClosing` to prevent crashes on exit; card drop-shadows added.
- **Flutter UI polish** — dashboard "Last run" label renamed to "Status", errors shown in red with a tooltip for the full message; status lamp enlarged from 64→96px; job count chips gain rounded corners + background colours; settings sections get subtle background tints.
- **Local Android notification** — new `NotificationService`: shows a high-priority notification when an app update is found; tapping it navigates to the Cloud tab. `_updateNotified` flag prevents duplicate alerts per session. Requests `POST_NOTIFICATIONS` permission on Android 13+.
- **Age enforcement tightened** — `max_hours` passed as a native freshness parameter to web-search APIs; stale/wrong-country jobs filtered pre-DB-insert across all five sources; 3-layer guard (scraper → pre-insert → Telegram gate) prevents old job notifications.

New file: `mobile/lib/services/notification_service.dart`

---

### Phase 9 — CV-Driven Relevance Engine
**Problem:** Hardcoded `_IT_DOMAIN_TERMS` / `_NON_IT_TITLE_REJECT` regexes were scattered
across `worker.py` and `enricher.py`. They needed manual updates whenever a new false-positive
appeared (e.g. "Packaging Coordinator", "Teacher-English" slipping through).

**Solution:** New `cloud/relevance_engine.py` — a 5-tier classifier driven entirely by the
structured CV profile already stored in Supabase. No hardcoded role lists.

```
T1  Any search keyword found in title (whole-word)           → ACCEPT
T2  Any CV job-title word found in title                     → ACCEPT
T3  Any CV skill word found in title                         → ACCEPT
T5* Hard-reject — title is clearly a non-target-field role   → REJECT  (evaluated before T4)
T4  Any CV domain-term found in title                        → ACCEPT
--  No tier matched                                          → REJECT
```

`cv_analyzer.py` gains `generate_domain_terms()` — derives filter words from CV skills and job
titles; stored as `cv_domain_terms` in `bot_state` automatically on every CV analysis.

`worker.py` removes all old helpers and calls `RelevanceEngine.from_supabase()` uniformly across
all five sources (LinkedIn, Indeed, Adzuna, Web, Gmail).

**Telegram gate:** `worker.py` reads `setting_llm_min_score` from Supabase; skips Telegram
alert for unscored jobs (deferred to enricher) and suppresses pre-scored jobs below min_score.

**`enricher.py`:** removes `_ENRICHER_NON_IT_TITLE`; uses `engine.is_relevant()` as a
pre-LLM gate. Irrelevant jobs get a structured rejection reason written to the Supabase
`llm_summary` field.

**Flutter jobs screen:** gains 5 tabs (All / New / Scored / Applied / Saved), date group headers,
smart sort (score DESC, then date DESC), enlarged score badge, and a summary chip on job cards.

New file: `cloud/relevance_engine.py`

---

### Phase 10 — Easy Apply
**What it does:** Lets you fill in your application answers on your phone, review them, then
trigger LinkedIn Easy Apply from GitHub Actions — without touching a laptop.

**Flutter (`mobile/`):**
- New `ApplyPreviewScreen` — loads CV profile from Supabase and pre-fills all answer fields
  (name, email, phone, city, years experience, job title, skills, work authorisation, notice
  period, salary expectation, why-interested statement). Every field is editable.
- "Confirm & Apply" button shows a confirmation dialog, then saves the answer package to
  Supabase (`apply_req_{job_id}`) and dispatches `easy-apply.yml` via `GitHubService`.
- "Easy Apply" teal button added to `JobDetailScreen`.
- `SupabaseService` gains: `getCvProfile()`, `saveApplyRequest()`, `getApplyRequest()`.
- `GitHubService` gains: `triggerEasyApply(jobId)`.

**Cloud:**
- `cloud/apply_executor.py` — Playwright executor: reads confirmed answers from Supabase,
  opens the job URL with the LinkedIn cookie, clicks Easy Apply, steps through every form
  page (phone, city, years, skills, notice, salary, why-interested, work-auth radios),
  submits, and writes result back to Supabase (`status: done / failed`).
- `.github/workflows/easy-apply.yml` — `workflow_dispatch` trigger accepting `job_id` input;
  installs Playwright + Chromium, runs `apply_executor.py`.

New files: `cloud/apply_executor.py`, `mobile/lib/screens/apply_preview_screen.dart`,
`.github/workflows/easy-apply.yml`

---

## 9. All Bugs Encountered and Fixed

| Bug | Root cause | Fix |
|-----|-----------|-----|
| Saudi Arabia / other-country jobs in Telegram alerts (round 1) | `scan_gmail()` had no location parameter — all parsed emails stored regardless of country | Added `_job_location_matches()` with UAE city alias table; `scan_gmail()` now filters by `location` before returning; web search results filtered same way in `worker.py` |
| Saudi Arabia / other-country jobs still arriving via LinkedIn (round 2) | LinkedIn, Indeed, and Adzuna scrapers had no post-scrape location filter — only Gmail/web search were filtered | Added `_loc_filter()` helper in `worker.py` and applied it to all four sources (LinkedIn, Indeed, Adzuna, web search) before `db.sync_jobs()` |
| AI scores never appeared | Enricher never auto-triggered from headless worker | Added `Invoke-EnricherAsync` to `linkedin-job-worker.ps1` |
| Supabase writes silently failed (HTTP 401) | RLS policies missing for `anon` role | Added `anon_full_access_jobs` + `anon_full_access_bot_state` policies in SQL editor |
| `timedelta` not found in db.py | Missing import | Added `timedelta` to top-level import |
| NUL bytes in PostgreSQL (error 22P05) | LinkedIn descriptions contained `\x00` characters | Added `_strip_nul()` + `_strip_nul_list()` helpers before all DB writes |
| Unicode box-drawing chars crashed Windows | `───` in enricher.py triggered cp1252 encoding error | Replaced with ASCII `---` |
| NUL byte literally in Python source file | Accidental `\x00` in a comment during edit | Binary-stripped with Python |
| em-dash `—` caused PowerShell parse error | PS parser doesn't accept em-dash in scripts | Replaced all `—` with `--` |
| `+00:00` in PostgREST query strings parsed as space | URL encoding: `+` = space in query params | Used `strftime("%Y-%m-%dT%H:%M:%SZ")` instead of `.isoformat()` |
| f-string typo: `_log("ERROR: Cannot reach {url}")` | Missing `f` prefix | Added `f` |
| Embeddings cold-start timeout (>30s) | `nomic-embed-text` first call after pull is slow | Kill competing enricher process, retry |
| Flutter app crashed on launch | Stale APK from before Android scaffold fixes | Needs fresh `flutter build apk --release` |
| Indeed returns 403 | Bot detection on Indeed search pages | Switched to RSS feed (partial — still unreliable) |
| Cloud worker showed `inserted=0` for weeks | RLS failure — inserts were silently rejected | Fixed by RLS policies |
| 0 jobs found in LinkedIn scan | LinkedIn changed CSS class names + returned SPA for auth URLs | Switch to guest URLs + resilient CSS fallbacks |
| LinkedIn 429 rate limiting | Too many rapid requests | Added random delays between page requests |
| Duplicate Telegram alerts | Both cloud worker and enricher sent alerts | Added dedup tracking — only newly-inserted jobs get alerted |
| Health check timestamps wrong timezone | datetime printed in UTC not local | Read `setting_timezone` from Supabase |
| GitHub Release workflow failed | Missing `contents: write` permission | Added `permissions: contents: write` to workflow |
| Flutter couldn't compile Android | Missing `MainActivity.kt` file | Added manually with correct package `com.khalaf.jobalert` |
| Supabase connection failed on GitHub Actions | IPv6 unreachable; direct PostgreSQL tried ipv6 | Switched from direct PG connection to PostgREST (HTTPS) |
| Non-IT jobs slipping through (Teacher-English, Packaging Coordinator) | Hardcoded `_IT_DOMAIN_TERMS` too broad; "teacher" and "coordinator" matched generic domain words | Phase 9: replaced all hardcoded filters with `RelevanceEngine` T5 hard-reject tier, evaluated before the domain-term catch-all |
| LinkedIn geoId caused wrong-country results | geoId=101452733 returned jobs from wrong countries in some query combinations | Reverted to plain `location=United+Arab+Emirates` query param; kept f_TPR time filter |
| score-1 jobs being Telegrammed when min_score=6 | `worker.py` alerted all newly-inserted jobs regardless of score | Added `setting_llm_min_score` gate: unscored jobs deferred to enricher; pre-scored jobs below threshold suppressed |
| Stale jobs still appearing in Telegram alerts | Age check only in scraper; jobs re-inserted from cache could bypass it | Added 3-layer guard: native API freshness param + pre-DB-insert date check + Telegram send gate |
| flutter_local_notifications build failed on Android | Requires Java 8+ desugaring; not enabled by default | Added `coreLibraryDesugaringEnabled = true` to `build.gradle.kts` |
| Windows GUI crashed on close if scan was running | Timer callbacks fired after form disposed; null reference on job list | Initialised timer/job vars to null; stop all timers in `FormClosing` event handler |

---

## 10. Pending Tasks

### Must Do Soon
- [ ] **Build fresh Android APK** — current APK on phone is stale (Easy Apply, 5-tab list, local notifications not on phone yet)
  ```powershell
  cd mobile
  flutter build apk --release
  # Output: build\app\outputs\flutter-apk\app-release.apk
  # Install: adb install build\app\outputs\flutter-apk\app-release.apk
  # Or copy to phone manually
  ```

- [x] **Push all commits to GitHub** — done; branch is up to date with origin/main as of 2026-05-18

- [ ] **Run CV analysis for the first time** — open the app, click Browse PDF, pick your CV,
  the Analyze CV button auto-triggers. Or run manually:
  ```powershell
  python cloud/cv_analyzer.py --cv "C:\path\to\your\cv.pdf"
  python cloud/cv_analyzer.py --show   # verify what was extracted
  ```

### Should Do
- [ ] **Bulk generate cover letters for existing jobs** — ~60 jobs with `llm_score >= 7` have none
  - Need to add `--force-cover-letters` flag to `cloud/enricher.py`
  - Or run: `python cloud/enricher.py --limit 100` (picks up ones missing cover letters)

- [ ] **Reduce Phase 4 cache TTL** — currently 6h; after marking applied/dismissed, takes up to 6h to affect scoring
  - In `cloud/preferences.py` → change `CACHE_TTL_HOURS = 6` to `CACHE_TTL_HOURS = 1`

### Nice to Have
- [ ] **`/cover {job_id}` Telegram command** — serve cover letter on demand from `telegram_linkedin_ai_assistant.py`
- [ ] **Indeed scraping fix** — RSS feed is unreliable; consider Adzuna API or Google Jobs RSS as full replacement
- [ ] **"Similar to N jobs you applied to" badge** — Phase 4 cosmetic: show in Flutter job detail how many applied jobs match this one by embedding similarity
- [ ] **Salary extraction** — parse salary ranges from descriptions; add `salary_min`/`salary_max` columns
- [ ] **Score history chart** — Flutter dashboard tab showing match quality trend over days
- [ ] **Settings UI toggle for compact alerts** — currently set manually in `settings.json`

---

## 11. Day-to-Day Operations

### Start everything (morning routine)
```powershell
# 1. Start Ollama (if not already running as a service)
ollama serve

# 2. Start the desktop GUI
.\linkedin-job-alert.ps1

# OR: start the background worker only (no GUI)
.\Start-LinkedInJobWorker-Hidden.vbs
```

### Check if enricher is working
```powershell
.\Run-EnrichmentHealthCheck.ps1
# Should print: OK — Ollama up, profile fetched, 1 job scored successfully
```

### Manual enrichment run (score all pending jobs)
```powershell
python cloud/enricher.py --limit 50 --verbose
```

### Trigger cloud scan manually (from GitHub)
- Go to repo → Actions → "Job Alert Scan" → Run workflow

### Update LinkedIn cookie (when it expires, usually every 2–4 weeks)
1. Open LinkedIn in Chrome → F12 → Network → reload → click any request
2. Request Headers → find `cookie:` → copy only the `li_at=...` portion
3. Paste into `settings.json` → `LinkedInCookie` field
4. Also update GitHub Secret `LINKEDIN_COOKIE`

---

## 12. How to Start a New Claude Session for This Project

Paste this at the start:

```
I am working on my LinkedIn UAE job-alert project.
Location: C:\Users\Mohamed Khalaf\Documents\Codex\2026-05-06\create-a-simple-windows-app-to\
Read UPDATES.md first — it is the complete project memory.

Stack:
- PowerShell desktop app (linkedin-job-alert.ps1)
- Python cloud worker via GitHub Actions (cloud/worker.py → Supabase)
- Local Ollama AI enrichment (llama3.1:latest + nomic-embed-text)
- Flutter Android app (mobile/)
- Supabase as central database
- Telegram for push alerts

After reading UPDATES.md, check the "Pending Tasks" section and continue from there.
```

---

*End of UPDATES.md — update this file after every session.*
