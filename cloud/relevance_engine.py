"""
Dynamic job relevance classifier — driven entirely by the user's CV profile
stored in Supabase.  Replaces all hardcoded _IT_DOMAIN_TERMS / _NON_IT_TITLE_REJECT /
_ENRICHER_NON_IT_TITLE regex patterns that were scattered across worker.py and enricher.py.

Usage (worker / enricher):
    import relevance_engine

    engine = relevance_engine.RelevanceEngine.from_supabase(
        supabase_url, supabase_key, keywords=["IT Support", "System Administrator"]
    )

    # Per-job check
    relevant, reason = engine.is_relevant(job["Title"])

    # Batch filter
    kept_jobs, dropped_count = engine.filter_jobs(jobs, log_prefix="LinkedIn 'IT Support'")

    # Nationals filter (separate dimension)
    jobs = [j for j in jobs if not relevance_engine.is_nationals_only(j)]

Five-tier classification:
    T1  Any keyword word found in title (whole-word)                 → ACCEPT
    T2  Any CV job-title word found in title                         → ACCEPT
    T3  Any CV skill word found in title                             → ACCEPT
    T5* Hard-reject — title is clearly a non-target-field role       → REJECT
    T4  Any CV domain-term found in title (derived from T2+T3 words) → ACCEPT
    --  No tier matched                                              → REJECT

* T5 is evaluated BEFORE T4 to prevent the domain-term catch-all from
  accidentally accepting non-IT roles (e.g. "Risk Analyst" contains "analyst",
  which is an IT domain term, but is a finance role that should be rejected).
"""

from __future__ import annotations

import re
import sys
import os

_DIR = os.path.dirname(os.path.abspath(__file__))


# ── Stopwords ─────────────────────────────────────────────────────────────────

_STOPWORDS = frozenset({
    "and", "or", "the", "of", "in", "at", "for", "to", "with",
    "using", "via", "a", "an", "be", "are", "is", "was", "as",
    "on", "by", "from", "up", "into", "over", "under", "its",
    "that", "this", "has", "have", "not", "but",
})


# ── Hard-reject patterns (T5) ─────────────────────────────────────────────────
#
# Titles that are unambiguously outside the IT/technology domain, regardless
# of what the CV says.  Only triggers after T1-T3 have all failed.
# Keep patterns explicit and specific — vague patterns cause false positives.

_HARD_REJECT = re.compile(
    r"\b("
    # ── Real estate / property ────────────────────────────────────────────────
    r"real[\s\-]estate|property\s+(consultant|agent|manager|broker|developer)|"
    # ── Sales / marketing ─────────────────────────────────────────────────────
    r"sales\s+(executive|manager|representative|agent|associate|officer)|"
    r"marketing\s+(manager|executive|specialist|coordinator|analyst)|"
    r"digital\s+marketing|social\s+media(\s+(manager|specialist|executive))?|"
    # ── Finance / accounting ──────────────────────────────────────────────────
    r"accountant|accounting\s+(manager|officer)|"
    r"finance\s+manager|financial\s+(advisor|consultant|controller|analyst\s+(?!systems))|"
    # ── Non-IT engineering disciplines ───────────────────────────────────────
    # NOTE: "engineer" alone is intentionally absent — it appears in IT titles.
    # Only hard-reject when a non-IT qualifier is present.
    r"civil\s+engineer(ing)?|mechanical\s+engineer(ing)?|electrical\s+engineer(ing)?|"
    r"structural\s+engineer(ing)?|process\s+engineer(ing)?|petroleum\s+engineer(ing)?|"
    r"chemical\s+engineer(ing)?|piping\s+engineer|instrument\s+engineer|"
    r"oil\s+(and|&)\s+gas\s+engineer|subsea\s+engineer|"
    r"pmc\s+engineer|engineering\s+manager|"  # PMC = Project Mgmt Consultant (O&G)
    # ── HR / recruitment ──────────────────────────────────────────────────────
    r"human\s+resources|hr\s+(manager|executive|specialist|officer|director)|"
    r"recruitment\s+(consultant|manager|executive)|recruiter|talent\s+acquisition|"
    # ── Healthcare / hospitality / transport ──────────────────────────────────
    r"nurse|nursing|doctor|physician|medical\s+(officer|representative)|pharmacist|"
    r"chef|cook|barista|waiter|waitress|driver|delivery\s+(driver|rider)|"
    # ── Supply chain / procurement ────────────────────────────────────────────
    r"procurement\s+(manager|officer)|supply\s+chain\s+(manager|coordinator)|"
    r"logistics\s+(coordinator|manager)|"
    # ── Education / teaching ──────────────────────────────────────────────────
    r"teacher|teaching\s+assistant|lecturer|professor|tutor|"
    r"academic\s+(coordinator|advisor|director|dean)|"
    r"curriculum\s+(developer|specialist|coordinator)|"
    r"school\s+(principal|counselor|coordinator)|"
    r"early\s+childhood|nursery\s+teacher|"
    # ── Compliance / legal / financial crime ──────────────────────────────────
    r"compliance\s+(manager|officer|head|director|analyst)|"
    r"financial\s+crime|aml\s+(analyst|officer|manager)|anti[\s\-]money\s+laundering|"
    r"kyc\s+(analyst|officer|manager)|legal\s+(counsel|manager|officer|advisor)|"
    r"risk\s+(manager|officer|director)|"  # "risk analyst" excluded — can be IT security
    r"head\s+of\s+(compliance|legal|risk|finance|marketing|sales|hr)"
    r")\b",
    re.I,
)


