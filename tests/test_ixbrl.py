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


def test_ixbrl_sample():
    """Test that iXBRL sample can be loaded and validated."""
    sample_path = project_root / "samples" / "test_ixbrl.xhtml"
    
    if not sample_path.exists():
        pytest.skip("iXBRL sample not found")
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        log_path = f.name
    
    try:
        summary = run_validation(
            input_path=str(sample_path),
            taxonomy_paths=[],
            plugins=[],
            log_jsonl_path=log_path,
            validate=False,  # No schema available for this sample
            offline=True,
        )
        
        # Should at least load without crashing
        assert summary["returnCode"] in (0, 1)  # May have validation errors without schema
        assert summary["total"] >= 0
        
        # Check that JSONL was written
        assert Path(log_path).exists()
        
    finally:
        try:
            os.unlink(log_path)
        except Exception:
            pass


def test_oim_json_sample():
    """Test that OIM JSON sample can be loaded."""
    sample_path = project_root / "samples" / "test_oim.json"
    
    if not sample_path.exists():
        pytest.skip("OIM JSON sample not found")
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        log_path = f.name
    
    try:
        summary = run_validation(
            input_path=str(sample_path),
            taxonomy_paths=[],
            plugins=["oim", "LoadFromOIM"],
            log_jsonl_path=log_path,
            validate=False,  # No schema available for this sample
            offline=True,
        )
        
        # Should at least load without crashing
        assert summary["returnCode"] in (0, 1)
        assert summary["total"] >= 0
        
        # Check that JSONL was written
        assert Path(log_path).exists()
        
    finally:
        try:
            os.unlink(log_path)
        except Exception:
            pass


if __name__ == "__main__":
    test_ixbrl_sample()
    test_oim_json_sample()
    print("✓ iXBRL and OIM JSON samples tested")
