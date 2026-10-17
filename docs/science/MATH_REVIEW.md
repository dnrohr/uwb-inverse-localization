# Independent mathematical review: synchronized planar

Reviewed October 13, 2026 against `docs/archive/PROJECT_REQUIREMENTS.md`,
`docs/archive/UWB_PROJECT_HANDOFF.md`, the generator and estimator, and the nine final saved
reference runs. This review covers synchronized measurements, four beacons,
planar tag positions, and a shared positive beacon height. It supplies no
validation of timing, free-height, multipath, or historical Ceres experiments.

## Assessment

The baseline mathematics and saved reference evidence pass independent checks.
No blocking mathematical defect was found. The informative exact experiment
recovers geometry from independent initialization; the straight-line experiment
correctly exposes a continuous ambiguity. Weak geometry also demonstrates
converged solutions with substantial geometric error. These outcomes support
the synchronized planar baseline, rather than a general guarantee of unique recovery.

## Objective, derivatives, and frame

Each residual is `(predicted_range - observed_range) / sigma_m`. This is an
unsquared range residual with one positive assumed standard deviation per
observation; its least-squares objective is half the sum of squared normalized
residuals. The Gaussian noise injected by the generator and uncertainty used
by the estimator are separate settings. Squared-range differences are used
only to initialize positions.

For horizontal tag coordinates the derivative is `(p_xy - b_xy)/(R sigma)`;
estimated horizontal beacon coordinates have the opposite sign. The shared
height derivative is `h/(R sigma)`, because every tag has z=0. Finite differences
verified both known-map and joint derivatives, including heterogeneous
uncertainties and reversed observation ordering. The reference check's largest
absolute derivative discrepancy was approximately `1.93e-9`; the regression
check uses `rtol=atol=2e-8` with a central-difference step of `1e-5 m`.

The joint variables are `2N` planar tag coordinates and six map variables
`(d,a,b,c,e,h)`, all in metres: `b0=(0,0,h)`, `b1=(d,0,h)`,
`b2=(a,b,h)`, `b3=(c,e,h)`. Fixing b0's horizontal position and b1's
horizontal direction removes the two translations and one rotation. The
positive b2 y coordinate selects the horizontal handedness convention. The
positive shared height encodes beacons above the fixed tag plane and selects
the vertical sign branch. These conventions are explicit model choices;
range data alone cannot establish an external compass direction or vertical
sign. Joint bounds use a `1e-6 m` positive floor for d, b, and h. Exact collinear
b0/b1/b2 geometry and zero height fall outside this canonical parameter domain.

Known-map localization estimates only `2N` tag coordinates and keeps the
explicitly supplied surveyed map fixed. It receives that map from synthetic
truth in the experiment wrapper, which is appropriate for this declared
known-map comparison. Independent joint fitting accepts observations, epoch
times, solver settings, and optional explicit initial geometries; it accepts
no truth object. Replacing the wrapper's valid truth trajectory and map while
holding observations fixed produced identical independent initial and fitted
joint geometries. Truth-near initialization is a separate, labeled diagnostic.

## Rank and alignment

The diagnostic spectrum is calculated from `scale * J`, where J is the
measurement-only Jacobian of normalized residuals and
`scale=max(median(abs(observed_ranges)),1 m)`. This is differentiation with
respect to dimensionless coordinates `theta/scale`. It supplies no priors or
motion information. All coordinates receive the same length scale, so that
scale does not change the condition number. Uniformly multiplying all assumed
uncertainties rescales the spectrum and absolute threshold together, preserving
the reported rank and condition number; a regression test verifies this.
Heterogeneous uncertainties do change the row weights and weighted spectrum.

Numerical rank counts singular values exceeding `1e-8 * largest_singular_value`.
This is a stated numerical separation rule, not a physical uncertainty limit,
a proof of global uniqueness, or the solver's termination tolerance. Full rank
means local measurement sensitivity in the chosen parameterization. Small
nonzero singular values still permit severe noise amplification. Condition
warnings are heuristics and should be interpreted alongside the full spectrum.
The weak-condition warning uses a disclosed condition-number threshold of
1000 and checks truth as well as the selected fitted geometry.
Active positivity bounds can additionally affect a constrained solution;
the measurement Jacobian does not attribute information to those bounds.

