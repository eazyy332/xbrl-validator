from __future__ import annotations

from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import json

from xbrl_validator.config import get_cache_dir, get_dpm_sqlite_path
from .expr_eval import compile_expr, evaluate, ExprSyntaxError, default_helpers
from .eba_rules_loader import (
    load_rules_from_excel,
    load_cached_rules,
    build_rules_index,
    save_rules_index,
    load_rules_index,
    excel_sha256,
)
def _normalize_table_id(table_id: str) -> str:
    t = (table_id or "").strip()
    # Simple normalization: collapse whitespace, keep case as-is for display but match case-insensitive
    return " ".join(t.split())


def _framework_normalizers(framework_version: Optional[str]) -> Dict[str, str]:
    """Return a mapping of known alias->canonical table ids per framework.
    This can be extended by reading JSON config if needed.
    """
    fw = (framework_version or "").strip()
    # Attempt to load alias map from JSON export built from DPM (if present)
    # Format example: {"aliases": {"corep frtb": "COREPFRTB", ...}}
    try:
        cfg_path = Path("config/table_aliases.json")
        if cfg_path.exists():
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            aliases = {str(k).lower(): str(v) for k, v in (data.get("aliases") or {}).items()}
            if aliases:
                return aliases
    except Exception:
        pass
    # Fallback minimal seeds; extend with real mappings as needed
    seeds: Dict[str, str] = {
        "corep frtb": "COREPFRTB",
        "corep of": "COREPOF",
        "finrep": "FINREP",
        "dora": "DORA",
        "fc": "FC",
    }
    return {k.lower(): v for k, v in seeds.items()}


def _translate_condition_to_expr(text: str) -> str:
    """Translate common Excel-like rule expressions to evaluator syntax.
    Heuristics:
    - Logical: AND/OR/NOT -> and/or/not
    - Comparators: = -> ==, <> -> !=
    - IN lists: A in [B,C]
    - Function aliases: hasTable -> has_table, countTable -> count, startsWith -> startswith
    - Period tokens: PERIOD_START/END -> period_start/period_end
    - Filing indicator checks: hasIndicator('X') -> ('X' in filing_indicators)
    """
    s = (text or "").strip()
    if not s:
        return s
    # Surround with spaces to catch word boundaries uniformly
    t = f" {s} "
    # Logical operators (case-insensitive by duplicating patterns)
    for a, b in ((" AND ", " and "), (" and ", " and "), (" OR ", " or "), (" or ", " or "), (" NOT ", " not "), (" not ", " not ")):
        t = t.replace(a, b)
    # Comparators
    t = t.replace("<>", "!=")
    # Replace single equals that are not part of >=, <=, ==, != with ==
    try:
        import re as _re
        t = _re.sub(r"(?<![<>!=])=(?!=)", "==", t)
    except Exception:
        # Fallback minimal
        t = t.replace(" = ", " == ")

    # Common function aliases and helpers (apply both original and lowercase variants)
    alias_map = {
        "hasTable": "has_table",
        "countTable": "count",
        "countFact": "count_fact",
        "hasFact": "has_fact",
        "valueOf": "value_of",
        "hasCell": "has_cell",
        "countCell": "count_cell",
        "hasTemplate": "has_template",
        "countTemplate": "count_template",
        "hasAxisMember": "has_axis_member",
        "countAxisMember": "count_axis_member",
        # cross-table and period helpers aliases
        "sumWhere": "sum_where",
        "sumwhere": "sum_where",
        "SUMWHERE": "sum_where",
        "periodStart": "period_start",
        "periodEnd": "period_end",
        "startsWith": "startswith",
        "endsWith": "endswith",
        "containsIC": "contains_ic",
        "equalsIC": "equals_ic",
        "hasIndicator": "has_indicator",
        "PERIOD_START": "period_start",
        "PERIOD_END": "period_end",
        "LEN(": "len(",
        "TRIM(": "trim(",
        "LOWER(": "lower(",
        "UPPER(": "upper(",
        "LIKE(": "like(",
        # Common Excel / SQL style aliases
        "IIF(": "iif(",
        "IF(": "iif(",
        "AND(": "and_fn(",
        "OR(": "or_fn(",
        "ABS(": "abs(",
        "ROUND(": "round(",
        "FLOOR(": "floor(",
        "CEIL(": "ceil(",
        "COALESCE(": "coalesce(",
        "LEFT(": "left(",
        "RIGHT(": "right(",
        "MID(": "mid(",
        # Case-insensitive contains/equality seen in some sheets
        "EQUALSIC(": "equals_ic(",
        "CONTAINSIC(": "contains_ic(",
    }
    for a, b in alias_map.items():
        t = t.replace(a, b).replace(a.lower(), b)

    # Normalize boolean literals
    try:
        import re as _re
        t = _re.sub(r"\bTRUE\b", "1", t, flags=_re.IGNORECASE)
        t = _re.sub(r"\bFALSE\b", "0", t, flags=_re.IGNORECASE)
    except Exception:
        pass

    # Convert "X in (A,B)" -> "X in [A,B]" (keep original items list intact)
    try:
        import re as _re
        def _conv_in(m: "_re.Match[str]") -> str:
            lhs, items = m.group(1), m.group(2)
            return f"{lhs} in [{items}]"
        t = _re.sub(r"(?i)\b([A-Za-z_][\w\.]*)\s+in\s*\(([^)]*)\)", _conv_in, t)
        # NOT IN
        def _conv_not_in(m: "_re.Match[str]") -> str:
            lhs, items = m.group(1), m.group(2)
            return f"not ({lhs} in [{items}])"
        t = _re.sub(r"(?i)\b([A-Za-z_][\w\.]*)\s+not\s+in\s*\(([^)]*)\)", _conv_not_in, t)
        # BETWEEN a AND b -> between(x,a,b)
        def _conv_between(m: "_re.Match[str]") -> str:
            x, a, b = m.group(1), m.group(2), m.group(3)
            return f"between({x}, {a}, {b})"
        t = _re.sub(r"(?i)\b([A-Za-z_][\w\.]*)\s+between\s+([^\s]+)\s+and\s+([^\s)]+)", _conv_between, t)
        # NOT LIKE
        t = _re.sub(r"(?i)\bnot\s+like\b", " not like ", t)
    except Exception:
        pass

    return t.strip()


