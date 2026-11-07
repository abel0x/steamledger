/* SPDX-License-Identifier: Apache-2.0 */
/* Copyright 2026 abel0x <https://github.com/abel0x> */
/*
 * Small chart kit for the site: ranked bars, columns, a time line with a
 * crosshair, a segmented part-to-whole bar and a calendar heatmap. Plain DOM
 * and SVG, no dependencies. Every chart takes text through callbacks, so all
 * labels arrive translated and formatted by the caller, and every value it
 * shows on hover is also reachable from the keyboard and a data table.
 */
(function (root) {
  "use strict";

  var SVG = "http://www.w3.org/2000/svg";
  var mounted = [];

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    setAttrs(node, attrs);
    append(node, children);
    return node;
  }

  function svg(tag, attrs, children) {
    var node = document.createElementNS(SVG, tag);
    setAttrs(node, attrs);
    append(node, children);
    return node;
  }

  function setAttrs(node, attrs) {
    if (!attrs) return;
    Object.keys(attrs).forEach(function (key) {
      var value = attrs[key];
      if (value === null || value === undefined || value === false) return;
      if (key === "text") node.textContent = value;
      else if (key === "class") node.setAttribute("class", value);
      else node.setAttribute(key, value === true ? "" : value);
    });
  }

  function append(node, children) {
    if (children === null || children === undefined || children === false) return;
    if (Array.isArray(children)) {
      children.forEach(function (child) { append(node, child); });
      return;
    }
    node.appendChild(typeof children === "object" ? children : document.createTextNode(String(children)));
  }

  /* ------------------------------------------------------------------ tooltip */

  var tip = null;

  function tooltipNode() {
    if (!tip) tip = document.getElementById("tip");
    return tip;
  }

  function showTip(target, value, label, event) {
    var node = tooltipNode();
    if (!node) return;
    node.textContent = "";
    node.appendChild(el("strong", { text: value }));
    if (label) node.appendChild(el("span", { text: label }));
    node.hidden = false;
    var rect = target.getBoundingClientRect();
    var x = event && event.clientX !== undefined && event.type.indexOf("pointer") === 0 ? event.clientX : rect.left + rect.width / 2;
    var y = event && event.clientY !== undefined && event.type.indexOf("pointer") === 0 ? event.clientY : rect.top;
    var width = node.offsetWidth;
    var height = node.offsetHeight;
    var left = Math.min(window.innerWidth - width - 8, Math.max(8, x - width / 2));
    var top = y - height - 12;
    if (top < 8) top = y + 18;
    node.style.left = left + "px";
    node.style.top = top + "px";
  }

  function hideTip() {
    var node = tooltipNode();
    if (node) node.hidden = true;
  }

  function hover(node, value, label) {
    node.addEventListener("pointermove", function (event) { showTip(node, value, label, event); });
    node.addEventListener("pointerleave", hideTip);
    node.addEventListener("focus", function (event) { showTip(node, value, label, event); });
    node.addEventListener("blur", hideTip);
  }

  /* ------------------------------------------------------------------ scales */

  function niceMax(value) {
    if (value <= 0) return 1;
    var power = Math.pow(10, Math.floor(Math.log10(value)));
    var steps = [1, 1.25, 2, 2.5, 5, 10];
    for (var i = 0; i < steps.length; i++) {
      if (steps[i] * power >= value) return steps[i] * power;
    }
    return 10 * power;
  }

  /* Smallest round step (1, 2, 2.5, 5 x 10^n) at least `raw`; whole numbers only when `whole`. */
  function niceStep(raw, whole) {
    if (!(raw > 0)) return 1;
    var power = Math.pow(10, Math.floor(Math.log10(raw)));
    var steps = whole && power < 10 ? [1, 2, 5, 10] : [1, 2, 2.5, 5, 10];
    for (var i = 0; i < steps.length; i++) {
      var step = steps[i] * power;
      if (step >= raw) return whole ? Math.max(1, step) : step;
    }
    return 10 * power;
  }

  /*
   * A [base, top] range for a line chart that does not start at zero. Both ends
   * and the midpoint land on round values, so the three tick labels never
   * repeat once they are formatted.
   */
  function niceRange(low, high, whole) {
    var step = niceStep(Math.max(high - low, whole ? 1 : Math.abs(high) * 0.1 || 1) / 2, whole);
    for (;;) {
      var base = Math.max(0, Math.floor(low / step) * step);
      if (high === low && base === low) base = Math.max(0, low - step);
      if (base + 2 * step >= high) return [base, base + 2 * step];
      step = niceStep(step * 1.01, whole);
    }
  }

  /* Top of a count axis whose midpoint is a whole number too: 2, 4, 6, 8, 10, 20, 40... */
  function niceCount(value) {
    if (value <= 2) return 2;
    var power = Math.pow(10, Math.floor(Math.log10(value)));
    var steps = [2, 4, 6, 8, 10];
    for (var i = 0; i < steps.length; i++) {
      if (steps[i] * power >= value) return steps[i] * power;
    }
    return 20 * power;
  }

  /* ------------------------------------------------------------------ data table twin */

  function dataTable(caption, headers, rows) {
    var table = el("table", { class: "data compact" });
    table.appendChild(el("thead", null, el("tr", null, headers.map(function (h, i) {
      return el("th", { class: i ? "num" : null, text: h });
    }))));
    table.appendChild(el("tbody", null, rows.map(function (row) {
      return el("tr", null, row.map(function (cell, i) {
        return el("td", { class: i ? "num" : null, text: cell });
      }));
    })));
    return el("details", { class: "twin" }, [el("summary", { text: caption }), table]);
  }

  /* ------------------------------------------------------------------ ranked bars */

  /*
   * items: [{label, value, href, icon, note}], format(value) -> text.
   * One series, one colour; the value sits at the end of each row.
   */
  function bars(options) {
    var items = options.items || [];
    var max = Math.max.apply(null, items.map(function (i) { return Math.abs(i.value); }).concat([1]));
    var list = el("ol", { class: "bars" + (options.diverging ? " diverging" : "") });
    items.forEach(function (item) {
      var share = Math.abs(item.value) / max * 100;
      var labelChildren = [];
      if (item.icon) labelChildren.push(item.icon);
      labelChildren.push(el("span", { class: "bar-name", text: item.label }));
      var label = item.href ? el("a", { class: "bar-label", href: item.href }, labelChildren) : el("span", { class: "bar-label" }, labelChildren);
      var fill = el("span", { class: "bar-fill" + (item.value < 0 ? " neg" : ""), style: "width:" + share.toFixed(2) + "%" });
      var row = el("li", null, [
        label,
        el("span", { class: "bar-track", "aria-hidden": "true" }, fill),
        el("span", { class: "bar-value", text: options.format(item.value) })
      ]);
      if (item.note) row.title = item.note;
      list.appendChild(row);
    });
    return list;
  }

  /* ------------------------------------------------------------------ columns */

  /*
   * items: [{label, value, tip}], format(value) -> text, axis labels every
   * `every` columns. Each column is focusable and shows its value on hover.
   */
  function columns(options) {
    var items = options.items || [];
    var top = niceCount(Math.max.apply(null, items.map(function (i) { return i.value; }).concat([0])));
    var plot = el("div", { class: "cols-plot", role: "list" });
    var every = options.every || 1;
    items.forEach(function (item, index) {
      var height = top ? item.value / top * 100 : 0;
      var column = el("div", {
        class: "col" + (item.value ? "" : " zero") + (item.current ? " current" : ""),
        role: "listitem",
        tabindex: "0",
        "aria-label": item.tip + ": " + options.format(item.value)
      }, [
        el("span", { class: "col-bar", style: "height:" + height.toFixed(2) + "%" }),
        el("span", { class: "col-label", "aria-hidden": "true", text: index % every === 0 ? item.label : "" })
      ]);
      hover(column, options.format(item.value), item.tip);
      plot.appendChild(column);
    });
    var grid = el("div", { class: "cols-grid", "aria-hidden": "true" }, [
      el("span", { style: "bottom:100%", text: options.axis(top) }),
      el("span", { style: "bottom:50%", text: options.axis(top / 2) }),
      el("span", { style: "bottom:0%", text: options.axis(0) })
    ]);
    var wrap = el("div", { class: "cols", style: "--count:" + items.length }, [grid, plot]);
    var out = el("div", { class: "chart" }, wrap);
    if (options.table) out.appendChild(dataTable(options.table, options.headers, items.map(function (i) { return [i.tip, options.format(i.value)]; })));
    return out;
  }

  /* ------------------------------------------------------------------ segmented bar */

  /*
   * parts: [{key, label, value}] in a fixed order; colours come from CSS
   * classes (seg-<key>) so each part keeps its colour in every chart.
   */
  function segmented(options) {
    var parts = (options.parts || []).filter(function (p) { return p.value > 0; });
    var total = parts.reduce(function (sum, p) { return sum + p.value; }, 0);
    var bar = el("div", { class: "seg", role: "img", "aria-label": options.label });
    var legend = el("ul", { class: "legend" });
    parts.forEach(function (part) {
      var share = total ? part.value / total : 0;
      var block = el("span", {
        class: "seg-part seg-" + part.key,
        style: "flex-grow:" + part.value,
        tabindex: "0",
        "aria-label": part.label + ": " + options.format(part.value) + ", " + options.percent(share)
      });
      if (share >= 0.09) block.appendChild(el("span", { class: "seg-text", text: options.percent(share) }));
      hover(block, options.format(part.value) + " (" + options.percent(share) + ")", part.label);
      bar.appendChild(block);
      legend.appendChild(el("li", null, [
        el("span", { class: "key seg-" + part.key, "aria-hidden": "true" }),
        el("span", { text: part.label }),
        el("span", { class: "legend-value", text: options.format(part.value) })
      ]));
    });
    if (!parts.length) return el("p", { class: "muted", text: options.empty });
    return el("div", { class: "chart" }, [bar, legend]);
  }

  /* ------------------------------------------------------------------ line over time */

  /*
   * points: [{t: Date, v: number, label}] sorted by time. `unit` is how many
   * raw units make one axis unit (60 for minutes shown as hours), so the axis
   * rounds in the units it prints. Drawn on mount so it can use the real
   * width; redrawn on resize.
   */
  function line(options) {
    var points = options.points || [];
    var box = el("div", { class: "line", tabindex: "0", role: "img", "aria-label": options.label });
    var out = el("div", { class: "chart" }, box);
    if (options.table) {
      out.appendChild(dataTable(options.table, options.headers, points.map(function (p) { return [p.label, options.format(p.v)]; })));
    }
    var active = points.length - 1;

    function draw() {
      box.textContent = "";
      var width = Math.max(220, box.clientWidth || 600);
      var height = options.height || 180;
      var pad = { top: 14, right: 16, bottom: 26, left: 52 };
      var w = width - pad.left - pad.right;
      var h = height - pad.top - pad.bottom;
      if (!points.length) return;
      var t0 = points[0].t.getTime();
      var t1 = points[points.length - 1].t.getTime();
      var span = Math.max(1, t1 - t0);
      var values = points.map(function (p) { return p.v; });
      var low = Math.min.apply(null, values);
      var high = Math.max.apply(null, values);
      var whole = values.every(function (v) { return Math.round(v) === v; });
      var unit = options.unit || 1;
      var range = options.zero ? [0, niceMax(high / unit)] : niceRange(low / unit, high / unit, whole);
      var base = range[0] * unit;
      var top = range[1] * unit;
      function x(p) { return pad.left + (points.length === 1 ? w : (p.t.getTime() - t0) / span * w); }
      function y(v) { return pad.top + h - (v - base) / (top - base) * h; }

      var chart = svg("svg", { width: width, height: height, viewBox: "0 0 " + width + " " + height, "aria-hidden": "true" });
      [0, 0.5, 1].forEach(function (f) {
        var value = base + (top - base) * f;
        var yy = y(value);
        chart.appendChild(svg("line", { class: "grid", x1: pad.left, x2: width - pad.right, y1: yy, y2: yy }));
        chart.appendChild(svg("text", { class: "tick", x: pad.left - 8, y: yy + 4, "text-anchor": "end", text: options.axis(value) }));
      });
      var first = points[0];
      var last = points[points.length - 1];
      chart.appendChild(svg("text", { class: "tick", x: pad.left, y: height - 6, "text-anchor": "start", text: options.xlabel(first.t) }));
      if (points.length > 1) {
        chart.appendChild(svg("text", { class: "tick", x: width - pad.right, y: height - 6, "text-anchor": "end", text: options.xlabel(last.t) }));
      }
      var path = points.map(function (p, i) { return (i ? "L" : "M") + x(p).toFixed(1) + " " + y(p.v).toFixed(1); }).join(" ");
      if (points.length > 1) {
        var area = path + " L" + x(last).toFixed(1) + " " + (pad.top + h) + " L" + x(first).toFixed(1) + " " + (pad.top + h) + " Z";
        chart.appendChild(svg("path", { class: "area", d: area }));
        chart.appendChild(svg("path", { class: "stroke", d: path }));
      }
      var cross = svg("line", { class: "cross", y1: pad.top, y2: pad.top + h, visibility: "hidden" });
      var dot = svg("circle", { class: "dot", r: 4.5, cx: x(last), cy: y(last.v) });
      chart.appendChild(cross);
      chart.appendChild(dot);
      box.appendChild(chart);

      function focusPoint(index, event) {
        active = Math.max(0, Math.min(points.length - 1, index));
        var p = points[active];
        cross.setAttribute("x1", x(p));
        cross.setAttribute("x2", x(p));
        cross.setAttribute("visibility", "visible");
        dot.setAttribute("cx", x(p));
        dot.setAttribute("cy", y(p.v));
        showTip(box, options.format(p.v), p.label, event);
      }
      box.onpointermove = function (event) {
        var rect = chart.getBoundingClientRect();
        var px = event.clientX - rect.left;
        var best = 0;
        points.forEach(function (p, i) {
          if (Math.abs(x(p) - px) < Math.abs(x(points[best]) - px)) best = i;
        });
        focusPoint(best, event);
      };
      box.onpointerleave = function () {
        cross.setAttribute("visibility", "hidden");
        dot.setAttribute("cx", x(last));
        dot.setAttribute("cy", y(last.v));
        hideTip();
      };
      box.onkeydown = function (event) {
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
          event.preventDefault();
          focusPoint(active + (event.key === "ArrowLeft" ? -1 : 1), event);
        }
      };
      box.onfocus = function (event) { focusPoint(active, event); };
      box.onblur = box.onpointerleave;
    }

    mounted.push(draw);
    out.draw = draw;
    return out;
  }

  /* ------------------------------------------------------------------ calendar heatmap */

  /*
   * counts: {"YYYY-MM-DD": n}, end: Date, weeks: number, firstDay: 0 (Sunday)
   * or 1 (Monday). Five bins on one hue; empty days use the hairline colour.
   * Cells grow to fill the width (9-16px) and the newest week sits on the right;
   * on narrow screens the grid scrolls and starts scrolled to the end.
   */
  function calendar(options) {
    var counts = options.counts || {};
    var weeks = options.weeks || 53;
    var end = new Date(options.end.getFullYear(), options.end.getMonth(), options.end.getDate());
    var offset = (end.getDay() - options.firstDay + 7) % 7;
    var start = new Date(end);
    start.setDate(end.getDate() - offset - (weeks - 1) * 7);
    var left = 32;
    var topPad = 16;
    var gap = 3;
    var scroller = el("div", { class: "scroll-x calendar" });

    function draw() {
      scroller.textContent = "";
      var room = scroller.clientWidth || 720;
      var size = Math.max(9, Math.min(16, Math.floor((room - left) / weeks) - gap));
      var step = size + gap;
      var width = left + weeks * step;
      var height = topPad + 7 * step;
      var chart = svg("svg", { width: width, height: height, viewBox: "0 0 " + width + " " + height, role: "group", "aria-label": options.label });
      var lastMonth = -1;
      var day = new Date(start);
      for (var col = 0; col < weeks; col++) {
        for (var row = 0; row < 7; row++) {
          if (day > end) break;
          var key = day.getFullYear() + "-" + String(day.getMonth() + 1).padStart(2, "0") + "-" + String(day.getDate()).padStart(2, "0");
          var count = counts[key] || 0;
          var bin = count === 0 ? 0 : count === 1 ? 1 : count <= 3 ? 2 : count <= 7 ? 3 : 4;
          var cell = svg("rect", {
            class: "heat heat-" + bin,
            x: left + col * step,
            y: topPad + row * step,
            width: size,
            height: size,
            rx: 2,
            tabindex: count ? "0" : null,
            role: count ? "img" : null,
            "aria-label": count ? options.cellLabel(new Date(day), count) : null,
            "aria-hidden": count ? null : "true"
          });
          hover(cell, options.countLabel(count), options.dayLabel(new Date(day)));
          chart.appendChild(cell);
          if (row === 0 && day.getMonth() !== lastMonth && day.getDate() <= 7) {
            lastMonth = day.getMonth();
            chart.appendChild(svg("text", { class: "tick", x: left + col * step, y: 10, "aria-hidden": "true", text: options.monthLabel(new Date(day)) }));
          }
          day.setDate(day.getDate() + 1);
        }
      }
      [1, 3, 5].forEach(function (row) {
        var labelDay = new Date(start);
        labelDay.setDate(start.getDate() + row);
        chart.appendChild(svg("text", { class: "tick", x: 0, y: topPad + row * step + size - 2, "aria-hidden": "true", text: options.weekdayLabel(labelDay) }));
      });
      scroller.appendChild(chart);
      scroller.scrollLeft = scroller.scrollWidth;
    }

    var scale = el("div", { class: "heat-scale", "aria-hidden": "true" }, [
      el("span", { text: options.less }),
      [0, 1, 2, 3, 4].map(function (bin) { return el("span", { class: "heat-key heat-" + bin }); }),
      el("span", { text: options.more })
    ]);
    mounted.push(draw);
    return el("div", { class: "chart" }, [scroller, scale]);
  }

  /* ------------------------------------------------------------------ small pieces */

  function meter(percent, label) {
    var value = Math.max(0, Math.min(100, percent || 0));
    return el("span", { class: "meter", role: "img", "aria-label": label || "" },
      el("span", { class: "meter-fill" + (value >= 100 ? " full" : ""), style: "width:" + value.toFixed(1) + "%" }));
  }

  function redrawAll() {
    mounted = mounted.filter(function (draw) {
      try { draw(); return true; } catch (e) { return false; }
    });
  }

  var resizeTimer = null;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(redrawAll, 120);
  });

  root.SteamCharts = {
    bars: bars,
    columns: columns,
    segmented: segmented,
    line: line,
    calendar: calendar,
    meter: meter,
    hover: hover,
    hideTip: hideTip,
    reset: function () { mounted = []; hideTip(); },
    drawMounted: redrawAll
  };
})(window);
