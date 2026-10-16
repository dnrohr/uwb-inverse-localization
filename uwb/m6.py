"""Saved contamination experiments and range-only robust estimation.

Synthetic references never enter ``fit_observations``. Robust objectives are
represented by differentiable signed square-root residuals, allowing TRF and
strict-interior LM to optimize the same loss while keeping priors quadratic.
"""
from __future__ import annotations

import copy
import json
import time

import numpy as np
from scipy.optimize import least_squares

from . import m3, m4, m5

SCHEMA_VERSION = "6.0"
MAX_KNOTS = m5.MAX_KNOTS
EXTRA_KEYS = {"loss", "loss_scale_sigma", "rejection_threshold_sigma", "weight_decision_threshold"}
LOSSES = ("gaussian", "huber", "soft_l1", "cauchy", "hard_rejection")


@m3._format_errors
def normalize_config(config=None):
    supplied = copy.deepcopy(dict(config or {}))
    raw = dict(supplied.pop("contamination", {}))
    cfg = m5.normalize_config(supplied)
    count = cfg["beacon_layout"]["count"]
    allowed = {"nlos", "offsets_m", "correlated_noise_std_m", "correlation", "quantization_m", "dropout_probability", "seed"}
    if set(raw) - allowed:
        raise ValueError("Unsupported contamination keys")
    nlos = dict(raw.get("nlos", {}))
    if set(nlos) - {"prevalence", "magnitude_m", "burst_duration_cycles", "affected_beacons"}:
        raise ValueError("Unsupported nlos keys")
    duration = nlos.get("burst_duration_cycles", 1)
    if isinstance(duration, bool) or not isinstance(duration, int) or not 1 <= duration <= 100:
        raise ValueError("burst_duration_cycles requires an integer from 1 through 100")
    affected = nlos.get("affected_beacons", list(range(count)))
    if not isinstance(affected, (list, tuple)) or any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < count for v in affected) or len(set(affected)) != len(affected):
        raise ValueError("affected_beacons requires distinct valid beacon IDs")
    offsets = raw.get("offsets_m", [0.] * count)
    if isinstance(offsets, (int, float)) and not isinstance(offsets, bool):
        offsets = [offsets] * count
    if not isinstance(offsets, (list, tuple)) or len(offsets) != count:
        raise ValueError("offsets_m must be scalar or have beacon-count entries")
    seed = raw.get("seed", (cfg["seed"] + 606) % 2 ** 32)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2 ** 32:
        raise ValueError("contamination seed must be an unsigned 32-bit integer")
    cfg["contamination"] = {
        "nlos": {"prevalence": m3._number(nlos.get("prevalence", 0.), "prevalence", 0., 1.),
                 "magnitude_m": m3._number(nlos.get("magnitude_m", 1.), "magnitude_m", 1e-9, 100.),
                 "burst_duration_cycles": duration, "affected_beacons": list(affected)},
        "offsets_m": [m3._number(v, "offsets_m", -100., 100.) for v in offsets],
        "correlated_noise_std_m": m3._number(raw.get("correlated_noise_std_m", 0.), "correlated_noise_std_m", 0., 100.),
        "correlation": m3._number(raw.get("correlation", 0.), "correlation", -.999, .999),
        "quantization_m": m3._number(raw.get("quantization_m", 0.), "quantization_m", 0., 100.),
        "dropout_probability": m3._number(raw.get("dropout_probability", 0.), "dropout_probability", 0., 1.), "seed": seed}
    return cfg


def _base_config(config):
    return {key: copy.deepcopy(value) for key, value in config.items() if key != "contamination"}


