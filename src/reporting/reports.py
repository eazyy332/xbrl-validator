from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Iterable, Dict, Any, List


def _summarize(messages: Iterable[dict]) -> dict:
    by_level: Counter[str] = Counter()
    by_code: Counter[str] = Counter()
    total = 0
    for m in messages:
        total += 1
        lvl = (m.get("level") or m.get("severity") or "INFO").upper()
        by_level[lvl] += 1
        code = (m.get("code") or "").strip()
        if code:
            by_code[code] += 1
    return {
        "total": total,
        "byLevel": dict(by_level),
        "byCode": dict(by_code.most_common()),
    }


def write_excel_report(messages: List[dict], exports_dir: str, formula_rows: List[dict] | None = None, summary: Dict[str, Any] | None = None) -> str:
    try:
        import xlsxwriter  # type: ignore
    except Exception as e:
        raise RuntimeError("xlsxwriter is required to write Excel reports. pip install xlsxwriter") from e

    exp = Path(exports_dir)
    exp.mkdir(parents=True, exist_ok=True)
    out_path = exp / "validation_report.xlsx"

    summ = summary or _summarize(messages)
    by_code_sorted = list(summ.get("byCode", {}).items())

    wb = xlsxwriter.Workbook(str(out_path))
    fmt_title = wb.add_format({"bold": True, "font_size": 14})
    fmt_hdr = wb.add_format({"bold": True, "bg_color": "#D9D9D9", "border": 1})
    fmt_cell = wb.add_format({"border": 1})

    # Summary sheet
    ws = wb.add_worksheet("Summary")
    ws.write(0, 0, "Validation Summary", fmt_title)
    # License banner
    try:
        from xbrl_validator.license import licensed_to_text, watermark_text
        lic_line = licensed_to_text()
        mark = watermark_text()
    except Exception:
        lic_line = ""
        mark = None
    if lic_line:
        ws.write(1, 0, lic_line)
    if mark:
        fmt_warn = wb.add_format({"font_color": "#C00000"})
        ws.write(1, 2, mark, fmt_warn)
    ws.write(3, 0, "Total Messages")
    ws.write(3, 1, summ.get("total", 0))
    ws.write(5, 0, "By Severity", fmt_hdr)
    ws.write(5, 1, "Count", fmt_hdr)
    row = 6
    for lvl, cnt in (summ.get("byLevel", {}) or {}).items():
        ws.write(row, 0, lvl, fmt_cell)
        ws.write(row, 1, cnt, fmt_cell)
        row += 1
    ws.write(row + 1, 0, "Top Codes", fmt_hdr)
    ws.write(row + 1, 1, "Count", fmt_hdr)
    r = row + 2
    for code, cnt in by_code_sorted[:50]:
        ws.write(r, 0, code, fmt_cell)
        ws.write(r, 1, cnt, fmt_cell)
        r += 1

    # ByCode sheet (full)
    ws2 = wb.add_worksheet("ByCode")
    ws2.write(0, 0, "Code", fmt_hdr)
    ws2.write(0, 1, "Count", fmt_hdr)
    r = 1
    for code, cnt in by_code_sorted:
        ws2.write(r, 0, code, fmt_cell)
        ws2.write(r, 1, cnt, fmt_cell)
        r += 1
    ws2.autofilter(0, 0, max(1, r - 1), 1)
    ws2.set_column(0, 0, 60)
    ws2.set_column(1, 1, 12)

    # Messages sheet
    ws3 = wb.add_worksheet("Messages")
    headers = [
        "level", "code", "message", "file", "modelDocument", "line", "col",
        "fact", "context", "unit", "dpm_template", "dpm_table", "dpm_table_version",
        "dpm_cell", "dpm_axis", "dpm_member"
    ]
    for c, h in enumerate(headers):
        ws3.write(0, c, h, fmt_hdr)
    for r, m in enumerate(messages, start=1):
        ws3.write(r, 0, (m.get("level") or "").upper(), fmt_cell)
        ws3.write(r, 1, m.get("code") or "", fmt_cell)
        ws3.write(r, 2, m.get("message") or "", fmt_cell)
        ws3.write(r, 3, m.get("file") or m.get("file_path") or "", fmt_cell)
        ws3.write(r, 4, m.get("modelDocument") or "", fmt_cell)
        ws3.write(r, 5, m.get("line") or "", fmt_cell)
        ws3.write(r, 6, m.get("col") or "", fmt_cell)
        ws3.write(r, 7, m.get("fact") or m.get("fact_qname") or "", fmt_cell)
        ws3.write(r, 8, m.get("context") or m.get("context_ref") or "", fmt_cell)
        ws3.write(r, 9, m.get("unit") or m.get("unit_ref") or "", fmt_cell)
        ws3.write(r, 10, m.get("dpm_template") or "", fmt_cell)
        ws3.write(r, 11, m.get("dpm_table") or "", fmt_cell)
        ws3.write(r, 12, m.get("dpm_table_version") or "", fmt_cell)
        ws3.write(r, 13, m.get("dpm_cell") or "", fmt_cell)
        ws3.write(r, 14, m.get("dpm_axis") or "", fmt_cell)
        ws3.write(r, 15, m.get("dpm_member") or "", fmt_cell)
    ws3.autofilter(0, 0, max(1, len(messages)), len(headers) - 1)
    ws3.set_column(0, 0, 10)
    ws3.set_column(1, 1, 40)
    ws3.set_column(2, 2, 120)
    ws3.set_column(3, 3, 60)

    # Filing Rules sheet (subset of messages with EBA.* codes)
    fr_msgs = [m for m in messages if str(m.get("code") or "").upper().startswith("EBA.") or str(m.get("code") or "").upper().startswith("EBA_")]
    if fr_msgs:
        ws5 = wb.add_worksheet("Filing Rules")
        headers_fr = [
            "level", "code", "message", "table", "template", "rule_id", "framework",
            "prereq", "cond_expr", "applicability", "docUri", "_sheet", "_row",
            "fi_status", "eval_result"
        ]
        for c, h in enumerate(headers_fr):
            ws5.write(0, c, h, fmt_hdr)
        for r, m in enumerate(fr_msgs, start=1):
            ws5.write(r, 0, (m.get("level") or "").upper(), fmt_cell)
            ws5.write(r, 1, m.get("code") or "", fmt_cell)
            ws5.write(r, 2, m.get("message") or "", fmt_cell)
            ws5.write(r, 3, m.get("table") or "", fmt_cell)
            ws5.write(r, 4, m.get("template") or "", fmt_cell)
            ws5.write(r, 5, m.get("id") or m.get("rule_id") or "", fmt_cell)
            ws5.write(r, 6, m.get("framework") or "", fmt_cell)
            ws5.write(r, 7, m.get("prereq") or "", fmt_cell)
            ws5.write(r, 8, m.get("cond_expr") or "", fmt_cell)
            ws5.write(r, 9, m.get("applicability") or "", fmt_cell)
            ws5.write(r, 10, m.get("docUri") or m.get("file") or m.get("file_path") or "", fmt_cell)
            ws5.write(r, 11, m.get("_sheet") or "", fmt_cell)
            ws5.write(r, 12, m.get("_row") or "", fmt_cell)
            fi = m.get("filing_indicators") or []
            ws5.write(r, 13, ",".join(map(str, fi)) if fi else "", fmt_cell)
            eval_res = "FAILED" if "condition not satisfied" in (m.get("message") or "").lower() else "OK"
            ws5.write(r, 14, eval_res, fmt_cell)
        ws5.autofilter(0, 0, max(1, len(fr_msgs)), len(headers_fr) - 1)
        ws5.set_column(0, 14, 16)

    # Formula sheet (optional)
    if formula_rows:
        ws4 = wb.add_worksheet("Formula")
        if formula_rows:
            cols = sorted({k for row in formula_rows for k in row.keys()})
        else:
            cols = []
        for c, h in enumerate(cols):
            ws4.write(0, c, h, fmt_hdr)
        for r, row in enumerate(formula_rows or [], start=1):
            for c, h in enumerate(cols):
                ws4.write(r, c, row.get(h), fmt_cell)
        if cols:
            ws4.autofilter(0, 0, max(1, len(formula_rows or [])), len(cols) - 1)

    wb.close()
    return str(out_path)


