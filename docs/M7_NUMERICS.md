# M7 partial survey and conditional uncertainty

`uwb/m7.py` adds surveyed-world joint fitting without changing M0–M6 models.
With no `survey` (or `survey: null`), its solve/build/fit functions delegate to
M6 and return the existing schema-6 result. In particular, the extension does
not insert a new gauge, prior, seed, uncertainty calculation or schema into a
legacy solve. `summarize_uncertainty` is a separate offline operation for saved
M6 and M7 runs; it never fits or generates data.

## Declared survey schema

A survey is explicit input knowledge. The generator does not populate it from
synthetic truth. For example:

```json
{
  "frame": "world",
  "units": "m",
  "fixed": [
    {"beacon_id": 0, "mask": [true, false, true], "mean_m": [1.2, 0.0, 3.0]}
  ],
  "priors": [
    {"beacon_id": 1, "mask": [true, true, false], "mean_m": [5.0, 2.0, 0.0],
     "covariance_m2": [[0.04, 0.01], [0.01, 0.09]]}
  ]
}
```

Masks select x, y, z in that order. All three means must be finite even for
unselected axes; only selected components affect fitting. A prior covariance
has one row/column per selected axis, in x/y/z order, in square metres. It must
be finite, symmetric and positive definite. Correlation within this block is
supported. Distinct prior blocks are assumed independent, as are ranges,
survey blocks, and motion/height priors. A coordinate cannot occur in multiple
blocks or both fixed and prior lists; combine correlated axes in one block.
Cross-beacon covariance is currently unsupported and unknown fields are
rejected. Zero variance is an exact constraint and belongs in `fixed`.

Fixed coordinates are eliminated from the parameter vector. They add no
residuals or noisy information rows. Unfixed coordinates remain unknown even
when absent from every prior. Coordinates are physical world metres, including
world z in height priors and world horizontal tag planes. The solver adds no
canonical anchor translation/rotation or beacon sign convention. Remaining
continuous rigid freedoms stay present in the free-coordinate Jacobian. This
allows fitting under incomplete anchoring while reporting rank deficiency and
withholding covariance. Discrete reflection alternatives can remain even with
full local rank.

Supported survey options require `mode: joint`,
`beacon_height_model: independent`, and `height_parameterization: h`.
Fixed/shared/soft/free tag heights, timestamp-aware/grouped timing, motion
priors, Gaussian/Huber/soft-L1/Cauchy/hard-rejection losses and TRF/LM are
supported. A shared tag height is a free world z, unlike the old joint
canonical datum. Below-beacon bounds are supported only with fixed world tag
height: every unfixed beacon z is bounded above the tag datum by the inherited
1e-6 m numerical margin; contradictory fixed z fails before solving.
Nonfixed tag heights below partially surveyed beacons require coupled
inequalities and are rejected. Shared beacon-plane coupling, q coordinates,
algebraic initialization and simultaneous hidden `surveyed_beacons` maps are
explicitly rejected. The independent fitter requires explicit beacon_count
(integer 3–8), since an unobserved beacon cannot safely be inferred.

## Objective and derivatives

The piecewise-linear trajectory, assumed timestamps, normalized signed ranges,
motion residuals and soft height residuals retain the M4 definitions. Let x be
the vector of free physical metre parameters. The tag and map are affine:
`p = p0 + T x`, `b = b0 + B x`, where b0 contains only fixed survey values.
The distance derivative is

`d r_i / d x = (p(t_i)-b_j)^T (T(t_i)-B_j) / (sigma_i * norm(p(t_i)-b_j))`.

For survey block s, write `C_s = L_s L_s^T` using a Cholesky factor. Its
residual is `L_s^-1 (b_selected - mean_selected)` and its Jacobian is
`L_s^-1 B_selected`. Therefore its quadratic objective is exactly
`0.5 * delta^T C_s^-1 delta`, including the off-diagonal covariance terms.
Robust transforms apply only to range residuals; survey, motion and height
rows remain quadratic. The saved objective separates measurement, survey,
motion and height contributions. Hard rejection saves a Gaussian pilot and
its frozen label-independent mask, then refits once from that pilot. Its mask
can differ between starts; objectives under different masks are not a
common-data quality score.

TRF works directly with the physical box bounds. LM uses M5's strict-interior
exponential bound transform and chain rule, without clipping. It requires
retained range plus prior/survey row count at least the free parameter count.
Invalid proposals, unsupported model requests and nonconvergence are distinct;
attempt failures retain messages and their physical proposals. Independent
proposals use only ranges, declared survey means and the saved random seed.
Truth-near initializers are explicitly labeled oracle diagnostics. Label,
clean-range, actual-time and delivery annotations are stripped before fitting.

World-frame evaluation occurs after fitting. It compares estimates directly
with world truth, without fitting translation, rotation, reflection or scale.
`evaluation.raw` equals `evaluation.aligned`; the latter exists for viewer
compatibility and its `alignment.applied` is false. Insufficient survey
anchoring can consequently leave large world errors despite a low residual.
Injected labels are used only in separate post-fit rejection evaluation.

## Conditional uncertainty

