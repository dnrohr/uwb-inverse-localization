# M0–M1 acceptance evidence

Completed October 13, 2026. Scope is the synchronized four-beacon, planar-tag,
shared-positive-height baseline. Existing handoff and requirements are preserved;
This is the historical M0–M1 record. M2 completion is documented separately in
[M2_ACCEPTANCE.md](M2_ACCEPTANCE.md); M3 and later remain unimplemented.

## Reproduce and launch

Use Python 3.12 from the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-lock.txt
.\.venv\Scripts\python -m unittest discover -s tests -v
.\.venv\Scripts\python scripts\validate.py
.\.venv\Scripts\python app.py
```

Open http://127.0.0.1:5050. Installation was performed into a newly created
project virtual environment. The tested direct versions are NumPy 2.5.4,
SciPy 1.18.1, Flask 3.1.3 and Plotly 7.1.0 on Python 3.12.10/Windows.
`requirements-lock.txt` records transitive versions. No CDN, cloud service,
Geomstats dependency, account, or external publication is required.

The server saves complete run envelopes under `runs/`, with atomic replacement.
At startup it copies bundled reference runs there once, without solving.
`scripts/validate.py` regenerates evidence but never overwrites user history.
Delete neither the reference observations nor failed starts when comparing fits.

## Numerical checks and declared tolerances

The full unittest suite passes **28 tests**. It checks independent distance
generation (`1e-12 m`), fixed-seed equality, per-beacon noise, constant-speed
reference sampling, lossless JSON round trips, input isolation, analytic weighted
Jacobians against central differences, proper rigid alignment, gauge and positive
bounds, true rank loss, and failed/nonconverged outcome retention. Service tests
assert reopening/importing never invokes the solver and malformed payloads are
rejected before corrupting history or entering the worker queue.

Exact recovery acceptance requires **every matched tag position and beacon error
below `1e-5 m`**, plus **maximum absolute original-range residual below `1e-7 m`**.
These are implementation tolerances, not noisy-data accuracy or confidence bounds.
The measurement Jacobian is normalized by assumed sigma and differentiated with
respect to dimensionless coordinates using the recorded common length scale.
Rank uses **`s > 1e-8 * s_max`**. A condition number over 1000 is a disclosed weak
geometry heuristic. See [NUMERICS.md](NUMERICS.md) for parameter units, objective,
initialization, solver tolerances, bounds, alignment and schema details.

`evidence/acceptance_summary.json` and ten full JSON runs in
`evidence/reference_runs/` preserve 28 attempted starts, including failures.
All measured geometry errors below are raw canonical errors, before alignment.

| Case (32 epochs, three starts unless noted) | Tag RMSE (m) | Map RMSE (m) | Truth rank | Evidence |
| --- | ---: | ---: | --- | --- |
| Exact joint, independent | 1.03e-15 | 9.04e-16 | 70/70 | `exact_joint_independent.json` |
| Exact joint, truth-near diagnostic | 8.79e-16 | 1.11e-16 | 70/70 | `exact_joint_truth_near.json` |
| Exact known map, independent | 7.10e-16 | 0 (survey fixed) | 64/64 | `exact_known_map.json` |
| Gaussian 0.05 m, measurement seed 7 | 0.0898 | 0.0990 | 70/70 | `noisy_joint_seed7.json` |
| Gaussian 0.05 m, measurement seed 8 | 0.1191 | 0.1553 | 70/70 | `noisy_joint_seed8.json` |
| Straight line, exact | 0.1134 | 0.1318 | 69/70 | `straight_line.json` |
| Narrow coverage, exact | ~1e-14 | ~1e-14 | 70/70 | `narrow_coverage.json` |
| Nearly collinear, exact selected start | ~1e-13 | ~1e-13 | 70/70 | `nearly_collinear.json` |
| One-evaluation cap, all nonconverged | 0.9474 | 1.2616 | 70/70 | `forced_nonconvergence.json` |
| Invalid negative-baseline diagnostic, one start | unavailable | unavailable | 70/70 | `failed_initialization.json` |

Measurement seed is 7 unless identified otherwise; initialization seed is 19.
Exact noise is zero while assumed sigma stays 0.05 m. All three informative exact
independent starts meet both tolerances. The largest tag error of the selected
independent exact joint fit is 2.60e-15 m; its largest beacon error is 9.49e-16 m.
Floating-point last digits and runtimes can vary across platforms.

The straight-line result has three distinct geometries with residuals near
machine precision. It demonstrates actual continuous ambiguity after gauge
fixing, rather than relying on equation counts. The informative condition number
is 41.44; narrow coverage is 1056.57 and nearly collinear is 10829.73. Two of three
nearly-collinear starts converge to wrong local minima (tag RMSE 6.83 m and
6.42 m). All attempts remain selectable. [MATH_REVIEW.md](MATH_REVIEW.md) records
the independent review, a constructive straight-line ambiguity, and an audit of
the original nine runs/27 starts. The additional invalid-start fixture uses the
already-tested failed-initialization path and explicitly declares its truth-based
diagnostic construction.

## Application and visual acceptance

Verified in the running in-app browser:

- An explicit Run generates an independently seeded result in the background,
  with running and final convergence status; the existing scene remains usable.
- Truth and estimated trajectories/beacons appear together, with B0–B3 IDs,
  separate sample markers and connecting visual guides, metre axes and equal
  spatial scale (`aspectmode: data`, fixed numeric axis ranges).
- Manual rotation, zoom, pan tools, Reset/Top/Side/3D views, and independent truth,
  estimate, initialization, error-vector, range-ray and two plane layers work.
  Segment layers are combined into one trace each to avoid repeated WebGL redraws.
- Manual camera rotation survives raw/aligned redraws. Proper planar alignment
  applies the same transform to estimates and initial guesses; scale remains one
  and reflections are disallowed. Known-map runs lock to the surveyed frame.
- Matched-time errors, map errors, signed metre residual distributions and
  per-beacon residuals, normalized residuals versus time, and truth/fit singular
  spectra render. Warnings appear beside the scene metrics. Every start and its
  solver evaluations/objectives/status remains inspectable; unavailable iteration
  counts and failed geometry show unavailable values instead of false zeros.
- Saved exact, noisy, degenerate and nonconverged results reopen. Exported JSON
  preserves the experiment and all start records exactly; browser import restores
  it. Automated service checks prove these operations do not solve again.
- Scene PNG export was downloaded, reopened and visually inspected. The exported
  scene has a white background. The complete UI uses local assets and system fonts.

Visual evidence is in `evidence/screenshots/`: `noisy_scene.jpg`,
`rotated_aligned.jpg`, `top_view.jpg`, `side_view.jpg`,
`straight_line_diagnostics.jpg`, `failed_run.jpg`, `app_full.jpg`, and
`known_map_scene.png`. Screenshots show the compact browser layout; on a wider
window the configuration and scene use the two-column layout.

## Performance and remaining limits

The 32-epoch, three-start informative cases take about 0.05–0.12 seconds for the
complete numerical wrapper here; narrow coverage about 0.2–0.3 seconds and nearly
collinear about 4–6 seconds. A separate 100-epoch, 0.05 m noise, three-start run
took 0.79 seconds (9/11/11 objective evaluations). These are local measurements,
not a cross-hardware performance guarantee. Jobs execute serially in a background
worker; scene interaction remains on the browser thread.

The application supports 8–100 samples, 1–12 starts, four complete synchronized
pings per epoch, fixed tag z=0, and one shared positive beacon height. Reference
paths use constant-speed polyline sampling (the narrow sinusoid is approximated
with a dense polyline). Injected and assumed per-beacon sigmas are supported by
the generator/API; GUI noise controls are global. The scene samples at most 20
error vectors and 45 fitted-endpoint range rays for clarity; calculations and
saved residuals use every observation.

The independent initializer is a plausible range-scaled map guess and a linear
position seed, not a globally reliable calibration algorithm. Positivity floors
exclude zero height and a collapsed first baseline. Full local rank and agreement
among finitely many starts cannot rule out other branches or continuous ambiguities.
Alignment supplies no metric scale, reflection, z shift or tilt correction.
Exact-reference acceptance flags deliberately do not classify useful noisy
accuracy. Numerical failures preserve their state; a process terminated mid-run
retains its pending input envelope but does not automatically resume the job.
The Flask server is a local research application. Timing, free height, sweeps,
real data, robust losses, additional solvers and uncertainty analysis are deferred.

