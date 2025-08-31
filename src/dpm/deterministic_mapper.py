from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass
class MappedCell:
    template_id: str
    table_id: str
    table_version: str
    cell_id: str
    axes: Dict[str, str]  # axis_code -> member_code
    concept: str
    period: str
    unit: Optional[str]
    fact_context_id: Optional[str]
    fact_qname: Optional[str]
    source_doc: Optional[str]
    confidence: float = 0.0


@dataclass
class MappingWarning:
    fact_context_id: Optional[str]
    fact_qname: Optional[str]
    message: str


class DpmDb:
    def __init__(self, sqlite_path: str, schema_prefix: str = "dpm35_10") -> None:
        self.sqlite_path = sqlite_path
        self.schema = schema_prefix
        self.conn = sqlite3.connect(sqlite_path)
        self.conn.row_factory = sqlite3.Row
        # Simple caches to reduce repeated lookups
        self._cache_concept_ids: Dict[str, List[str]] = {}
        self._cache_datapoints: Dict[str, List[sqlite3.Row]] = {}
        self._cache_axes: Dict[str, List[Tuple[str, str]]] = {}
        self._cache_cells: Dict[str, List[sqlite3.Row]] = {}

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    # --- Lookups ---
    def resolve_concept_ids(self, concept_local_or_code: str) -> List[str]:
        # Try conceptid, conceptcode, conceptname
        q = concept_local_or_code
        if q in self._cache_concept_ids:
            return self._cache_concept_ids[q]
        rows = self.conn.execute(
            f"""
            SELECT conceptid
            FROM {self.schema}_concept
            WHERE conceptid = ? OR conceptcode = ? OR conceptname = ?
            """,
            (q, q, q),
        ).fetchall()
        vals = [r[0] for r in rows]
        self._cache_concept_ids[q] = vals
        return vals

    def datapoints_for_concept(self, conceptid: str) -> List[sqlite3.Row]:
        if conceptid in self._cache_datapoints:
            return self._cache_datapoints[conceptid]
        rows = self.conn.execute(
            f"SELECT datapointid FROM {self.schema}_datapoint WHERE conceptid = ?",
            (conceptid,),
        ).fetchall()
        self._cache_datapoints[conceptid] = rows
        return rows

    def axes_for_datapoint(self, datapointid: str) -> List[Tuple[str, str]]:
        if datapointid in self._cache_axes:
            return self._cache_axes[datapointid]
        # Try known linking tables between datapoint and (dimension, member)
        candidates = (
            f"{self.schema}_datapointdimension",
            f"{self.schema}_datapoint_member",
            f"{self.schema}_datapointaxis",
        )
        dim_mem: List[Tuple[str, str]] = []
        for link in candidates:
            try:
                rows = self.conn.execute(
                    f"SELECT dimensionid, memberid FROM {link} WHERE datapointid = ?",
                    (datapointid,),
                ).fetchall()
            except Exception:
                rows = []
            if not rows:
                continue
            for r in rows:
                dimid = r[0]
                memid = r[1]
                # Resolve codes
                drow = self.conn.execute(
                    f"SELECT dimensioncode FROM {self.schema}_dimension WHERE dimensionid = ?",
                    (dimid,),
                ).fetchone()
                mrow = self.conn.execute(
                    f"SELECT membercode FROM {self.schema}_member WHERE memberid = ?",
                    (memid,),
                ).fetchone()
                if drow and mrow:
                    dim_mem.append((drow[0], mrow[0]))
            if dim_mem:
                break
        self._cache_axes[datapointid] = dim_mem
        return dim_mem

    def cell_candidates_for_datapoint(self, datapointid: str) -> List[sqlite3.Row]:
        if datapointid in self._cache_cells:
            return self._cache_cells[datapointid]
        rows = self.conn.execute(
            f"""
            SELECT TC.cellcode AS cellcode,
                   TV.tableversioncode AS tableversioncode,
                   TV.tablevid AS tablevid,
                   T.templateid AS templateid,
                   TV.tableid AS tableid
            FROM {self.schema}_tablecell AS TC
            JOIN {self.schema}_tableversion AS TV ON TC.tablevid = TV.tablevid
            JOIN {self.schema}_template AS T ON TV.templateid = T.templateid
            WHERE TC.datapointid = ?
            """,
            (datapointid,),
        ).fetchall()
        self._cache_cells[datapointid] = rows
        return rows


