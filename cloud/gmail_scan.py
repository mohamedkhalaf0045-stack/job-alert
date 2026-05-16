"""
Gmail job alert scanner — reads unprocessed job alert emails via IMAP.
Parses LinkedIn (jobalerts-noreply), Indeed (jobalert.indeed.com),
NaukriGulf, and Glassdoor digest formats.
Marks emails as read after processing so they are never re-scanned.

Required env vars:
    GMAIL_EMAIL         your Gmail address
    GMAIL_APP_PASSWORD  Google App Password (not your account password)
    SEARCH_GMAIL        "true" to enable (default: false)
"""

from __future__ import annotations

import email
import hashlib
import imaplib
import re
from email.header import decode_header as _decode_header
from urllib.parse import urlparse, urlunparse

# ---------------------------------------------------------------------------
# Location filtering
# ---------------------------------------------------------------------------
# Maps a normalised location string to a list of substrings that count as
# a match.  Add more entries here if you ever search in other countries.
_LOCATION_ALIASES: dict[str, list[str]] = {
    "united arab emirates": [
        "united arab emirates", "uae", "u.a.e",
        "dubai", "abu dhabi", "sharjah", "ajman",
        "ras al khaimah", "fujairah", "umm al quwain", "al ain",
        "rak", "dxb",
    ],
    "saudi arabia": [
        "saudi arabia", "ksa", "k.s.a",
        "riyadh", "jeddah", "dammam", "mecca", "medina",
        "makkah", "madinah",
    ],
    "egypt": [
        "egypt", "cairo", "alexandria", "giza",
        # Cairo districts / suburbs LinkedIn commonly uses
        "nasr city", "maadi", "heliopolis", "zamalek", "mohandessin",
        "new cairo", "6th of october", "sixth of october", "dokki",
        "shubra", "obour", "el obour", "el shorouk", "shorouk",
        "10th of ramadan", "tenth of ramadan", "fifth settlement",
        "new capital", "el rehab", "rehab city", "badr city",
        "hadayek el ahram", "hadayek", "imbaba", "ain shams",
        "abbassia", "ramses", "downtown cairo", "garden city",
        "new heliopolis", "sheraton", "nasr",
        # Tech / business hubs
        "smart village", "techno park", "tiec",
        # Alexandria areas
        "smouha", "sidi beshr", "moharam bek", "miami",
        # Other major cities
        "port said", "suez", "mansoura", "tanta", "assiut",
        "luxor", "aswan", "hurghada", "sharm el sheikh",
        "el mahalla", "fayoum", "beni suef", "minya",
        "zagazig", "ismailia", "damietta", "sohag", "qena",
    ],
    "kuwait": ["kuwait", "kuwait city"],
    "bahrain": ["bahrain", "manama"],
    "qatar": ["qatar", "doha"],
    "oman": ["oman", "muscat"],
    "jordan": ["jordan", "amman"],
}


def _normalise(text: str) -> str:
    return text.strip().lower()


def _get_aliases(location: str) -> list[str]:
    """Return the alias list for the given location string.

    Falls back to [normalised location string] so at minimum we do an
    exact-substring match even for unknown countries.
    """
    key = _normalise(location)
    # Direct key lookup first
    if key in _LOCATION_ALIASES:
        return _LOCATION_ALIASES[key]
    # Partial: does the key contain a known entry?
    for known_key, aliases in _LOCATION_ALIASES.items():
        if known_key in key or key in known_key:
            return aliases
    return [key]


def _job_location_matches(job_location: str, filter_location: str) -> bool:
    """Return True if job_location is consistent with filter_location.

    Rules:
    - Empty job location  -> ACCEPT (we can't reject what we don't know)
    - job location contains any alias of filter_location -> ACCEPT
    - Otherwise -> REJECT
    """
    loc = _normalise(job_location)
    if not loc:
        return True  # unknown location — let it through, enricher will judge

    for alias in _get_aliases(filter_location):
        if alias in loc:
            return True
    return False

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

