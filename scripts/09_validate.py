"""T9 validate: the gate before publish (SPEC §7, T9).

Every check is a hard failure. A check whose inputs do not exist yet is reported
as PENDING, and PENDING also fails the gate unless --allow-pending is passed
(used by `make all` while stages are still stubs). Check 6 never needs pipeline
output, so it is always enforced.
"""
from __future__ import annotations

import argparse
import sys

from gwlib import PROCESSED, SITE_DATA, compares_to_limit, params, settings, unverified_compared


def check_params_verified():
    """6. Every limit that outputs compare against has verified: true.

    A parameter may carry an unverified limit only with compare_to_limit: false,
    in which case values are published but no well is counted against the limit.
    """
    bad = unverified_compared(params())
    if bad:
        return False, f"unverified limits used for comparison: {', '.join(bad)} (see docs/METHOD.md)"
    held = [k for k, p in params().items() if p.get("verified") is False and not compares_to_limit(p)]
    note = f"; values only, no limit comparison: {', '.join(held)}" if held else ""
    return True, "every compared limit verified against IS 10500:2012" + note


def pending(*paths):
    def check():
        missing = [str(p.relative_to(PROCESSED.parent.parent)) for p in paths if not p.exists()]
        return None, f"waiting for {', '.join(missing)}" if missing else "inputs exist but check not implemented"
    return check


def _dpy():
    import pandas as pd
    p = PROCESSED / "district_param_year.csv"
    return pd.read_csv(p, dtype={"district_code": str}) if p.exists() else None


# ---- site payload helpers (T8) ---------------------------------------------------------

def _site_json():
    """districts.json and every d/*.json, or None before T8 has run."""
    import json
    p = SITE_DATA / "districts.json"
    if not p.exists():
        return None
    out = {"districts.json": json.loads(p.read_text())}
    for f in sorted((SITE_DATA / "d").glob("*.json")):
        out[f"d/{f.name}"] = json.loads(f.read_text())
    return out


def _param_rows(doc):
    """(file, param, row dict) for every row of every detail parameter table."""
    for name, d in doc.items():
        for p, t in (d.get("params") or {}).items():
            for r in t["rows"]:
                yield name, p, dict(zip(t["columns"], r))


def _entries(doc):
    """(file, district entry) for districts.json entries and every d/*.json file."""
    for e in doc["districts.json"]["districts"]:
        yield "districts.json", e
    for name, d in doc.items():
        if name.startswith("d/"):
            yield name, d


def _headlines(doc):
    for f, e in _entries(doc):
        for p, h in e.get("headline", {}).items():
            yield f"{f} {e['dt_code']}", p, h


def check_reference():
    """1. §2.7 reference statistics reproduced to one decimal."""
    import json
    p = PROCESSED.parent / "interim" / "t5_reference.json"
    if not p.exists():
        return None, "waiting for data/interim/t5_reference.json"
    r = json.loads(p.read_text())
    exp = {"NO3_pre_range": (19.5, 25.1), "NO3_pre_mean6": 21.9, "Cl_pre_range": (2.4, 3.1),
           "SO4_pre_range": (3.4, 4.7), "EC_2024_pre": 23.5, "NO3_2024_post": 26.7, "F_pre_range": (5.6, 9.0)}
    bad = [k for k, e in exp.items()
           if (tuple(round(x, 1) for x in r[k]) if isinstance(e, tuple) else round(r[k], 1)) != e]
    return (False, f"not reproduced: {bad}") if bad else (True, "all 7 reproduced")


def check_small_n():
    """3. No percentage where n_wells < 3 (in fact none below the reportable threshold)."""
    d = _dpy()
    if d is None:
        return None, "waiting for data/processed/district_param_year.csv"
    from gwlib import settings
    small = d["n_wells"] < settings()["reporting_thresholds"]["reportable"]
    bad = d.loc[small, [c for c in d if c.startswith("pct_")]].notna().any(axis=1).sum()
    if bad:
        return False, f"{bad} aggregate rows"
    doc = _site_json()
    if doc is None:
        return None, "aggregates clean; site check waits for site/data/districts.json"
    rep = settings()["reporting_thresholds"]["reportable"]
    site = [f"{f} {p} {r['year']} {r['season']}" for f, p, r in _param_rows(doc)
            if r["n"] < rep and any(r.get(c) is not None for c in r if c.startswith("pct_"))]
    site += [f"{c} {p}" for c, p, h in _headlines(doc) if h["n"] < rep and h.get("pct") is not None]
    for f, e in _entries(doc):
        for p, x in e.get("season_2024", {}).items():
            if min(x["pre_n"], x["post_n"]) < rep:
                site.append(f"{f} {e['dt_code']} season {p}")
    return (False, f"{len(site)} site values, e.g. {site[:3]}") if site else \
        (True, "no percentage below the reportable threshold in aggregates or site data")


