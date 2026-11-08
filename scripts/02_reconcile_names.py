"""T2 reconcile: raw state/district names to Census 2011 district codes.

district_code is the national 3-digit Census 2011 district code, the `censuscode`
field of Datameet's 2011_Dist.shp (001-640). That file's DT_CEN_CD field is the
district's number *within its state* and is not unique nationally.

Resolution order for each raw (state, district) pair; first hit wins:
  override  config/district_overrides.yml (an explicit human decision beats any rule)
  exact     normalised name equals a 2011 district in the mapped state
  alias     config/district_aliases.yml (renames, abbreviations, misspellings)
  alias     "0" repair: an earlier cleaning step replaced "na"/"nd" with "0" in some
            names (Bula0sahar, Chen0i); every combination is tried, unique hit only
  exact     same name, unique, in a different state (state label wrong in source);
            district_match_note = state_corrected
  fuzzy     rapidfuzz ratio >= 90 within the state, with a 5-point lead over the runner-up
  spatial   per row, point-in-polygon of a valid coordinate. Only for names the
            alias table marks null (post-2011 districts with several 2011 parents),
            rows with no district name, and states listed in settings.spatial_states
            (Delhi: districts redrawn in 2012 under the old names). Never a catch-all: a name no rule
            resolves stays unmatched until a human adds an alias or override.
            Every spatial name is listed in docs/UNMATCHED.md.
  unmatched otherwise
"""
from __future__ import annotations

import itertools
import json
import re

import geopandas as gpd
import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from gwlib import DOCS, INTERIM, ROOT, load_yaml, settings

BOUNDARIES = ROOT / "data/external/boundaries/2011_Dist.shp"
FUZZY_MIN, FUZZY_LEAD = 90, 5
SPATIAL = "SPATIAL"          # alias sentinel: resolve this name per row by coordinates


def key(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s).upper()) if pd.notna(s) else ""


def load_districts():
    g = gpd.read_file(BOUNDARIES)
    g = g[g["censuscode"] > 0].copy()            # code 0 = "Data Not Available" (J&K), not a district
    g["st_code"] = g["ST_CEN_CD"].map(lambda v: f"{int(v):02d}")
    g["district_code"] = g["censuscode"].map(lambda v: f"{int(v):03d}")
    g["key"] = g["DISTRICT"].map(key)
    g["geometry"] = g.geometry.make_valid()
    assert len(g) == 640 and g["district_code"].is_unique
    assert not g.duplicated(["st_code", "key"]).any()
    return g