Options include:

```json
{"uncertainty": {"enabled": true,
 "range_model": "independent_gaussian_known_sigma",
 "rank_rtol": 1e-8, "bound_tolerance_m": 1e-7}}
```

The original physical measurement Jacobian differentiates
`(predicted range - saved range) / saved sigma`. Its columns all have metre
units and no hidden column rescaling. SVD rank uses `s > s_max * rank_rtol`;
the absolute cutoff, spectrum and linearization parameters are saved.
Original measurement, retained/frozen-influence-weight measurement, survey,
motion prior, height prior, augmented rows and positive-part robust scalar
curvature are separately reported. The robust spectrum is a conditioning
surrogate, excluding geometry second derivatives. Neither robust weights nor
positive curvature is presented as calibrated covariance.

Finite covariance requires a converged Gaussian fit, a full-column-rank
augmented Jacobian, no active/near-active bounds and no zero predicted range.
For its SVD `J = U diag(s) V^T`, covariance is
`V diag(1/s^2) V^T`, computed only after the rank check. No nullspace
pseudoinverse is substituted. There is no residual variance rescaling:
the saved sigmas and declared prior covariances are treated as known.
Standard deviations are square roots of covariance diagonal entries;
marginal 95% half widths use 1.959963984540054 standard deviations.
Knot, beacon and ping component standard deviations propagate the affine
bases through this covariance. Exact fixed components have conditional zero
variance by declaration, rather than measured zero error.

With uncertain survey or motion/height priors, this is a local linear Gaussian
posterior approximation conditional on those assumptions. It is not an
unconditional frequentist coverage guarantee. Full local rank is not global
uniqueness; local intervals exclude undiscovered/reflected geometries.
The module claims no measured coverage calibration. Repeated-trial coverage
studies must separately state their generative assumptions, trial failures,
finite-sample uncertainty and whether the survey itself is resampled.

Saved-source summaries suppress finite covariance when declared generation
metadata already reports noise/sigma mismatch, contamination/correlation/
quantization, timestamp errors, possible asynchronous/coarser-knot timing or
interpolation mismatch, or fixed/shared-height model mismatch. This conservative
gate uses configuration, not synthetic per-observation labels. It does not
detect every possible misspecification or survey bias. A direct measurement-only
fit cannot inspect an unavailable generator; its uncertainty is explicitly
conditional on the declared Gaussian model. Robust/rejection fits always retain
conditioning diagnostics but have no finite covariance in this implementation.

For saved M6 known-map runs, the offline API converts native h/q parameters to
physical metre coordinates before calculation and accounts for the selected
positive-height branch bound. Legacy joint canonical gauges receive no finite
world covariance even if their gauge-fixed reduced Jacobian is full rank.
Failed, pending/interrupted, nonconverged, rank-deficient and bound-limited
outcomes expose reasons and null covariance.

## Persistence and service

A version `7.0` run contains the original complete version-6 experiment,
normalized survey/uncertainty options, every physical start/estimate/status,
solver settings, residual decisions, world evaluation, uncertainty assumptions
and results, and software versions. Existing source observations and IDs are
preserved; imports receive a new ID and retain the source ID. Strict validation
reconstructs the objective, analytic diagnostics, covariance, world evaluation,
pilot mask and selected attempt without fitting or calling the generator.
Source M6 deterministic validation is reused. Empty accepted requests retain
explicit initial proposals before dispatch; an interrupted process exposes the
request without claiming an optimizer checkpoint. Final write failure is
reported separately from optimizer success; permanent-write durability is not
guaranteed.

`register_m7(app, directory, executor=None, jobs=None, lock=None, on_saved=None)`
registers routes; the existing shared executor/jobs API can supply async work.

| Operation | Route |
| --- | --- |
| Submit config or original saved experiment plus options and optional initial_geometries | `POST /api/m7/runs` |
| Strict offline reopen of M6 or M7 | `GET /api/m7/runs/<id>` |
| One start's offline summary; selected start by default | `GET /api/m7/runs/<id>/uncertainty?start=0` |
| Complete validated run JSON | `GET /api/m7/runs/<id>/json` |
| All attempts and observations; failed/empty placeholders retained | `GET /api/m7/runs/<id>/csv` |
| Validate/import existing M7 record without solving | `POST /api/m7/import` |

Config and saved experiment are mutually exclusive request sources. With an
explicit saved experiment the POST path never generates data. JSON is the
complete authoritative numerical export; CSV includes attempt outcomes,
messages, residuals, weights and separate survey/prior objectives. Existing
viewer PNG export belongs to the UI integration. Source JSON remains
authoritative; metadata-cache notifications are optional and never substitute
for detail/import/export validation.

`tests/test_m7.py` and `tests/test_m7_service.py` check independent line-of-sight
derivatives and analytic covariance, selected masks, coupled-prior quadratic
forms, finite differences across tag models/losses, gauge/rank limits, bounds,
TRF/LM, label isolation, exact no-survey delegation, strict corruption checks,
offline reuse/import/export, nonconvergence, interruption and storage errors.
These module tests are not milestone acceptance or a coverage study.
