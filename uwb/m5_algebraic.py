"""Measurement-only lifted initializer for synchronized planar/shared-height data.

This ordinary least-squares calculation is a proposal, never the final range
objective. Invalid fits are returned with their diagnostics and no fallback.
"""
from __future__ import annotations

import math

import numpy as np

PHYSICAL_TOLERANCE = 1e-7
RANK_RELATIVE_TOLERANCE = 1e-8
TIME_TOLERANCE_S = 1e-9
WEAK_CONDITION_THRESHOLD = 1000.


class _Failure(ValueError):
    def __init__(self, code, message, status="failed"):
        super().__init__(message)
        self.code, self.status = code, status


def _number(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)) or not math.isfinite(float(value)):
        raise _Failure("invalid_input", f"{name} must be a finite number")
    return float(value)


def _rank(matrix):
    singular = np.linalg.svd(matrix, compute_uv=False)
    cutoff = float(singular[0] * RANK_RELATIVE_TOLERANCE) if len(singular) else 0.
    rank = int(np.count_nonzero(singular > cutoff))
    full = rank == matrix.shape[1]
    return {"rank": rank, "column_count": matrix.shape[1], "row_count": matrix.shape[0],
            "full_column_rank": full, "singular_values": singular.tolist(),
            "relative_tolerance": RANK_RELATIVE_TOLERANCE, "absolute_cutoff": cutoff,
            "condition_number": float(singular[0] / singular[-1]) if full else None}


def _coefficient_names(values):
    return dict(zip(("alpha", "beta", "gamma", "delta", "eta", "kappa"), map(float, values)))


