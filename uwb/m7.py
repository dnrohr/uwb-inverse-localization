"""Partial surveyed-world knowledge and conditional local uncertainty.

No-survey calls delegate to M6 unchanged. Survey fitting uses physical metre
coordinates with selected fixed coordinates eliminated, never a canonical gauge.
"""
from __future__ import annotations

import copy
import csv
import io
import json
import time
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from . import m3, m4, m5, m6
from .experiments import _package_versions, _replace_with_retry

SCHEMA_VERSION = "7.0"
EXTRA_KEYS = {"survey", "uncertainty"}


@m3._format_errors
def normalize_survey(survey, beacon_count=None):
    if survey is None:
        return None
    if beacon_count is not None and (isinstance(beacon_count, bool) or not isinstance(beacon_count, int) or not 3 <= beacon_count <= 8):
        raise ValueError("Survey beacon_count must be an integer from 3 through 8")
    if not isinstance(survey, dict) or set(survey) - {"frame", "units", "fixed", "priors"}:
        raise ValueError("Survey requires frame, units, fixed and priors; unsupported survey fields")
    if survey.get("frame") != "world" or survey.get("units") != "m":
        raise ValueError("Survey requires explicit frame='world', units='m'")
    result = {"frame": "world", "units": "m", "fixed": [], "priors": []}
    occupied = set()
    for kind in ("fixed", "priors"):
        rows = survey.get(kind, [])
        if not isinstance(rows, list) or len(rows) > 24:
            raise ValueError("Survey rows must be a list, at most 24")
        for row in rows:
            required = {"beacon_id", "mask", "mean_m"} | ({"covariance_m2"} if kind == "priors" else set())
            if not isinstance(row, dict) or set(row) != required:
                raise ValueError("Survey row fields must be exactly " + ", ".join(sorted(required)))
            b = row["beacon_id"]
            if isinstance(b, bool) or not isinstance(b, int) or not 0 <= b < (beacon_count or 8):
                raise ValueError("Invalid survey beacon_id")
            mask = row["mask"]
            if not isinstance(mask, list) or len(mask) != 3 or any(type(v) is not bool for v in mask) or not any(mask):
                raise ValueError("Survey mask requires three booleans, at least one selected axis")
            mean = m3._array(row["mean_m"], (3,), "Survey mean_m")
            axes = np.flatnonzero(mask)
            for axis in axes:
                key = (b, int(axis))
                if key in occupied:
                    raise ValueError("Survey fixed/prior coordinate overlap or duplicate; combine coupled prior axes in one block")
                occupied.add(key)
            normalized = {"beacon_id": b, "mask": list(mask), "mean_m": mean.tolist()}
            if kind == "priors":
                covariance = m3._array(row["covariance_m2"], (len(axes), len(axes)), "Survey covariance_m2")
                if not np.allclose(covariance, covariance.T, atol=1e-14, rtol=1e-12):
                    raise ValueError("Survey covariance must be symmetric")
                covariance = .5 * covariance + .5 * covariance.T
                try:
                    np.linalg.cholesky(covariance)
                except np.linalg.LinAlgError as exc:
                    raise ValueError("Survey covariance must be positive definite; exact coordinates use fixed") from exc
                normalized["covariance_m2"] = covariance.tolist()
            result[kind].append(normalized)
    if not occupied:
        raise ValueError("An explicit survey requires at least one fixed or uncertain coordinate; omit survey for legacy behavior")
    return result


def normalize_uncertainty(value=None):
    defaults = {"enabled": True, "range_model": "independent_gaussian_known_sigma", "rank_rtol": 1e-8,
                "bound_tolerance_m": 1e-7}
    if value is not None and (not isinstance(value, dict) or set(value) - set(defaults)):
        raise ValueError("Unsupported uncertainty assumptions")
    result = {**defaults, **(value or {})}
    if type(result["enabled"]) is not bool or result["range_model"] != defaults["range_model"]:
        raise ValueError("Uncertainty supports explicitly assumed independent Gaussian ranges with known saved sigma")
    result["rank_rtol"] = m3._number(result["rank_rtol"], "rank_rtol", 1e-12, 1e-4)
    result["bound_tolerance_m"] = m3._number(result["bound_tolerance_m"], "bound_tolerance_m", 1e-12, 1e-3)
    return result


@m3._format_errors
def validate_options(options=None):
    supplied = copy.deepcopy(dict(options or {}))
    survey = normalize_survey(supplied.pop("survey", None))
    uncertainty = normalize_uncertainty(supplied.pop("uncertainty", None))
    opts = m6.validate_options(supplied)
    if survey is None:
        # Preserve the exact normalized legacy options when the extension is absent.
        return opts
    if opts["mode"] != "joint":
        raise ValueError("Partial survey uses joint mode; known_map already fixes the complete declared map")
    if opts["beacon_height_model"] != "independent":
        raise ValueError("Survey currently requires independent beacon heights; shared beacon-plane coupling is unsupported")
    if opts["height_parameterization"] != "h":
        raise ValueError("Survey uses physical metre coordinates (h); q is unsupported")
    if opts["initialization"] == "algebraic":
        raise ValueError("Algebraic initialization does not support partial surveyed-world constraints")
    if opts["tag_height_model"] != "fixed" and opts["below_beacons"]:
        raise ValueError("Non-fixed world tag height below partially surveyed beacons requires unsupported coupled inequalities")
    return {**opts, "survey": survey, "uncertainty": uncertainty}


def base_options(options):
    return m6.validate_options({k: v for k, v in options.items() if k not in EXTRA_KEYS})