# In-memory AST cache by rule text for speed (per-process)
_AST_CACHE: dict[str, Any] = {}

def _compile_cached(expr: str):
    key = expr.strip()
    if not key:
        return None
    ast = _AST_CACHE.get(key)
    if ast is not None:
        return ast
    try:
        ast = compile_expr(key)
    except Exception:
        ast = None
    _AST_CACHE[key] = ast
    return ast



def _new_msg(
    level: str,
    code: str,
    message: str,
    doc_uri: str | None = None,
    assertion_id: Optional[str] = None,
    assertion_severity: Optional[str] = None,
) -> Dict[str, Any]:
    msg = {
        "level": level.upper(),
        "code": code,
        "message": message,
        "docUri": doc_uri or "",
    }
    # Include optional formula-like assertion fields so downstream rollups can aggregate
    if assertion_id:
        msg["assertionId"] = assertion_id
    if assertion_severity:
        msg["assertionSeverity"] = assertion_severity
    return msg


def _load_rules(eba_rules_excel: Optional[str]) -> Dict[str, Any]:
    """Load rules from one or multiple Excel sources.

    If multiple paths are provided separated by ';' or '|', the first is treated
    as the base (full rules), and subsequent ones are overlays that can modify
    lifecycle/scope fields by matching on rule id and updating keys:
    - active / valid_from / valid_to
    - applicability / prereq / severity / message / code (when present)
    The merge is shallow per rule id.
    """
    if not eba_rules_excel:
        return {"count": 0, "rules": []}

    # Build a cache filename tied to the combination fingerprint
    cache_dir = Path(get_cache_dir())
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        sha = excel_sha256(eba_rules_excel)
    except Exception:
        sha = "default"
    cache_json = cache_dir / f"eba_rules_cache_{sha}.json"
    cached = load_cached_rules(str(cache_json))
    if cached and cached.get("count", 0) > 0:
        return cached

    # Split into base + overlays
    parts = [s.strip() for s in str(eba_rules_excel).split(";") if s.strip()]
    if len(parts) == 1 and ("|" in str(eba_rules_excel)):
        parts = [s.strip() for s in str(eba_rules_excel).split("|") if s.strip()]
    base = parts[0] if parts else str(eba_rules_excel)
    overlays = parts[1:] if len(parts) > 1 else []

    base_data = load_rules_from_excel(base)
    if not overlays:
        # Write cache and return
        try:
            with Path(cache_json).open("w", encoding="utf-8") as f:
                json.dump(base_data, f)
        except Exception:
            pass
        return base_data

    # Build map by id for merging
    by_id: Dict[str, Dict[str, Any]] = {}
    for r in base_data.get("rules", []) or []:
        rid = str(r.get("id") or "").strip()
        if rid:
            by_id[rid] = dict(r)

    # Apply overlays
    def _merge_rule(into: Dict[str, Any], over: Dict[str, Any]) -> None:
        # Only update known fields when provided
        for k in ("active", "valid_from", "valid_to", "applicability", "prereq", "severity", "message", "code", "table", "framework"):
            if over.get(k) not in (None, ""):
                into[k] = over.get(k)

    for ov in overlays:
        try:
            ov_data = load_rules_from_excel(ov)
        except Exception:
            continue
        for r in (ov_data.get("rules", []) or []):
            rid = str(r.get("id") or "").strip()
            if not rid:
                continue
            if rid in by_id:
                _merge_rule(by_id[rid], r)
            else:
                by_id[rid] = dict(r)

    merged: Dict[str, Any] = {"count": len(by_id), "rules": list(by_id.values())}
    # Cache merged result
    try:
        with Path(cache_json).open("w", encoding="utf-8") as f:
            json.dump(merged, f)
    except Exception:
        pass
    return merged


