from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any, Dict, Optional


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _write_text(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def gen_keypair(out_dir: Path) -> int:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
    except Exception:
        print("[error] cryptography is required: pip install cryptography")
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    private_bytes = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    (_out_priv := out_dir / "ed25519.priv.base64").write_text(base64.b64encode(private_bytes).decode("ascii"), encoding="utf-8")
    (_out_pub := out_dir / "ed25519.pub.base64").write_text(base64.b64encode(public_bytes).decode("ascii"), encoding="utf-8")
    print("[ok] wrote:", _out_priv)
    print("[ok] wrote:", _out_pub)
    return 0


def sign_license(private_key_b64: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64))
    data = dict(payload)
    data.pop("signature", None)
    blob = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = priv.sign(blob)
    data["signature"] = base64.b64encode(sig).decode("ascii")
    return data


def cmd_sign(args) -> int:
    priv_b64 = _read_text(Path(args.private_key))
    payload: Dict[str, Any] = {
        "name": args.name or "",
        "company": args.company or "",
        "edition": args.edition or "Standard",
        "expires": args.expires or "",
        "features": [s.strip() for s in (args.features.split(",") if args.features else []) if s.strip()],
    }
    lic = sign_license(priv_b64, payload)
    out = Path(args.out)
    _write_text(out, json.dumps(lic, ensure_ascii=False, indent=2))
    print("[ok] license written:", out)
    return 0


def cmd_verify(args) -> int:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except Exception:
        print("[error] cryptography is required: pip install cryptography")
        return 2
    pub_b64 = _read_text(Path(args.public_key))
    lic = json.loads(_read_text(Path(args.license)))
    sig_b64 = lic.get("signature") or ""
    if not sig_b64:
        print("[invalid] missing signature")
        return 1
    signed = dict(lic)
    signed.pop("signature", None)
    blob = json.dumps(signed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = base64.b64decode(sig_b64)
    pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64))
    try:
        pub.verify(sig, blob)
        print("[valid] signature ok")
        return 0
    except InvalidSignature:
        print("[invalid] signature mismatch")
        return 1


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description="License generator and verifier (offline)")
    sub = p.add_subparsers(dest="cmd", required=True)
    p_gen = sub.add_parser("gen-keypair", help="Generate ed25519 keypair in base64 files")
    p_gen.add_argument("out_dir", help="Output directory for key files")
    p_gen.set_defaults(func=lambda a: gen_keypair(Path(a.out_dir)))

    p_sign = sub.add_parser("sign", help="Sign a license payload with a private key")
    p_sign.add_argument("--private-key", required=True, help="Path to ed25519.priv.base64")
    p_sign.add_argument("--out", required=True, help="Output license.json path")
    p_sign.add_argument("--name", required=False, default="", help="Licensee name")
    p_sign.add_argument("--company", required=False, default="", help="Licensee company")
    p_sign.add_argument("--edition", required=False, default="Standard", help="Edition: Standard/Pro/Enterprise")
    p_sign.add_argument("--expires", required=False, default="", help="ISO date (UTC), empty for perpetual")
    p_sign.add_argument("--features", required=False, default="", help="Comma-separated feature flags")
    p_sign.set_defaults(func=cmd_sign)

    p_ver = sub.add_parser("verify", help="Verify a license against a public key")
    p_ver.add_argument("--public-key", required=True, help="Path to ed25519.pub.base64")
    p_ver.add_argument("--license", required=True, help="Path to license.json")
    p_ver.set_defaults(func=cmd_verify)

    def cmd_configure_pubkey(args) -> int:
        try:
            from xbrl_validator.config import get_project_root
            cfg = get_project_root() / "config" / "settings.json"
            data = {}
            if cfg.exists():
                try:
                    data = json.loads(cfg.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            data["public_key_b64"] = Path(args.public_key).read_text(encoding="utf-8").strip()
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print("[ok] updated:", cfg)
            return 0
        except Exception as e:
            print("[error]", e)
            return 1
    p_cfg = sub.add_parser("configure-pubkey", help="Store public key base64 into config/settings.json")
    p_cfg.add_argument("--public-key", required=True, help="Path to ed25519.pub.base64")
    p_cfg.set_defaults(func=cmd_configure_pubkey)

    args = p.parse_args(argv)
    try:
        if hasattr(args, "func"):
            return args.func(args)
        print("[error] no command")
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())


