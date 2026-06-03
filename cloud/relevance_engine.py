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
    "desk",         # "Housekeeping Desk", "Front Desk", "Reception Desk" — from the
                    # "IT Help Desk" keyword. Genuine IT desk roles are caught by the
                    # _IT_TITLE_PHRASES check below ("help desk"/"service desk") and
                    # by "helpdesk"/"it"/"support".
})


# ── IT-specific title phrases (positive multi-word signal) ────────────────────
#
# Multi-word phrases that are unambiguously IT even when no single keyword word
# matches.  Checked as an ACCEPT tier right after T5.  This rescues genuine
# service-desk / help-desk roles that lost their standalone "desk" T1 match when
# "desk" was added to the blocklist — without re-admitting "Housekeeping Desk",
# "Front Desk", "Reception Desk" (none of which contain these compounds).

_IT_TITLE_PHRASES = re.compile(
    r"\b("
    r"help\s*desk|service\s*desk|support\s*desk|it\s*desk|"
    r"service\s+desk\s+analyst|desktop\s+support"
    r")\b",
    re.I,
)


# ── Position-name (phrase) matching ───────────────────────────────────────────
#
# The title gate matches FULL POSITION NAMES, not single words.  A title
# qualifies only when it contains ALL the significant words of at least one
# position phrase — so "desk" alone never matches, but "IT Help Desk",
# "Service Desk", "System Administrator" etc. do.  This replaces the old
# word-by-word T1–T4 tiers that let "Housekeeping Desk" through on "desk".

# Seniority / level tokens are dropped from phrase requirements — they are not
# field indicators and would otherwise over-constrain (e.g. requiring "senior").
_SENIORITY_NOISE = frozenset({
    "senior", "junior", "lead", "sr", "jr", "mid", "principal", "staff",
    "level", "l1", "l2", "l3", "i", "ii", "iii", "trainee", "intern", "graduate",
})

# Normalise singular/plural and common variants so "Systems"≈"System",
# "Admin"≈"Administrator", etc.  Applied to both keyword phrases and job titles.
_TOKEN_NORMALIZE = {
    "systems": "system",
    "admin": "administrator", "admins": "administrator", "administrators": "administrator",
    "engineers": "engineer", "engineering": "engineer",
    "networks": "network", "networking": "network",
    "technologies": "technology",
    "specialists": "specialist",
    "analysts": "analyst",
    "technicians": "technician",
    "operations": "operation",
    "services": "service",
}

# A few single tokens that stand for a two-word position — expanded on the title
# side so e.g. "Sysadmin" satisfies the "system administrator" phrase.
_TOKEN_EXPAND = {
    "sysadmin": ("system", "administrator"),
    "helpdesk": ("help", "desk"),
    "m365": ("microsoft", "365"),
    "o365": ("microsoft", "365"),
}

# Built-in canonical IT-support / sysadmin / infrastructure position names.
# These give good recall (so "Network Administrator", "Cloud Engineer", etc. are
# caught even if not in the user's keyword list) while staying strictly
# position-based — never single generic words.
_BUILTIN_POSITIONS: tuple[str, ...] = (
    "it support", "it support engineer", "it support specialist", "it support technician",
    "it support analyst", "it technician", "it administrator", "it engineer",
    "it officer", "it analyst", "it coordinator", "it executive",
    "it help desk", "help desk", "service desk", "desktop support", "technical support",
    "technical support engineer", "technical support specialist",
    "system administrator", "system engineer", "systems engineer",
    "network administrator", "network engineer", "network security",
    "security administrator", "security engineer", "security analyst",
    "soc analyst", "noc engineer", "information security",
    "cloud administrator", "cloud engineer", "cloud architect",
    "infrastructure engineer", "infrastructure administrator", "infrastructure specialist",
    "devops engineer", "windows administrator", "linux administrator",
    "server administrator", "database administrator",
    "endpoint engineer", "endpoint administrator", "endpoint management",
    "microsoft 365", "microsoft 365 administrator", "azure administrator", "azure engineer",
    "identity engineer", "collaboration engineer",
    "workplace technology", "digital workplace", "end user computing", "end user support",
    "it manager", "it support manager", "infrastructure manager",
    # IT specialist / officer / support variants (also reached by the
    # "Information Technology" -> "it" normalization, e.g. "Information
    # Technology Officer" -> {it, officer}).
    "it specialist", "it officer", "it support officer", "it operations",
    "it security", "it infrastructure", "it systems",
    # Computer / desktop / user support (e.g. "Remote Computer User Support").
    "computer support", "user support", "computer operator", "computer technician",
    # Architect roles (design-level IT positions).
    "it architect", "solution architect", "solutions architect", "systems architect",
    "infrastructure architect", "security architect", "azure architect",
    "enterprise architect", "data architect", "network architect",
)


