"""Height models with explicit physical assumptions and coordinate gauges.

Measurement fitting is truth-free. Shared heights, soft height priors and
below-plane bounds are distinct models; rank diagnostics separate each prior.
"""
from __future__ import annotations

import copy
import json
import math
import time
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from . import m3
from . import experiments as reference

SCHEMA_VERSION = "4.0"
MAX_KNOTS = m3.MAX_KNOTS
FLOOR = 1e-6


def _vector(value, count, name, positive=False):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = [value] * count
    if not isinstance(value, (list, tuple)) or len(value) != count:
        raise ValueError(f"{name} must be scalar or have beacon-count entries")
    return [m3._number(v, name, 1e-6 if positive else 0., 1000. if positive else 100.) for v in value]


@m3._format_errors
def normalize_config(config=None):
    supplied = copy.deepcopy(dict(config or {}))
    layout = dict(supplied.pop("beacon_layout", {}))
    height = dict(supplied.pop("truth_height", {}))
    count = layout.get("count", 4)
    if isinstance(count, bool) or not isinstance(count, int) or not 3 <= count <= 8:
        raise ValueError("beacon_layout.count must be an integer from 3 through 8")
    if set(layout) - {"count", "geometry", "height_m", "height_spread_m", "baseline_scale", "coordinates_m"}:
        raise ValueError("Unsupported beacon_layout keys")
    geometry = layout.get("geometry", "equal")
    if geometry not in ("equal", "diverse", "near_collinear", "collinear"):
        raise ValueError("Invalid beacon geometry")
    layout = {"count": count, "geometry": geometry,
              "height_m": m3._number(layout.get("height_m", 3.), "height_m", -1000., 1000.),
              "height_spread_m": m3._number(layout.get("height_spread_m", 1.), "height_spread_m", 0., 100.),
              "baseline_scale": m3._number(layout.get("baseline_scale", 1.), "baseline_scale", .001, 100.),
              **({"coordinates_m": layout["coordinates_m"]} if "coordinates_m" in layout else {})}
    if "coordinates_m" in layout:
        layout["coordinates_m"] = m3._array(layout["coordinates_m"], (count, 3), "coordinates_m").tolist()
    if set(height) - {"type", "offset_m", "amplitude_m", "tilt_deg"}:
        raise ValueError("Unsupported truth_height keys")
    kind = height.get("type", "planar")
    if kind not in ("planar", "tilted", "excursion", "spatial"):
        raise ValueError("Invalid truth_height.type")
    height = {"type": kind, "offset_m": m3._number(height.get("offset_m", 0.), "offset_m", -1000., 1000.),
              "amplitude_m": m3._number(height.get("amplitude_m", .3), "amplitude_m", 0., 100.),
              "tilt_deg": m3._number(height.get("tilt_deg", 10.), "tilt_deg", -80., 80.)}
    acq = dict(supplied.pop("acquisition", {}))
    order = acq.pop("beacon_order", list(range(count)))
    strides = acq.pop("beacon_every_cycles", [1] * count)
    noise = _vector(supplied.pop("noise_std_m", 0.), count, "noise_std_m")
    sigma = _vector(supplied.pop("assumed_std_m", .05), count, "assumed_std_m", True)
    cfg = m3.normalize_config({**supplied, "acquisition": acq, "noise_std_m": noise[0], "assumed_std_m": sigma[0]})
    if not isinstance(order, (list, tuple)) or any(isinstance(v, bool) or not isinstance(v, int) for v in order) or sorted(order) != list(range(count)):
        raise ValueError("beacon_order must contain every beacon ID exactly once")
    if not isinstance(strides, (list, tuple)) or len(strides) != count or any(isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 100 for v in strides):
        raise ValueError("beacon_every_cycles requires beacon-count integers from 1 through 100")
    cfg["noise_std_m"], cfg["assumed_std_m"] = noise, sigma
    cfg["acquisition"]["beacon_order"], cfg["acquisition"]["beacon_every_cycles"] = list(order), list(strides)
    cfg["beacon_layout"], cfg["truth_height"] = layout, height
    return cfg


@m3._format_errors
def validate_options(options=None):
    supplied = dict(options or {})
    extra = {"tag_height_model": "fixed", "beacon_height_model": "shared", "fixed_tag_z_m": 0.,
             "height_prior_sigma_m": .2, "below_beacons": False}
    selected = {key: supplied.pop(key, value) for key, value in extra.items()}
    opts = m3.validate_options(supplied)
    if selected["tag_height_model"] not in ("fixed", "shared", "soft", "free"):
        raise ValueError("Invalid tag_height_model")
    if selected["beacon_height_model"] not in ("shared", "independent"):
        raise ValueError("Invalid beacon_height_model")
    selected["fixed_tag_z_m"] = m3._number(selected["fixed_tag_z_m"], "fixed_tag_z_m", -1000., 1000.)
    selected["height_prior_sigma_m"] = m3._number(selected["height_prior_sigma_m"], "height_prior_sigma_m", 1e-6, 1000.)
    if not isinstance(selected["below_beacons"], bool):
        raise ValueError("below_beacons must be boolean")
    opts.update(selected)
    if opts["mode"] == "joint" and opts["tag_height_model"] in ("soft", "free") and opts["beacon_height_model"] == "independent" and opts["below_beacons"]:
        raise ValueError("Joint independent beacon heights with free/soft tags require coupled below-every-beacon inequalities; these nonlinear bounds are unsupported. Disable below_beacons or use shared beacon plane/known map.")
    return opts


def _proxy_config(cfg):
    proxy = {k: copy.deepcopy(v) for k, v in cfg.items() if k not in ("beacon_layout", "truth_height")}
    proxy["noise_std_m"], proxy["assumed_std_m"] = cfg["noise_std_m"][0], cfg["assumed_std_m"][0]
    proxy["acquisition"]["beacon_order"], proxy["acquisition"]["beacon_every_cycles"] = [0, 1, 2, 3], [1] * 4
    return proxy


def beacon_coordinates(cfg):
    layout = cfg["beacon_layout"]
    if "coordinates_m" in layout:
        return np.asarray(layout["coordinates_m"], dtype=float)
    count = layout["count"]
    xy = np.array([[0., 0.], [10., 0.], [1., 8.], [11., 9.], [-2., 5.], [6., 11.], [13., 4.], [5., -3.]])[:count]
    if layout["geometry"] in ("near_collinear", "collinear"):
        xy[:, 0] = np.linspace(0., 10., count)
        xy[:, 1] = 0. if layout["geometry"] == "collinear" else .003 * np.arange(count) ** 2
    xy *= layout["baseline_scale"]
    z = np.full(count, layout["height_m"])
    if layout["geometry"] == "diverse":
        z += layout["height_spread_m"] * np.linspace(-.5, .5, count)
    return np.column_stack((xy, z))


