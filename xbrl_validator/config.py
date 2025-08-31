from __future__ import annotations

from pathlib import Path
import json
from typing import Optional


def get_project_root() -> Path:
    cur = Path(__file__).resolve().parent
    for _ in range(6):
        if (cur / "config" / "taxonomy.json").exists():
            return cur
        cur = cur.parent
    return Path.cwd()


def _load_settings() -> dict:
    settings_path = get_project_root() / "config" / "settings.json"
    if settings_path.exists():
        try:
            return json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def get_dpm_sqlite_path() -> str:
    s = _load_settings()
    val = s.get("dpm_sqlite")
    if val:
        return str(Path(val))
    return str(get_project_root() / "assets" / "dpm.sqlite")


def get_samples_dir() -> str:
    s = _load_settings()
    val = s.get("samples_dir")
    if val:
        return str(Path(val))
    return str(get_project_root() / "assets" / "work" / "samples")


def get_cache_dir() -> str:
    s = _load_settings()
    val = s.get("cache_dir")
    if val:
        return str(Path(val))
    return str(get_project_root() / "assets" / "cache")


def get_eba_rules_excel_path() -> str | None:
    """Return the configured path to the EBA Filing Rules Excel if present.

    Falls back to scanning extra_data for likely filenames.
    """
    s = _load_settings()
    val = s.get("eba_rules_excel")
    if val:
        p = Path(val)
        return str(p) if p.exists() else None
    extra = get_project_root() / "extra_data"
    if extra.exists():
        # pick largest xlsx containing EBA + Rule(s)
        cands = sorted(
            [p for p in extra.rglob("*.xlsx") if any(k in p.name.lower() for k in ("eba", "rule"))],
            key=lambda p: p.stat().st_size if p.exists() else 0,
            reverse=True,
        )
        if cands:
            return str(cands[0])
    return None


def set_eba_rules_excel_path(path: str) -> None:
    """Persist the EBA rules Excel absolute path into config/settings.json."""
    settings_path = get_project_root() / "config" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        s = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    except Exception:
        s = {}
    s["eba_rules_excel"] = str(Path(path).resolve())
    settings_path.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_eba_rules_caches() -> None:
    """Delete cached EBA rules cache/index files to force rebuild."""
    cache_dir = get_project_root() / "assets" / "cache"
    try:
        # Remove legacy single-cache and new per-fingerprint caches
        for p in [cache_dir / "eba_rules_cache.json"] + list(cache_dir.glob("eba_rules_cache_*.json")):
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
        for idx in cache_dir.glob("eba_rules_index_*.json"):
            try:
                idx.unlink()
            except Exception:
                pass
    except Exception:
        pass

