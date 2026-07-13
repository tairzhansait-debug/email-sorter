"""Central configuration for the Email Sorter (multi-user web app).

Values are read from environment variables (loaded from a local .env file in
development; set as real env vars on your host in production).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Paths -----------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
USERS_DIR = DATA_DIR / "users"        # per-user folder: tokens + last sort
CLIENT_SECRET_FILE = Path(
    os.getenv("CLIENT_SECRET_FILE", BASE_DIR / "credentials.json")
)  # "Web application" OAuth client from Google Cloud

USERS_DIR.mkdir(parents=True, exist_ok=True)

# --- Public URL & OAuth ----------------------------------------------------
BASE_URL = os.getenv("BASE_URL", "http://localhost:5000").rstrip("/")
OAUTH_REDIRECT_PATH = "/oauth2callback"
OAUTH_REDIRECT_URI = f"{BASE_URL}{OAUTH_REDIRECT_PATH}"

if BASE_URL.startswith("http://localhost") or BASE_URL.startswith("http://127."):
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

# --- Gmail scopes ----------------------------------------------------------
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

MAX_EMAILS = int(os.getenv("MAX_EMAILS", "40"))

# --- Microsoft 365 / Outlook (optional second provider) ---------------------
MS_CLIENT_ID = os.getenv("MS_CLIENT_ID", "")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET", "")
MS_REDIRECT_PATH = "/oauth2callback/ms"
MS_REDIRECT_URI = f"{BASE_URL}{MS_REDIRECT_PATH}"

# --- Classifier (Google Gemini free tier) ----------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

CATEGORIES = {
    "urgent_important": "Sorter/1 - Urgent & Important",
    "important": "Sorter/2 - Important, Not Urgent",
    "urgent": "Sorter/3 - Urgent, Not Important",
    "neither": "Sorter/4 - Neither",
}
CATEGORY_LABELS = {
    "urgent_important": "Urgent & Important",
    "important": "Important, Not Urgent",
    "urgent": "Urgent, Not Important",
    "neither": "Neither",
}
CATEGORY_ORDER = ["urgent_important", "urgent", "important", "neither"]

# --- Flask -----------------------------------------------------------------
FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("PORT", os.getenv("FLASK_PORT", "5000")))
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
