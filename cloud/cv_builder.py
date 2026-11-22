"""
Tailored CV builder: one PDF per job, in the owner's chosen design.

Master CV
    Structured JSON kept in the private Supabase table `cv_master`
    (RLS on, no policies: only the service_role key can read it). Personal
    data never goes into this public repo. Schema:

    {
      "name": "...", "headline": "...", "contact": ["City", "+971 ...", ...],
      "contact_extra": "UAE Residence",
      "summary": "...",
      "skills": [{"category": "Cloud & Identity", "items": ["Microsoft 365", ...]}],
      "experience": [{"title": "...", "company": "...", "dates": "...",
                      "note_top": "", "bullets": ["..."], "note_bottom": ""}],
      "education": [{"degree": "...", "school": "...", "details": ["..."]}],
      "certifications": ["..."], "strengths": ["..."], "languages": "..."
    }

Tailoring (Groq)
    The model only chooses an ORDER for skill groups, skill items, bullets and
    certificates (by index), and may rewrite the headline and summary. Nothing
    is ever dropped or added. A rewritten headline/summary is rejected if it
    contains any number that is not already in the master CV, so the AI cannot
    invent metrics, years or certificates.

Rendering
    HTML + CSS that recreates the design (navy name and section rules, bold
    skill categories, title left / dates right), printed to A4 PDF with
    Playwright's Chromium.
"""

from __future__ import annotations

import copy
import html
import json
import re

# ── Master CV storage ──────────────────────────────────────────────────────────

MASTER_TABLE = "cv_master"
MASTER_ID = "default"


def load_master(supabase_url: str, service_key: str, cv_id: str = MASTER_ID) -> dict | None:
    """Read the master CV JSON (needs the service_role key)."""
    import requests

    if not supabase_url or not service_key:
        return None
    try:
        resp = requests.get(
            f"{supabase_url}/rest/v1/{MASTER_TABLE}",
            params={"id": f"eq.{cv_id}", "select": "data"},
            headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
            timeout=15,
        )
        rows = resp.json() if resp.ok else []
        if rows:
            data = rows[0].get("data")
            return json.loads(data) if isinstance(data, str) else data
    except Exception:
        pass
    return None


# ── Tailoring ──────────────────────────────────────────────────────────────────

def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", (text or "").replace(",", "")))


def _full_order(order, n: int) -> list[int]:
    """Valid, de-duplicated indices from the model, then any it left out."""
    seen: list[int] = []
    for i in order or []:
        try:
            i = int(i)
        except (TypeError, ValueError):
            continue
        if 0 <= i < n and i not in seen:
            seen.append(i)
    return seen + [i for i in range(n) if i not in seen]


def _safe_text(new: str, fallback: str, master_numbers: set[str], max_len: int) -> str:
    new = (new or "").strip()
    if not new or len(new) > max_len:
        return fallback
    if not _numbers(new) <= master_numbers:      # invented a number → reject
        return fallback
    return new


def apply_tailoring(master: dict, plan: dict) -> dict:
    """Return a copy of the master CV reordered/rewritten per the model plan."""
    cv = copy.deepcopy(master)
    plan = plan or {}
    master_numbers = _numbers(json.dumps(master, ensure_ascii=False))

    cv["headline"] = _safe_text(plan.get("headline"), master.get("headline", ""),
                                master_numbers, 160)
    cv["summary"] = _safe_text(plan.get("summary"), master.get("summary", ""),
                               master_numbers, 1200)

    skills = master.get("skills") or []
    order = _full_order(plan.get("skill_order"), len(skills))
    item_orders = plan.get("skill_items") or {}
    new_skills = []
    for ci in order:
        group = copy.deepcopy(skills[ci])
        items = group.get("items") or []
        io = _full_order(item_orders.get(str(ci)) or item_orders.get(ci), len(items))
        group["items"] = [items[i] for i in io]
        new_skills.append(group)
    cv["skills"] = new_skills

    bullet_orders = plan.get("bullet_order") or {}
    for ei, exp in enumerate(cv.get("experience") or []):
        bullets = master["experience"][ei].get("bullets") or []
        bo = _full_order(bullet_orders.get(str(ei)) or bullet_orders.get(ei), len(bullets))
        exp["bullets"] = [bullets[i] for i in bo]

    certs = master.get("certifications") or []
    co = _full_order(plan.get("cert_order"), len(certs))
    cv["certifications"] = [certs[i] for i in co]
    return cv


