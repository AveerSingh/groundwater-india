"""T4 QC: charge balance, implausible carbonate, duplicates; write the published station table.

Writes:
  data/processed/stations.csv   the published station table (SPEC §5.1)
  data/interim/qc_report.md     counts per flag, per year, per state
  data/interim/t4_summary.json

Flags are recorded, never used to delete (SPEC §5.4).

Charge balance (meq/L): CBE% = (Σcations − Σanions) / (Σcations + Σanions) × 100.
  Cations Ca, Mg, Na, K; anions HCO3, CO3, Cl, SO4, NO3, F.
  Computed when Ca, Mg, Na, K, HCO3, Cl, SO4 each have a value or a below-detection
  result (counted as 0). CO3, NO3, F count as 0 when missing.
  |CBE| > settings.cbe_flag_pct -> cbe_high.
co3_implausible: CO3 > 10 mg/L at pH < 8.3. Carbonate is negligible below pH 8.3,
  so hundreds of mg/L there is a reporting error (SPEC §2.6, the 2023 southern
  Andhra cluster). The value is kept; the flag tells consumers not to trust it.
duplicate_obs: more than one row with the same site_key, year and season.
duplicate_copy: within such a group, a row identical to an earlier row in every
  parameter value and in location name. The first copy is unflagged; later copies
  carry duplicate_copy so aggregation can count the record once.
"""
from __future__ import annotations

import json
from collections import Counter

import numpy as np
import pandas as pd

from gwlib import INTERIM, PROCESSED, params, read_stations, settings

EQ_WT = {"Ca": 20.04, "Mg": 12.15, "Na": 22.99, "K": 39.10,
         "HCO3": 61.02, "CO3": 30.00, "Cl": 35.45, "SO4": 48.03, "NO3": 62.00, "F": 19.00}
CATIONS, ANIONS = ["Ca", "Mg", "Na", "K"], ["HCO3", "CO3", "Cl", "SO4", "NO3", "F"]
REQUIRED = ["Ca", "Mg", "Na", "K", "HCO3", "Cl", "SO4"]
CO3_MAX_BELOW_PH83 = 10.0

COLUMNS_FRONT = ["obs_id", "year", "season", "state_raw", "district_raw", "block_raw", "location_raw",
                 "state", "state_now", "state_code", "district_code", "district_name_2011", "district_assign",
                 "district_code_name", "district_match_method", "district_match_score", "district_match_note",
                 "lat", "lon", "lat_raw", "lon_raw", "coord_valid", "coord_in_claimed_district",
                 "coord_district_code", "coord_dist_to_claimed_km", "site_key", "well_id_raw"]
COLUMNS_BACK = ["n_params_measured", "censored", "cbe_pct", "qc_flags"]


def is_censored(s: pd.DataFrame, p: str) -> pd.Series:
    return s["censored"].fillna("").str.contains(rf"(?:^|,){p}(?:<|,|$)", regex=True)


def add_flag(s, mask, flag):
    cur = s.loc[mask, "qc_flags"]
    s.loc[mask, "qc_flags"] = [f"{c},{flag}" if isinstance(c, str) and c else flag for c in cur]


def charge_balance(s):
    meq = {}
    for p in CATIONS + ANIONS:
        v = s[p].copy()
        v[v.isna() & is_censored(s, p)] = 0.0
        if p not in REQUIRED:
            v = v.fillna(0.0)
        meq[p] = v / EQ_WT[p]
    ok = pd.concat([meq[p].notna() for p in REQUIRED], axis=1).all(axis=1)
    cat = sum(meq[p] for p in CATIONS)
    an = sum(meq[p] for p in ANIONS)
    tot = cat + an
    cbe = (100 * (cat - an) / tot).where(ok & (tot > 0))
    return cbe.round(2)


def main():
    S = settings()
    s = read_stations(INTERIM / "stations_spatial.csv")

    s["cbe_pct"] = charge_balance(s)
    add_flag(s, s["cbe_pct"].abs() > S["cbe_flag_pct"], "cbe_high")

    co3_bad = (s["CO3"] > CO3_MAX_BELOW_PH83) & (s["pH"] < 8.3)
    add_flag(s, co3_bad, "co3_implausible")

    has_key = s["site_key"].notna()
    grp = s[has_key].groupby(["site_key", "year", "season"])["obs_id"].transform("size")
    dup = pd.Series(False, index=s.index)
    dup.loc[grp.index] = grp > 1
    add_flag(s, dup, "duplicate_obs")

    pcols = list(params())
    ident = pcols + ["location_raw"]
    copy = dup & s.duplicated(subset=["site_key", "year", "season"] + ident, keep="first")
    add_flag(s, copy, "duplicate_copy")
    out = s[COLUMNS_FRONT + pcols + COLUMNS_BACK]
    PROCESSED.mkdir(parents=True, exist_ok=True)
    out.to_csv(PROCESSED / "stations.csv", index=False)

    summary = report(out, dup, pcols)
    (INTERIM / "t4_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {len(out):,} rows to data/processed/stations.csv; "
          f"CBE computed {summary['cbe_computed']:,}, high {summary['flags'].get('cbe_high', 0):,}; "
          f"co3_implausible {summary['flags'].get('co3_implausible', 0)}; duplicate_obs rows {summary['flags'].get('duplicate_obs', 0):,}")


