"""The rule that no unverified limit is ever shown to readers."""
from gwlib import compares_to_limit, params, unverified_compared


def test_no_unverified_limit_is_compared():
    assert unverified_compared(params()) == []


def test_arsenic_and_uranium_are_values_only_until_verified():
    for k in ("As", "U"):
        p = params()[k]
        if p.get("verified") is not True:
            assert not compares_to_limit(p), f"{k} limit is unverified but would be compared"


def test_map_layers_compare_to_verified_limits():
    for k, p in params().items():
        if p.get("tier") == "A":
            assert compares_to_limit(p) and p["verified"] is True, k


def test_flag_logic():
    assert compares_to_limit({"acceptable": 10})
    assert not compares_to_limit({"acceptable": 10, "compare_to_limit": False})
    assert not compares_to_limit({"acceptable": None, "permissible": None})
    assert unverified_compared({"X": {"acceptable": 1, "verified": False}}) == ["X"]
    assert unverified_compared({"X": {"acceptable": 1, "verified": False, "compare_to_limit": False}}) == []
