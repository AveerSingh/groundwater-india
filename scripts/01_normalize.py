"""T1 normalize: six CGWB CSVs to one schema.

Writes:
  data/interim/stations_raw.csv   SPEC §5.1 minus district codes and spatial-join fields
  data/interim/t1_summary.json    counts used by tests and by 04_qc's report
  data/interim/t1_report.md       human-readable record of every coercion

Value parsing (per cell, case-insensitive, whitespace-collapsed):
  number                      -> value
  number with a typo          -> value, flag value_repaired:<param>
                                 (internal spaces "8 .20", repeated dots "7..85")
  below detection             -> null, recorded in `censored` as <param> or <param><dl>
                                 (BDL, ND, nil, traces, "<0.1")
  missing / not analysed      -> null ("-", NA, N.A., #REF!, leaked, ...)
  anything else               -> null, flag unparsed:<param>
Then negatives -> null + neg_value:<param>; above plausibility_max -> null + extreme_value:<param>.

Rows are dropped only when no parameter has any reported result (number or
below-detection). Rows with no major-ion values (mostly trace-metal-only) are kept and
flagged no_major_ions (see docs/LIMITATIONS.md).
"""
from __future__ import annotations

import json
import re
from collections import Counter

import numpy as np
import pandas as pd

from gwlib import INTERIM, params, raw_path, resolve_columns, settings

NUM = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")
CENSORED_LT = re.compile(r"^<\s*([-+]?(\d+\.?\d*|\.\d+))$")
BDL_TOKENS = {"bdl", "nd", "nil", "traces", "trace", "below detection limit", "bdl."}
MISSING_TOKENS = {"", "-", "--", "na", "n a", "n.a.", "n.a", "nan", "#ref!", "…", "...",
                  "leaked", "leak", "sample leaked", "mple not received", "sample not received",
                  "─", "#n/a", "#######"}  # last three: spreadsheet placeholders
# Core major ions: a row with none of these is flagged no_major_ions (SPEC §2.1 counts these as empty).
CORE = ["pH", "EC", "Cl", "SO4", "Ca", "Mg", "Na", "K", "HCO3", "TH"]


def classify(raw: str):
    """Return (kind, value, detection_limit). kind in num|repaired|bdl|missing|unparsed."""
    s = re.sub(r"\s+", " ", str(raw)).strip()
    low = s.lower()
    if low in MISSING_TOKENS:
        return "missing", np.nan, None
    if NUM.match(s):
        return "num", float(s), None
    if low in BDL_TOKENS:
        return "bdl", np.nan, None
    m = CENSORED_LT.match(s)
    if m:
        return "bdl", np.nan, m.group(1)
    fixed = re.sub(r"\.{2,}", ".", s.replace(" ", ""))
    if NUM.match(fixed):
        return "repaired", float(fixed), None
    return "unparsed", np.nan, None


