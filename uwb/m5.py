"""Solver comparisons with identical physical range objectives and saved starts.

The bounded TRF method works in physical h/metre or q/metre² coordinates.
LM preserves all finite bounds through exponential coordinate maps. Its feasible
domain is the strict interior; this distinction is saved with every attempt.
"""
from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from . import m3, m4

SCHEMA_VERSION = "5.0"
MAX_KNOTS = m4.MAX_KNOTS
FLOOR = m4.FLOOR
EXTRA_KEYS = {"solver", "height_parameterization", "algebraic_physical_tolerance", "initialization_error_m"}
normalize_config = m4.normalize_config


def generate_experiment(config=None):
    exp = m4.generate_experiment(config)
    exp["schema_version"] = SCHEMA_VERSION
    return exp


def _m4_experiment(exp):
    result = copy.deepcopy(exp)
    result["schema_version"] = m4.SCHEMA_VERSION
    return result


@m3._format_errors
def validate_experiment(exp):
    if exp.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("M5 experiment requires schema5.0")
    m4.validate_experiment(_m4_experiment(exp))
    return exp


def base_options(options):
    result = {k: v for k, v in options.items() if k not in EXTRA_KEYS}
    if result.get("initialization") == "algebraic":
        result["initialization"] = "independent"
    return m4.validate_options(result)


@m3._format_errors
def validate_options(options=None):
    supplied = dict(options or {})
    solver = supplied.pop("solver", "trf")
    parameterization = supplied.pop("height_parameterization", "h")
    tolerance = m3._number(supplied.pop("algebraic_physical_tolerance", 1e-7), "algebraic_physical_tolerance", 1e-12, .1)
    initialization = supplied.get("initialization", "independent")
    error = m3._number(supplied.pop("initialization_error_m", .15 if initialization == "truth_near" else 0.), "initialization_error_m", 0., 1000.)
    if initialization == "algebraic": supplied["initialization"] = "independent"
    opts = m4.validate_options(supplied)
    if initialization not in ("independent", "truth_near", "algebraic"):
        raise ValueError("Invalid initialization")
    if solver not in ("trf", "lm"):
        raise ValueError("solver must be trf or lm")
    if parameterization not in ("h", "q"):
        raise ValueError("height_parameterization must be h or q")
    if parameterization == "q" and not (opts["tag_height_model"] in ("fixed", "shared") and
            ((opts["mode"] == "joint" and opts["beacon_height_model"] == "shared") or
             (opts["mode"] == "known_map" and opts["tag_height_model"] == "shared"))):
        raise ValueError("q requires one shared relative height: joint planar tags/shared beacon plane, or shared tags under a surveyed horizontal plane")
    return {**opts, "initialization": initialization, "solver": solver,
            "height_parameterization": parameterization, "algebraic_physical_tolerance": tolerance, "initialization_error_m": error}


@dataclass
class SolverProblem:
    physical: m4.HeightProblem
    options: dict
    height_index: int | None
    height_origin: float
    height_sign: float
    lower: np.ndarray
    upper: np.ndarray

    def __getattr__(self, name):
        return getattr(self.physical, name)

    def physical_parameters(self, parameters):
        x = np.asarray(parameters, dtype=float).copy()
        if self.height_index is not None:
            value = x[self.height_index]
            if self.options["height_parameterization"] == "q":
                if value < 0: raise ValueError("q must be nonnegative")
                value = np.sqrt(value)
            x[self.height_index] = self.height_origin + self.height_sign * value
        return x

    def unpack(self, parameters):
        return self.physical.unpack(self.physical_parameters(parameters))

    def geometry(self, parameters):
        return self.physical.geometry(self.physical_parameters(parameters))

    def pack(self, trajectory, beacons, *, project=False):
        x = self.physical.pack(trajectory, beacons, project=project)
        if self.height_index is not None:
            h = self.height_sign * (x[self.height_index] - self.height_origin)
            if project: h = max(h, 2 * FLOOR)
            if h < FLOOR: raise ValueError("Shared relative height must be positive (at least 1e-6 m); negative/reflected branch not selected")
            x[self.height_index] = h ** 2 if self.options["height_parameterization"] == "q" else h
        return x

    def disclosure(self):
        return {"height_parameterization": self.options["height_parameterization"],
                "shared_height_index": self.height_index, "height_origin_m": self.height_origin,
                "height_sign": self.height_sign,
                "height_units": "m²" if self.options["height_parameterization"] == "q" else "m",
                "positive_relative_height_branch": self.height_index is not None,
                "minimum_relative_height_m": FLOOR if self.height_index is not None else None,
                "objective": "Original unsquared range residual/sigma plus separately disclosed M4 motion and height priors",
                "q_definition": "q=h², positive beacon-minus-tag separation; no squared-range objective" if self.options["height_parameterization"] == "q" else None,
                "bounds_lower": [float(v) if np.isfinite(v) else None for v in self.lower],
                "bounds_upper": [float(v) if np.isfinite(v) else None for v in self.upper]}


