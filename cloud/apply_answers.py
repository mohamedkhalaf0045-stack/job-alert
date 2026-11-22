"""
Answer engine for Easy Apply forms.

Given one question from an application form (its label, field type and the
options it offers), find the answer to type or pick. Three sources, in order:

  1. Custom answers the user saved for that exact question (from the app's
     "Saved answers" screen, or added after an earlier run asked for them).
  2. Built-in rules that map common questions (phone, notice period, salary,
     years of experience, visa, relocation, languages, degree ...) to the
     user's saved answer bank.
  3. Groq AI, using the CV profile and the job. Only used when the AI says it
     is confident and, for choice fields, only when it picks a listed option.

Anything still unanswered is reported back to the app as a question for the
user instead of being guessed, so the executor never submits invented data.

Pure functions only (no browser, no network except ask_groq) so they can be
unit-tested without LinkedIn.
"""

from __future__ import annotations

import json
import re
from typing import Iterable

# ── Normalising ────────────────────────────────────────────────────────────────

_STOP = {
    "a", "an", "the", "of", "to", "in", "for", "with", "and", "or", "you", "your",
    "do", "does", "are", "is", "be", "have", "has", "what", "how", "many",
    "please", "this", "that", "on", "at", "as", "if", "any", "can", "will",
}


def normalize(text: str) -> str:
    """Lower-case, drop punctuation/asterisks and squeeze spaces."""
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9؀-ۿ+ ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in normalize(text).split() if t not in _STOP}


