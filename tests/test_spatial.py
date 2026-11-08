"""T3 tests: the coordinate cross-check (SPEC §7, T3)."""
import json

import pandas as pd
import pytest

from gwlib import INTERIM, ROOT, read_stations, settings

MAX_STATE_MISMATCH_PCT = 20   # SPEC T3: any state above this must be investigated


@pytest.fixture(scope="module")
def sp():
    p = INTERIM / "stations_spatial.csv"
    assert p.exists(), "data/interim/stations_spatial.csv missing: run `make spatial`"
    return read_stations(p)


@pytest.fixture(scope="module")
def named():
    return read_stations(INTERIM / "stations_named.csv")


def flags(df):
    return df["qc_flags"].fillna("")


def test_name_match_preserved(sp, named):
    """district_code_name keeps the T2 name match unchanged."""
    assert len(sp) == len(named)
    assert sp["district_code_name"].fillna("").equals(named["district_code"].fillna(""))


def test_reassignment_only_under_the_decided_rule(sp):
    """SPEC §12.3 decision: coordinate district only if >= min_km outside and same state."""
    rule = settings()["coord_reassign"]
    moved = sp["district_code"].fillna("") != sp["district_code_name"].fillna("")
    assert (moved == sp["district_assign"].eq("coordinate")).all()
    m = sp[moved]
    assert len(m) > 0
    assert (m["district_code"] == m["coord_district_code"]).all()
    assert (m["coord_dist_to_claimed_km"] >= rule["min_km"]).all()


def test_reassigned_rows_stay_in_their_state(sp):
    import geopandas as gpd
    g = gpd.read_file(ROOT / "data/external/boundaries/2011_Dist.shp")
    st = {f"{int(c):03d}": f"{int(s):02d}" for c, s in zip(g["censuscode"], g["ST_CEN_CD"])}
    m = sp[sp["district_assign"].eq("coordinate")]
    assert (m["district_code"].map(st) == m["district_code_name"].map(st)).all()


def test_rows_without_valid_coordinate_keep_their_name_match(sp):
    bad = ~sp["coord_valid"]
    assert bad.any()
    assert sp.loc[bad, "district_code"].notna().mean() > 0.9


def test_agreement_null_exactly_when_a_side_is_missing(sp):
    both = sp["district_code"].notna() & sp["coord_district_code"].notna()
    assert sp.loc[both, "coord_in_claimed_district"].notna().all()
    assert sp.loc[~both, "coord_in_claimed_district"].isna().all()


def test_mismatch_flag_matches_agreement(sp):
    disagree = sp["coord_in_claimed_district"].eq(False) & sp["district_match_method"].ne("spatial")
    flagged = flags(sp).str.contains("coord_district_mismatch")
    assert (disagree == flagged).all()
    assert sp.loc[flagged, "coord_dist_to_claimed_km"].notna().all()


def test_no_state_above_mismatch_threshold(sp):
    # spatial_states (Delhi) are placed by coordinates; their only name-matched rows are
    # the ones whose coordinates fell outside the state, so they mismatch by definition.
    chk = sp[sp["coord_in_claimed_district"].notna() & sp["district_match_method"].ne("spatial")
             & ~sp["state_code"].isin(settings().get("spatial_states") or {})]
    pct = 100 * (~chk["coord_in_claimed_district"].astype(bool)).groupby(chk["state_code"]).mean()
    assert (pct <= MAX_STATE_MISMATCH_PCT).all(), pct[pct > MAX_STATE_MISMATCH_PCT].round(1).to_dict()


def test_repaired_coordinates_land_in_named_district(sp):
    rep = sp[flags(sp).str.contains("coord_repaired")]
    assert len(rep) > 0
    assert rep["coord_valid"].all()
    assert (rep["coord_district_code"] == rep["district_code"]).all()
    assert not flags(rep).str.contains("coord_invalid").any()


def test_dms_conversion_only_in_configured_groups(sp):
    conv = sp[flags(sp).str.contains("coord_converted:dms")]
    allowed = {(g["state_code"], y) for g in settings()["coord_dms_groups"] for y in g["years"]}
    assert len(conv) > 0
    assert set(zip(conv["state_code"], conv["year"])) <= allowed
    moved = (conv["lat"] != conv["lat_raw"]) | (conv["lon"] != conv["lon_raw"])
    whole = (conv["lat_raw"] % 1 == 0) & (conv["lon_raw"] % 1 == 0)      # DD.00 converts to itself
    assert (moved | whole).all()


def test_dms_conversion_improves_jharkhand(sp):
    """Regression for the T3 finding: 2019-22 Jharkhand coordinates are degrees.minutes."""
    d = sp[sp["state_code"].eq("20") & sp["year"].between(2019, 2022)
           & sp["coord_in_claimed_district"].notna() & sp["district_match_method"].ne("spatial")]
    assert d["coord_in_claimed_district"].astype(bool).mean() > 0.75


def test_summary_consistent(sp):
    s = json.loads((INTERIM / "t3_summary.json").read_text())
    assert s["mismatch"] == int(flags(sp).str.contains("coord_district_mismatch").sum())
