from __future__ import annotations

import csv
import json
import re
import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Optional


# Arelle text log typically includes lines like:
# INFO|code123|message text (location info)
# ERROR|xbrl.msgCode|Message ... - fact: QName=..., contextRef=..., unitRef=...
_LINE_RE = re.compile(r"^(?P<severity>INFO|WARNING|ERROR|FATAL)\|(?P<code>[^|]+)\|(?P<message>.*)$")
_FACT_QNAME_RE = re.compile(r"QName=([^,\s]+)")
_CONTEXT_REF_RE = re.compile(r"contextRef=([^,\s]+)")
_UNIT_REF_RE = re.compile(r"unitRef=([^,\s]+)")


@dataclass
class ValidationIssue:
    severity: str
    code: str
    message: str
    location: Optional[str] = None
    file_path: Optional[str] = None
    fact_qname: Optional[str] = None
    context_ref: Optional[str] = None
    unit_ref: Optional[str] = None
    taxonomy_ref: Optional[str] = None
    dpm_template: Optional[str] = None
    dpm_table: Optional[str] = None
    dpm_table_version: Optional[str] = None
    dpm_cell: Optional[str] = None
    dpm_axis: Optional[str] = None
    dpm_member: Optional[str] = None


def parse_arelle_text_output(text: str, file_path: Optional[str] = None) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for line in text.splitlines():
        m = _LINE_RE.match(line.strip())
        if not m:
            continue
        severity = m.group("severity")
        code = m.group("code").strip()
        message = m.group("message").strip()

        location: Optional[str] = None
        # Heuristic: extract parentheses or trailing location hints
        if "(" in message and ")" in message:
            try:
                loc = message[message.rindex("(") + 1 : message.rindex(")")]
                if loc and 3 <= len(loc) <= 500:
                    location = loc
            except Exception:
                pass

        # Extract common XBRL fields if present
        fact_qname = None
        m_q = _FACT_QNAME_RE.search(message)
        if m_q:
            fact_qname = m_q.group(1)
        context_ref = None
        m_c = _CONTEXT_REF_RE.search(message)
        if m_c:
            context_ref = m_c.group(1)
        unit_ref = None
        m_u = _UNIT_REF_RE.search(message)
        if m_u:
            unit_ref = m_u.group(1)

        issues.append(ValidationIssue(
            severity=severity,
            code=code,
            message=message,
            location=location,
            file_path=file_path,
            fact_qname=fact_qname,
            context_ref=context_ref,
            unit_ref=unit_ref,
        ))
    return issues


def write_issues_json(issues: Iterable[ValidationIssue], out_path: str) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump([asdict(i) for i in issues], f, ensure_ascii=False, indent=2)


def write_issues_csv(issues: Iterable[ValidationIssue], out_path: str) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(issues)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "severity",
                "code",
                "message",
                "location",
                "file_path",
                "fact_qname",
                "context_ref",
                "unit_ref",
                "taxonomy_ref",
                "dpm_template",
                "dpm_table",
                "dpm_table_version",
                "dpm_cell",
                "dpm_axis",
                "dpm_member",
            ],
        )
        writer.writeheader()
        for i in rows:
            writer.writerow(asdict(i))


def aggregate_counts(issues: Iterable[ValidationIssue]) -> dict:
    counts = {"INFO": 0, "WARNING": 0, "ERROR": 0, "FATAL": 0}
    for i in issues:
        if i.severity in counts:
            counts[i.severity] += 1
    return counts

