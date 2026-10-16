"""Bounded paired M3 timing sweeps, retained outcomes and offline exports."""
from __future__ import annotations
import copy
import csv
import io
import json
import math
from pathlib import Path
import uuid

import numpy as np

from . import m3
from .experiments import ExperimentFormatError, _validate_json_values, _reject_constant, _replace_with_retry

SCHEMA_VERSION = "3.0"
MODELS = ("timestamp_aware", "grouped")
FACTORS = ("speed_scale", "spacing_s", "knot_spacing_s", "timestamp_offset_s", "timestamp_jitter_s", "missing_probability", "beacon_every_cycles")
MAX_RUNS = 40
MAX_TOTAL_STARTS = 240
THRESHOLDS = {"geometry_max_m": .25, "exact_geometry_max_m": 1e-5, "normalized_residual_rms": 2.}


def _cell(config, value, seed):
    experiment = copy.deepcopy(config["base_experiment"])
    options = copy.deepcopy(config["options"])
    experiment["seed"] = seed
    factor = config["factor"]
    if factor == "speed_scale":
        experiment.setdefault("motion", {})[factor] = value
    elif factor == "knot_spacing_s":
        options[factor] = value
    else:
        experiment.setdefault("acquisition", {})[factor] = [1, 1, 1, value] if factor == "beacon_every_cycles" else value
    options["seed"] = (options["seed"] + seed) % 2**32
    return m3.normalize_config(experiment), m3.validate_options(options)


def validate_sweep_config(config=None):
    config = {} if config is None else config
    _validate_json_values(config)
    if not isinstance(config, dict) or set(config) - {"base_experiment", "options", "factor", "values", "seeds"}:
        raise ValueError("Invalid timing sweep configuration keys")
    factor = config.get("factor", "spacing_s")
    if factor not in FACTORS:
        raise ValueError("Unsupported timing sweep factor")
    values, seeds = config.get("values", [0., .05, .1]), config.get("seeds", [7, 8])
    if not isinstance(values, list) or not 1 <= len(values) <= 10:
        raise ValueError("Supply 1–10 distinct finite factor values")
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Factor values must be finite numbers")
        if factor == "beacon_every_cycles" and (not isinstance(value, int) or value < 1):
            raise ValueError("Beacon stride must be a positive integer")
    if len(set(values)) != len(values):
        raise ValueError("Factor values must be distinct")
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= 10 or any(isinstance(s, bool) or not isinstance(s, int) or not 0 <= s <= 2**32-1 for s in seeds) or len(set(seeds)) != len(seeds):
        raise ValueError("Supply 1–10 distinct unsigned 32-bit seeds")
    base = m3.normalize_config(config.get("base_experiment", {}))
    options = m3.validate_options(config.get("options", {}))
    result = {"base_experiment": base, "options": options, "factor": factor, "values": copy.deepcopy(values), "seeds": seeds.copy()}
    count = len(values)*len(seeds)*2
    if count > MAX_RUNS or count*options["starts"] > MAX_TOTAL_STARTS:
        raise ValueError("Timing sweep limit: 40 runs and 240 starts")
    for value in values:
        _cell(result, value, seeds[0])
    return result


def _failed_run(experiment, options, error, initials=None):
    message = f"{type(error).__name__}: {error}"
    return {"schema_version": SCHEMA_VERSION, "experiment": copy.deepcopy(experiment), "options": options,
            "status": "failed", "selected_start": None, "error": message, "diagnostics": {},
            "software_versions": experiment.get("software_versions", {}),
            "starts": [{"index": i, "status": "failed", "success": False,
                        "initial": copy.deepcopy(initials[i]) if initials else None, "estimate": None,
                        "solver": {"message": message}, "diagnostics": {}} for i in range(options["starts"])]}


