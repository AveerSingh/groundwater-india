"""T7 covariates: exposure (Census HH-6), extraction (DGWR 2024), response (JJM). SPEC §7 T7.

Reads only local files under data/external/ (scripts/fetch_covariates.py downloads them).
Writes:
  data/processed/covariates.csv   one row per 2011 district (640); a covariate a district
                                  lacks is null, never an error
  data/interim/t7_report.md       match rate per join and what did not join
  data/interim/t7_summary.json

Every covariate column has a `<group>_vintage` column, set wherever that group has a value.

1. Census 2011 HH-6. District rows (Total, all locations) join on the census district code.
   pct_hh_untreated_groundwater = handpump + tubewell/borehole + covered + uncovered well.
2. DGWR 2024. The source uses current (~780) districts. One at least NESTED inside a 2011
   district goes to it whole; one that straddles 2011 boundaries has its volumes split by
   area (overlay_weights). Stage = 100 * extraction / extractable resource over the 2011
   district. A value needs source districts with 2024 figures covering DGWR_MIN_COVER of
   the 2011 district. Unit counts are assessment units (blocks/mandals/taluks) by CGWB
   category, given only where nothing was split; there is no official district
   category, so none is invented.
3. JJM. Rows with a 2011 census code join directly. Post-2011 rows are matched by name,
   within their state, to the DGWR layer's current boundaries and split with the same
   weights; failing that, placed by their dashboard point or a known parent (JJM_PARENT).
"""
from __future__ import annotations

import glob
import json
import re
import warnings

import geopandas as gpd
import pandas as pd
from rapidfuzz import fuzz, process

from gwlib import DATA, INTERIM, PROCESSED, ROOT

EXT = DATA / "external"
BOUNDARIES = ROOT / "data/external/boundaries/2011_Dist.shp"
AREA_CRS = 7755
DGWR_MIN_COVER = 0.5   # share of a 2011 district's area covered by source districts with 2024 figures
SLIVER = 0.02          # overlaps under 2% of a source district are boundary noise
NESTED = 0.90          # a source district this much inside one 2011 district counts as nested

HH6_VINTAGE = "Census of India 2011"
DGWR_VINTAGE = "CGWB Dynamic Ground Water Resources 2024 (assessment year 2023-24)"

HH6_COLS = ["hh_total", "tap_treated", "tap_untreated", "well_covered", "well_uncovered",
            "handpump", "tubewell", "spring", "river_canal", "tank_pond", "other"]


def boundaries():
    g = gpd.read_file(BOUNDARIES)
    g = g[g["censuscode"] != 0].copy()
    g["district_code"] = g["censuscode"].astype(int).map("{:03d}".format)
    g["st_code"] = g["ST_CEN_CD"].astype(int).map("{:02d}".format)
    return g[["district_code", "st_code", "geometry"]].set_crs(4326, allow_override=True)


# ---- 1. Census HH-6 --------------------------------------------------------------------

def read_hh6(folder=EXT / "census_hh6"):
    frames = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for f in sorted(glob.glob(str(folder / "DDW-HH2206-*.xls"))):
            x = pd.read_excel(f, header=None, engine="xlrd", dtype=str)
            rows = x[(x[0] == "HH2206") & (x[3] == "00000") & (x[4] == "000000")
                     & (x[6] == "Total") & (x[7] == "Total")]
            frames.append(rows)
    d = pd.concat(frames).rename(columns={1: "st_code", 2: "district_code", 5: "area_name",
                                          **dict(zip(range(8, 19), HH6_COLS))})
    for c in HH6_COLS:
        d[c] = d[c].astype(float)
    return d[["st_code", "district_code", "area_name"] + HH6_COLS].reset_index(drop=True)


def hh6_covariates(d):
    d = d[d["district_code"] != "000"].copy()
    n = d["hh_total"]
    out = pd.DataFrame({
        "district_code": d["district_code"],
        "hh6_households": n.astype(int),
        "pct_hh_untreated_groundwater": 100 * (d["handpump"] + d["tubewell"] + d["well_covered"]
                                               + d["well_uncovered"]) / n,
        "pct_hh_handpump": 100 * d["handpump"] / n,
        "pct_hh_tubewell": 100 * d["tubewell"] / n,
        "pct_hh_well": 100 * (d["well_covered"] + d["well_uncovered"]) / n,
        "pct_hh_tap_treated": 100 * d["tap_treated"] / n,
        "pct_hh_tap_untreated": 100 * d["tap_untreated"] / n,
    })
    out["hh6_vintage"] = HH6_VINTAGE
    return out


