// map.js: loads the data, draws the three layers, wires the controls.
// The browser computes no statistics (SPEC §3): it only picks a bin for numbers the
// pipeline already published.
(function () {
  "use strict";
  var GW = (window.GW = window.GW || {});
  var DATA = "data/";
  var NA_CODE = "000"; // boundary file's area beyond the Line of Control: outline only

  var state = { layer: "NO3", byCode: {}, layers: {}, selected: null, map: null, wellsOn: false };

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  // ---- bins ---------------------------------------------------------------------------
  // Contamination layers: share of tested wells above the limit, 2024 pre-monsoon.
  var PCT_BINS = [
    { key: "r1", test: function (v) { return v === 0; }, label: "no monitored well above the limit" },
    { key: "r2", test: function (v) { return v > 0 && v <= 10; }, label: "up to 10% of wells above" },
    { key: "r3", test: function (v) { return v > 10 && v <= 25; }, label: "10–25%" },
    { key: "r4", test: function (v) { return v > 25 && v <= 50; }, label: "25–50%" },
    { key: "r5", test: function (v) { return v > 50; }, label: "more than half" },
  ];
  var COV_BINS = [
    { key: "r1", test: function (v) { return v >= 10 && v < 15; }, label: "10–14 wells" },
    { key: "r2", test: function (v) { return v >= 15 && v < 20; }, label: "15–19" },
    { key: "r3", test: function (v) { return v >= 20 && v < 30; }, label: "20–29" },
    { key: "r4", test: function (v) { return v >= 30 && v < 45; }, label: "30–44" },
    { key: "r5", test: function (v) { return v >= 45; }, label: "45 or more" },
  ];
  var HATCH = {
    h45: "3–9 wells: counts in the panel, too few for a share",
    h135: "fewer than 3 wells, or none",
  };

  function binFor(d, layer) {
    if (layer === "coverage") {
      var w = d.coverage.wells_primary;
      if (w < 3) return "h135";
      if (w < 10) return "h45";
      for (var i = 0; i < COV_BINS.length; i++) if (COV_BINS[i].test(w)) return COV_BINS[i].key;
    }
    var h = d.headline[layer];
    if (!h || h.n < 3) return "h135";
    if (h.pct === null || h.pct === undefined) return "h45"; // count_only: never coloured
    for (var j = 0; j < PCT_BINS.length; j++) if (PCT_BINS[j].test(h.pct)) return PCT_BINS[j].key;
    return "h135";
  }

  function fillFor(bin) {
    return bin.charAt(0) === "h" ? "url(#" + bin + ")" : cssVar("--" + bin);
  }

  // Plain-text sentence for the active layer; tooltips escape it, aria-labels use it as is.
  function layerSentence(d) {
    if (state.layer === "coverage") {
      var w = d.coverage.wells_primary;
      return w === 0 ? "No well with nitrate or other major-ion results in the 2024 pre-monsoon round."
        : GW.num(w) + (w === 1 ? " well" : " wells") + " with major-ion results, 2024 pre-monsoon; sampled in " +
          d.coverage.n_years + " of 6 years.";
    }
    return GW.headlineSentence(d.headline[state.layer], state.layer);
  }

  function tooltipText(d) {
    return "<strong>" + GW.esc(GW.place(d)) + "</strong><br>" + GW.esc(layerSentence(d));
  }

  function ariaLabel(d) {
    return GW.place(d) + ". " + layerSentence(d) + " Press Enter for details.";
  }

  // ---- drawing ------------------------------------------------------------------------
  function styleFor(feature) {
    var d = state.byCode[feature.properties.dt_code];
    var sel = state.selected === feature.properties.dt_code;
    return {
      fillColor: d ? fillFor(binFor(d, state.layer)) : cssVar("--na-fill"),
      fillOpacity: 1,
      color: sel ? cssVar("--ink") : cssVar("--district-line"),
      weight: sel ? 2.5 : 0.6,
      opacity: 1,
    };
  }

  function restyle() {
    state.layers.districts.eachLayer(function (l) {
      l.setStyle(styleFor(l.feature));
      var d = state.byCode[l.feature.properties.dt_code];
      var el = l.getElement();
      if (el && d) el.setAttribute("aria-label", ariaLabel(d));
    });
    if (state.layers.na) state.layers.na.setStyle({ fillColor: cssVar("--na-fill"), color: cssVar("--axis") });
    if (state.selected) {
      var s = state.layers.byCode[state.selected];
      if (s) s.bringToFront();
    }
    renderLegend();
    if (state.wellsOn) GW.wells.refresh();
  }

  function addPatterns(map) {
    var svg = map.getPanes().overlayPane.querySelector("svg");
    if (!svg || svg.querySelector("#h45")) return;
    var ns = "http://www.w3.org/2000/svg";
    var defs = document.createElementNS(ns, "defs");
    [["h45", 45], ["h135", 135]].forEach(function (p) {
      var pat = document.createElementNS(ns, "pattern");
      pat.setAttribute("id", p[0]);
      pat.setAttribute("patternUnits", "userSpaceOnUse");
      pat.setAttribute("width", "6");
      pat.setAttribute("height", "6");
      pat.setAttribute("patternTransform", "rotate(" + p[1] + ")");
      pat.innerHTML = '<rect width="6" height="6" style="fill:var(--hatch-bg)"></rect>' +
        '<line x1="0" y1="0" x2="0" y2="6" style="stroke:var(--hatch-ink);stroke-width:1.5"></line>';
      defs.appendChild(pat);
    });
    svg.insertBefore(defs, svg.firstChild);
  }

  function renderLegend() {
    var el = document.getElementById("legend");
    var counts = {};
    Object.keys(state.byCode).forEach(function (c) {
      var b = binFor(state.byCode[c], state.layer);
      counts[b] = (counts[b] || 0) + 1;
    });
    var bins = state.layer === "coverage" ? COV_BINS : PCT_BINS;
    var title = state.layer === "coverage"
      ? "Wells with major-ion results per district, 2024 pre-monsoon"
      : "Share of monitored wells above " + GW.limitPhrase(state.layer) + " for " + GW.PARAM_NAME[state.layer] + ", 2024 pre-monsoon (districts with 10 or more wells)";
    var html = '<span class="legend-title">' + GW.esc(title) + "</span>";
    bins.forEach(function (b) {
      html += '<span class="legend-item"><span class="swatch" style="background:var(--' + b.key + ')"></span>' +
        GW.esc(b.label) + " (" + (counts[b.key] || 0) + ")</span>";
    });
    Object.keys(HATCH).forEach(function (k) {
      html += '<span class="legend-item"><span class="hatch-key ' + k + '"></span>' + GW.esc(HATCH[k]) +
        " (" + (counts[k] || 0) + ")</span>";
    });
    el.innerHTML = html;
  }

  // ---- selection ----------------------------------------------------------------------
  function select(code, opts) {
    opts = opts || {};
    var d = state.byCode[code];
    if (!d) return;
    var prev = state.selected;
    state.selected = code;
    if (prev && state.layers.byCode[prev]) state.layers.byCode[prev].setStyle(styleFor(state.layers.byCode[prev].feature));
    var l = state.layers.byCode[code];
    if (l) {
      l.setStyle(styleFor(l.feature));
      l.bringToFront();
      if (opts.zoom) state.map.fitBounds(l.getBounds(), { maxZoom: 8, padding: [24, 24] });
    }
    document.getElementById("district-pick").value = code;
    try { history.replaceState(null, "", "#d" + code); } catch (e) { /* file:// or sandbox */ }
    GW.panel.open(d, { focus: opts.focus });
  }
  GW.select = select;

  GW.deselect = function () {
    var prev = state.selected;
    state.selected = null;
    if (prev && state.layers.byCode[prev]) state.layers.byCode[prev].setStyle(styleFor(state.layers.byCode[prev].feature));
    document.getElementById("district-pick").value = "";
    try { history.replaceState(null, "", location.pathname + location.search); } catch (e) { /* ignore */ }
  };

  // ---- controls -----------------------------------------------------------------------
  function fillPicker(list) {
    var sel = document.getElementById("district-pick");
    var groups = {};
    list.forEach(function (d) { (groups[d.state_now] = groups[d.state_now] || []).push(d); });
    Object.keys(groups).sort().forEach(function (st) {
      var og = document.createElement("optgroup");
      og.label = st;
      groups[st].sort(function (a, b) { return a.district.localeCompare(b.district); }).forEach(function (d) {
        var o = document.createElement("option");
        o.value = d.dt_code;
        o.textContent = d.district;
        og.appendChild(o);
      });
      sel.appendChild(og);
    });
    sel.addEventListener("change", function () { if (sel.value) select(sel.value, { zoom: true, focus: true }); });
  }

  function wireControls() {
    document.querySelectorAll('input[name="layer"]').forEach(function (r) {
      r.addEventListener("change", function () {
        if (!r.checked) return;
        state.layer = r.value;
        GW.layer = r.value;
        restyle();
        if (state.selected) GW.panel.layerChanged(state.layer);
      });
    });
    var t = document.getElementById("wells-toggle");
    t.addEventListener("change", function () { state.wellsOn = t.checked; GW.wells.refresh(); });
  }

  // ---- wells in view ------------------------------------------------------------------
  GW.wells = (function () {
    var cache = {}, group = null, MIN_ZOOM = 7, MAX_DISTRICTS = 40;
    function status(msg) { document.getElementById("map-status").textContent = msg; }

    function inView() {
      var b = state.map.getBounds(), out = [];
      state.layers.districts.eachLayer(function (l) {
        if (b.intersects(l.getBounds())) out.push(l.feature.properties.dt_code);
      });
      return out;
    }

    function draw(codes) {
      group.clearLayers();
      var p = state.layer, L = GW.limits[p], lim = null, shown = 0, above = 0;
      if (L && !L.values_only) lim = p === "EC" ? L.indicator_threshold : (L.permissible !== undefined ? L.permissible : L.acceptable);
      var bounds = state.map.getBounds();
      codes.forEach(function (c) {
        var s = cache[c];
        if (!s || !s.rows) return;
        var ix = {};
        s.columns.forEach(function (k, i) { ix[k] = i; });
        s.rows.forEach(function (r) {
          if (r[ix.year] !== 2024 || r[ix.season] !== "pre") return;
          var ll = [r[ix.lat], r[ix.lon]];
          if (!bounds.contains(ll)) return;
          var pv = p === "coverage" ? null : r[ix[p]];
          var bdl = (r[ix.bdl] || "").split(";").indexOf(p) >= 0;
          if (p !== "coverage" && pv === null && !bdl) return; // not tested for this parameter
          var isAbove = lim !== null && pv !== null && pv > lim;
          shown++;
          if (isAbove) above++;
          var m = L_.circleMarker(ll, {
            radius: 4, weight: 1.5, color: cssVar("--well-above"), opacity: 1,
            fillColor: isAbove ? cssVar("--well-above") : cssVar("--well-below"), fillOpacity: 1,
          });
          var label = GW.esc(r[ix.location] || "Monitoring well");
          if (p !== "coverage") {
            label += "<br>" + GW.esc(GW.PARAM_NAME[p]) + ": " + (bdl ? "below detection" : GW.num(pv, 2) + " " + L.unit) +
              (isAbove ? " (above " + GW.esc(GW.limitPhrase(p)) + ")" : "");
          }
          m.bindTooltip(label);
          group.addLayer(m);
        });
      });
      if (p === "coverage") status("Showing " + GW.num(shown) + " wells sampled in the 2024 pre-monsoon round in this view.");
      else status("Showing " + GW.num(shown) + " wells tested for " + GW.PARAM_NAME[p] + " in this view, 2024 pre-monsoon. Filled: above " +
        GW.limitPhrase(p) + " (" + GW.num(above) + ").");
    }

    function refresh() {
      if (!group) group = L_.layerGroup().addTo(state.map);
      if (!state.wellsOn) { group.clearLayers(); status(""); return; }
      if (state.map.getZoom() < MIN_ZOOM) { group.clearLayers(); status("Zoom in closer to see individual wells."); return; }
      var codes = inView();
      if (codes.length > MAX_DISTRICTS) { group.clearLayers(); status("Zoom in closer to see individual wells."); return; }
      var need = codes.filter(function (c) { return !cache[c] && state.byCode[c]; });
      if (!need.length) { draw(codes); return; }
      status("Loading wells…");
      Promise.all(need.map(function (c) {
        return fetch(DATA + "s/" + c + ".json").then(function (r) { return r.json(); })
          .then(function (j) { cache[c] = j; }).catch(function () { cache[c] = { rows: [] }; });
      })).then(function () { if (state.wellsOn) draw(codes); });
    }
    return { refresh: refresh };
  })();

  // ---- boot ---------------------------------------------------------------------------
  var L_ = window.L;

  function boot(topo, dj) {
    GW.limits = dj.limits;
    GW.labels = dj.labels;
    // browsers restore form controls on reload/back: start from what the controls show
    var checked = document.querySelector('input[name="layer"]:checked');
    if (checked) state.layer = checked.value;
    state.wellsOn = document.getElementById("wells-toggle").checked;
    GW.layer = state.layer;
    dj.districts.forEach(function (d) { state.byCode[d.dt_code] = d; });

    var map = (state.map = L_.map("map", {
      zoomSnap: 0.25, minZoom: 4, maxZoom: 11, attributionControl: true, preferCanvas: false,
      keyboard: true, scrollWheelZoom: true,
    }));
    map.attributionControl.setPrefix(false);
    map.attributionControl.addAttribution("Boundaries: DataMeet India community, CC BY 4.0");

    var fc = topojson.feature(topo, topo.objects[Object.keys(topo.objects)[0]]);
    var na = { type: "FeatureCollection", features: fc.features.filter(function (f) { return f.properties.dt_code === NA_CODE; }) };
    var ds = { type: "FeatureCollection", features: fc.features.filter(function (f) { return f.properties.dt_code !== NA_CODE; }) };

    // Set the view before adding layers: Leaflet creates the SVG (and each path element)
    // only once the map has a view, and the patterns and keyboard wiring need them.
    var b = L_.geoJSON(ds).getBounds();
    map.fitBounds(b, { padding: [8, 8] });
    map.setMaxBounds(b.pad(0.4));

    state.layers.byCode = {};
    state.layers.na = L_.geoJSON(na, {
      interactive: false,
      style: function () { return { fillColor: cssVar("--na-fill"), fillOpacity: 1, color: cssVar("--axis"), weight: 0.6, dashArray: "3 3" }; },
    }).addTo(map);
    state.layers.districts = L_.geoJSON(ds, {
      style: styleFor,
      onEachFeature: function (f, layer) {
        var code = f.properties.dt_code;
        state.layers.byCode[code] = layer;
        layer.bindTooltip(function () { return tooltipText(state.byCode[code]); }, { sticky: true, direction: "top", offset: [0, -8] });
        layer.on("click", function () { select(code, { focus: false }); });
      },
    }).addTo(map);
    addPatterns(map);

    // keyboard: every district is a focusable button
    state.layers.districts.eachLayer(function (l) {
      var el = l.getElement(), code = l.feature.properties.dt_code, d = state.byCode[code];
      if (!el || !d) return;
      el.setAttribute("tabindex", "0");
      el.setAttribute("role", "button");
      el.setAttribute("class", (el.getAttribute("class") || "") + " district");
      el.setAttribute("aria-label", ariaLabel(d));
      el.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); select(code, { focus: true }); }
      });
      el.addEventListener("focus", function () { l.openTooltip(l.getBounds().getCenter()); });
      el.addEventListener("blur", function () { l.closeTooltip(); });
    });

    map.on("moveend", function () { if (state.wellsOn) GW.wells.refresh(); });

    renderLegend();
    fillPicker(dj.districts);
    wireControls();

    var mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
    if (mq && mq.addEventListener) mq.addEventListener("change", function () { restyle(); GW.chart.redraw(); });

    var m = /^#d(\d{3})$/.exec(location.hash);
    if (m && state.byCode[m[1]]) select(m[1], { zoom: true, focus: false });
  }

  function fail(err) {
    document.getElementById("map-status").textContent = "The map could not load. The national figures on this page still apply; the data are on the downloads page.";
    if (window.console) console.error(err);
  }

  function getJSON(u) { return fetch(u).then(function (r) { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); }); }

  if (!L_ || !window.topojson || !window.fetch) { fail(new Error("missing Leaflet/topojson/fetch")); return; }
  Promise.all([getJSON(DATA + "geo/districts.topo.json"), getJSON(DATA + "districts.json")])
    .then(function (r) { boot(r[0], r[1]); })
    .catch(fail);
  getJSON(DATA + "national.json").then(function (n) { GW.chart.draw(document.getElementById("trend-chart"), n.trend); })
    .catch(function (e) { if (window.console) console.error(e); });
})();
