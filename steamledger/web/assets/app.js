/* SPDX-License-Identifier: Apache-2.0 */
/* Copyright 2026 abel0x <https://github.com/abel0x> */
/*
 * The site. Every page reads one snapshot (the newest unless ?at= names
 * another), so the whole archive can be browsed as it was on any recorded
 * date. Data arrives as <script> files because browsers block fetch() on
 * pages opened from disk; nothing here needs a network connection.
 */
(function () {
  "use strict";

  var INDEX = window.STEAMLEDGER_INDEX || { snapshots: [], series: {}, names: {}, apps: [] };
  var I18N = window.STEAMLEDGER_I18N || {};
  var C = window.SteamCharts;
  var LANGS = Object.keys(I18N);
  var SNAPSHOTS = INDEX.snapshots || [];
  var APP_SET = {};
  (INDEX.apps || []).forEach(function (appid) { APP_SET[appid] = true; });

  var L = {};
  var renderToken = 0;
  var lastView = null;

  /* ================================================================== storage */

  function load(key) {
    try { return window.localStorage.getItem("steamledger." + key); } catch (e) { return null; }
  }

  function save(key, value) {
    try { window.localStorage.setItem("steamledger." + key, value); } catch (e) { /* private mode */ }
  }

  /* ================================================================== i18n */

  function pickLanguage() {
    var stored = load("lang");
    if (stored && I18N[stored]) return stored;
    var wanted = (navigator.languages || [navigator.language || "en"]);
    for (var i = 0; i < wanted.length; i++) {
      var code = String(wanted[i] || "").toLowerCase().split("-")[0];
      if (I18N[code]) return code;
    }
    return I18N.en ? "en" : LANGS[0];
  }

  function setLanguage(code) {
    var bundle = I18N[code] || I18N.en || { strings: {}, locale: "en", name: "English" };
    var locale = bundle.locale || code || "en";
    L = {
      code: code,
      locale: locale,
      strings: bundle.strings || {},
      fallback: (I18N.en || bundle).strings || {},
      plural: new Intl.PluralRules(locale),
      int: new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }),
      dec1: new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
      pct: new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }),
      pct0: new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }),
      compact: new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 }),
      date: new Intl.DateTimeFormat(locale, { year: "numeric", month: "short", day: "numeric" }),
      dateTime: new Intl.DateTimeFormat(locale, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }),
      month: new Intl.DateTimeFormat(locale, { month: "short" }),
      monthYear: new Intl.DateTimeFormat(locale, { month: "long", year: "numeric" }),
      weekday: new Intl.DateTimeFormat(locale, { weekday: "short" }),
      regions: typeof Intl.DisplayNames === "function" ? new Intl.DisplayNames([locale], { type: "region" }) : null,
      collator: new Intl.Collator(locale, { sensitivity: "base", numeric: true })
    };
    document.documentElement.lang = locale;
    save("lang", code);
  }

  function t(key, params) {
    var value = L.strings[key];
    if (value === undefined || value === null) value = L.fallback[key];
    if (value === undefined || value === null) return key;
    params = params || {};
    if (typeof value === "object") {
      var n = Number(params.count);
      value = value[L.plural.select(isFinite(n) ? n : 0)] || value.other;
    }
    return String(value).replace(/\{(\w+)\}/g, function (match, name) {
      if (params[name] === undefined || params[name] === null) return match;
      if (name === "count" && typeof params[name] === "number") return L.int.format(params[name]);
      return String(params[name]);
    });
  }

  function has(key) {
    return L.strings[key] !== undefined || L.fallback[key] !== undefined;
  }

  /* ================================================================== formatting */

  function num(value) { return L.int.format(value || 0); }

  function hours(minutes) {
    minutes = minutes || 0;
    if (minutes < 60) return t("units.minutes", { count: minutes });
    return t("units.hours", { value: L.dec1.format(minutes / 60) });
  }

  function hoursAxis(minutes) {
    var h = minutes / 60;
    return h >= 10000 ? L.compact.format(h) : L.int.format(h);
  }

  function signedHours(minutes) {
    return (minutes < 0 ? "−" : "+") + hours(Math.abs(minutes));
  }

  function signed(value) {
    return (value < 0 ? "−" : "+") + num(Math.abs(value));
  }

  function percent(value) { return L.pct.format((value || 0) / 100); }

  function stamp(seconds) { return seconds ? new Date(seconds * 1000) : null; }

  function date(seconds) {
    var d = stamp(seconds);
    return d ? L.date.format(d) : "";
  }

  function dateTime(value) {
    if (!value) return "";
    var d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
    return isNaN(d) ? "" : L.dateTime.format(d);
  }

  function snapshotDate(entry) { return dateTime(entry.collected_at); }

  function duration(fromSeconds, toDate) {
    if (!fromSeconds) return "";
    var days = Math.max(0, (toDate.getTime() / 1000 - fromSeconds) / 86400);
    if (days >= 365) return t("units.years", { count: Math.floor(days / 365.25) });
    if (days >= 31) return t("units.months", { count: Math.floor(days / 30.44) });
    return t("units.days", { count: Math.floor(days) });
  }

  function country(code) {
    if (!code) return "";
    try { return (L.regions && L.regions.of(code)) || code; } catch (e) { return code; }
  }

  function fold(text) {
    return String(text || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/ı/g, "i").toLowerCase();
  }

  function dayKey(d) {
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }

  /* ================================================================== DOM */

  function h(tag, attrs) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        var value = attrs[key];
        if (value === null || value === undefined || value === false) return;
        if (key === "class") node.className = value;
        else if (key === "text") node.textContent = value;
        else if (key.indexOf("on") === 0) node.addEventListener(key.slice(2), value);
        else node.setAttribute(key, value === true ? "" : value);
      });
    }
    for (var i = 2; i < arguments.length; i++) add(node, arguments[i]);
    return node;
  }

  function add(node, child) {
    if (child === null || child === undefined || child === false) return;
    if (Array.isArray(child)) { child.forEach(function (c) { add(node, c); }); return; }
    node.appendChild(typeof child === "object" ? child : document.createTextNode(String(child)));
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  function image(src, size, cls, alt) {
    var holder = h("span", { class: "ph " + (cls || ""), style: "width:" + size + "px;height:" + size + "px", "aria-hidden": "true" });
    if (!src) return holder;
    var node = h("img", { src: src, width: size, height: size, alt: alt || "", loading: "lazy", decoding: "async", class: cls || null });
    node.addEventListener("error", function () { if (node.parentNode) node.parentNode.replaceChild(holder, node); });
    return node;
  }

  function section(title, note) {
    var head = h("div", { class: "section-head" }, h("h2", { text: title }), note ? h("p", { class: "note", text: note }) : null);
    return h("section", { class: "block" }, head);
  }

  function empty(text, hint) {
    return h("div", { class: "empty" }, h("p", { text: text }), hint ? h("p", { class: "muted", text: hint }) : null);
  }

  function facts(items) {
    return h("dl", { class: "facts" }, items.filter(Boolean).map(function (item) {
      return h("div", { class: "fact" },
        h("dt", { text: item.label }),
        h("dd", null, item.value, item.note ? h("span", { class: "fact-note", text: item.note }) : null));
    }));
  }

  function chip(text, cls) { return h("span", { class: "chip" + (cls ? " " + cls : ""), text: text }); }

  function levelRing(level, big) {
    if (level === null || level === undefined) return h("span", { class: "level none", text: "–" });
    var tier = Math.floor((level % 100) / 10);
    return h("span", {
      class: "level lvl-" + tier + (level >= 100 ? " lvl-century" : "") + (big ? " big" : ""),
      title: t("web.level", { level: level }),
      text: String(level)
    });
  }

  function sectionNote(snap, name) {
    var status = ((snap.meta.sections || {})[name] || {}).status;
    if (!status || status === "ok" || status === "partial") return null;
    return h("p", { class: "notice", text: t("data.section." + status) });
  }

  /* A long list shows its first rows and a button for the rest. */
  function longList(cls, items, render, initial) {
    var list = h("ul", { class: cls });
    var more = h("button", { type: "button", class: "button more" });
    var shown = 0;
    function fill(count) {
      var fragment = document.createDocumentFragment();
      items.slice(shown, count).forEach(function (item) { fragment.appendChild(render(item)); });
      list.appendChild(fragment);
      shown = Math.min(count, items.length);
      if (shown >= items.length) more.remove();
      else more.textContent = t("web.show_more", { count: Math.min(50, items.length - shown) });
    }
    more.addEventListener("click", function () { fill(shown + 50); });
    fill(initial || 20);
    return h("div", null, list, shown < items.length ? more : null);
  }

  function external(href, text) {
    // Only web addresses become links; anything else (javascript:, data:) stays text.
    if (!/^https?:\/\//i.test(String(href || ""))) return h("span", { text: text });
    return h("a", { href: href, rel: "noopener noreferrer", target: "_blank", text: text });
  }

  /* ================================================================== data */

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var node = document.createElement("script");
      node.src = src;
      node.async = true;
      node.onload = function () { resolve(); };
      node.onerror = function () { reject(new Error(src)); };
      document.head.appendChild(node);
    });
  }

  var pending = {};

  function getSnapshot(id) {
    var cache = window.STEAMLEDGER_SNAPSHOTS || {};
    if (cache[id] && cache[id].__ready) return Promise.resolve(cache[id]);
    if (!pending[id]) {
      pending[id] = loadScript("data/s/" + encodeURIComponent(id) + ".js").then(function () {
        var data = (window.STEAMLEDGER_SNAPSHOTS || {})[id];
        if (!data) throw new Error(id);
        prepare(data);
        return data;
      });
    }
    return pending[id];
  }

  function getApp(appid) {
    var cache = window.STEAMLEDGER_APPS || {};
    if (cache[appid]) return Promise.resolve(cache[appid]);
    if (!APP_SET[appid]) return Promise.resolve(null);
    var key = "app:" + appid;
    if (!pending[key]) {
      pending[key] = loadScript("data/a/" + appid + ".js").then(function () {
        return (window.STEAMLEDGER_APPS || {})[appid] || null;
      }, function () { return null; });
    }
    return pending[key];
  }

  function prepare(snap) {
    snap.games = snap.games || [];
    snap.friends = snap.friends || [];
    snap.badges = snap.badges || [];
    snap.wishlist = snap.wishlist || [];
    snap.recent = snap.recent || [];
    snap.achievements = snap.achievements || {};
    snap.profile = snap.profile || {};
    snap.meta = snap.meta || {};
    snap.when = new Date(snap.meta.collected_at);
    snap.gameMap = {};
    snap.games.forEach(function (g) { snap.gameMap[g.appid] = g; });
    var unlocks = [];
    Object.keys(snap.achievements).forEach(function (appid) {
      var entry = snap.achievements[appid];
      entry.unlocked.forEach(function (item) {
        unlocks.push({ appid: Number(appid), game: entry.name, item: item });
      });
    });
    unlocks.sort(function (x, y) { return (y.item.unlocktime || 0) - (x.item.unlocktime || 0); });
    snap.unlocks = unlocks;
    snap.__ready = true;
  }

  function localName(item) {
    var local = item.l && item.l[L.code];
    return (local && local.name) || item.name || item.apiname;
  }

  function localDescription(item) {
    var local = item.l && item.l[L.code];
    return (local && local.description) || item.description || "";
  }

  function tagName(id) {
    var names = ((INDEX.names || {})[L.code] || {}).tags || {};
    var english = ((INDEX.names || {}).en || {}).tags || {};
    return names[id] || english[id] || null;
  }

  function categoryName(id) {
    var names = ((INDEX.names || {})[L.code] || {}).categories || {};
    var english = ((INDEX.names || {}).en || {}).categories || {};
    return names[id] || english[id] || null;
  }

  function snapshotIndex(id) {
    for (var i = 0; i < SNAPSHOTS.length; i++) if (SNAPSHOTS[i].id === id) return i;
    return -1;
  }

  function latestId() { return SNAPSHOTS.length ? SNAPSHOTS[SNAPSHOTS.length - 1].id : null; }

  /* ================================================================== routing */

  var VIEWS = {
    overview: { nav: "web.nav.overview", render: viewOverview },
    games: { nav: "web.nav.games", render: viewGames },
    achievements: { nav: "web.nav.achievements", render: viewAchievements },
    friends: { nav: "web.nav.friends", render: viewFriends },
    profile: { nav: "web.nav.profile", render: viewProfile },
    history: { nav: "web.nav.history", render: viewHistory },
    compare: { nav: "web.nav.compare", render: viewCompare },
    game: { parent: "games", render: viewGame }
  };
  var NAV = ["overview", "games", "achievements", "friends", "profile", "history", "compare"];

  function parseHash() {
    var raw = location.hash.replace(/^#\/?/, "");
    var q = raw.indexOf("?");
    var path = q >= 0 ? raw.slice(0, q) : raw;
    var params = new URLSearchParams(q >= 0 ? raw.slice(q + 1) : "");
    var parts = path.split("/").filter(Boolean).map(function (p) {
      try { return decodeURIComponent(p); } catch (e) { return p; }
    });
    var view = VIEWS[parts[0]] ? parts[0] : "overview";
    return { view: view, arg: parts[1] || null, params: params };
  }

  function href(view, arg, params) {
    var route = parseHash();
    var query = new URLSearchParams();
    var at = route.params.get("at");
    if (at && at !== latestId() && view !== "compare") query.set("at", at);
    Object.keys(params || {}).forEach(function (key) {
      var value = params[key];
      if (value === null || value === undefined || value === "") query.delete(key);
      else query.set(key, value);
    });
    var text = query.toString();
    return "#/" + view + (arg !== null && arg !== undefined ? "/" + encodeURIComponent(arg) : "") + (text ? "?" + text : "");
  }

  function setParams(changes) {
    var route = parseHash();
    var query = new URLSearchParams(route.params.toString());
    Object.keys(changes).forEach(function (key) {
      if (changes[key] === null || changes[key] === "" || changes[key] === undefined) query.delete(key);
      else query.set(key, changes[key]);
    });
    var text = query.toString();
    var next = "#/" + route.view + (route.arg ? "/" + encodeURIComponent(route.arg) : "") + (text ? "?" + text : "");
    history.replaceState(null, "", next);
  }

  function currentId(route) {
    var at = route.params.get("at");
    if (at && snapshotIndex(at) >= 0) return at;
    return latestId();
  }

  /* ================================================================== chrome */

  function renderChrome(route, snapId) {
    var entry = SNAPSHOTS[snapshotIndex(snapId)] || {};
    var summary = entry.summary || {};
    var who = document.getElementById("who");
    clear(who);
    add(who, [image(summary.avatar, 36, "avatar"), h("span", { class: "who-name", text: summary.persona || "Steam" })]);

    var tabs = document.getElementById("tabs");
    clear(tabs);
    tabs.setAttribute("aria-label", t("web.nav.label"));
    var active = VIEWS[route.view].parent || route.view;
    NAV.forEach(function (view) {
      tabs.appendChild(h("a", { href: href(view), "aria-current": view === active ? "page" : null, text: t(VIEWS[view].nav) }));
    });

    renderRail(route, snapId);

    var foot = document.getElementById("foot");
    clear(foot);
    add(foot, h("p", null,
      t("web.footer.built", { version: INDEX.version || "", date: dateTime(INDEX.generated_at) }), " ",
      t("web.footer.valve"), " ",
      h("a", { href: "../database/index.html", text: t("web.footer.database") })));

    document.querySelectorAll("[data-i18n]").forEach(function (node) { node.textContent = t(node.getAttribute("data-i18n")); });
  }

  function renderRail(route, snapId) {
    var rail = document.getElementById("rail");
    clear(rail);
    if (!SNAPSHOTS.length) return;
    rail.setAttribute("aria-label", t("web.rail.label"));
    var times = SNAPSHOTS.map(function (s) { return new Date(s.collected_at).getTime(); });
    var first = times[0];
    var last = times[times.length - 1];
    var span = Math.max(1, last - first);
    function position(time) {
      if (SNAPSHOTS.length === 1) return 50;
      return 2 + (time - first) / span * 96;
    }
    var compare = route.view === "compare";
    var pair = compare ? comparePair(route) : null;
    var line = h("div", { class: "rail-line", "aria-hidden": "true" });
    rail.appendChild(line);
    if (pair) {
      var a = position(times[snapshotIndex(pair[0])]);
      var b = position(times[snapshotIndex(pair[1])]);
      rail.appendChild(h("div", { class: "rail-span", style: "left:" + Math.min(a, b) + "%;width:" + Math.abs(b - a) + "%", "aria-hidden": "true" }));
    }
    var years = {};
    var startYear = new Date(first).getFullYear();
    var endYear = new Date(last).getFullYear();
    if (endYear > startYear) {
      for (var year = startYear + 1; year <= endYear; year++) {
        years[year] = new Date(year, 0, 1).getTime();
      }
    }
    Object.keys(years).forEach(function (year) {
      rail.appendChild(h("span", { class: "rail-year", style: "left:" + position(years[year]) + "%", text: year, "aria-hidden": "true" }));
    });
    var selected = pair || [snapId];
    var buttons = [];
    SNAPSHOTS.forEach(function (entry, index) {
      var on = selected.indexOf(entry.id) >= 0;
      var button = h("button", {
        class: "tick" + (on ? " on" : ""),
        type: "button",
        style: "left:" + position(times[index]) + "%",
        "aria-label": t("web.rail.snapshot", { date: snapshotDate(entry) }),
        "aria-pressed": on ? "true" : "false",
        tabindex: on || (!pair && entry.id === snapId) ? "0" : "-1",
        onclick: function () { pickSnapshot(entry.id); }
      });
      button.addEventListener("keydown", function (event) {
        var step = event.key === "ArrowLeft" ? -1 : event.key === "ArrowRight" ? 1 : 0;
        if (!step) return;
        event.preventDefault();
        var next = buttons[Math.max(0, Math.min(buttons.length - 1, index + step))];
        next.focus();
      });
      C.hover(button, snapshotDate(entry), entry.summary && entry.summary.persona ? entry.summary.persona : "");
      buttons.push(button);
      rail.appendChild(button);
    });
    var current = SNAPSHOTS[snapshotIndex(selected[selected.length - 1])];
    var label = compare && pair
      ? t("web.rail.comparing", { from: snapshotDate(SNAPSHOTS[snapshotIndex(pair[0])]), to: snapshotDate(SNAPSHOTS[snapshotIndex(pair[1])]) })
      : snapId === latestId()
        ? t("web.rail.latest", { date: snapshotDate(current), count: SNAPSHOTS.length })
        : t("web.rail.viewing", { date: snapshotDate(current) });
    var caption = h("p", { class: "rail-caption" }, h("span", { text: label }));
    if (!compare && snapId !== latestId()) {
      caption.appendChild(h("a", { href: href(route.view, route.arg, { at: null }), text: t("web.rail.back") }));
    }
    rail.parentNode.querySelectorAll(".rail-caption").forEach(function (n) { n.remove(); });
    rail.parentNode.insertBefore(caption, rail);
  }

  function pickSnapshot(id) {
    var route = parseHash();
    if (route.view === "compare") {
      var pair = comparePair(route);
      var from = pair[0];
      var to = pair[1];
      var target = snapshotIndex(id);
      if (Math.abs(target - snapshotIndex(from)) <= Math.abs(target - snapshotIndex(to))) from = id; else to = id;
      if (snapshotIndex(from) > snapshotIndex(to)) { var swap = from; from = to; to = swap; }
      location.hash = "#/compare?from=" + encodeURIComponent(from) + "&to=" + encodeURIComponent(to);
      return;
    }
    var query = new URLSearchParams(route.params.toString());
    if (id === latestId()) query.delete("at"); else query.set("at", id);
    var text = query.toString();
    location.hash = "#/" + route.view + (route.arg ? "/" + encodeURIComponent(route.arg) : "") + (text ? "?" + text : "");
  }

  /* ================================================================== render loop */

  function render() {
    var route = parseHash();
    var main = document.getElementById("main");
    C.reset();
    if (!SNAPSHOTS.length) {
      renderChrome(route, null);
      clear(main);
      main.appendChild(empty(t("web.empty.title"), t("web.empty.hint")));
      return;
    }
    var snapId = currentId(route);
    renderChrome(route, snapId);
    var token = ++renderToken;
    main.classList.add("loading");
    var view = VIEWS[route.view];
    var wanted = route.view === "compare" ? comparePair(route) : [snapId];
    Promise.all(wanted.map(getSnapshot)).then(function (snaps) {
      if (token !== renderToken) return;
      clear(main);
      main.classList.remove("loading");
      var title = route.view === "game" ? t("web.nav.games") : t(VIEWS[route.view].nav);
      document.title = title + " – " + ((snaps[0].profile || {}).personaname || "steamledger");
      view.render(main, snaps[0], route, snaps);
      C.drawMounted();
      if (lastView !== null && lastView !== route.view + route.arg) {
        main.focus({ preventScroll: true });
        window.scrollTo(0, 0);
      }
      lastView = route.view + route.arg;
    }).catch(function (error) {
      if (token !== renderToken) return;
      clear(main);
      main.classList.remove("loading");
      main.appendChild(empty(t("web.error.load"), String(error && error.message || error)));
    });
  }

  /* ================================================================== shared blocks */

  function heading(title, sub) {
    return h("header", { class: "view-head" }, h("h1", { text: title }), sub ? h("p", { class: "lede", text: sub }) : null);
  }

  function platformParts(games) {
    var totals = { windows: 0, linux: 0, mac: 0, deck: 0, untracked: 0 };
    games.forEach(function (g) {
      var deck = g.playtime_deck || 0;
      var linux = g.playtime_linux || 0;
      var linuxOnly = deck <= linux ? linux - deck : linux;
      var tracked = (g.playtime_windows || 0) + (g.playtime_mac || 0) + linuxOnly + deck;
      totals.windows += g.playtime_windows || 0;
      totals.mac += g.playtime_mac || 0;
      totals.linux += linuxOnly;
      totals.deck += deck;
      totals.untracked += Math.max(0, (g.playtime_forever || 0) - tracked);
    });
    return ["windows", "linux", "mac", "deck", "untracked"].map(function (key) {
      return { key: key, label: t("data.platform." + key), value: totals[key] };
    });
  }

  function platformChart(games) {
    return C.segmented({
      parts: platformParts(games),
      format: hours,
      percent: function (share) { return L.pct0.format(share); },
      label: t("web.overview.platforms"),
      empty: t("web.none")
    });
  }

  function gameIcon(game, size) { return image(game && game.icon, size || 24, "icon"); }

  function gameLink(appid, name, icon) {
    return h("a", { class: "game-link", href: href("game", appid) }, icon || null, h("span", { text: name }));
  }

  function changeChips(summary, level) {
    if (!summary) return [];
    var chips = [];
    if (summary.playtime) chips.push(chip(t("diff.summary.playtime", { value: signedHours(summary.playtime) })));
    ["achievements", "completed", "games_added", "games_removed", "friends_added", "friends_removed", "badges", "wishlist_added", "wishlist_removed", "profile"].forEach(function (key) {
      if (summary[key]) chips.push(chip(t("diff.summary." + key, { count: summary[key] })));
    });
    if (level) chips.push(chip(t("diff.summary.level", { from: level.from, to: level.to })));
    return chips;
  }

  function unlockRow(entry, showGame) {
    var item = entry.item;
    return h("li", { class: "unlock" },
      image(item.icon, 40, "badge-icon"),
      h("div", { class: "unlock-body" },
        h("strong", { text: localName(item) }),
        h("span", { class: "muted", text: localDescription(item) }),
        showGame ? h("a", { class: "unlock-game", href: href("game", entry.appid), text: entry.game }) : null),
      h("div", { class: "unlock-meta" },
        h("span", { text: item.unlocktime ? dateTime(item.unlocktime) : t("web.unknown_date") }),
        item.percent !== null && item.percent !== undefined ? h("span", { class: "muted", text: t("web.rarity", { value: percent(item.percent) }) }) : null));
  }

  /* ================================================================== overview */

  function viewOverview(main, snap) {
    var p = snap.profile;
    var s = snap.meta.summary || {};
    var since = p.created ? L.monthYear.format(stamp(p.created)) : null;
    main.appendChild(h("h1", { class: "visually-hidden", text: t("web.nav.overview") }));
    var hero = h("section", { class: "hero" },
      h("div", { class: "hero-figure", text: hours(s.playtime || 0) }),
      h("p", { class: "hero-text", text: t("web.overview.lede", { count: s.games || 0, played: num(s.played || 0) }) }),
      since ? h("p", { class: "hero-sub", text: t("web.overview.member_since", { date: since, age: duration(p.created, snap.when) }) }) : null);
    main.appendChild(hero);
    add(main, sectionNote(snap, "games"));

    main.appendChild(facts([
      { label: t("web.fact.level"), value: levelRing(p.level), note: p.level_percentile ? t("web.overview.percentile", { value: percent(p.level_percentile) }) : null },
      { label: t("web.fact.achievements"), value: num(s.achievements), note: s.achievements_total ? t("web.of_total", { total: num(s.achievements_total) }) : null },
      { label: t("web.fact.completion"), value: s.completion !== null && s.completion !== undefined ? percent(s.completion) : "–", note: t("web.fact.completion_note") },
      { label: t("web.fact.perfect"), value: num(s.perfect_games) },
      { label: t("web.fact.recent"), value: hours(s.playtime_2weeks || 0) },
      { label: t("web.fact.friends"), value: num(s.friends) }
    ]));

    if (snap.changes) {
      var block = section(t("web.overview.since_previous", { date: dateTime(snap.changes.from.collected_at) }));
      var chips = changeChips(snap.changes.summary, snap.changes.level);
      if (chips.length) {
        block.appendChild(h("div", { class: "chips" }, chips));
        block.appendChild(h("p", null, h("a", { href: "#/compare?from=" + encodeURIComponent(snap.changes.from.id) + "&to=" + encodeURIComponent(snap.meta.id), text: t("web.overview.see_changes") })));
      } else {
        block.appendChild(h("p", { class: "muted", text: t("diff.none") }));
      }
      main.appendChild(block);
    }

    var activity = section(t("web.overview.activity"));
    activity.appendChild(unlockCalendar(snap, snap.when));
    main.appendChild(activity);

    var grid = h("div", { class: "grid" });
    var top = snap.games.filter(function (g) { return g.playtime_forever > 0; }).slice(0, 10);
    var most = section(t("web.overview.most_played"));
    most.appendChild(top.length ? C.bars({
      items: top.map(function (g) { return { label: g.name, value: g.playtime_forever, href: href("game", g.appid), icon: gameIcon(g, 20) }; }),
      format: hours
    }) : empty(t("web.none")));
    grid.appendChild(most);

    var platforms = section(t("web.overview.platforms"), t("web.overview.platforms_note"));
    platforms.appendChild(platformChart(snap.games));
    grid.appendChild(platforms);

    var recent = section(t("web.overview.recent"));
    if (snap.recent.length) {
      recent.appendChild(h("ul", { class: "rows" }, snap.recent.slice(0, 8).map(function (g) {
        return h("li", null, gameLink(g.appid, g.name, gameIcon(g, 24)),
          h("span", { class: "num", text: t("web.overview.recent_hours", { value: hours(g.playtime_2weeks) }) }));
      })));
    } else {
      recent.appendChild(empty(t("web.overview.recent_none")));
    }
    grid.appendChild(recent);

    var tags = tagPlaytime(snap.games).slice(0, 10);
    if (tags.length) {
      var tagBlock = section(t("web.overview.tags"), t("web.overview.tags_note"));
      tagBlock.appendChild(C.bars({ items: tags, format: hours }));
      grid.appendChild(tagBlock);
    }
    var years = releaseYears(snap.games);
    if (years.length) {
      var yearBlock = section(t("web.overview.release_years"));
      yearBlock.appendChild(C.columns({
        items: years,
        format: function (v) { return t("web.games_count", { count: v }); },
        axis: num,
        every: Math.ceil(years.length / 12),
        table: t("web.table_view"),
        headers: [t("web.col.year"), t("web.col.games")]
      }));
      grid.appendChild(yearBlock);
    }
    main.appendChild(grid);
  }

  function tagPlaytime(games) {
    var totals = {};
    games.forEach(function (g) {
      var ids = ((g.store || {}).tag_ids || []).slice(0, 3);
      ids.forEach(function (id) { totals[id] = (totals[id] || 0) + (g.playtime_forever || 0); });
    });
    return Object.keys(totals).filter(function (id) { return totals[id] > 0 && tagName(id); })
      .sort(function (a, b) { return totals[b] - totals[a]; })
      .map(function (id) { return { label: tagName(id), value: totals[id] }; });
  }

  function releaseYears(games) {
    var counts = {};
    games.forEach(function (g) {
      var release = (g.store || {}).release;
      if (release) {
        var year = new Date(release * 1000).getFullYear();
        counts[year] = (counts[year] || 0) + 1;
      }
    });
    var years = Object.keys(counts).map(Number).sort(function (a, b) { return a - b; });
    if (!years.length) return [];
    var out = [];
    for (var y = years[0]; y <= years[years.length - 1]; y++) {
      out.push({ label: String(y), value: counts[y] || 0, tip: String(y) });
    }
    return out;
  }

  function unlockCounts(snap) {
    var counts = {};
    snap.unlocks.forEach(function (u) {
      if (u.item.unlocktime) {
        var key = dayKey(new Date(u.item.unlocktime * 1000));
        counts[key] = (counts[key] || 0) + 1;
      }
    });
    return counts;
  }

  function unlockCalendar(snap, end) {
    var counts = unlockCounts(snap);
    var startTime = end.getTime() - 365 * 86400000;
    var year = snap.unlocks.filter(function (u) { return u.item.unlocktime && u.item.unlocktime * 1000 > startTime; }).length;
    var firstDay = Number(t("web.calendar.first_day")) || 0;
    var wrap = h("div");
    wrap.appendChild(h("p", { class: "muted", text: t("web.overview.activity_year", { count: year }) }));
    wrap.appendChild(C.calendar({
      counts: counts,
      end: end,
      weeks: 53,
      firstDay: firstDay,
      label: t("web.overview.activity"),
      less: t("web.calendar.less"),
      more: t("web.calendar.more"),
      monthLabel: function (d) { return L.month.format(d); },
      weekdayLabel: function (d) { return L.weekday.format(d); },
      dayLabel: function (d) { return L.date.format(d); },
      countLabel: function (n) { return t("web.calendar.unlocks", { count: n }); },
      cellLabel: function (d, n) { return L.date.format(d) + ": " + t("web.calendar.unlocks", { count: n }); }
    }));
    return wrap;
  }

  /* ================================================================== games */

  var GAME_SORTS = {
    playtime: function (a, b) { return b.playtime_forever - a.playtime_forever; },
    recent: function (a, b) { return (b.playtime_2weeks || 0) - (a.playtime_2weeks || 0) || b.playtime_forever - a.playtime_forever; },
    name: function (a, b) { return L.collator.compare(a.name, b.name); },
    last: function (a, b) { return (b.last_played || 0) - (a.last_played || 0); },
    achievements: function (a, b) { return ((b.achievements || {}).percent || -1) - ((a.achievements || {}).percent || -1); },
    release: function (a, b) { return ((b.store || {}).release || 0) - ((a.store || {}).release || 0); },
    rating: function (a, b) { return (((b.store || {}).review || {}).percent || 0) - (((a.store || {}).review || {}).percent || 0); }
  };

  var GAME_FILTERS = {
    all: function () { return true; },
    played: function (g) { return g.playtime_forever > 0; },
    unplayed: function (g) { return !g.playtime_forever; },
    achievements: function (g) { return !!g.achievements; },
    progress: function (g) { return g.achievements && g.achievements.unlocked > 0 && g.achievements.unlocked < g.achievements.total; },
    perfect: function (g) { return g.achievements && g.achievements.unlocked >= g.achievements.total; },
    recent: function (g) { return (g.playtime_2weeks || 0) > 0; }
  };

  function select(name, value, options, onchange) {
    var node = h("select", { name: name, onchange: function () { onchange(node.value); } }, options.map(function (o) {
      return h("option", { value: o[0], selected: o[0] === value ? true : null, text: o[1] });
    }));
    return node;
  }

  function viewGames(main, snap, route) {
    var list = route.params.get("list") === "wishlist" ? "wishlist" : "library";
    var s = snap.meta.summary || {};
    main.appendChild(heading(t("web.nav.games"), t("web.games.lede", { count: s.games || 0, played: num(s.played || 0), hours: hours(s.playtime || 0) })));
    var switcher = h("div", { class: "switch", role: "tablist" },
      h("a", { href: href("games", null, { list: null }), role: "tab", "aria-selected": list === "library" ? "true" : "false", text: t("web.games.library") }),
      h("a", { href: href("games", null, { list: "wishlist" }), role: "tab", "aria-selected": list === "wishlist" ? "true" : "false", text: t("web.games.wishlist", { count: snap.wishlist.length }) }));
    main.appendChild(switcher);
    if (list === "wishlist") {
      main.appendChild(wishlistTable(snap));
      return;
    }
    add(main, sectionNote(snap, "games"));
    var state = {
      q: route.params.get("q") || "",
      show: GAME_FILTERS[route.params.get("show")] ? route.params.get("show") : "all",
      sort: GAME_SORTS[route.params.get("sort")] ? route.params.get("sort") : "playtime"
    };
    var holder = h("div");
    var counter = h("p", { class: "muted count", "aria-live": "polite" });
    function refresh() {
      setParams({ q: state.q || null, show: state.show === "all" ? null : state.show, sort: state.sort === "playtime" ? null : state.sort });
      var needle = fold(state.q);
      var rows = snap.games.filter(GAME_FILTERS[state.show]).filter(function (g) {
        return !needle || fold(g.name).indexOf(needle) >= 0 || fold(((g.store || {}).developers || []).join(" ")).indexOf(needle) >= 0;
      }).sort(GAME_SORTS[state.sort]);
      counter.textContent = t("web.games.shown", { count: rows.length, total: num(snap.games.length) });
      clear(holder);
      holder.appendChild(rows.length ? gamesTable(rows) : empty(t("web.games.none")));
    }
    var search = h("input", { type: "search", value: state.q, placeholder: t("web.games.search"), "aria-label": t("web.games.search") });
    search.addEventListener("input", function () { state.q = search.value; refresh(); });
    main.appendChild(h("div", { class: "toolbar" },
      search,
      h("label", null, h("span", { text: t("web.games.show") }), select("show", state.show, Object.keys(GAME_FILTERS).map(function (k) { return [k, t("web.games.filter." + k)]; }), function (v) { state.show = v; refresh(); })),
      h("label", null, h("span", { text: t("web.games.sort") }), select("sort", state.sort, Object.keys(GAME_SORTS).map(function (k) { return [k, t("web.games.sort_by." + k)]; }), function (v) { state.sort = v; refresh(); }))));
    main.appendChild(counter);
    main.appendChild(holder);
    refresh();
  }

  function gamesTable(rows) {
    var max = Math.max.apply(null, rows.map(function (g) { return g.playtime_forever; }).concat([1]));
    var body = h("tbody");
    var fragment = document.createDocumentFragment();
    rows.forEach(function (g) {
      var store = g.store || {};
      var progress = g.achievements;
      var sub = [];
      if ((store.developers || []).length) sub.push(store.developers[0]);
      if (store.release) sub.push(String(new Date(store.release * 1000).getFullYear()));
      fragment.appendChild(h("tr", null,
        h("td", null, h("div", { class: "cell-game" }, gameIcon(g, 32), h("div", null,
          h("a", { href: href("game", g.appid), text: g.name }),
          sub.length ? h("span", { class: "muted small", text: sub.join(", ") }) : null))),
        h("td", { class: "num" }, g.playtime_forever ? h("div", { class: "cell-hours" },
          h("span", { text: hours(g.playtime_forever) }),
          h("span", { class: "thin", "aria-hidden": "true" }, h("span", { style: "width:" + (g.playtime_forever / max * 100).toFixed(1) + "%" }))) : h("span", { class: "muted", text: t("web.games.never_played") })),
        h("td", { class: "num" }, g.playtime_2weeks ? hours(g.playtime_2weeks) : ""),
        h("td", { class: "num" }, g.last_played ? date(g.last_played) : ""),
        h("td", { class: "num" }, progress ? h("div", { class: "cell-progress" },
          h("span", { text: progress.unlocked + " / " + progress.total }),
          C.meter(progress.percent, percent(progress.percent))) : ""),
        h("td", { class: "num" }, store.review && store.review.percent ? percent(store.review.percent) : "")));
    });
    body.appendChild(fragment);
    return h("div", { class: "table-wrap" }, h("table", { class: "data" },
      h("thead", null, h("tr", null,
        h("th", { scope: "col", text: t("web.col.game") }),
        h("th", { scope: "col", class: "num", text: t("web.col.playtime") }),
        h("th", { scope: "col", class: "num", text: t("web.col.recent") }),
        h("th", { scope: "col", class: "num", text: t("web.col.last_played") }),
        h("th", { scope: "col", class: "num", text: t("web.col.achievements") }),
        h("th", { scope: "col", class: "num", text: t("web.col.rating") }))),
      body));
  }

  function wishlistTable(snap) {
    if (!snap.wishlist.length) {
      return h("div", null, sectionNote(snap, "wishlist"), empty(t("web.games.wishlist_empty")));
    }
    var rows = snap.wishlist.map(function (w) {
      var store = w.store || {};
      var tags = (store.tag_ids || []).slice(0, 3).map(tagName).filter(Boolean).join(", ");
      return h("tr", null,
        h("td", null, h("div", { class: "cell-game" }, image(store.header, 92, "capsule"), h("div", null,
          h("a", { href: href("game", w.appid), text: w.name }),
          tags ? h("span", { class: "muted small", text: tags }) : null))),
        h("td", { class: "num", text: w.added ? date(w.added) : "" }),
        h("td", { class: "num", text: store.release ? date(store.release) : "" }),
        h("td", { class: "num", text: store.review && store.review.percent ? percent(store.review.percent) : "" }),
        h("td", { class: "num", text: w.priority ? String(w.priority) : "" }));
    });
    return h("div", { class: "table-wrap" }, h("table", { class: "data" },
      h("thead", null, h("tr", null,
        h("th", { scope: "col", text: t("web.col.game") }),
        h("th", { scope: "col", class: "num", text: t("web.col.added") }),
        h("th", { scope: "col", class: "num", text: t("web.col.release") }),
        h("th", { scope: "col", class: "num", text: t("web.col.rating") }),
        h("th", { scope: "col", class: "num", text: t("web.col.priority") }))),
      h("tbody", null, rows)));
  }

  /* ================================================================== one game */

  function viewGame(main, snap, route) {
    var appid = Number(route.arg);
    var game = snap.gameMap[appid];
    var wish = null;
    snap.wishlist.forEach(function (w) { if (w.appid === appid) wish = w; });
    var back = h("p", { class: "back" }, h("a", { href: href("games"), text: t("web.game.back") }));
    main.appendChild(back);
    if (!game && !wish) {
      main.appendChild(empty(t("web.game.missing"), t("web.game.missing_hint")));
      return;
    }
    var item = game || wish;
    var store = item.store || {};
    var head = h("header", { class: "game-head" },
      store.header ? image(store.header, 460, "header-image") : null,
      h("div", { class: "game-title" },
        h("h1", { text: item.name }),
        h("p", { class: "muted" }, [
          (store.developers || []).join(", "),
          store.release ? t("web.game.released", { date: date(store.release) }) : null
        ].filter(Boolean).join(". ")),
        h("p", null, external("https://store.steampowered.com/app/" + appid + "/", t("web.game.store")), " ",
          external("https://steamcommunity.com/stats/" + appid + "/achievements/", t("web.game.global_stats")))));
    main.appendChild(head);
    var description = h("p", { class: "description" });
    var reviewLabel = h("p", { class: "muted small" });
    main.appendChild(description);

    var tags = (store.tag_ids || []).map(tagName).filter(Boolean).slice(0, 12);
    var deck = store.deck;
    var details = [];
    if (game) {
      details.push({ label: t("web.fact.playtime"), value: hours(game.playtime_forever) });
      details.push({ label: t("web.fact.recent"), value: hours(game.playtime_2weeks || 0) });
      details.push({ label: t("web.fact.last_played"), value: game.last_played ? date(game.last_played) : t("web.games.never_played") });
      if (game.achievements) details.push({ label: t("web.fact.achievements"), value: game.achievements.unlocked + " / " + game.achievements.total, note: percent(game.achievements.percent) });
    } else if (wish) {
      details.push({ label: t("web.col.added"), value: date(wish.added) });
    }
    if (store.review) details.push({ label: t("web.fact.reviews"), value: percent(store.review.percent), note: t("web.game.reviews", { count: store.review.count || 0 }) });
    if (deck !== undefined && deck !== null) details.push({ label: t("web.fact.deck"), value: h("span", { class: "deck deck-" + deck, text: t("data.deck." + deck) }) });
    main.appendChild(facts(details));
    if (tags.length) main.appendChild(h("ul", { class: "tags", "aria-label": t("web.game.tags") }, tags.map(function (name) { return h("li", { text: name }); })));
    var categories = (store.category_ids || []).map(categoryName).filter(Boolean);
    if (categories.length) main.appendChild(h("p", { class: "muted small", text: categories.join(", ") }));
    main.appendChild(reviewLabel);

    if (game && game.playtime_forever) {
      var platforms = section(t("web.overview.platforms"), t("web.overview.platforms_note"));
      platforms.appendChild(platformChart([game]));
      main.appendChild(platforms);
    }
    var series = (INDEX.series || {})[String(appid)] || [];
    if (series.length >= 2) {
      var history = section(t("web.game.history"));
      var points = series.map(function (pair) {
        var entry = SNAPSHOTS[pair[0]];
        return { t: new Date(entry.collected_at), v: pair[1], label: snapshotDate(entry) };
      });
      if (points[points.length - 1].t < new Date(SNAPSHOTS[SNAPSHOTS.length - 1].collected_at)) {
        var lastEntry = SNAPSHOTS[SNAPSHOTS.length - 1];
        points.push({ t: new Date(lastEntry.collected_at), v: points[points.length - 1].v, label: snapshotDate(lastEntry) });
      }
      history.appendChild(C.line({
        points: points,
        format: hours,
        axis: hoursAxis,
        unit: 60,
        xlabel: function (d) { return L.date.format(d); },
        label: t("web.game.history"),
        table: t("web.table_view"),
        headers: [t("web.col.date"), t("web.col.playtime")]
      }));
      main.appendChild(history);
    }

    var achievements = section(t("web.nav.achievements"));
    main.appendChild(achievements);
    getApp(appid).then(function (app) {
      var local = app && app.store && (app.store[L.code] || app.store.en);
      if (local && local.description) description.textContent = local.description;
      if (local && local.review && store.review) {
        reviewLabel.textContent = t("web.game.review_label", { label: local.review, count: store.review.count || 0 });
      }
      achievements.appendChild(achievementList(snap, appid, app));
      C.drawMounted();
    });
  }

  function achievementList(snap, appid, app) {
    var entry = snap.achievements[String(appid)];
    var unlocked = {};
    ((entry || {}).unlocked || []).forEach(function (u) { unlocked[u.apiname] = u; });
    var schema = app && app.schema ? (app.schema[L.code] || app.schema.en || []) : [];
    var english = app && app.schema ? (app.schema.en || []) : [];
    var rarity = (app && app.rarity) || {};
    if (!schema.length && !entry) {
      return h("div", null, sectionNote(snap, "achievements"), empty(t("web.game.no_achievements")));
    }
    var rows = (schema.length ? schema : ((entry || {}).unlocked || [])).map(function (a, i) {
      var got = unlocked[a.apiname];
      var name = a.name || (english[i] || {}).name || a.apiname;
      return {
        apiname: a.apiname,
        name: got && !schema.length ? localName(got) : name,
        description: a.description || (got ? localDescription(got) : ""),
        hidden: !!a.hidden,
        icon: a.icon || (got && got.icon),
        unlocktime: got ? got.unlocktime : null,
        percent: rarity[a.apiname] !== undefined ? rarity[a.apiname] : (got ? got.percent : null)
      };
    });
    rows.sort(function (x, y) {
      var xu = x.unlocktime !== null;
      var yu = y.unlocktime !== null;
      if (xu !== yu) return xu ? -1 : 1;
      if (xu) return (y.unlocktime || 0) - (x.unlocktime || 0);
      return (y.percent || 0) - (x.percent || 0);
    });
    var total = (entry && entry.total) || rows.length;
    var count = Object.keys(unlocked).length;
    var wrap = h("div");
    wrap.appendChild(h("div", { class: "progress-line" },
      h("span", { text: t("web.game.progress", { count: count, total: num(total) }) }),
      C.meter(total ? count / total * 100 : 0, percent(total ? count / total * 100 : 0))));
    var filter = "all";
    var list = h("ul", { class: "achievements" });
    function fill() {
      clear(list);
      rows.filter(function (r) {
        return filter === "all" || (filter === "unlocked" ? r.unlocktime !== null : r.unlocktime === null);
      }).forEach(function (r) {
        var locked = r.unlocktime === null;
        var desc = h("span", { class: "muted", text: r.description || (r.hidden ? t("web.game.hidden_description") : "") });
        if (locked && r.hidden && r.description) {
          desc.classList.add("spoiler");
          desc.setAttribute("tabindex", "0");
          desc.setAttribute("role", "button");
          desc.setAttribute("aria-label", t("web.game.reveal"));
          var reveal = function () { desc.classList.add("revealed"); desc.removeAttribute("role"); desc.removeAttribute("aria-label"); };
          desc.addEventListener("click", reveal);
          desc.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); reveal(); } });
        }
        list.appendChild(h("li", { class: "achievement" + (locked ? " locked" : "") },
          image(r.icon, 48, "badge-icon"),
          h("div", { class: "unlock-body" }, h("strong", { text: r.name }), desc),
          h("div", { class: "unlock-meta" },
            h("span", { text: locked ? t("web.game.locked") : (r.unlocktime ? dateTime(r.unlocktime) : t("web.unknown_date")) }),
            r.percent !== null && r.percent !== undefined ? h("span", { class: "muted", text: t("web.rarity", { value: percent(r.percent) }) }) : null)));
      });
    }
    var buttons = ["all", "unlocked", "locked"].map(function (key) {
      var b = h("button", { type: "button", "aria-pressed": key === filter ? "true" : "false", text: t("web.game.filter." + key) });
      b.addEventListener("click", function () {
        filter = key;
        buttons.forEach(function (other) { other.setAttribute("aria-pressed", other === b ? "true" : "false"); });
        fill();
      });
      return b;
    });
    wrap.appendChild(h("div", { class: "segmented-control" }, buttons));
    wrap.appendChild(list);
    fill();
    return wrap;
  }

  /* ================================================================== achievements */

  function viewAchievements(main, snap) {
    var s = snap.meta.summary || {};
    main.appendChild(heading(t("web.nav.achievements"), t("web.achievements.lede", { count: s.achievements || 0, total: num(s.achievements_total || 0) })));
    add(main, sectionNote(snap, "achievements"));
    var monthAgo = snap.when.getTime() / 1000 - 30 * 86400;
    var rarest = snap.unlocks.filter(function (u) { return u.item.percent !== null && u.item.percent !== undefined; })
      .sort(function (a, b) { return a.item.percent - b.item.percent; });
    main.appendChild(facts([
      { label: t("web.fact.achievements"), value: num(s.achievements) },
      { label: t("web.fact.completion"), value: s.completion !== null && s.completion !== undefined ? percent(s.completion) : "–", note: t("web.fact.completion_note") },
      { label: t("web.fact.perfect"), value: num(s.perfect_games) },
      { label: t("web.achievements.last_30"), value: num(snap.unlocks.filter(function (u) { return u.item.unlocktime > monthAgo; }).length) },
      rarest.length ? { label: t("web.achievements.rarest"), value: percent(rarest[0].item.percent), note: localName(rarest[0].item) } : null
    ]));
    if (!snap.unlocks.length) {
      main.appendChild(empty(t("web.achievements.none")));
      return;
    }
    var activity = section(t("web.overview.activity"));
    activity.appendChild(unlockCalendar(snap, snap.when));
    main.appendChild(activity);

    var grid = h("div", { class: "grid" });
    var perYear = {};
    var perHour = [];
    var perDay = [0, 0, 0, 0, 0, 0, 0];
    for (var i = 0; i < 24; i++) perHour.push(0);
    snap.unlocks.forEach(function (u) {
      if (!u.item.unlocktime) return;
      var d = new Date(u.item.unlocktime * 1000);
      perYear[d.getFullYear()] = (perYear[d.getFullYear()] || 0) + 1;
      perHour[d.getHours()] += 1;
      perDay[d.getDay()] += 1;
    });
    var years = Object.keys(perYear).map(Number).sort(function (a, b) { return a - b; });
    if (years.length) {
      var yearItems = [];
      for (var y = years[0]; y <= years[years.length - 1]; y++) yearItems.push({ label: String(y), value: perYear[y] || 0, tip: String(y) });
      var byYear = section(t("web.achievements.per_year"));
      byYear.appendChild(C.columns({ items: yearItems, format: function (v) { return t("web.calendar.unlocks", { count: v }); }, axis: num, every: Math.ceil(yearItems.length / 10), table: t("web.table_view"), headers: [t("web.col.year"), t("web.col.unlocks")] }));
      grid.appendChild(byYear);
    }
    var hourItems = perHour.map(function (v, hour) {
      var label = String(hour).padStart(2, "0") + ":00";
      return { label: String(hour).padStart(2, "0"), value: v, tip: label };
    });
    var byHour = section(t("web.achievements.per_hour"), t("web.achievements.per_hour_note"));
    byHour.appendChild(C.columns({ items: hourItems, format: function (v) { return t("web.calendar.unlocks", { count: v }); }, axis: num, every: 3, table: t("web.table_view"), headers: [t("web.col.hour"), t("web.col.unlocks")] }));
    grid.appendChild(byHour);
    var firstDay = Number(t("web.calendar.first_day")) || 0;
    var dayItems = [];
    for (var k = 0; k < 7; k++) {
      var weekday = (firstDay + k) % 7;
      var sample = new Date(2024, 0, 7 + weekday);
      dayItems.push({ label: L.weekday.format(sample), value: perDay[weekday], tip: L.weekday.format(sample) });
    }
    var byDay = section(t("web.achievements.per_weekday"));
    byDay.appendChild(C.columns({ items: dayItems, format: function (v) { return t("web.calendar.unlocks", { count: v }); }, axis: num, table: t("web.table_view"), headers: [t("web.col.day"), t("web.col.unlocks")] }));
    grid.appendChild(byDay);

    var closest = snap.games.filter(GAME_FILTERS.progress).sort(function (a, b) { return b.achievements.percent - a.achievements.percent; }).slice(0, 10);
    if (closest.length) {
      var near = section(t("web.achievements.closest"));
      near.appendChild(C.bars({
        items: closest.map(function (g) { return { label: g.name, value: g.achievements.percent, href: href("game", g.appid), icon: gameIcon(g, 20) }; }),
        format: function (v) { return percent(v); }
      }));
      grid.appendChild(near);
    }
    main.appendChild(grid);

    var recent = section(t("web.achievements.recent"));
    recent.appendChild(longList("unlocks", snap.unlocks, function (u) { return unlockRow(u, true); }, 15));
    main.appendChild(recent);

    if (rarest.length) {
      var rare = section(t("web.achievements.rarest_list"));
      rare.appendChild(longList("unlocks", rarest, function (u) { return unlockRow(u, true); }, 10));
      main.appendChild(rare);
    }
    if ((snap.next || []).length) {
      var next = section(t("web.achievements.next"), t("web.achievements.next_note"));
      next.appendChild(longList("unlocks", snap.next, function (n) {
        var name = (n.names && (n.names[L.code] || n.names.en)) || n.apiname;
        return h("li", { class: "unlock locked" },
          image(n.icon, 40, "badge-icon"),
          h("div", { class: "unlock-body" }, h("strong", { text: name }), h("a", { class: "unlock-game", href: href("game", n.appid), text: n.game })),
          h("div", { class: "unlock-meta" }, h("span", { text: t("web.rarity", { value: percent(n.percent) }) })));
      }, 10));
      main.appendChild(next);
    }
    var perfect = snap.games.filter(GAME_FILTERS.perfect).sort(function (a, b) { return (b.achievements.last_unlock || 0) - (a.achievements.last_unlock || 0); });
    if (perfect.length) {
      var done = section(t("web.achievements.perfect", { count: perfect.length }));
      done.appendChild(h("ul", { class: "rows" }, perfect.map(function (g) {
        return h("li", null, gameLink(g.appid, g.name, gameIcon(g, 24)),
          h("span", { class: "num muted", text: g.achievements.last_unlock ? date(g.achievements.last_unlock) : "" }));
      })));
      main.appendChild(done);
    }
  }

  /* ================================================================== friends */

  var FRIEND_SORTS = {
    name: function (a, b) { return L.collator.compare(a.name || "", b.name || ""); },
    since: function (a, b) { return (a.friend_since || 0) - (b.friend_since || 0); },
    newest: function (a, b) { return (b.friend_since || 0) - (a.friend_since || 0); },
    level: function (a, b) { return (b.level || 0) - (a.level || 0); },
    country: function (a, b) { return L.collator.compare(country(a.country) || "~", country(b.country) || "~"); }
  };

  function viewFriends(main, snap, route) {
    main.appendChild(heading(t("web.nav.friends"), t("web.friends.lede", { count: snap.friends.length })));
    add(main, sectionNote(snap, "friends"));
    if (!snap.friends.length) return;
    var countries = {};
    var levels = [];
    var banned = 0;
    var perYear = {};
    snap.friends.forEach(function (f) {
      if (f.country) countries[f.country] = (countries[f.country] || 0) + 1;
      if (f.level !== null && f.level !== undefined) levels.push(f.level);
      if (f.bans && (f.bans.vac_bans || f.bans.game_bans)) banned += 1;
      if (f.friend_since) {
        var year = new Date(f.friend_since * 1000).getFullYear();
        perYear[year] = (perYear[year] || 0) + 1;
      }
    });
    var oldest = snap.friends.filter(function (f) { return f.friend_since; }).sort(FRIEND_SORTS.since)[0];
    main.appendChild(facts([
      { label: t("web.fact.friends"), value: num(snap.friends.length) },
      oldest ? { label: t("web.friends.oldest"), value: oldest.name, note: t("web.friends.since", { date: date(oldest.friend_since) }) } : null,
      { label: t("web.friends.countries"), value: num(Object.keys(countries).length) },
      levels.length ? { label: t("web.friends.average_level"), value: L.dec1.format(levels.reduce(function (a, b) { return a + b; }, 0) / levels.length) } : null,
      { label: t("web.friends.online"), value: num(snap.friends.filter(function (f) { return f.state; }).length), note: t("web.friends.at_snapshot") },
      banned ? { label: t("web.friends.banned"), value: num(banned) } : null
    ]));
    var state = {
      q: route.params.get("q") || "",
      sort: FRIEND_SORTS[route.params.get("sort")] ? route.params.get("sort") : "name"
    };
    var holder = h("div");
    function refresh() {
      setParams({ q: state.q || null, sort: state.sort === "name" ? null : state.sort });
      var needle = fold(state.q);
      var rows = snap.friends.filter(function (f) {
        return !needle || fold(f.name).indexOf(needle) >= 0 || fold(f.realname).indexOf(needle) >= 0 || fold(country(f.country)).indexOf(needle) >= 0;
      }).sort(FRIEND_SORTS[state.sort]);
      clear(holder);
      holder.appendChild(rows.length ? friendsTable(rows, snap) : empty(t("web.friends.none")));
    }
    var search = h("input", { type: "search", value: state.q, placeholder: t("web.friends.search"), "aria-label": t("web.friends.search") });
    search.addEventListener("input", function () { state.q = search.value; refresh(); });
    main.appendChild(h("div", { class: "toolbar" }, search,
      h("label", null, h("span", { text: t("web.games.sort") }), select("sort", state.sort, Object.keys(FRIEND_SORTS).map(function (k) { return [k, t("web.friends.sort_by." + k)]; }), function (v) { state.sort = v; refresh(); }))));
    main.appendChild(holder);
    refresh();

    var grid = h("div", { class: "grid" });
    var years = Object.keys(perYear).map(Number).sort(function (a, b) { return a - b; });
    if (years.length) {
      var items = [];
      for (var y = years[0]; y <= years[years.length - 1]; y++) items.push({ label: String(y), value: perYear[y] || 0, tip: String(y) });
      var added = section(t("web.friends.per_year"));
      added.appendChild(C.columns({ items: items, format: function (v) { return t("web.friends.count", { count: v }); }, axis: num, every: Math.ceil(items.length / 10), table: t("web.table_view"), headers: [t("web.col.year"), t("web.fact.friends")] }));
      grid.appendChild(added);
    }
    var top = Object.keys(countries).sort(function (a, b) { return countries[b] - countries[a] || L.collator.compare(country(a), country(b)); }).slice(0, 10);
    if (top.length) {
      var where = section(t("web.friends.top_countries"));
      where.appendChild(C.bars({ items: top.map(function (code) { return { label: country(code), value: countries[code] }; }), format: num }));
      grid.appendChild(where);
    }
    main.appendChild(grid);
  }

  function friendsTable(rows, snap) {
    return h("div", { class: "table-wrap" }, h("table", { class: "data" },
      h("thead", null, h("tr", null,
        h("th", { scope: "col", text: t("web.col.friend") }),
        h("th", { scope: "col", text: t("web.col.country") }),
        h("th", { scope: "col", class: "num", text: t("web.col.level") }),
        h("th", { scope: "col", class: "num", text: t("web.col.friends_since") }),
        h("th", { scope: "col", class: "num", text: t("web.col.account_age") }),
        h("th", { scope: "col", text: t("web.col.status") }))),
      h("tbody", null, rows.map(function (f) {
        var status = f.playing ? t("web.friends.playing", { game: f.playing.name || String(f.playing.appid) }) : t("data.state." + (f.state || 0));
        var bans = f.bans && (f.bans.vac_bans || f.bans.game_bans) ? chip(t("web.friends.ban_chip"), "warn") : null;
        return h("tr", null,
          h("td", null, h("div", { class: "cell-game" }, image(f.avatar, 32, "avatar"), h("div", null,
            external(f.profile_url, f.name || f.steamid), f.realname ? h("span", { class: "muted small", text: f.realname }) : null, bans))),
          h("td", { text: country(f.country) }),
          h("td", { class: "num" }, f.level !== null && f.level !== undefined ? levelRing(f.level) : ""),
          h("td", { class: "num" }, f.friend_since ? h("span", { title: date(f.friend_since), text: duration(f.friend_since, snap.when) }) : ""),
          h("td", { class: "num", text: f.created ? duration(f.created, snap.when) : "" }),
          h("td", { class: f.state ? "online" : "muted", text: status }));
      }))));
  }

  /* ================================================================== profile */

  function viewProfile(main, snap) {
    var p = snap.profile;
    var frame = (p.equipped || {}).avatar_frame;
    var portrait = h("div", { class: "portrait" }, image(p.avatar, 128, "avatar big"), frame ? image(frame.image, 160, "frame") : null);
    main.appendChild(h("header", { class: "profile-head" }, portrait, h("div", null,
      h("h1", { text: p.personaname || p.steamid }),
      p.realname ? h("p", { class: "lede", text: p.realname }) : null,
      p.country ? h("p", { class: "muted", text: country(p.country) }) : null,
      p.profile_url ? h("p", null, external(p.profile_url, t("web.profile.open_steam"))) : null)));

    var xp = p.xp;
    var levelBlock = section(t("web.profile.level"));
    var levelRow = h("div", { class: "level-row" }, levelRing(p.level, true));
    if (xp) {
      var next = xp.current + xp.to_next;
      var progress = next > xp.level_start ? (xp.current - xp.level_start) / (next - xp.level_start) * 100 : 0;
      levelRow.appendChild(h("div", { class: "xp" },
        h("p", { text: t("web.profile.xp", { xp: num(xp.current), next: num(xp.to_next) }) }),
        C.meter(progress, percent(progress))));
    }
    levelBlock.appendChild(levelRow);
    if (p.level_percentile) levelBlock.appendChild(h("p", { class: "muted", text: t("web.overview.percentile", { value: percent(p.level_percentile) }) }));
    main.appendChild(levelBlock);

    var account = section(t("web.profile.account"));
    var ids = [
      ["SteamID64", p.steamid], ["SteamID3", p.steamid3], ["SteamID", p.steamid2],
      [t("web.profile.account_id"), p.account_id], [t("web.profile.custom_url"), p.custom_url]
    ];
    var rows = ids.filter(function (r) { return r[1] !== null && r[1] !== undefined && r[1] !== ""; }).map(function (r) { return [r[0], h("code", { text: String(r[1]) })]; });
    rows.push([t("web.profile.created"), p.created ? date(p.created) + " (" + duration(p.created, snap.when) + ")" : "–"]);
    rows.push([t("web.profile.last_online"), p.last_online ? dateTime(p.last_online) : "–"]);
    rows.push([t("web.profile.visibility"), t("data.visibility." + (p.visibility || 0))]);
    rows.push([t("web.profile.comments"), t(p.comments ? "web.yes" : "web.no")]);
    rows.push([t("web.fact.status"), t("data.state." + (p.state || 0)) + (p.playing ? " (" + (p.playing.name || p.playing.appid) + ")" : "")]);
    if (p.bans) {
      var b = p.bans;
      var clean = !b.vac_bans && !b.game_bans && !b.community_banned && (!b.economy_ban || b.economy_ban === "none");
      rows.push([t("web.profile.bans"), clean ? t("web.profile.no_bans") : t("web.profile.bans_detail", { vac: b.vac_bans, game: b.game_bans, days: b.days_since_last_ban })]);
    }
    account.appendChild(h("dl", { class: "pairs" }, rows.map(function (r) { return h("div", null, h("dt", { text: r[0] }), h("dd", null, r[1])); })));
    main.appendChild(account);

    var badges = section(t("web.profile.badges", { count: snap.badges.length }));
    add(badges, sectionNote(snap, "badges"));
    if (snap.badges.length) {
      badges.appendChild(h("ul", { class: "badges" }, snap.badges.map(function (badge) {
        var key = "data.badge." + badge.badgeid;
        var name = !badge.appid && has(key) ? t(key) : badge.name || (badge.appid ? t("web.profile.badge_app", { appid: badge.appid }) : t("web.profile.badge_id", { id: badge.badgeid }));
        return h("li", null,
          h("strong", { text: name }),
          h("span", { text: t("web.profile.badge_level", { level: badge.level, xp: num(badge.xp) }) }),
          badge.foil ? chip(t("web.profile.foil")) : null,
          badge.earned ? h("span", { class: "muted small", text: date(badge.earned) }) : null,
          badge.scarcity ? h("span", { class: "muted small", text: t("web.profile.scarcity", { count: badge.scarcity }) }) : null);
      })));
    }
    main.appendChild(badges);

    var groups = p.groups || [];
    var groupBlock = section(t("web.profile.groups", { count: groups.length }));
    add(groupBlock, sectionNote(snap, "groups"));
    if (groups.length) {
      groupBlock.appendChild(h("ul", { class: "rows" }, groups.map(function (g) {
        return h("li", null,
          h("span", { class: "cell-game" }, image(g.avatar, 32, "avatar"), external(g.url, g.name || g.gid), g.primary ? chip(t("web.profile.primary")) : null),
          h("span", { class: "num muted", text: g.members ? t("web.profile.members", { count: g.members }) : "" }));
      })));
    }
    main.appendChild(groupBlock);

    var equipped = Object.keys(p.equipped || {});
    if (equipped.length) {
      var items = section(t("web.profile.equipped"));
      items.appendChild(h("ul", { class: "rows" }, equipped.map(function (slot) {
        var item = p.equipped[slot];
        return h("li", null, h("span", { class: "cell-game" }, image(item.image, 48, "item"), h("span", { text: item.name })), h("span", { class: "muted", text: t("data.equipped." + slot) }));
      })));
      main.appendChild(items);
    }
  }

  /* ================================================================== history */

  function viewHistory(main) {
    main.appendChild(heading(t("web.nav.history"), t("web.history.lede", { count: SNAPSHOTS.length })));
    if (SNAPSHOTS.length > 1) {
      var charts = section(t("web.history.over_time"), t("web.history.over_time_note"));
      var grid = h("div", { class: "grid small" });
      var metrics = [
        ["playtime", t("web.history.metric.playtime"), hours, hoursAxis, 60],
        ["achievements", t("web.history.metric.achievements"), num, num],
        ["games", t("web.history.metric.games"), num, num],
        ["friends", t("web.history.metric.friends"), num, num],
        ["level", t("web.history.metric.level"), num, num],
        ["badges", t("web.history.metric.badges"), num, num]
      ];
      metrics.forEach(function (m) {
        var points = SNAPSHOTS.filter(function (s) { return s.summary && s.summary[m[0]] !== null && s.summary[m[0]] !== undefined; }).map(function (s) {
          return { t: new Date(s.collected_at), v: s.summary[m[0]], label: snapshotDate(s) };
        });
        if (points.length < 2) return;
        var box = h("div", { class: "small-chart" }, h("h3", { text: m[1] }));
        box.appendChild(C.line({ points: points, format: m[2], axis: m[3], xlabel: function (d) { return L.date.format(d); }, label: m[1], unit: m[4], height: 150, table: t("web.table_view"), headers: [t("web.col.date"), m[1]] }));
        grid.appendChild(box);
      });
      charts.appendChild(grid);
      main.appendChild(charts);
    }

    var names = [];
    var avatars = [];
    SNAPSHOTS.forEach(function (s) {
      var summary = s.summary || {};
      if (summary.persona && (!names.length || names[names.length - 1].name !== summary.persona)) names.push({ name: summary.persona, from: s });
      if (summary.avatar && (!avatars.length || avatars[avatars.length - 1].src !== summary.avatar)) avatars.push({ src: summary.avatar, from: s });
    });
    if (names.length > 1 || avatars.length > 1) {
      var identity = section(t("web.history.identity"));
      if (names.length > 1) {
        identity.appendChild(h("ul", { class: "rows" }, names.slice().reverse().map(function (n) {
          return h("li", null, h("span", { text: n.name }), h("span", { class: "num muted", text: t("web.history.first_seen", { date: snapshotDate(n.from) }) }));
        })));
      }
      if (avatars.length > 1) {
        identity.appendChild(h("ul", { class: "avatars" }, avatars.slice().reverse().map(function (a) {
          return h("li", null, image(a.src, 64, "avatar"), h("span", { class: "muted small", text: snapshotDate(a.from) }));
        })));
      }
      main.appendChild(identity);
    }

    var list = section(t("web.history.snapshots"));
    var body = h("tbody");
    SNAPSHOTS.slice().reverse().forEach(function (s) {
      var index = snapshotIndex(s.id);
      var previous = index > 0 ? SNAPSHOTS[index - 1] : null;
      var summary = s.summary || {};
      var chips = changeChips(s.changes, null);
      body.appendChild(h("tr", null,
        h("td", null, h("a", { href: "#/overview" + (s.id === latestId() ? "" : "?at=" + encodeURIComponent(s.id)), text: snapshotDate(s) })),
        h("td", { class: "num", text: num(summary.games) }),
        h("td", { class: "num", text: hours(summary.playtime || 0) }),
        h("td", { class: "num", text: num(summary.achievements) }),
        h("td", { class: "num", text: num(summary.friends) }),
        h("td", { class: "num" }, levelRing(summary.level)),
        h("td", null, h("div", { class: "chips" }, chips.length ? chips : (previous ? h("span", { class: "muted small", text: t("diff.none") }) : null))),
        h("td", null, previous ? h("a", { href: "#/compare?from=" + encodeURIComponent(previous.id) + "&to=" + encodeURIComponent(s.id), text: t("web.history.compare_previous") }) : null)));
    });
    list.appendChild(h("div", { class: "table-wrap" }, h("table", { class: "data" },
      h("thead", null, h("tr", null,
        h("th", { scope: "col", text: t("web.col.date") }),
        h("th", { scope: "col", class: "num", text: t("web.col.games") }),
        h("th", { scope: "col", class: "num", text: t("web.col.playtime") }),
        h("th", { scope: "col", class: "num", text: t("web.col.achievements") }),
        h("th", { scope: "col", class: "num", text: t("web.fact.friends") }),
        h("th", { scope: "col", class: "num", text: t("web.col.level") }),
        h("th", { scope: "col", text: t("web.col.changes") }),
        h("th", { scope: "col", text: "" }))),
      body)));
    main.appendChild(list);
  }

  /* ================================================================== compare */

  function comparePair(route) {
    var from = route.params.get("from");
    var to = route.params.get("to");
    if (snapshotIndex(to) < 0) to = latestId();
    if (snapshotIndex(from) < 0) from = SNAPSHOTS.length > 1 ? SNAPSHOTS[snapshotIndex(to) > 0 ? snapshotIndex(to) - 1 : 0].id : to;
    if (snapshotIndex(from) > snapshotIndex(to)) { var swap = from; from = to; to = swap; }
    return [from, to];
  }

  function viewCompare(main, snap, route, snaps) {
    var pair = comparePair(route);
    main.appendChild(heading(t("web.nav.compare"), t("web.compare.lede")));
    if (SNAPSHOTS.length < 2) {
      main.appendChild(empty(t("web.compare.need_two"), t("web.empty.hint")));
      return;
    }
    function picker(name, value) {
      return select(name, value, SNAPSHOTS.map(function (s) { return [s.id, snapshotDate(s)]; }).reverse(), function (v) {
        var next = name === "from" ? [v, pair[1]] : [pair[0], v];
        location.hash = "#/compare?from=" + encodeURIComponent(next[0]) + "&to=" + encodeURIComponent(next[1]);
      });
    }
    var changes = window.SteamLedgerDiff.compare(snaps[0], snaps[1]);
    var download = h("button", { type: "button", class: "button", text: t("web.compare.download") });
    download.addEventListener("click", function () {
      var blob = new Blob([JSON.stringify(changes, null, 2)], { type: "application/json" });
      var link = h("a", { href: URL.createObjectURL(blob), download: pair[0] + "__" + pair[1] + ".json" });
      document.body.appendChild(link);
      link.click();
      setTimeout(function () { URL.revokeObjectURL(link.href); link.remove(); }, 1000);
    });
    main.appendChild(h("div", { class: "toolbar" },
      h("label", null, h("span", { text: t("web.compare.from") }), picker("from", pair[0])),
      h("label", null, h("span", { text: t("web.compare.to") }), picker("to", pair[1])),
      download));
    if (pair[0] === pair[1]) {
      main.appendChild(empty(t("web.compare.same")));
      return;
    }
    var days = (new Date(changes.to.collected_at) - new Date(changes.from.collected_at)) / 86400000;
    main.appendChild(h("p", { class: "lede", text: t("web.compare.period", { days: days < 1 ? t("units.hours_long", { count: Math.max(1, Math.round(days * 24)) }) : t("units.days", { count: Math.round(days) }) }) }));
    var chips = changeChips(changes.summary, changes.level);
    main.appendChild(chips.length ? h("div", { class: "chips" }, chips) : empty(t("diff.none")));
    renderChanges(main, changes, snaps[1]);
  }

  function renderChanges(main, d, after) {
    function block(key, count) {
      var node = section(t("diff.section." + key) + (count ? " (" + num(count) + ")" : ""));
      main.appendChild(node);
      return node;
    }
    if (d.profile.length) {
      var p = block("profile");
      p.appendChild(h("dl", { class: "pairs" }, d.profile.map(function (c) {
        return h("div", null, h("dt", { text: t("data.profile_field." + c.field) }), h("dd", { class: "change" }, value(c.field, c.from), h("span", { class: "arrow", "aria-hidden": "true", text: "→" }), value(c.field, c.to)));
      })));
    }
    if (d.level || d.xp) {
      var lv = block("level");
      lv.appendChild(h("p", null,
        d.level ? h("span", { class: "change" }, levelRing(d.level.from), h("span", { class: "arrow", "aria-hidden": "true", text: "→" }), levelRing(d.level.to)) : null,
        d.xp ? h("span", { class: "muted", text: " " + t("diff.xp", { value: signed(d.xp.to - d.xp.from) }) }) : null));
    }
    if (d.playtime.length) {
      var pt = block("playtime", d.playtime.length);
      pt.appendChild(C.bars({
        diverging: true,
        items: d.playtime.map(function (r) {
          return { label: r.name, value: r.delta, href: href("game", r.appid), icon: gameIcon(after.gameMap[r.appid], 20), note: hours(r.from) + " → " + hours(r.to) };
        }),
        format: signedHours
      }));
    }
    if (d.games_added.length) {
      var ga = block("games_added", d.games_added.length);
      ga.appendChild(h("ul", { class: "rows" }, d.games_added.map(function (g) {
        return h("li", null, gameLink(g.appid, g.name, gameIcon(after.gameMap[g.appid], 24)), h("span", { class: "num muted", text: g.playtime ? hours(g.playtime) : "" }));
      })));
    }
    if (d.games_removed.length) {
      var gr = block("games_removed", d.games_removed.length);
      gr.appendChild(h("ul", { class: "rows" }, d.games_removed.map(function (g) { return h("li", null, h("span", { text: g.name })); })));
    }
    if (d.achievements.length) {
      var total = d.achievements.reduce(function (s, g) { return s + g.items.length; }, 0);
      var ac = block("achievements", total);
      d.achievements.forEach(function (group) {
        ac.appendChild(h("h3", null, h("a", { href: href("game", group.appid), text: group.name }), " ", h("span", { class: "muted", text: "(" + num(group.items.length) + ")" })));
        var local = after.achievements[String(group.appid)];
        var lookup = {};
        ((local || {}).unlocked || []).forEach(function (u) { lookup[u.apiname] = u; });
        ac.appendChild(h("ul", { class: "unlocks" }, group.items.map(function (item) {
          var full = lookup[item.apiname] || item;
          return unlockRow({ appid: group.appid, game: group.name, item: full }, false);
        })));
      });
    }
    if (d.achievements_lost.length) {
      var lost = block("achievements_lost");
      lost.appendChild(h("ul", { class: "rows" }, d.achievements_lost.map(function (g) {
        return h("li", null, h("span", { text: g.name + ": " + g.items.map(function (i) { return i.name; }).join(", ") }));
      })));
    }
    if (d.completed.length) {
      var cp = block("completed", d.completed.length);
      cp.appendChild(h("ul", { class: "rows" }, d.completed.map(function (g) { return h("li", null, gameLink(g.appid, g.name, gameIcon(after.gameMap[g.appid], 24))); })));
    }
    [["friends_added", d.friends_added], ["friends_removed", d.friends_removed]].forEach(function (pair) {
      if (!pair[1].length) return;
      var node = block(pair[0], pair[1].length);
      node.appendChild(h("ul", { class: "rows" }, pair[1].map(function (f) {
        return h("li", null, h("span", { class: "cell-game" }, image(f.avatar, 28, "avatar"), h("span", { text: f.name || f.steamid })),
          f.friend_since ? h("span", { class: "num muted", text: date(f.friend_since) }) : null);
      })));
    });
    if (d.friends_renamed.length) {
      var rn = block("friends_renamed", d.friends_renamed.length);
      rn.appendChild(h("ul", { class: "rows" }, d.friends_renamed.map(function (r) {
        return h("li", null, h("span", { class: "change" }, h("span", { text: r.from }), h("span", { class: "arrow", "aria-hidden": "true", text: "→" }), h("span", { text: r.to })));
      })));
    }
    var badgeLines = d.badges_added.map(function (b) { return t("diff.badge_new", { name: badgeName(b), level: b.level }); })
      .concat(d.badges_changed.map(function (b) { return t("diff.badge_level", { name: badgeName(b), from: b.from, to: b.to }); }));
    if (badgeLines.length) {
      var bd = block("badges", badgeLines.length);
      bd.appendChild(h("ul", { class: "rows" }, badgeLines.map(function (line) { return h("li", { text: line }); })));
    }
    var wish = d.wishlist_added.map(function (w) { return ["+", w]; }).concat(d.wishlist_removed.map(function (w) { return ["−", w]; }));
    if (wish.length) {
      var wl = block("wishlist", wish.length);
      wl.appendChild(h("ul", { class: "rows" }, wish.map(function (pair) { return h("li", null, h("span", { class: pair[0] === "+" ? "up" : "down", text: pair[0] + " " }), h("span", { text: pair[1].name })); })));
    }
    var groups = d.groups_joined.map(function (g) { return ["+", g]; }).concat(d.groups_left.map(function (g) { return ["−", g]; }));
    if (groups.length) {
      var gp = block("groups", groups.length);
      gp.appendChild(h("ul", { class: "rows" }, groups.map(function (pair) { return h("li", null, h("span", { class: pair[0] === "+" ? "up" : "down", text: pair[0] + " " }), h("span", { text: pair[1].name || pair[1].gid })); })));
    }
    if (d.bans.length) {
      var bn = block("bans");
      bn.appendChild(h("dl", { class: "pairs" }, d.bans.map(function (c) {
        return h("div", null, h("dt", { text: t("data.ban_field." + c.field) }), h("dd", { class: "change" }, value("", c.from), h("span", { class: "arrow", "aria-hidden": "true", text: "→" }), value("", c.to)));
      })));
    }
    if (d.unavailable.length) {
      main.appendChild(h("p", { class: "notice", text: t("diff.unavailable", { sections: d.unavailable.map(function (n) { return t("data.section_name." + n); }).join(", ") }) }));
    }
  }

  function badgeName(b) {
    var key = "data.badge." + b.badgeid;
    if (!b.appid && has(key)) return t(key);
    return b.name || (b.appid ? t("web.profile.badge_app", { appid: b.appid }) : t("web.profile.badge_id", { id: b.badgeid }));
  }

  function value(field, raw) {
    if (raw === null || raw === undefined || raw === "") return h("span", { class: "muted", text: "–" });
    if (field === "avatar") return image(raw, 48, "avatar");
    if (field === "visibility") return h("span", { text: t("data.visibility." + raw) });
    if (field === "country") return h("span", { text: country(raw) });
    if (typeof raw === "boolean") return h("span", { text: t(raw ? "web.yes" : "web.no") });
    return h("span", { text: String(raw) });
  }

  /* ================================================================== boot */

  function setupControls() {
    var lang = document.getElementById("lang");
    clear(lang);
    LANGS.forEach(function (code) {
      lang.appendChild(h("option", { value: code, selected: code === L.code ? true : null, text: I18N[code].name || code }));
    });
    lang.onchange = function () { setLanguage(lang.value); render(); };
    var theme = document.getElementById("theme");
    theme.value = load("theme") || "auto";
    theme.onchange = function () {
      var choice = theme.value;
      save("theme", choice);
      if (choice === "auto") document.documentElement.removeAttribute("data-theme");
      else document.documentElement.setAttribute("data-theme", choice);
      C.drawMounted();
    };
  }

  setLanguage(pickLanguage());
  setupControls();
  window.addEventListener("hashchange", render);
  render();
})();
