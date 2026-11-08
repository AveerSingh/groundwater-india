"""T5 tests: district x year x season x parameter aggregates (SPEC §5.2, §7 T5)."""
import importlib.util

import numpy as np
import pandas as pd
import pytest

from gwlib import PROCESSED, ROOT, compares_to_limit, params, settings

T = settings()["reporting_thresholds"]


def agg_module():
    spec = importlib.util.spec_from_file_location("agg", ROOT / "scripts/05_aggregate.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def dpy():
    p = PROCESSED / "district_param_year.csv"
    assert p.exists(), "data/processed/district_param_year.csv missing: run `make aggregate`"
    return pd.read_csv(p, dtype={"district_code": str})


# ---- rules on a hand-built example --------------------------------------------------

def frame(rows):
    base = {"district_code": "001", "year": 2024, "season": "pre", "censored": None, "qc_flags": None, "Mg": 10.0}
    df = pd.DataFrame([{**base, **r} for r in rows])
    for p in params():
        if p not in df:
            df[p] = np.nan
    return df


def run(df):
    return agg_module().aggregate(df, params(), settings())


def test_hand_example_nitrate():
    # 12 wells: 3 above 45, 2 below detection, 1 negative, 1 extreme (not tested), 5 ordinary
    rows = ([{"NO3": v} for v in (50, 60, 100)] + [{"censored": "NO3"}, {"censored": "NO3<0.2"}]
            + [{"qc_flags": "neg_value:NO3"}] + [{"qc_flags": "extreme_value:NO3"}]
            + [{"NO3": v} for v in (1, 2, 3, 4, 45)])
    r = run(frame(rows)).query("param == 'NO3'").iloc[0]
    assert r.n_wells == 11                      # extreme value is not a test result
    assert r.n_below_detection == 3             # BDL, "<0.2", negative
    assert r.n_above_acceptable == 3            # 45 itself does not exceed
    assert r.n_above_permissible == 3           # no relaxation: permissible = acceptable
    assert r.pct_above_permissible == pytest.approx(27.3)
    assert r.coverage_tier == "reportable"


def test_count_only_and_insufficient_have_null_percentages():
    df = pd.concat([frame([{"NO3": 50}] * 5), frame([{"NO3": 50, "district_code": "002"}] * 2)])
    out = run(df).query("param == 'NO3'").set_index("district_code")
    assert out.loc["001", "coverage_tier"] == "count_only" and pd.isna(out.loc["001", "pct_above_permissible"])
    assert out.loc["002", "coverage_tier"] == "insufficient" and pd.isna(out.loc["002", "pct_above_permissible"])
    assert out.loc["001", "n_above_permissible"] == 5        # counts are kept


def test_sulphate_magnesium_condition():
    rows = [{"SO4": 300, "Mg": 10}, {"SO4": 300, "Mg": 50}, {"SO4": 300}]    # Mg unknown in the third
    df = frame(rows)
    df.loc[2, "Mg"] = np.nan
    r = run(df).query("param == 'SO4'").iloc[0]
    assert r.n_above_acceptable == 3
    assert r.n_above_permissible == 1                        # only the high-Mg well


def test_excluded_flags_and_missing_district():
    rows = [{"NO3": 50}, {"NO3": 50, "qc_flags": "coord_invalid"},
            {"NO3": 50, "qc_flags": "duplicate_obs,duplicate_copy"}, {"NO3": 50, "district_code": None}]
    r = run(frame(rows)).query("param == 'NO3'").iloc[0]
    assert r.n_wells == 1


def test_values_only_params_have_no_limit_counts():
    r = run(frame([{"As": 500.0, "year": 2024}] * 12)).query("param == 'As'").iloc[0]
    assert pd.isna(r.n_above_acceptable) and pd.isna(r.pct_above_permissible)
    assert r["max"] == 500


def test_ec_uses_indicator_not_limit():
    r = run(frame([{"EC": 2000.0}] * 10)).query("param == 'EC'").iloc[0]
    assert pd.isna(r.n_above_acceptable) and pd.isna(r.n_above_permissible)
    assert r.n_above_indicator == 10 and r.pct_above_indicator == 100.0


# ---- properties of the real output --------------------------------------------------

def test_no_percentage_below_reportable(dpy):
    small = dpy["n_wells"] < T["reportable"]
    pct = [c for c in dpy if c.startswith("pct_")]
    assert dpy.loc[small, pct].isna().all().all()


def test_tier_matches_n(dpy):
    expect = np.where(dpy["n_wells"] >= T["reportable"], "reportable",
                      np.where(dpy["n_wells"] >= T["count_only"], "count_only", "insufficient"))
    assert (dpy["coverage_tier"] == expect).all()


def test_no_null_district_code(dpy):
    assert dpy["district_code"].notna().all() and dpy["district_code"].str.fullmatch(r"\d{3}").all()


def test_no_parameter_outside_its_years(dpy):
    for p, spec in params().items():
        assert set(dpy.loc[dpy["param"] == p, "year"]) <= set(spec["years"]), p


def test_no_limit_counts_for_values_only_params(dpy):
    for p, spec in params().items():
        if not compares_to_limit(spec):
            d = dpy[dpy["param"] == p]
            assert d[["n_above_acceptable", "n_above_permissible", "pct_above_acceptable",
                      "pct_above_permissible"]].isna().all().all(), p


def test_counts_bounded(dpy):
    for c in ("n_above_acceptable", "n_above_permissible", "n_above_indicator", "n_below_detection"):
        v = dpy[c].dropna()
        assert (v <= dpy.loc[v.index, "n_wells"]).all(), c
