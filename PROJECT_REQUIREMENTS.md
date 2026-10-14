# UWB localization experiment workspace

## Purpose

Build an interactive, reproducible research workspace for understanding when UWB ranges can recover a moving vehicle-mounted tag trajectory and an unknown beacon map. The central interface is a rotatable 3D view of ground truth and estimated geometry, paired with controls and numerical diagnostics.

This document defines requirements, not a choice of implementation language, visualization framework, or solver library. UWB_PROJECT_HANDOFF.md supplies the mathematical background. Historical Ceres results and deployment assumptions remain unverified.

## Questions the workspace must answer

- Can the estimator recover the tag path and beacon map, rather than merely fit the ranges?
- How do motion, beacon placement, and spatial coverage affect observability and uncertainty?
- How much error results from treating sequential pings as simultaneous?
- How do constant-height constraints, free height, and beacon height diversity affect recovery?
- How do noise, initialization, and solver choice affect accuracy and convergence?
- Eventually, which multipath and outlier treatments improve geometry without discarding useful measurements?

## Initial scope

Start with one tag, four stationary beacons, a planar ground-truth trajectory, equal beacon height above the tag plane, exact synchronized ranges followed by independent additive Gaussian range noise, and a batch nonlinear least-squares estimator. Support both a known-map localization mode and a joint trajectory/map estimation mode.

Build the visualization and reproducible baseline first. Sequential ping timing, variable speed, and constrained versus free tag height are required subsequent capabilities. Multipath rejection is a later extension after those comparisons work.

## Experiment data and measurement model

Represent ground truth as a time-indexed trajectory p(t). Each range record must contain beacon identity, measurement timestamp, observed range, and assumed range uncertainty. Preserve the actual measurement time and any timestamp supplied to the estimator separately.

Generate each observation from the tag's position at its actual measurement time:

    r_k = ||p(t_k) - b_j|| + epsilon_k

The asynchronous estimator must evaluate or interpolate the estimated trajectory at each measurement time. Its trajectory parameterization, knot spacing, interpolation rule, and any motion prior must be explicit experiment settings. Do not introduce a new unconstrained 3D point for every individual ping and claim that this alone handles asynchronous localization.

Keep three timing effects separate:

- Sequential acquisition: different beacons are measured at different physical times.
- Timestamp error: the estimator receives an incorrect time for a measurement.
- Delivery latency: a correctly timestamped measurement arrives later. This affects an online estimator; it does not alter the measurement geometry in a timestamp-aware batch fit.

Compare a timestamp-aware estimator with a deliberately grouped, simultaneous-ping approximation using exactly the same generated observations. State the grouping reference time and rule.

## Experiment controls

| Variable | Required controls and comparisons |
| --- | --- |
| Tag path | Straight line, circle/arc, rectangle, figure-eight, and spatially spread waypoint path; path size, location, duration, and sampling density. Add a 3D path to test violations of planarity later. |
| Motion | Constant speed initially; variable speed, acceleration, stops, and direction changes. Define speed over time and show it alongside the geometry. |
| Beacon count | Default four; support at least three through eight where the chosen model permits. Flag insufficient or unobservable configurations. |
| Beacon geometry | Editable coordinates; equal-height and varying-height layouts; collinearity, coplanarity, horizontal baseline, vertical separation, and tag inside/outside beacon coverage. |
| Ping schedule | Simultaneous baseline; ordered sequential pings; cycle rate, within-cycle spacing, beacon order, and timing jitter. Add missing observations and unequal per-beacon rates later. |
| Timing knowledge | Exact timestamps versus grouped timestamps; configurable offset/jitter later. Record actual and assumed times. |
| Noise | Noiseless baseline and additive Gaussian noise in metres; global standard deviation and per-beacon standard deviations; deterministic random seed. Separate injected noise from uncertainty assumed by the estimator. |
| Tag height model | Fixed/shared motion plane; soft height constraint with stated uncertainty; independently free trajectory heights. Below-beacon constraints are separate from a constant-height constraint. |
| Beacon knowledge | Surveyed/fixed map versus jointly estimated map; shared unknown height versus independent unknown heights where supported. Later, partially known coordinates and uncertain survey priors. |
| Solver | Begin with one trusted batch least-squares baseline; compare Levenberg-Marquardt and a bounded trust-region method when feasible. Later compare another implementation, such as Ceres, against identical data and objectives. |
| Initialization | Perturbation around truth for diagnosis; plausible independent initialization; multiple starts; eventually an algebraic initializer. Truth-based initialization must be visibly labeled. |
| Parameterization | Shared h versus q=h², with bounds and scaling specified; record all parameter units. |
| Later error models | Positive NLOS/multipath bias, outlier bursts, per-beacon offsets, correlated noise, quantization, and dropout. Add each separately before combining them. |

