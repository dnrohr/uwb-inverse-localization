# uwb-inverse-localization

Interactive investigation of joint UWB tag localization and beacon calibration.

- [Project handoff](UWB_PROJECT_HANDOFF.md): mathematical model, assumptions, and background.
- [Project requirements](PROJECT_REQUIREMENTS.md): experiment controls, interactive 3D visualization, diagnostics, and delivery stages.
- [Roadmap](ROADMAP.md): ordered implementation tasks, dependencies, and milestone acceptance checks.

## Run the M0–M7 application

From this directory in PowerShell (Python 3.12 tested):

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-lock.txt
.\.venv\Scripts\python app.py
```

Open [the local viewer](http://127.0.0.1:5050). Open **Library**, select a saved reference and choose **Open in viewer**, or configure an experiment and click **Run estimator**. Drag the 3D scene to rotate; use Top, Side, or 3D views, layer toggles, and raw/aligned coordinates. Expand solver details to inspect every start. Export JSON and a scene PNG, and import JSON to reopen a result without solving. The server binds to loopback and serves Plotly locally; no external account is needed.

The default exact informative case uses 32 synchronized epochs, four equal-height beacons, independent initialization, and three starts. Injected range noise and assumed uncertainty are separate controls. Exact observations still use a positive assumed uncertainty to normalize the residuals. Known-map mode uses the synthetic surveyed map explicitly; joint mode receives no truth coordinates. Truth-near initialization is a separately labeled diagnostic.

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
.\.venv\Scripts\python scripts\validate.py
```

The validation script regenerates saved reference evidence, including a deliberately nonconverged run. Startup copies bundled reference runs into `runs/` once without running the solver. New results and failed outcomes are also saved there. Keep that directory to preserve your history. The numerical API and JSON experiment format can be used independently of Flask.

## Implementation and evidence

- [Saved experiment/run format](docs/FORMAT.md)
- [Numerical model, tolerances, initialization and ambiguity](docs/NUMERICS.md)
- [Independent mathematical review](docs/MATH_REVIEW.md)
- [M0–M1 acceptance evidence and limitations](docs/ACCEPTANCE.md)
- [Machine-readable M0–M1 acceptance summary](evidence/acceptance_summary.json)
- [M2 controls, pairing, classification thresholds and limits](docs/M2.md)
- [M2 acceptance, screenshots, exports and performance](docs/M2_ACCEPTANCE.md)
- [M3 motion, timestamp model, priors and timing sweeps](docs/M3.md)
- [M3 acceptance, visual evidence, performance and limits](docs/M3_ACCEPTANCE.md)
- [M4 beacon geometry, tag-height models, priors and sweep controls](docs/M4.md)
- [M4 acceptance evidence, measured results and pending visual gates](docs/M4_ACCEPTANCE.md)
- [M5 TRF/LM solvers, `h`/`q` coordinates and initializers](docs/M5.md)
- [M5 acceptance record, numerical evidence and open release gates](docs/M5_ACCEPTANCE.md)

Python/NumPy/SciPy provides a compact, auditable conventional least-squares baseline with analytic Jacobians, bounded TRF, and LM. Flask separates background fitting from scene interaction. Plotly supplies rotatable 3D geometry and linked numerical charts using the same saved data. Direct dependencies are pinned in `requirements.txt`; the tested complete environment is in `requirements-lock.txt`. M5 retains SciPy TRF and LM; its recorded implementation decision defers Ceres and Geomstats because no measured need supports adding either for this milestone.

M0–M2 supports one planar tag, exactly four identified beacons at a shared positive height, synchronized complete observations, 8–100 samples, and 1–12 starts through the application. M3 adds sequential acquisition, variable motion, timestamp-aware/grouped trajectories and imperfect-data experiments described below. M4 adds 3–8 beacon 3D layouts, vertical truth profiles, fixed/shared/soft/free tag-height models, shared/independent beacon-height models, and 3D geometry sweeps. M5 adds paired SciPy TRF/LM comparisons, supported shared-height `h`/`q` coordinates, and independent, truth-near diagnostic, and algebraic initializers. Both M5 coordinates select a positive shared-height branch; its native projection displacement is a model-convention diagnostic, not an optimizer lower bound. M5 passed its defined numerical, backend persistence, and desktop UI scope; the [acceptance record](docs/M5_ACCEPTANCE.md) documents its evidence and limitations. Full local Jacobian rank and solver convergence do not establish global uniqueness. Weak geometry and alternate multistart outcomes remain visible; alignment never fits scale or reflections.

