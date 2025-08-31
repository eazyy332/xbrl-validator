from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
import argparse
from pathlib import Path
from typing import List, Tuple


BASE = Path(__file__).resolve().parents[1]


@dataclass
class Case:
    name: str
    file: Path
    eba_version: str
    expected_jsonl: Path


def run_case(case: Case, exports_dir: Path, core_only: bool = False) -> Tuple[int, Path]:
    out = exports_dir / f"{case.name}.jsonl"
    cmd = [
        sys.executable,
        "-m",
        "app.validate",
        "--file",
        str(case.file),
        "--ebaVersion",
        case.eba_version,
        "--out",
        str(out),
        "--plugins",
        "formula",
        "--offline",
        "--cacheDir",
        str(BASE / "assets/cache"),
        "--exports",
        str(exports_dir / case.name),
    ]
    if core_only:
        cmd.append("--noFilingRules")
    print("[run]", " ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
    return res.returncode, out


def load_jsonl(path: Path) -> List[dict]:
    rows: List[dict] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def assert_deterministic(current: Path, expected: Path, ignore_codes: set[str] | None = None, check_fields: bool = False) -> None:
    cur = load_jsonl(current)
    exp = load_jsonl(expected)
    # Basic assertions: length and top-10 codes histogram
    def by_code(rows: List[dict]) -> dict:
        h: dict[str, int] = {}
        for m in rows:
            c = (m.get("code") or "").strip()
            if c:
                if ignore_codes and c in ignore_codes:
                    continue
                h[c] = h.get(c, 0) + 1
        return dict(sorted(h.items(), key=lambda kv: kv[1], reverse=True)[:10])
    assert len(cur) == len(exp), f"message count differs: {len(cur)} != {len(exp)}"
    assert by_code(cur) == by_code(exp), "top codes histogram differs"
    if check_fields:
        # Compare distribution of (docUri,line,col) tuples for first 200 entries (ignoring message text)
        def sig(rows: List[dict]) -> List[tuple[str, int, int]]:
            out: List[tuple[str, int, int]] = []
            for m in rows[:200]:
                out.append((str(m.get("docUri") or ""), int(m.get("line") or 0), int(m.get("col") or 0)))
            return out
        assert sig(cur) == sig(exp), "docUri/line/col signature differs in first 200 messages"


def main() -> int:
    ap = argparse.ArgumentParser(description="Acceptance: deterministic outputs")
    ap.add_argument("--mode", choices=["core", "filing"], default="filing", help="core = --noFilingRules; filing = include rules")
    ap.add_argument("--rebaseline", action="store_true", help="Overwrite expected JSONL with current outputs")
    ap.add_argument("--ignore-codes", default="", help="Path to JSON file with list of codes to ignore in comparison")
    ap.add_argument("--check-fields", action="store_true", help="Also compare docUri/line/col for first N messages")
    ap.add_argument("--expect-csv", action="store_true", help="Require rules_coverage.csv to exist in exports for filing runs")
    ap.add_argument("--expect-json", default="", help="Path to expected outcomes JSON (per-table thresholds)")
    args = ap.parse_args()
    # Load acceptance matrix from artifacts/coverage.json if present
    cov_path = BASE / "artifacts/coverage.json"
    if not cov_path.exists():
        print("[warn] artifacts/coverage.json not found; falling back to sample set")
        runs = [
            {
                "path": str(BASE / "extra_data/sample_instances_architecture_1.0/xBRL_XML/DUMMYLEI123456789012.CON_FR_COREP030200_COREPFRTB_2024-12-31_20240625002144000.xbrl"),
                "eba_version": "3.5",
                "jsonl": str(BASE / "artifacts/xml/DUMMYLEI123456789012.CON_FR_COREP030200_COREPFRTB_2024-12-31_20240625002144000/validation.jsonl"),
            },
            {
                "path": str(BASE / "extra_data/sample_instances_architecture_1.0/xBRL_XML/DUMMYLEI123456789012.CON_FR_DORA010000_DORA_2025-01-31_20240625161151000.xbrl"),
                "eba_version": "3.5",
                "jsonl": str(BASE / "artifacts/xml/DUMMYLEI123456789012.CON_FR_DORA010000_DORA_2025-01-31_20240625161151000/validation.jsonl"),
            },
            {
                "path": str(BASE / "extra_data/sample_instances_architecture_1.0/xBRL_XML/DUMMYLEI123456789012.CON_FR_FC010000_FC_2024-12-31_20240625002201000.xbrl"),
                "eba_version": "3.5",
                "jsonl": str(BASE / "artifacts/xml/DUMMYLEI123456789012.CON_FR_FC010000_FC_2024-12-31_20240625002201000/validation.jsonl"),
            },
        ]
    else:
        data = json.loads(cov_path.read_text(encoding="utf-8"))
        runs = []
        for r in data.get("runs", []):
            runs.append({"path": r.get("path"), "eba_version": r.get("eba_version") or "3.5", "jsonl": r.get("jsonl")})

    cases: List[Case] = []
    for r in runs:
        p = Path(r["path"]).resolve()
        name = p.stem
        cases.append(Case(name=name, file=p, eba_version=str(r["eba_version"]), expected_jsonl=Path(r["jsonl"]).resolve()))

    exports_dir = BASE / "exports" / "acceptance"
    exports_dir.mkdir(parents=True, exist_ok=True)

    # Load ignore codes
    ignore_codes: set[str] = set()
    if args.ignore_codes:
        p = Path(args.ignore_codes)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    ignore_codes = {str(x) for x in data}
            except Exception:
                pass

    failures = 0
    # Load expected outcomes
    expected: dict = {}
    if args.expect_json:
        p = Path(args.expect_json)
        if p.exists():
            try:
                expected = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                expected = {}

    for c in cases:
        print(f"[case] {c.name}")
        rc, out = run_case(c, exports_dir, core_only=(args.mode == "core"))
        if rc != 0:
            print(f"[FAIL] validator exit code {rc} for {c.name}")
            failures += 1
            continue
        if args.rebaseline:
            # Write current to expected path
            try:
                Path(c.expected_jsonl).parent.mkdir(parents=True, exist_ok=True)
                Path(c.expected_jsonl).write_text(Path(out).read_text(encoding="utf-8"), encoding="utf-8")
                print(f"[BASELINED] {c.name} -> {c.expected_jsonl}")
            except Exception as e:
                print(f"[ERR] baseline failed for {c.name}: {e}")
                failures += 1
        else:
            try:
                assert_deterministic(out, c.expected_jsonl, ignore_codes=ignore_codes, check_fields=args.check_fields)
                print(f"[OK] {c.name}")
                if args.expect_csv and args.mode == "filing":
                    exp_dir = exports_dir / c.name
                    cov = exp_dir / "rules_coverage.csv"
                    if not cov.exists():
                        print(f"[DIFF] {c.name}: rules_coverage.csv missing")
                        failures += 1
            except AssertionError as e:
                print(f"[DIFF] {c.name}: {e}")
                failures += 1
        # Optional expected outcomes check (table-level thresholds)
        if expected and args.mode == "filing":
            try:
                cur_msgs = load_jsonl(out)
                # Compute per-table counts by severity
                by_table: dict[str, dict[str, int]] = {}
                for m in cur_msgs:
                    mc = m.get("mappedCell") or {}
                    table = mc.get("table_id") or (m.get("dpm_table") or "")
                    lvl = (m.get("level") or "INFO").upper()
                    if not table:
                        continue
                    d = by_table.setdefault(table, {})
                    d[lvl] = d.get(lvl, 0) + 1
                # Evaluate thresholds
                exp_for_case = expected.get(c.name) or {}
                for table, th in exp_for_case.items():
                    cur = by_table.get(table, {})
                    for lvl, min_val in th.items():
                        if cur.get(lvl, 0) < int(min_val):
                            print(f"[DIFF] {c.name}: table {table} {lvl} below expected {min_val} (got {cur.get(lvl,0)})")
                            failures += 1
            except Exception as e:
                print(f"[warn] expected check failed: {e}")


    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


