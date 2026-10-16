"""Paired M6 contamination/robustness sweeps with retained starts and offline exports."""
from __future__ import annotations
import copy
import csv
import io
import json
import math
from pathlib import Path
import uuid
import numpy as np
from . import m6 as m4
from .experiments import ExperimentFormatError, _validate_json_values, _reject_constant, _replace_with_retry

SCHEMA_VERSION = "6.0"
FACTORS = ("nlos_prevalence", "nlos_magnitude_m", "burst_duration_cycles", "offset_m", "correlated_noise_std_m", "correlation", "quantization_m", "dropout_probability", "noise_std_m")
MAX_RUNS, MAX_STARTS, MAX_TOTAL_STARTS = 40, 12, 240
THRESHOLDS = {"exact_geometry_max_m": 1e-5, "noisy_geometry_max_m": .25, "exact_range_max_m": 1e-7, "normalized_residual_rms": 2.}
DEFAULT_VARIANTS = [{"label": loss, "options": {"loss": loss}} for loss in ("gaussian", "huber", "cauchy", "hard_rejection")]


def _cell(config, value, seed):
    experiment, options = copy.deepcopy(config["base_experiment"]), copy.deepcopy(config["options"])
    experiment["seed"] = seed
    experiment.setdefault("contamination", {})["seed"] = (config["base_experiment"]["contamination"]["seed"] + seed) % 2**32
    factor = config["factor"]
    if factor == "noise_std_m": experiment[factor] = value
    else:
        contamination = experiment.setdefault("contamination", {})
        if factor.startswith("nlos_"):
            contamination.setdefault("nlos", {})[{"nlos_prevalence":"prevalence", "nlos_magnitude_m":"magnitude_m"}[factor]] = value
        elif factor == "burst_duration_cycles": contamination.setdefault("nlos", {})[factor] = value
        elif factor == "offset_m": contamination["offsets_m"] = [value] * experiment["beacon_layout"]["count"]
        else: contamination[factor] = value
    options["seed"] = (options["seed"] + seed) % 2**32
    return m4.normalize_config(experiment), m4.validate_options(options)


def _variant_options(options, variant, factor):
    return m4.validate_options({**options, **variant["options"]})


def validate_sweep_config(config=None):
    config = {} if config is None else config
    _validate_json_values(config)
    if not isinstance(config, dict) or set(config) - {"base_experiment", "options", "factor", "values", "seeds", "variants"}:
        raise ValueError("Invalid solver sweep configuration keys")
    factor = config.get("factor", "nlos_prevalence")
    if factor not in FACTORS:
        raise ValueError("Unsupported solver sweep factor")
    values = config.get("values", [0., .1])
    if not isinstance(values, list) or not 1 <= len(values) <= 10:
        raise ValueError("Supply 1–10 distinct factor values")
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Factor values must be finite numbers")
    if len(set(values)) != len(values):
        raise ValueError("Factor values must be distinct")
    seeds = config.get("seeds", [7, 8])
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= 10 or len(set(seeds)) != len(seeds) or any(isinstance(s, bool) or not isinstance(s, int) or not 0 <= s <= 2**32-1 for s in seeds):
        raise ValueError("Supply 1–10 distinct unsigned 32-bit seeds")
    options = m4.validate_options({"mode": "joint", "tag_height_model": "fixed", "beacon_height_model": "shared", **config.get("options", {})})
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
        if set(changes) - {"loss", "loss_scale_sigma", "rejection_threshold_sigma", "weight_decision_threshold", "solver", "height_parameterization", "max_nfev"}:
            raise ValueError("Paired variants may change only disclosed loss, decision, solver, height coordinate and evaluation budget; physical models, priors and initialization are shared")
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
        raise ValueError("Solver sweep limit: 40 runs and 240 starts")
    supplied_base = config.get("base_experiment", {})
    base = m4.normalize_config(supplied_base)
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
                        "estimate": None, "solver": {"message": message, "method": "scipy.optimize.least_squares/"+options["solver"], "height_parameterization":options["height_parameterization"]}, "diagnostics": {}} for i in range(options["starts"])]}


