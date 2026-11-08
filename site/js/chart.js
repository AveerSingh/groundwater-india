// chart.js: the national trend (SPEC §8.4). One axis (% of tested wells above the limit),
// four series in fixed categorical order, legend + direct end labels, crosshair tooltip.
(function () {
  "use strict";
  var GW = (window.GW = window.GW || {});
  var ORDER = ["NO3", "F", "EC", "Cl"];
  var NAMES = { NO3: "Nitrate", F: "Fluoride", EC: "EC (indicator)", Cl: "Chloride" };
  var SHORT = { NO3: "Nitrate", F: "Fluoride", EC: "EC", Cl: "Chloride" };
  var last = null;

  function draw(host, trend) {
    last = { host: host, trend: trend };
    var params = trend.params, keys = ORDER.filter(function (k) { return params[k]; });
    var years = params[keys[0]].series.map(function (r) { return r.year; });
    // drawn at the container's real width so text stays at its CSS size on phones
    var W = Math.max(300, Math.min(744, (host.clientWidth || 720) - 16)), H = W < 480 ? 240 : 300;
    var m = { t: 12, r: 104, b: 28, l: 40 };
    var iw = W - m.l - m.r, ih = H - m.t - m.b;
    var max = 0;
    keys.forEach(function (k) { params[k].series.forEach(function (r) { if (r.pct > max) max = r.pct; }); });
    var top = Math.ceil(max / 5) * 5 || 5;
    var x = function (y) { return m.l + (iw * (y - years[0])) / (years[years.length - 1] - years[0]); };
    var y = function (v) { return m.t + ih - (ih * v) / top; };
    var s = '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Line chart: national share of monitored wells above the limit, pre-monsoon, 2019 to 2024. The same values are in the table below.">';
    for (var g = 0; g <= top; g += 5) {
      s += '<line class="grid" x1="' + m.l + '" x2="' + (m.l + iw) + '" y1="' + y(g) + '" y2="' + y(g) + '"></line>';
      s += '<text class="tick" x="' + (m.l - 6) + '" y="' + (y(g) + 4) + '" text-anchor="end">' + g + "%</text>";
    }
    s += '<line class="axis" x1="' + m.l + '" x2="' + (m.l + iw) + '" y1="' + y(0) + '" y2="' + y(0) + '"></line>';
    years.forEach(function (yr) {
      s += '<text class="tick" x="' + x(yr) + '" y="' + (H - 8) + '" text-anchor="middle">' + yr + "</text>";
    });
    // end labels: nudge apart so they never collide
    var ends = keys.map(function (k, i) {
      var ser = params[k].series, v = ser[ser.length - 1].pct;
      return { k: k, i: i, v: v, ly: y(v) };
    }).sort(function (a, b) { return a.ly - b.ly; });
    for (var e = 1; e < ends.length; e++) if (ends[e].ly - ends[e - 1].ly < 14) ends[e].ly = ends[e - 1].ly + 14;
    keys.forEach(function (k, i) {
      var col = "var(--s" + (i + 1) + ")";
      var pts = params[k].series.filter(function (r) { return r.pct !== null; });
      s += '<path class="series" style="stroke:' + col + '" d="' + pts.map(function (r, j) { return (j ? "L" : "M") + x(r.year) + "," + y(r.pct); }).join("") + '"></path>';
      pts.forEach(function (r) { s += '<circle class="dot" r="4" style="fill:' + col + '" cx="' + x(r.year) + '" cy="' + y(r.pct) + '"></circle>'; });
    });
    ends.forEach(function (en) {
      s += '<text class="lab" x="' + (m.l + iw + 8) + '" y="' + (en.ly + 4) + '">' + SHORT[en.k] + " " + GW.pct(en.v) + "</text>";
    });
    s += '<line class="cross" id="trend-cross" x1="0" x2="0" y1="' + m.t + '" y2="' + (m.t + ih) + '" style="display:none"></line>';
    s += '<rect id="trend-hit" x="' + m.l + '" y="' + m.t + '" width="' + iw + '" height="' + ih + '" fill="transparent" tabindex="0" aria-label="Chart values: use the left and right arrow keys to step through years"></rect>';
    s += "</svg>";
    var legend = '<div class="chart-legend" aria-hidden="true">' + keys.map(function (k, i) {
      return '<span><i style="background:var(--s' + (i + 1) + ')"></i>' + NAMES[k] + "</span>";
    }).join("") + "</div>";
    host.innerHTML = legend + s + '<div class="chart-tip" role="status"></div>';

    var svg = host.querySelector("svg"), hit = host.querySelector("#trend-hit"), cross = host.querySelector("#trend-cross");
    var tip = host.querySelector(".chart-tip"), idx = -1;
    function show(j) {
      idx = Math.max(0, Math.min(years.length - 1, j));
      var yr = years[idx], cx = x(yr);
      cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.style.display = "";
      var rows = keys.map(function (k, i) {
        var r = params[k].series[idx];
        return '<div><i style="background:var(--s' + (i + 1) + ')"></i>' + NAMES[k] + ": " + GW.pct(r.pct) +
          " <span style=\"color:var(--muted)\">(" + GW.num(r.above) + " of " + GW.num(r.n) + ")</span></div>";
      }).join("");
      tip.innerHTML = "<strong>" + yr + " pre-monsoon</strong>" + rows;
      tip.style.display = "block";
      var box = svg.getBoundingClientRect(), hb = host.getBoundingClientRect();
      var px = (cx / W) * box.width + (box.left - hb.left);
      var left = px + 12, tw = tip.offsetWidth;
      if (left + tw > hb.width - 4) left = px - tw - 12;
      tip.style.left = Math.max(4, left) + "px";
      tip.style.top = (box.top - hb.top + 8) + "px";
    }
    function hide() { cross.style.display = "none"; tip.style.display = "none"; }
    function nearest(ev) {
      var box = svg.getBoundingClientRect(), vx = ((ev.clientX - box.left) / box.width) * W;
      var best = 0;
      years.forEach(function (yr, j) { if (Math.abs(x(yr) - vx) < Math.abs(x(years[best]) - vx)) best = j; });
      return best;
    }
    hit.addEventListener("pointermove", function (ev) { show(nearest(ev)); });
    hit.addEventListener("pointerleave", hide);
    hit.addEventListener("focus", function () { show(idx < 0 ? years.length - 1 : idx); });
    hit.addEventListener("blur", hide);
    hit.addEventListener("keydown", function (ev) {
      if (ev.key === "ArrowRight") { ev.preventDefault(); show(idx + 1); }
      if (ev.key === "ArrowLeft") { ev.preventDefault(); show(idx - 1); }
      if (ev.key === "Escape") hide();
    });
  }

  var rt = null;
  window.addEventListener("resize", function () {
    clearTimeout(rt);
    rt = setTimeout(function () { if (last) draw(last.host, last.trend); }, 150);
  });

  GW.chart = {
    draw: draw,
    redraw: function () { if (last) draw(last.host, last.trend); },
  };
})();
