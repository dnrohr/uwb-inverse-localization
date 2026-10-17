# Synchronized planar numerical model

The numerical layer implements four synchronized, identified beacons and one planar tag position per epoch. Joint fitting estimates a shared positive beacon height; known-map fitting keeps all supplied surveyed coordinates fixed. Missing pings, asynchronous assumed times, free tag heights, motion priors, robust losses, survey uncertainty, and uncertainty intervals are outside this baseline.

## Measurement-only API and truth boundary

`fit_observations(observations, times_s, *, mode='joint', surveyed_beacons=None, starts=3, seed=19, initial_geometries=None, max_nfev=2000)` accepts observations and epoch times, without an experiment or truth argument. `surveyed_beacons` is mandatory in known-map mode and rejected in joint mode. `initial_geometries`, when supplied, explicitly provides one trajectory/map pair per start. Every attempted start is returned, including invalid initial geometry and optimizer nonconvergence. Input schema errors are raised before solving.

`solve_experiment(experiment, options)` is the synthetic evaluation wrapper. Its independent joint initialization reads only estimator inputs. In known-map mode the wrapper explicitly supplies the synthetic truth map as surveyed knowledge, disclosed in `diagnostics.surveyed_map_source`. In `truth_near` mode only, it explicitly perturbs truth by independent Gaussian 0.15 m parameter offsets with the configured seed, clipped at positive parameters. Truth is subsequently used to compute errors and truth Jacobian rank. A test alters truth while keeping joint observations fixed and verifies identical independent initial guesses and estimates.

Options are `mode` (`joint` or `known_map`), `initialization` (`independent` or `truth_near`), `starts` (1–20, default 3), `seed` (nonnegative integer, default 19), and `max_nfev` (positive integer, default 2000). Unsupported options are rejected. The reference generator supports 8–100 epochs; the fitter requires at least four and all four pings per epoch.

## Model, gauge, residuals, and optimization

Tag positions are `(x_i,y_i,0)`. The joint map is `b0=(0,0,h)`, `b1=(d,0,h)`, `b2=(a,b,h)`, `b3=(c,e,h)`. The parameter vector contains all trajectory xy values followed by `[d,a,b,c,e,h]`, giving `2N+6` unknowns for `4N` ranges. Known-map mode has `2N` parameters.

Predicted ranges are `R_ij = norm(p_i-b_j)`. Each residual is the unsquared signed range error `(R_ij-r_ij)/sigma_ij`; the minimized objective is one-half the sum of squared normalized residuals. Sigma is the strictly positive **assumed** uncertainty, separate from injected noise. Residuals in metres use the convention prediction minus observation. Arrays retain the input observation order and match records by epoch and beacon ID.

For `v=p_i-b_j`, range derivatives are `v_x/R`, `v_y/R` for the tag and their negatives for fitted beacon coordinates; the shared-height derivative is `h/R`. Divide derivatives by each observation's sigma. `jacobian` provides these analytic derivatives. Central finite differences check both modes at perturbed, nonzero-residual parameters with relative/absolute derivative tolerance `2e-7`.

SciPy `least_squares` uses bounded trust-region reflective (`trf`) optimization, linear loss, analytic Jacobian, `x_scale='jac'`, and `ftol=xtol=gtol=1e-12`. Joint bounds enforce `d,b,h >= 1e-6 m`; other parameters are unbounded. The positive numerical floor excludes collapsed baselines and zero height. The tag plane is fixed directly in the model.

The gauge removes planar translation and rotation. Positive d selects x direction, positive beacon 2 y selects a planar reflection branch, and positive h places beacons above the tag plane. These are conventions/physical branch restrictions, not extra measurements. Full local rank cannot establish global uniqueness.

Independent start zero uses a coarse four-beacon rectangle scaled by the median observed absolute range (at least 1 m), with height 0.3 times that scale. Additional starts perturb rectangle scale, height, beacon xy coordinates, and tag xy positions using the initialization seed. Tag seeds solve linear squared-range **differences against the guessed map**. In known-map mode this same seed uses the explicit surveyed map. This is a position seed, not an algebraic joint calibration comparison; the optimization objective always uses unsquared ranges. The independently guessed map is never the reference truth map.

Start selection uses the smallest finite objective among converged starts, or the smallest finite objective among nonconverged starts if none converged. Failed starts stay saved. Selection is an optimizer choice, not a guarantee of geometric recovery. Numerical run status (`success`, `not_converged`, or `failed`) remains distinct from range and geometry acceptance.

## Rank and alignment

The measurement-only analytic Jacobian is evaluated at truth and every fitted solution after gauge removal. Let `L=max(median(abs(observed_ranges_m)),1 m)`. Singular values are computed on `J*L`: the derivative of dimensionless normalized residuals with respect to dimensionless coordinates `theta/L`. All parameters are in metres and use the same documented L. Numerical rank counts singular values larger than `1e-8*s_max`. The absolute cutoff, L, full singular spectrum, parameter/measurement counts, rank, and full-column-rank flag are saved. The condition number is `s_max/s_min` for full column rank and null for rank loss. A disclosed heuristic warns above condition number 1000; this heuristic is not an uncertainty bound or a rank test.