## Controlled sweeps and saved comparisons (M2)

Enable **Custom path** for constant-speed line, circle/arc, rectangle, figure-eight or waypoint motion. Set full dimensions, center, rotation, duration and samples. Waypoints are local offsets. Use **Parameter sweep** to vary noise, coverage, sample count, diagnostic initialization error or assumed uncertainty across seeds. The paired budget variants reuse observations and compatible guesses. Click aggregate curves or individual attempt rows to inspect saved geometry, including failed attempts.

Choose two saved runs in **Library** with **Use as A/B**, then select **Compare A / B**. Both share one camera, equal metre scale and elapsed-time reference. Joint alignment uses proper planar rigid transforms at scale one; known-map results stay in the surveyed frame. Download configuration/run/sweep/comparison JSON, complete attempt CSV tables, charts and scene PNGs. Import or reopen saved results without solving again. Keep `runs/artifacts/` alongside `runs/`.

M2 validation used port 5051 to preserve the existing M1 server on 5050. Launch that port with `.\.venv\Scripts\python.exe app.py --port 5051` and open [the M2 viewer](http://127.0.0.1:5051). Reproduce only M2 evidence with:

```powershell
.\.venv\Scripts\python.exe scripts\validate_m2.py
.\.venv\Scripts\python.exe scripts\benchmark_m2.py
```

These scripts write `evidence/m2/`. The existing `scripts/validate.py` regenerates M0–M1 evidence; it is not needed to reopen saved M2 fixtures. M2 allows 40 runs and 240 total starts per sweep, up to 12 starts per run and 100 samples. Local three-start benchmarks measured 0.184–0.200 s at 32 samples and 3.819–4.804 s at 100 samples. Details, render timings and limitations are in the M2 acceptance record.

## Moving tags and sequential pings (M3)

Launch `.\.venv\Scripts\python.exe app.py --port 5052` and open [the M3 viewer](http://127.0.0.1:5052). The separate **Ping timing and motion** panel uses the existing map, path, duration, noise and seed controls. Select variable/constant/stationary motion, beacon order, cycle rate, spacing, acquisition jitter, supplied timestamp errors, delivery latency, missingness and per-beacon strides. Choose timestamp-aware or cycle-start grouped fitting. Knots are piecewise linear; spacing 0 uses the cycle grid. Prior sigma 0 disables the disclosed constant-velocity preference. Maximum evaluations per start is explicit.

Click **Run M3**, or **Run paired sweep** to reuse observations and compatible initial guesses between models. Open the bundled M3 examples or seven timing sweeps without solving. Scrub/play individual retained pings alongside the speed chart; actual position, receiving beacon, measured range ray, common cycle position and fitted position are distinct. Camera and comparison settings survive scrubbing. Select any attempted start, including failures; convergence, geometry, measurement/prior information, interpolation and timing error are separate. Export complete configuration/run/sweep JSON, per-start CSV and scene/chart PNGs. Saved M3 runs also work in the shared comparison workspace.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\validate_m3.py
.\.venv\Scripts\python.exe scripts\benchmark_m3.py
```

The final suite has 81 passing tests. M3 scripts create unique directories under `evidence/m3/`, preserving earlier evidence/history. The numerical record retains seven sweeps (68 runs / 136 starts), verifies zero-spacing synchronized equivalence, stationary geometry and batch latency invariance, and includes failed/nonconverged examples. Local two-start-per-model paired wrapper measurements were about 0.193 s at 16 samples and 0.385–0.393 s at 32; one measured ping restyle was 22.3 ms. Limits are 100 display samples/cycles, 150 knots, 12 application starts, 5000 evaluations per start, 40 sweep runs and 240 sweep starts. See the M3 acceptance record for initialization scope, measured errors, timing reference assumptions and remaining limitations. No external push or publication was performed.

## 3D beacon and tag-height experiments (M4)

Launch `.\.venv\Scripts\python.exe app.py --port 5053` and open [the M4 viewer](http://127.0.0.1:5053). The separate **M4 · 3D beacon and tag geometry** panel reuses the path, acquisition, range-noise and solver controls while adding 3–8 beacons, generated or explicit XYZ beacon coordinates, beacon-height diversity, planar/tilted/excursion/spatial truth height, fixed/shared/soft/free tag-height models, and shared/independent beacon heights. The free tag model estimates 3D trajectory knots, not independent unconstrained positions at every display sample.

Use **Run M4** for one experiment or **Run paired sweep** to compare fixed/shared/soft/free tag-height variants over beacon count, nominal beacon height, height spread, path coverage, prior sigma or beacon-height model. The UI exposes measurement-only and prior-augmented rank separately, height and plane diagnostics, all attempted starts, saved runs/sweeps, JSON/CSV import/export, and chart/scene PNG export. Joint soft-height priors are measured from a disclosed canonical plane, not world z; below-beacon bounds are separate branch constraints. See [M4 controls and numerical conventions](docs/M4.md).

Reproduce the numerical acceptance and paired benchmark with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\validate_m4.py
.\.venv\Scripts\python.exe scripts\benchmark_m4.py
```

The recorded integration run has 110 passing tests; six geometry sweeps retained 112 starts, and the paired benchmark measured about 0.178–0.353 s for three beacons and 0.192–0.343 s for eight beacons at 12/24 samples. These are local Python wrapper timings, not browser performance guarantees. [`docs/M4_ACCEPTANCE.md`](docs/M4_ACCEPTANCE.md) maps the numerical, independent mathematical, live-browser, persistence and export evidence with measured performance and limitations.

## Solver and initializer comparisons (M5)

Launch the M5 viewer on its separate local port:

```powershell
.\.venv\Scripts\python.exe app.py --port 5054
```

Open [the M5 viewer](http://127.0.0.1:5054). Use the M5 panel to run SciPy TRF or LM with the supported shared-height `h` or `q` coordinate and independent, truth-near diagnostic, or algebraic initialization. Configure a paired benchmark to vary the supported experiment factor, choose labeled solver/coordinate/initializer variants, and set measurement seeds. Saved runs and sweeps retain all attempted starts, including failed algebraic proposals and nonconverged fits; select a row to inspect the attempt and its diagnostics. JSON import reopens a saved artifact without solving it. See [M5 numerical conventions](docs/M5.md) for the positive height branch, initializer support, pairing and objective definitions.

Reproduce the numerical checks and retained evidence with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/validate_m5.py
.\.venv\Scripts\python.exe scripts/benchmark_m5.py
.\.venv\Scripts\python.exe scripts/review_m5.py
```

The final-source test run passed 127 tests in 11.541 s (`evidence/m5/test_results_final.txt`); the earlier delivery run passed in 10.119 s. Acceptance retains nine sweeps (160 runs, 320 starts) plus eight fixtures (16 starts), including 40 invalid algebraic proposals, 51 failed sweep attempts, and one nonconverged sweep attempt. Limits are 40 runs, 240 starts total, 12 starts per run, and 5,000 function evaluations per start; `q` is restricted to supported shared relative-height models and `FLOOR = 1e-6 m`. Across the 48-record local benchmark, median wrapper times by variant were TRF/h 0.06536 s, TRF/q 0.06297 s, LM/h 0.04844 s, and LM/q 0.05043 s. These modest-workload measurements are descriptive, not general speed guarantees. Single desktop browser samples measured 250.5 ms for the scene, 230.1 ms for comparison, and 32.4–107.7 ms for chart/sweep redraws; they are not throughput guarantees.

M5 acceptance passed for its defined numerical, persistence and desktop UI scope. The [acceptance record](docs/M5_ACCEPTANCE.md), [backend audit](evidence/m5/backend_final_audit.json), [UI validation](evidence/m5/visual/ui_validation.json), and [final audit](evidence/m5/final_audit.json) describe evidence and limitations. At 390×844, M5 controls fit and history lists scroll, while the full page still has horizontal overflow. Checkpoint recovery requires a readable main artifact, and dedicated tests for sweep checkpoint-write failure and permanent double-write failure were not run. M5 defers a second solver implementation; no M6 implementation is included.

## Multipath and robust estimation (M6)

Launch the current local viewer without replacing earlier servers:

```powershell
.\.venv\Scripts\python.exe app.py --port 5056
```

Open [the M6 viewer](http://127.0.0.1:5056). Set geometry in M4 and motion, acquisition, noise, starts and evaluation budget in the shared controls. In **Contamination and robust fit study**, select an isolated source or a combined experiment, explicit contamination seed, per-beacon offsets and affected NLOS beacon IDs. Select Gaussian, Huber, soft L1, Cauchy or frozen hard rejection, plus its scale/threshold. M6 has its own TRF/LM, h/q and initializer controls. Truth-near starts are diagnostic only. Enable **Measurement rays** for sampled decision colors and supporting knot segments; the complete decision table keeps synthetic labels separate from estimator decisions.

Run a paired benchmark with distinct seeds, numeric factor values and labeled estimator variants. Each data cell shares observations and compatible physical starts. Inspect every attempt, original-range residuals, geometry, confusion metrics, coverage and original/retained information. Import/reopen saved JSON, export attempts and observations CSV separately, and export scene/chart PNGs. Lower cost after rejection is not evidence of better geometry. See [M6 model and controls](docs/M6.md) and [M6 acceptance, measurements and limits](docs/M6_ACCEPTANCE.md).

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\validate_m6.py
.\.venv\Scripts\python.exe scripts\benchmark_m6.py
.\.venv\Scripts\python.exe scripts\review_m6.py
```

Validation, review and benchmark invocations retain unique attempts under `evidence/m6/`. Source observations and earlier evidence/history are preserved. Saved files are local; no push or external publication is required. Full mobile layout remains uncertified.


## Library, partial survey and uncertainty (M7)

Keep existing servers intact and launch the current viewer on its own port:

```powershell
.\.venv\Scripts\python.exe app.py --port 5057
```

Open [the M7 viewer](http://127.0.0.1:5057). The persistent **Experiment / Library** navigation replaces repeated history panels. Search and filter runs, benchmarks and comparisons; default pages contain 25 rows, with a maximum of 50. Select a row for metadata preview, then explicitly **Open in viewer**. Benchmark children retain recorded cell/seed/variant relationships and every attempt. The A/B tray keeps selected sources across pages and filters, including self-contained imported comparisons. JSON/CSV/PNG exports and older milestone controls remain available. Leaving Experiment pauses playback at the same ping and retains cameras, layers and unsaved controls.

**Partial survey investigation** accepts selected fixed beacon coordinates and uncertain survey blocks in an explicit world frame: means in metres, selected-axis covariance in m². Fixed coordinates are constraints; survey priors are separate information. Enter declared knowledge, or import a saved M7 configuration; values are never filled from hidden truth. Reuse active M6/M7 observations to compare survey settings without generating different data. Survey fitting currently requires independent beacon heights and physical h coordinates; unsupported coupled constraints, q and algebraic initialization are rejected. With survey absent the numerical API preserves the M6 solve unchanged.

**Inspect saved uncertainty** performs a strict offline calculation for saved M6/M7 results. Available intervals are conditional local Gaussian approximations, with separate range/survey/motion/height information. Robust, rank-deficient, bound-active and declared-misspecified cases explain why covariance is unavailable. Full local rank is not global uniqueness. See [M7 usage and results](docs/M7.md), [numerical assumptions](docs/M7_NUMERICS.md), [acceptance and limitations](docs/M7_ACCEPTANCE.md), and [requirement audit](evidence/m7/final_audit.json).

The recorded final suite passed 208 tests. The survey bundle retains 75 runs / 94 attempts; the packaged investigations link 262 attempts across seven topics. All 1,665 original evidence/history files retain their original scientific bytes: 1,663 exact hashes remain unchanged and two active server logs only appended bytes after hash-verified original prefixes. Warm backend metadata medians were 19 ms for the initial retained history and 77 ms for an isolated 10,000-record fixture. Final browser warm refreshes of that fixture took 84–93 ms; its cold browser load took 113 seconds. Cold indexing remains a material cost. Only the Library is certified at 390×844; full Experiment mobile layout remains uncertified.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\validate_m7.py
.\.venv\Scripts\python.exe scripts\package_m7_investigations.py
.\.venv\Scripts\python.exe scripts\review_m7.py
.\.venv\Scripts\python.exe scripts\audit_m7_delivery.py
```

Validation scripts retain unique evidence directories. M7 examples can be imported from `evidence/m7/acceptance_20261015_190356_30ad31d9/runs/` if they are not already retained in Library. The local SQLite index is disposable; source JSON remains authoritative. Same-size edits with restored timestamps require **Rebuild index**. Single-run optimizer internals are not checkpointed, readable main JSON is required for sweep recovery, and permanent-write durability is not guaranteed. No commit, push or external publication was performed.