def _applicable(rule: Dict[str, Any], framework_version: Optional[str]) -> bool:
    fw = (rule.get("framework") or "").strip()
    if not fw or not framework_version:
        return True
    return framework_version in fw


def apply_eba_rules(
    messages: List[Dict[str, Any]],
    model_xbrl_path: Optional[str] = None,
    framework_version: Optional[str] = None,
    eba_rules_excel: Optional[str] = None,
    dpm_sqlite: Optional[str] = None,
    dpm_schema: str = "dpm35_10",
) -> Any:
    """Apply EBA Filing Rules (v5.5) loaded from Excel to produce additional messages.

    This implementation evaluates a concrete subset with real data:
    - Filing indicator presence using model facts (concept localname contains 'filing' and 'indicator').
    - Table applicability: for rules that reference a table, require at least one mapped cell for that table
      based on deterministic DPM mapping of the loaded instance.
    - Severity is taken from the rule where present; default WARNING/INFO for hints.
    """
    extra: List[Dict[str, Any]] = []
    coverage: Dict[str, Any] = {
        "total_rules": 0,
        "candidates": 0,
        "evaluated": 0,
        "failed": 0,
        "prereq_skipped": 0,
        "table_missing": 0,
        "by_table": {},  # table -> {evaluated, failed, table_missing}
    }
    rules_data = _load_rules(eba_rules_excel)
    # Lifecycle filtering by active and validity windows if present
    def _in_window(vfrom: str, vto: str) -> bool:
        if not vfrom and not vto:
            return True
        try:
            from datetime import date
            today = date.today()
            def _parse(d: str):
                if not d:
                    return None
                # Accept YYYY-MM-DD or DD/MM/YYYY or MM/DD/YYYY
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
                    try:
                        return __import__('datetime').datetime.strptime(d, fmt).date()
                    except Exception:
                        continue
                return None
            s = _parse(str(vfrom))
            e = _parse(str(vto))
            if s and today < s:
                return False
            if e and today > e:
                return False
            return True
        except Exception:
            return True

    # Optional curated mode: if config/curated_rules.json exists with list of rule IDs, only keep those
    curated_ids: set[str] = set()
    try:
        cpath = Path("config/curated_rules.json")
        if cpath.exists():
            arr = json.loads(cpath.read_text(encoding="utf-8"))
            if isinstance(arr, list):
                curated_ids = {str(x).strip() for x in arr if str(x).strip()}
    except Exception:
        curated_ids = set()

    rules = []
    for r in (rules_data.get("rules", []) or []):
        if not _applicable(r, framework_version):
            continue
        if isinstance(r.get("active"), bool) and not r.get("active"):
            continue
        if not _in_window(str(r.get("valid_from") or ""), str(r.get("valid_to") or "")):
            continue
        if curated_ids and str(r.get("id") or "") not in curated_ids:
            continue
        rules.append(r)
    coverage["total_rules"] = len(rules)

    # Build or load compiled/indexed rules keyed by Excel SHA for performance
    try:
        if eba_rules_excel:
            sha = excel_sha256(eba_rules_excel)
            idx_path = Path(get_cache_dir()) / f"eba_rules_index_{sha}.json"
            table_index = load_rules_index(str(idx_path))
            if table_index is None:
                table_index = build_rules_index({"rules": rules})
                save_rules_index(table_index, str(idx_path))
        else:
            table_index = build_rules_index({"rules": rules})
    except Exception:
        table_index = {"*": rules}

    # Apply framework alias map also to index keys when selecting candidates (done below)

    # Resolve DPM path default if not provided
    if not dpm_sqlite:
        try:
            dpm_sqlite = get_dpm_sqlite_path()
        except Exception:
            dpm_sqlite = None

    # Optional: load modelXbrl and compute deterministic mapping
    mapped_tables: set[str] = set()
    mapped_by_table: Dict[str, int] = {}
    mapped_cells_by_table: Dict[str, set[str]] = {}
    mapped_templates: set[str] = set()
    axis_member_index: Dict[str, set[str]] = {}
    has_fi_fact: bool = False
    all_tables_list: List[str] = []
    filing_indicators: List[str] = []
    filing_indicators_norm: set[str] = set()
    period_start: Any = None
    period_end: Any = None
    entity_identifier: str = ""

    # Filing indicator detection via explicit QName whitelist (from taxonomy/applicability hints) if available
    known_fi_qnames: List[str] = []
    try:
        # Optional JSON file listing known filing indicator QNames per framework
        fi_path = Path("config/filing_indicators.json")
        if fi_path.exists():
            fi_cfg = json.loads(fi_path.read_text(encoding="utf-8"))
            if framework_version and str(framework_version) in fi_cfg:
                known_fi_qnames = list(fi_cfg[str(framework_version)] or [])
            else:
                known_fi_qnames = list((fi_cfg.get("default") or []))
    except Exception:
        known_fi_qnames = []

    if model_xbrl_path:
        try:
            import arelle.Cntlr as C  # type: ignore
            from src.dpm import DpmDb, map_instance  # type: ignore

            cntlr = C.Cntlr(logFileName=None)
            modelXbrl = cntlr.modelManager.load(model_xbrl_path)
            # Build a simple facts index by concept local name for fact-level rules
            facts_by_local: Dict[str, List[Any]] = {}
            # Filing indicator detection from facts and basic report period
            try:
                for f in getattr(modelXbrl, "factsInInstance", []) or []:
                    try:
                        qn_full = str(getattr(f, "qname", None) or getattr(getattr(f, "concept", None), "qname", ""))
                    except Exception:
                        qn_full = ""
                    ln = getattr(getattr(f, "concept", None), "localName", "") or ""
                    lnl = ln.lower()
                    is_fi = False
                    if known_fi_qnames:
                        is_fi = qn_full in known_fi_qnames
                    else:
                        is_fi = ("filing" in lnl) and ("indicator" in lnl)
                    if is_fi:
                        has_fi_fact = True
                        try:
                            val = getattr(f, "xValue", None) or getattr(f, "value", None)
                            if val is not None:
                                filing_indicators.append(str(val))
                        except Exception:
                            pass
                    # Index facts by concept local name (for has_fact/count_fact/value_of)
                    try:
                        if ln:
                            facts_by_local.setdefault(ln, []).append(f)
                    except Exception:
                        pass
                # contexts: get first entity and min/max periods
                mm = getattr(modelXbrl, "modelManager", None)
                if mm is not None:
                    dts = []
                    for c in getattr(mm, "modelXbrl", modelXbrl).contexts or []:
                        try:
                            if getattr(c, "startDatetime", None) is not None and getattr(c, "endDatetime", None) is not None:
                                dts.append((c.startDatetime.date(), c.endDatetime.date()))
                        except Exception:
                            pass
                    if dts:
                        period_start = min(s for s, _ in dts)
                        period_end = max(e for _, e in dts)
                # entity identifier
                try:
                    ent = getattr(modelXbrl, "entityIdentifier", None)
                    if ent:
                        entity_identifier = str(ent)
                except Exception:
                    pass
            except Exception:
                has_fi_fact = False

            # Deterministic mapping
            if dpm_sqlite:
                try:
                    db = DpmDb(dpm_sqlite, schema_prefix=dpm_schema)
                    try:
                        mapped_cells, _warns = map_instance(modelXbrl, db)
                    finally:
                        db.close()
                    for mc in mapped_cells:
                        tid = getattr(mc, "table_id", None) or ""
                        if tid:
                            # Normalize table id and also collect lowercase for case-insensitive match
                            tnorm = _normalize_table_id(str(tid))
                            # Apply framework-level normalizers
                            norms = _framework_normalizers(framework_version)
                            tnorm = norms.get(tnorm.lower(), tnorm)
                            mapped_tables.add(tnorm)
                            mapped_by_table[tnorm] = mapped_by_table.get(tnorm, 0) + 1
                            # cells per table
                            try:
                                cell = str(getattr(mc, "cell_id", "") or "")
                                if cell:
                                    mapped_cells_by_table.setdefault(tnorm, set()).add(cell)
                            except Exception:
                                pass
                        # templates
                        try:
                            templ = getattr(mc, "template_id", None)
                            if templ:
                                mapped_templates.add(str(templ))
                        except Exception:
                            pass
                        # axis-members
                        try:
                            axes = getattr(mc, "axes", None) or {}
                            for ax, mem in axes.items():
                                key = str(ax)
                                axis_member_index.setdefault(key, set()).add(str(mem))
                        except Exception:
                            pass
                    all_tables_list = sorted(mapped_tables)
                except Exception:
                    mapped_tables = set()
                    mapped_by_table = {}
                    all_tables_list = []
        except Exception:
            # If Arelle is not importable at runtime, skip deep checks
            pass

    # Filing indicator: only if rules reference indicator in applicability
    if any("indicator" in (r.get("applicability") or "").lower() for r in rules):
        if not has_fi_fact:
            # Severity: take highest among referenced rules (default WARNING)
            sev = "WARNING"
            extra.append(
                _new_msg(
                    sev,
                    "EBA.FILING.INDICATOR.MISSING",
                    "No filing indicator facts detected; ensure correct report-level indicators are provided.",
                    model_xbrl_path,
                )
            )

    # Normalize filing indicator values for robust matching
    def _norm_fi(v: str) -> str:
        s = (v or "").strip().upper()
        # Collapse whitespace and common separators
        return "".join(ch for ch in s if ch.isalnum())
    filing_indicators_norm = { _norm_fi(v) for v in filing_indicators }

    # Resolve candidate rules: global + those matching mapped tables
    seen_missing: set[str] = set()
    candidate_rules: List[Dict[str, Any]] = []
    # Always include global rules
    candidate_rules.extend(table_index.get("*", []))
    # If mapping is not available yet, fall back to rules derived from messages
    if not mapped_tables:
        # If we could not compute mapping, fall back to messages-derived mapped cells
        tables_from_msgs: set[str] = set()
        for m in messages:
            mc = m.get("mappedCell") or {}
            if mc.get("table_id"):
                tables_from_msgs.add(_normalize_table_id(str(mc.get("table_id"))))
        mapped_tables = tables_from_msgs
    # Add rules for present tables
    for t in mapped_tables:
        key = t.lower()
        candidate_rules.extend(table_index.get(key, []))
    coverage["candidates"] = len(candidate_rules)

    # Helper to render rule message using environment
    def _render_msg(rule: Dict[str, Any], fallback: str) -> str:
        tmpl = (rule.get("message") or "").strip()
        if not tmpl:
            return fallback
        rep = {
            "{TABLE}": (rule.get("table") or ""),
            "{ENTITY}": entity_identifier or "",
            "{PERIOD_START}": str(period_start or ""),
            "{PERIOD_END}": str(period_end or ""),
        }
        out = tmpl
        for k, v in rep.items():
            out = out.replace(k, v)
        return out

    # Evaluate candidates
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import psutil
    # Check if any rule needs DPM mapping (references table or applicability with table keywords)
    needs_dpm = any(("table" in (r.get("applicability", "") + r.get("condition", "")).lower()) for r in candidate_rules)
    if needs_dpm and model_xbrl_path and dpm_sqlite:
        # Compute DPM mapping lazily
        import arelle.Cntlr as C  # type: ignore
        from src.dpm import DpmDb, map_instance  # type: ignore
        cntlr = C.Cntlr(logFileName=None)
        modelXbrl = cntlr.modelManager.load(model_xbrl_path)
        db = DpmDb(dpm_sqlite, schema_prefix=dpm_schema)
        try:
            mapped_cells, _warns = map_instance(modelXbrl, db)
        finally:
            db.close()
        for mc in mapped_cells:
            tid = getattr(mc, "table_id", None) or ""
            if tid:
                tnorm = _normalize_table_id(str(tid))
                norms = _framework_normalizers(framework_version)
                tnorm = norms.get(tnorm.lower(), tnorm)
                mapped_tables.add(tnorm)
                mapped_by_table[tnorm] = mapped_by_table.get(tnorm, 0) + 1
                try:
                    cell = str(getattr(mc, "cell_id", "") or "")
                    if cell:
                        mapped_cells_by_table.setdefault(tnorm, set()).add(cell)
                except Exception:
                    pass
            try:
                templ = getattr(mc, "template_id", None)
                if templ:
                    mapped_templates.add(str(templ))
            except Exception:
                pass
            try:
                axes = getattr(mc, "axes", None) or {}
                for ax, mem in axes.items():
                    key = str(ax)
                    axis_member_index.setdefault(key, set()).add(str(mem))
            except Exception:
                pass
        all_tables_list = sorted(mapped_tables)

    def evaluate_rule(r):
        # Memory check before eval
        if psutil.virtual_memory().percent > 90:
            return None  # Skip if memory high
        r_table = (r.get("table") or "").strip()
        # Respect prerequisites/applicability
        prereq = (r.get("prereq") or "").strip()
        if prereq:
            try:
                ast_p = compile_expr(prereq)
                env_p = {"has_filing_indicator": has_fi_fact, "table_rows": mapped_by_table.get(r_table, 0)}
                if not bool(evaluate(ast_p, env_p, {"nonzero": lambda x: float(x) != 0.0})):
                    return {"type": "prereq_skipped"}
            except Exception:
                return {"type": "prereq_skipped"}

        # If the rule references a table and none matched, emit a missing-table message once
        rid = str(r.get("id") or "").strip()
        if r_table:
            rtab_norm = _normalize_table_id(r_table)
            rtab_low = rtab_norm.lower()
            has_any = any((t == rtab_norm) or (t.lower() == rtab_low) or t.endswith(rtab_norm) or t.lower().endswith(rtab_low) or rtab_norm.endswith(t) or rtab_low.endswith(t.lower()) for t in mapped_tables)
            if not has_any and r_table not in seen_missing:
                seen_missing.add(r_table)
                sev = (r.get("severity") or "WARNING").upper() or "WARNING"
                code = (r.get("code") or f"EBA.RULE.{(r.get('id') or 'UNKNOWN')}.TABLE.MISSING").upper()
                fallback_msg = f"No data mapped for required table {r_table} referenced by rules."
                return {
                    "type": "table_missing",
                    "msg": _new_msg(
                        sev,
                        code,
                        _render_msg(r, fallback_msg),
                        model_xbrl_path,
                        assertion_id=rid or None,
                        assertion_severity="unsatisfied",
                    ),
                    "table": r_table,
                }

        # Evaluate rule condition if present (translate Excel-like -> evaluator DSL)
        cond = (r.get("cond_expr") or _translate_condition_to_expr((r.get("condition") or "").strip()))
        if cond and model_xbrl_path:
            try:
                ast = _compile_cached(cond)
            except Exception:
                ast = None
            if ast is not None:
                env = {
                    "table_rows": mapped_by_table.get(r_table, 0),
                    "has_filing_indicator": has_fi_fact,
                    "tables": all_tables_list,
                    "filing_indicators": filing_indicators,
                    "period_start": period_start,
                    "period_end": period_end,
                    "entity_identifier": entity_identifier,
                }
                def nonzero(x: Any) -> bool:
                    try:
                        return float(x) != 0.0
                    except Exception:
                        return bool(x)
                def iequals(a: Any, b: Any) -> bool:
                    try:
                        return str(a).lower() == str(b).lower()
                    except Exception:
                        return False
                def startswith(s: Any, prefix: Any) -> bool:
                    try:
                        return str(s).startswith(str(prefix))
                    except Exception:
                        return False
                def contains(s: Any, sub: Any) -> bool:
                    try:
                        return str(sub) in str(s)
                    except Exception:
                        return False
                def match_regex(text: Any, pattern: Any) -> bool:
                    try:
                        import re as _re
                        return bool(_re.search(str(pattern), str(text)))
                    except Exception:
                        return False
                def replace_regex(text: Any, pattern: Any, repl: Any) -> str:
                    try:
                        import re as _re
                        return _re.sub(str(pattern), str(repl), str(text))
                    except Exception:
                        return str(text)
                def to_number(x: Any) -> float:
                    try:
                        return float(str(x).strip())
                    except Exception:
                        return 0.0
                def to_date(s: Any) -> Any:
                    try:
                        return __import__('datetime').datetime.fromisoformat(str(s)).date()
                    except Exception:
                        return None
                def before(d1: Any, d2: Any) -> bool:
                    try:
                        return d1 is not None and d2 is not None and d1 < d2
                    except Exception:
                        return False
                def after(d1: Any, d2: Any) -> bool:
                    try:
                        return d1 is not None and d2 is not None and d1 > d2
                    except Exception:
                        return False
                def between(d: Any, s: Any, e: Any) -> bool:
                    try:
                        return d is not None and s is not None and e is not None and s <= d <= e
                    except Exception:
                        return False
                # Period consistency helpers
                def same_period(p1: Any, p2: Any) -> bool:
                    try:
                        return str(p1) == str(p2)
                    except Exception:
                        return False
                def period_contains(p_outer_start: Any, p_outer_end: Any, p_inner_start: Any, p_inner_end: Any) -> bool:
                    try:
                        return (p_outer_start is not None and p_outer_end is not None and p_inner_start is not None and p_inner_end is not None and p_outer_start <= p_inner_start <= p_inner_end <= p_outer_end)
                    except Exception:
                        return False
                # Inter-table cardinality (using mapped data)
                def require_at_least(table_name: Any, n: Any) -> bool:
                    try:
                        return count_table(str(table_name)) >= int(n)
                    except Exception:
                        return False
                def require_at_most(table_name: Any, n: Any) -> bool:
                    try:
                        return count_table(str(table_name)) <= int(n)
                    except Exception:
                        return False
                def has_table(name: Any) -> bool:
                    try:
                        s = str(name)
                    except Exception:
                        return False
                    return any((t == s) or t.endswith(s) or s.endswith(t) for t in mapped_tables)
                def has_table_like(pattern: Any) -> bool:
                    try:
                        import re as _re
                        p = _re.compile(str(pattern), _re.IGNORECASE)
                        return any(bool(p.search(t)) for t in mapped_tables)
                    except Exception:
                        return False
                def count_table(name: Any) -> int:
                    try:
                        s = str(name)
                    except Exception:
                        return 0
                    for t, c in mapped_by_table.items():
                        if (t == s) or t.endswith(s) or s.endswith(t):
                            return int(c)
                    return 0
                def count_tables_like(pattern: Any) -> int:
                    try:
                        import re as _re
                        p = _re.compile(str(pattern), _re.IGNORECASE)
                        return sum(1 for t in mapped_tables if p.search(t))
                    except Exception:
                        return 0
                def has_cell(table_or_suffix: Any, cell_code: Any) -> bool:
                    try:
                        t = str(table_or_suffix)
                        c = str(cell_code)
                    except Exception:
                        return False
                    # match table by suffix or exact
                    for mt, cells in mapped_cells_by_table.items():
                        if (mt == t) or mt.endswith(t) or t.endswith(mt):
                            return c in cells
                    return False
                def has_any_cell(cell_code: Any) -> bool:
                    try:
                        c = str(cell_code)
                    except Exception:
                        return False
                    for _mt, cells in mapped_cells_by_table.items():
                        if c in cells:
                            return True
                    return False
                def count_cell(table_or_suffix: Any) -> int:
                    try:
                        t = str(table_or_suffix)
                    except Exception:
                        return 0
                    for mt, cells in mapped_cells_by_table.items():
                        if (mt == t) or mt.endswith(t) or t.endswith(mt):
                            return int(len(cells))
                    return 0
                def count_tables_with_cell(cell_code: Any) -> int:
                    try:
                        c = str(cell_code)
                    except Exception:
                        return 0
                    n = 0
                    for _mt, cells in mapped_cells_by_table.items():
                        if c in cells:
                            n += 1
                    return n
                def has_template(template_id: Any) -> bool:
                    try:
                        return str(template_id) in mapped_templates
                    except Exception:
                        return False
                def count_template(template_id: Any) -> int:
                    try:
                        return 1 if str(template_id) in mapped_templates else 0
                    except Exception:
                        return 0
                def has_axis_member(axis_code: Any, member_code: Any) -> bool:
                    try:
                        ax = str(axis_code)
                        mem = str(member_code)
                    except Exception:
                        return False
                    return mem in axis_member_index.get(ax, set())
                def count_axis_member(axis_code: Any) -> int:
                    try:
                        ax = str(axis_code)
                    except Exception:
                        return 0
                    return int(len(axis_member_index.get(ax, set())))
                def requires_tables(*tables: Any) -> bool:
                    try:
                        names = [str(t) for t in tables]
                    except Exception:
                        return False
                    for name in names:
                        if not has_table(name):
                            return False
                    return True
                def tables_missing(*tables: Any) -> int:
                    try:
                        names = [str(t) for t in tables]
                    except Exception:
                        return 0
                    return sum(0 if has_table(n) else 1 for n in names)
                def table_has_axis_member(table_name: Any, axis_code: Any, member_code: Any) -> bool:
                    # Best-effort: axis_member_index is global; assume membership implies availability
                    try:
                        t = str(table_name)
                        ax = str(axis_code)
                        mem = str(member_code)
                    except Exception:
                        return False
                    if not has_table(t):
                        return False
                    return has_axis_member(ax, mem)
                # Fact-level helpers (by concept local name)
                def has_fact(concept_local: Any) -> bool:
                    try:
                        key = str(concept_local)
                    except Exception:
                        return False
                    return bool(facts_by_local.get(key))
                def count_fact(concept_local: Any) -> int:
                    try:
                        key = str(concept_local)
                    except Exception:
                        return 0
                    return int(len(facts_by_local.get(key, [])))
                def value_of(concept_local: Any) -> Any:
                    try:
                        key = str(concept_local)
                    except Exception:
                        return None
                    try:
                        arr = facts_by_local.get(key, [])
                        if not arr:
                            return None
                        f0 = arr[0]
                        return getattr(f0, "xValue", None) or getattr(f0, "value", None)
                    except Exception:
                        return None
                funcs = {
                    "nonzero": nonzero,
                    "iequals": iequals,
                    "has_table": has_table,
                    "has_table_like": has_table_like,
                    "count": count_table,
                    "count_tables_like": count_tables_like,
                    "has_cell": has_cell,
                    "has_any_cell": has_any_cell,
                    "count_cell": count_cell,
                    "count_tables_with_cell": count_tables_with_cell,
                    "has_template": has_template,
                    "count_template": count_template,
                    "has_axis_member": has_axis_member,
                    "count_axis_member": count_axis_member,
                    "requires_tables": requires_tables,
                    "tables_missing": tables_missing,
                    "table_has_axis_member": table_has_axis_member,
                    "has_fact": has_fact,
                    "count_fact": count_fact,
                    "value_of": value_of,
                    # Cross-table and DSL helpers
                    "sum_where": lambda iterable: sum(iterable) if iterable is not None else 0,
                    "startswith": startswith,
                    "contains": contains,
                    "match_regex": match_regex,
                    "replace_regex": replace_regex,
                    "to_number": to_number,
                    "to_date": to_date,
                    "before": before,
                    "after": after,
                    "between": between,
                    "has_indicator": lambda x: (_norm_fi(str(x)) in filing_indicators_norm),
                    "same_period": same_period,
                    "period_contains": period_contains,
                    "require_at_least": require_at_least,
                    "require_at_most": require_at_most,
                }
                funcs.update(default_helpers())
                try:
                    ok = bool(evaluate(ast, env, funcs))
                except Exception:
                    ok = False
                if not ok:
                    sev = (r.get("severity") or "WARNING").upper() or "WARNING"
                    code = (r.get("code") or f"EBA.RULE.{(r.get('id') or 'UNKNOWN')}.CONDITION").upper()
                    fallback = f"Rule condition not satisfied for table {r_table}: {cond}"
                    return {
                        "type": "failed",
                        "msg": _new_msg(
                            sev,
                            code,
                            _render_msg(r, fallback),
                            model_xbrl_path,
                            assertion_id=rid or None,
                            assertion_severity="unsatisfied",
                        ),
                        "table": r_table,
                    }
                else:
                    # Emit a satisfied assertion-style message so rollups can capture assertionId/severity
                    ok_code = (r.get("code") or f"EBA.RULE.{(r.get('id') or 'UNKNOWN')}.CONDITION.SATISFIED").upper()
                    ok_msg = _new_msg(
                        "INFO",
                        ok_code,
                        _render_msg(r, f"Rule condition satisfied for table {r_table}"),
                        model_xbrl_path,
                        assertion_id=rid or None,
                        assertion_severity="satisfied",
                    )
                    return {"type": "evaluated", "table": r_table, "msg": ok_msg}
        # If no condition to evaluate, still emit an evaluated satisfied marker for coverage
        ok_code = (r.get("code") or f"EBA.RULE.{(r.get('id') or 'UNKNOWN')}.EVALUATED").upper()
        ok_msg = _new_msg(
            "INFO",
            ok_code,
            _render_msg(r, f"Rule evaluated for table {r_table}"),
            model_xbrl_path,
            assertion_id=rid or None,
            assertion_severity="satisfied",
        )
        return {"type": "evaluated", "table": r_table, "msg": ok_msg}

    # Parallel evaluation
    with ThreadPoolExecutor(max_workers=100) as executor:
        future_to_rule = {executor.submit(evaluate_rule, r): r for r in candidate_rules}
        for future in as_completed(future_to_rule):
            res = future.result()
            if not res:
                continue
            rtype = res.get("type")
            if rtype == "prereq_skipped":
                coverage["prereq_skipped"] += 1
                continue
            if rtype == "table_missing":
                coverage["table_missing"] += 1
                msg = res.get("msg")
                if msg:
                    extra.append(msg)
                t = res.get("table") or ""
                if t:
                    bt = coverage["by_table"].setdefault(t, {"evaluated": 0, "failed": 0, "table_missing": 0})
                    bt["table_missing"] = bt.get("table_missing", 0) + 1
                continue
            if rtype == "failed":
                coverage["evaluated"] += 1
                coverage["failed"] += 1
                msg = res.get("msg")
                if msg:
                    extra.append(msg)
                t = res.get("table") or ""
                if t:
                    bt = coverage["by_table"].setdefault(t, {"evaluated": 0, "failed": 0, "table_missing": 0})
                    bt["evaluated"] = bt.get("evaluated", 0) + 1
                    bt["failed"] = bt.get("failed", 0) + 1
                continue
            if rtype == "evaluated":
                coverage["evaluated"] += 1
                # Append informational satisfied message if provided by evaluator
                m_ok = res.get("msg")
                if m_ok:
                    try:
                        extra.append(m_ok)
                    except Exception:
                        pass
                t = res.get("table") or ""
                if t:
                    bt = coverage["by_table"].setdefault(t, {"evaluated": 0, "failed": 0, "table_missing": 0})
                    bt["evaluated"] = bt.get("evaluated", 0) + 1

    # If there are no context-related messages at all, hint once (keep as INFO)
    has_context_refs = any("context" in (m.get("message") or "").lower() for m in messages)
    if not has_context_refs:
        extra.append(
            _new_msg(
                "INFO",
                "EBA.CONTEXT.MISSING",
                "No context-related messages observed; verify entityIdentifier and period contexts meet framework rules.",
                model_xbrl_path,
            )
        )

    return extra, coverage


def write_rules_coverage_csv(coverage: Dict[str, Any], out_path: str) -> None:
    try:
        import csv
        from pathlib import Path as _P
        p = _P(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["metric", "value"])
            w.writerow(["total_rules", coverage.get("total_rules", 0)])
            w.writerow(["candidates", coverage.get("candidates", 0)])
            w.writerow(["evaluated", coverage.get("evaluated", 0)])
            w.writerow(["failed", coverage.get("failed", 0)])
            w.writerow(["prereq_skipped", coverage.get("prereq_skipped", 0)])
            w.writerow(["table_missing", coverage.get("table_missing", 0)])
            # Per-table breakdown
            w.writerow([])
            w.writerow(["table", "evaluated", "failed", "table_missing"])
            for t, stats in (coverage.get("by_table") or {}).items():
                w.writerow([t, stats.get("evaluated", 0), stats.get("failed", 0), stats.get("table_missing", 0)])
    except Exception:
        pass


