from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed

from xbrl_validator.results_parser import parse_arelle_text_output

class _JsonlHandler(logging.Handler):
    def __init__(self, path: str) -> None:
        super().__init__(level=logging.INFO)
        self.path = path
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")

    def emit(self, record: logging.LogRecord) -> None:  # type: ignore[override]
        try:
            payload = {
                "ts": getattr(record, "asctime", None) or None,
                "level": record.levelname,
                "code": getattr(record, "messageCode", None)
                or getattr(record, "code", None)
                or getattr(record, "msgCode", None)
                or None,
                "message": record.getMessage(),
                "ref": getattr(record, "ref", None),
                "modelObjectQname": getattr(record, "modelObjectQname", None),
                "docUri": getattr(record, "file", None) or getattr(record, "docURI", None),
                "line": getattr(record, "line", None) or getattr(record, "lineNumber", None),
                "col": getattr(record, "col", None) or getattr(record, "columnNumber", None),
                # Best-effort optional fields commonly seen in Arelle logs for formula
                "assertionId": getattr(record, "assertionId", None),
                "assertionSeverity": getattr(record, "assertionSeverity", None),
                "dimensionInfo": getattr(record, "dimensionInfo", None),
            }
            self._fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._fh.flush()
        except Exception:
            # Never raise on logging
            pass

    def close(self) -> None:  # type: ignore[override]
        try:
            self._fh.close()
        except Exception:
            pass
        super().close()


