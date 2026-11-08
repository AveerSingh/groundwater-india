"""T3 spatial join: coordinates as an independent check on the name match.

Writes:
  data/interim/stations_spatial.csv   stations_named + coordinate columns below
  data/interim/t3_report.md           mismatch rates by state
  data/interim/t3_summary.json

Steps
1. Repair. A coordinate outside India's box is repaired only when exactly one
   candidate (lat/lon swapped, and/or a decimal point restored by dividing by a
   power of ten) lands inside the district the *name* matched. The original
   values are kept in lat_raw/lon_raw and the row is flagged coord_repaired:<how>.
2. Point-in-polygon for every valid coordinate -> coord_district_code.
3. coord_in_claimed_district = coord_district_code == district_code.
   Null when either side is missing. Rows whose district came from coordinates
   in T2 (method spatial) agree by construction; they are excluded from the
   mismatch rates and flagged nothing.
4. For mismatches, distance from the point to the named district's polygon.
   Under 2 km is likely boundary generalisation in the 2011 shapefile; the flag
   is still set, but the report separates near and far mismatches.
5. Aggregation district (SPEC §12.3, decided 2026-11-07). district_code_name keeps
   the name match. district_code, which every later stage aggregates on, becomes the
   coordinate district when the point is >= coord_reassign.min_km outside the named
   district AND the coordinate district is in the same state. Mostly wells still
   labelled with a parent district after a split (Erode for Tiruppur). Cross-state
   disagreements keep the name: those are more often bad coordinates.
   district_assign = name | coordinate records which applied.
"""
from __future__ import annotations

import itertools
import json

import geopandas as gpd
import numpy as np
import pandas as pd

from gwlib import INTERIM, ROOT, load_yaml, settings

BOUNDARIES = ROOT / "data/external/boundaries/2011_Dist.shp"
METRIC_CRS = 7755          # WGS 84 / India NSF LCC, metres
NEAR_KM = 2.0


def load_districts():
    g = gpd.read_file(BOUNDARIES)
    g = g[g["censuscode"] > 0].copy()
    g["district_code"] = g["censuscode"].map(lambda v: f"{int(v):03d}")
    g["st_code"] = g["ST_CEN_CD"].map(lambda v: f"{int(v):02d}")
    g["geometry"] = g.geometry.make_valid()
    return g[["district_code", "st_code", "DISTRICT", "geometry"]]


def in_box(lat, lon, b):
    return b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]


def scalings(v):
    """v, and v divided by powers of ten (restores a lost decimal point)."""
    out = [v]
    for k in range(1, 9):
        out.append(v / 10 ** k)
    return out


def repair(s, g, b):
    """Return {index: (lat, lon, how)} for unambiguous, name-confirmed repairs."""
    poly = dict(zip(g["district_code"], g["geometry"]))
    cand_rows = s.index[~s["coord_valid"].astype(bool) & s["lat"].notna() & s["lon"].notna() & s["district_code"].notna()]
    fixes = {}
    for i in cand_rows:
        lat, lon, code = s.at[i, "lat"], s.at[i, "lon"], s.at[i, "district_code"]
        hits = set()
        for swap in (False, True):
            a, o = (lon, lat) if swap else (lat, lon)
            for (ka, va), (ko, vo) in itertools.product(enumerate(scalings(a)), enumerate(scalings(o))):
                if not in_box(va, vo, b):
                    continue
                if poly[code].contains(gpd.points_from_xy([vo], [va])[0]):
                    how = "+".join(x for x in ("swap" if swap else "", f"lat/1e{ka}" if ka else "", f"lon/1e{ko}" if ko else "") if x)
                    hits.add((round(va, 6), round(vo, 6), how))
        if len({(h[0], h[1]) for h in hits}) == 1:
            fixes[i] = sorted(hits, key=lambda h: len(h[2]))[0]
    return fixes


