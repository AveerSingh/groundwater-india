"""T1 tests.

The header and row-count tests run against data/raw directly and guard
the column regexes. The rest check data/interim/stations_raw.csv,
which `make normalize` writes.
"""
import json

import pandas as pd
import pytest

from gwlib import (INTERIM, ColumnResolutionError, params, raw_path,
                   resolve_columns, settings)

YEARS = settings()["raw_files"]["years"]
ENC = settings()["raw_files"]["encoding"]


def header(year):
    return list(pd.read_csv(raw_path(year), encoding=ENC, nrows=0).columns)


@pytest.mark.parametrize("year", YEARS)
def test_every_configured_param_resolves(year):
    """SPEC T1: a missing column in a configured year is a hard failure."""
    resolved = resolve_columns(header(year), params(), year)
    for key, spec in params().items():
        if year in spec["years"]:
            assert resolved[key] is not None, f"{key} missing in {year}"


@pytest.mark.parametrize("year", YEARS)
def test_every_meta_column_resolves(year):
    resolved = resolve_columns(header(year), settings()["meta_columns"], year)
    for key, spec in settings()["meta_columns"].items():
        if year in spec["years"]:
            assert resolved[key] is not None, f"{key} missing in {year}"


@pytest.mark.parametrize("year", YEARS)
def test_ec_resolves_despite_unicode(year):
    """The bug that reached publication: EC uses μ (U+03BC) in 2019 and µ (U+00B5) in 2023."""
    col = resolve_columns(header(year), {"EC": params()["EC"]}, year)["EC"]
    assert col is not None and col.strip().upper().startswith("EC")


def test_fluoride_regex_does_not_match_iron():
    cols = ["F (mg/L)", "Fe (ppm)"]
    assert resolve_columns(cols, {"F": params()["F"]}, 2023)["F"] == "F (mg/L)"


def test_ambiguous_match_is_a_hard_failure():
    with pytest.raises(ColumnResolutionError):
        resolve_columns(["EC", "EC (µS/cm)"], {"EC": params()["EC"]}, 2024)


def test_missing_required_column_is_a_hard_failure():
    with pytest.raises(ColumnResolutionError):
        resolve_columns(["pH", "Cl"], {"EC": params()["EC"]}, 2024)


def test_newlines_in_headers_are_normalised():
    assert resolve_columns(["TDS\n(mg/L)"], {"TDS": params()["TDS"]}, 2024)["TDS"] == "TDS\n(mg/L)"


@pytest.mark.parametrize("year", YEARS)
def test_raw_row_counts(year):
    n = len(pd.read_csv(raw_path(year), encoding=ENC, low_memory=False))
    assert n == settings()["expected_rows"][year]


# ---- Tests on T1 output. A missing output is a failure, not a skip. ----

@pytest.fixture(scope="module")
def stations_raw():
    p = INTERIM / "stations_raw.csv"
    assert p.exists(), "data/interim/stations_raw.csv missing: run `make normalize`"
    return pd.read_csv(p, low_memory=False)


@pytest.fixture(scope="module")
def t1_summary():
    p = INTERIM / "t1_summary.json"
    assert p.exists(), "data/interim/t1_summary.json missing: run `make normalize`"
    return json.loads(p.read_text(encoding="utf-8"))


def test_raw_rows_and_seasons_match_spec(t1_summary):
    for y in YEARS:
        assert t1_summary["years"][str(y)]["raw_rows"] == settings()["expected_rows"][y]
    assert t1_summary["years"]["2024"]["raw_rows_by_season"] == settings()["expected_rows_2024_by_season"]


def test_no_major_ion_rows_match_spec(t1_summary):
    """SPEC §2.1's 1,513 / 1,061 / 13 'empty' rows: counted exactly, kept unless truly empty."""
    for y in YEARS:
        r = t1_summary["years"][str(y)]
        assert r["no_core_ion_rows"] == settings()["expected_no_major_ion_rows"][y], y
        assert r["no_core_ion_rows"] == r["dropped_no_measurements"] + r["kept_no_major_ions"], y
        assert r["kept_rows"] + r["dropped_no_measurements"] == r["raw_rows"], y


def test_every_row_has_a_measurement(stations_raw):
    assert (stations_raw["n_params_measured"] > 0).all()


def test_obs_id_unique(stations_raw):
    assert stations_raw["obs_id"].is_unique


@pytest.mark.parametrize("year", YEARS)
def test_every_configured_param_has_values(stations_raw, year):
    """Catches a column that resolves but silently yields nothing."""
    s = stations_raw[stations_raw["year"] == year]
    for key, spec in params().items():
        if year in spec["years"]:
            assert s[key].notna().sum() > 0, f"{key} all null in {year}"


def test_param_counts_match_spec_section_2_2(stations_raw):
    s = stations_raw[(stations_raw["season"] == "pre")
                     & ~stations_raw["qc_flags"].fillna("").str.contains("no_major_ions")]
    flags, cens = s["qc_flags"].fillna(""), s["censored"].fillna("")
    for p, by_year in settings()["expected_param_counts_pre"].items():
        for y, expected in by_year.items():
            m = s["year"] == y
            got = (s.loc[m, p].notna().sum()
                   + flags[m].str.contains(rf"(?:neg|extreme)_value:{p}(?:,|$)").sum()
                   + cens[m].str.contains(rf"(?:^|,){p}<").sum())
            assert got == expected, f"{p} {y}: {got} != {expected}"


def test_no_negative_or_extreme_values_survive(stations_raw):
    for key, spec in params().items():
        v = stations_raw[key].dropna()
        assert (v >= 0).all(), key
        if spec.get("plausibility_max") is not None:
            assert (v <= spec["plausibility_max"]).all(), key


def test_unconfigured_2022_uranium_not_loaded(stations_raw):
    assert stations_raw.loc[stations_raw["year"] == 2022, "U"].isna().all()


def test_invalid_coords_have_no_site_key(stations_raw):
    bad = ~stations_raw["coord_valid"]
    assert stations_raw.loc[bad, "site_key"].isna().all()
    assert stations_raw.loc[bad, "qc_flags"].str.contains("coord_invalid").all()


def test_ec_present_all_years(stations_raw):
    """SPEC T1: EC non-null for >=13,000 rows in 2019 and >=15,000 in 2023."""
    ec = stations_raw.groupby("year")["EC"].count()
    assert ec[2019] >= 13000
    assert ec[2023] >= 15000
    for y in YEARS:
        assert ec.get(y, 0) > 0, f"EC entirely missing in {y}"


def test_fluoride_present_all_years(stations_raw):
    f = stations_raw.groupby("year")["F"].count()
    for y in YEARS:
        assert f.get(y, 0) >= 6700, f"F only {f.get(y, 0)} rows in {y}"
