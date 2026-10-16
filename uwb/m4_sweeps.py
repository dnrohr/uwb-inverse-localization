"""Bounded M4 geometry/model sweeps with retained starts and offline exports."""
from __future__ import annotations
import copy
import csv
import io
import json
import math
from pathlib import Path
import uuid
import numpy as np
from . import m4
from .experiments import ExperimentFormatError, _validate_json_values, _reject_constant, _replace_with_retry

SCHEMA_VERSION = "4.0"
FACTORS = ("beacon_count", "vertical_separation", "height_spread", "coverage", "height_prior_sigma_m", "beacon_height_model")
MAX_RUNS, MAX_STARTS, MAX_TOTAL_STARTS = 40, 12, 240
THRESHOLDS = {"exact_geometry_max_m": 1e-5, "noisy_geometry_max_m": .25, "exact_range_max_m": 1e-7, "normalized_residual_rms": 2.}
DEFAULT_VARIANTS = [{"label": model, "options": {"tag_height_model": model}} for model in ("fixed", "shared", "soft", "free")]


def _cell(config, value, seed):
    experiment, options = copy.deepcopy(config["base_experiment"]), copy.deepcopy(config["options"])
    experiment["seed"] = seed
    factor = config["factor"]
    if factor in ("height_prior_sigma_m", "beacon_height_model"):
        options[factor] = value
    elif factor == "coverage":
        experiment.setdefault("path", {"type": "rectangle"})["scale"] = value
    else:
        experiment.setdefault("beacon_layout", {})[{"beacon_count": "count", "vertical_separation": "height_m", "height_spread": "height_spread_m"}[factor]] = value
        if factor == "beacon_count":
            # Count sweeps require generated layouts; vectors are resized only
            # when they are homogeneous defaults, preserving uncertainty units.
            for key in ("noise_std_m", "assumed_std_m"):
                old = experiment.get(key)
                if isinstance(old, list) and len(set(old)) == 1:
                    experiment[key] = old[0]
            acquisition = experiment.get("acquisition", {})
            acquisition.pop("beacon_order", None)
            acquisition.pop("beacon_every_cycles", None)
    options["seed"] = (options["seed"] + seed) % 2**32
    return m4.normalize_config(experiment), m4.validate_options(options)


def _variant_options(options, variant, factor):
    return m4.validate_options({**options, **variant["options"]})


def validate_sweep_config(config=None):
    config = {} if config is None else config
    _validate_json_values(config)
    if not isinstance(config, dict) or set(config) - {"base_experiment", "options", "factor", "values", "seeds", "variants"}:
        raise ValueError("Invalid geometry sweep configuration keys")
    factor = config.get("factor", "vertical_separation")
    if factor not in FACTORS:
        raise ValueError("Unsupported geometry sweep factor")
    values = config.get("values", [1., 3.])
    if not isinstance(values, list) or not 1 <= len(values) <= 10:
        raise ValueError("Supply 1–10 distinct factor values")
    for value in values:
        if factor == "beacon_height_model":
            if value not in ("shared", "independent"):
                raise ValueError("Beacon height model must be shared or independent")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Factor values must be finite numbers")
        elif factor == "beacon_count" and (not isinstance(value, int) or not 3 <= value <= 8):
            raise ValueError("Beacon count must be an integer from 3 through 8")
    if len(set(values)) != len(values):
        raise ValueError("Factor values must be distinct")
    seeds = config.get("seeds", [7, 8])
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= 10 or len(set(seeds)) != len(seeds) or any(isinstance(s, bool) or not isinstance(s, int) or not 0 <= s <= 2**32-1 for s in seeds):
        raise ValueError("Supply 1–10 distinct unsigned 32-bit seeds")
    options = m4.validate_options({"mode": "known_map", **config.get("options", {})})
    if not 1 <= options["starts"] <= MAX_STARTS or options["max_nfev"] > 5000:
        raise ValueError("Sweeps permit 1–12 starts and at most 5000 evaluations per start")
    variants = config.get("variants", DEFAULT_VARIANTS)
    if not isinstance(variants, list) or not 1 <= len(variants) <= 4:
        raise ValueError("Supply 1–4 labeled model variants")
    normalized = []
    for variant in variants:
        if not isinstance(variant, dict) or set(variant) - {"label", "options"}:
            raise ValueError("Variants require label and solver options")
        label, changes = variant.get("label"), variant.get("options", {})
        if not isinstance(label, str) or not label.strip() or len(label) > 80 or not isinstance(changes, dict):
            raise ValueError("Each variant needs a nonempty label of at most 80 characters and object options")
        if set(changes) & {"starts", "seed", "initialization", "mode", "fixed_tag_z_m"}:
            raise ValueError("Paired variants share starts, seed, initialization, estimation mode and height-prior mean")
        if factor in changes:
            raise ValueError("A variant must not override the swept option")
        effective = m4.validate_options({**options, **changes})
        if effective["max_nfev"] > 5000:
            raise ValueError("Variant budget exceeds 5000 evaluations")
        normalized.append({"label": label, "options": copy.deepcopy(changes)})
    if len({v["label"] for v in normalized}) != len(normalized):
        raise ValueError("Variant labels must be distinct")
    count = len(values)*len(seeds)*len(normalized)
    if count > MAX_RUNS or count*options["starts"] > MAX_TOTAL_STARTS:
        raise ValueError("Geometry sweep limit: 40 runs and 240 starts")
    supplied_base = config.get("base_experiment", {})
    if factor == "coverage" and "path" not in supplied_base and supplied_base.get("scenario", "informative") not in ("informative", "nearly_collinear"):
        raise ValueError("Coverage sweep for this scenario requires an explicit path")
    base = m4.normalize_config(supplied_base)
    if factor in ("beacon_count", "vertical_separation", "height_spread") and base["beacon_layout"].get("coordinates_m") is not None:
        raise ValueError("Layout factors require a generated map rather than explicit coordinates")
    result = {"base_experiment": base, "options": options, "factor": factor, "values": copy.deepcopy(values), "seeds": seeds.copy(), "variants": normalized}
    for value in values:
        cell, opts = _cell(result, value, seeds[0])
        for variant in normalized:
            _variant_options(opts, variant, factor)
    return result