def propose_initialization(observations, times_s, beacon_count, options=None):
    """Return ``{status, diagnostics, geometry, error}`` without accessing truth.

    Full solver options may be supplied. Only model choices, fixed_tag_z_m and
    algebraic_physical_tolerance affect this calculation. All epochs must have
    exactly one positive range for each beacon, measured at their epoch time.
    The default canonical proposal has d>0, beacon2.y>0 and positive height
    separation; reflected branches are disclosed rather than inferred by data.
    """
    diagnostics = {
        "method": "lifted_squared_range_ordinary_least_squares",
        "measurement_only": True, "reference_beacon_ids": [0, 1, 2],
        "warnings": [], "support": "Joint planar fixed/shared tag height, shared beacon height, 3–8 beacons, complete synchronized epochs, at least six rank-six samples",
        "statistical_note": "Squared noisy ranges are biased and heteroscedastic; differences share correlated noise and explanatory variables are noisy. This ordinary linear fit is only an initializer; final estimation uses unsquared normalized range residuals.",
        "branch": {"d_positive": True, "beacon2_y_positive": True,
                   "height_separation_sign": "positive",
                   "ambiguity": "Horizontal y reflection and height-separation sign reflection preserve ranges. These conventions select a branch; full lifted rank does not prove global uniqueness."},
    }
    result = {"status": "failed", "diagnostics": diagnostics, "geometry": None, "error": None}
    try:
        opts = dict(options or {})
        if opts.get("mode", "joint") != "joint" or opts.get("tag_height_model", "fixed") not in ("fixed", "shared") or opts.get("beacon_height_model", "shared") != "shared":
            raise _Failure("unsupported_model", "Algebraic calibration requires joint planar fixed/shared tags and shared beacon height", "unsupported")
        tolerance = _number(opts.get("algebraic_physical_tolerance", PHYSICAL_TOLERANCE), "algebraic_physical_tolerance")
        if not 0. < tolerance <= 1.:
            raise _Failure("invalid_input", "algebraic_physical_tolerance must be greater than zero and at most one")
        diagnostics["physical_tolerance"] = tolerance
        datum = _number(opts.get("fixed_tag_z_m", 0.), "fixed_tag_z_m")
        if isinstance(beacon_count, bool) or not isinstance(beacon_count, (int, np.integer)) or not 3 <= beacon_count <= 8:
            raise _Failure("unsupported_beacon_count", "beacon_count must be an integer from 3 through 8", "unsupported")
        times = np.asarray(times_s, dtype=float)
        if times.ndim != 1 or not np.all(np.isfinite(times)) or np.any(np.diff(times) <= 0):
            raise _Failure("invalid_input", "Epoch times must be a finite strictly increasing vector")
        diagnostics["epoch_count"] = len(times)
        if len(times) < 6:
            raise _Failure("insufficient_epochs", "The six-coefficient lifted fit requires at least six informative synchronized epochs", "unsupported")
        ranges = np.full((len(times), beacon_count), np.nan)
        for item in observations:
            epoch, beacon = item["epoch"], item["beacon_id"]
            if isinstance(epoch, bool) or not isinstance(epoch, (int, np.integer)) or not 0 <= epoch < len(times) or isinstance(beacon, bool) or not isinstance(beacon, (int, np.integer)) or not 0 <= beacon < beacon_count:
                raise _Failure("invalid_input", "Observation epoch and beacon_id must be valid integer indices")
            if math.isfinite(ranges[epoch, beacon]):
                raise _Failure("duplicate_observation", "Exactly one observation per epoch/beacon is required")
            value = _number(item["range_m"], "range_m")
            if value <= 0.:
                raise _Failure("invalid_squared_range", "Nonpositive measured ranges cannot be squared into a valid physical distance")
            # Actual and delivery timestamps, synthetic metadata and truth are
            # intentionally excluded: only estimator-assumed timestamps enter.
            assumed = _number(item["assumed_time_s"], "assumed_time_s")
            if abs(assumed - times[epoch]) > TIME_TOLERANCE_S:
                raise _Failure("asynchronous_observations", "All assumed ping times must coincide with their common-position epoch; grouped asynchronous approximation is unsupported", "unsupported")
            if "sigma_m" in item and _number(item["sigma_m"], "sigma_m") <= 0.:
                raise _Failure("invalid_input", "sigma_m must be strictly positive")
            ranges[epoch, beacon] = value
        missing = np.argwhere(~np.isfinite(ranges)).tolist()
        diagnostics["missing_epoch_beacon_pairs"] = missing
        if missing:
            raise _Failure("missing_observations", "Complete synchronized observations for every epoch and beacon are required; no interpolation or fabricated ranges are used", "unsupported")
        scale = float(np.median(ranges))
        diagnostics["range_scale_m"] = scale
        # Divide before squaring to avoid overflowing otherwise valid metre
        # inputs. Reject any remaining unrepresentable dynamic range.
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            squared = (ranges / scale) ** 2
        if not np.all(np.isfinite(squared)):
            raise _Failure("invalid_squared_range", "Squared ranges are not finite at the declared scale")
        u, v = squared[:, 1] - squared[:, 0], squared[:, 2] - squared[:, 0]
        centers = np.array([np.mean(u), np.mean(v)])
        spreads = np.array([np.std(u), np.std(v)])
        diagnostics["scaling"] = {"squared_range_units": "D/L², u/L², v/L²", "difference_centers": centers.tolist(), "difference_standard_deviations": spreads.tolist(), "design": "Centered standardized u,v polynomial; each design column divided by its RMS. Rank and condition refer to this dimensionless design."}
        # Keep constant columns finite, so rank loss retains a complete spectrum.
        safe_spreads = np.where(spreads > 0., spreads, 1.)
        U, V = (u - centers[0]) / safe_spreads[0], (v - centers[1]) / safe_spreads[1]
        design = np.column_stack((U * U, U * V, V * V, U, V, np.ones(len(times))))
        column_scales = np.sqrt(np.mean(design ** 2, axis=0))
        column_scales = np.where(column_scales > 0., column_scales, 1.)
        normalized = design / column_scales
        diagnostics["scaling"]["design_column_rms"] = column_scales.tolist()
        diagnostics["design"] = _rank(normalized)
        if not diagnostics["design"]["full_column_rank"]:
            raise _Failure("lifted_rank_loss", "Lifted design has fewer than six independent columns; motion or reference geometry does not support this initializer")
        if diagnostics["design"]["condition_number"] > WEAK_CONDITION_THRESHOLD:
            diagnostics["warnings"].append("Lifted design condition exceeds the disclosed heuristic threshold 1000; this is not an uncertainty bound")
        p = np.linalg.lstsq(normalized, squared[:, 0], rcond=RANK_RELATIVE_TOLERANCE)[0] / column_scales
        mu, mv = centers; su, sv = safe_spreads
        alpha, beta, gamma = p[0] / su ** 2, p[1] / (su * sv), p[2] / sv ** 2
        delta = p[3] / su - 2. * alpha * mu - beta * mv
        eta = p[4] / sv - 2. * gamma * mv - beta * mu
        kappa = p[5] + alpha * mu ** 2 + beta * mu * mv + gamma * mv ** 2 - p[3] * mu / su - p[4] * mv / sv
        coefficients = np.array([alpha, beta, gamma, delta, eta, kappa])
        diagnostics["coefficients_dimensionless"] = _coefficient_names(coefficients)
        physical_units = coefficients.copy(); physical_units[:3] /= scale ** 2; physical_units[5] *= scale ** 2
        if not np.all(np.isfinite(physical_units)):
            raise _Failure("nonfinite_coefficients", "Lifted coefficients cannot be represented in physical metre units")
        diagnostics["coefficients_physical"] = _coefficient_names(physical_units)
        fit_error = design @ p - squared[:, 0]
        diagnostics["lifted_fit"] = {"dimensionless_residuals": fit_error.tolist(), "rmse": float(np.sqrt(np.mean(fit_error ** 2))), "max_abs": float(np.max(np.abs(fit_error)))}
        if gamma <= 0.:
            raise _Failure("nonpositive_quadratic", "Lifted gamma must be positive to recover nonzero beacon2.y")
        schur = alpha - beta ** 2 / (4. * gamma)
        diagnostics["quadratic_positivity"] = {"gamma": float(gamma), "schur_complement": float(schur)}
        if schur <= 0.:
            raise _Failure("nonpositive_quadratic", "Lifted alpha-beta²/(4gamma) must be positive to recover a nonzero baseline")
        b = 1. / (2. * np.sqrt(gamma)); d = 1. / (2. * np.sqrt(schur)); a = -beta * d / (2. * gamma)
        c = (a * a + b * b - a * d) / (2. * b)
        expected_delta, expected_eta = -.5 + a * c / (b * d), -c / b
        incompatibility = max(abs(delta - expected_delta), abs(eta - expected_eta))
        diagnostics["physical_coefficients"] = {"expected_delta": float(expected_delta), "expected_eta": float(expected_eta), "delta_error": float(delta - expected_delta), "eta_error": float(eta - expected_eta), "max_abs_error": float(incompatibility)}
        x = (d * d - u) / (2. * d)
        y = (a * a + b * b - v - 2. * a * x) / (2. * b)
        h2_each = squared[:, 0] - x * x - y * y
        h2 = float(np.mean(h2_each))
        intercept_h2 = float(kappa - d * d / 4. - c * c)
        diagnostics["recovered_parameters"] = {"d_m": float(d * scale), "a_m": float(a * scale), "b_m": float(b * scale), "height_squared_m2": float(h2 * scale ** 2), "intercept_height_squared_m2": float(intercept_h2 * scale ** 2), "epoch_height_squared_m2": (h2_each * scale ** 2).tolist(), "height_squared_dimensionless_max_departure": float(np.max(np.abs(h2_each - h2)))}
        if h2 <= 0. or intercept_h2 <= 0.:
            raise _Failure("nonpositive_height_squared", "Recovered shared height squared must be positive; negative/zero values are retained and never clipped")
        if incompatibility > tolerance:
            raise _Failure("physical_coefficient_mismatch", "Unconstrained lifted linear coefficients disagree with the recovered physical beacon model")
        if max(float(np.max(np.abs(h2_each - h2))), abs(h2 - intercept_h2)) > tolerance:
            raise _Failure("inconsistent_height_squared", "Recovered per-epoch/intercept height squared is not a common physical value within the disclosed tolerance")
        xy = np.column_stack((x, y))
        beacon_xy = [[0., 0.], [d, 0.], [a, b]]
        diagnostics["additional_beacons"] = []
        if beacon_count > 3:
            extra_design = np.column_stack((-2. * x, -2. * y, np.ones(len(x))))
            extra_scales = np.sqrt(np.mean(extra_design ** 2, axis=0))
            extra_scaled = extra_design / np.where(extra_scales > 0., extra_scales, 1.)
            diagnostics["additional_beacon_design"] = _rank(extra_scaled)
            if not diagnostics["additional_beacon_design"]["full_column_rank"]:
                raise _Failure("additional_beacon_rank_loss", "Path does not support fitting additional beacon horizontal positions")
            for beacon in range(3, beacon_count):
                target = squared[:, beacon] - squared[:, 0]
                coeff = np.linalg.lstsq(extra_scaled, target, rcond=RANK_RELATIVE_TOLERANCE)[0] / extra_scales
                aj, cj, intercept = coeff
                closure = float(intercept - aj * aj - cj * cj)
                residual = extra_design @ coeff - target
                diagnostics["additional_beacons"].append({"beacon_id": beacon, "xy_m": (coeff[:2] * scale).tolist(), "squared_norm_intercept_dimensionless": float(intercept), "physical_intercept_error_dimensionless": closure, "fit_residuals_dimensionless": residual.tolist()})
                if abs(closure) > tolerance or np.max(np.abs(residual)) > tolerance:
                    raise _Failure("additional_beacon_physical_mismatch", f"Beacon {beacon} squared-range equations do not fit the shared-height physical map within tolerance")
                beacon_xy.append([float(aj), float(cj)])
        height = float(np.sqrt(h2) * scale)
        trajectory = np.column_stack((xy * scale, np.full(len(times), datum)))
        beacons = np.column_stack((np.asarray(beacon_xy) * scale, np.full(beacon_count, datum + height)))
        if not np.all(np.isfinite(trajectory)) or not np.all(np.isfinite(beacons)):
            raise _Failure("nonfinite_geometry", "Recovered physical geometry is not finite")
        residual_m = np.linalg.norm(trajectory[:, None] - beacons[None, :], axis=2) - ranges
        diagnostics["proposal_range_residuals_m"] = residual_m.tolist()
        diagnostics["proposal_range_rmse_m"] = float(np.sqrt(np.mean(residual_m ** 2)))
        diagnostics["branch"]["negative_height_beacon_z_m"] = datum - height
        diagnostics["branch"]["horizontal_reflection_rule"] = "Negate all trajectory and beacon y coordinates; distances remain equal"
        geometry = {"trajectory": trajectory.tolist(), "beacons": beacons.tolist(), "knot_times_s": times.tolist(), "knot_trajectory": trajectory.tolist()}
        result.update(status="success", geometry=geometry)
    except _Failure as exc:
        result.update(status=exc.status, error={"code": exc.code, "message": str(exc)})
    except (TypeError, ValueError, KeyError, OverflowError, np.linalg.LinAlgError) as exc:
        result.update(error={"code": "invalid_input_or_numerical_failure", "message": str(exc)})
    return result