Restrict comparisons to solver capabilities: classical LM does not directly support general bounds. Any transformation used to enforce positivity must be recorded, and solver comparisons must acknowledge resulting parameterization differences.

Additional useful variables are trajectory knot spacing, initial-guess error, measurement density, range uncertainty miscalibration, motion-prior strength, and partial beacon survey knowledge. These can expose model limitations independently of solver quality.

## Estimation and observability requirements

- Use one normalized, unsquared range residual per measurement as the Gaussian baseline. Robust losses and bias parameters are separate, labeled model changes.
- Encode the chosen height model directly. Physical beacon placement does not imply an optimizer constraint.
- Remove coordinate freedoms before diagnosing rank. Planar and free-3D models require different frame conventions. Any remaining reflection ambiguity or continuous freedom must be reported.
- For free-3D joint fitting, explicitly fix translation and rotation freedoms using a suitable beacon-frame convention. Do not retain a planar coordinate convention without checking its validity. Explain which physical constraints distinguish reflected solutions.
- Compute numerical rank and singular values of the measurement Jacobian with a documented tolerance and parameter scaling. Report measurement-only information separately from information supplied by priors.
- Diagnose at ground truth as well as at the fitted solution. Equation counts are a screening check, not a proof of observability or uniqueness.
- Mark unsupported or unidentifiable configurations with an explanation. A solver may still run for exploration, but must not label such a fit as uniquely recovered.
- Keep optimizer convergence, residual quality, geometric accuracy, and identifiability as distinct diagnostics.
- Treat shared-height coplanar beacons and freely varying tag height carefully: a below-plane constraint removes a reflection branch but does not impose a planar trajectory or supply a missing height reference.

## Interactive 3D visualization

- Rotate, pan, and zoom the scene with mouse/touch controls; provide reset, top, side, and perspective views.
- Show ground-truth and estimated tag trajectories and beacon coordinates simultaneously, with distinct styling, a legend, beacon IDs, metre axes, and equal spatial aspect ratio.
- Toggle truth, estimates, initial guesses, error vectors, measurement rays, and the tag/beacon planes independently.
- Scrub or animate time. Show the actual tag position for each ping, its receiving beacon, and the cycle's assumed common position in the simultaneous approximation.
- When estimates are discrete, show fitted samples separately from interpolated trajectories. A smooth connecting curve must not be mistaken for measured information.
- Compare at least two saved runs using the same camera, scale, time reference, and geometry alignment.
- Color estimated points or range rays by position error, signed range residual, or rejection status; disclose the selected quantity and color scale.
- Show raw coordinates and an optional aligned comparison. Alignment must use only valid model symmetries, never rescale metric geometry, and explicitly disclose reflection handling. Known-map runs remain in the surveyed frame.
- For free-height fits, show both z versus time and departure from a best-fit plane so a tilted plane can be distinguished from a warped path.
- Preserve the camera when changing display layers or reviewing runs. Expensive fits must execute through an explicit Run action with visible status, keeping visualization responsive.

## Diagnostics and experiment comparison

