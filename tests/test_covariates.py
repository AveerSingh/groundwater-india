"""T7 tests: covariate joins (SPEC §7 T7)."""
import importlib.util
import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from gwlib import INTERIM, PROCESSED, ROOT


def mod():
    spec = importlib.util.spec_from_file_location("cov7", ROOT / "scripts/07_covariates.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def cv():
    p = PROCESSED / "covariates.csv"
    assert p.exists(), "data/processed/covariates.csv missing: run `make covariates`"
    return pd.read_csv(p, dtype={"district_code": str})


@pytest.fixture(scope="module")
def summary():
    return json.loads((INTERIM / "t7_summary.json").read_text())


def test_one_row_per_district(cv):
    g = gpd.read_file(ROOT / "data/external/boundaries/2011_Dist.shp", ignore_geometry=True)
    codes = {f"{c:03d}" for c in g["censuscode"] if c != 0}
    assert set(cv["district_code"]) == codes and cv["district_code"].is_unique


# ---- national reference figures (SPEC §7 T7 and published totals) ----------------------

def test_hh6_national_figures(summary):
    n = summary["hh6"]["national_pct"]
    assert (n["untreated_groundwater"], n["handpump"], n["tubewell"], n["well"], n["tap"], n["tap_untreated"]) \
        == (53.0, 33.5, 8.5, 11.0, 43.5, 11.6)


def test_hh6_districts_sum_to_states():
    m = mod()
    d = m.read_hh6()
    st = d[d["district_code"] == "000"].set_index("st_code")[m.HH6_COLS]
    ds = d[d["district_code"] != "000"].groupby("st_code")[m.HH6_COLS].sum()
    assert (st - ds).abs().max().max() == 0
    assert len(st) == 35 and len(ds.index) == 35


def test_dgwr_national_stage(summary):
    assert abs(summary["dgwr"]["national_stage_pct"] - 60.47) < 0.05       # CGWB, DGWR 2024


@pytest.mark.parametrize("district,official", [("Bokaro", 45.62), ("Khunti", 26.92), ("Ramgarh", 60.12),
                                               ("Ranchi", 46.37), ("Pashchimi Singhbhum", 10.74)])
def test_dgwr_matches_jharkhand_report(cv, district, official):
    """Spot check against CGWB's Dynamic Ground Water Resource of Jharkhand, 2024 (district table).

    Dhanbad is left out: the source layer has 73.48, the report's chapter table 73.24.
    """
    g = gpd.read_file(ROOT / "data/external/boundaries/2011_Dist.shp", ignore_geometry=True)
    code = f"{int(g.loc[(g['ST_NM'] == 'Jharkhand') & (g['DISTRICT'] == district), 'censuscode'].iat[0]):03d}"
    assert cv.set_index("district_code").at[code, "gw_stage_extraction_pct"] == pytest.approx(official, abs=0.01)


def test_jjm_counts_reconcile(cv, summary):
    j = summary["jjm"]
    assert j["unplaced"] == 0
    assert j["direct"] + j["by_name"] + j["by_point"] + j["by_known_parent"] == j["source_districts"]
    jd, _ = mod().read_jjm()
    assert cv["jjm_rural_households"].sum() == pytest.approx(jd["Total"].sum(), rel=1e-4)


# ---- rules -----------------------------------------------------------------------------

def test_values_in_range(cv):
    for c in [c for c in cv if c.startswith("pct_")] + ["jjm_pct_rural_hh_tap"]:
        v = cv[c].dropna()
        assert ((v >= 0) & (v <= 100)).all(), c
    assert (cv["gw_stage_extraction_pct"].dropna() > 0).all()


def test_stage_consistent_with_volumes(cv):
    d = cv.dropna(subset=["gw_stage_extraction_pct"])
    calc = 100 * d["dgwr_extraction_ham"] / d["dgwr_extractable_ham"]
    assert (calc - d["gw_stage_extraction_pct"]).abs().max() < 0.05


def test_apportioned_districts_have_no_unit_counts(cv):
    ap = cv["dgwr_apportioned"].fillna(False).astype(bool)
    assert cv.loc[ap, "dgwr_units"].isna().all()


def test_urban_districts_have_no_jjm_value(cv):
    g = gpd.read_file(ROOT / "data/external/boundaries/2011_Dist.shp", ignore_geometry=True)
    delhi = {f"{c:03d}" for c in g.loc[g["ST_NM"] == "NCT of Delhi", "censuscode"]}
    assert cv.loc[cv["district_code"].isin(delhi), "jjm_pct_rural_hh_tap"].isna().all()


def test_overlay_weights_split_and_nesting():
    m = mod()
    b = gpd.GeoDataFrame({"district_code": ["001", "002"], "st_code": ["01", "01"]},
                         geometry=[box(77, 20, 78, 21), box(78, 20, 79, 21)], crs=4326)
    cur = gpd.GeoDataFrame({"cur_id": [0, 1, 2]},
                           geometry=[box(77.0, 20, 77.5, 21),     # wholly in 001
                                     box(77.5, 20, 78.5, 21),     # half and half
                                     box(77.6, 20, 78.04, 21)],   # ~91% in 001: nested
                           crs=4326)
    W = m.overlay_weights(cur, b).set_index(["cur_id", "district_code"])["w"]
    assert W[(0, "001")] == 1
    assert W[(1, "001")] == pytest.approx(0.5, abs=0.01) and W[(1, "002")] == pytest.approx(0.5, abs=0.01)
    assert W[(2, "001")] == 1 and (2, "002") not in W.index


def test_dgwr_zero_extractable_has_no_stage():
    m = mod()
    b = gpd.GeoDataFrame({"district_code": ["001"], "st_code": ["01"]}, geometry=[box(77, 20, 78, 21)], crs=4326)
    g = gpd.GeoDataFrame({"cur_id": [0], "totgwrec24": [0.0], "exgwres24": [0.0], "totgwex24": [0.0],
                          "totno24": [5.0], "safeno24": [0.0], "semcrino24": [0.0], "crino24": [0.0],
                          "ovrexpno24": [0.0], "salno24": [5.0]}, geometry=[box(77, 20, 78, 21)], crs=4326)
    out, _ = m.dgwr_covariates(g, b, m.overlay_weights(g, b))
    r = out.iloc[0]
    assert pd.isna(r["gw_stage_extraction_pct"]) and r["dgwr_units_saline"] == 5
    assert pd.notna(r["dgwr_note"]) and pd.notna(r["dgwr_vintage"])


def test_jjm_names_matched_within_state_only():
    m = mod()
    cur = pd.DataFrame({"cur_id": [0, 1], "district": ["Jhansi", "Bharatpur"], "st": ["09", "08"]})
    rows = pd.DataFrame({"code": ["901", "902"], "Name": ["Hansi", "Jhansi"], "StCode11": ["06", "09"]})
    assert m.match_names(rows, cur) == {"902": 0}
