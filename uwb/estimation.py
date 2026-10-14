"""Planar range-only estimation. Truth is available only to the evaluation wrapper."""
from __future__ import annotations

import copy
import platform
import time
from dataclasses import dataclass

import numpy as np
import scipy
from scipy.optimize import least_squares


POSITIVE_FLOOR_M = 1e-6
RANK_RELATIVE_TOLERANCE = 1e-8
WEAK_CONDITION_THRESHOLD = 1e3


@dataclass
class RangeProblem:
    times_s: np.ndarray
    epochs: np.ndarray
    beacon_ids: np.ndarray
    ranges_m: np.ndarray
    sigma_m: np.ndarray
    mode: str
    surveyed_beacons: np.ndarray | None = None

    @property
    def parameter_count(self):
        return 2 * len(self.times_s) + (6 if self.mode == "joint" else 0)

    def unpack(self, parameters):
        p = np.asarray(parameters, dtype=float)
        trajectory = np.column_stack((p[:2 * len(self.times_s)].reshape(-1, 2), np.zeros(len(self.times_s))))
        if self.mode == "known_map":
            beacons = self.surveyed_beacons.copy()
        else:
            d, a, b, c, e, h = p[-6:]
            beacons = np.array([[0., 0., h], [d, 0., h], [a, b, h], [c, e, h]])
        return trajectory, beacons

    def pack(self, trajectory, beacons):
        t = np.asarray(trajectory, dtype=float)
        b = np.asarray(beacons, dtype=float)
        if t.shape != (len(self.times_s), 3) or not np.all(np.isfinite(t)) or not np.allclose(t[:, 2], 0):
            raise ValueError("Initial trajectory must contain one finite planar xyz point per epoch")
        if b.shape != (4, 3) or not np.all(np.isfinite(b)):
            raise ValueError("Initial beacons must be a finite 4 by 3 array")
        p = t[:, :2].ravel()
        if self.mode == "known_map" and not np.allclose(b, self.surveyed_beacons, atol=1e-10, rtol=0):
            raise ValueError("Known-map initial beacons must equal the explicitly surveyed map")
        if self.mode == "joint":
            if not (np.allclose(b[0, :2], 0) and abs(b[1, 1]) < 1e-8 and np.allclose(b[:, 2], b[0, 2])):
                raise ValueError("Joint initial map must satisfy the documented canonical gauge")
            if min(b[1, 0], b[2, 1], b[0, 2]) <= POSITIVE_FLOOR_M:
                raise ValueError("Joint initial d, beacon 2 y, and shared height must be positive")
            p = np.concatenate((p, [b[1, 0], b[2, 0], b[2, 1], b[3, 0], b[3, 1], b[0, 2]]))
        return p


def build_problem(observations, times_s, *, mode="joint", surveyed_beacons=None):
    """Build measurement-only inputs; deliberately accepts no experiment or truth."""
    if mode not in ("joint", "known_map"):
        raise ValueError("mode must be joint or known_map")
    times = np.asarray(times_s, dtype=float)
    if times.ndim != 1 or len(times) < 4 or not np.all(np.isfinite(times)) or np.any(np.diff(times) <= 0):
        raise ValueError("At least four strictly increasing finite epoch times are required")
    if not observations:
        raise ValueError("No observations")
    epochs, ids, ranges, sigmas = [], [], [], []
    seen = set()
    for o in observations:
        epoch, beacon = int(o["epoch"]), int(o["beacon_id"])
        if epoch != o["epoch"] or beacon != o["beacon_id"] or not 0 <= epoch < len(times) or not 0 <= beacon < 4:
            raise ValueError("Observation epoch or beacon ID is invalid")
        if (epoch, beacon) in seen:
            raise ValueError("Duplicate epoch/beacon observation")
        seen.add((epoch, beacon))
        if not np.isclose(float(o["assumed_time_s"]), times[epoch], atol=1e-9, rtol=0):
            raise ValueError("M1 supports synchronized assumed timestamps only")
        r, sigma = float(o["range_m"]), float(o["sigma_m"])
        if not np.isfinite(r) or not np.isfinite(sigma) or sigma <= 0:
            raise ValueError("Ranges must be finite and assumed uncertainties strictly positive")
        epochs.append(epoch); ids.append(beacon); ranges.append(r); sigmas.append(sigma)
    if len(seen) != 4 * len(times):
        raise ValueError("M1 requires four observations at every epoch")
    surveyed = None
    if mode == "known_map":
        surveyed = np.asarray(surveyed_beacons, dtype=float)
        if surveyed.shape != (4, 3) or not np.all(np.isfinite(surveyed)):
            raise ValueError("known_map requires an explicit finite surveyed 4 by 3 map")
    elif surveyed_beacons is not None:
        raise ValueError("A surveyed map must not be supplied to joint estimation")
    return RangeProblem(times, np.array(epochs), np.array(ids), np.array(ranges), np.array(sigmas), mode, surveyed)


