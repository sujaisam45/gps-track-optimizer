// Run the JS port on the same demo walks as Python and compare every metric.
//   NODE_PATH=<dir with proj4> node web/crosscheck.js
const fs = require("fs");
const path = require("path");
const GTO = require("./src/core.js");

const samples = JSON.parse(fs.readFileSync(path.join(__dirname, "src/samples.json"), "utf8"));
const ref = JSON.parse(fs.readFileSync(path.join(__dirname, "python_reference.json"), "utf8"));

const toRaw = (s) => {
  const t0 = Date.parse(s.start);
  return s.points.map(([t, lat, lon, ele]) => ({
    track: 0, segment: 0, time: t0 + Math.round(t * 1000),
    lat: lat === null ? NaN : lat, lon: lon === null ? NaN : lon, ele, speed: NaN,
  }));
};

const pairs = [
  ["rawPoints", "raw_points", 0], ["validatedPoints", "validated_points", 0],
  ["afterStationaryPoints", "after_stationary_points", 0], ["finalPoints", "final_points", 0],
  ["stopsDetected", "stops_detected", 0], ["pointsInStops", "points_in_stops", 0],
  ["maxDeviationM", "max_deviation_m", 0.002], ["meanDeviationM", "mean_deviation_m", 0.002],
  ["hausdorffM", "hausdorff_m", 0.002], ["stopJitterMaxM", "stop_jitter_max_m", 0.002],
  ["originalLengthM", "original_length_m", 0.02], ["cleanedLengthM", "cleaned_length_m", 0.02],
  ["truthMaxErrorM", "truth_max_error_m", 0.002], ["truthMeanErrorM", "truth_mean_error_m", 0.002],
  ["originalTruthMeanErrorM", "original_truth_mean_error_m", 0.002],
];

let fails = 0, checks = 0;
for (const [key, py] of Object.entries(ref)) {
  const [noise, tol, rad] = key.split("|");
  const s = samples[noise];
  const r = GTO.run(toRaw(s), { tolerance: +tol, stop: { radius: +rad } }, s.truth);
  const bad = [];
  for (const [js, pk, eps] of pairs) {
    checks++;
    if (Math.abs(r.metrics[js] - py[pk]) > eps) bad.push(`${js}: js=${r.metrics[js].toFixed(4)} py=${py[pk]}`);
  }
  if (bad.length) { fails += bad.length; console.log("MISMATCH", key, bad.join("; ")); }
}
console.log(`${checks - fails}/${checks} metric checks match Python across ${Object.keys(ref).length} runs`);
process.exit(fails ? 1 : 0);
// Note: needs `npm i proj4` somewhere on NODE_PATH, e.g. `npm i proj4 && node web/crosscheck.js`