def check_years():
    """4. No parameter outside its configured years."""
    d = _dpy()
    if d is None:
        return None, "waiting for data/processed/district_param_year.csv"
    P = params()
    bad = [p for p, s in P.items() if not set(d.loc[d["param"] == p, "year"]) <= set(s["years"])]
    if bad:
        return False, f"aggregates: {bad}"
    doc = _site_json()
    if doc is None:
        return None, "aggregates clean; site check waits for site/data/districts.json"
    site = sorted({f"{p} {r['year']}" for _, p, r in _param_rows(doc) if r["year"] not in P[p]["years"]})
    return (False, f"site: {site}") if site else (True, "every parameter within its years, aggregates and site")


def check_null_codes():
    """8. No null district_code in published aggregates."""
    d = _dpy()
    if d is None:
        return None, "waiting for data/processed/district_param_year.csv"
    n = int(d["district_code"].isna().sum())
    return (False, f"{n} null codes") if n else (True, "none")


def check_values_only():
    """11. No limit counts for compare_to_limit: false params (aggregates; site checked at T8)."""
    d = _dpy()
    if d is None:
        return None, "waiting for data/processed/district_param_year.csv"
    held = [p for p, s in params().items() if not compares_to_limit(s)]
    cols = ["n_above_acceptable", "n_above_permissible", "pct_above_acceptable", "pct_above_permissible"]
    bad = [p for p in held if d.loc[d["param"] == p, cols].notna().any().any()]
    if bad:
        return False, f"limit counts present for {bad}"
    doc = _site_json()
    if doc is None:
        return None, f"aggregates clean for {', '.join(held)}; site check waits for site/data/districts.json"
    limit_cols = {"n_above_acceptable", "n_above_permissible", "pct_above_acceptable", "pct_above_permissible"}
    site = sorted({f"{f} {p}" for f, p, r in _param_rows(doc) if p in held and limit_cols & set(r)})
    site += [f"headline {c} {p}" for c, p, h in _headlines(doc) if p in held]
    lim = doc["districts.json"]["limits"]
    site += [f"limits {p}" for p in held if p in lim and ({"acceptable", "permissible"} & set(lim[p]))]
    return (False, f"site: {site[:5]}") if site else (True, f"no limit fields or counts for {', '.join(held)} anywhere")


def check_all_districts():
    """2. All 640 districts present (coverage.csv now; site/data/districts.json at T8)."""
    import geopandas as gpd
    import pandas as pd
    from gwlib import ROOT
    p = PROCESSED / "coverage.csv"
    if not p.exists():
        return None, "waiting for data/processed/coverage.csv"
    g = gpd.read_file(ROOT / "data/external/boundaries/2011_Dist.shp", ignore_geometry=True)
    codes = {f"{c:03d}" for c in g["censuscode"] if c != 0}
    got = pd.read_csv(p, dtype={"district_code": str})["district_code"]
    if set(got) != codes or not got.is_unique:
        return False, f"coverage.csv: {len(codes - set(got))} missing, {len(set(got) - codes)} unknown"
    import json
    p = SITE_DATA / "districts.json"
    if not p.exists():
        return None, "coverage.csv has all 640; site check waits for site/data/districts.json"
    dj = [e["dt_code"] for e in json.loads(p.read_text())["districts"]]
    if set(dj) != codes or len(dj) != len(set(dj)):
        return False, f"districts.json: {len(codes - set(dj))} missing, {len(set(dj) - codes)} unknown"
    # exactly the expected files: sync tools (e.g. iCloud) can leave "001 2.json" copies
    stray = [f"{sub}/{p.name}" for sub, ext in (("d", ".json"), ("s", ".json"), ("dl", ".csv"))
             for p in (SITE_DATA / sub).iterdir()
             if p.suffix == ext and p.stem not in codes and p.name not in ("all_districts.csv", "coverage.csv",
                                                                             "covariates.csv")
             or p.suffix not in (ext, ".gz")]
    if stray:
        return False, f"{len(stray)} unexpected files in site/data, e.g. {stray[:3]}"
    missing = [c for c in codes if not (SITE_DATA / "d" / f"{c}.json").exists()
               or not (SITE_DATA / "s" / f"{c}.json").exists() or not (SITE_DATA / "dl" / f"{c}.csv").exists()]
    topo = json.loads((SITE_DATA / "geo" / "districts.topo.json").read_text())
    geo = {g["properties"]["dt_code"] for o in topo["objects"].values() for g in o["geometries"]}
    if missing or not codes <= geo:
        return False, f"{len(missing)} districts missing lazy files; {len(codes - geo)} missing geometry"
    return True, "640 in coverage.csv, districts.json, geometry, and d/ s/ dl/ files"