def build_problem(observations, times_s, *, beacon_count=None, display_times_s=None, surveyed_beacons=None, **options):
    opts = validate_options(options)
    if "survey" not in opts:
        return m6.build_problem(observations, times_s, beacon_count=beacon_count, display_times_s=display_times_s,
                                surveyed_beacons=surveyed_beacons, **opts)
    if surveyed_beacons is not None:
        raise ValueError("Partial survey must be explicit; a complete hidden map cannot enter joint fitting")
    if isinstance(beacon_count, bool) or not isinstance(beacon_count, int) or not 3 <= beacon_count <= 8:
        raise ValueError("Partial survey requires explicit beacon_count from 3 through 8; unobserved beacons cannot be inferred")
    survey = normalize_survey(opts["survey"], beacon_count)
    # Known-map construction supplies validated times/interpolation and the world
    # tag-height basis only. Its placeholder map is replaced before any evaluation.
    physical_opts = m5.base_options(m6.base_options(base_options(opts)))
    scaffold = {**physical_opts, "mode": "known_map", "below_beacons": False}
    problem = m4.build_problem(observations, times_s, beacon_count=beacon_count, display_times_s=display_times_s,
                               surveyed_beacons=np.zeros((beacon_count, 3)).tolist(), **scaffold)
    problem.options = physical_opts
    count = problem.parameter_count
    fixed = {(r["beacon_id"], a): r["mean_m"][a] for r in survey["fixed"] for a in range(3) if r["mask"][a]}
    free = [(b, a) for b in range(beacon_count) for a in range(3) if (b, a) not in fixed]
    n = count + len(free)
    problem.tag_basis = np.pad(problem.tag_basis, ((0, 0), (0, 0), (0, len(free))))
    problem.beacon_basis = np.zeros((beacon_count, 3, n))
    problem.beacon_offset = np.zeros((beacon_count, 3))
    for (b, a), v in fixed.items():
        problem.beacon_offset[b, a] = v
    for j, (b, a) in enumerate(free):
        problem.beacon_basis[b, a, count + j] = 1.
    lower = np.full(len(free), -np.inf)
    if opts["below_beacons"]:  # only fixed tag world-z is supported here
        minimum = opts["fixed_tag_z_m"] + m4.FLOOR
        if any(a == 2 and v < minimum for (b, a), v in fixed.items()):
            raise ValueError("Fixed surveyed beacon violates below-beacons constraint")
        lower = np.asarray([minimum if a == 2 else -np.inf for b, a in free])
    problem.lower = np.r_[problem.lower, lower]
    problem.upper = np.r_[problem.upper, np.full(len(free), np.inf)]
    problem.surveyed_beacons = None
    problem.survey = survey
    problem.robust_options = opts
    problem.original_cycle_count = len(times_s)
    labels = []
    for j in range(count):
        support = np.argwhere(problem.tag_basis[:, :, j])
        labels.append({"kind": "tag", "knots": support[:, 0].tolist(), "axis": "xyz"[int(support[0, 1])], "units": "m"})
    labels.extend({"kind": "beacon", "beacon_id": b, "axis": "xyz"[a], "units": "m"} for b, a in free)
    problem.parameter_labels = labels
    matrices, offsets = [], []
    for row in survey["priors"]:
        b = row["beacon_id"]; axes = np.flatnonzero(row["mask"])
        chol = np.linalg.cholesky(np.asarray(row["covariance_m2"]))
        matrices.append(np.linalg.solve(chol, problem.beacon_basis[b, axes]))
        offsets.append(np.linalg.solve(chol, problem.beacon_offset[b, axes] - np.asarray(row["mean_m"])[axes]))
    problem.survey_matrix = np.vstack(matrices) if matrices else np.zeros((0, n))
    problem.survey_offset = np.concatenate(offsets) if offsets else np.zeros(0)
    return problem


def survey_residuals(x, problem):
    return problem.survey_matrix @ x + problem.survey_offset


def residuals(x, problem, mask=None):
    if not hasattr(problem, "survey"):
        return m6.residuals(x, problem, mask)
    values, _ = m6.range_transform(m4.measurement_residuals(x, problem), problem.robust_options["loss"], problem.robust_options["loss_scale_sigma"])
    if mask is not None:
        values *= mask
    motion, height = m4.prior_components(x, problem)
    return np.r_[values, motion, height, survey_residuals(x, problem)]


def jacobian(x, problem, mask=None):
    if not hasattr(problem, "survey"):
        return m6.jacobian(x, problem, mask)
    _, chain = m6.range_transform(m4.measurement_residuals(x, problem), problem.robust_options["loss"], problem.robust_options["loss_scale_sigma"])
    if mask is not None:
        chain *= mask
    matrix = m4.jacobian(x, problem).copy()
    matrix[:len(chain)] *= chain[:, None]
    return np.vstack((matrix, problem.survey_matrix))


def information(matrix, n, rtol=1e-8):
    # All columns are physical metres; no hidden h/q or gauge scaling.
    singular = np.linalg.svd(matrix, compute_uv=False)
    cutoff = float(singular[0] * rtol) if len(singular) else 0.
    rank = int(np.count_nonzero(singular > cutoff))
    return {"rank": rank, "parameter_count": n, "row_count": len(matrix), "full_column_rank": rank == n,
            "singular_values_per_m": singular.tolist(), "relative_tolerance": rtol, "absolute_tolerance_per_m": cutoff,
            "condition_number": float(singular[0] / singular[-1]) if rank == n and n else None}