def _contaminate(source, cfg):
    exp = copy.deepcopy(source)
    exp.update(schema_version=SCHEMA_VERSION, config=copy.deepcopy(cfg))
    c = cfg["contamination"]; nlos = c["nlos"]
    observations = source["estimator_input"]["observations"]
    count = cfg["beacon_layout"]["count"]; epochs = len(source["estimator_input"]["times_s"])
    streams = [np.random.default_rng(s) for s in np.random.SeedSequence(c["seed"]).spawn(3)]
    onsets = streams[0].random((epochs, count)) < nlos["prevalence"]
    labels = np.zeros_like(onsets)
    for beacon in nlos["affected_beacons"]:
        for epoch in np.flatnonzero(onsets[:, beacon]):
            labels[epoch:min(epochs, epoch + nlos["burst_duration_cycles"]), beacon] = True
    # Independent stationary AR(1) process per beacon on the complete cycle
    # grid, including cycles missing from the acquisition source.
    innovation = streams[1].normal(size=(epochs, count))
    correlated = np.empty_like(innovation)
    correlated[0] = c["correlated_noise_std_m"] * innovation[0]
    for epoch in range(1, epochs):
        correlated[epoch] = c["correlation"] * correlated[epoch - 1] + c["correlated_noise_std_m"] * np.sqrt(1. - c["correlation"] ** 2) * innovation[epoch]
    dropped = streams[2].random(len(observations)) < c["dropout_probability"]
    kept, records, indices = [], [], []
    positions = np.asarray(source["truth"]["ping_positions"]).reshape((-1, 3))
    beacons = np.asarray(source["truth"]["beacons"])
    for index, observation in enumerate(observations):
        beacon, epoch = observation["beacon_id"], observation["epoch"]
        clean = float(np.linalg.norm(positions[index] - beacons[beacon]))
        bias = nlos["magnitude_m"] if labels[epoch, beacon] else 0.
        offset = c["offsets_m"][beacon]; ar = float(correlated[epoch, beacon])
        value = observation["range_m"] + offset + ar + bias
        quantized = float(np.rint(value / c["quantization_m"]) * c["quantization_m"]) if c["quantization_m"] else value
        record = {"source_index": index, "retained_index": None if dropped[index] else len(kept),
                  "epoch": epoch, "beacon_id": beacon, "clean_range_m": clean,
                  "white_noise_m": observation["range_m"] - clean, "offset_m": offset, "correlated_noise_m": ar,
                  "nlos_bias_m": bias, "quantization_error_m": quantized - value,
                  "range_m": quantized, "nlos": bool(labels[epoch, beacon]), "dropped": bool(dropped[index])}
        records.append(record)
        if not dropped[index]:
            kept.append({**observation, "range_m": quantized}); indices.append(index)
    exp["estimator_input"]["observations"] = kept
    for field in ("ping_times_s", "ping_positions", "grouped_positions"):
        exp["truth"][field] = [copy.deepcopy(source["truth"][field][i]) for i in indices]
    exp["contamination_reference"] = {
        "source_experiment": copy.deepcopy(source), "records": records,
        "generation": {"order": "M5 acquisition/white noise, beacon offset, stationary cycle-grid AR(1), positive NLOS, nearest-even quantization, independent dropout",
                       "nlos_prevalence_definition": "Independent Bernoulli burst-onset probability per eligible beacon/cycle; forward union of duration-cycle windows. Realized contaminated fraction can exceed onset probability.",
                       "noise_definition": "AR(1) per beacon, stationary SD in metres, independent beacon streams; correlation is between adjacent cycle indices, not elapsed seconds. Base M5 white noise remains additive.",
                       "dropout_definition": "Independent Bernoulli selection after M5 acquisition selection; source pings and dropped records retained; missingness is not an estimator rejection.",
                       "uncertainty_definition": "sigma_m is the original assumed M5 range SD; not silently inflated for contamination or quantization",
                       "label_definition": "nlos marks injected positive NLOS bias only; offsets, white/AR noise and quantization are separate factors",
                       "randomness": "NumPy default_rng, SeedSequence(seed).spawn(3): onset, AR innovations, dropout"}}
    return exp


def generate_experiment(config=None):
    cfg = normalize_config(config)
    exp = _contaminate(m5.generate_experiment(_base_config(cfg)), cfg)
    validate_experiment(exp)
    return exp


def _legacy_experiment(exp):
    result = copy.deepcopy(exp)
    result.update(schema_version=m4.SCHEMA_VERSION, config=_base_config(exp["config"]))
    result.pop("contamination_reference", None)
    return result


@m3._format_errors
def validate_experiment(exp):
    if exp.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("M6 experiment requires schema6.0")
    json.dumps(exp, allow_nan=False)
    cfg = normalize_config(exp["config"])
    if cfg != exp["config"]:
        raise ValueError("M6 configuration must contain normalized defaults")
    m4.validate_experiment(_legacy_experiment(exp))
    source = exp["contamination_reference"]["source_experiment"]
    m5.validate_experiment(source)
    if source["config"] != _base_config(cfg):
        raise ValueError("Saved source configuration differs from M6 base configuration")
    expected = _contaminate(source, cfg)
    if not m5._same_diagnostics(exp, expected):
        raise ValueError("Saved observations, labels, contamination components or selection disagree with deterministic source replay")
    return exp


def base_options(options):
    return m5.validate_options({k: v for k, v in options.items() if k not in EXTRA_KEYS})


@m3._format_errors
def validate_options(options=None):
    supplied = dict(options or {})
    loss = supplied.pop("loss", "gaussian")
    scale = m3._number(supplied.pop("loss_scale_sigma", 2.), "loss_scale_sigma", 1e-6, 1000.)
    threshold = m3._number(supplied.pop("rejection_threshold_sigma", 3.), "rejection_threshold_sigma", 1e-6, 1000.)
    decision = m3._number(supplied.pop("weight_decision_threshold", .5), "weight_decision_threshold", 0., 1.)
    if loss not in LOSSES:
        raise ValueError("loss must be one of " + ", ".join(LOSSES))
    return {**m5.validate_options(supplied), "loss": loss, "loss_scale_sigma": scale,
            "rejection_threshold_sigma": threshold, "weight_decision_threshold": decision}


