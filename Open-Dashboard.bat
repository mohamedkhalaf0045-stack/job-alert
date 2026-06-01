@echo off
REM ── Job Alert — Monitoring Dashboard launcher ─────────────────────────────
REM Double-click to open the real-time monitoring & control dashboard in your
REM browser. Starts a local server on http://127.0.0.1:8765 (localhost only).
cd /d "%~dp0"
python cloud\dashboard.py