def run_sweep(config=None, on_progress=None):
    cfg = validate_sweep_config(config)
    result = {"schema_version": SCHEMA_VERSION, "artifact_type": "timing_sweep", "config": cfg,
              "status": "running", "entries": [], "thresholds": THRESHOLDS.copy(),
              "pairing": {"scope": "Identical retained experiment and initial knot geometries within each value/seed cell",
                          "models": list(MODELS), "stride_factor": "Only beacon 3 changes cadence; other beacons remain every cycle",
                          "interpretation": "Convergence, geometry, measurement rank, interpolation, prior and timing approximation are separate; full rank does not prove uniqueness"}}
    for vi, value in enumerate(cfg["values"]):
        for seed in cfg["seeds"]:
            cell, options = _cell(cfg, value, seed)
            experiment = m3.generate_experiment(cell)
            initials = None
            for mi, model in enumerate(MODELS):
                model_options = {**options, "timing_model": model}
                try:
                    run = m3.solve_experiment(experiment, model_options, initial_geometries=initials)
                except Exception as exc:
                    run = _failed_run(experiment, model_options, exc, initials)
                if mi == 0 and all(s.get("initial") is not None for s in run["starts"]):
                    initials = [copy.deepcopy(s["initial"]) for s in run["starts"]]
                result["entries"].append({"index": len(result["entries"]), "value_index": vi, "value": value,
                                          "seed": seed, "variant_index": mi, "variant": model, "model": model, "run": run})
                result.update(aggregate_sweep(result))
                if on_progress:
                    on_progress(copy.deepcopy(result))
    result["status"] = "complete"
    result.update(aggregate_sweep(result))
    validate_artifact(result)
    return result


def _distribution(values):
    values = [float(v) for v in values if v is not None and math.isfinite(v)]
    return {"count": len(values), "min": min(values) if values else None,
            "median": float(np.median(values)) if values else None,
            "p90": float(np.percentile(values, 90)) if values else None, "max": max(values) if values else None}


def aggregate_sweep(artifact):
    rows = []
    for entry in artifact["entries"]:
        run = entry["run"]
        exact = not any(run["experiment"]["config"]["noise_std_m"])
        for start in run["starts"]:
            diag, solver = start.get("diagnostics", {}), start.get("solver", {})
            evaluation = diag.get("evaluation", {})
            frame = "raw" if exact or run["options"]["mode"] == "known_map" else "aligned"
            geometry = evaluation.get(frame, {})
            ping = diag.get("ping_evaluation", {}).get(frame, {})
            normalized = diag.get("residuals_normalized", [])
            norm_rms = float(np.sqrt(np.mean(np.square(normalized)))) if normalized else None
            maximum = geometry.get("position_max_error_m")
            beacon = geometry.get("beacon_errors_m", [])
            tolerance = artifact["thresholds"]["exact_geometry_max_m" if exact else "geometry_max_m"]
            accurate = maximum is not None and maximum <= tolerance and bool(beacon) and max(beacon) <= tolerance
            converged = bool(start.get("success"))
            rank = diag.get("jacobian", {})
            floor = run.get("diagnostics", {}).get("truth_interpolation_floor", {})
            timing = run.get("diagnostics", {}).get("timing_approximation", {})
            row = {"entry_index": entry["index"], "value_index": entry["value_index"], "value": entry["value"],
                   "seed": entry["seed"], "model": entry["model"], "variant": entry["model"], "start_index": start["index"],
                   "selected": start["index"] == run.get("selected_start"), "status": start["status"],
                   "optimizer_converged": converged, "converged": converged, "geometric_accuracy": bool(accurate),
                   "classification": "failed" if start.get("estimate") is None else "not_converged" if not converged else "geometrically_accurate" if accurate else "converged_geometry_inaccurate",
                   "exact_data": exact, "error_frame": frame, "position_rmse_m": geometry.get("position_rmse_m"),
                   "position_max_error_m": maximum, "map_rmse_m": geometry.get("map_rmse_m"),
                   "ping_position_rmse_m": ping.get("position_rmse_m"), "range_rmse_m": diag.get("range_rmse_m"),
                   "normalized_residual_rms": norm_rms, "low_residual": norm_rms is not None and norm_rms <= artifact["thresholds"]["normalized_residual_rms"],
                   "measurement_full_column_rank": rank.get("full_column_rank"), "measurement_rank": rank.get("rank"),
                   "parameter_count": rank.get("parameter_count"), "condition_number": rank.get("condition_number"),
                   "augmented_full_column_rank": diag.get("augmented_jacobian", {}).get("full_column_rank"),
                   "measurement_objective": solver.get("measurement_objective", diag.get("measurement_objective")),
                   "prior_objective": solver.get("prior_objective", diag.get("prior_objective")),
                   "interpolation_display_rmse_m": floor.get("display_position_rmse_m"),
                   "interpolation_ping_rmse_m": floor.get("ping_position_rmse_m"),
                   "timing_approximation_position_rmse_m": timing.get("position_rmse_m"),
                   "runtime_s": solver.get("runtime_s"), "nfev": solver.get("nfev")}
            rows.append(row)
    aggregates = []
    for vi, value in enumerate(artifact["config"]["values"]):
        for model in MODELS:
            group = [r for r in rows if r["value_index"] == vi and r["model"] == model]
            if not group:
                continue
            entries = [e for e in artifact["entries"] if e["value_index"] == vi and e["model"] == model]
            summary = {"value_index": vi, "value": value, "model": model, "variant": model, "run_count": len(entries),
                       "start_count": len(group), "failed_run_count": sum(e["run"]["status"] == "failed" for e in entries),
                       "failed_start_count": sum(r["status"] == "failed" for r in group),
                       "optimizer_converged_count": sum(r["optimizer_converged"] for r in group),
                       "geometric_accuracy_count": sum(r["geometric_accuracy"] for r in group),
                       "measurement_rank_deficient_count": sum(r["measurement_full_column_rank"] is False for r in group),
                       "nonconvergence_rate": sum(not r["optimizer_converged"] for r in group)/len(group)}
            for field in ("position_rmse_m", "ping_position_rmse_m", "range_rmse_m", "measurement_objective", "prior_objective", "interpolation_display_rmse_m", "interpolation_ping_rmse_m", "timing_approximation_position_rmse_m", "runtime_s"):
                summary["all_start_"+field] = _distribution(r[field] for r in group)
                summary["selected_"+field] = _distribution(r[field] for r in group if r["selected"])
            aggregates.append(summary)
    return {"start_table": rows, "aggregates": aggregates}


