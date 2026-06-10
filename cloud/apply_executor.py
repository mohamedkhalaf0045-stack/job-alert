"""
Easy Apply executor — fills a LinkedIn Easy Apply form automatically.

Triggered by .github/workflows/easy-apply.yml with --job-id input.

Flow:
  1. Read apply_req_{job_id} from Supabase bot_state (written by the mobile app).
  2. Open the job URL in a Playwright browser with the user's LinkedIn cookie.
  3. Click "Easy Apply", step through all pages, fill each field from the
     confirmed answer package.
  4. Submit the application.
  5. Write the result back to apply_req_{job_id} (status: done/failed).
  6. Update the job row to status='applied' on success.

Requires:
    pip install playwright requests
    playwright install chromium
    playwright install-deps chromium  (Linux)

Environment variables (set as GitHub Actions secrets):
    SUPABASE_URL    — Supabase REST endpoint
    SUPABASE_KEY    — Supabase anon key
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

import requests

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)
import db


# ── Logging ────────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] [apply] {msg}", flush=True)


# ── Form-fill logic ────────────────────────────────────────────────────────────

async def _fill_easy_apply(page, answers: dict, job_url: str) -> str:
    """Navigate to a LinkedIn job page and fill the Easy Apply form.

    Returns a human-readable result string.
    Strings starting with 'ERROR:' indicate failure.
    """
    from playwright.async_api import TimeoutError as PWTimeout

    _log(f"Navigating to: {job_url}")
    try:
        await page.goto(job_url, wait_until="domcontentloaded", timeout=45_000)
    except PWTimeout:
        return "ERROR: Job page timed out"

    await page.wait_for_timeout(2_500)

    # ── Click Easy Apply button ────────────────────────────────────────────
    try:
        btn = await page.wait_for_selector(
            '.jobs-apply-button--top-card, '
            '[aria-label*="Easy Apply"], '
            'button:has-text("Easy Apply")',
            timeout=12_000,
        )
        await btn.click()
        await page.wait_for_timeout(2_000)
        _log("Easy Apply dialog opened")
    except PWTimeout:
        return "ERROR: No Easy Apply button found — job may not support Easy Apply or login failed"

    personal    = answers.get("personal",    {})
    experience  = answers.get("experience",  {})
    screening   = answers.get("screening",   {})
    open_text   = answers.get("open_text",   {})

    phone   = personal.get("phone",        "")
    city    = personal.get("city",         "")
    years   = str(experience.get("years",  4))
    skills  = experience.get("skills",     "")
    notice  = screening.get("notice_period",    "")
    salary  = screening.get("expected_salary",  "")
    why     = open_text.get("why_interested",   "")

    # ── Step through form pages ────────────────────────────────────────────
    max_steps = 12
    for step in range(max_steps):
        await page.wait_for_timeout(1_200)

        # Phone
        for sel in [
            'input[id*="phoneNumber"]',
            'input[aria-label*="Phone"]',
            'input[aria-label*="phone"]',
        ]:
            if phone and await page.locator(sel).count() > 0:
                field = page.locator(sel).first
                await field.triple_click()
                await field.fill(phone)
                break

        # City
        for sel in [
            'input[id*="city"]',
            'input[aria-label*="City"]',
            'input[aria-label*="city"]',
        ]:
            if city and await page.locator(sel).count() > 0:
                field = page.locator(sel).first
                await field.triple_click()
                await field.fill(city)
                break

        # Notice period (text inputs with label containing "notice")
        notice_inputs = page.locator('input[aria-label*="notice" i], input[id*="notice"]')
        if notice and await notice_inputs.count() > 0:
            await notice_inputs.first.triple_click()
            await notice_inputs.first.fill(notice)

        # Salary
        salary_inputs = page.locator(
            'input[aria-label*="salary" i], input[aria-label*="Salary" i],'
            'input[id*="salary"]'
        )
        if salary and await salary_inputs.count() > 0:
            await salary_inputs.first.triple_click()
            await salary_inputs.first.fill(salary)

        # Years of experience (numeric inputs)
        year_inputs = page.locator('input[type="number"][aria-label*="year" i]')
        for inp in await year_inputs.all():
            await inp.triple_click()
            await inp.fill(years)

        # "Why are you interested" / cover letter text areas
        # NOTE: no cover letter — only fill if it's a short "interest" field
        interest_areas = page.locator(
            'textarea[aria-label*="why" i], textarea[aria-label*="interest" i],'
            'textarea[id*="coverLetter"]'
        )
        if why and await interest_areas.count() > 0:
            ta = interest_areas.first
            await ta.triple_click()
            await ta.fill(why)

        # Skills summary textarea
        skills_areas = page.locator(
            'textarea[aria-label*="skill" i], textarea[aria-label*="experience" i]'
        )
        if skills and await skills_areas.count() > 0:
            ta = skills_areas.first
            if (await ta.input_value()).strip() == "":
                await ta.fill(skills)

        # Radio/checkbox: "authorized to work" → Yes
        for label_text in ["authorized", "legally authorized"]:
            radio = page.locator(
                f'label:has-text("{label_text}") input[type="radio"][value*="yes" i],'
                f'label:has-text("{label_text}") input[type="radio"][value="1"]'
            )
            if await radio.count() > 0:
                await radio.first.check()

        # Sponsorship → No (unless user set it to Yes)
        sponsor_answer = screening.get("requires_sponsorship", "No")
        for label_text in ["sponsorship", "visa sponsorship"]:
            val = "yes" if sponsor_answer == "Yes" else "no"
            radio = page.locator(
                f'label:has-text("{label_text}") input[type="radio"][value*="{val}" i]'
            )
            if await radio.count() > 0:
                await radio.first.check()

        # Check for submission / next page
        submit_btn = page.locator(
            'button[aria-label="Submit application"],'
            'button:has-text("Submit application")'
        )
        if await submit_btn.count() > 0:
            _log(f"Step {step+1}: clicking Submit")
            await submit_btn.click()
            await page.wait_for_timeout(3_000)
            # Confirm dialog ("Your application was sent")
            confirm = page.locator(
                ':has-text("application was sent"),'
                ':has-text("Applied")'
            )
            if await confirm.count() > 0:
                return "Applied successfully via Easy Apply"
            return "Submitted — could not confirm success toast (form may still have succeeded)"

        next_btn = page.locator(
            'button[aria-label="Continue to next step"],'
            'button[aria-label="Review your application"],'
            'button:has-text("Next"),'
            'button:has-text("Review")'
        )
        if await next_btn.count() > 0:
            _log(f"Step {step+1}: advancing to next step")
            await next_btn.first.click()
            continue

        _log(f"Step {step+1}: no Next/Submit button found — stopping")
        break

    return "ERROR: Ran out of form steps without reaching Submit"


# ── Main runner ────────────────────────────────────────────────────────────────

async def run(job_id: str, supabase_url: str, supabase_key: str) -> None:
    # ── Load request ───────────────────────────────────────────────────────
    raw = db.get_config(supabase_url, supabase_key, f"apply_req_{job_id}", "")
    if not raw:
        _log(f"No apply request found for job_id={job_id}")
        return

    try:
        req = json.loads(raw)
    except json.JSONDecodeError as exc:
        _log(f"Invalid JSON in apply request: {exc}")
        return

    if req.get("status") not in ("pending", "retry"):
        _log(f"Request already processed (status={req.get('status')})")
        return

    # Mark as running
    req["status"] = "running"
    db.set_config(supabase_url, supabase_key, f"apply_req_{job_id}", json.dumps(req))

    answers = req.get("answers", {})
    job_url = req.get("job_url", "")

    if not job_url:
        _log("No job_url in apply request")
        req["status"] = "failed"
        req["result_msg"] = "Missing job_url"
        db.set_config(supabase_url, supabase_key, f"apply_req_{job_id}", json.dumps(req))
        return

    # ── LinkedIn cookie ────────────────────────────────────────────────────
    # SECURITY: env (GitHub Secrets) / settings.json only — never bot_state,
    # which is readable with the public anon key shipped in the mobile app.
    li_cookie = os.environ.get("LINKEDIN_COOKIE", "").strip()
    if not li_cookie:
        try:
            with open(os.path.join(os.path.dirname(__file__), "..", "settings.json"),
                      encoding="utf-8-sig") as f:
                li_cookie = (json.load(f).get("LinkedInCookie") or "").strip()
        except Exception:
            pass
    if not li_cookie:
        _log("No LinkedIn cookie — set the LINKEDIN_COOKIE secret (or settings.json locally)")
        req["status"] = "failed"
        req["result_msg"] = "No LinkedIn cookie configured. Set the LINKEDIN_COOKIE secret."
        db.set_config(supabase_url, supabase_key, f"apply_req_{job_id}", json.dumps(req))
        return

    # ── Playwright ─────────────────────────────────────────────────────────
    result_msg = "Unknown error"
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except ImportError:
        result_msg = "ERROR: playwright not installed — run: pip install playwright"
        req["status"] = "failed"
        req["result_msg"] = result_msg
        db.set_config(supabase_url, supabase_key, f"apply_req_{job_id}", json.dumps(req))
        _log(result_msg)
        return

    _log(f"Launching browser for job: {req.get('job_title', '?')} @ {req.get('company', '?')}")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        # Inject the LinkedIn session cookie
        await ctx.add_cookies([{
            "name":   "li_at",
            "value":  li_cookie,
            "domain": ".linkedin.com",
            "path":   "/",
            "secure": True,
            "httpOnly": True,
        }])
        page = await ctx.new_page()
        try:
            result_msg = await _fill_easy_apply(page, answers, job_url)
        except Exception as exc:
            result_msg = f"ERROR: Unhandled exception — {exc}"
            _log(result_msg)
        finally:
            await browser.close()

    # ── Update Supabase ────────────────────────────────────────────────────
    success = not result_msg.startswith("ERROR")
    req["status"]     = "done" if success else "failed"
    req["result_msg"] = result_msg
    db.set_config(supabase_url, supabase_key, f"apply_req_{job_id}", json.dumps(req))
    _log(f"Result: {result_msg}")

    if success:
        # Update the jobs table so the app shows "applied"
        try:
            resp = requests.patch(
                f"{supabase_url}/rest/v1/jobs?job_id=eq.{job_id}",
                headers={
                    "apikey":        supabase_key,
                    "Authorization": f"Bearer {supabase_key}",
                    "Content-Type":  "application/json",
                    "Prefer":        "return=minimal",
                },
                json={"status": "applied"},
                timeout=10,
            )
            if resp.ok:
                _log("Job status updated to 'applied' in Supabase")
            else:
                _log(f"Warning: could not update job status ({resp.status_code})")
        except Exception as exc:
            _log(f"Warning: job status update failed — {exc}")


# ── CLI entry point ────────────────────────────────────────────────────────────

def _load_settings() -> dict:
    path = os.path.join(_DIR, "..", "settings.json")
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f) or {}
    except Exception:
        return {}


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Easy Apply executor")
    parser.add_argument("--job-id", required=True, help="job_id to process")
    args = parser.parse_args()

    cfg          = _load_settings()
    supa_url = (os.environ.get("SUPABASE_URL") or cfg.get("SupabaseUrl") or "").strip()
    supa_key = (os.environ.get("SUPABASE_KEY") or cfg.get("SupabaseKey") or "").strip()

    if not supa_url or not supa_key:
        _log("ERROR: Set SUPABASE_URL / SUPABASE_KEY env vars or fill them in settings.json")
        sys.exit(1)

    asyncio.run(run(args.job_id, supa_url, supa_key))
