# Job Alert — Improvement Plan
> Generated: 2026-07-02

---

## Immediate Fixes (blocking / broken)

| # | Issue | Action |
|---|-------|--------|
| 1 | `settings.json` uses anon key | Replace `SupabaseKey` with service_role key → fixes local `mark_telegram_sent()` |
| 2 | Vercel missing `TELEGRAM_BOT_TOKEN` | Add to Vercel env vars → fixes "Send test message" button |
| 3 | 2 unapplied migrations | Run `cloud/migrations/2026-06-14-user-skill-gaps.sql` + `keyword-expansions.sql` on Supabase |
| 4 | Google OAuth unconfigured | Supabase Dashboard → Auth → Providers → Google → add callback `https://xsuqhjmonzcguedekqjt.supabase.co/auth/v1/callback` |

---

## Infrastructure (unknown state)

| # | Issue | Action |
|---|-------|--------|
| 5 | Oracle Cloud VM PID 1000 | SSH + check `ps aux \| grep python` — restart if dead |
| 6 | `TELEGRAM_CHAT_ID` GA secret | Skill says "LIKELY MISSING" — verify in GitHub Actions secrets |

---

## Undocumented Features (exist in code, not in skill docs)

### Web Routes (undocumented — unknown if live)
- `conversations/` + `conversations/[id]/messages/`
- `employers/` + `employer/onboarding/` + `employer/profile/`
- `jobs/posting/` + `jobs/posting/[id]/`
- `messages/[id]/report/`
- `saved-searches/` + `saved-searches/[id]/`
- `users/[id]/block/`

> Looks like a marketplace/employer layer. Decide: ship or delete.

### Cloud Modules (undocumented)

| File | Size | What it does |
|------|------|--------------|
| `enricher.py` | 74KB | CV enrichment pipeline |
| `relevance_engine.py` | 39KB | Job matching / scoring |
| `apply_executor.py` | 15KB | Auto-apply pipeline |
| `crew_worker.py` | 21KB | Unknown |
| `gmail_scan.py` | 18KB | Gmail scanning |
| `push_notify.py` | 2.6KB | Push notifications |
| `dashboard.py` | 35KB | Unknown |

### Extra Scrapers (undocumented — UAE/Egypt coverage)
- `bayt.py` — Bayt (major MENA job board)
- `careerjet.py` — CareerJet
- `gulftalent.py` — GulfTalent
- `naukri_gulf.py` — Naukri Gulf
- `adzuna.py` — Adzuna

> Skill only mentions LinkedIn/Indeed. These extras could massively expand coverage — verify they work.

---

## Feature Gaps / Next Steps

| Priority | Feature | Why |
|----------|---------|-----|
| High | Verify extra scrapers (Bayt, GulfTalent, etc.) | Critical for UAE/Egypt market — if working, big coverage win |
| High | Audit employer/marketplace routes | Unknown if deployed or half-built |
| Medium | Wire `apply_executor.py` to GitHub Actions | Auto-apply is a killer feature |
| Medium | Salary backfill enrichment | ~1,400 old jobs have no salary estimate — one Groq enrichment run |
| Low | Mobile app status | Flutter APK GA build exists — verify it ships to users |

---

## Recommended Order

1. Fix items 1–4 (config changes only, no code)
2. Confirm GA secret #6 (TELEGRAM_CHAT_ID)
3. Check Oracle VM
4. Audit undocumented scrapers → enable or remove
5. Audit marketplace routes → ship or delete
6. Wire auto-apply to GA
