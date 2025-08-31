from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, List, Tuple
import json


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def diff_runs(baseline_path: str, current_path: str) -> Dict[str, Any]:
    base = _load_jsonl(baseline_path)
    curr = _load_jsonl(current_path)
    def key(m: Dict[str, Any]) -> Tuple[str, str, str]:
        return (
            (m.get("level") or "").upper(),
            m.get("code") or "",
            m.get("message") or "",
        )
    base_set = {key(m) for m in base}
    curr_set = {key(m) for m in curr}
    added = list(curr_set - base_set)
    removed = list(base_set - curr_set)
    return {
        "baseline": baseline_path,
        "current": current_path,
        "added": added,
        "removed": removed,
        "summary": {
            "added": len(added),
            "removed": len(removed),
        },
    }