def _fact_dimensions(fact) -> Dict[str, str]:
    dims: Dict[str, str] = {}
    try:
        ctx = fact.context
        if ctx is None:
            return dims
        for dim, dimVal in (ctx.qnameDims or {}).items():
            # dim is QName; dimVal can be ExplicitDimensionValue or TypedDimension
            axis_code = dim.localName
            try:
                mem_q = dimVal.memberQname  # explicit
                member_code = mem_q.localName
            except Exception:
                # typed: serialize string value
                try:
                    member_code = (dimVal.typedMember.text or "").strip()
                except Exception:
                    member_code = ""
            dims[axis_code] = member_code
    except Exception:
        pass
    return dims


def _fact_period(fact) -> str:
    try:
        ctx = fact.context
        if ctx is None:
            return ""
        if ctx.isInstantPeriod:
            return str(ctx.instantDatetime or ctx.instantDate or "")
        if ctx.isStartEndPeriod:
            return f"{ctx.startDatetime or ctx.startDate}/{ctx.endDatetime or ctx.endDate}"
        return ""
    except Exception:
        return ""


def _fact_unit(fact) -> Optional[str]:
    try:
        u = getattr(fact, "unit", None)
        if u is not None:
            if u.measures:
                # First numerator measure
                m = u.measures[0][0] if u.measures[0] else None
                return m.localName if m is not None else None
    except Exception:
        pass
    return None


def map_fact_to_cell(fact, modelXbrl, dpm_db: DpmDb) -> Tuple[Optional[MappedCell], Optional[MappingWarning]]:
    # Extract identifiers
    try:
        fq = fact.qname
        concept_local = fq.localName
        fact_qname = str(fq)
    except Exception:
        return None, MappingWarning(None, None, "Fact missing QName")

    dims = _fact_dimensions(fact)
    period = _fact_period(fact)
    unit = _fact_unit(fact)
    ctx = getattr(fact, "context", None)
    ctx_id = getattr(ctx, "id", None) if ctx is not None else None
    doc_uri = getattr(fact.modelDocument, "uri", None)

    # Resolve concept -> datapoint(s)
    concept_ids = dpm_db.resolve_concept_ids(concept_local)
    if not concept_ids:
        return None, MappingWarning(ctx_id, fact_qname, f"Concept not found in DPM: {concept_local}")

    # Try all datapoints for the concept until we find a full axis match
    for cid in concept_ids:
        for dp_row in dpm_db.datapoints_for_concept(cid):
            dp_id = dp_row[0]
            required_axes = dpm_db.axes_for_datapoint(dp_id)  # list[(axis_code, member_code)]
            req_map = {a: m for a, m in required_axes}
            # Compare with fact dims
            missing = []
            mismatched = []
            for axis_code, member_code in req_map.items():
                if axis_code not in dims:
                    missing.append(axis_code)
                elif dims[axis_code] != member_code:
                    mismatched.append((axis_code, dims[axis_code], member_code))
            # Extra dims present in fact but not required
            extra = [a for a in dims.keys() if a not in req_map]
            if missing or mismatched:
                # Not a match; continue to next datapoint
                continue
            # Fetch cell candidates
            cells = dpm_db.cell_candidates_for_datapoint(dp_id)
            if not cells:
                # No cells for datapoint; continue
                continue
            # Rank candidates with a simple confidence score
            best = None
            best_score = -1.0
            for c in cells:
                # Base score for exact axis match
                score = 1.0
                # Penalize extra dimensions on the fact
                score -= 0.1 * len(extra)
                # Penalize mismatched axis members (fact member differs from DPM-required)
                try:
                    score -= 0.1 * len(mismatched)
                except Exception:
                    pass
                # Axis/member reinforcement: if DPM axes for the datapoint include members matching the fact dims
                try:
                    dp_axes = required_axes  # list of (axis_code, member_code)
                    matches = sum(1 for (ax, mem) in dp_axes if dims.get(ax) == mem)
                    score += 0.2 * matches
                except Exception:
                    pass
                # Negative evidence: if fact has a dimension not in DPM axes, penalize
                try:
                    negative = sum(1 for ax in dims.keys() if ax not in {a for a, _ in required_axes})
                    score -= 0.15 * negative
                except Exception:
                    pass
                # Slight bonus if unit present (non-empty) to prefer numeric datapoints
                if unit:
                    score += 0.05
                # Period alignment: boost if period string is non-empty
                if period:
                    score += 0.05
                # Prefer lexicographically earlier cell codes for stability
                try:
                    cellcode = str(c[0])
                    score += max(0.0, 0.01 * (1.0 - (ord(cellcode[0]) - ord('A')) / 26.0)) if cellcode else 0.0
                except Exception:
                    pass
                if score > best_score:
                    best_score = score
                    best = c
            if best is None:
                continue
            mapped = MappedCell(
                template_id=str(best[3]),
                table_id=str(best[4]),
                table_version=str(best[1]),
                cell_id=str(best[0]),
                axes=req_map,
                concept=concept_local,
                period=period,
                unit=unit,
                fact_context_id=ctx_id,
                fact_qname=fact_qname,
                source_doc=doc_uri,
                confidence=max(0.0, min(1.0, best_score)),
            )
            # If there are extra dims, return a warning but keep mapping as successful
            if extra:
                warn = MappingWarning(ctx_id, fact_qname, f"Extra dimensions present and ignored: {','.join(extra)}")
                return mapped, warn
            return mapped, None

    # If none matched, return a detailed warning
    return None, MappingWarning(ctx_id, fact_qname, "No datapoint matched all required axes for concept")


