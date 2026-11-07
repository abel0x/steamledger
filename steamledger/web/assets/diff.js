/* SPDX-License-Identifier: Apache-2.0 */
/* Copyright 2026 abel0x <https://github.com/abel0x> */
/*
 * What changed between two snapshots - the same rules as steamledger/diff.py.
 * tests/test_diff.py runs both on the same input and requires identical output,
 * so keep the two in step. Lists are ordered by numbers and ids only, never by
 * names, so the result does not depend on the language.
 */
(function (root) {
  "use strict";

  var USABLE = ["ok", "empty", "partial"];
  var PROFILE_FIELDS = ["personaname", "realname", "avatar", "country", "custom_url", "visibility", "primary_group"];
  var BAN_FIELDS = ["vac_bans", "game_bans", "community_banned", "economy_ban"];

  function val(object, key) {
    return object && object[key] !== undefined ? object[key] : null;
  }

  function status(snapshot, name) {
    var sections = (snapshot.meta || {}).sections || {};
    var section = sections[name];
    return section && section.status ? String(section.status) : "ok";
  }

  function usable(a, b, name) {
    return USABLE.indexOf(status(a, name)) >= 0 && USABLE.indexOf(status(b, name)) >= 0;
  }

  function failed(snapshot) {
    var section = ((snapshot.meta || {}).sections || {}).achievements || {};
    return (section.failed || []).concat(section.hidden || []).map(Number);
  }

  function byNumber(a, b) { return a - b; }

  function byString(a, b) { return a < b ? -1 : a > b ? 1 : 0; }

  function keyed(list, key) {
    var map = {};
    (list || []).forEach(function (item) { map[item[key]] = item; });
    return map;
  }

  function minus(left, right) {
    return Object.keys(left).filter(function (k) { return !Object.prototype.hasOwnProperty.call(right, k); });
  }

  function both(left, right) {
    return Object.keys(left).filter(function (k) { return Object.prototype.hasOwnProperty.call(right, k); });
  }

  function achievement(item) {
    return {
      apiname: item.apiname,
      name: item.name || item.apiname,
      unlocktime: item.unlocktime || 0,
      percent: val(item, "percent"),
      icon: val(item, "icon")
    };
  }

  function byUnlock(a, b) {
    return a.unlocktime - b.unlocktime || byString(a.apiname, b.apiname);
  }

  function compare(a, b) {
    var pa = a.profile || {};
    var pb = b.profile || {};
    var unavailable = [];
    var result = {
      from: { id: val(a.meta, "id"), collected_at: val(a.meta, "collected_at") },
      to: { id: val(b.meta, "id"), collected_at: val(b.meta, "collected_at") }
    };

    result.profile = [];
    PROFILE_FIELDS.forEach(function (field) {
      if (field === "avatar") {
        if (val(pa, "avatar_hash") !== val(pb, "avatar_hash")) {
          result.profile.push({ field: "avatar", from: val(pa, "avatar_medium"), to: val(pb, "avatar_medium") });
        }
      } else if (val(pa, field) !== val(pb, field)) {
        result.profile.push({ field: field, from: val(pa, field), to: val(pb, field) });
      }
    });

    var la = val(pa, "level");
    var lb = val(pb, "level");
    result.level = la !== null && lb !== null && la !== lb ? { from: la, to: lb } : null;
    var xa = val(pa.xp, "current");
    var xb = val(pb.xp, "current");
    result.xp = xa !== null && xb !== null && xa !== xb ? { from: xa, to: xb } : null;

    /* games */
    var playtime = [];
    var added = [];
    var removed = [];
    if (usable(a, b, "games")) {
      var ga = keyed(a.games, "appid");
      var gb = keyed(b.games, "appid");
      minus(gb, ga).map(Number).sort(byNumber).forEach(function (appid) {
        var game = gb[appid];
        added.push({ appid: appid, name: game.name, playtime: game.playtime_forever || 0 });
      });
      minus(ga, gb).map(Number).sort(byNumber).forEach(function (appid) {
        removed.push({ appid: appid, name: ga[appid].name });
      });
      both(ga, gb).map(Number).forEach(function (appid) {
        var before = ga[appid].playtime_forever || 0;
        var after = gb[appid].playtime_forever || 0;
        if (before !== after) {
          playtime.push({ appid: appid, name: gb[appid].name, from: before, to: after, delta: after - before });
        }
      });
      playtime.sort(function (x, y) { return y.delta - x.delta || x.appid - y.appid; });
    } else {
      unavailable.push("games");
    }
    result.playtime = playtime;
    result.games_added = added;
    result.games_removed = removed;

    /* achievements */
    var unlocked = [];
    var lost = [];
    var completed = [];
    if (usable(a, b, "achievements") && usable(a, b, "games")) {
      var aa = a.achievements || {};
      var ab = b.achievements || {};
      var skip = failed(a).concat(failed(b));
      Object.keys(ab).map(Number).sort(byNumber).forEach(function (appid) {
        if (skip.indexOf(appid) >= 0) return;
        var after = ab[String(appid)];
        var before = aa[String(appid)] || {};
        var ea = keyed(before.unlocked, "apiname");
        var eb = keyed(after.unlocked, "apiname");
        var name = after.name || before.name || String(appid);
        var fresh = minus(eb, ea).map(function (k) { return achievement(eb[k]); }).sort(byUnlock);
        var gone = minus(ea, eb).map(function (k) { return achievement(ea[k]); }).sort(byUnlock);
        if (fresh.length) unlocked.push({ appid: appid, name: name, items: fresh });
        if (gone.length) lost.push({ appid: appid, name: name, items: gone });
        var totalAfter = after.total || 0;
        var totalBefore = before.total || 0;
        var perfectAfter = totalAfter > 0 && Object.keys(eb).length >= totalAfter;
        var perfectBefore = Object.keys(before).length > 0 && totalBefore > 0 && Object.keys(ea).length >= totalBefore;
        if (perfectAfter && !perfectBefore) completed.push({ appid: appid, name: name });
      });
    } else {
      unavailable.push("achievements");
    }
    result.achievements = unlocked;
    result.achievements_lost = lost;
    result.completed = completed;

    /* friends */
    var friendsAdded = [];
    var friendsRemoved = [];
    var renamed = [];
    if (usable(a, b, "friends")) {
      var fa = keyed(a.friends, "steamid");
      var fb = keyed(b.friends, "steamid");
      minus(fb, fa).sort(byString).forEach(function (id) {
        var f = fb[id];
        friendsAdded.push({ steamid: id, name: f.name || "", avatar: val(f, "avatar"), friend_since: val(f, "friend_since") });
      });
      minus(fa, fb).sort(byString).forEach(function (id) {
        var f = fa[id];
        friendsRemoved.push({ steamid: id, name: f.name || "", avatar: val(f, "avatar") });
      });
      both(fa, fb).sort(byString).forEach(function (id) {
        var oldName = fa[id].name || "";
        var newName = fb[id].name || "";
        if (oldName && newName && oldName !== newName) renamed.push({ steamid: id, from: oldName, to: newName });
      });
    } else {
      unavailable.push("friends");
    }
    result.friends_added = friendsAdded;
    result.friends_removed = friendsRemoved;
    result.friends_renamed = renamed;

    /* badges */
    var badgesAdded = [];
    var badgesChanged = [];
    if (usable(a, b, "badges")) {
      var key = function (badge) { return [badge.badgeid, badge.appid || 0, badge.foil ? 1 : 0]; };
      var tupleOrder = function (x, y) { return x[0] - y[0] || x[1] - y[1] || x[2] - y[2]; };
      var mapA = {};
      var mapB = {};
      (a.badges || []).forEach(function (x) { mapA[key(x).join(":")] = x; });
      (b.badges || []).forEach(function (x) { mapB[key(x).join(":")] = x; });
      var parse = function (k) { return k.split(":").map(Number); };
      minus(mapB, mapA).map(parse).sort(tupleOrder).forEach(function (k) {
        var x = mapB[k.join(":")];
        badgesAdded.push({ badgeid: x.badgeid, appid: val(x, "appid"), name: val(x, "name"), level: val(x, "level"), foil: !!x.foil });
      });
      both(mapA, mapB).map(parse).sort(tupleOrder).forEach(function (k) {
        var before = mapA[k.join(":")];
        var x = mapB[k.join(":")];
        if (val(before, "level") !== val(x, "level")) {
          badgesChanged.push({ badgeid: x.badgeid, appid: val(x, "appid"), name: val(x, "name"), foil: !!x.foil, from: val(before, "level"), to: val(x, "level") });
        }
      });
    } else {
      unavailable.push("badges");
    }
    result.badges_added = badgesAdded;
    result.badges_changed = badgesChanged;

    /* wishlist */
    var wishAdded = [];
    var wishRemoved = [];
    if (usable(a, b, "wishlist")) {
      var wa = keyed(a.wishlist, "appid");
      var wb = keyed(b.wishlist, "appid");
      wishAdded = minus(wb, wa).map(Number).sort(byNumber).map(function (i) { return { appid: i, name: wb[i].name || String(i) }; });
      wishRemoved = minus(wa, wb).map(Number).sort(byNumber).map(function (i) { return { appid: i, name: wa[i].name || String(i) }; });
    } else {
      unavailable.push("wishlist");
    }
    result.wishlist_added = wishAdded;
    result.wishlist_removed = wishRemoved;

    /* groups */
    var joined = [];
    var left = [];
    if (usable(a, b, "groups")) {
      var ra = keyed(pa.groups, "gid");
      var rb = keyed(pb.groups, "gid");
      joined = minus(rb, ra).sort(byString).map(function (g) { return { gid: g, name: val(rb[g], "name") }; });
      left = minus(ra, rb).sort(byString).map(function (g) { return { gid: g, name: val(ra[g], "name") }; });
    } else {
      unavailable.push("groups");
    }
    result.groups_joined = joined;
    result.groups_left = left;

    /* bans */
    var bans = [];
    var banA = pa.bans;
    var banB = pb.bans;
    if (banA && banB) {
      BAN_FIELDS.forEach(function (field) {
        if (val(banA, field) !== val(banB, field)) bans.push({ field: field, from: val(banA, field), to: val(banB, field) });
      });
    }
    result.bans = bans;

    result.unavailable = unavailable;
    result.summary = summary(result);
    return result;
  }

  function count(groups) {
    return groups.reduce(function (sum, group) { return sum + group.items.length; }, 0);
  }

  function summary(d) {
    var achievements = count(d.achievements);
    var lost = count(d.achievements_lost);
    var s = {
      playtime: d.playtime.reduce(function (sum, r) { return sum + r.delta; }, 0) + d.games_added.reduce(function (sum, g) { return sum + g.playtime; }, 0),
      games_played: d.playtime.filter(function (r) { return r.delta > 0; }).length,
      achievements: achievements,
      achievements_lost: lost,
      completed: d.completed.length,
      games_added: d.games_added.length,
      games_removed: d.games_removed.length,
      friends_added: d.friends_added.length,
      friends_removed: d.friends_removed.length,
      badges: d.badges_added.length + d.badges_changed.length,
      level: d.level ? d.level.to - d.level.from : 0,
      xp: d.xp ? d.xp.to - d.xp.from : 0,
      wishlist_added: d.wishlist_added.length,
      wishlist_removed: d.wishlist_removed.length,
      profile: d.profile.length
    };
    s.total = d.profile.length + (d.level ? 1 : 0) + (d.xp ? 1 : 0) + d.playtime.length + d.games_added.length +
      d.games_removed.length + achievements + lost + d.friends_added.length + d.friends_removed.length +
      d.friends_renamed.length + d.badges_added.length + d.badges_changed.length + d.wishlist_added.length +
      d.wishlist_removed.length + d.groups_joined.length + d.groups_left.length + d.bans.length;
    return s;
  }

  root.SteamLedgerDiff = { compare: compare };
})(typeof window !== "undefined" ? window : globalThis);
