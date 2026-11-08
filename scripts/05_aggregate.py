"""T5 aggregate: district x year x season x parameter (SPEC §5.2).

Writes:
  data/processed/district_param_year.csv
  data/interim/t5_reference.json     §2.7 statistics recomputed by the manuscript's method

Rules (config/settings.yml `aggregation`, decided 2026-11-07):
  tested     value present, or below detection (BDL/ND/nil/traces/"<x"), or a negative
             reading (near-zero instrument value). Values nulled as extreme are NOT tested:
             the true value is unknown.
  exceeds    value strictly greater than the limit. Below-detection and negative readings
             never exceed.
  limits     from config/params.yml. A null permissible limit means "no relaxation", so
             permissible = acceptable. Sulphate's permissible 400 applies only where
             Mg <= 30 mg/L (else 200); unknown Mg -> 400. EC has an indicator threshold,
             not a BIS limit (n_above_indicator). Parameters with compare_to_limit: false
             (As, U until verified) get no limit counts at all.
  thresholds n >= reportable: percentages; count_only <= n < reportable: counts, no
             percentage; n < count_only: insufficient (counts kept, no percentage).
             A suppressed percentage is null, never zero.
  statistics median / p90 / max over tested wells, below-detection and negative as 0.
  excluded   rows flagged coord_invalid (SPEC T5) or duplicate_copy (identical repeats),
             and rows with no district_code.

The manuscript's method, used only for the §2.7 regression: all rows, value > limit over
rows with a value, "<x" read as x, below-detection excluded, unconditional limits.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from gwlib import INTERIM, PROCESSED, compares_to_limit, params, read_stations, settings

OUT_COLS = ["district_code", "year", "season", "param", "n_wells", "n_below_detection",
            "n_above_acceptable", "n_above_permissible", "n_above_indicator",
            "pct_above_acceptable", "pct_above_permissible", "pct_above_indicator",
            "median", "p90", "max", "coverage_tier", "n_cbe_high"]


def censored_mask(s, p):
    return s["censored"].fillna("").str.contains(rf"(?:^|,){p}(?:<|,|$)", regex=True)


def flag_mask(s, flag):
    return s["qc_flags"].fillna("").str.contains(rf"(?:^|,){flag}(?:,|$)", regex=True)


def tested_values(s, p, rules):
    """Return (tested mask, value series with below-detection/negative as 0, bdl mask)."""
    v = s[p].copy()
    bdl = censored_mask(s, p) if rules["below_detection_counts_as_tested"] else pd.Series(False, index=s.index)
    if rules["negative_counts_as_below_detection"]:
        bdl = bdl | flag_mask(s, f"neg_value:{p}")
    bdl = bdl & v.isna()
    tested = v.notna() | bdl
    return tested, v.where(~bdl, 0.0), bdl


def permissible_series(s, p, spec, rules):
    acc, perm = spec.get("acceptable"), spec.get("permissible")
    if perm is None:
        perm = acc
    lim = pd.Series(perm, index=s.index, dtype=float)
    if p == "SO4" and rules["sulphate_mg_condition"] and acc is not None:
        lim = lim.where(~(s["Mg"] > 30), float(acc))
    return lim


def tier(n, T):
    return "reportable" if n >= T["reportable"] else ("count_only" if n >= T["count_only"] else "insufficient")


def aggregate(s, P, S):
    rules, T = S["aggregation"], S["reporting_thresholds"]
    keep = s["district_code"].notna()
    for fl in rules["exclude_flags"]:
        keep &= ~flag_mask(s, fl)
    s = s[keep]
    cbe_high = flag_mask(s, "cbe_high")
    rows = []
    for p, spec in P.items():
        tested, val, bdl = tested_values(s, p, rules)
        cmp = compares_to_limit(spec)
        acc = spec.get("acceptable")
        perm = permissible_series(s, p, spec, rules) if cmp else None
        ind = spec.get("indicator_threshold")
        d = pd.DataFrame({
            "district_code": s["district_code"], "year": s["year"], "season": s["season"],
            "tested": tested, "val": val, "bdl": bdl, "cbe": cbe_high,
            "above_acc": (val > acc) & tested if cmp and acc is not None else False,
            "above_perm": (val > perm) & tested if cmp and perm is not None else False,
            "above_ind": (val > ind) & tested if ind is not None else False,
        })
        d = d[d["tested"] & d["year"].isin(spec["years"])]
        if d.empty:
            continue
        g = d.groupby(["district_code", "year", "season"])
        agg = g.agg(n_wells=("tested", "size"), n_below_detection=("bdl", "sum"),
                    n_above_acceptable=("above_acc", "sum"), n_above_permissible=("above_perm", "sum"),
                    n_above_indicator=("above_ind", "sum"), median=("val", "median"),
                    p90=("val", lambda x: x.quantile(0.9)), max=("val", "max"),
                    n_cbe_high=("cbe", "sum")).reset_index()
        agg["param"] = p
        if not (cmp and acc is not None):
            agg[["n_above_acceptable", "n_above_permissible"]] = np.nan
        if ind is None:
            agg["n_above_indicator"] = np.nan
        agg["coverage_tier"] = agg["n_wells"].map(lambda n: tier(n, T))
        rep = agg["n_wells"] >= T["reportable"]
        for k in ("acceptable", "permissible", "indicator"):
            agg[f"pct_above_{k}"] = (100 * agg[f"n_above_{k}"] / agg["n_wells"]).round(1).where(rep)
        rows.append(agg)
    out = pd.concat(rows, ignore_index=True)[OUT_COLS]
    for c in ("median", "p90", "max"):
        out[c] = out[c].round(3)
    return out.sort_values(["district_code", "param", "year", "season"]).reset_index(drop=True)


def manuscript_pct(s, p, limit, year, season):
    """§2.7 regression method: all rows; value > limit over rows with a value; "<x" read as x."""
    d = s[(s["year"] == year) & (s["season"] == season)]
    lt = d["censored"].fillna("").str.extract(rf"(?:^|,){p}<([0-9.]+)")[0].astype(float)
    v = d[p].fillna(lt)
    return 100 * (v > limit).sum() / v.notna().sum()


def reference(s):
    yrs = range(2019, 2025)
    pre = {p: [manuscript_pct(s, p, lim, y, "pre") for y in yrs]
           for p, lim in (("NO3", 45), ("Cl", 1000), ("SO4", 400), ("F", 1.5))}
    return {
        "NO3_pre_range": [min(pre["NO3"]), max(pre["NO3"])],
        "NO3_pre_mean6": float(np.mean(pre["NO3"])),
        "Cl_pre_range": [min(pre["Cl"]), max(pre["Cl"])],
        "SO4_pre_range": [min(pre["SO4"]), max(pre["SO4"])],
        "F_pre_range": [min(pre["F"]), max(pre["F"])],
        "EC_2024_pre": manuscript_pct(s, "EC", 1500, 2024, "pre"),
        "NO3_2024_post": manuscript_pct(s, "NO3", 45, 2024, "post"),
        "by_year": {p: dict(zip(yrs, v)) for p, v in pre.items()},
    }


def main():
    P, S = params(), settings()
    s = read_stations(PROCESSED / "stations.csv")
    out = aggregate(s, P, S)
    out.to_csv(PROCESSED / "district_param_year.csv", index=False)
    ref = reference(s)
    (INTERIM / "t5_reference.json").write_text(json.dumps(ref, indent=2), encoding="utf-8")
    print(f"wrote {len(out):,} rows to data/processed/district_param_year.csv "
          f"({out['district_code'].nunique()} districts); tiers: {out['coverage_tier'].value_counts().to_dict()}")
    print("§2.7 by manuscript method: " + ", ".join(
        f"{k} {v[0]:.2f}-{v[1]:.2f}" if isinstance(v, list) else f"{k} {v:.2f}"
        for k, v in ref.items() if k != "by_year"))


if __name__ == "__main__":
    main()
