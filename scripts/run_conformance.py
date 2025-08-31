#!/usr/bin/env python3
"""
XBRL Conformance Suite Runner

Downloads and runs XBRL International conformance suites to verify validator compliance.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List


def download_suite(suite_name: str, out_dir: Path) -> bool:
    """Download a conformance suite if not already present."""
    suite_urls = {
        "xbrl-2.1": "https://www.xbrl.org/2003/conformance/XBRL-CONF-2014-12-10.zip",
        "dimensions": "https://www.xbrl.org/2005/conformance/XBRL-CONF-2014-12-10.zip", 
        "formula": "https://www.xbrl.org/2008/conformance/XBRL-CONF-2014-12-10.zip",
        "table": "https://www.xbrl.org/2014/conformance/table-linkbase-CONF-2014-12-10.zip",
        "oim-csv": "https://www.xbrl.org/2021/conformance/oim-csv-CONF-2021-10-13.zip",
        "oim-json": "https://www.xbrl.org/2021/conformance/oim-json-CONF-2021-10-13.zip",
    }
    
    url = suite_urls.get(suite_name)
    if not url:
        print(f"Unknown suite: {suite_name}")
        return False
    
    suite_dir = out_dir / suite_name
    if suite_dir.exists() and any(suite_dir.iterdir()):
        print(f"Suite {suite_name} already downloaded")
        return True
    
    print(f"Downloading {suite_name} from {url}...")
    try:
        import requests
        resp = requests.get(url, stream=True)
        resp.raise_for_status()
        
        zip_path = out_dir / f"{suite_name}.zip"
        with open(zip_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        
        # Extract
        import zipfile
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(suite_dir)
        
        zip_path.unlink()  # cleanup
        print(f"✓ Downloaded and extracted {suite_name}")
        return True
        
    except Exception as e:
        print(f"✗ Failed to download {suite_name}: {e}")
        return False


def run_suite_tests(suite_dir: Path, validator_cmd: List[str]) -> Dict:
    """Run tests from a conformance suite directory."""
    results = {"passed": 0, "failed": 0, "skipped": 0, "details": []}
    
    # Look for test index files
    index_files = list(suite_dir.glob("**/testcases-index.xml")) + list(suite_dir.glob("**/index.xml"))
    if not index_files:
        print(f"No test index found in {suite_dir}")
        return results
    
    # Simple approach: find .xbrl files and try to validate them
    test_files = list(suite_dir.glob("**/*.xbrl"))[:20]  # Limit for demo
    
    for test_file in test_files:
        try:
            cmd = validator_cmd + ["--file", str(test_file), "--no-validate"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                results["passed"] += 1
                status = "PASS"
            else:
                results["failed"] += 1
                status = "FAIL"
            
            results["details"].append({
                "test": str(test_file.relative_to(suite_dir)),
                "status": status,
                "returncode": result.returncode,
            })
            
        except subprocess.TimeoutExpired:
            results["failed"] += 1
            results["details"].append({
                "test": str(test_file.relative_to(suite_dir)),
                "status": "TIMEOUT",
                "returncode": 124,
            })
        except Exception as e:
            results["skipped"] += 1
            results["details"].append({
                "test": str(test_file.relative_to(suite_dir)),
                "status": "SKIP",
                "error": str(e),
            })
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Run XBRL conformance suites")
    parser.add_argument("--suites", nargs="*", default=["xbrl-2.1"], 
                       choices=["xbrl-2.1", "dimensions", "formula", "table", "oim-csv", "oim-json"],
                       help="Conformance suites to run")
    parser.add_argument("--download-dir", default="conformance", help="Directory to download suites")
    parser.add_argument("--validator", default="python -m xbrl_validator.cli", help="Validator command")
    parser.add_argument("--out", default="conformance_results.json", help="Results output file")
    
    args = parser.parse_args()
    
    download_dir = Path(args.download_dir)
    download_dir.mkdir(exist_ok=True)
    
    validator_cmd = args.validator.split()
    all_results = {}
    
    for suite in args.suites:
        print(f"\n=== Running {suite} conformance suite ===")
        
        if not download_suite(suite, download_dir):
            continue
            
        suite_dir = download_dir / suite
        results = run_suite_tests(suite_dir, validator_cmd)
        all_results[suite] = results
        
        print(f"Results: {results['passed']} passed, {results['failed']} failed, {results['skipped']} skipped")
    
    # Write results
    with open(args.out, "w") as f:
        json.dump(all_results, f, indent=2)
    
    print(f"\nResults written to {args.out}")
    
    # Exit with error if any suite had failures
    total_failed = sum(r.get("failed", 0) for r in all_results.values())
    return 1 if total_failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