def build_problem(observations, times_s, *, beacon_count=None, display_times_s=None, surveyed_beacons=None, **options):
    opts = validate_options(options)
    physical = m4.build_problem(observations, times_s, beacon_count=beacon_count, display_times_s=display_times_s,
                                surveyed_beacons=surveyed_beacons, **base_options(opts))
    index = None; origin = 0.; sign = 1.
    if opts["mode"] == "joint" and opts["tag_height_model"] in ("fixed", "shared") and opts["beacon_height_model"] == "shared":
        index = int(np.flatnonzero(np.all(physical.beacon_basis[:, 2] == 1., axis=0))[0])
        origin = opts["fixed_tag_z_m"]
    elif opts["mode"] == "known_map" and opts["tag_height_model"] == "shared" and np.ptp(physical.surveyed_beacons[:, 2]) <= 1e-12:
        index = int(np.flatnonzero(np.all(physical.tag_basis[:, 2] == 1., axis=0))[0])
        origin = float(physical.surveyed_beacons[0, 2]); sign = -1.
    if opts["height_parameterization"] == "q" and index is None:
        raise ValueError("q requires a horizontal surveyed beacon plane; varying world-z maps have no single shared relative height")
    lower, upper = physical.lower.copy(), physical.upper.copy()
    if index is not None:
        lower[index] = FLOOR ** 2 if opts["height_parameterization"] == "q" else FLOOR
        upper[index] = np.inf
    return SolverProblem(physical, opts, index, origin, sign, lower, upper)


def measurement_residuals(parameters, problem):
    return m4.measurement_residuals(problem.physical_parameters(parameters), problem.physical)


def prior_components(parameters, problem):
    return m4.prior_components(problem.physical_parameters(parameters), problem.physical)


def residuals(parameters, problem):
    motion, height = prior_components(parameters, problem)
    return np.r_[measurement_residuals(parameters, problem), motion, height]


def measurement_jacobian(parameters, problem):
    physical = problem.physical_parameters(parameters)
    matrix = m4.measurement_jacobian(physical, problem.physical)
    index = problem.height_index
    if index is not None:
        if problem.options["height_parameterization"] == "h":
            matrix[:, index] *= problem.height_sign
        else:
            p, b = problem.unpack(parameters)
            distance = np.linalg.norm(problem.weights @ p - b[problem.beacon_ids], axis=1)
            # Analytic derivative of sqrt(horizontal²+q). No 1/sqrt(q)
            # intermediate is needed, including at q=0 (nonzero range).
            matrix[:, index] = .5 / (np.maximum(distance, np.finfo(float).tiny) * problem.sigma_m)
    return matrix


def jacobian(parameters, problem):
    matrix = m4.jacobian(problem.physical_parameters(parameters), problem.physical)
    matrix[:len(problem.ranges_m)] = measurement_jacobian(parameters, problem)
    if problem.height_index is not None:
        # A shared constant tag height cancels from all time-weighted motion
        # priors; soft height models have no q/shared-height coordinate.
        matrix[len(problem.ranges_m):, problem.height_index] = 0.
    return matrix


