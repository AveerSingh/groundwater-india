PY ?= .venv/bin/python
export PYTHONPATH := scripts

.PHONY: all fetch setup normalize reconcile spatial qc aggregate coverage covariates export validate validate-dev test checksums serve clean

# `make all` runs every stage. While stages are stubs, validation tolerates
# checks whose inputs do not exist yet; it never tolerates a failed check.
all: normalize reconcile spatial qc aggregate coverage covariates export validate-dev

setup:      ; python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

normalize:  ; $(PY) scripts/01_normalize.py
reconcile:  ; $(PY) scripts/02_reconcile_names.py
spatial:    ; $(PY) scripts/03_spatial_join.py
qc:         ; $(PY) scripts/04_qc.py
aggregate:  ; $(PY) scripts/05_aggregate.py
coverage:   ; $(PY) scripts/06_coverage.py
covariates: ; $(PY) scripts/07_covariates.py
export:     ; $(PY) scripts/08_export.py

# The publish gate (CI): every check must pass, nothing pending.
validate:     checksums ; $(PY) scripts/09_validate.py && $(PY) -m pytest -q
validate-dev: checksums ; $(PY) scripts/09_validate.py --allow-pending && $(PY) -m pytest -q
test:       ; $(PY) -m pytest -q

checksums:  ; for d in data/raw data/external/*/; do (cd $$d && shasum -a 256 -c SHA256SUMS --quiet) || exit 1; done
# downloads T7 covariate sources into data/external/ (network; not part of `all`)
fetch:      ; $(PY) scripts/fetch_covariates.py
serve:      ; $(PY) -m http.server 8000 --directory site
clean:      ; rm -rf data/interim/* site/data/*