# Senders → parser function (matched via substring in From header)
_JOB_ALERT_SENDERS = [
    "jobalert.indeed.com",
    "match.indeed.com",
    "jobalerts-noreply@linkedin.com",
    "naukrigulf.com",       # covers both info@ and similarjobs@
    "glassdoor.com",
]


# ── URL helpers ───────────────────────────────────────────────────────────────

def _canonical_url(raw: str) -> str:
    """Normalize a job URL for deduplication.

    LinkedIn job URLs come in two shapes depending on the source:
      - Guest API / email:  /jobs/view/4203456789
      - Web search:         /jobs/view/it-support-specialist-at-company-4203456789
    Both refer to the same job. Extract the trailing numeric ID and build a
    stable canonical form so lookups always match across sources.
    """
    try:
        raw = (raw or "").strip()
        if "linkedin.com/jobs/view/" in raw.lower():
            m = re.search(r'/jobs/view/[^/?#]*?(\d{7,})(?:[/?#]|$)', raw)
            if m:
                return f"https://www.linkedin.com/jobs/view/{m.group(1)}"
        p = urlparse(raw)
        return urlunparse((p.scheme, p.netloc, p.path, "", "", "")).rstrip("/")
    except Exception:
        return (raw or "").strip()


def _url_id(url: str) -> str:
    return hashlib.sha256(_canonical_url(url).lower().encode()).hexdigest()[:16]


def _clean_li_url(raw: str) -> str:
    """Strip LinkedIn tracking params, keep only the /jobs/view/{ID} path.

    Handles both numeric-only paths and slug+ID paths (e.g.
    /jobs/view/it-support-specialist-4203456789).
    """
    m = re.search(r'/jobs/view/[^/?#]*?(\d{7,})(?:[/?#]|$)', raw)
    if m:
        return f"https://www.linkedin.com/jobs/view/{m.group(1)}"
    return _canonical_url(raw)


# ── LinkedIn parser ───────────────────────────────────────────────────────────

_SKIP_LI = re.compile(r"^(apply\b|this company\b|https?://|-{5,})", re.I)


def _parse_linkedin_email(body: str) -> list[dict]:
    """
    Email format (per block):
        [Title]
        [Company]
        [Location]

        [optional: This company is actively hiring]
        [optional: X school alumni]
        [optional: Apply with resume & profile]
        View job: https://www.linkedin.com/comm/jobs/view/ID/?...
    """
    jobs: list[dict] = []
    seen: set[str] = set()
    lines = body.split("\n")

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("View job:"):
            continue

        raw_url = stripped[len("View job:"):].strip()
        url = _clean_li_url(raw_url)
        uid = _url_id(url)
        if uid in seen or not url:
            continue

        # Backtrack: skip meta lines, collect [title, company, location]
        parts: list[str] = []
        j = i - 1
        while j >= 0 and len(parts) < 3:
            prev = lines[j].strip()
            j -= 1
            if not prev:
                continue
            if _SKIP_LI.match(prev) or "school alumni" in prev.lower():
                continue
            parts.insert(0, prev)

        if len(parts) >= 2:
            seen.add(uid)
            jobs.append({
                "Id":         uid,
                "Keyword":    "",
                "Title":      parts[0],
                "Company":    parts[1],
                "Location":   parts[2] if len(parts) > 2 else "",
                "Url":        url,
                "PostedDate": "",
                "PostedText": "from email",
                "IsApplied":  False,
                "Source":     "Gmail/LinkedIn",
            })

    return jobs


# ── Indeed parser ─────────────────────────────────────────────────────────────

_INDEED_JK = re.compile(r"jk.([a-f0-9]{10,})", re.I)  # handles =, {, control chars
_SKIP_INDEED = re.compile(
    r"^(easily apply|https?://|jobs \d|see matching|indeed job|do not share|"
    r"salaries estimated|©|\d+ day|\d+ hour|just posted|\*|aed|usd|sar|\$|£|€|salary)",
    re.I,
)
_SALARY_LINE = re.compile(r"(aed|usd|sar|\$|£|€)\s*[\d,]", re.I)