def truth_positions(cfg, times_s):
    positions = m3.truth_positions(cfg, times_s)
    height = cfg["truth_height"]
    t = np.clip(np.asarray(times_s) / cfg["duration_s"], 0., 1.)
    z = np.full(len(t), height["offset_m"])
    if height["type"] == "tilted":
        # A geometric plane, including during stops/reversal, not a time ramp.
        z += np.tan(np.deg2rad(height["tilt_deg"])) * (positions[:, 0] - 5.)
    elif height["type"] == "excursion":
        z += height["amplitude_m"] * np.sin(2 * np.pi * t)
    elif height["type"] == "spatial":
        z += height["amplitude_m"] * (np.sin(2 * np.pi * t) + .45 * np.sin(6 * np.pi * t + .2))
    positions[:, 2] = z
    return positions


def generate_experiment(config=None):
    cfg = normalize_config(config)
    exp = m3.generate_experiment(_proxy_config(cfg))
    exp["schema_version"], exp["config"] = SCHEMA_VERSION, cfg
    b = beacon_coordinates(cfg); count = len(b)
    cycles = np.asarray(exp["estimator_input"]["times_s"])
    acq = cfg["acquisition"]
    rng = np.random.default_rng(cfg["seed"] + 101)
    noise = np.random.default_rng(cfg["seed"]).normal(0., cfg["noise_std_m"], (len(cycles), count))
    jitter = rng.uniform(-acq["jitter_s"], acq["jitter_s"], (len(cycles), count))
    clock = rng.uniform(-acq["timestamp_jitter_s"], acq["timestamp_jitter_s"], (len(cycles), count))
    missing = rng.random((len(cycles), count)) < acq["missing_probability"]
    observations, ping_times, positions, grouped = [], [], [], []
    for epoch, cycle in enumerate(cycles):
        for slot, beacon in enumerate(acq["beacon_order"]):
            if epoch % acq["beacon_every_cycles"][beacon] or missing[epoch, beacon]:
                continue
            actual = float(cycle + slot * acq["spacing_s"] + jitter[epoch, beacon])
            p = truth_positions(cfg, [actual])[0]
            observations.append({"epoch": epoch, "beacon_id": beacon, "actual_time_s": actual,
                                 "assumed_time_s": actual + acq["timestamp_offset_s"] + float(clock[epoch, beacon]),
                                 "delivery_time_s": actual + acq["delivery_latency_s"], "range_m": float(np.linalg.norm(p - b[beacon]) + noise[epoch, beacon]),
                                 "sigma_m": cfg["assumed_std_m"][beacon]})
            ping_times.append(actual); positions.append(p.tolist()); grouped.append(truth_positions(cfg, [cycle])[0].tolist())
    truth = exp["truth"]
    exp["estimator_input"]["observations"] = observations
    truth.update(trajectory=truth_positions(cfg, truth["times_s"]).tolist(), beacons=b.tolist(), ping_times_s=ping_times,
                 ping_positions=positions, grouped_positions=grouped)
    mt = np.asarray(truth["motion"]["times_s"])
    spatial = truth_positions(cfg, mt)
    truth["motion"]["spatial_speed_m_s"] = np.linalg.norm(np.gradient(spatial, mt, axis=0), axis=1).tolist()
    truth["motion"]["height_parameterization"] = "tilted: z=offset+tan(tilt)*(x-5m); excursion: offset+A*sin(2pi*t/T); spatial adds .45A*sin(6pi*t/T+.2); endpoint times hold"
    exp["coordinate_convention"] = "World Cartesian metres for synthetic truth/surveyed maps; estimator joint gauge is separately disclosed in run diagnostics"
    validate_experiment(exp)
    return exp


def _observations(observations, times, count):
    seen = set()
    for o in observations:
        epoch, beacon = o["epoch"], o["beacon_id"]
        if isinstance(epoch, bool) or not isinstance(epoch, int) or not 0 <= epoch < len(times) or isinstance(beacon, bool) or not isinstance(beacon, int) or not 0 <= beacon < count:
            raise ValueError("Invalid epoch or beacon ID")
        if (epoch, beacon) in seen:
            raise ValueError("Duplicate cycle/beacon observation")
        seen.add((epoch, beacon))
        for key in ("assumed_time_s", "range_m", "sigma_m"):
            m3._number(o[key], key, 1e-6 if key == "sigma_m" else -math.inf)


@m3._format_errors
def validate_experiment(exp):
    if exp.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("M4 experiment requires schema4.0")
    json.dumps(exp, allow_nan=False)
    cfg = normalize_config(exp["config"])
    if cfg != exp["config"]:
        raise ValueError("M4 configuration must contain normalized defaults")
    truth, inputs = exp["truth"], exp["estimator_input"]
    times, cycles = np.asarray(truth["times_s"]), np.asarray(inputs["times_s"])
    for vector in (times, cycles):
        if vector.ndim != 1 or not 2 <= len(vector) <= 100 or not np.all(np.isfinite(vector)) or np.any(np.diff(vector) <= 0):
            raise ValueError("Times require2–100 finite increasing values")
    if len(times) != cfg["samples"]:
        raise ValueError("Display count disagrees with samples")
    count = cfg["beacon_layout"]["count"]
    m3._array(truth["trajectory"], (len(times), 3), "trajectory")
    m3._array(truth["beacons"], (count, 3), "beacons")
    obs = inputs["observations"]
    _observations(obs, cycles, count)
    for field in ("ping_positions", "grouped_positions"):
        m3._array(np.asarray(truth[field]).reshape((-1, 3)), (len(obs), 3), field)
    m3._array(truth["ping_times_s"], (len(obs),), "ping_times_s")
    for i, o in enumerate(obs):
        for field in ("actual_time_s", "delivery_time_s"):
            m3._number(o[field], field, -math.inf)
        if o["actual_time_s"] != truth["ping_times_s"][i]:
            raise ValueError("Actual ping times disagree with truth")
    motion = truth["motion"]; mt = np.asarray(motion["times_s"])
    if mt.ndim != 1 or len(mt) < 2 or not np.all(np.isfinite(mt)) or np.any(np.diff(mt) <= 0):
        raise ValueError("Invalid motion times")
    for field in ("speed_m_s", "signed_speed_m_s", "acceleration_m_s2", "spatial_speed_m_s"):
        m3._array(motion[field], (len(mt),), field)
    if exp["units"] != "metres, seconds":
        raise ValueError("Invalid units")
    return exp


def _spatial(opts):
    return opts["tag_height_model"] in ("soft", "free")