def _build_args(
    input_path: str,
    taxonomy_paths: List[str],
    plugins: List[str],
    validate: bool,
    offline: bool = False,
    cache_dir: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    args: List[str] = ["--file", input_path]
    if validate:
        args.append("--validate")
        # Enable built-in calculation validation
        args.extend([
            "--calcDecimals",  # Enable calculation validation with decimals  
        ])
    
    # Add taxonomy packages/search entries
    for t in taxonomy_paths or []:
        if t:
            args.extend(["--packages", t])
    
    # Ensure formula plugin is enabled when validating; merge with caller-provided plugins
    normalized_plugins: List[str] = []
    seen: set[str] = set()
    for p in (plugins or []):
        pl = (p or "").strip()
        if pl and pl.lower() not in seen:
            normalized_plugins.append(pl)
            seen.add(pl.lower())
    if validate and "formula" not in seen:
        normalized_plugins.append("formula")
        seen.add("formula")
    if normalized_plugins:
        args.extend(["--plugins", "|".join(normalized_plugins)])
    
    # Offline/caching controls
    if cache_dir:
        args.extend(["--cacheDir", cache_dir])
    if offline:
        # Enhanced offline mode configuration
        args.extend([
            "--internetConnectivity", "offline",
            "--noCertificateCheck",  # Skip cert validation in offline mode
            "--keepOpen",  # Keep connections open for better performance
        ])
    
    # Additional raw args passthrough (e.g., --calcDecimals)
    for a in (extra_args or []):
        if a:
            args.append(a)
    return args


def _try_cntlr_run(args: List[str]) -> int:
    """Run Arelle headless controller in-process. Returns pseudo-exit code."""
    import arelle.CntlrCmdLine as CCL  # type: ignore
    import sys as _sys

    # CntlrCmdLine.main reads from sys.argv; emulate CLI
    old_argv = list(_sys.argv)
    _sys.argv = ["arelle"] + args
    try:
        CCL.main()
        return 0
    except SystemExit as e:  # Arelle may exit with code
        try:
            return int(e.code) if e.code is not None else 0
        except Exception:
            return 0
    finally:
        _sys.argv = old_argv


def _run_subprocess_validation(
    input_path: str,
    taxonomy_paths: List[str],
    plugins: List[str],
    log_jsonl_path: str,
    validate: bool = True,
    offline: bool = False,
    cache_dir: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
    timeout: int = 300,
) -> Dict:
    """Run validation in subprocess with timeout for better isolation."""
    args = _build_args(input_path, taxonomy_paths, plugins, validate, offline, cache_dir, extra_args)
    cmd = [sys.executable, "-m", "arelle.CntlrCmdLine"] + args
    
    # Add JSONL logging via environment
    env = os.environ.copy()
    env["ARELLE_JSONL_LOG"] = log_jsonl_path
    # Ensure Arelle loads formula plugin even in subprocess
    if "--plugins" not in args:
        env["ARELLE_PLUGINS"] = "formula"
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False
        )
        rc = result.returncode
    except subprocess.TimeoutExpired:
        rc = 124  # timeout exit code
    except Exception:
        rc = 1
    
    # Build summary by reading JSONL
    summary = {
        "returnCode": rc,
        "total": 0,
        "byLevel": {},
        "byCode": {},
        "formula": {"evaluated": 0, "satisfied": 0, "unsatisfied": 0},
    }
    
    path = Path(log_jsonl_path)
    if path.exists():
        level_counts: Dict[str, int] = {}
        code_counts: Dict[str, int] = {}
        formula_eval = 0
        formula_sat = 0
        formula_unsat = 0
        
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                summary["total"] += 1
                level = (rec.get("level") or "").upper() or "INFO"
                level_counts[level] = level_counts.get(level, 0) + 1
                code = rec.get("code") or ""
                if code:
                    code_counts[code] = code_counts.get(code, 0) + 1
                # Heuristics for formula assertion results
                msg = (rec.get("message") or "").lower()
                as_sev = (rec.get("assertionSeverity") or "").lower()
                if "assertion" in msg or as_sev:
                    formula_eval += 1
                    if "unsatisfied" in msg or as_sev == "unsatisfied":
                        formula_unsat += 1
                    elif "satisfied" in msg or as_sev == "satisfied":
                        formula_sat += 1
        
        summary["byLevel"] = level_counts
        summary["byCode"] = dict(sorted(code_counts.items(), key=lambda kv: kv[1], reverse=True))
        summary["formula"] = {
            "evaluated": formula_eval,
            "satisfied": formula_sat,
            "unsatisfied": formula_unsat,
        }
    
    # If JSONL is empty or missing, parse captured stdout/stderr or Arelle log file in text format and write to JSONL
    try:
        need_parse_stdout = (not path.exists()) or (path.exists() and path.stat().st_size == 0)
    except Exception:
        need_parse_stdout = True
    if need_parse_stdout:
        try:
            # Prefer combined stdout+stderr
            combined = "" + (getattr(result, "stdout", "") or "") + "\n" + (getattr(result, "stderr", "") or "")
            # If combined is empty, and caller passed --logFile, try to read that file
            if (not combined.strip()) and extra_args:
                try:
                    if "--logFile" in extra_args:
                        idx = extra_args.index("--logFile")
                        if idx + 1 < len(extra_args):
                            lf = extra_args[idx + 1]
                            if lf and Path(lf).exists():
                                try:
                                    combined = Path(lf).read_text(encoding="utf-8", errors="ignore")
                                except Exception:
                                    combined = Path(lf).read_text(errors="ignore")
                except Exception:
                    pass
            issues = parse_arelle_text_output(combined or "", file_path=None)
        except Exception:
            issues = []
        if issues:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as fh:
                    for i in issues:
                        payload = {
                            "level": i.severity,
                            "code": i.code,
                            "message": i.message,
                            "docUri": i.file_path,
                            "modelObjectQname": i.fact_qname,
                        }
                        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
                # Recompute summary quickly from issues
                level_counts: Dict[str, int] = {}
                code_counts: Dict[str, int] = {}
                for i in issues:
                    summary["total"] += 1
                    lvl = (i.severity or "INFO").upper()
                    level_counts[lvl] = level_counts.get(lvl, 0) + 1
                    if i.code:
                        code_counts[i.code] = code_counts.get(i.code, 0) + 1
                summary["byLevel"] = level_counts
                summary["byCode"] = dict(sorted(code_counts.items(), key=lambda kv: kv[1], reverse=True))
            except Exception:
                pass
    
    return summary


