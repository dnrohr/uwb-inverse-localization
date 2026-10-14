# uwb-inverse-localization

Interactive investigation of joint UWB tag localization and beacon calibration.

- [Project handoff](UWB_PROJECT_HANDOFF.md): mathematical model, assumptions, and background.
- [Project requirements](PROJECT_REQUIREMENTS.md): experiment controls, interactive 3D visualization, diagnostics, and delivery stages.
- [Roadmap](ROADMAP.md): ordered implementation tasks, dependencies, and milestone acceptance checks.

## Run the M0–M2 application

From this directory in PowerShell (Python 3.12 tested):

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-lock.txt
.\.venv\Scripts\python app.py
```

Open [the local viewer](http://127.0.0.1:5050). Select a bundled saved reference result, or configure an experiment and click **Run estimator**. Drag the 3D scene to rotate; use Top, Side, or 3D views, layer toggles, and raw/aligned coordinates. Expand solver details to inspect every start. Export JSON and a scene PNG, and import JSON to reopen a result without solving. The server binds to loopback and serves Plotly locally; no external account is needed.

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

Python/NumPy/SciPy provides a compact, auditable conventional least-squares baseline with analytic Jacobians and bounded trust-region optimization. Flask separates background fitting from scene interaction. Plotly supplies rotatable 3D geometry and linked numerical charts using the same saved data. Direct dependencies are pinned in `requirements.txt`; the tested complete environment is in `requirements-lock.txt`. Geomstats remains optional until a specific operation warrants it.

M0–M2 supports one planar tag, exactly four identified beacons at a shared positive height, synchronized complete observations, 8–100 samples, and 1–12 starts through the application. Timing, free height, additional solvers, missing ranges, and robustness remain in later roadmap milestones. Full local Jacobian rank and solver convergence do not establish global uniqueness. Weak geometry and alternate multistart outcomes remain visible; alignment never fits scale or reflections.

## Controlled sweeps and saved comparisons (M2)

Enable **Custom path** for constant-speed line, circle/arc, rectangle, figure-eight or waypoint motion. Set full dimensions, center, rotation, duration and samples. Waypoints are local offsets. Use **Parameter sweep** to vary noise, coverage, sample count, diagnostic initialization error or assumed uncertainty across seeds. The paired budget variants reuse observations and compatible guesses. Click aggregate curves or individual attempt rows to inspect saved geometry, including failed attempts.

Choose two saved runs under **Compare saved runs**. Both share one camera, equal metre scale and elapsed-time reference. Joint alignment uses proper planar rigid transforms at scale one; known-map results stay in the surveyed frame. Download configuration/run/sweep/comparison JSON, complete attempt CSV tables, charts and scene PNGs. Import or reopen saved results without solving again. Keep `runs/artifacts/` alongside `runs/`.

M2 validation used port 5051 to preserve the existing M1 server on 5050. Launch that port with `.\.venv\Scripts\python.exe app.py --port 5051` and open [the M2 viewer](http://127.0.0.1:5051). Reproduce only M2 evidence with:

```powershell
.\.venv\Scripts\python.exe scripts\validate_m2.py
.\.venv\Scripts\python.exe scripts\benchmark_m2.py
```

These scripts write `evidence/m2/`. The existing `scripts/validate.py` regenerates M0–M1 evidence; it is not needed to reopen saved M2 fixtures. M2 allows 40 runs and 240 total starts per sweep, up to 12 starts per run and 100 samples. Local three-start benchmarks measured 0.184–0.200 s at 32 samples and 3.819–4.804 s at 100 samples. Details, render timings and limitations are in the M2 acceptance record.
