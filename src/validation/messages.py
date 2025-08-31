from __future__ import annotations

from typing import Dict, Any


def humanize_message(m: Dict[str, Any]) -> str:
    """Create a friendlier message using DPM enrichment when present."""
    sev = (m.get("level") or "").upper()
    code = m.get("code") or ""
    base = m.get("message") or ""
    mc = m.get("mappedCell") or {}
    dpm_template = mc.get("template_id") or m.get("dpm_template")
    dpm_table = mc.get("table_id") or m.get("dpm_table")
    dpm_cell = mc.get("cell_id") or m.get("dpm_cell")
    parts: list[str] = []
    if dpm_template:
        parts.append(f"Template {dpm_template}")
    if dpm_table:
        parts.append(f"Table {dpm_table}")
    if dpm_cell:
        parts.append(f"Cell {dpm_cell}")
    where = " | ".join(parts)
    if where:
        return f"[{sev}] {code} at {where}: {base}"
    return f"[{sev}] {code}: {base}"


