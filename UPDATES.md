# LinkedIn Job Alert — Complete Project Memory

> **How to use this file:**
> - Read it at the start of every new Claude session before asking for anything
> - Update the "Pending Tasks" section whenever something is done or added
> - This file is the single source of truth for what exists, how it works, and what comes next
>
> Last updated: 2026-06-01

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
| **Groq** | Cloud LLM fallback for scoring (when Ollama is down/slow) | Yes (free tier) | console.groq.com |
| **LinkedIn** | Job source (scraped, no API) | Uses cookie | Your browser session |
| **Indeed** | Job source (Playwright headless Chrome — RSS now 403; residential IP only) | Yes | No auth needed |
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
│   ├── bayt.py                     Bayt.com scraper (UAE #1 job board, priority 2)
│   ├── gulftalent.py               GulfTalent.com scraper (UAE, priority 3)
│   ├── naukri_gulf.py              NaukriGulf.com scraper (UAE/MENA, priority 4)
│   ├── indeed.py                   Indeed Playwright scraper (RSS now 403; skipped on GitHub Actions — datacenter IPs blocked)
│   ├── adzuna.py                   Adzuna job API client
│   ├── websearch.py                Web deep search (Tavily → Brave → Google → Bing)
│   ├── gmail_scan.py               Gmail IMAP scanner (reads job alert emails)
│   ├── enricher.py                 Local Ollama: scoring + cover letter + tailored CV
│   ├── dedup.py                    Cross-source duplicate detection (embeddings)
│   ├── preferences.py              Active learning -- few-shot from user history
│   ├── digest.py                   Daily 8am top-3 digest to Telegram
│   ├── telegram_notify.py          Telegram formatting + send + inline buttons
│   ├── health_check.py             Checks if scanner is stuck, alerts if so
│   ├── relevance_engine.py         CV-driven 5-tier job relevance classifier (Phase 9)
│   ├── cv_analyzer.py              AI CV parsing → structured profile in Supabase
│   ├── apply_executor.py           Playwright Easy Apply executor (Phase 10)
│   ├── url_safety.py               URL safety check + tracking-param stripper
│   ├── runner.py                   Railway persistent loop runner (2-min interval)
│   ├── requirements.txt            Python deps: requests==2.32.3, supabase==2.10.0
│   └── migrations/
│       ├── 2026-05-13-multi-criteria.sql   Phase 2 DB columns
│       ├── 2026-05-14-dedup.sql            Phase 3 DB columns
│       ├── 2026-05-15-cover-letter.sql     Phase 5 DB column
│       └── 2026-05-19-tailored-cv.sql      Tailored CV columns (⚠️ run this!)
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
  cover_letter_generated_at TIMESTAMPTZ,

  -- Tailored CV per job (2026-05-19) -- run migrations/2026-05-19-tailored-cv.sql
  tailored_cv_draft         TEXT,
  tailored_cv_generated_at  TIMESTAMPTZ
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
- `setting_groq_api_key`, `setting_groq_model`, `setting_prefer_cloud` — Groq cloud-scoring fallback (Phase 18)
- `worker_last_run` — heartbeat timestamp for downtime detection (Phase 17)
- `linkedin_zero_streak`, `linkedin_cookie_alerted` — LinkedIn cookie-expiry detection state (Phase 17)
- `setting_healthcheck_url` — optional external dead-man's-switch ping URL (Phase 17)

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
cloud/migrations/2026-05-13-multi-criteria.sql   -- Phase 2 columns
cloud/migrations/2026-05-14-dedup.sql            -- Phase 3 columns + indexes
cloud/migrations/2026-05-15-cover-letter.sql     -- Phase 5 column
cloud/migrations/2026-05-19-tailored-cv.sql      -- Tailored CV columns (⚠️ not yet run!)
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
  cover_letter_generated_at TIMESTAMPTZ,
  tailored_cv_draft         TEXT,
  tailored_cv_generated_at  TIMESTAMPTZ
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
| — | `cb7b4f2` | **(2026-06-01)** Enricher `--prefer-cloud` / `setting_prefer_cloud`: score via Groq directly for fast backlog clearing |
| — | `a9a4ee9` | **(2026-06-01)** Indeed skips on GitHub Actions (datacenter IPs blocked by Cloudflare); drop pointless Chromium install from workflow |
| — | `d5346fa` | **(2026-06-01)** Indeed: wait for `[data-jk]` job cards, not `networkidle` (fixes 30s timeouts) |
| — | `b5429f4` | **(2026-06-01)** CI: install Playwright Chromium in job-alert workflow (later refined) |
| — | `29169bb` | **(2026-06-01)** Merge PR #1 — worker resilience |
| — | `f130068` | **(2026-06-01)** Worker resilience: downtime alert + LinkedIn cookie-expiry alert + Groq fallback + Indeed Playwright + relevance-engine tuning (Phases 17–19) |
| 1 | `79ba2cc` | Tailored CV per job: enricher generates a role-specific CV draft (score >= 7); two inline buttons in Telegram: "📝 Cover Letter" + "📄 Tailored CV"; worker handles cv_ callbacks |
| 2 | `988fae8` | Cover Letter button: every Telegram alert now has an inline "📝 Cover Letter" button; worker handles cover_ callbacks on-demand (not auto-sent) |
| 3 | `5d348ea` | URL safety checker: validates every link before Telegram send (HTTPS only, no IP/shortener/bad-TLD, 40+ trusted-domain whitelist); strips UTM/tracking params |
| 4 | `9e24414` | Railway deployment: cloud/runner.py loops every 2 min; railway.toml configures build + start command |
| 5 | `f6f8928` | (pre-button) Enricher auto-sent cover letter to Telegram — later changed to button UX |
| 6 | `0124d84` | Per-source instant alerts: _alert_new() called after each sync_jobs() so LinkedIn jobs reach phone in seconds; GulfTalent + NaukriGulf scrapers added; ntfy.sh push for score >= 7 |
| 7 | `70bb5bc` | Bayt.com scraper: UAE's #1 job board added as priority 2 source |
| 8 | `3184609` | Web search listing-page fix: reject aggregator/listing URLs (Glassdoor SRCH, Indeed /q-l-jobs, etc.) — only individual job postings allowed |
| 9 | `2451224` | APK infinite update loop fix: normalize version tag by stripping -dev/-beta suffix before comparison |
| 10 | `76173ab` | Re-alert scan catches jobs that entered DB but were never notified |
| 11 | `ef652f9` | Drop stale web-search jobs that slip past freshness filter — final safety net after all other age checks |
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

### Phase 11 — New UAE Sources + Instant Per-Source Alerts
**Goal:** Get matching jobs before anyone else.

**New scrapers:**
- `cloud/bayt.py` — Bayt.com (UAE's #1 job board). Priority 2 after LinkedIn.
- `cloud/gulftalent.py` — GulfTalent.com. Priority 3. BeautifulSoup4 HTML parsing with fallback.
- `cloud/naukri_gulf.py` — NaukriGulf.com. Priority 4. Slug-based pagination.

**Instant alerts:** `_alert_new()` closure in `worker.py` is called immediately after each
`sync_jobs()` call — not at the end of the full scan. LinkedIn jobs reach the phone within
seconds of being found, not minutes.

**Source priority ordering:** LinkedIn(1) → Bayt(2) → GulfTalent(3) → NaukriGulf(4) →
Indeed(5) → Gmail(6) → Adzuna(7) → Web(8).

**ntfy.sh push:** Optionally sends a native phone notification (not Telegram) for jobs
scoring >= 7. Set `setting_ntfy_url` in Supabase `bot_state` to enable.
Example value: `https://ntfy.sh/your-topic-name`

---

### Phase 12 — URL Safety Layer
**Goal:** Never accidentally send a phishing or malicious link to the user's phone.

**New file: `cloud/url_safety.py`**
- `check_url(url) → (bool, reason)`: 9 rules — HTTPS only, no bare IPs, no URL shorteners,
  no suspicious TLDs (.ru/.cn/etc.), no executable extensions, max 2000 chars, trusted-domain
  whitelist (40+ ATS + job boards).
- `sanitize_url(url) → str`: strips `utm_*`, `fbclid`, `gclid`, `trk`, `_ga` tracking params.

Every Telegram link goes through `url_safety.check_url()` before send. Sanitized URL
(not the raw scraped URL) is what the user sees and clicks.

---

### Phase 13 — Cover Letter On-Demand Button
**Goal:** User asked for a button, not an auto-sent wall of text.

Every job alert in Telegram now has an inline `[📝 Cover Letter]` button.
When the user taps it, the worker picks up the `cover_{job_id}` callback on the next run
and sends the pre-generated cover letter draft.

`telegram_notify.py` — `send_job_alert_with_button()` sends inline keyboard with the button.
`worker.py` — polls `getUpdates` at run start, handles `cover_*` callbacks.
`answer_callback_query()` called within the run to dismiss the loading spinner on the button.

---

### Phase 14 — Railway Deployment (2-Minute Scanning)
**Goal:** GitHub Actions minimum cron = 5 min. Railway runs a persistent process.

**New files:**
- `cloud/runner.py` — infinite loop calling `worker.py` every 2 min (`SCAN_INTERVAL_SECONDS`, default 120).
- `railway.toml` — build: nixpacks, start: `pip install -r cloud/requirements.txt && python cloud/runner.py`.

Deploy: connect the repo to Railway, set the same 3 GitHub Actions secrets as env vars.
Cost: Railway free tier covers ~500 hours/month (enough for 24/7 with hobby plan).

---

### Phase 15 — Web Search Listing-Page Fix
**Goal:** Web search was returning Glassdoor/Indeed listing pages (100 jobs per page) as if
they were individual job postings.

**Fix in `cloud/websearch.py`:**
- `_LISTING_PAGE_URL` regex: matches Glassdoor `SRCH_*`, Indeed `/q-*-l-*-jobs.html`,
  `/jobs/search`, `/job-search`, generic `?keywords=` query strings.
- `_LISTING_PAGE_TITLE` regex: matches "247 jobs in Dubai", "Search Results", "Job Board".
- `_is_job_url(url, title)`: returns False for listing pages. Only individual job postings pass.

---

### Phase 16 — Tailored CV Per Job
**Goal:** For each high-scoring job, rewrite the user's CV to match that specific role's
language and requirements — making it past ATS screening.

**How it works:**
- `enricher.py` calls `generate_tailored_cv()` for jobs scoring >= 7 (capped at 3/run).
- Prompt rules: no invented content, reorder sections by relevance, name company and role
  in summary, echo job description language in bullet points, plain text, max 600 words.
- Output sections: PROFESSIONAL SUMMARY, CORE SKILLS, PROFESSIONAL EXPERIENCE,
  EDUCATION & CERTIFICATIONS.
- Saved to `jobs.tailored_cv_draft` in Supabase.

**Telegram delivery:**
Every alert now has TWO inline buttons:
```
[📝 Cover Letter]  [📄 Tailored CV]
```
Tap either → delivered to Telegram on next worker run.

**Migration required:** Run `cloud/migrations/2026-05-19-tailored-cv.sql` in Supabase SQL Editor.

---

### Phase 17 — Worker Resilience (2026-06-01)
**Problem:** When the pipeline broke, it broke *silently*. Two real incidents:
1. The worker was off for 2 days (laptop asleep) — no jobs, no warning.
2. The local LinkedIn cookie expired — LinkedIn returned 0 jobs for days, but
   because Indeed kept inserting jobs, the existing `health_check.py`
   ("0 jobs in 25h") never fired. The dead cookie went unnoticed.

**Solution (all in `cloud/worker.py`):**
- **Downtime alert** — worker writes `worker_last_run` to `bot_state` at the end
  of every run. On the next run, if the gap exceeds 30 min (6 missed cycles) it
  sends a Telegram alert: *"⚠️ Worker was offline for ~Xh… jobs may have been missed."*
- **LinkedIn cookie-expiry alert** — tracks the per-run LinkedIn result total
  across all keywords. A run-total of exactly 0 (nothing inserted/updated/seen/
  invalid) is the signature of a dead cookie, not "no new jobs". After 3
  consecutive empty runs it sends a one-time alert telling the user to refresh
  `li_at`, with step-by-step instructions. Auto re-arms (`linkedin_cookie_alerted`
  reset) once LinkedIn recovers. State in `linkedin_zero_streak`.
- **External dead-man's switch (optional)** — if `setting_healthcheck_url` is set,
  the worker GETs it each run so an external monitor (e.g. healthchecks.io) can
  page if the worker stops pinging entirely.
- **`_ENV_TO_JSON` fix** — mapped `SEARCH_LINKEDIN`, `SEARCH_INDEED`,
  `HIDE_APPLIED` so `settings.json` toggles actually take effect (previously
  `SearchIndeed: true` in settings.json was silently ignored).

---

### Phase 18 — Cloud LLM Fallback (Groq) (2026-06-01)
**Problem:** The enricher hadn't run since ~May 21 — Ollama times out on the
low-RAM Windows box. An **871-job backlog** of unscored jobs piled up. Without a
fallback, each job would also waste the full 300 s Ollama timeout before failing.

**Solution (all in `cloud/enricher.py`):**
- **Groq cloud fallback** — when Ollama is unreachable or times out, scoring
  falls back to Groq's free, OpenAI-compatible API (`llama-3.3-70b-versatile`),
  which scores in <1 s. Graceful no-op when no key is set. Key read from
  `setting_groq_api_key` / `GROQ_API_KEY` / `--groq-key`.
- **`--prefer-cloud` / `setting_prefer_cloud`** — skips Ollama entirely and
  scores via Groq directly. Essential for backlog clearing: without it, a machine
  whose Ollama times out would burn 300 s × 871 ≈ 72 h just on timeouts.
  **Set to `true` in Supabase** for this user (their Ollama times out).
- **Shared `_breakdown_from_json()`** — one validated JSON parser used by both the
  Ollama and Groq paths (no duplicated clamp/clean logic).
- **Staleness gate on the score-update path** — previously only *new* alerts were
  age-gated; the "score update for an already-alerted job" branch had no age check,
  so a 4-day-old backlog job (e.g. the Parsons 7/10) still pinged Telegram. Now
  both paths skip jobs older than `max(setting_max_hours, 48h)`.

**To get a key:** console.groq.com → Create API Key (`gsk_...`) → stored in
`bot_state.setting_groq_api_key`. Verified end-to-end: scored a real
"Senior IT End User Specialist" 9/10.

---

### Phase 19 — Indeed Playwright Scraper (2026-06-01)
**Problem:** Indeed's RSS feed now returns **HTTP 403 on all domains**
(Cloudflare Bot Management). `cloud/indeed.py` returned 0 jobs.

**Solution:**
- Rewrote `cloud/indeed.py` to use **Playwright headless Chromium**. Loads the
  `/jobs` search page, waits for `[data-jk]` job cards (not `networkidle`, which
  never settles on Indeed), extracts title/company/location/age from the DOM,
  paginates one page deep. Returns 16 jobs locally for "IT Support" in UAE.
- **Datacenter-IP block** — Indeed serves a block page to GitHub Actions
  (datacenter IP) while allowing residential IPs. `scrape_indeed()` detects
  `GITHUB_ACTIONS=true` and skips Indeed instantly, so the cloud worker doesn't
  waste ~20 s/keyword on a guaranteed-empty fetch. **Indeed is collected only by
  the local (residential) worker.**
- `cloud/requirements.txt` gains `playwright>=1.44.0`; `linux/setup.sh` gains
  `playwright install --with-deps chromium`.

---

### Relevance Engine Tuning (2026-06-01)
Ongoing refinements to `cloud/relevance_engine.py` from auditing 5 days of alerts:
- Added `_IT_CORE_TERMS = {soc, noc, csirt, gsoc}` — always merged into domain
  terms so "SOC Analyst" / "NOC Engineer" pass (security-ops roles).
- Added `admin`, `senior` to `_KEYWORD_WORD_BLOCKLIST` (and applied the blocklist
  to `cv_domain_terms`, not just keyword/title words) — stops "Female Admin",
  "Senior BIM Engineer", "Senior Engagement Manager" false positives.
- New T5 hard-reject patterns: software/web/mobile **developer** roles
  (the user is IT support/sysadmin, not a dev), consulting (`engagement manager`,
  `management consultant`, `strategy manager`), and many more non-IT disciplines.
- New `T_DESC` tier — accepts a vague title when the **description** contains a
  highly specific IT tool (Intune, SCCM, Fortinet, Veeam, etc.).

---

### Phase 20 — Position-Name Matching + "Search → Think → Learn" (2026-06-01)
**Problem:** The relevance engine matched **single words** — it split "IT Help Desk"
into `it`/`help`/`desk` and accepted a job if *any one* appeared. That let
"Housekeeping Desk", "Security Guard" (security), "Cloud Kitchen Manager" (cloud)
through. The user's directive: *"don't use one keyword… search with all position
names, not word by word… then check the description against my CV."*

**The model — three stages:**
```
1. SEARCH → match full POSITION NAMES (title gate)   [wide, clean net]
2. THINK  → LLM reads description, reasons vs CV       [keeps only real matches]
3. LEARN  → applies/dismisses retrain the THINK step   [smarter over time]
```

**Stage 1 — Position-name title gate (`cloud/relevance_engine.py`, the NEW work):**
- A title qualifies only when it contains **ALL** significant words of at least one
  *position phrase* (order-independent). One generic word never accepts a job.
- Position phrases come from: user keywords + **64 built-in canonical IT positions**
  ("network administrator", "cloud engineer", "service desk", "soc analyst"…) +
  the user's own CV job titles.
- Normalization: `systems`≈`system`, `admin`≈`administrator`, plus token expansion
  (`sysadmin`→system+administrator, `helpdesk`→help+desk, `m365`→microsoft+365).
- **Every phrase requires ≥2 words** — enforces "not word by word". A bare "IT"
  keyword contributes no phrase; "IT X" roles are covered by 2-word built-ins.
- Removed the leaky word-by-word T1–T4 tiers. Kept T5 hard-reject (+ hospitality
  cluster), T1P desk-compounds, and T_DESC (description IT-vocab) as a rescue when
  the title is vague but the description is clearly IT.
- Verified live in the cloud: "Housekeeping Desk Coordinator" → dropped; Data
  Scientist / Head of Operations / Co-Founder (CTO) / Talent Management Specialist
  → dropped; IT Support / System Administrator / IT Helpdesk / IT Infrastructure
  → accepted. 49/49 regression cases pass.

**Stage 2 — "Think" (already operational):** the enricher's Groq scoring reads the
description and reasons about fit vs the CV (skills/experience/seniority) with a
rationale. Fast (<1s via Groq, `setting_prefer_cloud=true`).

**Stage 3 — "Learn" (already operational):** `cloud/preferences.py` feeds the last
applied/dismissed jobs into the scoring prompt as few-shot examples, so the THINK
step calibrates to the user's taste. Feedback signal = the `status` field
(applied/dismissed/saved) set from the mobile app. *(Optional future add: Telegram
👍/👎 buttons for one-tap feedback — not yet built.)*

**Speed:** a stricter title gate means **fewer** jobs reach the LLM, and Groq scores
in <1s — so the pipeline is both more accurate and faster than before.

---

### Phase 21 — Monitoring & Control Dashboard (2026-06-01)
**Goal:** Real-time visibility and full control over the whole pipeline — logs,
process status, and one-click actions — from the web and the Windows GUI.

**New file: `cloud/dashboard.py`** — a zero-dependency (stdlib-only) local web
server + single-page dashboard. Run `python cloud/dashboard.py` → opens
`http://127.0.0.1:8765` (binds to localhost only, so Supabase/GitHub creds never
leave the machine). It reads credentials from the same `settings.json`.

Monitoring (auto-refresh every 4s):
- **Worker health** — local heartbeat (`worker_last_run`), GitHub Actions last
  run + conclusion + age, LinkedIn cookie health (`linkedin_zero_streak`).
- **Job stats** — total / scored / backlog / sent / collected-today /
  applied / dismissed, plus a breakdown by source.
- **AI scoring** — Groq key present?, prefer-cloud on?, model, live enricher
  process state, backlog size.
- **Live logs** — tails `worker.log`, `enricher.log`, and dashboard-launched
  run logs, streaming.
- **Recent cloud runs** — last GitHub Actions runs with status + links.

Full control (write):
- ▶ **Trigger Cloud Scan** — GitHub `workflow_dispatch` of job-alert.yml.
- 🤖 **Run Enricher** — launches `enricher.py --prefer-cloud --limit N` to clear
  the backlog via Groq; output tailed live.
- 🖥️ **Run Local Scan** — runs `cloud/worker.py` once.
- 💾 **Settings** — edit keywords / min-score / max-hours / prefer-cloud,
  saved straight to Supabase `bot_state`.
- **Jobs table** — filter (all/new/scored/backlog/applied/dismissed) and mark
  jobs applied/dismissed inline.

REST endpoints: `/api/status`, `/api/logs`, `/api/jobs`, `/api/scan`,
`/api/enrich`, `/api/worker`, `/api/settings`, `/api/job`.

**Windows GUI integration (`linkedin-job-alert.ps1`):** a **"Monitoring
Dashboard"** button added to the header bar. It starts the dashboard server
(hidden) if not already running, then opens the browser — idempotent (re-uses
the running server via a localhost TCP check). The GUI is a flat 2752-line
WinForms form with no TabControl, so a launch-button into the richer web
dashboard is safer and better for real-time monitoring than retrofitting a
native tab.

**Also:** `Open-Dashboard.bat` — double-click launcher.

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
| APK infinite update loop | `tag_name = "v1.0.4-dev"` → version "1.0.4-dev" never matched app version "1.0.4" → always triggered update | Strip suffix with `.split(RegExp(r'[-+]')).first` in `update_service.dart` |
| Web search returning listing pages (100 jobs per page) | Glassdoor/Indeed search URLs passed `_is_job_url()` because it only checked host, not URL path pattern | Added `_LISTING_PAGE_URL` + `_LISTING_PAGE_TITLE` regex to `websearch.py`; both URL and page title are checked |
| Double Telegram alerts on some jobs | `already_sent` set was initialized inside the scan loop, not before it | Moved initialization before the keyword loop so all per-source instant alerts share the same dedup set |
| Indeed returns 403 on RSS (all domains) | Cloudflare now blocks the RSS feed entirely | Rewrote `cloud/indeed.py` with Playwright headless Chromium (Phase 19) |
| Indeed returns 0 on GitHub Actions | Cloudflare blocks datacenter IPs (works on residential) | Skip Indeed when `GITHUB_ACTIONS=true`; collected by local worker only |
| `SearchIndeed: true` in settings.json ignored | `SEARCH_INDEED` missing from `_ENV_TO_JSON` map in `worker.py` | Added `SEARCH_INDEED`/`SEARCH_LINKEDIN`/`HIDE_APPLIED` to the map |
| Dead LinkedIn cookie went unnoticed for days | `health_check.py` only fires on "0 jobs in 25h"; Indeed kept inserting so total was never 0 | Phase 17 LinkedIn-specific cookie-expiry alert (3 empty LinkedIn runs) |
| 4-day-old job (Parsons 7/10) alerted from backlog | Staleness gate applied only to new alerts, not the enricher score-update path | Apply `max(max_hours,48h)` age gate to both alert paths |
| 871-job enricher backlog never cleared | Ollama times out on low-RAM Windows; no fallback | Phase 18 Groq cloud fallback + `--prefer-cloud` |
| Worker offline 2 days with no warning | No heartbeat / downtime detection | Phase 17 `worker_last_run` heartbeat + >30min gap Telegram alert |
| "Housekeeping Desk" alerted (and class of word-by-word false positives) | Engine matched single words — "IT Help Desk" → `desk` matched any "…Desk" title | Phase 20 position-name gate: title must contain ALL words of a ≥2-word position phrase |

---

## 10. Pending Tasks

### 🆕 Added 2026-06-01 (Phases 17–19)

- [x] **Groq cloud fallback configured** — `setting_groq_api_key` + `setting_prefer_cloud=true`
  set in Supabase. The enricher now scores via Groq (free, <1s/job) instead of stalling on
  Ollama timeouts.
- [ ] **Clear the 871-job backlog** — now feasible via Groq. Run on the local (residential)
  machine so LinkedIn descriptions fetch:
  ```powershell
  python cloud/enricher.py --limit 200 --prefer-cloud
  ```
  Bottleneck is ~40s/job for the LinkedIn description fetch (scoring itself is instant).
  Jobs older than 48h are scored silently (no Telegram spam); recent high-scorers notify.
- [ ] **Refresh the LOCAL LinkedIn cookie** — the cloud worker's cookie (GitHub secret) is
  alive and delivering LinkedIn jobs 24/7. The *local* PowerShell worker's cookie is dead,
  but that only matters for local LinkedIn scans (Indeed still works locally). Refresh it in
  the GUI if you want the local worker doing LinkedIn too. The new Phase-17 alert will now
  warn you whenever a cookie dies.
- [ ] **(Optional) True 5-min cadence** — GitHub's `*/5` cron is throttled (runs land hours
  apart under load). A free external pinger (cron-job.org → `workflow_dispatch`) gives real
  5-min scans. Not set up yet.

### ⚠️ Must Do Now (one-time manual steps)

- [ ] **Run tailored CV migration** — paste into Supabase → SQL Editor → Run:
  ```sql
  ALTER TABLE jobs ADD COLUMN IF NOT EXISTS tailored_cv_draft        text;
  ALTER TABLE jobs ADD COLUMN IF NOT EXISTS tailored_cv_generated_at timestamptz;
  ```
  File: `cloud/migrations/2026-05-19-tailored-cv.sql`

- [ ] **Enable ntfy.sh push notifications (optional)** — for instant native phone alerts on
  score >= 7 jobs. In Supabase → Table Editor → bot_state → insert:
  ```
  key:   setting_ntfy_url
  value: https://ntfy.sh/YOUR-TOPIC-NAME
  ```
  Install the free `ntfy` app on your phone and subscribe to YOUR-TOPIC-NAME.

- [ ] **Set max_hours to 72** — in mobile app Settings, change "Max hours" from 5 to 72.
  (5h misses jobs posted while you sleep; 72h = 3 days coverage.)

### Must Do Soon

- [ ] **Build fresh Android APK** — tailored CV button, two-button alerts, and all new sources
  not on phone yet:
  ```powershell
  cd mobile
  flutter build apk --release
  # Output: build\app\outputs\flutter-apk\app-release.apk
  # Install: adb install build\app\outputs\flutter-apk\app-release.apk
  ```
  Or push a tag: `git tag v1.0.6 && git push origin v1.0.6` → CI builds + releases APK.

- [x] **Push all commits to GitHub** — done; main is at `79ba2cc` as of 2026-05-19

- [ ] **Run CV analysis for the first time** — open the Windows app, click Browse PDF,
  pick your CV. The Analyze CV button auto-triggers. Or manually:
  ```powershell
  python cloud/cv_analyzer.py --cv "C:\path\to\your\cv.pdf"
  python cloud/cv_analyzer.py --show   # verify what was extracted
  ```

### Should Do

- [ ] **Bulk generate tailored CVs for existing high-score jobs**:
  ```powershell
  python cloud/enricher.py --limit 50 --tailored-cv-threshold 7 --tailored-cv-max-per-run 20
  ```

- [ ] **Bulk generate cover letters for existing jobs** (~60 jobs with score >= 7 have none):
  ```powershell
  python cloud/enricher.py --limit 100 --cover-letter-threshold 7 --cover-letter-max-per-run 20
  ```

- [ ] **Reduce Phase 4 cache TTL** — in `cloud/preferences.py` change `CACHE_TTL_HOURS = 6`
  to `CACHE_TTL_HOURS = 1` so applied/dismissed history takes effect faster.

### Nice to Have

- [ ] **Deploy to Railway** — break the 5-min GitHub Actions limit; get 2-min scanning.
  Connect repo to Railway.app, set env vars: `SUPABASE_URL`, `SUPABASE_KEY`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `LINKEDIN_COOKIE`, `KEYWORDS`, `LOCATION`.
  Start command is already in `railway.toml`.

- [x] **Indeed scraping fix** — DONE (2026-06-01). RSS now 403; replaced with Playwright
  headless Chromium. Works locally (residential IP); skipped on GitHub Actions (datacenter
  IPs blocked by Cloudflare), so Indeed is collected only by the local worker.

- [ ] **Tailored CV in Flutter app** — `job_detail_screen.dart` currently shows cover letter card;
  add a second card for the tailored CV draft with a copy button.

- [ ] **Salary extraction** — parse salary ranges from descriptions; add `salary_min`/`salary_max`.

- [ ] **Score history chart** — Flutter dashboard trend over days.

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
