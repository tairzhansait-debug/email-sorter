# 📥 Email Sorter (web app)

A shareable web app that sorts Gmail inboxes by **urgency** and **importance**
using AI, applies matching **labels back into Gmail**, and exports a **report**.

Anyone with the link can **sign in with their own Google account** and sort
**their own inbox** — each person's data is isolated on the server. A single
user can also connect **several of their own Gmail accounts** and switch between
them at any time.

Emails are placed into four buckets (the "Eisenhower matrix"):

| | Urgent | Not urgent |
|---|---|---|
| **Important** | 🔴 Urgent & Important | 🔵 Important, Not Urgent |
| **Not important** | 🟠 Urgent, Not Important | ⚪ Neither |

---

## How it fits together

- **Flask** app (`app.py`) with Google **web OAuth** sign-in.
- Each signed-in person is a *user*; their connected inboxes and sort results
  live only in their own folder under `DATA_DIR` on the server.
- **Google Gemini** (`classifier.py`) scores each email's urgency & importance
  using its **free API tier**.
- Runs anywhere that runs Python or Docker.

---

## What you need before deploying

1. A **Google Cloud OAuth client** of type **Web application** (free).
2. A **free Gemini API key** (no credit card) — <https://aistudio.google.com/apikey>.
3. A host that gives you an **HTTPS URL** (Render, Railway, Fly, a VPS, etc.).
   Google requires HTTPS for OAuth on any non-localhost URL.

---

## 1. Create the Google OAuth client (one time)

1. Open <https://console.cloud.google.com/> → create a project.
2. Search **"Gmail API"** → **Enable**.
3. **APIs & Services → OAuth consent screen**:
   - User type **External**; fill in app name + your email.
   - Add the Gmail scope `.../auth/gmail.modify` when prompted (optional at this
     stage — the app requests it at sign-in).
   - While in **Testing** mode, add each person who should be allowed in as a
     **Test user**. To open it to anyone, **Publish** the app (Google may ask
     for verification for sensitive scopes).
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Web application**.
   - **Authorized redirect URI:** `https://YOUR-DOMAIN/oauth2callback`
     (for local testing also add `http://localhost:5000/oauth2callback`).
   - Create → **Download JSON** → this is your `credentials.json`.

> You can add/adjust the redirect URI later once you know your deployed URL.

---

## 2. Run it locally first (recommended)

```bash
cd email-sorter
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: set GEMINI_API_KEY and FLASK_SECRET_KEY
# put your downloaded credentials.json in this folder

python app.py
```

Open <http://localhost:5000>, click **Sign in with Google**, then **Sort**.
(`BASE_URL` defaults to `http://localhost:5000`, and the redirect URI must be
registered in the Google client as shown above.)

---

## 3. Deploy to the web

Set these environment variables on your host:

| Variable | Value |
|---|---|
| `BASE_URL` | your public URL, e.g. `https://email-sorter.onrender.com` (no trailing slash) |
| `GEMINI_API_KEY` | your free Gemini key from Google AI Studio |
| `FLASK_SECRET_KEY` | a long random string (`python -c "import secrets;print(secrets.token_hex(32))"`) |
| `CLIENT_SECRET_FILE` | path to your uploaded `credentials.json` |
| `DATA_DIR` | a path on a **persistent disk** so tokens survive restarts |
| `GEMINI_MODEL` | optional, defaults to `gemini-2.0-flash` |
| `MAX_EMAILS` | optional, defaults to `40` |

Then, back in the Google OAuth client, make sure the **Authorized redirect
URI** is `https://YOUR-DOMAIN/oauth2callback`.

### Option A — Render (config included)

This repo ships a `render.yaml`. In Render: **New + → Blueprint**, point at the
repo, then in the dashboard upload `credentials.json` as a **Secret File**, set
`BASE_URL` to the URL Render assigns, and paste your `GEMINI_API_KEY`.
`FLASK_SECRET_KEY` is generated for you and a 1 GB persistent disk is mounted at
`/data`.

### Option B — Docker (any host)

```bash
docker build -t email-sorter .
docker run -p 5000:5000 \
  -e BASE_URL="https://your-domain" \
  -e GEMINI_API_KEY="your-gemini-key" \
  -e FLASK_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')" \
  -e CLIENT_SECRET_FILE="/data/credentials.json" \
  -v "$PWD/data:/data" \
  email-sorter
```

(Place `credentials.json` in `./data` before running, or bake it in another way.)

### Option C — Any Procfile host (Railway, Heroku-style)

A `Procfile` is included: `web: gunicorn app:app ...`. Set the same env vars.

---

## Using it

1. Go to your URL → **Sign in with Google** (this is your account; it becomes
   your first sortable inbox).
2. **⚡ Sort newest emails** — AI classifies your recent inbox into the four
   columns.
3. **🏷️ Apply labels in Gmail** — creates `Sorter/…` labels and tags each email.
4. **⬇ CSV / HTML** — download a ranked report.
5. **+ Connect another inbox** to add more of your own Gmail accounts; use the
   dropdown to switch which one you're sorting. **Disconnect** removes local
   access only (nothing in Gmail is deleted). **Sign out** ends your session.

---

## Files

| File | Purpose |
|---|---|
| `app.py` | Flask routes: login, OAuth, dashboard, sort, labels, export |
| `gmail_client.py` | Web OAuth, per-user token storage, fetch, labeling |
| `classifier.py` | AI urgency/importance scoring (Gemini, free tier) |
| `report.py` | CSV / HTML export |
| `config.py` | Settings from environment |
| `templates/` | `login.html`, `dashboard.html` |
| `Dockerfile`, `Procfile`, `render.yaml` | Deployment |
| `data/users/<user>/` | Per-user tokens + cached sorts (git-ignored) |

---

## Security & privacy notes

- Gmail scope is `gmail.modify` — read and label only, **never delete**.
- `credentials.json`, `.env`, and `data/` are git-ignored. Never commit them.
- Set a strong `FLASK_SECRET_KEY`; it protects everyone's login sessions.
- Cookies are marked Secure automatically when `BASE_URL` is `https://`.
- Users revoke access anytime at <https://myaccount.google.com/permissions>,
  and inside the app via **Disconnect**.
- The current build stores per-user data on the server's local disk. For larger
  multi-user use, move token/session storage to a database and encrypt tokens
  at rest.

---

## Troubleshooting

- **`redirect_uri_mismatch`** — the redirect URI in Google must exactly equal
  `<BASE_URL>/oauth2callback` (scheme, domain, path). Fix `BASE_URL` or the
  Google client.
- **`access_denied`** — add the person as a Test user, or publish the consent
  screen.
- **`credentials.json ... not found`** — set `CLIENT_SECRET_FILE` to where you
  uploaded it.
- **`GEMINI_API_KEY is not set`** — set it in the environment.
- **Sorting is slow** — one AI call per email; lower `MAX_EMAILS`.