def _canonical(trajectory, beacons, opts):
    p, b = np.asarray(trajectory, dtype=float).copy(), np.asarray(beacons, dtype=float).copy()
    if opts["mode"] == "known_map":
        return p, b, {"rotation_xyz": np.eye(3).tolist(), "translation_xyz_m": [0., 0., 0.]}
    if _spatial(opts):
        ex = b[1] - b[0]
        if np.linalg.norm(ex) <= FLOOR:
            raise ValueError("Joint3D gauge requires distinct first two beacons")
        ex /= np.linalg.norm(ex)
        ey = b[2] - b[0]; ey -= ex * (ey @ ex)
        if np.linalg.norm(ey) <= FLOOR:
            raise ValueError("Joint3D gauge requires a noncollinear first-three beacon triangle; reorder/edit coordinates or use known map")
        ey /= np.linalg.norm(ey); rotation = np.column_stack((ex, ey, np.cross(ex, ey)))
        origin = b[0].copy()
    else:
        delta = b[1, :2] - b[0, :2]
        if np.linalg.norm(delta) <= FLOOR:
            raise ValueError("Joint planar gauge requires a nonzero horizontal first baseline")
        ex = delta / np.linalg.norm(delta); rotation = np.eye(3)
        rotation[:2, :2] = [[ex[0], -ex[1]], [ex[1], ex[0]]]
        origin = np.r_[b[0, :2], 0.]
        if opts["tag_height_model"] == "shared":
            origin[2] = np.mean(p[:, 2]) - opts["fixed_tag_z_m"]
    p, b = (p - origin) @ rotation, (b - origin) @ rotation
    return p, b, {"rotation_xyz": rotation.tolist(), "translation_xyz_m": (-origin @ rotation).tolist()}


def gauge_metadata(opts):
    if opts["mode"] == "known_map":
        name = "Surveyed world frame; no gauge freedoms are fitted"
    elif _spatial(opts):
        name = "Proper3D rigid gauge: b0 origin, b1 positive x, b2 in positive-y xy plane; first-three reference plane z=0"
    else:
        name = "Planar xy translation/rotation gauge: b0xy=0, b1y=0, b1x>0; tag datum supplies z origin"
    return {"description": name, "tag_shared_absolute_height": "Gauge fixed to fixed_tag_z_m; absolute shared tag height is not recovered" if opts["mode"] == "joint" and opts["tag_height_model"] == "shared" else "Shared world z estimated" if opts["tag_height_model"] == "shared" else None,
            "height_prior_plane": "Surveyed world z datum" if opts["mode"] == "known_map" else "Fitted first-three beacon reference plane; not surveyed world z or ground" if _spatial(opts) else "Fixed horizontal tag datum",
            "remaining_reflections": ("Coplanar surveyed maps can admit tag reflections across the beacon plane; noncoplanar surveyed coordinates generally break that symmetry. Bounds and priors may select branches; rank alone does not prove uniqueness." if opts["mode"] == "known_map" else "Distances permit reflected map/tag solutions; no reflection is removed by alignment. In 3D, reflection across the first-three plane preserves canonical anchors; supported below bounds may select a branch."),
            "local_rank_note": "After valid gauge removal, measurement rank deficits disclose first-order information loss; they may indicate continuous ambiguity or singular sensitivity, requiring additional analysis"}


@dataclass
class HeightProblem:
    times_s: np.ndarray
    display_times_s: np.ndarray
    epochs: np.ndarray
    beacon_ids: np.ndarray
    ranges_m: np.ndarray
    sigma_m: np.ndarray
    assumed_times_s: np.ndarray
    weights: np.ndarray
    options: dict
    tag_offset: np.ndarray
    beacon_offset: np.ndarray
    tag_basis: np.ndarray
    beacon_basis: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    prior_matrix: np.ndarray
    surveyed_beacons: np.ndarray | None

    @property
    def parameter_count(self):
        return len(self.lower)

    @property
    def beacon_count(self):
        return len(self.beacon_offset)

    def unpack(self, parameters):
        x = np.asarray(parameters, dtype=float)
        return self.tag_offset + np.einsum("kcn,n->kc", self.tag_basis, x), self.beacon_offset + np.einsum("bcn,n->bc", self.beacon_basis, x)

    def pack(self, trajectory, beacons, *, project=False):
        p = m3._array(trajectory, self.tag_offset.shape, "Initial knots")
        b = m3._array(beacons, self.beacon_offset.shape, "Initial beacons")
        matrix = np.vstack((self.tag_basis.reshape((-1, self.parameter_count)), self.beacon_basis.reshape((-1, self.parameter_count))))
        target = np.r_[(p - self.tag_offset).ravel(), (b - self.beacon_offset).ravel()]
        norm = np.sum(matrix ** 2, axis=0)
        x = matrix.T @ target / norm
        if not project and not np.allclose(matrix @ x, target, atol=1e-8, rtol=1e-9):
            raise ValueError("Initial geometry violates selected height model or canonical gauge")
        if project:
            x = np.maximum(np.minimum(x, np.where(np.isfinite(self.upper), self.upper - FLOOR, self.upper)), np.where(np.isfinite(self.lower), self.lower + FLOOR, self.lower))
        if not np.all(np.isfinite(x)):
            raise ValueError("Initial parameters must be finite")
        return x

    def geometry(self, parameters):
        p, b = self.unpack(parameters)
        return {"trajectory": (m3._weights(self.times_s, self.display_times_s) @ p).tolist(), "beacons": b.tolist(),
                "knot_times_s": self.times_s.tolist(), "knot_trajectory": p.tolist(), "ping_trajectory": (self.weights @ p).tolist(),
                "assumed_ping_trajectory": (m3._weights(self.times_s, self.assumed_times_s) @ p).tolist()}


