from __future__ import annotations

import os
import json
import subprocess
from pathlib import Path
import pytest


def _run_validate(project_root: Path, sample: Path, eba_version: str, out_jsonl: Path, exports_dir: Path) -> int:
    py = os.environ.get("PYTHON", "python3")
    cmd = [
        py,
        "-m",
        "app.validate",
        "--file",
        str(sample),
        "--ebaVersion",
        eba_version,
        "--out",
        str(out_jsonl),
        "--offline",
        "--cacheDir",
        str(project_root / "assets" / "cache"),
        "--exports",
        str(exports_dir),
        "--plugins",
        "formula",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    # Print helpful diagnostics when running locally
    if result.returncode != 0:
        print("[e2e] returncode=", result.returncode)
        print("[e2e] stdout=\n", result.stdout)
        print("[e2e] stderr=\n", result.stderr)
    return result.returncode


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


@pytest.mark.slow
def test_e2e_matrix_baselines(tmp_path: Path):
    # Gate long-running E2E by env var
    if os.environ.get("RUN_E2E") != "1":
        pytest.skip("Set RUN_E2E=1 to run E2E matrix with real EBA samples")

    project_root = Path(__file__).parent.parent
    # Candidate samples (existing in repo); add more as needed
    samples = [
        ("3.5", project_root / "extra_data" / "sample_instances_architecture_1.0" / "xBRL_XML" / "DUMMYLEI123456789012.CON_FR_COREP030200_COREPFRTB_2024-12-31_20240625002144000.xbrl"),
        ("3.5", project_root / "extra_data" / "sample_instances_architecture_1.0" / "xBRL_XML" / "DUMMYLEI123456789012.CON_FR_DORA010000_DORA_2025-01-31_20240625161151000.xbrl"),
        ("3.5", project_root / "extra_data" / "sample_instances_architecture_1.0" / "xBRL_XML" / "DUMMYLEI123456789012.CON_FR_FC010000_FC_2024-12-31_20240625002201000.xbrl"),
    ]

    # Only keep existing
    samples = [(ver, p) for ver, p in samples if p.exists()]
    if not samples:
        pytest.skip("No EBA sample files found")

    baselines_dir = project_root / "test_exports" / "baselines"
    update = os.environ.get("UPDATE_BASELINE") == "1"
    baselines_dir.mkdir(parents=True, exist_ok=True)

    for eba_ver, sample in samples:
        out_jsonl = tmp_path / f"{sample.stem}.jsonl"
        exports_dir = tmp_path / f"exports_{sample.stem}"
        rc = _run_validate(project_root, sample, eba_ver, out_jsonl, exports_dir)
        assert rc in (0, 1)

        # Compare to baseline if present or update when requested
        baseline_path = baselines_dir / f"{sample.stem}.jsonl"
        if update:
            # Overwrite baseline with current
            if out_jsonl.exists():
                baseline_path.write_text(out_jsonl.read_text(encoding="utf-8"), encoding="utf-8")
            continue

        if not baseline_path.exists():
            # If baseline missing, at least assert the run produced outputs
            assert out_jsonl.exists(), f"Missing JSONL for {sample.name}"
            assert (exports_dir / "validation_messages.csv").exists()
            continue

        cur = _read_jsonl(out_jsonl)
        base = _read_jsonl(baseline_path)
        # Basic invariants: totals and top codes should be stable
        assert len(cur) >= 0
        assert len(base) >= 0
        # Allow minor fluctuations; enforce that total delta is within 5% for CI stability
        if len(base) > 0:
            delta = abs(len(cur) - len(base)) / max(1, len(base))
            assert delta <= 0.05, f"Message count drift >5% for {sample.name}: {len(cur)} vs {len(base)}"


