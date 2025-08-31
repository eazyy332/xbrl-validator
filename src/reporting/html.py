from __future__ import annotations

from pathlib import Path
from typing import Iterable, Dict, Any
import html


def write_html_summary(messages: Iterable[Dict[str, Any]], out_path: str, summary: Dict[str, Any] | None = None) -> str:
    msgs = list(messages)
    summ = summary or {
        "total": len(msgs),
        "byLevel": {},
    }
    by_level = summ.get("byLevel", {})
    rows = []
    for m in msgs[:2000]:  # cap to keep file light
        sev = html.escape((m.get("level") or "").upper())
        code = html.escape(m.get("code") or "")
        text = html.escape(m.get("message") or "")
        doc = html.escape(m.get("docUri") or m.get("file") or "")
        rows.append(f"<tr><td>{sev}</td><td>{code}</td><td>{text}</td><td>{doc}</td></tr>")
    table = "\n".join(rows)
    page = f"""
<!doctype html>
<html><head><meta charset='utf-8'><title>XBRL Validation Summary</title>
<style>body{{font-family:sans-serif}} table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #ccc;padding:4px}}</style>
</head><body>
<h1>XBRL Validation Summary</h1>
<p>Total messages: <b>{summ.get('total', len(msgs))}</b></p>
<h2>By severity</h2>
<ul>
{''.join(f"<li>{html.escape(str(k))}: {html.escape(str(v))}</li>" for k,v in (by_level or {}).items())}
</ul>
<h2>Messages (first 2000)</h2>
<table>
<thead><tr><th>Severity</th><th>Code</th><th>Message</th><th>File</th></tr></thead>
<tbody>
{table}
</tbody>
</table>
</body></html>
"""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(page, encoding="utf-8")
    return str(p)


