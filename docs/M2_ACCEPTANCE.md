# M2 acceptance evidence

Completed October 13, 2026. This extends the preserved M0–M1 record in
[ACCEPTANCE.md](ACCEPTANCE.md); M3 and later remain out of scope.

## Launch and reproduce

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe app.py --port 5051
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\validate_m2.py
.\.venv\Scripts\python.exe scripts\benchmark_m2.py
```

Open http://127.0.0.1:5051. A fresh environment can be installed using the
existing `requirements-lock.txt` instructions in README.md. Port 5051 was used
for M2 validation because the earlier M1 server was already running on 5050.
Startup copies bundled M2 path runs, five sweeps, and two comparisons once;
it does not solve them. User history remains in `runs/` and `runs/artifacts/`.
The M2 scripts write only `evidence/m2/`, never M0–M1 evidence or user history.

## Requirement-to-evidence checks

| Requirement | Authoritative evidence |
| --- | --- |
| Constant-speed line, circle/arc, rectangle, figure-eight, waypoints; size, position, rotation, duration, samples | `tests/test_paths.py`, six full `evidence/m2/path_runs/*.json` files; numerical arclength, independent quadrature, transformed coordinates, exact ranges and round-trip checks |
| Saved two-run comparison, common camera/metre scale/elapsed time, proper rigid alignment only | `tests/test_sweeps.py` comparison tests; `evidence/m2/comparisons/`; `camera_check.json`; comparison scene PNG and browser screenshots |
| Paired single-factor sweeps | Five `evidence/m2/sweeps/*.json` artifacts and CSV tables; `tests/test_sweeps.py` and `tests/test_m2_review.py`; `ui_noise_sweep.json` from the live UI |
| Seeds, every start, failures, geometric errors, variability, distinct solutions | Full embedded runs, `start_table`, `aggregates`, `solution_groups`; exact/noisy/rank tests; nonconverged start inspection; failed-run comparison |
| Complete export/import/reopen, charts and scene images | `browser_sweep.json` and `browser_sweep.csv` (24 corresponding per-start rows); `comparison_scene.png`, `sweep_chart.png`; service tests prohibit solves/regeneration on reopen |
| Configuration limits and solver/UI performance | [M2.md](M2.md), `performance_benchmark.json`, complete `benchmark_runs/`, `ui_performance.json` |
| Preserve existing observations and M0–M1 evidence | `preservation_check.json`: all 18 existing reference/screenshot files and all 14 prior user run files match the initial SHA-256 manifests |

All evidence paths in this table are under `evidence/m2/` unless otherwise
specified. `test_results.txt` records **61 passing tests**, including all 28
original tests. Mathematical review separately checked compatible known-map
starts, preserved observations under uncertainty changes, zero initialization
error with small positive map coordinates, and complete null/error accounting.

## Numerical results and interpretation

The six 32-sample exact custom-path runs each retain three independent starts.
Circle, arc, rectangle, figure-eight and the spatially spread waypoint reference
recover geometry at roughly 1e-15 m RMS and have truth rank 70/70. The line has
rank 69/70, three distinct raw fitted geometries, and selected position RMSE
0.8649 m despite optimizer convergence and near-zero range residuals. These
results test recovery and expose ambiguity; rank or sampled-start agreement is
never treated as global uniqueness.

The five numerical sweeps cover noise, coverage, sample count, initialization
error, and assumed uncertainty. Together they retain **48 runs and 96 starts**,
including **48 deliberately nonconverged starts** from the one-evaluation
variant. Paired variants share complete observations and compatible initial
geometry. Exact acceptance uses raw canonical/surveyed errors; noisy joint
accuracy uses proper rigid alignment at scale one. The 0.2 m noise baseline
cases converge but exceed the disclosed geometric thresholds. Thresholds,
frames, failure denominators, clipping and grouping are described in M2.md and
saved in every sweep.

The live UI also completed a noise sweep with four paired runs/eight starts.
Its observations and initial geometries were checked for equality within each
pair. The export CSV matched all 24 per-start geometry values in the exported
bundled noise-sweep JSON (30 exported columns). `circle_serialization_check.json`
proves a 45° circle configuration export reproduces the complete live-run
experiment exactly, including observations. Run, sweep and configuration export
use the same UI serializer. Importing that JSON, reloading the page, opening
saved comparisons, clicking a curve point and choosing an individual
nonconverged row all display saved data without solving.

## Persistence failure and recovery

Live testing exposed a Windows reader-lock race during atomic checkpoint
replacement. `failed_checkpoint_original.json` retains the first failure
record; `failed_checkpoint_recovered.json` retains **both completed runs/four
starts**, recovered from the full temporary checkpoint without rerunning.
The two remaining planned runs were never attempted. The stopped sweep and
its infrastructure error remain inspectable, separately from optimizer status.

Atomic replacements now retry transient permission errors. Permanent errors
produce a terminal job with its latest snapshot, preserve the complete
temporary file, and allow reopening that file after a process restart.
Six dedicated persistence tests also prove stable per-entry IDs, no duplicate
run files from progress callbacks, and consistent imported IDs. A restarted
partial sweep is disclosed as interrupted; it does not silently resume.

## Visual checks and performance

The running application was inspected at a 1360×900 desktop viewport and the
normal compact in-app viewport. Checks included custom waypoint submission,
noisy figure-eight geometry, Top camera interaction during a queued sweep,
all-start tables, scalar/map variability, rank and failure disclosures,
two-run overlay with both maps, error colors/units, proper alignment, and
comparison camera persistence across a raw/aligned comparison change.
`camera_check.json` records the identical rotated camera before/after redraw.

Exported scene and chart PNGs were downloaded, reopened and visually inspected.
They use white backgrounds and metre/second/error labels. Fitted epoch markers
are separate from connecting interpolation lines. Comparison error statistics
use the original epochs; interpolation is not extra measured information.

Two local solver-wrapper measurements with 0.05 m noise and three starts gave:

| Samples | Wrapper wall time | Objective evaluations per start |
| --- | --- | --- |
| 32 | 0.184–0.200 s | 10 / 11 / 15 |
| 100 | 3.819–4.804 s | 9 / 11 / 11 |

Every measured benchmark run is saved. Browser `performance.now()` timings
around resolved Plotly rendering measured approximately 51–94 ms for sweep
charts, 93–407 ms for comparisons, and 210–1236 ms for primary scenes, including
first-page resource creation and concurrent chart updates. These are local
observations under the recorded workload, not cross-hardware guarantees or
network/solver-inclusive UI timings. See the machine-readable performance files
for individual cases.

## Remaining limits

The model remains one planar tag and exactly four identified, synchronized,
equal-height beacons. Samples are 8–100; starts 1–12 per application run;
sweeps allow 40 runs and 240 total starts. Jobs execute serially in a background
worker. Extreme or weak geometry may be slow or inaccurate. The figure-eight
is an arclength approximation; corners and curves can make display chords
shorter than the distance actually traveled. No timing, free-height, additional
solver, robust-loss, real-data or uncertainty extensions were added.

Acceptance and clustering thresholds are descriptive choices, not confidence
intervals. Noisy low-residual groups use normalized residual RMS, while exact
groups use the exact range threshold. Groups are per identical-data cell and
never clustered across seeds. A stopped process retains completed checkpoints
but does not automatically finish unattempted cells. No external push or
publication was performed.
