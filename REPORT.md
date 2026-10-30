# Technical evaluation: cleaning pedestrian GPS/RTK traces

**Author:** Sujai Samraj · **Date:** 30 Oct 2026
**Data used:** SYNTHETIC walks only (no real recording yet). Every number below
comes from `python main.py --synthetic` and is reproducible. Results on a real
recorded walk will be added in a separate section, clearly labelled.

## 1. The problem

When a walking trace is recorded, the receiver stores a fix every second.
While the walker waits at a crossing, the fixes keep arriving and scatter
around the same spot. The trace ends up with hundreds of points that carry no
route information, and the jitter adds fake distance to the route.

## 2. Method

| Step | What it does | Why |
|---|---|---|
| 1. Validate | Drop missing/invalid coordinates and timestamps, duplicates, and single-fix jumps faster than 4 m/s | Multipath spikes would otherwise become "corners" |
| 2. Project | WGS84 → UTM 31N (EPSG:32631, metres) | A 0.5 m tolerance is meaningless in degrees |
| 3. Collapse stops | A group of fixes is a stop if all stay within 1.5 m of the group centre for ≥ 5 s **and** net drift < 0.25 m/s. The group becomes one point at the median position, with start/end time kept | Speed alone fails: jitter looks like motion, and careful walking can be slow |
| 4. Douglas–Peucker | Per segment, tolerance 0.5–1 m, stop points always kept | Removes points on straight stretches; corners are always the furthest points, so they survive |
| 5. Evaluate | Deviation of every moving original fix from the cleaned line; Hausdorff distance; length; GPX size; and, for synthetic data, error against the **true** path | Fewer points is not a success if the route moved |

## 3. Test data (synthetic)

One 505 m route near Place du Vieux-Marché, Rouen: 7 legs with right angles
and one diagonal, one leg walked slowly (0.45 m/s), three stops of 30, 45 and
20 s, 1 % missing fixes and 2 multipath spikes of 30 m. Sampled at 1 Hz
(625 fixes). Noise is time-correlated (AR(1), 10 s), at three quality levels:
RTK fix (σ ≈ 2 cm), RTK float (σ ≈ 30 cm), phone GNSS (σ ≈ 3 m).

## 4. Results (synthetic)

| GNSS quality | Tolerance | Points before → after | Reduction | Stops found | Max deviation from recording | Mean error vs true path, before → after |
|---|---|---|---|---|---|---|
| RTK fix | 0.5 m | 625 → 8 | 98.7 % | 3 / 3 | 0.05 m | 0.016 → 0.008 m |
| RTK float | 0.5 m | 625 → 34 | 94.6 % | 3 / 3 | 0.50 m | 0.24 → 0.20 m |
| RTK float | 0.75 m | 625 → 12 | 98.1 % | 3 / 3 | 0.75 m | 0.24 → 0.16 m |
| RTK float | 1.0 m | 625 → 8 | 98.7 % | 3 / 3 | 0.77 m | 0.24 → 0.11 m |
| Phone | 3.0 m | 625 → 96 | 84.6 % | 1 / 3 | 2.96 m | 2.42 → 2.42 m |

Other measurements (RTK float, 0.75 m):

- **Storage:** GPX file shrinks by 97.7 %. For the app this mainly means
  lighter routes to sync and fewer points for the route editor to handle.
- **Route length:** raw trace 530.6 m, true route 505.2 m, cleaned 505.5 m.
  Jitter had added 5 % of fake distance; cleaning removed it.
- **Speed:** about 40 ms for 625 fixes in Python, including validation.

## 5. Answers to the key questions

**How many points were removed?** 94–99 % with RTK data, depending on the
tolerance. These figures are an upper bound: the synthetic route is made of
straight streets. A real route with curves keeps more points.

**How accurate is the cleaned route?** No moving fix is further from the
cleaned line than the tolerance (this is guaranteed by Douglas–Peucker and
checked by the tests). Against the true path, the cleaned RTK-float route is
*more* accurate on average than the raw recording (0.16 m vs 0.24 m), because
straight segments average out the jitter.

**How does stop detection help?** With Douglas–Peucker alone, RTK-float
gives 14 points and a mean error of 0.215 m. With stops collapsed first: 12
points and 0.162 m (25 % lower error). The bigger gains are not in the point
count: each stop becomes a recorded event (where, when, how long), and the
stop detector can run point by point *during* recording, while Douglas–Peucker
needs the finished trace. Using the median instead of the mean for the stop
position cut the stop-position error on RTK fix from 0.19 m to 0.03 m.

**How does Douglas–Peucker keep corners?** It joins the two ends of a stretch
and keeps the point furthest from that line if it is further than the
tolerance, then repeats on both halves. A corner is always the furthest point
of its stretch, so it is always kept; points along a straight street never
exceed the tolerance, so they are dropped.

## 6. Limitations

- **Synthetic data only so far.** The noise model is my own; the parameters
  (1.5 m radius, 5 s, 0.25 m/s) have not been tuned on real SonarVision traces.
- **Phone-grade GNSS is out of scope.** With ~3 m noise only 1 of 3 stops was
  found, and no amount of simplification fixes a 2.4 m average error. The
  method targets RTK data (fix and float), which is what produced the bug.
- **Tolerance must exceed the noise.** In RTK float, a 0.5 m tolerance keeps
  34 points because the jitter itself crosses the threshold.
- **Systematic errors are not corrected.** A receiver that is consistently
  0.5 m to one side stays 0.5 m to one side.
- **Stops at corners:** the stop point replaces the corner. Fine here, but a
  stop in the middle of a curve could shift the curve slightly.

## 7. How it could fit into SonarVision

1. **During recording (iOS app):** port the stop detector (≈ 40 lines) to
   Swift so stationary fixes are never stored. This addresses the roadmap item
   on too many points in traces directly.
2. **When the trace is saved (server or app):** run Douglas–Peucker with a
   tolerance chosen from the receiver's reported solution (fix vs float).
3. **Keep stop events:** stops recorded at the same spot by several users may
   reveal crossings and waiting points worth adding to the route instructions.
4. **Validate on real traces** from RTK users before choosing default values.