def jacobian_diagnostics(parameters, problem, *, augmented=False):
    matrix = jacobian(parameters, problem) if augmented else measurement_jacobian(parameters, problem)
    scale = max(float(np.median(np.abs(problem.ranges_m))) if len(problem.ranges_m) else 1., 1.)
    scales = np.full(problem.parameter_count, scale)
    if problem.height_index is not None and problem.options["height_parameterization"] == "q": scales[problem.height_index] = scale ** 2
    singular = np.linalg.svd(matrix * scales, compute_uv=False)
    cutoff = singular[0] * 1e-8 if len(singular) else 0.
    rank = int(np.sum(singular > cutoff)); full = rank == problem.parameter_count
    return {"rank": rank, "parameter_count": problem.parameter_count, "measurement_count": len(problem.ranges_m),
            "prior_residual_count": len(matrix) - len(problem.ranges_m), "full_column_rank": full,
            "condition_number": float(singular[0] / singular[-1]) if full else None,
            "singular_values": singular.tolist(), "relative_tolerance": 1e-8, "absolute_tolerance": float(cutoff),
            "parameter_scales": scales.tolist(), "parameter_units": ["m²" if i == problem.height_index and problem.options["height_parameterization"] == "q" else "m" for i in range(problem.parameter_count)],
            "scaling": "Dimensionless physical coordinates: metre parameters/median-range; q/median-range²",
            "interpretation": "Coordinate-dependent local sensitivity; q at zero has a singular inverse to h and must not be interpreted as new physical height information"}


class BoundTransform:
    """Exact interior maps for every finite coordinate bound; no clipping."""
    def __init__(self, lower, upper):
        self.lower, self.upper = lower, upper
        if np.any(np.isfinite(lower) & np.isfinite(upper)):
            raise ValueError("Two-sided LM transforms are unsupported")

    def encode(self, x):
        u = np.asarray(x).copy()
        lo, hi = np.isfinite(self.lower), np.isfinite(self.upper)
        if np.any(x[lo] <= self.lower[lo]) or np.any(x[hi] >= self.upper[hi]):
            raise ValueError("LM exponential bounds require strictly interior starts")
        u[lo] = np.log(x[lo] - self.lower[lo]); u[hi] = np.log(self.upper[hi] - x[hi])
        return u

    def decode(self, u):
        x, derivative = np.asarray(u).copy(), np.ones(len(u))
        lo, hi = np.isfinite(self.lower), np.isfinite(self.upper)
        with np.errstate(over="raise", invalid="raise"):
            x[lo] = self.lower[lo] + np.exp(u[lo]); derivative[lo] = np.exp(u[lo])
            x[hi] = self.upper[hi] - np.exp(u[hi]); derivative[hi] = -np.exp(u[hi])
        if not np.all(np.isfinite(x)) or not np.all(np.isfinite(derivative)) or np.any(x[lo] <= self.lower[lo]) or np.any(x[hi] >= self.upper[hi]) or np.any(derivative[lo | hi] == 0):
            raise FloatingPointError("LM exponential transform lost strict interior through underflow/rounding or produced a nonfinite coordinate; no clipping or zero derivative accepted")
        return x, derivative


def _initial(problem, rng, index):
    saved = m4._initial(problem.physical, rng, index)
    x = problem.pack(saved["knot_trajectory"], saved["beacons"], project=True)
    return problem.geometry(x)


def _perturb(problem, initial, rng):
    if not problem.options["initialization_error_m"]: return initial
    physical = problem.physical
    x = physical.pack(initial["knot_trajectory"], initial["beacons"])
    x += rng.normal(0., problem.options["initialization_error_m"], len(x))
    x = np.maximum(np.minimum(x, np.where(np.isfinite(physical.upper), physical.upper - FLOOR, physical.upper)), np.where(np.isfinite(physical.lower), physical.lower + FLOOR, physical.lower))
    p, b = physical.unpack(x)
    return problem.geometry(problem.pack(p, b, project=True))


def _algebraic(problem, observations, times_s):
    from . import m5_algebraic
    return m5_algebraic.propose_initialization(observations, times_s, beacon_count=problem.beacon_count, options=problem.options)