def loss_statistics(residual_sigma, loss, scale):
    """Return influence weights rho'(z) and signed exact scalar curvature.

    Objective is .5*scale²*rho((residual/scale)²). The curvature here
    differentiates with respect to the normalized scalar residual; geometry
    second derivatives are excluded.
    """
    r = np.asarray(residual_sigma, dtype=float); z = (r / scale) ** 2
    if loss in ("gaussian", "hard_rejection"):
        return np.ones_like(r), np.ones_like(r)
    if loss == "huber":
        weight = np.ones_like(r); outside = z > 1.
        weight[outside] = 1. / np.sqrt(z[outside])
        return weight, (~outside).astype(float)
    if loss == "soft_l1":
        return 1. / np.sqrt(1. + z), (1. + z) ** -1.5
    if loss == "cauchy":
        return 1. / (1. + z), (1. - z) / (1. + z) ** 2
    raise ValueError("Unsupported range loss")


def range_transform(residual_sigma, loss, scale):
    r = np.asarray(residual_sigma, dtype=float)
    z = (r / scale) ** 2
    if loss in ("gaussian", "hard_rejection"):
        return r.copy(), np.ones_like(r)
    if loss == "huber":
        rho = np.where(z <= 1., z, 2. * np.sqrt(z) - 1.)
    elif loss == "soft_l1":
        # Rationalized form avoids catastrophic cancellation near zero.
        rho = 2. * z / (np.sqrt(1. + z) + 1.)
    elif loss == "cauchy":
        rho = np.log1p(z)
    else:
        raise ValueError("Unsupported range loss")
    transformed = np.sign(r) * scale * np.sqrt(rho)
    weight, _ = loss_statistics(r, loss, scale)
    derivative = np.ones_like(r)
    nonzero = np.abs(transformed) > np.finfo(float).tiny
    derivative[nonzero] = weight[nonzero] * np.abs(r[nonzero]) / np.abs(transformed[nonzero])
    return transformed, derivative


def _objective_vectors(x, problem, opts, mask=None):
    mr = m5.measurement_residuals(x, problem)
    values, chain = range_transform(mr, opts["loss"], opts["loss_scale_sigma"])
    if mask is not None:
        values *= mask; chain *= mask
    motion, height = m5.prior_components(x, problem)
    derivative = m5.jacobian(x, problem).copy()
    derivative[:len(mr)] *= chain[:, None]
    return np.r_[values, motion, height], derivative


def build_problem(observations, times_s, *, beacon_count=None, display_times_s=None, surveyed_beacons=None, **options):
    opts = validate_options(options)
    problem = m5.build_problem(observations, times_s, beacon_count=beacon_count, display_times_s=display_times_s,
                               surveyed_beacons=surveyed_beacons, **base_options(opts))
    problem.robust_options = opts
    problem.original_cycle_count = len(times_s)
    return problem


def residuals(parameters, problem, mask=None):
    return _objective_vectors(parameters, problem, problem.robust_options, mask)[0]


def jacobian(parameters, problem, mask=None):
    return _objective_vectors(parameters, problem, problem.robust_options, mask)[1]


measurement_residuals = m5.measurement_residuals
measurement_jacobian = m5.measurement_jacobian
prior_components = m5.prior_components


def _optimize(problem, opts, x0, mask=None):
    def fun(x):
        return _objective_vectors(x, problem, opts, mask)[0]
    def derivative(x):
        return _objective_vectors(x, problem, opts, mask)[1]
    keywords = {"x_scale": "jac", "ftol": 1e-12, "xtol": 1e-12, "gtol": 1e-12, "max_nfev": opts["max_nfev"]}
    if opts["solver"] == "lm":
        retained = len(problem.ranges_m) if mask is None else int(np.count_nonzero(mask))
        prior_count = len(m5.residuals(x0, problem)) - len(problem.ranges_m)
        if retained + prior_count < problem.parameter_count:
            raise ValueError("LM requires retained range plus prior residual count >= parameter count; rejected zero rows do not count")
        transform = m5.BoundTransform(problem.lower, problem.upper)
        def lm_fun(u):
            return fun(transform.decode(u)[0])
        def lm_jac(u):
            x, chain = transform.decode(u)
            return derivative(x) * chain
        result = least_squares(lm_fun, transform.encode(x0), jac=lm_jac, method="lm", **keywords)
        solution = transform.decode(result.x)[0]
    else:
        result = least_squares(fun, x0, jac=derivative, bounds=(problem.lower, problem.upper), method="trf", **keywords)
        solution = result.x
    return result, solution


def _information(matrix, problem, *, prior_count=0, description):
    scale = max(float(np.median(np.abs(problem.ranges_m))) if len(problem.ranges_m) else 1., 1.)
    singular = np.linalg.svd(matrix * scale, compute_uv=False)
    cutoff = float(singular[0] * 1e-8) if len(singular) else 0.
    rank = int(np.sum(singular > cutoff)); full = rank == problem.parameter_count
    return {"rank": rank, "parameter_count": problem.parameter_count,
            "measurement_count": len(problem.ranges_m), "prior_residual_count": prior_count,
            "full_column_rank": full, "condition_number": float(singular[0] / singular[-1]) if full else None,
            "singular_values": singular.tolist(), "relative_tolerance": 1e-8,
            "absolute_tolerance": cutoff, "parameter_scale_m": scale,
            "scaling": "Physical metre coordinates scaled by median original absolute range (minimum 1 m); residuals divided by original sigma",
            "interpretation": description}