def _phrase_token_set(text: str) -> frozenset[str]:
    """Return the set of significant, normalised tokens for a phrase or title.

    Drops stopwords + seniority/level noise; normalises plurals/variants;
    expands single tokens that stand for two words (sysadmin → system+administrator).
    Also folds "Information Technology" / "Info Tech" → the token "it" so spelled-out
    titles ("Information Technology Officer") match the same positions as "IT" ones.
    """
    low = text.lower()
    low = re.sub(r"\binformation\s+technology\b", " it ", low)
    low = re.sub(r"\binfo(?:rmation)?\s*tech\b", " it ", low)
    out: set[str] = set()
    for raw in re.split(r"\W+", low):
        tok = re.sub(r"[^a-z0-9+#]", "", raw)
        if not tok or tok in _STOPWORDS or tok in _SENIORITY_NOISE:
            continue
        if tok in _TOKEN_EXPAND:
            out.update(_TOKEN_EXPAND[tok])
            continue
        out.add(_TOKEN_NORMALIZE.get(tok, tok))
    return frozenset(out)


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
    # ── Hospitality / hotel (not IT) ──────────────────────────────────────────
    # Must precede the T1P "service desk" phrase check — a hotel "Guest Service
    # Desk" is hospitality, not an IT service desk.
    r"housekeeping|concierge|valet|bell\s*(boy|man|hop)|room\s+service|butler|hostess|"
    r"guest\s+(service|services|relation|relations|experience)|"
    r"front\s+desk\s+(agent|associate|receptionist|clerk|coordinator|supervisor|manager)|"
    r"front\s+office\s+(agent|associate|coordinator|supervisor|manager)|"
    r"reservations?\s+(agent|officer|executive|coordinator)|cabin\s+crew|"
    r"spa\s+(therapist|receptionist)|"
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
        cv_job_titles: list[str] | None = None,
    ) -> None:
        # Raw CV job-title strings (e.g. ["IT Systems Administrator", "Senior Onsite Engineer"])
        # used to derive position phrases.  Optional — empty when not supplied.
        self._cv_titles_raw: list[str] = list(cv_job_titles or [])
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

        # ── Position phrases (the title gate) ─────────────────────────────────
        # A title matches only when it contains ALL significant words of one of
        # these phrases.  Built from: the user's keyword/position list + the
        # built-in canonical IT positions + the user's own CV job titles.
        # Single-word phrases (e.g. bare "IT") are kept but flagged so we don't
        # accept a job on one generic word alone unless it's a genuine IT token.
        # Every phrase must have >= 2 significant words — a job is NEVER accepted
        # on a single generic word (the user's explicit rule: "not word by word").
        # A bare keyword like "IT" therefore contributes no phrase; "IT X" roles
        # are still covered by the 2-word built-in positions ("it support", etc.).
        phrases: set[frozenset[str]] = set()
        for src in list(keywords) + list(_BUILTIN_POSITIONS) + list(self._cv_titles_raw):
            ts = _phrase_token_set(src)
            if len(ts) >= 2:
                phrases.add(ts)
        self.position_phrases: list[frozenset[str]] = sorted(phrases, key=len)

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
        cv_job_titles_list = [t.strip() for t in cv_titles_csv.split(",") if t.strip()]

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

        engine = cls(keywords, cv_skill_words, cv_domain_terms, cv_job_title_words,
                     cv_job_titles=cv_job_titles_list)

        # Log summary for GitHub Actions visibility
        print(
            f"[RelevanceEngine] Loaded: {len(cv_skill_words)} skill-word(s), "
            f"{len(cv_job_title_words)} title-word(s), "
            f"{len(cv_domain_terms)} domain-term(s), "
            f"{len(engine.keyword_words)} keyword-word(s), "
            f"{len(engine.position_phrases)} position-phrase(s)",
            flush=True,
        )
        return engine

    def is_relevant(self, title: str, description: str = "") -> tuple[bool, str]:
        """Classify a single job by TITLE (position-name match), not word-by-word.

        Pipeline:
            T5     hard-reject — clearly non-IT / non-target role        → REJECT
            POS    title contains ALL words of a position phrase          → ACCEPT
            T_DESC (only with description) IT skill vocab in description   → ACCEPT
            --     no position phrase matched                             → REJECT

        The POS tier replaces the old word-by-word T1–T4 tiers: a single generic
        word ("desk", "cloud", "security") can no longer accept a job — the title
        must match a whole position name.  Description-vs-CV fit is judged
        separately by the enricher's LLM reasoning step.

        Returns (is_relevant, reason_str).
        """
        title_lower = title.lower()

        # T5 — hard-reject FIRST (sales, hospitality, civil eng, etc.).
        m = _HARD_REJECT.search(title_lower)
        if m:
            fragment = m.group(0)[:40].lower()
            return False, f"T5:hard_reject({fragment})"

        # T1P — IT-specific compound phrase (help desk / service desk / desktop support).
        pm = _IT_TITLE_PHRASES.search(title_lower)
        if pm:
            return True, f"T1P:it_phrase({pm.group(0).strip()})"

        # POS — full position-name match: every significant word of at least one
        # position phrase must be present in the title (order-independent).
        title_tokens = _phrase_token_set(title)
        if title_tokens:
            for phrase in self.position_phrases:
                if phrase <= title_tokens:
                    return True, f"POS:position({' '.join(sorted(phrase))})"

        # T_DESC — title didn't match a position, but the DESCRIPTION clearly shows
        # IT work (Intune, SCCM, Fortinet, …).  Only when a description is supplied.
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
