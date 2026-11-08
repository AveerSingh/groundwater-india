"""T5 gate: reproduce the manuscript's reference statistics (SPEC §2.7) to one decimal.

If this fails, the pipeline is wrong, not the reference. These use the manuscript's
method (05_aggregate.manuscript_pct), not the project's published rules.
"""
import json

import pytest

from gwlib import INTERIM

# key in t5_reference.json -> expected value or (lo, hi), percent, one decimal
REFERENCE = {
    "NO3_pre_range": (19.5, 25.1),   # NO3 > 45 mg/L, pre-monsoon, range across years
    "NO3_pre_mean6": 21.9,           # mean of 6 years
    "Cl_pre_range": (2.4, 3.1),      # Cl > 1,000 mg/L
    "SO4_pre_range": (3.4, 4.7),     # SO4 > 400 mg/L
    "EC_2024_pre": 23.5,             # EC > 1,500 µS/cm, 2024 pre
    "NO3_2024_post": 26.7,           # NO3 > 45 mg/L, 2024 post
    "F_pre_range": (5.6, 9.0),       # F > 1.5 mg/L
}


@pytest.fixture(scope="module")
def ref():
    p = INTERIM / "t5_reference.json"
    assert p.exists(), "data/interim/t5_reference.json missing: run `make aggregate`"
    return json.loads(p.read_text())


@pytest.mark.parametrize("name", REFERENCE)
def test_reference_statistic(ref, name):
    expected, got = REFERENCE[name], ref[name]
    if isinstance(expected, tuple):
        assert [round(got[0], 1), round(got[1], 1)] == list(expected), got
    else:
        assert round(got, 1) == expected, got
