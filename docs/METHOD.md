# Method

Working document. Sections are filled in as each pipeline task lands.

## Drinking-water limits

Checked on 2026-11-07 against the text of **IS 10500:2012 (Second Revision), May 2012**, plus **Amendment No. 2 (September 2018)**, read from the copy hosted by the Department of Consumer Affairs (consumerhelpline.gov.in) and the Public.Resource.Org copy of the base text.

| Param | Acceptable | Permissible (no alternate source) | Where in IS 10500:2012 | Status |
|---|---|---|---|---|
| NO₃ | 45 mg/L | no relaxation | Table 2, Sl No. xvi | verified |
| F | 1.0 mg/L | 1.5 mg/L | Table 2, Sl No. x | verified |
| Cl | 250 mg/L | 1,000 mg/L | Table 2, Sl No. viii | verified |
| SO₄ | 200 mg/L | 400 mg/L, only where Mg ≤ 30 mg/L | Table 2, Sl No. xx | verified, see note |
| Fe | 0.3 mg/L | no relaxation | Table 2, Sl No. xii | verified |
| TDS | 500 mg/L | 2,000 mg/L | Table 1, Sl No. vi | verified (context for the EC indicator) |
| As | 0.01 mg/L | 0.05 mg/L | Table 3, Sl No. x | **open**: matches the 2012 text; Amendment No. 1 not seen and may have removed the relaxation |
| U | 0.03 mg/L (as reported) | — | not in the 2012 text | **open**: added by a later amendment whose text has not been seen |
| EC | — | — | no EC limit in the standard | confirmed; 1,500 µS/cm is this project's indicator threshold |

Amendment No. 2 changes only the boron permissible limit (1.0 → 2.4 mg/L) and a test-method reference. It does not touch any parameter used here.

**Sulphate note.** The 400 mg/L permissible limit is conditional on magnesium ≤ 30 mg/L. The reference statistic in SPEC §2.7 uses an unconditional 400 mg/L cut. Decide before T5 whether the map applies the condition; the regression test should stay unconditional to match the manuscript.

**Arsenic and uranium are published as values only** (decision 2026-11-07). Until their limits are verified, `compare_to_limit: false` in `config/params.yml` means wells tested, median, 90th percentile and maximum are published. No output counts wells above a limit, computes a percentage above it, or describes a district in limit terms. Coverage measures ("never tested for arsenic") don't depend on the limit and are unaffected. `09_validate.py` allows an unverified limit only under this setting.

**To restore the limit comparison:** obtain Amendment No. 1 and the amendment that added uranium (BIS standards portal, or the Gazette notification). Then set `verified: true`, remove `compare_to_limit: false`, and record the amendment number and date here.

## Column resolution (T1)

Raw column names differ by year and include lookalike Unicode (`μ` U+03BC in 2019, `µ` U+00B5 in 2023–24) and embedded newlines (2024). Names are whitespace-normalised and matched with a start-anchored, case-insensitive regex from `config/params.yml`. A configured parameter with no matching column, or a regex matching more than one column, fails the run. `tests/test_normalize.py` checks this against the raw headers.

Some columns exist but are empty, or are populated in a year the spec doesn't trust. These are excluded by year in `config/params.yml` and listed in `data/interim/t1_report.md`: 2022 TDS (empty), 2022 SiO₂ (empty), 2022 U (populated, provenance unchecked).

## Value parsing (T1)

Every cell is classified rather than blindly stripped of non-digits:

| Raw | Stored as | Recorded in |
|---|---|---|
| a number | the number | — |
| a number with a typo (`7..85`, `8 .20`, `1 20.00`) | the repaired number | `qc_flags`: `value_repaired:<param>` |
| below detection (`BDL`, `ND`, `nil`, `Traces`) | null | `censored`: `<param>` |
| below a stated limit (`<0.1`) | null | `censored`: `<param><0.1` |
| missing (`-`, `NA`, `#N/A`, `#REF!`, `leaked`, `─`) | null | — |
| anything else (PDF-extraction debris) | null | `qc_flags`: `unparsed:<param>` |

Negative values are then nulled (`neg_value:<param>`), as are values above `plausibility_max` (`extreme_value:<param>`). Every token that was repaired or left unparsed is listed in `data/interim/t1_report.md`.