def write_pdf_summary(summary: Dict[str, Any], exports_dir: str, top_n: int = 25, messages: List[dict] | None = None) -> str:
    try:
        from reportlab.lib.pagesizes import A4  # type: ignore
        from reportlab.lib import colors  # type: ignore
        from reportlab.lib.styles import getSampleStyleSheet  # type: ignore
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle  # type: ignore
    except Exception as e:
        raise RuntimeError("reportlab is required to write PDF reports. pip install reportlab") from e

    exp = Path(exports_dir)
    exp.mkdir(parents=True, exist_ok=True)
    out_path = exp / "validation_summary.pdf"

    doc = SimpleDocTemplate(str(out_path), pagesize=A4, title="XBRL Validation Summary")
    styles = getSampleStyleSheet()
    story: list = []
    story.append(Paragraph("XBRL Validation Summary", styles["Title"]))
    # License banner
    try:
        from xbrl_validator.license import licensed_to_text, watermark_text
        lic_line = licensed_to_text()
        mark = watermark_text()
    except Exception:
        lic_line = ""
        mark = None
    if lic_line:
        story.append(Paragraph(lic_line, styles["Normal"]))
    if mark:
        story.append(Paragraph(f"<font color='#C00000'>{mark}</font>", styles["Normal"]))
    story.append(Spacer(1, 12))

    # Totals
    total = summary.get("total", 0)
    by_level = summary.get("byLevel", {}) or {}
    story.append(Paragraph(f"Total messages: <b>{total}</b>", styles["Normal"]))
    lvl_rows = [["Severity", "Count"]] + [[k, v] for k, v in by_level.items()]
    tbl = Table(lvl_rows, hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ]))
    story.append(Spacer(1, 6))
    story.append(tbl)
    story.append(Spacer(1, 12))

    # Top codes
    by_code = list((summary.get("byCode", {}) or {}).items())[:top_n]
    code_rows = [["Code", "Count"]] + [[c, n] for c, n in by_code]
    tbl2 = Table(code_rows, hAlign="LEFT")
    tbl2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ]))
    story.append(Paragraph("Top message codes", styles["Heading2"]))
    story.append(Spacer(1, 6))
    story.append(tbl2)
    # Breakdown per severity with top codes (only if messages provided)
    if messages is not None:
        story.append(Spacer(1, 12))
        story.append(Paragraph("Breakdown per Severity", styles["Heading2"]))
        for lvl in sorted(by_level.keys()):
            lvl_msgs = [m for m in messages if (m.get("level") or "").upper() == lvl]
            lvl_summ = _summarize(lvl_msgs)
            lvl_by_code = list(lvl_summ.get("byCode", {}).items())[:20]
            story.append(Paragraph(f"{lvl} (Total: {by_level.get(lvl, 0)})", styles["Heading3"]))
            if lvl_by_code:
                lvl_rows = [["Code", "Count"]] + [[c, n] for c, n in lvl_by_code]
                tbl_lvl = Table(lvl_rows, hAlign="LEFT")
                tbl_lvl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ]))
                story.append(Spacer(1, 6))
                story.append(tbl_lvl)
            else:
                story.append(Paragraph("No messages for this severity.", styles["Normal"]))
            story.append(Spacer(1, 12))

    doc.build(story)
    return str(out_path)