Raw geometry errors compare matched epoch positions and matching beacon IDs. Joint aligned errors additionally fit one proper planar rigid transformation to corresponding beacon xy coordinates and apply it to both the map and trajectory. Scale stays exactly one. Reflections, z translations, and 3D tilt are prohibited. Alignment transformation and fitted geometry are saved. Known-map errors stay in the surveyed frame; aligned fields equal raw fields, with `alignment.applied=false`. Alignment cannot hide metric distortion or shared height error.

## Run schema for the viewer

`solve_experiment` returns a strict-JSON-compatible object:

| Path | Contents |
| --- | --- |
| `schema_version` | `"1.0"` |
| `experiment` | Complete original experiment, unchanged |
| `options` | Complete solver configuration, including defaults |
| `status`, `selected_start` | Selected outcome status and integer index, or null when no estimate exists |
| `starts[]` | Every attempted start, in index order |
| `starts[].initial`, `starts[].estimate` | `{trajectory: Nx3, beacons: 4x3}`; estimate null on exceptions |
| `starts[].index`, `.status`, `.success` | Start index, status text, optimizer convergence boolean |
| `starts[].solver` | Method/status/message, nfev/njev, runtime, initial/final objective, optimality, active bounds, evaluation limit, tolerances, scaling/loss/bounds |
| `starts[].solver.iterations` | null, with note: SciPy exposes evaluation counts, not iteration count |
| `starts[].diagnostics.residuals_m`, `.residuals_normalized` | One signed residual per original observation |
| `starts[].diagnostics.range_rmse_m`, `.max_abs_residual_m` | Range summary in original metres |
| `starts[].diagnostics.jacobian` | Rank/scaling/spectrum/conditioning structure described above |
| `starts[].diagnostics.evaluation.raw`, `.aligned` | `position_errors_m`, `position_rmse_m`, `position_max_error_m`, `beacon_errors_m`, `map_rmse_m`, signed `height_error_m` |
| `starts[].diagnostics.evaluation.alignment`, `.aligned_geometry` | Disclosed valid transformation and transformed trajectory/map |
| `starts[].diagnostics.geometric_recovery`, `.range_recovery`, `.recovery_classification` | Truth-based accuracy and range acceptance, separately from convergence |
| `diagnostics.truth_jacobian` | Truth rank/scaling/spectrum/conditioning |
| `diagnostics.start_recovery_outcomes` | Per-start optimizer/range/geometry outcomes, including failures |
| `diagnostics.failure_count` | Failed or nonconverged optimizer attempts |
| `diagnostics.geometric_recovery_count`, `.range_recovery_count` | Number meeting each declared numerical accuracy threshold |
| `diagnostics.distinct_solution_count` | Distinct finite fitted geometries from all starts |
| `diagnostics.distinct_low_residual_solution_count` | Distinct fitted geometries with maximum absolute range residual below `1e-7 m` |
| `diagnostics.warnings`, `.ambiguity` | Rank/conditioning warnings and general branch/global-uniqueness disclosure |
| `software_versions` | Python, NumPy, SciPy |

Geometric acceptance means all position errors and all beacon errors below `1e-5 m` in raw canonical coordinates. Range acceptance means maximum absolute range residual below `1e-7 m`. These are **exact-reference acceptance thresholds**, not expectations for noisy data. Clustering uses greedy representatives in start order and raw canonical geometry RMS over all trajectory/map xyz entries, with `1e-3 m` threshold. Counts are descriptive sampled-start variability, not exhaustive enumeration of continuous/discrete solutions. Exceptions have their initial guess and error message preserved, null estimate/objectives/evaluation counts, and runtime. Nonconverged starts retain their final geometry and all evaluable diagnostics.

## Validation and baseline evidence

Run `.venv/Scripts/python.exe -m unittest discover -s tests -p test_estimation.py -v`. Nine numerical tests cover independent and truth-near exact recovery in both modes, analytic derivatives, gauge/input enforcement, straight-line rank loss with tiny residuals, weak geometry conditioning, heteroscedastic normalized/metre residuals with Gaussian noise, truth independence, failed/nonconverged retention, and rigid-only alignment.

Default 32-epoch, noiseless, independent joint runs with three starts and initialization seed 19 gave:

| Reference scenario | Truth rank / 70 | Truth condition number | Selected maximum position error (m) | Maximum range residual (m) | Distinct low-residual geometries |
| --- | --- | --- | --- | --- | --- |
| informative | 70 | 41.44 | `2.60e-15` | `1.78e-15` | 1 |
| straight_line | 69 | null (rank loss) | 0.1134 | `1.78e-15` | 3 |
| narrow_coverage | 70 | 1056.57 | `1.91e-14` | `1.78e-15` | 1 |
| nearly_collinear | 70 | 10829.73 | `2.80e-13` | `1.78e-15` | 1 |

Values were measured with NumPy 2.5.4 and SciPy 1.18.1; floating-point details may vary across platforms. The straight-line example demonstrates why optimizer convergence and almost-zero residuals cannot establish recovered geometry. Narrow and nearly-collinear exact cases can recover while still being sensitive to noise. Tests assert declared tolerances, not those particular last-bit errors. No guarantee is made for arbitrary initializations, noisy geometric recovery, or uniqueness across unsearched solution branches.


## Controlled comparisons

See the [user guide](../USER_GUIDE.md#run-parameter-studies) for paired studies, model variants and all-attempt accounting. Comparison alignment preserves scale. Optimizer convergence, geometric accuracy and measurement-only observability remain separate diagnostics.
