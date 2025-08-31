import argparse
import hashlib
import os
from pathlib import Path
from typing import Optional

import requests


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", "0")) or None
        written = 0
        with out_path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    written += len(chunk)
                    if total:
                        pct = (written / total) * 100
                        print(f"\rDownloading: {written}/{total} bytes ({pct:.1f}%)", end="")
    print("\nDownload complete:", out_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download EBA taxonomy package")
    parser.add_argument("--url", required=True, help="Download URL for taxonomy package zip")
    parser.add_argument("--out", required=True, help="Output file path for the zip")
    parser.add_argument("--sha256", required=False, help="Expected SHA256 to verify (optional)")
    args = parser.parse_args()

    out_path = Path(args.out)
    download(args.url, out_path)

    if args.sha256:
        actual = sha256_file(out_path)
        if actual.lower() != args.sha256.lower():
            print("SHA256 mismatch! Expected:", args.sha256, "Actual:", actual)
            return 2
        print("SHA256 verified:", actual)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

