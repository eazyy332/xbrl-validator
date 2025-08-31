# Full EBA XBRL Validator Completeness Proof

## Coverage vs. Criteria

| # | Criteria | Status | Note |
|---|---|---|---|
| 1 |  | ✅ | EBA stacks discovered from config/taxonomy.json; SHA256 recorded in artifacts/taxonomy_hashes.json |
| 2 |  | ✅ | Arelle CLI used via app.validate with formula active; JSONL shows formula stats |
| 3 |  | ❌ | Filing rules engine implemented (Excel), but full coverage not yet 100% (work in progress) |
| 4 |  | ✅ | Deterministic DPM mapping to template/table/cell via SQLite |
| 5 |  | ✅ | XML/iXBRL/OIM JSON/OIM CSV executed |
| 6 |  | ✅ | CLI + GUI + API present in repo |
| 7 |  | ✅ | Offline cache used; timings captured per file |
| 8 |  | ✅ | CSV/JSON/Excel/PDF outputs produced per run |
| 9 |  | ✅ | Run: python scripts/selftest.py |
| 10 |  | ✅ | Unit/integration tests under tests/ all passing |
| 11 |  | ❌ | Review/lock Arelle and pip deps for strict pinning |
| 12 |  | ✅ | README includes quick start and examples |

## Stacks and Hashes

- eba_3_4:
  - `assets/work/eba-package/EBA_CRD_XBRL_3.4_Reporting_Frameworks_3.4.0.0.zip`: `614af9f6cc113b208277d000c07a71407477fb1c9572e953f11b4cfce01308f2`
  - `assets/work/eba-package/EBA_CRD_IV_XBRL_3.4_Dictionary_3.4.0.0.zip`: `4b34657abb0954b4387da1c1cec11c5b9eff19aedd4475305f02a1f722a2d716`
  - `assets/work/eba-package/EBA_CRD_IV_XBRL_3.4_Severity_3.4.0.0.zip`: `9ee430ae3fa338288913d00487570fc91c29a4ab71fec6b2acccb29f1f8e6ed3`
- eba_3_5:
  - `extra_data/taxo_package_architecture_1.0/EBA_CRD_XBRL_3.5_Reporting_Frameworks_3.5.0.0.zip`: `4b48a3defd6318d68612d0e9da6326e107195382db112abcc481c2fe926fd475`
  - `extra_data/taxo_package_architecture_1.0/EBA_CRD_IV_XBRL_3.5_Dictionary_3.5.0.0.zip`: `3e1e2d2f4f2b5984ede6b8f500f16f0542a36b6573264e57004c7362e89a689d`
  - `extra_data/taxo_package_architecture_1.0/EBA_CRD_IV_XBRL_3.5_Severity_3.5.0.0.zip`: `6a084c683d12364fb6506427e84d3f188fff3ba4add021132b8f2105d7a06dce`

## Runs

- `xml` `DUMMYLEI123456789012.CON_FR_COREP030200_COREPFRTB_2024-12-31_20240625002144000.xbrl` rc=0 time=0.40s -> artifacts/xml/DUMMYLEI123456789012.CON_FR_COREP030200_COREPFRTB_2024-12-31_20240625002144000/validation.jsonl
- `xml` `DUMMYLEI123456789012.CON_FR_DORA010000_DORA_2025-01-31_20240625161151000.xbrl` rc=0 time=30.80s -> artifacts/xml/DUMMYLEI123456789012.CON_FR_DORA010000_DORA_2025-01-31_20240625161151000/validation.jsonl
- `xml` `DUMMYLEI123456789012.CON_FR_FC010000_FC_2024-12-31_20240625002201000.xbrl` rc=0 time=0.52s -> artifacts/xml/DUMMYLEI123456789012.CON_FR_FC010000_FC_2024-12-31_20240625002201000/validation.jsonl
- `ixbrl` `test_ixbrl.xhtml` rc=0 time=0.45s -> artifacts/ixbrl/test_ixbrl/validation.jsonl
- `oim_json` `test_oim.json` rc=0 time=0.63s -> artifacts/oim_json/test_oim/validation.jsonl
- `oim_csv` `DUMMYLEI123456789012.CON_FR_COREP030500_COREPFRTB_2024-12-31_20240514021828000.zip` rc=0 time=0.42s -> artifacts/oim_csv/DUMMYLEI123456789012.CON_FR_COREP030500_COREPFRTB_2024-12-31_20240514021828000/validation.jsonl
- `oim_csv` `DUMMYLEI123456789012.CON_FR_DORA010000_DORA_2025-01-31_20250514020443000.zip` rc=0 time=0.38s -> artifacts/oim_csv/DUMMYLEI123456789012.CON_FR_DORA010000_DORA_2025-01-31_20250514020443000/validation.jsonl