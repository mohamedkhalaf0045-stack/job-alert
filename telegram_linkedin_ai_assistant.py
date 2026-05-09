"""
LinkedIn Job Assistant Telegram Bot.

Architecture:
- The PowerShell app (linkedin-job-alert.ps1 / linkedin-job-worker.ps1) monitors
  LinkedIn, stores jobs in jobs.db, and sends new-job alerts to this chat.
- This bot reads from that local jobs.db and lets the user search, browse, and
  analyze jobs using a local Ollama LLM — no direct LinkedIn scraping needed.

Requirements:
    pip install pyTelegramBotAPI requests

Run:
    python telegram_linkedin_ai_assistant.py
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

import requests
import telebot
from requests import RequestException


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

APP_ROOT = Path(__file__).parent

WORKER_STARTER = APP_ROOT / "Start-LinkedInJobWorker-Hidden.vbs"
WORKER_STOPPER = APP_ROOT / "Stop-LinkedInJobWorker.ps1"
WORKER_PID_FILE = APP_ROOT / "worker.pid"
WORKER_LOG_FILE = APP_ROOT / "worker.log"
JOBS_DB_FILE    = APP_ROOT / "jobs.db"

LINKEDIN_DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
INDEED_DETAIL_URL   = "https://www.indeed.com/viewjob?jk={jk}"
LINKEDIN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LinkedInTelegramAssistant/1.0",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
INDEED_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

OLLAMA_URL              = "http://localhost:11434/api/generate"
OLLAMA_TAGS_URL         = "http://localhost:11434/api/tags"
OLLAMA_MODEL            = "llama3.1"
REQUEST_TIMEOUT_SECONDS = 60

SYSTEM_PROMPT = (
    "You are an expert HR recruiter. Analyze the following job description. "
    "Output a concise summary in English:\n"
    "1. Top 3 required skills\n"
    "2. Match score out of 10 for a Mid-level IT professional\n"
    "3. One tip for applying\n"
    "Do not write anything else."
)


def _load_settings() -> dict:
    path = APP_ROOT / "settings.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    return {}


_settings = _load_settings()

TELEGRAM_BOT_TOKEN: str = _settings.get("TelegramBotToken", "")
_raw_chat_id: str       = str(_settings.get("TelegramChatId", "")).strip()
ALLOWED_CHAT_IDS: Set[int] = (
    {int(_raw_chat_id)} if _raw_chat_id.lstrip("-").isdigit() else set()
)

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "TelegramBotToken is missing from settings.json. Add it before running the bot."
    )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bot instance  (no default parse_mode — set per message to avoid silent failures)
# ---------------------------------------------------------------------------

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Per-chat state: last job list shown so user can say "analyze 3"
_recent_jobs: Dict[int, List[Dict]] = {}


def _is_authorized(message) -> bool:
    return not ALLOWED_CHAT_IDS or message.chat.id in ALLOWED_CHAT_IDS


# ---------------------------------------------------------------------------
# Telegram helpers
# ---------------------------------------------------------------------------

def safe_reply(chat_id: int, text: str) -> None:
    """Send a plain-text message."""
    try:
        bot.send_message(chat_id, text)
    except Exception as exc:
        logger.exception("plain send failed chat_id=%s: %s", chat_id, exc)


def safe_reply_html(chat_id: int, html_text: str) -> None:
    """Send an HTML-formatted message, falling back to plain text on parse error."""
    try:
        bot.send_message(chat_id, html_text, parse_mode="HTML")
    except Exception as exc:
        logger.exception("HTML send failed chat_id=%s: %s", chat_id, exc)
        plain = re.sub(r"<[^>]+>", "", html_text)
        try:
            bot.send_message(chat_id, plain)
        except Exception:
            pass


def h(text: str) -> str:
    """Escape a value for safe embedding inside an HTML Telegram message."""
    return html_lib.escape(str(text or ""), quote=False)


# ---------------------------------------------------------------------------
# Local database
# ---------------------------------------------------------------------------

def _db_rows(sql: str, params: tuple = ()) -> List[Dict]:
    if not JOBS_DB_FILE.exists():
        return []
    try:
        con = sqlite3.connect(str(JOBS_DB_FILE))
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute(sql, params).fetchall()]
        finally:
            con.close()
    except Exception as exc:
        logger.exception("DB query failed: %s", exc)
        return []


def db_recent(limit: int = 10) -> List[Dict]:
    return _db_rows(
        "SELECT job_id, title, company, location, url, date_posted, source "
        "FROM jobs ORDER BY date_collected DESC LIMIT ?",
        (limit,),
    )


def db_search(query: str, limit: int = 10) -> List[Dict]:
    like = f"%{query}%"
    return _db_rows(
        "SELECT job_id, title, company, location, url, date_posted, source "
        "FROM jobs "
        "WHERE title LIKE ? OR company LIKE ? OR location LIKE ? "
        "ORDER BY date_collected DESC LIMIT ?",
        (like, like, like, limit),
    )


def db_count() -> int:
    rows = _db_rows("SELECT COUNT(*) AS n FROM jobs")
    return rows[0]["n"] if rows else 0


def db_count_by_source() -> Dict[str, int]:
    rows = _db_rows("SELECT source, COUNT(*) AS n FROM jobs GROUP BY source")
    return {r["source"]: r["n"] for r in rows}


# ---------------------------------------------------------------------------
# Job list formatting
# ---------------------------------------------------------------------------

def _fmt_date(iso: str) -> str:
    if not iso:
        return ""
    return iso[:10]


def format_job_list(jobs: List[Dict], header: str, chat_id: int) -> str:
    _recent_jobs[chat_id] = jobs  # global numbered list — index used for "analyze N"

    linkedin_jobs = [j for j in jobs if j.get("source", "LinkedIn").lower() == "linkedin"]
    indeed_jobs   = [j for j in jobs if j.get("source", "").lower() == "indeed"]
    other_jobs    = [j for j in jobs if j.get("source", "").lower() not in ("linkedin", "indeed")]

    lines = [f"<b>{h(header)}</b>\n"]
    num = 1

    def _render(section: List[Dict], emoji: str, label: str) -> None:
        nonlocal num
        if not section:
            return
        lines.append(f"<b>{emoji} {label} ({len(section)})</b>")
        for job in section:
            lines.append(
                f"{num}. <b>{h(job.get('title', ''))}</b>\n"
                f"   🏢 {h(job.get('company', ''))}\n"
                f"   📍 {h(job.get('location', ''))}\n"
                f"   📅 {_fmt_date(job.get('date_posted', ''))}\n"
                f"   🔗 {job.get('url', '')}\n"
            )
            num += 1

    _render(linkedin_jobs, "🔵", "LinkedIn")
    if linkedin_jobs and (indeed_jobs or other_jobs):
        lines.append("")
    _render(indeed_jobs, "🟠", "Indeed")
    if (linkedin_jobs or indeed_jobs) and other_jobs:
        lines.append("")
    _render(other_jobs, "📋", "Other")

    lines.append("Reply with a number to analyze that job with AI.  Example: <code>2</code>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Job description fetching (for Ollama analysis)
# ---------------------------------------------------------------------------

def fetch_job_description(job_id: str, fallback: str) -> str:
    """Fetch a job's full description from LinkedIn or Indeed."""
    if not job_id:
        return fallback

    if job_id.startswith("jooble-") or job_id.startswith("adzuna-"):
        # No structured detail API — fall back to title/company/location summary
        return fallback
    elif job_id.startswith("indeed-"):
        jk = job_id[7:]
        target_url = INDEED_DETAIL_URL.format(jk=jk)
        fetch_headers = INDEED_HEADERS
        patterns = (
            r'id="jobDescriptionText"[^>]*>(.*?)</div>',
            r'class="jobsearch-jobDescriptionText[^"]*"[^>]*>(.*?)</div>',
            r'class="[^"]*jobDescription[^"]*"[^>]*>(.*?)</section>',
        )
    else:
        target_url = LINKEDIN_DETAIL_URL.format(job_id=job_id)
        fetch_headers = LINKEDIN_HEADERS
        patterns = (
            r'show-more-less-html__markup[^>]*>\s*(.*?)\s*</div>',
            r'description__text[^>]*>\s*(.*?)\s*</section>',
        )

    try:
        resp = requests.get(target_url, headers=fetch_headers, timeout=20)
        resp.raise_for_status()
        for pattern in patterns:
            m = re.search(pattern, resp.text, flags=re.DOTALL | re.IGNORECASE)
            if m:
                text = re.sub(r"<[^>]+>", " ", html_lib.unescape(m.group(1)))
                text = re.sub(r"\s+", " ", text).strip()
                if text:
                    return text[:3000]
    except Exception as exc:
        logger.warning("Could not fetch description for job_id=%s: %s", job_id, exc)
    return fallback


