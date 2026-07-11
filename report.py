"""Export sorted emails to CSV and HTML reports."""
from __future__ import annotations

import csv
import html
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import config

if TYPE_CHECKING:
    from gmail_client import Email

REPORTS_DIR = config.DATA_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _sorted_for_report(emails: list["Email"]) -> list["Email"]:
    order = {c: i for i, c in enumerate(config.CATEGORY_ORDER)}
    return sorted(
        emails,
        key=lambda e: (
            order.get(e.category or "neither", 99),
            -((e.urgency or 0) + (e.importance or 0)),
        ),
    )


def export_csv(emails: list["Email"], account: str) -> Path:
    path = REPORTS_DIR / f"report_{account}_{_timestamp()}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["Category", "Urgency", "Importance", "Sender", "Email", "Subject", "Reason", "Date"]
        )
        for e in _sorted_for_report(emails):
            writer.writerow(
                [
                    config.CATEGORY_LABELS.get(e.category or "neither", ""),
                    e.urgency,
                    e.importance,
                    e.sender,
                    e.sender_email,
                    e.subject,
                    e.reason,
                    e.date,
                ]
            )
    return path


def export_html(emails: list["Email"], account: str) -> Path:
    path = REPORTS_DIR / f"report_{account}_{_timestamp()}.html"
    rows = []
    for e in _sorted_for_report(emails):
        rows.append(
            "<tr>"
            f"<td>{html.escape(config.CATEGORY_LABELS.get(e.category or 'neither', ''))}</td>"
            f"<td style='text-align:center'>{e.urgency}</td>"
            f"<td style='text-align:center'>{e.importance}</td>"
            f"<td>{html.escape(e.sender)}</td>"
            f"<td>{html.escape(e.subject)}</td>"
            f"<td>{html.escape(e.reason)}</td>"
            "</tr>"
        )
    doc = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Email Sort Report</title>
<style>
 body{{font-family:system-ui,Arial,sans-serif;margin:2rem;color:#1a1a1a}}
 h1{{font-size:1.4rem}}
 table{{border-collapse:collapse;width:100%;font-size:.9rem}}
 th,td{{border:1px solid #ddd;padding:.5rem;text-align:left;vertical-align:top}}
 th{{background:#f5f5f7}}
 tr:nth-child(even){{background:#fafafa}}
</style></head><body>
<h1>Email Sort Report &mdash; {html.escape(account)}</h1>
<p>Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} &middot; {len(emails)} emails</p>
<table>
<tr><th>Category</th><th>Urg.</th><th>Imp.</th><th>Sender</th><th>Subject</th><th>Reason</th></tr>
{''.join(rows)}
</table></body></html>"""
    path.write_text(doc, encoding="utf-8")
    return path