def validate_artifact(data):
    """Validate retained runs and recompute tables; never generate data or solve."""
    try:
        _validate_json_values(data)
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION or data.get("artifact_type") != "timing_sweep":
            raise ValueError("Expected version 3.0 timing_sweep")
        cfg = validate_sweep_config(data["config"])
        if cfg != data["config"] or data.get("thresholds") != THRESHOLDS:
            raise ValueError("Sweep config/thresholds must be normalized")
        expected = [(vi, seed, mi) for vi in range(len(cfg["values"])) for seed in cfg["seeds"] for mi in range(2)]
        entries = data["entries"]
        if data.get("status") not in ("running", "complete", "failed", "interrupted") or not isinstance(entries, list) or len(entries) > len(expected) or (data["status"] == "complete" and len(entries) != len(expected)):
            raise ValueError("Sweep must account for every run")
        for index, (entry, (vi, seed, mi)) in enumerate(zip(entries, expected)):
            if (entry["index"], entry["value_index"], entry["seed"], entry["variant_index"], entry["model"], entry["value"], entry["variant"]) != (index, vi, seed, mi, MODELS[mi], cfg["values"][vi], MODELS[mi]):
                raise ValueError("Entry identity disagrees with sweep")
            run = entry["run"]
            m3.validate_run(run)
            cell, options = _cell(cfg, cfg["values"][vi], seed)
            if run["experiment"]["config"] != cell or run["options"] != {**options, "timing_model": MODELS[mi]}:
                raise ValueError("Saved run controls disagree with sweep")
            if len(run["starts"]) != options["starts"] or [s["index"] for s in run["starts"]] != list(range(options["starts"])):
                raise ValueError("Sweep must retain every attempted start")
            for start in run["starts"]:
                if start.get("status") not in ("success", "not_converged", "failed") or not isinstance(start.get("success"), bool):
                    raise ValueError("Invalid saved start status")
                if start["success"] != (start["status"] == "success") or (start["status"] == "failed") != (start.get("estimate") is None):
                    raise ValueError("Saved start status and estimate disagree")
            if mi:
                first = entries[index-1]["run"]
                if run["experiment"] != first["experiment"]:
                    raise ValueError("Paired models must share exact observations")
                for left, right in zip(first["starts"], run["starts"]):
                    if left.get("initial") is not None and left["initial"] != right.get("initial"):
                        raise ValueError("Paired models must share initial geometries")
        reference = aggregate_sweep(data)
        for key in reference:
            if reference[key] != data.get(key):
                raise ValueError(f"Saved {key} disagrees with source runs")
    except ExperimentFormatError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ExperimentFormatError(f"Invalid timing sweep: {exc}") from exc


def save_artifact(path, data):
    validate_artifact(data)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    _replace_with_retry(temporary, path)


def load_artifact(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ExperimentFormatError(f"Invalid timing sweep JSON: {exc}") from exc
    validate_artifact(data)
    return data


def table_csv(artifact):
    validate_artifact(artifact)
    stream = io.StringIO(newline="")
    rows = artifact["start_table"]
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else [])
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()
