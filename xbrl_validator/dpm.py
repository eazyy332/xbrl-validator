from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class DpmTemplate:
    templateid: str
    templatecode: str
    templatelabel: str


@dataclass
class DpmTable:
    tableid: str
    originaltablecode: str
    originaltablelabel: str


def _connect(sqlite_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    return conn


def list_templates(sqlite_path: str, schema_prefix: str = "dpm35_10", like: Optional[str] = None, limit: int = 200) -> List[DpmTemplate]:
    conn = _connect(sqlite_path)
    try:
        if like:
            rows = conn.execute(
                f"SELECT templateid, templatecode, templatelabel FROM {schema_prefix}_template WHERE templatecode LIKE ? OR templatelabel LIKE ? LIMIT ?",
                (f"%{like}%", f"%{like}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT templateid, templatecode, templatelabel FROM {schema_prefix}_template LIMIT ?",
                (limit,),
            ).fetchall()
        return [DpmTemplate(r["templateid"], r["templatecode"], r["templatelabel"]) for r in rows]
    finally:
        conn.close()


def list_tables_for_template(sqlite_path: str, templateid: str, schema_prefix: str = "dpm35_10", limit: int = 500) -> List[DpmTable]:
    conn = _connect(sqlite_path)
    try:
        rows = conn.execute(
            f"SELECT tableid, originaltablecode, originaltablelabel FROM {schema_prefix}_table WHERE templateid = ? LIMIT ?",
            (templateid, limit),
        ).fetchall()
        return [DpmTable(r["tableid"], r["originaltablecode"], r["originaltablelabel"]) for r in rows]
    finally:
        conn.close()


def find_entry_for_template_in_package(package_zip_path: str, template_code: str, entries: List[Tuple[str, str]]) -> Optional[Tuple[str, str]]:
    # entries: list of (label, entry_uri)
    lc = template_code.lower()
    # Prefer label match
    for label, uri in entries:
        if lc in (label or "").lower():
            return label, uri
    # Fallback: uri contains code
    for label, uri in entries:
        if lc in (uri or "").lower():
            return label, uri
    return None


