"""M3 site tests: the page is self-contained, its static text matches the data, and its
wording follows the editorial rules (SPEC §8.6, §10)."""
import base64
import hashlib
import json
import re
import shutil
import subprocess

import pytest

from gwlib import ROOT, SITE_DATA

SITE = ROOT / "site"
PAGES = sorted(SITE.glob("*.html"))
SCRIPTS = sorted((SITE / "js").glob("*.js"))


def text_of(paths):
    return {p.name: p.read_text(encoding="utf-8") for p in paths}


def test_static_numbers_match_national_json():
    nat = json.loads((SITE_DATA / "national.json").read_text())
    html = (SITE / "index.html").read_text(encoding="utf-8")
    marks = re.findall(r"<!--n:([\w.]+)-->(.*?)<!--/n-->", html, flags=re.S)
    assert len(marks) >= 6
    for path, shown in marks:
        v = nat
        for k in path.split("."):
            v = v[k]
        if isinstance(v, str):
            assert shown == v.replace("&", "&amp;"), path
        else:
            assert shown.replace(",", "") == str(v), path


def test_static_trend_table_matches_national_json():
    nat = json.loads((SITE_DATA / "national.json").read_text())["trend"]["params"]
    html = (SITE / "index.html").read_text(encoding="utf-8")
    body = re.search(r"<!--trend-rows-->(.*?)<!--/trend-rows-->", html, flags=re.S)[1]
    rows = re.findall(r"<tr><th scope=\"row\">(\d{4})</th>(.*?)</tr>", body)
    assert [int(y) for y, _ in rows] == [r["year"] for r in nat["NO3"]["series"]]
    for y, cells in rows:
        got = re.findall(r"<td>([\d.]+)%</td>", cells)
        want = [f"{next(r for r in nat[p]['series'] if r['year'] == int(y))['pct']:.1f}" for p in nat]
        assert got == want, y


def test_no_external_resources():
    """Everything load-bearing is vendored (SPEC §8.6): no CDN, no tiles, no fonts."""
    for name, t in text_of(PAGES).items():
        loaded = re.findall(r'<(?:script|img|iframe)[^>]*\ssrc="([^"]+)"', t) + re.findall(r'<link[^>]*\shref="([^"]+)"', t)
        for ref in loaded:
            assert not re.match(r"(https?:)?//", ref), f"{name} loads {ref}"
            assert (SITE / ref.split("#")[0]).exists(), f"{name}: missing {ref}"
        for ref in re.findall(r'<a[^>]*\shref="([^"]+)"', t):              # links may go out; local ones must exist
            if not re.match(r"(https?:)?//|#|mailto:", ref):
                assert (SITE / ref.split("#")[0]).exists(), f"{name}: broken link {ref}"
    for name, t in text_of(SCRIPTS + [SITE / "css" / "app.css"]).items():
        urls = [u for u in re.findall(r"https?://[^\s'\")]+", t) if "www.w3.org/2000/svg" not in u]
        assert not urls, f"{name}: {urls}"


def test_vendored_files_match_recorded_hashes():
    src = (SITE / "vendor" / "SOURCE.txt").read_text()
    recorded = re.findall(r"(\S+\.(?:js|css))\s+sha256-(\S+)=", src)
    assert len(recorded) == 2
    for fname, b64 in recorded:
        f = SITE / "vendor" / "leaflet-1.9.4" / fname
        assert base64.b64encode(hashlib.sha256(f.read_bytes()).digest()).decode().rstrip("=") == b64, fname


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("js", SCRIPTS, ids=lambda p: p.name)
def test_javascript_parses(js):
    r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


FORBIDDEN = [
    r"\bsafe to drink\b", r"\bclean\b", r"\bpeople affected\b", r"\bpopulation exposed\b",
    r"\bEC limit\b", r"\bBIS limit for EC\b",
]


def test_editorial_wording():
    """SPEC §10: no verdicts, no people-affected figures, EC never called a BIS limit."""
    for name, t in text_of(PAGES + SCRIPTS).items():
        t = re.sub(r"/\*.*?\*/|<!--.*?-->", " ", t, flags=re.S)       # comments state the rules
        t = re.sub(r"^\s*//.*$", " ", t, flags=re.M)
        for pat in FORBIDDEN:
            assert not re.search(pat, t, flags=re.I), f"{name}: {pat}"


def test_page_states_what_the_wells_are():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert "not household taps" in html                       # SPEC §8.1, line under the map
    assert "What this map cannot tell you" in html              # SPEC §10.5
