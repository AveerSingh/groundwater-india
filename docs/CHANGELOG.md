# Changelog

## 2026-11-07 — T0
- Repo skeleton, config, stub pipeline, CI.
- Raw CGWB CSVs (2019–2024, `_coords_fixed`) committed verbatim with SHA-256 checksums.
- Drinking-water limits checked against IS 10500:2012; arsenic and uranium still open (see METHOD.md).
- Arsenic and uranium set to values-only (`compare_to_limit: false`) until their limits are verified.

## 2026-11-07 — T1
- `01_normalize.py`: six files to one schema, 74,836 rows kept of 74,916 (80 rows with nothing reported dropped).
- Below-detection results recorded as `censored` instead of being coerced to numbers.
- Rows with trace metals but no major ions kept and flagged `no_major_ions` (spec said drop).
- SPEC §2.1 row counts and all 19 §2.2 parameter counts reproduced exactly.

## 2026-11-07 — T2
- Census 2011 district boundaries (Datameet, commit 5ea9037) added under `data/external/boundaries/`.
- `district_code` = national `censuscode`, not `DT_CEN_CD` (within-state number in this file).
- `02_reconcile_names.py` with `state_map.yml` (63 strings) and `district_aliases.yml` (~300 entries).
- 99.98% of rows matched; 16 rows unmatched, each with a reason, in `docs/UNMATCHED.md`.

## 2026-11-07 — T3
- `03_spatial_join.py`: coordinate cross-check, name-confirmed coordinate repair, distance to named district.
- Jharkhand 2019–22 coordinates found to be degrees.minutes; converted (803 rows).
- Delhi placed by coordinates (2012 redistricting reused old names).
- 3.96% of checkable rows fall outside their named district; no state above 20%.
- SPEC §12.3 decided: wells ≥ 2 km outside their named district are aggregated by their coordinate district when it is in the same state (1,739 wells). Name match kept in `district_code_name`.

## 2026-11-07 — T4
- `04_qc.py`: charge balance, implausible-carbonate rule, duplicate detection; writes the published `data/processed/stations.csv`.
- New flags `co3_implausible` (239 rows; the 2023 southern Andhra carbonate cluster) and `duplicate_copy` (132 identical copies).
- Checked that the upstream "0" name corruption did not touch measured values.

## 2026-11-07 — T5
- Reporting threshold frozen at 10 / 3 (SPEC §12.1).
- `05_aggregate.py` writes `data/processed/district_param_year.csv` (60,729 rows, 600 districts).
- Below-detection and negative readings count as tested, not exceeding; sulphate's permissible limit conditional on Mg; identical copies counted once.
- All seven §2.7 reference statistics reproduced by the manuscript's method; validation checks 1, 3, 4, 8 and 11 (aggregates) wired.

## 2026-11-07 — T6
- `06_coverage.py`: `coverage.csv` for all 640 districts (40 never sampled, tier `insufficient`) and the `coverage` block of `site/data/national.json`.
- `config/population_2011.yml`: Census 2011 state populations for wells per million.
- Never-sampled count corrected from 43 to 40 (the T2 figure, before T3's location-based assignment).
- Validation check 2 now confirms all 640 districts in `coverage.csv`; check 5 waits for T8's trend series.

## 2026-11-07 — T7
- `fetch_covariates.py` (`make fetch`): Census 2011 HH-6 (35 state files), DGWR 2024 district layer, JJM district tap connections, all in `data/external/` with checksums and `SOURCE.txt`; `make checksums` now covers them.
- `07_covariates.py`: `covariates.csv` for 640 districts. HH-6 640, DGWR stage 602, JJM 623 (the 17 without are urban-only).
- DGWR taken from ESRI India's Living Atlas layer instead of 36 state PDFs; checked against CGWB's national total and the Jharkhand report.
- Validation check 9 (every covariate dated) implemented.
- `xlrd==2.0.2` added to read the Census .xls files.

## 2026-11-07 — T8
- `08_export.py`: `districts.json`, `national.json` (limits, headline, trend, coverage), `d/`, `s/`, `dl/` for all 640 districts, and the simplified topology.
- `config/states.yml`: clean 2011 state names, present-day states (Telangana, Ladakh, merged Dadra-Daman), district display fixes.
- Geometry simplified with the Python `topojson` package instead of mapshaper (`topojson==1.10` added).
- Validation checks 2, 3, 4, 5, 7, 10 and 11 now cover the site payloads, and check 12 enforces the §3 budgets: all 12 pass, none pending.
- LIMITATIONS 15 corrected: the J&K "Data Not Available" polygon is the area beyond the Line of Control and overlaps no district.

## 2026-11-08 — M3 site
- First working site: landing claim and numbers, map with nitrate / fluoride / coverage layers and the below-threshold hatch, district panel, national trend chart with table, wells-in-view overlay, limitations on the page.
- Leaflet 1.9.4 and topojson-client 3.1.0 vendored (hashes in `site/vendor/SOURCE.txt`).
- Geometry re-tuned (0.003° on a 1e4 grid): 172 KB gzipped, more faithful than before. `districts.json` slimmed to first-paint fields (17 KB); the rest moved to `d/`.
- `08_export.py` writes the page's no-JS numbers and trend table into `index.html` and adds parameter labels.
- `tests/test_site.py`: static numbers match the data, no external resources, vendored hashes, JS parses, editorial wording. Validation checks 3 and 11 now read the per-district files too.
- Not yet: the method and downloads pages (M6), the authorities layer (M5), a throttled Slow 3G measurement.
- Public release: the ESRI DGWR layer is no longer committed; `data/external/dgwr/` holds CGWB's figures and the derived 2011 area weights (covariates.csv unchanged byte for byte). GitHub Pages deploys via Actions from a fresh pipeline run; generated `site/data/` is not committed.
- Live at https://aveersingh.github.io/groundwater-india/ (M3 gate met), deployed by `.github/workflows/pages.yml` from a fresh pipeline run behind the strict gate.
