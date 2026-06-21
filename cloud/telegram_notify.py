"""
Telegram notification helpers — port of Send-TelegramMessage / Format-TelegramMessage.
Uses only the requests library.
"""

from __future__ import annotations

import time

import requests


def format_message(job: dict) -> str:
    # Accept both capitalized (worker in-memory dicts) and lowercase (DB row dicts)
    source   = job.get("Source")   or job.get("source")   or "LinkedIn"
    title    = job.get("Title")    or job.get("title")    or ""
    company  = job.get("Company")  or job.get("company")  or ""
    location = job.get("Location") or job.get("location") or ""
    url      = job.get("Url")      or job.get("url")      or ""
    parts = [f"New {source} job", title, company, location]
    posted = job.get("PostedText") or job.get("PostedDate") or job.get("date_posted") or ""
    if posted:
        parts.append(f"Posted: {posted}")
    score = job.get("llm_score")
    if score is not None:
        summary = job.get("llm_summary", "")
        score_line = f"AI Score: {score}/10"
        if summary:
            score_line += f" — {summary}"
        parts.append(score_line)
    sal = salary_line(job)
    if sal:
        parts.append(sal)
    parts.append(url)
    return "\n".join(p for p in parts if p)


# ── Salary line (Phase 24) ────────────────────────────────────────────────────

_SALARY_LABEL = {
    "posted":        "posted",
    "adzuna_est":    "Adzuna est.",
    "adzuna_market": "market avg, Adzuna",
    "ai_estimate":   "AI estimate",
}


def _fmt_amount(v: float) -> str:
    return f"{v:,.0f}"


def _salary_fields(job: dict | None, breakdown: dict | None) -> dict | None:
    """Normalise salary data from a job dict (scraper/DB keys) or a scoring
    breakdown (enricher market lookup). Posted salary on the job wins."""
    job = job or {}
    g = lambda *names: next(
        (job[n] for n in names if job.get(n) not in (None, "", 0)), None)
    mn  = g("SalaryMin", "salary_min")
    mx  = g("SalaryMax", "salary_max")
    avg = g("SalaryAvg", "salary_avg")
    if mn or mx or avg:
        return {"min": mn, "max": mx, "avg": avg,
                "currency": g("SalaryCurrency", "salary_currency") or "",
                "period":   g("SalaryPeriod", "salary_period") or "year",
                "source":   g("SalarySource", "salary_source") or "posted"}
    s = (breakdown or {}).get("salary")
    return s if isinstance(s, dict) and (s.get("min") or s.get("max") or s.get("avg")) else None


def salary_line(job: dict | None = None, breakdown: dict | None = None,
                compact: bool = False) -> str:
    """One-line salary info for Telegram alerts; '' when nothing is known.

    Monthly figures are shown regardless of source period (Adzuna amounts are
    annualised, so they are divided by 12)."""
    s = _salary_fields(job, breakdown)
    if not s:
        return ""
    try:
        div = 12.0 if (s.get("period") or "year") == "year" else 1.0
        cur = (s.get("currency") or "").strip()
        mn, mx, avg = s.get("min"), s.get("max"), s.get("avg")
        label = _SALARY_LABEL.get(s.get("source") or "", s.get("source") or "")

        if compact:
            v = avg if avg else (((mn or mx) + (mx or mn)) / 2 if (mn or mx) else None)
            if not v:
                return ""
            return f"💰 ~{cur} {float(v) / div / 1000:.1f}k/mo".strip()

        if mn and mx:
            rng = f"{cur} {_fmt_amount(float(mn) / div)}–{_fmt_amount(float(mx) / div)}/mo"
        elif avg:
            rng = f"~{cur} {_fmt_amount(float(avg) / div)}/mo"
        elif mn or mx:
            rng = f"~{cur} {_fmt_amount(float(mn or mx) / div)}/mo"
        else:
            return ""
        head = "Salary" if s.get("source") == "posted" else "Market salary"
        return f"💰 {head}: {rng}".strip() + (f" ({label})" if label else "")
    except (TypeError, ValueError):
        return ""


def send_message(bot_token: str, chat_id: str, text: str) -> bool:
    bot_token = (bot_token or "").strip()
    chat_id = (chat_id or "").strip()
    if not bot_token or not chat_id or not text:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": False,
    }

    for attempt in range(1, 4):
        try:
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code == 200:
                return True
            print(f"[Telegram] HTTP {resp.status_code}: {resp.text[:200]}")
        except requests.RequestException as exc:
            print(f"[Telegram] send attempt {attempt} failed: {exc}")
        if attempt < 3:
            time.sleep(attempt)

    return False


def send_job_alert(bot_token: str, chat_id: str, job: dict) -> bool:
    return send_message(bot_token, chat_id, format_message(job))