def _fit_diagnostics(x, problem, opts, mask=None, pilot=None):
    mr = m5.measurement_residuals(x, problem); motion, height = m5.prior_components(x, problem)
    values, _ = range_transform(mr, opts["loss"], opts["loss_scale_sigma"])
    weights, curvature = loss_statistics(mr, opts["loss"], opts["loss_scale_sigma"])
    if mask is not None:
        weights = mask.astype(float); curvature = weights.copy(); values *= weights
    flagged = (weights == 0.) if opts["loss"] == "hard_rejection" else weights < opts["weight_decision_threshold"]
    # Independent of h/q: all information matrices below differentiate physical
    # metre geometry in the original M4 gauge, with a common original-data scale.
    physical_x = problem.physical_parameters(x)
    original = m4.measurement_jacobian(physical_x, problem.physical)
    full = m4.jacobian(physical_x, problem.physical)
    priors = full[len(mr):]
    weighted = original * np.sqrt(weights)[:, None]
    information = {
        "original_measurement": _information(original, problem, description="Original saved ranges, measurement-only physical Jacobian at this estimate; local rank is not uniqueness"),
        "retained_measurement": _information(weighted, problem, description="sqrt(influence weight) times original range Jacobian; frozen weights, measurement-only effective information; not exact robust curvature"),
        "prior_augmented": _information(np.vstack((weighted, priors)), problem, prior_count=len(priors), description="Weighted measurement Jacobian plus quadratic motion/height prior rows; priors are model assumptions, not measurements"),
        "positive_part_robust_curvature": _information(original * np.sqrt(np.maximum(curvature, 0.))[:, None], problem, description="Positive part of signed rho'+2*z*rho'' scalar curvature; conditioning surrogate only; excludes geometry second derivatives and priors"),
        "signed_scalar_curvature": curvature.tolist(), "coordinate_system": "M4 physical metre coordinates, selected canonical gauge; h/q native sensitivity is separate",
        "definition": "J is derivative of (predicted range - measured range)/sigma; effective information J^T W J. Original and weighted matrices share physical column scaling and SVD tolerance."}
    observations = []
    for i in range(len(mr)):
        observations.append({"observation_index": i, "epoch": int(problem.epochs[i]), "beacon_id": int(problem.beacon_ids[i]),
                             "assumed_time_s": float(problem.assumed_times_s[i]), "residual_m": float(mr[i] * problem.sigma_m[i]),
                             "residual_sigma": float(mr[i]), "weight": float(weights[i]), "flagged": bool(flagged[i]),
                             "rejected": bool(weights[i] == 0.), "pilot_residual_sigma": float(pilot[i]) if pilot is not None else None})
    def coverage_rows(ids, n):
        return [{"id": i, "original_count": int(np.sum(ids == i)), "retained_count": int(np.sum((ids == i) & (weights > 0.))),
                 "flagged_count": int(np.sum((ids == i) & flagged)), "effective_weight_sum": float(np.sum(weights[ids == i]))} for i in range(n)]
    coverage = {"original_count": len(mr), "retained_count": int(np.sum(weights > 0.)), "flagged_count": int(np.sum(flagged)),
                "effective_weight_sum": float(np.sum(weights)), "by_beacon": coverage_rows(problem.beacon_ids, problem.beacon_count),
                "by_epoch": coverage_rows(problem.epochs, problem.original_cycle_count),
                "definition": "Retained count means strictly positive weight. Robust flags use weight < decision threshold; hard rejection flags mean zero frozen pilot weight. Missing pings are outside estimator decisions."}
    objectives = {"measurement_objective": float(.5 * values @ values), "gaussian_all_measurement_objective": float(.5 * mr @ mr),
                  "motion_prior_objective": float(.5 * motion @ motion), "height_prior_objective": float(.5 * height @ height),
                  "prior_objective": float(.5 * (motion @ motion + height @ height)), "contamination_model_objective": 0.}
    return {"residuals_m": (mr * problem.sigma_m).tolist(), "residuals_normalized": mr.tolist(),
            "motion_prior_residuals_normalized": motion.tolist(), "height_prior_residuals_normalized": height.tolist(),
            "range_rmse_m": float(np.sqrt(np.mean((mr * problem.sigma_m) ** 2))),
            "max_abs_residual_m": float(np.max(np.abs(mr * problem.sigma_m))),
            "jacobian": m4.jacobian_diagnostics(physical_x, problem.physical),
            "augmented_jacobian": m4.jacobian_diagnostics(physical_x, problem.physical, augmented=True),
            "native_jacobian": m5.jacobian_diagnostics(x, problem),
            "native_augmented_jacobian": m5.jacobian_diagnostics(x, problem, augmented=True),
            "observation_decisions": observations, "information": information, "coverage": coverage, **objectives}


