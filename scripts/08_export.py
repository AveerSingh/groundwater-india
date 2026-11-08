"""T8 export: web payloads in site/data/ (SPEC §7 T8, budgets §3, schema §5.3).

  national.json            limits, headline numbers, national trend (no uranium), coverage
                           (the coverage key is written by T6 and kept)
  districts.json           640 entries, headline fields only
  geo/districts.topo.json  simplified shared-border topology; `dt_code` is the only property
  d/{dt_code}.json         full district detail, lazy-loaded
  s/{dt_code}.json         that district's stations, compact columns, lazy-loaded
  dl/{dt_code}.csv         that district's aggregate table
  dl/all_districts.csv     every district's aggregate table
  dl/coverage.csv, dl/covariates.csv
  dl/stations.csv.gz       the full published station table
  data/interim/t8_budget.json   gzipped sizes against the §3 budgets (GitHub Pages serves
                                JSON gzipped, so gzipped bytes are what a phone downloads)

The browser computes nothing (SPEC §3): every number here is final. Limits are written
from config/params.yml so the site never hard-codes one. Parameters with
compare_to_limit: false (As, U) carry values only: no limit, no counts against one.

Geometry: Datameet 2011 districts, simplified with the `topojson` package (shared arcs,
Douglas-Peucker, prevent_oversimplify keeps every polygon) instead of mapshaper, so the
pipeline stays Python-only. A few rings self-touch at a single shared vertex after simplification
(no area change; Leaflet draws them normally). Code "000" is the boundary file's "Data Not Available" area
beyond the Line of Control; it is kept so the outline of India is complete, and has no
entry in districts.json.
"""
from __future__ import annotations

import gzip
import importlib.util
import io
import json
import shutil

import geopandas as gpd
import numpy as np
import pandas as pd

from gwlib import (INTERIM, PROCESSED, ROOT, SITE_DATA, compares_to_limit, load_yaml, params,
                   read_stations, settings)

BOUNDARIES = ROOT / "data/external/boundaries/2011_Dist.shp"
HEADLINE = ["NO3", "F", "EC", "Cl"]          # Tier A: map layers and landing numbers
TREND = ["NO3", "F", "EC", "Cl"]             # SPEC §8.4; uranium never
PANEL_TIERS = ("A", "B")
PERSIST_MIN_YEARS = 4
PERSIST_RULE = ("Pre-monsoon years in which the district had at least 3 wells tested for the parameter; "
                "a year counts as above when at least one well exceeded the limit (EC: the indicator "
                "threshold). Shown only where at least 4 such years exist. Different wells may be "
                "sampled in different years.")
SEASON_RULE = ("2024 pre- vs post-monsoon share above the limit, shown only where both rounds have at "
               "least 10 wells. The two rounds need not sample the same wells.")
SIMPLIFY_EPS = 0.003                         # degrees (~330 m), Douglas-Peucker
QUANTIZE = 1e4                               # coordinate grid (~330 m over India's extent)
BUDGET_KB = {"geometry": 600, "districts": 250, "detail_max": 15, "stations_max": 40}


