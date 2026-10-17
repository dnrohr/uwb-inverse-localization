# RangeLab user guide

RangeLab simulates UWB range measurements and fits a moving tag trajectory and beacon map. Use it to investigate geometry, timing, height assumptions, numerical methods, contamination and survey knowledge. It is a local research application for synthetic data; recorded-device ingestion, IMU/odometry, online estimation, multiple tags and heading estimation are not implemented.

This guide describes the Experiment and Library interface, from configuring a first experiment through comparing and exporting saved results.

## Guide contents

- [Start the application](#start-the-application)
- [First experiment](#first-experiment)
- [Choose a numerical model](#choose-a-numerical-model)
- [Edit inputs](#edit-inputs)
- [Paths and explicit coordinates](#paths-and-explicit-coordinates)
- [Survey knowledge](#survey-knowledge)
- [Run parameter studies](#run-parameter-studies)
- [Inspect results](#inspect-results)
- [Library and comparisons](#library-and-comparisons)
- [Import, export and reproducibility](#import-export-and-reproducibility)
- [Troubleshooting](#troubleshooting)
- [Input reference](INPUT_REFERENCE.md): every editable configuration field, defaults, units, bounds and model availability.
- [Function reference](FUNCTION_REFERENCE.md): Python functions/methods, arguments, source links and HTTP routes.
- [Workspace architecture and API semantics](WORKSPACE.md), [mathematics](science/MATH_REVIEW.md), [survey uncertainty](science/SURVEY_UNCERTAINTY.md).

## Start the application

Python 3.12 is the tested environment. Open PowerShell in the repository:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe app.py --port 5057
```

Visit [RangeLab](http://127.0.0.1:5057). Keep the terminal running; Ctrl+C stops the server. The server binds to `127.0.0.1` and serves Plotly locally. The page needs the Python server; opening index.html directly is insufficient. If the port is occupied, choose another `--port` and change the browser URL. If omitted, the command-line port defaults to `5050`.

Saved results live in `runs/`, studies/comparisons in `runs/artifacts/`, and the disposable Library metadata index in `runs/.library.sqlite3`. Keep the JSON files to retain your work. Browser session storage retains the editable draft and Library preferences independently of the saved scientific records.

## First experiment

1. In **Experiment**, choose **Planar synchronized ranges** under **Numerical model**. Selecting a model loads its defaults, replacing the current editable draft. Export Draft JSON first if you need those settings later.
2. Open **Geometry**. Leave scenario `informative`, samples `32`, duration `20`, noise `[0,0,0,0]` and seed `7`.
3. In **Estimator assumptions**, use map knowledge `joint` and assumed range sigma `[0.05,0.05,0.05,0.05]`. A noiseless simulation still requires positive assumed sigma.
4. In **Numerical method**, retain independent initialization, two starts, seed `19` and budget `1000`.
5. Select **Validate draft**. Validation checks settings; it creates no observations and performs no optimization.
6. Select **Run experiment**. A background worker creates and saves a result. Keep the page open for completion status. Existing displayed results remain visible while another job runs.
7. Choose a **Physical start**, inspect **Overview**, then examine **Residuals** and **Observability and uncertainty**. Review every attempt before interpreting the selected outcome.
8. Download **Run JSON** for the full record and **Draft JSON** for the editable setup.

Editing controls changes only the draft. Opening a saved source changes only inspection. **Use configuration** copies a saved setup to the draft; **Reuse observations** also selects its exact saved observation source. Only an explicit Run creates a new fit. Validation errors leave a message near the run controls; there is no automatic switch to another numerical model.

## Choose a numerical model

| Model key and displayed name | Use it for | Main restrictions |
|---|---|---|
| `planar` — Planar synchronized ranges | Baseline joint map/trajectory recovery, noise, sample count and optimizer budget studies | Four synchronized beacons, planar tags, shared beacon height, Gaussian/TRF |
| `timing` — Timestamp-aware trajectory | Sequential pings, variable motion, clock errors, missingness, knot spacing and motion priors | Four beacons; planar tags/shared height; timestamp-aware or grouped timing; Gaussian/TRF |
| `spatial` — Spatial height models | 3–8 beacons, vertical diversity, tag height profiles and height priors | TRF, physical height coordinates; independent or truth-near starts |
| `solver` — Solver and height parameterization | Paired TRF/LM, h/q and initializer investigations | q needs a single supported relative height; algebraic has stricter input requirements |
| `robust` — Contaminated ranges and robust estimation | NLOS, offsets, temporal correlation, quantization/dropout and robust losses | Inherits solver/model restrictions; robust uncertainty is not calibrated Gaussian covariance |
| `survey` — Partial surveyed-world knowledge | Fixed survey coordinates, uncertain survey blocks and conditional local intervals | Joint world frame, independent beacon heights, physical h, no algebraic initialization; single fits only |

The initial page uses robust-model defaults unless your browser session has a retained draft. These defaults use clean, Gaussian measurements. A dropdown may offer values unsupported in the chosen combination; **Validate draft** gives the authoritative acceptance result. See the input reference for exact defaults by model.

TRF enforces physical bounds directly. LM maps finite bounds through exponential transforms and operates strictly inside them; its behavior near a bound can differ from TRF. LM also requires the retained range/prior residual count to be at least the parameter count. `q = h²` changes a positive shared relative-height coordinate, not the range objective. It is unavailable for free heights, a nonhorizontal known beacon plane, or partial survey.

Independent starts use measurement inputs. Truth-near starts deliberately use synthetic truth and are diagnostic. Algebraic initialization is available only in solver/robust models for supported complete, synchronous planar/shared-height cases. Unsupported, rank-deficient or physically inconsistent algebraic proposals fail explicitly; they do not silently become independent starts.

## Edit inputs

The six configuration groups separate physical truth from fitting assumptions:

| Group | What it controls |
|---|---|
| Geometry | Reference scenario, duration/display samples, beacon layout, custom XY path and synthetic tag Z |
| Motion and acquisition | True speed profile, beacon ping order/rate/spacing, clock errors, missing pings and delivery latency |
| Measurement model | White range noise, physical/contamination seeds, positive NLOS, biases, AR(1) noise, quantization and dropout |
| Estimator assumptions | Assumed sigma, known/unknown map, timing approximation, knot/prior settings, height models, robust losses, survey and uncertainty assumptions |
| Numerical method | Solver, height coordinate, initializer, perturbation, start count/seed and evaluation budget |
| Study design | Single fit or parameter study, swept factor/values, measurement seeds and named variants |

Hover over a field, or focus it with the keyboard, to see its explanation. Escape dismisses the visible help. Screen readers receive the same help through field descriptions. Existing labels remain available. The [input reference](INPUT_REFERENCE.md) is the searchable list of all explanations, including optional fields.

Numeric controls require finite numbers. Integer fields (samples, seeds, counts, strides, budgets) must contain integers. Array controls use **JSON**, e.g. `[0.02,0.02,0.02,0.02]`, not bare comma-separated text. Use lowercase `true`, `false`, `null` in JSON, double-quoted strings and no trailing commas. JSON editors for optional geometry, survey, variants and draft imports take effect when their **Apply** button succeeds; ordinary fields edit immediately. Incomplete JSON may show a validation message while being typed.

Lengths are metres, times seconds, angles degrees and covariance entries square metres. IDs start at zero. Assumed sigma controls the weighted residual `(predicted range − measured range) / sigma`; injected noise changes simulated measurements. They are independent quantities. Physical, contamination and numerical seeds control different random streams.

In timing and later models, `samples` sets display resolution. The number of acquisition cycles is `floor(duration_s * cycle_rate_hz + 1e-10) + 1`, limited to 2–100. Editing samples/duration does not recompute an already explicit rate. Within a cycle, actual ping time is cycle start plus order-slot × spacing plus uniform acquisition jitter; supplied timestamp adds offset and uniform clock jitter. Delivery time adds latency to actual acquisition time. Delivery delay does not move the tag at measurement time. Timestamp-aware fitting uses supplied timestamps; grouped fitting approximates every cycle at its start.

For 3–8-beacon models, changing count can require changing noise/sigma arrays, ping order, stride arrays, offsets, NLOS IDs, survey IDs and explicit coordinates. Normalized defaults expand scalar noise/sigma into per-beacon arrays, so update those arrays or replace them with a scalar using full draft JSON before validation.

Contamination is applied in order: base acquisition/white noise, per-beacon offsets, stationary per-beacon AR(1), positive NLOS, nearest-even quantization, then independent dropout. NLOS prevalence is a burst-onset probability; the realized fraction can be larger when bursts span multiple cycles. AR correlation is per adjacent cycle, not per elapsed second. Acquisition missingness and contamination dropout remove inputs before fitting; hard rejection removes ranges according to a fitted pilot. Synthetic labels are kept for evaluation and never set fitted weights.

## Paths and explicit coordinates

Expand **Optional path and explicit beacon coordinates**, enter JSON, then select **Apply optional geometry**. For example:

```json
{
  "path": {
    "type": "circle",
    "center_m": [5, 4],
    "size_m": [7, 7],
    "scale": 1,
    "rotation_deg": 0
  }
}
```

Line, rectangle and figure-eight use full width/height. Circle and arc use equal size entries giving diameter. Arc also accepts starting angle and signed sweep. Waypoint paths take local XY points; scale and rotation apply before translating by center. Adjacent repeated points are allowed if total path length remains positive. Motion speed and truth-height models operate separately. Figure-eight arclength uses a dense polyline approximation, disclosed in path metadata.

For a four-beacon spatial model, explicit world coordinates can be included as:

```json
{
  "path": {"type": "rectangle", "size_m": [7, 5.6]},
  "coordinates_m": [[0,0,3], [10,0,3.5], [1,8,2.5], [11,9,4]]
}
```

Explicit coordinates override generated layout geometry, nominal height, spread and baseline. They are generation truth; only known-map fitting or an explicit survey supplies coordinate knowledge to the estimator. Planar/timing models do not support explicit beacon arrays in this editor. Omit `path` to remove the custom path. Omit `coordinates_m` or set it to `null` to remove explicit coordinates. Applying `{}` removes both optional overrides; it does not reset other draft settings.

## Survey knowledge

Select **Partial surveyed-world knowledge**. Under estimator assumptions, **Add survey row** adds a fixed X coordinate for beacon 0. Set Beacon, Knowledge type, selected X/Y/Z axes and Mean XYZ. Uncertain rows also need selected-axis covariance; the default single-axis block `[[0.01]]` means a 0.1 m SD. For XY use a 2×2 covariance, e.g. `[[0.01,0],[0,0.04]]`. A three-axis mean is always required even when only one axis is selected. Remove a row with ×.

The exact declaration is also available in **Advanced survey JSON**:

```json
{
  "frame": "world",
  "units": "m",
  "fixed": [{"beacon_id":0,"mask":[true,true,true],"mean_m":[0,0,3]}],
  "priors": [{"beacon_id":1,"mask":[true,true,false],"mean_m":[10,0,3],"covariance_m2":[[0.01,0],[0,0.04]]}]
}
```

Fixed coordinates are exact eliminated constraints. Priors add uncertain information and must have symmetric positive-definite covariance. Axis order is selected XYZ order. Cross-beacon covariance, duplicate coordinates and fixed/prior overlaps reject. At most 24 rows per list are supported; at least one coordinate must be selected overall. Fixing one beacon does not by itself guarantee that all orientation freedoms are removed. Inspect measurement-only and survey-augmented ranks.

Survey fitting requires joint mode, independent beacon heights, h coordinates and a nonalgebraic initializer. Below-beacon bounds with non-fixed world tag height reject. **Validate draft** also checks survey IDs against beacon count. Table edits update the draft; full model validation happens through Validate/Run. Advanced JSON Apply validates before adoption.

## Run parameter studies

Under **Study design**, choose **Parameter study**, select a supported factor and enter values/seeds as JSON arrays. Example for robust model: factor `nlos_prevalence`, values `[0,0.1]`, seeds `[7,8]`, default variants. This creates 2 × 2 × 4 = 16 runs; with 3 starts each, 48 attempts. Choose **Validate draft**, then **Run study**. Review the source and cell accounting in **Attempts and study results**.

Native studies allow 1–10 distinct values, 1–10 distinct unsigned 32-bit seeds, usually 1–4 uniquely labeled variants (labels at most 80 characters), at most 40 runs and 240 physical starts. The app limits each start to 5000 evaluations and start count to 12. Timing always has two variants; survey has no study engine. Studies generate paired cells and do not accept saved-observation reuse.

| Model | Factors and meanings |
|---|---|
| Planar | `noise_std_m`, `assumed_std_m`, `samples`; `path_scale` sets custom horizontal path scale; `initial_error_m` is truth-near diagnostic initialization error and requires truth_near explicitly in the workspace |
| Timing | `speed_scale`, `spacing_s`, `knot_spacing_s`, `timestamp_offset_s`, `timestamp_jitter_s`, `missing_probability`; `beacon_every_cycles` varies only beacon 3's stride, leaving other beacons at 1 |
| Spatial | `beacon_count`, `vertical_separation` (nominal beacon world Z, not measured separation), `height_spread`, `coverage` (custom path scale), `height_prior_sigma_m`, `beacon_height_model` |
| Solver | `initialization_error_m`, `noise_std_m`, `beacon_count`, `vertical_separation`, `coverage` |
| Robust | `nlos_prevalence`, `nlos_magnitude_m`, `burst_duration_cycles`, `offset_m` (same offset on every beacon), `correlated_noise_std_m`, `correlation`, `quantization_m`, `dropout_probability`, `noise_std_m` |

Values inherit the target field's units/bounds; `beacon_height_model` values are JSON strings. Coverage/path-scale studies need an explicit path for straight-line/narrow-coverage reference scenarios. Layout studies require generated beacon coordinates. Count studies can resize homogeneous noise/sigma defaults; heterogeneous vectors require a compatible setup.

**Named estimator variants** accepts native JSON. Planar variants may change mode/budget:

```json
[{"label":"short budget","max_nfev":200},{"label":"long budget","max_nfev":1000}]
```

Spatial, solver and robust variants use option objects:

```json
[{"label":"Gaussian","options":{"loss":"gaussian"}},{"label":"Huber","options":{"loss":"huber","loss_scale_sigma":2}}]
```

The latter example is for robust. Solver variants can change solver/height coordinate/initializer within native pairing rules; spatial variants compare height models. `null` selects recorded defaults. Timing requires `null` or an omitted variants field because its timestamp-aware/grouped pair is fixed. Variants cannot override shared seed/start count or the swept option; further model-specific restrictions are validated explicitly. Compatible physical starts and observations are paired; failed or nonconverged outcomes remain part of accounting and aggregates. Check the retained pairing disclosure before claiming two variants used identical starts.

## Inspect results

**Physical start** selects one saved attempt consistently across plots, metrics, playback and provenance. Switching it does not refit. The default selected outcome is not a substitute for examining multistart spread and failures.

Rotate, pan and zoom the 3D scene with Plotly controls. Use the named camera buttons to reset/view geometry. The layer switches show truth, estimate, initial guess, error vectors, measurement rays and tag/beacon planes. All axes use metres. **Coordinates** selects raw or supported rigid-aligned evaluation coordinates. Alignment preserves scale; it can remove frame differences while leaving physical map distortion visible. In comparison mode some per-run controls are disabled; use Inspect A/B to return to them.

Ping playback supports Play, Pause, previous/next and the scrubber. The detail panel shows the selected event's beacon, measured range and timing/position evidence. Actual, supplied and delivery times have distinct meanings. Unsupported playback/diagnostics remain unavailable or give an explanation. Browsing Library pauses playback and it remains paused on return.

| Diagnostic tab | How to use it |
|---|---|
| Overview | Read saved outcome, warnings and accuracy/residual metrics together. A converged optimizer may still recover a distorted map. |
| Residuals | Examine distribution, per-beacon and time structure. Robust models add signed residuals, influence decisions, retained coverage and detailed per-range records. Residual sign is predicted minus measured. |
| Geometry and timing | Inspect trajectory/map error, speed/pings, recovered heights and plane diagnostics when supported. Distinguish display samples, estimator knots and actual pings. |
| Observability and uncertainty | Inspect singular spectrum, local measurement rank and augmented rank. Request conditional local uncertainty explicitly with its supported assumptions; export its result when available. |
| Attempts and study results | Examine every initial start, failure, nonconvergence, budget, study factor/seed/variant and source/cell accounting. Use native study tables and chart exports. |
| Configuration and provenance | Read immutable original source and selected attempt; inspect/export the separate editable draft; paste exact workspace JSON and Apply to validate/adopt it. |

Residual RMS in metres measures range agreement. Standardized residuals divide by assumed sigma. Geometry RMSE/max errors compare against separate synthetic truth in disclosed evaluation frames. Solver cost may include robust transforms and priors and is not interchangeable across objectives. Rank and condition number describe local sensitivity; small singular values reveal weak directions. Full local rank does not prove global uniqueness or eliminate reflected/alternate solutions.

Robust scenes sample at most 45 measurement rays: gray weight ≥ 0.999, amber positive downweighting, red zero-weight rejection. Decision markers are flagged below the configured threshold and sized by influence weight. These fitted decisions are separate from injected NLOS labels. A robust fit may reject useful geometry, so inspect retained coverage and rank as well as residual reduction.

Conditional intervals assume the supported local representation, independent Gaussian ranges with known saved sigmas, chosen constraints/priors and a converged interior full-rank solution. Rank deficiency, active bounds, contamination/noise assumptions, robust loss or rejection can withhold covariance. Read the reported reason; absence is not zero uncertainty. Curvature diagnostics for robust objectives are not calibrated covariance. These intervals cannot establish global uniqueness.

## Library and comparisons

Select **Library** to browse saved runs, studies and comparisons. Search names/scenarios/IDs/settings, filter type/status/model/source, sort newest/oldest/name/outcome, and choose grouped parents/standalone or all items. Default page size is 25; maximum is 50. Previous/Next pages and filters preserve A/B selections. Refresh updates metadata; Rebuild index reconstructs the disposable cache from authoritative JSON. Cold scans of large histories can be slow.

Select a row to preview settings/provenance. **Open in viewer** strictly validates and opens it without fitting or changing the draft. For a benchmark, browse its recorded children and inspect all attempts, including failed/nonconverged entries. Unsupported historical editable representations remain inspectable/exportable but cannot be silently converted into a supported draft.

Choose **Use as A** and **Use as B** on two runs, then **Compare A / B**. Set the offered alignment to raw or rigid alignment with scale 1. Both sources share scene scale, camera and elapsed-time reference. **Inspect A/B** returns to source-specific diagnostics. Pairing is asserted only when saved observation/start records support it. Comparison JSON and PNG retain/export the comparison view; comparison CSV uses the native table exporter.

To repeat a saved physical realization with different supported solver assumptions, open its run and select **Reuse observations**. It requires an exact authoritative Library source key and a compatible native schema. Physical settings and original observation sigmas must remain identical. Change solver/loss/budget as supported, then Run for a new record. To change truth, noise or assumed saved sigmas, select **Generate new observations** first. **Use configuration** copies settings without retaining an observation reuse requirement.

## Import, export and reproducibility

| Action | Result |
|---|---|
| Import run / Library Import JSON | Workspace draft or native configuration updates the editable setup; validated native run/study/comparison imports are saved and opened without solving |
| Draft JSON / Export config | Version-1 workspace settings, including physical/assumption/numerical/study/source sections; no retained observations unless referencing an existing source key |
| Run JSON | Complete saved run, observations, truth/reference data, starts, options, diagnostics and provenance; in comparison mode exports comparison JSON |
| Complete CSV | Typed source, experiment, estimator_input, observation and attempt rows with `complete_record_json` preserving full records; comparison uses native tables |
| Native study JSON / CSV | Complete study with all entries; attempt tables, and robust per-observation tables through their native controls |
| Scene/chart PNG | Current scene or supported chart, reflecting selected source/start/view; an image does not replace source JSON |
| Uncertainty export | Explicit uncertainty inspection result and assumption/reason disclosures where supported |

Imports accept strict finite JSON; NaN/Infinity, unsupported versions and malformed records reject. The server request limit is 100 MiB. Exported JSON escapes Unicode with explicit UTF-8 transport so mathematical symbols survive reimport. Back up native JSON plus the draft when reproducibility matters. A saved-source key refers to local history and does not embed that history inside a draft export; import the corresponding native source and reselect reuse on a different installation.

The app uses one background fitting worker. Do not assume closing the browser cancels a job. There is no general job-cancel or solver-state resume UI. Study checkpoints preserve completed entries, not optimizer internals. Imported incomplete work is marked conservatively; reopening it does not resume fitting. Saved IDs are server-owned on import to avoid overwriting unrelated history. JSON records are authoritative; the SQLite index can be rebuilt. Saving and atomic file replacement do not claim permanent-write durability.

## Troubleshooting

| Symptom | Explanation and next step |
|---|---|
| Page fails to initialize or fetch | Check the Python server is running and open the matching localhost port; reload after restoring the server |
| Unsupported keys/combination | Use the chosen model's field reference and Validate; remove foreign fields or choose another explicit model before applying its defaults |
| Arrays have wrong length | Match beacon count in noise/sigma/order/strides/offsets/coordinates and verify all zero-based IDs |
| Invalid JSON while editing | Complete brackets, quote strings and use JSON arrays; Apply advanced editors explicitly |
| Too many cycles/knots/runs | Adjust duration/rate or knot spacing; reduce study values, seeds, variants or starts |
| Saved source config is immutable | Restore source physical settings and sigma exactly, or choose generation to simulate a new realization |
| q rejected | Use fixed/shared tag and one supported shared relative height; otherwise select h |
| Algebraic initialization fails | Check synchronous complete observations and supported planar/shared geometry; inspect failure instead of assuming a fallback |
| LM fails or approaches a bound slowly | Check residual count and strict-interior constraints; compare a supported TRF fit on the same observations/starts |
| Small residual, poor map | Inspect weak geometry, reflections, alternative starts, rank and truth errors in the disclosed frame |
| Uncertainty unavailable | Read withheld reasons; robust loss, rejected ranges, unsupported noise, rank deficiency, active bounds or nonconvergence can invalidate Gaussian intervals |
| Imported/old work cannot become a draft | Export and retain native JSON; use a supported native model/configuration rather than silently converting schema |
| Library is slow/stale | Refresh; allow cold inventory to finish; Rebuild index if needed while retaining source JSON |
| Configuration is hidden on narrow screen | Select Configuration to open the drawer; Close or Escape returns to results; Tab stays within the open drawer |

For numerical interpretation consult the mathematical documents linked above. To verify a local change, run `.\.venv\Scripts\python.exe -m unittest discover -s tests -v` and the relevant checks under `scripts/`. Validation/benchmark scripts can generate new evidence and are not required for ordinary browsing.
