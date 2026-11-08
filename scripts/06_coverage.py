"""T6 coverage: the monitoring-blind-spot layer (SPEC §7 T6).

Writes:
  data/processed/coverage.csv   one row per 2011 district, all 640, including districts
                                with no data (tier "insufficient")
  site/data/national.json       key "coverage": national headline numbers. T8 adds its own
                                keys to this file and must keep this one.
  data/interim/t6_summary.json

Definitions (docs/METHOD.md, "Monitoring coverage (T6)"):
  well       a distinct site_key (3-decimal coordinates) within a district and year; a row
             without a site_key counts as one well. Rows flagged coord_invalid or
             duplicate_copy are left out, as in T5, so coverage and aggregates agree.
  wells_YYYY wells sampled in that year, either season, any parameter.
  wells_primary
             wells in the primary year and season (2024 pre-monsoon) with major-ion results,
             i.e. not flagged no_major_ions. This is the count the map's tier is built on:
             the map's contamination layers are major-ion parameters.
  tier       reportable / count_only / insufficient from wells_primary, same thresholds as T5.
  tested     a parameter is tested in a district if any well has a value, a below-detection
             result or a negative reading for it, in a year configured for that parameter.
"""
from __future__ import annotations

import importlib.util
import json

import geopandas as gpd
import pandas as pd

from gwlib import INTERIM, PROCESSED, ROOT, SITE_DATA, load_yaml, params, read_stations, settings

BOUNDARIES = ROOT / "data/external/boundaries/2011_Dist.shp"
YEARS = list(range(2019, 2025))
HEADLINE_PARAMS = ["F", "As", "U"]