class Resolver:
    def __init__(self, g):
        self.g = g
        self.by_state = {st: dict(zip(d["key"], d["district_code"])) for st, d in g.groupby("st_code")}
        self.national = g.groupby("key")["district_code"].agg(list).to_dict()
        aliases = load_yaml("district_aliases.yml") or {}
        self.alias = {}
        for st, table in aliases.items():
            st = f"{int(st):02d}"
            for raw, target in (table or {}).items():
                if target is None:                     # post-2011, multi-parent: place by coordinates
                    self.alias[(st, key(raw))] = SPATIAL
                    continue
                tk = key(target)
                if tk not in self.by_state.get(st, {}):
                    raise SystemExit(f"district_aliases.yml: {target!r} is not a 2011 district in state {st}")
                self.alias[(st, key(raw))] = self.by_state[st][tk]
        self.spatial_states = set(settings().get("spatial_states") or {})
        self.override = {}
        for o in load_yaml("district_overrides.yml") or []:
            code = f"{int(o['dt_code']):03d}"
            if code not in set(g["district_code"]):
                raise SystemExit(f"district_overrides.yml: unknown code {code}")
            self.override[(o["state_raw"], o["district_raw"])] = (code, o["reason"])

    def resolve(self, state_raw, district_raw, st, use_spatial_states=True):
        """Return (code|None, method, score, note[, state for spatial placement])."""
        if (state_raw, district_raw) in self.override:
            code, why = self.override[(state_raw, district_raw)]
            return code, "override", 1.0, why
        if use_spatial_states and st in self.spatial_states:
            return None, "spatial_pending", None, "state placed by coordinates (settings.spatial_states)", st
        k = key(district_raw)
        if not k:
            return None, "spatial_pending", None, "no district name", st
        local = self.by_state.get(st, {})
        if k in local:
            return local[k], "exact", 1.0, None
        if (st, k) in self.alias:
            return self._alias(self.alias[(st, k)], "alias table", st)
        if "0" in k:
            hits = set()
            parts = k.split("0")
            for combo in itertools.product(("NA", "ND"), repeat=len(parts) - 1):
                cand = "".join(p + c for p, c in zip(parts, combo)) + parts[-1]
                if cand in local:
                    hits.add(local[cand])
                elif (st, cand) in self.alias:
                    hits.add(self.alias[(st, cand)])
            if len(hits) == 1:
                return self._alias(hits.pop(), "repaired '0' -> na/nd", st)
        other = self.national.get(k, [])
        if len(other) == 1:
            return other[0], "exact", 1.0, "state_corrected"
        for (ast, ak), code in self.alias.items():
            if ak == k and ast != st:
                return self._alias(code, "alias table; state_corrected", ast)
        if local:
            best = process.extract(k, list(local), scorer=fuzz.ratio, limit=2)
            top = best[0]
            lead = top[1] - (best[1][1] if len(best) > 1 else 0)
            if top[1] >= FUZZY_MIN and lead >= FUZZY_LEAD:
                return local[top[0]], "fuzzy", round(top[1] / 100, 3), f"fuzzy -> {top[0]}"
        return None, "unmatched", None, None

    @staticmethod
    def _alias(code, note, st):
        if code == SPATIAL:
            return None, "spatial_pending", None, "post-2011 district, multi-parent", st
        return code, "alias", 1.0, note


def dms_to_dd(v):
    """DD.MMSS read as decimal -> decimal degrees; second value says whether the digits are valid minutes/seconds."""
    d = np.floor(v)
    f = (v - d) * 100
    m = np.floor(f + 1e-9)
    sec = (f - m) * 100
    return d + m / 60 + sec / 3600, (m < 60) & (sec < 60 + 1e-6)


def apply_dms(s):
    """Convert coordinate groups recorded as degrees.minutes (settings.coord_dms_groups).

    Keeps the original values in lat_raw/lon_raw and flags coord_converted:dms.
    Applied here, before any coordinate is used, keyed on the source state label.
    """
    s["lat_raw"], s["lon_raw"] = s["lat"], s["lon"]
    for grp in settings().get("coord_dms_groups") or []:
        m = s["state_code"].eq(grp["state_code"]) & s["year"].isin(grp["years"]) & s["lat"].notna() & s["lon"].notna()
        la, ok_a = dms_to_dd(s.loc[m, "lat"].to_numpy())
        lo, ok_o = dms_to_dd(s.loc[m, "lon"].to_numpy())
        ok = ok_a & ok_o
        idx = s.index[m][ok]
        s.loc[idx, "lat"], s.loc[idx, "lon"] = la[ok].round(6), lo[ok].round(6)
        s.loc[idx, "qc_flags"] = [(f + "," if isinstance(f, str) and f else "") + "coord_converted:dms" for f in s.loc[idx, "qc_flags"]]
        d = settings()["site_key_decimals"]
        s.loc[idx, "site_key"] = [f"{round(a, d):.{d}f},{round(o, d):.{d}f}" for a, o in zip(s.loc[idx, "lat"], s.loc[idx, "lon"])]
        print(f"DMS conversion state {grp['state_code']} {grp['years']}: {len(idx)} rows converted, {int((~ok).sum())} left as-is (not valid DD.MMSS)")


