from __future__ import annotations

import io
import zipfile
from typing import List, Optional, Tuple
import os
from xml.etree import ElementTree as ET


def _read_taxonomy_package_xml(package_zip_path: str) -> Optional[bytes]:
    with zipfile.ZipFile(package_zip_path, "r") as zf:
        # Find META-INF/taxonomyPackage.xml
        for name in zf.namelist():
            lower_name = name.lower()
            if lower_name.endswith("meta-inf/taxonomypackage.xml"):
                with zf.open(name, "r") as fp:
                    return fp.read()
    return None


def list_entry_points(package_zip_path: str) -> List[Tuple[str, str]]:
    """
    Returns a list of (label, entry_uri) from taxonomyPackage.xml in the zip.
    The entry_uri is typically an absolute URI to the entry XSD.
    """
    data = _read_taxonomy_package_xml(package_zip_path)
    if data is None:
        return []
    try:
        tree = ET.parse(io.BytesIO(data))
    except ET.ParseError:
        return []

    ns = {
        "tp": "http://xbrl.org/2016/taxonomy-package",
        "link": "http://www.xbrl.org/2003/linkbase",
    }
    entry_points: List[Tuple[str, str]] = []
    for ep in tree.findall(".//tp:entryPoint", ns):
        # PreferredLabel or name may be available; fall back to entryURI
        label_el = ep.find("tp:name", ns)
        if label_el is None:
            label_el = ep.find("tp:description", ns)
        entry_uri_el = ep.find("tp:entryURI", ns)
        if entry_uri_el is None:
            continue
        label = (label_el.text or entry_uri_el.text or "").strip()
        entry_uri = (entry_uri_el.text or "").strip()
        if entry_uri:
            entry_points.append((label, entry_uri))
    return entry_points


def to_zip_entry_syntax(package_zip_path: str, entry_uri: str) -> str:
    """
    Convert an absolute entry URI to a zip#entry syntax usable by Arelle.
    Tries multiple candidates by inspecting the zip contents:
      1) host+path (e.g. www.eba.europa.eu/eu/fr/xbrl/....xsd)
      2) path-only (e.g. eu/fr/xbrl/....xsd)
      3) any member that endswith the path-only
      4) any member that endswith the basename
    Falls back to host+path if nothing matches.
    """
    cleaned = entry_uri
    if "://" in cleaned:
        cleaned = cleaned.split("://", 1)[1]
    host_plus_path = cleaned
    # Derive path-only by stripping host segment
    path_only = cleaned.split("/", 1)[1] if "/" in cleaned else cleaned
    basename = os.path.basename(path_only)

    try:
        with zipfile.ZipFile(package_zip_path, "r") as zf:
            names = zf.namelist()
            # Prefer exact matches
            if host_plus_path in names:
                return f"{package_zip_path}#{host_plus_path}"
            if path_only in names:
                return f"{package_zip_path}#{path_only}"
            # Case-insensitive suffix match for path-only
            pol = path_only.lower()
            for n in names:
                if n.lower().endswith(pol):
                    return f"{package_zip_path}#{n}"
            # Fallback: basename match
            bnl = basename.lower()
            for n in names:
                if n.lower().endswith(bnl):
                    return f"{package_zip_path}#{n}"
    except Exception:
        pass
    # Last resort: return host+path
    return f"{package_zip_path}#{host_plus_path}"