def _metadata(problem, opts):
    return {"method": f"scipy.optimize.least_squares/{opts['solver']}", "height_parameterization": opts["height_parameterization"],
            "parameterization": problem.disclosure(), "bounds_transform_revision": 2,
            "bounds_handling": "M5 native TRF bounds" if opts["solver"] == "trf" else "M5 strict-interior exponential bounds; no clipping",
            "loss": opts["loss"], "loss_scale_sigma": opts["loss_scale_sigma"], "rejection_threshold_sigma": opts["rejection_threshold_sigma"],
            "weight_decision_threshold": opts["weight_decision_threshold"],
            "loss_units": "Dimensionless normalized range residual: (predicted-measured)/original assumed sigma_m",
            "objective": ".5*c²*sum rho((range_residual/sigma/c)²) plus quadratic motion/height priors; hard rejection substitutes a frozen binary pilot mask",
            "loss_implementation": "Analytic signed-sqrt rho residual transform; exact objective, transformed-residual Gauss-Newton approximation. Priors never robustified; SciPy loss=linear",
            "rejection_rule": "Gaussian pilot from saved physical start; retain abs(pilot residual/sigma)<=threshold; one second Gaussian fit initialized at pilot geometry with frozen mask; no label access",
            "rejection_support": "All rows remain in saved diagnostics; rejected range residual rows have zero optimizer weight. At least one retained range required; LM requires retained+prior count >= parameter count.",
            "max_nfev": opts["max_nfev"], "ftol": 1e-12, "xtol": 1e-12, "gtol": 1e-12, "x_scale": "jac",
            "derivatives": "Analytic M5 h/q Jacobian times exact range-loss and optional bound coordinate chain rules"}


def fit_observations(observations, times_s, *, beacon_count=None, display_times_s=None, surveyed_beacons=None, initial_geometries=None, **options):
    """Fit assumed times/ranges/sigmas only; no labels, clean ranges or truth."""
    opts = validate_options(options)
    # Explicitly project out actual/delivery annotations before constructing the
    # independent problem. The estimator has no synthetic observation labels.
    inputs = [{key: row[key] for key in ("epoch", "beacon_id", "assumed_time_s", "range_m", "sigma_m")} for row in observations]
    problem = build_problem(inputs, times_s, beacon_count=beacon_count, display_times_s=display_times_s,
                             surveyed_beacons=surveyed_beacons, **opts)
    if initial_geometries is not None and len(initial_geometries) != opts["starts"]:
        raise ValueError("Supply every requested physical initial geometry")
    if initial_geometries is None and opts["initialization"] == "truth_near":
        raise ValueError("Truth-near diagnostics require explicitly supplied geometry")
    rng = np.random.default_rng(opts["seed"]); outcomes = []
    for index in range(opts["starts"]):
        begun = time.perf_counter()
        start = {"index": index, "status": "failed", "success": False, "initial": None, "estimate": None, "solver": {}, "diagnostics": {}}
        metadata = _metadata(problem, opts)
        try:
            if initial_geometries is not None:
                initial = copy.deepcopy(initial_geometries[index])
            elif opts["initialization"] == "algebraic":
                proposal = m5._algebraic(problem, inputs, times_s)
                start["diagnostics"]["algebraic_initializer"] = proposal
                if proposal["status"] != "success":
                    raise ValueError(f"Algebraic initializer {proposal['status']}: {proposal.get('error')}")
                saved = proposal["geometry"]; points = np.asarray(saved["knot_trajectory"])
                points = np.column_stack([np.interp(problem.times_s, saved["knot_times_s"], points[:, j]) for j in range(3)])
                initial = problem.geometry(problem.pack(points, saved["beacons"]))
            else:
                initial = m5._initial(problem, rng, index)
            if initial_geometries is None:
                initial = m5._perturb(problem, initial, rng)
            start["initial"] = initial
            if initial.get("initialization_error"):
                raise ValueError(initial["initialization_error"])
            x0 = problem.pack(initial["knot_trajectory"], initial["beacons"])
            if np.any(x0 < problem.lower) or np.any(x0 > problem.upper):
                raise ValueError("Initial geometry violates physical bounds")
            if not len(problem.ranges_m):
                raise ValueError("No retained observations; priors alone are not fitted")
            start["diagnostics"]["initializer"] = {"status": "success", "method": opts["initialization"], "source": "supplied physical geometry" if initial_geometries is not None else "generated proposal"}
            pilot = None; mask = None; second_x0 = x0
            if opts["loss"] == "hard_rejection":
                pilot_opts = {**opts, "loss": "gaussian"}
                pilot_result, pilot_x = _optimize(problem, pilot_opts, x0)
                pilot = m5.measurement_residuals(pilot_x, problem)
                mask = np.abs(pilot) <= opts["rejection_threshold_sigma"]
                start["diagnostics"]["rejection_pilot"] = {"success": bool(pilot_result.success), "status": int(pilot_result.status),
                    "message": str(pilot_result.message), "nfev": int(pilot_result.nfev), "objective": float(pilot_result.cost),
                    "parameters": pilot_x.tolist(), "geometry": problem.geometry(pilot_x), "residuals_normalized": pilot.tolist(), "retained_mask": mask.tolist()}
                if not np.any(mask):
                    raise ValueError("Hard rejection retained no range measurements; pilot preserved")
                second_x0 = pilot_x
            result, solution = _optimize(problem, opts, second_x0, mask)
            diag = _fit_diagnostics(solution, problem, opts, mask, pilot)
            start["diagnostics"].update(diag)
            start.update(status="success" if result.success else "not_converged", success=bool(result.success), estimate=problem.geometry(solution))
            initial_objective = .5 * np.sum(_objective_vectors(x0, problem, opts, mask)[0] ** 2)
            start["solver"] = {**metadata, "status": int(result.status), "message": str(result.message), "nfev": int(result.nfev),
                "njev": int(result.njev) if result.njev is not None else None, "iterations": None,
                "iterations_note": "SciPy reports evaluations, not iteration count; rejection pilot evaluations are separately retained",
                "runtime_s": time.perf_counter() - begun, "initial_objective": float(initial_objective),
                "second_stage_initial_objective": float(.5 * np.sum(_objective_vectors(second_x0, problem, opts, mask)[0] ** 2)),
                "initial_objective_definition": "Final declared robust objective at original physical start; for hard rejection, uses the mask frozen from pilot",
                "final_objective": float(result.cost), "optimality": float(result.optimality), "active_bounds": result.active_mask.tolist(),
                "initial_parameters": x0.tolist(), "final_parameters": solution.tolist(),
                **{key: value for key, value in diag.items() if key.endswith("objective")}}
        except Exception as exc:
            start["diagnostics"].setdefault("initializer", {"status": "failed", "method": opts["initialization"], "error": str(exc)})
            start["solver"] = {**metadata, "status": None, "message": f"{type(exc).__name__}: {exc}", "nfev": None, "njev": None,
                               "iterations": None, "runtime_s": time.perf_counter() - begun, "initial_objective": None,
                               "final_objective": None, "measurement_objective": None, "prior_objective": None}
        outcomes.append(start)
    return outcomes


