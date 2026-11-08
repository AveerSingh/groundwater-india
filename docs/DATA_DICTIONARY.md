# Data dictionary

Published files live in `data/processed/` (CC BY 4.0). Schemas follow SPEC §5 and are finalised as each task lands.

## stations.csv — one row per station-season observation

| Column | Type | Notes |
|---|---|---|
| `obs_id` | str | `{year}-{season_code}-{row_index}`, stable |
| `year` | int | 2019–2024 |
| `season` | `pre` \| `post` | |
| `state_raw`, `district_raw`, `block_raw`, `location_raw` | str | verbatim from source |
| `state` | str | Census 2011 state name (clean spelling) |
| `state_now` | str | present-day state, for display (e.g. Telangana) |
| `state_code` | str | 2-digit Census 2011 state code of the matched district |
| `district_code` | str | aggregation district: 3-digit national Census 2011 code (`censuscode` in Datameet's 2011_Dist.shp, 001–640); null if unmatched. Not the shapefile's `DT_CEN_CD`, which is a within-state number. See `district_assign` |
| `district_code_name` | str | district from the name match alone (T2) |
| `district_assign` | enum | `name` \| `coordinate`: coordinate when the well is ≥ 2 km outside its named district and inside another district of the same state |
| `district_name_2011` | str | Census 2011 district name |
| `district_match_method` | enum | `exact` \| `alias` \| `fuzzy` \| `spatial` \| `override` \| `unmatched` |
| `district_match_score` | float | 0–1 for fuzzy, else 1.0 |
| `district_match_note` | str | why: alias table, `state_corrected`, "0" repair, fuzzy target, or reason unmatched |
| `lat`, `lon` | float | WGS84, after any T2/T3 correction |
| `lat_raw`, `lon_raw` | float | as in the source file |
| `coord_district_code` | str | district the coordinate falls in (point-in-polygon); null if none |
| `coord_dist_to_claimed_km` | float | for mismatches, distance from the point to the named district |
| `coord_valid` | bool | lat 6–38, lon 68–98 |
| `coord_in_claimed_district` | bool | point-in-polygon agrees with name match |
| `site_key` | str | coordinates rounded to 3 dp |
| `well_id_raw` | str | absent 2023–24 |
| one column per parameter | float | units in `config/params.yml`; null where not measured |
| `n_params_measured` | int | parameters with a reported result (number or below-detection) |
| `censored` | str | below-detection results, comma-separated: `NO3` (BDL/ND/nil/traces) or `PO4<0.1` (with stated limit); the parameter column is null |
| `cbe_pct` | float | ionic charge balance error, % |
| `qc_flags` | str | comma-separated; see below |

## QC flags

Parameter-specific flags carry the parameter after a colon, e.g. `neg_value:Fe`.

| Flag | Meaning |
|---|---|
| `neg_value:<p>` | a concentration was negative; set to null |
| `extreme_value:<p>` | above the parameter's plausibility ceiling; set to null |
| `value_repaired:<p>` | a typo in the raw number was repaired (e.g. `7..85`); value kept |
| `unparsed:<p>` | raw cell could not be read as a value; set to null |
| `no_major_ions` | row reports no major ion (mostly trace-metal-only rows); kept |
| `coord_converted:dms` | coordinate was degrees.minutes and was converted to decimal degrees |
| `coord_repaired:<how>` | invalid coordinate repaired (swap and/or decimal restored); confirmed by the name match |
| `coord_invalid` | outside India's bounding box |
| `coord_district_mismatch` | point-in-polygon district ≠ name-matched district |
| `cbe_high` | \|charge balance error\| > 10% |
| `co3_implausible` | carbonate > 10 mg/L at pH < 8.3 (chemically implausible); value kept |
| `no_measurements` | nothing reported for any parameter; row dropped in T1 (not present in the table) |
| `duplicate_obs` | same site_key, year, season appears more than once |
| `duplicate_copy` | second or later identical copy within a duplicate group; aggregation counts the record once |

## district_param_year.csv

One row per district × year × season × parameter, for every parameter in the years it was measured. Rules in METHOD.md, "Aggregation rules (T5)".

| Column | Type | Notes |
|---|---|---|
| `district_code`, `year`, `season`, `param` | key | `district_code` is the aggregation district (see `stations.csv`) |
| `n_wells` | int | wells tested for this parameter (value, below detection, or negative reading) |
| `n_below_detection` | int | of those, below detection or negative |
| `n_above_acceptable` | int | value > acceptable limit; null for parameters without a verified limit (As, U) and for EC |
| `n_above_permissible` | int | value > permissible limit ("no relaxation" = acceptable; sulphate conditional on Mg); null as above |
| `n_above_indicator` | int | EC only: value > 1,500 µS/cm, a project indicator, **not a BIS limit** |
| `pct_above_acceptable`, `pct_above_permissible`, `pct_above_indicator` | float | percent of `n_wells`, one decimal; **null when `n_wells` < 10** |
| `median`, `p90`, `max` | float | over tested wells; below detection as 0 |
| `coverage_tier` | enum | `reportable` (n ≥ 10) \| `count_only` (3–9) \| `insufficient` (< 3) |
| `n_cbe_high` | int | wells in the aggregate with charge balance error > 10% |

## coverage.csv — one row per Census 2011 district (640)

| Column | Type | Notes |
|---|---|---|
| `district_code` | str | 3-digit census code |
| `district`, `state_2011` | str | names from the 2011 boundary file |
| `st_code` | str | 2-digit 2011 state code |
| `wells_2019` … `wells_2024` | int | wells sampled that year, either season, any parameter (0 if none) |
| `wells_2024_pre`, `wells_2024_post` | int | wells sampled in each 2024 season |
| `wells_primary` | int | 2024 pre-monsoon wells with major-ion results; the tier is built on this |
| `years_sampled` | str | `;`-separated years with at least one well |
| `n_years` | int | number of years sampled (0–6) |
| `in_2024` | bool | any well in 2024 |
| `params_ever_tested` | str | `;`-separated parameters with a tested well in any configured year |
| `params_never_tested` | str | the rest of `config/params.yml` |
| `n_params_never_tested` | int | |
| `tier` | enum | `reportable` (≥10) \| `count_only` (3–9) \| `insufficient` (<3, including no data) |

## site/data/national.json — key `coverage`

Landing-page numbers written by T6: `districts_zero_wells_primary_year`, `districts_lt3_wells_primary_year` (includes zero), `districts_1_to_2_wells_primary_year`, `districts_never_sampled`, `districts_by_tier`, `districts_never_tested` (F, As, U) with the district codes, `wells_primary_year`, `wells_per_million_primary_year`, and `wells_per_million_by_state` (Census 2011 population). `definitions` gives each in words. T8 adds further keys to this file.

## covariates.csv — one row per Census 2011 district (640)

| Column | Type | Notes |
|---|---|---|
| `district_code` | str | 3-digit census code |
| `hh6_households` | int | households (excl. institutional), Census 2011 |
| `pct_hh_untreated_groundwater` | float | handpump + tubewell/borehole + covered + uncovered well, % of households |
| `pct_hh_handpump`, `pct_hh_tubewell`, `pct_hh_well` | float | components, % |
| `pct_hh_tap_treated`, `pct_hh_tap_untreated` | float | tap water from treated / untreated source, % |
| `hh6_vintage` | str | `Census of India 2011` |
| `dgwr_recharge_ham`, `dgwr_extractable_ham`, `dgwr_extraction_ham` | float | annual recharge, extractable resource, total extraction, hectare-metres, DGWR 2024 |
| `gw_stage_extraction_pct` | float | 100 × extraction ÷ extractable resource; null where not assessed or not defined |
| `dgwr_units`, `dgwr_units_safe`, `dgwr_units_semi_critical`, `dgwr_units_critical`, `dgwr_units_over_exploited`, `dgwr_units_saline` | int | assessment units by CGWB category; null when `dgwr_apportioned` |
| `dgwr_area_cover` | float | share of the 2011 district covered by source districts with 2024 figures |
| `dgwr_n_source_districts` | int | current districts contributing |
| `dgwr_apportioned` | bool | some contribution split by area |
| `dgwr_note` | str | why a stage is missing, where a reason is known |
| `dgwr_vintage` | str | DGWR 2024 (assessment year 2023-24) |
| `jjm_rural_households`, `jjm_rural_households_tap` | float | rural households, and those with a functional household tap connection |
| `jjm_pct_rural_hh_tap` | float | % of rural households with a tap connection; null for urban-only districts |
| `jjm_n_source_districts` | int | current districts contributing |
| `jjm_apportioned` | bool | some contribution split by area |
| `jjm_as_of` | str | retrieval date of the live dashboard figures |

## site/data/ (T8)

See METHOD.md "Web payloads (T8)" for the file list. `districts.json` carries `headline` with `n`, `tier`, `pct` and the count above only; everything below is in `d/{dt_code}.json`. Field notes:

- `headline.{param}`: `n` wells tested, `tier`, `median`, `max`; `above_acceptable`, `above_permissible` and `pct` (share above permissible, null below 10 wells). For EC, `above_indicator` and `pct` (share above 1,500 µS/cm).
- `persistence.{param}`: `years_measured`, `years_above`, `years`, `label`; rule text in `rules.persistence`.
- `season_2024.{param}`: `pre_pct`, `post_pct`, `delta` (post − pre, points), `pre_n`, `post_n`.
- `context`: `hh_total`, `pct_hh_untreated_groundwater`, `hh_source_year` (2011), `gw_extraction_stage_pct`, `gw_extraction_year`, `gw_units` (assessment units by category, null when apportioned), `gw_note`, `gw_apportioned`, `jjm_fhtc_pct`, `jjm_as_of`.
- `params.{param}` (d/ only): `columns` and `rows`; limit columns appear only for parameters compared against a limit.
- Station lists (s/): `columns` = lat, lon, year, season, location, NO3, F, EC, Cl, SO4, Fe, U, As, bdl. `bdl` is a `;`-list of parameters reported below detection; a null value means not tested.
