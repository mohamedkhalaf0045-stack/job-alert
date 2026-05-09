"""
Telegram notification helpers — port of Send-TelegramMessage / Format-TelegramMessage.
Uses only the requests library.
"""

from __future__ import annotations

import time

import requests


def format_message(job: dict) -> str:
    source = job.get("Source") or "LinkedIn"
    parts = [
        f"New {source} job",
        job.get("Title", ""),
        job.get("Company", ""),
        job.get("Location", ""),
    ]
    posted = job.get("PostedText") or job.get("PostedDate") or ""
    if posted:
        parts.append(f"Posted: {posted}")
    parts.append(job.get("Url", ""))
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


def send_summary(bot_token: str, chat_id: str, jobs: list[dict], label: str = "") -> None:
    if not jobs:
        send_message(bot_token, chat_id, f"{label}No new jobs found.")
        return
    header = f"{label}{len(jobs)} new job(s) found:\n"
    lines = []
    for i, job in enumerate(jobs[:10], 1):
        lines.append(f"{i}. {job.get('Title','')} @ {job.get('Company','')}\n   {job.get('Url','')}")
    send_message(bot_token, chat_id, header + "\n".join(lines))