@m3._format_errors
def build_problem(observations, times_s, *, beacon_count=None, display_times_s=None, surveyed_beacons=None, **options):
    opts = validate_options(options)
    cycles = np.asarray(times_s, dtype=float); display = cycles if display_times_s is None else np.asarray(display_times_s, dtype=float)
    for t in (cycles, display):
        if t.ndim != 1 or len(t) < 2 or not np.all(np.isfinite(t)) or np.any(np.diff(t) <= 0):
            raise ValueError("Times must be finite and increasing")
    count = len(surveyed_beacons) if beacon_count is None and surveyed_beacons is not None else beacon_count
    if isinstance(count, bool) or not isinstance(count, int) or not 3 <= count <= 8:
        raise ValueError("Explicit beacon_count3–8 is required")
    _observations(observations, cycles, count)
    surveyed = m3._array(surveyed_beacons, (count, 3), "Surveyed map") if opts["mode"] == "known_map" else None
    if opts["mode"] == "joint" and surveyed_beacons is not None:
        raise ValueError("Joint fitting receives no surveyed map")
    epochs = np.asarray([o["epoch"] for o in observations], dtype=int)
    assumed = np.asarray([o["assumed_time_s"] for o in observations])
    domain = np.r_[cycles, display, assumed]; lo, hi = float(domain.min()), float(domain.max())
    spacing = opts["knot_spacing_s"]
    if spacing:
        intervals = int(math.ceil((hi - lo) / spacing))
        if intervals + 1 > MAX_KNOTS:
            raise ValueError(f"Knot count exceeds{MAX_KNOTS}")
        knots = np.r_[lo + np.arange(intervals) * spacing, hi]
    else:
        knots = np.unique(np.r_[lo, cycles, hi])
    if len(knots) > MAX_KNOTS:
        raise ValueError("Too many knots")
    used = assumed if opts["timing_model"] == "timestamp_aware" else cycles[epochs]
    tag_offset = np.zeros((len(knots), 3)); boffset = np.zeros((count, 3))
    columns = []; bounds = []
    def column(tag_entries=(), beacon_entries=(), lower=-np.inf, upper=np.inf):
        tag = np.zeros_like(tag_offset); beacon = np.zeros_like(boffset)
        for k, axis in tag_entries: tag[k, axis] = 1.
        for k, axis in beacon_entries: beacon[k, axis] = 1.
        columns.append((tag, beacon)); bounds.append((lower, upper))
    tagmodel = opts["tag_height_model"]
    if tagmodel in ("fixed", "shared"):
        tag_offset[:, 2] = opts["fixed_tag_z_m"]
        for k in range(len(knots)):
            for axis in (0, 1): column([(k, axis)])
        if tagmodel == "shared" and opts["mode"] == "known_map":
            tag_offset[:, 2] = 0.
            column([(k, 2) for k in range(len(knots))], upper=float(surveyed[:, 2].min()) - FLOOR if opts["below_beacons"] else np.inf)
    else:
        zupper = float(surveyed[:, 2].min()) - FLOOR if opts["below_beacons"] and surveyed is not None else -FLOOR if opts["below_beacons"] else np.inf
        for k in range(len(knots)):
            for axis in range(3): column([(k, axis)], upper=zupper if axis == 2 else np.inf)
    if surveyed is not None:
        boffset[:] = surveyed
        if tagmodel == "fixed" and opts["below_beacons"] and opts["fixed_tag_z_m"] >= float(surveyed[:, 2].min()) - FLOOR:
            raise ValueError("Fixed tag height violates the independently enabled below-beacon bound")
    else:
        column(beacon_entries=[(1, 0)], lower=FLOOR)
        column(beacon_entries=[(2, 0)])
        column(beacon_entries=[(2, 1)], lower=FLOOR if _spatial(opts) else -np.inf)
        for beacon in range(3, count):
            for axis in range(3 if _spatial(opts) and opts["beacon_height_model"] == "independent" else 2):
                column(beacon_entries=[(beacon, axis)])
        if not _spatial(opts):
            zlower = opts["fixed_tag_z_m"] + FLOOR if opts["below_beacons"] else -np.inf
            if opts["beacon_height_model"] == "shared":
                column(beacon_entries=[(beacon, 2) for beacon in range(count)], lower=zlower)
            else:
                for beacon in range(count): column(beacon_entries=[(beacon, 2)], lower=zlower)
    tbasis, bbasis = np.stack([c[0] for c in columns], axis=2), np.stack([c[1] for c in columns], axis=2)
    prior = np.zeros((len(knots) - 2, len(knots))) if opts["prior_sigma_m"] else np.zeros((0, len(knots)))
    for row in range(len(prior)):
        left, right = knots[row + 1] - knots[row], knots[row + 2] - knots[row + 1]
        prior[row, row:row + 3] = [-right / (left + right), 1., -left / (left + right)]
    if len(prior): prior /= opts["prior_sigma_m"]
    return HeightProblem(knots, display, epochs, np.asarray([o["beacon_id"] for o in observations], dtype=int),
                         np.asarray([o["range_m"] for o in observations]), np.asarray([o["sigma_m"] for o in observations]), assumed,
                         m3._weights(knots, used), opts, tag_offset, boffset, tbasis, bbasis,
                         np.asarray(bounds)[:, 0], np.asarray(bounds)[:, 1], prior, surveyed)


def measurement_residuals(parameters, problem):
    p, b = problem.unpack(parameters)
    return (np.linalg.norm(problem.weights @ p - b[problem.beacon_ids], axis=1) - problem.ranges_m) / problem.sigma_m


def prior_components(parameters, problem):
    p, _ = problem.unpack(parameters)
    motion = (problem.prior_matrix @ p).ravel()
    height = (p[:, 2] - problem.options["fixed_tag_z_m"]) / problem.options["height_prior_sigma_m"] if problem.options["tag_height_model"] == "soft" else np.zeros(0)
    return motion, height


def residuals(parameters, problem):
    motion, height = prior_components(parameters, problem)
    return np.r_[measurement_residuals(parameters, problem), motion, height]


def measurement_jacobian(parameters, problem):
    p, b = problem.unpack(parameters)
    delta = problem.weights @ p - b[problem.beacon_ids]
    direction = delta / (np.maximum(np.linalg.norm(delta, axis=1), np.finfo(float).tiny) * problem.sigma_m)[:, None]
    basis = np.einsum("mk,kcn->mcn", problem.weights, problem.tag_basis) - problem.beacon_basis[problem.beacon_ids]
    return np.einsum("mc,mcn->mn", direction, basis)


def jacobian(parameters, problem):
    motion = np.einsum("rk,kcn->rcn", problem.prior_matrix, problem.tag_basis).reshape((-1, problem.parameter_count))
    height = problem.tag_basis[:, 2] / problem.options["height_prior_sigma_m"] if problem.options["tag_height_model"] == "soft" else np.zeros((0, problem.parameter_count))
    return np.vstack((measurement_jacobian(parameters, problem), motion, height))


def jacobian_diagnostics(parameters, problem, *, augmented=False):
    scale = max(float(np.median(np.abs(problem.ranges_m))) if len(problem.ranges_m) else 1., 1.)
    matrix = jacobian(parameters, problem) if augmented else measurement_jacobian(parameters, problem)
    spectrum = np.linalg.svd(matrix * scale, compute_uv=False)
    cutoff = float(spectrum[0] * 1e-8) if len(spectrum) else 0.
    rank = int(np.sum(spectrum > cutoff)); full = rank == problem.parameter_count
    return {"rank": rank, "parameter_count": problem.parameter_count, "measurement_count": len(problem.ranges_m), "prior_residual_count": len(matrix) - len(problem.ranges_m),
            "full_column_rank": full, "condition_number": float(spectrum[0] / spectrum[-1]) if full else None,
            "singular_values": spectrum.tolist(), "relative_tolerance": 1e-8, "absolute_tolerance": cutoff, "parameter_scale_m": scale,
            "scaling": "All coordinates in metres; normalized residual Jacobian with respect to theta/median-range scale",
            "interpretation": "Augmented rank includes physical/model assumptions, not new measurement information" if augmented else "Local measurement-only rank after gauge removal; full rank does not prove global uniqueness"}


def _project_geometry(problem, p, b):
    p, b, _ = _canonical(p, b, problem.options)
    return problem.geometry(problem.pack(p, b, project=True))


