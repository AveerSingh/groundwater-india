"""Download the three T7 covariate sources into data/external/ (run by hand, not by `make all`).

  census_hh6/  Census 2011 Table HH-6 (HL-06), one .xls per state, from the ORGI NADA catalogue
  dgwr/        CGWB Dynamic Ground Water Resources, district-wise, from the ESRI India Living
               Atlas layer "District Wise Dynamic Ground Water Resources 2025" (holds 2022-2025).
               The layer goes to dgwr/raw/ (git-ignored: its licence is unstated); only CGWB's
               figures and the derived 2011 area weights are committed.
  jjm/         Jal Jeevan Mission district tap connections, from the JJM dashboard's own
               district-map request (live figures, saved with the retrieval date)

Every file is written with a SHA256SUMS entry so the pipeline is reproducible offline.
Uses curl (system certificate store); Python's own store is not configured on every machine.

  python scripts/fetch_covariates.py [census|dgwr|jjm ...]
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.parse

from gwlib import DATA, load_yaml

EXT = DATA / "external"
UA = "Mozilla/5.0 (groundwater-india research pipeline)"

CENSUS_CATALOG = range(8445, 8480)     # HL-06 by state, 35 entries (8444 is the India total)
NADA = "https://censusindia.gov.in/nada/index.php/catalog"

DGWR_LAYER = ("https://livingatlas.esri.in/server1/rest/services/Water/"
              "Dynamic_Ground_Water_Resource_Estimation/MapServer/0/query")
DGWR_FIELDS = ("objectid,uid,district,state,lgd_dist,totno24,safeno24,semcrino24,crino24,"
               "ovrexpno24,salno24,totgwrec24,exgwres24,totgwex24,gwexstg24")

JJM_PAGE = "https://ejalshakti.gov.in/jjmreport/JJMIndia.aspx"
# The dashboard files reorganised states under new codes, and returns nothing for their 2011
# codes: 36 Telangana, 37 Andhra Pradesh, 38 Ladakh, 39 Dadra & Nagar Haveli and Daman & Diu.
JJM_NEW_STATES = ["36", "37", "38", "39"]


def curl(url, out=None, data=None, headers=(), cookies=None, remote_name=False, cwd=None):
    cmd = ["curl", "-sS", "--fail", "-m", "300", "-A", UA]
    for h in headers:
        cmd += ["-H", h]
    if cookies:
        cmd += ["-b", str(cookies), "-c", str(cookies)]
    if data is not None:
        cmd += ["-d", data]
    if remote_name:
        cmd += ["-OJ"]
    elif out:
        cmd += ["-o", str(out)]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, text=not (out or remote_name), cwd=cwd, check=True)
    return r.stdout


def write_sums(folder):
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}"
             for p in sorted(folder.iterdir()) if p.is_file() and p.name not in ("SHA256SUMS", "SOURCE.txt")]
    (folder / "SHA256SUMS").write_text("\n".join(lines) + "\n")


def census():
    d = EXT / "census_hh6"
    d.mkdir(parents=True, exist_ok=True)
    for cid in CENSUS_CATALOG:
        page = curl(f"{NADA}/{cid}/related-materials")
        m = re.search(rf"{NADA}/{cid}/download/\d+", page)
        if not m:
            raise SystemExit(f"no download link on catalogue entry {cid}")
        curl(m.group(0), remote_name=True, cwd=d)
        time.sleep(1)
    write_sums(d)


def dgwr():
    """Download the layer into dgwr/raw/ (git-ignored), then write the committed tables:
    CGWB's figures without shapes, and current-to-2011 district area weights."""
    import importlib.util
    d = EXT / "dgwr"
    (d / "raw").mkdir(parents=True, exist_ok=True)
    q = urllib.parse.urlencode({"where": "1=1", "outFields": DGWR_FIELDS, "returnGeometry": "true",
                                "outSR": "4326", "maxAllowableOffset": "0.002", "f": "geojson"})
    curl(f"{DGWR_LAYER}?{q}", out=d / "raw" / "dgwr_districts_2024.geojson")
    spec = importlib.util.spec_from_file_location("cov7", DATA.parent / "scripts" / "07_covariates.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.build_dgwr_tables()
    write_sums(d)


def _jjm_enc(s, n=1):
    """The dashboard's own parameter encoding (encodeTxt in JJM_Dashboard.js, encN = 1)."""
    s = urllib.parse.quote(s, safe="@*_+-./")
    return urllib.parse.quote("".join(chr(ord(c) + n) for c in s), safe="@*_+-./") + str(n)


def jjm():
    """One request per 2011 state, so every row carries its state (StCode11)."""
    d = EXT / "jjm"
    d.mkdir(parents=True, exist_ok=True)
    jar = d / ".cookies"
    curl(JJM_PAGE, cookies=jar)
    rows = []
    for st in sorted(load_yaml("population_2011.yml")["by_state"]) + JJM_NEW_STATES:
        body = json.dumps({"StCode11": _jjm_enc(st), "Cat": _jjm_enc("0"), "SubCat": _jjm_enc("0"),
                           "Param": _jjm_enc("1")})
        r = json.loads(curl(f"{JJM_PAGE}/BindDistrictMap", data=body, cookies=jar,
                            headers=["Content-Type: application/json; charset=utf-8"]))["d"]
        rows += [{**x, "StCode11": st} for x in r]
        time.sleep(1)
    jar.unlink(missing_ok=True)
    out = d / f"jjm_districts_{dt.date.today().isoformat()}.json"
    out.write_text(json.dumps({"d": rows}, ensure_ascii=False, indent=0), encoding="utf-8")
    write_sums(d)


if __name__ == "__main__":
    todo = sys.argv[1:] or ["census", "dgwr", "jjm"]
    for name in todo:
        print(f"fetching {name} ...")
        {"census": census, "dgwr": dgwr, "jjm": jjm}[name]()
