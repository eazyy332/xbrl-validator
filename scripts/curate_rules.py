from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Set


BASE = Path(__file__).resolve().parents[1]


def load_rules() -> List[Dict[str, Any]]:
    cache = BASE / "assets/cache/eba_rules_cache.json"
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            return list(data.get("rules", []))
        except Exception:
            pass
    # Fallback: try loading via loader if available
    try:
        from src.validation.eba_rules_loader import load_rules_from_excel  # type: ignore
        # Heuristic to find Excel under extra_data or fillingrules
        candidates = [
            BASE / "extra_data" / "EBA Filing Rules v5.5_2025_01_14 (1).pdf",  # not excel, placeholder
            BASE / "fillingrules" / "EBA Filing Rules v5.5_2025_01_14 (1).xlsx",
            BASE / "fillingrules" / "eba_filing_rules_v5.4_07_01.xlsx",
        ]
        xlsx = None
        for p in candidates:
            if p.suffix.lower() in (".xlsx", ".xlsm") and p.exists():
                xlsx = p
                break
        if xlsx is None:
            return []
        data = load_rules_from_excel(str(xlsx), cache_json=str(cache))
        return list(data.get("rules", []))
    except Exception:
        return []


def load_aliases() -> Dict[str, str]:
    p = BASE / "config/table_aliases.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in (data.get("aliases", {}) or {}).items()}
    except Exception:
        return {}


def curate(rules: List[Dict[str, Any]], count: int, focus: List[str]) -> List[str]:
    focus_low = [f.lower() for f in focus]
    aliases = load_aliases()
    # Score rules: severity weight + focus table match
    sev_weight = {"FATAL": 3, "ERROR": 3, "WARNING": 2, "INFO": 1}
    scored: List[tuple[int, str]] = []
    seen: Set[str] = set()
    for r in rules:
        rid = str(r.get("id") or "").strip()
        if not rid or rid in seen:
            continue
        seen.add(rid)
        sev = str(r.get("severity") or "").upper()
        base = sev_weight.get(sev, 1)
        table = str(r.get("table") or "")
        tnorm = table
        if table:
            low = table.lower()
            tnorm = aliases.get(low, table)
        bonus = 0
        for kw in focus_low:
            if (tnorm and kw in str(tnorm).lower()) or (table and kw in table.lower()):
                bonus = 5
                break
        # Prefer rules with conditions
        cond_bonus = 1 if (r.get("condition") or r.get("cond_expr")) else 0
        scored.append((base + bonus + cond_bonus, rid))
    scored.sort(key=lambda kv: (-kv[0], kv[1]))
    return [rid for _score, rid in scored[:count]]


def main() -> int:
    ap = argparse.ArgumentParser(description="Curate a subset of EBA rules for faster iteration")
    ap.add_argument("--out", default=str(BASE / "config/curated_rules.json"))
    ap.add_argument("--count", type=int, default=300)
    ap.add_argument("--focus", default="COREP,FINREP,DORA,FC", help="Comma-separated keywords for table focus")
    args = ap.parse_args()

    rules = load_rules()
    if not rules:
        print("[error] No rules found (missing cache and excel)")
        return 2
    focus = [s.strip() for s in (args.focus or "").split(",") if s.strip()]
    ids = curate(rules, args.count, focus)
    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(ids, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[curate] wrote {outp} with {len(ids)} rule ids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


