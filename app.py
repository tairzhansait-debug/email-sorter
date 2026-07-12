"""Email Sorter — multi-user web app."""
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
    except Exception
