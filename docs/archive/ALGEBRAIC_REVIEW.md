# M5 algebraic initializer and independent mathematical review

`uwb/m5_algebraic.py` exposes `propose_initialization(observations, times_s,
beacon_count, options=None)`. It receives no experiment or truth argument. Its
result retains `status`, `diagnostics`, `geometry` and `error`; unsuccessful
proposals have no geometry. M5 retains every failed initializer attempt and
does not substitute an independent initializer.

## Supported measurement contract

The initializer supports joint planar tags with the fixed/shared tag-height
model and a shared beacon height, with 3–8 identified beacons. Every supplied
epoch must contain exactly one finite strictly positive measured range to
every beacon. At least six epochs are required, and the six-column lifted
design must have full numerical rank. Six observations of uninformative motion
do not suffice. Missing data are rejected rather than interpolated or replaced.

Every estimator-assumed ping timestamp must equal its supplied epoch time to
within `1e-9 s`. A grouped asynchronous approximation is rejected. Actual and
delivery timestamps and synthetic truth metadata are excluded from the
measurement-only calculation. Thus support refers to the asserted estimator
timing; this calculation cannot detect undisclosed physical clock error or
unequal beacon heights from metadata it does not receive.

Known-map calibration, free/soft tag heights and independent beacon heights
are unsupported by this initializer. Full M5 solver options can be supplied;
solver and height-coordinate choices do not affect the algebraic fit. The
proposal uses the supplied cycle times as its knot grid. M5 explicitly
interpolates this saved geometry to a different declared solver grid before
optimization. This projection is an initial guess, not a new measurement.

## Lifted equations and physical constraints

Let `Dij = rij²`, `u = Di1-Di0` and `v = Di2-Di0`. Choose the canonical
horizontal map `(0,0)`, `(d,0)`, `(a,b)`, with `d>0` and `b>0`. With the tag
plane as the height datum,

\[
x=(d^2-u)/(2d),\qquad
y=(a^2+b^2-v-2ax)/(2b).
\]

The lifted fit is

\[
D_{i0}=\alpha u_i^2+\beta u_iv_i+\gamma v_i^2+
\delta u_i+\eta v_i+\kappa.
\]

Writing `c=(a²+b²-ad)/(2b)` gives the independently checked coefficients

\[
\alpha=\frac1{4d^2}+\frac{a^2}{4b^2d^2},\quad
\beta=-\frac a{2b^2d},\quad
\gamma=\frac1{4b^2},\quad
\delta=-\frac12+\frac{ac}{bd},\quad
\eta=-\frac cb,\quad
\kappa=\frac{d^2}4+c^2+h^2.
\]

Recovery uses

\[
b=\frac1{2\sqrt\gamma},\quad
d=\frac1{2\sqrt{\alpha-\beta^2/(4\gamma)}},\quad
a=-\frac{\beta d}{2\gamma}.
\]

Both `gamma` and its Schur complement must be strictly positive. The fitted
linear coefficients must match the recovered physical `delta` and `eta`.
Per-epoch `h²=Di0-x²-y²` and intercept-derived
`h²=kappa-d²/4-c²` must be positive and agree within the disclosed tolerance.
Negative or zero height squared is retained as a failure and is never clipped.
All recovered geometry must be finite. These checks reject an unconstrained
quadratic fit that reproduces squared data but fails the original physical
model.

For beacon IDs 3–7, fit

\[
D_{ij}-D_{i0}=-2x_i a_j-2y_i c_j+w_j.
\]

The three-column horizontal-position design must have full numerical rank.
Each fitted intercept must satisfy `wj=aj²+cj²`, and its squared-difference
residuals must meet the same tolerance. This recovers additional anchors from
physical equations; no surveyed or truth map supplies their coordinates.

## Scaling, tolerances and noisy failures

Let `L` be the median positive measured range. The fit divides ranges by `L`
before squaring, so squared ranges and differences use units `D/L²`. It centers
and standardizes the two differences, forms their quadratic polynomial design,
and divides each design column by its RMS. Diagnostics retain all scaling
values, fitted coefficients in dimensionless and metre units, singular values,
rank and condition number. Numerical rank uses `1e-8` times the largest
singular value. The condition-number warning threshold is 1000. These are
disclosed numerical diagnostics, not error bounds or uniqueness proofs.

`algebraic_physical_tolerance` defaults to `1e-7`. Physical linear-coefficient
errors are dimensionless; squared-height departures, extra-beacon squared-norm
closure and extra-beacon equation residuals are tested in squared-range units
divided by `L²`. This is a compatibility tolerance, not a measurement noise
standard deviation or statistical goodness-of-fit test. The M5 options layer
permits values from `1e-12` through `0.1`.

Strict default checks generally reject noisy unconstrained fits. Increasing
the tolerance can admit approximate proposals but does not repair the noise
model. Squaring additive Gaussian range errors introduces mean `sigma²` and
variance `4R²sigma²+2sigma⁴`; differences also reuse noisy observations, and
the polynomial explanatory variables are noisy. Ordinary linear least squares
is therefore only an initializer. M5's final objective always uses the
original unsquared normalized range residuals. Diagnostics retain the fitted
polynomial, physical mismatches, height estimates and proposal range residuals
where those stages were reached, including on failure.