def check_uranium_trend():
    """5. Uranium absent from the national trend series (written by T8)."""
    import json
    p = SITE_DATA / "national.json"
    if not p.exists():
        return None, "waiting for site/data/national.json"
    trend = json.loads(p.read_text()).get("trend")
    if trend is None:
        return None, "national.json has no trend series yet (T8)"
    if "U" in trend.get("params", {}) or '"U"' in json.dumps(trend):
        return False, "U present in trend series"
    return True, f"trend series: {', '.join(trend['params'])}; U absent"


COVARIATE_GROUPS = {          # value columns -> the vintage column that must accompany them
    "hh6_vintage": ("pct_hh_", "hh6_households"),
    "dgwr_vintage": ("gw_stage_", "dgwr_units", "dgwr_recharge", "dgwr_extract"),
    "jjm_as_of": ("jjm_pct_", "jjm_rural_"),
}


def check_covariate_vintage():
    """9. Every covariate value has a non-null vintage / as-of date."""
    import pandas as pd
    p = PROCESSED / "covariates.csv"
    if not p.exists():
        return None, "waiting for data/processed/covariates.csv"
    d = pd.read_csv(p, dtype={"district_code": str})
    bad = []
    for vint, prefixes in COVARIATE_GROUPS.items():
        if vint not in d:
            bad.append(f"{vint} missing")
            continue
        cols = [c for c in d if c.startswith(prefixes)]
        n = int((d[cols].notna().any(axis=1) & d[vint].isna()).sum())
        if n:
            bad.append(f"{vint}: {n} rows")
    return (False, "; ".join(bad)) if bad else (True, f"{len(COVARIATE_GROUPS)} covariate groups, all dated")


def check_station_count():
    """7. Rows in dl/stations.csv.gz match the pipeline's station table."""
    import gzip
    import pandas as pd
    p = SITE_DATA / "dl" / "stations.csv.gz"
    if not p.exists():
        return None, "waiting for site/data/dl/stations.csv.gz"
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        n_dl = len(pd.read_csv(fh, dtype=str, keep_default_na=False))
    n = len(pd.read_csv(PROCESSED / "stations.csv", dtype=str, keep_default_na=False))
    import json
    n_nat = json.loads((SITE_DATA / "national.json").read_text()).get("stations_published")
    if n_dl != n or n_nat != n:
        return False, f"download {n_dl:,}, national.json {n_nat}, pipeline {n:,}"
    return True, f"{n:,} rows in download, national.json and pipeline"


LIMIT_KEYS_SITE = ("acceptable", "permissible", "indicator_threshold")


