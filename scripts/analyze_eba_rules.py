#!/usr/bin/env python3
"""Analyze EBA rules to understand full coverage vs curated subset."""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.validation.eba_rules_loader import load_rules_from_excel


def main():
    # Load full rules without curation
    excel_path = "eba_validation_rules/eba_validation_rules_2025-03-10.xlsx"
    
    if not Path(excel_path).exists():
        print(f"❌ EBA rules Excel not found: {excel_path}")
        return 1
    
    print("Loading EBA validation rules...")
    data = load_rules_from_excel(excel_path)
    print(f"✅ Total rules in Excel: {data['count']}")

    # Count by framework
    frameworks = {}
    severities = {}
    active_count = 0
    
    for r in data['rules']:
        fw = r.get('framework', 'unknown')
        frameworks[fw] = frameworks.get(fw, 0) + 1
        
        sev = r.get('severity', 'UNKNOWN')
        severities[sev] = severities.get(sev, 0) + 1
        
        if r.get('active', True):
            active_count += 1

    print(f"\n📊 ANALYSIS:")
    print(f"  Total rules: {data['count']}")
    print(f"  Active rules: {active_count}")
    print(f"  Inactive rules: {data['count'] - active_count}")

    print(f"\n🏛️ Rules by framework:")
    for fw, count in sorted(frameworks.items(), key=lambda x: x[1], reverse=True):
        print(f"  {fw}: {count}")

    print(f"\n⚠️ Rules by severity:")
    for sev, count in sorted(severities.items(), key=lambda x: x[1], reverse=True):
        print(f"  {sev}: {count}")
    
    # Load curated rules
    curated_path = Path("config/curated_rules.json")
    if curated_path.exists():
        import json
        curated_ids = set(json.loads(curated_path.read_text(encoding="utf-8")))
        print(f"\n🎯 CURATED SUBSET:")
        print(f"  Curated rules: {len(curated_ids)}")
        
        # Find which curated rules exist in Excel
        excel_ids = {r.get('id', '') for r in data['rules']}
        found_curated = curated_ids & excel_ids
        missing_curated = curated_ids - excel_ids
        
        print(f"  Found in Excel: {len(found_curated)}")
        print(f"  Missing from Excel: {len(missing_curated)}")
        
        if missing_curated:
            print(f"  Missing IDs: {sorted(list(missing_curated))[:10]}...")
        
        # Coverage percentage
        coverage = (len(found_curated) / active_count) * 100 if active_count > 0 else 0
        print(f"  Coverage: {coverage:.1f}% of active rules")
    
    print(f"\n💡 RECOMMENDATIONS:")
    if active_count > 500:
        print(f"  • Remove config/curated_rules.json to enable all {active_count} active rules")
        print(f"  • Current curated mode limits to only 500 rules ({coverage:.1f}% coverage)")
    
    print(f"  • For Altova parity, we need to evaluate all active rules")
    print(f"  • Consider framework-specific curation (e.g., only COREP rules for COREP instances)")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
