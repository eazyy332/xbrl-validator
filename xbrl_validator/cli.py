import argparse
import sys
from pathlib import Path
from typing import Optional

from .arelle_runner import validate_with_arelle, validate_many_with_arelle, validate_many_parallel_with_arelle, path_exists
from .results_parser import parse_arelle_text_output, write_issues_json, write_issues_csv, aggregate_counts, enrich_with_dpm
from .taxonomy_package import list_entry_points, to_zip_entry_syntax
from src.validation.arelle_runner import run_validation
from src.pipeline import (
    ingest_jsonl,
    write_validation_messages_csv,
    write_results_by_file_json,
    write_formula_rollup_csv,
)
from src.reporting.reports import generate_reports


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="XBRL validation tool (Arelle-based)")
    parser.add_argument("--file", required=False, help="Path to XBRL instance document")
    parser.add_argument(
        "--files",
        nargs="*",
        help="Additional XBRL instance files for batch processing",
    )
    parser.add_argument(
        "--packages",
        required=False,
        help="Path to taxonomy package zip or 'zip#entry.xsd' syntax",
    )
    parser.add_argument(
        "--discover-entry",
        action="store_true",
        help="If a package zip is provided, discover entry points and pick the first one",
    )
    parser.add_argument(
        "--entry-match",
        required=False,
        help="When discovering entries, select the first whose label or URI contains this substring",
    )
    parser.add_argument(
        "--arelle",
        required=False,
        metavar="ARGS",
        help="Additional raw Arelle args, e.g. --arelle=\"--disclosureSystem esef\"",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Run without --validate (not typical)",
    )
    parser.add_argument(
        "--out-json",
        required=False,
        help="Write issues to JSON at this path",
    )
    parser.add_argument(
        "--out-csv",
        required=False,
        help="Write issues to CSV at this path",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print aggregated severity counts",
    )
    # Exports unified with app.validate
    parser.add_argument("--exports", required=False, default="exports", help="Exports directory (CSV/JSON/Excel/PDF)")
    parser.add_argument("--out-jsonl", required=False, help="Write raw JSONL validation log to this path")
    parser.add_argument(
        "--dpm-sqlite",
        required=False,
        default="assets/dpm.sqlite",
        help="Path to DPM SQLite database for enrichment (default: assets/dpm.sqlite)",
    )
    parser.add_argument(
        "--dpm-schema",
        required=False,
        default="dpm35_10",
        choices=["dpm35_10", "dpm35_20"],
        help="DPM schema prefix to use for enrichment",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Parallel jobs for batch validation",
    )
    parser.add_argument(
        "--severity-exit",
        choices=["INFO", "WARNING", "ERROR", "FATAL"],
        help="Return non-zero exit if any issue at or above the given severity is found",
    )
    parser.add_argument(
        "--license-info",
        action="store_true",
        help="Print license status and exit",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    args = parse_args(argv)

    if args.license_info:
        try:
            from xbrl_validator.license import get_license_status
            st = get_license_status()
            print("[license] state=", st.state, "edition=", st.edition, "expires=", st.expires)
            return 0 if st.state == "valid" else 1
        except Exception as e:
            print("[license] error:", e)
            return 2

    if not path_exists(args.file):
        print(f"[error] File not found: {args.file}")
        return 2
    if args.packages and not path_exists(args.packages):
        # Allow zip#entry.xsd syntax; we already checked the zip path part
        print(f"[warn] Packages file not found (zip or path): {args.packages}")

    packages = args.packages
    if args.discover_entry and packages and "#" not in packages:
        eps = list_entry_points(packages)
        if eps:
            label, entry_uri = eps[0]
            if args.entry_match:
                em = args.entry_match.lower()
                for lbl, uri in eps:
                    if em in (lbl or "").lower() or em in (uri or "").lower():
                        label, entry_uri = lbl, uri
                        break
            packages = to_zip_entry_syntax(packages, entry_uri)
            print(f"[info] Using discovered entry: {label} -> {packages}")

    # Pipe-friendly text logging by default (still helpful for stdout); JSONL used via run_validation
    extra_list = ["--plugin", "Logging|logCode|SEVERITY|message"]

    # Optional caching for performance
    cache_dir = "assets/.arelle-cache"
    import os
    os.makedirs(cache_dir, exist_ok=True)

    files = [args.file] + (args.files or [])
    if len(files) == 1:
        # Unified JSONL path using run_validation for reliable exports
        log_path = args.out_jsonl or str(Path("assets/logs/cli_run.jsonl"))
        tax_list = [packages] if packages else []
        summary = run_validation(
            input_path=files[0],
            taxonomy_paths=tax_list,
            plugins=[],
            log_jsonl_path=log_path,
            validate=(not args.no_validate),
            offline=False,
            cache_dir=cache_dir,
            extra_args=[p for p in extra_list if p],
            use_subprocess=True,
            timeout=600,
        )
        msgs, roll, by_file = ingest_jsonl(log_path, dpm_sqlite=args.dpm_sqlite, dpm_schema=args.dpm_schema, model_xbrl_path=files[0])
        # Apply EBA Filing Rules from configured Excel and merge into outputs
        try:
            from src.validation.eba_rules import apply_eba_rules
            try:
                from xbrl_validator.config import get_eba_rules_excel_path
                eba_rules_excel = get_eba_rules_excel_path()
            except Exception:
                eba_rules_excel = None
            if eba_rules_excel:
                extra_msgs = apply_eba_rules(
                    msgs,
                    model_xbrl_path=files[0],
                    framework_version=None,
                    eba_rules_excel=eba_rules_excel,
                    dpm_sqlite=args.dpm_sqlite,
                    dpm_schema=args.dpm_schema,
                )
                if extra_msgs:
                    msgs.extend(extra_msgs)
                    # Update rollup and by_file to include extra messages
                    sev_roll = roll.get("bySeverity", {}) if isinstance(roll, dict) else {}
                    for m in extra_msgs:
                        lv = (m.get("level") or "INFO").upper()
                        sev_roll[lv] = sev_roll.get(lv, 0) + 1
                        doc = m.get("docUri") or files[0]
                        by_file.setdefault(doc, []).append(m)
                    if isinstance(roll, dict):
                        roll["bySeverity"] = sev_roll
                        roll["total"] = int(roll.get("total", 0)) + len(extra_msgs)
        except Exception:
            # Never fail CLI due to filing rules
            pass
        exp_dir = Path(args.exports)
        exp_dir.mkdir(parents=True, exist_ok=True)
        write_validation_messages_csv(msgs, str(exp_dir / "validation_messages.csv"))
        write_results_by_file_json(by_file, str(exp_dir / "results_by_file.json"))
        write_formula_rollup_csv(msgs, str(exp_dir / "formula_rollup.csv"))
        _paths = generate_reports(messages=msgs, exports_dir=str(exp_dir))
        if args.out_json:
            write_results_by_file_json(by_file, args.out_json)
        if args.out_csv:
            write_validation_messages_csv(msgs, args.out_csv)
        if args.summary:
            print("[summary]", roll)
        if args.severity_exit:
            order = {"INFO": 0, "WARNING": 1, "ERROR": 2, "FATAL": 3}
            threshold = order[args.severity_exit]
            sev = roll.get("bySeverity", {})
            has = (threshold <= 1 and sev.get("WARNING", 0) > 0) or (threshold <= 2 and sev.get("ERROR", 0) > 0) or (threshold <= 3 and sev.get("FATAL", 0) > 0)
            if has:
                return 1
        return int(summary.get("returnCode", 0))
    else:
        # Batch mode: aggregate outputs
        if args.jobs and args.jobs > 1:
            procs = validate_many_parallel_with_arelle(
                instance_paths=files,
                packages=packages,
                validate=(not args.no_validate),
                additional_arelle_args=args.arelle,
                additional_arelle_args_list=extra_list,
                cache_dir=cache_dir,
                log_format=None,
                max_workers=args.jobs,
            )
        else:
            procs = validate_many_with_arelle(
            instance_paths=files,
            packages=packages,
            validate=(not args.no_validate),
            additional_arelle_args=args.arelle,
            additional_arelle_args_list=extra_list,
            cache_dir=cache_dir,
            log_format=None,
            )
        worst_rc = 0
        all_issues = []
        for p in procs:
            print(p.stdout)
            worst_rc = max(worst_rc, p.returncode)
            # We don't know which file a proc belongs to here; fall back without file_path
            all_issues.extend(parse_arelle_text_output(p.stdout))
        all_issues = enrich_with_dpm(all_issues, sqlite_path=args.dpm_sqlite, schema_prefix=args.dpm_schema)
        if args.out_json:
            write_issues_json(all_issues, args.out_json)
        if args.out_csv:
            write_issues_csv(all_issues, args.out_csv)
        if args.summary:
            print("[summary]", aggregate_counts(all_issues))
        if args.severity_exit:
            order = {"INFO": 0, "WARNING": 1, "ERROR": 2, "FATAL": 3}
            threshold = order[args.severity_exit]
            counts = aggregate_counts(all_issues)
            # If any at or above threshold
            has = (threshold <= 1 and counts["WARNING"] > 0) or (threshold <= 2 and counts["ERROR"] > 0) or (threshold <= 3 and counts["FATAL"] > 0)
            if has:
                return 1
        return worst_rc


if __name__ == "__main__":
    sys.exit(main())