def fit_observations(observations, times_s, *, beacon_count=None, display_times_s=None, surveyed_beacons=None, initial_geometries=None, **options):
    opts = validate_options(options)
    problem = build_problem(observations, times_s, beacon_count=beacon_count, display_times_s=display_times_s, surveyed_beacons=surveyed_beacons, **opts)
    if initial_geometries is not None and len(initial_geometries) != opts["starts"]: raise ValueError("Supply every requested initial geometry")
    if initial_geometries is None and opts["initialization"] == "truth_near": raise ValueError("Measurement-only fitting requires explicitly supplied truth-near geometry")
    rng = np.random.default_rng(opts["seed"]); outcomes = []
    for index in range(opts["starts"]):
        begun = time.perf_counter()
        start = {"index": index, "status": "failed", "success": False, "initial": None, "estimate": None, "solver": {}, "diagnostics": {}}
        metadata = {"bounds_transform_revision":2, "method": f"scipy.optimize.least_squares/{opts['solver']}", "height_parameterization": opts["height_parameterization"],
                    "bounds_handling": "Explicit native bounds" if opts["solver"] == "trf" else "x=lower+exp(u), x=upper-exp(u); all finite bounds preserved, strict interior",
                    "lm_coordinate_units": "Finite-bound coordinates are dimensionless logs of the offset measured in one native unit (1 m or 1 m²); unbounded coordinates retain native units" if opts["solver"] == "lm" else None,
                    "bounds_domain": "Closed native bounds" if opts["solver"] == "trf" else "Strict interior, boundary approached asymptotically",
                    "derivatives": "Analytic original-range/prior Jacobian with exact coordinate chain rule", "parameterization": problem.disclosure(),
                    "initialization_error_m": opts["initialization_error_m"], "initialization_perturbation": "Gaussian metre-coordinate SD on canonical M4 parameters before h/q mapping; interior projection; skipped for supplied paired starts",
                    "ftol": 1e-12, "xtol": 1e-12, "gtol": 1e-12, "x_scale": "jac", "loss": "linear", "max_nfev": opts["max_nfev"]}
        try:
            if initial_geometries is not None:
                initial = copy.deepcopy(initial_geometries[index])
            elif opts["initialization"] == "algebraic":
                initializer = _algebraic(problem, observations, times_s)
                start["diagnostics"]["algebraic_initializer"] = initializer
                if initializer["status"] != "success": raise ValueError(f"Algebraic initializer {initializer['status']}: {initializer.get('error')}")
                initial = initializer["geometry"]
                # Project only onto the declared knot grid/model, preserving the
                # algebraic geometry. Repeated starts are explicitly identical.
                p = np.asarray(initial.get("knot_trajectory", initial["trajectory"]))
                grid = np.asarray(initial.get("knot_times_s", times_s))
                p = np.column_stack([np.interp(problem.times_s, grid, p[:, j]) for j in range(3)])
                initial = problem.geometry(problem.pack(p, initial["beacons"]))
            else:
                initial = _initial(problem, rng, index)
            if initial_geometries is None: initial = _perturb(problem, initial, rng)
            start["initial"] = initial
            if initial.get("initialization_error"):
                raise ValueError(initial["initialization_error"])
            x0 = problem.pack(initial.get("knot_trajectory", initial.get("trajectory")), initial["beacons"])
            if np.any(x0 < problem.lower) or np.any(x0 > problem.upper): raise ValueError("Initial geometry violates bounds")
            start["diagnostics"]["initializer"] = {"status":"success", "method":opts["initialization"], "source":"supplied physical geometry" if initial_geometries is not None else "generated proposal"}
            r0 = residuals(x0, problem)
            if not len(problem.ranges_m): raise ValueError("No retained observations; priors alone are not fitted")
            if opts["solver"] == "lm":
                transform = BoundTransform(problem.lower, problem.upper)
                def fun(u): return residuals(transform.decode(u)[0], problem)
                def derivative(u):
                    x, chain = transform.decode(u)
                    return jacobian(x, problem) * chain
                result = least_squares(fun, transform.encode(x0), jac=derivative, method="lm", x_scale="jac", ftol=1e-12, xtol=1e-12, gtol=1e-12, max_nfev=opts["max_nfev"])
                solution = transform.decode(result.x)[0]
            else:
                result = least_squares(residuals, x0, jac=jacobian, args=(problem,), bounds=(problem.lower, problem.upper), method="trf", x_scale="jac", ftol=1e-12, xtol=1e-12, gtol=1e-12, max_nfev=opts["max_nfev"])
                solution = result.x
            mr = measurement_residuals(solution, problem); motion, height = prior_components(solution, problem); metres = mr * problem.sigma_m
            objectives = {"measurement_objective": float(.5 * mr @ mr), "motion_prior_objective": float(.5 * motion @ motion), "height_prior_objective": float(.5 * height @ height), "prior_objective": float(.5 * motion @ motion + .5 * height @ height)}
            start.update(status="success" if result.success else "not_converged", success=bool(result.success), estimate=problem.geometry(solution))
            start["solver"] = {**metadata, "status": int(result.status), "message": str(result.message), "nfev": int(result.nfev), "njev": int(result.njev) if result.njev is not None else None,
                               "iterations": None, "iterations_note": "SciPy reports evaluations, not iteration count", "runtime_s": time.perf_counter() - begun,
                               "initial_objective": float(.5 * r0 @ r0), "final_objective": float(result.cost), "optimality": float(result.optimality), "active_bounds": result.active_mask.tolist(),
                               "initial_parameters": x0.tolist(), "final_parameters": solution.tolist(), **objectives}
            start["diagnostics"].update(residuals_m=metres.tolist(), residuals_normalized=mr.tolist(), motion_prior_residuals_normalized=motion.tolist(), height_prior_residuals_normalized=height.tolist(),
                                       range_rmse_m=float(np.sqrt(np.mean(metres ** 2))), max_abs_residual_m=float(np.max(np.abs(metres))),
                                       jacobian=m4.jacobian_diagnostics(problem.physical_parameters(solution), problem.physical),
                                       augmented_jacobian=m4.jacobian_diagnostics(problem.physical_parameters(solution), problem.physical, augmented=True),
                                       native_jacobian=jacobian_diagnostics(solution, problem), native_augmented_jacobian=jacobian_diagnostics(solution, problem, augmented=True), **objectives)
        except Exception as exc:
            start["diagnostics"].setdefault("initializer", {"status":start["diagnostics"].get("algebraic_initializer", {}).get("status", "failed"), "method":opts["initialization"], "error":str(exc)})
            start["solver"] = {**metadata, "status": None, "message": f"{type(exc).__name__}: {exc}", "nfev": None, "njev": None, "iterations": None,
                               "runtime_s": time.perf_counter() - begun, "initial_objective": None, "final_objective": None, "measurement_objective": None, "prior_objective": None}
        outcomes.append(start)
    return outcomes