def main():
    st_map = load_yaml("state_map.yml")
    s = pd.read_csv(INTERIM / "stations_raw.csv", low_memory=False,
                    dtype={"state_raw": str, "district_raw": str, "block_raw": str,
                           "location_raw": str, "well_id_raw": str})
    missing = sorted(set(s["state_raw"].dropna()) - set(st_map)) + (["<null>"] if s["state_raw"].isna().any() else [])
    if missing:
        raise SystemExit(f"state_map.yml has no entry for: {missing}")
    s["state"] = s["state_raw"].map(lambda x: st_map[x]["state"])
    s["state_code"] = s["state_raw"].map(lambda x: st_map[x]["st_code"])
    s["state_now"] = s["state_raw"].map(lambda x: st_map[x].get("state_now", st_map[x]["state"]))

    apply_dms(s)

    g = load_districts()
    R = Resolver(g)
    pairs = s[["state_raw", "district_raw", "state_code"]].drop_duplicates()
    res = {}
    for r in pairs.itertuples(index=False):
        res[(r.state_raw, r.district_raw)] = R.resolve(r.state_raw, r.district_raw, r.state_code)
    looked = [res[(a, b)] + (None,) * (5 - len(res[(a, b)])) for a, b in zip(s["state_raw"], s["district_raw"])]
    s["district_code"] = [x[0] for x in looked]
    s["district_match_method"] = [x[1] for x in looked]
    s["district_match_score"] = [x[2] for x in looked]
    s["district_match_note"] = [x[3] for x in looked]
    spatial_state = pd.Series([x[4] for x in looked], index=s.index)

    # Spatial placement, per row, only for names marked for it (or blank names),
    # and only inside the state the name belongs to. A point outside that state
    # is a coordinate problem, not evidence of a district: it stays unmatched.
    pending = s["district_match_method"].eq("spatial_pending")
    todo = pending & s["coord_valid"].astype(bool)
    pts = gpd.GeoDataFrame(s.loc[todo, []], geometry=gpd.points_from_xy(s.loc[todo, "lon"], s.loc[todo, "lat"]), crs=g.crs)
    hit = gpd.sjoin(pts, g[["district_code", "st_code", "geometry"]], how="left", predicate="within")
    hit = hit[~hit.index.duplicated()]
    ok = hit["district_code"].notna() & hit["st_code"].eq(spatial_state.loc[hit.index])
    idx = hit.index[ok]
    s.loc[idx, "district_code"] = hit.loc[ok, "district_code"]
    s.loc[idx, "district_match_method"] = "spatial"
    s.loc[idx, "district_match_score"] = 1.0
    s.loc[idx, "district_match_note"] = s.loc[idx, "district_match_note"] + "; point-in-polygon"

    # spatial_states rows the coordinates could not place fall back to the name match.
    retry = s["district_match_method"].eq("spatial_pending") & s["district_match_note"].fillna("").str.contains("spatial_states")
    for i in s.index[retry]:
        r = R.resolve(s.at[i, "state_raw"], s.at[i, "district_raw"], spatial_state.at[i], use_spatial_states=False)
        if r[0] is not None:
            s.at[i, "district_code"], s.at[i, "district_match_method"], s.at[i, "district_match_score"] = r[0], r[1], r[2]
            s.at[i, "district_match_note"] = "coordinates outside the state or missing; name used"

    left = s["district_match_method"].eq("spatial_pending")
    outside = left & s["coord_valid"].astype(bool)
    s.loc[outside, "district_match_note"] = s.loc[outside, "district_match_note"] + "; coordinate outside the named state"
    s.loc[left & ~outside, "district_match_note"] = s.loc[left & ~outside, "district_match_note"] + "; no valid coordinate"
    s.loc[left, "district_match_method"] = "unmatched"

    # The state of record is the 2011 state of the matched district.
    code2st = dict(zip(g["district_code"], g["st_code"]))
    code2name = dict(zip(g["district_code"], g["DISTRICT"]))
    matched = s["district_code"].notna()
    s.loc[matched, "state_code"] = s.loc[matched, "district_code"].map(code2st)
    s["district_name_2011"] = s["district_code"].map(code2name)

    s.to_csv(INTERIM / "stations_named.csv", index=False)
    summary = write_unmatched(s, g)
    (INTERIM / "t2_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"rows with district_code: {summary['pct_rows_matched']:.2f}%  "
          f"distinct codes: {summary['distinct_codes']}  by method: {summary['rows_by_method']}")


