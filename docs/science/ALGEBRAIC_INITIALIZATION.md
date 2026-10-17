# Algebraic initialization

`uwb/m5_algebraic.py` exposes `propose_initialization(observations, times_s,
beacon_count, options=None)`. It receives no experiment or truth argument. Its
result retains `status`, `diagnostics`, `geometry` and `error`; unsuccessful
proposals have no geometry. solver retains every failed initializer attempt and
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
are unsupported by this initializer. Full solver solver options can be supplied;
solver and height-coordinate choices do not affect the algebraic fit. The
proposal uses the supplied cycle times as its knot grid. solver explicitly
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
standard deviation or statistical goodness-of-fit test. The solver options layer
permits values from `1e-12` through `0.1`.

Strict default checks generally reject noisy unconstrained fits. Increasing
the tolerance can admit approximate proposals but does not repair the noise
model. Squaring additive Gaussian range errors introduces mean `sigma²` and
variance `4R²sigma²+2sigma⁴`; differences also reuse noisy observations, and
the polynomial explanatory variables are noisy. Ordinary linear least squares
is therefore only an initializer. solver's final objective always uses the
original unsquared normalized range residuals. Diagnostics retain the fitted
polynomial, physical mismatches, height estimates and proposal range residuals
where those stages were reached, including on failure.

The positive height-separation and positive beacon-2-y conventions select
reflection branches. Negating every horizontal y coordinate or reflecting the
beacon plane across the fixed tag datum preserves distances. Diagnostics
disclose these alternatives; the range data alone do not choose their sign.
Full lifted rank is local information for this construction and does not prove
global uniqueness of the nonlinear model.

## Numerical validation

The initializer is checked against original unsquared range residuals, physical constraints and analytic derivatives. Invalid proposals remain explicit failed attempts. The final nonlinear solver uses the range objective rather than the lifted squared-range equations. For detailed source checks, run the relevant tests under `tests/`.
