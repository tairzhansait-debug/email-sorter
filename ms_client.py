"""Microsoft 365 / Outlook connector via Microsoft Graph.

Adds work-mailbox support alongside Gmail. Accounts from this provider are
stored with an "ms:" prefix (e.g. "ms:someone@company.com") so the rest of the
app can tell which client to use. Tokens live in the same storage backend as
Gmail tokens (Upstash Redis when configured, else local files).

Outlook has no labels; we apply color-coded Categories with the same names as
the Gmail labels. The message's webLink is stashed in Email.thread_id so the
dashboard can link to the message in Outlook on the web.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

import config
import gmail_client
from gmail_client import Email, GmailClient as _G

AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = "offline_access User.Read Mail.ReadWrite"

PREFIX = "ms:"

_CATEGORY_COLORS = {
    "urgent_important": "preset0",
    "urgent": "preset3",
    "important": "preset7",
    "neither": "preset10",
}


def is_ms_account(account: str) -> bool:
    return account.startswith(PREFIX)


def display_name(account: str) -> str:
    return account[len(PREFIX):] if is_ms_account(account) else account


def _configured() -> bool:
    return bool(config.MS_CLIENT_ID and config.MS_CLIENT_SECRET)


def _save_ms_token(user_id: str, account: str, tok: dict) -> None:
    raw = json.dumps(tok)
    if gmail_client._redis_on():
        gmail_client._redis("SET", f"tok:{user_id}|{account}", raw)
        gmail_client._redis("SADD", f"accts:{user_id}", account)
        gmail_client._redis("SADD", "users", user_id)
        return
    gmail_client._account_path(user_id, account).write_text(raw)


def _load_ms_token(user_id: str, account: str) -> dict:
    if gmail_client._redis_on():
        raw = gmail_client._redis("GET", f"tok:{user_id}|{account}")
        if not raw:
            raise FileNotFoundError(f"No connected account {display_name(account)}.")
        return json.loads(raw)
    p = gmail_client._account_path(user_id, account)
    if not p.exists():
        raise FileNotFoundError(f"No connected account {display_name(account)}.")
    return json.loads(p.read_text())


def build_auth_url(state: str) -> str:
    if not _configured():
        raise RuntimeError(
            "Microsoft sign-in is not configured: set MS_CLIENT_ID and "
            "MS_CLIENT_SECRET in the environment."
        )
    params = {
        "client_id": config.MS_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": config.MS_REDIRECT_URI,
        "response_mode": "query",
        "scope": SCOPES,
        "state": state,
        "prompt": "select_account",
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def _token_request(form: dict) -> dict:
    data = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            tok = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Microsoft sign-in failed ({e.code}): {detail}")
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    return tok


def exchange_code(code: str) -> tuple[str, dict]:
    tok = _token_request({
        "client_id": config.MS_CLIENT_ID,
        "client_secret": config.MS_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.MS_REDIRECT_URI,
        "scope": SCOPES,
    })
    me = _graph_get(tok["access_token"], "/me?$select=mail,userPrincipalName")
    email = me.get("mail") or me.get("userPrincipalName") or "unknown"
    return PREFIX + email, tok


def _refresh(user_id: str, account: str, tok: dict) -> dict:
    if tok.get("expires_at", 0) > time.time():
        return tok
    if not tok.get("refresh_token"):
        raise RuntimeError(f"Access for {display_name(account)} expired. Reconnect it.")
    newtok = _token_request({
        "client_id": config.MS_CLIENT_ID,
        "client_secret": config.MS_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": tok["refresh_token"],
        "scope": SCOPES,
    })
    if "refresh_token" not in newtok:
        newtok["refresh_token"] = tok["refresh_token"]
    _save_ms_token(user_id, account, newtok)
    return newtok


def _graph_get(access_token: str, path: str) -> dict:
    req = urllib.request.Request(
        GRAPH + path,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _graph_send(access_token: str, path: str, payload: dict, method: str) -> None:
    req = urllib.request.Request(
        GRAPH + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {access_token}",
                 "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        if e.code in (409,):
            return
        raise


class MSClient:
    """Same interface as GmailClient: fetch_inbox / apply_labels_bulk."""

    def __init__(self, user_id: str, account: str):
        self.user_id = user_id
        self.account = account
        tok = _load_ms_token(user_id, account)
        tok = _refresh(user_id, account, tok)
        self._access = tok["access_token"]
        self._categories_ready = False

    def fetch_inbox(self, max_results: int = config.MAX_EMAILS) -> list[Email]:
        sel = "id,subject,from,receivedDateTime,bodyPreview,body,webLink"
        data = _graph_get(
            self._access,
            f"/me/mailFolders/inbox/messages?$top={max_results}"
            f"&$select={sel}&$orderby=receivedDateTime%20desc",
        )
        out: list[Email] = []
        for m in data.get("value", []):
            frm = (m.get("from") or {}).get("emailAddress", {})
            body = m.get("body") or {}
            content = body.get("content") or ""
            if (body.get("contentType") or "").lower() == "html":
                content = _G._strip_html(content)
            out.append(Email(
                id=m.get("id", ""),
                thread_id=m.get("webLink", ""),
                sender=frm.get("name") or frm.get("address") or "",
                sender_email=frm.get("address") or "",
                subject=m.get("subject") or "(no subject)",
                snippet=m.get("bodyPreview") or "",
                date=m.get("receivedDateTime") or "",
                body=content.strip()[:4000],
            ))
        return out

    def _ensure_categories(self) -> None:
        if self._categories_ready:
            return
        for cat, color in _CATEGORY_COLORS.items():
            try:
                _graph_send(self._access, "/me/outlook/masterCategories",
                            {"displayName": config.CATEGORIES[cat], "color": color},
                            "POST")
            except Exception:
                pass
        self._categories_ready = True

    def apply_labels_bulk(self, emails: list[Email]) -> int:
        self._ensure_categories()
        count = 0
        for e in emails:
            if not e.category:
                continue
            _graph_send(self._access, f"/me/messages/{e.id}",
                        {"categories": [config.CATEGORIES[e.category]]}, "PATCH")
            count += 1
        return count
