# Project Memory

Long-lived memory for Claude sessions working on job-alert (cloud sessions, the
owner's PC, and routines). Loaded automatically via `CLAUDE.md`.

**Keep it current:** at the end of any session that changes behaviour, settings,
infrastructure or decisions, update the relevant section here and commit it with
the work. Prune stale lines instead of only appending. This repo is **public**:
never write secrets, tokens, chat IDs, emails or personal data here.

Last updated: 2026-10-15

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
- `setting_fast_keywords`: 18 keywords (17 set 2026-10-10; `Information Security` added 2026-10-14
  at the owner's request).
- `setting_fast_locations`: not set, so the code default applies: UAE, Egypt, Oman
  (Oman added 2026-10-12 to match `setting_location`; 18 x 3 = 54 queries/cycle).
- `setting_llm_min_score` = 5 (owner was asked about raising to 6; unanswered).
- `setting_alert_max_age_hours` = 24 (default).

## Known issues / open items
- **Proxy:** code reads `LINKEDIN_PROXY` (repo secret or variable; any common
  format). As of 2026-10-10 the owner's secret is NOT reaching Actions
  (`linkedin_health.proxy_info.env_len = 0`). Must be added under
  Settings → Secrets and variables → Actions → Repository secrets. Webshare
  residential recommended. LinkedIn currently answers GitHub IPs without it.
- `LINKEDIN_COOKIE` secret starts with a BOM (U+FEFF); code strips it now. Always
  `.strip().strip("﻿")` env values used in HTTP headers.
- RLS is disabled on `public.telegram_claude_history` (owner hasn't approved the fix).
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
