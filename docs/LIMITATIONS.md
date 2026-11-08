# Limitations

Living list. Every QC flag category must be explained here before T4 is done.

## Known at T0

- **The wells are monitoring wells.** They are shallow wells in CGWB's National Hydrograph Network, not household taps or the deep borewells many households draw from.
- **No multi-year station panel.** Well IDs are absent in 2023 and 2024; cross-year linkage goes through coordinates (SPEC §2.3).
- **Uneven parameter coverage.** Arsenic and iron were measured only in 2023–24, uranium only in 2021 (selected states, not a random sample), 2023 and 2024.

## Raw-data findings

1. **2022 uranium column (open).** The 2022 file has a `U_ppb_` column populated for every row (13,527 values, integers only, 7,455 zeros). SPEC §2.2 treats 2022 as having no uranium. It is excluded via `config/params.yml` until its provenance is checked against the CGWB 2022 report.
2. **Rows with no major ions (decided at T1: kept).** 1,513 rows in 2023 and 990 in 2024 report trace metals but no major ions; most are different wells from the major-ion rows. They are kept and flagged `no_major_ions`; see METHOD.md.
3. **Empty columns.** 2022 TDS and 2022 SiO₂ exist but contain no values; 2023 has no SiO₂ column.
4. **Below-detection results.** Recorded in `censored`, not as numbers. They count as tested and not exceeding (decided at T5). This makes published figures differ slightly from the manuscript's, most in 2020 nitrate (23.6% vs 25.1%).
5. **Small negative iron values (T5 decision).** 187 iron results in 2023 are between −0.04 and −0.01 mg/L, 176 of them from Jammu & Kashmir. These are near-zero instrument readings, effectively non-detections. They are nulled and flagged `neg_value:Fe`, and counted as below detection (tested, not exceeding) at T5; the same applies to the 11 other negative readings.
6. **Invalid coordinates.** 30 rows in 2019 and 30 in 2024 fall outside India's bounding box even in the `_coords_fixed` files, mostly lat/lon swaps or lost decimal points. T3 repaired 12 where a single fix lands in the named district (`coord_repaired`); 48 remain `coord_invalid` and keep their name match.
7. **Corrupted cells.** Five 2024 cells contain PDF-extraction debris (`hem0.003`, `ed in NRay Cls`, `0.07a1yls`, `23.73.`). They are nulled and flagged `unparsed`. Their rows may have other shifted values; T4 should look at them.
8. **Repaired typos.** Ten values were repaired (`7..85` → 7.85, `1 20.00` → 120.0, `1 5` → 15). The digit-gap repairs (`1 20.00`, `2 2.00`, `1 5`) are a judgement; all ten are flagged `value_repaired`.
9. **Upstream "na"/"nd" → "0" replacement.** District names such as `Bula0sahar` and `Chen0i` show that an earlier cleaning step replaced the letters "na"/"nd" with "0". If the same step ran on value columns, some `ND` (not detected) or `NA` cells may now read as 0. T4 should compare the `_coords_fixed` files against the originals (`all_india_long_{year}.csv`, also in the research folder) to see which files and columns were touched.
10. **Districts never sampled.** 40 of the 640 Census 2011 districts have no well in any year (after T3 assigns wells by location where the name is out of date). They are in Arunachal Pradesh (8), Manipur (8), Jammu & Kashmir (7, including Leh and Kargil), Sikkim (4), Himachal Pradesh (3), Mizoram, Nagaland and Puducherry (2 each), and one each in the Andaman & Nicobar Islands, Chhattisgarh, Lakshadweep and Delhi. They appear on the map as "no monitoring", not as gaps or as clean.
11. **2011 boundaries for a 2024 map.** Telangana appears under 2011 Andhra Pradesh codes, and post-2011 districts are folded into their 2011 parents. The site should show present-day state names (`state_now`) alongside 2011 district names.
12. **Jharkhand 2019–2022 coordinates were degrees.minutes.** This is in CGWB's source. 803 rows were converted (`coord_converted:dms`); converted values carry minute-level precision (about 1.8 km). See METHOD.md.
13. **Delhi placed by coordinates.** Delhi's 2012 redistricting reused old names for new shapes, so Delhi wells are assigned to 2011 districts by location. Delhi district figures are therefore "wells located in 2011 district X", not "wells CGWB labels X".
14. **Name vs. location disagree for 4% of wells.** Mostly outdated parent-district names (Erode for Tiruppur, Kathua for Samba). Wells 2 km or more outside their named district are aggregated by location when that location is in the same state (1,739 wells). The 239 cross-state cases keep their name. Near some borders the disagreement runs both ways, so part of it is coordinate noise.
15. **The boundary file has no districts beyond the Line of Control.** Its "Data Not Available" polygon (86,083 km², code 0) covers that area and does not overlap any district. 141 wells labelled Jammu, Rajouri or Poonch have coordinates inside it, which puts them close to or past the line as Datameet draws it. Their district comes from the name. The map keeps the polygon (code `000`) so the outline of India is complete; it carries no data and has no panel.