def _initial(problem, rng, index):
    scale = max(float(np.median(np.abs(problem.ranges_m))) if len(problem.ranges_m) else 1., 1.)
    if problem.surveyed_beacons is not None:
        b = problem.surveyed_beacons.copy()
    else:
        template = np.array([[0., 0.], [1.1, 0.], [.1, .9], [1.2, 1.05], [-.2, .5], [.6, 1.1], [1.3, .4], [.5, -.3]])[:problem.beacon_count]
        b = np.column_stack((template * scale, np.full(problem.beacon_count, .3 * scale)))
        if index:
            b[2:, :2] += rng.normal(0., .08 * scale, (len(b) - 2, 2))
        if problem.options["beacon_height_model"] == "independent":
            b[:, 2] += np.linspace(-.1, .1, len(b)) * scale
    table = np.full((len(problem.times_s), problem.beacon_count), scale)
    model_times = problem.weights @ problem.times_s
    for beacon in range(problem.beacon_count):
        mask = problem.beacon_ids == beacon
        if np.any(mask):
            order = np.argsort(model_times[mask], kind="stable")
            table[:, beacon] = np.interp(problem.times_s, model_times[mask][order], problem.ranges_m[mask][order])
    a = 2 * (b[1:] - b[0]); rhs = np.sum(b[1:] ** 2, axis=1) - np.sum(b[0] ** 2) - (table[:, 1:] ** 2 - table[:, :1] ** 2)
    if _spatial(problem.options) or problem.options["tag_height_model"] == "shared":
        p = np.linalg.lstsq(a, rhs.T, rcond=None)[0].T
        if np.linalg.matrix_rank(a) < 3:
            p[:, :2] = np.linalg.lstsq(a[:, :2], (rhs - a[:, 2] * problem.options["fixed_tag_z_m"]).T, rcond=None)[0].T
            horizontal = np.sum((p[:, None, :2] - b[None, :, :2]) ** 2, axis=2)
            gap = np.sqrt(np.maximum(np.mean(table ** 2 - horizontal, axis=1), .01))
            sign = 1. if index % 2 and not problem.options["below_beacons"] else -1.
            p[:, 2] = np.mean(b[:, 2]) + sign * gap
    else:
        z = problem.options["fixed_tag_z_m"]
        xy = np.linalg.lstsq(a[:, :2], (rhs - a[:, 2] * z).T, rcond=None)[0].T
        p = np.column_stack((xy, np.full(len(xy), z)))
    if index:
        p += rng.normal(0., .08 * scale, p.shape)
    return _project_geometry(problem, p, b)


def fit_observations(observations, times_s, *, beacon_count=None, display_times_s=None, surveyed_beacons=None, initial_geometries=None, **options):
    opts = validate_options(options)
    problem = build_problem(observations, times_s, beacon_count=beacon_count, display_times_s=display_times_s, surveyed_beacons=surveyed_beacons, **opts)
    if initial_geometries is not None and len(initial_geometries) != opts["starts"]:
        raise ValueError("Supply every requested initial geometry")
    rng = np.random.default_rng(opts["seed"]); outcomes = []
    for index in range(opts["starts"]):
        initial = copy.deepcopy(initial_geometries[index]) if initial_geometries is not None else _initial(problem, rng, index)
        start = {"index": index, "status": "failed", "success": False, "initial": initial, "estimate": None, "solver": {}, "diagnostics": {}}
        begun = time.perf_counter()
        try:
            x0 = problem.pack(initial.get("knot_trajectory", initial.get("trajectory")), initial["beacons"])
            r0 = residuals(x0, problem)
            if not len(problem.ranges_m): raise ValueError("No retained observations; priors alone are not fitted")
            result = least_squares(residuals, x0, jac=jacobian, args=(problem,), bounds=(problem.lower, problem.upper), method="trf",
                                   x_scale="jac", ftol=1e-12, xtol=1e-12, gtol=1e-12, max_nfev=opts["max_nfev"])
            mr = measurement_residuals(result.x, problem); motion, height = prior_components(result.x, problem); metres = mr * problem.sigma_m
            objectives = {"measurement_objective": float(.5 * mr @ mr), "motion_prior_objective": float(.5 * motion @ motion), "height_prior_objective": float(.5 * height @ height),
                          "prior_objective": float(.5 * motion @ motion + .5 * height @ height)}
            start.update(status="success" if result.success else "not_converged", success=bool(result.success), estimate=problem.geometry(result.x))
            start["solver"] = {"method": "scipy.optimize.least_squares/trf", "status": int(result.status), "message": str(result.message), "nfev": int(result.nfev),
                               "njev": int(result.njev) if result.njev is not None else None, "iterations": None, "iterations_note": "SciPy reports evaluations, not iteration count",
                               "runtime_s": time.perf_counter() - begun, "initial_objective": float(.5 * r0 @ r0), "final_objective": float(result.cost), "optimality": float(result.optimality),
                               "active_bounds": result.active_mask.tolist(), "max_nfev": opts["max_nfev"], "ftol": 1e-12, "xtol": 1e-12, "gtol": 1e-12, "x_scale": "jac", "loss": "linear", **objectives}
            start["diagnostics"] = {"residuals_m": metres.tolist(), "residuals_normalized": mr.tolist(), "motion_prior_residuals_normalized": motion.tolist(), "height_prior_residuals_normalized": height.tolist(),
                                    "range_rmse_m": float(np.sqrt(np.mean(metres ** 2))), "max_abs_residual_m": float(np.max(np.abs(metres))),
                                    "jacobian": jacobian_diagnostics(result.x, problem), "augmented_jacobian": jacobian_diagnostics(result.x, problem, augmented=True), **objectives}
        except Exception as exc:
            start["solver"] = {"status": None, "message": f"{type(exc).__name__}: {exc}", "nfev": None, "njev": None, "iterations": None, "runtime_s": time.perf_counter() - begun,
                               "initial_objective": None, "final_objective": None, "measurement_objective": None, "prior_objective": None}
        outcomes.append(start)
    return outcomes


def plane_diagnostics(points):
    p = np.asarray(points, dtype=float); centroid = p.mean(axis=0)
    _, singular, vt = np.linalg.svd(p - centroid, full_matrices=True)
    normal = vt[-1]
    if normal[2] < 0.: normal = -normal
    departure = (p - centroid) @ normal
    u, v = vt[0], np.cross(normal, vt[0]); extent = max(float(np.max(np.linalg.norm(p - centroid, axis=1))), .5)
    corners = np.array([centroid + extent * (su * u + sv * v) for su, sv in ((-1,-1),(1,-1),(1,1),(-1,1))])
    return {"normal": normal.tolist(), "centroid": centroid.tolist(), "offset_m": float(-centroid @ normal), "rms_m": float(np.sqrt(np.mean(departure ** 2))),
            "max_abs_m": float(np.max(np.abs(departure))), "rms_departure_m": float(np.sqrt(np.mean(departure ** 2))), "max_departure_m": float(np.max(np.abs(departure))),
            "plane_corners": corners.tolist(), "point_cloud_rank": int(np.sum(singular > (singular[0] * 1e-8 if len(singular) and singular[0] else 0.))),
            "interpretation": "Best-fit-plane departure; normal is underdetermined for collinear/stationary point clouds"}


