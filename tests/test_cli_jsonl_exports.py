import os
from pathlib import Path
import subprocess


def test_cli_jsonl_exports(tmp_path: Path):
    project_root = Path(__file__).parent.parent
    py = os.environ.get("PYTHON", "python3")
    exports_dir = tmp_path / "exports"
    jsonl_path = tmp_path / "run.jsonl"
    sample = project_root / "samples" / "test_oim.json"
    if not sample.exists():
        # skip if sample missing
        return
    cmd = [
        py, "-m", "xbrl_validator.cli",
        "--file", str(sample),
        "--exports", str(exports_dir),
        "--out-jsonl", str(jsonl_path),
        "--summary",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode in (0, 1)
    # Exports should exist
    assert (exports_dir / "validation_messages.csv").exists()
    assert (exports_dir / "results_by_file.json").exists()
    assert (exports_dir / "formula_rollup.csv").exists()
    assert (exports_dir / "validation_report.xlsx").exists()
    assert (exports_dir / "validation_summary.pdf").exists()