def run_sweep(config=None, on_progress=None):
    cfg = validate_sweep_config(config)
    result = {"schema_version": SCHEMA_VERSION, "artifact_type": "robust_sweep", "config": cfg,
              "status":"running", "entries":[], "thresholds":THRESHOLDS.copy(),
              "pairing":{"scope":"Identical observations within value/seed; same physical starts within each initializer group",
              "reference":"First variant supplies physical starts; other loss/solver variants reuse them",
              "interpretation":"Contamination labels never enter fitting; residual fit, rejection decisions, geometry and retained information are separate"}}
    for vi, value in enumerate(cfg["values"]):
        for seed in cfg["seeds"]:
            cell, options = _cell(cfg, value, seed); experiment = m4.generate_experiment(cell); references = {}
            for mi, variant in enumerate(cfg["variants"]):
                opts = _variant_options(options, variant, cfg["factor"]); group = opts["initialization"]
                initials = None; pairing_error = None; reference_index = None
                try:
                    if group in references:
                        reference_index, reference = references[group]
                        try: initials = m4.compatible_initial_geometries(reference, experiment, opts)
                        except Exception as exc: pairing_error = f"{type(exc).__name__}: {exc}"; raise
                    run = m4.solve_experiment(experiment, opts, initial_geometries=initials)
                except Exception as exc: run = _failed_run(experiment, opts, exc, initials)
                index = len(result["entries"])
                if group not in references and all(isinstance(start.get("initial"),dict) and "knot_trajectory" in start["initial"] and "beacons" in start["initial"] for start in run["starts"]): references[group] = (index, run)
                result["entries"].append({"index":index, "value_index":vi, "value":value, "seed":seed,
                    "variant_index":mi, "variant":variant["label"], "run":run, "pairing_error":pairing_error,
                    "initialization_group":group, "initial_reference_entry":reference_index})
                result.update(aggregate_sweep(result))
                if on_progress: on_progress(copy.deepcopy(result))
    result["status"] = "complete"; result.update(aggregate_sweep(result)); validate_artifact(result); return result


def _distribution(values):
    values = [float(v) for v in values if v is not None and math.isfinite(v)]
    return {"count": len(values), "min": min(values) if values else None, "median": float(np.median(values)) if values else None,
            "p90": float(np.percentile(values, 90)) if values else None, "max": max(values) if values else None}


def aggregate_sweep(artifact):
    rows = []
    for entry in artifact["entries"]:
        run = entry["run"]
        for start in run["starts"]:
            d = start.get("diagnostics", {})
            # Exact refers to every retained measured range, not Gaussian SD alone.
            refs = run["experiment"].get("contamination_reference", {}).get("records", [])
            exact = not any(run["experiment"]["config"]["noise_std_m"]) and not any(
                abs(r.get("range_m", 0) - r.get("clean_range_m", 0)) > 1e-12 for r in refs if not r.get("dropped"))
            frame = "raw" if exact or run["options"]["mode"] == "known_map" else "aligned"
            geometry = d.get("evaluation", {}).get(frame, {})
            ev = d.get("rejection_evaluation", {})
            info = d.get("information", {})
            original = info.get("original_measurement", {})
            retained = info.get("retained_measurement", {})
            original_trace = sum(s*s for s in original.get("singular_values", []))
            retained_trace = sum(s*s for s in retained.get("singular_values", []))
            norm = d.get("residuals_normalized", [])
            norm_rms = float(np.sqrt(np.mean(np.square(norm)))) if norm else None
            max_position = geometry.get("position_max_error_m")
            beacon = geometry.get("beacon_errors_m", [])
            tol = artifact["thresholds"]["exact_geometry_max_m" if exact else "noisy_geometry_max_m"]
            accurate = max_position is not None and max_position <= tol and bool(beacon) and max(beacon) <= tol
            solver = start.get("solver", {})
            rows.append({"entry_index": entry["index"], "value_index": entry["value_index"], "value": entry["value"],
                "seed": entry["seed"], "variant": entry["variant"], "start_index": start["index"],
                "selected": start["index"] == run.get("selected_start"), "status": start["status"],
                "optimizer_converged": bool(start.get("success")), "geometric_accuracy": bool(accurate),
                "exact_data": exact, "error_frame": frame, "position_rmse_m": geometry.get("position_rmse_m"),
                "position_max_error_m": max_position, "map_rmse_m": geometry.get("map_rmse_m"),
                "range_rmse_m": d.get("range_rmse_m"), "normalized_residual_rms": norm_rms,
                "low_residual": d.get("max_abs_residual_m") is not None and d["max_abs_residual_m"] <= artifact["thresholds"]["exact_range_max_m"] if exact else norm_rms is not None and norm_rms <= artifact["thresholds"]["normalized_residual_rms"],
                "solver": run["options"]["solver"], "loss": run["options"]["loss"],
                "height_parameterization": run["options"]["height_parameterization"],
                "initialization": run["options"]["initialization"], "truth_assisted_diagnostic": run["options"]["initialization"] == "truth_near",
                "rejection_precision": ev.get("precision"), "rejection_recall": ev.get("recall"),
                "false_rejections": ev.get("false_positive"), "true_rejections": ev.get("true_positive"),
                "original_measurement_rank": original.get("rank"), "retained_measurement_rank": retained.get("rank"),
                "information_loss_fraction": 1. - retained_trace/original_trace if original_trace else None,
                "measurement_objective": solver.get("measurement_objective"),
                "motion_prior_objective": solver.get("motion_prior_objective"), "height_prior_objective": solver.get("height_prior_objective"),
                "runtime_s": solver.get("runtime_s"), "nfev": solver.get("nfev")})
    aggregates = []
    fields = ("position_rmse_m", "map_rmse_m", "range_rmse_m", "normalized_residual_rms", "rejection_precision", "rejection_recall", "false_rejections", "information_loss_fraction", "runtime_s")
    for vi, value in enumerate(artifact["config"]["values"]):
        for variant in artifact["config"]["variants"]:
            group = [r for r in rows if r["value_index"] == vi and r["variant"] == variant["label"]]
            if not group: continue
            summary = {"value_index":vi, "value":value, "variant":variant["label"], "start_count":len(group),
                "optimizer_converged_count":sum(r["optimizer_converged"] for r in group),
                "failed_start_count":sum(r["status"] == "failed" for r in group),
                "nonconvergence_rate":sum(not r["optimizer_converged"] for r in group)/len(group),
                "geometric_accuracy_count":sum(r["geometric_accuracy"] for r in group),
                "denominators":"Failures remain in attempt counts; finite metric distributions omit unavailable values and report their count"}
            for field in fields:
                summary["all_start_"+field] = _distribution(r[field] for r in group)
                summary["selected_"+field] = _distribution(r[field] for r in group if r["selected"])
            aggregates.append(summary)
    return {"start_table":rows, "aggregates":aggregates}