def conditional_uncertainty(x, problem, *, converged=True, mask=None):
    assumptions = problem.robust_options["uncertainty"]
    opts = problem.robust_options; n = problem.parameter_count; nr = len(problem.ranges_m)
    original = m4.measurement_jacobian(x, problem)
    r = m4.measurement_residuals(x, problem)
    weights, curvature = m6.loss_statistics(r, opts["loss"], opts["loss_scale_sigma"])
    if mask is not None:
        weights = np.asarray(mask, float); curvature = weights.copy()
    weighted = original * np.sqrt(weights)[:, None]
    priors = m4.jacobian(x, problem)[nr:]
    motion, height = m4.prior_components(x, problem)
    motion_j, height_j = priors[:len(motion)], priors[len(motion):]
    matrices = {"original_measurement": original, "retained_weighted_measurement": weighted,
                "survey": problem.survey_matrix, "motion_prior": motion_j, "height_prior": height_j,
                "augmented": np.vstack((weighted, problem.survey_matrix, priors)),
                "positive_part_robust_curvature": original * np.sqrt(np.maximum(curvature, 0.))[:, None]}
    infos = {k: information(v, n, assumptions["rank_rtol"]) for k, v in matrices.items()}
    result = {"available": False, "method": "local_linear_gaussian_conditional_known_sigma",
              "coordinate_frame": "world", "parameter_units": "m", "covariance_units": "m2",
              "parameter_labels": copy.deepcopy(problem.parameter_labels), "linearization_parameters_m": np.asarray(x).tolist(),
              "assumptions": copy.deepcopy(assumptions), "information": infos, "signed_scalar_robust_curvature": curvature.tolist(),
              "fixed_coordinate_count": sum(sum(r["mask"]) for r in problem.survey["fixed"]),
              "fixed_coordinates_are": "Exact declared constraints eliminated from the free vector, not extra noisy rows",
              "survey_model": "Independent Gaussian blocks across rows; covariance couples selected axes within a row",
              "prior_model": "Independent Gaussian quadratic motion/height assumptions, independent of ranges and survey",
              "jacobian_definition": "d[(predicted range - saved range)/saved sigma]/d[physical metre coordinates]; survey whitened by Cholesky inverse",
              "interpretation": "Conditional local linear Gaussian approximation with known sigma, no residual variance rescaling. With priors this is a local Gaussian posterior approximation, not unconditional frequentist coverage.",
              "limitations": ["Full local rank is not global uniqueness; undiscovered or reflected geometries are excluded.",
                              "No coverage calibration is claimed; known-sigma Gaussian assumptions can be misspecified.",
                              "Correlation, quantization, contamination, timing/height mismatch and fixed survey bias can invalidate intervals.",
                              "Weighted information and positive robust curvature are conditioning diagnostics, not calibrated covariance."],
              "covariance_m2": None, "standard_deviation_m": None, "marginal_95_half_width_m": None}
    reasons = []
    if not assumptions["enabled"]: reasons.append("Uncertainty disabled")
    if not converged: reasons.append("Optimizer did not converge")
    if opts["loss"] != "gaussian" or mask is not None: reasons.append("Robust/rejection selection has no calibrated Gaussian covariance here")
    if getattr(problem, "canonical_gauge", False): reasons.append("Legacy joint canonical gauge fixes unobserved rigid coordinates; no finite world-coordinate covariance is claimed")
    reasons.extend(getattr(problem, "uncertainty_model_limits", []))
    if not infos["augmented"]["full_column_rank"]: reasons.append("Augmented free-coordinate Jacobian is rank deficient; remaining gauge/nullspace is not assigned finite covariance")
    tol = assumptions["bound_tolerance_m"]
    if np.any(x - problem.lower <= tol) or np.any(problem.upper - x <= tol): reasons.append("An active or near-active bound invalidates unconstrained Gaussian covariance")
    p, b = problem.unpack(x)
    if np.any(np.linalg.norm(problem.weights @ p - b[problem.beacon_ids], axis=1) <= 1e-12): reasons.append("Zero predicted range has nondifferentiable distance")
    if reasons:
        result["unavailable_reasons"] = reasons
        return result
    _, singular, vt = np.linalg.svd(matrices["augmented"], full_matrices=False)
    inverse = vt.T / singular
    covariance = inverse @ inverse.T
    deviation = np.sqrt(np.maximum(np.diag(covariance), 0.))
    def propagate(basis):
        variance = np.einsum("...i,ij,...j->...", basis, covariance, basis)
        return np.sqrt(np.maximum(variance, 0.)).tolist()
    result.update(available=True, unavailable_reasons=[], covariance_m2=covariance.tolist(), standard_deviation_m=deviation.tolist(),
                  marginal_95_half_width_m=(1.959963984540054 * deviation).tolist(),
                  knot_standard_deviation_m=propagate(problem.tag_basis), beacon_standard_deviation_m=propagate(problem.beacon_basis),
                  ping_standard_deviation_m=propagate(np.einsum("mk,kcn->mcn", problem.weights, problem.tag_basis)),
                  interval_definition="Two-sided marginal 95% normal approximation; fixed geometry components have conditional zero variance by declaration")
    return result


