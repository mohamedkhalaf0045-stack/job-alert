# Job Alert Platform — Full Documentation

> **Purpose:** Reference guide to rebuild, extend, or hand off this project.  
> **Last updated:** 2026-06-13  
> **Stack:** Next.js 14 · Supabase · Python · GitHub Actions · Telegram · Resend · Groq

---

## Table of Contents
1. [What It Does](#1-what-it-does)
2. [System Architecture](#2-system-architecture)
3. [Database Schema](#3-database-schema)
4. [Scraper System](#4-scraper-system)
5. [Web Application](#5-web-application)
6. [Alert System](#6-alert-system)
7. [Telegram AI Bot](#7-telegram-ai-bot)
8. [GitHub Actions Workflows](#8-github-actions-workflows)
9. [Setup From Scratch](#9-setup-from-scratch)
10. [Configuration Reference](#10-configuration-reference)
11. [Security Rules](#11-security-rules)
12. [Windows GUI](#12-windows-gui)
13. [Linux GUI](#13-linux-gui)
14. [Android App](#14-android-app)

---

## 1. What It Does

A **multi-user job alert platform** that:
- Scrapes LinkedIn, Bayt, GulfTalent, NaukriGulf, Indeed every 5 minutes
- Scores each job with an AI relevance score (1–10)
- Shows each user a personalised feed filtered by their keywords, location, and min score
- Sends instant or daily digest alerts via **Email** (Resend) and/or **Telegram**
- Provides an AI assistant in Telegram (Groq / Llama 3.3 70B, free)

---

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        USERS (browser)                        │
│  signup → onboarding → feed → settings → saved               │
│              Next.js 14  (Vercel)                             │
└────────────────────────┬─────────────────────────────────────┘
                         │ Supabase JS (anon key, RLS)
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                     SUPABASE (PostgreSQL)                      │
│  auth.users  profiles  user_preferences  user_job_interactions│
│  user_alert_log  jobs  bot_state  telegram_claude_history     │
└───────┬──────────────────────┬────────────────────────────────┘
        │ service_role key      │ service_role key
        ▼                       ▼
┌───────────────┐     ┌─────────────────────────────────────────┐
│  SCRAPER      │     │  ALERT SENDER          (GitHub Actions) │
│  worker.py    │     │  user_alerts.py  every 15 min           │
│  every 5 min  │     │  ├─ Email via Resend                    │
│  GitHub Actions│    │  └─ Telegram per user                   │
│               │     └─────────────────────────────────────────┘
│  Sources:     │
│  LinkedIn     │     ┌─────────────────────────────────────────┐
│  Bayt         │     │  TELEGRAM AI BOT       (Vercel webhook) │
│  GulfTalent   │     │  /api/telegram/webhook                  │
│  NaukriGulf   │     │  Groq Llama 3.3 70B (free)             │
│  Indeed       │     │  History stored in telegram_claude_history│
└───────────────┘     └─────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  BACKUP TRIGGER  (cron-job.org → Vercel → GitHub dispatch)   │
│  /api/cron/trigger-worker  every 5 min                       │
│  Fires worker when GitHub Actions scheduler is delayed        │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Database Schema

### Tables Overview

```
auth.users (Supabase managed)
    │ 1:1
    ▼
profiles ──────────────── alert_email, alert_telegram, telegram_chat_id, timezone
    │ 1:1
    ▼
user_preferences ───────── keywords[], locations[], exclude_keywords[],
                            min_score, alert_frequency, digest_hour, paused

jobs ◄──────────────────── scraped jobs (all users share one pool)
    │
    ├──► user_job_interactions  (per user: saved/applied/dismissed/hidden)
    └──► user_alert_log         (per user per channel: dedup log)

bot_state ──────────────── global scraper config (key/value pairs)
telegram_claude_history ─── AI chat history per chat_id
```

### `jobs` — Core job data

| Column | Type | Notes |
|--------|------|-------|
| job_id | text PK | SHA-256 of URL |
| title, company, location | text | |
| url | text unique | canonical URL |
| source | text | LinkedIn/Bayt/GulfTalent/… |
| date_posted | timestamptz | |
| date_collected | timestamptz | when scraped |
| llm_score | integer | 1–10 AI relevance score |
| llm_summary | text | AI-generated summary |
| matched_skills | jsonb | |
| salary_min/max/avg | numeric | |
| salary_currency, period, source | text | |
| search_tsv | tsvector | auto-generated, used for FTS |
| duplicate_of_url | text | null if original |

### `profiles`

| Column | Type | Default |
|--------|------|---------|
| id | uuid PK | → auth.users.id |
| email | text | |
| display_name | text | |
| timezone | text | Asia/Dubai |
| telegram_chat_id | text | |
| alert_email | boolean | true |
| alert_telegram | boolean | false |

### `user_preferences`

| Column | Type | Default |
|--------|------|---------|
| user_id | uuid PK | → auth.users.id |
| keywords | text[] | [] |
| locations | text[] | [] |
| exclude_keywords | text[] | [] |
| min_score | smallint | null (show all) |
| alert_frequency | text | 'daily' |
| digest_hour | integer | 8 |
| paused | boolean | false |

### `user_job_interactions`

| Column | Type |
|--------|------|
| user_id | uuid |
| job_id | text |
| status | text — saved/applied/dismissed/hidden |
| updated_at | timestamptz |

### `user_alert_log`

| Column | Type |
|--------|------|
| user_id | uuid |
| job_id | text |
| channel | text — email/telegram |
| sent_at | timestamptz |

PK = (user_id, job_id, channel) — prevents duplicate alerts.

### `bot_state` — Global scraper config

All values are stored as `text`. Read by worker.py each run.

| key | meaning |
|-----|---------|
| setting_keywords | comma-separated scrape keywords (auto-synced from all users) |
| setting_location | comma-separated scrape locations (auto-synced from all users) |
| setting_max_hours | max job age to accept (default 72) |
| setting_llm_min_score | global Telegram alert min score (default 4) |
| setting_exclude_keywords | global exclude list |
| setting_search_linkedin | true/false |
| setting_search_bayt | true/false |
| setting_search_gulftalent | true/false |
| setting_search_naukrigulf | true/false |
| setting_search_indeed | true/false |
| setting_search_web | true/false |
| setting_legacy_telegram | true = worker.py sends direct TG alerts (set false when user_alerts.py is running) |

### `telegram_claude_history` — AI chat memory

| Column | Type |
|--------|------|
| id | bigserial PK |
| chat_id | bigint |
| role | text — user/assistant |
| content | text |
| created_at | timestamptz |

Max 20 pairs stored per chat (older trimmed automatically).

---

## 4. Scraper System

### Flow (every 5 min)

```
worker.py starts
    │
    ├─ sync_scrape_keywords()  ← merges all users' keywords into bot_state
    ├─ sync_scrape_locations() ← merges all users' locations into bot_state
    │
    ├─ Read bot_state settings (keywords, locations, max_hours, …)
    │
    ├─ For each (keyword × location):
    │     ├─ LinkedIn scraper
    │     ├─ Bayt scraper
    │     ├─ GulfTalent scraper
    │     ├─ NaukriGulf scraper
    │     └─ (Indeed / Web / Gmail if enabled)
    │
    ├─ Each source result goes through:
    │     ├─ _age_filter()   — drop jobs older than max_hours
    │     ├─ _loc_filter()   — drop jobs outside location
    │     ├─ _nat_filter()   — drop nationals-only jobs
    │     └─ engine.filter_jobs() — drop unrelated jobs
    │
    ├─ db.sync_jobs() — upsert new jobs to Supabase
    └─ _alert_new()   — send Telegram alert for new jobs (legacy mode)
```

### Key functions in `cloud/db.py`

```python
sync_scrape_keywords(url, key)   # merges user_preferences.keywords → bot_state
sync_scrape_locations(url, key)  # merges user_preferences.locations → bot_state
sync_jobs(url, key, jobs, source)  # upserts jobs, returns {inserted, updated, seen}
get_config(url, key, setting, default)  # reads bot_state key
set_config(url, key, setting, value)    # writes bot_state key
log_user_alert(url, key, user_id, job_ids, channel)  # writes user_alert_log
```

### `user_jobs_feed()` SQL Function

Called by the web app to show each user their personalised feed.

```sql
create or replace function public.user_jobs_feed(
    p_user   uuid        default null,
    p_limit  int         default 30,
    p_before timestamptz default null,  -- keyset pagination cursor
    p_after  timestamptz default null   -- date filter (e.g. last 7 days)
)
-- Returns jobs filtered by the calling user's preferences:
-- keywords (FTS + ILIKE), locations (ILIKE %), exclude_keywords (NOT FTS),
-- min_score, dismissed/hidden status.
-- Ordered by date_collected DESC.
```

---

## 5. Web Application

**Deployed at:** `https://job-alert-nine.vercel.app`  
**Stack:** Next.js 14 App Router · TypeScript · Tailwind · @supabase/ssr

### Pages

| Route | Type | Purpose |
|-------|------|---------|
| `/` | public | Landing page |
| `/signup` | public | Create account (email + password min 8 chars) |
| `/login` | public | Sign in |
| `/onboarding` | auth | First-time: set keywords, location, alert frequency |
| `/app/feed` | auth | Personalised job feed with pagination |
| `/app/saved` | auth | Saved/applied jobs |
| `/app/settings` | auth | Update preferences, alerts, min score |
| `/app/admin` | admin only | Global scraper settings (bot_state) |

### Auth Flow

```
Sign up → email confirmation → /onboarding → save preferences → /app/feed
Sign in → /app/feed (middleware redirects unauthenticated to /login)
```

### Supabase Clients

| File | Key used | Purpose |
|------|----------|---------|
| `src/lib/supabase/client.ts` | NEXT_PUBLIC_SUPABASE_ANON_KEY | Browser (RLS enforced) |
| `src/lib/supabase/server.ts` | NEXT_PUBLIC_SUPABASE_ANON_KEY | Server Components (RLS enforced) |
| `src/lib/supabase/admin.ts` | SUPABASE_SERVICE_ROLE_KEY | API routes that bypass RLS |

### Admin Page Guard

```typescript
// web/src/app/app/layout.tsx
const isAdmin = user.email === process.env.ADMIN_EMAIL
// web/src/app/app/admin/page.tsx
if (user.email !== process.env.ADMIN_EMAIL) redirect('/app/feed')
// POST /api/admin/bot-state — also verifies email server-side
```

### Vercel Environment Variables

| Variable | Where set | Purpose |
|----------|-----------|---------|
| NEXT_PUBLIC_SUPABASE_URL | Vercel | Supabase project URL |
| NEXT_PUBLIC_SUPABASE_ANON_KEY | Vercel | Supabase anon (public) key |
| SUPABASE_SERVICE_ROLE_KEY | Vercel | Service role key for admin routes |
| ADMIN_EMAIL | Vercel | Owner email — unlocks /app/admin |
| TELEGRAM_BOT_TOKEN | Vercel | Bot token for AI assistant webhook |
| TELEGRAM_ALLOWED_CHAT_ID | Vercel | Only this chat ID can use the AI bot |
| GROQ_API_KEY | Vercel | Groq API key (free tier) |
| GH_PAT | Vercel | GitHub PAT — triggers workflow dispatch |
| CRON_SECRET | Vercel | Secret to protect /api/cron/trigger-worker |

---

## 6. Alert System

### Flow (every 15 min via GitHub Actions)

```
user_alerts.py --mode instant
    │
    ├─ Fetch all profiles WHERE alert_email OR alert_telegram
    ├─ For each user:
    │     ├─ Load user_preferences (keywords, locations, min_score)
    │     ├─ Query jobs matching preferences WHERE date_collected > last alert
    │     ├─ Exclude jobs already in user_alert_log
    │     │
    │     ├─ alert_frequency = 'instant' → send now
    │     └─ alert_frequency = 'daily'  → skip (handled by digest run at 8 AM)
    │
    ├─ Send Email via Resend  (if alert_email = true)
    └─ Send Telegram message  (if alert_telegram = true AND telegram_chat_id set)
```

### Email (Resend)

- **From:** `onboarding@resend.dev` (no domain verification needed)
- **Future:** Set up custom domain in Resend → change RESEND_FROM_EMAIL
- **Template:** Plain HTML list of job title + company + URL + AI score

### Telegram Alert Format

```
🔔 3 new jobs matching your search

1. Data Analyst @ RAKBANK [8/10]
   https://linkedin.com/jobs/view/...

2. Oracle Data Quality Analyst @ Cyient [7/10]
   https://linkedin.com/jobs/view/...
```

### GitHub Actions Secrets Required

| Secret | Purpose |
|--------|---------|
| SUPABASE_URL | Supabase project URL |
| SUPABASE_KEY | **service_role** key (NOT anon) |
| TELEGRAM_BOT_TOKEN | Bot token |
| TELEGRAM_CHAT_ID | Owner's chat ID (legacy single-user) |
| RESEND_API_KEY | Resend email API key |
| RESEND_FROM_EMAIL | Sender address (onboarding@resend.dev) |

---

## 7. Telegram AI Bot

### How It Works

```
User sends message to Telegram bot
    │
    Telegram → POST https://job-alert-nine.vercel.app/api/telegram/webhook
    │
    ├─ Check TELEGRAM_ALLOWED_CHAT_ID (only owner can use)
    ├─ Return 200 OK immediately (prevents Telegram timeout)
    │
    └─ Background (waitUntil):
          ├─ Load last 20 messages from telegram_claude_history
          ├─ Call Groq API (llama-3.3-70b-versatile, free)
          ├─ Save user message + reply to telegram_claude_history
          └─ Send reply via Telegram sendMessage API
```

### Commands

| Command | Effect |
|---------|--------|
| Any text | AI replies using conversation context |
| `/clear` | Deletes all conversation history for this chat |

### Code: `web/src/app/api/telegram/webhook/route.ts`

```typescript
// Core logic
const groq = new Groq({ apiKey: process.env.GROQ_API_KEY })
const response = await groq.chat.completions.create({
  model: 'llama-3.3-70b-versatile',
  max_tokens: 2048,
  messages: [ systemPrompt, ...history, userMessage ],
})
```

### Webhook Registration

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://job-alert-nine.vercel.app/api/telegram/webhook"
```

Re-run this if the Vercel domain changes.

---

## 8. GitHub Actions Workflows

### `job-alert.yml` — Main scraper

| Setting | Value |
|---------|-------|
| Schedule | Every 5 minutes (`*/5 * * * *`) |
| Concurrency | group: job-alert-scan, cancel-in-progress: true |
| Timeout | 12 minutes |
| Command | `python cloud/worker.py` |
| Runner | ubuntu-22.04 (pinned — 24.04 breaks Playwright) |

### `user-alerts.yml` — Per-user alerts

| Setting | Value |
|---------|-------|
| Schedule | Every 15 min + every hour |
| Concurrency | group: user-alerts, cancel-in-progress: false |
| Command | `python cloud/user_alerts.py --mode {instant|digest}` |
| Logic | 15-min → instant users; top-of-hour → digest users |

### `daily-digest.yml` — Daily digest

| Setting | Value |
|---------|-------|
| Schedule | `0 4 * * *` UTC (= 8 AM Dubai) |
| Command | `python cloud/digest.py --hours 24 --top 3` |

### `health-check.yml` — System monitoring

| Setting | Value |
|---------|-------|
| Schedule | Every 3 hours |
| Command | `python cloud/health_check.py` |
| Checks | Supabase connectivity, workflow run gaps |

### Backup Trigger (cron-job.org)

GitHub Actions cron is unreliable (can be delayed hours). A backup:

- **cron-job.org** calls `GET https://job-alert-nine.vercel.app/api/cron/trigger-worker?secret=<CRON_SECRET>` every 5 min
- That endpoint calls GitHub API to dispatch `job-alert.yml`
- Prevents >5 min scraping gaps

```typescript
// web/src/app/api/cron/trigger-worker/route.ts
await fetch(`https://api.github.com/repos/mohamedkhalaf0045-stack/job-alert/actions/workflows/job-alert.yml/dispatches`, {
  method: 'POST',
  headers: { Authorization: `Bearer ${process.env.GH_PAT}` },
  body: JSON.stringify({ ref: 'main' }),
})
```

---

## 9. Setup From Scratch

### Step 1 — Supabase

1. Create project at supabase.com
2. Run migrations in order (SQL Editor):
   ```
   2026-05-13-multi-criteria.sql
   2026-05-14-dedup.sql
   2026-05-15-cover-letter.sql
   2026-05-19-tailored-cv.sql
   2026-06-10-salary-insights.sql
   2026-06-11-auth-profiles.sql
   2026-06-11-user-preferences.sql
   2026-06-11-user-job-interactions.sql
   2026-06-11-user-alert-log.sql
   2026-06-11-jobs-fts-fixed.sql       ← use this, not jobs-fts.sql
   ```
3. Run the feed date-filter update:
   ```sql
   -- Add p_after parameter to user_jobs_feed
   -- (see DOCUMENTATION section 4 for full SQL)
   drop function if exists public.user_jobs_feed(uuid, int, timestamptz);
   -- then recreate with p_after parameter
   ```
4. Create `telegram_claude_history` table:
   ```sql
   create table public.telegram_claude_history (
     id bigserial primary key,
     chat_id bigint not null,
     role text not null check (role in ('user','assistant')),
     content text not null,
     created_at timestamptz default now()
   );
   create index on public.telegram_claude_history (chat_id, created_at desc);
   ```
5. Note: **anon key** = public (safe for web/mobile). **service_role key** = private (GitHub Actions + Vercel admin routes only).

### Step 2 — GitHub Repository

1. Push code to GitHub
2. Add GitHub Actions secrets:

```
SUPABASE_URL          = https://xxxx.supabase.co
SUPABASE_KEY          = service_role key (NOT anon)
TELEGRAM_BOT_TOKEN    = from @BotFather
TELEGRAM_CHAT_ID      = your numeric chat ID
LINKEDIN_COOKIE       = li_at=... from browser cookies
RESEND_API_KEY        = from resend.com
RESEND_FROM_EMAIL     = onboarding@resend.dev
GH_PAT                = GitHub personal access token (workflow scope)
```

### Step 3 — Vercel Web App

```bash
cd web
npx vercel link   # link to Vercel project
```

Add env vars:
```bash
npx vercel env add NEXT_PUBLIC_SUPABASE_URL production
npx vercel env add NEXT_PUBLIC_SUPABASE_ANON_KEY production
npx vercel env add SUPABASE_SERVICE_ROLE_KEY production
npx vercel env add ADMIN_EMAIL production          # owner email
npx vercel env add TELEGRAM_BOT_TOKEN production
npx vercel env add TELEGRAM_ALLOWED_CHAT_ID production
npx vercel env add GROQ_API_KEY production         # from console.groq.com (free)
npx vercel env add GH_PAT production
npx vercel env add CRON_SECRET production          # any random string
```

In Supabase → Auth → URL Configuration:
- Site URL: `https://job-alert-nine.vercel.app`
- Redirect URLs: `https://job-alert-nine.vercel.app/**`

### Step 4 — Register Telegram Webhook

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://job-alert-nine.vercel.app/api/telegram/webhook"
```

### Step 5 — Backup Cron (cron-job.org)

1. Sign up free at cron-job.org
2. Create cronjob:
   - URL: `https://job-alert-nine.vercel.app/api/cron/trigger-worker?secret=<CRON_SECRET>`
   - Schedule: Every 5 minutes
   - Method: GET

### Step 6 — First User (Owner)

1. Sign up at `/signup` with owner email
2. Confirm email (or run SQL: `update auth.users set email_confirmed_at = now() where email = '...'`)
3. Complete onboarding (keywords, location, alert frequency)
4. If profile row missing, run:
   ```sql
   insert into public.profiles (id, email, alert_email, alert_telegram, timezone)
   select id, email, true, false, 'Asia/Dubai'
   from auth.users where email = 'your@email.com'
   on conflict (id) do nothing;
   ```

---

## 10. Configuration Reference

### Per-User Settings (web `/app/settings`)

| Setting | Where stored | Effect |
|---------|-------------|--------|
| Keywords | user_preferences.keywords | Feed + scraper filters |
| Locations | user_preferences.locations | Feed + scraper location |
| Exclude keywords | user_preferences.exclude_keywords | Hidden from feed |
| Min AI score | user_preferences.min_score | Feed hides lower scores |
| Alert frequency | user_preferences.alert_frequency | instant/daily/off |
| Email alerts | profiles.alert_email | Resend emails on/off |
| Telegram alerts | profiles.alert_telegram | Telegram alerts on/off |
| Telegram chat ID | profiles.telegram_chat_id | Where TG alerts go |
| Pause | user_preferences.paused | Stop all alerts |

### Global Scraper Settings (web `/app/admin`)

| Setting | bot_state key | Default |
|---------|--------------|---------|
| Max job age | setting_max_hours | 72 |
| Global min score (TG) | setting_llm_min_score | 4 |
| Global excludes | setting_exclude_keywords | — |
| LinkedIn on/off | setting_search_linkedin | true |
| Bayt on/off | setting_search_bayt | true |
| GulfTalent on/off | setting_search_gulftalent | true |
| NaukriGulf on/off | setting_search_naukrigulf | true |
| Indeed on/off | setting_search_indeed | false |
| Web search on/off | setting_search_web | false |
| Legacy Telegram | setting_legacy_telegram | true |

**Note:** `setting_keywords` and `setting_location` are auto-synced from all users' preferences on every worker run — do not edit manually.

---

## 11. Security Rules

| Rule | Reason |
|------|--------|
| `SUPABASE_KEY` in GitHub Actions = service_role | Scraper must write to jobs table |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` = anon key | Safe to expose in browser |
| `SUPABASE_SERVICE_ROLE_KEY` in Vercel = service_role | Admin API routes bypass RLS |
| NEVER put service_role in `NEXT_PUBLIC_*` vars | Would expose it to all browsers |
| LinkedIn cookie stays in GitHub Secrets only | Not in bot_state (anon-readable) |
| Telegram bot token stays in GitHub Secrets + Vercel only | Not in bot_state |
| `user_alert_log` has no insert RLS policy | Only service_role can write |
| `handle_new_user()` trigger must be SECURITY DEFINER | Needs to write profiles as system |
| Telegram AI bot checks TELEGRAM_ALLOWED_CHAT_ID | Prevents strangers from using bot |
| `/api/admin/bot-state` checks user.email === ADMIN_EMAIL | Server-side admin guard |

### RLS Summary

| Table | anon | authenticated user | service_role |
|-------|------|--------------------|-------------|
| jobs | SELECT only | SELECT only | full |
| profiles | none | own row only | full |
| user_preferences | none | own row only | full |
| user_job_interactions | none | own row only | full |
| user_alert_log | none | SELECT own | full |
| bot_state | SELECT only | SELECT only | full |

---

---

## 12. Windows GUI

### What It Is

A **PowerShell Windows Forms desktop app** (`linkedin-job-alert.ps1`) that runs the scraper locally, shows a live job table, and controls everything from a GUI. Requires Windows 10/11. Size: ~2800 lines of PowerShell.

### Files

| File | Purpose |
|------|---------|
| `linkedin-job-alert.ps1` | Main GUI (1160×1030 window) |
| `linkedin-job-worker.ps1` | Background scan worker spawned by GUI |
| `shared-functions.ps1` | LinkedIn + Indeed scraping logic |
| `job-database.ps1` | SQLite job table (jobs.db) |
| `settings.json` | All credentials + preferences |
| `seen-jobs.json` | Dedup cache (job_id → timestamp, 90-day TTL) |
| `telegram-offset.json` | Last Telegram update_id processed |
| `Run-LinkedInJobAlert.bat` | CLI launcher |
| `Run-LinkedInJobAlert.vbs` | Hidden-window launcher (no terminal) |

### Window Layout

```
┌──────────────────────────────────────────────────────────────┐
│  LinkedIn UAE Job Alert                   [Monitoring Dashboard]│
├──────────────────────────┬───────────────────────────────────┤
│  SEARCH SETTINGS         │  AUTOMATION                       │
│  Keywords (one/line)     │  [▶ Start] [■ Stop] [⟳ Scan Now]  │
│  Exclude keywords        │  Interval: [5] min                │
│  Location                │  Browser: Chrome ▼                │
│  Time filter ▼           │  [Enrich AI] [Open Job]           │
│  Custom hours            │                                   │
│  ☑ LinkedIn  ☑ Indeed   │  OLLAMA                           │
│                          │  URL: http://localhost:11434       │
│  LINKEDIN SESSION        │  Min AI Score: [5]                │
│  Cookie: li_at=...       │  ☑ Auto-enrich                   │
│  [Import Cookies]        │                                   │
│                          │  CV ANALYSIS                      │
│  TELEGRAM ALERTS         │  Profile: [Browse PDF...]         │
│  Bot token: ****         │  [Analyze CV]                     │
│  Chat ID: 12345          │                                   │
│  [Test] [Send Visible]   │  GMAIL ALERTS                     │
│                          │  ☐ Search Gmail                   │
│                          │  Email / App Password             │
├──────────────────────────┴───────────────────────────────────┤
│  JOBS TABLE (all columns: Source/Keyword/Title/Company/       │
│  Location/Posted/Applied/Tg/Score)                           │
│  Green = <3h  Yellow = 4-24h  White = older                  │
│  Double-click → open in browser                              │
│  Right-click → Open / Applied / Dismiss / Save / AI info /  │
│               Copy Cover Letter                              │
├──────────────────────────────────────────────────────────────┤
│  ACTIVITY LOG (live, auto-scroll)                            │
├──────────────────────────────────────────────────────────────┤
│  Status: monitoring  ● (worker lamp)  ☁ (cloud lamp)  🤖    │
└──────────────────────────────────────────────────────────────┘
```

**Status lamps:**
- **Worker lamp** (red/green): green = background worker PID alive
- **Cloud lamp** (grey/yellow/green/red): GitHub Actions last run status; right-click → Run Cloud Now / Cancel / Open Logs / Pause Schedule
- **AI lamp**: reflects enricher subprocess health

### What It Does

**Scanning**
1. Reads `settings.json`
2. Extracts LinkedIn cookie from Chrome/Edge/Chromium browser profile (DPAPI decryption; falls back to manual paste if v20 App-Bound Encryption detected)
3. Fetches LinkedIn jobs via guest API (no browser needed)
4. Fetches Indeed via Playwright + Chromium (residential IP, bypasses datacenter block)
5. Filters by time window, location, keyword
6. Deduplicates against `seen-jobs.json` and local `jobs.db`
7. Displays results in table; alerts new jobs to Telegram

**Background Worker**
- Spawned as a hidden PowerShell process
- PID written to `worker.pid`
- Runs in a loop (interval from settings)
- Logs to `worker.log`

**Telegram Commands** (polled every 5 seconds)
| Command | Effect |
|---------|--------|
| `/scan` | Trigger an immediate scan, reply with count |
| `/start` / `/stop` | Start/stop the worker loop |
| `/status` | Reply with current worker status |
| `/jobs` | List latest N jobs |
| `/get key` | Read a setting |
| `/set key value` | Update a setting |

**GitHub Actions Cloud Control**
- Polls `GET /repos/{repo}/actions/workflows/job-alert.yml/runs` every 5 min → updates cloud lamp
- Right-click cloud lamp → triggers `workflow_dispatch` or cancels run

**Supabase Sync** (on Settings save)
- Pushes `setting_keywords`, `setting_location`, `setting_max_hours`, source toggles to `bot_state`
- Never pushes credentials (cookie, TG token, Gmail password)
- Reads back `llm_score` from `jobs` table after enrichment

**AI Enrichment**
- "Enrich AI" button → runs `cloud/enricher.py` in background
- Reads `enricher-last-run.log` to update AI lamp status

**CV Analysis**
- Browse PDF → runs `cloud/cv_analyzer.py` → stores extracted skills in `bot_state.cv_skills`

### Configuration: `settings.json`

```json
{
  "Keywords":          ["IT Support", "System Administrator"],
  "Location":          "United Arab Emirates, Egypt",
  "IntervalMinutes":   5,
  "TimeFilter":        "Last 24 hours",
  "CustomHours":       5,
  "BrowserChoice":     "Chrome (Chromium)",
  "LinkedInCookie":    "li_at=...; JSESSIONID=...",
  "HideAppliedJobs":   true,
  "TelegramBotToken":  "...",
  "TelegramChatId":    "941885724",
  "SearchLinkedIn":    true,
  "SearchIndeed":      true,
  "ExcludeKeywords":   "intern,fresh,trainee",
  "GitHubToken":       "ghp_...",
  "GitHubRepo":        "mohamedkhalaf0045-stack/job-alert",
  "SupabaseUrl":       "https://xxxx.supabase.co",
  "SupabaseKey":       "eyJ...",
  "UserProfile":       "C:\\Users\\...\\CV.pdf",
  "MinAiScore":        5,
  "OllamaUrl":         "http://localhost:11434",
  "AutoEnrich":        true,
  "SearchGmail":       false,
  "GmailEmail":        "",
  "GmailPassword":     ""
}
```

> **Security:** `SupabaseKey` must be the **service_role** key (worker writes jobs). Settings.json is local-only; never commit it.

### Setup From Scratch

```
1. Requirements
   - Windows 10/11
   - PowerShell 5.1+ (built-in)
   - Python 3.9+  →  pip install requests playwright pypdf supabase python-dotenv
   - playwright install chromium
   - System.Data.SQLite.dll (auto-detected from Chrome/Dell/etc., or download from system.data.sqlite.org)

2. Copy files
   - All .ps1 files + cloud/ folder to any local folder

3. Fill settings.json
   - Add your Supabase URL + service_role key
   - Add LinkedIn cookie (or use Import Cookies button)
   - Add Telegram bot token + chat ID
   - Add GitHub PAT + repo name

4. Launch
   powershell -NoProfile -ExecutionPolicy Bypass -File linkedin-job-alert.ps1

5. (Optional) Auto-start on login
   powershell -NoProfile -ExecutionPolicy Bypass -File Install-LinkedInJobWorkerTask.ps1
```

---

## 13. Linux GUI

### What It Is

A **Python Tkinter desktop app** (`linux/gui.py`) that mirrors the Windows GUI features on Linux. Uses the same Supabase backend. Background worker runs as a **systemd user service**.

### Files

| File | Purpose |
|------|---------|
| `linux/gui.py` | Main Tkinter GUI (1000×700) |
| `linux/setup.sh` | One-time installer |
| `~/.config/job-alert/settings.json` | Local config (same structure as Windows) |
| `~/.config/job-alert/settings.env` | Env file for systemd service |
| `~/.config/systemd/user/job-alert-worker.service` | Worker unit |
| `~/.config/systemd/user/job-alert-worker.timer` | 5-minute timer |
| `~/.local/share/job-alert/job-alert.log` | Log file |

### Window Layout

```
┌──────────────────────────────────────────────┐
│  📋 Job Alert                                 │
├──────────────────────────────────────────────┤
│  [⚙ Settings] [💼 Jobs] [📋 Log]            │
├──────────────────────────────────────────────┤
│  TAB: Settings (scrollable)                  │
│    Supabase URL / Key                        │
│    Telegram Bot Token / Chat ID              │
│    LinkedIn Cookie                           │
│    Keywords (comma-separated)                │
│    Location, Max Job Age (hours)             │
│    Min AI Score (1-10)                       │
│    Exclude Keywords                          │
│    ☑ LinkedIn  ☑ Indeed  ☐ Gmail           │
│    ☑ Auto-run Enricher                      │
│    Ollama URL                                │
│    CV PDF Path  [Browse]                     │
│    [Save & Sync to Cloud]                    │
├──────────────────────────────────────────────┤
│  TAB: Jobs                                   │
│    [All] [New] [Applied] [Dismissed] [Refresh]│
│    TreeView: title | company | score |       │
│              source | date | status          │
│    [Mark Applied] [Dismiss] [Open Browser]   │
├──────────────────────────────────────────────┤
│  TAB: Log (dark bg, live tail)               │
│    [Clear] [Open Log File]                   │
├──────────────────────────────────────────────┤
│  [▶ Scan Now] [🤖 Run Enricher]              │
│  [📄 Analyze CV] [⏹ Stop]   status: ready   │
└──────────────────────────────────────────────┘
```

### What It Does

- **Settings tab** — edit + save locally + push to `bot_state`; also generates `settings.env`
- **Jobs tab** — fetches from Supabase `jobs` table; filter by status; mark applied/dismissed
- **Log tab** — live tail of the log file; output from all subprocesses appended here
- **Scan Now** → runs `python3 cloud/worker.py --limit 50` in background thread
- **Run Enricher** → runs `cloud/enricher.py --limit 20`
- **Analyze CV** → runs `cloud/cv_analyzer.py --cv <path> --ollama <url>`
- Background worker via systemd timer (every 5 min) — separate from the GUI

### Systemd Worker

```ini
# job-alert-worker.service
[Service]
Type=oneshot
ExecStart=python3 /path/to/cloud/worker.py --limit 50
EnvironmentFile=%h/.config/job-alert/settings.env
StandardOutput=append:/home/user/.local/share/job-alert/job-alert.log
TimeoutStartSec=600

# job-alert-worker.timer
[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Persistent=true
```

### Setup From Scratch

```bash
# 1. Clone repo
git clone https://github.com/mohamedkhalaf0045-stack/job-alert.git
cd job-alert

# 2. Run one-time setup (installs everything)
bash linux/setup.sh
# Installs: python3-tk, requests, supabase, python-dotenv, pypdf, playwright
# Creates: ~/.config/job-alert/, ~/.local/share/job-alert/
# Installs: systemd service + timer, desktop launcher

# 3. Fill in credentials (GUI or direct edit)
nano ~/.config/job-alert/settings.json

# 4. Launch GUI
python3 linux/gui.py

# 5. Start background worker
systemctl --user enable job-alert-worker.timer
systemctl --user start job-alert-worker.timer

# Check worker status
systemctl --user status job-alert-worker.timer
tail -f ~/.local/share/job-alert/job-alert.log
```

### Dependencies

| Package | Install |
|---------|---------|
| Python 3.9+ | `apt install python3` |
| tkinter | `apt install python3-tk` |
| requests, supabase, python-dotenv, pypdf | `pip install ...` |
| playwright Chromium | `pip install playwright && python3 -m playwright install chromium` |
| Ollama (optional) | `curl https://ollama.ai/install.sh \| sh && ollama pull llama3.1` |

---

## 14. Android App

### What It Is

A **Flutter Android app** that lets you browse the job feed, mark jobs, and trigger cloud scans from your phone. Uses the same Supabase database (public anon key, RLS enforced). No local scraping — it's a read/control interface.

### Project Structure

```
mobile/
├── lib/
│   ├── main.dart                  # Entry point (MaterialApp, 3-tab scaffold)
│   ├── config.dart                # Supabase URL + anon key + GitHub repo
│   ├── models/job.dart            # Job data model
│   ├── services/
│   │   ├── supabase_service.dart  # REST calls to Supabase
│   │   ├── github_service.dart    # GitHub Actions status + dispatch
│   │   └── notification_service.dart
│   ├── screens/
│   │   ├── dashboard_screen.dart  # Cloud status + trigger
│   │   ├── jobs_screen.dart       # 5-tab job list
│   │   ├── job_detail_screen.dart # Full job + apply/save/dismiss
│   │   └── settings_screen.dart  # Read-only bot_state view
│   └── widgets/job_card.dart      # Reusable job card
├── pubspec.yaml
└── android/
    ├── app/key.properties         # Signing (generated at build)
    └── build.gradle
```

### App Screens

**Bottom nav: Dashboard | Jobs | Settings**

```
DASHBOARD TAB
─────────────
Cloud status lamp (green/red/yellow/grey)
Last run: 5 min ago  [▶ Run Now]
Long-press → View Logs in GitHub / Cancel Run

JOBS TAB (5 sub-tabs)
──────────────────────
[All] [New] [Scored] [Applied] [Saved]

Each card:
  Data Analyst @ RAKBANK · Dubai
  LinkedIn · Score: 8/10 · 2h ago
  [tap to open detail]

JOB DETAIL
──────────
Title, Company, Location, Source
AI Score: 8/10   Summary: "..."
Matched skills: Python, SQL
Missing skills: Power BI
[Open in Browser] [Mark Applied] [Mark Saved] [Dismiss]
[Copy Cover Letter]  [Copy AI Reasoning]

SETTINGS TAB
─────────────
Reads bot_state from Supabase (read-only)
Keywords: IT Support, Data Analyst
Location: UAE, Egypt
Min score: 5
Sources: LinkedIn ✓, Bayt ✓
```

### Supabase Integration

| Operation | Endpoint |
|-----------|----------|
| List jobs | `GET /rest/v1/jobs?order=date_collected.desc` |
| Filter by status | `?status=eq.new` |
| Filter scored | `?llm_score=not.is.null` |
| Update status | `PATCH /rest/v1/jobs?job_id=eq.{id}` body `{"status":"applied"}` |
| Read settings | `GET /rest/v1/bot_state` |

Uses **anon key** — RLS enforces user cannot write jobs directly.

### GitHub Integration

```dart
// config.dart
static const githubToken = String.fromEnvironment('GITHUB_TOKEN', defaultValue: '');
static const githubRepo  = 'mohamedkhalaf0045-stack/job-alert';
```

- List runs: `GET /repos/{repo}/actions/workflows/job-alert.yml/runs?per_page=1`
- Trigger: `POST /repos/{repo}/actions/workflows/job-alert.yml/dispatches`
- Polls every 30 seconds to update Dashboard lamp

### Dependencies (`pubspec.yaml`)

```yaml
dependencies:
  http: ^1.2.0
  url_launcher: ^6.3.0
  intl: ^0.19.0
  package_info_plus: ^8.0.0
  open_filex: ^4.7.0
  path_provider: ^2.1.0
  flutter_local_notifications: ^18.0.0
```

### Build From Source

```bash
# 1. Install Flutter SDK 3.0+  (flutter.dev/docs/get-started/install)
flutter --version

# 2. Set up signing key (one time)
cd mobile/android
keytool -genkey -v -keystore job-alert-key.jks \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -alias job-alert -storepass <password> -keypass <password>

# Encode for GitHub Secrets
base64 -w 0 job-alert-key.jks > keystore.b64
# Copy keystore.b64 content → GitHub Secret KEYSTORE_BASE64

# 3. Build APK
cd mobile
flutter pub get
flutter build apk --release --split-per-abi \
  --dart-define=GITHUB_TOKEN=ghp_...

# APK output: build/app/outputs/flutter-apk/app-arm64-v8a-release.apk

# 4. Install on phone
adb install build/app/outputs/flutter-apk/app-arm64-v8a-release.apk
```

### Build via GitHub Actions (Recommended)

Workflow: `.github/workflows/build-apk.yml`

```
Trigger: git tag v1.0.x  →  git push origin v1.0.x
Steps:
  1. Decode KEYSTORE_BASE64 → job-alert-key.jks
  2. Write key.properties (storePassword, keyPassword, keyAlias, storeFile)
  3. flutter pub get
  4. flutter build apk --release --split-per-abi --dart-define=GITHUB_TOKEN=$GH_PAT
  5. Upload APKs to GitHub Release (arm64-v8a + armeabi-v7a + x86_64)
```

**GitHub Secrets needed for APK build:**

| Secret | Value |
|--------|-------|
| KEYSTORE_BASE64 | `base64 -w 0 job-alert-key.jks` output |
| KEY_STORE_PASSWORD | keystore password |
| KEY_PASSWORD | key password (usually same) |
| KEY_ALIAS | `job-alert` |
| GH_PAT | GitHub PAT with `actions:write` scope |

### Install Pre-built APK (No Build Needed)

```bash
# Download from GitHub Releases
# Choose the right ABI for your device:
#   arm64-v8a  → most modern phones (2016+)
#   armeabi-v7a → older phones
#   x86_64     → Android emulator

adb install app-arm64-v8a-release.apk
# or just share the .apk file to the phone and open it
```

### Minimum Requirements

- Android 5.0+ (API 21)
- ARM64 or ARMv7 processor
- Internet access for Supabase + GitHub APIs

---

## Updating This Document

When you add or change something, update the relevant section:
- New table → Section 3
- New scraper source → Section 4
- New web page → Section 5
- New alert channel → Section 6
- New workflow → Section 8
- New env var → Section 5 (Vercel) or Section 8 (GitHub)
- New security rule → Section 11
