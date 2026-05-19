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
    parts.append(url)
    return "\n".join(p for p in parts if p)


def send_message(bot_token: str, chat_id: str, text: str) -> bool:
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
            resp = requests.post(url, json=payload, timeout=15)
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
    """Send a job alert with an inline '📝 Cover Letter' button.

    When the user taps the button, Telegram sends a callback_query with
    callback_data = 'cover_{job_id}'.  The worker picks it up on the next
    run and sends the pre-generated (or freshly generated) cover letter.

    Falls back to a plain text send if job_id is unavailable.
    """
    text = format_message(job)

    if not job_id:
        # No ID → plain send (button would be useless without it)
        return send_message(bot_token, chat_id, text)

    if not bot_token or not chat_id:
        return False

    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id":                 chat_id,
        "text":                    text,
        "disable_web_page_preview": False,
        "reply_markup": {
            "inline_keyboard": [[
                {
                    "text":          "\U0001f4dd Cover Letter",   # 📝
                    "callback_data": f"cover_{job_id}",
                }
            ]]
        },
    }

    for attempt in range(1, 4):
        try:
            resp = requests.post(api_url, json=payload, timeout=15)
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

    reasoning = (breakdown.get("reasoning") or "").strip()
    if reasoning:
        parts.append(reasoning)

    if url:
        parts.append(url)

    return "\n".join(p for p in parts if p)


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
        resp = requests.get(url, params={"offset": offset, "limit": limit, "timeout": 0}, timeout=15)
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
