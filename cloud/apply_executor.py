"""
Easy Apply executor — fills a LinkedIn Easy Apply form automatically.

Triggered by .github/workflows/easy-apply.yml with --job-id input.

Flow:
  1. Read apply_req_{job_id} from Supabase bot_state (written by the mobile app).
  2. Open the job URL in a Playwright browser with the user's LinkedIn cookie.
  3. Click "Easy Apply" and step through all pages. Every question is read
     and answered by apply_answers: saved answers first, then built-in rules,
     then Groq AI (GROQ_API_KEY) from the CV profile.
  4. If a required question still has no answer, stop WITHOUT submitting and
     report it (status: needs_input, list in "missing") so the app can ask
     the user and retry. Otherwise submit the application.
  5. Write the result back to apply_req_{job_id} (status: done/needs_input/failed).
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
import apply_answers
import cv_builder
import db


# ── Logging ────────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] [apply] {msg}", flush=True)


# ── Form-fill logic ────────────────────────────────────────────────────────────
# Every Easy Apply page is a list of "form elements" (one question each). For
# each one we read the label, work out the control type, and answer it with
# apply_answers (saved answers → rules → Groq). Required questions we cannot
# answer are reported back to the app instead of being guessed.

_GROUP_SELECTORS = [
    "div[data-test-form-element]",
    ".jobs-easy-apply-form-section__grouping",
    ".fb-dash-form-element",
]
_PLACEHOLDER_OPTIONS = {"select an option", "select", "choose", "please select", ""}


class FillState:
    """What happened while filling the form, sent back to the app."""

    def __init__(self, answers: dict, profile: str, job: dict, groq_key: str):
        self.bank = apply_answers.build_bank(answers)
        self.custom = apply_answers.custom_pairs(answers)
        self.profile = profile
        self.job = job
        self.groq_key = groq_key
        self.resume_path: str | None = None   # tailored CV PDF to upload
        self.resume_uploaded = False
        self.filled: list[dict] = []      # {"q", "a", "source"}
        self.missing: list[dict] = []     # {"q", "type", "options"}
        self._ai_cache: dict[str, str | None] = {}

    def answer(self, question: str, field_type: str, options: list[str]) -> tuple[str | None, str]:
        value, source = apply_answers.answer_for(
            question, field_type, options, self.bank, self.custom)
        if value is not None:
            return value, source
        key = f"{apply_answers.normalize(question)}|{field_type}|{'|'.join(options)}"
        if key not in self._ai_cache:
            self._ai_cache[key] = apply_answers.ask_groq(
                question, field_type, options, self.profile, self.job, self.groq_key)
        value = self._ai_cache[key]
        return (value, "ai") if value else (None, "")

    def add_missing(self, question: str, field_type: str, options: list[str]) -> None:
        if not any(m["q"] == question for m in self.missing):
            self.missing.append({"q": question, "type": field_type, "options": options})


async def _clean_text(locator) -> str:
    try:
        text = (await locator.inner_text()).strip()
    except Exception:
        return ""
    # LinkedIn renders the label twice (visible + screen-reader); keep line 1.
    line = text.splitlines()[0] if text else ""
    return line.replace("*", "").replace("Required", "").strip()


async def _group_label(group) -> str:
    # Radio groups: the question is the <legend>; their <label>s are the options.
    for sel in ["legend span[aria-hidden='true']", "legend"]:
        loc = group.locator(sel)
        if await loc.count() > 0:
            text = await _clean_text(loc.first)
            if text:
                return text
    for sel in ["label","span[data-test-form-builder-radio-button-form-component__title]",
                ".fb-dash-form-element__label", "span[aria-hidden='true']"]:
        loc = group.locator(sel)
        if await loc.count() > 0:
            text = await _clean_text(loc.first)
            if text:
                return text
    return await _clean_text(group)


async def _is_required(group, control) -> bool:
    try:
        if await control.get_attribute("required") is not None:
            return True
        if (await control.get_attribute("aria-required") or "").lower() == "true":
            return True
        return "*" in (await group.inner_text())
    except Exception:
        return False


async def _radio_options(group) -> list[tuple[str, object]]:
    """[(label text, radio input locator)] for a radio group."""
    out = []
    radios = group.locator("input[type='radio']")
    for i in range(await radios.count()):
        radio = radios.nth(i)
        rid = await radio.get_attribute("id")
        text = ""
        if rid:
            lab = group.locator(f"label[for='{rid}']")
            if await lab.count() > 0:
                text = await _clean_text(lab.first)
        if not text:
            text = await radio.get_attribute("value") or ""
        out.append((text, radio))
    return out


async def _fill_group(page, group, state: FillState) -> None:
    """Answer one question block if it is empty."""
    label = await _group_label(group)
    if not label:
        return

    # ── Dropdown ──────────────────────────────────────────────────────────
    select = group.locator("select")
    if await select.count() > 0:
        select = select.first
        current = (await select.evaluate(
            "s => s.options[s.selectedIndex] ? s.options[s.selectedIndex].text : ''")).strip()
        if current.lower() not in _PLACEHOLDER_OPTIONS:
            return
        options = [o.strip() for o in await select.locator("option").all_inner_texts()
                   if o.strip().lower() not in _PLACEHOLDER_OPTIONS]
        value, source = state.answer(label, "select", options)
        if value:
            await select.select_option(label=value)
            state.filled.append({"q": label, "a": value, "source": source})
        elif await _is_required(group, select):
            state.add_missing(label, "select", options)
        return

    # ── Radio buttons ─────────────────────────────────────────────────────
    radios = await _radio_options(group)
    if radios:
        for _, radio in radios:
            if await radio.is_checked():
                return
        options = [text for text, _ in radios]
        value, source = state.answer(label, "radio", options)
        if value:
            for text, radio in radios:
                if text == value:
                    rid = await radio.get_attribute("id")
                    lab = group.locator(f"label[for='{rid}']") if rid else None
                    if lab is not None and await lab.count() > 0:
                        await lab.first.click()
                    else:
                        await radio.check(force=True)
                    state.filled.append({"q": label, "a": value, "source": source})
                    return
        state.add_missing(label, "radio", options)
        return

    # ── Text area ─────────────────────────────────────────────────────────
    area = group.locator("textarea")
    if await area.count() > 0:
        area = area.first
        if (await area.input_value()).strip():
            return
        value, source = state.answer(label, "textarea", [])
        if value:
            await area.fill(value)
            state.filled.append({"q": label, "a": value, "source": source})
        elif await _is_required(group, area):
            state.add_missing(label, "textarea", [])
        return

    # ── Text / number input ───────────────────────────────────────────────
    field = group.locator(
        "input:not([type='hidden']):not([type='file']):not([type='checkbox']):not([type='radio'])")
    if await field.count() > 0:
        field = field.first
        if (await field.input_value()).strip():
            return
        kind = (await field.get_attribute("type") or "text").lower()
        field_type = "number" if kind == "number" or "numeric" in (
            await field.get_attribute("id") or "") else "text"
        value, source = state.answer(label, field_type, [])
        if value:
            await field.fill(value)
            # City / location boxes are typeaheads: pick the first suggestion.
            if (await field.get_attribute("role") or "") == "combobox":
                await page.wait_for_timeout(1_200)
                option = page.locator("[role='listbox'] [role='option']")
                if await option.count() > 0:
                    await option.first.click()
            state.filled.append({"q": label, "a": value, "source": source})
        elif await _is_required(group, field):
            state.add_missing(label, field_type, [])
        return

    # ── Required checkbox (e.g. "I confirm the information is correct") ───
    box = group.locator("input[type='checkbox']")
    if await box.count() > 0 and await _is_required(group, box.first):
        if await box.first.is_checked():
            return
        value, source = state.answer(label, "radio", ["Yes", "No"])
        if value == "Yes":
            await box.first.check(force=True)
            state.filled.append({"q": label, "a": "Yes", "source": source})
        else:
            state.add_missing(label, "checkbox", ["Yes", "No"])


async def _upload_resume(modal, state: FillState) -> None:
    """Upload the tailored CV on the resume step (once).

    LinkedIn's resume step has a hidden <input type=file> (id contains
    'upload-resume'); setting a file on it uploads and selects that CV.
    Cover-letter file inputs are left alone.
    """
    if not state.resume_path or state.resume_uploaded:
        return
    inputs = modal.locator("input[type='file']")
    for i in range(await inputs.count()):
        inp = inputs.nth(i)
        ident = " ".join(filter(None, [
            await inp.get_attribute("id"), await inp.get_attribute("name"),
            await inp.get_attribute("aria-label")])).lower()
        if "cover" in ident:
            continue
        if not ident or "resume" in ident or "cv" in ident:
            await inp.set_input_files(state.resume_path)
            await modal.page.wait_for_timeout(3_000)
            state.resume_uploaded = True
            state.filled.append({"q": "Resume", "a": os.path.basename(state.resume_path),
                                 "source": "tailored_cv"})
            _log(f"  uploaded tailored CV {os.path.basename(state.resume_path)}")
            return


async def _fill_page(page, modal, state: FillState) -> None:
    try:
        await _upload_resume(modal, state)
    except Exception as exc:
        _log(f"  resume upload failed ({exc}) — LinkedIn's default CV will be used")
    groups = None
    for sel in _GROUP_SELECTORS:
        loc = modal.locator(sel)
        if await loc.count() > 0:
            groups = loc
            break
    if groups is None:
        return
    for i in range(await groups.count()):
        group = groups.nth(i)
        try:
            if not await group.is_visible():
                continue
            await _fill_group(page, group, state)
        except Exception as exc:  # one odd field must not stop the run
            _log(f"  field {i + 1}: could not fill ({exc})")


async def _error_labels(modal) -> list[str]:
    """Labels of questions LinkedIn marked with a validation error."""
    out = []
    errors = modal.locator(".artdeco-inline-feedback--error")
    for i in range(await errors.count()):
        err = errors.nth(i)
        if not await err.is_visible():
            continue
        group = err.locator("xpath=ancestor::div[@data-test-form-element][1]")
        if await group.count() == 0:
            group = err.locator("xpath=ancestor::div[contains(@class,'form-element')][1]")
        label = await _group_label(group.first) if await group.count() > 0 else ""
        out.append(label or await _clean_text(err))
    return out


async def _fill_easy_apply(page, job_url: str, state: FillState) -> tuple[str, str]:
    """Open the job, fill every Easy Apply page and submit.

    Returns (status, message). status is "done", "needs_input" or "failed".
    """
    from playwright.async_api import TimeoutError as PWTimeout

    _log(f"Navigating to: {job_url}")
    try:
        await page.goto(job_url, wait_until="domcontentloaded", timeout=45_000)
    except PWTimeout:
        return "failed", "Job page timed out"

    await page.wait_for_timeout(2_500)

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
        return "failed", ("No Easy Apply button found — the job may not support Easy Apply, "
                          "it may be closed, or the LinkedIn cookie has expired")

    modal = page.locator("div.jobs-easy-apply-modal, div[role='dialog']").first

    for step in range(15):
        await page.wait_for_timeout(1_200)
        await _fill_page(page, modal, state)

        if state.missing:
            names = "; ".join(m["q"] for m in state.missing)
            return "needs_input", f"Stopped before submitting — please answer: {names}"

        submit_btn = modal.locator(
            'button[aria-label="Submit application"]:visible, '
            'button:has-text("Submit application"):visible')
        if await submit_btn.count() > 0:
            _log(f"Step {step + 1}: clicking Submit")
            await submit_btn.first.click()
            await page.wait_for_timeout(3_000)
            sent = page.locator(':text("application was sent"), :text("Application submitted")')
            if await sent.count() > 0:
                return "done", "Applied successfully via Easy Apply"
            return "done", "Submitted — could not confirm the success message (it may still have worked)"

        next_btn = modal.locator(
            'button[aria-label="Continue to next step"]:visible, '
            'button[aria-label="Review your application"]:visible, '
            'button:has-text("Next"):visible, button:has-text("Review"):visible')
        if await next_btn.count() == 0:
            return "failed", f"Step {step + 1}: no Next or Submit button found"

        _log(f"Step {step + 1}: next page")
        await next_btn.first.click()
        await page.wait_for_timeout(1_500)

        bad = await _error_labels(modal)
        if bad:
            # Try once more: the errors may be questions that appeared late.
            await _fill_page(page, modal, state)
            if state.missing:
                names = "; ".join(m["q"] for m in state.missing)
                return "needs_input", f"Stopped before submitting — please answer: {names}"
            await next_btn.first.click()
            await page.wait_for_timeout(1_500)
            bad = await _error_labels(modal)
            if bad:
                for label in bad:
                    state.add_missing(label, "text", [])
                names = "; ".join(bad)
                return "needs_input", f"LinkedIn rejected these answers — please check: {names}"

    return "failed", "Ran out of form steps without reaching Submit"


def _profile_text(supabase_url: str, supabase_key: str, bank: dict) -> str:
    """Plain-text CV profile for the AI fallback."""
    lines = []
    for key, title in [("cv_summary", "Summary"), ("cv_job_titles", "Job titles"),
                       ("cv_years_experience", "Years of experience"), ("cv_skills", "Skills"),
                       ("cv_certifications", "Certifications"), ("cv_education", "Education"),
                       ("cv_languages", "Languages")]:
        try:
            value = db.get_config(supabase_url, supabase_key, key, "")
        except Exception:
            value = ""
        if value:
            lines.append(f"{title}: {value}")
    for key, value in bank.items():
        if key not in ("why_interested",):
            lines.append(f"{key.replace('_', ' ')}: {value}")
    return "\n".join(lines)


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

    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    bank = apply_answers.build_bank(answers)
    state = FillState(answers, _profile_text(supabase_url, supabase_key, bank),
                      req, groq_key)
    if not groq_key:
        _log("GROQ_API_KEY not set — unknown questions will be sent back to the app")

    _log(f"Launching browser for job: {req.get('job_title', '?')} @ {req.get('company', '?')}")
    status = "failed"
    cv_info: dict = {}

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
        # Tailored CV (in the owner's design) to upload on the resume step.
        if req.get("use_tailored_cv", True):
            cv_info = await _build_tailored_cv(job_id, req, supabase_url, supabase_key,
                                               groq_key, browser)
            state.resume_path = cv_info.get("path")

        page = await ctx.new_page()
        # Fail fast on a field that never becomes usable instead of hanging.
        page.set_default_timeout(10_000)
        try:
            status, result_msg = await _fill_easy_apply(page, job_url, state)
        except Exception as exc:
            status, result_msg = "failed", f"Unhandled exception — {exc}"
            _log(result_msg)
        finally:
            await browser.close()

    # ── Update Supabase ────────────────────────────────────────────────────
    success = status == "done"
    req["status"]          = status
    req["result_msg"]      = result_msg
    req["missing"]         = state.missing     # questions the app must ask the user
    req["filled"]          = state.filled      # what was typed, and from where
    req["cv_file"]         = cv_info.get("file", "")
    req["cv_tailored"]     = cv_info.get("tailored", False)
    req["cv_uploaded"]     = state.resume_uploaded
    req["finished_at"]     = datetime.now(timezone.utc).isoformat()
    db.set_config(supabase_url, supabase_key, f"apply_req_{job_id}", json.dumps(req))
    _log(f"Result: {status} — {result_msg}")
    for item in state.filled:
        # Question + source only: the repo is public, so logs must not show
        # answers (phone, salary ...). Full answers are in apply_req_{job_id}.
        _log(f"  [{item['source']}] {item['q']}")

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


# ── Tailored CV ────────────────────────────────────────────────────────────────

CV_OUT_DIR = os.path.join(_DIR, "..", "tailored_cv")   # uploaded as a workflow artifact


def _service_key(supabase_key: str) -> str:
    """cv_master is service_role only; fall back to SUPABASE_KEY if that is it."""
    return (os.environ.get("SUPABASE_SERVICE_KEY") or supabase_key or "").strip()


async def _build_tailored_cv(job_id: str, req: dict, supabase_url: str, supabase_key: str,
                             groq_key: str, browser=None) -> dict:
    """Tailor the master CV to this job and print it to PDF.

    Returns {"path", "file", "tailored"} or {} when no master CV is stored.
    """
    master = cv_builder.load_master(supabase_url, _service_key(supabase_key))
    if not master:
        _log("No master CV in cv_master (needs SUPABASE_SERVICE_KEY) — using LinkedIn's saved CV")
        return {}
    job = db.get_job_by_id(supabase_url, supabase_key, job_id) or {}
    job_info = {"job_title": req.get("job_title") or job.get("title", ""),
                "company": req.get("company") or job.get("company", "")}
    cv, tailored = cv_builder.tailor(master, job_info, job.get("description") or "", groq_key)
    os.makedirs(CV_OUT_DIR, exist_ok=True)
    name = cv_builder.file_name(cv, job_info)
    path = os.path.join(CV_OUT_DIR, name)
    await cv_builder.render_pdf(cv, path, browser=browser)
    _log(f"Built {'tailored' if tailored else 'master'} CV: {name}")
    return {"path": path, "file": name, "tailored": tailored}


async def build_cv_only(job_id: str, supabase_url: str, supabase_key: str) -> None:
    """--cv-only: make the tailored CV for a job without applying."""
    raw = db.get_config(supabase_url, supabase_key, f"apply_req_{job_id}", "")
    req = json.loads(raw) if raw else {}
    info = await _build_tailored_cv(job_id, req, supabase_url, supabase_key,
                                    os.environ.get("GROQ_API_KEY", "").strip())
    if not info:
        sys.exit(1)


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
    parser.add_argument("--cv-only", action="store_true",
                        help="only build the tailored CV PDF (no application)")
    args = parser.parse_args()

    cfg          = _load_settings()
    supa_url = (os.environ.get("SUPABASE_URL") or cfg.get("SupabaseUrl") or "").strip()
    supa_key = (os.environ.get("SUPABASE_KEY") or cfg.get("SupabaseKey") or "").strip()

    if not supa_url or not supa_key:
        _log("ERROR: Set SUPABASE_URL / SUPABASE_KEY env vars or fill them in settings.json")
        sys.exit(1)

    if args.cv_only:
        asyncio.run(build_cv_only(args.job_id, supa_url, supa_key))
    else:
        asyncio.run(run(args.job_id, supa_url, supa_key))
