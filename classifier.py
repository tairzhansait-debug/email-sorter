"""AI-based email classification using Google Gemini's free API tier.

Each email is scored for urgency (time pressure) and importance (consequence),
then placed into one of four Eisenhower-matrix buckets.

We call Gemini's REST endpoint directly with the standard library, so there is
no extra SDK dependency to install or keep up to date.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

import config

if TYPE_CHECKING:
    from gmail_client import Email


ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
)

SYSTEM_PROMPT = """You are an expert executive assistant who triages email.

For each email, judge two things independently on a 1-5 scale:
- URGENCY: how time-sensitive it is. 5 = needs action within hours; \
1 = no time pressure at all.
- IMPORTANCE: how consequential it is to the recipient's goals, \
relationships, money, or obligations. 5 = major consequences; \
1 = trivial/noise (newsletters, promos, automated notifications).

Then assign a category using these thresholds (urgency/importance >= 4 counts \
as high):
- "urgent_important": high urgency AND high importance
- "important": high importance, low urgency
- "urgent": high urgency, low importance
- "neither": neither high

Marketing, promotions, newsletters, and automated no-reply notifications are \
almost always "neither" unless they contain a real personal deadline.

Respond with ONLY a JSON object, no prose, in exactly this shape:
{"urgency": <1-5>, "importance": <1-5>, "category": "<one of the four>", \
"reason": "<one short sentence>"}"""


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
                "maxOutputTokens": 300,
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["candidates"][0]["content"]["parts"][0]["text"]

    def classify(self, email: "Email") -> "Email":
        user_content = (
            f"From: {email.sender} <{email.sender_email}>\n"
            f"Subject: {email.subject}\n"
            f"Date: {email.date}\n\n"
            f"Body:\n{email.body or email.snippet}"
        )
        try:
            raw = self._call_gemini(user_content)
            parsed = self._parse_json(raw)
            email.urgency = int(parsed.get("urgency", 1))
            email.importance = int(parsed.get("importance", 1))
            email.category = parsed.get("category", "neither")
            email.reason = parsed.get("reason", "")
            if email.category not in config.CATEGORIES:
                email.category = self._derive_category(email.urgency, email.importance)
        except Exception as exc:  # noqa: BLE001 - keep the run alive on one bad email
            email.category = "neither"
            email.urgency = email.urgency or 1
            email.importance = email.importance or 1
            email.reason = f"Could not classify ({exc.__class__.__name__})."
        return email

    def classify_all(self, emails: list["Email"]) -> list["Email"]:
        for e in emails:
            self.classify(e)
        return emails

    @staticmethod
    def _derive_category(urgency: int, importance: int) -> str:
        u, i = urgency >= 4, importance >= 4
        if u and i:
            return "urgent_important"
        if i:
            return "important"
        if u:
            return "urgent"
        return "neither"

    @staticmethod
    def _parse_json(raw: str) -> dict:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1:
            raw = raw[start : end + 1]
        return json.loads(raw)
