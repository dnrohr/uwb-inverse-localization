"""Reproducible synthetic UWB range experiments.

The estimator input contains only timestamps, measured ranges, beacon IDs, and
assumed standard deviations. Ground truth is kept in a separate top-level
section of the returned experiment for evaluation and visualization.
"""

from __future__ import annotations

import json
import math
import platform
import time
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping

import numpy as np

SCENARIOS = ("informative", "straight_line", "narrow_coverage", "nearly_collinear")
PATH_TYPES = ("line", "circle", "arc", "rectangle", "figure_eight", "waypoint")
# These bounds apply to custom paths; legacy reference configurations retain
# their original normalization and exact observations.
PATH_LIMITS = {"scale": [0.01, 100.0], "size_m": [0.01, 100.0],
               "coordinate_m": [-1000.0, 1000.0], "duration_s": [0.01, 3600.0],
               "waypoint_count": [2, 100], "samples": [8, 100]}
SCHEMA_VERSION = "1.0"
BEACON_MAP = np.array(
    [[0.0, 0.0, 3.0], [10.0, 0.0, 3.0], [1.0, 8.0, 3.0], [11.0, 9.0, 3.0]],
    dtype=float,
)
COORDINATE_CONVENTION = (
    "Right-handed Cartesian frame in metres. The planar tag trajectory is z=0. "
    "For the informative map, beacon b0=(0,0,h), b1=(d,0,h), b2 has positive y, "
    "and all four beacons share height h>0. Beacon IDs are zero-based."
)


class ExperimentFormatError(ValueError):
    """Raised when an experiment does not conform to the version 1 format."""