**Why censored values are kept separately.** The manuscript read `<0.20` as 0.20 and `BDL` as missing. That drops below-detection results from the denominator and slightly inflates exceedance shares; in 2020, 414 nitrate results are below detection. T1 preserves both readings, so T5 can reproduce the manuscript for the §2.7 regression and still count below-detection wells as tested and not exceeding in the published figures. Decide at T5.

**Reproduction check.** The per-parameter station counts in SPEC §2.2 (NO₃, F, U, As, Fe; pre-monsoon; 19 year-values) are reproduced exactly when a value counts as reported if it is numeric (including values later nulled as negative or extreme) or `<x`. `tests/test_normalize.py` asserts this.

## Dropped and kept rows (T1)

A row is dropped only when nothing was reported for any parameter: 9 rows in 2020, 71 in 2024. SPEC §2.1's 13 / 1,513 / 1,061 "empty" rows are rows with no major-ion value. Of these, 4 (2020), 1,513 (2023) and 990 (2024) still report trace metals, silica or phosphate. They are kept and flagged `no_major_ions`. In 2023 only 476 of the 1,513 share coordinates with a major-ion row, so they are mostly separate wells sampled for trace metals. They add arsenic, uranium and iron observations and don't affect any major-ion statistic, which is computed only over wells with a value for that parameter. Coverage counts in T6 must not count them as monitored wells for major ions.

## Reporting threshold (T5)

Decided and frozen 2026-11-07 (SPEC §12.1):

- **10 or more** wells tested for a parameter in a district-year-season: a percentage is shown.
- **3–9 wells:** "x of y wells" only, no percentage.
- **Fewer than 3:** "insufficient monitoring", hatched on the map, no value.

A suppressed percentage is stored as null, never as zero, so no downstream consumer can render it by accident. Counts are kept at every tier.

Why 10: at 10 wells one exceedance moves the share by 10 points, which is about as coarse as a percentage can be and still mean something. Below 3, even "x of y" mostly describes which wells happened to be sampled. The threshold will not be tuned to improve the map's appearance.

## Aggregation rules (T5)

Decided 2026-11-07; `aggregation` in `config/settings.yml`.

- **Tested.** A well counts as tested for a parameter if it has a value, a below-detection result (BDL, ND, nil, traces, "<x", or a reported 0), or a negative reading. Below-detection and negative readings count as tested and not exceeding. Negative readings are near-zero instrument values (187 iron results in 2023, plus 11 others). Values nulled as implausibly high are not counted as tested, because their true value is unknown.
- **Exceeds.** Strictly greater than the limit (a nitrate of exactly 45 does not exceed).
- **Limits** come from `config/params.yml`. "No relaxation" means permissible = acceptable. Sulphate's 400 mg/L permissible limit applies only where magnesium ≤ 30 mg/L, as IS 10500 states; where Mg > 30 it is 200, and where Mg is unknown it is 400. EC is compared with the project's 1,500 µS/cm indicator threshold, never as a BIS limit. Arsenic and uranium get no limit counts until their limits are verified.
- **Excluded rows:** `coord_invalid` (SPEC T5), `duplicate_copy` (identical repeats are counted once), and rows with no district code.
- **Median, p90, max** are over tested wells, with below-detection and negative readings as 0.
- `n_cbe_high` records how many wells in each aggregate failed charge balance; they are included.

**Effect of counting below-detection results.** National pre-monsoon nitrate exceedance is the same as the manuscript's to within 0.1 point in every year except 2020 (published 23.6% vs manuscript 25.1%), when labs reported 414 nitrate non-detects as "BDL" or "traces". Fluoride moves by at most 0.2 points.

**Regression.** The manuscript's method is kept as a separate function (`manuscript_pct` in `05_aggregate.py`): all rows, value > limit over rows with a number, "<x" read as x, below-detection excluded, unconditional limits. It reproduces all seven §2.7 statistics to one decimal; `tests/test_reference_stats.py` and validation check 1 enforce this.

## Name reconciliation (T2)

**Boundaries.** Census 2011 districts from Datameet (`2011_Dist.shp`), pinned to commit `5ea9037` (see `data/external/boundaries/SOURCE.txt`). The file has 641 polygons: 640 districts plus one 86,000 km² polygon in Jammu & Kashmir labelled "Data Not Available" (code 0), which is not a district and is excluded.