def _failed_run(experiment, options, error, initials=None):
    message = f"{type(error).__name__}: {error}"
    return {"schema_version": SCHEMA_VERSION, "experiment": copy.deepcopy(experiment), "options": options,
            "status": "failed", "selected_start": None, "error": message, "diagnostics": {},
            "software_versions": experiment.get("software_versions", {}),
            "starts": [{"index": i, "status": "failed", "success": False, "initial": copy.deepcopy(initials[i]) if initials else None,
                        "estimate": None, "solver": {"message": message}, "diagnostics": {}} for i in range(options["starts"])]}


def run_sweep(config=None, on_progress=None):
    cfg = validate_sweep_config(config)
    result = {"schema_version": SCHEMA_VERSION, "artifact_type": "geometry_sweep", "config": cfg,
              "status": "running", "entries": [], "thresholds": THRESHOLDS.copy(),
              "pairing": {"scope": "One retained experiment per value/seed; physical initial geometry projected into each model's constrained parameterization and canonical frame",
                          "reference": "First variant's saved start geometries; projection is retained and validated offline",
                          "height_prior": "Model variants share the explicitly configured fixed_tag_z_m height-prior mean; all priors and frame choices remain disclosed",
                          "interpretation": "Measurement rank, prior-augmented rank, convergence, geometry, planarity, timing and interpolation are separate; sampled starts do not prove uniqueness"}}
    for vi, value in enumerate(cfg["values"]):
        for seed in cfg["seeds"]:
            cell, options = _cell(cfg, value, seed)
            experiment = m4.generate_experiment(cell)
            reference = None
            for mi, variant in enumerate(cfg["variants"]):
                opts = _variant_options(options, variant, cfg["factor"])
                initials = None
                pairing_error = None
                try:
                    if reference is not None:
                        try:
                            initials = m4.compatible_initial_geometries(reference, experiment, opts)
                        except Exception as exc:
                            pairing_error = f"{type(exc).__name__}: {exc}"
                            raise
                    run = m4.solve_experiment(experiment, opts, initial_geometries=initials)
                except Exception as exc:
                    run = _failed_run(experiment, opts, exc, initials)
                if mi == 0 and all(s.get("initial") is not None for s in run["starts"]):
                    reference = run
                result["entries"].append({"index": len(result["entries"]), "value_index": vi, "value": value, "seed": seed,
                                          "variant_index": mi, "variant": variant["label"], "run": run, "pairing_error": pairing_error})
                result.update(aggregate_sweep(result))
                if on_progress:
                    on_progress(copy.deepcopy(result))
    result["status"] = "complete"
    result.update(aggregate_sweep(result))
    validate_artifact(result)
    return result


