from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
import zipfile


def _find_taxonomy_root(extracted_dir: Path) -> Path:
    # Prefer directory containing taxonomyPackage.xml (or taxonomy-package.xml)
    candidates = []
    for p in extracted_dir.rglob("taxonomyPackage.xml"):
        candidates.append(p.parent)
    for p in extracted_dir.rglob("taxonomy-package.xml"):
        candidates.append(p.parent)
    if candidates:
        # pick shortest path (closest to root)
        return sorted(candidates, key=lambda p: len(str(p)))[0]
    return extracted_dir


def _zip_dir(src_dir: Path, out_zip: Path) -> None:
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(out_zip), "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in src_dir.rglob("*"):
            if p.is_file():
                arc = p.relative_to(src_dir)
                zf.write(str(p), str(arc))


def main() -> int:
    ap = argparse.ArgumentParser(description="Convert EBA FullTaxonomy.7z to taxonomy ZIP")
    ap.add_argument("--input", required=True, help="Path to FullTaxonomy.7z")
    ap.add_argument("--out", required=True, help="Output taxonomy ZIP path (e.g., eba-3.5-taxonomy.zip)")
    ap.add_argument("--workdir", default=None, help="Working directory for extraction (optional)")
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.out)
    if not in_path.exists():
        print(f"[ERROR] Input not found: {in_path}", file=sys.stderr)
        return 2

    try:
        import py7zr  # type: ignore
    except Exception:
        print("[ERROR] py7zr is required. Install with: python3 -m pip install --break-system-packages py7zr", file=sys.stderr)
        return 2

    if args.workdir:
        tdir = Path(args.workdir)
        tdir.mkdir(parents=True, exist_ok=True)
        # Extract 7z
        with py7zr.SevenZipFile(str(in_path), mode="r") as z:
            z.extractall(path=str(tdir))
        root = _find_taxonomy_root(tdir)
        _zip_dir(root, out_path)
    else:
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            with py7zr.SevenZipFile(str(in_path), mode="r") as z:
                z.extractall(path=str(tdir))
            root = _find_taxonomy_root(tdir)
            _zip_dir(root, out_path)
    print(f"[OK] Wrote taxonomy ZIP: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