**District code.** `district_code` is the national 3-digit Census 2011 code, the shapefile's `censuscode` field (001–640). The spec names `DT_CEN_CD`, but in this file that field is the district's number *within its state* (72 distinct values across 640 districts), so joining on it would merge unrelated districts. The spec's own example (Barmer = 115) is a `censuscode` value.

**States.** `config/state_map.yml` maps all 63 raw state strings to a 2011 state code. Telangana rows map to 2011 Andhra Pradesh, keeping `state_now: Telangana` for display.

**Districts.** For each raw (state, district) pair, the first rule that hits wins:

1. **override:** `config/district_overrides.yml`, an explicit human decision (none so far).
2. **exact:** normalised name equals a 2011 district in the mapped state.
3. **alias:** `config/district_aliases.yml`, about 300 entries covering official renames (Gurugram→Gurgaon, Prayagraj→Allahabad, Belagavi→Belgaum), spellings (Ferozpur→Firozpur), and post-2011 districts with a single 2011 parent (Fazilka→Firozpur, Alipurduar→Jalpaiguri). Each entry is tagged in a comment.
4. **"0" repair:** an earlier cleaning step replaced "na"/"nd" with "0" inside some names (`Bula0sahar`, `Chen0i`, `0makkal`). Every na/nd combination is tried; a unique hit is accepted.
5. **state label wrong:** the name matches exactly one district in a different state (Cachar under Tripura, Daman under Gujarat, North Goa under Karnataka). All are listed in `UNMATCHED.md` for review.
6. **fuzzy:** rapidfuzz ratio ≥ 90 within the state, with a 5-point lead over the runner-up. All fuzzy matches are listed with scores and were reviewed; two wrong ones (Sangareddy→Rangareddy, Kamrup (M)→Kamrup) are now overridden by aliases.
7. **spatial:** point-in-polygon, used only for (a) post-2011 districts with several 2011 parents, which the alias table marks `null` (most of Telangana's 2016 districts and Andhra's 2022 districts, Botad, Morbi, Mahisagar, Amethi, Sambhal, Delhi's 2012 districts), and (b) rows with no district name. The point must fall inside the state the name belongs to.

**Deviation from SPEC T2 step 4.** The spec asks for LGD parentage tables to map post-2011 districts to 2011 parents. Instead, single-parent districts are mapped in the alias table, and multi-parent districts are placed well by well from coordinates. Multi-parent districts straddle 2011 boundaries, so a single parent would be wrong for part of their wells.

**Why coordinates are not a general fallback.** Used for every unresolved name, point-in-polygon put 52 of 82 "E. Singhbhum" wells into Mayurbhanj (Odisha) and scattered Gurugram wells across six districts in three states. Names are the primary key, as the spec says; coordinates are cross-checked in T3.

**Result.** 74,820 of 74,836 rows (99.98%) carry a district code: exact 59,509, alias 9,340, fuzzy 4,251, spatial 1,720, unmatched 16. 597 of 640 districts have at least one row in some year; the 43 that never do are listed in `UNMATCHED.md`.

## Spatial cross-check (T3)

Every valid coordinate is placed in a 2011 district polygon and compared with the name match. Rows placed by coordinates in T2 agree by construction and are left out of the rates. Full output: `data/interim/t3_report.md`.

**Result.** Of 72,348 independently checkable rows, 2,867 (3.96%) fall outside their named district. 889 of those are within 2 km of it, which is likely boundary generalisation in the shapefile. The remaining 1,978 (2.7%) are 2 km or more away. No state is above 20%. The highest are J&K 17.1%, Nagaland 15.4%, Arunachal 14.1%, Jharkhand 11.7% and Tamil Nadu 11.4%.

**Investigated: Jharkhand (33.4% before correction).** In 2019–2022 Jharkhand's coordinates have two decimals and are degrees.minutes written as decimal degrees (23°52′ stored as 23.52). Mismatch in those years was 50–70%, against 3–5% in 2023–24. Reading the values as DD.MM raised agreement from about 45% to about 73% in each of the four years. The same test applied to every other state-year lowered agreement, so the problem is confined to these four years. The values are the same in the pre-"coords_fixed" files, so the error is in CGWB's source. Fix: `settings.coord_dms_groups`; 803 rows converted, flagged `coord_converted:dms`, originals in `lat_raw`/`lon_raw`. 112 rows in those years are not valid as DD.MM (minutes ≥ 60) and are left as-is.

**Investigated: Delhi (40.5%).** Delhi's districts were redrawn in 2012 while keeping most old names, so source names describe post-2012 boundaries. "North" wells fall mostly in 2011 North West, and "Central" wells in 2011 North. The rate was the same every year (34–45%). Fix: `settings.spatial_states`; Delhi wells are placed by coordinates within Delhi (method `spatial`). The 20 Delhi wells whose coordinates fall just across the border (Ghaziabad, Sonipat, Gurgaon, Baghpat) or are missing fall back to the name match.

**What the remaining mismatches are.** The largest clusters are wells still labelled with a parent district after a split, or with a city's present extent:

| Named district | Coordinates fall in | Why |
|---|---|---|
| Erode, Coimbatore | Tiruppur | Tiruppur carved out in 2009 |
| Kathua, Jammu | Samba | Samba created 2006 |
| Ranchi | Khunti | Khunti created 2007 |
| Mumbai | Mumbai Suburban | city vs. suburban district |
| Kolkata | South 24 Parganas | city extent |
| Chennai | Kancheepuram | Chennai expanded in 2018 |
| Kamrup | Kamrup Metropolitan | metro district since 2003 |

In these cases the coordinate is probably right and the name is out of date; see the aggregation rule below.

**Coordinate repair.** A coordinate outside India's box is repaired only when exactly one candidate (lat/lon swap and/or a restored decimal point) lands inside the district its name matched. 12 repaired (flagged `coord_repaired:<how>`); 48 remain invalid and keep their name match.

**Points in no polygon.** 323 valid coordinates fall in no 2011 district. 141 are Jammu, Rajouri and Poonch wells inside the shapefile's J&K "Data Not Available" polygon, which covers the area beyond the Line of Control and does not overlap any district. The rest are mostly coastal points just offshore of the generalised coastline (median 0.1–2 km), plus a few far-off coordinates (Punjab up to 253 km).

## Aggregation district (SPEC §12.3, decided 2026-11-07)

`district_code_name` keeps the name match from T2. `district_code`, which every later stage aggregates on, is the coordinate district when both of these hold:

- the point is at least 2 km outside its named district (beyond boundary-generalisation noise), and
- the coordinate district is in the same state as the named one.

Otherwise it is the name match. `district_assign` records which applied (`name` or `coordinate`). Settings: `coord_reassign` in `config/settings.yml`.

Effect: 1,739 wells (2.4% of those checkable) are aggregated by location. The largest moves are Erode→Tiruppur (88), Ranchi→Khunti (47), Kathua→Samba (39), Coimbatore→Tiruppur (37) and Mumbai→Mumbai Suburban (35). 239 far mismatches whose coordinates are in another state keep their name, because those are more often bad coordinates than outdated names.

Caveat: some pairs move in both directions (Ranchi↔Khunti, Jammu↔Samba), so near those borders part of the disagreement is coordinate noise rather than outdated labels. Rule-based reassignment accepts that trade-off; the full list is in `data/interim/t3_report.md`.

## Charge balance and QC (T4)

**Charge balance.** CBE% = (Σcations − Σanions) / (Σcations + Σanions) × 100 in meq/L, with Ca, Mg, Na, K against HCO₃, CO₃, Cl, SO₄, NO₃, F. It is computed when Ca, Mg, Na, K, HCO₃, Cl and SO₄ each have a value or a below-detection result (counted as 0); CO₃, NO₃ and F count as 0 when missing. Of 71,985 computable rows, the median |CBE| is 1.4% and 2.7% exceed 10% (`cbe_high`). High-CBE rows are kept: charge balance speaks to the reliability of the major-ion set, not of a single nitrate or fluoride result.

**Implausible carbonate.** CO₃ above 10 mg/L at pH below 8.3 is flagged `co3_implausible` (239 rows), because carbonate is negligible below pH 8.3. 146 are in 2023 Andhra Pradesh, mainly Nellore and Chittoor at 600–1,000 mg/L and pH 7–8: the wells behind the manuscript's IDW artefact (SPEC §2.6). A chemistry rule catches them, and any others, without hard-coding a region.

**Duplicates.** 1,575 site/year/season groups (3,324 rows) share coordinates to ~110 m. 500 are a major-ion row plus its trace-metal row; 935 have different values (nearby wells or resampling); 140 are identical records. The 132 second-and-later identical copies (same values and location name) are flagged `duplicate_copy` so aggregation counts the record once.

**Zeros.** Some regional labs write non-detects as 0. Exact-zero shares by state and year show this is a stable lab convention (UP nitrate 42–62% zero in 2019 and 2021–23), not a 2019 artefact of the "na/nd" → "0" name corruption, which touched only district names in 2019 Tamil Nadu and UP.

## Monitoring coverage (T6)

`scripts/06_coverage.py` writes one row per Census 2011 district to `data/processed/coverage.csv`: all 640 from the boundary file, including the 40 with no data, which get tier `insufficient`. It also writes the landing-page numbers to the `coverage` key of `site/data/national.json`.

**Well.** A distinct site (`site_key`, coordinates to 3 decimals) within a district and year. Rows at one site in one round that are not identical copies count as separate wells, the same as in T5, so a district's wells in a round are never fewer than any parameter's `n_wells` for that round. Rows flagged `coord_invalid` or `duplicate_copy` are left out, as in T5.

**Tier.** From `wells_primary`: 2024 pre-monsoon wells with major-ion results (not flagged `no_major_ions`), using the frozen thresholds (≥10 reportable, 3–9 count only, <3 insufficient). Metal-only rows are left out because they are mostly different wells, and the map's main layers (nitrate, fluoride, EC, chloride) are major ions.

**Tested.** A parameter is tested in a district if any well has a value, a below-detection result or a negative reading for it, in a year configured for that parameter. This is the same test as T5's `n_wells`.

**Wells per million.** 2024 wells (either season) by 2011 state, divided by Census 2011 state population (`config/population_2011.yml`; the 35 values sum to the published India total of 1,210,854,977).

**2024 results.** 9,422 wells were sampled in 2024: 7.8 per million people nationally, from 0 (Sikkim, Dadra & Nagar Haveli, Lakshadweep) to 76 (Andaman & Nicobar). 56 districts have no well in 2024 and 94 have fewer than 3. On the map tier, 281 districts are reportable, 216 count only and 143 insufficient. 43 districts have never had a fluoride result, 116 never an arsenic result and 84 never a uranium result.

## Covariates (T7)

`scripts/fetch_covariates.py` (run by hand, `make fetch`) downloads the three sources into `data/external/` with checksums and a `SOURCE.txt` each. `scripts/07_covariates.py` joins them offline to the 640 Census 2011 districts in `data/processed/covariates.csv`. A district without a covariate gets nulls, never an error. Each group carries its own vintage column, and validation check 9 fails if a value lacks one. Match rates and every unmatched district are in `data/interim/t7_report.md`.

| Covariate | Districts with a value | Vintage |
|---|---|---|
| Households on untreated groundwater (`pct_hh_untreated_groundwater`) | 640 of 640 | Census 2011 |
| Stage of groundwater extraction (`gw_stage_extraction_pct`) | 602 of 640 | DGWR 2024 |
| Rural households with a tap connection (`jjm_pct_rural_hh_tap`) | 623 of 640 | JJM, retrieved 2026-11-07 |

**Census 2011 HH-6.** The state files' district rows (all households, all locations) join on the census district code, which is the same code as `district_code`. `pct_hh_untreated_groundwater` = handpump + tubewell/borehole + covered well + uncovered well. Nationally that is 53.0% (handpump 33.5, tubewell 8.5, wells 11.0); tap water is 43.5%, of which 11.6 points are untreated. All match SPEC T7, and district rows sum exactly to state rows.

**DGWR 2024 source.** CGWB publishes DGWR as one PDF per state. The same district figures are served as a single structured layer by ESRI India's Living Atlas ("District Wise Dynamic Ground Water Resources 2025", which holds 2022–2025). That layer is used instead of scraping 36 PDFs. It states no source, so it was checked three ways: national 2024 stage of extraction 60.48% (CGWB published 60.47%); 6,745 assessment units (published 6,746); and five Jharkhand districts match CGWB's Jharkhand 2024 report to two decimals. One, Dhanbad, has 73.48 in the layer and 73.24 in the report's chapter table.

**DGWR to 2011 districts.** The layer uses current districts (782). Each current district is overlaid on the 2011 boundaries.
- A current district at least 90% inside one 2011 district goes to it whole. The remainder is disagreement between the two boundary drawings.
- A district that straddles 2011 boundaries has its recharge, extractable resource and extraction split by area. This assumes they are spread evenly within it, which is an approximation. Overlaps under 2% are dropped as noise.
- Stage = 100 × extraction ÷ extractable resource, summed over the 2011 district. This is CGWB's own definition, so a stage is never averaged.

114 districts have a value built partly from split districts (`dgwr_apportioned`), mostly where states were reorganised after 2011 (Andhra Pradesh and Telangana, Rajasthan, Assam, the Kashmir valley). Assessment-unit counts by category (safe, semi-critical, critical, over-exploited, saline) are given only where nothing was split, because whole units cannot be divided by area.

CGWB categorises assessment units (blocks, mandals, taluks), not districts, so no district category is published here. Using stage thresholds alone would invent one.

38 districts have no stage:
- 24 have no assessed area in the layer: hill districts of Himachal, Uttarakhand, Arunachal and Manipur, which CGWB does not assess, and Lakshadweep.
- 12 have less than half their area covered by assessed districts.
- Kolkata and South 24 Parganas have zero extractable fresh groundwater (urban, and saline units). The source writes their stage as 0.00, which would read as "no pressure", so it is left null with a note.

**JJM.** The dashboard's district map request returns, for every current district, rural households and those with a tap connection. It is requested one state at a time, because reorganised states only answer to their new codes (36–39). Rows are placed as follows:
- 623 carry a 2011 census code and join directly.
- 131 post-2011 districts are matched by name, within the same state, to the DGWR layer's current boundaries, and split across 2011 districts with the same area weights.
- 1 (Hansi, carved from Hisar) has neither boundary nor coordinates and is placed by its known parent.

The 17 districts without a value are urban-only: all Delhi districts, Chandigarh, Kolkata, Mumbai, Mumbai Suburban, Hyderabad, Chennai, and Yanam and Mahe. National rural tap coverage on 2026-11-07 is 82.6%. These are live, self-reported programme figures (`jjm_as_of`); "tap connection" is JJM's own definition and says nothing about water quality.

## Web payloads (T8)

`scripts/08_export.py` writes everything the site reads into `site/data/`. The browser computes nothing; every number is final.

| File | Contents |
|---|---|
| `districts.json` | 640 entries with only what the first paint needs: names (2011 and present-day state), well counts and tier, and the 2024 pre-monsoon headline (n, tier, share, count above) for nitrate, fluoride, EC and chloride; plus the `limits` and `labels` blocks |
| `d/{dt_code}.json` | the full entry: coverage and parameter lists, persistence, 2024 pre vs post, context covariates, rules text, and every parameter's year × season table; lazy-loaded |
| `s/{dt_code}.json` | the district's located stations (compact columns: Tier A and B values, below-detection markers), lazy-loaded |
| `dl/{dt_code}.csv`, `dl/all_districts.csv` | aggregate tables with names |
| `dl/coverage.csv`, `dl/covariates.csv`, `dl/stations.csv.gz` | published tables; the station download is byte-identical to `stations.csv` |
| `national.json` | `limits`, `headline` (landing numbers), `trend` (nitrate, fluoride, EC, chloride; never uranium), `coverage` (T6) |
| `geo/districts.topo.json` | simplified district topology; `dt_code` is the only property |

**Limits come from config.** The `limits` blocks are written from `config/params.yml`. Arsenic and uranium carry `values_only: true` and no limit numbers. Validation check 10 fails if a limit in the JSON differs from params.yml, or if the site's HTML or JS hard-codes a number with a concentration unit that is not a configured limit.

**Headline.** Taken directly from the 2024 pre-monsoon district aggregates (T5), so the map and the downloads agree. EC reports wells above the 1,500 µS/cm indicator, never "above the limit".

**Persistence.** Shown where a district has at least 4 pre-monsoon years with 3 or more wells tested. A year counts as above when at least one well exceeded. The label reads "every year measured", "x of y years" or "no year measured".

**National trend.** Share of tested pre-monsoon wells above the limit, nationally, by year, under the published rules (below-detection counts as tested). Nitrate: 20.6, 23.6, 19.5, 22.4, 19.7, 24.0% (2019–2024).

**Landing numbers (2024).**
- 110 of the 281 reportable districts have more than a quarter of monitored wells above the nitrate limit.
- 94 of 640 districts have fewer than 3 monitored wells.
- 116 have no arsenic result in 2023–2024, the only years CGWB reported arsenic.

**Geometry.** Simplified with the Python `topojson` package rather than mapshaper, to keep the pipeline Python-only. It builds shared arcs like mapshaper, so neighbours never gap or overlap. The settings are Douglas-Peucker at 0.003° with `prevent_oversimplify` so no polygon disappears, on a 1e4 coordinate grid (both about 330 m). Coarser rounding turned out smaller and more faithful than finer rounding with lighter simplification. Median district area is unchanged; 99.8% of districts are within 2.5%; the worst keeps 96%. The property is named `dt_code`, not `DT_CEN_CD`, because in this boundary file `DT_CEN_CD` is a within-state number (see T2).

**Budgets (gzipped, validation check 12).**

| Asset | Size | Budget |
|---|---|---|
| Geometry | 172 KB | 600 KB |
| `districts.json` | 17 KB | 250 KB |
| Largest district detail | 3 KB | 15 KB |
| Largest station list | 11 KB | 40 KB |

## The site (M3)

`site/` is static: one page (`index.html`), vanilla JS in `site/js/`, Leaflet 1.9.4 and topojson-client 3.1.0 vendored in `site/vendor/` with recorded hashes. There are no CDN, tile or font requests. Run it with `make serve` and open http://localhost:8000.

**Above the fold:** the claim, the three landing numbers and the map (nitrate, 2024 pre-monsoon). The numbers and the trend table are written into the HTML by `08_export.py`, so the page says something true with JavaScript off.

**Layers:**
- **Nitrate and fluoride** show the share of tested wells above the permissible limit in five bins, starting with "no monitored well above the limit". The bin is wording, not a verdict.
- **Coverage** shows major-ion wells per district: 10-14, 15-19, 20-29, 30-44 and 45 or more, cut at roughly the quintiles of the 281 reportable districts.
- **Below the reporting threshold**, districts are never coloured. 3-9 wells get a 45° hatch (counts in the panel) and fewer than 3 a 135° hatch, so "no data" can never read as "low".

**Colour:** one blue ramp, checked with the dataviz palette validator as an ordinal ramp in light and dark mode. Dark mode uses its own steps, not an inversion. The trend chart uses the first four categorical colours; light mode passes with the required relief (direct labels and a table view).

**Panel (SPEC §8.3 order):**
1. The well count and years sampled.
2. The 2024 table, pre or post monsoon, always "x of y" (EC against the indicator; arsenic and uranium as values only).
3. Persistence.
4. Pre vs post monsoon.
5. Context with dates.
6. Authorities (empty until sourced).
7. Downloads.
8. Parameters never tested.

The panel's full data loads on click. Every limit, unit and label is read from the pipeline's JSON.

**Wells in view:** off by default. At zoom 7 or closer it loads station lists for the districts in view (at most 40) and draws the 2024 pre-monsoon wells, filled where above the active layer's limit.

**Accessibility:**
- Every district is a focusable button, labelled with its sentence. Tab to it and press Enter to open the panel.
- "Find a district" lists all 640, grouped by present-day state.
- The trend chart has arrow-key stepping and a table.
- Colour never carries meaning alone: the hatch, the legend counts and the panel text carry it too.
- A link such as `#d115` opens a district.

**Load time.** The initial load is 253 KB gzipped: 172 KB geometry, 17 KB districts, 41 KB Leaflet, about 23 KB for everything else. On Chrome's strictest Slow 3G profile (400 kb/s, 2 s round trip) that comes to about 9.4 s to the painted map, and about 2 s on the current "3G" profile. This is an estimate from those sizes; a throttled measurement in Chrome DevTools is still to be done. The headline text arrives with the HTML, after the first round trip.

