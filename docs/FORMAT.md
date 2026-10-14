# Experiment format (schema 1.0)

The Python package uses NumPy, SciPy, Flask, and Plotly. NumPy generates the
synthetic measurements; SciPy is the planned nonlinear optimization library,
Flask the application server, and Plotly the interactive 3D viewer. Geomstats
is optional and is not needed by the generator. Install the stack with
`python -m pip install -r requirements.txt`.

`uwb.experiments.generate_experiment(config)` returns a JSON-compatible object.
`save_json(path, experiment)` and `load_json(path)` accept either a standalone
experiment or a saved run envelope containing an `experiment` and `starts`
list. Both validate the nested experiment and use strict JSON (non-finite
numeric values are rejected). Run envelopes may contain additional result,
diagnostic, and error fields; they are preserved as-is, including failed runs
with `starts: []` and an `error` string. The normalized `config`
is complete, including default values and the expanded four-beacon uncertainty
vectors. `software_versions` records Python, NumPy, SciPy, Flask, and Plotly
versions; a missing optional-at-runtime package version is `null`.

## Fields

- `schema_version`: currently `"1.0"`.
- `config`: scenario, sample count, duration, four range-noise standard
  deviations, four assumed observation standard deviations, and PRNG seed.
- `units`: `"metres, seconds"`.
- `coordinate_convention`: right-handed Cartesian metres; tag samples lie in
  the plane `z=0`; beacon IDs are zero-based. The informative map is
  `b0=(0,0,3)`, `b1=(10,0,3)`, `b2=(1,8,3)`, `b3=(11,9,3)`. Thus the horizontal
  origin is beacon 0, beacon 1 establishes positive x, and beacon 2 is on the
  positive-y side. All four are at shared positive height `h=3 m`.
- `truth`: `times_s` (N), `trajectory` (N×3), and `beacons` (4×3). Truth is
  reserved for evaluation and display.
- `estimator_input`: `times_s` (N) and `observations` (one record per epoch and
  beacon). Each record has `epoch`, `beacon_id`, `actual_time_s`,
  `assumed_time_s`, `range_m`, and `sigma_m`. This section has no truth fields.
- `software_versions`: runtime and dependency version strings.

## Timing and uncertainty

The reference experiments use simultaneous pings: for each epoch, all four
`actual_time_s` and `assumed_time_s` values equal that epoch's timestamp. Times
span `[0, duration_s]` evenly, including both endpoints. The generator records
both clocks even though they are identical in this synchronous baseline.

`noise_std_m` can be one nonnegative number shared by all beacons or four
nonnegative numbers ordered by beacon ID. A value of zero creates exact
distances without consuming a different model or adding noise. Otherwise,
independent Gaussian noise is drawn for each epoch/beacon pair from a seeded
NumPy generator and added to the Euclidean distance. `assumed_std_m` accepts
the same one-or-four-value form, defaults to `0.05 m`, and must be finite and
strictly positive; it becomes each record's `sigma_m`. Noise standard deviation
and estimator-assumed uncertainty are separate fields by design.

Supported scenarios are:

| Scenario | Reference geometry | Intended comparison |
| --- | --- | --- |
| `informative` | Default four-beacon map; constant-speed rectangular waypoint loop with corners (1.5,1.2), (8.5,1.2), (8.5,6.8), (1.5,6.8) m | Spatially spread baseline |
| `straight_line` | Informative map; straight path from (1,2) to (8,2) m | Reduced motion diversity |
| `narrow_coverage` | Informative map; short sinusoidal path centered near (4.5,3.5) m and sampled uniformly by arclength | Limited spatial coverage |
| `nearly_collinear` | Informative path; beacons have y coordinates 0, 0, 0.004, 0.006 m | Poor beacon geometry while preserving the b0/b1 x-axis gauge |

Each trajectory has z=0 and is sampled at uniform intervals of traveled
distance along its piecewise-linear path representation, so samples have
constant speed over the evenly spaced timestamps. The narrow path preserves a
short sinusoidal footprint using a dense polyline approximation before
arclength sampling. Every scenario uses four fixed, equal-height beacons
above the tag plane. These are diagnostics and comparisons, not a claim of
identifiability; evaluate the measurement Jacobian and geometry before
interpreting a fit as unique.

## API and example

```python
from uwb import generate_experiment, save_json, load_json

experiment = generate_experiment({
    "scenario": "informative",
    "samples": 32,
    "duration_s": 20,
    "noise_std_m": [0.0, 0.02, 0.02, 0.04],
    "assumed_std_m": 0.05,
    "seed": 7,
})
save_json("runs/example.json", experiment)
reloaded = load_json("runs/example.json")
```

Supported sample count is 8–100 inclusive. Duration and assumed uncertainties
must be finite and positive. Noise standard deviations may be zero or positive.
The random seed is a nonnegative integer. Saved JSON rejects `NaN` and infinity;
Python's JSON float representation round-trips finite binary floating-point
values exactly.

Run envelopes additionally require object-valued options/diagnostics, object
start records with unique nonnegative integer indices, numeric Nx3/4x3 initial
and estimated geometry when present, and a valid selected-start reference or
null. Failed records may have a null estimate; a pre-start failure may have an
empty starts list. Additional metadata is retained. Writes replace the target
atomically so a history read cannot observe a partly written JSON file.
Standalone experiments can share the local runs directory; the UI lists fitted
run envelopes and reports unreadable files without deleting them.

## M2 extensions

An optional `config.path` adds line, circle, arc, rectangle, figure-eight and waypoint
paths. Omitting it preserves legacy scenario generation and observations exactly.
Path parameter meanings, bounds and motion metadata are documented in [M2.md](M2.md).

Sweep/comparison envelopes use schema version `2.0` and `artifact_type` of `sweep`
or `comparison`. Sweeps retain configuration, thresholds, every embedded run/start,
aggregate statistics and solution groups. Comparisons embed both complete runs,
transforms at scale one, shared bounds and elapsed-time/interpolation data.
Artifacts are stored in `runs/artifacts/`; sweep child runs also appear in ordinary
run history with stable server-owned IDs. Import validates before saving and does
not solve or regenerate observations. Partial/failed checkpoint envelopes retain
completed entries and disclose unattempted cells and infrastructure errors.
Atomic replacement retries transient Windows permission errors; a complete
temporary checkpoint is retained for recovery if replacement permanently fails.