def _diagnostics(x, problem, converged, mask=None):
    r = m4.measurement_residuals(x, problem); motion, height = m4.prior_components(x, problem)
    survey = survey_residuals(x, problem)
    transformed, _ = m6.range_transform(r, problem.robust_options["loss"], problem.robust_options["loss_scale_sigma"])
    weights, _ = m6.loss_statistics(r, problem.robust_options["loss"], problem.robust_options["loss_scale_sigma"])
    if mask is not None:
        transformed *= mask; weights = np.asarray(mask, float)
    measurements = .5 * float(transformed @ transformed)
    prior = .5 * float(motion @ motion + height @ height)
    surveyed = .5 * float(survey @ survey)
    flagged = weights == 0. if problem.robust_options["loss"] == "hard_rejection" else weights < problem.robust_options["weight_decision_threshold"]
    decisions = [{"observation_index": i, "epoch": int(problem.epochs[i]), "beacon_id": int(problem.beacon_ids[i]),
                  "assumed_time_s": float(problem.assumed_times_s[i]), "residual_m": float(r[i] * problem.sigma_m[i]),
                  "residual_sigma": float(r[i]), "weight": float(weights[i]), "flagged": bool(flagged[i]), "rejected": bool(weights[i] == 0.)}
                 for i in range(len(r))]
    def coverage_rows(ids, count):
        return [{"id": i, "original_count": int(np.sum(ids == i)), "retained_count": int(np.sum((ids == i) & (weights > 0))),
                 "flagged_count": int(np.sum((ids == i) & flagged)), "effective_weight_sum": float(np.sum(weights[ids == i]))} for i in range(count)]
    coverage = {"original_count": len(r), "retained_count": int(np.count_nonzero(weights)), "flagged_count": int(np.count_nonzero(flagged)),
                "effective_weight_sum": float(np.sum(weights)), "by_beacon": coverage_rows(problem.beacon_ids, problem.beacon_count),
                "by_epoch": coverage_rows(problem.epochs, problem.original_cycle_count),
                "definition": "Retained means positive final influence weight; missing/dropout observations are outside estimator counts"}
    return {"measurement_objective": measurements, "motion_prior_objective": .5 * float(motion @ motion),
            "height_prior_objective": .5 * float(height @ height), "prior_objective": prior, "survey_objective": surveyed,
            "total_objective": measurements + prior + surveyed, "residuals_m": (r * problem.sigma_m).tolist(),
            "gaussian_all_measurement_objective": .5 * float(r @ r), "observation_decisions": decisions, "coverage": coverage,
            "residuals_normalized": r.tolist(), "weights": weights.tolist(), "survey_residuals_whitened": survey.tolist(),
            "rms_residual_m": float(np.sqrt(np.mean((r * problem.sigma_m) ** 2))) if len(r) else None,
            "range_rmse_m": float(np.sqrt(np.mean((r * problem.sigma_m) ** 2))) if len(r) else None,
            "max_abs_residual_m": float(np.max(np.abs(r * problem.sigma_m))) if len(r) else None,
            "jacobian": information(m4.measurement_jacobian(x, problem), problem.parameter_count),
            "uncertainty": conditional_uncertainty(x, problem, converged=converged, mask=mask)}


def _optimize(problem, x0, opts, mask=None):
    original = problem.robust_options
    problem.robust_options = opts
    try:
        kw = {"x_scale": "jac", "ftol": 1e-12, "xtol": 1e-12, "gtol": 1e-12, "max_nfev": opts["max_nfev"]}
        if opts["solver"] == "lm":
            retained = len(problem.ranges_m) if mask is None else int(np.count_nonzero(mask))
            if retained + len(residuals(x0, problem)) - len(problem.ranges_m) < problem.parameter_count:
                raise ValueError("LM requires nonzero retained/prior/survey residual count >= free parameter count")
            transform = m5.BoundTransform(problem.lower, problem.upper)
            def fun(u): return residuals(transform.decode(u)[0], problem, mask)
            def jac(u):
                x, chain = transform.decode(u)
                return jacobian(x, problem, mask) * chain
            result = least_squares(fun, transform.encode(x0), jac=jac, method="lm", **kw)
            return result, transform.decode(result.x)[0]
        result = least_squares(lambda x: residuals(x, problem, mask), x0, jac=lambda x: jacobian(x, problem, mask),
                               bounds=(problem.lower, problem.upper), method="trf", **kw)
        return result, result.x
    finally:
        problem.robust_options = original


def _independent_initial(problem, rng):
    # All proposal information is declared survey plus measured ranges, never
    # synthetic geometry. Unspecified coordinates get a reproducible broad basin.
    size = max(float(np.median(np.abs(problem.ranges_m))) if len(problem.ranges_m) else 1., 1.)
    x = rng.normal(0., size / 2., problem.parameter_count)
    declared = [[] for _ in range(3)]
    for row in problem.survey["fixed"] + problem.survey["priors"]:
        for a in np.flatnonzero(row["mask"]): declared[a].append(row["mean_m"][a])
    center = [float(np.mean(values)) if values else 0. for values in declared]
    for j, label in enumerate(problem.parameter_labels): x[j] += center["xyz".index(label["axis"])]
    for row in problem.survey["priors"]:
        b = row["beacon_id"]
        for a in np.flatnonzero(row["mask"]):
            indices = np.flatnonzero(problem.beacon_basis[b, a])
            x[indices] = row["mean_m"][a]
    x = np.maximum(x, np.where(np.isfinite(problem.lower), problem.lower + .1, problem.lower))
    x = np.minimum(x, np.where(np.isfinite(problem.upper), problem.upper - .1, problem.upper))
    return problem.geometry(x)


