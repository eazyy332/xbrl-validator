from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, List, Optional, Tuple

from src.dpm import DpmDb, map_instance, MappedCell


def _stream_jsonl(path: Path) -> Generator[Dict[str, Any], None, None]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def _normalize_entry(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ts": rec.get("ts"),
        "level": (rec.get("level") or "").upper(),
        "code": rec.get("code") or "",
        "message": rec.get("message") or "",
        "ref": rec.get("ref"),
        "modelObjectQname": rec.get("modelObjectQname"),
        "docUri": rec.get("docUri"),
        "line": rec.get("line"),
        "col": rec.get("col"),
        "assertionId": rec.get("assertionId"),
        "assertionSeverity": rec.get("assertionSeverity"),
        "dimensionInfo": rec.get("dimensionInfo"),
    }


def _index_mapping_by_qname(mapped: Iterable[MappedCell]) -> Dict[str, List[MappedCell]]:
    idx: Dict[str, List[MappedCell]] = {}
    for m in mapped:
        qn = m.fact_qname or ""
        if not qn:
            continue
        idx.setdefault(qn, []).append(m)
    return idx


def ingest_jsonl(
    jsonl_path: str,
    dpm_sqlite: Optional[str] = None,
    dpm_schema: str = "dpm35_10",
    model_xbrl_path: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, List[Dict[str, Any]]]]:
    """
    Ingest Arelle JSONL logs, normalize fields, and optionally enrich with DPM-mapped cells.
    Returns: (messages, rollup, grouped_by_file)
    """
    p = Path(jsonl_path)
    raw_entries = list(_stream_jsonl(p))
    msgs = [_normalize_entry(e) for e in raw_entries]

    # Optional deterministic mapping
    mapping_idx: Dict[str, List[MappedCell]] = {}
    if dpm_sqlite and model_xbrl_path:
        try:
            import arelle.Cntlr as C
            cntlr = C.Cntlr(logFileName=None)
            modelXbrl = cntlr.modelManager.load(model_xbrl_path)
            if modelXbrl is not None:
                db = DpmDb(dpm_sqlite, schema_prefix=dpm_schema)
                try:
                    mapped, _warns = map_instance(modelXbrl, db)
                finally:
                    db.close()
                mapping_idx = _index_mapping_by_qname(mapped)
        except Exception:
            mapping_idx = {}

    # Attach first matching mapped cell by qname
    for m in msgs:
        qn = m.get("modelObjectQname") or ""
        if qn and qn in mapping_idx and mapping_idx[qn]:
            mc = mapping_idx[qn][0]
            m["mappedCell"] = {
                "template_id": mc.template_id,
                "table_id": mc.table_id,
                "table_version": mc.table_version,
                "cell_id": mc.cell_id,
                "axes": mc.axes,
                "concept": mc.concept,
                "period": mc.period,
                "unit": mc.unit,
            }

    # Rollups
    by_sev: Dict[str, int] = {}
    by_code: Dict[str, int] = {}
    for m in msgs:
        sev = m["level"] or "INFO"
        by_sev[sev] = by_sev.get(sev, 0) + 1
        code = m["code"] or ""
        if code:
            by_code[code] = by_code.get(code, 0) + 1
    rollup = {
        "total": len(msgs),
        "bySeverity": by_sev,
        "byCode": dict(sorted(by_code.items(), key=lambda kv: kv[1], reverse=True)),
    }

    # Grouped by file
    by_file: Dict[str, List[Dict[str, Any]]] = {}
    for m in msgs:
        doc = m.get("docUri") or "(unknown)"
        by_file.setdefault(doc, []).append(m)

    return msgs, rollup, by_file


def write_validation_messages_csv(messages: Iterable[Dict[str, Any]], out_path: str) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "ts",
                "level",
                "code",
                "message",
                "docUri",
                "line",
                "col",
                "modelObjectQname",
                "assertionId",
                "assertionSeverity",
            ],
        )
        w.writeheader()
        for m in messages:
            w.writerow({k: m.get(k) for k in w.fieldnames})


def write_results_by_file_json(grouped: Dict[str, List[Dict[str, Any]]], out_path: str) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(grouped, f, ensure_ascii=False, indent=2)


def write_formula_rollup_csv(messages: Iterable[Dict[str, Any]], out_path: str) -> None:
    counts: Dict[Tuple[str, str], int] = {}
    for m in messages:
        a = m.get("assertionId") or ""
        s = (m.get("assertionSeverity") or "").lower()
        # If severity is missing but message signals assertion status, infer it
        if not s:
            msg = (m.get("message") or "").lower()
            if "assertion" in msg and ("unsatisfied" in msg or "violation" in msg):
                s = "unsatisfied"
            elif "assertion" in msg and ("satisfied" in msg or "evaluated" in msg):
                s = "satisfied"
        if not a and not s:
            continue
        key = (a, s)
        counts[key] = counts.get(key, 0) + 1
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["assertionId", "severity", "count"])
        for (a, s), c in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
            w.writerow([a, s, c])