def _problem(exp, opts):
    return build_problem(exp["estimator_input"]["observations"], exp["estimator_input"]["times_s"], beacon_count=exp["config"]["beacon_layout"]["count"], display_times_s=exp["truth"]["times_s"],
                         surveyed_beacons=exp["truth"]["beacons"] if opts["mode"] == "known_map" else None, **opts)


def solve_experiment(exp, options=None, initial_geometries=None):
    validate_experiment(exp); opts = validate_options(options)
    problem = _problem(exp, opts)
    supplied_starts = initial_geometries is not None
    if initial_geometries is None and opts["initialization"] == "truth_near":
        try: initial_geometries = make_initial_geometries(exp, opts)
        except Exception as exc:
            initial_geometries = [{"initialization_error":f"Truth-near initialization failed: {type(exc).__name__}: {exc}"} for _ in range(opts["starts"])]
    def fitter(observations, times_s, **kwargs):
        kwargs.update(opts)
        return fit_observations(observations, times_s, **kwargs)
    run = m4.solve_experiment(_m4_experiment(exp), base_options(opts), initial_geometries, fit_callback=fitter)
    run.update(schema_version=SCHEMA_VERSION, experiment=copy.deepcopy(exp), options=opts)
    run["diagnostics"]["solver_comparison"] = {**problem.disclosure(), "solver": opts["solver"], "initialization": opts["initialization"],
        "physical_rank_note": "Primary Jacobian diagnostics use metre geometry; native diagnostics separately expose h/q coordinate sensitivity",
        "lm_limitations": "LM needs residual_count>=parameter_count and strictly interior starts; failed starts retained. Exponential transforms can overflow or underflow and can stagnate near bounds."}
    run["diagnostics"]["initialization_source"] = "explicit compatible saved physical starts" if supplied_starts else opts["initialization"]
    # This is truth-only evaluation, never used by the fitter or initialization.
    # M4's representation diagnostics precede M5's optional positive-height map.
    try:
        tp,tb,_ = m4._canonical(m4.truth_positions(exp["config"],problem.times_s),exp["truth"]["beacons"],base_options(opts))
        projected = problem.geometry(problem.pack(tp,tb,project=True))
        pe=np.linalg.norm(np.asarray(projected["knot_trajectory"])-tp,axis=1)
        be=np.linalg.norm(np.asarray(projected["beacons"])-tb,axis=1)
        run["diagnostics"]["native_model_projection"]={"available":True,"knot_position_rmse_m":float(np.sqrt(np.mean(pe**2))),"map_rmse_m":float(np.sqrt(np.mean(be**2))),"note":"Projection of canonical truth into M5 native model/bounds, including the selected shared-height branch; not an optimizer lower bound. M4 interpolation/model diagnostics describe the preceding physical parameterization."}
    except (ValueError,IndexError) as exc:
        run["diagnostics"]["native_model_projection"]={"available":False,"reason":str(exc)}

    validate_run(run)
    return run


