# XBRL Validation Tool Development Roadmap

## Priority Items (1-3)

### 1) EBA Rules Engine Completeness
- Extend the DSL (Domain Specific Language)
- Add cross-table operations
- Finalize severity mapping
- Ship a verified coverage report per framework
- Wire into exports with clear codes

### 2) Deterministic Mapping Hardening
- Improve axis/member matching and fallbacks
- Attach mapped cell consistently to messages for precise drill-down

### 3) UX Upgrade
- Interactive error grid with table/fact linking
- Add filters and search functionality
- Integrate taxonomy browser
- Enhance current GUI or FastAPI UI

## Additional Roadmap Items (4-7)

### 4) Packaging
- Build macOS app bundle + Windows installer
- Embed Arelle runtime
- Cache bootstrap and taxonomy stacks
- Code-sign applications

### 5) Scale Tests
- Run full-size OIM CSV/JSON instances
- Test large XML instances
- Profile and tune caching, parallelism, and memory usage

### 6) Taxonomy Management
- Robust package discovery
- Version selector functionality
- Offline pre-extraction capabilities
- Remove heuristics where possible

### 7) CI Baselines
- Lock sample suites
- Produce diffable JSONL and reports
- Enforce severity thresholds

## Next Steps Question

**Would you like me to prioritize items 1–3 and start by:**
- Expanding the filing-rules evaluator
- Adding an interactive messages view with DPM table/cell drill-down in the existing GUI?
