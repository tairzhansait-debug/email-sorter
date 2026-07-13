"""Email Sorter — multi-user web app (Gmail + Outlook)."""
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
import ms_client
import report
from classifier import Classifier
from gmail_client import Email
from templates_html import DASHBOARD_HTML, LOGIN_HTML


def make_client(user_id, account):
    """Pick the right mailbox client for an account (Gmail or Microsoft)."""
    if ms_client.is_ms_account(account):
        return ms_client.MSClient(user_id, account)
    return gmail_client.GmailClient(user_id, account)


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


@app.route("/authorize/ms")
def authorize_ms():
    """Start Microsoft sign-in (work/school or personal Microsoft account)."""
    session["ms_mode"] = "add" if current_user() else "login"
    try:
        import secrets as _s
        state = _s.token_urlsafe(16)
        url = ms_client.build_auth_url(state)
    except Exception as exc:
        flash(f"Microsoft sign-in is not configured: {exc}", "error")
        return redirect(url_for("login") if not current_user() else url_for("dashboard"))
    session["ms_oauth_state"] = state
    return redirect(url)


@app.route(config.MS_REDIRECT_PATH)
def oauth2callback_ms():
    if request.args.get("error"):
        desc = request.args.get("error_description", request.args["error"])[:200]
        flash(f"Microsoft sign-in was cancelled or blocked: {desc}", "error")
        return redirect(url_for("login") if not current_user() else url_for("dashboard"))
    state = session.pop("ms_oauth_state", None)
    mode = session.pop("ms_mode", "login")
    if not state or request.args.get("state") != state:
        abort(400, "Missing or mismatched OAuth state.")
    try:
        account, tok = ms_client.exchange_code(request.args.get("code", ""))
    except Exception as exc:
        flash(f"Could not complete Microsoft sign-in: {exc}", "error")
        return redirect(url_for("login") if not current_user() else url_for("dashboard"))

    if mode == "login" or not current_user():
        session["user_id"] = ms_client.display_name(account)
    user_id = session["user_id"]
    ms_client._save_ms_token(user_id, account, tok)
    session["account"] = account
    flash(f"Connected {ms_client.display_name(account)} (Outlook).", "success")
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
        flash("Connect an inbox first.", "error")
        return redirect(url_for("dashboard"))
    try:
        classifier = Classifier()
        client = make_client(user_id, account)
        emails = client.fetch_inbox()
        classifier.classify_all(emails)
        gmail_client.save_last_sort(user_id, account, emails)
        flash(f"Sorted {len(emails)} emails.", "success")
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
        client = make_client(user_id, account)
        n = client.apply_labels_bulk([Email.from_dict(d) for d in cached])
        flash(f"Applied labels/categories to {n} emails.", "success")
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
        return redirect(url_for("dashboard"))
    objs = [Email.from_dict(d) for d in cached]
    path = report.export_csv(objs, account) if fmt == "csv" else report.export_html(objs, account)
    return send_file(path, as_attachment=True)


@app.route("/healthz")
def healthz():
    return {"status": "ok"}


def _run_all_sorts():
    clf = Classifier()
    summary = {"users": 0, "accounts": 0, "emails": 0, "labeled": 0, "errors": []}
    for user_id in gmail_client.list_all_users():
        summary["users"] += 1
        for account in gmail_client.list_accounts(user_id):
            try:
                client = make_client(user_id, account)
                emails = client.fetch_inbox()
                clf.classify_all(emails)
                gmail_client.save_last_sort(user_id, account, emails)
                n = client.apply_labels_bulk(emails)
                summary["accounts"] += 1
                summary["emails"] += len(emails)
                summary["labeled"] += n
            except Exception as exc:
                summary["errors"].append(f"{account}: {exc.__class__.__name__}")
    return summary


@app.route("/cron/run")
def cron_run():
    secret = os.environ.get("CRON_SECRET", "")
    if not secret or request.args.get("token") != secret:
        abort(403)
    return _run_all_sorts()


if __name__ == "__main__":
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=False)