def main():
    S = settings()
    b = S["coord_bounds"]
    s = pd.read_csv(INTERIM / "stations_named.csv", low_memory=False,
                    dtype={"district_code": str, "state_code": str, "well_id_raw": str,
                           "state_raw": str, "district_raw": str, "block_raw": str, "location_raw": str})
    g = load_districts()

    # 1. repair
    if "lat_raw" not in s:                       # set by T2 before any DMS conversion
        s["lat_raw"], s["lon_raw"] = s["lat"], s["lon"]
    fixes = repair(s, g, b)
    d = S["site_key_decimals"]
    for i, (la, lo, how) in fixes.items():
        s.at[i, "lat"], s.at[i, "lon"] = la, lo
        s.at[i, "coord_valid"] = True
        s.at[i, "site_key"] = f"{round(la, d):.{d}f},{round(lo, d):.{d}f}"
        flags = [f for f in str(s.at[i, "qc_flags"]).split(",") if f and f != "nan" and f != "coord_invalid"]
        s.at[i, "qc_flags"] = ",".join(flags + [f"coord_repaired:{how}"])
    s["coord_valid"] = s["coord_valid"].astype(bool)

    # 2. point in polygon
    v = s["coord_valid"]
    pts = gpd.GeoDataFrame(index=s.index[v], geometry=gpd.points_from_xy(s.loc[v, "lon"], s.loc[v, "lat"]), crs=g.crs)
    hit = gpd.sjoin(pts, g[["district_code", "geometry"]], how="left", predicate="within")
    hit = hit[~hit.index.duplicated()]
    s["coord_district_code"] = None
    s.loc[hit.index, "coord_district_code"] = hit["district_code"]

    # 3. agreement
    both = s["district_code"].notna() & s["coord_district_code"].notna()
    s["coord_in_claimed_district"] = pd.Series(pd.NA, index=s.index, dtype="boolean")
    s.loc[both, "coord_in_claimed_district"] = s.loc[both, "coord_district_code"] == s.loc[both, "district_code"]
    independent = both & s["district_match_method"].ne("spatial")
    mism = independent & ~s["coord_in_claimed_district"].fillna(True).astype(bool)

    # 4. distance to the named district for mismatches
    gm = g.to_crs(METRIC_CRS).set_index("district_code")
    pm = gpd.GeoSeries(gpd.points_from_xy(s.loc[mism, "lon"], s.loc[mism, "lat"]), index=s.index[mism], crs=4326).to_crs(METRIC_CRS)
    s["coord_dist_to_claimed_km"] = np.nan
    s.loc[mism, "coord_dist_to_claimed_km"] = [
        round(p.distance(gm.at[c, "geometry"]) / 1000, 2) for p, c in zip(pm, s.loc[mism, "district_code"])]

    for i in s.index[mism]:
        f = str(s.at[i, "qc_flags"])
        s.at[i, "qc_flags"] = (f + "," if f and f != "nan" else "") + "coord_district_mismatch"
    s.loc[s["qc_flags"].astype(str).eq("nan"), "qc_flags"] = None

    no_poly = v & s["coord_district_code"].isna()       # valid box, but in no district (sea, disputed area, border)

    # 5. aggregation district
    rule = S["coord_reassign"]
    st_of = dict(zip(g["district_code"], g["st_code"]))
    s["district_code_name"] = s["district_code"]
    far = mism & (s["coord_dist_to_claimed_km"] >= rule["min_km"])
    same_state = s["coord_district_code"].map(st_of) == s["district_code"].map(st_of)
    move = far & (same_state if rule["same_state_only"] else True)
    s["district_assign"] = np.where(s["district_code"].isna(), None, "name")
    s.loc[move, "district_code"] = s.loc[move, "coord_district_code"]
    s.loc[move, "district_assign"] = "coordinate"
    names = dict(zip(g["district_code"], g["DISTRICT"]))
    s["district_name_2011"] = s["district_code"].map(names)

    s.to_csv(INTERIM / "stations_spatial.csv", index=False)
    summary = report(s, independent, mism, no_poly, fixes, move, far)
    (INTERIM / "t3_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"repaired {len(fixes)} coordinates; independent checks {int(independent.sum()):,}; "
          f"mismatch {int(mism.sum()):,} ({100 * mism.sum() / independent.sum():.2f}%), "
          f"of which within {NEAR_KM:g} km {int((s.loc[mism, 'coord_dist_to_claimed_km'] < NEAR_KM).sum()):,}; "
          f"valid coords in no district {int(no_poly.sum())}")


STATE_NAMES = {v["st_code"]: v["state"] for v in load_yaml("state_map.yml").values()}