def fit_observations(observations, times_s, *, beacon_count=None, display_times_s=None, surveyed_beacons=None, initial_geometries=None, **options):
    opts = validate_options(options)
    if "survey" not in opts:
        return m6.fit_observations(observations, times_s, beacon_count=beacon_count, display_times_s=display_times_s,
                                  surveyed_beacons=surveyed_beacons, initial_geometries=initial_geometries, **opts)
    inputs = [{k: o[k] for k in ("epoch", "beacon_id", "assumed_time_s", "range_m", "sigma_m")} for o in observations]
    problem = build_problem(inputs, times_s, beacon_count=beacon_count, display_times_s=display_times_s, surveyed_beacons=surveyed_beacons, **opts)
    if initial_geometries is not None and len(initial_geometries) != opts["starts"]:
        raise ValueError("Supply one world-frame physical initial geometry per requested start")
    if opts["initialization"] == "truth_near" and initial_geometries is None:
        raise ValueError("Truth-near initialization requires explicitly supplied diagnostic geometry")
    rng = np.random.default_rng(opts["seed"]); outcomes = []
    for index in range(opts["starts"]):
        begun = time.perf_counter()
        start = {"index": index, "status": "failed", "success": False, "initial": None, "estimate": None, "diagnostics": {}, "solver": {}}
        try:
            initial = copy.deepcopy(initial_geometries[index]) if initial_geometries is not None else _independent_initial(problem, rng)
            start["initial"] = initial
            x0 = problem.pack(initial["knot_trajectory"], initial["beacons"])
            if np.any(x0 < problem.lower) or np.any(x0 > problem.upper): raise ValueError("Physical start violates bounds")
            if not len(problem.ranges_m): raise ValueError("No observations; survey/priors alone are not fitted")
            second = x0; mask = None
            if opts["loss"] == "hard_rejection":
                pilot, second = _optimize(problem, x0, {**opts, "loss": "gaussian"})
                pilot_r = m4.measurement_residuals(second, problem)
                mask = np.abs(pilot_r) <= opts["rejection_threshold_sigma"]
                start["diagnostics"]["rejection_pilot"] = {"parameters": second.tolist(), "geometry": problem.geometry(second),
                    "residuals_normalized": pilot_r.tolist(), "retained_mask": mask.tolist(), "success": bool(pilot.success),
                    "message": str(pilot.message), "nfev": int(pilot.nfev)}
                if not np.any(mask): raise ValueError("Hard rejection retained no range rows")
            result, x = _optimize(problem, second, opts, mask)
            start.update(status="success" if result.success else "not_converged", success=bool(result.success), estimate=problem.geometry(x))
            start["diagnostics"].update(_diagnostics(x, problem, bool(result.success), mask))
            start["solver"] = {"status": int(result.status), "message": str(result.message), "nfev": int(result.nfev),
                "njev": int(result.njev) if result.njev is not None else None, "initial_parameters": x0.tolist(), "final_parameters": x.tolist(),
                "initial_objective": float(.5 * np.sum(residuals(x0, problem, mask) ** 2)),
                "second_stage_initial_objective": float(.5 * np.sum(residuals(second, problem, mask) ** 2)),
                "final_objective": float(result.cost), "active_bounds": result.active_mask.tolist(), "optimality": float(result.optimality)}
        except Exception as exc:
            start.update(status="failed", success=False, estimate=None)
            start["solver"].update(status=None, message=f"{type(exc).__name__}: {exc}", nfev=None, njev=None,
                                    initial_objective=None, final_objective=None)
        start["solver"]["runtime_s"] = time.perf_counter() - begun
        outcomes.append(start)
    return outcomes


def _problem(exp, opts):
    data = exp["estimator_input"]
    problem = build_problem(data["observations"], data["times_s"], beacon_count=exp["config"]["beacon_layout"]["count"],
                            display_times_s=exp["truth"]["times_s"], **opts)
    problem.uncertainty_model_limits = _source_model_limits(exp, opts)
    return problem


def _source_model_limits(exp, opts=None):
    """Declared generation metadata only, never per-observation labels/truth."""
    config = exp["config"]; contamination = config.get("contamination", {})
    nlos = contamination.get("nlos", {})
    limits = []
    if (contamination.get("correlated_noise_std_m", 0.) or contamination.get("quantization_m", 0.) or
            any(contamination.get("offsets_m", [])) or nlos.get("prevalence", 0.)):
        limits.append("Declared contamination/correlation/quantization is outside the assumed independent Gaussian range model")
    if not np.allclose(config.get("noise_std_m"), config.get("assumed_std_m"), rtol=1e-12, atol=1e-15):
        limits.append("Declared generated range noise differs from the assumed known sigma model")
    acquisition = config.get("acquisition", {})
    if acquisition.get("timestamp_offset_s", 0.) or acquisition.get("timestamp_jitter_s", 0.):
        limits.append("Declared assumed timestamp error is outside the conditional range-noise model")
    if acquisition.get("spacing_s", 0.) or acquisition.get("jitter_s", 0.) or (opts or {}).get("knot_spacing_s", 0.):
        limits.append("Asynchronous/coarser-knot source can have interpolation or grouped-timing mismatch; covariance calibration is unsupported here")
    if opts is not None:
        height = config.get("truth_height", {})
        if opts["tag_height_model"] == "fixed" and (height.get("type") != "planar" or height.get("offset_m") != opts["fixed_tag_z_m"]):
            limits.append("Declared source tag-height model differs from the fixed fitted world height")
        elif opts["tag_height_model"] == "shared" and height.get("type") != "planar":
            limits.append("Declared source nonplanar height differs from the shared fitted world height")
    return limits


