# Project roadmap

Source: [project requirements](PROJECT_REQUIREMENTS.md), with mathematical background in [the handoff](UWB_PROJECT_HANDOFF.md).

M0, M1 and M2 are complete, with acceptance evidence linked below. M3 and later items remain planned and unchecked. Milestones are ordered by dependency, without speculative completion dates. Completing a milestone means delivering its working interface, numerical evidence, and documented limitations.

## M0 — Establish the experiment foundation

**Outcome:** a reproducible experiment can be generated, saved, and inspected independently of the UI.

- [x] **M0.1 — Select the implementation stack.** Record the numerical solver, interactive 3D library, application structure, installation instructions, and rationale. Keep Geomstats optional.
- [x] **M0.2 — Define versioned experiment and run formats.** Include configuration, units, coordinate convention, actual/assumed timestamps, observations, uncertainties, seeds, initialization, results, diagnostics, software versions, and failure status. Separate truth from estimator inputs.
- [x] **M0.3 — Implement the synthetic generator.** Start with one tag, four equal-height beacons, synchronized pings, a planar spatially spread path, and exact ranges. Add additive Gaussian noise with independent reproducible seeds and global/per-beacon standard deviations.
- [x] **M0.4 — Add reference scenarios.** Provide informative motion, straight-line motion, narrow spatial coverage, and nearly collinear beacon layouts. Document coordinates, timing, and intended comparisons.
- [x] **M0.5 — Add save/load and numerical checks.** Check range generation against independently calculated distances, fixed-seed repeatability, and lossless run-data round trips. Document tolerances.

**Exit check:** passed. A fresh virtual environment generated and reloaded reference data; fixed seeds reproduce observations and JSON round trips are lossless. Exact/noisy observations are distinct. The measurement-only joint API receives no truth. Evidence: [format and scenarios](docs/FORMAT.md), `tests/test_experiments.py`, [acceptance record](docs/ACCEPTANCE.md), and `evidence/reference_runs/`.

## M1 — Deliver the four-beacon estimator and rotatable 3D viewer

**Depends on:** M0. **Outcome:** the first useful end-to-end application.

- [x] **M1.1 — Implement known-map planar localization.** Use normalized unsquared range residuals, fixed tag plane, and explicit solver diagnostics.
- [x] **M1.2 — Implement joint planar trajectory/map fitting.** Estimate horizontal beacon coordinates and shared relative height, fix the planar frame freedoms, and encode positivity/bounds appropriately.
- [x] **M1.3 — Add initialization and multistart.** Support visibly labeled truth-near diagnostic initialization, a truth-independent strategy, controlled perturbations, and saved per-start outcomes.
- [x] **M1.4 — Implement observability and error reporting.** Compute measurement Jacobian rank and scaled singular values at truth and the solution. Report trajectory/map error, residuals, objective, termination reason, iterations, and runtime. Keep convergence and geometric recovery distinct.
- [x] **M1.5 — Build the interactive scene.** Rotate/pan/zoom; show truth, estimates, initial guesses, beacon IDs, metre axes, and equal aspect ratio. Add reset/top/side/perspective views, layer toggles, and raw versus validly aligned coordinates without scale fitting.
- [x] **M1.6 — Connect controls and run execution.** Select reference scenario, map mode, noise, seed, and initialization. Use an explicit Run action with visible status; preserve camera state and keep scene interaction responsive.
- [x] **M1.7 — Show numerical evidence beside the scene.** Include matched-time position errors, per-beacon map errors, signed/normalized residuals, residual distributions, and singular spectra. Make failed runs reviewable and reopen saved results without solving again.

**Exit check:** passed. The informative noiseless scenario recovers geometry and ranges within declared tolerances from independent initialization; truth-near runs provide separate diagnostic validation. The straight-line scenario exposes rank loss and alternate exact-range geometries. Both reconstructions rotate in the working viewer and Gaussian-noise errors are visible. Known-map results remain in the surveyed frame; optional joint alignment is proper planar rigid, with no scale or reflection fitting. Evidence is recorded in the first-release entry below.

**First release:** M0 + M1 completed October 13, 2026. Evidence: [acceptance record](docs/ACCEPTANCE.md), [numerical conventions](docs/NUMERICS.md), [independent mathematical review](docs/MATH_REVIEW.md), `evidence/acceptance_summary.json`, ten saved reference runs, and `evidence/screenshots/`. All 28 tests pass. Independent exact geometry recovery meets 1e-5 m maximum tag/beacon error and 1e-7 m maximum range residual; straight-line rank loss and alternate low-residual geometries are demonstrated. Iteration counts unavailable from SciPy are explicitly disclosed; evaluation counts are reported. Scope/limits: four synchronized equal-height beacons, planar tags, 8–100 samples, 1–12 application starts, finite multistart exploration rather than global uniqueness. No timing, free-height or multipath extensions are implemented.