def check_limit_strings():
    """10. Every limit the site states matches params.yml.

    (a) the `limits` blocks in districts.json and national.json carry exactly the
        params.yml numbers; (b) no number-with-unit in the site's HTML/JS is a limit
        params.yml does not have for that unit (the site should read limits from JSON).
    """
    import json
    import re
    doc = _site_json()
    if doc is None:
        return None, "waiting for site/data/districts.json"
    P = params()
    bad = []
    blocks = {"districts.json": doc["districts.json"]["limits"]}
    npath = SITE_DATA / "national.json"
    if npath.exists():
        blocks["national.json"] = json.loads(npath.read_text()).get("limits", {})
    for name, lim in blocks.items():
        for p, e in lim.items():
            for k in LIMIT_KEYS_SITE:
                want = P[p].get(k) if compares_to_limit(P[p]) else None
                if e.get(k) != want:
                    bad.append(f"{name} {p}.{k}={e.get(k)} (params.yml {want})")
    allowed = {}
    for p in P.values():
        for k in LIMIT_KEYS_SITE:
            if p.get(k) is not None and compares_to_limit(p):
                allowed.setdefault(p["unit"], set()).add(float(p[k]))
    unit_re = r"(mg/L|mg/l|ppb|µg/L|ug/L|µS/cm|uS/cm)"
    for f in list(SITE_DATA.parent.glob("*.html")) + list((SITE_DATA.parent / "js").glob("*.js")):
        for num, unit in re.findall(rf"(\d[\d,]*(?:\.\d+)?)\s*{unit_re}", f.read_text(encoding="utf-8")):
            u = {"mg/l": "mg/L", "ug/L": "ppb", "µg/L": "ppb", "uS/cm": "µS/cm"}.get(unit, unit)
            if float(num.replace(",", "")) not in allowed.get(u, set()):
                bad.append(f"{f.name}: '{num} {unit}'")
    return (False, "; ".join(bad[:5])) if bad else (True, "limits blocks match params.yml; no stray limit in HTML/JS")


def check_budgets():
    """12. SPEC §3 performance budgets, gzipped."""
    import gzip
    if not (SITE_DATA / "districts.json").exists():
        return None, "waiting for site/data/districts.json"
    gz = lambda p: len(gzip.compress(p.read_bytes(), 9, mtime=0)) / 1024
    site = SITE_DATA.parent
    initial = sum(gz(p) for p in [site / "index.html", *site.glob("css/*.css"), *site.glob("js/*.js"),
                                  *site.glob("vendor/**/*.js"), *site.glob("vendor/**/*.css")] if p.is_file())
    geo, dj = gz(SITE_DATA / "geo" / "districts.topo.json"), gz(SITE_DATA / "districts.json")
    d_max = max(gz(p) for p in (SITE_DATA / "d").glob("*.json"))
    s_max = max(gz(p) for p in (SITE_DATA / "s").glob("*.json"))
    got = {"html+css+js": (initial, 120), "geometry": (geo, 600), "districts.json": (dj, 250),
           "initial total": (initial + geo + dj, 1024), "detail max": (d_max, 15), "stations max": (s_max, 40)}
    over = [f"{k} {v:.0f}>{b} KB" for k, (v, b) in got.items() if v > b]
    msg = ", ".join(f"{k} {v:.0f}/{b} KB" for k, (v, b) in got.items())
    return (False, "over budget: " + "; ".join(over)) if over else (True, msg)


CHECKS = [
    ("1 reference statistics (§2.7)", check_reference),
    ("2 all 640 districts present", check_all_districts),
    ("3 no percentage where n_wells < 3", check_small_n),
    ("4 no parameter outside its years", check_years),
    ("5 uranium absent from trend series", check_uranium_trend),
    ("6 every limit verified", check_params_verified),
    ("7 station count matches download", check_station_count),
    ("8 no null district_code in aggregates", check_null_codes),
    ("9 every covariate has a vintage", check_covariate_vintage),
    ("10 site limit strings match params.yml", check_limit_strings),
    ("11 no limit counts for compare_to_limit: false params", check_values_only),
    ("12 performance budgets (§3, gzipped)", check_budgets),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-pending", action="store_true",
                    help="treat checks whose inputs do not exist yet as non-fatal")
    args = ap.parse_args(argv)

    failed = pend = 0
    for name, fn in CHECKS:
        ok, msg = fn()
        tag = "PASS" if ok else ("PENDING" if ok is None else "FAIL")
        failed += ok is False
        pend += ok is None
        print(f"[{tag:7}] {name}: {msg}")

    print(f"\n{failed} failed, {pend} pending, {len(CHECKS) - failed - pend} passed")
    if failed or (pend and not args.allow_pending):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
