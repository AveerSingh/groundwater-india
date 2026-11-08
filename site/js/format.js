// format.js: shared wording and number formatting.
// Editorial rules (SPEC §10) live here so every sentence on the page follows them:
// always "x of y wells", never "safe"/"clean", EC is an indicator threshold, not a BIS limit.
(function () {
  "use strict";
  var GW = (window.GW = window.GW || {});

  var nf = new Intl.NumberFormat("en-IN");
  GW.num = function (v, digits) {
    if (v === null || v === undefined) return "–";
    if (digits !== undefined) return Number(v).toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
    return nf.format(v);
  };
  GW.pct = function (v) {
    return v === null || v === undefined ? "–" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + "%";
  };

  GW.esc = function (s) {
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };

  GW.PARAM_NAME = { NO3: "nitrate", F: "fluoride", EC: "EC", Cl: "chloride" };

  // The limit phrase for a parameter, from the limits block written by the pipeline.
  GW.limitPhrase = function (p) {
    var L = GW.limits && GW.limits[p];
    if (!L) return "";
    if (L.values_only) return "values only (limit not yet verified)";
    if (p === "EC") return "the " + GW.num(L.indicator_threshold) + " " + L.unit + " indicator threshold (not a BIS limit)";
    var lim = L.permissible !== undefined ? L.permissible : L.acceptable;
    return "the " + GW.num(lim) + " " + L.unit + " limit";
  };

  // One sentence for a district's headline on one parameter (tooltips, picker, panel).
  GW.headlineSentence = function (h, p) {
    var name = GW.PARAM_NAME[p] || p;
    if (!h || !h.n) return "No well was tested for " + name + " in the 2024 pre-monsoon round.";
    var above = p === "EC" ? h.above_indicator : h.above_permissible;
    var what = p === "EC" ? "above the EC indicator threshold" : "above the " + name + " limit";
    if (h.n < 3) return GW.num(h.n) + (h.n === 1 ? " well" : " wells") + " tested for " + name + ": too few to say anything as a share.";
    if (above === 0) return "No monitored well exceeded the " + (p === "EC" ? "EC indicator threshold" : name + " limit") + " in this round (0 of " + GW.num(h.n) + ").";
    var s = GW.num(above) + " of " + GW.num(h.n) + " monitored wells " + what;
    if (h.pct !== null && h.pct !== undefined) s += " (" + GW.pct(h.pct) + ")";
    else s += " (too few wells for a percentage)";
    return s + ".";
  };

  GW.place = function (d) {
    var s = d.district + ", " + d.state_now;
    return s;
  };
})();
