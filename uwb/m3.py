"""M3 asynchronous acquisition and piecewise-linear, planar trajectory fitting.

The optimizer receives only assumed timestamps, ranges and uncertainty. Actual
timestamps, delivery times and synthetic positions are reserved for evaluation.
"""
from __future__ import annotations

import copy
import json
import math
import time
from dataclasses import dataclass
from functools import wraps

import numpy as np
from scipy.optimize import least_squares

from . import experiments as reference
from . import estimation as baseline

SCHEMA_VERSION = "3.0"
MAX_CYCLES = 100
MAX_KNOTS = 150
# Linear signed-speed transitions include acceleration, a stop, and reversal.
VARIABLE_NODES = [[0., .3], [.15, 1.5], [.35, 1.5], [.45, 0.],
                  [.55, 0.], [.7, 1.8], [.8, 0.], [.9, -.9], [1., -.9]]


def _format_errors(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (KeyError, TypeError, OverflowError, AttributeError) as exc:
            raise ValueError(f"Invalid M3 {function.__name__}: {exc}") from exc
    return wrapped


def _number(value, name, lower=0., upper=math.inf):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError(f"{name} must be finite and between {lower} and {upper}")
    return value


@_format_errors
def normalize_config(config=None):
    supplied = dict(config or {})
    motion = dict(supplied.pop("motion", {}))
    acquisition = dict(supplied.pop("acquisition", {}))
    cfg = reference._normalise_config(supplied)
    cfg["duration_s"] = _number(cfg["duration_s"], "duration_s", .01, 3600.)
    if cfg["seed"] > 2 ** 32 - 1:
        raise ValueError("seed must be at most 4294967295")
    if max(cfg["noise_std_m"]) > 100. or min(cfg["assumed_std_m"]) < 1e-6 or max(cfg["assumed_std_m"]) > 1000.:
        raise ValueError("noise_std_m must be at most 100; assumed_std_m must be from 1e-6 through 1000")
    if set(motion) - {"profile", "speed_scale"}:
        raise ValueError("Unsupported motion keys")
    profile = motion.get("profile", "constant")
    if profile not in ("constant", "variable", "stationary"):
        raise ValueError("motion.profile must be constant, variable, or stationary")
    cfg["motion"] = {"profile": profile, "speed_scale": _number(motion.get("speed_scale", 1.), "speed_scale", 0., 10.)}
    defaults = {"beacon_order": [0, 1, 2, 3],
                "cycle_rate_hz": (cfg["samples"] - 1) / cfg["duration_s"],
                "spacing_s": 0., "jitter_s": 0., "timestamp_offset_s": 0.,
                "timestamp_jitter_s": 0., "delivery_latency_s": 0.,
                "missing_probability": 0., "beacon_every_cycles": [1, 1, 1, 1]}
    if set(acquisition) - set(defaults):
        raise ValueError("Unsupported acquisition keys")
    acq = {**defaults, **acquisition}
    order = acq["beacon_order"]
    if not isinstance(order, (list, tuple)) or any(isinstance(v, bool) or not isinstance(v, int) for v in order) or sorted(order) != [0, 1, 2, 3]:
        raise ValueError("beacon_order must be a permutation of 0,1,2,3")
    acq["beacon_order"] = list(order)
    rates = acq["beacon_every_cycles"]
    if not isinstance(rates, (list, tuple)) or len(rates) != 4 or any(isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 100 for v in rates):
        raise ValueError("beacon_every_cycles must contain four integers from 1 through 100")
    acq["beacon_every_cycles"] = list(rates)
    for key in ("cycle_rate_hz", "spacing_s", "jitter_s", "timestamp_jitter_s", "delivery_latency_s"):
        acq[key] = _number(acq[key], key, np.finfo(float).tiny if key == "cycle_rate_hz" else 0., 10000.)
    acq["timestamp_offset_s"] = _number(acq["timestamp_offset_s"], "timestamp_offset_s", -10000., 10000.)
    acq["missing_probability"] = _number(acq["missing_probability"], "missing_probability", 0., 1.)
    cycles = math.floor(cfg["duration_s"] * acq["cycle_rate_hz"] + 1e-10) + 1
    if not 2 <= cycles <= MAX_CYCLES:
        raise ValueError(f"cycle rate and duration must produce 2 through {MAX_CYCLES} cycles")
    cfg["acquisition"] = acq
    return cfg


@_format_errors
def validate_options(options=None):
    defaults = {"mode": "joint", "initialization": "independent", "starts": 3,
                "seed": 19, "max_nfev": 2000, "timing_model": "timestamp_aware",
                "knot_spacing_s": 0., "prior_sigma_m": 0.}
    supplied = dict(options or {})
    if set(supplied) - set(defaults):
        raise ValueError("Unsupported M3 solver options")
    opts = {**defaults, **supplied}
    for key, choices in (("mode", ("joint", "known_map")), ("initialization", ("independent", "truth_near")),
                         ("timing_model", ("timestamp_aware", "grouped"))):
        if opts[key] not in choices:
            raise ValueError(f"{key} must be one of {choices}")
    for key, lower, upper in (("starts", 1, 20), ("seed", 0, 2 ** 32 - 1), ("max_nfev", 1, 100000)):
        v = opts[key]
        if isinstance(v, bool) or not isinstance(v, int) or not lower <= v <= upper:
            raise ValueError(f"{key} must be an integer from {lower} through {upper}")
    for key in ("knot_spacing_s", "prior_sigma_m"):
        opts[key] = _number(opts[key], key, 0., 10000.)
    return opts


def _path(cfg, fraction):
    """Continuous arclength path; open/closed paths stop at their endpoints."""
    fraction = np.clip(np.asarray(fraction, dtype=float), 0., 1.)
    spec = cfg.get("path")
    if spec and spec["type"] in ("circle", "arc"):
        theta = np.deg2rad(spec["start_angle_deg"] + fraction * spec.get("arc_angle_deg", 360.))
        xy = spec["size_m"][0] / 2 * np.column_stack((np.cos(theta), np.sin(theta)))
    else:
        if spec:
            kind = spec["type"]
            w, h = spec.get("size_m", [7., 5.6])
            if kind == "line":
                vertices = np.array([[-w / 2, 0.], [w / 2, 0.]])
            elif kind == "rectangle":
                vertices = np.array([[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2], [-w / 2, -h / 2]])
            elif kind == "waypoint":
                vertices = np.asarray(spec["waypoints_m"])
            else:
                theta = np.linspace(0., 2 * np.pi, 16385)
                vertices = np.column_stack((w / 2 * np.sin(theta), h / 2 * np.sin(2 * theta)))
        elif cfg["scenario"] in ("informative", "nearly_collinear"):
            vertices = np.array([[1.5, 1.2], [8.5, 1.2], [8.5, 6.8], [1.5, 6.8], [1.5, 1.2]])
        elif cfg["scenario"] == "straight_line":
            vertices = np.array([[1., 2.], [8., 2.]])
        else:
            u = np.linspace(-1., 1., max(1001, cfg["samples"] * 20))
            vertices = np.column_stack((4.5 + .35 * u, 3.5 + .25 * np.sin(np.pi * u)))
        vertices = vertices[np.r_[True, np.linalg.norm(np.diff(vertices, axis=0), axis=1) > 0.]]
        distance = np.r_[0., np.cumsum(np.linalg.norm(np.diff(vertices, axis=0), axis=1))]
        xy = np.column_stack([np.interp(fraction * distance[-1], distance, vertices[:, axis]) for axis in range(2)])
    if spec:
        theta = np.deg2rad(spec["rotation_deg"])
        xy = spec["scale"] * xy @ np.array([[np.cos(theta), np.sin(theta)], [-np.sin(theta), np.cos(theta)]]) + spec["center_m"]
    return np.column_stack((xy, np.zeros(len(xy))))


def _progress(cfg, times):
    t = np.asarray(times, dtype=float) / cfg["duration_s"]
    clipped = np.clip(t, 0., 1.)
    if cfg["motion"]["profile"] == "stationary":
        return np.zeros_like(t), np.zeros_like(t), np.zeros_like(t)
    if cfg["motion"]["profile"] == "constant":
        progress, velocity, acceleration = clipped.copy(), np.ones_like(t), np.zeros_like(t)
    else:
        nodes = np.asarray(VARIABLE_NODES)
        dt = np.diff(nodes[:, 0]); dv = np.diff(nodes[:, 1])
        area = np.r_[0., np.cumsum(dt * (nodes[:-1, 1] + nodes[1:, 1]) / 2)]
        # Normalize by peak forward excursion so reversal does not clip at 1.
        norm = max(area)
        i = np.minimum(np.searchsorted(nodes[:, 0], clipped, side="right") - 1, len(dt) - 1)
        local = clipped - nodes[i, 0]
        slope = dv[i] / dt[i]
        progress = (area[i] + nodes[i, 1] * local + .5 * slope * local ** 2) / norm
        velocity = (nodes[i, 1] + slope * local) / norm
        acceleration = slope / norm
    scale = cfg["motion"]["speed_scale"]
    progress *= scale; velocity *= scale; acceleration *= scale
    stopped = (t < 0.) | (t > 1.) | (progress > 1.) | (progress < 0.)
    velocity[stopped] = 0.; acceleration[stopped] = 0.
    return progress, velocity, acceleration


def truth_positions(config, times_s):
    """Synthetic evaluator; never used by the measurement-only fitter."""
    return _path(config, _progress(config, times_s)[0])


def generate_experiment(config=None):
    cfg = normalize_config(config)
    acq = cfg["acquisition"]
    count = math.floor(cfg["duration_s"] * acq["cycle_rate_hz"] + 1e-10) + 1
    cycles = np.arange(count) / acq["cycle_rate_hz"]
    display = np.linspace(0., cfg["duration_s"], cfg["samples"])
    beacons = reference._beacons(cfg["scenario"])
    # Separate random streams: spacing, timestamp error and missingness never
    # change the range-noise draw assigned to a particular cycle/beacon.
    noise = np.random.default_rng(cfg["seed"]).normal(0., np.asarray(cfg["noise_std_m"]), (count, 4))
    rng = np.random.default_rng(cfg["seed"] + 101)
    jitter = rng.uniform(-acq["jitter_s"], acq["jitter_s"], (count, 4))
    clock = rng.uniform(-acq["timestamp_jitter_s"], acq["timestamp_jitter_s"], (count, 4))
    missing = rng.random((count, 4)) < acq["missing_probability"]
    observations, ping_times, ping_positions, grouped_positions = [], [], [], []
    for epoch, cycle in enumerate(cycles):
        for slot, beacon in enumerate(acq["beacon_order"]):
            if epoch % acq["beacon_every_cycles"][beacon] or missing[epoch, beacon]:
                continue
            actual = float(cycle + slot * acq["spacing_s"] + jitter[epoch, beacon])
            assumed = actual + acq["timestamp_offset_s"] + clock[epoch, beacon]
            position = truth_positions(cfg, [actual])[0]
            observations.append({"epoch": epoch, "beacon_id": beacon, "actual_time_s": actual,
                                 "assumed_time_s": float(assumed), "delivery_time_s": actual + acq["delivery_latency_s"],
                                 "range_m": float(np.linalg.norm(position - beacons[beacon]) + noise[epoch, beacon]),
                                 "sigma_m": cfg["assumed_std_m"][beacon]})
            ping_times.append(actual); ping_positions.append(position.tolist())
            grouped_positions.append(truth_positions(cfg, [cycle])[0].tolist())
    legacy_cfg = {key: value for key, value in cfg.items() if key not in ("motion", "acquisition")}
    length = reference.path_metadata(legacy_cfg)["length_m"]
    motion_times = np.unique(np.r_[np.linspace(0., cfg["duration_s"], 401), np.asarray(VARIABLE_NODES)[:, 0] * cfg["duration_s"]])
    _, velocity, acceleration = _progress(cfg, motion_times)
    experiment = {"schema_version": SCHEMA_VERSION, "config": cfg, "units": "metres, seconds",
                  "coordinate_convention": reference.COORDINATE_CONVENTION,
                  "truth": {"times_s": display.tolist(), "trajectory": truth_positions(cfg, display).tolist(), "beacons": beacons.tolist(),
                            "ping_times_s": ping_times, "ping_positions": ping_positions, "grouped_positions": grouped_positions,
                            "motion": {"times_s": motion_times.tolist(), "speed_m_s": (np.abs(velocity) * length / cfg["duration_s"]).tolist(),
                                       "signed_speed_m_s": (velocity * length / cfg["duration_s"]).tolist(),
                                       "acceleration_m_s2": (acceleration * length / cfg["duration_s"] ** 2).tolist(),
                                       "profile_nodes": copy.deepcopy(VARIABLE_NODES) if cfg["motion"]["profile"] == "variable" else None,
                                       "profile_node_units": "fraction of duration, signed relative speed; variable profile normalized by peak forward excursion",
                                       "endpoint_rule": "Position holds at path endpoints and outside [0,duration]; speed is zero while held",
                                       "path_length_m": length, "path_parameterization": reference.path_metadata(legacy_cfg)["parameterization"]}},
                  "estimator_input": {"times_s": cycles.tolist(), "observations": observations},
                  "acquisition_metadata": {"cycle_count": count, "grouping_rule": "assume every ping in epoch occurs at estimator_input.times_s[epoch]",
                                           "jitter_distribution": "independent uniform [-jitter_s,+jitter_s] per potential cycle/beacon",
                                           "timestamp_error_distribution": "offset plus independent uniform [-timestamp_jitter_s,+timestamp_jitter_s]",
                                           "delivery_latency_rule": "delivery_time_s=actual_time_s+latency; never used in batch fitting",
                                           "range_noise_pairing": "fixed Gaussian draw indexed by cycle and beacon, independent of missingness and timing"},
                  "software_versions": reference._package_versions()}
    validate_experiment(experiment)
    return experiment


def _array(value, shape, name):
    array = np.asarray(value, dtype=float)
    if array.shape != shape or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be a finite array of shape {shape}")
    return array


@_format_errors
def validate_experiment(experiment):
    if not isinstance(experiment, dict) or experiment.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("M3 experiment requires schema_version 3.0")
    json.dumps(experiment, allow_nan=False)
    if normalize_config(experiment["config"]) != experiment["config"]:
        raise ValueError("Saved M3 configuration must include normalized defaults")
    truth, inputs = experiment["truth"], experiment["estimator_input"]
    times = np.asarray(truth["times_s"], dtype=float)
    epochs = np.asarray(inputs["times_s"], dtype=float)
    for array in (times, epochs):
        if array.ndim != 1 or not 2 <= len(array) <= 100 or not np.all(np.isfinite(array)) or np.any(np.diff(array) <= 0):
            raise ValueError("Display and cycle times must contain 2 through 100 increasing finite timestamps")
    if len(times) != experiment["config"]["samples"]:
        raise ValueError("Display times must agree with config.samples")
    trajectory = _array(truth["trajectory"], (len(times), 3), "truth trajectory")
    if not np.allclose(trajectory[:, 2], 0., atol=1e-12, rtol=0):
        raise ValueError("Truth tag trajectory must be planar")
    _array(truth["beacons"], (4, 3), "truth beacons")
    obs = inputs["observations"]
    for key in ("ping_positions", "grouped_positions"):
        _array(np.asarray(truth[key]).reshape((-1, 3)), (len(obs), 3), key)
    _array(truth["ping_times_s"], (len(obs),), "ping times")
    _validate_observations(obs, epochs)
    for index, observation in enumerate(obs):
        for key in ("actual_time_s", "delivery_time_s"):
            _number(observation[key], key, -math.inf)
        if truth["ping_times_s"][index] != observation["actual_time_s"]:
            raise ValueError("Truth ping times must agree with actual observation times")
    motion = truth["motion"]
    motion_times = np.asarray(motion["times_s"], dtype=float)
    if motion_times.ndim != 1 or len(motion_times) < 2 or not np.all(np.isfinite(motion_times)) or np.any(np.diff(motion_times) <= 0):
        raise ValueError("Invalid motion times")
    for key in ("speed_m_s", "signed_speed_m_s", "acceleration_m_s2"):
        _array(motion[key], (len(motion_times),), key)
    if experiment["units"] != "metres, seconds" or not isinstance(experiment["acquisition_metadata"], dict):
        raise ValueError("Invalid units or acquisition metadata")
    return experiment


def _validate_observations(observations, times):
    seen = set()
    for o in observations:
        epoch, beacon = o["epoch"], o["beacon_id"]
        if isinstance(epoch, bool) or not isinstance(epoch, int) or not 0 <= epoch < len(times) or isinstance(beacon, bool) or not isinstance(beacon, int) or not 0 <= beacon < 4:
            raise ValueError("Invalid observation epoch or beacon ID")
        if (epoch, beacon) in seen:
            raise ValueError("Duplicate cycle/beacon observation")
        seen.add((epoch, beacon))
        for key in ("assumed_time_s", "range_m", "sigma_m"):
            _number(o[key], key, np.finfo(float).tiny if key == "sigma_m" else -math.inf)


def _weights(knots, times):
    times = np.asarray(times, dtype=float)
    if np.any(times < knots[0] - 1e-9) or np.any(times > knots[-1] + 1e-9):
        raise ValueError("Interpolation times outside disclosed knot domain")
    i = np.clip(np.searchsorted(knots, times, side="right") - 1, 0, len(knots) - 2)
    alpha = (times - knots[i]) / (knots[i + 1] - knots[i])
    weights = np.zeros((len(times), len(knots)))
    weights[np.arange(len(times)), i] = 1. - alpha
    weights[np.arange(len(times)), i + 1] = alpha
    return weights


@dataclass
class TrajectoryProblem(baseline.RangeProblem):
    display_times_s: np.ndarray = None
    measurement_times_s: np.ndarray = None
    assumed_times_s: np.ndarray = None
    weights: np.ndarray = None
    prior_matrix: np.ndarray = None
    timing_model: str = "timestamp_aware"

    def geometry(self, parameters):
        knots, beacons = self.unpack(parameters)
        return {"trajectory": (_weights(self.times_s, self.display_times_s) @ knots).tolist(), "beacons": beacons.tolist(),
                "knot_times_s": self.times_s.tolist(), "knot_trajectory": knots.tolist(),
                "ping_trajectory": (self.weights @ knots).tolist(),
                "assumed_ping_trajectory": (_weights(self.times_s, self.assumed_times_s) @ knots).tolist()}


def build_problem(observations, times_s, *, mode="joint", surveyed_beacons=None,
                  timing_model="timestamp_aware", knot_spacing_s=0., prior_sigma_m=0., display_times_s=None):
    """Build a truth-free problem. Delivery and actual timestamps are ignored."""
    opts = validate_options({"mode": mode, "timing_model": timing_model, "knot_spacing_s": knot_spacing_s, "prior_sigma_m": prior_sigma_m})
    cycles = np.asarray(times_s, dtype=float)
    display = cycles if display_times_s is None else np.asarray(display_times_s, dtype=float)
    for vector in (cycles, display):
        if vector.ndim != 1 or len(vector) < 2 or not np.all(np.isfinite(vector)) or np.any(np.diff(vector) <= 0):
            raise ValueError("Times must be finite and strictly increasing")
    _validate_observations(observations, cycles)
    epochs = np.asarray([o["epoch"] for o in observations], dtype=int)
    assumed = np.asarray([o["assumed_time_s"] for o in observations])
    domain = np.r_[cycles, display, assumed]
    lower, upper = float(domain.min()), float(domain.max())
    if opts["knot_spacing_s"] == 0.:
        knots = np.unique(np.r_[lower, cycles, upper])
    else:
        intervals = int(math.ceil((upper - lower) / opts["knot_spacing_s"]))
        if intervals + 1 > MAX_KNOTS:
            raise ValueError(f"Knot spacing produces more than {MAX_KNOTS} knots")
        knots = np.r_[lower + np.arange(intervals) * opts["knot_spacing_s"], upper]
    if len(knots) > MAX_KNOTS:
        raise ValueError("Too many knots")
    surveyed = None
    if mode == "known_map":
        surveyed = _array(surveyed_beacons, (4, 3), "surveyed map")
    elif surveyed_beacons is not None:
        raise ValueError("Joint fitting cannot receive a surveyed map")
    used = assumed if timing_model == "timestamp_aware" else cycles[epochs]
    prior = np.zeros((max(0, len(knots) - 2), len(knots))) if prior_sigma_m else np.zeros((0, len(knots)))
    for row in range(len(prior)):
        left, right = knots[row + 1] - knots[row], knots[row + 2] - knots[row + 1]
        prior[row, row:row + 3] = [-right / (left + right), 1., -left / (left + right)]
    if prior_sigma_m:
        prior /= prior_sigma_m
    return TrajectoryProblem(knots, epochs, np.asarray([o["beacon_id"] for o in observations], dtype=int),
                             np.asarray([o["range_m"] for o in observations]), np.asarray([o["sigma_m"] for o in observations]),
                             mode, surveyed, display, used, assumed, _weights(knots, used), prior, timing_model)


def measurement_residuals(parameters, problem):
    knots, beacons = problem.unpack(parameters)
    delta = problem.weights @ knots - beacons[problem.beacon_ids]
    return (np.linalg.norm(delta, axis=1) - problem.ranges_m) / problem.sigma_m


def prior_residuals(parameters, problem):
    knots, _ = problem.unpack(parameters)
    return (problem.prior_matrix @ knots[:, :2]).ravel()


def residuals(parameters, problem):
    return np.r_[measurement_residuals(parameters, problem), prior_residuals(parameters, problem)]


def measurement_jacobian(parameters, problem):
    knots, beacons = problem.unpack(parameters)
    delta = problem.weights @ knots - beacons[problem.beacon_ids]
    distance = np.maximum(np.linalg.norm(delta, axis=1), np.finfo(float).tiny)
    direction = delta / (distance * problem.sigma_m)[:, None]
    j = np.zeros((len(delta), problem.parameter_count))
    j[:, :2 * len(knots):2] = direction[:, 0, None] * problem.weights
    j[:, 1:2 * len(knots):2] = direction[:, 1, None] * problem.weights
    if problem.mode == "joint":
        for beacon, columns in ((1, (0, None)), (2, (1, 2)), (3, (3, 4))):
            mask = problem.beacon_ids == beacon
            for axis, column in enumerate(columns):
                if column is not None:
                    j[mask, 2 * len(knots) + column] = -direction[mask, axis]
        j[:, -1] = -direction[:, 2]
    return j


def jacobian(parameters, problem):
    prior = np.zeros((2 * len(problem.prior_matrix), problem.parameter_count))
    prior[::2, :2 * len(problem.times_s):2] = problem.prior_matrix
    prior[1::2, 1:2 * len(problem.times_s):2] = problem.prior_matrix
    return np.vstack((measurement_jacobian(parameters, problem), prior))


def jacobian_diagnostics(parameters, problem, *, augmented=False):
    scale = max(float(np.median(np.abs(problem.ranges_m))) if len(problem.ranges_m) else 1., 1.)
    matrix = jacobian(parameters, problem) if augmented else measurement_jacobian(parameters, problem)
    spectrum = np.linalg.svd(matrix * scale, compute_uv=False)
    cutoff = float(spectrum[0] * baseline.RANK_RELATIVE_TOLERANCE) if len(spectrum) else 0.
    rank = int(np.sum(spectrum > cutoff))
    full = rank == problem.parameter_count
    return {"rank": rank, "parameter_count": problem.parameter_count, "measurement_count": len(problem.ranges_m),
            "prior_residual_count": 2 * len(problem.prior_matrix) if augmented else 0, "singular_values": spectrum.tolist(),
            "full_column_rank": full, "condition_number": float(spectrum[0] / spectrum[-1]) if full else None,
            "relative_tolerance": baseline.RANK_RELATIVE_TOLERANCE, "absolute_tolerance": cutoff, "parameter_scale_m": scale,
            "scaling": "Jacobian of normalized residuals with respect to theta / parameter_scale_m; all parameters in metres",
            "interpretation": "Augmented measurement and prior rank; prior is an assumption, not measurement information" if augmented else "Local measurement-only rank; full rank does not establish global uniqueness"}


def _initial(problem, rng, index):
    """M1-compatible rectangular map and squared-difference position seed."""
    scale = max(float(np.median(np.abs(problem.ranges_m))) if len(problem.ranges_m) else 1., 1.)
    if problem.mode == "known_map":
        beacons = problem.surveyed_beacons.copy()
    else:
        factor = 1. if index == 0 else rng.uniform(.7, 1.4)
        height = .3 if index == 0 else rng.uniform(.12, .55)
        beacons = scale * np.array([[0., 0., height], [1.1 * factor, 0., height], [.1 * factor, .9 * factor, height], [1.2 * factor, 1.05 * factor, height]])
        if index:
            beacons[2:, :2] += rng.normal(0., .1 * scale, (2, 2))
            beacons[2, 1] = max(beacons[2, 1], .1 * scale)
    # Fill missing beacon ranges by interpolation in estimator time, then seed
    # each knot. This is initialization only, never invented observations.
    table = np.full((len(problem.times_s), 4), scale)
    for beacon in range(4):
        mask = problem.beacon_ids == beacon
        if np.any(mask):
            order = np.argsort(problem.measurement_times_s[mask], kind="stable")
            table[:, beacon] = np.interp(problem.times_s, problem.measurement_times_s[mask][order], problem.ranges_m[mask][order])
    a = 2 * (beacons[1:, :2] - beacons[0, :2])
    rhs = np.sum(beacons[1:] ** 2, axis=1) - np.sum(beacons[0] ** 2) - (table[:, 1:] ** 2 - table[:, :1] ** 2)
    xy = np.linalg.lstsq(a, rhs.T, rcond=None)[0].T
    if index:
        xy += rng.normal(0., .12 * scale, xy.shape)
    return problem.geometry(problem.pack(np.column_stack((xy, np.zeros(len(xy)))), beacons))


def compatible_initial_geometries(run, experiment, options=None):
    """Reuse each saved start's map and interpolate its knots onto a new grid."""
    opts = validate_options(options if options is not None else run["options"])
    inputs = experiment["estimator_input"]
    problem = build_problem(inputs["observations"], inputs["times_s"], mode=opts["mode"],
                            surveyed_beacons=experiment["truth"]["beacons"] if opts["mode"] == "known_map" else None,
                            timing_model=opts["timing_model"], knot_spacing_s=opts["knot_spacing_s"],
                            prior_sigma_m=opts["prior_sigma_m"], display_times_s=experiment["truth"]["times_s"])
    result = []
    for start in run["starts"][:opts["starts"]]:
        saved = start["initial"]
        points = np.asarray(saved["knot_trajectory"])
        knots = np.asarray(saved["knot_times_s"])
        # np.interp endpoint holds are disclosed only for cross-grid starts.
        projected = np.column_stack([np.interp(problem.times_s, knots, points[:, axis]) for axis in range(3)])
        result.append(problem.geometry(problem.pack(projected, saved["beacons"])))
    if len(result) != opts["starts"]:
        raise ValueError("Source run has fewer starts than requested")
    return result


def fit_observations(observations, times_s, *, display_times_s=None, surveyed_beacons=None,
                     initial_geometries=None, **options):
    opts = validate_options(options)
    problem = build_problem(observations, times_s, display_times_s=display_times_s, surveyed_beacons=surveyed_beacons,
                            **{k: opts[k] for k in ("mode", "timing_model", "knot_spacing_s", "prior_sigma_m")})
    if initial_geometries is not None and len(initial_geometries) != opts["starts"]:
        raise ValueError("Supply one explicit geometry per start")
    rng = np.random.default_rng(opts["seed"])
    outcomes = []
    for index in range(opts["starts"]):
        initial = copy.deepcopy(initial_geometries[index]) if initial_geometries is not None else _initial(problem, rng, index)
        outcome = {"index": index, "status": "failed", "success": False, "initial": initial, "estimate": None, "solver": {}, "diagnostics": {}}
        begun = time.perf_counter()
        try:
            points = initial.get("knot_trajectory", initial.get("trajectory"))
            x0 = problem.pack(points, initial["beacons"])
            lower, upper = np.full(len(x0), -np.inf), np.full(len(x0), np.inf)
            if problem.mode == "joint":
                lower[[-6, -4, -1]] = baseline.POSITIVE_FLOOR_M
            r0 = residuals(x0, problem)
            if not len(problem.ranges_m):
                raise ValueError("No retained range observations; no measurement fit attempted")
            result = least_squares(residuals, x0, jac=jacobian, args=(problem,), bounds=(lower, upper),
                                   method="trf", x_scale="jac", ftol=1e-12, xtol=1e-12, gtol=1e-12, max_nfev=opts["max_nfev"])
            normalized = measurement_residuals(result.x, problem)
            prior = prior_residuals(result.x, problem)
            metres = normalized * problem.sigma_m
            measurement_objective, prior_objective = float(.5 * normalized @ normalized), float(.5 * prior @ prior)
            outcome.update(status="success" if result.success else "not_converged", success=bool(result.success), estimate=problem.geometry(result.x))
            outcome["solver"] = {"method": "scipy.optimize.least_squares/trf", "status": int(result.status), "message": str(result.message),
                                 "nfev": int(result.nfev), "njev": int(result.njev) if result.njev is not None else None,
                                 "iterations": None, "iterations_note": "SciPy exposes evaluations, not iteration count",
                                 "runtime_s": time.perf_counter() - begun, "initial_objective": float(.5 * r0 @ r0), "final_objective": float(result.cost),
                                 "measurement_objective": measurement_objective, "prior_objective": prior_objective,
                                 "optimality": float(result.optimality), "active_bounds": result.active_mask.tolist(), "max_nfev": opts["max_nfev"],
                                 "ftol": 1e-12, "xtol": 1e-12, "gtol": 1e-12, "x_scale": "jac", "loss": "linear",
                                 "positive_floor_m": baseline.POSITIVE_FLOOR_M if problem.mode == "joint" else None}
            outcome["diagnostics"] = {"residuals_m": metres.tolist(), "residuals_normalized": normalized.tolist(), "prior_residuals_normalized": prior.tolist(),
                                      "range_rmse_m": float(np.sqrt(np.mean(metres ** 2))), "max_abs_residual_m": float(np.max(np.abs(metres))),
                                      "measurement_objective": measurement_objective, "prior_objective": prior_objective,
                                      "jacobian": jacobian_diagnostics(result.x, problem), "augmented_jacobian": jacobian_diagnostics(result.x, problem, augmented=True)}
        except Exception as exc:
            outcome["solver"] = {"status": None, "message": f"{type(exc).__name__}: {exc}", "nfev": None, "njev": None, "iterations": None,
                                 "runtime_s": time.perf_counter() - begun, "initial_objective": None, "final_objective": None,
                                 "measurement_objective": None, "prior_objective": None}
        outcomes.append(outcome)
    return outcomes


def solve_experiment(experiment, options=None, *, initial_geometries=None):
    validate_experiment(experiment)
    opts = validate_options(options)
    inputs, truth = experiment["estimator_input"], experiment["truth"]
    surveyed = truth["beacons"] if opts["mode"] == "known_map" else None
    problem = build_problem(inputs["observations"], inputs["times_s"], display_times_s=truth["times_s"], surveyed_beacons=surveyed,
                            **{k: opts[k] for k in ("mode", "timing_model", "knot_spacing_s", "prior_sigma_m")})
    truth_knots = truth_positions(experiment["config"], problem.times_s)
    xtruth = problem.pack(truth_knots, truth["beacons"])
    if initial_geometries is None and opts["initialization"] == "truth_near":
        rng = np.random.default_rng(opts["seed"])
        initial_geometries = []
        for _ in range(opts["starts"]):
            x = xtruth + rng.normal(0., .15, xtruth.shape)
            if opts["mode"] == "joint":
                x[[-6, -4, -1]] = np.maximum(x[[-6, -4, -1]], .01)
            initial_geometries.append(problem.geometry(x))
    outcomes = fit_observations(inputs["observations"], inputs["times_s"], display_times_s=truth["times_s"],
                                surveyed_beacons=surveyed, initial_geometries=initial_geometries, **opts)
    finite = [s for s in outcomes if s["estimate"] is not None and np.isfinite(s["solver"]["final_objective"])]
    preferred = [s for s in finite if s["success"]] or finite
    chosen = min(preferred, key=lambda s: s["solver"]["final_objective"]) if preferred else None
    truth_ping = {"trajectory": truth["ping_positions"], "beacons": truth["beacons"]}
    groups, low_groups, classifications = [], [], []
    for outcome in outcomes:
        if outcome["estimate"] is not None:
            diag = outcome["diagnostics"]
            diag["evaluation"] = baseline.evaluate_geometry(outcome["estimate"], truth, opts["mode"])
            diag["ping_evaluation"] = baseline.evaluate_geometry({"trajectory": outcome["estimate"]["ping_trajectory"], "beacons": outcome["estimate"]["beacons"]}, truth_ping, opts["mode"])
        evaluation = outcome["diagnostics"].get("evaluation")
        geometry = bool(evaluation and evaluation["raw"]["position_max_error_m"] < 1e-5 and max(evaluation["raw"]["beacon_errors_m"]) < 1e-5)
        ranges = bool(evaluation and outcome["diagnostics"]["max_abs_residual_m"] < 1e-7)
        classification = "failed" if outcome["estimate"] is None else "not_converged" if not outcome["success"] else "geometry_recovered" if geometry else "converged_geometry_inaccurate"
        outcome["diagnostics"].update(geometric_recovery=geometry, range_recovery=ranges, recovery_classification=classification)
        classifications.append({"index": outcome["index"], "optimizer_converged": outcome["success"], "geometric_recovery": geometry, "range_recovery": ranges, "classification": classification})
        if outcome["estimate"] is not None:
            signature = np.r_[np.ravel(outcome["estimate"]["trajectory"]), np.ravel(outcome["estimate"]["beacons"])]
            if not any(np.sqrt(np.mean((signature - ref) ** 2)) < 1e-3 for ref in groups):
                groups.append(signature)
            if ranges and not any(np.sqrt(np.mean((signature - ref) ** 2)) < 1e-3 for ref in low_groups):
                low_groups.append(signature)
    projected = problem.geometry(xtruth)
    display_floor = np.linalg.norm(np.asarray(projected["trajectory"]) - np.asarray(truth["trajectory"]), axis=1)
    actual_weights = _weights(problem.times_s, np.clip(np.asarray(truth["ping_times_s"]), problem.times_s[0], problem.times_s[-1]))
    # Actual truth may lie outside estimator time domain when clocks are wrong;
    # actual-time floor uses endpoint holds, explicitly reported here.
    ping_floor = np.linalg.norm(actual_weights @ truth_knots - np.asarray(truth["ping_positions"]).reshape((-1, 3)), axis=1)
    timing_errors = np.linalg.norm(np.asarray(truth["ping_positions"]).reshape((-1, 3)) - np.asarray(truth["grouped_positions"]).reshape((-1, 3)), axis=1)
    summary = lambda values: {"position_rmse_m": float(np.sqrt(np.mean(values ** 2))) if len(values) else None,
                              "position_max_error_m": float(np.max(values)) if len(values) else None}
    rank = jacobian_diagnostics(xtruth, problem)
    warnings = []
    if not rank["full_column_rank"]:
        warnings.append("Truth-projected measurement Jacobian is rank deficient; priors do not establish measurement observability")
    if chosen and not chosen["diagnostics"]["jacobian"]["full_column_rank"]:
        warnings.append("Fitted measurement Jacobian is rank deficient")
    if rank["condition_number"] and rank["condition_number"] > baseline.WEAK_CONDITION_THRESHOLD:
        warnings.append("Truth-projected measurement condition number exceeds disclosed heuristic 1000")
    diagnostics = {"truth_jacobian": rank, "truth_augmented_jacobian": jacobian_diagnostics(xtruth, problem, augmented=True),
                   "failure_count": sum(not s["success"] for s in outcomes), "distinct_solution_count": len(groups), "distinct_low_residual_solution_count": len(low_groups),
                   "solution_grouping_rms_threshold_m": 1e-3, "low_residual_max_abs_threshold_m": 1e-7,
                   "solution_grouping": "Raw canonical display trajectory and beacon RMS; sampled starts only",
                   "start_recovery_outcomes": classifications, "geometric_recovery_count": sum(s["geometric_recovery"] for s in classifications),
                   "range_recovery_count": sum(s["range_recovery"] for s in classifications), "geometric_recovery": bool(chosen and chosen["diagnostics"]["geometric_recovery"]),
                   "acceptance_geometry_tolerance_m": 1e-5, "acceptance_max_range_residual_m": 1e-7,
                   "surveyed_map_source": "Synthetic truth map explicitly supplied as surveyed knowledge" if surveyed is not None else None,
                   "timing_approximation": {**summary(timing_errors), "position_errors_m": timing_errors.tolist(), "definition": "Actual ping truth position minus truth at common cycle start; independent of fitted interpolation and priors"},
                   "truth_interpolation_floor": {"display": summary(display_floor), "pings": summary(ping_floor),
                                                 "display_position_rmse_m": summary(display_floor)["position_rmse_m"], "ping_position_rmse_m": summary(ping_floor)["position_rmse_m"],
                                                 "definition": "Truth sampled at estimator knots and linearly interpolated; representation discrepancy, not a guaranteed optimization lower bound",
                                                 "actual_times_outside_domain": int(np.sum((np.asarray(truth["ping_times_s"]) < problem.times_s[0]) | (np.asarray(truth["ping_times_s"]) > problem.times_s[-1]))),
                                                 "outside_domain_rule": "Endpoint hold for floor evaluation only; estimator residual times always lie in knot domain"},
                   "trajectory_model": {"type": "piecewise_linear", "knot_times_s": problem.times_s.tolist(), "knot_count": len(problem.times_s), "parameter_count": problem.parameter_count,
                                        "domain_s": [float(problem.times_s[0]), float(problem.times_s[-1])], "max_knots": MAX_KNOTS,
                                        "knot_rule": "Cycle grid plus endpoint coverage" if opts["knot_spacing_s"] == 0 else "Requested spacing from domain start with final endpoint included",
                                        "domain_rule": "Union of cycle, display, and assumed ping times; actual/delivery times excluded",
                                        "grouping_rule": "estimator_input.times_s[epoch]", "prior_sigma_m": opts["prior_sigma_m"],
                                        "prior_definition": "Interior knot minus time-weighted interpolation of neighbors, xy metres divided by prior_sigma_m; zero disables",
                                        "prior_residual_count": 2 * len(problem.prior_matrix)},
                   "initialization_source": "Explicit saved compatible starts" if initial_geometries is not None and opts["initialization"] != "truth_near" else opts["initialization"],
                   "weak_condition_threshold": baseline.WEAK_CONDITION_THRESHOLD,
                   "ambiguity": "Local measurement rank does not prove global uniqueness; d>0, beacon2 y>0 and h>0 select canonical branches. Priors are assumptions.", "warnings": warnings}
    run = {"schema_version": SCHEMA_VERSION, "experiment": copy.deepcopy(experiment), "options": opts, "status": chosen["status"] if chosen else "failed",
           "selected_start": chosen["index"] if chosen else None, "starts": outcomes, "diagnostics": diagnostics,
           "software_versions": reference._package_versions()}
    validate_run(run)
    return run


@_format_errors
def validate_run(run):
    if not isinstance(run, dict) or run.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("M3 run requires schema_version 3.0")
    json.dumps(run, allow_nan=False)
    validate_experiment(run["experiment"])
    if validate_options(run["options"]) != run["options"]:
        raise ValueError("Saved run options must include normalized defaults")
    if not isinstance(run.get("diagnostics"), dict) or not isinstance(run.get("starts"), list):
        raise ValueError("Run requires object diagnostics and list starts")
    count = len(run["experiment"]["truth"]["times_s"])
    ping_count = len(run["experiment"]["estimator_input"]["observations"])
    if run.get("status") not in ("pending", "running", "failed", "success", "not_converged"):
        raise ValueError("Invalid M3 run status")
    if run["starts"] and len(run["starts"]) != run["options"]["starts"]:
        raise ValueError("Completed run must retain every requested start")
    indices = []
    for start in run["starts"]:
        index = start["index"]
        if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index in indices:
            raise ValueError("Start indices must be unique nonnegative integers")
        indices.append(index)
        if start.get("status") not in ("failed", "success", "not_converged") or not isinstance(start.get("success"), bool):
            raise ValueError("Invalid start outcome")
        if start["success"] != (start["status"] == "success") or (start.get("estimate") is None) != (start["status"] == "failed"):
            raise ValueError("Start status, convergence and estimate contradict each other")
        for key in ("initial", "estimate"):
            geometry = start.get(key)
            if geometry is None:
                continue
            _array(geometry["trajectory"], (count, 3), key + " trajectory")
            _array(geometry["beacons"], (4, 3), key + " beacons")
            if "knot_times_s" in geometry:
                knots = np.asarray(geometry["knot_times_s"], dtype=float)
                if knots.ndim != 1 or not 2 <= len(knots) <= MAX_KNOTS or not np.all(np.isfinite(knots)) or np.any(np.diff(knots) <= 0):
                    raise ValueError("Invalid geometry knot times")
                _array(geometry["knot_trajectory"], (len(knots), 3), key + " knots")
                if key == "estimate" and not np.allclose(np.asarray(geometry["knot_trajectory"])[:, 2], 0., atol=1e-12, rtol=0):
                    raise ValueError("Estimated knots must be planar")
            for field in ("ping_trajectory", "assumed_ping_trajectory"):
                if field in geometry:
                    _array(np.asarray(geometry[field]).reshape((-1, 3)), (ping_count, 3), field)
    if run.get("selected_start") is not None and run["selected_start"] not in indices:
        raise ValueError("selected_start must reference a saved start")
    selected = next((s for s in run["starts"] if s["index"] == run.get("selected_start")), None)
    if run["status"] in ("success", "not_converged") and (selected is None or selected["status"] != run["status"]):
        raise ValueError("Run outcome must match a selected finite start")
    if selected is not None and (selected["estimate"] is None or run["status"] in ("failed", "pending", "running")):
        raise ValueError("Selected start must have a finite estimate and matching terminal status")
    if run["starts"] and set(indices) != set(range(run["options"]["starts"])):
        raise ValueError("Start indices must cover every requested attempt")
    return run