Joint evaluation uses a map-only least-squares proper planar rigid transform.
Tests confirm that it preserves all pairwise tag/beacon ranges and recovers
an arbitrary common planar rotation/translation. It fixes scale to one,
preserves z, and does not allow reflection or 3D tilt. Separate tests verify
that scale changes, mirrored geometry, vertical shifts, and tilt cannot be
hidden by this alignment. Known-map evaluation applies no alignment. Raw
canonical errors remain available independently of the aligned display.

## Saved reference evidence

The following numbers are from the saved 32-epoch runs, with 128 measurements
and three starts each. Joint problems have 70 variables; known-map problems
have 64. Position error is the selected start's maximum raw error at matched
sample times, and map error is its maximum raw per-beacon error.

| Run | Truth rank | Truth condition | Max position error (m) | Max map error (m) |
| --- | ---: | ---: | ---: | ---: |
| Exact joint, independent | 70/70 | 41.44 | 2.60e-15 | 9.49e-16 |
| Exact joint, truth-near | 70/70 | 41.44 | 1.78e-15 | 2.22e-16 |
| Exact known map | 64/64 | 1.40 | 1.26e-15 | 0 |
| Gaussian joint, seed 7 | 70/70 | 41.44 | 0.1813 | 0.1448 |
| Gaussian joint, seed 8 | 70/70 | 41.44 | 0.1931 | 0.1841 |
| Straight line | 69/70 | Rank deficient | 0.1134 | 0.1713 |
| Narrow coverage | 70/70 | 1056.57 | 1.91e-14 | 3.54e-14 |
| Nearly collinear map | 70/70 | 10829.73 | 2.80e-13 | 1.13e-13 |
| Forced nonconvergence | 70/70 | 41.44 | 1.3727 | 1.7084 |

All three informative independent exact starts recover geometry, and their
maximum absolute range residuals are at most `1.78e-15 m`. These comfortably
satisfy the declared exact-data acceptance thresholds: `1e-5 m` maximum tag
and beacon error and `1e-7 m` maximum absolute range residual. The thresholds
are implementation/recovery acceptance criteria; they are not confidence
intervals, uncertainty estimates, or useful accuracy targets for noisy data.
The two Gaussian runs have selected range RMSE below the injected `0.05 m`
standard deviation because parameters are fitted; that alone establishes
neither overfitting nor superior geometry. Their geometric errors remain visible.

Narrow coverage and nearly collinear beacons remain locally full rank but have
approximately 26 and 261 times the informative condition number. Their exact
selected solutions establish feasibility, not stability under noise. Two of
the nearly collinear starts converge to distorted local minima with trajectory
RMSE `6.83 m` and `6.42 m`; their objectives are `0.0158` and `0.0191`, compared
with approximately `1.61e-26` for the recovered third start. A solver success
flag must therefore be distinguished from geometric recovery and range-fit
acceptance. Finite-start variability cannot certify that every alternative
solution has been found, even when all starts agree.

## Exact straight-line ambiguity

The straight-line truth has tag y coordinate k=2 m and h=3 m. There is an exact
continuous family even after the prescribed gauge is fixed. For q=1 square
metre, keep all x coordinates unchanged and set

```
k_new = sqrt(k^2 - q)
h_new = sqrt(h^2 + q)
tag_y_new = k_new
beacon_y_new[j] = k_new + sign(beacon_y[j] - k)
                             * sqrt((beacon_y[j] - k)^2 - q)
```

This leaves b0.y=b1.y=0, d>0, b2.y>0, and h>0, while changing trajectory and
map geometry. Every range remains identical: the change in squared height
exactly cancels the change in squared perpendicular offset. The independent
test verifies this to `8e-14` in normalized residuals and observes rank `21/22`
for an eight-epoch version. Height changes cannot be removed by permitted
planar rigid alignment. The 32-epoch saved run has rank `69/70`; three starts
reach distinct geometries with effectively zero residuals. This is genuine
unidentifiability, not an optimizer defect or an unfixed planar gauge.

