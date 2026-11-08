# India Groundwater Quality & Monitoring Map

Live site: https://aveersingh.github.io/groundwater-india/

**Where in India is groundwater unsafe to drink, how much of it has anyone actually tested, and who is supposed to act?**

Built from CGWB's full groundwater-quality station tables for 2019–2024, including wells that did *not* exceed a limit. That denominator is what lets this project report exceedance as "x of y monitored wells" and map where nobody has looked.

Status: **T0 (skeleton)**. Pipeline stages are stubs. The build plan is SPEC.md (tasks T0–T9, milestones M0–M7).

## Run it

```bash
make setup      # create .venv and install requirements
make all        # run every stage, then the validation gate (tolerates stages not yet built)
make validate   # the strict publish gate used in CI before launch
make serve      # preview the site on http://localhost:8000
```

## Layout

- `data/raw/` — the six CGWB CSVs, verbatim, with `SHA256SUMS`.
- `data/processed/` — the published dataset (generated, committed).
- `config/` — parameter limits, thresholds, name maps, authorities.
- `scripts/01–09_*.py` — one script per pipeline stage.
- `site/` — static site served by GitHub Pages.
- `docs/` — method, limitations, data dictionary.

## Licences

Code: MIT (`LICENSE`). Derived data: CC BY 4.0 (`LICENSE-DATA`). Underlying measurements are published by the Central Ground Water Board, Government of India, and are not relicensed here.

Covariate sources (Census HH-6, DGWR, JJM) are committed under `data/external/`. To refresh them, run `make fetch`; it needs network access and is not part of `make all`.