def summarize_uncertainty(run, start_index=None, assumptions=None):
    """Strict offline local summary for a saved M6/M7 outcome; never fit.

    M6 known-map native h/q coordinates are first converted to physical metres.
    Legacy joint gauge coordinates remain conditioning diagnostics only.
    """
    if run.get("schema_version") == SCHEMA_VERSION:
        validate_run(run); opts = copy.deepcopy(run["options"])
        if assumptions is not None: opts["uncertainty"] = normalize_uncertainty(assumptions)
        problem = _problem(run["experiment"], opts)
        legacy = None
    elif run.get("schema_version") == m6.SCHEMA_VERSION:
        m6.validate_run(run); opts = copy.deepcopy(run["options"])
        legacy = m6._problem(run["experiment"], opts)
        problem = copy.deepcopy(legacy.physical)
        problem.robust_options = {**opts, "uncertainty": normalize_uncertainty(assumptions)}
        problem.canonical_gauge = opts["mode"] != "known_map"
        problem.uncertainty_model_limits = _source_model_limits(run["experiment"], opts)
        problem.survey = {"frame": "world", "units": "m", "fixed": [], "priors": []}
        if opts["mode"] == "known_map":
            problem.survey["fixed"] = [{"beacon_id": b, "mask": [True] * 3, "mean_m": xyz.tolist()} for b, xyz in enumerate(problem.surveyed_beacons)]
        problem.survey_matrix = np.zeros((0, problem.parameter_count)); problem.survey_offset = np.zeros(0)
        if legacy.height_index is not None:
            j = legacy.height_index
            if legacy.height_sign < 0:
                problem.upper[j] = min(problem.upper[j], legacy.height_origin - m4.FLOOR)
            else:
                problem.lower[j] = max(problem.lower[j], legacy.height_origin + m4.FLOOR)
        problem.parameter_labels = []
        for j in range(problem.parameter_count):
            tag = np.argwhere(problem.tag_basis[:, :, j]); beacon = np.argwhere(problem.beacon_basis[:, :, j])
            problem.parameter_labels.append({"kind": "legacy_physical", "tag_support": tag.tolist(), "beacon_support": beacon.tolist(), "units": "m"})
    else:
        raise ValueError("Conditional uncertainty supports saved M6 and M7 runs")
    index = run.get("selected_start") if start_index is None else start_index
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(run["starts"]):
        return {"available": False, "unavailable_reasons": ["No selected finite attempt"], "covariance_m2": None}
    start = run["starts"][index]
    if start["estimate"] is None:
        return {"available": False, "unavailable_reasons": ["Attempt failed without a finite geometry"], "covariance_m2": None}
    x = np.asarray(start["solver"]["final_parameters"])
    if legacy is not None: x = legacy.physical_parameters(x)
    pilot = start["diagnostics"].get("rejection_pilot")
    mask = np.asarray(pilot["retained_mask"], dtype=bool) if pilot else None
    return conditional_uncertainty(x, problem, converged=start["success"], mask=mask)


def make_initial_geometries(exp, options=None):
    opts = validate_options(options)
    if "survey" not in opts: return m6.make_initial_geometries(exp, opts)
    m6.validate_experiment(exp); problem = _problem(exp, opts); rng = np.random.default_rng(opts["seed"])
    if opts["initialization"] == "truth_near":
        # Explicit oracle policy only. Fixed coordinates stay fixed if truth and
        # survey disagree; this is a declared model projection, not hidden truth.
        p = m4.truth_positions(exp["config"], problem.times_s)
        base = problem.pack(p, exp["truth"]["beacons"], project=True)
        output = []
        for _ in range(opts["starts"]):
            x = base + rng.normal(0., opts["initialization_error_m"], len(base))
            x = np.maximum(x, np.where(np.isfinite(problem.lower), problem.lower + m4.FLOOR, problem.lower))
            x = np.minimum(x, np.where(np.isfinite(problem.upper), problem.upper - m4.FLOOR, problem.upper))
            output.append(problem.geometry(x))
        return output
    return [_independent_initial(problem, rng) for _ in range(opts["starts"])]


def _run_diagnostics(opts, starts):
    return {"gauge": {"coordinate_frame": "world", "canonical_constraints": False,
                      "rule": "Only declared fixed coordinates and selected height model are eliminated; remaining rigid freedoms remain in free coordinates and rank",
                      "remaining_reflections": "Local rank/intervals do not exclude alternative reflected solutions"},
            "survey": copy.deepcopy(opts["survey"]), "initialization_source": opts["initialization"],
            "initialization_truth_used": opts["initialization"] == "truth_near",
            "numerical_contract": {"method": "scipy.optimize.least_squares/" + opts["solver"],
                "ftol": 1e-12, "xtol": 1e-12, "gtol": 1e-12, "x_scale": "jac", "scipy_loss": "linear",
                "derivatives": "Analytic physical metre geometry, range-loss transform and optional strict-interior LM chain rule",
                "range_residual": "(predicted range - saved range)/saved sigma; actual and delivery times excluded",
                "survey_residual": "Cholesky inverse times selected world beacon-minus-survey mean; independent blocks",
                "bounds": "TRF physical box constraints" if opts["solver"] == "trf" else "Strict-interior M5 exponential transform; no clipping",
                "minimum_beacon_above_fixed_tag_m": m4.FLOOR if opts["below_beacons"] else None},
            "failure_count": sum(not s["success"] for s in starts),
            "selection_policy": "Prefer converged finite attempts then minimum declared objective; hard-rejection masks can differ so objectives are not common-data quality scores"}