def residuals(parameters, problem):
    trajectory, beacons = problem.unpack(parameters)
    delta = trajectory[problem.epochs] - beacons[problem.beacon_ids]
    return (np.linalg.norm(delta, axis=1) - problem.ranges_m) / problem.sigma_m


def jacobian(parameters, problem):
    trajectory, beacons = problem.unpack(parameters)
    delta = trajectory[problem.epochs] - beacons[problem.beacon_ids]
    distance = np.maximum(np.linalg.norm(delta, axis=1), np.finfo(float).tiny)
    direction = delta / (distance * problem.sigma_m)[:, None]
    j = np.zeros((len(delta), problem.parameter_count))
    rows = np.arange(len(delta))
    j[rows, 2 * problem.epochs] = direction[:, 0]
    j[rows, 2 * problem.epochs + 1] = direction[:, 1]
    if problem.mode == "joint":
        offset = 2 * len(problem.times_s)
        for beacon, columns in ((1, (0, None)), (2, (1, 2)), (3, (3, 4))):
            mask = problem.beacon_ids == beacon
            for axis, column in enumerate(columns):
                if column is not None:
                    j[mask, offset + column] = -direction[mask, axis]
        j[:, -1] = -direction[:, 2]
    return j


def _linear_positions(problem, beacons):
    """Known-map squared differences supply a seed, never the fitted objective."""
    table = np.empty((len(problem.times_s), 4))
    table[problem.epochs, problem.beacon_ids] = problem.ranges_m
    a = 2 * (beacons[1:, :2] - beacons[0, :2])
    rhs = np.sum(beacons[1:] ** 2, axis=1) - np.sum(beacons[0] ** 2) - (table[:, 1:] ** 2 - table[:, :1] ** 2)
    xy = np.linalg.lstsq(a, rhs.T, rcond=None)[0].T
    return np.column_stack((xy, np.zeros(len(xy))))


def _independent_initial(problem, rng, index):
    scale = max(float(np.median(np.abs(problem.ranges_m))), 1.)
    if problem.mode == "known_map":
        beacons = problem.surveyed_beacons.copy()
    else:
        factor = 1. if index == 0 else rng.uniform(.7, 1.4)
        height = .3 if index == 0 else rng.uniform(.12, .55)
        beacons = scale * np.array([[0., 0., height], [1.1 * factor, 0., height], [.1 * factor, .9 * factor, height], [1.2 * factor, 1.05 * factor, height]])
        if index:
            beacons[2:, :2] += rng.normal(0, .1 * scale, (2, 2))
            beacons[2, 1] = max(beacons[2, 1], .1 * scale)
    trajectory = _linear_positions(problem, beacons)
    if index:
        trajectory[:, :2] += rng.normal(0, .12 * scale, (len(trajectory), 2))
    return {"trajectory": trajectory.tolist(), "beacons": beacons.tolist()}


def jacobian_diagnostics(parameters, problem):
    scale = max(float(np.median(np.abs(problem.ranges_m))), 1.)
    spectrum = np.linalg.svd(jacobian(parameters, problem) * scale, compute_uv=False)
    tolerance = RANK_RELATIVE_TOLERANCE * spectrum[0] if len(spectrum) else 0.
    rank = int(np.sum(spectrum > tolerance))
    return {"rank": rank, "parameter_count": problem.parameter_count, "measurement_count": len(problem.ranges_m),
            "singular_values": spectrum.tolist(), "relative_tolerance": RANK_RELATIVE_TOLERANCE,
            "absolute_tolerance": float(tolerance), "parameter_scale_m": scale,
            "scaling": "J of normalized range residuals with respect to theta / parameter_scale_m; all parameters in metres",
            "condition_number": float(spectrum[0] / spectrum[-1]) if rank == problem.parameter_count else None,
            "full_column_rank": rank == problem.parameter_count,
            "interpretation": "Local measurement rank only; full rank does not prove global uniqueness"}