def build_tailor_prompt(master: dict, job: dict, description: str) -> str:
    skills = "\n".join(
        f"[{ci}] {g.get('category')}: " + "; ".join(f"({ii}) {it}" for ii, it in enumerate(g.get("items") or []))
        for ci, g in enumerate(master.get("skills") or []))
    exp = "\n".join(
        f"EXPERIENCE [{ei}] {e.get('title')} @ {e.get('company')}\n" +
        "\n".join(f"  ({bi}) {b}" for bi, b in enumerate(e.get("bullets") or []))
        for ei, e in enumerate(master.get("experience") or []))
    certs = "\n".join(f"({i}) {c}" for i, c in enumerate(master.get("certifications") or []))
    return (
        "You tailor a CV to one job. You may ONLY reorder existing items by index and "
        "rewrite the headline and summary. Do not add skills, tools, employers, numbers, "
        "years or certificates that are not already in the CV. Keep every fact true.\n\n"
        f"JOB: {job.get('job_title') or job.get('title', '')} at {job.get('company', '')}\n"
        f"JOB DESCRIPTION:\n{(description or '')[:3500]}\n\n"
        f"CURRENT HEADLINE: {master.get('headline', '')}\n"
        f"CURRENT SUMMARY: {master.get('summary', '')}\n\n"
        f"SKILL GROUPS (group index, item indexes):\n{skills}\n\n{exp}\n\n"
        f"CERTIFICATIONS:\n{certs}\n\n"
        "Return JSON only:\n"
        '{"headline": "same style as current, job-relevant terms first, max 140 chars",\n'
        ' "summary": "3-5 sentences, most relevant experience for this job first, only facts from the CV",\n'
        ' "skill_order": [group indexes, most relevant first],\n'
        ' "skill_items": {"<group index>": [item indexes, most relevant first]},\n'
        ' "bullet_order": {"<experience index>": [bullet indexes, most relevant first]},\n'
        ' "cert_order": [certificate indexes, most relevant first]}'
    )


def tailor(master: dict, job: dict, description: str, groq_key: str,
           timeout: int = 60) -> tuple[dict, bool]:
    """(tailored CV, True) or (master CV, False) when Groq is unavailable."""
    if not groq_key or not master:
        return copy.deepcopy(master), False
    import requests

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
            json={"model": "openai/gpt-oss-120b", "temperature": 0.2,
                  "messages": [{"role": "user",
                                "content": build_tailor_prompt(master, job, description)}]},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return copy.deepcopy(master), False
        text = resp.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", text, re.S)
        plan = json.loads(m.group(0)) if m else {}
    except Exception:
        return copy.deepcopy(master), False
    return apply_tailoring(master, plan), True


# ── Rendering ──────────────────────────────────────────────────────────────────

_CSS = """
@page { size: A4; margin: 14mm 15mm 14mm 15mm; }
* { box-sizing: border-box; }
body { font-family: Arial, "Liberation Sans", Helvetica, sans-serif; color: #111;
       font-size: 9.3pt; line-height: 1.22; margin: 0; }
.name { text-align: center; color: #1f3864; font-size: 21pt; font-weight: 700;
        letter-spacing: .3px; margin: 0; text-transform: uppercase; }
.headline, .contact { text-align: center; color: #555; margin: 1px 0; }
.headline { font-size: 10pt; }
.contact { font-size: 9pt; }
h2 { color: #2b4a7a; font-size: 10.8pt; font-weight: 700; text-transform: uppercase;
     border-bottom: 1px solid #2b4a7a; margin: 10px 0 4px; padding-bottom: 2px;
     page-break-after: avoid; }
p { margin: 0; text-align: left; }
ul { margin: 2px 0 0; padding-left: 15px; }
li { margin: 0 0 1px; }
.job { margin-top: 5px; page-break-inside: auto; }
.row { display: flex; justify-content: space-between; font-weight: 700; page-break-after: avoid; }
.org { color: #555; padding-left: 4px; page-break-after: avoid; }
.note { font-style: italic; color: #333; }
b { font-weight: 700; }
"""