def report(s, independent, mism, no_poly, fixes, move, far_mask):
    dist = s["coord_dist_to_claimed_km"]
    rows = []
    for st, d in s[independent].groupby("state_code"):
        m = mism.loc[d.index]
        dd = dist.loc[d.index][m]
        rows.append({
            "state_code": st, "state": STATE_NAMES.get(st, st), "checked": len(d),
            "mismatch": int(m.sum()), "pct": round(100 * m.mean(), 2),
            "far": int((dd >= NEAR_KM).sum()), "pct_far": round(100 * (dd >= NEAR_KM).sum() / len(d), 2),
            "median_km": round(float(dd.median()), 1) if len(dd) else None,
        })
    rows.sort(key=lambda r: -r["pct"])
    total_far = int((dist[mism] >= NEAR_KM).sum())
    L = ["# T3 spatial cross-check", "", "Generated by `scripts/03_spatial_join.py`. Do not edit.", "",
         f"- Coordinates repaired (name-confirmed): {len(fixes)}",
         f"- Rows checked independently (name match + valid coordinate, not placed spatially in T2): {int(independent.sum()):,}",
         f"- Point outside the named district: {int(mism.sum()):,} ({100 * mism.sum() / independent.sum():.2f}%)",
         f"  - within {NEAR_KM:g} km of it (boundary noise likely): {int(mism.sum()) - total_far:,}",
         f"  - {NEAR_KM:g} km or more: {total_far:,} ({100 * total_far / independent.sum():.2f}%)",
         f"- Valid coordinate inside no 2011 district polygon: {int(no_poly.sum())}", "",
         "## By state", "",
         f"`far` = point {NEAR_KM:g} km or more outside the named district.", "",
         "| State | Code | Checked | Mismatch | % | Far | % far | Median km (mismatches) |",
         "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['state']} | {r['state_code']} | {r['checked']:,} | {r['mismatch']:,} | {r['pct']:.1f} | "
                 f"{r['far']:,} | {r['pct_far']:.1f} | {r['median_km'] if r['median_km'] is not None else '—'} |")
    L += ["", "## Aggregation district (SPEC §12.3)", "",
          f"Wells reassigned to their coordinate district (far mismatch, same state): {int(move.sum()):,}. "
          f"Far mismatches kept on the name because the coordinate is in another state: {int((far_mask & ~move).sum()):,}.", "",
          "| Named district | Moved to | Wells |", "|---|---|---|"]
    names = dict(zip(s["district_code"].dropna(), s["district_name_2011"].dropna()))
    mv = s[move].groupby(["district_code_name", "district_code"]).size().sort_values(ascending=False)
    for (a, b), n in mv.head(40).items():
        L.append(f"| {names.get(a, a)} | {names.get(b, b)} | {n} |")
    L += ["", "## Repaired coordinates", "", "| obs_id | District (2011) | Raw lat, lon | Repaired | How |", "|---|---|---|---|---|"]
    for i, (la, lo, how) in sorted(fixes.items()):
        L.append(f"| {s.at[i, 'obs_id']} | {s.at[i, 'district_name_2011']} | {s.at[i, 'lat_raw']}, {s.at[i, 'lon_raw']} | {la}, {lo} | {how} |")
    left = s[~s["coord_valid"]]
    L += ["", f"## Still invalid ({len(left)})", "", "| obs_id | State (raw) | District (raw) | lat | lon |", "|---|---|---|---|---|"]
    L += [f"| {r.obs_id} | {r.state_raw} | {r.district_raw} | {r.lat_raw} | {r.lon_raw} |" for r in left.itertuples()]
    L += ["", "## Far mismatches by named district (top 40)", "",
          "| State | Named district (2011) | Far mismatches | Of rows checked | Most common coordinate district |", "|---|---|---|---|---|"]
    far = s[mism & (dist >= NEAR_KM)]
    for code, d in sorted(far.groupby("district_code"), key=lambda x: -len(x[1]))[:40]:
        n_chk = int((independent & s["district_code"].eq(code)).sum())
        top = d["coord_district_code"].value_counts()
        names = dict(zip(s["district_code"], s["district_name_2011"]))
        L.append(f"| {d['state'].iat[0]} | {d['district_name_2011'].iat[0]} | {len(d)} | {n_chk} | "
                 f"{names.get(top.index[0], top.index[0])} ({top.iat[0]}) |")
    (INTERIM / "t3_report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return {"repaired": len(fixes), "checked": int(independent.sum()), "mismatch": int(mism.sum()),
            "reassigned_to_coordinate": int(move.sum()), "far_kept_cross_state": int((far_mask & ~move).sum()),
            "far": total_far, "no_polygon": int(no_poly.sum()), "by_state": rows}


if __name__ == "__main__":
    main()
