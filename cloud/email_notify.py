"""
Email notification helpers using the Resend API.
https://resend.com/docs/api-reference/emails/send-email

Set RESEND_API_KEY (env var or settings.json ResendApiKey) and verify a sender
domain in the Resend dashboard before emails will actually deliver.
"""

from __future__ import annotations

import time

import requests

_RESEND_API = "https://api.resend.com/emails"


def _score_badge(score: int | None) -> str:
    if score is None:
        return ""
    color = "#16a34a" if score >= 8 else "#ca8a04" if score >= 6 else "#dc2626"
    return (
        f'<span style="background:{color};color:#fff;font-size:11px;font-weight:700;'
        f'padding:2px 7px;border-radius:9999px;">{score}/10</span>'
    )


def _salary_text(job: dict) -> str:
    mn  = job.get("salary_min")
    mx  = job.get("salary_max")
    avg = job.get("salary_avg")
    cur = (job.get("salary_currency") or "AED").strip()
    per = job.get("salary_period") or "year"
    if not (mn or mx or avg):
        return ""
    div = 12.0 if per == "year" else 1.0
    try:
        if mn and mx:
            return f"{cur} {int(float(mn)/div):,}–{int(float(mx)/div):,}/mo"
        val = avg or mx or mn
        return f"~{cur} {int(float(val)/div):,}/mo"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""


def _job_card_html(job: dict) -> str:
    title    = job.get("title", "")
    company  = job.get("company", "")
    location = job.get("location", "")
    url      = job.get("url", "#")
    score    = job.get("llm_score")
    summary  = (job.get("llm_summary") or "").strip()
    salary   = _salary_text(job)

    sub        = " · ".join(p for p in [company, location] if p)
    score_html = _score_badge(score)
    sal_html   = (
        f'<p style="margin:4px 0 0;color:#16a34a;font-size:12px;font-weight:600;">{salary}</p>'
        if salary else ""
    )
    summary_html = (
        f'<p style="margin:6px 0 0;color:#4b5563;font-size:13px;line-height:1.5;">{summary}</p>'
        if summary else ""
    )

    return f"""
    <div style="border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;margin-bottom:12px;">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px;">
        <div>
          <a href="{url}" style="font-size:15px;font-weight:600;color:#1d4ed8;text-decoration:none;">
            {title}
          </a>
          <p style="margin:3px 0 0;color:#6b7280;font-size:13px;">{sub}</p>
        </div>
        <div style="flex-shrink:0;">{score_html}</div>
      </div>
      {summary_html}
      {sal_html}
      <p style="margin:10px 0 0;">
        <a href="{url}"
           style="display:inline-block;background:#2563eb;color:#fff;font-size:12px;
                  font-weight:600;padding:5px 14px;border-radius:6px;text-decoration:none;">
          View job →
        </a>
      </p>
    </div>"""


def format_email_html(jobs: list[dict], display_name: str = "") -> tuple[str, str]:
    """Return (subject, html_body) for a job-alert email."""
    n        = len(jobs)
    subject  = f"{n} new job match{'es' if n != 1 else ''} for you"
    greeting = f"Hi {display_name}," if display_name else "Hi,"
    cards    = "\n".join(_job_card_html(j) for j in jobs[:20])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
             background:#f9fafb;margin:0;padding:0;">
  <div style="max-width:600px;margin:24px auto;padding:0 16px;">
    <h2 style="font-size:20px;font-weight:700;margin:0 0 4px;color:#111827;">{subject}</h2>
    <p style="color:#6b7280;font-size:14px;margin:0 0 20px;">{greeting} Here are your latest matches.</p>
    {cards}
    <p style="color:#9ca3af;font-size:11px;margin-top:24px;text-align:center;">
      Manage alerts in your
      <a href="https://job-alert.vercel.app/app/settings" style="color:#6b7280;">settings</a>.
    </p>
  </div>
</body>
</html>"""
    return subject, html


def send_job_alert_email(
    api_key:      str,
    to:           str,
    jobs:         list[dict],
    from_email:   str = "JobAlert <alerts@jobalert.app>",
    display_name: str = "",
) -> bool:
    """Send a job-alert email via Resend. Returns True on success."""
    if not api_key or not to or not jobs:
        return False

    subject, html = format_email_html(jobs, display_name)

    for attempt in range(1, 4):
        try:
            resp = requests.post(
                _RESEND_API,
                json={"from": from_email, "to": [to], "subject": subject, "html": html},
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=30,
            )
            if resp.status_code in (200, 201):
                return True
            print(f"[Email] Resend HTTP {resp.status_code}: {resp.text[:200]}")
            if resp.status_code == 422:
                return False  # Validation error — no point retrying (bad address / unverified domain)
        except requests.RequestException as exc:
            print(f"[Email] attempt {attempt} failed: {exc}")
        if attempt < 3:
            time.sleep(attempt)

    return False
