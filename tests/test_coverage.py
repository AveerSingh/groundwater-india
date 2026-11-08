"""T6 tests: the monitoring-coverage layer (SPEC §7 T6)."""
import importlib.util
import json

import geopandas as gpd
import pandas as pd
import pytest

from gwlib import PROCESSED, ROOT, SITE_DATA, load_yaml, params, settings

T = settings()["reporting_thresholds"]
Y0 = settings()["primary_year"]


@pytest.fixture(scope="module")
def cov():
    p = PROCESSED / "coverage.csv"
    assert p.exists(), "data/processed/coverage.csv missing: run `make coverage`"
    return pd.read_csv(p, dtype={"district_code": str, "st_code": str}, keep_default_na=False)


@pytest.fixture(scope="module")
def nat():
    p = SITE_DATA / "national.json"
    assert p.exists(), "site/data/national.json missing: run `make coverage`"
    return json.loads(p.read_text())["coverage"]


def test_every_boundary_district_present_once(cov):
    g = gpd.read_file(ROOT / "data/external/boundaries/2011_Dist.shp", ignore_geometry=True)
    codes = {f"{c:03d}" for c in g["censuscode"] if c != 0}
    assert len(codes) == 640
    assert set(cov["district_code"]) == codes and cov["district_code"].is_unique


def test_no_data_districts_are_insufficient(cov):
    empty = cov[cov["n_years"] == 0]
    assert len(empty) > 0
    assert (empty["tier"] == "insufficient").all()
    assert (empty["params_ever_tested"] == "").all()
    assert (empty["n_params_never_tested"] == len(params())).all()


def test_tier_matches_primary_wells(cov):
    n = cov["wells_primary"]
    expect = n.map(lambda x: "reportable" if x >= T["reportable"] else
                   "count_only" if x >= T["count_only"] else "insufficient")
    assert (cov["tier"] == expect).all()


def test_ever_and_never_partition_params(cov):
    allp = set(params())
    for ever, never in zip(cov["params_ever_tested"], cov["params_never_tested"]):
        e, n = set(filter(None, ever.split(";"))), set(filter(None, never.split(";")))
        assert e | n == allp and not e & n


def test_years_sampled_consistent(cov):
    for _, r in cov.iterrows():
        yrs = [int(y) for y in r["years_sampled"].split(";") if y]
        assert yrs == [y for y in range(2019, 2025) if r[f"wells_{y}"] > 0]
        assert len(yrs) == r["n_years"]


def test_season_counts_match_aggregates(cov):
    """A district's wells in a round bound every parameter's n_wells in that round (same unit as T5).

    Not equal in general: metal-only wells and major-ion wells are often different wells."""
    d = pd.read_csv(PROCESSED / "district_param_year.csv", dtype={"district_code": str})
    for season in ("pre", "post"):
        m = d[(d["year"] == Y0) & (d["season"] == season)].groupby("district_code")["n_wells"].max()
        w = cov.set_index("district_code")[f"wells_{Y0}_{season}"]
        assert (m <= w.reindex(m.index)).all(), season


def test_primary_wells_within_year_wells(cov):
    assert (cov["wells_primary"] <= cov[f"wells_{Y0}_pre"]).all()
    assert (cov[f"wells_{Y0}_pre"] <= cov[f"wells_{Y0}"]).all()
    assert (cov[f"wells_{Y0}"] <= cov[f"wells_{Y0}_pre"] + cov[f"wells_{Y0}_post"]).all()


def test_wells_counted_once_across_seasons():
    m = importlib.util.spec_from_file_location("cov", ROOT / "scripts/06_coverage.py")
    mod = importlib.util.module_from_spec(m)
    m.loader.exec_module(mod)
    s = pd.DataFrame({"obs_id": ["1", "2", "3", "4"], "district_code": ["001"] * 4, "year": [Y0] * 4,
                      "season": ["pre", "pre", "post", "post"], "site_key": ["a", "a", "a", None],
                      "qc_flags": [None] * 4})
    s = mod.usable(s, settings())
    # two wells at site a in pre (not copies), one of them again in post, one well without a key
    assert s.groupby("district_code")["well"].nunique().iat[0] == 3


def test_national_numbers_reconcile(cov, nat):
    w = cov[f"wells_{Y0}"]
    assert nat["districts_total"] == 640
    assert nat["districts_zero_wells_primary_year"] == (w == 0).sum()
    assert nat["districts_lt3_wells_primary_year"] == (w < T["count_only"]).sum()
    assert nat["wells_primary_year"] == w.sum()
    assert sum(nat["districts_by_tier"].values()) == 640
    for p in ("F", "As", "U"):
        never = cov["params_never_tested"].str.split(";").map(lambda x: p in x)
        assert nat["districts_never_tested"][p] == never.sum()
        assert sorted(nat["districts_never_tested_codes"][p]) == sorted(cov.loc[never, "district_code"])
        assert nat["districts_never_tested"][p] >= nat["districts_never_sampled"]


def test_population_table():
    pop = load_yaml("population_2011.yml")
    assert len(pop["by_state"]) == 35
    assert sum(r["population"] for r in pop["by_state"].values()) == pop["india_total"] == 1210854977


def test_wells_per_million_by_state(cov, nat):
    rows = nat["wells_per_million_by_state"]
    assert len(rows) == 35
    assert sum(r[f"wells_{Y0}"] for r in rows) == nat["wells_primary_year"]
    for r in rows:
        assert r["wells_per_million"] == round(r[f"wells_{Y0}"] / r["population_2011"] * 1e6, 1)