def map_instance(modelXbrl, dpm_db: DpmDb) -> Tuple[List[MappedCell], List[MappingWarning]]:
    mapped: List[MappedCell] = []
    warnings: List[MappingWarning] = []
    try:
        facts = list(getattr(modelXbrl, "factsInInstance", []) or getattr(modelXbrl, "facts", []))
    except Exception:
        facts = []
    for f in facts:
        # Skip nil facts
        if getattr(f, "isNil", False):
            continue
        mc, warn = map_fact_to_cell(f, modelXbrl, dpm_db)
        if mc is not None:
            mapped.append(mc)
        if warn is not None:
            warnings.append(warn)
    return mapped, warnings


def write_mapping_report_csv(mapped: Iterable[MappedCell], warnings: Iterable[MappingWarning], out_path: str) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "docUri",
            "factContextId",
            "factQName",
            "concept",
            "period",
            "unit",
            "template_id",
            "table_id",
            "table_version",
            "cell_id",
            "axes",  # axisCode=memberCode;...
            "warning",
            "confidence",
        ])
        # Index warnings by context/qname for quick lookup
        warn_idx: Dict[Tuple[Optional[str], Optional[str]], List[str]] = {}
        for wmsg in warnings:
            warn_idx.setdefault((wmsg.fact_context_id, wmsg.fact_qname), []).append(wmsg.message)
        for m in mapped:
            axes_str = ";".join(f"{a}={b}" for a, b in sorted(m.axes.items()))
            key = (m.fact_context_id, m.fact_qname)
            w_msgs = "; ".join(warn_idx.get(key, []))
            w.writerow([
                m.source_doc or "",
                m.fact_context_id or "",
                m.fact_qname or "",
                m.concept,
                m.period,
                m.unit or "",
                m.template_id,
                m.table_id,
                m.table_version,
                m.cell_id,
                axes_str,
                w_msgs,
                f"{m.confidence:.2f}",
            ])