Every run must report:

- Trajectory position RMSE, maximum error, and error versus time, evaluated at matched times and with any alignment disclosed.
- Per-beacon and aggregate map error when a map is estimated.
- Range residuals in metres and normalized units, residual distribution, and residuals by beacon and time.
- Height error and best-fit-plane departure for free-height runs.
- Measurement count, parameter count, Jacobian rank, scaled singular spectrum, and the documented numerical rank tolerance.
- Solver termination reason, iteration count, objective evaluations if available, wall time, and initial/final objective.
- Variability across random seeds and initializations, including failure rate and distinct low-residual solutions.
- Later, uncertainty summaries only when the stated noise model and local rank support them; distinguish conditional local uncertainty from global ambiguity.

Comparison charts must accompany the 3D scene: error versus noise level, ping spacing, speed, beacon count, or another selected variable. Controlled sweeps should vary one factor initially; paired estimator comparisons must reuse the same observations and initial guesses where compatible.

## Reproducibility and export

- Save the complete configuration, seeds, truth, actual and assumed timestamps, observations, initialization, estimates, solver settings, versions, diagnostics, and run status.
- Export machine-readable run data/configurations and a scene image or report suitable for sharing.
- Reopen a saved run without rerunning its solver. Reproducing a fit must preserve the measurement realization.
- Distinguish synthetic results from future recorded UWB data; never silently substitute truth for estimator input.
- Define supported configuration limits and benchmark interactive performance once the implementation stack is selected.

## Delivery sequence and acceptance criteria

### 1. Four-beacon baseline and 3D viewer

Generate noiseless and Gaussian-noise data with synchronized pings; provide known-map and joint planar estimation, multistart runs, a rotatable truth/estimate scene, and saved results.

Acceptance: for a documented, observable noiseless reference scenario, an independently initialized fit recovers both ranges and geometry within declared numerical tolerances. A truth-near initialization separately checks implementation correctness. A straight-line or degenerate-layout case demonstrates rank loss or poor conditioning without claiming unique recovery. A fixed seed recreates the same observations. All errors and convergence outcomes remain visible, including failed runs.

### 2. Timing and motion experiments

Add variable-speed paths and sequential ping schedules; compare timestamp-aware and grouped-time models with animation of individual pings.

Acceptance: zero within-cycle spacing reproduces the synchronized baseline. A stationary tag shows no geometric effect from acquisition spacing alone. Moving-tag experiments quantify the approximation error as spacing and speed change. Correctly timestamped delivery latency alone does not change a batch solution. The trajectory representation and motion priors are disclosed.

### 3. Height, geometry, and solver comparisons

Add constrained/free tag height, varying beacon heights, three-to-eight-beacon configurations, parameterization comparisons, and a second solver strategy.

Acceptance: known-map tests expose the coplanar reflection ambiguity and distinguish below-plane bounds from constant-height constraints. Joint-map comparisons fix the appropriate freedoms and report any remaining ambiguity. Best-fit-plane diagnostics distinguish tilt from nonplanarity. Solver comparisons use the same data and state any differences in bounds, parameterization, priors, or objective.

### 4. Multipath and robustness

Add controlled NLOS contamination with known synthetic labels; compare Gaussian least squares, robust losses, and explicit rejection or bias models.

Acceptance: report geometric accuracy plus rejection precision/recall against injected labels, retained measurement coverage, and resulting observability. Show rejected ranges in the scene. A lower residual after rejection alone does not establish improvement. Residual-based rejection must be evaluated for masking by a jointly distorted trajectory/map.

## Deferred choices

Choose the UI stack and numerical libraries during implementation based on interactive 3D support, reproducibility, solver capabilities, and ease of installation. Geomstats remains optional until a specific geometric operation warrants it. Real-data import, odometry/IMU factors, online estimation, multiple tags, and vehicle heading are later extensions. A single tag's range measurements alone do not independently measure vehicle heading.
