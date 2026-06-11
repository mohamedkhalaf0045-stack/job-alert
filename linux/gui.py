#!/usr/bin/env python3
"""
Job Alert — Linux GUI
Tkinter-based desktop app for Ubuntu/Linux.
Replaces the Windows PowerShell GUI (linkedin-job-alert.ps1).

Requirements (all standard or one pip install):
    tkinter     — ships with Python on Ubuntu
    requests    — pip install requests

Usage:
    python3 linux/gui.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from tkinter import (
    BooleanVar, IntVar, StringVar,
    filedialog, messagebox, scrolledtext
)
import tkinter as tk
from tkinter import ttk

try:
    import requests
except ImportError:
    print("ERROR: 'requests' not installed. Run: pip install requests")
    sys.exit(1)

# ──────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────
_REPO_ROOT   = Path(__file__).resolve().parent.parent
_CLOUD_DIR   = _REPO_ROOT / "cloud"
_CONFIG_DIR  = Path.home() / ".config" / "job-alert"
_LOG_DIR     = Path.home() / ".local" / "share" / "job-alert"
_SETTINGS_FILE = _CONFIG_DIR / "settings.json"
_ENV_FILE      = _CONFIG_DIR / "settings.env"
_LOG_FILE      = _LOG_DIR / "job-alert.log"

# Keys to sync from settings.json → Supabase bot_state
# SECURITY: credentials (LinkedIn cookie, Telegram token/chat id) are
# deliberately NOT in this map. bot_state is readable with the public anon
# key that ships in the mobile app, so anything synced here is
# world-readable. Cloud workers read secrets from GitHub Actions Secrets;
# local workers read settings.json / .env.
_SUPABASE_SETTING_MAP = {
    "Keywords":         "setting_keywords",       # comma-joined list
    "Location":         "setting_location",
    "CustomHours":      "setting_max_hours",
    "MinAiScore":       "setting_llm_min_score",
    "OllamaUrl":        "setting_ollama_url",
    "SearchLinkedIn":   "setting_search_linkedin",
    "SearchIndeed":     "setting_search_indeed",
    "ExcludeKeywords":  "setting_exclude_keywords",
}

# Default settings (same structure as Windows settings.json)
_DEFAULTS: dict = {
    "SupabaseUrl":      "",
    "SupabaseKey":      "",
    "TelegramBotToken": "",
    "TelegramChatId":   "",
    "LinkedInCookie":   "",
    "Keywords":         ["IT Support", "IT Helpdesk", "System Administrator"],
    "Location":         "United Arab Emirates",
    "CustomHours":      72,
    "MinAiScore":       5,
    "OllamaUrl":        "http://localhost:11434",
    "SearchLinkedIn":   True,
    "SearchIndeed":     False,
    "ExcludeKeywords":  "intern,fresh",
    "HideAppliedJobs":  True,
    "AutoEnrich":       True,
    "UserProfile":      "",
}


# ──────────────────────────────────────────────────────────────
# Settings helpers
# ──────────────────────────────────────────────────────────────
def load_settings() -> dict:
    """Load settings from ~/.config/job-alert/settings.json (or project root fallback)."""
    for candidate in [_SETTINGS_FILE, _REPO_ROOT / "settings.json"]:
        if candidate.exists():
            try:
                with open(candidate, encoding="utf-8") as f:
                    data = json.load(f)
                merged = dict(_DEFAULTS)
                merged.update(data)
                return merged
            except Exception:
                pass
    return dict(_DEFAULTS)


def save_settings_local(settings: dict) -> None:
    """Write settings to ~/.config/job-alert/settings.json and settings.env."""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=4)

    # Also write settings.env for systemd EnvironmentFile
    with open(_ENV_FILE, "w", encoding="utf-8") as f:
        f.write(f'SUPABASE_URL={settings.get("SupabaseUrl", "")}\n')
        f.write(f'SUPABASE_KEY={settings.get("SupabaseKey", "")}\n')
        f.write(f'TELEGRAM_BOT_TOKEN={settings.get("TelegramBotToken", "")}\n')
        f.write(f'TELEGRAM_CHAT_ID={settings.get("TelegramChatId", "")}\n')
        kw = settings.get("Keywords", [])
        if isinstance(kw, list):
            kw = ",".join(kw)
        f.write(f'KEYWORDS={kw}\n')
        f.write(f'LOCATION={settings.get("Location", "")}\n')


def push_settings_to_supabase(settings: dict) -> tuple[bool, str]:
    """Push settings to Supabase bot_state table. Returns (success, message)."""
    url = settings.get("SupabaseUrl", "").strip()
    key = settings.get("SupabaseKey", "").strip()
    if not url or not key:
        return False, "Supabase URL and Key are required."

    headers = {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
        "Prefer":        "resolution=merge-duplicates",
    }
    api_url = f"{url.rstrip('/')}/rest/v1/bot_state"

    rows = []
    for local_key, supa_key in _SUPABASE_SETTING_MAP.items():
        val = settings.get(local_key, "")
        if isinstance(val, list):
            val = ",".join(str(v) for v in val)
        elif isinstance(val, bool):
            val = "true" if val else "false"
        else:
            val = str(val)
        rows.append({"key": supa_key, "value": val})

    try:
        resp = requests.post(api_url, headers=headers, json=rows, timeout=15)
        if resp.status_code in (200, 201):
            return True, f"Saved {len(rows)} settings to Supabase."
        return False, f"Supabase error {resp.status_code}: {resp.text[:200]}"
    except Exception as exc:
        return False, f"Connection error: {exc}"


def fetch_jobs_from_supabase(settings: dict, status_filter: str = "all",
                              limit: int = 200) -> tuple[list[dict], str]:
    """Fetch jobs from Supabase jobs table. Returns (rows, error_message)."""
    url = settings.get("SupabaseUrl", "").strip()
    key = settings.get("SupabaseKey", "").strip()
    if not url or not key:
        return [], "Supabase URL/Key not configured. Go to Settings tab."

    headers = {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
    }
    params = {
        "select": "job_id,title,company,location,url,llm_score,status,date_collected,source",
        "order":  "date_collected.desc",
        "limit":  str(limit),
    }
    if status_filter and status_filter != "all":
        params["status"] = f"eq.{status_filter}"

    try:
        resp = requests.get(
            f"{url.rstrip('/')}/rest/v1/jobs",
            headers=headers, params=params, timeout=15,
        )
        if resp.status_code == 200:
            return resp.json(), ""
        return [], f"Supabase error {resp.status_code}: {resp.text[:200]}"
    except Exception as exc:
        return [], f"Connection error: {exc}"


def update_job_status_supabase(settings: dict, job_id: str, status: str) -> bool:
    """Update a job's status in Supabase."""
    url = settings.get("SupabaseUrl", "").strip()
    key = settings.get("SupabaseKey", "").strip()
    if not url or not key:
        return False
    headers = {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
    }
    try:
        resp = requests.patch(
            f"{url.rstrip('/')}/rest/v1/jobs?job_id=eq.{job_id}",
            headers=headers,
            json={"status": status},
            timeout=10,
        )
        return resp.status_code in (200, 204)
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────
# Main application
# ──────────────────────────────────────────────────────────────
class JobAlertApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Job Alert")
        self.geometry("1000x700")
        self.minsize(800, 550)
        self._settings: dict = load_settings()
        self._running_proc: subprocess.Popen | None = None
        self._log_tail_active = False
        self._job_rows: list[dict] = []
        self._build_ui()
        self._tail_log_async()
        self.after(200, self._reload_jobs_async)   # load jobs shortly after startup

    # ─── UI construction ──────────────────────────────────────

    def _build_ui(self) -> None:
        # Top bar
        top = tk.Frame(self, bg="#1a1a2e", height=46)
        top.pack(fill="x")
        tk.Label(
            top, text="  📋 Job Alert", font=("Sans", 14, "bold"),
            bg="#1a1a2e", fg="white",
        ).pack(side="left", pady=8)

        # Notebook (tabs)
        style = ttk.Style(self)
        style.configure("TNotebook.Tab", padding=[10, 5])
        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill="both", expand=True, padx=0, pady=0)

        self._settings_frame = ttk.Frame(self._notebook)
        self._jobs_frame     = ttk.Frame(self._notebook)
        self._log_frame      = ttk.Frame(self._notebook)

        self._notebook.add(self._settings_frame, text="⚙  Settings")
        self._notebook.add(self._jobs_frame,     text="💼  Jobs")
        self._notebook.add(self._log_frame,      text="📋  Log")

        self._build_settings_tab(self._settings_frame)
        self._build_jobs_tab(self._jobs_frame)
        self._build_log_tab(self._log_frame)

        # Bottom toolbar
        toolbar = tk.Frame(self, bg="#2d2d44", height=52)
        toolbar.pack(fill="x", side="bottom")
        toolbar.pack_propagate(False)

        btn_style = {"bg": "#4a90d9", "fg": "white", "relief": "flat",
                     "font": ("Sans", 10, "bold"), "padx": 14, "pady": 6,
                     "cursor": "hand2", "bd": 0}

        self._btn_scan = tk.Button(toolbar, text="▶  Scan Now",
                                   command=self._scan_now, **btn_style)
        self._btn_scan.pack(side="left", padx=(12, 4), pady=10)

        btn2 = dict(btn_style); btn2["bg"] = "#7b5ea7"
        self._btn_enrich = tk.Button(toolbar, text="🤖  Run Enricher",
                                     command=self._run_enricher, **btn2)
        self._btn_enrich.pack(side="left", padx=4, pady=10)

        btn3 = dict(btn_style); btn3["bg"] = "#4caf50"
        self._btn_cv = tk.Button(toolbar, text="📄  Analyze CV",
                                 command=self._analyze_cv, **btn3)
        self._btn_cv.pack(side="left", padx=4, pady=10)

        btn4 = dict(btn_style); btn4["bg"] = "#e53935"
        self._btn_stop = tk.Button(toolbar, text="⏹  Stop",
                                   command=self._stop_process, **btn4)
        self._btn_stop.pack(side="left", padx=4, pady=10)
        self._btn_stop.config(state="disabled")

        self._status_var = StringVar(value="Idle")
        tk.Label(
            toolbar, textvariable=self._status_var,
            bg="#2d2d44", fg="#aaaacc", font=("Sans", 9),
        ).pack(side="right", padx=16)

    # ─── Settings tab ─────────────────────────────────────────

    def _build_settings_tab(self, parent: ttk.Frame) -> None:
        canvas = tk.Canvas(parent, borderwidth=0, highlightthickness=0)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_resize(evt):
            canvas.itemconfig(win_id, width=evt.width)
        canvas.bind("<Configure>", _on_resize)

        def _on_frame_configure(_evt):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_frame_configure)

        # Mousewheel scroll
        def _on_mousewheel(evt):
            canvas.yview_scroll(int(-1 * (evt.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # Build fields
        self._sv: dict[str, StringVar | BooleanVar | IntVar] = {}
        s = self._settings

        def section(label: str) -> None:
            ttk.Separator(inner, orient="horizontal").pack(fill="x", pady=(16, 2), padx=20)
            tk.Label(inner, text=label, font=("Sans", 10, "bold"),
                     fg="#4a90d9").pack(anchor="w", padx=20)

        def field(label: str, key: str, show: str = "", wide: bool = False,
                  tooltip: str = "") -> None:
            row = ttk.Frame(inner)
            row.pack(fill="x", padx=20, pady=3)
            tk.Label(row, text=label, width=20, anchor="w",
                     font=("Sans", 9)).pack(side="left")
            sv = StringVar(value=str(s.get(key, "")))
            self._sv[key] = sv
            w = 80 if wide else 50
            entry = ttk.Entry(row, textvariable=sv, show=show, width=w)
            entry.pack(side="left", fill="x", expand=True)
            if tooltip:
                self._add_tooltip(entry, tooltip)

        def check_field(label: str, key: str) -> None:
            row = ttk.Frame(inner)
            row.pack(fill="x", padx=20, pady=2)
            bv = BooleanVar(value=bool(s.get(key, False)))
            self._sv[key] = bv
            ttk.Checkbutton(row, text=label, variable=bv).pack(side="left")

        # ── Supabase ──
        section("☁  Supabase")
        field("Supabase URL", "SupabaseUrl", wide=True,
              tooltip="From Supabase dashboard → Project Settings → API")
        field("Supabase Key", "SupabaseKey", show="*", wide=True,
              tooltip="The 'anon public' key from Supabase API settings")

        # ── Telegram ──
        section("📱  Telegram")
        field("Bot Token", "TelegramBotToken", show="*",
              tooltip="From @BotFather — looks like: 1234567890:AAG...")
        field("Chat ID",   "TelegramChatId",
              tooltip="Your numeric chat ID — get it from @userinfobot")

        # ── LinkedIn ──
        section("🔗  LinkedIn")
        field("Cookie (li_at)", "LinkedInCookie", wide=True,
              tooltip="Open LinkedIn in browser → F12 → Application → Cookies → li_at value")

        # ── Search settings ──
        section("🔍  Search Settings")
        field("Keywords (comma-separated)", "Keywords", wide=True,
              tooltip='e.g. "IT Support,System Administrator,IT Helpdesk"')
        field("Location", "Location",
              tooltip='e.g. "United Arab Emirates" or "Dubai"')
        field("Max Job Age (hours)", "CustomHours",
              tooltip="Jobs older than this are ignored. Default: 72")
        field("Min AI Score (1–10)", "MinAiScore",
              tooltip="Only notify via Telegram if score ≥ this value. Default: 5")
        field("Exclude Keywords", "ExcludeKeywords",
              tooltip='Comma-separated words that auto-dismiss matching jobs: "intern,fresh"')
        check_field("Search LinkedIn",   "SearchLinkedIn")
        check_field("Search Indeed",     "SearchIndeed")
        check_field("Hide Applied Jobs", "HideAppliedJobs")
        check_field("Auto-run Enricher", "AutoEnrich")

        # ── AI (Ollama) ──
        section("🤖  AI Scoring (Ollama)")
        field("Ollama URL", "OllamaUrl",
              tooltip="Default: http://localhost:11434 — run `ollama serve` first")
        field("CV PDF Path", "UserProfile", wide=True,
              tooltip="Path to your CV PDF for analysis (click Browse below)")

        # CV browse button
        def _browse_cv():
            path = filedialog.askopenfilename(
                title="Select CV PDF",
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            )
            if path:
                self._sv["UserProfile"].set(path)

        ttk.Button(inner, text="📂  Browse CV…", command=_browse_cv).pack(
            anchor="w", padx=20, pady=(0, 8))

        # Save button
        ttk.Separator(inner, orient="horizontal").pack(fill="x", pady=(16, 8), padx=20)

        btn_row = ttk.Frame(inner)
        btn_row.pack(fill="x", padx=20, pady=(0, 20))
        ttk.Button(btn_row, text="💾  Save & Sync to Cloud",
                   command=self._save_settings).pack(side="left")
        self._save_status = StringVar()
        tk.Label(btn_row, textvariable=self._save_status,
                 fg="green", font=("Sans", 9)).pack(side="left", padx=12)

    def _add_tooltip(self, widget: tk.Widget, text: str) -> None:
        tip = None

        def enter(_):
            nonlocal tip
            x = widget.winfo_rootx() + 20
            y = widget.winfo_rooty() + widget.winfo_height() + 4
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x}+{y}")
            tk.Label(
                tip, text=text, background="#ffffe0", relief="solid",
                borderwidth=1, font=("Sans", 8), wraplength=320, justify="left",
            ).pack()

        def leave(_):
            nonlocal tip
            if tip:
                tip.destroy()
                tip = None

        widget.bind("<Enter>", enter)
        widget.bind("<Leave>", leave)

    def _save_settings(self) -> None:
        # Collect values from StringVars
        s = dict(self._settings)
        for key, var in self._sv.items():
            val = var.get()
            if key == "Keywords":
                s[key] = [k.strip() for k in str(val).split(",") if k.strip()]
            elif key in ("CustomHours", "MinAiScore"):
                try:
                    s[key] = int(val)
                except ValueError:
                    s[key] = _DEFAULTS.get(key, 0)
            elif isinstance(var, BooleanVar):
                s[key] = bool(val)
            else:
                s[key] = str(val).strip()

        self._settings = s

        # Write local file + env file
        try:
            save_settings_local(s)
        except Exception as exc:
            messagebox.showerror("Save Error", f"Could not write settings file:\n{exc}")
            return

        # Push to Supabase in background
        self._save_status.set("Saving…")
        self.update_idletasks()

        def _push():
            ok, msg = push_settings_to_supabase(s)
            self.after(0, lambda: self._save_status.set(
                "✓ Saved & synced to cloud!" if ok else f"Local saved. Supabase: {msg}"
            ))
            self.after(5000, lambda: self._save_status.set(""))

        threading.Thread(target=_push, daemon=True).start()

    # ─── Jobs tab ─────────────────────────────────────────────

    def _build_jobs_tab(self, parent: ttk.Frame) -> None:
        # Filter bar
        bar = ttk.Frame(parent)
        bar.pack(fill="x", padx=8, pady=6)

        tk.Label(bar, text="Show:").pack(side="left")
        self._filter_var = StringVar(value="all")
        filters = [("All", "all"), ("New", "new"), ("Applied", "applied"),
                   ("Dismissed", "dismissed")]
        for label, val in filters:
            ttk.Radiobutton(
                bar, text=label, variable=self._filter_var, value=val,
                command=self._reload_jobs_async,
            ).pack(side="left", padx=4)

        ttk.Button(bar, text="🔄 Refresh", command=self._reload_jobs_async).pack(
            side="right", padx=4)

        # Table
        cols = ("title", "company", "score", "source", "date", "status")
        self._tree = ttk.Treeview(parent, columns=cols, show="headings",
                                  selectmode="browse")
        for col, width, anchor in [
            ("title",   380, "w"),
            ("company", 180, "w"),
            ("score",    60, "center"),
            ("source",   90, "center"),
            ("date",    120, "center"),
            ("status",   90, "center"),
        ]:
            self._tree.heading(col, text=col.title())
            self._tree.column(col, width=width, anchor=anchor, stretch=(col == "title"))

        vsb = ttk.Scrollbar(parent, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        vsb.pack(side="right", fill="y", pady=(0, 8), padx=(0, 4))

        # Double-click to open URL
        self._tree.bind("<Double-1>", self._open_job_url)

        # Action row below table
        act = ttk.Frame(parent)
        act.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(act, text="✅ Mark Applied",
                   command=lambda: self._set_job_status("applied")).pack(side="left", padx=4)
        ttk.Button(act, text="❌ Dismiss",
                   command=lambda: self._set_job_status("dismissed")).pack(side="left", padx=4)
        ttk.Button(act, text="🔗 Open in Browser",
                   command=self._open_selected_job).pack(side="left", padx=4)

        self._jobs_status_var = StringVar(value="")
        tk.Label(act, textvariable=self._jobs_status_var,
                 fg="#777", font=("Sans", 9)).pack(side="right", padx=8)

    def _reload_jobs_async(self) -> None:
        self._jobs_status_var.set("Loading…")

        def _fetch():
            filt = self._filter_var.get()
            rows, err = fetch_jobs_from_supabase(self._settings, status_filter=filt)
            self.after(0, lambda: self._populate_jobs_table(rows, err))

        threading.Thread(target=_fetch, daemon=True).start()

    def _populate_jobs_table(self, rows: list[dict], err: str) -> None:
        self._tree.delete(*self._tree.get_children())
        self._job_rows = rows

        if err:
            self._jobs_status_var.set(f"Error: {err}")
            return

        for row in rows:
            score = row.get("llm_score", "")
            date_raw = row.get("date_collected", "")
            date_short = date_raw[:10] if date_raw else ""
            status = row.get("status", "") or "new"

            # Colour-code rows by status
            tag = status
            self._tree.insert(
                "", "end",
                iid=row.get("job_id", ""),
                values=(
                    row.get("title", ""),
                    row.get("company", ""),
                    f"{score}/10" if score else "—",
                    row.get("source", ""),
                    date_short,
                    status,
                ),
                tags=(tag,),
            )

        self._tree.tag_configure("applied",   foreground="#4caf50")
        self._tree.tag_configure("dismissed", foreground="#aaaaaa")
        self._tree.tag_configure("new",       foreground="#ffffff")

        self._jobs_status_var.set(f"{len(rows)} job(s) loaded")

    def _open_job_url(self, _event) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        job_id = sel[0]
        for row in self._job_rows:
            if row.get("job_id") == job_id:
                url = row.get("url", "")
                if url:
                    webbrowser.open(url)
                return

    def _open_selected_job(self) -> None:
        self._open_job_url(None)

    def _set_job_status(self, new_status: str) -> None:
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Please select a job first.")
            return
        job_id = sel[0]

        def _update():
            ok = update_job_status_supabase(self._settings, job_id, new_status)
            self.after(0, lambda: (
                self._jobs_status_var.set(
                    f"✓ Marked as {new_status}" if ok else "Failed to update status"
                ),
                self._reload_jobs_async(),
            ))

        threading.Thread(target=_update, daemon=True).start()

    # ─── Log tab ──────────────────────────────────────────────

    def _build_log_tab(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent)
        bar.pack(fill="x", padx=8, pady=6)
        tk.Label(bar, text="Live log output", font=("Sans", 9)).pack(side="left")
        ttk.Button(bar, text="🗑 Clear",
                   command=self._clear_log).pack(side="right", padx=4)
        ttk.Button(bar, text="📂 Open Log File",
                   command=self._open_log_file).pack(side="right", padx=4)

        self._log_text = scrolledtext.ScrolledText(
            parent, wrap="word", font=("Monospace", 9),
            bg="#0d1117", fg="#c9d1d9", insertbackground="white",
            state="disabled",
        )
        self._log_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _append_log(self, text: str) -> None:
        self._log_text.config(state="normal")
        self._log_text.insert("end", text)
        self._log_text.see("end")
        self._log_text.config(state="disabled")

    def _clear_log(self) -> None:
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")

    def _open_log_file(self) -> None:
        if _LOG_FILE.exists():
            webbrowser.open(_LOG_FILE.as_uri())
        else:
            messagebox.showinfo("No log file", f"Log file not found:\n{_LOG_FILE}")

    def _tail_log_async(self) -> None:
        """Tail the log file in a background thread."""
        def _run():
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            _LOG_FILE.touch(exist_ok=True)
            with open(_LOG_FILE, encoding="utf-8", errors="replace") as f:
                f.seek(0, 2)   # go to end
                while True:
                    line = f.readline()
                    if line:
                        self.after(0, lambda l=line: self._append_log(l))
                    else:
                        import time; time.sleep(0.4)

        threading.Thread(target=_run, daemon=True).start()

    # ─── Process runner ───────────────────────────────────────

    def _run_cloud_cmd(self, cmd: list[str], label: str) -> None:
        """Run a cloud/*.py script in a background thread, streaming to Log tab."""
        if self._running_proc and self._running_proc.poll() is None:
            messagebox.showwarning("Busy", "A process is already running. Stop it first.")
            return

        self._notebook.select(self._log_frame)
        self._append_log(f"\n{'─'*60}\n[{_ts()}] ▶ {label}\n{'─'*60}\n")
        self._set_status(f"Running: {label}")
        self._btn_scan.config(state="disabled")
        self._btn_enrich.config(state="disabled")
        self._btn_cv.config(state="disabled")
        self._btn_stop.config(state="normal")

        # Build env for subprocess: inject Supabase + Telegram creds
        env = os.environ.copy()
        env["SUPABASE_URL"]        = self._settings.get("SupabaseUrl", "")
        env["SUPABASE_KEY"]        = self._settings.get("SupabaseKey", "")
        env["TELEGRAM_BOT_TOKEN"]  = self._settings.get("TelegramBotToken", "")
        env["TELEGRAM_CHAT_ID"]    = self._settings.get("TelegramChatId", "")
        env["LINKEDIN_COOKIE"]     = self._settings.get("LinkedInCookie", "")
        kw = self._settings.get("Keywords", [])
        if isinstance(kw, list):
            kw = ",".join(kw)
        env["KEYWORDS"] = kw
        env["LOCATION"] = self._settings.get("Location", "")
        env["OLLAMA_URL"] = self._settings.get("OllamaUrl", "http://localhost:11434")

        def _stream():
            try:
                proc = subprocess.Popen(
                    cmd, cwd=str(_REPO_ROOT),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, env=env,
                )
                self._running_proc = proc
                for line in proc.stdout:
                    self.after(0, lambda l=line: self._append_log(l))
                    # Also append to log file
                    try:
                        _LOG_DIR.mkdir(parents=True, exist_ok=True)
                        with open(_LOG_FILE, "a", encoding="utf-8") as lf:
                            lf.write(line)
                    except Exception:
                        pass
                proc.wait()
                rc = proc.returncode
            except FileNotFoundError as exc:
                rc = -1
                self.after(0, lambda e=str(exc): self._append_log(
                    f"ERROR: {e}\nMake sure Python 3 is installed and cloud/ scripts exist.\n"
                ))
            self.after(0, lambda: self._on_proc_done(rc, label))

        threading.Thread(target=_stream, daemon=True).start()

    def _on_proc_done(self, returncode: int, label: str) -> None:
        self._running_proc = None
        self._append_log(f"[{_ts()}] ✓ {label} finished (exit {returncode})\n")
        self._set_status("Idle")
        self._btn_scan.config(state="normal")
        self._btn_enrich.config(state="normal")
        self._btn_cv.config(state="normal")
        self._btn_stop.config(state="disabled")
        if "Scan" in label:
            self.after(1000, self._reload_jobs_async)

    def _stop_process(self) -> None:
        if self._running_proc and self._running_proc.poll() is None:
            self._running_proc.terminate()
            self._append_log(f"[{_ts()}] ⏹ Process stopped by user.\n")
            self._set_status("Idle")
            self._btn_scan.config(state="normal")
            self._btn_enrich.config(state="normal")
            self._btn_cv.config(state="normal")
            self._btn_stop.config(state="disabled")

    def _set_status(self, text: str) -> None:
        self._status_var.set(text)

    # ─── Toolbar actions ──────────────────────────────────────

    def _scan_now(self) -> None:
        min_score = self._settings.get("MinAiScore", 5)
        cmd = [
            sys.executable, str(_CLOUD_DIR / "worker.py"),
            "--limit", "50",
        ]
        self._run_cloud_cmd(cmd, "Scan Now (worker.py)")

    def _run_enricher(self) -> None:
        min_score = self._settings.get("MinAiScore", 5)
        cmd = [
            sys.executable, str(_CLOUD_DIR / "enricher.py"),
            "--limit", "20",
            "--cover-letter-threshold", str(min_score + 2),
            "--tailored-cv-threshold",  str(min_score + 2),
        ]
        self._run_cloud_cmd(cmd, "Run Enricher (enricher.py)")

    def _analyze_cv(self) -> None:
        cv_path = self._settings.get("UserProfile", "")
        if not cv_path:
            cv_path = filedialog.askopenfilename(
                title="Select your CV (PDF)",
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            )
        if not cv_path:
            return
        # Also save to settings
        self._settings["UserProfile"] = cv_path
        if "UserProfile" in self._sv:
            self._sv["UserProfile"].set(cv_path)

        ollama_url = self._settings.get("OllamaUrl", "http://localhost:11434")
        cmd = [
            sys.executable, str(_CLOUD_DIR / "cv_analyzer.py"),
            "--cv", cv_path,
            "--ollama", ollama_url,
        ]
        self._run_cloud_cmd(cmd, f"Analyze CV: {Path(cv_path).name}")


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────
def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    app = JobAlertApp()
    app.mainloop()


if __name__ == "__main__":
    main()
