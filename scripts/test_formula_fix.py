#!/usr/bin/env python3
"""
Test script to verify EBA formula execution after cache priming fix.
Checks for specific issues that were blocking formula evaluation.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List


def run_cache_prime() -> bool:
    """Prime the cache and return success status."""
    print("[test] Priming cache...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "scripts.cache_prime"],
            capture_output=True, text=True, check=False, timeout=120
        )
        if result.returncode == 0:
            print("[test] ✓ Cache priming succeeded")
            return True
        else:
            print(f"[test] ✗ Cache priming failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"[test] ✗ Cache priming exception: {e}")
        return False


def run_validation_test(instance_path: str) -> Dict:
    """Run validation and return analysis of results."""
    print(f"[test] Running validation on {instance_path}...")
    
    log_path = Path("assets/logs/formula_test.jsonl")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        sys.executable, "-m", "app.validate",
        "--file", instance_path,
        "--ebaVersion", "3.5",
        "--out", str(log_path),
        "--plugins", "formula",
        "--offline",
        "--cacheDir", "assets/cache",
        "--exports", "exports/formula_test"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=300)
        analysis = analyze_validation_log(log_path)
        analysis["validation_returncode"] = result.returncode
        return analysis
    except Exception as e:
        return {"error": str(e), "validation_returncode": -1}


def analyze_validation_log(log_path: Path) -> Dict:
    """Analyze validation log for specific formula-related issues."""
    analysis = {
        "total_messages": 0,
        "io_errors": 0,
        "custom_function_errors": 0,
        "dimensional_errors": 0,
        "formula_assertions": 0,
        "specific_issues": []
    }
    
    if not log_path.exists():
        analysis["error"] = "Log file not found"
        return analysis
    
    try:
        with log_path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                    
                try:
                    entry = json.loads(line)
                    analysis["total_messages"] += 1
                    
                    code = entry.get("code", "")
                    message = entry.get("message", "").lower()
                    level = entry.get("level", "").upper()
                    
                    # Track specific problematic patterns
                    if code == "IOerror" and "could not load file" in message:
                        analysis["io_errors"] += 1
                        if "eurofiling.info" in message or "eba.europa.eu" in message:
                            analysis["specific_issues"].append(f"Line {line_num}: Missing EBA resource - {message[:100]}")
                    
                    if "nocustomfunctionsignature" in code.lower():
                        analysis["custom_function_errors"] += 1
                        analysis["specific_issues"].append(f"Line {line_num}: Custom function missing - {message[:100]}")
                    
                    if "dimensionallyinvaliderror" in code.lower():
                        analysis["dimensional_errors"] += 1
                    
                    if "assertion" in message and level in ("ERROR", "WARNING", "INFO"):
                        analysis["formula_assertions"] += 1
                        
                except json.JSONDecodeError:
                    continue
                    
    except Exception as e:
        analysis["error"] = f"Failed to read log: {e}"
    
    return analysis


def print_analysis(analysis: Dict) -> None:
    """Print formatted analysis results."""
    print("\n" + "="*60)
    print("FORMULA EXECUTION ANALYSIS")
    print("="*60)
    
    if "error" in analysis:
        print(f"❌ ERROR: {analysis['error']}")
        return
    
    print(f"Total messages: {analysis['total_messages']}")
    print(f"Validation return code: {analysis.get('validation_returncode', 'unknown')}")
    print()
    
    # Critical issues that block formulas
    critical_issues = analysis["io_errors"] + analysis["custom_function_errors"]
    
    print("CRITICAL FORMULA BLOCKERS:")
    print(f"  IOerrors (missing HTTP resources): {analysis['io_errors']}")
    print(f"  Custom function signature errors: {analysis['custom_function_errors']}")
    print(f"  → Total critical issues: {critical_issues}")
    
    if critical_issues == 0:
        print("  ✅ NO CRITICAL FORMULA BLOCKERS FOUND!")
    else:
        print("  ❌ FORMULA BLOCKERS STILL PRESENT")
    
    print()
    print("OTHER VALIDATION RESULTS:")
    print(f"  Dimensional validation errors: {analysis['dimensional_errors']}")
    print(f"  Formula assertions processed: {analysis['formula_assertions']}")
    
    if analysis.get("specific_issues"):
        print(f"\nFIRST {min(5, len(analysis['specific_issues']))} SPECIFIC ISSUES:")
        for issue in analysis["specific_issues"][:5]:
            print(f"  • {issue}")
        if len(analysis["specific_issues"]) > 5:
            print(f"  ... and {len(analysis['specific_issues']) - 5} more")


def main() -> int:
    """Main test execution."""
    print("EBA Formula Execution Test")
    print("=" * 40)
    
    # Find a test instance
    test_instances = [
        "assets/work/samples/DUMMYLEI123456789012.CON_FR_COREP030200_COREPFRTB_2024-12-31_20240625002144000.xbrl",
        "WithRandomValues/DUMMYLEI123456789012_GB_COREP020400_COREPALMIND_2020-04-30_20190513212405000.xbrl",
    ]
    
    instance_path = None
    for path in test_instances:
        if Path(path).exists():
            instance_path = path
            break
    
    if not instance_path:
        print("❌ No test instance found. Available instances:")
        for path in test_instances:
            print(f"  - {path} (exists: {Path(path).exists()})")
        return 1
    
    print(f"Using test instance: {instance_path}")
    
    # Step 1: Prime cache
    if not run_cache_prime():
        print("❌ Cache priming failed - test cannot continue reliably")
        return 1
    
    # Step 2: Run validation and analyze
    analysis = run_validation_test(instance_path)
    print_analysis(analysis)
    
    # Step 3: Determine success
    critical_issues = analysis.get("io_errors", 0) + analysis.get("custom_function_errors", 0)
    
    if critical_issues == 0:
        print("\n🎉 SUCCESS: Formula execution appears to be working!")
        return 0
    else:
        print(f"\n❌ FAILURE: {critical_issues} critical formula blockers remain")
        return 1


if __name__ == "__main__":
    sys.exit(main())
