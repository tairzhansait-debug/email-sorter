"""Email Sorter — multi-user web app.

Anyone with the link can sign in with their own Google account and sort their
own inbox. Each user's data is isolated on the server. Gmail auth uses a web
OAuth redirect flow, so it works at a public URL.

Local run:   python app.py
Production:  gunicorn app:app   (see README)
"""
from __future__ import annotations

import functools
import os

from flask import (
    Flask, abort, flash, redirect, render_template_string, request, send_file,
    session, url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

import config
import gmail_client
import report
from classifier import Classifier
from gmail_client import Email
from templates_html import DASHBOARD_HTML, LOGIN_HTML

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=config.BASE_URL.startswith("https://"),
)


def current_user():
    return session.get("user_id")


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def _selected_account(user_id):
    accts = gmail_client.list_accounts(user_id)
    sel = session.get("account")
    if sel in accts:
        return sel
    if accts:
        session["account"] = accts[0]
        return accts[0]
    return None


@app.route("/")
def index():
    if not current_user():
        return render_template_string(LOGIN_HTML, has_api_key=bool(config.GEMINI_API_KEY))
    return redirect(url_for("dashboard"))


@app.route("/login")
def login():
    if current_user():
        return redirect(url_for("dashboard"))
    return render_template_string(LOGIN_HTML, has_api_key=bool(config.GEMINI_API_KEY))


@app.route("/logout")
def logout():
    session.clear()
    flash("Signed out.", "info")
    return redirect(url_for("login"))


@app.route("/authorize")
def authorize():
    session["oauth_mode"] = "add" if current_user() else "login"
    try:
        auth_url, state = gmail_client.build_auth_url()
    except Exception as exc:
        flash(f"Sign-in is not configured: {exc}", "error")
        return redirect(url_for("login"))
    session["oauth_state"] = state
    return redirect(auth_url)


@app.route(config.OAUTH_REDIRECT_PATH)
def oauth2callback():
    if request.args.get("error"):
        flash(f"Google sign-in was cancelled ({request.args['error']}).", "error")
        return redirect(url_for("login"))
    state = session.pop("oauth_state", None)
    mode = session.pop("oauth_mode", "login")
    if not state:
        abort(400, "Missing OAuth state.")
    authorization_response = config.BASE_URL + request.full_path
    try:
        email, creds = gmail_client.exchange_code(authorization_response, state)
    except Exception as exc:
        flash(f"Could not complete sign-in: {exc}", "error")
        return redirect(url_for("login"))

    if mode == "login" or not current_user():
        session["user_id"] = email
    user_id = session["user_id"]
    gmail_client.save_token(user_id, email, creds)
    session["account"] = email
    flash(f"Connected {email}.", "success")
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    user_id = current_user()
    accounts = gmail_client.list_accounts(user_id)
    account = _selected_account(user_id)
    emails = gmail_client.load_last_sort(user_id, account) if account else []

    buckets = {c: [] for c in config.CATEGORY_ORDER}
    for e in emails:
        buckets.setdefault(e.get("category", "neither"), []).append(e)

    return render_template_string(
        DASHBOARD_HTML,
        user_id=user_id,
        accounts=accounts,
        account=account,
        buckets=buckets,
        category_order=config.CATEGORY_ORDER,
        category_labels=config.CATEGORY_LABELS,
        total=len(emails),
        has_api_key=bool(config.GEMINI_API_KEY),
        max_emails=config.MAX_EMAILS,
    )


@app.route("/switch", methods=["POST"])
@login_required
def switch():
    account = request.form.get("account")
    if account in gmail_client.list_accounts(current_user()):
        session["account"] = account
    return redirect(url_for("dashboard"))


@app.route("/remove-account", methods=["POST"])
@login_required
def remove_account():
    account = request.form.get("account")
    user_id = current_user()
    if account:
        gmail_client.remove_account(user_id, account)
        if session.get("account") == account:
            session.pop("account", None)
        flash(f"Disconnected {account}.", "info")
    return redirect(url_for("dashboard"))


@app.route("/sort", methods=["POST"])
@login_required
def sort_emails():
    user_id = current_user()
    account = _selected_account(user_id)
    if not account:
        flash("Connect a Gmail inbox first.", "error")
        return redirect(url_for("dashboard"))
    try:
        classifier = Classifier()
        client = gmail_client.GmailClient(user_id, account)
        emails = client.fetch_inbox()
        classifier.classify_all(emails)
        gmail_client.save_last_sort(user_id, account, emails)
        flash(f"Sorted {len(emails)} emails from {account}.", "success")
    except Exception as exc:
        flash(f"Sorting failed: {exc}", "error")
    return redirect(url_for("dashboard"))


@app.route("/apply-labels", methods=["POST"])
@login_required
def apply_labels():
    user_id = current_user()
    account = _selected_account(user_id)
    cached = gmail_client.load_last_sort(user_id, account) if account else []
    if not cached:
        flash("Nothing to label — run a sort first.", "error")
        return redirect(url_for("dashboard"))
    try:
        client = gmail_client.GmailClient(user_id, account)
        n = client.apply_labels_bulk([Email.from_dict(d) for d in cached])
        flash(f"Applied labels to {n} emails in Gmail.", "success")
    except Exception as exc:
        flash(f"Applying labels failed: {exc}", "error")
    return redirect(url_for("dashboard"))


@app.route("/export/<fmt>")
@login_required
def export(fmt):
    user_id = current_user()
    account = _selected_account(user_id)
    cached = gmail_client.load_last_sort(user_id, account) if account else []
    if not cached:
        flash("Nothing to export — run a sort first.", "error")