# ---------------------------------------------------------------------------
# Ollama integration
# ---------------------------------------------------------------------------

def analyze_job_with_llm(job_title: str, job_description: str) -> str:
    prompt = f"{SYSTEM_PROMPT}\n\nJob Title: {job_title}\nJob Description:\n{job_description}\n"
    logger.info("Sending to Ollama: %s", job_title)
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        output = resp.json().get("response", "").strip()
        if not output:
            return "Analysis unavailable for this listing."
        return output
    except RequestException as exc:
        logger.exception("Ollama failed for '%s': %s", job_title, exc)
        return "⚠️ Ollama is not reachable. Make sure it is running on port 11434."
    except Exception as exc:
        logger.exception("Unexpected Ollama error: %s", exc)
        return "An unexpected error occurred during analysis."


def check_ollama_status() -> str:
    try:
        resp = requests.get(OLLAMA_TAGS_URL, timeout=10)
        resp.raise_for_status()
        models = [m.get("name", "") for m in resp.json().get("models", []) if m.get("name")]
        return "🟢 online — " + ", ".join(models[:5]) if models else "🟢 online (no models loaded)"
    except Exception as exc:
        return f"🔴 offline ({exc})"


# ---------------------------------------------------------------------------
# Worker control
# ---------------------------------------------------------------------------