# ── Nationals-only filter (separate dimension) ────────────────────────────────

_NATIONALS_ONLY = re.compile(
    r"\b("
    r"uae\s+national[s]?"
    r"|emirati[s]?"
    r"|gcc\s+national[s]?"
    r"|saudi\s+national[s]?"
    r"|omani\s+national[s]?"
    r"|kuwaiti\s+national[s]?"
    r"|bahraini\s+national[s]?"
    r"|qatari\s+national[s]?"
    r"|jordanian\s+national[s]?"
    r"|nationals\s+only"
    r"|citizens\s+only"
    r"|local\s+hire[s]?\s+only"
    r")\b",
    re.I,
)


def is_nationals_only(job: dict) -> bool:
    """Return True if the job is restricted to nationals / citizens.

    Checks the title field only (description is not yet available at scan time).
    Example: "IT Support – UAE Nationals Only" → True.
    """
    title = job.get("Title", "")
    return bool(_NATIONALS_ONLY.search(title))


# ── Domain-term fallback (used when cv_domain_terms not yet stored) ───────────

def _fallback_domain_terms(keywords: list[str]) -> frozenset[str]:
    """Minimal built-in fallback when the user hasn't analyzed their CV yet.

    Detects the user's field from the keyword list and returns a minimal but
    safe domain-term set so the engine doesn't block all jobs.
    """
    kw_lower = " ".join(keywords).lower()

    # IT Support / Sysadmin
    if any(w in kw_lower for w in ("support", "helpdesk", "sysadmin", "administrator",
                                    "infrastructure", "technician")):
        return frozenset({
            "it", "tech", "technical", "support", "system", "network", "server",
            "sysadmin", "admin", "administrator", "software", "hardware", "cloud",
            "cyber", "security", "helpdesk", "desktop", "infrastructure", "database",
            "analyst", "programmer", "devops", "linux", "windows", "azure", "aws",
            "technician", "developer", "architect", "technology", "ict",
        })

    # Software engineering / Development
    if any(w in kw_lower for w in ("python", "developer", "software", "backend",
                                    "frontend", "fullstack", "django", "react")):
        return frozenset({
            "software", "developer", "engineer", "python", "backend", "frontend",
            "fullstack", "api", "cloud", "aws", "azure", "database", "sql",
            "django", "flask", "fastapi", "react", "javascript", "typescript",
            "devops", "architect", "programmer", "technology", "tech",
        })

    # Data science / ML / AI
    if any(w in kw_lower for w in ("data", "machine learning", "ml", "ai", "analytics",
                                    "deep learning", "scientist")):
        return frozenset({
            "data", "machine", "learning", "ai", "ml", "analytics", "scientist",
            "engineer", "python", "sql", "cloud", "aws", "azure", "tensorflow",
            "pytorch", "statistician", "analyst", "pipeline", "spark", "hadoop",
        })

    # Generic tech fallback (unknown field)
    return frozenset({
        "it", "tech", "technical", "software", "developer", "engineer", "system",
        "network", "cloud", "cyber", "security", "data", "analyst", "programmer",
        "devops", "administrator", "support", "infrastructure", "technology", "ict",
    })


# ── Utility: CSV → word-set ───────────────────────────────────────────────────

def _csv_to_words(csv: str) -> set[str]:
    """Split a comma-separated skills/titles string into a set of matchable words.

    Example: "Windows Server, Active Directory, C++" → {"windows","server","active","directory","c++"}
    """
    words: set[str] = set()
    for item in csv.split(","):
        for word in re.split(r"[\s/\-\.]+", item.strip().lower()):
            word = re.sub(r"[^a-z0-9+#]", "", word)
            if len(word) >= 3 and word not in _STOPWORDS:
                words.add(word)
    return words


# ── RelevanceEngine ───────────────────────────────────────────────────────────

