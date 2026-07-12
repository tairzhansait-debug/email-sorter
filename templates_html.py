"""HTML pages for the app, kept inline so there are no separate template files
to upload. Rendered with Flask's render_template_string (same Jinja syntax as
normal templates)."""

LOGIN_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Email Sorter — Sign in</title>
<style>
  :root{--bg:#0f1115;--panel:#181b22;--text:#e6e8ec;--muted:#9aa2b1;
        --line:#2a2f3a;--accent:#4f8cff}
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;
       background:radial-gradient(1200px 600px at 50% -10%,#1b2640,#0f1115);color:var(--text)}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:16px;
        padding:2.25rem;max-width:420px;width:calc(100% - 2rem);text-align:center;
        box-shadow:0 20px 60px rgba(0,0,0,.4)}
  h1{font-size:1.5rem;margin:.25rem 0 .5rem}
  p{color:var(--muted);line-height:1.5}
  .btn{display:inline-flex;align-items:center;gap:.6rem;background:#fff;color:#1a1a1a;
       border:0;border-radius:10px;padding:.7rem 1.1rem;font-weight:600;font-size:1rem;
       cursor:pointer;text-decoration:none;margin-top:1rem}
  .g{width:20px;height:20px}
  .matrix{display:grid;grid-template-columns:1fr 1fr;gap:.4rem;margin:1.5rem 0}
  .q{border-radius:10px;padding:.6rem;font-size:.72rem;font-weight:600;color:#fff}
  .q1{background:#e11d48}.q3{background:#f59e0b;color:#1a1a1a}
  .q2{background:#3b82f6}.q4{background:#6b7280}
  .warn{background:#2a1f08;border:1px solid #713f12;color:#fde68a;padding:.6rem;
        border-radius:8px;font-size:.8rem;margin-top:1rem}
  .fine{font-size:.72rem;color:var(--muted);margin-top:1.25rem}
  a{color:var(--accent)}
</style>
</head>
<body>
  <div class="card">
    <h1>📥 Email Sorter</h1>
    <p>Sort your Gmail inbox by <strong>urgency</strong> and <strong>importance</strong>
       with AI — then label it and export a report.</p>
    <div class="matrix">
      <div class="q q1">Urgent &amp; Important</div>
      <div class="q q3">Urgent, Not Important</div>
      <div class="q q2">Important, Not Urgent</div>
      <div class="q q4">Neither</div>
    </div>
    <a class="btn" href="{{ url_for('authorize') }}">
      <svg class="g" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.9 2.4 30.3 0 24 0 14.6 0 6.4 5.4 2.5 13.3l7.9 6.1C12.3 13.2 17.7 9.5 24 9.5z"/><path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.5 3-2.2 5.5-4.7 7.2l7.3 5.7C43.9 38 46.5 31.9 46.5 24.5z"/><path fill="#FBBC05" d="M10.4 28.6c-.5-1.5-.8-3-.8-4.6s.3-3.1.8-4.6l-7.9-6.1C.9 16.5 0 20.1 0 24s.9 7.5 2.5 10.7l7.9-6.1z"/><path fill="#34A853" d="M24 48c6.3 0 11.6-2.1 15.5-5.7l-7.3-5.7c-2 1.4-4.7 2.3-8.2 2.3-6.3 0-11.7-3.7-13.6-9.1l-7.9 6.1C6.4 42.6 14.6 48 24 48z"/></svg>
      Sign in with Google
    </a>
    {% if not has_api_key %}
      <div class="warn">⚠️ Server note: <code>GEMINI_API_KEY</code> is not set,
        so AI sorting is disabled until the admin configures it.</div>
    {% endif %}
    <p class="fine">We request read + label access only — the app can never delete
      your mail. Your data stays on this server and is isolated per account.</p>
  </div>
</body>
</html>
"""


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Email Sorter</title>
<style>
  :root{
    --bg:#0f1115; --panel:#181b22; --panel2:#1f232c; --text:#e6e8ec;
    --muted:#9aa2b1; --line:#2a2f3a; --accent:#4f8cff;
    --ui:#e11d48; --u:#f59e0b; --i:#3b82f6; --n:#6b7280;
  }
  *{box-sizing:border-box}
  body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;
       background:var(--bg);color:var(--text)}
  header{display:flex;align-items:center;gap:1rem;flex-wrap:wrap;
         padding:1rem 1.5rem;border-bottom:1px solid var(--line);background:var(--panel)}
  h1{font-size:1.1rem;margin:0;font-weight:600}
  .spacer{flex:1}
  form.inline{display:inline-flex;gap:.5rem;align-items:center;margin:0}
  select,button,input{font:inherit}
  select,input{background:var(--panel2);color:var(--text);border:1px solid var(--line);
        border-radius:8px;padding:.45rem .6rem}
  button{background:var(--accent);color:#fff;border:0;border-radius:8px;
         padding:.5rem .85rem;cursor:pointer;font-weight:500}
  button.secondary{background:var(--panel2);border:1px solid var(--line);color:var(--text)}
  button.danger{background:transparent;border:1px solid #7f1d1d;color:#fca5a5}
  main{padding:1.5rem;max-width:1200px;margin:0 auto}
  .toolbar{display:flex;gap:.6rem;flex-wrap:wrap;align-items:center;margin-bottom:1.25rem}
  .flash{padding:.6rem .9rem;border-radius:8px;margin:.4rem 0;font-size:.9rem}
  .flash.success{background:#0d2818;color:#86efac;border:1px solid #14532d}
  .flash.error{background:#2a1113;color:#fca5a5;border:1px solid #7f1d1d}
  .flash.info,.flash{background:#111a2e;color:#bfdbfe;border:1px solid #1e3a5f}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem}
  .col{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
  .col h2{font-size:.85rem;margin:0;padding:.75rem 1rem;display:flex;justify-content:space-between;
          align-items:center;color:#fff}
  .col .count{background:rgba(0,0,0,.25);border-radius:20px;padding:.1rem .55rem;font-size:.8rem}
  .col.urgent_important h2{background:var(--ui)}
  .col.urgent h2{background:var(--u);color:#1a1a1a}
  .col.important h2{background:var(--i)}
  .col.neither h2{background:var(--n)}
  .card{border-top:1px solid var(--line)}
  details.card>summary{padding:.7rem 1rem;cursor:pointer;list-style:none;outline:none}
  details.card>summary::-webkit-details-marker{display:none}
  details.card>summary::after{content:"▸ click to read";float:right;color:var(--muted);
        font-size:.7rem;margin-top:.15rem}
  details.card[open]>summary{background:var(--panel2)}
  details.card[open]>summary::after{content:"▾ hide"}
  .card .subj{font-weight:600;font-size:.92rem;margin-bottom:.15rem}
  .card .from{color:var(--muted);font-size:.8rem;margin-bottom:.3rem}
  .card .reason{color:var(--muted);font-size:.8rem;font-style:italic}
  .scores{font-size:.72rem;color:var(--muted);margin-top:.35rem}
  .ebody{padding:.6rem 1rem;white-space:pre-wrap;word-break:break-word;
        font-size:.82rem;line-height:1.45;color:#c9cfda;max-height:300px;overflow:auto;
        border-top:1px dashed var(--line);background:#12151c}
  .elink{display:inline-block;margin:.55rem 1rem .75rem;font-size:.8rem}
  .pill{display:inline-block;background:var(--panel2);border:1px solid var(--line);
        border-radius:6px;padding:.05rem .4rem;margin-right:.3rem}
  .empty{padding:1.25rem 1rem;color:var(--muted);font-size:.85rem}
  .banner{background:#2a1f08;border:1px solid #713f12;color:#fde68a;padding:.75rem 1rem;
          border-radius:10px;margin-bottom:1rem;font-size:.9rem}
  a{color:var(--accent)}
  .muted{color:var(--muted);font-size:.85rem}
</style>
</head>
<body>
<header>
  <h1>📥 Email Sorter</h1>
  {% if accounts %}
  <form class="inline" method="post" action="{{ url_for('switch') }}">
    <select name="account" onchange="this.form.submit()" title="Inbox being sorted">
      {% for a in accounts %}
        <option value="{{ a }}" {{ 'selected' if a == account }}>{{ a }}</option>
      {% endfor %}
    </select>
  </form>
  {% endif %}
  <a class="inline" href="{{ url_for('authorize') }}">
    <button class="secondary" type="button">+ Connect another inbox</button>
  </a>
  {% if account %}
  <form class="inline" method="post" action="{{ url_for('remove_account') }}"
        onsubmit="return confirm('Disconnect {{ account }}? (removes local access only — nothing in Gmail is deleted)')">
    <input type="hidden" name="account" value="{{ account }}">
    <button class="danger" type="submit">Disconnect</button>
  </form>
  {% endif %}
  <div class="spacer"></div>
  <span class="muted">👤 {{ user_id }}</span>
  <a href="{{ url_for('logout') }}"><button class="secondary" type="button">Sign out</button></a>
</header>

<main>
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for category, msg in messages %}
      <div class="flash {{ category }}">{{ msg }}</div>
    {% endfor %}
  {% endwith %}

  {% if not has_api_key %}
    <div class="banner">⚠️ No <code>GEMINI_API_KEY</code> found. Add it to your
      host settings to enable AI sorting.</div>
  {% endif %}

  {% if not accounts %}
    <div class="banner">👋 No Gmail account connected yet. Click
      <strong>“+ Connect another inbox”</strong> to authorize one. You can add
      several and switch between them anytime.</div>
  {% endif %}

  <div class="toolbar">
    <form class="inline" method="post" action="{{ url_for('sort_emails') }}">
      <button type="submit" {{ 'disabled' if not account or not has_api_key }}>
        ⚡ Sort {{ max_emails }} newest emails
      </button>
    </form>
    <form class="inline" method="post" action="{{ url_for('apply_labels') }}">
      <button class="secondary" type="submit" {{ 'disabled' if not total }}>
        🏷️ Apply labels in Gmail
      </button>
    </form>
    <a href="{{ url_for('export', fmt='csv') }}"><button class="secondary" {{ 'disabled' if not total }}>⬇ CSV</button></a>
    <a href="{{ url_for('export', fmt='html') }}"><button class="secondary" {{ 'disabled' if not total }}>⬇ HTML</button></a>
    <span class="spacer"></span>
    <span class="muted">{{ total }} sorted</span>
  </div>

  <div class="grid">
    {% for cat in category_order %}
    <section class="col {{ cat }}">
      <h2>{{ category_labels[cat] }} <span class="count">{{ buckets[cat]|length }}</span></h2>
      {% if buckets[cat] %}
        {% for e in buckets[cat] %}
        <details class="card">
          <summary>
            <div class="subj">{{ e.subject }}</div>
            <div class="from">{{ e.sender }}</div>
            {% if e.reason %}<div class="reason">{{ e.reason }}</div>{% endif %}
            <div class="scores">
              <span class="pill">Urgency {{ e.urgency }}/5</span>
              <span class="pill">Importance {{ e.importance }}/5</span>
            </div>
          </summary>
          <div class="ebody">{{ e.body or e.snippet or 'No preview available.' }}</div>
          <a class="elink" target="_blank" rel="noopener"
             href="https://mail.google.com/mail/?authuser={{ account }}#all/{{ e.id }}">
             Open in Gmail ↗</a>
        </details>
        {% endfor %}
      {% else %}
        <div class="empty">Nothing here.</div>
      {% endif %}
    </section>
    {% endfor %}
  </div>
</main>
</body>
</html>
"""