def _mod(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def clean(x):
    """JSON-safe scalars: NaN -> None, numpy -> python, floats trimmed."""
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if x is None or x is pd.NA or (isinstance(x, float) and np.isnan(x)):
        return None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return int(f) if f.is_integer() else round(f, 3)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def dump(obj, path, indent=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    sep = (",", ":") if indent is None else None
    path.write_text(json.dumps(clean(obj), ensure_ascii=False, separators=sep, indent=indent), encoding="utf-8")


def gz_size(path):
    return len(gzip.compress(path.read_bytes(), compresslevel=9, mtime=0))


# ---- limits ----------------------------------------------------------------------------

def limits_block(P):
    """What the site may state about each panel parameter. No limit for values-only params."""
    out = {}
    for k, p in P.items():
        if p["tier"] not in PANEL_TIERS:
            continue
        e = {"label": p["label"], "unit": p["unit"], "tier": p["tier"], "years": p["years"]}
        if compares_to_limit(p):
            for key in ("acceptable", "permissible", "indicator_threshold", "permissible_condition", "source"):
                if p.get(key) is not None:
                    e[key] = p[key]
            if p.get("note"):
                e["note"] = p["note"]
        else:
            e["values_only"] = True
            e["note"] = "Limit not yet verified against the IS 10500 text; values shown without comparison."
        out[k] = e
    return out


# ---- districts -------------------------------------------------------------------------

def district_names():
    st = load_yaml("states.yml")
    g = gpd.read_file(BOUNDARIES, ignore_geometry=True)
    g = g[g["censuscode"] != 0]
    d = pd.DataFrame({"dt_code": g["censuscode"].astype(int).map("{:03d}".format),
                      "district": g["DISTRICT"].astype(str),
                      "st_code": g["ST_CEN_CD"].astype(int).map("{:02d}".format)})
    d["district"] = d["dt_code"].map(st["district_display"]).fillna(d["district"])
    d["state"] = d["st_code"].map(st["state_2011"])
    now = d["dt_code"].map(st["state_now"]["by_district"]).fillna(d["st_code"].map(st["state_now"]["by_state"]))
    d["state_now"] = now.fillna(d["state"])
    if d["state"].isna().any():
        raise SystemExit("state code missing from config/states.yml")
    return d.sort_values("dt_code").set_index("dt_code")


def headline_entry(r, p):
    """One parameter's 2024 pre-monsoon headline from a district_param_year row."""
    e = {"n": r["n_wells"], "tier": r["coverage_tier"], "median": r["median"], "max": r["max"]}
    if p == "EC":
        e["above_indicator"] = r["n_above_indicator"]
        e["pct"] = r["pct_above_indicator"]
    else:
        e["above_acceptable"] = r["n_above_acceptable"]
        e["above_permissible"] = r["n_above_permissible"]
        e["pct"] = r["pct_above_permissible"]
    return e


def persistence(dd, p, S):
    """Pre-monsoon years with >= count_only wells; 'above' = at least one well over the limit."""
    col = "n_above_indicator" if p == "EC" else "n_above_permissible"
    x = dd[(dd["param"] == p) & (dd["season"] == "pre") & (dd["n_wells"] >= S["reporting_thresholds"]["count_only"])]
    m = len(x)
    if m < PERSIST_MIN_YEARS or x[col].isna().all():
        return None
    a = int((x[col] > 0).sum())
    label = ("every year measured" if a == m else
             "no year measured" if a == 0 else f"{a} of {m} years")
    return {"years_measured": m, "years_above": a, "years": sorted(x["year"].tolist()), "label": label}


def season_2024(dd, p, y0):
    col = "pct_above_indicator" if p == "EC" else "pct_above_permissible"
    x = dd[(dd["param"] == p) & (dd["year"] == y0)].set_index("season")
    if not {"pre", "post"} <= set(x.index):
        return None
    pre, post = x.at["pre", col], x.at["post", col]
    if pd.isna(pre) or pd.isna(post):
        return None
    return {"pre_pct": pre, "post_pct": post, "delta": round(post - pre, 1),
            "pre_n": x.at["pre", "n_wells"], "post_n": x.at["post", "n_wells"]}


def context(cv):
    if cv is None:
        return {}
    return {
        "hh_total": cv["hh6_households"],
        "pct_hh_untreated_groundwater": round(cv["pct_hh_untreated_groundwater"], 1),
        "hh_source_year": 2011,
        "gw_extraction_stage_pct": cv["gw_stage_extraction_pct"],
        "gw_extraction_year": 2024 if pd.notna(cv["dgwr_vintage"]) else None,
        "gw_units": None if pd.isna(cv["dgwr_units"]) else {
            "total": cv["dgwr_units"], "safe": cv["dgwr_units_safe"],
            "semi_critical": cv["dgwr_units_semi_critical"], "critical": cv["dgwr_units_critical"],
            "over_exploited": cv["dgwr_units_over_exploited"], "saline": cv["dgwr_units_saline"]},
        "gw_note": cv["dgwr_note"],
        "gw_apportioned": cv["dgwr_apportioned"],
        "jjm_fhtc_pct": None if pd.isna(cv["jjm_pct_rural_hh_tap"]) else round(cv["jjm_pct_rural_hh_tap"], 1),
        "jjm_as_of": cv["jjm_as_of"],
    }


def coverage_entry(c):
    yrs = [int(y) for y in str(c["years_sampled"]).split(";") if y and y != "nan"]
    split = lambda s: [x for x in str(s).split(";") if x and x != "nan"]
    return {"years_sampled": yrs, "n_years": c["n_years"],
            "wells_by_year": {str(y): c[f"wells_{y}"] for y in yrs},
            "wells_2024": c["wells_2024"], "wells_2024_pre": c["wells_2024_pre"],
            "wells_2024_post": c["wells_2024_post"], "wells_primary": c["wells_primary"],
            "params_ever_tested": split(c["params_ever_tested"]),
            "params_never_tested": split(c["params_never_tested"]), "tier": c["tier"]}


SLIM_HEAD = ("n", "tier", "pct", "above_permissible", "above_indicator")


def slim_entry(e):
    c = e["coverage"]
    return {"dt_code": e["dt_code"], "district": e["district"], "state": e["state"], "state_now": e["state_now"],
            "coverage": {"n_years": c["n_years"], "wells_2024": c["wells_2024"],
                         "wells_primary": c["wells_primary"], "tier": c["tier"]},
            "headline": {p: {k: h[k] for k in SLIM_HEAD if k in h} for p, h in e["headline"].items()}}


def authorities_for(st_code, A):
    """Sourced entries only: central bodies everywhere, state bodies for their state."""
    out = []
    for k, a in (A or {}).items():
        if not a.get("source_url"):
            continue
        if a.get("level") == "central" or st_code in (a.get("st_codes") or []):
            out.append(k)
    return out


def param_table(dd, P):
    """All parameters, compact rows. Values-only parameters carry no limit columns."""
    cols = ["year", "season", "n", "n_below_detection", "n_above_acceptable", "n_above_permissible",
            "n_above_indicator", "pct_above_acceptable", "pct_above_permissible", "pct_above_indicator",
            "median", "p90", "max", "tier"]
    src = ["year", "season", "n_wells", "n_below_detection", "n_above_acceptable", "n_above_permissible",
           "n_above_indicator", "pct_above_acceptable", "pct_above_permissible", "pct_above_indicator",
           "median", "p90", "max", "coverage_tier"]
    out = {}
    for p, spec in P.items():
        x = dd[dd["param"] == p].sort_values(["year", "season"])
        if x.empty:
            continue
        keep = [i for i, c in enumerate(cols) if c in ("year", "season", "n", "n_below_detection", "median", "p90",
                                                        "max", "tier")
                or (compares_to_limit(spec) and x[src[i]].notna().any())]
        out[p] = {"columns": [cols[i] for i in keep],
                  "rows": [[r[src[i]] for i in keep] for _, r in x.iterrows()]}
    return out


# ---- stations --------------------------------------------------------------------------

STATION_PARAMS = ["NO3", "F", "EC", "Cl", "SO4", "Fe", "U", "As"]


def station_payload(s):
    """Compact station list for the viewport overlay: located, counted rows only."""
    agg = _mod("agg", "05_aggregate.py")
    s = s[s["lat"].notna() & s["lon"].notna() & ~agg.flag_mask(s, "duplicate_copy")]
    cols = ["lat", "lon", "year", "season", "location"] + STATION_PARAMS + ["bdl"]
    rows = []
    for _, r in s.iterrows():
        bdl = [p for p in STATION_PARAMS if agg.censored_mask(r.to_frame().T, p).iat[0]] if pd.notna(r["censored"]) else []
        rows.append([round(r["lat"], 4), round(r["lon"], 4), r["year"], r["season"],
                     None if pd.isna(r["location_raw"]) else str(r["location_raw"])[:40]]
                    + [None if pd.isna(r[p]) else round(float(r[p]), 3) for p in STATION_PARAMS]
                    + [";".join(bdl) or None])
    return {"columns": cols, "rows": rows,
            "note": "bdl lists parameters reported below detection; a null value is not tested."}


# ---- national --------------------------------------------------------------------------

def trend(s, P, S):
    """National % of tested pre-monsoon wells above the limit, by year (published rules)."""
    agg = _mod("agg", "05_aggregate.py")
    rules = S["aggregation"]
    keep = s["district_code"].notna()
    for fl in rules["exclude_flags"]:
        keep &= ~agg.flag_mask(s, fl)
    s = s[keep & (s["season"] == "pre")]
    out = {}
    for p in TREND:
        spec = P[p]
        tested, val, _ = agg.tested_values(s, p, rules)
        if p == "EC":
            above = (val > spec["indicator_threshold"]) & tested
        else:
            above = (val > agg.permissible_series(s, p, spec, rules)) & tested
        ser = []
        for y in spec["years"]:
            m = s["year"] == y
            n, a = int(tested[m].sum()), int(above[m].sum())
            ser.append({"year": y, "n": n, "above": a, "pct": round(100 * a / n, 1) if n else None})
        out[p] = {"label": spec["label"], "measure": "indicator" if p == "EC" else "permissible",
                  "series": ser}
    return {"season": "pre", "params": out,
            "caption": "National share of monitored wells above the limit, pre-monsoon. The monitored network "
                       "changes between years: these are national aggregates, not district trends. "
                       "Uranium is excluded because its sampled states changed between years."}


def _years_text(ys):
    ys = sorted(ys)
    return f"{ys[0]}-{ys[-1]}" if ys == list(range(ys[0], ys[-1] + 1)) else ", ".join(map(str, ys))


def headline_numbers(dpy, cov, S, P):
    y0, s0, T = S["primary_year"], S["primary_season"], S["reporting_thresholds"]
    x = dpy[(dpy["param"] == "NO3") & (dpy["year"] == y0) & (dpy["season"] == s0) & (dpy["n_wells"] >= T["reportable"])]
    never_as = int(cov["params_never_tested"].fillna("").str.split(";").map(lambda l: "As" in l).sum())
    return {
        "nitrate_quarter": {"districts": int((x["pct_above_permissible"] > 25).sum()), "of": len(x),
                            "text": f"districts where more than a quarter of monitored wells exceed the nitrate limit "
                                    f"({y0} pre-monsoon, districts with at least {T['reportable']} wells)"},
        "fewer_than_3_wells": {"districts": int((cov[f"wells_{y0}"] < T["count_only"]).sum()), "of": len(cov),
                               "text": f"districts with fewer than {T['count_only']} monitored wells in {y0}"},
        "never_tested_arsenic": {"districts": never_as, "of": len(cov),
                                 "text": f"districts with no arsenic result in {_years_text(P['As']['years'])}, "
                                         f"the years CGWB reported arsenic"},
    }


# ---- static page values ---------------------------------------------------------------

def _get(doc, path):
    for k in path.split("."):
        doc = doc[k]
    return doc


def _fmt(v):
    import html
    if isinstance(v, str):
        return html.escape(v)
    if isinstance(v, float) and not v.is_integer():
        return f"{v:,.1f}"
    return f"{int(v):,}"


def fill_static(html_path, nat):
    """Write pipeline numbers into the page's no-JS text: <!--n:path-->value<!--/n-->.

    The trend table body between <!--trend-rows--> markers is rebuilt too. Nothing on the
    page is typed by hand, so the static text can never drift from the data.
    """
    import re
    if not html_path.exists():
        return
    h = html_path.read_text(encoding="utf-8")
    h = re.sub(r"<!--n:([\w.]+)-->.*?<!--/n-->", lambda m: f"<!--n:{m[1]}-->{_fmt(_get(nat, m[1]))}<!--/n-->", h,
               flags=re.S)
    t = nat["trend"]["params"]
    years = [r["year"] for r in t["NO3"]["series"]]
    rows = "".join(
        "<tr><th scope=\"row\">{}</th>{}</tr>".format(
            y, "".join(f"<td>{next(r for r in t[p]['series'] if r['year'] == y)['pct']:.1f}%</td>" for p in t))
        for y in years)
    h = re.sub(r"<!--trend-rows-->.*?<!--/trend-rows-->", f"<!--trend-rows-->{rows}<!--/trend-rows-->", h, flags=re.S)
    html_path.write_text(h, encoding="utf-8")


# ---- geometry --------------------------------------------------------------------------

def geometry(out_path):
    import topojson as tp
    g = gpd.read_file(BOUNDARIES)
    g["geometry"] = g.geometry.make_valid()
    g = g.explode(index_parts=False)
    g = g[g.geom_type.isin(["Polygon", "MultiPolygon"])]
    g = g.dissolve(by="censuscode", as_index=False)
    g["dt_code"] = g["censuscode"].astype(int).map("{:03d}".format)
    g = g[["dt_code", "geometry"]].set_crs(4326, allow_override=True)
    topo = tp.Topology(g, prequantize=QUANTIZE, topology=True, toposimplify=SIMPLIFY_EPS,
                       simplify_algorithm="dp", prevent_oversimplify=True)
    d = json.loads(topo.to_json())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(d, separators=(",", ":")), encoding="utf-8")
    return len(g)


# ---- main ------------------------------------------------------------------------------

def main():
    P, S = params(), settings()
    y0, s0 = S["primary_year"], S["primary_season"]
    names = district_names()
    dpy = pd.read_csv(PROCESSED / "district_param_year.csv", dtype={"district_code": str})
    cov = pd.read_csv(PROCESSED / "coverage.csv", dtype={"district_code": str, "st_code": str})
    cvp = PROCESSED / "covariates.csv"
    cvs = pd.read_csv(cvp, dtype={"district_code": str}).set_index("district_code") if cvp.exists() else None
    st = read_stations(PROCESSED / "stations.csv")
    A = load_yaml("authorities.yml")

    for sub in ("d", "s", "dl"):
        shutil.rmtree(SITE_DATA / sub, ignore_errors=True)
        (SITE_DATA / sub).mkdir(parents=True)

    by_d = dict(tuple(dpy.groupby("district_code")))
    by_s = dict(tuple(st[st["district_code"].notna()].groupby("district_code")))
    cov_i = cov.set_index("district_code")
    empty = dpy.iloc[0:0]
    lim = limits_block(P)
    entries, detail_sizes, station_sizes = [], {}, {}
    for code, nm in names.iterrows():
        dd = by_d.get(code, empty)
        prim = dd[(dd["year"] == y0) & (dd["season"] == s0)].set_index("param")
        head = {p: headline_entry(prim.loc[p], p) for p in HEADLINE if p in prim.index}
        pers = {p: v for p in HEADLINE if (v := persistence(dd, p, S))}
        seas = {p: v for p in HEADLINE if (v := season_2024(dd, p, y0))}
        e = {"dt_code": code, "district": nm["district"], "state": nm["state"], "state_now": nm["state_now"],
             "st_code": nm["st_code"], "coverage": coverage_entry(cov_i.loc[code]), "headline": head,
             "persistence": pers, "season_2024": seas,
             "context": context(cvs.loc[code] if cvs is not None and code in cvs.index else None),
             "authorities": authorities_for(nm["st_code"], A)}
        entries.append(e)
        detail = {**e, "rules": {"persistence": PERSIST_RULE, "season_2024": SEASON_RULE},
                  "params": param_table(dd, P),
                  "downloads": {"csv": f"dl/{code}.csv", "json": f"d/{code}.json", "stations": f"s/{code}.json"}}
        dump(detail, SITE_DATA / "d" / f"{code}.json")
        detail_sizes[code] = gz_size(SITE_DATA / "d" / f"{code}.json")
        sp = station_payload(by_s[code]) if code in by_s else {"columns": [], "rows": []}
        dump(sp, SITE_DATA / "s" / f"{code}.json")
        station_sizes[code] = gz_size(SITE_DATA / "s" / f"{code}.json")

    # districts.json: what the first paint needs (map colours, tooltips, district picker).
    # Persistence, seasons, context and parameter lists load with d/{dt_code}.json on click.
    slim = [slim_entry(e) for e in entries]
    labels = {k: {"label": v["label"], "unit": v.get("unit", "")} for k, v in P.items()}
    dump({"limits": lim, "labels": labels, "districts": slim}, SITE_DATA / "districts.json")

    # downloads
    full = dpy.merge(names.reset_index().rename(columns={"dt_code": "district_code"})[
        ["district_code", "district", "state", "state_now"]], on="district_code", how="left")
    lead = ["district_code", "district", "state", "state_now"]
    full = full[lead + [c for c in full if c not in lead]]
    full.to_csv(SITE_DATA / "dl" / "all_districts.csv", index=False)
    for code, x in full.groupby("district_code"):
        x.to_csv(SITE_DATA / "dl" / f"{code}.csv", index=False)
    for code in set(names.index) - set(full["district_code"]):
        full.iloc[0:0].to_csv(SITE_DATA / "dl" / f"{code}.csv", index=False)
    shutil.copy(PROCESSED / "coverage.csv", SITE_DATA / "dl" / "coverage.csv")
    if cvp.exists():
        shutil.copy(cvp, SITE_DATA / "dl" / "covariates.csv")
    raw = (PROCESSED / "stations.csv").read_bytes()
    with open(SITE_DATA / "dl" / "stations.csv.gz", "wb") as fh:
        with gzip.GzipFile(fileobj=fh, mode="wb", compresslevel=9, mtime=0, filename="stations.csv") as z:
            z.write(raw)

    # national.json: keep T6's coverage key
    npath = SITE_DATA / "national.json"
    nat = json.loads(npath.read_text()) if npath.exists() else {}
    nat.update({"limits": lim, "headline": headline_numbers(dpy, cov, S, P), "trend": trend(st, P, S),
                "stations_published": len(st)})
    dump(nat, npath, indent=1)

    fill_static(SITE_DATA.parent / "index.html", nat)

    n_geo = geometry(SITE_DATA / "geo" / "districts.topo.json")

    budget = {
        "geometry_kb": round(gz_size(SITE_DATA / "geo" / "districts.topo.json") / 1024, 1),
        "districts_kb": round(gz_size(SITE_DATA / "districts.json") / 1024, 1),
        "national_kb": round(gz_size(npath) / 1024, 1),
        "detail_max_kb": round(max(detail_sizes.values()) / 1024, 1),
        "detail_max_district": max(detail_sizes, key=detail_sizes.get),
        "stations_max_kb": round(max(station_sizes.values()) / 1024, 1),
        "stations_max_district": max(station_sizes, key=station_sizes.get),
        "budget_kb": BUDGET_KB, "geometry_features": n_geo, "districts": len(entries),
    }
    budget["ok"] = (budget["geometry_kb"] <= BUDGET_KB["geometry"] and budget["districts_kb"] <= BUDGET_KB["districts"]
                    and budget["detail_max_kb"] <= BUDGET_KB["detail_max"]
                    and budget["stations_max_kb"] <= BUDGET_KB["stations_max"])
    (INTERIM / "t8_budget.json").write_text(json.dumps(budget, indent=2), encoding="utf-8")
    print(json.dumps(budget, indent=1))


if __name__ == "__main__":
    main()