def run_validation(
    input_path: str,
    taxonomy_paths: List[str],
    plugins: List[str],
    log_jsonl_path: str,
    validate: bool = True,
    offline: bool = False,
    cache_dir: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
    use_subprocess: bool = False,
    timeout: int = 300,
) -> Dict:
    """
    Run Arelle validation headlessly with guaranteed formula execution and JSONL logging.
    
    Args:
        use_subprocess: If True, run in subprocess for better isolation (recommended for batch)
        timeout: Timeout in seconds for subprocess runs
    
    Returns a summary dict with counts by level, by code, and formula assertion stats.
    """
    # Default cache dir if not provided
    if cache_dir is None:
        cache_dir = str(Path("assets/cache").absolute())
    Path(cache_dir).mkdir(parents=True, exist_ok=True)

    # Respect explicit parameter; do not override with environment
    # This ensures API/CLI control online/offline behavior deterministically
    
    if use_subprocess:
        return _run_subprocess_validation(
            input_path, taxonomy_paths, plugins, log_jsonl_path,
            validate, offline, cache_dir, extra_args, timeout
        )

    args = _build_args(input_path, taxonomy_paths, plugins, validate, offline=offline, cache_dir=cache_dir, extra_args=extra_args)

    # Prefer native JSON logging if supported via environment toggle
    # Caller can set ARELLE_USE_JSON_LOG=1 to try Arelle's built-in JSON format
    use_native_json = os.environ.get("ARELLE_USE_JSON_LOG", "0") == "1"
    if use_native_json:
        args = args + ["--logFile", log_jsonl_path, "--logFormat", "json"]
        jsonl_handler = None
        arelle_logger = None
    else:
        # Attach JSONL handler to Arelle logger and prevent propagation to root
        jsonl_handler = _JsonlHandler(log_jsonl_path)
        arelle_logger = logging.getLogger("arelle")
        arelle_logger.setLevel(logging.INFO)
        arelle_logger.addHandler(jsonl_handler)
        # Avoid duplicating messages to console (suppresses stray 'Forbidden retrieving ...')
        arelle_logger.propagate = False
        # Keep root quieter to avoid incidental console noise
        logging.getLogger().setLevel(logging.WARNING)

    # Execute controller
    rc = _try_cntlr_run(args)

    # Detach handler if we attached it
    if not use_native_json and arelle_logger is not None and jsonl_handler is not None:
        try:
            arelle_logger.removeHandler(jsonl_handler)
            jsonl_handler.close()
        except Exception:
            pass

    # Build summary by reading JSONL
    summary = {
        "returnCode": rc,
        "total": 0,
        "byLevel": {},
        "byCode": {},
        "formula": {"evaluated": 0, "satisfied": 0, "unsatisfied": 0},
    }

    level_counts: Dict[str, int] = {}
    code_counts: Dict[str, int] = {}
    formula_eval = 0
    formula_sat = 0
    formula_unsat = 0

    path = Path(log_jsonl_path)
    if path.exists():
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                summary["total"] += 1
                level = (rec.get("level") or "").upper() or "INFO"
                level_counts[level] = level_counts.get(level, 0) + 1
                code = rec.get("code") or ""
                if code:
                    code_counts[code] = code_counts.get(code, 0) + 1
                # Heuristics for formula assertion results
                msg = (rec.get("message") or "").lower()
                as_sev = (rec.get("assertionSeverity") or "").lower()
                if "assertion" in msg or as_sev:
                    formula_eval += 1
                    if "unsatisfied" in msg or as_sev == "unsatisfied":
                        formula_unsat += 1
                    elif "satisfied" in msg or as_sev == "satisfied":
                        formula_sat += 1

    summary["byLevel"] = level_counts
    summary["byCode"] = dict(sorted(code_counts.items(), key=lambda kv: kv[1], reverse=True))
    summary["formula"] = {
        "evaluated": formula_eval,
        "satisfied": formula_sat,
        "unsatisfied": formula_unsat,
    }
    return summary


def run_batch_validation_parallel(
    input_paths: List[str],
    taxonomy_paths: List[str],
    plugins: List[str],
    log_jsonl_base: str,
    validate: bool = True,
    offline: bool = False,
    cache_dir: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
    max_workers: int = 4,
    timeout: int = 300,
) -> List[Dict]:
    """Run batch validation using process pool for better isolation and performance."""
    
    def validate_one(input_path: str) -> Dict:
        log_path = f"{log_jsonl_base}__{Path(input_path).stem}.jsonl"
        return run_validation(
            input_path=input_path,
            taxonomy_paths=taxonomy_paths,
            plugins=plugins,
            log_jsonl_path=log_path,
            validate=validate,
            offline=offline,
            cache_dir=cache_dir,
            extra_args=extra_args,
            use_subprocess=True,
            timeout=timeout,
        )
    
    results: List[Dict] = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_path = {executor.submit(validate_one, path): path for path in input_paths}
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                result = future.result()
                result["input_path"] = path
                results.append(result)
            except Exception as exc:
                results.append({
                    "input_path": path,
                    "returnCode": 1,
                    "total": 0,
                    "byLevel": {"ERROR": 1},
                    "byCode": {"BATCH.EXCEPTION": 1},
                    "formula": {"evaluated": 0, "satisfied": 0, "unsatisfied": 0},
                    "exception": str(exc),
                })
    
    return results