from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    spec = root / "packaging" / "pyinstaller_gui.spec"
    if not spec.exists():
        print(f"[error] spec not found: {spec}")
        return 2
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])  # ensure installed
        cmd = [sys.executable, "-m", "PyInstaller", str(spec), "--noconfirm"]
        print("[build]", " ".join(cmd))
        subprocess.check_call(cmd)
        dist = root / "dist" / "XBRLValidatorGUI"
        if dist.exists():
            print(f"[build] GUI bundled at: {dist}")
        else:
            print("[warn] dist folder not found; check PyInstaller output")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"[error] build failed: {e}")
        return e.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())


