#!/usr/bin/env python3
"""Debug cache priming to see what's happening."""
from __future__ import annotations

import zipfile
from pathlib import Path


def debug_prime_from_packages(packages: list[str], cache_dir: str = "assets/cache") -> int:
    http_root = Path(cache_dir) / "http"
    http_root.mkdir(parents=True, exist_ok=True)
    copied = 0
    
    for pkg in packages:
        base = str(pkg).split("#", 1)[0]
        p = Path(base)
        print(f"Processing package: {p}")
        print(f"  Exists: {p.exists()}")
        print(f"  Is ZIP: {p.suffix.lower() == '.zip'}")
        
        if not p.exists() or not p.suffix.lower() == ".zip":
            print(f"  SKIPPING: {pkg}")
            continue
            
        try:
            with zipfile.ZipFile(str(p), "r") as zf:
                all_names = zf.namelist()
                print(f"  Total files in ZIP: {len(all_names)}")
                
                # Filter for XSD/XML
                xml_files = [n for n in all_names if n.lower().endswith((".xsd", ".xml"))]
                print(f"  XSD/XML files: {len(xml_files)}")
                
                # Filter for HTTP resources
                http_files = []
                for name in xml_files:
                    low = name.lower()
                    if any(marker in low for marker in (
                        "www.eba.europa.eu/",
                        "www.eurofiling.info/", 
                        "www.xbrl.org/",
                        "www.w3.org/",
                        "eba.europa.eu/",
                        "eurofiling.info/",
                        "xbrl.org/",
                        "w3.org/",
                    )):
                        http_files.append(name)
                
                print(f"  HTTP XSD/XML files: {len(http_files)}")
                print(f"  First 3 HTTP files:")
                for f in http_files[:3]:
                    print(f"    {f}")
                
                # Try to extract first few
                for name in http_files[:5]:
                    target = http_root / name
                    if target.exists():
                        print(f"    SKIP (exists): {name}")
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        with zf.open(name, "r") as src, open(target, "wb") as dst:
                            dst.write(src.read())
                        copied += 1
                        print(f"    COPIED: {name} -> {target}")
                    except Exception as e:
                        print(f"    ERROR copying {name}: {e}")

        except Exception as e:
            print(f"  ERROR processing {pkg}: {e}")
            continue
            
    return copied


if __name__ == "__main__":
    packages = [
        "extra_data/taxo_package_architecture_1.0/EBA_CRD_XBRL_3.5_Reporting_Frameworks_3.5.0.0.zip",
        "extra_data/taxo_package_architecture_1.0/EBA_CRD_IV_XBRL_3.5_Dictionary_3.5.0.0.zip",
    ]
    
    copied = debug_prime_from_packages(packages)
    print(f"\nTotal copied: {copied}")
    
    # Check what's in cache now
    cache_http = Path("assets/cache/http")
    if cache_http.exists():
        files = list(cache_http.rglob("*"))
        print(f"Files in cache: {len(files)}")
        for f in files[:5]:
            print(f"  {f}")
