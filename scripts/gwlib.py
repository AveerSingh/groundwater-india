"""Shared helpers for the pipeline stages: paths, config loading, column resolution."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
SITE_DATA = ROOT / "site" / "data"
DOCS = ROOT / "docs"


def load_yaml(name: str):
    with open(CONFIG / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def params() -> dict:
    return load_yaml("params.yml")


def settings() -> dict:
    return load_yaml("settings.yml")


LIMIT_KEYS = ("acceptable", "permissible", "indicator_threshold")


def states_limit(p: dict) -> bool:
    return any(p.get(k) is not None for k in LIMIT_KEYS)


def compares_to_limit(p: dict) -> bool:
    """True when outputs may count or label wells against this parameter's limit.

    Every stage that computes n_above_*, pct_above_*, persistence or any
    limit wording must check this first.
    """
    return states_limit(p) and p.get("compare_to_limit", True) is not False


def unverified_compared(all_params: dict) -> list[str]:
    """Parameters whose limit would be shown to readers without being verified."""
    return [k for k, p in all_params.items() if compares_to_limit(p) and p.get("verified") is not True]


def raw_path(year: int) -> Path:
    return ROOT / settings()["raw_files"]["pattern"].format(year=year)


def normalise_colname(name: str) -> str:
    """Collapse all whitespace (including embedded newlines) to single spaces."""
    return re.sub(r"\s+", " ", str(name)).strip()


class ColumnResolutionError(Exception):
    pass


def resolve_columns(columns, specs: dict, year: int) -> dict:
    """Map each spec key to exactly one raw column name for `year`.

    `specs` is {key: {"column_regex": ..., "years": [...]}}. Keys whose `years`
    include `year` must match exactly one column; zero or several matches is a
    hard failure. Keys not configured for `year` are resolved if present and
    reported, but never required.
    Returns {key: raw_column_name_or_None}.
    """
    normed = {c: normalise_colname(c) for c in columns}
    out, errors = {}, []
    for key, spec in specs.items():
        rx = re.compile(spec["column_regex"], re.IGNORECASE)
        hits = [raw for raw, n in normed.items() if rx.match(n)]
        required = year in spec.get("years", [])
        if len(hits) > 1:
            errors.append(f"{year} {key}: regex {spec['column_regex']!r} matched several columns {hits}")
        elif not hits and required:
            errors.append(f"{year} {key}: no column matches {spec['column_regex']!r}")
        out[key] = hits[0] if len(hits) == 1 else None
    if errors:
        raise ColumnResolutionError("\n".join(errors))
    return out


def stub(task: str, outputs: list[str] | None = None) -> None:
    """Placeholder used until a stage is implemented. Prints and exits cleanly."""
    print(f"[stub] {task}: not implemented yet" + (f" (will write {', '.join(outputs)})" if outputs else ""))


# Columns that are identifiers, not numbers: always read as text so codes keep
# their leading zeros ("031", not 31.0).
TEXT_COLUMNS = ["obs_id", "state_raw", "district_raw", "block_raw", "location_raw", "well_id_raw",
                "state", "state_now", "state_code", "district_code", "district_code_name",
                "coord_district_code", "district_name_2011", "district_match_method",
                "district_match_note", "district_assign", "site_key", "censored", "qc_flags"]


def read_stations(path):
    import pandas as pd
    head = pd.read_csv(path, nrows=0).columns
    return pd.read_csv(path, low_memory=False, dtype={c: str for c in TEXT_COLUMNS if c in head})