def _error(p, b, tp, tb):
    pe = np.linalg.norm(p - tp, axis=1); be = np.linalg.norm(b - tb, axis=1)
    return {"position_errors_m": pe.tolist(), "position_rmse_m": float(np.sqrt(np.mean(pe ** 2))), "position_max_error_m": float(np.max(pe)),
            "beacon_errors_m": be.tolist(), "map_rmse_m": float(np.sqrt(np.mean(be ** 2))), "height_error_m": float(np.mean(b[:, 2] - tb[:, 2]))}


def evaluate_geometry(estimate, truth, options=None):
    opts = validate_options(options); p, b = np.asarray(estimate["trajectory"]), np.asarray(estimate["beacons"])
    tp, tb = np.asarray(truth["trajectory"]), np.asarray(truth["beacons"])
    cp, cb, canonical = _canonical(tp, tb, opts)
    raw = _error(p, b, cp, cb)
    if opts["mode"] == "known_map":
        ap, ab = p.copy(), b.copy(); alignment = {"applied": False, "scale": 1., "reflection_allowed": False, "description": "Surveyed frame retained"}
    elif _spatial(opts):
        u, _, vt = np.linalg.svd((b - b.mean(axis=0)).T @ (tb - tb.mean(axis=0)))
        correction = np.eye(3); correction[-1, -1] = np.linalg.det(u @ vt)
        rotation = u @ correction @ vt; translation = tb.mean(axis=0) - b.mean(axis=0) @ rotation
        ap, ab = p @ rotation + translation, b @ rotation + translation
        alignment = {"applied": True, "scale": 1., "reflection_allowed": False, "rotation_xyz": rotation.tolist(), "translation_xyz_m": translation.tolist(),
                     "description": "Map-only proper3D rigid alignment; no metric scale or reflection"}
    else:
        u, _, vt = np.linalg.svd((b[:, :2] - b[:, :2].mean(axis=0)).T @ (tb[:, :2] - tb[:, :2].mean(axis=0)))
        correction = np.diag([1., np.linalg.det(u @ vt)]); rotation = u @ correction @ vt
        translation = tb[:, :2].mean(axis=0) - b[:, :2].mean(axis=0) @ rotation
        ap, ab = p.copy(), b.copy(); ap[:, :2] = p[:, :2] @ rotation + translation; ab[:, :2] = b[:, :2] @ rotation + translation
        ztranslation = float(np.mean(tp[:, 2]) - opts["fixed_tag_z_m"]) if opts["tag_height_model"] == "shared" else 0.
        ap[:, 2] += ztranslation; ab[:, 2] += ztranslation
        alignment = {"applied": True, "scale": 1., "reflection_allowed": False, "rotation_xy": rotation.tolist(), "translation_xy_m": translation.tolist(), "gauge_translation_z_m": ztranslation,
                     "description": "Proper planar rigid alignment; shared-tag absolute z gauge restored for world display only; no fitted tilt or metric scale"}
    return {"raw": raw, "aligned": _error(ap, ab, tp, tb), "alignment": alignment,
            "aligned_geometry": {"trajectory": ap.tolist(), "beacons": ab.tolist()}, "truth_canonical_transform": canonical}


def _problem(exp, opts):
    return build_problem(exp["estimator_input"]["observations"], exp["estimator_input"]["times_s"], beacon_count=exp["config"]["beacon_layout"]["count"],
                         display_times_s=exp["truth"]["times_s"], surveyed_beacons=exp["truth"]["beacons"] if opts["mode"] == "known_map" else None, **opts)


def compatible_initial_geometries(run, experiment, options=None):
    opts = validate_options(run["options"] if options is None else options); problem = _problem(experiment, opts)
    result = []
    for start in run["starts"][:opts["starts"]]:
        saved = start["initial"]
        points = np.asarray(saved["knot_trajectory"]); oldtimes = np.asarray(saved["knot_times_s"])
        p = np.column_stack([np.interp(problem.times_s, oldtimes, points[:, axis]) for axis in range(3)])
        b = np.asarray(saved["beacons"])
        # Conversion uses only the saved initial geometry and explicitly surveyed
        # knowledge in the destination known-map mode. Evaluation truth frames
        # must never supply an initialization transform.
        if problem.surveyed_beacons is not None:
            target = problem.surveyed_beacons
            u, _, vt = np.linalg.svd((b - b.mean(axis=0)).T @ (target - target.mean(axis=0)))
            correction = np.eye(3); correction[-1, -1] = np.linalg.det(u @ vt)
            rotation = u @ correction @ vt
            p = (p - b.mean(axis=0)) @ rotation + target.mean(axis=0)
            b = target.copy()
        elif not _spatial(opts) and _spatial(run["options"]):
            # The destination tag datum fixes the otherwise free z origin.
            shift = opts["fixed_tag_z_m"] - np.mean(p[:, 2])
            p[:, 2] += shift; b[:, 2] += shift
        result.append(_project_geometry(problem, p, b))
    if len(result) != opts["starts"]: raise ValueError("Source run has fewer starts than requested")
    return result