def make_initial_geometries(exp, options=None):
    """Return deterministic physical starts for pairing; explicitly uses truth
    only when truth_near was selected. Failed algebraic fits raise here; solving
    retains those failures as attempts instead of calling this helper.
    """
    validate_experiment(exp); opts = validate_options(options); problem = _problem(exp, opts)
    rng = np.random.default_rng(opts["seed"]); geometries = []
    if opts["initialization"] == "truth_near":
        p, b, _ = m4._canonical(m4.truth_positions(exp["config"], problem.times_s), exp["truth"]["beacons"], base_options(opts))
        base = problem.geometry(problem.pack(p, b, project=True))
    elif opts["initialization"] == "algebraic":
        result = _algebraic(problem, exp["estimator_input"]["observations"], exp["estimator_input"]["times_s"])
        if result["status"] != "success": raise ValueError(f"Algebraic initializer {result['status']}: {result.get('error')}")
        saved = result["geometry"]; p = np.asarray(saved["knot_trajectory"])
        p = np.column_stack([np.interp(problem.times_s, saved["knot_times_s"], p[:, j]) for j in range(3)])
        base = problem.geometry(problem.pack(p, saved["beacons"]))
    for index in range(opts["starts"]):
        initial = _initial(problem, rng, index) if opts["initialization"] == "independent" else copy.deepcopy(base)
        geometries.append(_perturb(problem, initial, rng))
    return geometries


def compatible_initial_geometries(run, experiment, options=None):
    opts = validate_options(run["options"] if options is None else options)
    source = copy.deepcopy(run); source["options"] = base_options(source["options"])
    return m4.compatible_initial_geometries(source, _m4_experiment(experiment), base_options(opts))


def _same_diagnostics(saved, expected):
    if isinstance(expected, dict): return isinstance(saved, dict) and set(saved)==set(expected) and all(_same_diagnostics(saved[key],value) for key,value in expected.items())
    if isinstance(expected, list): return isinstance(saved,list) and len(saved)==len(expected) and all(_same_diagnostics(a,b) for a,b in zip(saved,expected))
    if isinstance(expected,float): return isinstance(saved,(float,int)) and np.isclose(saved,expected,atol=1e-8,rtol=1e-8)
    return saved==expected