## QC flags

Every flag in `data/processed/stations.csv`, what it means for a reader, and how many rows carry it. Flags never delete a row (except `no_measurements`, which by definition has nothing to keep). Counts are from `data/interim/qc_report.md`, which breaks them down by year and state.

| Flag | Rows | What it means | How it is handled |
|---|---|---|---|
| `no_measurements` | 80 | nothing was reported for any parameter | row dropped in T1 and counted |
| `no_major_ions` | 2,507 | trace metals (or silica/phosphate) only; mostly a separate trace-metal sampling round | kept; contributes only to the parameters it measured; not counted as a major-ion monitored well in coverage |
| `neg_value:<p>` | 198 | negative concentration; 187 are near-zero iron in 2023 J&K/Punjab | value nulled; counted as below detection in aggregates |
| `extreme_value:<p>` | 3 | above the plausibility ceiling (fluoride 168 mg/L, etc.) | value nulled |
| `value_repaired:<p>` | 7 | typo in the number repaired (`7..85`) | value kept |
| `unparsed:<p>` | 2 | cell held PDF debris | value nulled; the rest of the row looked normal on inspection |
| `coord_invalid` | 48 | coordinate outside India's box and not repairable | district from the name; no point on the map |
| `coord_repaired:<how>` | 12 | lat/lon swap or lost decimal fixed, confirmed by the name | repaired coordinate used |
| `coord_converted:dms` | 803 | Jharkhand 2019–22 degrees.minutes converted | converted coordinate used (about 1.8 km precision) |
| `coord_district_mismatch` | 2,867 | point lies outside the district its name gives | aggregated by location if ≥ 2 km outside and in the same state; otherwise by name |
| `cbe_high` | 1,921 | ionic charge balance error > 10%: major ions don't add up | kept; bears on major-ion reliability, not on nitrate or fluoride; T5 records how many are in each aggregate |
| `co3_implausible` | 239 | carbonate > 10 mg/L at pH < 8.3, chemically implausible; 146 are the 2023 southern Andhra (Nellore/Chittoor) cluster behind the manuscript's IDW artefact | kept and flagged; carbonate is not a map layer; these rows' charge balance is also unreliable |
| `duplicate_obs` | 3,324 | another row shares the site (~110 m), year and season: complementary trace rows, nearby wells or resampling | all kept |
| `duplicate_copy` | 132 | second or later identical copy of a record (all values and location name) | kept in the table; aggregation counts the record once |

**Zeros are not artefacts.** Some regional labs report non-detects as 0 rather than "BDL". UP reports 42–62% zero nitrate in most years, and Uttarakhand, Assam and West Bengal are similar. T4 checked whether the upstream "na/nd" → "0" name corruption (2019 Tamil Nadu and UP only) also hit values: it did not. Zero and below-detection both mean "tested, not detected".