def validate_artifact(data):
    """Validate source runs and projection pairing; never generate or solve."""
    try:
        _validate_json_values(data)
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION or data.get("artifact_type") != "robust_sweep":
            raise ValueError("Expected version 6.0 robust_sweep")
        cfg = validate_sweep_config(data["config"])
        if cfg != data["config"] or data.get("thresholds") != THRESHOLDS:
            raise ValueError("Sweep config and thresholds must be normalized")
        expected = [(vi, seed, mi) for vi in range(len(cfg["values"])) for seed in cfg["seeds"] for mi in range(len(cfg["variants"]))]
        entries = data["entries"]
        if data.get("status") not in ("running", "complete", "failed", "interrupted") or not isinstance(entries, list) or len(entries) > len(expected) or (data["status"] == "complete" and len(entries) != len(expected)):
            raise ValueError("Sweep must account for every run")
        references = {}
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
            if mi and run["experiment"] != entries[index-mi]["run"]["experiment"]:
                raise ValueError("Paired variants must retain identical observations")
            reference_index = entry.get("initial_reference_entry")
            group_key = (vi, seed, opts["initialization"])
            if reference_index != references.get(group_key):
                raise ValueError("Initial reference must identify the first compatible saved physical starts in this cell")
            if entry.get("initialization_group") != opts["initialization"]:
                raise ValueError("Initializer grouping mismatch")
            if reference_index is not None:
                if isinstance(reference_index,bool) or not isinstance(reference_index,int) or not 0 <= reference_index < index: raise ValueError("Invalid initial reference")
                reference = entries[reference_index]
                if (reference["value_index"],reference["seed"],reference["initialization_group"]) != (vi,seed,opts["initialization"]): raise ValueError("Initial reference belongs to another data/initializer cell")
                if entry.get("pairing_error"):
                    if run["status"]!="failed": raise ValueError("Failed pairing must retain failed run")
                else:
                    projected = m4.compatible_initial_geometries(reference["run"],run["experiment"],opts)
                    if projected != [start.get("initial") for start in run["starts"]]: raise ValueError("Physical starts differ from paired projection")
            if group_key not in references and all(isinstance(s.get("initial"), dict) and "knot_trajectory" in s["initial"] and "beacons" in s["initial"] for s in run["starts"]):
                references[group_key] = index
        for key, table in aggregate_sweep(data).items():
            if data.get(key) != table:
                raise ValueError(f"Saved {key} disagrees with retained runs")
    except ExperimentFormatError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ExperimentFormatError(f"Invalid solver sweep: {exc}") from exc


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
        raise ExperimentFormatError(f"Invalid solver sweep JSON: {exc}") from exc
    validate_artifact(data)
    return data


def table_csv(artifact):
    validate_artifact(artifact)
    rows, stream = artifact["start_table"], io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(key for row in rows for key in row)))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()
