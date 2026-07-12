"""Email classification: AI-first with an automatic no-cost fallback.

Primary: Google Gemini (free tier) classifies emails in BATCHES (many emails
per request) to stay within rate limits.

Fallback: if Gemini is unavailable for ANY reason (no key, quota/429, region
block, network error), we transparently fall back to a rules-based scorer so
the inbox still gets sorted. Rules use urgency keywords, sender type, and
conversation signals. When the free AI becomes available, the app uses it
again automatically with no changes.
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
        self.api_key = api_key if api_key is not None else config.GEMINI_API_KEY
        self.model = model or config.GEMINI_MODEL

    def _call_gemini(self, user_content):
        if not self.api_key:
            raise GeminiError("no-key", "No API key configured.")
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
                    detail = json.loads(e.read().decode("utf-8", "replace"))["error"]["message"]
                except Exception:
                    detail = "HTTP error"
                last_err = GeminiError(e.code, detail)
                if e.code in (429, 500, 503) and attempt <
