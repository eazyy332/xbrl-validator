from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def build_aliases(sqlite_path: str, schema_prefix: str = "dpm35_10") -> dict:
    aliases: dict[str, str] = {}
    if not Path(sqlite_path).exists():
        return {"aliases": aliases}
    try:
        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row
    except Exception:
        return {"aliases": aliases}
    try:
        # Common mapping: originaltablecode -> xbrltablecode (or canonical code)
        rows = conn.execute(
            f"""
            SELECT TV.tableversioncode, TV.tableversionlabel, TV.xbrltablecode,
                   T.templatecode, T.templatelabel
            FROM {schema_prefix}_tableversion AS TV
            LEFT JOIN {schema_prefix}_template AS T ON T.conceptid = TV.conceptid
            """
        ).fetchall()
        for r in rows:
            orig = ""  # not present in this schema
            xbrl = (r["xbrltablecode"] or "").strip()
            ver = (r["tableversioncode"] or "").strip()
            templ = (r["templatecode"] or "").strip()
            canonical = xbrl or ver or orig
            if not canonical:
                continue
            # Normalize typical forms to canonical
            for k in (xbrl, xbrl.lower(), ver, ver.lower(), templ, templ.lower(), templ.replace(" ", "")):
                if k and k not in aliases:
                    aliases[k] = canonical
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return {"aliases": aliases}


def main() -> int:
    out = Path("config/table_aliases.json")
    data = build_aliases("assets/dpm.sqlite", schema_prefix="dpm35_10")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[aliases] wrote {out} with {len(data.get('aliases', {}))} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