def generate_reports(messages: List[dict], exports_dir: str, formula_rows: List[dict] | None = None, summary: Dict[str, Any] | None = None) -> dict:
    """Create Excel workbook and PDF summary from messages and optional formula rows."""
    summ = summary or _summarize(messages)
    paths = {}
    paths["excel"] = write_excel_report(messages, exports_dir, formula_rows=formula_rows, summary=summ)
    # Write Filing Rules coverage XLSX if CSV exists
    try:
        import csv
        from pathlib import Path as _P
        cov_csv = _P(exports_dir) / "rules_coverage.csv"
        if cov_csv.exists():
            import xlsxwriter  # type: ignore
            wb = xlsxwriter.Workbook(str(_P(exports_dir) / "rules_coverage.xlsx"))
            ws = wb.add_worksheet("Coverage")
            fmt_hdr = wb.add_format({"bold": True, "bg_color": "#D9D9D9", "border": 1})
            fmt_cell = wb.add_format({"border": 1})
            rows: list[list[str]] = []
            with open(cov_csv, "r", encoding="utf-8") as f:
                rdr = csv.reader(f)
                for r in rdr:
                    rows.append(r)
            for r, row in enumerate(rows):
                for c, val in enumerate(row):
                    ws.write(r, c, val, fmt_hdr if r == 0 or (r == 2 and c == 0) else fmt_cell)
            wb.close()
            paths["rules_coverage_xlsx"] = str(_P(exports_dir) / "rules_coverage.xlsx")
    except Exception:
        pass
    try:
        paths["pdf"] = write_pdf_summary(summ, exports_dir, messages=messages)
    except RuntimeError:
        # Allow Excel-only if reportlab unavailable
        paths["pdf"] = ""
    return paths