def send_job_alert_with_button(bot_token: str, chat_id: str, job: dict,
                                job_id: str = "") -> bool:
    """Send a job alert with inline '📝 Cover Letter' and '📄 Tailored CV' buttons.

    When the user taps a button, Telegram sends a callback_query with
    callback_data = 'cover_{job_id}' or 'cv_{job_id}'.  The worker picks it
    up on the next run and sends the pre-generated content.

    Falls back to a plain text send if job_id is unavailable.
    """
    text = format_message(job)

    if not job_id:
        # No ID → plain send (buttons would be useless without it)
        return send_message(bot_token, chat_id, text)

    if not bot_token or not chat_id:
        return False

    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id":                 chat_id,
        "text":                    text,
        "disable_web_page_preview": False,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {
                        "text":          "\U0001f4dd Cover Letter",   # 📝
                        "callback_data": f"cover_{job_id}",
                    },
                    {
                        "text":          "\U0001f4c4 Tailored CV",    # 📄
                        "callback_data": f"cv_{job_id}",
                    },
                ],
                [
                    {
                        "text":          "\U0001f50d Analyze",        # 🔍
                        "callback_data": f"analyze_{job_id}",
                    },
                ],
                [
                    {
                        "text":          "\U0001f44d Good match",     # 👍
                        "callback_data": f"good_{job_id}",
                    },
                    {
                        "text":          "\U0001f44e Not for me",     # 👎
                        "callback_data": f"bad_{job_id}",
                    },
                ],
            ]
        },
    }

    for attempt in range(1, 4):
        try:
            resp = requests.post(api_url, json=payload, timeout=30)
            if resp.status_code == 200:
                return True
            print(f"[Telegram] send_with_button HTTP {resp.status_code}: {resp.text[:200]}")
        except requests.RequestException as exc:
            print(f"[Telegram] send_with_button attempt {attempt} failed: {exc}")
        if attempt < 3:
            time.sleep(attempt)

    return False


def answer_callback_query(bot_token: str, callback_query_id: str,
                           text: str = "", show_alert: bool = False) -> bool:
    """Acknowledge a Telegram inline-button press.

    Must be called within 30 s of the press — otherwise Telegram shows a
    spinning loading indicator on the button indefinitely.
    text  — optional small pop-up shown to the user on their screen (≤200 chars).
    """
    if not bot_token or not callback_query_id:
        return False
    api_url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
    payload: dict = {"callback_query_id": callback_query_id}
    if text:
        payload["text"]       = text[:200]
        payload["show_alert"] = show_alert
    try:
        resp = requests.post(api_url, json=payload, timeout=10)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def extract_callbacks(updates: list[dict]) -> list[dict]:
    """Extract inline-keyboard callback_query events from a getUpdates response.

    Returns a list of dicts with keys:
        update_id          — used to advance the offset (already handled by worker)
        callback_query_id  — must be passed to answer_callback_query()
        data               — the callback_data string (e.g. 'cover_abc123')
        chat_id            — where to send the reply
    """
    callbacks = []
    for update in updates:
        cq = update.get("callback_query")
        if not cq:
            continue
        data = (cq.get("data") or "").strip()
        if not data:
            continue
        msg     = cq.get("message") or {}
        chat_id = str(msg.get("chat", {}).get("id", ""))
        callbacks.append({
            "update_id":         update["update_id"],
            "callback_query_id": cq["id"],
            "data":              data,
            "chat_id":           chat_id,
        })
    return callbacks


def format_score_alert(job: dict, breakdown: dict, compact: bool = False) -> str:
    """Phase 2: richer Telegram message that shows the multi-criteria breakdown.
    Phase 6: when compact=True, emit only the headline lines (score, title,
    company, URL) - useful when the user just wants a fire-hose of new matches
    without per-message breakdown noise.

    Example (full):
        AI Score: 8/10
        Site Reliability Engineer - L2 Support
        Open Innovation AI - Dubai
        Skills:9 Exp:8 Loc:9 Sr:8
        Matched: Linux, AD, M365
        Missing: AWS, Kubernetes
        Strong match due to overlap in IT experience and UAE location.
        https://...

    Example (compact):
        AI 8/10  Site Reliability Engineer - L2 Support  @  Open Innovation AI
        https://...
    """
    score   = breakdown.get("overall_score", "?")
    title   = job.get("title")   or job.get("Title")   or ""
    company = job.get("company") or job.get("Company") or ""
    loc     = job.get("location")or job.get("Location")or ""
    url     = job.get("url") or job.get("Url") or ""

    if compact:
        head = f"AI {score}/10  {title}"
        if company:
            head += f"  @  {company}"
        lines = [head]
        sal = salary_line(job, breakdown, compact=True)
        if sal:
            lines.append(sal)
        if url:
            lines.append(url)
        return "\n".join(lines)

    parts = [f"AI Score: {score}/10"]
    parts.append(title)
    if company and loc:
        parts.append(f"{company} - {loc}")
    elif company:
        parts.append(company)
    elif loc:
        parts.append(loc)

    parts.append(
        f"Skills:{breakdown.get('skills_match','?')} "
        f"Exp:{breakdown.get('experience_match','?')} "
        f"Loc:{breakdown.get('location_match','?')} "
        f"Sr:{breakdown.get('seniority_match','?')}"
    )

    matched = breakdown.get("matched_skills") or []
    missing = breakdown.get("missing_skills") or []
    flags   = breakdown.get("red_flags")      or []
    if matched: parts.append("Matched: "  + ", ".join(matched[:5]))
    if missing: parts.append("Missing: "  + ", ".join(missing[:5]))
    if flags:   parts.append("Flags: "    + " | ".join(flags[:3]))

    sal = salary_line(job, breakdown)
    if sal:
        parts.append(sal)

    reasoning = (breakdown.get("reasoning") or "").strip()
    if reasoning:
        parts.append(reasoning)

    if url:
        parts.append(url)

    return "\n".join(p for p in parts if p)