def enrich_with_dpm(issues: List[ValidationIssue], sqlite_path: str, schema_prefix: str = "dpm35_10") -> List[ValidationIssue]:
    if not Path(sqlite_path).exists():
        return issues
    try:
        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row
    except Exception:
        return issues
    try:
        for i in issues:
            # Prefer the parsed fact_qname field if present
            qname = i.fact_qname
            if not qname:
                m = _FACT_QNAME_RE.search(i.message)
                if m:
                    qname = m.group(1)
            if not qname:
                continue
            local = qname.split(":")[-1]
            # Try a precise join path: concept -> datapoint -> tablecell -> tableversion -> template
            # We do not assume exact column sets; catch exceptions and fall back to heuristics
            mapped = False
            try:
                row = conn.execute(
                    f"""
                    SELECT T.templatecode AS t_code,
                           T.templatelabel AS t_label,
                           TV.tableversioncode AS tv_code,
                           TV.tableversionlabel AS tv_label,
                           TV.xbrltablecode AS tv_xbrl,
                           TC.cellcode AS cell_code,
                           DP.datapointid AS dp_id
                    FROM {schema_prefix}_concept AS C
                    JOIN {schema_prefix}_datapoint AS DP ON C.conceptid = DP.conceptid
                    JOIN {schema_prefix}_tablecell AS TC ON DP.datapointid = TC.datapointid
                    JOIN {schema_prefix}_tableversion AS TV ON TC.tablevid = TV.tablevid
                    JOIN {schema_prefix}_template AS T ON TV.templateid = T.templateid
                    WHERE C.conceptid = ? OR C.conceptcode = ? OR C.conceptname = ?
                    LIMIT 1
                    """,
                    (local, local, local),
                ).fetchone()
                if row:
                    i.dpm_template = f"{row['t_code']}\t{row['t_label']}" if (row["t_code"] or row["t_label"]) else None
                    # Prefer xbrl table code if present, else version code
                    table_label = row["tv_label"]
                    table_code = row["tv_xbrl"] or row["tv_code"]
                    if table_code or table_label:
                        i.dpm_table = f"{table_code}\t{table_label}" if (table_code and table_label) else (table_code or table_label)
                    i.dpm_table_version = row["tv_code"]
                    i.dpm_cell = row["cell_code"]
                    # Try to map axis/member for this datapoint id via common DPM link tables
                    try:
                        dp_id = row["dp_id"]
                        if dp_id is not None:
                            # Attempt several possible schema variants for linking tables
                            # 1) datapointdimension (datapointid -> dimensionid, memberid)
                            link_rows = None
                            for link_table in (
                                f"{schema_prefix}_datapointdimension",
                                f"{schema_prefix}_datapoint_member",
                                f"{schema_prefix}_datapointaxis",
                            ):
                                try:
                                    link_rows = conn.execute(
                                        f"SELECT dimensionid, memberid FROM {link_table} WHERE datapointid = ? LIMIT 1",
                                        (dp_id,),
                                    ).fetchone()
                                except Exception:
                                    link_rows = None
                                if link_rows:
                                    break
                            if link_rows:
                                dim_id = link_rows["dimensionid"] if "dimensionid" in link_rows.keys() else link_rows[0]
                                mem_id = link_rows["memberid"] if "memberid" in link_rows.keys() else link_rows[1]
                                # Dimension label/code
                                try:
                                    dim = conn.execute(
                                        f"SELECT dimensioncode, dimensionlabel FROM {schema_prefix}_dimension WHERE dimensionid = ?",
                                        (dim_id,),
                                    ).fetchone()
                                    if dim:
                                        dcode = dim["dimensioncode"] if "dimensioncode" in dim.keys() else dim[0]
                                        dlabel = dim["dimensionlabel"] if "dimensionlabel" in dim.keys() else (dim[1] if len(dim) > 1 else None)
                                        i.dpm_axis = f"{dcode}\t{dlabel}" if (dcode and dlabel) else (dcode or dlabel)
                                except Exception:
                                    pass
                                # Member label/code
                                try:
                                    mem = conn.execute(
                                        f"SELECT membercode, memberlabel FROM {schema_prefix}_member WHERE memberid = ?",
                                        (mem_id,),
                                    ).fetchone()
                                    if mem:
                                        mcode = mem["membercode"] if "membercode" in mem.keys() else mem[0]
                                        mlabel = mem["memberlabel"] if "memberlabel" in mem.keys() else (mem[1] if len(mem) > 1 else None)
                                        i.dpm_member = f"{mcode}\t{mlabel}" if (mcode and mlabel) else (mcode or mlabel)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    mapped = True
            except Exception:
                mapped = False

            if not mapped:
                # Heuristic fallbacks using LIKE to at least suggest template/table
                try:
                    tmpl = conn.execute(
                        f"SELECT templatecode, templatelabel FROM {schema_prefix}_template WHERE templatecode LIKE ? LIMIT 1",
                        (f"%{local}%",),
                    ).fetchone()
                    if tmpl:
                        i.dpm_template = f"{tmpl['templatecode']}\t{tmpl['templatelabel']}"
                except Exception:
                    pass
                try:
                    tv = conn.execute(
                        f"SELECT xbrltablecode, tableversioncode, tableversionlabel FROM {schema_prefix}_tableversion WHERE xbrltablecode LIKE ? OR tableversioncode LIKE ? LIMIT 1",
                        (f"%{local}%", f"%{local}%"),
                    ).fetchone()
                    if tv:
                        code = tv["xbrltablecode"] or tv["tableversioncode"]
                        label = tv["tableversionlabel"]
                        if code or label:
                            i.dpm_table = f"{code}\t{label}" if (code and label) else (code or label)
                        i.dpm_table_version = tv["tableversioncode"]
                except Exception:
                    pass
                try:
                    cell = conn.execute(
                        f"SELECT cellcode, tablevid FROM {schema_prefix}_tablecell WHERE cellcode LIKE ? LIMIT 1",
                        (f"%{local}%",),
                    ).fetchone()
                    if cell:
                        i.dpm_cell = cell["cellcode"]
                        tv2 = conn.execute(
                            f"SELECT xbrltablecode, tableversionlabel, tableversioncode FROM {schema_prefix}_tableversion WHERE tablevid = ?",
                            (cell["tablevid"],),
                        ).fetchone()
                        if tv2:
                            code = tv2["xbrltablecode"]
                            label = tv2["tableversionlabel"]
                            if code or label:
                                i.dpm_table = f"{code}\t{label}" if (code and label) else (code or label)
                            i.dpm_table_version = tv2["tableversioncode"]
                except Exception:
                    pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return issues