def hh6_national(d):
    s = d[d["district_code"] == "000"][HH6_COLS].sum()
    pct = lambda *k: round(100 * sum(s[x] for x in k) / s["hh_total"], 1)
    return {"untreated_groundwater": pct("handpump", "tubewell", "well_covered", "well_uncovered"),
            "handpump": pct("handpump"), "tubewell": pct("tubewell"),
            "well": pct("well_covered", "well_uncovered"), "tap": pct("tap_treated", "tap_untreated"),
            "tap_untreated": pct("tap_untreated"), "households": int(s["hh_total"])}


# ---- 2. DGWR 2024 ----------------------------------------------------------------------

DGWR_SUM = {"totgwrec24": "dgwr_recharge_ham", "exgwres24": "dgwr_extractable_ham",
            "totgwex24": "dgwr_extraction_ham", "totno24": "dgwr_units", "safeno24": "dgwr_units_safe",
            "semcrino24": "dgwr_units_semi_critical", "crino24": "dgwr_units_critical",
            "ovrexpno24": "dgwr_units_over_exploited", "salno24": "dgwr_units_saline"}


DGWR_DIR = EXT / "dgwr"
DGWR_RAW = DGWR_DIR / "raw" / "dgwr_districts_2024.geojson"   # ESRI layer: not committed (licence unstated)
DGWR_TABLE = DGWR_DIR / "dgwr_districts_2024.csv"              # CGWB figures, no shapes
DGWR_WEIGHTS = DGWR_DIR / "dgwr_weights_2011.csv"              # current district -> 2011 district area weights


def build_dgwr_tables(raw=DGWR_RAW, b=None):
    """From the downloaded layer, write the two committed tables (run by fetch_covariates.py).

    The layer's shapes are used only here, to compute area weights against the 2011
    boundaries; the public repo carries CGWB's figures and the weights, not ESRI's shapes.
    """
    g = gpd.read_file(raw)
    g["geometry"] = g.geometry.make_valid()
    g["cur_id"] = g["objectid"].astype(int)
    W = overlay_weights(g, boundaries() if b is None else b)
    g.drop(columns="geometry").sort_values("cur_id").to_csv(DGWR_TABLE, index=False)
    W.sort_values(["cur_id", "district_code"]).to_csv(DGWR_WEIGHTS, index=False, float_format="%.17g")
    return len(g), len(W)


def read_dgwr():
    return pd.read_csv(DGWR_TABLE)


def read_weights():
    return pd.read_csv(DGWR_WEIGHTS, dtype={"district_code": str})


def overlay_weights(cur, b):
    """Area weights: share of each current district's area in each 2011 district.

    Slivers under SLIVER of a source district are dropped and the rest renormalised, so
    volumes are preserved.
    Returns cur_id, district_code, w (share of the source district), a (area, m2).
    """
    cur = cur.to_crs(AREA_CRS)
    ov = gpd.overlay(cur[["cur_id", "geometry"]], b.to_crs(AREA_CRS), how="intersection", keep_geom_type=True)
    ov["a"] = ov.area
    ov = ov[ov["a"] / ov["cur_id"].map(cur.set_index("cur_id").area) >= SLIVER]
    ov["w"] = ov["a"] / ov.groupby("cur_id")["a"].transform("sum")
    # a source district at least NESTED inside one 2011 district goes to it whole: the rest
    # is disagreement between the two boundary drawings, not a real split
    top = ov.groupby("cur_id")["w"].transform("max")
    nested = top >= NESTED
    ov = ov[~nested | (ov["w"] == top)].copy()
    ov.loc[nested, "w"] = 1.0
    return pd.DataFrame(ov[["cur_id", "district_code", "w", "a"]])