def _agg_module():
    spec = importlib.util.spec_from_file_location("agg", ROOT / "scripts/05_aggregate.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def districts():
    """The 640 Census 2011 districts (code 0, J&K 'Data Not Available', excluded)."""
    g = gpd.read_file(BOUNDARIES, ignore_geometry=True)
    g = g[g["censuscode"] != 0]
    return pd.DataFrame({
        "district_code": g["censuscode"].astype(int).map("{:03d}".format),
        "district": g["DISTRICT"].astype(str),
        "st_code": g["ST_CEN_CD"].astype(int).map("{:02d}".format),
        "state_2011": g["ST_NM"].astype(str),
    }).sort_values("district_code").reset_index(drop=True)


def usable(s, S):
    agg = _agg_module()
    keep = s["district_code"].notna()
    for fl in S["aggregation"]["exclude_flags"]:
        keep &= ~agg.flag_mask(s, fl)
    s = s[keep].copy()
    # Rows sharing a site_key in one round that are not identical copies are kept apart
    # (T5 counts them as separate wells: two wells within ~110 m). Numbering them within
    # the round lets the same well match across seasons while keeping the per-season
    # count equal to T5's n_wells.
    rank = s.groupby(["site_key", "year", "season"]).cumcount().astype(str)
    s["well"] = (s["site_key"] + "#" + rank).fillna("obs:" + s["obs_id"].astype(str))
    return s


def count_wells(s, by):
    return s.groupby(by)["well"].nunique()


def tested_params(s, P, S):
    """district_code -> set of parameters with at least one tested well in a configured year."""
    agg = _agg_module()
    out = {}
    for p, spec in P.items():
        tested, _, _ = agg.tested_values(s, p, S["aggregation"])
        codes = s.loc[tested & s["year"].isin(spec["years"]), "district_code"].unique()
        for c in codes:
            out.setdefault(c, set()).add(p)
    return out


def tier(n, T):
    return "reportable" if n >= T["reportable"] else ("count_only" if n >= T["count_only"] else "insufficient")


def coverage(s, D, P, S):
    T = S["reporting_thresholds"]
    y0, s0 = S["primary_year"], S["primary_season"]
    agg = _agg_module()
    by_year = count_wells(s, ["district_code", "year"]).unstack(fill_value=0).reindex(columns=YEARS, fill_value=0)
    by_year.columns = [f"wells_{y}" for y in YEARS]
    prim = s[(s["year"] == y0) & (s["season"] == s0) & ~agg.flag_mask(s, "no_major_ions")]
    seas = {f"wells_{y0}_{x}": count_wells(s[(s["year"] == y0) & (s["season"] == x)], "district_code")
            for x in ("pre", "post")}

    out = D.set_index("district_code").join(by_year)
    for k, v in seas.items():
        out[k] = v
    out["wells_primary"] = count_wells(prim, "district_code")
    wcols = list(by_year.columns) + list(seas) + ["wells_primary"]
    out[wcols] = out[wcols].fillna(0).astype(int)

    ycols = [f"wells_{y}" for y in YEARS]
    out["years_sampled"] = out[ycols].apply(lambda r: ";".join(str(y) for y, n in zip(YEARS, r) if n), axis=1)
    out["n_years"] = (out[ycols] > 0).sum(axis=1)
    out[f"in_{y0}"] = out[f"wells_{y0}"] > 0
    tp = tested_params(s, P, S)
    order = list(P)
    out["params_ever_tested"] = [";".join(p for p in order if p in tp.get(c, ())) for c in out.index]
    out["params_never_tested"] = [";".join(p for p in order if p not in tp.get(c, ())) for c in out.index]
    out["n_params_never_tested"] = [sum(p not in tp.get(c, ()) for p in order) for c in out.index]
    out["tier"] = out["wells_primary"].map(lambda n: tier(n, T))
    return out.reset_index()


def per_state(cov, s, pop, y0):
    """Wells in the primary year per million people, by 2011 state."""
    wells = cov.groupby("st_code")[f"wells_{y0}"].sum()
    rows = []
    for code, rec in sorted(pop["by_state"].items()):
        w = int(wells.get(code, 0))
        rows.append({"st_code": code, "state": rec["name"], "population_2011": rec["population"],
                     f"wells_{y0}": w, "wells_per_million": round(w / rec["population"] * 1e6, 1)})
    return rows


def national(cov, s, pop, S):
    y0, T = S["primary_year"], S["reporting_thresholds"]
    n = len(cov)
    never = {p: sorted(cov.loc[cov["params_never_tested"].str.split(";").map(lambda x: p in x), "district_code"])
             for p in HEADLINE_PARAMS}
    w = cov[f"wells_{y0}"]
    total_wells = int(w.sum())
    return {
        "as_of": f"CGWB groundwater quality data 2019-{y0}",
        "districts_total": n,
        "definitions": {
            "boundaries": "Census 2011 districts (640), Datameet 2011_Dist.shp",
            "well": "distinct site (coordinates to 3 decimals) within a district and year; "
                    "rows with invalid coordinates or identical duplicates are left out",
            f"wells_{y0}": f"wells sampled in {y0}, either season, any parameter",
            "tier": f"from wells with major-ion results in {y0} {S['primary_season']}-monsoon: "
                    f">= {T['reportable']} reportable, {T['count_only']}-{T['reportable'] - 1} count only, "
                    f"fewer than {T['count_only']} insufficient",
            "never_tested": "no tested well in any year 2019-2024 in which CGWB reported that parameter",
        },
        "districts_zero_wells_primary_year": int((w == 0).sum()),
        "districts_lt3_wells_primary_year": int((w < T["count_only"]).sum()),
        "districts_1_to_2_wells_primary_year": int(((w > 0) & (w < T["count_only"])).sum()),
        "districts_never_sampled": int((cov["n_years"] == 0).sum()),
        "districts_by_tier": {t: int((cov["tier"] == t).sum()) for t in ("reportable", "count_only", "insufficient")},
        "districts_never_tested": {p: len(v) for p, v in never.items()},
        "districts_never_tested_codes": never,
        "wells_primary_year": total_wells,
        "wells_per_million_primary_year": round(total_wells / pop["india_total"] * 1e6, 1),
        "population_vintage": pop["vintage"],
        "wells_per_million_by_state": per_state(cov, s, pop, y0),
    }


def write_national(cov_summary):
    path = SITE_DATA / "national.json"
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    doc = json.loads(path.read_text()) if path.exists() else {}
    doc["coverage"] = cov_summary
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")


def main():
    P, S = params(), settings()
    D = districts()
    s = read_stations(PROCESSED / "stations.csv")
    unknown = set(s["district_code"].dropna()) - set(D["district_code"])
    if unknown:
        raise SystemExit(f"district codes not in the boundary file: {sorted(unknown)}")
    s = usable(s, S)
    cov = coverage(s, D, P, S)
    cov.to_csv(PROCESSED / "coverage.csv", index=False)
    nat = national(cov, s, load_yaml("population_2011.yml"), S)
    write_national(nat)
    summ = {k: v for k, v in nat.items() if k not in ("districts_never_tested_codes", "wells_per_million_by_state",
                                                       "definitions")}
    (INTERIM / "t6_summary.json").write_text(json.dumps(summ, indent=2), encoding="utf-8")
    print(f"wrote {len(cov)} districts to data/processed/coverage.csv and site/data/national.json")
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
