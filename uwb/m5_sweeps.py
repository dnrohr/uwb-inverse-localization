"""Paired M5 solver/initializer sweeps with retained starts and offline exports."""
from __future__ import annotations
import copy
import csv
import io
import json
import math
from pathlib import Path
import uuid
import numpy as np
from . import m5 as m4
from . import m4_sweeps as previous
from .experiments import ExperimentFormatError, _validate_json_values, _reject_constant, _replace_with_retry

SCHEMA_VERSION = "5.0"
FACTORS = ("initialization_error_m", "noise_std_m", "beacon_count", "vertical_separation", "coverage")
MAX_RUNS, MAX_STARTS, MAX_TOTAL_STARTS = 40, 12, 240
THRESHOLDS = {"exact_geometry_max_m": 1e-5, "noisy_geometry_max_m": .25, "exact_range_max_m": 1e-7, "normalized_residual_rms": 2.}
DEFAULT_VARIANTS = [{"label": solver+" / "+parameter, "options": {"solver": solver, "height_parameterization": parameter}} for solver in ("trf", "lm") for parameter in ("h", "q")]


def _cell(config, value, seed):
    experiment, options = copy.deepcopy(config["base_experiment"]), copy.deepcopy(config["options"])
    experiment["seed"] = seed
    factor = config["factor"]
    if factor == "initialization_error_m": options[factor] = value
    elif factor == "noise_std_m": experiment[factor] = value
    elif factor == "coverage": experiment.setdefault("path", {"type": "rectangle"})["scale"] = value
    else:
        experiment.setdefault("beacon_layout", {})[{"beacon_count":"count", "vertical_separation":"height_m"}[factor]] = value
        if factor == "beacon_count":
            for key in ("noise_std_m", "assumed_std_m"):
                old = experiment.get(key)
                if isinstance(old, list) and len(set(old)) == 1: experiment[key] = old[0]
            acquisition = experiment.get("acquisition", {})
            acquisition.pop("beacon_order", None); acquisition.pop("beacon_every_cycles", None)
    options["seed"] = (options["seed"] + seed) % 2**32
    return m4.normalize_config(experiment), m4.validate_options(options)


def _variant_options(options, variant, factor):
    return m4.validate_options({**options, **variant["options"]})


def validate_sweep_config(config=None):
    config = {} if config is None else config
    _validate_json_values(config)
    if not isinstance(config, dict) or set(config) - {"base_experiment", "options", "factor", "values", "seeds", "variants"}:
        raise ValueError("Invalid solver sweep configuration keys")
    factor = config.get("factor", "initialization_error_m")
    if factor not in FACTORS:
        raise ValueError("Unsupported solver sweep factor")
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
        if set(changes) & {"starts", "seed", "initialization_error_m", "algebraic_physical_tolerance", "mode", "fixed_tag_z_m", "tag_height_model", "beacon_height_model", "timing_model", "knot_spacing_s", "prior_sigma_m", "height_prior_sigma_m", "below_beacons"}:
            raise ValueError("Paired variants share perturbation scale, initializer tolerance, start count/seed and all physical model/prior choices; initializer methods may differ explicitly")
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
    if factor == "coverage" and "path" not in supplied_base and supplied_base.get("scenario", "informative") not in ("informative", "nearly_collinear"):
        raise ValueError("Coverage sweep for this scenario requires an explicit path")
    base = m4.normalize_config(supplied_base)
    if factor in ("beacon_count", "vertical_separation") and base["beacon_layout"].get("coordinates_m") is not None:
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
                        "estimate": None, "solver": {"message": message, "method": "scipy.optimize.least_squares/"+options["solver"], "height_parameterization":options["height_parameterization"]}, "diagnostics": {}} for i in range(options["starts"])]}


def run_sweep(config=None, on_progress=None):
    cfg = validate_sweep_config(config)
    result = {"schema_version": SCHEMA_VERSION, "artifact_type": "solver_sweep", "config": cfg,
              "status":"running", "entries":[], "thresholds":THRESHOLDS.copy(),
              "pairing":{"scope":"Identical observations within value/seed; same physical starts within each initializer group",
              "reference":"First variant of each initialization method supplies physical starts; other solvers/parameterizations reuse them",
              "interpretation":"Different initializer methods deliberately have different starts; this is not a solver-only comparison"}}
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
    tables = previous.aggregate_sweep(artifact)
    for row in tables["start_table"]:
        run = artifact["entries"][row["entry_index"]]["run"]; start = run["starts"][row["start_index"]]
        row.update(solver=run["options"]["solver"], height_parameterization=run["options"]["height_parameterization"],
            initialization=run["options"]["initialization"], initializer_status=start.get("diagnostics",{}).get("algebraic_initializer",{}).get("status", start.get("diagnostics",{}).get("initializer",{}).get("status")),
            initializer_error=start.get("diagnostics",{}).get("algebraic_initializer",{}).get("error", start.get("diagnostics",{}).get("initializer",{}).get("error")))
    for summary in tables["aggregates"]:
        group = [r for r in tables["start_table"] if r["value_index"]==summary["value_index"] and r["variant"]==summary["variant"]]
        summary["initializer_invalid_count"] = sum(r["initializer_status"] in ("invalid", "failed", "unsupported") for r in group)
    return tables


def validate_artifact(data):
    """Validate source runs and projection pairing; never generate or solve."""
    try:
        _validate_json_values(data)
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION or data.get("artifact_type") != "solver_sweep":
            raise ValueError("Expected version 5.0 solver_sweep")
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
            if mi and run["experiment"] != entries[index-mi]["run"]["experiment"]:
                raise ValueError("Paired variants must retain identical observations")
            reference_index = entry.get("initial_reference_entry")
            if entry.get("initialization_group") != opts["initialization"]:
                raise ValueError("Initializer grouping mismatch")
            if reference_index is not None:
                if not isinstance(reference_index,int) or reference_index>=index: raise ValueError("Invalid initial reference")
                reference = entries[reference_index]
                if (reference["value_index"],reference["seed"],reference["initialization_group"]) != (vi,seed,opts["initialization"]): raise ValueError("Initial reference belongs to another data/initializer cell")
                if entry.get("pairing_error"):
                    if run["status"]!="failed": raise ValueError("Failed pairing must retain failed run")
                else:
                    projected = m4.compatible_initial_geometries(reference["run"],run["experiment"],opts)
                    if projected != [start.get("initial") for start in run["starts"]]: raise ValueError("Physical starts differ from paired projection")
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
