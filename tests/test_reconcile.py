"""T2 tests: name reconciliation to Census 2011 district codes (SPEC §7, T2)."""
import json
import re

import geopandas as gpd
import pandas as pd
import pytest

from gwlib import DOCS, INTERIM, ROOT, load_yaml, settings

METHODS = {"exact", "alias", "fuzzy", "spatial", "override", "unmatched"}


@pytest.fixture(scope="module")
def named():
    p = INTERIM / "stations_named.csv"
    assert p.exists(), "data/interim/stations_named.csv missing: run `make reconcile`"
    return pd.read_csv(p, low_memory=False, dtype={"district_code": str, "state_code": str,
                                                   "district_raw": str, "state_raw": str})


@pytest.fixture(scope="module")
def codes():
    g = gpd.read_file(ROOT / "data/external/boundaries/2011_Dist.shp")
    g = g[g["censuscode"] > 0]
    return {f"{int(c):03d}": n for c, n in zip(g["censuscode"], g["DISTRICT"])}


def code_of(codes, name):
    hits = [c for c, n in codes.items() if n == name]
    assert len(hits) == 1, name
    return hits[0]


def test_at_least_99_pct_rows_matched(named):
    assert named["district_code"].notna().mean() >= 0.99


def test_codes_are_valid_2011_codes(named, codes):
    used = set(named["district_code"].dropna())
    assert used <= set(codes)
    assert len(used) <= 640


def test_methods_in_vocabulary(named):
    assert set(named["district_match_method"]) <= METHODS


def test_no_fuzzy_match_below_90(named):
    fz = named.loc[named["district_match_method"] == "fuzzy", "district_match_score"]
    assert (fz >= 0.90).all()


def test_unmatched_rows_have_no_code(named):
    um = named["district_match_method"] == "unmatched"
    assert named.loc[um, "district_code"].isna().all()
    assert named.loc[~um, "district_code"].notna().all()


def test_unmatched_report_exists():
    text = (DOCS / "UNMATCHED.md").read_text(encoding="utf-8")
    assert "## Unmatched" in text and "## Resolved by coordinates" in text


def test_spatial_only_for_marked_blank_or_spatial_state(named):
    """Coordinates are never a catch-all: only null-aliased names, blank names, or spatial_states."""
    aliases = load_yaml("district_aliases.yml")
    k = lambda s: re.sub(r"[^A-Z0-9]", "", str(s).upper())
    marked = {k(raw) for table in aliases.values() for raw, tgt in (table or {}).items() if tgt is None}
    sp = named[named["district_match_method"] == "spatial"]
    st_code = {raw: v["st_code"] for raw, v in load_yaml("state_map.yml").items()}
    sp = sp[~sp["state_raw"].map(st_code).isin(settings().get("spatial_states") or {})]
    names = sp["district_raw"].fillna("").map(k)
    assert names.map(lambda n: n == "" or n in marked).all(), sorted(set(sp["district_raw"][~names.isin(marked | {""})]))


@pytest.mark.parametrize("state_raw,district_raw,expected", [
    ("Uttar Pradesh", "Lakhimpur", "Kheri"),                  # not Assam's Lakhimpur
    ("Chhattisgarh", "Balrampur", "Surguja"),                 # not UP's Balrampur
    ("Telangana", "Sangareddy", "Medak"),                     # fuzzy said Rangareddy
    ("Assam", "Kamrup (M)", "Kamrup Metropolitan"),           # fuzzy said Kamrup
    ("U P", "Bula0sahar", "Bulandshahr"),                     # "nd" replaced by "0" upstream
    ("Tamilnadu", "Chen0i", "Chennai"),                       # "na" replaced by "0" upstream
    ("Haryana", "Gurugram", "Gurgaon"),                       # rename; coordinates alone scatter it
    ("Jharkhand", "E. Singhbhum", "Purbi Singhbhum"),         # coordinates put 52 wells in Odisha
    ("Tripura", "Cachar", "Cachar"),                          # state label wrong in source
])
def test_known_traps(named, codes, state_raw, district_raw, expected):
    rows = named[(named["state_raw"] == state_raw) & (named["district_raw"] == district_raw)]
    assert len(rows), f"no rows for {state_raw}/{district_raw}"
    assert (rows["district_code"] == code_of(codes, expected)).all()


def test_summary_matches_output(named):
    s = json.loads((INTERIM / "t2_summary.json").read_text())
    assert s["rows"] == len(named)
    assert s["unmatched_rows"] == int(named["district_code"].isna().sum())
