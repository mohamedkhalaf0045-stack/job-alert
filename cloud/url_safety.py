"""
URL safety checker for job-alert Telegram notifications.

Every job URL is validated before being sent to the user so that
clicking it is safe: no phishing redirects, no IP-based URLs,
no non-HTTPS links, no suspicious URL patterns.

Usage:
    from url_safety import check_url, sanitize_url

    safe, reason = check_url("https://www.linkedin.com/jobs/view/1234567")
    if not safe:
        print(f"Blocked: {reason}")
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# ── Trusted job-board domains ─────────────────────────────────────────────────
# These are the domains the scrapers produce.  URLs whose apex domain is in
# this set are accepted without further scrutiny (still must be HTTPS).
_TRUSTED_DOMAINS: frozenset[str] = frozenset({
    # LinkedIn
    "linkedin.com",
    # Bayt / GulfTalent / NaukriGulf / Gulf-region boards
    "bayt.com",
    "gulftalent.com",
    "naukrigulf.com",
    "naukri.com",
    "gulfnews.com",
    "careers.ae",
    "jobs.ae",
    "dubizzle.com",
    # International boards
    "indeed.com",
    "glassdoor.com",
    "glassdoor.co.uk",
    "monster.com",
    "monster.ae",
    "totaljobs.com",
    "reed.co.uk",
    "adzuna.com",
    "adzuna.ae",
    "adzuna.co.uk",
    "jobsindubai.ae",
    "simplyhired.com",
    "careerjet.com",
    "careerjet.ae",
    "ziprecruiter.com",
    # Company career portals (common ATS/HRIS domains)
    "greenhouse.io",
    "lever.co",
    "workday.com",
    "myworkdayjobs.com",
    "icims.com",
    "smartrecruiters.com",
    "taleo.net",
    "bamboohr.com",
    "jobvite.com",
    "workable.com",
    "recruitee.com",
    "ashbyhq.com",
    "applytojob.com",
    "careers.microsoft.com",
    "careers.google.com",
    "jobs.apple.com",
    "amazon.jobs",
    "careers.amazon.com",
    "careers.ibm.com",
    "careers.cisco.com",
    "careers.oracle.com",
    "careers.sap.com",
    # UAE gov / semi-gov companies
    "emiratesnbd.com",
    "adcb.com",
    "etisalat.ae",
    "du.ae",
    "adnoc.ae",
    "mubadala.ae",
    "dewa.gov.ae",
    "rta.ae",
    "emaratech.ae",
    "g42.ai",
})

# ── Suspicious URL patterns ───────────────────────────────────────────────────

# Raw IPv4 address in the hostname — never a legitimate job board
_IP_IN_HOST = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

# URL shorteners / redirect services — hide the real destination
_URL_SHORTENERS: frozenset[str] = frozenset({
    "bit.ly", "t.co", "goo.gl", "tinyurl.com", "ow.ly", "buff.ly",
    "short.io", "rb.gy", "is.gd", "v.gd", "clck.ru", "cutt.ly",
    "tiny.cc", "lnkd.in", "t.ly", "shorturl.at",
})

# TLDs commonly used in phishing (not job boards)
_SUSPICIOUS_TLDS: frozenset[str] = frozenset({
    ".xyz", ".tk", ".ml", ".ga", ".cf", ".gq", ".top",
    ".click", ".download", ".loan", ".stream", ".gdn",
})

# Suspicious path patterns
_SUSPICIOUS_PATH = re.compile(
    r"""
    \.(exe|msi|bat|cmd|ps1|vbs|sh|dmg|apk|deb|rpm)   # executable files
    | /download/[^/]{1,30}\.(exe|msi|bat|cmd|ps1|vbs)  # explicit download
    """,
    re.I | re.X,
)

# Allowed schemes
_ALLOWED_SCHEMES: frozenset[str] = frozenset({"https"})   # http not allowed


# ── Core checker ─────────────────────────────────────────────────────────────

def check_url(url: str) -> tuple[bool, str]:
    """
    Validate a job URL before it is sent to the user.

    Returns:
        (True, "")               — safe to send
        (False, "<reason>")      — blocked; log the reason, do not send

    Rules (in order):
    1. Must be a non-empty string.
    2. Scheme must be https.
    3. Host must not be a raw IP address.
    4. Host must not be a known URL shortener (hides real destination).
    5. TLD must not be from the known-phishing list.
    6. Path must not contain executable file extensions.
    7. URL must not be excessively long (>2000 chars — typical of tracking spam).
    8. If the apex domain is in _TRUSTED_DOMAINS → accept.
    9. Otherwise: warn but allow (company career pages not all listed above).
    """
    url = (url or "").strip()
    if not url:
        return False, "empty URL"

    try:
        parsed = urlparse(url)
    except Exception:
        return False, "URL parse error"

    scheme = parsed.scheme.lower()
    host   = parsed.netloc.lower().split(":")[0]  # strip port
    path   = parsed.path.lower()
    host_bare = host.lstrip("www.")

    # 1. Scheme check
    if scheme not in _ALLOWED_SCHEMES:
        return False, f"insecure scheme '{scheme}' — only HTTPS links are sent"

    # 2. Must have a real hostname
    if not host:
        return False, "URL has no hostname"

    # 3. Raw IP address
    if _IP_IN_HOST.match(host):
        return False, f"raw IP address '{host}' — not a real job board"

    # 4. URL shortener
    apex = _apex_domain(host_bare)
    if apex in _URL_SHORTENERS or host_bare in _URL_SHORTENERS:
        return False, f"URL shortener '{host}' hides the real destination"

    # 5. Suspicious TLD
    for tld in _SUSPICIOUS_TLDS:
        if host_bare.endswith(tld):
            return False, f"suspicious TLD '{tld}' — typically used in phishing"

    # 6. Executable in path
    if _SUSPICIOUS_PATH.search(path):
        return False, f"URL path suggests executable download"

    # 7. Excessively long URL (spam / tracking abuse)
    if len(url) > 2000:
        return False, f"URL too long ({len(url)} chars) — possible spam"

    # 8. Trusted domain → safe
    if apex in _TRUSTED_DOMAINS or host_bare in _TRUSTED_DOMAINS:
        return True, ""

    # 9. Unknown domain — allow but caller can log a notice
    # (company career pages on bespoke subdomains: acme.workday.com, jobs.acme.com, etc.)
    return True, f"unverified-domain:{host_bare}"   # truthy = safe; non-empty reason = notice


def sanitize_url(url: str) -> str:
    """
    Return a clean version of a URL safe to embed in a message:
    - Strips tracking query params (utm_*, fbclid, gclid, etc.)
    - Forces https scheme
    - Strips fragment identifiers (#)
    - Trims whitespace

    Returns the original URL unchanged if parsing fails.
    """
    url = (url or "").strip()
    if not url:
        return url
    try:
        from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
        p = urlparse(url)

        # Force https
        scheme = "https"

        # Remove tracking params
        _TRACKING_PARAMS = frozenset({
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid",
            "ref", "referrer", "source", "campaign",
            "_ga", "_gl", "trk", "trkInfo",    # LinkedIn tracking
        })
        qs = parse_qs(p.query, keep_blank_values=False)
        clean_qs = {k: v for k, v in qs.items() if k not in _TRACKING_PARAMS}
        clean_query = urlencode(clean_qs, doseq=True) if clean_qs else ""

        return urlunparse((scheme, p.netloc, p.path, p.params, clean_query, ""))
    except Exception:
        return url


# ── Helper ────────────────────────────────────────────────────────────────────

def _apex_domain(host: str) -> str:
    """Extract apex domain (last two labels) from a hostname.

    www.linkedin.com  → linkedin.com
    jobs.bayt.com     → bayt.com
    myworkdayjobs.com → myworkdayjobs.com
    """
    parts = host.rstrip(".").split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host