def _distribution(values):
    values = [float(v) for v in values if v is not None and math.isfinite(v)]
    return {"count": len(values), "min": min(values) if values else None, "median": float(np.median(values)) if values else None,
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
            rank = diag.get("jacobian", {})
            height = diag.get("height", {})
            planarity = height.get("best_fit_plane", {})
            floor = run.get("diagnostics", {}).get("truth_interpolation_floor", {})
            if floor.get("available") is False:
                floor = {}
            interpolation = run.get("diagnostics", {}).get("truth_interpolation_only", {})
            if interpolation.get("available") is False:
                interpolation = {}
            projection = run.get("diagnostics", {}).get("truth_model_projection", {})
            if projection.get("available") is False:
                projection = {}
            timing = run.get("diagnostics", {}).get("timing_approximation", {})
            normalized = diag.get("residuals_normalized", [])
            norm_rms = float(np.sqrt(np.mean(np.square(normalized)))) if normalized else None
            maximum, beacon = geometry.get("position_max_error_m"), geometry.get("beacon_errors_m", [])
            tolerance = artifact["thresholds"]["exact_geometry_max_m" if exact else "noisy_geometry_max_m"]
            accurate = maximum is not None and maximum <= tolerance and bool(beacon) and max(beacon) <= tolerance
            converged = bool(start.get("success"))
            rows.append({"entry_index": entry["index"], "value_index": entry["value_index"], "value": entry["value"], "seed": entry["seed"],
                         "variant": entry["variant"], "start_index": start["index"], "selected": start["index"] == run.get("selected_start"),
                         "status": start["status"], "optimizer_converged": converged, "converged": converged,
                         "tag_height_model": run["options"]["tag_height_model"], "beacon_height_model": run["options"]["beacon_height_model"],
                         "geometric_accuracy": bool(accurate), "exact_data": exact, "error_frame": frame,
                         "classification": "failed" if start.get("estimate") is None else "not_converged" if not converged else "geometrically_accurate" if accurate else "converged_geometry_inaccurate",
                         "position_rmse_m": geometry.get("position_rmse_m"), "position_max_error_m": maximum, "map_rmse_m": geometry.get("map_rmse_m"),
                         "height_error_frame": height.get("frame", "known-map world z or saved evaluation-aligned joint frame"),
                         "height_rmse_m": height.get("world_z_rmse_m"), "height_max_error_m": max([abs(v) for v in height.get("height_errors_m", [])], default=None),
                         "plane_departure_rmse_m": planarity.get("rms_departure_m"), "plane_departure_max_m": planarity.get("max_departure_m"),
                         "range_rmse_m": diag.get("range_rmse_m"), "normalized_residual_rms": norm_rms,
                         "low_residual": diag.get("max_abs_residual_m") is not None and diag["max_abs_residual_m"] <= artifact["thresholds"]["exact_range_max_m"] if exact else norm_rms is not None and norm_rms <= artifact["thresholds"]["normalized_residual_rms"],
                         "measurement_full_column_rank": rank.get("full_column_rank"), "measurement_rank": rank.get("rank"), "parameter_count": rank.get("parameter_count"),
                         "condition_number": rank.get("condition_number"), "augmented_full_column_rank": diag.get("augmented_jacobian", {}).get("full_column_rank"),
                         "measurement_objective": solver.get("measurement_objective", diag.get("measurement_objective")), "prior_objective": solver.get("prior_objective", diag.get("prior_objective")),
                         "height_prior_objective": solver.get("height_prior_objective", diag.get("height_prior_objective")),
                         "motion_prior_objective": solver.get("motion_prior_objective", diag.get("motion_prior_objective")),
                         "interpolation_display_rmse_m": floor.get("display_position_rmse_m"), "interpolation_ping_rmse_m": floor.get("ping_position_rmse_m"),
                         "timing_approximation_position_rmse_m": timing.get("position_rmse_m"), "runtime_s": solver.get("runtime_s"), "nfev": solver.get("nfev")})
            if "truth_interpolation_only" in run.get("diagnostics", {}):
                rows[-1].update(interpolation_only_display_rmse_m=interpolation.get("display", {}).get("position_rmse_m"),
                                interpolation_only_ping_rmse_m=interpolation.get("pings", {}).get("position_rmse_m"))
            if "truth_model_projection" in run.get("diagnostics", {}):
                rows[-1].update(model_projection_knot_rmse_m=projection.get("knot_position_rmse_m"),
                                model_projection_map_rmse_m=projection.get("beacon_rmse_m"))
    aggregates = []
    for vi, value in enumerate(artifact["config"]["values"]):
        for variant in artifact["config"]["variants"]:
            group = [r for r in rows if r["value_index"] == vi and r["variant"] == variant["label"]]
            if not group:
                continue
            entries = [e for e in artifact["entries"] if e["value_index"] == vi and e["variant"] == variant["label"]]
            summary = {"value_index": vi, "value": value, "variant": variant["label"], "run_count": len(entries), "start_count": len(group),
                       "failed_run_count": sum(e["run"]["status"] == "failed" for e in entries), "failed_start_count": sum(r["status"] == "failed" for r in group),
                       "optimizer_converged_count": sum(r["optimizer_converged"] for r in group), "geometric_accuracy_count": sum(r["geometric_accuracy"] for r in group),
                       "measurement_rank_deficient_count": sum(r["measurement_full_column_rank"] is False for r in group),
                       "nonconvergence_rate": sum(not r["optimizer_converged"] for r in group)/len(group)}
            for field in ("position_rmse_m", "map_rmse_m", "height_rmse_m", "plane_departure_rmse_m", "range_rmse_m", "measurement_objective", "prior_objective", "height_prior_objective", "motion_prior_objective", "interpolation_display_rmse_m", "interpolation_ping_rmse_m", "timing_approximation_position_rmse_m", "runtime_s"):
                summary["all_start_"+field] = _distribution(r[field] for r in group)
                summary["selected_"+field] = _distribution(r[field] for r in group if r["selected"])
            for field in ("interpolation_only_display_rmse_m", "interpolation_only_ping_rmse_m", "model_projection_knot_rmse_m", "model_projection_map_rmse_m"):
                if any(field in r for r in group):
                    summary["all_start_"+field] = _distribution(r.get(field) for r in group)
                    summary["selected_"+field] = _distribution(r.get(field) for r in group if r["selected"])
            aggregates.append(summary)
    return {"start_table": rows, "aggregates": aggregates}


def validate_artifact(data):
    """Validate source runs and projection pairing; never generate or solve."""
    try:
        _validate_json_values(data)
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION or data.get("artifact_type") != "geometry_sweep":
            raise ValueError("Expected version 4.0 geometry_sweep")
        cfg = validate_sweep_config(data["config"])
        if cfg != data["config"] or data.get("thresholds") != THRESHOLDS:
            raise ValueError("Sweep config and thresholds must be normalized")
        expected = [(vi, seed, mi) for vi in range(len(cfg["values"])) for seed in cfg["seeds"] for mi in range(len(cfg["variants"]))]
        entries = data["entries"]
        if data.get("status") not in ("running", "complete", "failed", "interrupted") or not isinstance(entries, list) or len(entries) > len(expected) or (data["status"] == "complete" and len(entries) != len(expected)):
            raise ValueError("Sweep must account for every run")
        for index, (entry, (vi, seed, mi)) in enumerate(zip(entries, expected)):
            variant = cfg["variants"][mi]
            if (entry["index"], entry["value_index"], entry["seed"], entry["variant_index"], entry["value"], entry["variant"]) != (index, vi, seed, mi, cfg["values"][vi], variant["label"]):
                raise ValueError("Entry identity disagrees with sweep")
            run = entry["run"]
            m4.validate_run(run)
            cell, options = _cell(cfg, cfg["values"][vi], seed)
            opts = _variant_options(options, variant, cfg["factor"])
            if run["experiment"]["config"] != cell or run["options"] != opts:
                raise ValueError("Saved run controls disagree with sweep")
            if len(run["starts"]) != opts["starts"] or [s["index"] for s in run["starts"]] != list(range(opts["starts"])):
                raise ValueError("Sweep must retain every attempted start")
            if mi:
                first = entries[index-mi]["run"]
                if run["experiment"] != first["experiment"]:
                    raise ValueError("Paired models must share exact observations")
                pairing_error = entry.get("pairing_error")
                if pairing_error is not None:
                    if not isinstance(pairing_error, str) or not pairing_error or run["status"] != "failed" or any(s.get("initial") is not None or s.get("estimate") is not None for s in run["starts"]):
                        raise ValueError("A failed initial projection must retain its explanation and empty failed starts")
                elif all(s.get("initial") is not None for s in first["starts"]):
                    projected = m4.compatible_initial_geometries(first, run["experiment"], opts)
                    if projected != [s.get("initial") for s in run["starts"]]:
                        raise ValueError("Initial geometry must equal the disclosed compatible projection")
        for key, table in aggregate_sweep(data).items():
            if data.get(key) != table:
                raise ValueError(f"Saved {key} disagrees with retained runs")
    except ExperimentFormatError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ExperimentFormatError(f"Invalid geometry sweep: {exc}") from exc


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
        raise ExperimentFormatError(f"Invalid geometry sweep JSON: {exc}") from exc
    validate_artifact(data)
    return data


def table_csv(artifact):
    validate_artifact(artifact)
    rows, stream = artifact["start_table"], io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(key for row in rows for key in row)))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()
