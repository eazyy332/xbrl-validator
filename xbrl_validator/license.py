from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


# Public key for license signature verification (Ed25519 raw 32-byte key in base64)
# Replace with your real production public key when issuing licenses
_PUBLIC_KEY_B64 = (
    "n5bqHq3Qm6m3zqgVnZ7v2mFQ9y7Q1o0k2kqgB7XK1eE="
)


@dataclass
class LicenseStatus:
    state: str  # valid | trial | expired_trial | absent | invalid
    name: Optional[str] = None
    company: Optional[str] = None
    edition: Optional[str] = None
    expires: Optional[str] = None
    reason: Optional[str] = None


def _settings_path() -> Path:
    from .config import get_project_root  # lazy import
    return get_project_root() / "config" / "settings.json"


def _load_settings() -> Dict[str, Any]:
    p = _settings_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_settings(data: Dict[str, Any]) -> None:
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_public_key_b64() -> str:
    # Allow override via config/settings.json or env
    try:
        s = _load_settings()
        v = s.get("public_key_b64")
        if v:
            return str(v).strip()
    except Exception:
        pass
    v = os.environ.get("XBRL_VALIDATOR_PUBLIC_KEY_B64")
    if v:
        return v.strip()
    return _PUBLIC_KEY_B64


def _default_license_locations() -> list[Path]:
    from .config import get_project_root
    locs: list[Path] = []
    env = os.environ.get("XBRL_VALIDATOR_LICENSE")
    if env:
        locs.append(Path(env))
    # Configured path in settings
    s = _load_settings()
    lp = s.get("license_path")
    if lp:
        locs.append(Path(lp))
    # Project config
    locs.append(get_project_root() / "config" / "license.json")
    # User home
    locs.append(Path.home() / ".xbrl_validator" / "license.json")
    return locs


def load_license_file() -> Tuple[Optional[Dict[str, Any]], Optional[Path]]:
    for p in _default_license_locations():
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                return data, p
        except Exception:
            continue
    return None, None


def set_license_path(path: str) -> None:
    s = _load_settings()
    s["license_path"] = str(Path(path).resolve())
    _save_settings(s)


def _verify_signature(payload: Dict[str, Any], signature_b64: str) -> bool:
    try:
        signed = dict(payload)
        if "signature" in signed:
            signed.pop("signature")
        blob = json.dumps(signed, sort_keys=True, separators=(",", ":")).encode("utf-8")
        sig = base64.b64decode(signature_b64)
        pub = base64.b64decode(_get_public_key_b64())
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            from cryptography.exceptions import InvalidSignature
        except Exception:
            # cryptography not installed
            return False
        key = Ed25519PublicKey.from_public_bytes(pub)
        try:
            key.verify(sig, blob)
            return True
        except InvalidSignature:
            return False
    except Exception:
        return False


def _parse_date(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00").replace("/", "-"))
    except Exception:
        return None


def _trial_state() -> Tuple[str, Optional[str]]:
    s = _load_settings()
    started = s.get("trial_started_at")
    days = int(s.get("trial_days", 14))
    if not started:
        # initialize trial on first call
        now = datetime.utcnow().isoformat()
        s["trial_started_at"] = now
        s["trial_days"] = days
        _save_settings(s)
        return "trial", None
    dt = _parse_date(started)
    if not dt:
        return "trial", None
    if datetime.utcnow() <= dt + timedelta(days=days):
        return "trial", None
    return "expired_trial", f"Trial expired (>{days} days)"


def get_license_status() -> LicenseStatus:
    data, path = load_license_file()
    if not data:
        st, why = _trial_state()
        return LicenseStatus(state=st, reason=why)
    if not isinstance(data, dict):
        return LicenseStatus(state="invalid", reason="Malformed license file")
    sig = str(data.get("signature") or "")
    if not sig:
        return LicenseStatus(state="invalid", reason="Missing signature")
    ok = _verify_signature(data, sig)
    if not ok:
        return LicenseStatus(state="invalid", reason="Signature verification failed")
    # Expiry check (optional)
    exp = data.get("expires")
    if exp:
        dt = _parse_date(str(exp))
        if dt and datetime.utcnow() > dt:
            return LicenseStatus(state="invalid", reason="License expired", expires=str(exp))
    return LicenseStatus(
        state="valid",
        name=str(data.get("name") or ""),
        company=str(data.get("company") or ""),
        edition=str(data.get("edition") or "Standard"),
        expires=str(exp) if exp else None,
        reason=str(path) if path else None,
    )


def is_eval_mode() -> bool:
    st = get_license_status().state
    return st in ("trial", "expired_trial", "absent", "invalid")


def watermark_text() -> Optional[str]:
    st = get_license_status()
    if st.state == "valid":
        return None
    if st.state == "expired_trial":
        return "Evaluation expired - Not for redistribution"
    return "Evaluation copy - Not for redistribution"


def licensed_to_text() -> str:
    st = get_license_status()
    if st.state == "valid":
        who = st.company or st.name or "Licensed user"
        return f"Licensed to: {who}"
    if st.state == "trial":
        return "Evaluation license"
    if st.state == "expired_trial":
        return "Evaluation expired"
    return "Unlicensed"


def feature_enabled(feature_name: str) -> bool:
    # Optional feature gating by license payload; falls back to edition matrix in config/features.json
    data, _ = load_license_file()
    if not data or not isinstance(data, dict):
        return False
    # 1) Explicit features array in license
    feats = data.get("features") or []
    if feats:
        try:
            return str(feature_name).lower() in [str(f).lower() for f in feats]
        except Exception:
            return False
    # 2) Edition mapping
    ed = str(data.get("edition") or "").strip() or "Standard"
    try:
        from .config import get_project_root
        p = get_project_root() / "config" / "features.json"
        if p.exists():
            cfg = json.loads(p.read_text(encoding="utf-8"))
            eds = (cfg.get("editions") or {})
            arr = [str(x) for x in (eds.get(ed) or [])]
            return str(feature_name) in arr or str(feature_name).lower() in [a.lower() for a in arr]
    except Exception:
        return False
    return False