def _parse_indeed_email(body: str) -> list[dict]:
    """
    Email format (per block):
        [Title]
        [Company] - [Location]
        [optional: Easily apply]
        [optional: description snippet]
        [optional: X days ago]
        https://ae.indeed.com/rc/clk/dl?jk=...
    """
    jobs: list[dict] = []
    seen: set[str] = set()
    lines = body.split("\n")

    for i, line in enumerate(lines):
        stripped = line.strip()
        if "ae.indeed.com/rc/clk" not in stripped and "ae.indeed.com/viewjob" not in stripped:
            continue

        url_m = re.search(r"(https://[^\s]+)", stripped)
        if not url_m:
            continue
        raw_url = url_m.group(1)

        # Prefer canonical viewjob URL keyed by jk param
        jk_m = _INDEED_JK.search(raw_url)
        url = f"https://ae.indeed.com/viewjob?jk={jk_m.group(1)}" if jk_m else _canonical_url(raw_url)
        uid = _url_id(url)
        if uid in seen:
            continue

        # Backtrack: find "Company - Location" line then title above it
        title = company = location = ""
        for k in range(i - 1, max(i - 12, -1), -1):
            prev = lines[k].strip()
            if not prev or _SKIP_INDEED.match(prev):
                continue
            # Indeed puts "Company - Location" on one line with " - " separator
            # Skip salary lines like "AED5,000 - AED8,000 a month"
            if " - " in prev and not company and not _SALARY_LINE.search(prev):
                parts = prev.split(" - ", 1)
                company = parts[0].strip()
                location = parts[1].strip()
                # Title is the line before the company-location line
                for m in range(k - 1, max(k - 5, -1), -1):
                    tprev = lines[m].strip()
                    if tprev and not _SKIP_INDEED.match(tprev):
                        title = tprev
                        break
                break

        if title and url:
            seen.add(uid)
            jobs.append({
                "Id":         uid,
                "Keyword":    "",
                "Title":      title,
                "Company":    company,
                "Location":   location or "UAE",
                "Url":        url,
                "PostedDate": "",
                "PostedText": "from email",
                "IsApplied":  False,
                "Source":     "Gmail/Indeed",
            })

    return jobs


# ── NaukriGulf parser ─────────────────────────────────────────────────────────

_NG_URL = re.compile(r"(https://www\.naukrigulf\.com/[^\s]+)")


def _parse_naukrigulf_email(body: str) -> list[dict]:
    jobs: list[dict] = []
    seen: set[str] = set()
    lines = body.split("\n")

    for i, line in enumerate(lines):
        m = _NG_URL.search(line.strip())
        if not m:
            continue
        url = _canonical_url(m.group(1))
        uid = _url_id(url)
        if uid in seen:
            continue

        title = company = location = ""
        for k in range(i - 1, max(i - 8, -1), -1):
            prev = lines[k].strip()
            if not prev or prev.startswith("http"):
                continue
            if not title:
                title = prev
            elif not company:
                company = prev
            elif not location:
                location = prev
                break

        if title:
            seen.add(uid)
            jobs.append({
                "Id":         uid,
                "Keyword":    "",
                "Title":      title,
                "Company":    company,
                "Location":   location or "UAE",
                "Url":        url,
                "PostedDate": "",
                "PostedText": "from email",
                "IsApplied":  False,
                "Source":     "Gmail/NaukriGulf",
            })

    return jobs


# ── Glassdoor parser ──────────────────────────────────────────────────────────

_GD_URL = re.compile(r"(https://www\.glassdoor\.com/job[^\s]+)", re.I)