def _run_ps(script: str, timeout: int = 20) -> str:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    return (result.stdout or result.stderr or "").strip()


def is_worker_running() -> bool:
    try:
        escaped = str(APP_ROOT / "linkedin-job-worker.ps1").replace("\\", "\\\\")
        out = _run_ps(
            rf"$wp='{escaped}';"
            r"$p=Get-CimInstance Win32_Process|Where-Object{"
            r"$_.ProcessId -ne $PID -and $_.Name -match 'powershell' -and "
            r"$_.CommandLine -and $_.CommandLine -match [regex]::Escape($wp) -and "
            r"$_.CommandLine -match '(?i)-File'};"
            r"if($p){'RUNNING'}else{'STOPPED'}"
        )
        return "RUNNING" in out
    except Exception:
        return WORKER_PID_FILE.exists()


def start_worker() -> str:
    if not WORKER_STARTER.exists():
        return f"❌ Starter script not found: {WORKER_STARTER}"
    try:
        subprocess.run(["wscript.exe", str(WORKER_STARTER)], check=True, timeout=15)
        return "✅ Background worker started."
    except Exception as exc:
        return f"❌ Could not start worker: {exc}"


def stop_worker() -> str:
    if not WORKER_STOPPER.exists():
        return f"❌ Stopper script not found: {WORKER_STOPPER}"
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(WORKER_STOPPER)],
            capture_output=True, text=True, timeout=20, check=False,
        )
        out = (result.stdout or result.stderr or "").strip()
        return ("🛑 Worker stopped." + (f"\n{out}" if out else "")
                if result.returncode == 0 else f"❌ Stop failed: {out}")
    except Exception as exc:
        return f"❌ Could not stop worker: {exc}"


