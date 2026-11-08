// panel.js: the district panel (SPEC §8.3). Order matters: denominator first.
(function () {
  "use strict";
  var GW = (window.GW = window.GW || {});
  var DATA = "data/";
  var PANEL_PARAMS = ["NO3", "F", "EC", "Cl", "SO4", "Fe", "As", "U"];
  var cache = {}, current = null, season = "pre";

  function el() { return document.getElementById("panel"); }
  function label(p) { var L = GW.labels && GW.labels[p]; return L ? L.label : p; }
  function unit(p) { var L = GW.labels && GW.labels[p]; return L && L.unit ? L.unit : ""; }

  function header(d) {
    var c = d.coverage, s = "";
    s += '<button type="button" class="close" aria-label="Close district details">Close</button>';
    s += "<h2>" + GW.esc(d.district) + "</h2>";
    s += '<p class="sub">' + GW.esc(d.state_now) +
      (d.state_now !== d.state ? " · " + GW.esc(d.state) + " in the 2011 boundaries" : "") + "</p>";
    var w = c.wells_2024, yrs = c.n_years;
    var line = yrs === 0 ? "No well sampled here in any year, 2019–2024."
      : (w === 0 ? "No monitored well in 2024" : "<strong>" + GW.num(w) + "</strong> monitored " + (w === 1 ? "well" : "wells") + " in 2024") +
        "; sampled in " + yrs + " of 6 years.";
    s += '<p class="denom">' + line + "</p>";
    return s;
  }

  function rowsFor(det, p, yr, se) {
    var t = det.params && det.params[p];
    if (!t) return null;
    var ix = {};
    t.columns.forEach(function (k, i) { ix[k] = i; });
    for (var i = 0; i < t.rows.length; i++) {
      var r = t.rows[i];
      if (r[ix.year] === yr && r[ix.season] === se) {
        var o = {};
        t.columns.forEach(function (k, j) { o[k] = r[j]; });
        return o;
      }
    }
    return null;
  }

  function xofy(x, n) { return x === null || x === undefined ? "–" : GW.num(x) + " of " + GW.num(n); }

  function paramTable(det) {
    var s = '<div class="season-switch" role="group" aria-label="2024 round">' +
      '<button type="button" data-season="pre" aria-pressed="' + (season === "pre") + '">Pre-monsoon 2024</button> ' +
      '<button type="button" data-season="post" aria-pressed="' + (season === "post") + '">Post-monsoon 2024</button></div>';
    s += '<div class="table-wrap"><table class="ptable"><thead><tr><th scope="col">Parameter</th><th scope="col">Wells tested</th>' +
      '<th scope="col">Above acceptable</th><th scope="col">Above permissible</th><th scope="col">Median / max</th></tr></thead><tbody>';
    PANEL_PARAMS.forEach(function (p) {
      var L = GW.limits[p] || {};
      var r = rowsFor(det, p, 2024, season);
      var name = GW.esc(p === "EC" ? "EC" : label(p)) + (unit(p) ? ' <span class="unit">' + GW.esc(unit(p)) + "</span>" : "");
      var cls = p === GW.layer ? ' class="current"' : "";
      if (!r || !r.n) {
        s += "<tr" + cls + '><th scope="row">' + name + '</th><td class="na" colspan="4">not tested in this round</td></tr>';
        return;
      }
      var cells;
      if (L.values_only) {
        cells = '<td class="na" colspan="2">values only: limit not yet verified</td>';
      } else if (p === "EC") {
        cells = '<td colspan="2">' + xofy(r.n_above_indicator, r.n) + ' <span class="unit">above the indicator threshold</span></td>';
      } else {
        cells = "<td>" + xofy(r.n_above_acceptable, r.n) + "</td><td>" + xofy(r.n_above_permissible, r.n) + "</td>";
      }
      s += "<tr" + cls + '><th scope="row">' + name + "</th><td>" + GW.num(r.n) + "</td>" + cells +
        "<td>" + GW.num(r.median, 2) + ' <span class="na">/</span> ' + GW.num(r.max, 2) + "</td></tr>";
    });
    s += "</tbody></table></div>";
    s += '<p class="note">Wells tested includes results below detection. Limits are IS 10500:2012 acceptable and permissible limits; ' +
      "where the standard allows no relaxation the two columns are the same. " +
      (GW.limits.SO4 && GW.limits.SO4.permissible_condition ? "Sulphate permissible limit: " + GW.esc(GW.limits.SO4.permissible_condition.toLowerCase()) + ". " : "") +
      "EC: wells above " + GW.esc(GW.limitPhrase("EC")) + ".</p>";
    return s;
  }

  function persistence(det) {
    var keys = Object.keys(det.persistence || {});
    if (!keys.length) return "";
    var s = "<h3>Year after year</h3><ul>";
    keys.forEach(function (p) {
      var x = det.persistence[p], what = p === "EC" ? "above the EC indicator threshold" : "above the " + label(p).toLowerCase() + " limit";
      var txt;
      if (x.years_above === x.years_measured) txt = "At least one well " + what + " in every year measured (" + x.years_measured + " pre-monsoon rounds).";
      else if (x.years_above === 0) txt = "No monitored well " + what + " in any of the " + x.years_measured + " pre-monsoon rounds measured.";
      else txt = "At least one well " + what + " in " + x.years_above + " of " + x.years_measured + " pre-monsoon rounds measured.";
      s += "<li><strong>" + GW.esc(label(p)) + ":</strong> " + GW.esc(txt) + "</li>";
    });
    s += '</ul><p class="note">' + GW.esc(det.rules.persistence) + "</p>";
    return s;
  }

  function seasons(det) {
    var keys = Object.keys(det.season_2024 || {});
    if (!keys.length) return "";
    var s = "<h3>Before and after the 2024 monsoon</h3><ul>";
    keys.forEach(function (p) {
      var x = det.season_2024[p], sign = x.delta > 0 ? "+" : "";
      var ab = p === "EC" ? " wells above the indicator threshold before the monsoon, " : " wells above the limit before the monsoon, ";
      s += "<li><strong>" + GW.esc(label(p)) + ":</strong> " + GW.pct(x.pre_pct) + " of " + GW.num(x.pre_n) + ab + GW.pct(x.post_pct) + " of " + GW.num(x.post_n) + " after (" + sign + GW.num(x.delta, 1) + " points).</li>";
    });
    s += '</ul><p class="note">' + GW.esc(det.rules.season_2024) + "</p>";
    return s;
  }

  function context(det) {
    var c = det.context || {}, items = [];
    if (c.pct_hh_untreated_groundwater !== null && c.pct_hh_untreated_groundwater !== undefined)
      items.push(GW.pct(c.pct_hh_untreated_groundwater) + " of households drank untreated groundwater (handpump, tubewell or well) in " + c.hh_source_year + " <span class=\"na\">(Census 2011)</span>.");
    if (c.gw_extraction_stage_pct !== null && c.gw_extraction_stage_pct !== undefined) {
      var t = "Groundwater extraction was " + GW.pct(c.gw_extraction_stage_pct) + " of the annual extractable resource";
      if (c.gw_units) t += "; of " + GW.num(c.gw_units.total) + " assessment units, " + GW.num(c.gw_units.over_exploited) + " over-exploited, " +
        GW.num(c.gw_units.critical) + " critical, " + GW.num(c.gw_units.semi_critical) + " semi-critical, " + GW.num(c.gw_units.safe) + " safe" +
        (c.gw_units.saline ? ", " + GW.num(c.gw_units.saline) + " saline" : "");
      items.push(t + ' <span class="na">(CGWB assessment, 2024' + (c.gw_apportioned ? "; built from districts that straddle 2011 boundaries" : "") + ")</span>.");
    } else if (c.gw_note) {
      items.push("Groundwater extraction: " + GW.esc(c.gw_note) + ' <span class="na">(CGWB, 2024)</span>.');
    } else {
      items.push('Groundwater extraction: not assessed here <span class="na">(CGWB, 2024)</span>.');
    }
    if (c.jjm_fhtc_pct !== null && c.jjm_fhtc_pct !== undefined)
      items.push(GW.pct(c.jjm_fhtc_pct) + " of rural households have a household tap connection " +
        '<span class="na">(' + GW.esc(c.jjm_as_of) + "; a connection says nothing about water quality)</span>.");
    if (!items.length) return "";
    return "<h3>Context</h3><ul><li>" + items.join("</li><li>") + "</li></ul>" +
      '<p class="note">Context is shown beside the well results, not combined with them: the wells are a monitoring network, not a sample of what people drink.</p>';
  }

  function authorities(det) {
    var a = det.authorities || [];
    if (!a.length) return '<h3>Who is responsible</h3><p class="note">The list of agencies and their mandates for this district is being compiled.</p>';
    return "<h3>Who is responsible</h3><ul>" + a.map(function (k) { return "<li>" + GW.esc(k) + "</li>"; }).join("") + "</ul>";
  }

  function downloads(d) {
    var c = d.dt_code;
    return '<h3>Download</h3><p><a href="' + DATA + "dl/" + c + '.csv" download>District table (CSV)</a> · <a href="' + DATA + "d/" + c +
      '.json" download>Everything shown here (JSON)</a> · <a href="' + DATA + "s/" + c + '.json" download>Wells (JSON)</a></p>';
  }

  function never(det) {
    var n = (det.coverage && det.coverage.params_never_tested) || [];
    if (!n.length) return "";
    return "<h3>Never tested here, 2019–2024</h3><p>" + n.map(function (p) { return GW.esc(label(p)); }).join(", ") + '.</p><p class="note">Some parameters were only reported in some years; see the method page.</p>';
  }

  function render(d, det) {
    var s = header(d);
    if (!det) { el().innerHTML = s + '<p class="note">Loading district details…</p>'; return; }
    s += "<h3>2024 results</h3>" + paramTable(det) + persistence(det) + seasons(det) + context(det) + authorities(det) + downloads(d) + never(det);
    el().innerHTML = s;
    el().querySelectorAll(".season-switch button").forEach(function (b) {
      b.addEventListener("click", function () { season = b.getAttribute("data-season"); render(d, det); el().querySelector('[data-season="' + season + '"]').focus(); });
    });
    bindClose();
  }

  function bindClose() {
    var b = el().querySelector(".close");
    if (b) b.addEventListener("click", function () { GW.panel.close(); });
  }

  GW.panel = {
    open: function (d, opts) {
      current = d;
      render(d, cache[d.dt_code]);
      bindClose();
      if (opts && opts.focus) el().focus();
      if (cache[d.dt_code]) return;
      fetch(DATA + "d/" + d.dt_code + ".json").then(function (r) { return r.json(); }).then(function (det) {
        cache[d.dt_code] = det;
        if (current && current.dt_code === d.dt_code) render(d, det);
      }).catch(function () {
        if (current && current.dt_code === d.dt_code) el().insertAdjacentHTML("beforeend", '<p class="note">District details could not load.</p>');
      });
    },
    layerChanged: function () { if (current && cache[current.dt_code]) render(current, cache[current.dt_code]); },
    close: function () {
      current = null;
      el().innerHTML = '<div class="panel-empty"><h2>Pick a district</h2><p>Click a district, tab to it and press Enter, or use <em>Find a district</em>.</p></div>';
      GW.deselect();
    },
  };
})();
