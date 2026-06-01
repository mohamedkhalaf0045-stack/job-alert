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


# ── Keyword-word blocklist (T1 guard) ─────────────────────────────────────────
#
# These words are too generic to use as standalone T1 signals even when they
# appear inside a keyword phrase.  Examples:
#   "Endpoint Management Engineer" → "management" would match "Waste Management"
#   "Technical Services Engineer"  → "services" matched aviation roles via T1
# The remaining IT-specific words from each phrase still make it through T1.
# T5 (hard-reject) is the primary guard; this is defence-in-depth.

_KEYWORD_WORD_BLOCKLIST = frozenset({
    # Seniority / level words — not field indicators
    "senior",       # "Senior Business Development Manager" matched on this
    "junior",       # "Junior Marketing Executive" matched on this
    "lead",         # "Lead Accountant", "Lead Chef" etc. would match
    # Generic role-type words — appear in too many non-IT disciplines
    "engineer",     # 17 false positives: Project Engineer, Maintenance Engineer, Dental Service Eng…
    "specialist",   # 5 false positives: QHSES Specialist, Sustainability Specialist, Internship Spec…
    "help",         # "help your business clients escape brutal interest rates" scored 9/10 via T1
    "management",   # waste / property / brand / fleet management
    "services",     # "Technical Services" matched aviation roles; too broad alone
    "admin",        # "Female Admin", "HR Admin", "Sales Admin" — IT roles already
                    # caught by "administrator", "it", "system", "network" etc.
})


# ── IT-core terms (always merged into cv_domain_terms) ────────────────────────
#
# These acronyms/terms are so specific to IT/security operations that they
# should ALWAYS trigger T4 acceptance, regardless of what cv_domain_terms was
# loaded from Supabase.  Whole-word matching (via set intersection against
# title_words) is safe — "soc" never appears as a standalone token in non-IT titles.
#
# Roles covered:
#   SOC Analyst / Engineer       Security Operations Center
#   NOC Engineer / Analyst       Network Operations Center
#   CSIRT Engineer               Computer Security Incident Response Team
#   GSOC Analyst                 Global Security Operations Center

_IT_CORE_TERMS = frozenset({
    "soc",    # Security Operations Center
    "noc",    # Network Operations Center
    "csirt",  # Computer Security Incident Response Team
    "gsoc",   # Global SOC
})


# ── Generic role words (T4 guard) ─────────────────────────────────────────────
#
# These words appear in both IT and non-IT job titles, so they are too ambiguous
# to trigger T4 acceptance on their own.  When cv_analyzer extracts domain terms
# from the user's CV (e.g. "IT Support Coordinator" → "coordinator"), these words
# end up in cv_domain_terms and would otherwise match unrelated roles like
# "Packaging Coordinator" or "Document Controller".
#
# T4 only fires when at least one match is NOT in this set — i.e. there must be
# a genuinely IT-flavoured domain word in the title alongside the generic one.
# T1/T2/T3 are unaffected: "IT Support Coordinator" is already accepted by T1
# (keyword word "support"), so removing "coordinator" from T4 causes no loss.

_GENERIC_ROLE_WORDS = frozenset({
    "coordinator",    # Packaging Coordinator, Logistics Coordinator
    "controller",     # Document Controller, Financial Controller
    "inspector",      # Site Inspector, Quality Inspector
    "supervisor",     # Floor Supervisor, Warehouse Supervisor
    "officer",        # Compliance Officer, Safety Officer, HSE Officer
    "assistant",      # Administrative Assistant, Executive Assistant
    "associate",      # Sales Associate, Operations Associate
    "executive",      # Sales Executive, Marketing Executive
    "representative", # Sales Representative, Brand Representative
    "planner",        # Event Planner, Urban Planner
    "advisor",        # Financial Advisor, HR Advisor
    "facilitator",    # Training Facilitator
    "liaison",        # Client Liaison, Site Liaison
    "specialist",     # Packaging Specialist — legitimate IT use (T1/T3 cover those)
})


# ── Skill vocabulary regex (T_DESC — description matching) ───────────────────
#
# Highly specific IT terms extracted from the user's full skill taxonomy.
# Used to accept jobs whose title misses all positive tiers but whose
# description clearly shows IT relevance (e.g. a vague title like
# "Systems Specialist" paired with a description mentioning "Intune" or "Veeam").
# Only fires when a non-empty description is passed to is_relevant().
#
# Single-word terms use \b anchors; multi-word phrases use a flexible [\s\-]+ joiner.