@m3._format_errors
def validate_run(run):
    if run.get("schema_version") != SCHEMA_VERSION: raise ValueError("M5 run requires schema5.0")
    json.dumps(run, allow_nan=False); validate_experiment(run["experiment"])
    opts = validate_options(run["options"])
    if opts != run["options"]: raise ValueError("Saved options must contain normalized defaults")
    proxy = copy.deepcopy(run)
    proxy.update(schema_version=m4.SCHEMA_VERSION, experiment=_m4_experiment(run["experiment"]), options=base_options(opts))
    m4.validate_run(proxy)
    problem = _problem(run["experiment"], opts)
    for start in run["starts"]:
        if start["estimate"] is not None:
            diag, solver = start["diagnostics"], start["solver"]
            # Native coordinates are retained explicitly: inverse world-z packing
            # can lose small h/q offsets through cancellation near a surveyed plane.
            x = np.asarray(solver.get("final_parameters"),dtype=float)
            if x.shape != (problem.parameter_count,) or not np.all(np.isfinite(x)): raise ValueError("Invalid saved native parameter vector")
            expected_geometry = problem.geometry(x)
            for field in ("trajectory","beacons","knot_trajectory","ping_trajectory","assumed_ping_trajectory"):
                if not np.allclose(start["estimate"][field],expected_geometry[field],atol=1e-8,rtol=1e-9): raise ValueError("Saved native parameters disagree with physical estimate")
            if np.any(x < problem.lower - 1e-14) or np.any(x > problem.upper + 1e-14): raise ValueError("M5 geometry violates native physical bounds")
            mr = measurement_residuals(x, problem); motion, height = prior_components(x, problem)
            for key, expected in [("residuals_normalized",mr),("residuals_m",mr*problem.sigma_m),("motion_prior_residuals_normalized",motion),("height_prior_residuals_normalized",height)]:
                saved = np.asarray(diag.get(key),dtype=float)
                if saved.shape != expected.shape or not np.allclose(saved,expected,atol=1e-8,rtol=1e-8): raise ValueError("Saved residuals disagree with retained measurements/geometry: "+key)
            values = {"measurement_objective":.5*mr@mr,"motion_prior_objective":.5*motion@motion,"height_prior_objective":.5*height@height,"prior_objective":.5*(motion@motion+height@height),"final_objective":.5*(mr@mr+motion@motion+height@height)}
            for key,value in values.items():
                if not np.isclose(solver.get(key,float("nan")),value,atol=1e-8,rtol=1e-8): raise ValueError("Saved objective disagrees with retained measurements/geometry: "+key)
            if solver.get("parameterization") != problem.disclosure() or solver.get("loss") != "linear": raise ValueError("Saved parameterization/objective disclosure is inconsistent")
            for key, expected in [("jacobian",m4.jacobian_diagnostics(problem.physical_parameters(x),problem.physical)),("augmented_jacobian",m4.jacobian_diagnostics(problem.physical_parameters(x),problem.physical,augmented=True)),("native_jacobian",jacobian_diagnostics(x,problem)),("native_augmented_jacobian",jacobian_diagnostics(x,problem,augmented=True))]:
                if not _same_diagnostics(diag.get(key),expected): raise ValueError("Saved information diagnostics disagree with retained geometry: "+key)
            initial = start["initial"]
            x0 = problem.pack(initial["knot_trajectory"],initial["beacons"])
            if not np.allclose(solver.get("initial_parameters"),x0,atol=1e-8,rtol=1e-8) or not np.isclose(solver.get("initial_objective",float("nan")),.5*residuals(x0,problem)@residuals(x0,problem),atol=1e-8,rtol=1e-8): raise ValueError("Saved initial parameters/objective disagree with physical start")

            if opts["solver"] == "lm" and solver.get("bounds_transform_revision",1) >= 2 and (np.any(x <= problem.lower) or np.any(x >= problem.upper)): raise ValueError("Saved LM estimate violates its strict interior domain")

        if start.get("solver", {}).get("height_parameterization") != opts["height_parameterization"] or start.get("solver", {}).get("method") != f"scipy.optimize.least_squares/{opts['solver']}":
            raise ValueError("Attempt solver metadata disagrees with saved options")
    return run