def dgwr_covariates(g, b, W):
    """Volumes apportioned by area; stage = extraction / extractable over the 2011 district."""
    b_area = b.to_crs(AREA_CRS).set_index("district_code").area
    has = g["exgwres24"].notna() & g["totgwex24"].notna()
    x = W.merge(g.loc[has, ["cur_id", *DGWR_SUM]], on="cur_id")
    vol = ["totgwrec24", "exgwres24", "totgwex24"]
    for c in vol:
        x[c] = x[c] * x["w"]
    grp = x.groupby("district_code")
    out = grp[vol].sum().rename(columns=DGWR_SUM)
    out["dgwr_area_cover"] = (grp["a"].sum() / b_area.reindex(out.index)).clip(upper=1).round(3)
    out["dgwr_n_source_districts"] = grp.size()
    # nested: every contributing source district lies (almost) wholly in this 2011 district
    out["dgwr_apportioned"] = grp["w"].min().lt(1).astype("boolean")
    units = [c for c in DGWR_SUM if c.endswith("no24")]
    u = grp[units].sum().rename(columns=DGWR_SUM)
    u.loc[out["dgwr_apportioned"]] = pd.NA            # unit counts cannot be split by area
    out = out.join(u.astype("Float64"))
    out["gw_stage_extraction_pct"] = (100 * out["dgwr_extraction_ham"] / out["dgwr_extractable_ham"]).round(2)
    low = out["dgwr_area_cover"] < DGWR_MIN_COVER
    out.loc[low, [c for c in out if c != "dgwr_area_cover"]] = pd.NA
    zero = out["dgwr_extractable_ham"] == 0
    out.loc[zero, "gw_stage_extraction_pct"] = pd.NA
    out["dgwr_note"] = pd.Series(pd.NA, index=out.index, dtype="string")
    out.loc[zero, "dgwr_note"] = "no extractable fresh groundwater assessed (saline or urban units); stage not defined"
    has_any = out[[c for c in out if c.startswith(("dgwr_units", "gw_stage", "dgwr_recharge", "dgwr_extract"))]].notna().any(axis=1)
    out["dgwr_vintage"] = DGWR_VINTAGE
    out.loc[~has_any, "dgwr_vintage"] = pd.NA
    for c in ("dgwr_recharge_ham", "dgwr_extractable_ham", "dgwr_extraction_ham"):
        out[c] = out[c].round(1)
    return out.reset_index(), int(low.sum())


# ---- 3. JJM ----------------------------------------------------------------------------