def evaluate_geometry(estimate, truth, options=None):
    """Compare declared world coordinates directly; never fit a truth alignment."""
    p = np.asarray(estimate["trajectory"], dtype=float).reshape((-1, 3))
    b = np.asarray(estimate["beacons"], dtype=float).reshape((-1, 3))
    tp = m3._array(truth["trajectory"], p.shape, "World truth trajectory")
    tb = m3._array(truth["beacons"], b.shape, "World truth beacons")
    if not len(p): raise ValueError("World evaluation needs at least one trajectory position")
    errors = m4._error(p, b, tp, tb)
    return {"raw": errors, "aligned": copy.deepcopy(errors),
            "alignment": {"applied": False, "scale": 1., "reflection_allowed": False,
                          "description": "Declared partial-survey world frame retained; no fitted translation, rotation, scale or reflection"},
            "aligned_geometry": {"trajectory": p.tolist(), "beacons": b.tolist()}, "truth_canonical_transform": None}


def _evaluation_diagnostics(exp, start):
    if start["estimate"] is None: return {}
    estimate = start["estimate"]; truth = exp["truth"]
    evaluation = evaluate_geometry(estimate, truth)
    result = {"evaluation": evaluation}
    if truth["ping_positions"]:
        result["ping_evaluation"] = evaluate_geometry({"trajectory": estimate["ping_trajectory"], "beacons": estimate["beacons"]},
            {"trajectory": truth["ping_positions"], "beacons": truth["beacons"]})
    records = exp["contamination_reference"]["records"]
    retained = [r for r in records if r["retained_index"] is not None]
    decisions = copy.deepcopy(start["diagnostics"]["observation_decisions"])
    for decision, source in zip(decisions, retained): decision["source_index"] = source["source_index"]
    result["observation_decisions"] = decisions
    result["rejection_evaluation"] = m6.rejection_evaluation(decisions, records)
    result["geometric_recovery"] = bool(evaluation["raw"]["position_max_error_m"] < 1e-5 and max(evaluation["raw"]["beacon_errors_m"]) < 1e-5)
    result["range_recovery"] = bool(start["diagnostics"]["max_abs_residual_m"] < 1e-7)
    result["recovery_classification"] = "not_converged" if not start["success"] else "geometry_recovered" if result["geometric_recovery"] else "converged_geometry_inaccurate"
    return result


def solve_experiment(exp, options=None, initial_geometries=None):
    opts = validate_options(options)
    if "survey" not in opts:
        return m6.solve_experiment(exp, opts, initial_geometries)
    m6.validate_experiment(exp)
    if initial_geometries is None:
        initial_geometries = make_initial_geometries(exp, opts)
    data = exp["estimator_input"]
    starts = fit_observations(data["observations"], data["times_s"], beacon_count=exp["config"]["beacon_layout"]["count"],
        display_times_s=exp["truth"]["times_s"], initial_geometries=initial_geometries, **opts)
    problem = _problem(exp, opts)
    for start in starts:
        if start["estimate"] is not None:
            pilot = start["diagnostics"].get("rejection_pilot")
            mask = np.asarray(pilot["retained_mask"], bool) if pilot else None
            start["diagnostics"]["uncertainty"] = conditional_uncertainty(np.asarray(start["solver"]["final_parameters"]), problem,
                                                                         converged=start["success"], mask=mask)
            start["diagnostics"].update(_evaluation_diagnostics(exp, start))
    finite = [s for s in starts if s["estimate"] is not None]; preferred = [s for s in finite if s["success"]] or finite
    chosen = min(preferred, key=lambda s: s["solver"]["final_objective"]) if preferred else None
    run = {"schema_version": SCHEMA_VERSION, "experiment": copy.deepcopy(exp), "options": opts, "starts": starts,
           "selected_start": chosen["index"] if chosen else None, "status": chosen["status"] if chosen else "failed",
           "diagnostics": _run_diagnostics(opts, starts), "software_versions": _package_versions()}
    validate_run(run)
    return run


