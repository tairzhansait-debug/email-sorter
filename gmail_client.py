"""Gmail access layer for the multi-user web app.

Storage backend:
- If UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN are set, per-user OAuth
  tokens and last-sort results are stored in Upstash Redis (over plain HTTPS,
  no extra library). This persists across restarts.
- Otherwise it falls back to local files under data/ (fine for local dev).
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.utils import parseaddr
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

import config


@dataclass
class Email:
    id: str
    thread_id: str
    sender: str
    sender_email: str
    subject: str
    snippet: str
    date: str
    body: str = ""
    category: Optional[str] = None
    urgency: Optional[int] = None
    importance: Optional[int] = None
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "thread_id": self.thread_id, "sender": self.sender,
            "sender_email": self.sender_email, "subject": self.subject,
            "snippet": self.snippet, "date": self.date, "category": self.category,
            "urgency": self.urgency, "importance": self.importance,
            "reason": self.reason,
            "body": (self.body or "")[:2500],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Email":
        return cls(**{k: d.get(k) for k in (
            "id", "thread_id", "sender", "sender_email", "subject", "snippet",
            "date", "body", "category", "urgency", "importance", "reason") if k in d})


_UPSTASH_URL = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
_UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")


def _redis_on() -> bool:
    return bool(_UPSTASH_URL and _UPSTASH_TOKEN)


def _redis(*cmd) -> object:
    body = json.dumps([str(c) for c in cmd]).encode("utf-8")
    req = urllib.request.Request(
        _UPSTASH_URL, data=body,
        headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8")).get("result")


_SAFE = re.compile(r"[^A-Za-z0-9._@-]")


def _safe(name: str) -> str:
    return _SAFE.sub("_", name)


def _user_dir(user_id: str) -> Path:
    d = config.USERS_DIR / _safe(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _account_path(user_id: str, email: str) -> Path:
    return _user_dir(user_id) / f"account_{_safe(email)}.json"


def _lastsort_path(user_id: str, email: str) -> Path:
    return _user_dir(user_id) / f"lastsort_{_safe(email)}.json"


def list_accounts(user_id: str) -> list[str]:
    if _redis_on():
        res = _redis("SMEMBERS", f"accts:{user_id}") or []
        return sorted(res)
    out = []
    for f in _user_dir(user_id).glob("account_*.json"):
        out.append(f.stem[len("account_"):])
    return sorted(out)


def list_all_users() -> list[str]:
    if _redis_on():
        return sorted(_redis("SMEMBERS", "users") or [])
    if not config.USERS_DIR.exists():
        return []
    return sorted(p.name for p in config.USERS_DIR.iterdir() if p.is_dir())


def save_token(user_id: str, email: str, creds: Credentials) -> None:
    if _redis_on():
        _redis("SET", f"tok:{user_id}|{email}", creds.to_json())
        _redis("SADD", f"accts:{user_id}", email)
        _redis("SADD", "users", user_id)
        return
    _account_path(user_id, email).write_text(creds.to_json())


def remove_account(user_id: str, email: str) -> None:
    if _redis_on():
        _redis("DEL", f"tok:{user_id}|{email}")
        _redis("DEL", f"ls:{user_id}|{email}")
        _redis("SREM", f"accts:{user_id}", email)
        if not (_redis("SMEMBERS", f"accts:{user_id}") or []):
            _redis("SREM", "users", user_id)
        return
    for p in (_account_path(user_id, email), _lastsort_path(user_id, email)):
        if p.exists():
            p.unlink()


def save_last_sort(user_id: str, email: str, emails: list[Email]) -> None:
    data = json.dumps([e.to_dict() for e in emails])
    if _redis_on():
        _redis("SET", f"ls:{user_id}|{email}", data)
        return
    _lastsort_path(user_id, email).write_text(data)


def load_last_sort(user_id: str, email: str) -> list[dict]:
    if _redis_on():
        raw = _redis("GET", f"ls:{user_id}|{email}")
        return json.loads(raw) if raw else []
    p = _lastsort_path(user_id, email)
    if p.exists():
        return json.loads(p.read_text())
    return []


def _flow(state: str | None = None) -> Flow:
    return Flow.from_client_secrets_file(
        str(config.CLIENT_SECRET_FILE),
        scopes=config.GMAIL_SCOPES,
        redirect_uri=config.OAUTH_REDIRECT_URI,
        state=state,
    )


def build_auth_url() -> tuple[str, str]:
    if not config.CLIENT_SECRET_FILE.exists():
        raise FileNotFoundError(
            "credentials.json (Web application OAuth client) not found. "
            "See the README for setup."
        )
    flow = _flow()
    auth_url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent",
    )
    return auth_url, state


def exchange_code(authorization_response_url: str, state: str) -> tuple[str, Credentials]:
    flow = _flow(state=state)
    flow.fetch_token(authorization_response=authorization_response_url)
    creds = flow.credentials
    service = build("gmail", "v1", credentials=creds)
    email = service.users().getProfile(userId="me").execute()["emailAddress"]
    return email, creds


def _load_credentials(user_id: str, email: str) -> Credentials:
    if _redis_on():
        raw = _redis("GET", f"tok:{user_id}|{email}")
        if not raw:
            raise FileNotFoundError(f"No connected account {email} for this user.")
        creds = Credentials.from_authorized_user_info(json.loads(raw), config.GMAIL_SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                _redis("SET", f"tok:{user_id}|{email}", creds.to_json())
            else:
                raise RuntimeError(f"Access for {email} expired. Reconnect the account.")
        return creds

    path = _account_path(user_id, email)
    if not path.exists():
        raise FileNotFoundError(f"No connected account {email} for this user.")
    creds = Credentials.from_authorized_user_file(str(path), config.GMAIL_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            path.write_text(creds.to_json())
        else:
            raise RuntimeError(f"Access for {email} expired. Reconnect the account.")
    return creds


class GmailClient:
    def __init__(self, user_id: str, email: str):
        self.user_id = user_id
        self.email = email
        self.service = build("gmail", "v1", credentials=_load_credentials(user_id, email))
        self._label_cache: dict[str, str] = {}

    def fetch_inbox(self, max_results: int = config.MAX_EMAILS) -> list[Email]:
        resp = (
            self.service.users().messages()
            .list(userId="me", labelIds=["INBOX"], maxResults=max_results)
            .execute()
        )
        emails: list[Email] = []
        for m in resp.get("messages", []):
            full = (
                self.service.users().messages()
                .get(userId="me", id=m["id"], format="full")
                .execute()
            )
            emails.append(self._parse_message(full))
        return emails

    def _parse_message(self, msg: dict) -> Email:
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        name, addr = parseaddr(headers.get("from", ""))
        return Email(
            id=msg["id"],
            thread_id=msg.get("threadId", ""),
            sender=name or addr,
            sender_email=addr,
            subject=headers.get("subject", "(no subject)"),
            snippet=msg.get("snippet", ""),
            date=headers.get("date", ""),
            body=self._extract_body(msg["payload"])[:4000],
        )

    def _extract_body(self, payload: dict) -> str:
        def walk(part) -> str:
            mime = part.get("mimeType", "")
            data = part.get("body", {}).get("data")
            if mime == "text/plain" and data:
                return self._decode(data)
            if "parts" in part:
                for p in part["parts"]:
                    text = walk(p)
                    if text:
                        return text
            if mime == "text/html" and data:
                return self._strip_html(self._decode(data))
            return ""
        return walk(payload).strip()

    @staticmethod
    def _decode(data: str) -> str:
        return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")

    @staticmethod
    def _strip_html(html: str) -> str:
        html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        html = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", html)

    def _ensure_label(self, name: str) -> str:
        if name in self._label_cache:
            return self._label_cache[name]
        existing = self.service.users().labels().list(userId="me").execute().get("labels", [])
        by_name = {lbl["name"]: lbl["id"] for lbl in existing}
        parts = name.split("/")
        for i in range(1, len(parts) + 1):
            partial = "/".join(parts[:i])
            if partial not in by_name:
                created = self.service.users().labels().create(
                    userId="me",
                    body={"name": partial, "labelListVisibility": "labelShow",
                          "messageListVisibility": "show"},
                ).execute()
                by_name[partial] = created["id"]
        self._label_cache[name] = by_name[name]
        return by_name[name]

    def apply_labels_bulk(self, emails: list[Email]) -> int:
        count = 0
        for e in emails:
            if not e.category:
                continue
            label_id = self._ensure_label(config.CATEGORIES[e.category])
            self.service.users().messages().modify(
                userId="me", id=e.id, body={"addLabelIds": [label_id]}
            ).execute()
            count += 1
        return count