## M2 — Add controlled sweeps and saved-run comparison

**Depends on:** M1. **Outcome:** experiments can be compared systematically rather than by individual screenshots.

- [x] **M2.1 — Expand path controls.** Add straight line, circle/arc, rectangle, figure-eight, and waypoint paths; expose scale, location, duration, and sample density with constant-speed motion.
- [x] **M2.2 — Compare two saved runs.** Share camera, spatial scale, time reference, and alignment convention; distinguish fitted samples from interpolation and color geometry by a disclosed error/residual quantity.
- [x] **M2.3 — Implement paired single-variable sweeps.** Begin with noise level, path coverage, sample density, initial-guess error, and assumed uncertainty. Pair estimator comparisons using identical observations and compatible initial guesses.
- [x] **M2.4 — Aggregate repeated runs.** Report seed/start variability, failure rate, geometric error distributions, and distinct low-residual solutions. Define thresholds used to group solutions and classify failures.
- [x] **M2.5 — Export results.** Export machine-readable configurations/data, comparison tables, charts, and scene images or reports. Record supported configuration sizes and benchmark baseline solve/UI performance.

**Exit check:** passed October 13, 2026. Six path fixtures, five controlled sweeps (48 runs / 96 starts), saved comparisons, all-start inspection, JSON/CSV/PNG exports, reopen without solving, and Windows checkpoint recovery were numerically and visually verified. All 61 tests pass, including the original 28. Evidence: [M2 acceptance record](docs/M2_ACCEPTANCE.md), [controls, pairing and thresholds](docs/M2.md), and `evidence/m2/`. Solver/UI benchmarks and configuration limits are recorded there. M0–M1 evidence and prior user observations remain unchanged. Convergence, exact-reference acceptance, noisy geometric accuracy and rank remain separate; no global uniqueness claim is made.

## M3 — Explore moving tags and non-simultaneous pings

**Depends on:** M2. **Outcome:** quantify when a simultaneous-ping approximation distorts the solution.

- [ ] **M3.1 — Add time-dependent motion.** Support variable speed, acceleration, stops, and direction changes; show speed versus time.
- [ ] **M3.2 — Generate sequential acquisition.** Control beacon order, cycle rate, within-cycle spacing, and acquisition jitter. Generate ranges at each actual tag position and retain actual/assumed times separately.
- [ ] **M3.3 — Implement a timestamp-aware trajectory model.** Choose and document knots/interpolation and optional motion priors; expose knot spacing and prior strength. Evaluate each residual at its measurement time and diagnose measurement information separately from priors.
- [ ] **M3.4 — Implement the grouped-time approximation.** State the grouping rule/reference time and fit the same observations as the timestamp-aware estimator.
- [ ] **M3.5 — Animate and scrub individual pings.** Show actual ping positions, receiving beacons, range rays, and assumed common cycle position. Preserve camera and comparison settings during playback.
- [ ] **M3.6 — Add timing sweeps and imperfect data.** Sweep speed, ping spacing, and knot spacing. Then add timestamp offsets/jitter, missing observations, and unequal beacon rates. Distinguish timestamp error from acquisition spacing and delivery latency.

**Exit check:** zero ping spacing reproduces the synchronized baseline; a stationary tag shows no acquisition-spacing geometry effect. Correctly timestamped delivery latency alone leaves batch results unchanged. Moving-tag comparisons report timing approximation error and any interpolation/prior effects, rather than attributing all differences to timing.

## M4 — Investigate height constraints and beacon geometry

**Depends on:** M2; use M3 for asynchronous comparisons. **Outcome:** expose height ambiguity, nonplanarity, and geometry sensitivity.

- [ ] **M4.1 — Expand beacon controls.** Support three through eight beacons, editable coordinates, horizontal baselines, height diversity, nearly collinear/coplanar layouts, and paths inside/outside beacon coverage.
- [ ] **M4.2 — Compare tag height models with known maps first.** Add fixed/shared plane, soft height constraint with stated uncertainty, and free trajectory heights. Treat below-beacon bounds as a separate option.
- [ ] **M4.3 — Extend joint estimation.** Support shared and independent beacon heights where identifiable; define the appropriate 3D frame convention and report remaining reflection/continuous ambiguities. Flag unsupported combinations with explanations.
- [ ] **M4.4 — Add height diagnostics.** Show z versus time, height error, best-fit-plane departure, relevant planes, and residual/geometry changes between models.
- [ ] **M4.5 — Add model-mismatch scenarios.** Generate small vertical excursions and fully 3D truth paths, and fit them using planar and free-height models.
- [ ] **M4.6 — Sweep geometry and constraints.** Compare count, vertical separation, coverage, height-prior strength, and shared versus independent beacon heights using repeated runs and scaled rank diagnostics.