def read_jjm(folder=EXT / "jjm"):
    files = sorted(folder.glob("jjm_districts_*.json"))
    if not files:
        raise FileNotFoundError("no data/external/jjm/jjm_districts_*.json: run scripts/fetch_covariates.py jjm")
    f = files[-1]
    d = pd.DataFrame(json.loads(f.read_text())["d"])
    for c in ("Value", "Total", "Lat", "Long"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["code"] = d["KeyValue"].str.zfill(3)
    return d, f.stem.removeprefix("jjm_districts_")


def _norm(name):
    s = re.sub(r"[^a-z ]", " ", str(name).lower())
    s = re.sub(r"\b(district|dr|b r|sri|the)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Post-2011 JJM districts with neither a DGWR boundary nor a dashboard point, placed by
# their known parent (carved wholly from one 2011 district).
JJM_PARENT = {"Hansi": "080"}   # Haryana, from Hisar

# JJM state codes for reorganised states -> 2011 state codes
JJM_STATE_2011 = {"36": ["28"], "37": ["28"], "38": ["01"], "39": ["25", "26"]}


def match_names(rows, cur):
    """JJM post-2011 row -> DGWR cur_id, within the same 2011 state.

    Exact normalised name, else fuzzy (token-set >= 90 with a 5-point lead). A DGWR source
    district's 2011 state is that of the 2011 district holding most of its area (cur["st"]).
    """
    out = {}
    for code, nm, st in zip(rows["code"], rows["Name"], rows["StCode11"]):
        pool = cur[cur["st"].isin(JJM_STATE_2011.get(st, [st]))]
        idx = pool.assign(n=pool["district"].map(_norm)).groupby("n")["cur_id"].apply(list)
        k = _norm(nm)
        if k in idx and len(idx[k]) == 1:
            out[code] = idx[k][0]
            continue
        r = process.extract(k, list(idx.index), scorer=fuzz.token_set_ratio, limit=2)
        if r and r[0][1] >= 90 and (len(r) == 1 or r[0][1] - r[1][1] >= 5) and len(idx[r[0][0]]) == 1:
            out[code] = idx[r[0][0]][0]
    return out


def jjm_covariates(d, as_of, b, cur, W):
    """2011-coded rows join directly; post-2011 rows are split by the DGWR geometry of the
    same-named current district, else placed by the dashboard point."""
    codes = set(b["district_code"])
    d = d.copy()
    direct = d["code"].isin(codes)
    rows = [pd.DataFrame({"district_code": d.loc[direct, "code"], "w": 1.0,
                          "Value": d.loc[direct, "Value"], "Total": d.loc[direct, "Total"],
                          "src": d.loc[direct, "code"]})]
    new = d[~direct]
    st_of = b.set_index("district_code")["st_code"]
    dom = W.sort_values("w").groupby("cur_id").tail(1).set_index("cur_id")["district_code"].map(st_of)
    by_name = match_names(new, cur.assign(st=cur["cur_id"].map(dom)))
    named = new[new["code"].isin(by_name)]
    x = named.assign(cur_id=named["code"].map(by_name)).merge(W, on="cur_id")
    rows.append(pd.DataFrame({"district_code": x["district_code"], "w": x["w"], "Value": x["Value"],
                              "Total": x["Total"], "src": x["code"]}))
    rest = new[~new["code"].isin(by_name) & new["Lat"].notna()]
    pts = gpd.GeoDataFrame(rest, geometry=gpd.points_from_xy(rest["Long"], rest["Lat"]), crs=4326)
    placed = gpd.sjoin(pts, b, how="inner", predicate="within")
    rows.append(pd.DataFrame({"district_code": placed["district_code"], "w": 1.0, "Value": placed["Value"],
                              "Total": placed["Total"], "src": placed["code"]}))
    left = new[~new["code"].isin(by_name) & ~new["code"].isin(placed["code"]) & new["Name"].isin(JJM_PARENT)]
    rows.append(pd.DataFrame({"district_code": left["Name"].map(JJM_PARENT), "w": 1.0, "Value": left["Value"],
                              "Total": left["Total"], "src": left["code"]}))
    r = pd.concat(rows, ignore_index=True)
    r["Value"] *= r["w"]
    r["Total"] *= r["w"]
    g = r.groupby("district_code")
    agg = pd.DataFrame({"jjm_rural_households": g["Total"].sum().round(0),
                        "jjm_rural_households_tap": g["Value"].sum().round(0),
                        "jjm_n_source_districts": g["src"].nunique(),
                        "jjm_apportioned": (g["w"].min() < 1).astype("boolean")})
    agg["jjm_pct_rural_hh_tap"] = (100 * agg["jjm_rural_households_tap"] / agg["jjm_rural_households"]).round(2)
    agg.loc[agg["jjm_rural_households"] == 0, "jjm_pct_rural_hh_tap"] = pd.NA
    agg["jjm_as_of"] = f"Jal Jeevan Mission dashboard, retrieved {as_of}"
    agg.loc[agg["jjm_pct_rural_hh_tap"].isna(), "jjm_as_of"] = pd.NA
    unplaced = new[~new["code"].isin(set(r["src"]))]
    stats = {"direct": int(direct.sum()), "by_name": len(named), "by_point": len(placed),
             "by_known_parent": len(left), "unplaced": len(unplaced)}
    return agg.reset_index(), stats, unplaced


# ---- join ------------------------------------------------------------------------------

def main():
    b = boundaries()
    base = pd.DataFrame({"district_code": sorted(b["district_code"])})

    hh = read_hh6()
    c1 = hh6_covariates(hh)
    g = read_dgwr()
    W = read_weights()
    c2, n_low = dgwr_covariates(g, b, W)
    jd, as_of = read_jjm()
    c3, jstats, unplaced = jjm_covariates(jd, as_of, b, g, W)

    out = base.merge(c1, how="left").merge(c2, how="left").merge(c3, how="left")
    for c in out.select_dtypes("float").columns:
        if c.startswith("pct_"):
            out[c] = out[c].round(2)
    out.to_csv(PROCESSED / "covariates.csv", index=False)

    n = len(out)
    rate = lambda col: int(out[col].notna().sum())
    nat_stage = 100 * g["totgwex24"].sum() / g["exgwres24"].sum()
    summary = {
        "districts": n,
        "hh6": {"matched": rate("pct_hh_untreated_groundwater"), "national_pct": hh6_national(hh)},
        "dgwr": {"matched": rate("gw_stage_extraction_pct"), "source_districts": len(g),
                 "source_districts_no_2024": int(g["exgwres24"].isna().sum()),
                 "nulled_low_area_cover": n_low,
                 "apportioned": int(out["dgwr_apportioned"].fillna(False).astype(bool).sum()), "national_stage_pct": round(nat_stage, 2)},
        "jjm": {"matched": rate("jjm_pct_rural_hh_tap"), "source_districts": len(jd),
                **jstats, "as_of": as_of,
                "national_pct": round(100 * jd["Value"].sum() / jd["Total"].sum(), 2)},
    }
    (INTERIM / "t7_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    names = gpd.read_file(BOUNDARIES, ignore_geometry=True)
    names["district_code"] = names["censuscode"].astype(int).map("{:03d}".format)
    names = names.set_index("district_code")[["DISTRICT", "ST_NM"]]
    def missing(col):
        m = out.loc[out[col].isna(), "district_code"]
        return ", ".join(f"{names.at[c, 'DISTRICT']} ({names.at[c, 'ST_NM']})" for c in m)
    split = (W.groupby("cur_id")["w"].max().rename("share").to_frame().join(g.set_index("cur_id")[["district", "state"]])
             .query("share < @NESTED").sort_values("share"))
    lines = [
        "# T7 covariate joins", "",
        "| Covariate | Districts with a value | of | Source |", "|---|---|---|---|",
        f"| Census 2011 HH-6 | {summary['hh6']['matched']} | {n} | {HH6_VINTAGE} |",
        f"| DGWR 2024 stage of extraction | {summary['dgwr']['matched']} | {n} | {DGWR_VINTAGE} |",
        f"| JJM rural tap connections | {summary['jjm']['matched']} | {n} | retrieved {as_of} |", "",
        f"National checks: HH-6 untreated groundwater {summary['hh6']['national_pct']['untreated_groundwater']}%; "
        f"DGWR stage of extraction {summary['dgwr']['national_stage_pct']}% (published 60.47%); "
        f"JJM rural tap {summary['jjm']['national_pct']}%.", "",
        "## HH-6 without a value", missing("pct_hh_untreated_groundwater") or "none", "",
        "## DGWR without a value",
        f"{len(g)} source districts, {summary['dgwr']['source_districts_no_2024']} without 2024 figures "
        f"(unassessed hill districts, and districts created after the assessment whose figures sit with the parent). "
        f"{n_low} 2011 districts nulled because source districts with 2024 figures cover under {DGWR_MIN_COVER:.0%} of their area. "
        f"{summary['dgwr']['apportioned']} have a value apportioned by area from source districts that straddle 2011 boundaries.", "",
        missing("gw_stage_extraction_pct") or "none", "",
        f"## Source districts straddling 2011 boundaries (under {NESTED:.0%} in any one 2011 district)", "",
        "| Source district | State | Largest share in one 2011 district |", "|---|---|---|",
        *[f"| {r.district} | {r.state} | {r.share:.0%} |" for r in split.itertuples()], "",
        "## JJM without a value",
        "Urban-only districts have no rural households in JJM.", "",
        missing("jjm_pct_rural_hh_tap") or "none", "",
        f"Post-2011 JJM districts: {jstats['by_name']} split by the area of the same-named DGWR district, "
        f"{jstats['by_point']} placed by their dashboard point, {jstats['by_known_parent']} by a known parent "
        f"(JJM_PARENT), {jstats['unplaced']} not placed"
        + (": " + ", ".join(unplaced["Name"]) if len(unplaced) else "."),
    ]
    (INTERIM / "t7_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