def _m5_experiment(exp):
    result = _legacy_experiment(exp); result["schema_version"] = m5.SCHEMA_VERSION
    return result


def _problem(exp, opts):
    problem = m5._problem(_m5_experiment(exp), base_options(opts))
    problem.robust_options = opts
    problem.original_cycle_count = len(exp["estimator_input"]["times_s"])
    return problem


def make_initial_geometries(exp, options=None):
    validate_experiment(exp)
    return m5.make_initial_geometries(_m5_experiment(exp), base_options(validate_options(options)))


def compatible_initial_geometries(run, experiment, options=None):
    validate_experiment(experiment)
    opts = validate_options(run["options"] if options is None else options)
    source = copy.deepcopy(run); source["options"] = base_options(run["options"])
    return m5.compatible_initial_geometries(source, _m5_experiment(experiment), base_options(opts))


def rejection_evaluation(decisions, records):
    retained = [record for record in records if record["retained_index"] is not None]
    labels = np.array([record["nlos"] for record in retained], dtype=bool)
    flags = np.array([row["flagged"] for row in decisions], dtype=bool)
    tp = int(np.sum(labels & flags)); fp = int(np.sum(~labels & flags))
    fn = int(np.sum(labels & ~flags)); tn = int(np.sum(~labels & ~flags))
    return {"true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn,
            "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None,
            "false_positive_rate": fp / (fp + tn) if fp + tn else None,
            "evaluated_count": len(retained), "dropped_count_excluded": len(records) - len(retained),
            "definition": "Injected positive NLOS labels evaluated only after independent fitting. Gaussian/continuous-loss decisions use weight < weight_decision_threshold; hard rejection decisions use frozen zero weight. Dropped pings excluded; undefined denominator=null. Other contamination factors are not NLOS labels."}


def _robust_disclosure(opts):
    return {"loss": opts["loss"], "label_access": "Evaluation only; fitter receives assumed times, epoch/beacon, ranges/sigmas and declared surveyed map",
        "decision_rule": "hard_rejection: zero frozen pilot weight; otherwise influence weight strictly less than weight_decision_threshold",
        "loss_scale_sigma": opts["loss_scale_sigma"], "rejection_threshold_sigma": opts["rejection_threshold_sigma"],
        "weight_decision_threshold": opts["weight_decision_threshold"],
        "loss_assumptions": "Symmetric residual losses handle positive injected bias without knowing its sign/labels. No explicit per-beacon bias variables are fitted. Joint geometry can absorb contamination; low residual and optimizer convergence do not prove accuracy.",
        "selection_policy": "Prefer converged finite starts, then smallest final optimizer objective. Hard-rejection masks can differ between starts, so selected objective is not a common-data quality score; inspect all-data residuals, retained information and geometric errors separately.",
        "truth_assisted_diagnostic": opts["initialization"] == "truth_near", "all_observation_residuals_retained": True}


