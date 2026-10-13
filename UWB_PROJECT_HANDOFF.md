# UWB joint localization and beacon calibration: project handoff

Prepared October 13, 2026. This document transfers a conceptual discussion into a new repository. No implementation, dataset, or numerical validation has been performed in that discussion.

## Purpose and background

Investigate jointly estimating a moving UWB tag's trajectory and a fixed UWB beacon map using tag-to-beacon ranges. The motivating application is autonomous vehicles. Vehicle-mounted radios are called tags; infrastructure radios are called beacons. Start with one tag.

The central insight is that beacon coordinates are shared across time. Each new planar tag position introduces two unknowns, while measurements to three beacons add three scalar constraints. With sufficiently informative motion, the measurements can calibrate the map as well as localize the tag. This is joint range-only localization and mapping, and can become range-only SLAM when motion constraints and sequential estimation are included.

The user initially referenced [Geomstats](https://github.com/geomstats/geomstats) and wants to understand whether its geometric methods could help. Do not assume it is the right dependency: first establish a working conventional nonlinear least-squares baseline and identify a specific geometric operation it could improve.

## What the user remembers from an earlier experiment

- Ceres Solver was tried, and the result was unsatisfactory. The residual definition, initialization, solver settings, logs, and data are not available yet.
- The reconstructed vehicle path did not appear planar. The user suspects tag heights were unconstrained in that experiment.
- After discussing free tag height, the user recalled that the experiment must have had four beacons. Treat this as recollection, not verified metadata.
- Beacons were placed above the tags. Whether this was explicitly encoded in the optimizer is unknown.
- Equal beacon height is a simplifying assumption for the new mathematical discussion; it is not verified for the historical deployment.

Do not present a specific cause of the historical failure as established. Possible causes include free height, weak geometry, initialization, gauge freedoms, residual modeling, range bias, and implementation errors.

## Initial model: planar tag trajectory and shared beacon height

Use a coordinate system attached to the tag's motion plane:

\[
p_i=(x_i,y_i,0),\qquad i=1,\ldots,N.
\]

This can represent a tag at a constant physical height above the ground: choosing its motion plane as zero makes beacon heights relative to the tag plane. It does not require mounting the tag at ground level.

For three beacons, fix the horizontal coordinate freedoms using

\[
b_0=(0,0,h),\qquad b_1=(d,0,h),\qquad b_2=(a,b,h),
\]

with \(d>0\), \(b>0\), and \(h>0\). Beacon 0 is the horizontal origin, not the full three-dimensional origin. Beacon 1 sets the positive x direction; beacon 2 selects the positive-y side.

For additional beacons, use \(b_j=(a_j,c_j,h)\). Assume beacon identities are known and measurements at each epoch refer to the same tag position. Asynchronous measurements require a timing or motion model.

Predicted ranges are

\[
R_{ij}=\sqrt{(x_i-a_j)^2+(y_i-c_j)^2+h^2}.
\]

At three beacons, there are \(3N\) measurements and \(2N+4\) unknowns after fixing the horizontal frame. Thus \(N\ge4\) is a necessary counting condition. It is not a proof of local identifiability or global uniqueness. Evaluate the Jacobian rank and actual geometry; several discrete solutions can exist.

For M equal-height beacons in this planar model, the corresponding count is \(NM\) measurements and \(2N+2M-2\) unknowns after fixing three horizontal frame freedoms. Missing measurements change the count and connectivity requirements.

Range data provide metric scale, but without external references the chosen map frame is arbitrary. A single tag does not independently measure vehicle heading.

## Algebraic structure and initialization

Let \(D_{ij}=r_{ij}^2\) denote exact squared ranges. For the three-beacon convention above, define

\[
u_i=D_{i1}-D_{i0},\qquad v_i=D_{i2}-D_{i0}.
\]

Subtracting equations cancels the common height and the squared vehicle norm:

\[
u_i=d^2-2dx_i,
\]

\[
v_i=a^2+b^2-2ax_i-2by_i.
\]

If the beacon geometry is known, these are a linear position solve:

\[
x_i=\frac{d^2-u_i}{2d},\qquad
y_i=\frac{a^2+b^2-v_i-2ax_i}{2b}.
\]

If the geometry is unknown, the products of unknown coordinates remain. More equations support solvability but do not turn the original system into a known matrix times an unknown vector.

Substitution into \(D_{i0}=x_i^2+y_i^2+h^2\) eliminates all trajectory variables, leaving one nonlinear equation per epoch in the four shared parameters.

A possible algebraic initializer fits the lifted polynomial

\[
D_{i0}=\alpha u_i^2+\beta u_iv_i+\gamma v_i^2+
\delta u_i+\eta v_i+\kappa.
\]

Its six coefficients can be fitted linearly when the design matrix with rows \([u_i^2,u_iv_i,v_i^2,u_i,v_i,1]\) has rank six. This initializer therefore needs at least six suitable samples, even though the original model's counting lower bound is four.

For exact physically valid coefficients,

\[
b=\frac{1}{2\sqrt\gamma},\qquad
\frac{a}{d}=-\frac{\beta}{2\gamma},\qquad
d=\frac{1}{2\sqrt{\alpha-\beta^2/(4\gamma)}}.
\]

Recover a, then the trajectory, and \(h^2=D_{i0}-x_i^2-y_i^2\). Check that the remaining polynomial coefficients agree with the recovered physical model. Noisy unconstrained fits may violate positivity or physical consistency. Validate these formulas numerically before using them in implementation.

More generally, double differences of squared ranges satisfy

\[
D_{ij}-D_{kj}-D_{i\ell}+D_{k\ell}
=-2(p_i-p_k)^\top(q_j-q_\ell),
\]

where \(q_j\) is the horizontal beacon coordinate. Hence the double-difference matrix has rank at most two for exact planar data, even with differing beacon heights. A rank-two factorization is another potential initializer; converting an arbitrary factorization to Euclidean coordinates requires additional metric constraints.

## Noise model and optimization baseline

Start with additive independent Gaussian range noise:

\[
\widetilde r_{ij}=R_{ij}+\epsilon_{ij},\qquad
\epsilon_{ij}\sim\mathcal N(0,\sigma_{ij}^2).
\]

Use normalized range residuals

\[
e_{ij}=\frac{R_{ij}-\widetilde r_{ij}}{\sigma_{ij}},\qquad
F=\frac12\sum_{i,j}e_{ij}^2.
\]

This is the baseline maximum-likelihood objective under those assumptions. Real UWB errors may include NLOS bias, calibration offsets, correlations, and outliers; introduce these only in clearly labeled later experiments.

Squaring noisy ranges changes the error model:

\[
\widetilde r^2-R^2=2R\epsilon+\epsilon^2,
\]

\[
\mathbb E[\widetilde r^2-R^2]=\sigma^2,\qquad
\operatorname{Var}(\widetilde r^2-R^2)=4R^2\sigma^2+2\sigma^4.
\]

Squared-range noise is biased and range-dependent. Differencing reuses measurements and introduces correlations. A lifted polynomial fit also has noise in its explanatory variables, so ordinary linear least squares is not the final statistical estimator.

Ceres is a suitable candidate for the nonlinear baseline. Use one unsquared residual per measurement, automatic differentiation, and a trust-region method such as Levenberg-Marquardt. Ceres squares residuals itself; returning an already squared residual creates a fourth-power objective.

Relevant derivatives, for R>0, include

\[
\frac{\partial e}{\partial x_i}=\frac{x_i-a_j}{\sigma_{ij}R},\qquad
\frac{\partial e}{\partial h}=\frac{h}{\sigma_{ij}R}.
\]

Avoid initializing the entire geometry at zero. Squared-distance residuals then have zero Jacobian despite large errors, while ordinary range residuals encounter a nondifferentiable zero distance. Initializing h at zero also gives zero first-order height sensitivity when optimizing h directly.

An alternative parameter is \(q=h^2\ge0\), giving

\[
R=\sqrt{(x_i-a_j)^2+(y_i-c_j)^2+q},\qquad
\frac{\partial e}{\partial q}=\frac{1}{2\sigma_{ij}R}.
\]

This avoids the zero-height derivative issue for R>0, but q has units of metres squared and needs appropriate scaling. Compare parameterizations rather than assuming one universally wins.

## Height, planarity, and four beacons

If tag heights are independently free, use

\[
R_{ij}=\sqrt{(x_i-a_j)^2+(y_i-c_j)^2+(z_i-h_j)^2}.
\]

Each epoch then adds three unknowns. Three measured ranges per epoch no longer supply a surplus of constraints for the unknown map; four ranges supply one net scalar constraint per epoch. Counting still does not establish identifiability.

Four equal-height beacons are coplanar. For a known beacon plane z=h, a tag point at z and its reflection at 2h-z give identical ranges. Explicitly requiring tags below that plane eliminates this reflection branch. Physical placement alone does not encode the requirement in the optimizer.

Being below the beacons is an inequality, \(z_i<h\). It does not imply a shared height, \(z_i=z_{\mathrm{tag}}\), across epochs.

For known beacon coordinates and exact consistent measurements, informative noncollinear equal-height beacons determine horizontal coordinates and the magnitude of the vertical separation. Selecting the below-plane branch recovers the correct height. A true constant-height path should therefore reconstruct as such in that ideal case.

With noisy measurements and independent z_i variables, vertical movement can improve the range fit. Sensitivity is

\[
\frac{\partial R_{ij}}{\partial z_i}=\frac{z_i-h_j}{R_{ij}}.
\]

Near an equal-height beacon plane this sensitivity is weak. Beacons above tags can constrain height well when the geometry is favorable; they do not automatically enforce trajectory planarity. Noncoplanar known beacons eliminate the common-plane reflection ambiguity.

A tilted but planar reconstruction may only reflect the arbitrary coordinate frame. A warped trajectory is different. For a free 3D model, fix the relevant 3D frame freedoms rather than reusing a planar gauge blindly.

If constant tag height is known, use a shared height or set its plane to zero. For small real height variations, consider a soft ground constraint with physically justified uncertainty. A general tilted plane is another possible model, but was not requested or developed in this discussion.

## Suggested first experiment (proposal, not an already authorized implementation spec)

Build a small reproducible simulator and batch estimator before applying real UWB data:

1. Generate an informative planar trajectory and three/four fixed equal-height beacons above it, with deterministic random seeds and recorded ground truth.
2. Verify noiseless recovery with the planar model, a fixed coordinate convention, and multiple nondegenerate initializations. Distinguish successful range fitting from correct geometric recovery.
3. Compute Jacobian singular values after gauge fixing. Compare informative motion to a straight line, small spatial coverage, and nearly collinear beacon layouts.
4. Add controlled Gaussian range noise. Report beacon and trajectory error, original-range residuals, convergence status, and variability across seeds and initializations.
5. Compare constrained planar and independently free-height models with four beacons. For that comparison, clearly label whether the beacon map is known or jointly estimated, enforce equivalent frame conventions, and examine below-plane bounds separately from constant-height constraints.
6. Compare h and q=h^2 parameterizations, and an algebraic initializer against plausible multi-start initialization.
7. Only then explore outliers, unequal heights, motion/odometry factors, missing ranges, and potential Geomstats methods.

Use plots of reconstructed geometry and residuals to explain outcomes. For free-height fits, evaluate planarity relative to a best-fit plane as well as the chosen coordinate z axis.

The implementation language and repository structure remain undecided. Python with NumPy/SciPy is a possible quick baseline; C++/Ceres is another. Do not assume a choice was made or that Geomstats integration is mandatory.

## Open questions for the new project

- What code and conventions already exist in the new repository?
- Is historical data or the old Ceres implementation available?
- Were beacon heights actually equal, surveyed, or unknown?
- Was tag motion planar, and was the tag mounting height constant?
- Were there additional constraints from odometry or an IMU?
- Were all ranges synchronized, and were per-beacon range biases calibrated?
- Is the first deliverable a mathematical study, a simulator, or a production estimator?

Progress with the synthetic baseline where appropriate rather than requiring all historical details first.

## References

- [Geomstats repository](https://github.com/geomstats/geomstats): geometry and statistics on manifolds; a candidate to assess, not a selected solver.
- [Ceres modeling documentation](https://ceres-solver.readthedocs.io/latest/nnls_modeling.html): residual blocks, automatic differentiation, bounds, and robust losses.
- [Ceres solving documentation](https://ceres-solver.readthedocs.io/latest/nnls_solving.html): trust-region algorithms and solver diagnostics.

## Starter prompt for a new project chat

> Read docs/UWB_PROJECT_HANDOFF.md and inspect this repository. Use the document as background, distinguishing known facts, simplifying assumptions, and proposed experiments. Summarize the current mathematical model and the first useful experiment. Before treating equation counts as proof, assess observability after fixing the coordinate freedoms. Keep Geomstats as a candidate until there is a concrete reason to use it. We are continuing the UWB joint localization and beacon-calibration investigation described in the handoff.