def write_unmatched(s, g) -> dict:
    by_method = s["district_match_method"].value_counts().to_dict()
    pct = 100 * s["district_code"].notna().mean()
    L = ["# Name reconciliation report (T2)", "",
         "Generated by `scripts/02_reconcile_names.py`. Do not edit; fix names in",
         "`config/district_aliases.yml` or `config/district_overrides.yml` and rerun.", "",
         f"- Rows: {len(s):,}; with a district code: {s['district_code'].notna().sum():,} ({pct:.2f}%)",
         f"- Distinct district codes used: {s['district_code'].nunique()} of 640",
         "- Rows by match method: " + ", ".join(f"{k} {v:,}" for k, v in sorted(by_method.items())), ""]

    L += ["## Unmatched", "", "No district code. Reason in the last column.", "",
          "| State (raw) | District (raw) | Rows | Valid coords | Reason |", "|---|---|---|---|---|"]
    u = s[s["district_code"].isna()]
    for (a, b), d in u.groupby(["state_raw", "district_raw"], dropna=False):
        L.append(f"| {a} | {b} | {len(d)} | {int(d['coord_valid'].sum())} | {d['district_match_note'].fillna('no rule matched').iat[0]} |")

    L += ["", "## Resolved by coordinates (spatial)", "",
          "Names no rule resolved. Each row took the 2011 district its coordinates fall in.",
          "Post-2011 districts are expected here, often split across two 2011 parents.",
          "A name that is a typo of a 2011 district belongs in `district_aliases.yml` instead.", "",
          "| State (raw) | District (raw) | Rows | 2011 districts (rows) |", "|---|---|---|---|"]
    sp = s[s["district_match_method"] == "spatial"]
    for (a, b), d in sp.groupby(["state_raw", "district_raw"], dropna=False):
        dist = d["district_name_2011"].value_counts()
        L.append(f"| {a} | {b} | {len(d)} | " + ", ".join(f"{n} ({c})" for n, c in dist.items()) + " |")

    L += ["", "## Fuzzy matches", "", "| State (raw) | District (raw) | Matched 2011 district | Score | Rows |", "|---|---|---|---|---|"]
    fz = s[s["district_match_method"] == "fuzzy"]
    for (a, b), d in fz.groupby(["state_raw", "district_raw"]):
        L.append(f"| {a} | {b} | {d['district_name_2011'].iat[0]} | {d['district_match_score'].iat[0]:.2f} | {len(d)} |")

    L += ["", "## State label corrected", "", "Name matched a district in a different state from the one in the source.", "",
          "| State (raw) | District (raw) | Matched | Method | Rows |", "|---|---|---|---|---|"]
    sc = s[s["district_match_note"].fillna("").str.contains("state_corrected")]
    for (a, b), d in sc.groupby(["state_raw", "district_raw"]):
        L.append(f"| {a} | {b} | {d['district_name_2011'].iat[0]} ({d['state_code'].iat[0]}) | {d['district_match_method'].iat[0]} | {len(d)} |")

    L += ["", "## 2011 districts with no rows in any year", ""]
    absent = g[~g["district_code"].isin(set(s["district_code"].dropna()))]
    L += [f"- {r.district_code} {r.DISTRICT} ({r.ST_NM})" for r in absent.itertuples()] or ["- none"]
    (DOCS / "UNMATCHED.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return {"rows": len(s), "pct_rows_matched": pct, "distinct_codes": int(s["district_code"].nunique()),
            "rows_by_method": by_method, "unmatched_rows": int(s["district_code"].isna().sum()),
            "fuzzy_min_score": float(fz["district_match_score"].min()) if len(fz) else None}


if __name__ == "__main__":
    main()