def solve_experiment(exp, options=None, initial_geometries=None):
    validate_experiment(exp); opts = validate_options(options)
    supplied = initial_geometries is not None
    if initial_geometries is None and opts["initialization"] == "truth_near":
        try:
            initial_geometries = make_initial_geometries(exp, opts)
        except Exception as exc:
            initial_geometries = [{"initialization_error": f"Truth-near initialization failed: {type(exc).__name__}: {exc}"} for _ in range(opts["starts"])]
    def fitter(observations, times_s, **kwargs):
        kwargs.update(opts)
        return fit_observations(observations, times_s, **kwargs)
    run = m4.solve_experiment(_legacy_experiment(exp), m5.base_options(base_options(opts)), initial_geometries, fit_callback=fitter)
    run.update(schema_version=SCHEMA_VERSION, experiment=copy.deepcopy(exp), options=opts)
    records = exp["contamination_reference"]["records"]
    retained = [record for record in records if record["retained_index"] is not None]
    for start in run["starts"]:
        if start["estimate"] is None:
            continue
        decisions = start["diagnostics"]["observation_decisions"]
        for row, record in zip(decisions, retained):
            row["source_index"] = record["source_index"]
        start["diagnostics"]["rejection_evaluation"] = rejection_evaluation(decisions, records)
    run["diagnostics"]["robust_estimation"] = _robust_disclosure(opts)
    run["diagnostics"]["initialization_source"] = "explicit compatible saved physical starts" if supplied else opts["initialization"]
    problem = _problem(exp, opts)
    run["diagnostics"]["solver_comparison"] = {**problem.disclosure(), "solver": opts["solver"], "initialization": opts["initialization"],
        "physical_rank_note": "Original and retained information use physical metre coordinates; native h/q sensitivity is separately disclosed",
        "lm_limitations": "Retained+prior residual count must cover parameter count; strict interior bounds; exponential overflow/underflow may fail and remain inspectable"}
    try:
        tp, tb, _ = m4._canonical(m4.truth_positions(exp["config"], problem.times_s), exp["truth"]["beacons"], m5.base_options(base_options(opts)))
        projected = problem.geometry(problem.pack(tp, tb, project=True))
        pe = np.linalg.norm(np.asarray(projected["knot_trajectory"]) - tp, axis=1)
        be = np.linalg.norm(np.asarray(projected["beacons"]) - tb, axis=1)
        run["diagnostics"]["native_model_projection"] = {"available": True, "knot_position_rmse_m": float(np.sqrt(np.mean(pe ** 2))),
            "map_rmse_m": float(np.sqrt(np.mean(be ** 2))), "note": "Canonical truth projected through selected M5 native model/bounds and positive height branch; evaluation only, not optimizer lower bound"}
    except (ValueError, IndexError) as exc:
        run["diagnostics"]["native_model_projection"] = {"available": False, "reason": str(exc)}
    validate_run(run)
    return run


