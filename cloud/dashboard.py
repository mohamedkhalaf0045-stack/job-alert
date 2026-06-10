#!/usr/bin/env python3
"""
Job Alert — local monitoring & control dashboard.

A zero-dependency (stdlib-only) web app that gives real-time monitoring and
full control over the whole pipeline:

  • Process status   — local worker heartbeat, GitHub Actions cloud runs,
                       LinkedIn cookie health, Groq/Ollama config
  • Job stats        — totals by source/status, scored vs backlog, sent today
  • Live logs        — tails worker.log + enricher.log, auto-refreshing
  • Full control     — trigger a cloud scan, run the enricher (Groq backlog
                       clear), run a local scan, edit settings, mark jobs
                       applied/dismissed

Run:
    python cloud/dashboard.py            # opens http://127.0.0.1:8765
    python cloud/dashboard.py --port 9000 --no-browser

Binds to 127.0.0.1 only, so Supabase / GitHub credentials never leave the box.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD = ROOT / "cloud"

# ── Settings (read from the same settings.json the rest of the app uses) ──────

def _load_settings() -> dict:
    for p in (Path.home() / ".config" / "job-alert" / "settings.json",
              ROOT / "settings.json"):
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8-sig"))
            except Exception:
                pass
    return {}

S = _load_settings()
SUPABASE_URL = (os.environ.get("SUPABASE_URL") or S.get("SupabaseUrl", "")).rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or S.get("SupabaseKey", "")
GH_TOKEN     = os.environ.get("GH_TOKEN") or S.get("GitHubToken", "")
GH_REPO      = os.environ.get("GH_REPO") or S.get("GitHubRepo", "")

# ── Log file locations ────────────────────────────────────────────────────────
WORKER_LOG = ROOT / "worker.log"
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA")
_STATE_DIR = Path(_LOCALAPPDATA) / "JobAlert" if _LOCALAPPDATA else Path.home() / ".job-alert"
ENRICHER_LOG = _STATE_DIR / "enricher.log"
# Dashboard-launched subprocess logs (so we can tail jobs we start):
DASH_ENRICH_LOG = ROOT / "dashboard-enrich.log"
DASH_WORKER_LOG = ROOT / "dashboard-worker.log"

# Track subprocesses launched from the dashboard.
_PROCS: dict[str, subprocess.Popen] = {}
_PROCS_LOCK = threading.Lock()


# ── Supabase REST helpers (urllib, no supabase package) ───────────────────────

def _sb_headers(extra: dict | None = None) -> dict:
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def _sb_request(method: str, path: str, body=None, headers=None, timeout=12):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=_sb_headers(headers))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
        cr = resp.headers.get("content-range", "")
        parsed = json.loads(raw) if raw.strip() else []
        return parsed, cr


def sb_count(filter_q: str = "") -> int:
    """Exact row count for jobs matching filter_q (PostgREST query string)."""
    try:
        q = f"jobs?select=job_id&limit=1"
        if filter_q:
            q += "&" + filter_q
        _, cr = _sb_request("GET", q, headers={"Prefer": "count=exact",
                                               "Range-Unit": "items", "Range": "0-0"})
        if "/" in cr:
            tail = cr.split("/")[-1]
            return int(tail) if tail.isdigit() else 0
    except Exception:
        pass
    return 0


def get_config(key: str, default: str = "") -> str:
    try:
        rows, _ = _sb_request("GET", f"bot_state?key=eq.{urllib.parse.quote(key)}&select=value&limit=1")
        return rows[0]["value"] if rows else default
    except Exception:
        return default


def set_config(key: str, value: str) -> bool:
    try:
        _sb_request("POST", "bot_state", body={"key": key, "value": value},
                    headers={"Prefer": "resolution=merge-duplicates"})
        return True
    except Exception:
        return False


# ── GitHub Actions helpers ────────────────────────────────────────────────────

def gh_runs(limit: int = 8) -> list[dict]:
    if not (GH_TOKEN and GH_REPO):
        return []
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GH_REPO}/actions/runs?per_page={limit}",
            headers={"Authorization": f"Bearer {GH_TOKEN}",
                     "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=12) as r:
            runs = json.loads(r.read()).get("workflow_runs", [])
        out = []
        for run in runs:
            out.append({
                "name": run.get("name", ""),
                "status": run.get("status", ""),
                "conclusion": run.get("conclusion", ""),
                "created_at": run.get("created_at", ""),
                "url": run.get("html_url", ""),
                "event": run.get("event", ""),
            })
        return out
    except Exception:
        return []


def gh_dispatch(workflow: str = "job-alert.yml", ref: str = "main") -> tuple[bool, str]:
    if not (GH_TOKEN and GH_REPO):
        return False, "GitHub token/repo not configured"
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GH_REPO}/actions/workflows/{workflow}/dispatches",
            data=json.dumps({"ref": ref}).encode(), method="POST",
            headers={"Authorization": f"Bearer {GH_TOKEN}",
                     "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=12).read()
        return True, "Scan triggered on GitHub Actions"
    except Exception as exc:
        return False, f"Dispatch failed: {exc}"


# ── Log tail ──────────────────────────────────────────────────────────────────

def tail(path: Path, lines: int = 200, max_bytes: int = 96_000) -> str:
    try:
        if not path.exists():
            return f"(no log yet at {path})"
        size = path.stat().st_size
        with open(path, "rb") as fh:
            if size > max_bytes:
                fh.seek(-max_bytes, os.SEEK_END)
            data = fh.read().decode("utf-8", "replace")
        return "\n".join(data.splitlines()[-lines:])
    except Exception as exc:
        return f"(error reading {path}: {exc})"


# ── Status aggregation ────────────────────────────────────────────────────────

def _age_str(iso: str) -> str:
    if not iso:
        return "never"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        mins = (datetime.now(timezone.utc) - dt).total_seconds() / 60
        if mins < 1:   return "just now"
        if mins < 60:  return f"{int(mins)}m ago"
        if mins < 1440: return f"{mins/60:.1f}h ago"
        return f"{mins/1440:.1f}d ago"
    except Exception:
        return iso[:16]


def build_status() -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    last_run = get_config("worker_last_run", "")
    runs = gh_runs(6)
    last_cloud = runs[0] if runs else {}

    total      = sb_count()
    unscored   = sb_count("llm_score=is.null")
    scored     = total - unscored
    sent       = sb_count("telegram_sent_at=not.is.null")
    today_n    = sb_count(f"date_collected=gte.{today}T00:00:00Z")
    applied    = sb_count("status=eq.applied")
    dismissed  = sb_count("status=eq.dismissed")

    by_source = {}
    try:
        rows, _ = _sb_request("GET", "jobs?select=source&limit=2000&order=date_collected.desc")
        for r in rows:
            s = (r.get("source") or "?").split("/")[0]
            by_source[s] = by_source.get(s, 0) + 1
    except Exception:
        pass

    # worker health verdict
    healthy = True
    notes = []
    if last_run:
        try:
            dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
            gap_min = (datetime.now(timezone.utc) - dt).total_seconds() / 60
            if gap_min > 30:
                healthy = False
                notes.append(f"Worker last ran {int(gap_min)}m ago (>30m)")
        except Exception:
            pass
    streak = get_config("linkedin_zero_streak", "0")
    cookie_alerted = get_config("linkedin_cookie_alerted", "") == "true"
    if cookie_alerted:
        healthy = False
        notes.append("LinkedIn cookie likely expired")

    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "worker_last_run": last_run,
        "worker_last_run_age": _age_str(last_run),
        "healthy": healthy,
        "notes": notes,
        "cloud_run": {
            "name": last_cloud.get("name", ""),
            "status": last_cloud.get("status", ""),
            "conclusion": last_cloud.get("conclusion", ""),
            "age": _age_str(last_cloud.get("created_at", "")),
            "url": last_cloud.get("url", ""),
        },
        "runs": [{**r, "age": _age_str(r.get("created_at", ""))} for r in runs],
        "linkedin_zero_streak": streak,
        "linkedin_cookie_alerted": cookie_alerted,
        "stats": {
            "total": total, "scored": scored, "unscored": unscored,
            "sent": sent, "today": today_n, "applied": applied, "dismissed": dismissed,
        },
        "by_source": by_source,
        "groq": {
            "key_set": bool(get_config("setting_groq_api_key", "")),
            "prefer_cloud": get_config("setting_prefer_cloud", "") == "true",
            "model": get_config("setting_groq_model", "") or "llama-3.3-70b-versatile",
        },
        "procs": _proc_status(),
    }


def _proc_status() -> dict:
    out = {}
    with _PROCS_LOCK:
        for name, p in list(_PROCS.items()):
            rc = p.poll()
            out[name] = "running" if rc is None else f"done (exit {rc})"
    return out


# ── Subprocess launchers ──────────────────────────────────────────────────────

def _spawn(name: str, args: list[str], logfile: Path) -> tuple[bool, str]:
    with _PROCS_LOCK:
        existing = _PROCS.get(name)
        if existing and existing.poll() is None:
            return False, f"{name} is already running"
    try:
        logfile.write_text("", encoding="utf-8")  # truncate for this run
        fh = open(logfile, "a", encoding="utf-8")
        env = {**os.environ}
        p = subprocess.Popen([sys.executable, *args], cwd=str(ROOT),
                             stdout=fh, stderr=subprocess.STDOUT, env=env)
        with _PROCS_LOCK:
            _PROCS[name] = p
        return True, f"{name} started (pid {p.pid})"
    except Exception as exc:
        return False, f"Failed to start {name}: {exc}"


# ── HTTP handler ──────────────────────────────────────────────────────────────

# Only these settings may be written via the dashboard. Prevents an attacker
# (or a stray request) from overwriting sensitive secrets — Telegram token,
# LinkedIn cookie, API keys — through /api/settings.
_WRITABLE_SETTINGS = frozenset({
    "setting_keywords", "setting_location", "setting_max_hours",
    "setting_llm_min_score", "setting_prefer_cloud", "setting_blocked_domains",
    "setting_search_linkedin", "setting_search_indeed", "setting_search_web",
})


def _host_is_local(host_header: str, port: int) -> bool:
    """True only if the Host header points at this loopback server.

    Defends against DNS-rebinding / CSRF: a malicious web page can make the
    browser send requests to 127.0.0.1:port, but it cannot forge the Host
    header to a loopback name. Requests with any other Host are rejected.
    """
    host = (host_header or "").strip().lower()
    name = host.rsplit(":", 1)[0] if ":" in host else host
    return name in ("127.0.0.1", "localhost", "[::1]", "::1")


class Handler(BaseHTTPRequestHandler):
    server_version = "JobAlertDash/1.0"

    def log_message(self, *a):
        pass  # quiet

    def _guard(self) -> bool:
        """Reject non-loopback Host headers (DNS-rebinding / CSRF defense)."""
        port = self.server.server_address[1]
        if not _host_is_local(self.headers.get("Host", ""), port):
            self._send(403, b'{"error":"forbidden: non-local Host"}')
            return False
        return True

    def _send(self, code: int, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        # Block embedding / cross-origin reads as defense-in-depth.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode("utf-8"))

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    # ---- GET ----
    def do_GET(self):
        if not self._guard():
            return
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/":
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif u.path == "/api/status":
            self._json(build_status())
        elif u.path == "/api/logs":
            which = (q.get("which", ["worker"])[0])
            n = int(q.get("lines", ["250"])[0])
            path = {"worker": WORKER_LOG, "enricher": ENRICHER_LOG,
                    "dash_enrich": DASH_ENRICH_LOG, "dash_worker": DASH_WORKER_LOG}.get(which, WORKER_LOG)
            self._json({"which": which, "text": tail(path, n)})
        elif u.path == "/api/jobs":
            self._json(self._jobs(q))
        else:
            self._send(404, b'{"error":"not found"}')

    def _jobs(self, q) -> dict:
        filt = q.get("filter", ["all"])[0]
        limit = int(q.get("limit", ["40"])[0])
        clause = {"new": "&status=eq.new", "applied": "&status=eq.applied",
                  "dismissed": "&status=eq.dismissed", "saved": "&status=eq.saved",
                  "scored": "&llm_score=not.is.null", "unscored": "&llm_score=is.null"}.get(filt, "")
        try:
            rows, _ = _sb_request(
                "GET",
                f"jobs?select=job_id,title,company,location,url,source,status,llm_score,"
                f"date_collected,telegram_sent_at&order=date_collected.desc&limit={limit}{clause}")
            return {"jobs": rows}
        except Exception as exc:
            return {"jobs": [], "error": str(exc)}

    # ---- POST ----
    def do_POST(self):
        if not self._guard():
            return
        u = urllib.parse.urlparse(self.path)
        b = self._body()
        if u.path == "/api/scan":
            ok, msg = gh_dispatch("job-alert.yml")
            self._json({"ok": ok, "message": msg})
        elif u.path == "/api/enrich":
            try:
                limit = max(1, min(500, int(b.get("limit", 50))))   # clamp
            except (ValueError, TypeError):
                limit = 50
            args = ["cloud/enricher.py", "--limit", str(limit), "--prefer-cloud"]
            ok, msg = _spawn("enricher", args, DASH_ENRICH_LOG)
            self._json({"ok": ok, "message": msg})
        elif u.path == "/api/worker":
            ok, msg = _spawn("worker", ["cloud/worker.py"], DASH_WORKER_LOG)
            self._json({"ok": ok, "message": msg})
        elif u.path == "/api/settings":
            # Only allow known-safe keys — never let the dashboard overwrite the
            # Telegram token, LinkedIn cookie, or API keys.
            saved, rejected = [], []
            for key, val in (b or {}).items():
                if key in _WRITABLE_SETTINGS and set_config(key, str(val)):
                    saved.append(key)
                else:
                    rejected.append(key)
            self._json({"ok": True, "saved": saved, "rejected": rejected})
        elif u.path == "/api/job":
            jid = b.get("job_id", "")
            status = b.get("status", "")
            if status not in ("new", "applied", "dismissed", "saved"):
                self._json({"ok": False, "message": "invalid status"}, 400)
                return
            try:
                _sb_request("PATCH", f"jobs?job_id=eq.{urllib.parse.quote(jid)}",
                            body={"status": status})
                self._json({"ok": True})
            except Exception as exc:
                self._json({"ok": False, "message": str(exc)}, 500)
        else:
            self._send(404, b'{"error":"not found"}')


# ── Dashboard HTML (single page; polls the /api endpoints) ────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job Alert — Monitoring</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#e6edf3;padding:18px;font-size:14px}
  h1{font-size:1.3rem;font-weight:700;display:flex;align-items:center;gap:10px}
  h1 .dot{width:12px;height:12px;border-radius:50%;display:inline-block}
  .sub{color:#8b949e;font-size:.8rem;margin-top:3px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:18px 0}
  .card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:16px}
  .card h2{font-size:.72rem;text-transform:uppercase;letter-spacing:1px;color:#8b949e;margin-bottom:10px}
  .big{font-size:1.9rem;font-weight:700}
  .row{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #21262d}
  .row:last-child{border-bottom:0}
  .row .k{color:#8b949e}.row .v{font-weight:600}
  .ok{color:#3fb950}.warn{color:#d29922}.bad{color:#f85149}.mut{color:#8b949e}
  .btns{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}
  button{background:#21262d;border:1px solid #30363d;color:#e6edf3;border-radius:8px;padding:9px 14px;
         font-size:.85rem;cursor:pointer;font-weight:600}
  button:hover{background:#30363d}
  button.primary{background:#238636;border-color:#2ea043}button.primary:hover{background:#2ea043}
  button.amber{background:#9e6a03;border-color:#bb8009}button.amber:hover{background:#bb8009}
  .logwrap{display:flex;gap:8px;margin-bottom:8px}
  .tabbtn{padding:6px 12px;border-radius:6px}.tabbtn.active{background:#1f6feb;border-color:#1f6feb}
  pre{background:#010409;border:1px solid #30363d;border-radius:10px;padding:14px;height:340px;
      overflow:auto;font-family:'JetBrains Mono',Consolas,monospace;font-size:12px;line-height:1.5;white-space:pre-wrap}
  table{width:100%;border-collapse:collapse;font-size:.82rem}
  th{text-align:left;color:#8b949e;font-size:.7rem;text-transform:uppercase;padding:8px;border-bottom:1px solid #30363d}
  td{padding:8px;border-bottom:1px solid #21262d;vertical-align:top}
  tr:hover td{background:#1c2128}
  .badge{padding:2px 8px;border-radius:10px;font-size:.7rem;font-weight:700}
  .s-hi{background:#1a3d2b;color:#3fb950}.s-mid{background:#3d3a1a;color:#d29922}.s-lo{background:#3d1a1a;color:#f85149}.s-no{background:#21262d;color:#8b949e}
  a{color:#58a6ff;text-decoration:none}a:hover{text-decoration:underline}
  input,select{background:#0d1117;border:1px solid #30363d;color:#e6edf3;border-radius:6px;padding:7px;font-size:.82rem;width:100%}
  label{display:block;color:#8b949e;font-size:.72rem;margin:8px 0 3px}
  .toast{position:fixed;bottom:18px;right:18px;background:#1f6feb;color:#fff;padding:12px 18px;border-radius:8px;
         opacity:0;transition:.3s;font-weight:600}
  .toast.show{opacity:1}
  .src{display:inline-block;background:#21262d;border-radius:6px;padding:3px 9px;margin:3px;font-size:.78rem}
  .flex2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  details{margin-top:10px}summary{cursor:pointer;color:#8b949e;font-size:.8rem}
</style></head>
<body>
  <h1><span class="dot" id="health-dot"></span>Job Alert — Monitoring &amp; Control</h1>
  <div class="sub" id="subline">loading…</div>

  <div class="btns">
    <button class="primary" onclick="act('/api/scan',{})">▶ Trigger Cloud Scan</button>
    <button class="amber" onclick="enrich()">🤖 Run Enricher (clear backlog)</button>
    <button onclick="act('/api/worker',{})">🖥️ Run Local Scan</button>
    <button onclick="loadAll()">↻ Refresh</button>
    <label style="display:inline-flex;align-items:center;gap:6px;margin:0">
      <input type="checkbox" id="auto" checked style="width:auto"> auto-refresh
    </label>
  </div>

  <div class="grid">
    <div class="card"><h2>Worker Health</h2>
      <div class="big" id="health-text">—</div>
      <div class="sub" id="health-notes"></div>
      <div class="row"><span class="k">Last run</span><span class="v" id="wk-last">—</span></div>
      <div class="row"><span class="k">Cloud run</span><span class="v" id="cloud-run">—</span></div>
      <div class="row"><span class="k">LinkedIn cookie</span><span class="v" id="cookie">—</span></div>
    </div>
    <div class="card"><h2>Jobs</h2>
      <div class="big" id="st-total">—</div><div class="sub">total in database</div>
      <div class="row"><span class="k">Collected today</span><span class="v" id="st-today">—</span></div>
      <div class="row"><span class="k">Scored / backlog</span><span class="v" id="st-scored">—</span></div>
      <div class="row"><span class="k">Sent to Telegram</span><span class="v" id="st-sent">—</span></div>
      <div class="row"><span class="k">Applied / dismissed</span><span class="v" id="st-appdis">—</span></div>
    </div>
    <div class="card"><h2>AI Scoring</h2>
      <div class="row"><span class="k">Groq key</span><span class="v" id="groq-key">—</span></div>
      <div class="row"><span class="k">Prefer cloud</span><span class="v" id="groq-prefer">—</span></div>
      <div class="row"><span class="k">Model</span><span class="v mut" id="groq-model">—</span></div>
      <div class="row"><span class="k">Enricher</span><span class="v" id="proc-enricher">idle</span></div>
      <div class="row"><span class="k">Backlog</span><span class="v" id="backlog">—</span></div>
    </div>
    <div class="card"><h2>Sources</h2>
      <div id="sources">—</div>
    </div>
  </div>

  <div class="card">
    <h2>Live Logs</h2>
    <div class="logwrap">
      <button class="tabbtn active" data-log="worker" onclick="setLog('worker')">Cloud/Local worker.log</button>
      <button class="tabbtn" data-log="enricher" onclick="setLog('enricher')">enricher.log</button>
      <button class="tabbtn" data-log="dash_enrich" onclick="setLog('dash_enrich')">dashboard enrich run</button>
    </div>
    <pre id="log">loading…</pre>
  </div>

  <div class="grid" style="margin-top:14px">
    <div class="card">
      <h2>Recent Cloud Runs</h2>
      <table><tbody id="runs"></tbody></table>
    </div>
    <div class="card">
      <h2>Settings (saved to Supabase)</h2>
      <div class="flex2">
        <div><label>Min AI score</label><input id="set-min" type="number" min="1" max="10"></div>
        <div><label>Max hours</label><input id="set-hours" type="number"></div>
      </div>
      <label>Keywords (comma-separated)</label>
      <input id="set-kw">
      <label>Prefer cloud scoring (Groq)</label>
      <select id="set-prefer"><option value="true">true</option><option value="false">false</option></select>
      <div class="btns"><button class="primary" onclick="saveSettings()">💾 Save Settings</button></div>
    </div>
  </div>

  <div class="card" style="margin-top:14px">
    <h2>Jobs <select id="job-filter" onchange="loadJobs()" style="width:auto;display:inline-block;margin-left:8px">
      <option value="all">All</option><option value="new">New</option><option value="scored">Scored</option>
      <option value="unscored">Unscored (backlog)</option><option value="applied">Applied</option>
      <option value="dismissed">Dismissed</option></select></h2>
    <table><thead><tr><th>Score</th><th>Title</th><th>Company</th><th>Source</th><th>When</th><th>Sent</th><th></th></tr></thead>
    <tbody id="jobs"></tbody></table>
  </div>

  <div class="toast" id="toast"></div>

<script>
let curLog='worker';
function toast(m){const t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2600);}
async function act(url,body){try{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const j=await r.json();toast(j.message||(j.ok?'Done':'Failed'));setTimeout(loadAll,1200);}catch(e){toast('Error: '+e);}}
function enrich(){const n=prompt('How many backlog jobs to score via Groq?','50');if(n)act('/api/enrich',{limit:parseInt(n)});}
function scoreBadge(s){if(s===null||s===undefined)return '<span class="badge s-no">—</span>';const c=s>=7?'s-hi':s>=5?'s-mid':'s-lo';return '<span class="badge '+c+'">'+s+'</span>';}
async function loadStatus(){
  try{const s=await (await fetch('/api/status')).json();
   const dot=document.getElementById('health-dot');
   dot.style.background=s.healthy?'#3fb950':'#f85149';
   document.getElementById('health-text').innerHTML=s.healthy?'<span class="ok">● Healthy</span>':'<span class="bad">● Attention</span>';
   document.getElementById('health-notes').textContent=(s.notes||[]).join(' · ');
   document.getElementById('subline').textContent='Updated '+s.now;
   document.getElementById('wk-last').textContent=s.worker_last_run_age;
   const cr=s.cloud_run||{};
   document.getElementById('cloud-run').innerHTML=(cr.conclusion||cr.status||'—')+' · '+(cr.age||'');
   document.getElementById('cookie').innerHTML=s.linkedin_cookie_alerted?'<span class="bad">expired?</span>':'<span class="ok">ok</span> (streak '+s.linkedin_zero_streak+')';
   const st=s.stats;
   document.getElementById('st-total').textContent=st.total;
   document.getElementById('st-today').textContent=st.today;
   document.getElementById('st-scored').textContent=st.scored+' / '+st.unscored;
   document.getElementById('st-sent').textContent=st.sent;
   document.getElementById('st-appdis').textContent=st.applied+' / '+st.dismissed;
   document.getElementById('backlog').innerHTML=st.unscored>0?'<span class="warn">'+st.unscored+' unscored</span>':'<span class="ok">clear</span>';
   document.getElementById('groq-key').innerHTML=s.groq.key_set?'<span class="ok">set</span>':'<span class="bad">missing</span>';
   document.getElementById('groq-prefer').innerHTML=s.groq.prefer_cloud?'<span class="ok">on</span>':'<span class="mut">off</span>';
   document.getElementById('groq-model').textContent=s.groq.model;
   document.getElementById('proc-enricher').textContent=(s.procs&&s.procs.enricher)||'idle';
   document.getElementById('sources').innerHTML=Object.entries(s.by_source||{}).sort((a,b)=>b[1]-a[1]).map(([k,v])=>'<span class="src">'+k+' <b>'+v+'</b></span>').join('')||'—';
   document.getElementById('runs').innerHTML=(s.runs||[]).map(r=>{const c=r.conclusion==='success'?'ok':r.conclusion==='failure'?'bad':'mut';return '<tr><td><a href="'+r.url+'" target="_blank">'+(r.name||'run')+'</a></td><td class="'+c+'">'+(r.conclusion||r.status)+'</td><td class="mut">'+r.age+'</td></tr>';}).join('');
  }catch(e){document.getElementById('subline').textContent='status error: '+e;}
}
async function loadLog(){try{const j=await (await fetch('/api/logs?which='+curLog+'&lines=300')).json();const pre=document.getElementById('log');const atBottom=pre.scrollTop+pre.clientHeight>=pre.scrollHeight-40;pre.textContent=j.text;if(atBottom)pre.scrollTop=pre.scrollHeight;}catch(e){}}
function setLog(w){curLog=w;document.querySelectorAll('.tabbtn').forEach(b=>b.classList.toggle('active',b.dataset.log===w));loadLog();}
async function loadJobs(){const f=document.getElementById('job-filter').value;try{const j=await (await fetch('/api/jobs?filter='+f+'&limit=50')).json();
  document.getElementById('jobs').innerHTML=(j.jobs||[]).map(x=>{
   const when=(x.date_collected||'').slice(5,16).replace('T',' ');
   const sent=x.telegram_sent_at?'<span class="ok">✓</span>':'<span class="mut">—</span>';
   return '<tr><td>'+scoreBadge(x.llm_score)+'</td><td><a href="'+(x.url||'#')+'" target="_blank">'+(x.title||'')+'</a></td><td class="mut">'+(x.company||'')+'</td><td class="mut">'+((x.source||'').split('/')[0])+'</td><td class="mut">'+when+'</td><td>'+sent+'</td>'+
   '<td><button onclick="mark(\''+x.job_id+'\',\'applied\')">✓</button> <button onclick="mark(\''+x.job_id+'\',\'dismissed\')">✕</button></td></tr>';
  }).join('')||'<tr><td colspan=7 class="mut">no jobs</td></tr>';}catch(e){}}
async function mark(id,st){await fetch('/api/job',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:id,status:st})});toast('Marked '+st);loadJobs();loadStatus();}
async function saveSettings(){const body={setting_llm_min_score:document.getElementById('set-min').value,setting_max_hours:document.getElementById('set-hours').value,setting_prefer_cloud:document.getElementById('set-prefer').value};const kw=document.getElementById('set-kw').value.trim();if(kw)body.setting_keywords=kw;await act('/api/settings',body);}
async function primeSettings(){try{const s=await (await fetch('/api/status')).json();document.getElementById('set-prefer').value=s.groq.prefer_cloud?'true':'false';}catch(e){}}
function loadAll(){loadStatus();loadLog();loadJobs();}
loadAll();primeSettings();
setInterval(()=>{if(document.getElementById('auto').checked){loadStatus();loadLog();}},4000);
</script>
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description="Job Alert monitoring dashboard")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if not (SUPABASE_URL and SUPABASE_KEY):
        print("WARNING: Supabase URL/key not found in settings.json — stats will be empty.")

    addr = ("127.0.0.1", args.port)
    httpd = ThreadingHTTPServer(addr, Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Job Alert dashboard running at {url}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        httpd.shutdown()


if __name__ == "__main__":
    main()