def fit_observations(observations, times_s, *, mode="joint", surveyed_beacons=None,
                     starts=3, seed=19, initial_geometries=None, max_nfev=2000):
    """Fit ranges without truth. Optional initial geometries are explicitly supplied.

    A surveyed map is mandatory only in known_map mode. Every attempted start is
    retained, including exceptions and nonconvergence. Returns per-start records.
    """
    problem = build_problem(observations, times_s, mode=mode, surveyed_beacons=surveyed_beacons)
    if isinstance(starts, bool) or not isinstance(starts, int) or not 1 <= starts <= 20:
        raise ValueError("starts must be an integer from 1 to 20")
    if isinstance(max_nfev, bool) or not isinstance(max_nfev, int) or max_nfev < 1:
        raise ValueError("max_nfev must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    if initial_geometries is not None and len(initial_geometries) != starts:
        raise ValueError("Supply one explicit geometry per start")
    rng = np.random.default_rng(seed)
    outcomes = []
    for index in range(starts):
        initial = copy.deepcopy(initial_geometries[index]) if initial_geometries is not None else _independent_initial(problem, rng, index)
        outcome = {"index": index, "status": "failed", "success": False, "initial": initial, "estimate": None,
                   "solver": {}, "diagnostics": {}}
        begun = time.perf_counter()
        try:
            x0 = problem.pack(initial["trajectory"], initial["beacons"])
            lower, upper = np.full(len(x0), -np.inf), np.full(len(x0), np.inf)
            if mode == "joint":
                lower[-6], lower[-4], lower[-1] = POSITIVE_FLOOR_M, POSITIVE_FLOOR_M, POSITIVE_FLOOR_M
            r0 = residuals(x0, problem)
            result = least_squares(residuals, x0, jac=jacobian, args=(problem,), bounds=(lower, upper),
                                   method="trf", x_scale="jac", ftol=1e-12, xtol=1e-12, gtol=1e-12,
                                   max_nfev=int(max_nfev))
            trajectory, beacons = problem.unpack(result.x)
            outcome.update(status="success" if result.success else "not_converged", success=bool(result.success),
                           estimate={"trajectory": trajectory.tolist(), "beacons": beacons.tolist()})
            outcome["solver"] = {"method": "scipy.optimize.least_squares/trf", "status": int(result.status),
                                 "message": str(result.message), "nfev": int(result.nfev), "njev": int(result.njev) if result.njev is not None else None,
                                 "iterations": None, "iterations_note": "SciPy least_squares exposes evaluations, not iteration count",
                                 "runtime_s": time.perf_counter() - begun, "initial_objective": float(.5 * r0 @ r0),
                                 "final_objective": float(result.cost), "optimality": float(result.optimality),
                                 "active_bounds": result.active_mask.tolist(), "max_nfev": int(max_nfev),
                                 "ftol": 1e-12, "xtol": 1e-12, "gtol": 1e-12, "x_scale": "jac", "loss": "linear",
                                 "positive_floor_m": POSITIVE_FLOOR_M if mode == "joint" else None}
            normalized = residuals(result.x, problem)
            metres = normalized * problem.sigma_m
            outcome["diagnostics"] = {"residuals_m": metres.tolist(), "residuals_normalized": normalized.tolist(),
                                      "range_rmse_m": float(np.sqrt(np.mean(metres ** 2))), "max_abs_residual_m": float(np.max(np.abs(metres))),
                                      "jacobian": jacobian_diagnostics(result.x, problem)}
        except Exception as exc:
            outcome["solver"] = {"status": None, "message": f"{type(exc).__name__}: {exc}", "nfev": None, "njev": None,
                                 "iterations": None, "runtime_s": time.perf_counter() - begun,
                                 "initial_objective": None, "final_objective": None}
        outcomes.append(outcome)
    return outcomes


def _error_summary(trajectory, beacons, truth_trajectory, truth_beacons):
    position = np.linalg.norm(trajectory - truth_trajectory, axis=1)
    map_error = np.linalg.norm(beacons - truth_beacons, axis=1)
    return {"position_errors_m": position.tolist(), "position_rmse_m": float(np.sqrt(np.mean(position ** 2))),
            "position_max_error_m": float(np.max(position)), "beacon_errors_m": map_error.tolist(),
            "map_rmse_m": float(np.sqrt(np.mean(map_error ** 2))), "height_error_m": float(np.mean(beacons[:, 2] - truth_beacons[:, 2]))}


def evaluate_geometry(estimate, truth, mode):
    p, b = np.asarray(estimate["trajectory"]), np.asarray(estimate["beacons"])
    tp, tb = np.asarray(truth["trajectory"]), np.asarray(truth["beacons"])
    raw = _error_summary(p, b, tp, tb)
    if mode == "known_map":
        return {"raw": raw, "aligned": raw.copy(), "alignment": {"applied": False, "scale": 1., "reflection_allowed": False,
                "description": "Known-map estimates remain in the surveyed frame"}, "aligned_geometry": copy.deepcopy(estimate)}
    # Map-only planar proper rigid alignment preserves metric scale and the tag plane.
    source, target = b[:, :2], tb[:, :2]
    source_mean, target_mean = source.mean(axis=0), target.mean(axis=0)
    u, _, vt = np.linalg.svd((source - source_mean).T @ (target - target_mean))
    correction = np.diag([1., np.linalg.det(u @ vt)])
    rotation = u @ correction @ vt
    translation = target_mean - source_mean @ rotation
    ap, ab = p.copy(), b.copy()
    ap[:, :2] = p[:, :2] @ rotation + translation
    ab[:, :2] = b[:, :2] @ rotation + translation
    return {"raw": raw, "aligned": _error_summary(ap, ab, tp, tb),
            "alignment": {"applied": True, "scale": 1., "reflection_allowed": False, "rotation_xy": rotation.tolist(),
                          "translation_xy_m": translation.tolist(), "description": "Map-only least-squares planar proper rigid alignment; no scale, reflection, z translation, or 3D tilt"},
            "aligned_geometry": {"trajectory": ap.tolist(), "beacons": ab.tolist()}}


def solve_experiment(experiment, options=None):
    """Synthetic wrapper: explicit truth-near seeding and separate truth evaluation."""
    supplied = {} if options is None else dict(options)
    unknown = set(supplied) - {"mode", "initialization", "starts", "seed", "max_nfev"}
    if unknown:
        raise ValueError(f"Unsupported solver options: {', '.join(sorted(unknown))}")
    options = {"mode": "joint", "initialization": "independent", "starts": 3, "seed": 19, "max_nfev": 2000, **supplied}
    if isinstance(options["starts"], bool) or not isinstance(options["starts"], int) or not 1 <= options["starts"] <= 20:
        raise ValueError("starts must be an integer from 1 to 20")
    if isinstance(options["seed"], bool) or not isinstance(options["seed"], int) or options["seed"] < 0:
        raise ValueError("seed must be a nonnegative integer")
    if isinstance(options["max_nfev"], bool) or not isinstance(options["max_nfev"], int) or options["max_nfev"] < 1:
        raise ValueError("max_nfev must be a positive integer")
    if options["initialization"] not in ("independent", "truth_near"):
        raise ValueError("initialization must be independent or truth_near")
    inputs, truth = experiment["estimator_input"], experiment["truth"]
    surveyed = truth["beacons"] if options["mode"] == "known_map" else None
    initial = None
    if options["initialization"] == "truth_near":
        problem = build_problem(inputs["observations"], inputs["times_s"], mode=options["mode"], surveyed_beacons=surveyed)
        xtruth = problem.pack(truth["trajectory"], truth["beacons"])
        rng = np.random.default_rng(options["seed"])
        initial = []
        for _ in range(options["starts"]):
            x = xtruth + rng.normal(0, .15, xtruth.shape)
            if problem.mode == "joint":
                x[[-6, -4, -1]] = np.maximum(x[[-6, -4, -1]], .01)
            p, b = problem.unpack(x)
            initial.append({"trajectory": p.tolist(), "beacons": b.tolist()})
    outcomes = fit_observations(inputs["observations"], inputs["times_s"], mode=options["mode"], surveyed_beacons=surveyed,
                                starts=options["starts"], seed=options["seed"], initial_geometries=initial, max_nfev=options["max_nfev"])
    finite = [s for s in outcomes if s["estimate"] is not None and np.isfinite(s["solver"]["final_objective"])]
    preferred = [s for s in finite if s["success"]] or finite
    selected = min(preferred, key=lambda s: s["solver"]["final_objective"])["index"] if preferred else None
    problem = build_problem(inputs["observations"], inputs["times_s"], mode=options["mode"], surveyed_beacons=surveyed)
    truth_rank = jacobian_diagnostics(problem.pack(truth["trajectory"], truth["beacons"]), problem)
    for outcome in finite:
        outcome["diagnostics"]["evaluation"] = evaluate_geometry(outcome["estimate"], truth, options["mode"])
    groups, low_residual_groups, classifications = [], [], []
    for outcome in outcomes:
        evaluation = outcome["diagnostics"].get("evaluation")
        geometry = bool(evaluation and evaluation["raw"]["position_max_error_m"] < 1e-5
                        and max(evaluation["raw"]["beacon_errors_m"]) < 1e-5)
        ranges = bool(evaluation and outcome["diagnostics"]["max_abs_residual_m"] < 1e-7)
        classification = ("failed" if outcome["estimate"] is None else "not_converged" if not outcome["success"]
                          else "geometry_recovered" if geometry else "converged_geometry_inaccurate")
        outcome["diagnostics"].update(geometric_recovery=geometry, range_recovery=ranges,
                                       recovery_classification=classification)
        classifications.append({"index": outcome["index"], "optimizer_converged": outcome["success"],
                                "geometric_recovery": geometry, "range_recovery": ranges,
                                "classification": classification})
    for outcome in finite:
        signature = np.concatenate((np.ravel(outcome["estimate"]["trajectory"]), np.ravel(outcome["estimate"]["beacons"])))
        if not any(np.sqrt(np.mean((signature - ref) ** 2)) < 1e-3 for ref in groups):
            groups.append(signature)
        if outcome["diagnostics"]["range_recovery"] and not any(np.sqrt(np.mean((signature - ref) ** 2)) < 1e-3 for ref in low_residual_groups):
            low_residual_groups.append(signature)
    chosen = outcomes[selected] if selected is not None else None
    diagnostics = {"truth_jacobian": truth_rank, "failure_count": sum(not s["success"] for s in outcomes),
                   "distinct_solution_count": len(groups), "solution_grouping_rms_threshold_m": 1e-3,
                   "distinct_low_residual_solution_count": len(low_residual_groups), "low_residual_max_abs_threshold_m": 1e-7,
                   "solution_grouping": "Raw canonical geometry RMS over trajectory and beacon xyz, all finite starts",
                   "start_recovery_outcomes": classifications, "geometric_recovery_count": sum(s["geometric_recovery"] for s in classifications),
                   "range_recovery_count": sum(s["range_recovery"] for s in classifications),
                   "geometric_recovery": bool(chosen and chosen["diagnostics"]["geometric_recovery"]),
                   "acceptance_geometry_tolerance_m": 1e-5, "acceptance_max_range_residual_m": 1e-7,
                   "weak_condition_threshold": WEAK_CONDITION_THRESHOLD,
                   "surveyed_map_source": "Synthetic truth map explicitly passed as surveyed input" if options["mode"] == "known_map" else None,
                   "ambiguity": "Full Jacobian rank is local only and does not prove global uniqueness. In joint mode, d>0 fixes x direction, beacon 2 y>0 selects the planar reflection, and h>0 selects beacons above the fixed tag plane. These conventions select branches rather than supply new measurements.",
                   "warnings": []}
    if not truth_rank["full_column_rank"]:
        diagnostics["warnings"].append("Truth measurement Jacobian is rank deficient; geometry is locally unidentifiable")
    if chosen and not chosen["diagnostics"]["jacobian"]["full_column_rank"]:
        diagnostics["warnings"].append("Fitted measurement Jacobian is rank deficient")
    if truth_rank["condition_number"] and truth_rank["condition_number"] > WEAK_CONDITION_THRESHOLD:
        diagnostics["warnings"].append("Truth geometry is weakly conditioned (condition number exceeds the disclosed heuristic 1000)")
    if chosen and chosen["diagnostics"]["jacobian"]["condition_number"] and chosen["diagnostics"]["jacobian"]["condition_number"] > WEAK_CONDITION_THRESHOLD:
        diagnostics["warnings"].append("Fitted geometry is weakly conditioned (condition number exceeds the disclosed heuristic 1000)")
    return {"schema_version": "1.0", "experiment": copy.deepcopy(experiment), "options": options,
            "status": chosen["status"] if chosen else "failed", "selected_start": selected, "starts": outcomes,
            "diagnostics": diagnostics, "software_versions": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__}}