**Exit check:** known-map coplanar cases expose reflected solutions; below-plane bounds select a branch without being represented as a planarity constraint. Diagnostics distinguish a tilted plane from a warped trajectory. Joint fits remove valid coordinate freedoms and disclose any remaining unidentifiability.

## M5 — Compare solvers and initialization methods

**Depends on:** M4. **Outcome:** distinguish model/geometry failures from optimizer behavior.

- [ ] **M5.1 — Add a second solver strategy.** Compare LM and a bounded trust-region method where feasible. Record objective, derivatives, tolerances, bounds, scaling, and any positivity transformation; acknowledge differences imposed by solver capabilities.
- [ ] **M5.2 — Compare shared-height parameterizations.** Evaluate h and q=h² using stated units, scaling, and physically valid starts, including behavior near zero height.
- [ ] **M5.3 — Validate an algebraic initializer.** Numerically check exact-data recovery and physical consistency before noisy comparisons; report invalid algebraic fits explicitly.
- [ ] **M5.4 — Run paired solver/initializer benchmarks.** Reuse data and compatible starts; report accuracy, convergence basin, failure rate, runtime, and alternative solutions across representative observable and weak geometries.
- [ ] **M5.5 — Evaluate a second implementation if useful.** Consider Ceres on the same saved experiments after the baseline is stable. Record whether observed differences follow from configuration or implementation. Assess Geomstats only for a named operation with measurable benefit.

**Exit check:** benchmark results separate solver effects from changed objectives, priors, bounds, and parameterizations. Neither lower cost nor faster runtime alone is reported as better geometric recovery.

## M6 — Add multipath simulation and robust estimation

**Depends on:** M5. **Outcome:** evaluate rejection and robustness against controlled contamination.

- [ ] **M6.1 — Generate labeled NLOS/outliers.** Add positive range bias, isolated outliers, and bursts with configurable prevalence, magnitude, duration, and affected beacons. Keep synthetic labels out of estimator inputs.
- [ ] **M6.2 — Add robust estimators.** Compare Gaussian least squares, robust losses, and an explicit rejection or bias model; expose thresholds and assumptions.
- [ ] **M6.3 — Visualize decisions.** Show rejected/downweighted ranges, residuals, affected trajectory segments, retained coverage, and loss of observability.
- [ ] **M6.4 — Evaluate rejection quality.** Report precision/recall against injected labels together with trajectory/map error and false rejections on clean data. Test masking by jointly distorted trajectories/maps.
- [ ] **M6.5 — Expand error models individually.** Add per-beacon offsets, correlated noise, quantization, and dropout experiments before combining contamination sources.

**Exit check:** robustness comparisons disclose geometric gains and losses, rejection quality, and retained information. A reduced residual after deleting measurements is insufficient evidence of improvement.

## M7 — Strengthen calibration knowledge and uncertainty analysis

**Depends on:** M4–M6. **Outcome:** explore what additional information makes estimation reliable.

- [ ] **M7.1 — Add partial survey knowledge.** Support selected fixed beacon coordinates and uncertain survey priors with documented units and uncertainty.
- [ ] **M7.2 — Add conditional uncertainty summaries.** Only compute/report local uncertainty where rank and the assumed error model support it; distinguish local intervals from global alternatives and prior-supplied information.
- [ ] **M7.3 — Package investigation results.** Save reproducible demonstrations of geometry, timing, height, initialization, and multipath effects; document measured performance limits and unresolved questions.

**Exit check:** conclusions link to saved experiments; uncertainty assumptions and information sources are visible. No unsupported model is presented as uniquely recovered.

## Optional follow-on work

These are deferred research directions, not prerequisites for the milestones above:

- Real UWB log import after timestamp, units, beacon identity, and calibration conventions are established.
- Odometry/IMU factors and additional motion models.
- Online estimation, where delivery latency and out-of-order observations matter.
- Multiple tags, rigid vehicle geometry, and heading estimation.
- More physical multipath/channel models after simple contamination benchmarks are understood.

## Completion and maintenance rules

- Check an item only after its implementation and relevant acceptance evidence exist; record the evidence location and limitations when closing its milestone.
- Maintain meaningful numerical checks for residuals/Jacobians, gauge handling, timing, and reproducibility; perform visual checks for scene scale, alignment, controls, and playback.
- Preserve observations and truth when comparing estimators. Record configuration changes explicitly, and keep failed runs in aggregates.
- Update this roadmap when experiments change priorities or expose a prerequisite; retain the requirements document as the product scope reference.

## Next task

M0–M2 is delivered. The next milestone is **M3** (moving tags and non-simultaneous pings), subject to a separate request.