@m3._format_errors
def validate_run(run):
    if run.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("M7 survey run requires schema7.0")
    json.dumps(run, allow_nan=False)
    m6.validate_experiment(run["experiment"])
    opts = validate_options(run["options"])
    if "survey" not in opts or opts != run["options"]: raise ValueError("M7 requires normalized explicit survey options")
    if run["status"] not in ("pending", "running", "success", "not_converged", "failed", "interrupted"):
        raise ValueError("Invalid run status")
    if not isinstance(run["starts"], list): raise ValueError("starts must be a list")
    # Even empty queued/interrupted envelopes must contain a physically valid
    # request. An early lifecycle return must not bypass survey-count/bounds.
    problem = _problem(run["experiment"], opts)
    if not run["starts"] and run["status"] in ("pending", "running", "failed", "interrupted"):
        if run["selected_start"] is not None: raise ValueError("Empty request cannot select an attempt")
        if run["status"] in ("failed", "interrupted") and not isinstance(run.get("error"), str):
            raise ValueError("Failed/interrupted empty request requires error")
        return run
    if len(run["starts"]) != opts["starts"]: raise ValueError("All requested attempts must be retained")
    for i, start in enumerate(run["starts"]):
        if start["index"] != i or type(start["success"]) is not bool: raise ValueError("Invalid attempt index/success")
        solver = start["solver"]
        if not isinstance(solver.get("message"), str) or not solver["message"]: raise ValueError("Attempt requires inspectable solver message")
        m3._number(solver["runtime_s"], "runtime_s", 0., 1e12)
        if start["estimate"] is None:
            if start["success"] or start["status"] != "failed" or solver.get("final_objective") is not None:
                raise ValueError("Failed attempt cannot contain a finite outcome")
            continue
        if start["status"] != ("success" if start["success"] else "not_converged"): raise ValueError("Attempt status mismatch")
        x = m3._array(solver["final_parameters"], (problem.parameter_count,), "Final parameters")
        if np.any(x < problem.lower) or np.any(x > problem.upper): raise ValueError("Final geometry violates bounds")
        if opts["solver"] == "lm" and (np.any(x <= problem.lower) or np.any(x >= problem.upper)): raise ValueError("LM requires strict interior")
        if not m5._same_diagnostics(start["estimate"], problem.geometry(x)): raise ValueError("Saved geometry differs from parameters")
        x0 = problem.pack(start["initial"]["knot_trajectory"], start["initial"]["beacons"])
        if not m5._same_diagnostics(solver["initial_parameters"], x0.tolist()): raise ValueError("Initial physical/native geometry mismatch")
        if np.any(x0 < problem.lower) or np.any(x0 > problem.upper): raise ValueError("Initial parameters violate bounds")
        mask = None; second = x0; pilot = start["diagnostics"].get("rejection_pilot")
        if opts["loss"] == "hard_rejection":
            if pilot is None: raise ValueError("Hard rejection requires saved pilot")
            second = m3._array(pilot["parameters"], (problem.parameter_count,), "Pilot parameters")
            if np.any(second < problem.lower) or np.any(second > problem.upper): raise ValueError("Pilot violates bounds")
            pr = m4.measurement_residuals(second, problem); mask = np.abs(pr) <= opts["rejection_threshold_sigma"]
            if not np.any(mask): raise ValueError("Finite rejection result requires retained ranges")
            for k, v in {"geometry": problem.geometry(second), "residuals_normalized": pr.tolist(), "retained_mask": mask.tolist()}.items():
                if not m5._same_diagnostics(pilot[k], v): raise ValueError("Saved pilot inconsistent: " + k)
        elif pilot is not None: raise ValueError("Pilot belongs only to hard rejection")
        expected = _diagnostics(x, problem, start["success"], mask)
        expected.update(_evaluation_diagnostics(run["experiment"], {**start, "diagnostics": expected}))
        for k, value in expected.items():
            if not m5._same_diagnostics(start["diagnostics"].get(k), value): raise ValueError("Offline diagnostic mismatch: " + k)
        for key, expected_value in {"initial_objective": .5 * np.sum(residuals(x0, problem, mask) ** 2),
                                    "second_stage_initial_objective": .5 * np.sum(residuals(second, problem, mask) ** 2),
                                    "final_objective": expected["total_objective"]}.items():
            if not m5._same_diagnostics(solver[key], float(expected_value)): raise ValueError("Saved objective mismatch: " + key)
    finite = [s for s in run["starts"] if s["estimate"] is not None]; preferred = [s for s in finite if s["success"]] or finite
    chosen = min(preferred, key=lambda s: s["solver"]["final_objective"]) if preferred else None
    if run["selected_start"] != (chosen["index"] if chosen else None): raise ValueError("Selected attempt mismatch")
    if run["status"] != (chosen["status"] if chosen else "failed"): raise ValueError("Run status mismatch")
    if run["diagnostics"] != _run_diagnostics(opts, run["starts"]): raise ValueError("Run survey/gauge disclosures mismatch")
    return run


def save_run(path, run):
    validate_run(run)
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".m7.tmp")
    temporary.write_text(json.dumps(run, allow_nan=False, indent=2), encoding="utf-8")
    _replace_with_retry(temporary, path)


def load_run(path):
    return validate_run(json.loads(Path(path).read_text(encoding="utf-8")))


def table_csv(run):
    validate_run(run)
    output = io.StringIO(); fields = ["start", "status", "success", "solver_message", "source_index", "observation_index", "epoch", "beacon_id", "actual_time_s", "assumed_time_s", "delivery_time_s", "range_m", "sigma_m", "clean_range_m", "white_noise_m", "offset_m", "correlated_noise_m", "nlos_bias_m", "quantization_error_m", "nlos", "dropped", "residual_m", "weight", "flagged", "rejected", "measurement_objective", "survey_objective", "motion_prior_objective", "height_prior_objective", "prior_objective", "uncertainty_available"]
    writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
    experiment = run["experiment"]
    reference = experiment["contamination_reference"]
    source_observations = reference["source_experiment"]["estimator_input"]["observations"]
    for start in run["starts"]:
        diag = start["diagnostics"]
        for record in reference["records"] or [None]:
            row = {"start": start["index"], "status": start["status"], "success": start["success"], "solver_message": start["solver"]["message"],
                   **{key: diag.get(key) for key in ("measurement_objective", "survey_objective", "motion_prior_objective", "height_prior_objective", "prior_objective")},
                   "uncertainty_available": diag.get("uncertainty", {}).get("available")}
            if record is not None:
                row.update({k: record[k] for k in ("source_index", "epoch", "beacon_id", "range_m", "clean_range_m", "white_noise_m", "offset_m", "correlated_noise_m", "nlos_bias_m", "quantization_error_m", "nlos", "dropped")})
                source = source_observations[record["source_index"]]
                row.update({k: source[k] for k in ("actual_time_s", "assumed_time_s", "delivery_time_s", "sigma_m")})
                index = record["retained_index"]; row["observation_index"] = index
                if start["estimate"] is not None and index is not None:
                    decision = diag["observation_decisions"][index]
                    row.update(residual_m=diag["residuals_m"][index], weight=diag["weights"][index], flagged=decision["flagged"], rejected=decision["rejected"])
            writer.writerow(row)
    return output.getvalue()
