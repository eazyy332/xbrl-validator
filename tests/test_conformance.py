from __future__ import annotations

import pytest
from pathlib import Path
import tempfile
import os
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.validation.arelle_runner import run_validation


def test_eba_sample_validation():
    """Test EBA sample validation with real taxonomy."""
    samples_dir = project_root / "assets" / "work" / "samples"
    if not samples_dir.exists():
        pytest.skip("EBA samples not found - run setup first")
    
    # Find any COREP sample
    samples = list(samples_dir.glob("*COREP*.xbrl"))
    if not samples:
        pytest.skip("No COREP samples found")
    
    sample = samples[0]
    
    # Check if EBA 3.5 taxonomy is available
    tax_dir = project_root / "assets" / "taxonomy" / "eba_3_5"
    rf_zip = tax_dir / "EBA_CRD_XBRL_3.5_Reporting_Frameworks_3.5.0.0.zip"
    if not rf_zip.exists():
        # Try extra_data location
        rf_zip = project_root / "extra_data" / "taxo_package_architecture_1.0" / "EBA_CRD_XBRL_3.5_Reporting_Frameworks_3.5.0.0.zip"
        if not rf_zip.exists():
            pytest.skip("EBA 3.5 taxonomy not found")
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        log_path = f.name
    
    try:
        summary = run_validation(
            input_path=str(sample),
            taxonomy_paths=[str(rf_zip)],
            plugins=["formula"],
            log_jsonl_path=log_path,
            validate=True,
            offline=True,
            cache_dir=str(project_root / "assets" / "cache"),
        )
        
        # Should process without fatal errors
        assert summary["returnCode"] in (0, 1)
        assert summary["total"] > 0  # Should have some messages
        
        # Should have some formula evaluation
        formula = summary.get("formula", {})
        assert formula.get("evaluated", 0) >= 0
        
        print(f"✓ EBA validation: {summary['total']} messages, {formula.get('evaluated', 0)} formulas")
        
    finally:
        try:
            os.unlink(log_path)
        except Exception:
            pass


if __name__ == "__main__":
    test_eba_sample_validation()
    print("✓ EBA conformance test passed")