def solve_experiment(exp, options=None, initial_geometries=None, *, fit_callback=None):
    validate_experiment(exp); opts = validate_options(options); problem = _problem(exp, opts)
    truth = exp["truth"]
    tk_world = truth_positions(exp["config"], problem.times_s)
    evaluation_error = None
    try:
        tk, tb, transform = _canonical(tk_world, truth["beacons"], opts)
    except ValueError as exc:
        if opts["initialization"] == "truth_near" and initial_geometries is None:
            raise ValueError(f"Truth-near initialization cannot use this evaluation frame: {exc}") from exc
        evaluation_error = str(exc)
        # Evaluation metadata cannot prevent the independent measurement fit.
        # These placeholders are never represented as valid canonical truth.
        tk, tb = tk_world, np.asarray(truth["beacons"])
        transform = {"rotation_xyz": np.eye(3).tolist(), "translation_xyz_m": [0., 0., 0.]}
    xtruth = problem.pack(tk, tb, project=True)
    source = "explicit compatible saved starts" if initial_geometries is not None else opts["initialization"]
    if initial_geometries is None and opts["initialization"] == "truth_near":
        rng = np.random.default_rng(opts["seed"]); initial_geometries = []
        for _ in range(opts["starts"]):
            x = xtruth + rng.normal(0., .15, len(xtruth))
            x = np.maximum(np.minimum(x, np.where(np.isfinite(problem.upper), problem.upper - FLOOR, problem.upper)), np.where(np.isfinite(problem.lower), problem.lower + FLOOR, problem.lower))
            initial_geometries.append(problem.geometry(x))
    # Explicit extension point: alternate fitters consume only observations and
    # declared surveyed knowledge. Truth evaluation remains in this wrapper.
    fitter = fit_observations if fit_callback is None else fit_callback
    outcomes = fitter(exp["estimator_input"]["observations"], exp["estimator_input"]["times_s"], beacon_count=problem.beacon_count,
                                display_times_s=truth["times_s"], surveyed_beacons=problem.surveyed_beacons, initial_geometries=initial_geometries, **opts)
    finite = [s for s in outcomes if s["estimate"] is not None]; preferred = [s for s in finite if s["success"]] or finite
    chosen = min(preferred, key=lambda s: s["solver"]["final_objective"]) if preferred else None
    classifications = []; groups = []; lowgroups = []
    truthplane = plane_diagnostics(truth["trajectory"]); beaconplane = plane_diagnostics(truth["beacons"])
    for start in outcomes:
        diag = start["diagnostics"]
        if start["estimate"] is not None and evaluation_error is None:
            evaluation = evaluate_geometry(start["estimate"], truth, opts); diag["evaluation"] = evaluation
            ping_truth = {"trajectory": truth["ping_positions"], "beacons": truth["beacons"]}
            diag["ping_evaluation"] = evaluate_geometry({"trajectory": start["estimate"]["ping_trajectory"], "beacons": start["estimate"]["beacons"]}, ping_truth, opts)
            ap = np.asarray(evaluation["aligned_geometry"]["trajectory"]); tp = np.asarray(truth["trajectory"]); ze = ap[:, 2] - tp[:, 2]
            fitplane = plane_diagnostics(ap)
            diag["height"] = {"truth_planarity": truthplane, "fit_planarity": fitplane, "truth_beacon_planarity": beaconplane,
                              "times_s": truth["times_s"], "truth_z_m": tp[:, 2].tolist(), "estimate_z_m": ap[:, 2].tolist(), "z_errors_m": ze.tolist(),
                              "z_rmse_m": float(np.sqrt(np.mean(ze ** 2))), "world_z_rmse_m": float(np.sqrt(np.mean(ze ** 2))), "height_errors_m": ze.tolist(),
                              "world_z_span_m": float(np.ptp(ap[:, 2])), "best_fit_plane": fitplane,
                              "interpretation": "Matched world-z errors after allowed proper alignment; best-fit-plane departure distinguishes tilted planes from warped paths"}
        evaluation = diag.get("evaluation")
        geometry = bool(evaluation and evaluation["raw"]["position_max_error_m"] < 1e-5 and max(evaluation["raw"]["beacon_errors_m"]) < 1e-5)
        ranges = bool(evaluation and diag["max_abs_residual_m"] < 1e-7)
        classification = "failed" if start["estimate"] is None else "not_converged" if not start["success"] else "converged_evaluation_unavailable" if evaluation_error else "geometry_recovered" if geometry else "converged_geometry_inaccurate"
        diag.update(geometric_recovery=geometry, range_recovery=ranges, recovery_classification=classification)
        classifications.append({"index": start["index"], "optimizer_converged": start["success"], "geometric_recovery": geometry, "range_recovery": ranges, "classification": classification})
        if start["estimate"] is not None:
            signature = np.r_[np.ravel(start["estimate"]["trajectory"]), np.ravel(start["estimate"]["beacons"])]
            if not any(np.sqrt(np.mean((signature - r) ** 2)) < 1e-3 for r in groups): groups.append(signature)
            if ranges and not any(np.sqrt(np.mean((signature - r) ** 2)) < 1e-3 for r in lowgroups): lowgroups.append(signature)
    projected = problem.geometry(xtruth)
    cp, cb = np.asarray(truth["trajectory"]), np.asarray(truth["beacons"])
    if evaluation_error is None:
        cp, cb, _ = _canonical(cp, cb, opts)
    display_floor = np.linalg.norm(np.asarray(projected["trajectory"]) - cp, axis=1)
    pingpositions = np.asarray(truth["ping_positions"]).reshape((-1, 3))
    rotation, translation = np.asarray(transform["rotation_xyz"]), np.asarray(transform["translation_xyz_m"])
    canonical_pings = pingpositions @ rotation + translation
    actualweights = m3._weights(problem.times_s, np.clip(truth["ping_times_s"], problem.times_s[0], problem.times_s[-1]))
    projected_knots, _ = problem.unpack(xtruth)
    ping_floor = np.linalg.norm(actualweights @ projected_knots - canonical_pings, axis=1)
    timing = np.linalg.norm(pingpositions - np.asarray(truth["grouped_positions"]).reshape((-1, 3)), axis=1)
    summary = lambda x: {"position_rmse_m": float(np.sqrt(np.mean(x ** 2))) if len(x) else None, "position_max_error_m": float(np.max(x)) if len(x) else None}
    interpolation_display = np.linalg.norm(m3._weights(problem.times_s, problem.display_times_s) @ tk - cp, axis=1)
    interpolation_ping = np.linalg.norm(actualweights @ tk - canonical_pings, axis=1)
    projected_knots, projected_beacons = problem.unpack(xtruth)
    model_knot_errors = np.linalg.norm(projected_knots - tk, axis=1)
    model_beacon_errors = np.linalg.norm(projected_beacons - tb, axis=1)
    rank = jacobian_diagnostics(xtruth, problem) if evaluation_error is None else None
    warnings = []
    if evaluation_error: warnings.append(f"Canonical truth evaluation unavailable: {evaluation_error}; independent measurement fits retained")
    if rank and not rank["full_column_rank"]: warnings.append("Truth-projected measurement Jacobian is rank deficient; constraints/priors do not supply measurement observability")
    if chosen and not chosen["diagnostics"]["jacobian"]["full_column_rank"]: warnings.append("Fitted measurement Jacobian is rank deficient")
    if rank and rank["condition_number"] and rank["condition_number"] > 1000.: warnings.append("Truth-projected measurement condition number exceeds heuristic1000")
    constraints = {"tag_height_model": opts["tag_height_model"], "beacon_height_model": opts["beacon_height_model"], "below_beacons": opts["below_beacons"],
                   "below_rule": "Disabled" if not opts["below_beacons"] else "Every tag knot lies below the minimum surveyed beacon worldz" if opts["mode"] == "known_map" else "All fitted beacon heights above fixed/shared tag datum" if not _spatial(opts) else "Tag knots below fitted shared referenceplane z0",
                   "height_prior_enabled": opts["tag_height_model"] == "soft", "height_prior_sigma_m": opts["height_prior_sigma_m"] if opts["tag_height_model"] == "soft" else None,
                   "height_prior_mean_m": opts["fixed_tag_z_m"], "height_prior_plane": gauge_metadata(opts)["height_prior_plane"],
                   "separation_note": "Below inequalities select a branch; they neither fix a tag plane nor add range measurements",
                   "bounds_lower": [float(v) if np.isfinite(v) else None for v in problem.lower], "bounds_upper": [float(v) if np.isfinite(v) else None for v in problem.upper]}
    diagnostics = {"gauge": gauge_metadata(opts), "constraints": constraints, "truth_canonical_transform": transform if evaluation_error is None else None,
                   "evaluation_error": evaluation_error,
                   "canonical_truth_knots": {"times_s": problem.times_s.tolist(), "trajectory": tk.tolist(), "beacons": tb.tolist()} if evaluation_error is None else None,
                   "truth_jacobian": rank, "truth_augmented_jacobian": jacobian_diagnostics(xtruth, problem, augmented=True) if evaluation_error is None else None, "initialization_source": source,
                   "failure_count": sum(not s["success"] for s in outcomes), "start_recovery_outcomes": classifications,
                   "geometric_recovery_count": sum(c["geometric_recovery"] for c in classifications), "range_recovery_count": sum(c["range_recovery"] for c in classifications),
                   "geometric_recovery": bool(chosen and chosen["diagnostics"]["geometric_recovery"]), "distinct_solution_count": len(groups), "distinct_low_residual_solution_count": len(lowgroups),
                   "solution_grouping_rms_threshold_m": 1e-3, "low_residual_max_abs_threshold_m": 1e-7,
                   "acceptance_geometry_tolerance_m": 1e-5, "acceptance_max_range_residual_m": 1e-7,
                   "trajectory_model": {"type": "piecewise_linear", "knot_times_s": problem.times_s.tolist(), "knot_count": len(problem.times_s), "parameter_count": problem.parameter_count,
                                        "domain_s": [float(problem.times_s[0]), float(problem.times_s[-1])], "max_knots": MAX_KNOTS,
                                        "grouping_rule": "estimator_input.times_s[epoch]", "domain_rule": "Union cycle/display/assumed times; actual/delivery excluded",
                                        "prior_definition": "Time-weighted interior-knot deviation inxyz divided by prior_sigma_m; soft height is a separate prior"},
                   "truth_interpolation_floor": {"display": summary(display_floor), "pings": summary(ping_floor), "display_position_rmse_m": summary(display_floor)["position_rmse_m"], "ping_position_rmse_m": summary(ping_floor)["position_rmse_m"],
                                                 "available": evaluation_error is None, "definition": "Truth projected onto gauge and selected height model, then knots/interpolation; combined representation/model mismatch, not optimizer lower bound", "outside_domain_rule": "Endpoint hold only for actual-time evaluation"},
                   "truth_interpolation_only": {"display": summary(interpolation_display), "pings": summary(interpolation_ping), "available": evaluation_error is None,
                                                "definition": "Canonical truth sampled at knots and interpolated without imposing tag or beacon height models"},
                   "truth_model_projection": {"knot_position_rmse_m": float(np.sqrt(np.mean(model_knot_errors ** 2))), "beacon_rmse_m": float(np.sqrt(np.mean(model_beacon_errors ** 2))), "available": evaluation_error is None,
                                              "definition": "Selected tag/beacon height models projected at canonical truth knots, before time interpolation"},
                   "timing_approximation": {**summary(timing), "position_errors_m": timing.tolist()},
                   "height": {"truth_planarity": truthplane, "truth_beacon_planarity": beaconplane},
                   "surveyed_map_source": "Synthetic map explicitly supplied as surveyed knowledge" if opts["mode"] == "known_map" else None,
                   "weak_condition_threshold": 1000., "warnings": warnings, "ambiguity": gauge_metadata(opts)["remaining_reflections"]}
    run = {"schema_version": SCHEMA_VERSION, "experiment": copy.deepcopy(exp), "options": opts, "status": chosen["status"] if chosen else "failed",
           "selected_start": chosen["index"] if chosen else None, "starts": outcomes, "diagnostics": diagnostics, "software_versions": reference._package_versions()}
    validate_run(run)
    return run


