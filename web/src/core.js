/*
 * GPS Track Optimizer — browser port of the Python pipeline in /src.
 * Same steps, same defaults, same metrics. Cross-checked against the
 * Python results by web/crosscheck.js.
 *
 * Works in the browser (window.GTO) and in Node (module.exports).
 * Needs proj4 (global `proj4` in the browser, require('proj4') in Node).
 */
(function (root) {
  "use strict";
  const proj4lib = typeof proj4 !== "undefined" ? proj4 : (typeof require !== "undefined" ? require("proj4") : null);

  /* ---------- small helpers ---------- */
  const hyp = Math.hypot;
  const fail = (code, msg) => { const e = new Error(msg); e.code = code; throw e; };
  function median(arr) {
    const a = arr.filter((v) => Number.isFinite(v)).sort((p, q) => p - q);
    if (!a.length) return NaN;
    const m = a.length >> 1;
    return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
  }
  const mean = (a) => a.reduce((s, v) => s + v, 0) / a.length;
  function groupBySegment(points) {
    const map = new Map();
    for (const p of points) {
      const k = p.track + "|" + p.segment;
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(p);
    }
    return [...map.entries()]
      .sort((a, b) => { const [ta, sa] = a[0].split("|").map(Number); const [tb, sb] = b[0].split("|").map(Number); return ta - tb || sa - sb; })
      .map(([k, pts]) => ({ key: k, pts }));
  }

  /* ---------- projection: WGS84 <-> UTM metres ---------- */
  function makeProjector(lat, lon) {
    const zone = Math.floor((lon + 180) / 6) + 1;
    const south = lat < 0;
    const def = `+proj=utm +zone=${zone}${south ? " +south" : ""} +datum=WGS84 +units=m +no_defs`;
    const conv = proj4lib("EPSG:4326", def);
    return {
      epsg: (south ? 32700 : 32600) + zone,
      toXY: (la, lo) => conv.forward([lo, la]),
      toLatLon: (x, y) => { const r = conv.inverse([x, y]); return [r[1], r[0]]; },
    };
  }

  /* ---------- GPX in / out ---------- */
  function parseGpx(text) {
    const doc = new DOMParser().parseFromString(text, "application/xml");
    if (doc.getElementsByTagName("parsererror").length) fail("notXml", "This file is not valid GPX/XML.");
    const kid = (el, name) => { for (const c of el.children) if (c.localName === name) return c; return null; };
    const num = (v) => (v === null || v === undefined || v === "" ? NaN : Number(v));
    const readPoint = (el, track, segment) => {
      const timeEl = kid(el, "time"), eleEl = kid(el, "ele");
      let speed = NaN;
      const sp = kid(el, "speed");
      if (sp) speed = num(sp.textContent);
      else for (const e of el.getElementsByTagName("*")) if (/speed$/i.test(e.localName)) { speed = num(e.textContent); break; }
      return {
        track, segment,
        time: timeEl ? Date.parse(timeEl.textContent.trim()) : NaN,
        lat: num(el.getAttribute("lat")), lon: num(el.getAttribute("lon")),
        ele: eleEl ? num(eleEl.textContent) : NaN, speed,
      };
    };
    const pts = [];
    [...doc.getElementsByTagNameNS("*", "trk")].forEach((trk, ti) => {
      [...trk.children].filter((c) => c.localName === "trkseg").forEach((seg, si) => {
        for (const p of seg.children) if (p.localName === "trkpt") pts.push(readPoint(p, ti, si));
      });
    });
    if (!pts.length) {
      [...doc.getElementsByTagNameNS("*", "rte")].forEach((rte, ri) => {
        for (const p of rte.children) if (p.localName === "rtept") pts.push(readPoint(p, ri, 0));
      });
    }
    if (!pts.length) fail("noPoints", "No track points found. The file needs <trkpt> or <rtept> elements.");
    return pts;
  }

  function toGpx(points, name = "cleaned track") {
    const esc = (s) => String(s).replace(/[<>&"]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" }[c]));
    const out = ['<?xml version="1.0" encoding="UTF-8"?>',
      '<gpx version="1.1" creator="GPS Track Optimizer" xmlns="http://www.topografix.com/GPX/1/1">'];
    let curT = null, curS = null;
    const valid = points.filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));
    for (const p of valid) {
      if (p.track !== curT) {
        if (curT !== null) out.push("    </trkseg>", "  </trk>");
        out.push("  <trk>", `    <name>${esc(name)}</name>`, "    <trkseg>");
        curT = p.track; curS = p.segment;
      } else if (p.segment !== curS) {
        out.push("    </trkseg>", "    <trkseg>");
        curS = p.segment;
      }
      let s = `      <trkpt lat="${p.lat.toFixed(8)}" lon="${p.lon.toFixed(8)}">`;
      if (Number.isFinite(p.ele)) s += `<ele>${p.ele.toFixed(2)}</ele>`;
      if (Number.isFinite(p.time)) s += `<time>${new Date(p.time).toISOString()}</time>`;
      if (p.isStop) s += `<desc>Stop: ${Math.round((p.stopEnd - p.stopStart) / 1000)} s, ${p.stopPoints} fixes merged</desc>`;
      out.push(s + "</trkpt>");
    }
    if (curT !== null) out.push("    </trkseg>", "  </trk>");
    out.push("</gpx>");
    return out.join("\n");
  }

  /* ---------- 1. validation + projection + speed ---------- */
  function addMotion(points) {
    for (const { pts } of groupBySegment(points)) {
      pts.forEach((p, i) => {
        if (i === 0) { p.step = 0; p.dt = 0; p.speedEst = NaN; return; }
        const q = pts[i - 1];
        p.step = hyp(p.x - q.x, p.y - q.y);
        p.dt = (p.time - q.time) / 1000;
        p.speedEst = p.dt > 0 ? p.step / p.dt : NaN;
      });
    }
    return points;
  }

  function preprocess(raw, maxSpeed = 4.0) {
    const rep = { inputPoints: raw.length, missingCoords: 0, invalidCoords: 0, missingTime: 0, duplicates: 0, speedOutliers: 0, outputPoints: 0 };
    let pts = raw.map((p) => ({ ...p }));
    let n = pts.length;
    pts = pts.filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon)); rep.missingCoords = n - pts.length; n = pts.length;
    pts = pts.filter((p) => !(Math.abs(p.lat) > 90 || Math.abs(p.lon) > 180 || (p.lat === 0 && p.lon === 0))); rep.invalidCoords = n - pts.length; n = pts.length;
    pts = pts.filter((p) => Number.isFinite(p.time)); rep.missingTime = n - pts.length; n = pts.length;
    pts = pts.map((p, i) => ({ p, i })).sort((a, b) => a.p.track - b.p.track || a.p.segment - b.p.segment || a.p.time - b.p.time || a.i - b.i).map((o) => o.p);
    const seen = new Set();
    pts = pts.filter((p) => { const k = `${p.track}|${p.segment}|${p.time}`; if (seen.has(k)) return false; seen.add(k); return true; });
    rep.duplicates = n - pts.length;
    if (!pts.length) fail("noUsable", "No usable points: every point is missing a position or a timestamp.");

    const proj = makeProjector(median(pts.map((p) => p.lat)), median(pts.map((p) => p.lon)));
    for (const p of pts) [p.x, p.y] = proj.toXY(p.lat, p.lon);

    let removed = 0;
    for (let it = 0; it < 5; it++) {
      addMotion(pts);
      const spike = new Set();
      for (const { pts: seg } of groupBySegment(pts)) {
        seg.forEach((p, i) => {
          const nx = seg[i + 1];
          if (p.speedEst > maxSpeed && nx && nx.speedEst > maxSpeed) spike.add(p);
        });
      }
      if (!spike.size) break;
      removed += spike.size;
      pts = pts.filter((p) => !spike.has(p));
    }
    rep.speedOutliers = removed;
    addMotion(pts);
    for (const p of pts) p.speedUsed = Number.isFinite(p.speed) ? p.speed : (Number.isFinite(p.speedEst) ? p.speedEst : 0);
    rep.outputPoints = pts.length;
    return { points: pts, proj, report: rep };
  }

  /* ---------- 2. stationary detection ---------- */
  const DEFAULT_STOP = { radius: 1.5, minDuration: 5.0, maxSpeed: 0.25 };

  function findStationaryGroups(x, y, t, cfg) {
    const n = x.length, groups = [];
    let i = 0;
    while (i < n) {
      let j = i, sx = x[i], sy = y[i];
      while (j + 1 < n) {
        const k = j + 1, cnt = k - i + 1;
        const cx = (sx + x[k]) / cnt, cy = (sy + y[k]) / cnt;
        let dmax = 0;
        for (let m = i; m <= k; m++) { const d = hyp(x[m] - cx, y[m] - cy); if (d > dmax) dmax = d; }
        if (dmax > cfg.radius) break;
        sx += x[k]; sy += y[k]; j = k;
      }
      const dur = t[j] - t[i];
      if (j > i && dur >= cfg.minDuration && hyp(x[j] - x[i], y[j] - y[i]) / dur <= cfg.maxSpeed) {
        groups.push([i, j]); i = j + 1; continue;
      }
      i += 1;
    }
    // merge groups that are really one stop (see Python docstring)
    const merged = [];
    for (const [a, b] of groups) {
      if (merged.length) {
        const [pa, pb] = merged[merged.length - 1];
        const c1 = [mean(x.slice(pa, pb + 1)), mean(y.slice(pa, pb + 1))];
        const c2 = [mean(x.slice(a, b + 1)), mean(y.slice(a, b + 1))];
        if (a - pb - 1 <= 2 && hyp(c1[0] - c2[0], c1[1] - c2[1]) <= cfg.radius) { merged[merged.length - 1] = [pa, b]; continue; }
      }
      merged.push([a, b]);
    }
    return merged;
  }

  function collapseStationary(points, cfg, proj) {
    cfg = { ...DEFAULT_STOP, ...cfg };
    const out = [];
    for (const { pts } of groupBySegment(points)) {
      const t0 = pts[0].time;
      const x = pts.map((p) => p.x), y = pts.map((p) => p.y), t = pts.map((p) => (p.time - t0) / 1000);
      const groups = cfg.radius > 0 ? findStationaryGroups(x, y, t, cfg) : [];
      const rows = pts.map((p) => ({ ...p, isStop: false, stopStart: NaN, stopEnd: NaN, stopPoints: 1 }));
      const keep = new Array(rows.length).fill(true);
      for (const [a, b] of groups) {
        const block = rows.slice(a, b + 1);
        const r = rows[a];
        r.x = median(block.map((p) => p.x));
        r.y = median(block.map((p) => p.y));
        const eles = block.map((p) => p.ele).filter(Number.isFinite);
        r.ele = eles.length ? mean(eles) : NaN;
        r.isStop = true;
        r.stopStart = block[0].time;
        r.stopEnd = block[block.length - 1].time;
        r.stopPoints = block.length;
        r.time = r.stopStart + (r.stopEnd - r.stopStart) / 2;
        for (let m = a + 1; m <= b; m++) keep[m] = false;
      }
      rows.forEach((r, i) => { if (keep[i]) out.push(r); });
    }
    if (proj) for (const p of out) [p.lat, p.lon] = proj.toLatLon(p.x, p.y);
    return out;
  }

  /* ---------- 3. Douglas–Peucker ---------- */
  function segDist(px, py, ax, ay, bx, by) {
    const abx = bx - ax, aby = by - ay, L2 = abx * abx + aby * aby;
    if (L2 === 0) return hyp(px - ax, py - ay);
    let t = ((px - ax) * abx + (py - ay) * aby) / L2;
    t = t < 0 ? 0 : t > 1 ? 1 : t;
    return hyp(px - (ax + t * abx), py - (ay + t * aby));
  }

  function douglasPeuckerIndices(x, y, tol, forceKeep) {
    const n = x.length;
    if (n <= 2) return [...Array(n).keys()];
    const anchors = new Set([0, n - 1]);
    if (forceKeep) forceKeep.forEach((f, i) => { if (f) anchors.add(i); });
    const anc = [...anchors].sort((a, b) => a - b);
    const keep = new Uint8Array(n);
    anc.forEach((i) => (keep[i] = 1));
    const stack = [];
    for (let i = 0; i < anc.length - 1; i++) stack.push([anc[i], anc[i + 1]]);
    while (stack.length) {
      const [a, b] = stack.pop();
      if (b - a < 2) continue;
      let best = -1, bi = -1;
      for (let m = a + 1; m < b; m++) {
        const d = segDist(x[m], y[m], x[a], y[a], x[b], y[b]);
        if (d > best) { best = d; bi = m; }
      }
      if (best > tol) { keep[bi] = 1; stack.push([a, bi], [bi, b]); }
    }
    const idx = [];
    keep.forEach((k, i) => { if (k) idx.push(i); });
    return idx;
  }

  function simplifyTrack(points, tol, keepStops = true, proj) {
    const out = [];
    for (const { pts } of groupBySegment(points)) {
      const idx = douglasPeuckerIndices(pts.map((p) => p.x), pts.map((p) => p.y), tol, keepStops ? pts.map((p) => p.isStop) : null);
      idx.forEach((i) => out.push({ ...pts[i] }));
    }
    if (proj) for (const p of out) [p.lat, p.lon] = proj.toLatLon(p.x, p.y);
    return out;
  }

  /* ---------- 4. evaluation ---------- */
  function distToLine(px, py, line) {
    let best = Infinity;
    for (let i = 0; i < line.length - 1; i++) {
      const d = segDist(px, py, line[i][0], line[i][1], line[i + 1][0], line[i + 1][1]);
      if (d < best) best = d;
    }
    return best;
  }
  const lineLength = (line) => { let s = 0; for (let i = 1; i < line.length; i++) s += hyp(line[i][0] - line[i - 1][0], line[i][1] - line[i - 1][1]); return s; };
  function samplesAlong(line, step) {
    const out = [], L = lineLength(line);
    let seg = 0, segStart = 0;
    for (let s = 0; s < L; s += step) {
      while (seg < line.length - 2 && segStart + hyp(line[seg + 1][0] - line[seg][0], line[seg + 1][1] - line[seg][1]) < s) {
        segStart += hyp(line[seg + 1][0] - line[seg][0], line[seg + 1][1] - line[seg][1]); seg++;
      }
      const a = line[seg], b = line[seg + 1], l = hyp(b[0] - a[0], b[1] - a[1]);
      const f = l > 0 ? (s - segStart) / l : 0;
      out.push([a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])]);
    }
    return out;
  }

  function evaluate(raw, validated, stationary, final, procMs, tol, truthXY) {
    const stops = stationary.filter((p) => p.isStop);
    const moving = [], inStopD = [], haus = [], truthErr = [], origTruthErr = [], profile = [];
    const finalBySeg = new Map(groupBySegment(final).map((g) => [g.key, g.pts]));
    for (const { key, pts: oseg } of groupBySegment(validated)) {
      const fseg = finalBySeg.get(key) || [];
      if (fseg.length < 2) continue;
      const line = fseg.map((p) => [p.x, p.y]);
      const oline = oseg.map((p) => [p.x, p.y]);
      const segStops = stops.filter((s) => s.track + "|" + s.segment === key);
      let cum = 0, hmax = 0;
      oseg.forEach((p, i) => {
        if (i) cum += hyp(p.x - oseg[i - 1].x, p.y - oseg[i - 1].y);
        const d = distToLine(p.x, p.y, line);
        const inStop = segStops.some((s) => p.time >= s.stopStart && p.time <= s.stopEnd);
        (inStop ? inStopD : moving).push(d);
        profile.push({ dist: cum, dev: d, inStop, seg: key, lat: p.lat, lon: p.lon });
        if (d > hmax) hmax = d;
      });
      if (oline.length >= 2) for (const q of line) hmax = Math.max(hmax, distToLine(q[0], q[1], oline));
      haus.push(hmax);
      if (truthXY && key === "0|0") {
        for (const q of line) truthErr.push(distToLine(q[0], q[1], truthXY));
        for (const q of samplesAlong(line, 0.5)) truthErr.push(distToLine(q[0], q[1], truthXY));
        for (const q of oline) origTruthErr.push(distToLine(q[0], q[1], truthXY));
      }
    }
    const segLen = (pts) => groupBySegment(pts).reduce((s, g) => s + lineLength(g.pts.map((p) => [p.x, p.y])), 0);
    const nz = (a) => (a.length ? a : [0]);
    const maxOf = (a) => nz(a).reduce((m, v) => (v > m ? v : m), -Infinity);
    const ob = new Blob([toGpx(raw, "original track")]).size, cb = new Blob([toGpx(final)]).size;
    const res = {
      rawPoints: raw.length,
      validatedPoints: validated.length,
      afterStationaryPoints: stationary.length,
      finalPoints: final.length,
      reductionPct: 100 * (1 - final.length / Math.max(raw.length, 1)),
      stopsDetected: stops.length,
      pointsInStops: stops.reduce((s, p) => s + p.stopPoints, 0),
      originalLengthM: segLen(validated),
      cleanedLengthM: segLen(final),
      maxDeviationM: maxOf(moving),
      meanDeviationM: mean(nz(moving)),
      hausdorffM: haus.length ? maxOf(haus) : 0,
      stopJitterMaxM: maxOf(inStopD),
      originalGpxBytes: ob,
      cleanedGpxBytes: cb,
      sizeReductionPct: 100 * (1 - cb / Math.max(ob, 1)),
      processingMs: procMs,
      toleranceM: tol,
      truthMaxErrorM: null, truthMeanErrorM: null, originalTruthMeanErrorM: null,
    };
    if (truthErr.length) {
      res.truthMaxErrorM = maxOf(truthErr);
      res.truthMeanErrorM = mean(truthErr);
      res.originalTruthMeanErrorM = mean(nz(origTruthErr));
    }
    return { metrics: res, profile };
  }

  /* ---------- pipeline ---------- */
  function run(raw, cfg = {}, truthLatLon = null) {
    const c = { tolerance: 0.5, maxSpeed: 4.0, keepStops: true, stop: { ...DEFAULT_STOP }, ...cfg };
    c.stop = { ...DEFAULT_STOP, ...(cfg.stop || {}) };
    const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());
    const t0 = now();
    const pre = preprocess(raw, c.maxSpeed);
    const stat = collapseStationary(pre.points, c.stop, pre.proj);
    const fin = simplifyTrack(stat, c.tolerance, c.keepStops, pre.proj);
    const ms = now() - t0;
    const truthXY = truthLatLon ? truthLatLon.map(([la, lo]) => pre.proj.toXY(la, lo)) : null;
    const ev = evaluate(raw, pre.points, stat, fin, ms, c.tolerance, truthXY);
    return { config: c, validated: pre.points, stationary: stat, final: fin, proj: pre.proj, validation: pre.report, metrics: ev.metrics, profile: ev.profile };
  }

  const api = { parseGpx, toGpx, preprocess, collapseStationary, findStationaryGroups, douglasPeuckerIndices, simplifyTrack, evaluate, run, makeProjector, DEFAULT_STOP };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.GTO = api;
})(typeof window !== "undefined" ? window : globalThis);
