"""AI-based email classification using Google Gemini's free API tier.

To stay well within the free tier's rate/quota limits, we classify emails in
BATCHES: many emails are sent in a single request and Gemini returns a JSON
array with one verdict per email. That turns an N-email sort into just a
handful of API calls (usually one), instead of N calls.

We call Gemini's REST endpoint directly with the standard library (no SDK
dependency), retry on 429/503 with backoff, and surface the real HTTP error
text when something goes wrong.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

import config

if TYPE_CHECKING:
    from gmail_client import Email


ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
)

BATCH_SIZE = 15            # emails per single API call
DELAY_BETWEEN_BATCHES = 3  # seconds, only matters if there are multiple batches
MAX_RETRIES = 3
BODY_CHARS = 700           # how much of each email body to send

SYSTEM_PROMPT = """You are an expert executive assistant who triages email.

You will receive several emails, each marked with an [id]. For EACH email, judge:
- URGENCY (1-5): how time-sensitive it is. 5 = needs action within hours; \
1 = no time pressure.
- IMPORTANCE (1-5): how consequential it is to the recipient's goals, money, \
relationships, or obligations. 5 = major; 1 = trivial/noise (newsletters, \
promos, automated notifications).

Assign a category (>=4 counts as high):
- "urgent_important": high urgency AND high importance
- "important": high importance, low urgency
- "urgent": high urgency, low importance
- "neither": neither high

Marketing, promotions, newsletters, and automated no-reply notifications are \
almost always "neither" unless they contain a real personal deadline.

Respond with ONLY a JSON array, one object per email, no prose:
[{"id": <the id>, "urgency": <1-5>, "importance": <1-5>, \
"category": "<one of the four>", "reason": "<one short sentence>"}]"""


class GeminiError(Exception):
    """Carries the HTTP status and message from a failed Gemini call."""

    def __init__(self, status: int | str, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"{status}: {detail}")


class Classifier:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or config.GEMINI_API_KEY
        if not self.api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Get a free key at "
                "https://aistudio.google.com/apikey and set it in your environment."
            )
        self.model = model or config.GEMINI_MODEL

    def _call_gemini(self, user_content: str) -> str:
        url = ENDPOINT.format(model=self.model, key=self.api_key)
        body = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": user_content}]}],
            "generationConfig": {
                "maxOutputTokens": 4096,
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }
        data = json.dumps(body).encode("utf-8")

        last_err = None
        for attempt in range(MAX_RETRIES):
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                return payload["candidates"][0]["content"]["parts"][0]["text"]
            except urllib.error.HTTPError as e:
                try:
                    detail = e.read().decode("utf-8", errors="replace")
                except Exception:
                    detail = ""
                try:
                    detail = json.loads(detail)["error"]["message"]
                except Exception:
                    detail = detail[:200]
                last_err = GeminiError(e.code, detail)
                if e.code in (429, 500, 503) and attempt < MAX_RETRIES - 1:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise last_err
            except urllib.error.URLError as e:
                last_err = GeminiError("network", str(e.reason))
                if attempt < MAX_RETRIES - 1:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise last_err
        if last_err:
            raise last_err
        raise GeminiError("unknown", "no response")

    def _classify_batch(self, batch):
        parts = []
        for idx, e in enumerate(batch):
            body = (e.body or e.snippet or "")[:BODY_CHARS]
            parts.append(
                f"[{idx}]\nFrom: {e.sender} <{e.sender_email}>\n"
                f"Subject: {e.subject}\nDate: {e.date}\nBody: {body}"
            )
        user_content = "\n\n---\n\n".join(parts)

        try:
            raw = self._call_gemini(user_content)
            results = {int(r["id"]): r for r in self._parse_array(raw)}
        except GeminiError as ge:
            for e in batch:
                self._apply_error(e, f"AI error {ge.status}: {ge.detail}")
            return
        except Exception as exc:
            for e in batch:
                self._apply_error(e, f"Could not classify ({exc.__class__.__name__}).")
            return

        for idx, e in enumerate(batch):
            r = results.get(idx)
            if not r:
                self._apply_error(e, "No verdict returned for this email.")
                continue
            try:
                e.urgency = int(r.get("urgency", 1))
                e.importance = int(r.get("importance", 1))
                e.category = r.get("category", "neither")
                e.reason = r.get("reason", "")
                if e.category not in config.CATEGORIES:
                    e.category = self._derive_category(e.urgency, e.importance)
            except Exception:
                self._apply_error(e, "Malformed verdict for this email.")

    def classify(self, email):
        self._classify_batch([email])
        return email

    def classify_all(self, emails):
        for start in range(0, len(emails), BATCH_SIZE):
            batch = emails[start : start + BATCH_SIZE]
            self._classify_batch(batch)
            if start + BATCH_SIZE < len(emails):
                time.sleep(DELAY_BETWEEN_BATCHES)
        return emails

    @staticmethod
    def _apply_error(e, msg):
        e.category = "neither"
        e.urgency = e.urgency or 1
        e.importance = e.importance or 1
        e.reason = msg[:300]

    @staticmethod
    def _derive_category(urgency, importance):
        u, i = urgency >= 4, importance >= 4
        if u and i:
            return "urgent_important"
        if i:
            return "important"
        if u:
            return "urgent"
        return "neither"

    @staticmethod
    def _parse_array(raw):
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1:
            raw = raw[start : end + 1]
        data = json.loads(raw)
        return data if isinstance(data, list) else []