class RelevanceEngine:
    """CV-driven job relevance classifier.

    Constructed once per worker/enricher run.  Stateless after construction —
    all state is in the word-sets and keyword-words built from the CV profile.
    """

    def __init__(
        self,
        keywords: list[str],
        cv_skill_words: set[str],
        cv_domain_terms: set[str],
        cv_job_title_words: set[str],
    ) -> None:
        # Build the set of individual words from every keyword phrase.
        # e.g. ["IT Support", "System Administrator"] → {"it","support","system","administrator"}
        self.keyword_words: set[str] = set()
        for kw in keywords:
            for word in re.split(r"\W+", kw.lower()):
                word = re.sub(r"[^a-z0-9+#]", "", word)
                if len(word) >= 2:
                    self.keyword_words.add(word)

        self.cv_skill_words     = cv_skill_words       # from cv_skills CSV
        self.cv_domain_terms    = cv_domain_terms      # from cv_domain_terms CSV (or fallback)
        self.cv_job_title_words = cv_job_title_words   # from cv_job_titles CSV

    @classmethod
    def from_supabase(
        cls,
        supabase_url: str,
        supabase_key: str,
        keywords: list[str],
    ) -> "RelevanceEngine":
        """Load the user's CV profile from Supabase and construct the engine.

        Falls back gracefully if the DB is unavailable or no CV has been analyzed.
        """
        # Import db lazily to avoid circular deps and allow easy testing
        sys.path.insert(0, _DIR)
        try:
            import db  # type: ignore
        except ImportError:
            import importlib
            import importlib.util
            spec = importlib.util.spec_from_file_location("db", os.path.join(_DIR, "db.py"))
            db = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(db)

        try:
            cv_skills_csv  = db.get_config(supabase_url, supabase_key, "cv_skills",       "")
            cv_titles_csv  = db.get_config(supabase_url, supabase_key, "cv_job_titles",   "")
            cv_domain_csv  = db.get_config(supabase_url, supabase_key, "cv_domain_terms", "")
        except Exception as exc:
            print(f"[RelevanceEngine] Supabase load error (using fallback): {exc}", flush=True)
            cv_skills_csv = cv_titles_csv = cv_domain_csv = ""

        cv_skill_words     = _csv_to_words(cv_skills_csv)
        cv_job_title_words = _csv_to_words(cv_titles_csv)

        if cv_domain_csv.strip():
            cv_domain_terms: set[str] = _csv_to_words(cv_domain_csv)
        else:
            # First-run fallback: no CV analyzed yet
            cv_domain_terms = set(_fallback_domain_terms(keywords))
            if keywords:
                print(
                    "[RelevanceEngine] cv_domain_terms not found — using keyword-based fallback. "
                    "Run 'Analyze CV' in the Windows GUI to personalise results.",
                    flush=True,
                )

        engine = cls(keywords, cv_skill_words, cv_domain_terms, cv_job_title_words)

        # Log summary for GitHub Actions visibility
        print(
            f"[RelevanceEngine] Loaded: {len(cv_skill_words)} skill-word(s), "
            f"{len(cv_job_title_words)} title-word(s), "
            f"{len(cv_domain_terms)} domain-term(s), "
            f"{len(engine.keyword_words)} keyword-word(s)",
            flush=True,
        )
        return engine

    def is_relevant(self, title: str, description: str = "") -> tuple[bool, str]:
        """Classify a single job title.

        Returns (is_relevant, reason_str).

        reason_str examples:
            "T1:keyword(it)"
            "T2:job_title_word(administrator)"
            "T3:skill_word(active directory)"
            "T4:domain_term(networking)"
            "T5:hard_reject(property consultant)"
            "REJECT:no_match"
        """
        title_lower = title.lower()
        title_words = set(re.split(r"\W+", title_lower)) - {""}

        # T1 — any keyword word appears as a whole word in the title
        for kw_word in self.keyword_words:
            if re.search(r"\b" + re.escape(kw_word) + r"\b", title_lower):
                return True, f"T1:keyword({kw_word})"

        # T2 — any CV job-title word appears in the title
        matches = title_words & self.cv_job_title_words
        if matches:
            sample = next(iter(matches))
            return True, f"T2:job_title_word({sample})"

        # T3 — any CV skill word appears in the title
        matches = title_words & self.cv_skill_words
        if matches:
            sample = next(iter(matches))
            return True, f"T3:skill_word({sample})"

        # T5 — hard-reject before T4 to prevent domain-term false positives
        m = _HARD_REJECT.search(title_lower)
        if m:
            fragment = m.group(0)[:40].lower()
            return False, f"T5:hard_reject({fragment})"

        # T4 — CV domain-term catch-all
        matches = title_words & self.cv_domain_terms
        if matches:
            sample = next(iter(matches))
            return True, f"T4:domain_term({sample})"

        return False, "REJECT:no_match"

    def filter_jobs(
        self,
        jobs: list[dict],
        log_prefix: str = "",
    ) -> tuple[list[dict], int]:
        """Filter a list of job dicts.

        Returns (kept_jobs, dropped_count).
        Logs each dropped job with the rejection reason when log_prefix is given.
        """
        kept: list[dict] = []
        dropped = 0
        for job in jobs:
            title = job.get("Title", "")
            relevant, reason = self.is_relevant(title)
            if relevant:
                kept.append(job)
            else:
                dropped += 1
                if log_prefix:
                    print(
                        f"[Relevance] {log_prefix}: DROPPED '{title}' — {reason}",
                        flush=True,
                    )
        return kept, dropped
