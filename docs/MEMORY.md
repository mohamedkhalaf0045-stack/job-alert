# Project Memory

Long-lived memory for Claude sessions working on job-alert (cloud sessions, the
owner's PC, and routines). Loaded automatically via `CLAUDE.md`.

**Keep it current:** at the end of any session that changes behaviour, settings,
infrastructure or decisions, update the relevant section here and commit it with
the work. Prune stale lines instead of only appending. This repo is **public**:
never write secrets, tokens, chat IDs, emails or personal data here.

Last updated: 2026-11-26

## Owner rules and preferences
- **1-hour rule:** any LinkedIn job detected more than 1h after posting is a bug
  to diagnose and fix (gap monitor + gap-fixer routine below).
- Owner wants problems fixed automatically, not just reported. Gap-fixer may push
  to main and comment on/close `gap-monitor` issues (owner approved 2026-10-10).
- Do not add manager-level keywords (owner declined "IT Manager").
- Work so far is committed straight to `main` (no PRs). For the planned big
  cleanup, ask whether to use PRs per stage.
- Owner chose to wait out Groq free-tier daily limits rather than upgrade.
- Owner communicates briefly and in mixed English; confirm intent when a request
  is ambiguous (e.g. "employee agent" meant the gap monitoring agent).

## How the system runs (current)
| Piece | Where | Notes |
|---|---|---|
| Fast Lane (cloud) | `.github/workflows/fastlane-cloud.yml` → `cloud/fastlane.py --cloud --loop 90 --duration 20700` | **Real-time path.** ~5h45m per run; on a clean finish each run dispatches the next (`Start next run` step), hourly cron is only a fallback (concurrency group queues them). Polls LinkedIn every 90s, last ~60 min (`WINDOW_SECONDS`), `setting_fast_keywords` × `setting_fast_locations`; scores new jobs with Groq; Telegram alert. Heartbeat in `bot_state.fastlane_cloud_heartbeat`, catch-up state in `fastlane_cloud_last_ok`. |
| Job Alert Scan | `job-alert.yml` → `cloud/worker.py` | Full scan of all keywords × locations (~20 min, timeout 25). Cron `*/5` but GitHub only runs it every ~4–7h. Newest-first (`setting_li_sort_recent`). |
| Job Enricher | `enricher.yml` → `cloud/enricher.py --prefer-cloud` | Groq scoring (`openai/gpt-oss-120b`). |
| user-alerts / Daily Digest / health-check / cleanup | workflows of same name | Per-user alerts need service key (GitHub only). |
| Gap Monitor | `gap-monitor.yml` → `cloud/gap_monitor.py --auto-fix` | Every 3h at :15 UTC. Flags LinkedIn jobs with 1h < lag ≤ 72h once (`bot_state.gap_monitor_handled`), auto-adds safe keywords, writes `gap_monitor_last` + `linkedin_health`, opens/updates GitHub issue labeled `gap-monitor` (#9 closed 2026-10-11 after 3 clean runs; a new one opens if gaps return). |
| Gap-fixer routine | Claude routine `Gap monitor: find cause and fix late jobs`, every 3h at :20 UTC, posts into the persistent "Gap fixer (job-alert)" session (repo attached) | Reads the issue, finds root cause, fixes, comments/closes. Its prompt can only be edited from that session. Old routine "[OLD - no repo access]" is disabled. |
| Local Windows worker | `linkedin-job-worker.ps1` on owner's PC | Runs worker/enricher/user_alerts; uses local Ollama. Only while PC is on. |
| Local fast lane | `cloud/fastlane.py --loop 90` via `Start-FastLane-Hidden.vbs` startup shortcut | Ollama scoring; widens look-back after downtime. |
| Web app | `web/` (Next.js on Vercel) | Chat routes have Groq 429 retry. |
| Supabase | project `xsuqhjmonzcguedekqjt` | Settings live in `bot_state` (public-readable). |

## Key settings (bot_state)
- `setting_keywords`: 25 scan keywords (incl. IT Engineer, IT Officer, IT Executive,
  IT Service Delivery, System Engineer, Cloud Security Engineer added 2026-10-08).
- `setting_fast_keywords`: 20 keywords (17 set 2026-10-10; `Information Security` added 2026-10-14;
  `Cloud Engineer` + `Cyber Security` added 2026-10-26, all at the owner's request).
- `setting_fast_locations`: not set, so the code default applies: UAE, Egypt, Oman
  (Oman added 2026-10-12 to match `setting_location`; 20 x 3 = 60 queries/cycle).
- `setting_llm_min_score` = 5 (owner was asked about raising to 6; unanswered).
- `setting_alert_max_age_hours` = 24 (default).

## Known issues / open items
- **Proxy:** code reads `LINKEDIN_PROXY` (repo secret or variable; any common
  format). As of 2026-10-10 the owner's secret is NOT reaching Actions
  (`linkedin_health.proxy_info.env_len = 0`). Must be added under
  Settings → Secrets and variables → Actions → Repository secrets. Webshare
  residential recommended. LinkedIn currently answers GitHub IPs without it.
  Since 2026-10-26 the cloud fast lane does NOT get the proxy (owner choice, cost:
  ~58k requests/day ≈ 30-40 GB/month); main scan, enricher and gap monitor still do.
- `LINKEDIN_COOKIE` secret starts with a BOM (U+FEFF); code strips it now. Always
  `.strip().strip("﻿")` env values used in HTTP headers.
- **Security audit 2026-11-22:**
  - A fine-grained GitHub PAT was compiled into every APK (`--dart-define=GITHUB_TOKEN`) and
    the APKs are on the public Releases page → token public. Owner must REVOKE it and
    issue a new `GH_PAT` (repo secret + Vercel). Fixed in code: build-apk.yml no longer
    passes it; the app controls workflows via `web/src/app/api/mobile/github` (admin-only,
    workflow allowlist, GH_PAT server-side). Never put secrets in `--dart-define`.
  - Phase 1 APPLIED 2026-11-23 (owner said "apply it"):
    `cloud/migrations/2026-11-22-security-phase1.sql`. apply_req_* and cv_data:* are hidden
    from anon and non-admin users; update_* is admin-only to write; trigger functions are
    no longer callable via /rpc. Owner's user id is in `app_admins` (set in the DB, not
    the repo). Verified as anon: 0 private rows visible, update_apk_url not writable,
    setting_* still writable (PC worker unaffected). `jobs` still allows anon read/write.
  - Phase 2 (needs owner): PC `settings.json` SupabaseKey → service_role, then remove all
    anon writes (bot_state and jobs). The old 2026-06-10 lockdown migration is superseded.
  - Telegram webhook checks `TELEGRAM_WEBHOOK_SECRET` when set (owner: set it in Vercel and
    re-run setWebhook with secret_token). LinkedIn fetch-url SSRF fixed.
  - Still open: leaked-password protection off; restrict Firebase API key.
- Local `settings.json` holds the anon key → local runs can't read profiles (RLS).
- 2 SQL migrations were unapplied as of early Oct (check `cloud/migrations/`).
- Google OAuth for the web app still needs Supabase dashboard config.
- Unverified on PC: "multiple PowerShell windows popping up" report; first local
  pipeline run after the 2026-10-07 stdin-freeze fix.

## Job quality filters
- Enricher skips (score 0, no alert) jobs LinkedIn marks "No longer accepting
  applications" (`linkedin.fetch_job_details`) and mass-posted fake listings
  (`relevance_engine.is_template_scam`: description starts "Role Description" +
  "part-time ... remote/hybrid" / "work-from-home flexibility"). Added 2026-10-11:
  ~11% of alerts over 14 days were this template (44 different fake "companies"),
  which LinkedIn removes within hours → owner saw them as expired links. Not a block.

## Easy Apply (auto-apply)
- Mobile "Easy Apply" → `apply_req_{job_id}` in bot_state → `easy-apply.yml` →
  `cloud/apply_executor.py` (Playwright + `LINKEDIN_COOKIE`). LinkedIn Easy Apply only.
- Since 2026-11-22 (owner asked for AIApply-style auto-apply): the executor reads every
  question on each form page and answers it via `cloud/apply_answers.py`: saved answers
  for that exact question → rules over the answer bank → Groq (`GROQ_API_KEY`, only when
  confident, choice answers must be a listed option). A required question with no answer
  stops the run before submitting (`status: needs_input`, list in `missing`); the app shows
  those questions, saves the answers (phone-local "Saved Answers", SharedPreferences) and
  retries. Never guesses or submits invented data.
- The job is marked `applied` only by the executor after a successful submit.
- The workflow previously installed only requests+playwright (no `supabase`), so it could
  never run; it now installs `cloud/requirements.txt`. Both earlier runs (May 2026) failed.
- Tested against a mock form only (sandbox cannot reach LinkedIn); the LinkedIn selectors
  are unverified until a real run. Tests: `python -m pytest cloud/tests`.
- Tailored CV (2026-11-22, owner's design from their uploaded resume): master CV JSON in
  the private `cv_master` table (id `default`; RLS on, no policies → service_role only;
  migration `2026-11-22-cv-master.sql`). Never put CV data in the repo or bot_state.
  `cloud/cv_builder.py`: Groq only reorders skills/bullets/certs by index and may rewrite
  headline + summary (rejected if it adds any number not in the master); renders A4 PDF
  via Playwright; executor uploads it on the resume step (`use_tailored_cv`, default on).
  Workflow needs `SUPABASE_SERVICE_ROLE_KEY` (passed as SUPABASE_SERVICE_KEY); input
  `cv_only` builds the PDF without applying; PDF kept 7 days as an artifact. Public repo:
  logs show question + source only, never answer values. To change the CV, update the
  `cv_master` row (no app editor yet).
- Ideas not built yet: apply queue with daily limit, Greenhouse/Lever company forms,
  editing the master CV from the app.

## Planned work (not started)
Code cleanup plan (owner asked for plan first): stage 0 inventory → 1 tidy root
(docs/, dead files like empty `gh`, `check_scores.py`, tracked `tsbuildinfo`) →
2 pytest + CI → 3 split `enricher.py`/`worker.py`/`db.py` into packages with
compat shims → 4 web review → 5 Windows paths (needs PC session) → 6 security.
Open questions to owner: PR per stage? Still use `linux/`, Railway (`railway.toml`,
`runner.py`), Oracle VM script, `dashboard.py`, `telegram_linkedin_ai_assistant.py`?

## Environment lessons (cloud sessions)
- GitHub GraphQL is blocked; use `gh api` REST. Repo **settings/secrets/variables
  and Actions log downloads are blocked** → record diagnostics in `bot_state`
  and read them with the Supabase MCP tool instead.
- A routine that creates a fresh session per fire has no repo access; bind
  routines to a persistent session created with the repo as `source_url`.
- Foreground `sleep` is blocked; use an `until` loop with a time bound.
- The cloud sandbox cannot reach linkedin.com (proxy 403), so test LinkedIn
  behaviour via a workflow run + `bot_state` diagnostics.

## Decision log
- 2026-10-07: Telegram secret resynced; scan timeout 12→25 min; Groq model → gpt-oss-120b.
- 2026-10-08: Gap monitor built; 1h rule; newest-first scan; fast-lane catch-up.
- 2026-10-10: Cloud fast lane added (fixes GitHub cron throttling); BOM fix;
  gap-fixer moved to persistent session; fast keywords expanded to 17.
- 2026-10-11: "expired" alerts traced to fake template listings; enricher now
  skips them and closed postings.
- 2026-10-10: GitHub skipped every hourly fast-lane cron and the 12:15/15:15
  gap-monitor crons, so fast-lane runs now self-dispatch their successor; the
  gap-fixer dispatches Gap Monitor when its last run is >4h old.
- 2026-10-10: Fast-lane window 15 → 60 min: with f_TPR=r900 only ~1 of 34
  queries returned anything, and UAE jobs matching fast keywords (posted while
  the fast lane ran) were only caught by the next main scan, because LinkedIn
  lists jobs in search later than their posting time.
- 2026-10-11: Issue #9 closed: no new >1h detections in the 3 gap-monitor runs
  after the 60-min window; fast-lane self-handover confirmed (22:08, 03:53).
- 2026-10-11: Issue #10 closed (not fixable): 5 UAE/Egypt jobs surfaced in
  LinkedIn search 6-28h after their stated posting time (several 24h-window main
  scans missed them, then one scan found all 5). Median LinkedIn lag is now 0.0h.
  Pattern to recognise: many jobs first collected by the same scan + earlier
  scans in the window = LinkedIn late listing, not our miss.
- 2026-10-12: Issue #11: fast lane default locations += Oman (an Oman job waited
  for the main scan). 2 jobs were LinkedIn late listings (5 earlier scans missed);
  "Front Desk ... Customer Service" (not IT) and a German-language Service Desk
  job were loose keyword matches, not misses.
- 2026-10-14: Owner approved adding `Information Security` to fast keywords (issue #15).
- 2026-10-15: Issue #18 closed (not fixable): 3 UAE jobs reached us only through LinkedIn job-alert
  emails (Gmail/LinkedIn); the fast lane and 4-5 main scans never got them from guest search. 1
  more was listed in search >1h after posting. The fast lane was running and covered all 4.
- 2026-10-15: Issue #19 closed: 3 non-fast-keyword UAE jobs (Enterprise Architect, Accounts
  Receivable, Front Desk) waited for the throttled main scan (05:24 → 09:47). Not a fast-lane miss.
- 2026-10-15: Issue #20 closed: 3 more email-only late listings (as #18), 1 Cairo late listing,
  3 non-fast-keyword titles waiting for the main scan. Email-only late listings now recur every day.
- 2026-10-15: Issue #21 closed: 1 email-only late listing + 2 Cairo finance jobs waiting for the main scan.
- 2026-10-16: Issue #22 closed: 4 more email-only late listings (UAE/Cairo); auto-added keyword `Technology Service Desk`.
- 2026-10-16: Issue #23 closed: email-only `IT Specialist` job (keyword auto-added to scan keywords) + 1 finance late listing.
- 2026-10-16: Issue #24 closed: 3 LinkedIn late listings (loose IT/Network Engineer matches).
- 2026-10-17: Issue #25 closed: 7 LinkedIn late listings (4-8 scans missed each), mostly loose IT Engineer matches.
- 2026-10-17: Issue #26 closed: 1 LinkedIn late listing (Help Desk Assistant, 6 scans missed).
- 2026-10-17: Issue #27 closed: 1 LinkedIn late listing (Senior Technical Support Engineer, 8 scans missed).
- 2026-10-18: Issue #28 closed: 1 LinkedIn late listing (HR Systems Administrator, not IT; 10 scans missed).
- 2026-10-18: Issue #29 closed: 5 LinkedIn late listings (7-9 scans missed each); IT Manager keyword_gap left alone (owner rule).
- 2026-10-19: Issue #30 closed: 5 non-target titles (manager, C++, finance, instructor) waited for a 7h main-scan gap.
- 2026-10-20: Issue #31 closed: 4 LinkedIn late listings (loose IT Engineer / reposted) + 1 finance job waiting for the main scan.
- 2026-10-20: Issue #32 closed: 5 LinkedIn late listings (5-6 scans missed) + 3 finance jobs waiting for the main scan.
- 2026-10-20: Issue #33 closed: 13 LinkedIn late listings (4-6 scans missed, mostly loose IT Engineer) + 6 finance jobs waiting for the main scan.
- 2026-10-21: Issue #34 closed: 1 LinkedIn late listing (Technical Solution Architect, 7 scans missed).
- 2026-10-21: Issue #35 closed: 2 LinkedIn late listings + 1 email-only IT Administrator job (keyword auto-added to scan keywords).
- 2026-10-22: Issue #36 closed: 6 LinkedIn late listings + 9 non-fast-keyword jobs (finance, BIM, legal) waiting for the main scan + 1 IT Systems Administrator 2h (fast lane running; likely late in search). Manager keyword_gap left alone.
- 2026-10-22: Issue #37 closed: 1 finance job (1.0h) waiting for the main scan.
- 2026-10-22: Issue #38 closed: 9 LinkedIn late listings (4-7 scans missed, IT Officer/Support/Engineer) + IT Project Manager keyword_gap left alone.
- 2026-10-22: Issue #39 closed: 2 LinkedIn late listings (Assistant Manager cloud/infra, Accounts Payable); no fix needed.
- 2026-10-22: Issue #40 closed: 2 LinkedIn late listings (Infrastructure System Engineer 6 scans missed, Cloud Engineer).
- 2026-10-23: Issue #41 closed: 3 LinkedIn late listings (Solutions Architect, Accounts Payable, Database Administrator; 2-3 scans missed).
- 2026-10-23: Issue #42 closed: 2 LinkedIn late listings (Senior Network Engineer, IT Specialist; 3 scans missed).
- 2026-10-23: Issue #43 closed: 4 LinkedIn late listings, 2 manager titles left alone, finance + Cyber Security Engineer waiting for the main scan. Proposed adding `Cyber Security` to fast keywords (owner decision).
- 2026-10-23: Issue #44 closed: 9 LinkedIn late listings (1-6 scans missed; loose IT Engineer/Infrastructure matches, 3 Azure posts in one batch).
- 2026-10-23: Issue #45 closed: 2 LinkedIn late listings (IT System Administrator 6 scans missed, IT Sales Specialist).
- 2026-10-24: Issue #46 closed: 1 LinkedIn late listing (Accounts Payable, 3 scans missed).
- 2026-10-24: Issue #47 closed: 3 LinkedIn late listings + 1 System Administrator at 1.1h (fast keyword, fast lane running; borderline, watch for repeats).
- 2026-10-24: Issue #48 closed: 1 finance repost (Accounts Payable Supervisor) listed late; no fix.
- 2026-10-24: Issue #49 closed: 3 LinkedIn late listings, 2 email-only keyword_gaps (manager title; one-word Technician, not added), 1 finance job waiting for the main scan.
- 2026-10-25: Issue #50 closed: 3 LinkedIn late listings (3-8 scans missed) + IT Manager keyword_gap left alone.
- 2026-10-25: Issue #51 closed: finance + Senior Cloud Engineer (Egypt) waited for a 5h main-scan gap. Proposed adding `Cloud Engineer` to fast keywords (owner decision).
- 2026-10-26: Owner approved ("do it") adding `Cloud Engineer` and `Cyber Security` to fast keywords (#43, #51); written to bot_state.
- 2026-10-26: Owner chose proxy for the main scan only; removed LINKEDIN_PROXY from fastlane-cloud.yml to keep a residential proxy at ~1-3 GB/month.
- 2026-10-26: Issue #52 closed: 2 LinkedIn late listings (one probe_blocked single empty probe) + Executive IT Specialist at 1.0h (borderline, 2nd case after #47).
- 2026-10-26: Issue #53 closed: 3 LinkedIn late listings (Cloud/Network Security Engineer, C++) + 1 finance job waiting for the main scan.
- 2026-10-26: Issue #54 closed: 2 LinkedIn late listings (Cloud Support/SysAdmin 7 scans missed, Data Architect).
- 2026-10-27: Issue #55 closed: 4 LinkedIn late listings (several reposts of #45/#51/#52 jobs) + 1 IT Sales repost at 1.0h.
- 2026-10-27: Issue #56 closed: 5 LinkedIn late listings (2-5 scans missed; System/Network Engineer, InfoSec, IT Ops).
- 2026-10-27: Issue #57 closed: 1 reposted listing (IT Channels Engineer, loose IT Engineer match) listed late.
- 2026-10-28: Issue #58 closed: 2 LinkedIn late listings (DevOps/Cloud Engineer, Dynamics developer).
- 2026-10-28: Issue #59 closed: 9 LinkedIn late listings (3-5 scans missed, mostly fast-keyword IT Support/System Engineer titles, one batch) + 2 email-only keyword_gaps (auto-added `Information Technology Technician`). Gap Monitor crons 08:15/11:15 skipped by GitHub.
- 2026-10-28: Issue #60 closed: 3 LinkedIn late listings (IT Engineer/Administrator, 5 scans missed) + 3 finance jobs waiting for a 6.5h main-scan gap.
- 2026-10-29: Issue #61 closed: 1 LinkedIn late listing (Quality Systems Engineer, non-IT loose IT Engineer match). Gap Monitor 23:15 cron skipped by GitHub.
- 2026-10-29: Issue #62 closed: 1 LinkedIn late listing (IT Category Buyer, procurement; 3 scans missed). Gap Monitor 03:15 cron skipped by GitHub.
- 2026-10-29: Issue #63 closed: 6 email-only late listings (fast-keyword IT titles, UAE/Cairo, all collected at 12:01 from job-alert emails; 3-5 scans + fast lane never saw them in search). Gap Monitor 12:15/15:15 crons skipped.
- 2026-11-03: Owner asked to fix the Supabase "RLS Disabled in Public" alert: RLS enabled on `telegram_claude_history` (no policies; only service_role uses it). Migration in `cloud/migrations/`. Gap-fixer runs paused since 2026-10-30 (owner said "Stop"); issue #65 still open.
- 2026-11-22: Easy Apply upgraded to answer any form question (saved answers → rules → Groq), stop with `needs_input` instead of guessing, and fixed the workflow's missing `supabase` install. Gap-fixer still paused.
- 2026-11-22: Tailored CV per job in the owner's resume design, uploaded during Easy Apply (master CV in private `cv_master` table).
- 2026-11-22: Security audit: GitHub PAT found in public APKs (owner to revoke); app now uses a server route for GitHub.
- 2026-11-23: Owner approved and DB lockdown phase 1 applied. Gap-fixer resumed ("resume").
- 2026-11-23: Issue #65 closed: 275 late jobs from Oct 30 – Nov 22 (paused period). ~190 LinkedIn late listings (not fixable), 33 finance jobs waiting for the main scan, 26 loose IT matches waiting for the main scan, 20 keyword_gaps (mostly manager titles). Proposed: `Accounts Payable` + `Accounts Receivable` to fast keywords, `IT Technician` to scan keywords (owner decision). Issue #64 was closed before the pause (details not logged).
- 2026-11-23: Issue #66 closed: 6 LinkedIn late listings (loose IT/System Engineer matches, 13-25h, fast lane running) + Accounts Payable and a telecom PM waiting for a 10h main-scan gap. Gap Monitor 15:15 cron skipped.
- 2026-11-24: Issue #67 closed: 2 LinkedIn late listings (loose IT Engineer, 23-31h), Solution Architect late pickup, a manager title left alone, and Junior Accounts Payable waiting for an 11.5h main-scan gap.
- 2026-11-24: Issue #68 closed: 1 LinkedIn late listing (second listing of the Revolut graduate InfoSec job from #67).
- 2026-11-24: Issue #69 closed: 9 LinkedIn late listings in one batch (fast-keyword UAE IT titles, 21-27h, all collected by the 10:36 scan; fast lane running) + 4 non-fast titles (2 manager, BIM, Accounts Payable) waiting for a 9.5h main-scan gap.
- 2026-11-25: Issue #70 closed: 7 LinkedIn late listings (20-38h, fast lane running), an IT Manager keyword_gap left alone, 3 non-fast titles waiting for a 10h main-scan gap.
- 2026-11-25: Issue #71 closed: 7 LinkedIn late listings (15-28h, fast lane running) + 4 non-fast titles (IT QA, Accounts Receivable, Data Architect, DevOps) waiting for a 9.8h main-scan gap.
- 2026-11-26: Issue #72 closed: 5 LinkedIn late listings (22-35h, incl. a 3-post Talentmate batch; fast lane running) + Systems Architect keyword_gap (also listed late).