## Aggregates (T5)

- **Monitoring wells are not a population sample.** A district's percentage describes the wells CGWB sampled that round, not the water people drink (SPEC §10.1).
- **Sulphate's conditional limit.** Where magnesium exceeds 30 mg/L, sulphate above 200 mg/L counts as above permissible. Published sulphate figures are therefore higher than the manuscript's unconditional 400 mg/L figures.
- **High-CBE wells are included.** `n_cbe_high` reports how many are in each aggregate; they matter for major ions, not for nitrate or fluoride.

## Coverage (T6)

- **"Never tested" means in this dataset.** A district counts as never tested for a parameter when no well has a result for it in any year 2019–2024 in which CGWB reported that parameter. Arsenic, uranium and several metals were only reported in some years (see `config/params.yml`), so "never tested for arsenic" covers fewer rounds than "never tested for fluoride". It does not mean the water is free of it.
- **Two well counts.** `wells_2024` counts wells sampled in 2024 in either season, for any parameter; it drives the landing-page numbers (zero wells, fewer than 3). The map tier counts only 2024 pre-monsoon wells with major-ion results, because the map's layers are major-ion parameters. So 94 districts have fewer than 3 wells in 2024, but 143 are hatched as insufficient on the map.
- **Wells per million people uses 2011 population** and 2011 state boundaries (Telangana inside Andhra Pradesh, Ladakh inside Jammu & Kashmir). It describes network density, not exposure.
- **A "well" is a location, not a borehole ID.** CGWB rows carry no stable well ID across years, so a well is a site at about 110 m (3-decimal coordinates). Two different wells within 110 m in the same round are counted separately.

## Covariates (T7)

- **Three different years.** Household water sources are from 2011, extraction from 2024 (assessment year 2023–24), tap connections from the retrieval date. The page must show each vintage next to its number.
- **2011 household data is old.** JJM has changed rural drinking-water sources a great deal since 2011. `pct_hh_untreated_groundwater` describes 2011 dependence, not today's.
- **Tap connection ≠ safe water.** JJM counts connections; it does not certify the quality or reliability of what comes out of them, and the figures are self-reported by states.
- **DGWR comes through a republished layer.** The figures were taken from ESRI India's Living Atlas, not CGWB's PDFs, and checked against CGWB's national total and the Jharkhand report. The layer states no licence, so the repository carries only CGWB's figures from it and the derived area weights, not the layer itself.
- **Split districts are approximations.** For 114 districts, extraction figures were split by area from current districts that straddle 2011 boundaries (`dgwr_apportioned`); for 65, the same was done for JJM households (`jjm_apportioned`).
- **Hill districts have no stage of extraction.** CGWB does not assess most hill areas, so 24 districts have no DGWR figure at all. This is absence of assessment, not absence of extraction.
- **Covariates are context, not causes.** Placing extraction pressure or household dependence next to contamination counts invites inference; the page states the figures side by side and never combines them into an estimate of people affected (SPEC §10.3).

## Web payloads (T8)

- **Simplified boundaries.** District shapes are simplified to about 200 m for the web. One very small district (Mahe) loses about 8% of its drawn area, and a few rings touch themselves at a single point. Data are assigned before simplification, so no figure changes.
- **Persistence is a coarse measure.** "Above the limit in every year measured" means at least one tested well exceeded in each pre-monsoon year with 3 or more wells. Different wells are often sampled in different years (SPEC §2.3), so this says the problem keeps turning up in a district, not that the same well stays contaminated.
- **Pre- vs post-monsoon 2024** is shown only where both rounds have at least 10 wells, and the rounds need not sample the same wells.
- **The authorities layer is empty.** `config/authorities.yml` has no sourced entries yet, and unsourced entries are never published.

