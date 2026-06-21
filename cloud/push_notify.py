"""
FCM push notification sender — Firebase HTTP v1 API.

Reads FIREBASE_SERVICE_ACCOUNT env var (JSON string of service account key).
No firebase-admin package needed; uses google-auth for OAuth2 only.

Usage:
    import push_notify
    ok = push_notify.send(token, title, body, data={'job_id': '...'})
"""

from __future__ import annotations

import json
import os

import requests

_SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]
_FCM_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"


def _access_token(sa: dict) -> str:
    from google.oauth2.service_account import Credentials
    from google.auth.transport.requests import Request as GRequest
    creds = Credentials.from_service_account_info(sa, scopes=_SCOPES)
    creds.refresh(GRequest())
    return creds.token  # type: ignore[return-value]


def _sa() -> dict | None:
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def send(
    fcm_token: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> bool:
    """Send one FCM push. Returns True on success, False on any error."""
    if not fcm_token:
        return False
    sa = _sa()
    if not sa:
        print("[FCM] FIREBASE_SERVICE_ACCOUNT not set — skipping push")
        return False

    try:
        token = _access_token(sa)
    except Exception as exc:
        print(f"[FCM] auth error: {exc}")
        return False

    project_id = sa.get("project_id", "")
    payload = {
        "message": {
            "token": fcm_token,
            "notification": {"title": title, "body": body},
            "android": {
                "priority": "HIGH",
                "notification": {
                    "channel_id": "job_alerts",
                    "priority": "max",
                    "default_vibrate_timings": True,
                },
            },
            "data": {k: str(v) for k, v in (data or {}).items()},
        }
    }

    try:
        res = requests.post(
            _FCM_URL.format(project_id=project_id),
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        if res.status_code == 200:
            return True
        print(f"[FCM] send failed {res.status_code}: {res.text[:200]}")
        return False
    except Exception as exc:
        print(f"[FCM] request error: {exc}")
        return False
