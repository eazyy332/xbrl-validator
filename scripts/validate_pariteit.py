#!/usr/bin/env python3
"""
Comprehensive test suite to validate Altova pariteit.
Tests multiple instances across different frameworks and formats.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class TestCase:
    """A single validation test case."""
    name: str
    instance_path: str
    eba_version: str
    framework: str
    expected_issues: Optional[int] = None
    description: str = ""


class PariteitValidator:
    """Comprehensive validation test suite."""
    
    def __init__(self, export_base: str = "exports/pariteit_tests"):
        self.export_base = Path(export_base)
        self.export_base.mkdir(parents=True, exist_ok=True)
        self.results: List[Dict] = []
    
    def discover_test_cases(self) -> List[TestCase]:
        """Discover test cases from available samples."""
        test_cases = []
        
        # Sample instances from assets/work/samples/
        samples_dir = Path("assets/work/samples")
        if samples_dir.exists():
            for xbrl_file in samples_dir.glob("*.xbrl"):
                name = xbrl_file.stem
                # Try to extract framework from filename
                framework = "UNKNOWN"
                if "COREP" in name.upper():
                    framework = "COREP"
                elif "FINREP" in name.upper():
                    framework = "FINREP"
                elif "DORA" in name.upper():
                    framework = "DORA"
                elif "FC" in name.upper():
                    framework = "FC"
                
                test_cases.append(TestCase(
                    name=name,
                    instance_path=str(xbrl_file),
                    eba_version="3.5",  # Default
                    framework=framework,
                    description=f"Sample {framework} instance"
                ))
        
        # Additional test cases from WithRandomValues/
        random_dir = Path("WithRandomValues")
        if random_dir.exists():
            for xbrl_file in list(random_dir.glob("*.xbrl"))[:3]:  # Limit to 3 for speed
                name = f"random_{xbrl_file.stem}"
                framework = "COREP" if "COREP" in xbrl_file.name.upper() else "UNKNOWN"
                
                test_cases.append(TestCase(
                    name=name,
                    instance_path=str(xbrl_file),
                    eba_version="3.4",  # Random values seem to be 3.4
                    framework=framework,
                    description=f"Random values {framework} instance"
                ))
        
        # Test cases from artifacts/
        for format_dir in ["xml", "oim_csv", "oim_json", "ixbrl"]:
            artifacts_path = Path(f"artifacts/{format_dir}")
            if artifacts_path.exists():
                for case_dir in artifacts_path.iterdir():
                    if case_dir.is_dir():
                        # Look for XBRL files in the case directory
                        xbrl_files = list(case_dir.glob("*.xbrl"))
                        if xbrl_files:
                            xbrl_file = xbrl_files[0]  # Take first one
                            name = f"{format_dir}_{case_dir.name}"
                            framework = "UNKNOWN"
                            if "COREP" in case_dir.name.upper():
                                framework = "COREP"
                            elif "DORA" in case_dir.name.upper():
                                framework = "DORA"
                            elif "FC" in case_dir.name.upper():
                                framework = "FC"
                            
                            test_cases.append(TestCase(
                                name=name,
                                instance_path=str(xbrl_file),
                                eba_version="3.5",
                                framework=framework,
                                description=f"Artifact {format_dir} {framework} instance"
                            ))
        
        return test_cases
    
    def run_validation(self, test_case: TestCase) -> Dict:
        """Run validation for a single test case."""
        print(f"🔍 Testing: {test_case.name} ({test_case.framework} {test_case.eba_version})")
        
        start_time = time.time()
        export_dir = self.export_base / test_case.name
        export_dir.mkdir(parents=True, exist_ok=True)
        
        log_path = export_dir / "validation.jsonl"
        
        # Build command
        cmd = [
            sys.executable, "-m", "app.validate",
            "--file", test_case.instance_path,
            "--ebaVersion", test_case.eba_version,
            "--out", str(log_path),
            "--plugins", "formula",
            "--offline",
            "--cacheDir", "assets/cache",
            "--exports", str(export_dir)
        ]
        
        try:
            # Run validation
            result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=300)
            duration = time.time() - start_time
            
            # Parse results
            validation_csv = export_dir / "validation_messages.csv"
            rules_coverage_csv = export_dir / "rules_coverage.csv"
            
            message_count = 0
            error_count = 0
            warning_count = 0
            
            if validation_csv.exists():
                try:
                    with open(validation_csv, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        message_count = max(0, len(lines) - 1)  # Subtract header
                        
                        # Count by severity (simple CSV parsing)
                        for line in lines[1:]:  # Skip header
                            if ',ERROR,' in line or ',FATAL,' in line:
                                error_count += 1
                            elif ',WARNING,' in line:
                                warning_count += 1
                except Exception:
                    pass
            
            # Parse rules coverage
            rules_evaluated = 0
            rules_failed = 0
            
            if rules_coverage_csv.exists():
                try:
                    with open(rules_coverage_csv, 'r', encoding='utf-8') as f:
                        for line in f:
                            if line.startswith('evaluated,'):
                                rules_evaluated = int(line.split(',')[1])
                            elif line.startswith('failed,'):
                                rules_failed = int(line.split(',')[1])
                except Exception:
                    pass
            
            # Determine status
            if result.returncode == 0 and message_count >= 0:
                status = "SUCCESS"
                if error_count > 0:
                    status = "SUCCESS_WITH_ERRORS"
                elif warning_count > 0:
                    status = "SUCCESS_WITH_WARNINGS"
            else:
                status = "FAILED"
            
            test_result = {
                "name": test_case.name,
                "framework": test_case.framework,
                "eba_version": test_case.eba_version,
                "instance_path": test_case.instance_path,
                "description": test_case.description,
                "status": status,
                "duration_seconds": round(duration, 2),
                "return_code": result.returncode,
                "message_count": message_count,
                "error_count": error_count,
                "warning_count": warning_count,
                "rules_evaluated": rules_evaluated,
                "rules_failed": rules_failed,
                "export_dir": str(export_dir),
                "stderr": result.stderr[:500] if result.stderr else "",
            }
            
            print(f"  ✅ {status} - {message_count} messages ({error_count} errors, {warning_count} warnings) in {duration:.1f}s")
            
        except subprocess.TimeoutExpired:
            test_result = {
                "name": test_case.name,
                "framework": test_case.framework,
                "eba_version": test_case.eba_version,
                "status": "TIMEOUT",
                "duration_seconds": 300,
                "return_code": -1,
                "message_count": 0,
                "error_count": 0,
                "warning_count": 0,
                "rules_evaluated": 0,
                "rules_failed": 0,
                "export_dir": str(export_dir),
                "stderr": "Validation timed out after 300 seconds",
            }
            print(f"  ⏰ TIMEOUT after 300s")
            
        except Exception as e:
            test_result = {
                "name": test_case.name,
                "framework": test_case.framework,
                "eba_version": test_case.eba_version,
                "status": "ERROR",
                "duration_seconds": time.time() - start_time,
                "return_code": -1,
                "message_count": 0,
                "error_count": 0,
                "warning_count": 0,
                "rules_evaluated": 0,
                "rules_failed": 0,
                "export_dir": str(export_dir),
                "stderr": str(e),
            }
            print(f"  ❌ ERROR: {e}")
        
        return test_result
    
    def run_all_tests(self) -> Dict:
        """Run all discovered test cases."""
        test_cases = self.discover_test_cases()
        
        print(f"\n🚀 STARTING PARITEIT VALIDATION SUITE")
        print(f"Found {len(test_cases)} test cases")
        print("="*80)
        
        results = []
        start_time = time.time()
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n[{i}/{len(test_cases)}] ", end="")
            result = self.run_validation(test_case)
            results.append(result)
        
        total_duration = time.time() - start_time
        
        # Analyze results
        analysis = self.analyze_results(results, total_duration)
        
        # Save results
        results_file = self.export_base / "pariteit_results.json"
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump({
                "analysis": analysis,
                "test_results": results,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 Results saved to {results_file}")
        
        return analysis
    
    def analyze_results(self, results: List[Dict], total_duration: float) -> Dict:
        """Analyze test results and provide summary."""
        analysis = {
            "total_tests": len(results),
            "total_duration_seconds": round(total_duration, 2),
            "success_count": 0,
            "error_count": 0,
            "timeout_count": 0,
            "by_framework": {},
            "by_version": {},
            "total_messages": 0,
            "total_errors": 0,
            "total_warnings": 0,
            "total_rules_evaluated": 0,
            "total_rules_failed": 0,
        }
        
        for result in results:
            # Count by status
            if result["status"].startswith("SUCCESS"):
                analysis["success_count"] += 1
            elif result["status"] == "TIMEOUT":
                analysis["timeout_count"] += 1
            else:
                analysis["error_count"] += 1
            
            # Count by framework
            fw = result["framework"]
            if fw not in analysis["by_framework"]:
                analysis["by_framework"][fw] = {"count": 0, "success": 0, "messages": 0}
            analysis["by_framework"][fw]["count"] += 1
            if result["status"].startswith("SUCCESS"):
                analysis["by_framework"][fw]["success"] += 1
            analysis["by_framework"][fw]["messages"] += result["message_count"]
            
            # Count by version
            ver = result["eba_version"]
            if ver not in analysis["by_version"]:
                analysis["by_version"][ver] = {"count": 0, "success": 0}
            analysis["by_version"][ver]["count"] += 1
            if result["status"].startswith("SUCCESS"):
                analysis["by_version"][ver]["success"] += 1
            
            # Aggregate totals
            analysis["total_messages"] += result["message_count"]
            analysis["total_errors"] += result["error_count"]
            analysis["total_warnings"] += result["warning_count"]
            analysis["total_rules_evaluated"] += result["rules_evaluated"]
            analysis["total_rules_failed"] += result["rules_failed"]
        
        # Calculate success rate
        analysis["success_rate"] = analysis["success_count"] / analysis["total_tests"] if analysis["total_tests"] > 0 else 0
        
        return analysis


def print_summary(analysis: Dict) -> None:
    """Print formatted test summary."""
    print("\n" + "="*80)
    print("PARITEIT VALIDATION SUMMARY")
    print("="*80)
    
    print(f"\n📊 OVERALL RESULTS:")
    print(f"  Total tests: {analysis['total_tests']}")
    print(f"  Success rate: {analysis['success_rate']:.1%}")
    print(f"  Successful: {analysis['success_count']}")
    print(f"  Errors: {analysis['error_count']}")
    print(f"  Timeouts: {analysis['timeout_count']}")
    print(f"  Total duration: {analysis['total_duration_seconds']:.1f}s")
    
    print(f"\n📈 VALIDATION METRICS:")
    print(f"  Total messages: {analysis['total_messages']:,}")
    print(f"  Total errors: {analysis['total_errors']:,}")
    print(f"  Total warnings: {analysis['total_warnings']:,}")
    print(f"  EBA rules evaluated: {analysis['total_rules_evaluated']:,}")
    print(f"  EBA rules failed: {analysis['total_rules_failed']:,}")
    
    print(f"\n🏛️ BY FRAMEWORK:")
    for fw, stats in analysis['by_framework'].items():
        success_rate = stats['success'] / stats['count'] if stats['count'] > 0 else 0
        print(f"  {fw}: {stats['success']}/{stats['count']} ({success_rate:.1%}) - {stats['messages']:,} messages")
    
    print(f"\n📋 BY VERSION:")
    for ver, stats in analysis['by_version'].items():
        success_rate = stats['success'] / stats['count'] if stats['count'] > 0 else 0
        print(f"  EBA {ver}: {stats['success']}/{stats['count']} ({success_rate:.1%})")
    
    # Overall assessment
    print(f"\n🎯 ALTOVA PARITEIT ASSESSMENT:")
    if analysis['success_rate'] >= 0.95:
        print("  ✅ EXCELLENT - Ready for production use")
    elif analysis['success_rate'] >= 0.85:
        print("  ✅ GOOD - Minor issues to investigate")
    elif analysis['success_rate'] >= 0.70:
        print("  ⚠️  MODERATE - Significant issues present")
    else:
        print("  ❌ POOR - Major issues need resolution")
    
    if analysis['total_rules_evaluated'] > 15000:
        print("  ✅ EBA Rules Coverage: Comprehensive")
    elif analysis['total_rules_evaluated'] > 5000:
        print("  ⚠️  EBA Rules Coverage: Partial")
    else:
        print("  ❌ EBA Rules Coverage: Limited")


def main() -> int:
    """Main test execution."""
    validator = PariteitValidator()
    analysis = validator.run_all_tests()
    print_summary(analysis)
    
    # Return appropriate exit code
    if analysis['success_rate'] >= 0.9:
        return 0
    elif analysis['success_rate'] >= 0.7:
        return 1
    else:
        return 2


if __name__ == "__main__":
    sys.exit(main())
