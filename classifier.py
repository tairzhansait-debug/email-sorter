<!doctype html>
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
  .card{padding:.7rem 1rem;border-top:1px solid var(--line)}
  .card .subj{font-weight:600;font-size:.92rem;margin-bottom:.15rem}
  .card .from{color:var(--muted);font-size:.8rem;margin-bottom:.3rem}
  .card .reason{color:var(--muted);font-size:.8rem;font-style:italic}
  .scores{font-size:.72rem;color:var(--muted);margin-top:.35rem}
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
      <code>.env</code> file (or host settings) to enable AI sorting.</div>
  {% endif %}

  {% if not accounts %}
    <div class="banner">👋 No Gmail account connected yet. Click
      <strong>“+ Add account”</strong> to authorize one. You can add several and
      switch between them anytime.</div>
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
        <div class="card">
          <div class="subj">{{ e.subject }}</div>
          <div class="from">{{ e.sender }}</div>
          {% if e.reason %}<div class="reason">{{ e.reason }}</div>{% endif %}
          <div class="scores">
            <span class="pill">Urgency {{ e.urgency }}/5</span>
            <span class="pill">Importance {{ e.importance }}/5</span>
          </div>
        </div>
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