def get_status_html() -> str:
    running  = is_worker_running()
    ollama   = check_ollama_status()
    counts   = db_count_by_source()
    total    = sum(counts.values())
    li_count = counts.get("LinkedIn", 0)
    in_count = counts.get("Indeed", 0)
    db_line  = f"{total} total (🔵 {li_count} LinkedIn, 🟠 {in_count} Indeed)"
    log_line = ""
    if WORKER_LOG_FILE.exists():
        try:
            last = WORKER_LOG_FILE.read_text(encoding="utf-8").strip().splitlines()[-1]
            log_line = f"\n📋 Last log: {h(last)}"
        except Exception:
            pass
    return (
        "<b>System Status</b>\n"
        f"• Worker: {'🟢 running' if running else '🔴 stopped'}\n"
        f"• Ollama: {h(ollama)}\n"
        f"• Jobs in DB: {db_line}{log_line}"
    )


# ---------------------------------------------------------------------------
# Conversation helpers
# ---------------------------------------------------------------------------

GREETING_RE = re.compile(
    r"^(hi+|hello+|hey+|howdy|sup|yo|hola|greetings|"
    r"good\s+(morning|afternoon|evening|day)|"
    r"how are you|what'?s up|how'?s it going)"
    r"[\s!?.]*$",
    re.IGNORECASE,
)

ANALYZE_RE = re.compile(
    r"^(?:analyze|analyse|analysis|check|tell me about|job|#)[\s#]*(\d+)$",
    re.IGNORECASE,
)

SHOW_JOBS_RE = re.compile(
    r"^(show|list|get|find|display)?\s*(latest|recent|all|new)?\s*jobs?\s*$",
    re.IGNORECASE,
)


def welcome_html() -> str:
    return (
        "👋 <b>Hi! I'm your LinkedIn Job Assistant.</b>\n\n"
        "The background monitor finds jobs in UAE and stores them locally.\n"
        "I can search that database and analyze any job with AI.\n\n"
        "<b>Commands:</b>\n"
        "/jobs — show latest 10 jobs\n"
        "/search &lt;title&gt; — search by title, company or location\n"
        "/status — worker, Ollama and DB status\n"
        "/worker_start — start background monitor\n"
        "/worker_stop — stop background monitor\n\n"
        "<b>Tip:</b> just type a job title to search, or reply with a number to analyze a job."
    )


def _show_jobs(chat_id: int, jobs: List[Dict], header: str) -> None:
    if not jobs:
        safe_reply(chat_id, "No jobs found. The background worker will add more as it runs.")
        return
    safe_reply_html(chat_id, format_job_list(jobs, header, chat_id))


def _analyze_job_by_number(chat_id: int, num: int) -> None:
    jobs = _recent_jobs.get(chat_id, [])
    if not jobs:
        safe_reply(chat_id, "No job list yet. Use /jobs or search first, then pick a number.")
        return
    if num < 1 or num > len(jobs):
        safe_reply(chat_id, f"Please pick a number between 1 and {len(jobs)}.")
        return

    job = jobs[num - 1]
    title   = job.get("title", "Unknown")
    company = job.get("company", "")
    job_id  = job.get("job_id", "")
    url     = job.get("url", "")

    safe_reply(chat_id, f"🔍 Fetching description and analyzing: {title} at {company}...")

    fallback = f"{title} at {company} in {job.get('location', '')}."
    description = fetch_job_description(job_id, fallback)

    safe_reply(chat_id, "🤖 Analyzing with AI — please wait...")
    analysis = analyze_job_with_llm(title, description)

    safe_reply_html(
        chat_id,
        f"<b>Job Title:</b> {h(title)}\n"
        f"<b>Company:</b> {h(company)}\n"
        f"<b>Location:</b> {h(job.get('location', ''))}\n"
        f"<b>Link:</b> {url}\n\n"
        f"<b>AI Analysis:</b>\n{h(analysis)}"
    )


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["start", "help"])
def handle_start(message) -> None:
    logger.info("/start|/help from chat_id=%s", message.chat.id)
    if not _is_authorized(message):
        return
    safe_reply_html(message.chat.id, welcome_html())