def _parse_glassdoor_email(body: str) -> list[dict]:
    jobs: list[dict] = []
    seen: set[str] = set()
    lines = body.split("\n")

    for i, line in enumerate(lines):
        m = _GD_URL.search(line.strip())
        if not m:
            continue
        url = _canonical_url(m.group(1))
        uid = _url_id(url)
        if uid in seen:
            continue

        title = company = location = ""
        for k in range(i - 1, max(i - 8, -1), -1):
            prev = lines[k].strip()
            if not prev or prev.startswith("http"):
                continue
            if not title:
                title = prev
            elif not company:
                company = prev
            elif not location:
                location = prev
                break

        if title:
            seen.add(uid)
            jobs.append({
                "Id":         uid,
                "Keyword":    "",
                "Title":      title,
                "Company":    company,
                "Location":   location or "UAE",
                "Url":        url,
                "PostedDate": "",
                "PostedText": "from email",
                "IsApplied":  False,
                "Source":     "Gmail/Glassdoor",
            })

    return jobs


# ── Sender → parser map ───────────────────────────────────────────────────────

_PARSER_MAP = {
    "jobalert.indeed.com":            _parse_indeed_email,
    "jobalerts-noreply@linkedin.com": _parse_linkedin_email,
    "naukrigulf.com":                 _parse_naukrigulf_email,
    "glassdoor.com":                  _parse_glassdoor_email,
}


# ── IMAP helpers ──────────────────────────────────────────────────────────────

def _get_plaintext_body(msg: email.message.Message) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body += payload.decode("utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode("utf-8", errors="replace")
    return body


# ── Public entry point ────────────────────────────────────────────────────────

def scan_gmail(
    email_address: str,
    app_password: str,
    location: str = "",
    max_emails: int = 100,
) -> list[dict]:
    """
    Connect to Gmail via IMAP SSL, find all UNREAD job alert emails from
    known senders, parse them into job dicts, mark each as read.

    If ``location`` is provided (e.g. "United Arab Emirates"), any job whose
    Location field does NOT match that location (or its city aliases) is
    silently dropped before being returned.  Jobs with an empty location
    field are kept — we can't filter what we don't know.

    Returns [] if credentials are missing or on any error.
    """
    if not email_address or not app_password:
        return []

    all_jobs: list[dict] = []
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(email_address, app_password)
        mail.select("INBOX")

        # Collect unique message numbers for all job alert senders
        msg_nums: set[bytes] = set()
        for sender in _JOB_ALERT_SENDERS:
            _, data = mail.search(None, f'(UNSEEN FROM "{sender}")')
            if data and data[0]:
                msg_nums.update(data[0].split())

        candidates = list(msg_nums)[:max_emails]
        print(f"[Gmail] {len(candidates)} unread job alert email(s) to process")

        for num in candidates:
            try:
                _, msg_data = mail.fetch(num, "(RFC822)")
                raw_bytes = msg_data[0][1]
                msg = email.message_from_bytes(raw_bytes)
                sender_hdr = msg.get("From", "").lower()
                subject    = msg.get("Subject", "?")
                body       = _get_plaintext_body(msg)

                parser = None
                for domain, fn in _PARSER_MAP.items():
                    if domain in sender_hdr:
                        parser = fn
                        break

                if parser is None:
                    # Unknown sender — mark read and skip
                    mail.store(num, "+FLAGS", "\\Seen")
                    continue

                parsed = parser(body)

                # --- Location filter ---
                if location:
                    before = len(parsed)
                    parsed = [
                        j for j in parsed
                        if _job_location_matches(j.get("Location", ""), location)
                    ]
                    dropped = before - len(parsed)
                    if dropped:
                        print(
                            f"[Gmail] '{subject}' — dropped {dropped} job(s) "
                            f"outside '{location}' (location filter)"
                        )

                print(f"[Gmail] '{subject}' -> {len(parsed)} job(s) kept")
                all_jobs.extend(parsed)

                # Mark read regardless — prevents infinite reprocessing
                mail.store(num, "+FLAGS", "\\Seen")

            except Exception as exc:
                print(f"[Gmail] Error on message {num}: {exc}")

        mail.logout()

    except imaplib.IMAP4.error as exc:
        print(f"[Gmail] IMAP auth/connection error: {exc}")
    except Exception as exc:
        print(f"[Gmail] Unexpected error: {exc}")

    return all_jobs