@m3._format_errors
def validate_run(run):
    if run.get("schema_version") != SCHEMA_VERSION: raise ValueError("M4 run requires schema4.0")
    json.dumps(run, allow_nan=False); validate_experiment(run["experiment"])
    opts = validate_options(run["options"])
    if opts != run["options"]: raise ValueError("Saved options must contain normalized defaults")
    starts = run["starts"]
    if not isinstance(starts, list) or not isinstance(run["diagnostics"], dict) or run["status"] not in ("pending", "running", "failed", "success", "not_converged"):
        raise ValueError("Invalid run envelope")
    if starts and len(starts) != opts["starts"]: raise ValueError("Every requested start must be retained")
    indices = []; count = run["experiment"]["config"]["beacon_layout"]["count"]; displaycount = len(run["experiment"]["truth"]["times_s"]); pingcount = len(run["experiment"]["estimator_input"]["observations"])
    for start in starts:
        i = start["index"]
        if isinstance(i, bool) or not isinstance(i, int) or i < 0 or i in indices: raise ValueError("Invalid start index")
        indices.append(i)
        if start["status"] not in ("failed", "success", "not_converged") or not isinstance(start["success"], bool) or start["success"] != (start["status"] == "success"):
            raise ValueError("Invalid convergence outcome")
        if (start["estimate"] is None) != (start["status"] == "failed"): raise ValueError("Outcome and estimate disagree")
        for key in ("initial", "estimate"):
            geometry = start.get(key)
            if geometry is None: continue
            # Invalid initial geometry is retained on failures; strict JSON still
            # rules out NaN and infinity, while estimates must satisfy shapes.
            if key == "initial" and start["status"] == "failed": continue
            m3._array(geometry["trajectory"], (displaycount, 3), key + " trajectory")
            m3._array(geometry["beacons"], (count, 3), key + " beacons")
            times = np.asarray(geometry["knot_times_s"])
            if times.ndim != 1 or not 2 <= len(times) <= MAX_KNOTS or not np.all(np.isfinite(times)) or np.any(np.diff(times) <= 0): raise ValueError("Invalid knots")
            m3._array(geometry["knot_trajectory"], (len(times), 3), "knots")
            for field in ("ping_trajectory", "assumed_ping_trajectory"):
                m3._array(np.asarray(geometry[field]).reshape((-1, 3)), (pingcount, 3), field)
    if starts and set(indices) != set(range(opts["starts"])): raise ValueError("Every attempt index must be saved")
    selected = next((s for s in starts if s["index"] == run.get("selected_start")), None)
    if run["status"] in ("success", "not_converged") and (selected is None or selected["status"] != run["status"]): raise ValueError("Selected start must match run outcome")
    if run.get("selected_start") is not None and (selected is None or selected["estimate"] is None or run["status"] in ("pending", "running", "failed")): raise ValueError("Invalid selected start")
    if run["status"] == "failed" and any(s["estimate"] is not None for s in starts):
        raise ValueError("Failed run cannot discard a retained finite outcome")
    if any(s["estimate"] is not None for s in starts):
        problem = _problem(run["experiment"], opts)
        for start in starts:
            geometry = start["estimate"]
            if geometry is None: continue
            if not np.array_equal(np.asarray(geometry["knot_times_s"]), problem.times_s):
                raise ValueError("Estimated knots disagree with the disclosed solver grid")
            x = problem.pack(geometry["knot_trajectory"], geometry["beacons"])
            if np.any(x < problem.lower - 1e-8) or np.any(x > problem.upper + 1e-8):
                raise ValueError("Estimated geometry violates disclosed bounds")
            interpolated = problem.geometry(x)
            for field in ("trajectory", "ping_trajectory", "assumed_ping_trajectory"):
                if not np.allclose(geometry[field], interpolated[field], atol=1e-8, rtol=1e-9):
                    raise ValueError("Estimated positions disagree with saved knot interpolation")
    return run
