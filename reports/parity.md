Altova Parity Checklist
=======================

Targets
-------
- Taxonomy resolution: packages and `zip#entry` syntax with full DTS build (lazyLoad disabled).
- Core checks: XBRL 2.1 syntax, dimensions, calculations, and consistency.
- Formula linkbases: execution and assertion reporting with severities.
- UTR and measures: unit validation with ISO currency codes.
- Duplicate facts, contexts, and units detection.
- Filing rules (EBA): alignment with taxonomy semantics; no runtime Excel execution.
- Performance: large instances, memory profile, multi-file batches.
- GUI UX: progress, errors, exports parity.

Status (initial)
----------------
- Engine: Arelle available via `arelle-release` (to be verified in this environment).
- Packages: tooling for fetching/caching EBA packages to be added.
- GUI: runs validations; fallback path and exports generation to be added.

Gaps
----
- Confirm UTR coverage with Arelle configuration and resources.
- Automate fetching of Eurofiling patterns where applicable.

Evidence Log
------------
- Will attach run logs, summary JSON, and CSV exports in subsequent iterations.

