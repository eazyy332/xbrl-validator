from __future__ import annotations

from pathlib import Path
from typing import Iterable, Dict, Any
import xml.etree.ElementTree as ET


def write_junit(messages: Iterable[Dict[str, Any]], out_path: str) -> str:
    """Write a minimal JUnit XML file mapping validation messages to testcases.

    - One testsuite named 'xbrl-validation'
    - Each message -> one testcase; non-INFO severities become failures
    """
    tests = list(messages)
    ts = ET.Element("testsuite", attrib={
        "name": "xbrl-validation",
        "tests": str(len(tests)),
        "failures": str(sum(1 for m in tests if (m.get("level") or "INFO").upper() in ("WARNING", "ERROR", "FATAL"))),
    })
    for m in tests:
        code = (m.get("code") or "").strip() or "NO_CODE"
        sev = (m.get("level") or "INFO").upper()
        name = f"{sev}:{code}"
        tc = ET.SubElement(ts, "testcase", attrib={"classname": "xbrl", "name": name})
        if sev in ("WARNING", "ERROR", "FATAL"):
            fail = ET.SubElement(tc, "failure", attrib={"type": sev, "message": code})
            fail.text = m.get("message") or ""
    tree = ET.ElementTree(ts)
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tree.write(p, encoding="utf-8", xml_declaration=True)
    return str(p)


