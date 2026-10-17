# M3 acceptance evidence

Completed October 13, 2026. M3 adds moving-tag and acquisition timing experiments;
M4 and later remain out of scope. No external push or publication was performed.

## Launch and reproduce

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe app.py --port 5052
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\validate_m3.py
.\.venv\Scripts\python.exe scripts\benchmark_m3.py
```

Open http://127.0.0.1:5052. Port 5052 preserves earlier servers on 5050/5051.
Use the existing installation instructions in README.md for a fresh environment.
The M3 panel uses the existing path, map, noise, seed and initialization controls.
Open bundled `M3_variable_known_map`, the joint aware/grouped pair, or a timing
sweep. Run M3 and Run paired sweep are explicit background operations. Keep
`runs/` and `runs/artifacts/` for history. Startup/import/reopen do not solve.

## Evidence

The final numerical directory is
`evidence/m3/acceptance_20261013_223058_213b1611/`. The earlier independently
reviewed acceptance set remains at
`evidence/m3/acceptance_20261013_221140_761f23ec/`. Both retain seven sweeps,
**68 runs / 136 starts**, complete observations and compatible paired starts,
five demo runs, isolated acquisition-jitter/prior examples, and the invariant
fixtures. The final driver additionally retains incremental sweep checkpoints
and writes invariant results before testing assertions. New driver invocations
create separate directories and never overwrite previous evidence.

| Requirement | Evidence |
| --- | --- |
| Variable speed, acceleration, stop, reversal, speed chart | `tests/test_m3.py`; saved `truth.motion`; `visual/final_speed_and_scrub.jpg` |
| Order, cycle rate, ping spacing, acquisition jitter, separate clocks/positions | Core clock/range-generation tests; saved observations, ping/grouped positions and acquisition metadata |
| Controlled piecewise-linear knots and disclosed optional prior | `docs/archive/M3.md`; analytic-Jacobian and rank/prior tests; `isolated_effects/prior_off.json`, `prior_on.json` |
| Identical-data aware/grouped comparison | Seven full sweeps, paired initial geometries, sweep validation tests, `visual/browser_sweep.json` |
| Ping scene, rays, camera and comparison preservation | `visual/final_rotated_ping_scene.jpg`, `ping_scene.png`, `manual_camera_and_comparison_check.json` |
| Speed/spacing/knot sweeps; isolated clock error, missingness, unequal rates | `sweeps/*.json` and CSV; isolated jitter fixture; `visual/live_ui_sweep.json` |
| Failed and nonconverged inspection | `demo_runs/forced_nonconverged.json`; `extra_runs/all_missing_failed.json`, `invalid_initial_failed.json`; `visual/failed_starts.jpg` |
| Offline persistence and complete exports | Service/sweep tests forbid solving or generation on reopen/import; `visual/browser_sweep.csv` has 24 matching start rows; `visual/config_roundtrip.json` proves complete experiment and options equality |
| Numerical and syntax validation | `test_results_delivery.txt`: **81 passing tests**, including all original 61; JavaScript syntax checks pass |
| Preserve original evidence and user observations | `preservation_manifest.json`, `preservation_check.json`: all **188 initial files unchanged**; final driver separately checked 293 pre-existing evidence/history files |

Paths in the table without a directory prefix are under `evidence/m3/`, or
under the final numerical directory when naming its `sweeps`, `demo_runs` or
`isolated_effects` folders. M0–M2 acceptance documents/evidence are unchanged.

## Numerical results

Zero spacing reproduces M1 synchronized observations, initial trajectories and
fits in both map modes. Core tests use 2e-7 m fit tolerance; the retained
known-map common-start fixture passes 1e-8 m. A stationary known-map tag
recovers with nonzero acquisition spacing, with no actual-versus-cycle position
gap; the core maximum-error check is 1e-7 m. Stationary motion does not make an
unknown map observable. Adding 2 s correctly timestamped delivery latency
changes neither model's batch estimates within 1e-12 m.

For the noiseless variable-speed known-map reference, selected-start median
display-position RMSE at spacing 0 / .04 / .10 s is approximately
0 / .0854 / .180 m for aware fitting and 0 / .271 / .661 m for grouping.
At .04 s spacing, the truth timing gap is .312 m RMS and the truth-knot
representation discrepancy at actual pings is .101 m RMS. These are separate
quantities. The latter is not a guaranteed lower bound on optimized error.
The .1 m smoothness-prior example worsens display RMSE from .0854 to .150 m;
its measurement and prior objectives remain separately visible. Detailed
offset, jitter, knot, missingness and cadence results are in [M3.md](M3.md).

Independent joint-map examples remain diagnostic research results, not exact
recovery claims. In the proper rigid aligned comparison, aware display/map
RMSE is .1887/.3150 m, with measurement rank 40/40; grouped RMSE is
.3778/.4220 m, with rank 38/40. Both optimizers converge. Common endpoint knots
can be unobserved by the grouped model, and the rank diagnostic exposes this.
Alignment fixes scale at one and excludes reflections. Full local rank and
finite multistart agreement never establish global uniqueness.

## Visual checks and performance

The application was tested at its normal compact in-app viewport. Checks
included a live Run M3, a four-run live paired sweep, individual start selection,
zero-observation failures, speed/stops, receiver/range rays, actual versus cycle
positions, scrubbing, play/pause, raw/aligned geometry, manual rotation, saved
joint comparisons, import/reload and exports. Selecting a sweep start keeps its
complete attempt table. Manual camera and comparison selectors are byte-for-byte
unchanged across a scrub. Scene and sweep PNGs were reopened and inspected.
Configuration export reproduces observations and all options, including the
restored evaluation budget. A retained development console event from the
earlier overlay implementation is in `visual/browser_console_history.json`;
the final checks produced no newer console errors.

The retained benchmark at
`benchmark_20261013_221207_a4550df5/performance_benchmark.json` measures whole
paired wrappers, two starts per model: .193 s at 16 display samples and
.385–.393 s at 32. DOM timings in `visual/final_camera_and_timing.json` record
322.1 ms primary-scene rendering, 67.3 ms speed-chart rendering, and 22.3 ms
one ping restyle. These are local measurements, not hardware guarantees or
network-inclusive response times. The maximum 150-knot configuration was not
benchmarked. Large, weakly observable fits can be much slower.

Service fault-injection tests separately verify that persistence failure keeps
the optimizer outcome intact, and a restarted service recovers all completed
attempts from a unique temporary checkpoint. Interrupted jobs do not implicitly
resume. The original camera check spanning an intentional Top-view change is
retained; use `camera_check_final.json` and the manual-camera check for invariance.

## Remaining limits

One planar tag, four identified equal-height beacons, batch Gaussian range
fitting, and a fixed variable-speed preset remain the scope. Display samples
8–100, cycles 2–100, knots at most 150; application runs allow 12 starts and 5000
evaluations, sweeps 40 runs and 240 starts. Playback advances through retained
cycle/beacon records at a fixed display cadence, not wall-clock acquisition
speed or delivery order. Speed is synthetic truth, not an estimated velocity.
Paths hold at endpoints; corners can have instantaneous spatial direction
changes. Priors depend on knot spacing and can bias acceleration/stops.

Grouped reference cycle times remain the supplied synthetic cycle starts when
per-ping timestamp offsets/jitter change. Their unchanged estimates in those
tests do not demonstrate general clock-error robustness. No clock-offset
estimation, online delivery processing, real logs, arbitrary editable speed
curve, free height, extra solvers, multipath or uncertainty extension is added.
Measurement observability, priors, representation error, timing approximation,
optimizer convergence and geometric accuracy must continue to be interpreted
separately.