def similarity(a: str, b: str) -> float:
    """Token overlap (Jaccard) between two questions, 0..1."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ── Answer bank ────────────────────────────────────────────────────────────────

def build_bank(answers: dict) -> dict:
    """Flatten an apply request's answers into one {bank_key: value} dict.

    Accepts the original payload sections (personal / experience / screening /
    open_text) and the newer 'bank' section from the Saved answers screen.
    Empty values are dropped so they never get typed into a form.
    """
    answers = answers or {}
    personal = answers.get("personal") or {}
    experience = answers.get("experience") or {}
    screening = answers.get("screening") or {}
    open_text = answers.get("open_text") or {}

    bank = {
        "full_name": personal.get("full_name"),
        "first_name": None,
        "last_name": None,
        "email": personal.get("email"),
        "phone": personal.get("phone"),
        "city": personal.get("city"),
        "years": experience.get("years"),
        "current_title": experience.get("current_title"),
        "skills": experience.get("skills"),
        "authorized_to_work": screening.get("authorized_to_work"),
        "requires_sponsorship": screening.get("requires_sponsorship"),
        "notice_period": screening.get("notice_period"),
        "expected_salary": screening.get("expected_salary"),
        "why_interested": open_text.get("why_interested"),
    }
    full = (bank.get("full_name") or "").strip()
    if full:
        parts = full.split()
        bank["first_name"] = parts[0]
        bank["last_name"] = parts[-1] if len(parts) > 1 else None

    # Saved answers from the app fill whatever this application's own form
    # left empty (answers edited on the apply screen win).
    for key, value in (answers.get("bank") or {}).items():
        if not str(bank.get(key) or "").strip():
            bank[key] = value

    clean = {}
    for key, value in bank.items():
        if value is None:
            continue
        value = str(value).strip()
        if value:
            clean[key] = value
    return clean


def custom_pairs(answers: dict) -> list[tuple[str, str]]:
    """Saved question → answer pairs ([{"q":..,"a":..}] in the request)."""
    pairs = []
    for item in (answers or {}).get("custom") or []:
        q = str((item or {}).get("q") or "").strip()
        a = str((item or {}).get("a") or "").strip()
        if q and a:
            pairs.append((q, a))
    return pairs


# ── Rules for common questions ─────────────────────────────────────────────────
# (bank_key, regex on the normalised label). First match wins, so the more
# specific patterns come first.

RULES: list[tuple[str, str]] = [
    ("expected_salary", r"\b(expected|desired|asking)\b.*\b(salary|compensation|pay|ctc)\b"
                        r"|\b(salary|compensation|ctc)\b.*\b(expect|expectation|desired)"),
    ("current_salary",  r"\b(current|present|last)\b.*\b(salary|compensation|ctc|pay)\b"),
    ("expected_salary", r"\bsalary\b|\bcompensation\b|\bctc\b"),
    ("notice_period",   r"\bnotice\b|\bhow soon\b|\bstart date\b|\bearliest\b.*\b(start|join)\b"
                        r"|\bavailab\w*\b.*\b(start|join)\b|\bwhen can you (start|join)\b"),
    ("requires_sponsorship", r"\bsponsor"),
    ("authorized_to_work", r"\b(authori[sz]ed|eligible|legally|right) to work\b|\bwork (permit|authori[sz]ation)\b"),
    ("visa_status",     r"\bvisa\b|\bresidency\b|\bresidence permit\b"),
    ("nationality",     r"\bnationality\b|\bcitizenship\b"),
    ("relocate",        r"\brelocat"),
    ("driving_license", r"\bdriv\w* licen[cs]e\b|\bdriving\b"),
    ("english_level",   r"\benglish\b"),
    ("arabic_level",    r"\barabic\b"),
    ("degree",          r"\bdegree\b|\bbachelor\b|\beducation\b|\bqualification\b"),
    ("linkedin_url",    r"\blinkedin\b"),
    ("portfolio_url",   r"\b(website|portfolio|github)\b"),
    ("gender",          r"\bgender\b"),
    ("years",           r"\byears?\b.*\bexperience\b|\bexperience\b.*\byears?\b"),
    ("phone",           r"\bphone\b|\bmobile\b|\bcontact number\b"),
    ("email",           r"\bemail\b"),
    ("first_name",      r"\bfirst name\b|\bgiven name\b"),
    ("last_name",       r"\blast name\b|\bsurname\b|\bfamily name\b"),
    ("full_name",       r"\bfull name\b|^name$"),
    ("city",            r"\bcity\b|\blocation\b|\bwhere .* (based|located|live)\b"),
    ("current_title",   r"\b(current|recent)\b.*\b(title|position|role)\b"),
    ("why_interested",  r"\bwhy\b.*\b(interest|apply|join|company|role|position)\b|\bcover letter\b"),
    ("skills",          r"\bskills?\b|\bsummar"),
]
_RULES = [(key, re.compile(pat)) for key, pat in RULES]

_YES = {"yes", "y", "true", "1"}
_NO = {"no", "n", "false", "0"}


def rule_key(question: str) -> str | None:
    """Which answer-bank key a question asks for, or None."""
    q = normalize(question)
    for key, pattern in _RULES:
        if pattern.search(q):
            return key
    return None


def _first_number(text: str) -> str | None:
    m = re.search(r"\d+(?:\.\d+)?", (text or "").replace(",", ""))
    return m.group(0) if m else None


def choose_option(answer: str, options: Iterable[str]) -> str | None:
    """Pick the listed option that best matches an answer, or None."""
    options = [o for o in options if normalize(o) and normalize(o) not in
               {"select an option", "select", "choose", "please select"}]
    if not options or not answer:
        return None
    norm = normalize(answer)
    for opt in options:                      # exact
        if normalize(opt) == norm:
            return opt
    if norm in _YES or norm in _NO:          # yes / no
        want = _YES if norm in _YES else _NO
        for opt in options:
            if normalize(opt).split()[:1] and normalize(opt).split()[0] in want:
                return opt
        return None
    for opt in options:                      # one contains the other
        no = normalize(opt)
        if norm in no or no in norm:
            return opt
    num = _first_number(answer)              # numeric ranges like "3-5 years"
    if num is not None:
        val = float(num)
        for opt in options:
            nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", opt.replace(",", ""))]
            if len(nums) >= 2 and nums[0] <= val <= nums[1]:
                return opt
            if len(nums) == 1 and re.search(r"\+|more|above|over", opt.lower()) and val >= nums[0]:
                return opt
            if len(nums) == 1 and re.search(r"less|under|below", opt.lower()) and val < nums[0]:
                return opt
    best, best_score = None, 0.0
    for opt in options:                      # closest wording
        score = similarity(answer, opt)
        if score > best_score:
            best, best_score = opt, score
    return best if best_score >= 0.5 else None


def answer_for(question: str, field_type: str, options: list[str],
               bank: dict, custom: list[tuple[str, str]]) -> tuple[str | None, str]:
    """Answer one form question from saved data.

    field_type: "text" | "number" | "textarea" | "select" | "radio" | "checkbox".
    Returns (answer, source) where source is "custom", "rule" or "" when the
    question could not be answered (answer is None then).
    """
    options = options or []

    # 1. Saved answer for this exact (or near-identical) question.
    best_a, best_s = None, 0.0
    for q, a in custom:
        s = 1.0 if normalize(q) == normalize(question) else similarity(q, question)
        if s > best_s:
            best_a, best_s = a, s
    if best_a is not None and best_s >= 0.8:
        value = best_a
        if field_type in ("select", "radio"):
            value = choose_option(best_a, options)
        if value:
            return value, "custom"

    # 2. Built-in rule → answer bank.
    key = rule_key(question)
    value = bank.get(key) if key else None
    if value is None:
        return None, ""

    if key == "years":
        value = _first_number(value) or value
    if field_type == "number":
        value = _first_number(value)
        if value is None:
            return None, ""
    if field_type in ("select", "radio"):
        value = choose_option(value, options)
        if value is None:
            return None, ""
    return value, "rule"


# ── Groq fallback ──────────────────────────────────────────────────────────────

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"


def build_prompt(question: str, field_type: str, options: list[str],
                 profile: str, job: dict) -> str:
    opts = "\n".join(f"- {o}" for o in options) if options else "(free text)"
    return (
        "You fill in one question of a job application for the candidate.\n"
        "Answer ONLY from the candidate profile. Never invent employers, "
        "degrees, certificates, numbers or personal facts that are not in it.\n"
        "If the profile does not contain the answer, set confident to false.\n\n"
        f"CANDIDATE PROFILE:\n{profile[:3000]}\n\n"
        f"JOB: {job.get('job_title', '')} at {job.get('company', '')}\n\n"
        f"QUESTION: {question}\n"
        f"FIELD TYPE: {field_type}\n"
        f"OPTIONS:\n{opts}\n\n"
        "Rules: for a choice field the answer must be copied exactly from OPTIONS. "
        "For a number field answer with digits only. Keep text answers under 60 words, "
        "first person, professional.\n"
        'Reply with JSON only: {"answer": "...", "confident": true|false}'
    )


def parse_llm_reply(text: str, field_type: str, options: list[str]) -> str | None:
    """Validate the model's JSON reply; None when unusable or not confident."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not data.get("confident"):
        return None
    answer = str(data.get("answer") or "").strip()
    if not answer:
        return None
    if field_type in ("select", "radio"):
        return choose_option(answer, options)
    if field_type == "number":
        return _first_number(answer)
    return answer


def ask_groq(question: str, field_type: str, options: list[str], profile: str,
             job: dict, api_key: str, timeout: int = 30) -> str | None:
    """Ask Groq for an answer. Returns None on any failure or low confidence."""
    if not api_key or not profile:
        return None
    import requests

    try:
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "temperature": 0.1,
                "messages": [{"role": "user", "content":
                              build_prompt(question, field_type, options, profile, job)}],
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            return None
        text = resp.json()["choices"][0]["message"]["content"]
    except Exception:
        return None
    return parse_llm_reply(text, field_type, options)