The positive height-separation and positive beacon-2-y conventions select
reflection branches. Negating every horizontal y coordinate or reflecting the
beacon plane across the fixed tag datum preserves distances. Diagnostics
disclose these alternatives; the range data alone do not choose their sign.
Full lifted rank is local information for this construction and does not prove
global uniqueness of the nonlinear model.

## Independent verification and repairs

Run `.venv/Scripts/python.exe scripts/review_m5.py`. Each invocation writes a
new `evidence/m5/independent_review_<timestamp>_<id>/review.json` and updates
`evidence/m5/independent_math_review.json`. Earlier review attempts remain on
disk, including failures. Expected values use directly assembled Euclidean
distances, physical coefficient equations and analytic range/prior derivatives.

The review checks independent seeded exact geometry for every count 3–8,
all six physical coefficients, shuffled observation order, sign-reflection
invariance, noisy invalid fits, negative gamma, negative height squared,
incompatible linear coefficients, missing data, asynchronous timestamps,
insufficient epochs and straight-line rank loss. It poisons truth-only
metadata and verifies identical algebraic proposals and independent starts.

The solver review checks h/q range residuals, derivatives and dimensionless
scaling for joint and surveyed horizontal planes at 2.2 m and 10 micrometres
separation. It checks q's limiting derivative at zero without confusing its
singular inverse to h with new physical height information. Every supported
h height-model combination is checked against direct range, motion-prior and
soft-height-prior derivatives, including six-beacon free/soft models and LM
chains for finite lower and upper bounds. Unsupported coupled below-beacon
inequalities must fail explicitly. Budget exhaustion retains finite
nonconverged estimates.

The review exposed exponential underflow/roundoff reaching an LM bound with a
zero or ineffective chain derivative. The repaired transform rejects lost
strict interior, nonfinite coordinates and zero derivatives explicitly.
`pre_fix_defect_reproducer.json` retains the reconstructed former equations
and their failed contract alongside the repaired check. The review also
exposed variant overrides of start-generating controls during paired reuse;
variants now reject `initialization_error_m` and
`algebraic_physical_tolerance` overrides so those controls remain shared.

Some original near-zero-height LM attempts reached a numerical bound before
that repair. Their raw recorded statuses remain inspectable as historical
evidence; bound validity is a separate derived diagnostic and those estimates
do not establish the claimed strict-interior feasibility. New fits identify
bound-transform revision 2 and enforce that domain on reopening. The independent
review explicitly lists any historical bound-invalid estimates it encounters.

Retained acceptance review traverses source folders recursively and checks
the number of sweeps, demo files, runs and attempts against the acceptance
summary, so a nested bundle cannot produce an empty passing review. The
repaired bundle contains nine solver sweeps and eight standalone demo files.
The review independently recomputes original-range residuals, measurement
objectives, initial objectives and Jacobians for every finite estimate,
validates paired starts and saved source artifacts, and verifies the M0–M4
preservation manifest. Failed and nonconverged attempts remain in the saved
results. Source validation additionally recomputes saved residuals, objectives
and native parameters, together with physical/native/augmented rank spectra,
when reopening an artifact; it does not re-run a solver.

Native model projection is disclosed separately from M4's preceding physical
projection. For signed beacon height -3 m, the native positive-branch seed
projection moves the map by `3.000002 m`, while M4's unconstrained physical
projection has zero displacement. The reviewed h and q fits still reproduce
the distances to within `1.78e-15 m` through the positive reflected branch.
Thus that projection displacement is not an optimizer lower bound or an
unavoidable range mismatch. An additional degenerate reference-triangle check
retains all three requested truth-near failures for each solver, including the
original frame-construction error and unavailable native-projection reason.

Reopening uses retained native final coordinates and checks their agreement
with the displayed geometry. An independent surveyed-plane example at z=10 m
has valid native `h=1e-6 m`, but subtracting the saved tag world z recovers
`9.999999992515995e-7 m`; re-packing that rounded world geometry would wrongly
reject the height floor. The native-coordinate check preserves the declared
domain while still recomputing residuals, objectives and information diagnostics.

The final reviewed source is
`evidence/m5/acceptance_20261014_124422_c74e2389`. Its nine sweeps contain 160
runs and 320 attempted starts; eight demo files add 16 starts, totaling 336.
The retained statuses are 280 success, five nonconverged and 51 failed, with
285 finite estimates and 40 invalid algebraic attempts. The independent review
found zero direct normalized-range residual disagreement, maximum analytic
Jacobian disagreement `3.55e-15`, and no bound-invalid estimate in this repaired
bundle. All 649 preservation-manifest files match. The final retained review
is `evidence/m5/independent_review_20261014_165451_229006a4/review.json`.

The conditional second-implementation decision is retained in
`evidence/m5/second_implementation_decision.json`. It defers a Ceres port:
the present paired strategies and direct-equation review resolve the measured
solver/parameterization/initializer questions without a native build. No Ceres
comparison was performed, and this decision claims neither cross-implementation
agreement nor Ceres performance. A reproduced same-settings discrepancy or a
measured larger-problem need would justify revisiting it. The named candidate
Geomstats operation is proper rigid Euclidean alignment; the current reviewed
NumPy SVD implementation has no demonstrated unmet requirement.