@m3._format_errors
def validate_run(run):
    if run.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("M6 run requires schema6.0")
    json.dumps(run, allow_nan=False); validate_experiment(run["experiment"])
    opts = validate_options(run["options"])
    if opts != run["options"]:
        raise ValueError("Saved options require normalized defaults")
    proxy = copy.deepcopy(run)
    proxy.update(schema_version=m4.SCHEMA_VERSION, experiment=_legacy_experiment(run["experiment"]), options=m5.base_options(base_options(opts)))
    m4.validate_run(proxy)
    # Requests are persisted before fitting, and wrapper/infrastructure errors
    # can prevent construction of a native problem altogether. These envelopes
    # contain no finite result and must remain readable without claiming the
    # full numerical diagnostics exist. Finite outcomes always take the strict
    # recomputation path below, including after a terminal storage failure.
    if not run["starts"] and run["status"] in ("pending", "running"):
        return run
    if run["status"] == "failed" and isinstance(run.get("error"), str) and run["error"] and all(start["estimate"] is None for start in run["starts"]):
        for start in run["starts"]:
            if not isinstance(start.get("solver", {}).get("message"), str) or not start["solver"]["message"]:
                raise ValueError("Infrastructure-failed attempts require inspectable solver messages")
        return run
    problem = _problem(run["experiment"], opts)
    robust_expected = _robust_disclosure(opts)
    robust_saved = run["diagnostics"].get("robust_estimation")
    # The selection-policy prose was added during M6 integration. Earlier
    # retained attempts remain readable; when present it must be accurate.
    if isinstance(robust_saved, dict) and "selection_policy" not in robust_saved:
        robust_expected.pop("selection_policy")
    if robust_saved != robust_expected:
        raise ValueError("Saved robust assumptions or decision disclosures disagree with options")
    records = run["experiment"]["contamination_reference"]["records"]
    retained = [record for record in records if record["retained_index"] is not None]
    for start in run["starts"]:
        solver, diag = start["solver"], start["diagnostics"]
        for key, value in _metadata(problem, opts).items():
            if solver.get(key) != value:
                raise ValueError("Saved estimator metadata differs from declared objective: " + key)
        pilot = diag.get("rejection_pilot"); mask = None; pilot_r = None
        if pilot is not None:
            if opts["loss"] != "hard_rejection":
                raise ValueError("Pilot only belongs to explicit hard rejection")
            px = m3._array(pilot["parameters"], (problem.parameter_count,), "pilot parameters")
            if np.any(px < problem.lower) or np.any(px > problem.upper):
                raise ValueError("Pilot violates bounds")
            pilot_r = m5.measurement_residuals(px, problem)
            mask = np.abs(pilot_r) <= opts["rejection_threshold_sigma"]
            for key, value in {"geometry": problem.geometry(px), "residuals_normalized": pilot_r.tolist(), "retained_mask": mask.tolist(), "objective": float(.5 * np.sum(m5.residuals(px, problem) ** 2))}.items():
                if not m5._same_diagnostics(pilot.get(key), value):
                    raise ValueError("Saved rejection pilot disagrees with geometry: " + key)
        if start["estimate"] is None:
            if not isinstance(solver.get("message"), str) or not solver["message"]:
                raise ValueError("Failed outcomes require an inspectable failure message")
            continue
        if opts["loss"] == "hard_rejection" and (pilot is None or not np.any(mask)):
            raise ValueError("Hard rejection requires saved pilot and at least one retained measurement")
        x = m3._array(solver["final_parameters"], (problem.parameter_count,), "native parameters")
        if np.any(x < problem.lower) or np.any(x > problem.upper):
            raise ValueError("Saved estimate violates native bounds")
        if opts["solver"] == "lm" and (np.any(x <= problem.lower) or np.any(x >= problem.upper)):
            raise ValueError("Saved LM estimate violates strict interior")
        expected_geometry = problem.geometry(x)
        if not m5._same_diagnostics(start["estimate"], expected_geometry):
            raise ValueError("Saved native parameter vector disagrees with geometry")
        truth = run["experiment"]["truth"]
        physical_opts = m5.base_options(base_options(opts))
        try:
            evaluation = m4.evaluate_geometry(expected_geometry, truth, physical_opts)
            ping_evaluation = m4.evaluate_geometry({"trajectory": expected_geometry["ping_trajectory"], "beacons": expected_geometry["beacons"]},
                                                   {"trajectory": truth["ping_positions"], "beacons": truth["beacons"]}, physical_opts)
        except ValueError:
            evaluation = None
        if evaluation is not None:
            if not m5._same_diagnostics(diag.get("evaluation"), evaluation) or not m5._same_diagnostics(diag.get("ping_evaluation"), ping_evaluation):
                raise ValueError("Saved geometric evaluation disagrees with truth/estimate and permitted alignment")
        elif "evaluation" in diag or "ping_evaluation" in diag:
            raise ValueError("Unavailable truth frame cannot carry valid geometric evaluation")
        expected = _fit_diagnostics(x, problem, opts, mask, pilot_r)
        for row, record in zip(expected["observation_decisions"], retained):
            row["source_index"] = record["source_index"]
        expected["rejection_evaluation"] = rejection_evaluation(expected["observation_decisions"], records)
        for key, value in expected.items():
            if not m5._same_diagnostics(diag.get(key), value):
                raise ValueError("Saved M6 diagnostics fail offline recomputation: " + key)
        for key, value in expected.items():
            if key.endswith("objective") and not m5._same_diagnostics(solver.get(key), value):
                raise ValueError("Saved objective contribution inconsistent: " + key)
        total = expected["measurement_objective"] + expected["prior_objective"]
        if not m5._same_diagnostics(solver.get("final_objective"), total):
            raise ValueError("Saved total objective inconsistent")
        x0 = problem.pack(start["initial"]["knot_trajectory"], start["initial"]["beacons"])
        if not m5._same_diagnostics(solver.get("initial_parameters"), x0.tolist()):
            raise ValueError("Saved initial native coordinates inconsistent")
        initial_cost = float(.5 * np.sum(_objective_vectors(x0, problem, opts, mask)[0] ** 2))
        second_cost = float(.5 * np.sum(_objective_vectors(np.asarray(pilot["parameters"]) if pilot is not None else x0, problem, opts, mask)[0] ** 2))
        if not m5._same_diagnostics(solver.get("initial_objective"), initial_cost) or not m5._same_diagnostics(solver.get("second_stage_initial_objective"), second_cost):
            raise ValueError("Saved start objective inconsistent")
    if run["starts"]:
        finite = [s for s in run["starts"] if s["estimate"] is not None]
        preferred = [s for s in finite if s["success"]] or finite
        selected = min(preferred, key=lambda s: s["solver"]["final_objective"])["index"] if preferred else None
        if run["selected_start"] != selected:
            raise ValueError("Saved selected start inconsistent with objective and convergence policy")
    return run
