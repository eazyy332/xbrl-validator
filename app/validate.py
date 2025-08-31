from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.validation.arelle_runner import run_validation
from src.pipeline import ingest_jsonl, write_validation_messages_csv, write_results_by_file_json, write_formula_rollup_csv


def _load_taxonomy_stack(eba_version: str | None) -> List[str]:
    if not eba_version:
        return []
    try:
        cfg = json.loads(Path("config/taxonomy.json").read_text(encoding="utf-8"))
        key = "eba_3_4" if str(eba_version) == "3.4" else "eba_3_5"
        return [str(p) for p in (cfg.get("stacks", {}).get(key, []) or [])]
    except Exception:
        return []


def main() -> int:
    ap = argparse.ArgumentParser(description="XBRL validation CLI (Arelle-based)")
    ap.add_argument("--file", required=True, help="XBRL instance file path")
    ap.add_argument("--packages", action="append", default=[], help="Taxonomy package ZIP or zip#entry.xsd (repeatable)")
    ap.add_argument("--ebaVersion", dest="eba_version", default=None, help="EBA taxonomy version (e.g., 3.5)")
    ap.add_argument("--out", default="validation.jsonl", help="JSONL log output path")
    ap.add_argument("--plugins", default="formula", help="Arelle plugins list (pipe-separated)")
    ap.add_argument("--offline", action="store_true", help="Run in offline mode using cacheDir")
    ap.add_argument("--cacheDir", default="assets/cache", help="Cache directory for Arelle")
    ap.add_argument("--exports", default="exports", help="Exports directory for CSV/JSON reports")
    ap.add_argument("--severity-exit", default=None, help="Exit non-zero if severity present (e.g., ERROR)")
    args, extra = ap.parse_known_args()

    input_path = args.file
    plugins = [p for p in (args.plugins or "").split("|") if p]
    taxonomy_paths: List[str] = list(args.packages or [])
    if not taxonomy_paths and args.eba_version:
        taxonomy_paths = _load_taxonomy_stack(args.eba_version)

    Path(args.cacheDir).mkdir(parents=True, exist_ok=True)
    Path(Path(args.out).parent).mkdir(parents=True, exist_ok=True)

    summary = run_validation(
        input_path=input_path,
        taxonomy_paths=taxonomy_paths,
        plugins=plugins,
        log_jsonl_path=str(args.out),
        validate=True,
        offline=bool(args.offline),
        cache_dir=str(args.cacheDir),
        extra_args=extra,
        use_subprocess=False,
    )

    # Generate exports
    try:
        msgs, roll, by_file = ingest_jsonl(str(args.out))
        exp_dir = Path(args.exports)
        exp_dir.mkdir(parents=True, exist_ok=True)
        write_validation_messages_csv(msgs, str(exp_dir / "validation_messages.csv"))
        write_results_by_file_json(by_file, str(exp_dir / "results_by_file.json"))
        write_formula_rollup_csv(msgs, str(exp_dir / "formula_rollup.csv"))
    except Exception:
        pass

    # Severity-based exit if requested
    if args.severity_exit:
        sev = (args.severity_exit or "").upper().strip()
        try:
            msgs, roll, _ = ingest_jsonl(str(args.out))
            errs = sum(1 for m in msgs if (m.get("level") or "").upper() in (sev,))
            if errs:
                return 2
        except Exception:
            pass

    return int(summary.get("returnCode", 0) or 0)


if __name__ == "__main__":
    raise SystemExit(main())