def _std_vector(value: Any, name: str, *, allow_zero: bool) -> list[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        values = [float(value)] * 4
    elif isinstance(value, (list, tuple)) and len(value) == 4:
        values = [float(x) for x in value]
    else:
        raise ValueError(f"{name} must be a number or a list of four numbers")
    lower_ok = (lambda x: x >= 0.0) if allow_zero else (lambda x: x > 0.0)
    if not all(math.isfinite(x) and lower_ok(x) for x in values):
        qualifier = "nonnegative" if allow_zero else "positive"
        raise ValueError(f"all {name} values must be finite and {qualifier}")
    return values


def _normalise_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    supplied = dict(config or {})
    allowed = {"scenario", "samples", "duration_s", "noise_std_m", "assumed_std_m", "seed", "path"}
    unknown = set(supplied) - allowed
    if unknown:
        raise ValueError(f"unsupported configuration keys: {', '.join(sorted(unknown))}")
    scenario = supplied.get("scenario", "informative")
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {', '.join(SCENARIOS)}")
    samples = supplied.get("samples", 32)
    if isinstance(samples, bool) or not isinstance(samples, int) or not 8 <= samples <= 100:
        raise ValueError("samples must be an integer from 8 through 100")
    duration_s = float(supplied.get("duration_s", 20.0))
    if not math.isfinite(duration_s) or duration_s <= 0.0:
        raise ValueError("duration_s must be finite and positive")
    seed = supplied.get("seed", 7)
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    noise = _std_vector(supplied.get("noise_std_m", 0.0), "noise_std_m", allow_zero=True)
    assumed = _std_vector(supplied.get("assumed_std_m", 0.05), "assumed_std_m", allow_zero=False)
    normalized = {
        "scenario": scenario,
        "samples": samples,
        "duration_s": duration_s,
        "noise_std_m": noise,
        "assumed_std_m": assumed,
        "seed": seed,
    }
    if "path" in supplied:
        normalized["path"] = _normalise_path(supplied["path"])
        normalized["duration_s"] = _bounded_number(supplied.get("duration_s", 20.0),
                                                   "custom path duration_s", 0.01, 3600)
    return normalized


def _bounded_number(value: Any, name: str, lower: float, upper: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result) or not lower <= result <= upper:
        raise ValueError(f"{name} must be finite and from {lower} through {upper}")
    return result


def _pair(value: Any, name: str, lower: float, upper: float) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{name} must contain two numbers")
    return [_bounded_number(item, name, lower, upper) for item in value]


def _normalise_path(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("path must be an object")
    kind = value.get("type", "rectangle")
    if kind not in PATH_TYPES:
        raise ValueError(f"path.type must be one of {', '.join(PATH_TYPES)}")
    allowed = {"type", "center_m", "scale", "rotation_deg", "size_m"}
    if kind in ("circle", "arc"):
        allowed.add("start_angle_deg")
    if kind == "arc":
        allowed.add("arc_angle_deg")
    if kind == "waypoint":
        allowed = (allowed - {"size_m"}) | {"waypoints_m"}
    if set(value) - allowed:
        raise ValueError("unsupported path keys: " + ", ".join(sorted(set(value) - allowed)))
    result = {
        "type": kind,
        "center_m": _pair(value.get("center_m", [5.0, 4.0]), "path.center_m", -1000, 1000),
        "scale": _bounded_number(value.get("scale", 1.0), "path.scale", 0.01, 100),
        "rotation_deg": _bounded_number(value.get("rotation_deg", 0.0), "path.rotation_deg", -360, 360),
    }
    if kind != "waypoint":
        default_size = [7.0, 7.0] if kind in ("circle", "arc") else [7.0, 5.6]
        result["size_m"] = _pair(value.get("size_m", default_size), "path.size_m", 0.01, 100)
        if kind in ("circle", "arc") and result["size_m"][0] != result["size_m"][1]:
            raise ValueError("circle/arc size_m dimensions must be equal (diameter)")
    if kind in ("circle", "arc"):
        result["start_angle_deg"] = _bounded_number(value.get("start_angle_deg", 0.0), "path.start_angle_deg", -360, 360)
    if kind == "arc":
        angle = _bounded_number(value.get("arc_angle_deg", 180.0), "path.arc_angle_deg", -360, 360)
        if abs(angle) < 0.01:
            raise ValueError("path.arc_angle_deg magnitude must be at least 0.01")
        result["arc_angle_deg"] = angle
    if kind == "waypoint":
        points = value.get("waypoints_m", [[-3.5, -2.8], [3.5, -2.8], [3.5, 2.8], [-3.5, 2.8]])
        if not isinstance(points, (list, tuple)) or not 2 <= len(points) <= 100:
            raise ValueError("path.waypoints_m must contain 2 through 100 local xy points")
        result["waypoints_m"] = [_pair(point, "path.waypoints_m", -1000, 1000) for point in points]
        if np.sum(np.linalg.norm(np.diff(result["waypoints_m"], axis=0), axis=1)) <= 0:
            raise ValueError("waypoint path must have positive length")
    return result


def _custom_path(spec: Mapping[str, Any], count: int) -> tuple[np.ndarray, float]:
    """Return planar samples and traveled length, including closed-loop endpoint.

    size_m is full width/height; circle/arc use width as their diameter.
    Waypoints are local xy offsets before scale, rotation, and translation.
    Figure-eight arclength uses a fixed 16,385-point polyline approximation.
    """
    kind = spec["type"]
    width, height = spec.get("size_m", [7.0, 5.6])
    if kind in ("circle", "arc"):
        angle = np.deg2rad(spec["start_angle_deg"])
        sweep = np.deg2rad(spec.get("arc_angle_deg", 360.0))
        theta = angle + np.linspace(0.0, sweep, count)
        xy = width / 2 * np.column_stack((np.cos(theta), np.sin(theta)))
        length = width / 2 * abs(sweep)
    else:
        if kind == "line":
            vertices = np.array([[-width / 2, 0.0], [width / 2, 0.0]])
        elif kind == "rectangle":
            vertices = np.array([[-width / 2, -height / 2], [width / 2, -height / 2],
                                 [width / 2, height / 2], [-width / 2, height / 2],
                                 [-width / 2, -height / 2]])
        elif kind == "figure_eight":
            theta = np.linspace(0.0, 2 * np.pi, 16385)
            vertices = np.column_stack((width / 2 * np.sin(theta), height / 2 * np.sin(2 * theta)))
        else:
            vertices = np.asarray(spec["waypoints_m"], dtype=float)
        # Duplicate adjacent waypoints are harmless pauses of zero duration;
        # remove them so arclength interpolation has strictly increasing knots.
        vertices = vertices[np.r_[True, np.linalg.norm(np.diff(vertices, axis=0), axis=1) > 0]]
        length = float(np.sum(np.linalg.norm(np.diff(vertices, axis=0), axis=1)))
        xy = _sample_polyline_at_constant_speed(vertices, count)
    rotation = np.deg2rad(spec["rotation_deg"])
    matrix = np.array([[np.cos(rotation), -np.sin(rotation)], [np.sin(rotation), np.cos(rotation)]])
    xy = (xy * spec["scale"]) @ matrix.T + spec["center_m"]
    return np.column_stack((xy, np.zeros(count))), float(length * spec["scale"])


def path_metadata(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Disclose traveled arclength, speed and interpolation separately from inputs."""
    cfg = _normalise_config(config)
    if "path" in cfg:
        kind = cfg["path"]["type"]
        _, length = _custom_path(cfg["path"], cfg["samples"])
        approximation = "16385-point polyline arclength" if kind == "figure_eight" else "analytic circle arclength" if kind in ("circle", "arc") else "exact piecewise-linear arclength"
    else:
        kind = cfg["scenario"]
        if kind in ("informative", "nearly_collinear"):
            length = 25.2
        elif kind == "straight_line":
            length = 7.0
        else:
            dense_u = np.linspace(-1.0, 1.0, max(1001, cfg["samples"] * 20))
            vertices = np.column_stack((0.35 * dense_u, 0.25 * np.sin(np.pi * dense_u)))
            length = float(np.sum(np.linalg.norm(np.diff(vertices, axis=0), axis=1)))
        approximation = "reference path arclength; narrow coverage uses dense polyline"
    return {"type": kind, "length_m": length, "speed_m_s": length / cfg["duration_s"],
            "sample_arclength_m": length / (cfg["samples"] - 1),
            "constant_arclength_speed": True, "parameterization": approximation,
            "endpoint_included": True, "tag_plane_z_m": 0.0,
            "display_interpolation": "lines joining fitted samples are display chords, not the continuous path",
            "size_convention": "full width/height; line uses width as length; circle and arc use equal diameters; waypoint coordinates are local offsets"}


def _informative_path(count: int) -> np.ndarray:
    """Sample a spatially broad rectangle-like waypoint loop at constant speed."""
    waypoints = np.array(
        [[1.5, 1.2, 0.0], [8.5, 1.2, 0.0], [8.5, 6.8, 0.0], [1.5, 6.8, 0.0], [1.5, 1.2, 0.0]],
        dtype=float,
    )
    lengths = np.linalg.norm(np.diff(waypoints, axis=0), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
    distance = np.linspace(0.0, cumulative[-1], count)
    result = np.empty((count, 3), dtype=float)
    for axis in range(3):
        result[:, axis] = np.interp(distance, cumulative, waypoints[:, axis])
    return result


def _sample_polyline_at_constant_speed(points: np.ndarray, count: int) -> np.ndarray:
    """Sample a piecewise-linear path evenly by traveled distance."""
    segment_lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(segment_lengths)))
    if cumulative[-1] <= 0.0:
        raise ValueError("trajectory path must have positive length")
    distance = np.linspace(0.0, cumulative[-1], count)
    return np.column_stack(
        [np.interp(distance, cumulative, points[:, axis]) for axis in range(points.shape[1])]
    )


def _trajectory(scenario: str, count: int) -> np.ndarray:
    if scenario in ("informative", "nearly_collinear"):
        return _informative_path(count)
    u = np.linspace(-1.0, 1.0, count)
    if scenario == "straight_line":
        return np.column_stack((1.0 + 7.0 * (u + 1.0) / 2.0, np.full(count, 2.0), np.zeros(count)))
    if scenario == "narrow_coverage":
        # Keep the prior short sinusoidal footprint, but parameterize its
        # piecewise-linear approximation by arclength for constant sample speed.
        dense_u = np.linspace(-1.0, 1.0, max(1001, count * 20))
        path = np.column_stack(
            (4.5 + 0.35 * dense_u, 3.5 + 0.25 * np.sin(np.pi * dense_u), np.zeros_like(dense_u))
        )
        return _sample_polyline_at_constant_speed(path, count)
    raise AssertionError("scenario is validated before trajectory construction")


def _beacons(scenario: str) -> np.ndarray:
    beacons = BEACON_MAP.copy()
    if scenario == "nearly_collinear":
        # All four beacons remain above the tag plane; y spread is intentionally tiny.
        # Preserve the gauge convention b0.y = b1.y = 0.
        beacons[:, 1] = np.array([0.0, 0.0, 0.004, 0.006])
    return beacons


def _package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {"python": platform.python_version()}
    for package in ("numpy", "scipy", "Flask", "plotly"):
        try:
            versions[package.lower()] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package.lower()] = None
    return versions


def generate_experiment(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Generate a deterministic, synchronized, four-beacon range experiment.

    ``noise_std_m`` accepts one standard deviation shared by all beacons or a
    four-element sequence. Zero means exact ranges. ``assumed_std_m`` follows
    the same shape rules but must be strictly positive.
    """
    cfg = _normalise_config(config)
    path = (_custom_path(cfg["path"], cfg["samples"])[0] if "path" in cfg
            else _trajectory(cfg["scenario"], cfg["samples"]))
    beacons = _beacons(cfg["scenario"])
    times = np.linspace(0.0, cfg["duration_s"], cfg["samples"], dtype=float)
    distances = np.linalg.norm(path[:, None, :] - beacons[None, :, :], axis=2)
    rng = np.random.default_rng(cfg["seed"])
    noise = rng.normal(loc=0.0, scale=np.asarray(cfg["noise_std_m"])[None, :], size=distances.shape)
    ranges = distances + noise
    observations = [
        {
            "epoch": epoch,
            "beacon_id": beacon_id,
            "actual_time_s": float(times[epoch]),
            "assumed_time_s": float(times[epoch]),
            "range_m": float(ranges[epoch, beacon_id]),
            "sigma_m": float(cfg["assumed_std_m"][beacon_id]),
        }
        for epoch in range(cfg["samples"])
        for beacon_id in range(4)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "config": cfg,
        "units": "metres, seconds",
        "coordinate_convention": COORDINATE_CONVENTION,
        "truth": {
            "times_s": times.tolist(),
            "trajectory": path.tolist(),
            "beacons": beacons.tolist(),
        },
        "estimator_input": {
            "times_s": times.tolist(),
            "observations": observations,
        },
        "software_versions": _package_versions(),
    }


def _reject_constant(token: str) -> None:
    raise ExperimentFormatError(f"invalid JSON numeric constant: {token}")


def _validate_experiment(data: Any) -> None:
    if not isinstance(data, dict):
        raise ExperimentFormatError("experiment must be a JSON object")
    required = {"schema_version", "config", "units", "coordinate_convention", "truth", "estimator_input", "software_versions"}
    if set(data) != required:
        raise ExperimentFormatError("experiment has missing or unsupported top-level fields")
    if data["schema_version"] != SCHEMA_VERSION:
        raise ExperimentFormatError(f"unsupported schema_version: {data['schema_version']!r}")
    try:
        config = _normalise_config(data["config"])
    except (TypeError, ValueError) as exc:
        raise ExperimentFormatError(f"invalid config: {exc}") from exc
    if config != data["config"]:
        raise ExperimentFormatError("config must contain the normalized, complete configuration")
    truth = data["truth"]
    estimator = data["estimator_input"]
    if not isinstance(truth, dict) or set(truth) != {"times_s", "trajectory", "beacons"}:
        raise ExperimentFormatError("truth must contain times_s, trajectory, and beacons")
    if not isinstance(estimator, dict) or set(estimator) != {"times_s", "observations"}:
        raise ExperimentFormatError("estimator_input must contain times_s and observations")
    n = config["samples"]
    try:
        times = np.asarray(truth["times_s"], dtype=float)
        trajectory = np.asarray(truth["trajectory"], dtype=float)
        beacons = np.asarray(truth["beacons"], dtype=float)
        estimator_times = np.asarray(estimator["times_s"], dtype=float)
    except (TypeError, ValueError) as exc:
        raise ExperimentFormatError("coordinates and times must be numeric arrays") from exc
    if times.shape != (n,) or estimator_times.shape != (n,) or trajectory.shape != (n, 3) or beacons.shape != (4, 3):
        raise ExperimentFormatError("truth coordinates/times must have shapes N, N×3, and 4×3")
    if not all(np.isfinite(x).all() for x in (times, estimator_times, trajectory, beacons)):
        raise ExperimentFormatError("times and coordinates must be finite")
    if not np.array_equal(times, estimator_times):
        raise ExperimentFormatError("estimator and truth epoch times must match")
    observations = estimator["observations"]
    if not isinstance(observations, list) or len(observations) != n * 4:
        raise ExperimentFormatError("observations must contain exactly four beacon records per epoch")
    for i, obs in enumerate(observations):
        if not isinstance(obs, dict) or set(obs) != {"epoch", "beacon_id", "actual_time_s", "assumed_time_s", "range_m", "sigma_m"}:
            raise ExperimentFormatError(f"observation {i} has an invalid record shape")
        epoch, beacon_id = obs["epoch"], obs["beacon_id"]
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch != i // 4:
            raise ExperimentFormatError(f"observation {i} has invalid epoch ordering")
        if isinstance(beacon_id, bool) or not isinstance(beacon_id, int) or beacon_id != i % 4:
            raise ExperimentFormatError(f"observation {i} has invalid beacon ordering")
        numeric = [obs[key] for key in ("actual_time_s", "assumed_time_s", "range_m", "sigma_m")]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in numeric):
            raise ExperimentFormatError(f"observation {i} contains a non-finite/non-numeric value")
        if obs["sigma_m"] <= 0.0:
            raise ExperimentFormatError(f"observation {i} sigma_m must be positive")
        if obs["sigma_m"] != config["assumed_std_m"][beacon_id]:
            raise ExperimentFormatError(f"observation {i} sigma_m disagrees with config")
        if obs["actual_time_s"] != times[epoch] or obs["assumed_time_s"] != times[epoch]:
            raise ExperimentFormatError(f"observation {i} timestamps disagree with epoch time")


def _validate_json_values(value: Any, location: str = "$") -> None:
    """Reject values that JSON cannot represent strictly and portably."""
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ExperimentFormatError(f"non-finite number at {location}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_values(item, f"{location}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ExperimentFormatError(f"non-string object key at {location}")
            _validate_json_values(item, f"{location}.{key}")
        return
    raise ExperimentFormatError(f"unsupported JSON value at {location}: {type(value).__name__}")


def _validate_payload(data: Any) -> None:
    """Accept either a standalone experiment or a saved run containing one.

    Run envelopes intentionally allow additional result and diagnostic fields;
    persistence must retain failed runs (including an empty ``starts`` list and
    an ``error`` message) so they can be inspected later.
    """
    _validate_json_values(data)
    if not isinstance(data, dict):
        raise ExperimentFormatError("saved payload must be a JSON object")
    if "config" in data and "estimator_input" in data:
        _validate_experiment(data)
        return
    if data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("experiment"), dict):
        raise ExperimentFormatError("expected a version 1.0 experiment or run envelope containing experiment")
    if not isinstance(data.get("starts"), list):
        raise ExperimentFormatError("saved run envelope must contain a starts list")
    _validate_experiment(data["experiment"])
    if not isinstance(data.get("options", {}), dict):
        raise ExperimentFormatError("saved run options must be an object")
    if not isinstance(data.get("diagnostics", {}), dict):
        raise ExperimentFormatError("saved run diagnostics must be an object")
    indices = set()
    for start in data["starts"]:
        if not isinstance(start, dict):
            raise ExperimentFormatError("every saved start must be an object")
        index = start.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index in indices:
            raise ExperimentFormatError("saved starts need unique nonnegative integer indices")
        indices.add(index)
        for field in ("solver", "diagnostics"):
            if not isinstance(start.get(field, {}), dict):
                raise ExperimentFormatError(f"saved start {field} must be an object")
        for field in ("initial", "estimate"):
            geometry = start.get(field)
            if geometry is None:
                continue
            if not isinstance(geometry, dict):
                raise ExperimentFormatError(f"saved {field} geometry must be an object or null")
            try:
                trajectory = np.asarray(geometry.get("trajectory"), dtype=float)
                beacons = np.asarray(geometry.get("beacons"), dtype=float)
            except (TypeError, ValueError) as exc:
                raise ExperimentFormatError("saved geometry must be numeric") from exc
            n = data["experiment"]["config"]["samples"]
            if trajectory.shape != (n, 3) or beacons.shape != (4, 3):
                raise ExperimentFormatError("saved geometry must have trajectory Nx3 and beacon 4x3 shapes")
            if not np.isfinite(trajectory).all() or not np.isfinite(beacons).all():
                raise ExperimentFormatError("saved geometry must be finite")
    selected = data.get("selected_start")
    if selected is not None and (isinstance(selected, bool) or not isinstance(selected, int) or selected not in indices):
        raise ExperimentFormatError("selected_start must refer to a saved start or be null")


def _replace_with_retry(temporary: Path, target: Path) -> None:
    """Retry atomic replacement when a Windows reader briefly denies deletion."""
    for attempt in range(30):
        try:
            temporary.replace(target)
            return
        except PermissionError:
            if attempt == 29:
                raise
            time.sleep(0.02 + min(attempt, 5) * 0.01)


def save_json(path: str | Path, data: dict[str, Any]) -> None:
    """Validate and save an experiment or run envelope as strict JSON."""
    _validate_payload(data)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n"
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    _replace_with_retry(temporary, target)


def load_json(path: str | Path) -> dict[str, Any]:
    """Load an experiment or saved run; reject NaN/Infinity and invalid schemas."""
    try:
        with Path(path).open("r", encoding="utf-8") as stream:
            data = json.load(stream, parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ExperimentFormatError(f"invalid JSON: {exc}") from exc
    _validate_payload(data)
    return data