@bot.message_handler(commands=["jobs"])
def handle_jobs(message) -> None:
    logger.info("/jobs from chat_id=%s", message.chat.id)
    if not _is_authorized(message):
        return
    jobs = db_recent(10)
    _show_jobs(message.chat.id, jobs, f"Latest {len(jobs)} jobs in database")


@bot.message_handler(commands=["search"])
def handle_search(message) -> None:
    chat_id = message.chat.id
    if not _is_authorized(message):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        safe_reply(chat_id, "Usage: /search <job title or keyword>\nExample: /search IT Support")
        return
    query = parts[1].strip()
    logger.info("/search '%s' from chat_id=%s", query, chat_id)
    jobs = db_search(query, limit=10)
    _show_jobs(chat_id, jobs, f"Search results for: {query}")


@bot.message_handler(commands=["status"])
def handle_status(message) -> None:
    logger.info("/status from chat_id=%s", message.chat.id)
    if not _is_authorized(message):
        return
    safe_reply_html(message.chat.id, get_status_html())


@bot.message_handler(commands=["worker_start"])
def handle_worker_start(message) -> None:
    logger.info("/worker_start from chat_id=%s", message.chat.id)
    if not _is_authorized(message):
        return
    safe_reply(message.chat.id, start_worker())


@bot.message_handler(commands=["worker_stop"])
def handle_worker_stop(message) -> None:
    logger.info("/worker_stop from chat_id=%s", message.chat.id)
    if not _is_authorized(message):
        return
    safe_reply(message.chat.id, stop_worker())


@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_free_text(message) -> None:
    if not _is_authorized(message):
        return

    chat_id = message.chat.id
    text    = (message.text or "").strip()

    # --- greeting ---
    if GREETING_RE.match(text):
        logger.info("Greeting from chat_id=%s", chat_id)
        safe_reply_html(chat_id, welcome_html())
        return

    # --- "analyze N" or bare number ---
    m = ANALYZE_RE.match(text) or re.match(r"^(\d+)$", text)
    if m:
        num = int(m.group(1))
        logger.info("Analyze job #%s from chat_id=%s", num, chat_id)
        _analyze_job_by_number(chat_id, num)
        return

    # --- "show jobs" / "list jobs" variants ---
    if SHOW_JOBS_RE.match(text):
        jobs = db_recent(10)
        _show_jobs(chat_id, jobs, f"Latest {len(jobs)} jobs in database")
        return

    # --- anything else → search local DB ---
    logger.info("DB search '%s' from chat_id=%s", text, chat_id)
    jobs = db_search(text, limit=10)
    if jobs:
        _show_jobs(chat_id, jobs, f"Results for: {text}")
    else:
        total = db_count()
        safe_reply(
            chat_id,
            f"No jobs found matching '{text}'.\n"
            f"There are {total} jobs in the database.\n"
            "Try /jobs to see the latest ones, or a broader keyword."
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("Starting Telegram LinkedIn AI Assistant...")
    logger.info("Allowed chat IDs: %s", ALLOWED_CHAT_IDS or "all")
    print("Bot is running. Press Ctrl+C to stop.")

    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except KeyboardInterrupt:
            print("Bot stopped.")
            break
        except Exception as exc:
            logger.exception("Polling crashed: %s — restarting in 5 s", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
