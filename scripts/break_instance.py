from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: break_instance.py <path-to-instance.xbrl>")
        return 2
    src = Path(sys.argv[1])
    if not src.exists():
        print(f"[error] file not found: {src}")
        return 2
    dst_dir = Path("assets/work/tmp")
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / (src.stem + ".broken" + src.suffix)

    text = src.read_text(encoding="utf-8", errors="ignore")

    # Intentionally break 1: make the first fact refer to an undefined unit
    new_text, n1 = re.subn(r'unitRef="([^"]+)"', 'unitRef="MISSING_UNIT_XYZ"', text, count=1)
    changed = n1 > 0

    # Intentionally break 2: if no unitRef found, break contextRef instead
    if not changed:
        new_text, n2 = re.subn(r'contextRef="([^"]+)"', 'contextRef="MISSING_CTX_ABC"', text, count=1)
        changed = n2 > 0
    
    # Intentionally break 3: try removing all <context> elements to force schema errors
    if not changed:
        text2 = text
    else:
        text2 = new_text
    text3 = re.sub(r'<context\b[\s\S]*?</context>', '', text2, flags=re.IGNORECASE)
    new_text = text3
    changed = True

    dst.write_text(new_text if changed else text, encoding="utf-8")
    if changed:
        print(f"[info] wrote broken copy: {dst}")
    else:
        print("[warn] no changes made; copied unchanged")
    print(str(dst))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