## Reproducibility and retained failures

All 27 final saved starts retain their initial geometries, estimates, objectives,
normalized/metre residuals, rank diagnostics, and solver settings. Independently
recomputed residuals match the serialized values exactly, and recomputed
objectives/ranks agree. Every saved initial geometry satisfies its declared
frame and positive initialization requirements. Run persistence preserves the
measurement realization and can be reopened without invoking a solver.

Forced one-evaluation runs retain both `not_converged` starts, including their
finite estimates. An explicit invalid negative-d start is retained as `failed`
with its exception message and no estimate. SciPy evaluation counts are saved;
iteration count is correctly left unavailable rather than inferred. Recorded
per-start runtime measures solving, not full application latency. Convergence
failure counts and distinct-geometry grouping should be read according to their
saved definitions; solution groups may include finite nonconverged or imperfect
fits. The final diagnostic code separately records per-start optimizer status,
geometry acceptance, range acceptance, and groups satisfying the exact-range
threshold. Thus the nearly collinear case has one accepted exact-range group,
while the straight-line case has three. These exact-data flags intentionally
do not quantify useful noisy accuracy; inspect the continuous error metrics.
Final diagnostic changes were inspected after the initial evidence audit and
do not alter the objective, derivatives, initialization, or selected fits.

Validation command: `.venv\Scripts\python -m unittest discover -s tests -p
test_review.py -v` passes five independent structural tests. Review computations
also checked the nine final saved run files, truth replacement, and forced failure
paths. The remaining scientific limitation is global ambiguity and basin
coverage: local rank and three starts do not prove uniqueness or robustness
over arbitrary configurations.

## Integration review addendum

A focused code review of `app.py`, `web/app.js`, and persistence boundaries
identified and prompted corrections to the displayed default start, reopening
a saved run during solving, immediate failed-job rendering, small-number
formatting, and separation of inspected-start recovery flags from whole-run
statistics. The default now honors the saved `selected_start`, which matters
particularly for the nearly collinear reference: the recovered third start
must not silently be replaced by the distorted first start. Missing metrics
remain unavailable rather than becoming zero; sufficiently small nonzero
values use scientific notation, so the `1e-8` rank tolerance remains legible.

Scenes use `aspectmode='data'`, explicit metre axes, and shared ranges for
displayed geometry, preserving equal metric scale. Aligned fitted geometry,
initial geometry, error vectors, and measurement rays use the same permitted
planar rigid frame. Reported raw/aligned errors select the matching evaluation.
Layer checkbox state is reapplied when a new scene is drawn. Empty charts now
purge the previous Plotly chart, and empty scenes clear traces and disable PNG
export. Camera changes are captured through a relayout handler; interactive
camera and visual rendering checks are performed separately by the main agent.
Unavailable alignment resets the coordinate selector to raw, and scene purge
resets the camera-handler marker so later scenes can bind it again. The scene
subtitle follows the actual coordinate choice.

The review reproduced a malformed import that previously returned HTTP 200
and then broke run history with HTTP 500. Final validation rejects non-object
options/diagnostics and per-start records, invalid or repeated start indices,
malformed geometry, and invalid selected-start references. Rechecks confirm
HTTP 400 for `options:null`, `starts:[null]`, and a selected index absent from
the outcomes. A complete failed envelope with `starts:[]` still imports and
reopens successfully, and run history remains HTTP 200.

Submissions now reject non-finite JSON, invalid initialization seeds, and
unknown solver options before queueing. Independent probes confirm HTTP 400
for a NaN seed, negative seed, and unknown option; these cases cannot become
permanently running jobs through an unserializable failure envelope. A pending
envelope is saved before dispatch, and atomic temporary-file replacement
prevents readers from seeing a partially written result. The regenerated
evidence includes three retained one-evaluation `not_converged` starts, with
selected maximum range error `1.3579 m`. All 27 final saved starts were
independently rechecked for residual, objective, and rank agreement.