_SKILL_VOCAB_RE = re.compile(
    r"\b("
    # Identity & access management
    r"entra|intune|autopilot|okta|saml|ldap|rbac|iam|sso|mfa|pam|"
    # Microsoft 365 & collaboration
    r"sharepoint|purview|ediscovery|o365|m365|"
    r"exchange[\s\-]online|microsoft[\s\-]365|"
    # Endpoint & device management
    r"bitlocker|sccm|mecm|wsus|mdm|mam|uem|"
    r"microsoft[\s\-]defender|windows[\s\-]autopilot|"
    # Infrastructure
    r"vsphere|esxi|vmware|hyper[\s\-]v|veeam|zabbix|nagios|"
    r"active[\s\-]directory|azure[\s\-]ad|"
    # Networking & security
    r"fortinet|fortigate|forticlient|palo[\s\-]alto|ipsec|ospf|bgp|vlan|"
    # Scripting & automation
    r"powershell|power[\s\-]automate|"
    # Cloud platforms
    r"azure|terraform|kubernetes|"
    # Security
    r"zero[\s\-]trust|conditional[\s\-]access|dlp|"
    # Service management platforms
    r"servicenow|freshdesk|jira[\s\-]service"
    r")\b",
    re.I,
)


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
    r"inside\s+sales|account\s+director|account\s+(manager|executive)|"
    r"client\s+(manager|director|executive)|"
    r"business\s+development\s+(manager|executive|director|specialist|officer|representative)|"
    r"go[\s\-]to[\s\-]market|gtm\s+(manager|lead|engineer|specialist)|"
    r"sales\s+enablement|institutional\s+salesperson|"
    r"sales\s+(intern|internship)|commercial\s+sales\s+(intern|internship)|"
    r"marketing\s+(manager|executive|specialist|coordinator|analyst)|"
    r"digital\s+marketing|social\s+media(\s+(manager|specialist|executive))?|"
    r"(creative|brand)\s+(strategist|manager|director|designer)|"
    r"cro\s+(manager|specialist|analyst)|"    # conversion-rate optimisation
    # ── Finance / accounting ──────────────────────────────────────────────────
    r"accountant|accounting\s+(manager|officer)|"
    r"finance\s+(manager|administrator|officer)|financial\s+(advisor|consultant|controller|analyst\s+(?!systems))|"
    r"risk\s+operations|"
    # ── Design / creative (non-IT) ───────────────────────────────────────────
    r"interior\s+design(er|ing)?|graphic\s+design(er)?|fashion\s+design(er)?|"
    r"industrial\s+design(er)?(?!\s+automation)|"  # exclude "industrial automation"
    # ── Non-IT engineering disciplines ───────────────────────────────────────
    # NOTE: "engineer" alone is intentionally absent — it appears in IT titles.
    # Only hard-reject when a non-IT qualifier is present.
    r"civil\s+engineer(ing)?|mechanical\s+engineer(ing)?|electrical\s+engineer(ing)?|"
    r"structural\s+engineer(ing)?|process\s+engineer(ing)?|petroleum\s+engineer(ing)?|"
    r"chemical\s+engineer(ing)?|piping\s+engineer|instrument(ation)?\s+engineer|"
    r"oil\s+(and|&)\s+gas\s+engineer|subsea\s+engineer|"
    r"commissioning\s+engineer|"      # industrial plant/equipment commissioning
    r"planning\s+engineer|"           # civil/construction planning
    r"project\s+engineer|graduate\s+project\s+engineer|"   # construction/civil project engineers
    r"pmc\s+engineer|engineering\s+manager|"
    r"relay\s+(and\s+)?control\s+panel|"   # electrical panel manufacturing
    r"instrumentation\s+((and|&)\s+)?control\s+system|"  # I&C engineering
    r"occ\s+engineer|rail\s+communications?\s+(systems?\s+)?(engineer|expert|specialist)|"
    r"land\s+surveyor|resident\s+engineer|"
    r"maintenance\s+(engineer|technician)(?!\s*(support|server|it|system|network|cloud|cyber))|"
    r"electro[\s\-]mechanical\s+(inspector|technician)|"
    # ── Industrial / non-IT technician & physical trades ─────────────────────
    r"automotive\s+(technician|mechanic|engineer)|"
    r"(elevator|escalator)s?\s+(technician|engineer|mechanic)|"
    r"electrical\s+(and\s+|&\s+)?automation\s+technician|"
    r"hvac\s+technician|electromechanical\s+technician|"
    r"biomedical\s+(engineer|sales\s+engineer|tutor|specialist)|"
    # ── HSE / sustainability / physical inspection ────────────────────────────
    r"qhses|hse\s+assurance|"
    r"sustainability\s+(specialist|manager|engineer|officer|lead|expert|coordinator)|"
    r"associate\s+qhses|"
    # ── Writing / training / HR specialist ───────────────────────────────────
    r"technical\s+writer|content\s+writer|copywriter|"
    r"onboarding\s+specialist|"       # HR role, not IT
    r"customer\s+support\s+(assistant|specialist|coordinator|executive)|"
    r"customer\s+(sales\s+)?service\s+support|"
    # ── Legal ─────────────────────────────────────────────────────────────────
    r"legal\s+(counsel|consultant|manager|officer|advisor)|"
    # ── Software / web development (not IT support/ops) ─────────────────────
    # The user is an IT support/sysadmin — software developer roles are out of scope.
    # Negative lookahead preserves IT-adjacent titles like "Software Systems Engineer",
    # "Software Asset Management", "Cloud Platform Engineer", "Security Software Engineer".
    r"software\s+(developer|programmer)|"
    r"software\s+engineer(?!\s+(?:systems?|cloud|platform|security|network|infrastructure|it\b|asset|devops))|"
    r"(full[\s\-]?stack|front[\s\-]?end|back[\s\-]?end)\s+(developer|engineer)|"
    r"web\s+(developer|designer)|mobile\s+(developer|engineer)|"
    r"(android|ios|flutter|react\s+native)\s+developer|"
    # ── Consulting / management engagement roles ──────────────────────────────
    # "Engagement Manager" = management consulting role; "TMT" = sector label
    r"engagement\s+manager|"
    r"management\s+consultant(?!\s+it)|"   # IT management consulting is OK
    r"strategy\s+(manager|consultant|director)|"
    r"associate\s+(consultant|director)(?!\s+(it|technology|systems))|"
    # ── Blockchain / crypto dev (not IT support/ops) ─────────────────────────
    r"blockchain\s+(developer|engineer|architect|specialist)|"
    r"(software|senior|lead)\s+\w+\s+engineer,\s*blockchain|"  # "Software Engineer, Blockchain"
    r"smart\s+contract\s+developer|web3\s+(developer|engineer)|"
    # ── HR / recruitment ──────────────────────────────────────────────────────
    r"human\s+resources|hr\s+(manager|executive|specialist|officer|director)|"
    r"recruitment\s+(consultant|manager|executive)|recruiter|talent\s+acquisition|"
    # ── Aviation / aerospace ──────────────────────────────────────────────────
    r"aeronautical|aerospace\s+engineer(ing)?|"
    r"aviation\s+(manager|specialist|officer|coordinator|planner|operations)|"
    r"flight\s+(operations\s+specialist|dispatcher|planner|operations\s+officer)|"
    r"aircraft\s+(maintenance|systems|engineer|technician|avionics|structures|components|safety|performance)|"
    r"airline\s+(operations|coordinator|manager)|"
    r"avionics\s+(engineer|technician|specialist)|"
    # ── Healthcare / hospitality / transport ──────────────────────────────────
    r"nurse|nursing|doctor|physician|medical\s+(officer|representative)|pharmacist|"
    r"chef|cook|barista|waiter|waitress|driver|delivery\s+(driver|rider)|"
    # ── Supply chain / procurement / physical coordination ───────────────────
    r"procurement\s+(manager|officer)|supply\s+chain\s+(manager|coordinator)|"
    r"logistics\s+(coordinator|manager)|"
    r"packaging\s+(coordinator|specialist|engineer|technician|manager|operator)|"
    r"document\s+controller|"
    r"materials\s+(coordinator|controller|planner|handler|specialist)|"
    r"warehouse\s+(coordinator|supervisor|manager|operative)|"
    r"quality\s+inspector|"
    r"hse\s+(officer|engineer|manager|advisor)|health\s+safety\s+environment|"
    # ── Education / teaching ──────────────────────────────────────────────────
    r"teacher|teaching\s+assistant|lecturer|professor|tutor|"
    r"academic\s+(coordinator|advisor|director|dean)|"
    r"curriculum\s+(developer|specialist|coordinator)|"
    r"school\s+(principal|counselor|coordinator)|"
    r"early\s+childhood|nursery\s+teacher|"
    # ── Compliance / legal / financial crime ──────────────────────────────────
    r"compliance\s+(manager|officer|head|director|analyst)|"
    r"financial\s+crime|aml\s+(analyst|officer|manager)|anti[\s\-]money\s+laundering|"
    r"kyc\s+(analyst|officer|manager)|"
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
            # Core IT identifiers
            "it", "tech", "technical", "ict", "technology",
            # Role words  (no "analyst" — business/data/clinical analysts are not IT sysadmin)
            # (no "technician" — automotive/elevator technicians would pass via T4)
            "sysadmin", "admin", "administrator",
            "architect", "devops", "helpdesk", "support",
            # Infrastructure
            "system", "server", "network", "infrastructure", "database",
            "hardware", "software", "linux", "windows", "desktop",
            # Cloud & identity
            "cloud", "azure", "aws", "gcp", "hybrid",
            "identity", "access", "entra", "intune", "directory",
            # Collaboration & M365
            "exchange", "sharepoint", "teams", "collaboration", "workplace",
            # Endpoint management
            "endpoint", "autopilot", "mdm", "deployment",
            # Security (SOC = Security Operations Center, NOC = Network Ops Center)
            "cyber", "security", "firewall", "vpn", "compliance",
            "soc", "noc", "csirt", "gsoc",
            # Networking
            "cisco", "fortinet", "routing", "switching",
            # Backup & continuity
            "backup", "recovery", "veeam", "continuity",
            # Monitoring & operations
            "monitoring", "zabbix",
            # Automation & scripting
            "powershell", "scripting", "automation",
            # Virtualization
            "virtualization", "vmware", "hypervisor",
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
                if len(word) >= 2 and word not in _KEYWORD_WORD_BLOCKLIST:
                    self.keyword_words.add(word)

        self.cv_skill_words     = cv_skill_words       # from cv_skills CSV
        # Merge in IT-core terms so that roles like "SOC Analyst" / "NOC Engineer"
        # always pass T4, even when the user's CV-derived domain terms don't include
        # security-operations acronyms.
        # Also strip the same generic words that are blocked from T1/T2 — "senior",
        # "engineer", "specialist", etc. end up in cv_domain_terms when the CV analyzer
        # extracts words from job titles like "Senior IT Support Engineer".  Without this
        # strip, T4 would fire on "Senior BIM Engineer" via "senior" or "engineer".
        self.cv_domain_terms    = (cv_domain_terms - _KEYWORD_WORD_BLOCKLIST) | _IT_CORE_TERMS
        # Strip blocklist words from CV job-title words so that seniority/generic words
        # (e.g. "senior", "engineer", "specialist" from "Senior Onsite Engineer") cannot
        # accept non-IT titles via T2 alone.  IT roles are already caught by T1/T3/T4.
        self.cv_job_title_words = cv_job_title_words - _KEYWORD_WORD_BLOCKLIST

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

        # T5 — hard-reject FIRST, before any positive tier.
        # MUST run before T1/T2/T3 so a broad word like "engineer" or "technician"
        # in CV job-title words cannot rescue a non-IT role
        # (e.g. "Graduate Process Engineer" was passing T2 on "engineer").
        m = _HARD_REJECT.search(title_lower)
        if m:
            fragment = m.group(0)[:40].lower()
            return False, f"T5:hard_reject({fragment})"

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

        # T4 — CV domain-term catch-all
        # Strip generic role words (coordinator, controller, inspector, …) so that
        # a single vague word can't accept an unrelated role (e.g. "Packaging
        # Coordinator" matching only on "coordinator" from the user's CV titles).
        # A job must contain at least one genuinely IT-flavoured domain term.
        matches = title_words & self.cv_domain_terms
        real_matches = matches - _GENERIC_ROLE_WORDS
        if real_matches:
            sample = next(iter(real_matches))
            return True, f"T4:domain_term({sample})"

        # T_DESC — description contains a highly specific IT skill term.
        # Only activates when a non-empty description is supplied (enricher flow).
        # Catches roles where the title is ambiguous but the description is clearly IT.
        if description:
            desc_m = _SKILL_VOCAB_RE.search(description)
            if desc_m:
                return True, f"T_DESC:skill_vocab({desc_m.group(0)[:30].lower()})"

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