def _e(text) -> str:
    return html.escape(str(text or ""))


def render_html(cv: dict) -> str:
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><style>{_CSS}</style></head><body>"]
    parts.append(f"<h1 class='name'>{_e(cv.get('name'))}</h1>")
    if cv.get("headline"):
        parts.append(f"<div class='headline'>{_e(cv['headline'])}</div>")
    if cv.get("contact"):
        parts.append(f"<div class='contact'>{' | '.join(_e(c) for c in cv['contact'])}</div>")
    if cv.get("contact_extra"):
        parts.append(f"<div class='contact'>{_e(cv['contact_extra'])}</div>")

    if cv.get("summary"):
        parts.append(f"<h2>Professional Summary</h2><p>{_e(cv['summary'])}</p>")

    if cv.get("skills"):
        parts.append("<h2>Core Technical Skills</h2><ul>")
        for g in cv["skills"]:
            parts.append(f"<li><b>{_e(g.get('category'))}:</b> "
                         f"{_e(', '.join(g.get('items') or []))}</li>")
        parts.append("</ul>")

    if cv.get("experience"):
        parts.append("<h2>Professional Experience</h2>")
        for x in cv["experience"]:
            parts.append("<div class='job'>")
            parts.append(f"<div class='row'><span>{_e(x.get('title'))}</span>"
                         f"<span>{_e(x.get('dates'))}</span></div>")
            org = " | ".join(p for p in [x.get("company"), x.get("location")] if p)
            if org:
                parts.append(f"<div class='org'>{_e(org)}</div>")
            if x.get("note_top"):
                parts.append(f"<div class='note'>{_e(x['note_top'])}</div>")
            if x.get("bullets"):
                parts.append("<ul>" + "".join(f"<li>{_e(b)}</li>" for b in x["bullets"]) + "</ul>")
            if x.get("note_bottom"):
                parts.append(f"<div class='note'>{_e(x['note_bottom'])}</div>")
            parts.append("</div>")

    if cv.get("education"):
        parts.append("<h2>Education</h2>")
        for ed in cv["education"]:
            school = f" | {_e(ed.get('school'))}" if ed.get("school") else ""
            parts.append(f"<p><b>{_e(ed.get('degree'))}</b>{school}</p>")
            if ed.get("details"):
                parts.append("<ul>" + "".join(f"<li>{_e(d)}</li>" for d in ed["details"]) + "</ul>")

    for key, title in [("certifications", "Licenses &amp; Certifications"),
                       ("strengths", "Key Strengths")]:
        if cv.get(key):
            parts.append(f"<h2>{title}</h2><ul>" +
                         "".join(f"<li>{_e(i)}</li>" for i in cv[key]) + "</ul>")
    if cv.get("languages"):
        parts.append(f"<h2>Languages</h2><p>{_e(cv['languages'])}</p>")
    parts.append("</body></html>")
    return "".join(parts)


async def render_pdf(cv: dict, out_path: str, browser=None) -> str:
    """Print the CV to an A4 PDF. Reuses `browser` if given."""
    from playwright.async_api import async_playwright

    async def _print(b):
        page = await b.new_page()
        await page.set_content(render_html(cv), wait_until="load")
        await page.pdf(path=out_path, format="A4", print_background=True,
                       margin={"top": "14mm", "bottom": "14mm", "left": "15mm", "right": "15mm"})
        await page.close()

    if browser is not None:
        await _print(browser)
    else:
        async with async_playwright() as pw:
            b = await pw.chromium.launch(args=["--no-sandbox"])
            try:
                await _print(b)
            finally:
                await b.close()
    return out_path


def file_name(cv: dict, job: dict) -> str:
    """e.g. Mohamed_Khalaf_CV_YAS_Projects.pdf (LinkedIn shows this name)."""
    def slug(s: str) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "_", s or "").strip("_")
    name = slug(" ".join((cv.get("name") or "CV").split()[:2]).title())
    company = slug(job.get("company", ""))[:30]
    return f"{name}_CV{'_' + company if company else ''}.pdf"
