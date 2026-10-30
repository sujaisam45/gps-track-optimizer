/* UI for the GPS Track Optimizer page. Algorithms live in core.js (window.GTO). */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const PRESETS = {
    rtk_fix:   { tol: 0.5,  radius: 1.5, mindur: 5,  maxv: 0.25 },
    rtk_float: { tol: 0.75, radius: 1.5, mindur: 5,  maxv: 0.25 },
    phone:     { tol: 3.0,  radius: 5.0, mindur: 10, maxv: 0.25 },
  };

  const state = { raw: null, truth: null, name: "", demo: null, result: null, fit: true };

  /* ---------- language ---------- */
  const DICT = window.GTO_I18N;
  let lang = "en";
  function t(key, vars = {}) {
    let s = (DICT[lang] && DICT[lang][key]) ?? DICT.en[key] ?? key;
    s = s.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? vars[k] : `{${k}}`));
    // French typography: non-breaking space before : ; % ? !
    if (lang === "fr") s = s.replace(/ ([:;%?!])/g, "\u00a0$1");
    return s;
  }
  function pickInitialLang() {
    const h = location.hash.replace("#", "").toLowerCase();
    if (h === "fr" || h === "en") return h;
    try { const v = localStorage.getItem("gto-lang"); if (v === "fr" || v === "en") return v; } catch (e) { /* storage blocked */ }
    const langs = navigator.languages || [navigator.language || "en"];
    return langs.some((l) => /^fr/i.test(l)) ? "fr" : "en";
  }
  function applyStaticText() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll("[data-i18n-html]").forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
    document.querySelectorAll("[data-i18n-aria]").forEach((el) => el.setAttribute("aria-label", t(el.dataset.i18nAria)));
    const md = document.getElementById("meta-desc"); if (md) md.setAttribute("content", t("meta.description"));
    document.querySelectorAll('input[name="lang"]').forEach((el) => { el.checked = el.value === lang; });
  }
  function setLang(next, remember) {
    lang = next;
    if (remember) { try { localStorage.setItem("gto-lang", next); } catch (e) { /* storage blocked */ } }
    applyStaticText();
    showSliderValues();
    if (loadedMsg) $("loaded").textContent = loadedMsg();
    if (errorMsg) $("error").textContent = errorMsg();
    if (state.result) { drawMap(); renderResult(); renderMetrics(); renderFunnel(); renderChart(); renderStops(); }
  }
  let loadedMsg = null, errorMsg = null;
  function showError(fn) { errorMsg = fn; $("error").textContent = fn ? fn() : ""; }

  /* ---------- formatting ---------- */
  const nf = (v, d) => v.toLocaleString(lang === "fr" ? "fr-FR" : "en-GB", { minimumFractionDigits: d, maximumFractionDigits: d });
  const fmtInt = (n) => nf(Math.round(n), 0);
  const fmtM = (v, d = 2) => (v === null || v === undefined || !Number.isFinite(v) ? "–" : `${nf(v, d)}\u00a0m`);
  const fmtKB = (b) => (b < 1024 ? `${b}\u00a0${t("unit.B")}` : `${nf(b / 1024, 1)}\u00a0${t("unit.KB")}`);
  const fmtClock = (s) => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60; return (h ? `${h}:${String(m).padStart(2, "0")}` : `${m}`) + `:${String(r).padStart(2, "0")}`; };
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  /* ---------- map ---------- */
  const map = L.map("map", { preferCanvas: true, zoomSnap: 0.5 });
  map.setView([49.4429, 1.0884], 17);
  const dark = window.matchMedia("(prefers-color-scheme: dark)");
  let tiles = null;
  function setTiles() {
    if (tiles) map.removeLayer(tiles);
    const style = dark.matches ? "dark_all" : "light_all";
    tiles = L.tileLayer(`https://{s}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}{r}.png`, {
      maxZoom: 22, maxNativeZoom: 20, subdomains: "abcd",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    }).addTo(map);
  }
  setTiles();

  const layers = { truth: L.layerGroup(), cleaned: L.layerGroup(), recorded: L.layerGroup(), stops: L.layerGroup() };
  Object.values(layers).forEach((l) => l.addTo(map));
  let hoverMarker = null;

  function bySegment(points) {
    const m = new Map();
    for (const p of points) { const k = p.track + "|" + p.segment; if (!m.has(k)) m.set(k, []); m.get(k).push(p); }
    return [...m.values()];
  }

  function drawMap() {
    const r = state.result, C = { rec: css("--recorded"), cl: css("--cleaned"), st: css("--stop"), tr: css("--truth"), pan: css("--panel") };
    const view = document.querySelector('input[name="view"]:checked').value;
    const showRec = view !== "cleaned", showClean = view !== "recorded";
    Object.values(layers).forEach((l) => l.clearLayers());
    // Draw order = stacking order: true path, cleaned line, recorded fixes, cleaned vertices, stops.
    if (state.truth && $("showtruth").checked) {
      L.polyline(state.truth, { color: C.tr, weight: 1.5, dashArray: "5 4", opacity: 0.85, interactive: false }).addTo(layers.truth);
    }
    const finalSegs = bySegment(r.final);
    if (showClean) for (const seg of finalSegs) {
      const ll = seg.map((p) => [p.lat, p.lon]);
      L.polyline(ll, { color: C.pan, weight: 8, opacity: 0.9, interactive: false }).addTo(layers.cleaned);
      L.polyline(ll, { color: C.cl, weight: 4, interactive: false }).addTo(layers.cleaned);
    }
    if (showRec) {
      for (const seg of bySegment(r.validated)) {
        L.polyline(seg.map((p) => [p.lat, p.lon]), { color: C.rec, weight: 1.2, opacity: showClean ? 0.5 : 0.8, interactive: false }).addTo(layers.recorded);
      }
      if (r.validated.length <= 8000) {
        for (const p of r.validated) L.circleMarker([p.lat, p.lon], { radius: 1.8, stroke: false, fillColor: C.rec, fillOpacity: 0.8, interactive: false }).addTo(layers.recorded);
      }
    }
    if (showClean) for (const seg of finalSegs) {
      for (const p of seg) L.circleMarker([p.lat, p.lon], { radius: 4.5, color: C.pan, weight: 1.5, fillColor: C.cl, fillOpacity: 1, interactive: false }).addTo(layers.cleaned);
    }
    stopMarkers = [];
    if (showClean) r.stationary.filter((p) => p.isStop).forEach((p, i) => {
      const secs = (p.stopEnd - p.stopStart) / 1000;
      const m = L.circleMarker([p.lat, p.lon], { radius: 11, color: C.st, weight: 2.5, fillColor: C.st, fillOpacity: 0.3 })
        .bindTooltip(t("stop.tooltip", { i: i + 1, s: Math.round(secs), n: p.stopPoints }), { direction: "top", offset: [0, -10] })
        .addTo(layers.stops);
      stopMarkers.push(m);
    });
    if (state.fit) {
      map.fitBounds(L.latLngBounds(r.validated.map((p) => [p.lat, p.lon])), { padding: [40, 40], maxZoom: 20 });
      state.fit = false;
    }
  }
  let stopMarkers = [];

  document.querySelectorAll('input[name="view"]').forEach((el) => el.addEventListener("change", () => state.result && drawMap()));

  /* ---------- settings ---------- */
  const sliders = {
    tol: { el: $("tol"), out: $("tol-out"), fmt: (v) => fmtM(+v) },
    radius: { el: $("radius"), out: $("radius-out"), fmt: (v) => (+v === 0 ? t("off") : fmtM(+v, 1)) },
    mindur: { el: $("mindur"), out: $("mindur-out"), fmt: (v) => `${v}\u00a0s` },
    maxv: { el: $("maxv"), out: $("maxv-out"), fmt: (v) => `${nf(+v, 2)}\u00a0m/s` },
  };
  function showSliderValues() { for (const s of Object.values(sliders)) s.out.textContent = s.fmt(s.el.value); }
  function applyPreset(key) {
    const p = PRESETS[key];
    if (!p) return;
    for (const k of Object.keys(sliders)) sliders[k].el.value = p[k];
    document.querySelector(`input[name="preset"][value="${key}"]`).checked = true;
    showSliderValues();
  }
  document.querySelectorAll('input[name="preset"]').forEach((el) =>
    el.addEventListener("change", () => { if (el.value !== "custom") { applyPreset(el.value); schedule(); } }));
  for (const s of Object.values(sliders)) {
    s.el.addEventListener("input", () => {
      document.querySelector('input[name="preset"][value="custom"]').checked = true;
      showSliderValues(); schedule();
    });
  }
  $("keepstops").addEventListener("change", schedule);
  $("showtruth").addEventListener("change", () => state.result && drawMap());

  let pending = false;
  function schedule() {
    if (pending || !state.raw) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; compute(); });
  }

  /* ---------- load ---------- */
  function demoRaw(key) {
    const s = window.GTO_SAMPLES[key], t0 = Date.parse(s.start);
    return s.points.map(([t, la, lo, e]) => ({ track: 0, segment: 0, time: t0 + Math.round(t * 1000), lat: la === null ? NaN : la, lon: lo === null ? NaN : lo, ele: e, speed: NaN }));
  }
  function loadDemo(key) {
    state.raw = demoRaw(key);
    state.truth = window.GTO_SAMPLES[key].truth;
    state.demo = key;
    state.name = `simulated ${key}`;
    state.fit = true;
    document.querySelectorAll("[data-demo]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.demo === key)));
    showError(null);
    loadedMsg = () => t("loaded.demo", { noise: t(`noise.${key}`) });
    $("loaded").textContent = loadedMsg();
    $("truth-wrap").hidden = false;
    document.querySelector(".truth-key").hidden = false;
    applyPreset(key);
    compute();
  }
  document.querySelectorAll("[data-demo]").forEach((b) => b.addEventListener("click", () => loadDemo(b.dataset.demo)));

  async function loadFile(file) {
    showError(null);
    if (!file) return;
    if (file.size > 50 * 1024 * 1024) { showError(() => t("err.tooBig")); return; }
    try {
      const pts = GTO.parseGpx(await file.text());
      state.raw = pts; state.truth = null; state.demo = null; state.name = file.name; state.fit = true;
      document.querySelectorAll("[data-demo]").forEach((b) => b.setAttribute("aria-pressed", "false"));
      $("truth-wrap").hidden = true;
      document.querySelector(".truth-key").hidden = true;
      const segs = new Set(pts.map((p) => p.track + "|" + p.segment)).size;
      loadedMsg = () => t("loaded.file", { name: file.name, n: fmtInt(pts.length), s: segs, segs: t(segs > 1 ? "segments" : "segment") });
      $("loaded").textContent = loadedMsg();
      compute();
    } catch (e) {
      showError(() => t("err.read", { name: file.name, msg: e.code ? t(`err.${e.code}`) : e.message }));
    }
  }
  $("file").addEventListener("change", (e) => loadFile(e.target.files[0]));
  const drop = $("drop");
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => loadFile(e.dataTransfer.files[0]));
  // Allow dropping anywhere on the page.
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => { e.preventDefault(); if (e.dataTransfer.files[0]) loadFile(e.dataTransfer.files[0]); });

  /* ---------- run + render ---------- */
  function compute() {
    const cfg = {
      tolerance: +sliders.tol.el.value,
      keepStops: $("keepstops").checked,
      stop: { radius: +sliders.radius.el.value, minDuration: +sliders.mindur.el.value, maxSpeed: +sliders.maxv.el.value },
    };
    try {
      state.result = GTO.run(state.raw, cfg, state.truth);
    } catch (e) {
      showError(() => (e.code ? t(`err.${e.code}`) : e.message));
      return;
    }
    drawMap(); renderResult(); renderMetrics(); renderFunnel(); renderChart(); renderStops();
  }

  let announceTimer = null;
  function renderResult() {
    const m = state.result.metrics;
    const v = { raw: fmtInt(m.rawPoints), final: fmtInt(m.finalPoints) };
    $("result-line").innerHTML = t("result.line", v);
    const stops = m.stopsDetected === 0 ? t("stops.zero") : m.stopsDetected === 1 ? t("stops.one") : t("stops.many", { n: m.stopsDetected });
    $("result-sub").textContent = t("result.sub", { pct: nf(m.reductionPct, 1), stops, dev: fmtM(m.maxDeviationM) });
    clearTimeout(announceTimer);
    announceTimer = setTimeout(() => {
      $("announce").textContent = `${t("result.plain", v)} ${$("result-sub").textContent}`;
    }, 700);
  }

  function renderMetrics() {
    const m = state.result.metrics, v = state.result.validation;
    const rows = [
      ["m.max", fmtM(m.maxDeviationM)],
      ["m.mean", fmtM(m.meanDeviationM)],
      ["m.haus", fmtM(m.hausdorffM)],
      ["m.jitter", fmtM(m.stopJitterMaxM)],
      ["m.len", `${nf(m.originalLengthM, 1)} → ${fmtM(m.cleanedLengthM, 1)}`],
    ];
    if (m.truthMeanErrorM !== null) rows.push(["m.truth", `${fmtM(m.originalTruthMeanErrorM)} → ${fmtM(m.truthMeanErrorM)}`]);
    rows.push(
      ["m.size", `${fmtKB(m.originalGpxBytes)} → ${fmtKB(m.cleanedGpxBytes)}`],
      ["m.removed", fmtInt(v.missingCoords + v.invalidCoords + v.missingTime + v.duplicates + v.speedOutliers)],
      ["m.time", `${m.processingMs < 10 ? nf(m.processingMs, 1) : fmtInt(m.processingMs)}\u00a0ms`],
    );
    $("metrics").innerHTML = rows.map(([k, d]) => `<dt>${t(k)}<small>${t(k + ".s")}</small></dt><dd>${d}</dd>`).join("");
  }

  function renderFunnel() {
    const m = state.result.metrics;
    const per = m.rawPoints > 900 ? Math.ceil(m.rawPoints / 900) : 1;
    const steps = [
      [t("f.recorded"), m.rawPoints, css("--recorded")],
      [t("f.checked"), m.validatedPoints, css("--graphite")],
      [t("f.stops"), m.afterStationaryPoints, css("--graphite")],
      [t("f.simplified"), m.finalPoints, css("--cleaned")],
    ];
    const box = $("funnel");
    box.innerHTML = steps.map(([n, c]) => `<div class="funnel-row"><span class="name">${n}</span><span class="count">${fmtInt(c)}</span><canvas></canvas></div>`).join("");
    const width = box.clientWidth || 340, cell = 6, dot = 4, cols = Math.max(10, Math.floor(width / cell));
    const dpr = window.devicePixelRatio || 1;
    box.querySelectorAll("canvas").forEach((cv, i) => {
      const n = Math.ceil(steps[i][1] / per), rows = Math.max(1, Math.ceil(n / cols));
      cv.width = width * dpr; cv.height = rows * cell * dpr; cv.style.height = rows * cell + "px";
      const ctx = cv.getContext("2d");
      ctx.scale(dpr, dpr); ctx.fillStyle = steps[i][2];
      for (let k = 0; k < n; k++) {
        ctx.beginPath();
        ctx.arc((k % cols) * cell + dot / 2, Math.floor(k / cols) * cell + dot / 2, dot / 2, 0, Math.PI * 2);
        ctx.fill();
      }
    });
    $("funnel-note").textContent = per === 1 ? t("f.note.one") : t("f.note.many", { n: per });
  }

  /* deviation chart */
  let chartState = null;
  function renderChart() {
    const r = state.result, prof = [];
    let offset = 0, lastSeg = null, segEnd = 0;
    for (const p of r.profile) {
      if (p.seg !== lastSeg) { offset = segEnd; lastSeg = p.seg; }
      prof.push({ ...p, x: offset + p.dist });
      segEnd = offset + p.dist;
    }
    const box = $("chart");
    if (!prof.length) { box.innerHTML = `<p class="empty">${t("chart.empty")}</p>`; return; }
    const W = 640, H = 250, P = { l: 42, r: 12, t: 22, b: 44 };
    const xmax = prof[prof.length - 1].x || 1;
    const tol = r.config.tolerance;
    const ymax = Math.max(tol * 1.25, Math.max(...prof.map((p) => p.dev)) * 1.1, 0.05);
    const X = (v) => P.l + (v / xmax) * (W - P.l - P.r), Y = (v) => H - P.b - (v / ymax) * (H - P.t - P.b);
    const nice = (max, n) => { const raw = max / n, mag = 10 ** Math.floor(Math.log10(raw)); const f = raw / mag; return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag; };
    const xs = nice(xmax, 6), ys = nice(ymax, 4);
    const yDec = ys < 0.1 ? 2 : ys < 1 ? 1 : 0;
    let g = "";
    for (let v = 0; v <= ymax + 1e-9; v += ys) g += `<line x1="${P.l}" x2="${W - P.r}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${P.l - 6}" y="${Y(v) + 4}" text-anchor="end">${nf(v, yDec)}</text>`;
    for (let v = 0; v <= xmax + 1e-9; v += xs) g += `<text x="${X(v)}" y="${H - P.b + 16}" text-anchor="middle">${Math.round(v)}</text>`;
    let shade = "", start = null;
    prof.forEach((p, i) => {
      if (p.inStop && start === null) start = p.x;
      if ((!p.inStop || i === prof.length - 1) && start !== null) {
        const end = p.inStop ? p.x : prof[i - 1].x;
        shade += `<rect x="${X(start) - 1}" y="${P.t}" width="${Math.max(2, X(end) - X(start) + 2)}" height="${H - P.t - P.b}" fill="var(--stop)" opacity=".2"/>`;
        start = null;
      }
    });
    const path = prof.map((p, i) => `${i ? "L" : "M"}${X(p.x).toFixed(1)},${Y(p.dev).toFixed(1)}`).join("");
    box.innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${t("chart.aria", { max: fmtM(r.metrics.maxDeviationM), tol: fmtM(tol) })}">
        <g class="axis">${g}<text x="${(P.l + W - P.r) / 2}" y="${H - 6}" text-anchor="middle">${t("chart.x")}</text><text x="${P.l - 6}" y="${P.t - 10}" text-anchor="start" dx="-30">${t("chart.y")}</text></g>
        ${shade}
        <line x1="${P.l}" x2="${W - P.r}" y1="${Y(tol)}" y2="${Y(tol)}" stroke="var(--cleaned)" stroke-width="1.5" stroke-dasharray="6 4"/>
        <text x="${W - P.r}" y="${Y(tol) - 5}" text-anchor="end" fill="var(--cleaned)" font-size="11" font-weight="700">${t("chart.tol", { v: fmtM(tol) })}</text>
        <path d="${path}" fill="none" stroke="var(--ink)" stroke-width="1.2" stroke-linejoin="round"/>
        <line id="ch-cursor" y1="${P.t}" y2="${H - P.b}" stroke="var(--ink)" stroke-width="1" visibility="hidden"/>
        <circle id="ch-dot" r="4" fill="var(--recorded)" stroke="var(--panel)" stroke-width="1.5" visibility="hidden"/>
        <rect id="ch-hit" x="${P.l}" y="${P.t}" width="${W - P.l - P.r}" height="${H - P.t - P.b}" fill="transparent"/>
      </svg>
      <div class="tip" hidden></div>`;
    chartState = { prof, X, Y, W };
    const svg = box.querySelector("svg"), hit = box.querySelector("#ch-hit");
    const pick = (clientX) => {
      const rect = svg.getBoundingClientRect();
      const vx = ((clientX - rect.left) / rect.width) * W;
      const target = ((vx - P.l) / (W - P.l - P.r)) * xmax;
      let lo = 0, hi = prof.length - 1;
      while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (prof[mid].x < target) lo = mid; else hi = mid; }
      return Math.abs(prof[lo].x - target) < Math.abs(prof[hi].x - target) ? lo : hi;
    };
    hit.addEventListener("pointermove", (e) => showChartPoint(pick(e.clientX)));
    hit.addEventListener("pointerdown", (e) => showChartPoint(pick(e.clientX)));
    svg.addEventListener("pointerleave", hideChartPoint);
  }
  function showChartPoint(i) {
    const { prof, X, Y, W } = chartState, p = prof[i], box = $("chart"), svg = box.querySelector("svg");
    const cx = X(p.x), cy = Y(p.dev);
    const cur = svg.querySelector("#ch-cursor"), dot = svg.querySelector("#ch-dot");
    cur.setAttribute("x1", cx); cur.setAttribute("x2", cx); cur.setAttribute("visibility", "visible");
    dot.setAttribute("cx", cx); dot.setAttribute("cy", cy); dot.setAttribute("visibility", "visible");
    const tip = box.querySelector(".tip"), scale = svg.getBoundingClientRect().width / W;
    tip.hidden = false;
    tip.style.left = `${Math.min(Math.max(cx * scale, 70), svg.getBoundingClientRect().width - 70)}px`;
    tip.style.top = `${cy * scale}px`;
    tip.textContent = t("chart.tip", { d: fmtInt(p.x), dev: fmtM(p.dev) }) + (p.inStop ? t("chart.inStop") : "");
    if (!hoverMarker) hoverMarker = L.circleMarker([p.lat, p.lon], { radius: 7, color: css("--ink"), weight: 2.5, fillColor: css("--recorded"), fillOpacity: 1, interactive: false }).addTo(map);
    else hoverMarker.setLatLng([p.lat, p.lon]);
  }
  function hideChartPoint() {
    const box = $("chart");
    box.querySelectorAll("#ch-cursor, #ch-dot").forEach((e) => e.setAttribute("visibility", "hidden"));
    const tip = box.querySelector(".tip"); if (tip) tip.hidden = true;
    if (hoverMarker) { map.removeLayer(hoverMarker); hoverMarker = null; }
  }

  function renderStops() {
    const r = state.result, stops = r.stationary.filter((p) => p.isStop);
    const t0 = Math.min(...r.validated.map((p) => p.time));
    $("stops-lede").textContent = state.demo ? t("stops.lede.demo") : t("stops.lede.file");
    if (!stops.length) {
      $("stops").innerHTML = `<p class="empty">${t("stops.none")} ${+sliders.radius.el.value === 0 ? t("stops.none.off") : t("stops.none.try")}</p>`;
      return;
    }
    $("stops").innerHTML = `<table><thead><tr><th scope="col">${t("th.stop")}</th><th scope="col">${t("th.starts")}</th><th scope="col" class="num">${t("th.lasted")}</th><th scope="col" class="num">${t("th.merged")}</th><th scope="col"><span class="sr-only">${t("th.map")}</span></th></tr></thead><tbody>${
      stops.map((p, i) => `<tr><td>${i + 1}</td><td>${t("stops.into", { t: fmtClock((p.stopStart - t0) / 1000) })}</td><td class="num">${Math.round((p.stopEnd - p.stopStart) / 1000)}\u00a0s</td><td class="num">${p.stopPoints}</td><td><button type="button" data-stop="${i}">${t("stops.show")}</button></td></tr>`).join("")
    }</tbody></table>`;
    $("stops").querySelectorAll("[data-stop]").forEach((b) => b.addEventListener("click", () => {
      const s = stops[+b.dataset.stop];
      map.setView([s.lat, s.lon], 20);
      stopMarkers[+b.dataset.stop]?.openTooltip();
      $("map").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
    }));
  }

  /* ---------- downloads ---------- */
  function download(text, name, type) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  const baseName = () => (state.demo ? `simulated_${state.demo}` : state.name.replace(/\.gpx$/i, ""));
  $("dl-gpx").addEventListener("click", () => state.result && download(GTO.toGpx(state.result.final, `${baseName()} cleaned`), `${baseName()}_cleaned.gpx`, "application/gpx+xml"));
  $("dl-csv").addEventListener("click", () => {
    if (!state.result) return;
    const m = { source: state.name, ...state.result.metrics, stopRadiusM: state.result.config.stop.radius, stopMinDurationS: state.result.config.stop.minDuration, stopMaxSpeedMps: state.result.config.stop.maxSpeed };
    const keys = Object.keys(m);
    const cell = (v) => (typeof v === "number" ? +v.toFixed(4) : v === null ? "" : `"${String(v).replace(/"/g, '""')}"`);
    download(keys.join(",") + "\n" + keys.map((k) => cell(m[k])).join(",") + "\n", `${baseName()}_metrics.csv`, "text/csv");
  });

  /* ---------- theme changes ---------- */
  dark.addEventListener("change", () => { setTiles(); if (state.result) { drawMap(); renderFunnel(); } });
  let rz = null;
  window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => state.result && renderFunnel(), 150); });

  /* ---------- start ---------- */
  const live = document.createElement("p");
  live.id = "announce"; live.className = "sr-only"; live.setAttribute("aria-live", "polite");
  document.body.appendChild(live);
  $("result-line").removeAttribute("aria-live");
  document.querySelectorAll('input[name="lang"]').forEach((el) => el.addEventListener("change", () => setLang(el.value, true)));
  window.addEventListener("hashchange", () => { const h = location.hash.slice(1).toLowerCase(); if ((h === "fr" || h === "en") && h !== lang) setLang(h, false); });
  lang = pickInitialLang();
  applyStaticText();
  loadDemo("rtk_float");
})();
