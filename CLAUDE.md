# Job Alert — Project Context

Full context is in the `/job-alert` skill: `~/.claude/skills/job-alert/SKILL.md`
Invoke with `/job-alert` at the start of any session to load all project knowledge.

## Quick Reference

**Stack:** Next.js 14 App Router + Python scrapers + Supabase + GitHub Actions
**Web:** `web/src/` — App Router, all API routes under `web/src/app/api/`
**Cloud:** `cloud/` — worker.py (scraper), user_alerts.py (multi-user alerts), db.py
**Admin:** `/app/admin` — 3 tabs: Scraper Settings | Users | Recommended Settings

## Security — Never Break These

- `SUPABASE_SERVICE_ROLE_KEY` stays server-side only — never `NEXT_PUBLIC_*`
- Telegram token, LinkedIn cookie, Groq key — env vars only, never in `bot_state`
- `bot_state` is public (anon key readable) — no secrets there
- `user_alert_log` — no RLS insert/update/delete policy, service_role only writes it

## Next.js Conventions

- API routes: must be `route.ts` inside a subdirectory (`upload/route.ts` not `upload.ts`)
- Admin routes: check `isAdmin()` using service_role client, not anon
- CV stored per-user: `bot_state` key `cv_data:{user_id}` (JSON)
- Desktop app CV: global keys `cv_skills`, `cv_job_titles`, etc.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Architecture → invoke /plan-eng-review
- Bugs/errors → invoke /investigate
- QA/testing → invoke /qa or /qa-only
- Code review → invoke /review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
