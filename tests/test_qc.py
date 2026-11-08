"""T4 tests: QC flags, charge balance, duplicates, and the published station table."""
import importlib.util
import json

import numpy as np
import pandas as pd
import pytest

from gwlib import DOCS, INTERIM, PROCESSED, ROOT, params, read_stations, settings

SPEC_5_1 = ["obs_id", "year", "season", "state_raw", "district_raw", "block_raw", "location_raw",
            "state_code", "district_code", "district_match_method", "district_match_score",
            "lat", "lon", "coord_valid", "coord_in_claimed_district", "site_key", "well_id_raw",
            "n_params_measured", "cbe_pct", "qc_flags"]


def load_qc_module():
    spec = importlib.util.spec_from_file_location("qc", ROOT / "scripts/04_qc.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def st():
    p = PROCESSED / "stations.csv"
    assert p.exists(), "data/processed/stations.csv missing: run `make qc`"
    return read_stations(p)


def flags(df):
    return df["qc_flags"].fillna("")


def base_flags(df):
    return {f.split(":")[0] for q in flags(df) for f in q.split(",") if f}


def test_row_count_matches_t1(st):
    t1 = json.loads((INTERIM / "t1_summary.json").read_text())
    assert len(st) == sum(r["kept_rows"] for r in t1["years"].values())


def test_spec_columns_present(st):
    missing = [c for c in SPEC_5_1 + list(params()) if c not in st.columns]
    assert not missing, missing


def test_district_codes_are_three_digit_text(st):
    c = st["district_code"].dropna()
    assert c.str.fullmatch(r"\d{3}").all()


def test_charge_balance_hand_example():
    qc = load_qc_module()
    row = pd.DataFrame([{"Ca": 40.08, "Mg": 24.30, "Na": 22.99, "K": 0.0,      # 2 + 2 + 1 = 5 meq cations
                         "HCO3": 61.02, "CO3": np.nan, "Cl": 35.45, "SO4": 48.03,  # 1 + 1 + 1 = 3 meq anions
                         "NO3": np.nan, "F": np.nan, "censored": None}])
    assert qc.charge_balance(row).iat[0] == pytest.approx(25.0, abs=0.01)     # (5-3)/(5+3)


def test_charge_balance_needs_complete_majors():
    qc = load_qc_module()
    row = pd.DataFrame([{"Ca": 40, "Mg": 24, "Na": 23, "K": np.nan, "HCO3": 61, "CO3": 0,
                         "Cl": 35, "SO4": 48, "NO3": 0, "F": 0, "censored": None}])
    assert pd.isna(qc.charge_balance(row).iat[0])
    row["censored"] = "K"                                                    # below detection counts as 0
    assert pd.notna(qc.charge_balance(row).iat[0])


def test_cbe_flag_matches_threshold(st):
    high = st["cbe_pct"].abs() > settings()["cbe_flag_pct"]
    assert (high == flags(st).str.contains("cbe_high")).all()


def test_co3_flag_matches_rule(st):
    rule = (st["CO3"] > 10) & (st["pH"] < 8.3)
    assert (rule == flags(st).str.contains("co3_implausible")).all()
    assert rule.sum() > 100                                                  # the 2023 southern Andhra cluster


def test_duplicate_flags(st):
    key = ["site_key", "year", "season"]
    size = st[st["site_key"].notna()].groupby(key)["obs_id"].transform("size")
    dup = pd.Series(False, index=st.index)
    dup.loc[size.index] = size > 1
    assert (dup == flags(st).str.contains("duplicate_obs")).all()
    copy = flags(st).str.contains("duplicate_copy")
    assert (copy <= dup).all()
    left = st[dup & ~copy].groupby(key).size()
    assert len(left) == st[dup].groupby(key).ngroups                        # every group keeps one counted row


def test_every_flag_is_explained_in_limitations(st):
    text = (DOCS / "LIMITATIONS.md").read_text(encoding="utf-8")
    present = base_flags(st) | {"no_measurements"}
    unexplained = sorted(f for f in present if f"`{f}" not in text)
    assert not unexplained, unexplained


def test_every_flag_is_in_data_dictionary(st):
    text = (DOCS / "DATA_DICTIONARY.md").read_text(encoding="utf-8")
    missing = sorted(f for f in base_flags(st) if f"`{f}" not in text)
    assert not missing, missing