def send_score_update(bot_token: str, chat_id: str, job: dict, breakdown: dict,
                       job_id: str = "") -> bool:
    """Send a concise score UPDATE for a job already alerted by the worker.

    Used by the enricher when a job was sent to Telegram before Ollama scored it.
    Shows the score, matched/missing skills, and Cover Letter / Tailored CV buttons.

    Format:
        📊 Score: 7/10 — IT Support Engineer @ Company
        ✅ Matched: Active Directory, Exchange Online
        ❌ Missing: CCNA, Fortinet
        🔗 https://...
    """
    score   = breakdown.get("overall_score", "?")
    title   = (job.get("title")   or job.get("Title")   or "Unknown Title").strip()
    company = (job.get("company") or job.get("Company") or "").strip()
    url     = (job.get("url")     or job.get("Url")     or "").strip()

    # Score emoji
    try:
        s = int(score)
        if s >= 8:   star = "🌟"
        elif s >= 6: star = "✅"
        elif s >= 4: star = "🔵"
        else:        star = "⚪"
    except (ValueError, TypeError):
        star = "📊"

    lines = [f"{star} Score: {score}/10 — {title} @ {company}"]

    matched = breakdown.get("matched_skills") or []
    missing = breakdown.get("missing_skills") or []
    if matched:
        lines.append("Matched: " + ", ".join(matched[:5]))
    if missing:
        lines.append("Missing: " + ", ".join(missing[:4]))

    sal = salary_line(job, breakdown)
    if sal:
        lines.append(sal)

    flags = breakdown.get("red_flags") or []
    if flags:
        lines.append("Note: " + flags[0][:80])

    if url:
        lines.append(url)

    text = "\n".join(lines)

    if not job_id:
        return send_message(bot_token, chat_id, text)

    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id":                  chat_id,
        "text":                     text,
        "disable_web_page_preview": True,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "\U0001f4dd Cover Letter", "callback_data": f"cover_{job_id}"},
                    {"text": "\U0001f4c4 Tailored CV",  "callback_data": f"cv_{job_id}"},
                ],
                [
                    {"text": "\U0001f44d Good match", "callback_data": f"good_{job_id}"},
                    {"text": "\U0001f44e Not for me", "callback_data": f"bad_{job_id}"},
                ],
            ]
        },
    }
    for attempt in range(1, 4):
        try:
            resp = requests.post(api_url, json=payload, timeout=30)
            if resp.status_code == 200:
                return True
            print(f"[Telegram] score_update HTTP {resp.status_code}: {resp.text[:200]}")
        except requests.RequestException as exc:
            print(f"[Telegram] score_update attempt {attempt} failed: {exc}")
        if attempt < 3:
            time.sleep(attempt)
    return False


def send_score_alert(bot_token: str, chat_id: str, job: dict, breakdown: dict,
                      compact: bool = False) -> bool:
    """Phase 2: send a multi-criteria score alert to Telegram.
    Phase 6: pass compact=True to emit the slim 2-line format."""
    return send_message(bot_token, chat_id, format_score_alert(job, breakdown, compact=compact))


def send_summary(bot_token: str, chat_id: str, jobs: list[dict], label: str = "") -> None:
    if not jobs:
        send_message(bot_token, chat_id, f"{label}No new jobs found.")
        return
    header = f"{label}{len(jobs)} new job(s) found:\n"
    lines = []
    for i, job in enumerate(jobs[:10], 1):
        lines.append(f"{i}. {job.get('Title','')} @ {job.get('Company','')}\n   {job.get('Url','')}")
    send_message(bot_token, chat_id, header + "\n".join(lines))


def get_updates(bot_token: str, offset: int = 0, limit: int = 20) -> list[dict]:
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    try:
        resp = requests.get(url, params={"offset": offset, "limit": limit, "timeout": 0}, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                return data.get("result", [])
        print(f"[Telegram] getUpdates HTTP {resp.status_code}")
    except requests.RequestException as exc:
        print(f"[Telegram] getUpdates failed: {exc}")
    return []


def extract_commands(updates: list[dict]) -> list[dict]:
    cmds = []
    for update in updates:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            continue
        text = (msg.get("text") or "").strip()
        if text.startswith("/"):
            cmd = text.split()[0].lower().split("@")[0]  # strip @botname suffix
            cmds.append({
                "update_id": update["update_id"],
                "command": cmd,
                "chat_id": str(msg["chat"]["id"]),
            })
    return cmds