def base_flags(q):
    return [f.split(":")[0] for f in q.split(",")] if isinstance(q, str) and q else []


def report(s, dup, pcols):
    t1 = json.loads((INTERIM / "t1_summary.json").read_text())
    flags = Counter(f for q in s["qc_flags"] for f in set(base_flags(q)))
    flags["no_measurements"] = sum(r["dropped_no_measurements"] for r in t1["years"].values())
    cbe = s["cbe_pct"].dropna()
    years = sorted(s["year"].unique())

    def table(by):
        rows = {}
        for k, d in s.groupby(by):
            c = Counter(f for q in d["qc_flags"] for f in set(base_flags(q)))
            rows[k] = (len(d), c)
        return rows

    names = sorted(f for f in flags if f != "no_measurements")
    L = ["# QC report (T4)", "", "Generated by `scripts/04_qc.py`. Do not edit. Flags are recorded, never used to delete.", "",
         f"- Rows in the published table: {len(s):,}",
         f"- Rows dropped for having no measurement at all (`no_measurements`, T1): {flags['no_measurements']}", "",
         "## Rows carrying each flag", "", "| Flag | Rows |", "|---|---|"]
    L += [f"| `{f}` | {flags[f]:,} |" for f in names]

    L += ["", "## By year", "", "| Year | Rows | " + " | ".join(f"`{f}`" for f in names) + " |",
          "|---|---|" + "---|" * len(names)]
    for y, (n, c) in table("year").items():
        L.append(f"| {y} | {n:,} | " + " | ".join(f"{c.get(f, 0):,}" for f in names) + " |")
    L += ["", "## By state", "", "| State | Rows | " + " | ".join(f"`{f}`" for f in names) + " |",
          "|---|---|" + "---|" * len(names)]
    for st, (n, c) in table("state").items():
        L.append(f"| {st} | {n:,} | " + " | ".join(f"{c.get(f, 0):,}" for f in names) + " |")

    by_year_cbe = s.groupby("year")["cbe_pct"].agg(lambda v: f"{v.notna().sum():,} / {100 * (v.abs() > 10).sum() / max(v.notna().sum(), 1):.1f}% / {v.abs().median():.1f}")
    L += ["", "## Charge balance", "",
          f"Computed for {len(cbe):,} rows (complete major ions). |CBE| > 10%: {(cbe.abs() > 10).sum():,} "
          f"({100 * (cbe.abs() > 10).mean():.1f}%). Median |CBE|: {cbe.abs().median():.1f}%.", "",
          "| Year | Computed / % above 10 / median abs CBE |", "|---|---|"]
    L += [f"| {y} | {v} |" for y, v in by_year_cbe.items()]

    d = s[dup]
    key = ["site_key", "year", "season"]
    groups = d.groupby(key)
    n_groups = groups.ngroups
    mixed = groups["qc_flags"].agg(lambda q: any("no_major_ions" in str(x) for x in q) and not all("no_major_ions" in str(x) for x in q)).sum()
    identical = groups[pcols].apply(lambda g: (g.nunique(dropna=False) <= 1).all()).sum()
    L += ["", "## Duplicates", "",
          f"{len(d):,} rows in {n_groups:,} groups share a site (coordinates to 3 dp, ~110 m), year and season.",
          f"- Groups pairing a major-ion row with a trace-metal-only row: {mixed:,} (complementary, not repeated measurements)",
          f"- Groups whose rows have identical values in every parameter: {identical:,} (likely the same record entered twice)",
          f"- Rows flagged `duplicate_copy` (second and later identical copies, incl. location name): {int(s['qc_flags'].fillna('').str.contains('duplicate_copy').sum()):,}",
          f"- Other groups: {n_groups - mixed - identical:,} (different values at the same spot: nearby wells or resampling)",
          "", "No row is removed. T5 counts each row as a well; see LIMITATIONS.md."]

    co3 = s[s["qc_flags"].fillna("").str.contains("co3_implausible")]
    L += ["", "## Implausible carbonate", "",
          f"{len(co3)} rows report CO₃ > 10 mg/L at pH < 8.3. By year and state:", "",
          "| Year | State | Rows | Max CO₃ |", "|---|---|---|---|"]
    for (y, st), g in co3.groupby(["year", "state"]):
        L.append(f"| {y} | {st} | {len(g)} | {g['CO3'].max():.0f} |")
    (INTERIM / "qc_report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return {"rows": len(s), "flags": dict(flags), "cbe_computed": int(len(cbe)),
            "cbe_high_pct": round(float(100 * (cbe.abs() > 10).mean()), 2),
            "duplicate_groups": int(n_groups), "duplicate_groups_mixed": int(mixed),
            "duplicate_groups_identical": int(identical)}


if __name__ == "__main__":
    main()