def normalise_year(year: int, P: dict, S: dict, report: dict) -> pd.DataFrame:
    df = pd.read_csv(raw_path(year), encoding=S["raw_files"]["encoding"], dtype=str, keep_default_na=False)
    n_raw = len(df)
    expected = S["expected_rows"][year]
    if n_raw != expected:
        raise SystemExit(f"{year}: {n_raw} raw rows, expected {expected} (SPEC §2.1)")

    pcols = resolve_columns(df.columns, P, year)
    mcols = resolve_columns(df.columns, S["meta_columns"], year)
    used = {k: c for k, c in pcols.items() if c is not None and year in P[k]["years"]}
    unconfigured = {k: c for k, c in pcols.items() if c is not None and year not in P[k]["years"]}

    out = pd.DataFrame(index=df.index)
    out["year"] = year
    if mcols.get("season"):
        smap = S["season_values"]
        seas = df[mcols["season"]].str.strip().str.lower().map(smap)
        if seas.isna().any():
            bad = sorted(df.loc[seas.isna(), mcols["season"]].unique())
            raise SystemExit(f"{year}: unknown season values {bad}")
        out["season"] = seas
    else:
        out["season"] = "pre"
    out.insert(0, "obs_id", [f"{year}-{s}-{i}" for s, i in zip(out["season"], df.index)])

    for key in ("state", "district", "block", "location"):
        out[f"{key}_raw"] = df[mcols[key]].str.strip() if mcols.get(key) else None

    lat = pd.to_numeric(df[mcols["lat"]].str.strip(), errors="coerce")
    lon = pd.to_numeric(df[mcols["lon"]].str.strip(), errors="coerce")
    b = S["coord_bounds"]
    valid = lat.between(b["lat_min"], b["lat_max"]) & lon.between(b["lon_min"], b["lon_max"])
    out["lat"], out["lon"], out["coord_valid"] = lat, lon, valid
    d = S["site_key_decimals"]
    out["site_key"] = np.where(valid, lat.round(d).map(lambda v: f"{v:.{d}f}") + "," + lon.round(d).map(lambda v: f"{v:.{d}f}"), None)
    out["well_id_raw"] = df[mcols["well_id"]].str.strip().replace("", None) if mcols.get("well_id") else None

    flags = [[] for _ in range(n_raw)]
    censored = [[] for _ in range(n_raw)]
    reported = pd.DataFrame(False, index=df.index, columns=list(used))
    yr = report.setdefault("by_param", {})
    tokens = Counter()

    for key in P:
        if key not in used:
            out[key] = np.nan
            continue
        col = df[used[key]]
        cache = {u: classify(u) for u in col.unique()}
        kinds = col.map(lambda u: cache[u][0])
        vals = col.map(lambda u: cache[u][1]).astype(float)
        reported[key] = kinds.isin(["num", "repaired", "bdl"])

        for i in np.flatnonzero(kinds.eq("bdl").to_numpy()):
            dl = cache[col.iat[i]][2]
            censored[i].append(f"{key}<{dl}" if dl else key)
        for kind, flag in (("repaired", "value_repaired"), ("unparsed", "unparsed")):
            for i in np.flatnonzero(kinds.eq(kind).to_numpy()):
                flags[i].append(f"{flag}:{key}")
                tokens[(key, kind, col.iat[i].strip())] += 1

        neg = vals < 0
        pmax = P[key].get("plausibility_max")
        ext = vals > pmax if pmax is not None else pd.Series(False, index=vals.index)
        for i in np.flatnonzero(neg.to_numpy()):
            flags[i].append(f"neg_value:{key}")
        for i in np.flatnonzero(ext.to_numpy()):
            flags[i].append(f"extreme_value:{key}")
        vals = vals.mask(neg | ext)
        out[key] = vals

        k = kinds.value_counts().to_dict()
        yr.setdefault(key, {})[str(year)] = {
            "numeric": int(k.get("num", 0) + k.get("repaired", 0)),
            "repaired": int(k.get("repaired", 0)),
            "below_detection": int(k.get("bdl", 0)),
            "missing": int(k.get("missing", 0)),
            "unparsed": int(k.get("unparsed", 0)),
            "negative_nulled": int(neg.sum()),
            "extreme_nulled": int(ext.sum()),
            "non_null_after_qc": int(vals.notna().sum()),
        }

    out["n_params_measured"] = reported.sum(axis=1).astype(int)
    core_cols = [c for c in CORE if c in reported]
    no_core = ~reported[core_cols].any(axis=1)
    empty = out["n_params_measured"].eq(0)
    no_majors = no_core & ~empty

    for i in np.flatnonzero(no_majors.to_numpy()):
        flags[i].append("no_major_ions")
    for i in np.flatnonzero((~valid).to_numpy()):
        flags[i].append("coord_invalid")
    out["censored"] = [",".join(c) or None for c in censored]
    out["qc_flags"] = [",".join(f) or None for f in flags]

    report.setdefault("years", {})[str(year)] = {
        "raw_rows": n_raw,
        "raw_rows_by_season": {k: int(v) for k, v in out["season"].value_counts().items()},
        "no_core_ion_rows": int(no_core.sum()),
        "dropped_no_measurements": int(empty.sum()),
        "kept_no_major_ions": int(no_majors.sum()),
        "kept_rows": int((~empty).sum()),
        "coord_invalid": int((~valid).sum()),
        "coord_missing": int((lat.isna() | lon.isna()).sum()),
        "columns_present_not_configured": {k: c for k, c in unconfigured.items()},
        "columns_used": used,
    }
    report.setdefault("tokens", []).extend(
        {"year": year, "param": p, "kind": kd, "token": t, "count": n} for (p, kd, t), n in sorted(tokens.items())
    )
    return out[~empty]


def write_report(report: dict, path):
    L = ["# T1 normalisation report", "", "Generated by `scripts/01_normalize.py`. Do not edit.", "",
         "## Rows", "",
         "| Year | Raw | No core-ion values | Dropped (nothing reported) | Kept, no major ions | Kept | Coord invalid | Coord missing |",
         "|---|---|---|---|---|---|---|---|"]
    for y, r in report["years"].items():
        L.append(f"| {y} | {r['raw_rows']:,} | {r['no_core_ion_rows']:,} | {r['dropped_no_measurements']:,} | "
                 f"{r['kept_no_major_ions']:,} | {r['kept_rows']:,} | {r['coord_invalid']:,} | {r['coord_missing']:,} |")
    L += ["", "## Columns present in the raw file but not configured for that year", ""]
    for y, r in report["years"].items():
        for k, c in r["columns_present_not_configured"].items():
            L.append(f"- {y}: `{c!r}` resolved as {k}, ignored")
    L += ["", "## Values per parameter and year", "",
          "numeric / below-detection / repaired / unparsed / negative nulled / extreme nulled", ""]
    L += ["| Param | " + " | ".join(report["years"]) + " |", "|---|" + "---|" * len(report["years"])]
    for p, by in report["by_param"].items():
        cells = []
        for y in report["years"]:
            c = by.get(y)
            cells.append("—" if c is None else
                         f"{c['numeric']:,} / {c['below_detection']} / {c['repaired']} / {c['unparsed']} / "
                         f"{c['negative_nulled']} / {c['extreme_nulled']}")
        L.append(f"| {p} | " + " | ".join(cells) + " |")
    L += ["", "## Repaired and unparsed tokens", "", "| Year | Param | Kind | Raw token | Count |", "|---|---|---|---|---|"]
    for t in report["tokens"]:
        L.append(f"| {t['year']} | {t['param']} | {t['kind']} | `{t['token']}` | {t['count']} |")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main():
    P, S = params(), settings()
    report: dict = {}
    frames = [normalise_year(y, P, S, report) for y in S["raw_files"]["years"]]
    st = pd.concat(frames, ignore_index=True)
    INTERIM.mkdir(parents=True, exist_ok=True)
    st.to_csv(INTERIM / "stations_raw.csv", index=False)
    (INTERIM / "t1_summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_report(report, INTERIM / "t1_report.md")
    for y, r in report["years"].items():
        print(f"{y}: raw {r['raw_rows']:>6,}  kept {r['kept_rows']:>6,}  dropped {r['dropped_no_measurements']:>4}  "
              f"no-majors {r['kept_no_major_ions']:>5}  coord-invalid {r['coord_invalid']}")
    print(f"wrote {len(st):,} rows to data/interim/stations_raw.csv")


if __name__ == "__main__":
    main()
