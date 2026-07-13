"""Email classification: AI-first with an automatic no-cost fallback.

Primary: Groq's free AI tier (Llama models) classifies emails in BATCHES
(many emails per request) to stay within rate limits.

Fallback: if the AI is unavailable for ANY reason (no key, rate limit,
network error), we transparently fall back to a rules-based scorer so the
inbox still gets sorted. The first email card shows the AI error so problems
are visible instead of silent.
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


ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

BATCH_SIZE = 15
DELAY_BETWEEN_BATCHES = 3
MAX_RETRIES = 2
BODY_CHARS = 700

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


URGENT_STRONG = [
    "urgent", "asap", "as soon as possible", "immediately", "action required",
    "action needed", "response required", "time sensitive", "time-sensitive",
    "final notice", "last chance", "overdue", "expires today", "due today",
    "respond today", "eod", "deadline", "past due", "act now", "expiring soon",
]
URGENT_SOFT = [
    "today", "tomorrow", "reminder", "due", "expires", "expiring", "reply by",
    "respond by", "please respond", "please reply", "confirm", "closing",
    "ends soon", "limited time", "waiting", "follow up", "follow-up",
]
IMPORTANT_TERMS = [
    "invoice", "payment", "past due", "contract", "agreement", "legal", "tax",
    "security alert", "suspicious", "password", "verify your", "verification",
    "suspended", "account", "interview", "job offer", "offer", "meeting",
    "calendar", "refund", "bank", "wire", "transfer", "important", "approval",
    "approve", "sign", "signature", "renewal", "delivery", "shipment", "order",
    "receipt", "statement", "appointment", "deadline",
]
BULK_SENDER = [
    "no-reply", "noreply", "no_reply", "donotreply", "do-not-reply",
    "newsletter", "marketing", "notifications", "notification", "mailer",
    "updates", "promo", "promotions", "deals", "news@", "campaign",
]
BULK_BODY = [
    "unsubscribe", "view in browser", "% off", "shop now", "coupon",
    "promo code", "newsletter", "limited time offer", "manage preferences",
    "you are receiving this", "update your preferences",
]


def _hits(text, terms):
    return [t for t in terms if t in text]


class GeminiError(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail
        super().__init__(f"{status}: {detail}")


class Classifier:
    def __init__(self, api_key=None, model=None):
        self.api_key = api_key if api_key is not None else config.GROQ_API_KEY
        self.model = model or config.GROQ_MODEL
        self._ai_down = False  # set after the first AI failure in this run

    def _call_gemini(self, user_content):
        if not self.api_key:
            raise GeminiError("no-key", "No API key configured.")
        body = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 4096,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        }
        data = json.dumps(body).encode("utf-8")
        last_err = None
        for attempt in range(MAX_RETRIES):
            req = urllib.request.Request(
                ENDPOINT, data=data,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {self.api_key}"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                return payload["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                try:
                    detail = json.loads(e.read().decode("utf-8", "replace"))["error"]["message"]
                except Exception:
                    detail = "HTTP error"
                last_err = GeminiError(e.code, detail)
                if e.code in (500, 503) and attempt < MAX_RETRIES - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise last_err
            except urllib.error.URLError as e:
                last_err = GeminiError("network", str(e.reason))
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise last_err
        raise last_err or GeminiError("unknown", "no response")

    def _classify_batch(self, batch):
        if self._ai_down:
            for e in batch:
                self._rules_classify(e)
            return

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
        except Exception as exc:
            self._ai_down = True  # AI unavailable → rules for the rest of this run
            detail = str(exc)[:220]
            for i, e in enumerate(batch):
                self._rules_classify(e)
                if i == 0:
                    e.reason = f"[AI error: {detail}] {e.reason}"
            return

        for idx, e in enumerate(batch):
            r = results.get(idx)
            if not r:
                self._rules_classify(e)
                continue
            try:
                e.urgency = int(r.get("urgency", 1))
                e.importance = int(r.get("importance", 1))
                e.category = r.get("category", "neither")
                e.reason = r.get("reason", "")
                if e.category not in config.CATEGORIES:
                    e.category = self._derive_category(e.urgency, e.importance)
            except Exception:
                self._rules_classify(e)

    def classify(self, email):
        self._classify_batch([email])
        return email

    def classify_all(self, emails):
        for start in range(0, len(emails), BATCH_SIZE):
            batch = emails[start : start + BATCH_SIZE]
            self._classify_batch(batch)
            if not self._ai_down and start + BATCH_SIZE < len(emails):
                time.sleep(DELAY_BETWEEN_BATCHES)
        return emails

    def _rules_classify(self, e):
        subject = (e.subject or "").lower()
        body = (e.body or e.snippet or "").lower()
        sender = f"{e.sender} {e.sender_email}".lower()
        reasons = []

        is_bulk = bool(_hits(sender, BULK_SENDER) + _hits(body, BULK_BODY))

        urgency = 1
        if _hits(subject, URGENT_STRONG):
            urgency += 3
            reasons.append("urgent wording in subject")
        elif _hits(body, URGENT_STRONG):
            urgency += 2
            reasons.append("urgent wording")
        if _hits(subject, URGENT_SOFT):
            urgency += 1
        if subject.startswith(("re:", "fwd:", "fw:")):
            urgency += 1
        if is_bulk:
            urgency -= 1
        urgency = max(1, min(5, urgency))

        importance = 2
        if _hits(subject, IMPORTANT_TERMS):
            importance += 2
            reasons.append("important topic")
        elif _hits(body, IMPORTANT_TERMS):
            importance += 1
        if subject.startswith(("re:", "fwd:", "fw:")):
            importance += 1
        if not is_bulk and " " in (e.sender or "").strip():
            importance += 1
        if is_bulk:
            importance -= 2
            reasons.append("looks like a bulk/promotional message")
        importance = max(1, min(5, importance))

        e.urgency = urgency
        e.importance = importance
        e.category = self._derive_category(urgency, importance)
        note = "; ".join(reasons) if reasons else "no strong signals"
        e.reason = f"{note} (quick sort)"

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
