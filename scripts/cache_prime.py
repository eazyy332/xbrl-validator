from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Iterable


def prime_from_packages(packages: Iterable[str], cache_dir: str = "assets/cache") -> int:
    http_root = Path(cache_dir) / "http"
    http_root.mkdir(parents=True, exist_ok=True)
    copied = 0
    for pkg in packages:
        base = str(pkg).split("#", 1)[0]
        p = Path(base)
        if not p.exists() or not p.suffix.lower() == ".zip":
            continue
        try:
            with zipfile.ZipFile(str(p), "r") as zf:
                for name in zf.namelist():
                    low = name.lower()
                    if not low.endswith((".xsd", ".xml")):
                        continue
                    # More aggressive extraction - include any HTTP-style resource
                    if not any(marker in low for marker in (
                        "www.eba.europa.eu/",
                        "www.eurofiling.info/", 
                        "www.xbrl.org/",
                        "www.w3.org/",
                        "eba.europa.eu/",
                        "eurofiling.info/",
                        "xbrl.org/",
                        "w3.org/",
                    )):
                        continue
                    target = http_root / name
                    if target.exists():
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name, "r") as src, open(target, "wb") as dst:
                        dst.write(src.read())
                        copied += 1
        except Exception:
            continue
    return copied


def main() -> int:
    cfg = Path("config/taxonomy.json")
    if not cfg.exists():
        print("[error] missing config/taxonomy.json")
        return 2
    import json
    data = json.loads(cfg.read_text(encoding="utf-8"))
    stacks = []
    for key in ("eba_3_4", "eba_3_5"):
        stacks.extend([str(p) for p in (data.get("stacks", {}).get(key, []) or [])])
    n = prime_from_packages(stacks)
    print(f"[prime] copied {n} resources into assets/cache/http")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


