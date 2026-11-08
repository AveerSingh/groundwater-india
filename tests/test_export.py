"""T8 tests: web payloads, and that the T9 gate catches planted violations."""
import gzip
import importlib.util
import json
import shutil

import pytest

from gwlib import PROCESSED, ROOT, SITE_DATA, params, settings

T = settings()["reporting_thresholds"]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def dj():
    p = SITE_DATA / "districts.json"
    assert p.exists(), "site/data/districts.json missing: run `make export`"
    return json.loads(p.read_text())


@pytest.fixture(scope="module")
def nat():
    return json.loads((SITE_DATA / "national.json").read_text())


# ---- payload properties ----------------------------------------------------------------

def test_districts_json_shape(dj):
    assert len(dj["districts"]) == 640
    e = dj["districts"][0]
    for k in ("dt_code", "district", "state", "state_now", "coverage", "headline"):
        assert k in e
    for k in ("params", "context", "persistence", "season_2024"):
        assert k not in e                                      # lazy-loaded with d/{dt_code}.json
    d = json.loads((SITE_DATA / "d" / f"{e['dt_code']}.json").read_text())
    for k in ("params", "context", "persistence", "season_2024", "rules"):
        assert k in d


def test_headline_matches_aggregates(dj):
    import pandas as pd
    d = pd.read_csv(PROCESSED / "district_param_year.csv", dtype={"district_code": str})
    d = d[(d["year"] == 2024) & (d["season"] == "pre")].set_index(["district_code", "param"])
    for e in dj["districts"]:
        for p, h in e["headline"].items():
            r = d.loc[(e["dt_code"], p)]
            assert h["n"] == r["n_wells"]
            col = "pct_above_indicator" if p == "EC" else "pct_above_permissible"
            assert (h["pct"] is None) == pd.isna(r[col])


def test_state_now(dj):
    by = {e["dt_code"]: e for e in dj["districts"]}
    assert by["536"]["state_now"] == "Telangana" and by["536"]["state"] == "Andhra Pradesh"
    assert by["003"]["state_now"] == "Ladakh"
    assert by["545"]["state_now"] == "Andhra Pradesh"
    assert all(e["state"] and e["state_now"] for e in dj["districts"])


def test_persistence_needs_four_years(dj):
    for e in dj["districts"]:
        d = json.loads((SITE_DATA / "d" / f"{e['dt_code']}.json").read_text())
        for p, x in d["persistence"].items():
            assert x["years_measured"] >= 4 and 0 <= x["years_above"] <= x["years_measured"]
            assert len(x["years"]) == x["years_measured"]


def test_trend_excludes_uranium_and_matches_t5_2020(nat):
    t = nat["trend"]["params"]
    assert set(t) == {"NO3", "F", "EC", "Cl"}
    no3 = {r["year"]: r["pct"] for r in t["NO3"]["series"]}
    assert no3[2020] == 23.6                                    # published rules (T5 finding)


def test_values_only_params_have_no_limits(dj, nat):
    for blk in (dj["limits"], nat["limits"]):
        for p in ("As", "U"):
            assert blk[p].get("values_only") and "acceptable" not in blk[p] and "permissible" not in blk[p]


def test_station_download_roundtrip():
    with gzip.open(SITE_DATA / "dl" / "stations.csv.gz", "rb") as fh:
        assert fh.read() == (PROCESSED / "stations.csv").read_bytes()


def test_geometry_one_property_and_na_area(dj):
    topo = json.loads((SITE_DATA / "geo" / "districts.topo.json").read_text())
    geoms = [g for o in topo["objects"].values() for g in o["geometries"]]
    assert all(set(g["properties"]) == {"dt_code"} for g in geoms)
    codes = {g["properties"]["dt_code"] for g in geoms}
    assert codes == {e["dt_code"] for e in dj["districts"]} | {"000"}


def test_station_lists_hold_located_counted_rows():
    s = json.loads((SITE_DATA / "s" / "403.json").read_text())
    i = {c: k for k, c in enumerate(s["columns"])}
    assert all(r[i["lat"]] is not None and r[i["lon"]] is not None for r in s["rows"])


# ---- the gate catches violations -------------------------------------------------------

@pytest.fixture()
def gate(tmp_path, monkeypatch):
    """09_validate pointed at a copy of site/ that a test may corrupt."""
    site = tmp_path / "site"
    shutil.copytree(SITE_DATA.parent, site, ignore=shutil.ignore_patterns("s", "dl"))
    v = load("val", "09_validate.py")
    monkeypatch.setattr(v, "SITE_DATA", site / "data")
    return v, site


def test_gate_passes_on_real_output(gate):
    v, _ = gate
    for fn in (v.check_limit_strings, v.check_values_only, v.check_uranium_trend):
        assert fn()[0] is True, fn.__name__


def test_gate_catches_stray_limit_in_html(gate):
    v, site = gate
    (site / "index.html").write_text("<p>Nitrate above 50 mg/L</p>")
    ok, msg = v.check_limit_strings()
    assert ok is False and "50 mg/L" in msg


def test_gate_accepts_configured_limit_in_html(gate):
    v, site = gate
    (site / "index.html").write_text("<p>Nitrate above 45 mg/L; fluoride above 1.5 mg/L</p>")
    assert v.check_limit_strings()[0] is True


def test_gate_catches_changed_limit_in_json(gate):
    v, site = gate
    p = site / "data" / "districts.json"
    d = json.loads(p.read_text())
    d["limits"]["NO3"]["acceptable"] = 50
    p.write_text(json.dumps(d))
    assert v.check_limit_strings()[0] is False


def test_gate_catches_uranium_trend(gate):
    v, site = gate
    p = site / "data" / "national.json"
    d = json.loads(p.read_text())
    d["trend"]["params"]["U"] = {"series": []}
    p.write_text(json.dumps(d))
    assert v.check_uranium_trend()[0] is False


def test_gate_catches_small_n_percentage(gate):
    v, site = gate
    p = site / "data" / "districts.json"
    d = json.loads(p.read_text())
    e = next(e for e in d["districts"] if e["headline"].get("NO3"))
    e["headline"]["NO3"].update(n=5, pct=40.0)
    p.write_text(json.dumps(d))
    ok, msg = v.check_small_n()
    assert ok is False and "NO3" in msg


def test_gate_catches_arsenic_limit_counts(gate):
    v, site = gate
    f = next((site / "data" / "d").glob("*.json"))
    d = json.loads(f.read_text())
    d["params"]["As"] = {"columns": ["year", "season", "n", "n_above_acceptable"], "rows": [[2024, "pre", 12, 3]]}
    f.write_text(json.dumps(d))
    assert v.check_values_only()[0] is False
