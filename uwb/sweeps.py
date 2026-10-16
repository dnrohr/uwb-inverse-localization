"""Controlled paired sweeps and self-contained saved-run comparisons.

Pairing is within a (factor value, seed) cell: measurements and trajectory
starts are identical. A known-map variant fixes the explicitly surveyed map;
its beacon initial coordinates must therefore be replaced by that map.
"""
from __future__ import annotations

import copy
import csv
import io
import json
import math
from pathlib import Path

import numpy as np

from .estimation import (POSITIVE_FLOOR_M, WEAK_CONDITION_THRESHOLD, _independent_initial, build_problem, evaluate_geometry,
                         fit_observations, jacobian_diagnostics)
from .experiments import (ExperimentFormatError, _normalise_config, _reject_constant,
                          _validate_json_values, _validate_payload, generate_experiment,
                          _replace_with_retry)

SCHEMA_VERSION = "2.0"
MAX_RUNS = 40
MAX_STARTS = 12
MAX_TOTAL_STARTS = 240
FACTORS = ("noise_std_m", "path_scale", "samples", "initial_error_m", "assumed_std_m")
THRESHOLDS = {"exact_geometry_max_m": 1e-5, "exact_range_max_m": 1e-7,
              "noisy_geometry_max_m": .25, "noisy_normalized_residual_rms": 2.,
              "solution_grouping_rms_m": 1e-3}


def _integer(value, name, lower, upper):
    if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
        raise ValueError(f"{name} must be an integer from {lower} through {upper}")
    return value


def validate_sweep_config(config):
    """Normalize bounded, single-factor controls before any solve is attempted."""
    if not isinstance(config, dict):
        raise ValueError("Sweep configuration must be an object")
    if set(config) - {"factor", "values", "seeds", "experiment", "options", "variants"}:
        raise ValueError("Unsupported sweep configuration keys")
    _validate_json_values(config)
    factor = config.get("factor", "noise_std_m")
    if factor not in FACTORS:
        raise ValueError(f"factor must be one of {', '.join(FACTORS)}")
    values = config.get("values", [0., .05, .1])
    if not isinstance(values, list) or not 1 <= len(values) <= 10:
        raise ValueError("Supply 1–10 factor values")
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Factor values must be finite numbers")
        if factor == "samples":
            _integer(value, "samples", 8, 100)
        elif factor == "path_scale":
            if not .01 <= value <= 100:
                raise ValueError("path_scale must be from 0.01 through 100")
        elif value < 0 or (factor == "assumed_std_m" and value == 0):
            raise ValueError("Factor value must be nonnegative; assumed uncertainty must be positive")
        elif factor in ("noise_std_m", "initial_error_m") and value > 100:
            raise ValueError("Noise and initial parameter error SD are limited to 100 m")
        elif factor == "assumed_std_m" and not 1e-6 <= value <= 1000:
            raise ValueError("Assumed uncertainty must be from 1e-6 through 1000 m")
    if len(set(values)) != len(values):
        raise ValueError("Factor values must be distinct")
    seeds = config.get("seeds", [7, 8])
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= 10:
        raise ValueError("Supply 1–10 distinct seeds")
    for seed in seeds:
        _integer(seed, "seed", 0, 2**32 - 1)
    if len(set(seeds)) != len(seeds):
        raise ValueError("Supply distinct seeds")
    supplied = config.get("options", {})
    if not isinstance(supplied, dict) or set(supplied) - {"mode", "initialization", "starts", "seed", "max_nfev"}:
        raise ValueError("Invalid sweep solver options")
    options = {"mode": "joint", "initialization": "independent", "starts": 2, "seed": 19, "max_nfev": 1000, **supplied}
    _integer(options["starts"], "starts", 1, MAX_STARTS)
    _integer(options["seed"], "initialization seed", 0, 2**32 - 1)
    _integer(options["max_nfev"], "max_nfev", 1, 5000)
    if options["mode"] not in ("joint", "known_map") or options["initialization"] not in ("independent", "truth_near"):
        raise ValueError("Unsupported mode or initialization")
    if factor == "initial_error_m":
        options["initialization"] = "truth_near"
    variants = config.get("variants", [{"label": "budget_200", "max_nfev": 200},
                                        {"label": "budget_1000", "max_nfev": 1000}])
    if not isinstance(variants, list) or not 1 <= len(variants) <= 4:
        raise ValueError("Supply 1–4 paired variants")
    normalized = []
    for variant in variants:
        if not isinstance(variant, dict) or set(variant) - {"label", "mode", "max_nfev"}:
            raise ValueError("Variants may only change mode or evaluation budget")
        item = {"label": variant.get("label"), "mode": variant.get("mode", options["mode"]),
                "max_nfev": variant.get("max_nfev", options["max_nfev"])}
        if not isinstance(item["label"], str) or not item["label"].strip() or len(item["label"]) > 80:
            raise ValueError("Every variant needs a nonempty label of at most 80 characters")
        if item["mode"] not in ("joint", "known_map"):
            raise ValueError("Variant mode must be joint or known_map")
        _integer(item["max_nfev"], "variant max_nfev", 1, 5000)
        normalized.append(item)
    if len({v["label"] for v in normalized}) != len(normalized):
        raise ValueError("Variant labels must be distinct")
    count = len(values) * len(seeds) * len(normalized)
    if count > MAX_RUNS or count * options["starts"] > MAX_TOTAL_STARTS:
        raise ValueError(f"Sweep limit: {MAX_RUNS} runs, {MAX_TOTAL_STARTS} total starts")
    experiment = copy.deepcopy(config.get("experiment", {}))
    if not isinstance(experiment, dict):
        raise ValueError("Sweep experiment controls must be an object")
    if factor == "path_scale" and "path" not in experiment:
        scenario = experiment.get("scenario", "informative")
        if scenario not in ("informative", "nearly_collinear"):
            raise ValueError("path_scale for this reference scenario requires an explicit path so the sweep preserves path shape")
    base = _normalise_config(experiment)  # validate controls without regenerating saved observations
    if max(base["noise_std_m"]) > 100 or min(base["assumed_std_m"]) < 1e-6 or max(base["assumed_std_m"]) > 1000:
        raise ValueError("Sweep base noise is limited to 100 m; assumed uncertainty must be 1e-6–1000 m")
    result = {"factor": factor, "values": copy.deepcopy(values), "seeds": seeds.copy(),
              "experiment": experiment, "options": options, "variants": normalized}
    for value in values:
        _normalise_config(_cell_config(result, value, seeds[0]))
    return result


def _cell_config(config, value, seed):
    experiment = copy.deepcopy(config["experiment"])
    experiment["seed"] = seed
    factor = config["factor"]
    if factor == "path_scale":
        experiment.setdefault("path", {})["scale"] = value
    elif factor != "initial_error_m":
        experiment[factor] = value
    return experiment


def _initials(experiment, config, value, seed):
    inputs, truth = experiment["estimator_input"], experiment["truth"]
    mode = "joint" if any(v["mode"] == "joint" for v in config["variants"]) else "known_map"
    problem = build_problem(inputs["observations"], inputs["times_s"], mode=mode,
                            surveyed_beacons=truth["beacons"] if mode == "known_map" else None)
    init_seed = (config["options"]["seed"] + seed) % 2**32
    rng = np.random.default_rng(init_seed)
    initials = []
    for index in range(config["options"]["starts"]):
        if config["options"]["initialization"] == "independent":
            initials.append(_independent_initial(problem, rng, index))
        else:
            scale = value if config["factor"] == "initial_error_m" else .15
            x = problem.pack(truth["trajectory"], truth["beacons"])
            x += rng.normal(0., scale, x.shape)
            if mode == "joint":
                x[[-6, -4, -1]] = np.maximum(x[[-6, -4, -1]], 2 * POSITIVE_FLOOR_M)
            trajectory, beacons = problem.unpack(x)
            initials.append({"trajectory": trajectory.tolist(), "beacons": beacons.tolist()})
    return initials, init_seed


def _solve_cell(experiment, options, initials):
    inputs, truth = experiment["estimator_input"], experiment["truth"]
    mode = options["mode"]
    initial = copy.deepcopy(initials)
    if mode == "known_map":
        for geometry in initial:
            geometry["beacons"] = copy.deepcopy(truth["beacons"])
    outcomes = fit_observations(inputs["observations"], inputs["times_s"], mode=mode,
                                surveyed_beacons=truth["beacons"] if mode == "known_map" else None,
                                starts=options["starts"], seed=options["seed"],
                                initial_geometries=initial, max_nfev=options["max_nfev"])
    finite = [s for s in outcomes if s["estimate"] is not None]
    for start in finite:
        start["diagnostics"]["evaluation"] = evaluate_geometry(start["estimate"], truth, mode)
    preferred = [s for s in finite if s["success"]] or finite
    selected = min(preferred, key=lambda s: s["solver"]["final_objective"])["index"] if preferred else None
    problem = build_problem(inputs["observations"], inputs["times_s"], mode=mode,
                            surveyed_beacons=truth["beacons"] if mode == "known_map" else None)
    rank = jacobian_diagnostics(problem.pack(truth["trajectory"], truth["beacons"]), problem)
    return {"schema_version": "1.0", "experiment": copy.deepcopy(experiment), "options": options,
            "starts": outcomes, "selected_start": selected,
            "status": outcomes[selected]["status"] if selected is not None else "failed",
            "software_versions": experiment["software_versions"].copy(),
            "diagnostics": {"truth_jacobian": rank, "failure_count": sum(not s["success"] for s in outcomes),
                            "warnings": [] if rank["full_column_rank"] else ["Truth measurement Jacobian is rank deficient"],
                            "surveyed_map_source": "Synthetic truth explicitly provided as surveyed map" if mode == "known_map" else None}}


def run_sweep(config=None, on_progress=None):
    """Execute every bounded cell; retain every run and start, including failures."""
    cfg = validate_sweep_config(config or {})
    entries = []
    result = {"schema_version": SCHEMA_VERSION, "artifact_type": "sweep", "config": cfg,
              "status": "running", "limits": {"max_runs": MAX_RUNS, "max_starts_per_run": MAX_STARTS, "max_total_starts": MAX_TOTAL_STARTS},
              "thresholds": THRESHOLDS.copy(), "entries": entries,
              "pairing": {"scope": "Identical observations and trajectory starts within each value/seed cell",
                          "noise": "Same seed reuses standard-normal draws across noise levels; sample-count levels have different grids",
                          "initialization": "truth_near is diagnostic; initial_error_m is Gaussian parameter SD, with constrained positive coordinates clipped at twice the solver floor (2e-6 m)",
                          "map_constraint": "Known-map mode fixes the synthetic surveyed truth map and projects only beacon starts onto it; joint mode fits its map",
                          "default_variants": "Same estimator and starts, differing only in evaluation budget"}}
    for value_index, value in enumerate(cfg["values"]):
        for seed in cfg["seeds"]:
            experiment = generate_experiment(_cell_config(cfg, value, seed))
            init_seed = (cfg["options"]["seed"] + seed) % 2**32
            initialization_error = None
            try:
                initials, init_seed = _initials(experiment, cfg, value, seed)
            except Exception as exc:
                initials = [None] * cfg["options"]["starts"]
                initialization_error = f"Initialization {type(exc).__name__}: {exc}"
            for variant_index, variant in enumerate(cfg["variants"]):
                options = {**cfg["options"], "mode": variant["mode"], "seed": init_seed, "max_nfev": variant["max_nfev"]}
                try:
                    if initialization_error is not None:
                        raise ValueError(initialization_error)
                    run = _solve_cell(experiment, options, initials)
                except Exception as exc:
                    message = f"{type(exc).__name__}: {exc}"
                    failed_initials = copy.deepcopy(initials)
                    if options["mode"] == "known_map":
                        for geometry in failed_initials:
                            if geometry is not None:
                                geometry["beacons"] = copy.deepcopy(experiment["truth"]["beacons"])
                    run = {"schema_version": "1.0", "experiment": copy.deepcopy(experiment), "options": options,
                           "status": "failed", "selected_start": None, "error": message, "diagnostics": {},
                           "starts": [{"index": i, "status": "failed", "success": False, "initial": g,
                                       "estimate": None, "solver": {"message": message}, "diagnostics": {}}
                                      for i, g in enumerate(failed_initials)]}
                entries.append({"index": len(entries), "value_index": value_index, "value": value, "seed": seed,
                                "variant_index": variant_index, "variant": variant["label"], "run": run})
                _refresh_sweep(result)
                if on_progress is not None:
                    on_progress(copy.deepcopy(result))
    result["status"] = "complete"
    _refresh_sweep(result)
    validate_artifact(result)
    return result


def _distribution(values):
    numbers = [float(v) for v in values if v is not None]
    return {"count": len(numbers), "min": min(numbers) if numbers else None,
            "median": float(np.median(numbers)) if numbers else None,
            "p90": float(np.percentile(numbers, 90)) if numbers else None,
            "max": max(numbers) if numbers else None}


def aggregate_sweep(sweep):
    """Report all-start variability separately from the selected run outcome."""
    rows, groups = [], {}
    thresholds = sweep.get("thresholds", THRESHOLDS)
    for entry in sweep["entries"]:
        run = entry["run"]
        exact = not any(run["experiment"]["config"]["noise_std_m"])
        representatives, low_representatives = [], []
        for start in run["starts"]:
            diagnostics = start.get("diagnostics", {})
            evaluation = diagnostics.get("evaluation")
            error = evaluation["raw" if exact else "aligned"] if evaluation else {}
            raw_error = evaluation["raw"] if evaluation else {}
            normalized = diagnostics.get("residuals_normalized", [])
            norm_rms = float(np.sqrt(np.mean(np.square(normalized)))) if normalized else None
            geometry = bool(error and error["position_max_error_m"] <= thresholds["exact_geometry_max_m" if exact else "noisy_geometry_max_m"]
                            and max(error["beacon_errors_m"]) <= thresholds["exact_geometry_max_m" if exact else "noisy_geometry_max_m"])
            low = bool(evaluation and (diagnostics["max_abs_residual_m"] <= thresholds["exact_range_max_m"] if exact
                                       else norm_rms is not None and norm_rms <= thresholds["noisy_normalized_residual_rms"]))
            converged = bool(start.get("success"))
            exact_geometry = bool(raw_error and raw_error["position_max_error_m"] <= thresholds["exact_geometry_max_m"]
                                  and max(raw_error["beacon_errors_m"]) <= thresholds["exact_geometry_max_m"])
            classification = "failed" if start.get("estimate") is None else "not_converged" if not converged else "accepted" if geometry and low else "converged_outside_thresholds"
            row = {"entry_index": entry["index"], "value": entry["value"], "value_index": entry["value_index"],
                   "seed": entry["seed"], "variant": entry["variant"], "start_index": start["index"],
                   "selected": start["index"] == run.get("selected_start"), "status": start["status"],
                   "optimizer_converged": converged, "geometric_recovery": geometry, "low_residual": low,
                   "exact_reference_geometry": exact and exact_geometry,
                   "noisy_geometric_accuracy": not exact and geometry,
                   "error_frame": "raw canonical/surveyed" if exact else "proper planar rigid aligned joint; surveyed known-map",
                   "accepted": converged and geometry and low, "classification": classification, "exact_data": exact,
                   "position_rmse_m": error.get("position_rmse_m"), "position_max_error_m": error.get("position_max_error_m"),
                   "map_rmse_m": error.get("map_rmse_m"), "range_rmse_m": diagnostics.get("range_rmse_m"),
                   "normalized_residual_rms": norm_rms, "objective": start.get("solver", {}).get("final_objective"),
                   "runtime_s": start.get("solver", {}).get("runtime_s"), "full_column_rank": diagnostics.get("jacobian", {}).get("full_column_rank"),
                   "condition_number": diagnostics.get("jacobian", {}).get("condition_number"),
                   "truth_full_column_rank": run.get("diagnostics", {}).get("truth_jacobian", {}).get("full_column_rank")}
            rows.append(row)
            if evaluation:
                g = evaluation["aligned_geometry"]
                signature = np.concatenate((np.ravel(g["trajectory"]), np.ravel(g["beacons"])))
                for refs, eligible in ((representatives, True), (low_representatives, low)):
                    if eligible and not any(float(np.sqrt(np.mean((signature - ref)**2))) <= thresholds["solution_grouping_rms_m"] for ref in refs):
                        refs.append(signature)
        groups[entry["index"]] = {"entry_index": entry["index"], "distinct_solution_count": len(representatives),
                                   "distinct_low_residual_solution_count": len(low_representatives)}
    summary = []
    for value_index, value in enumerate(sweep["config"]["values"]):
        for variant in sweep["config"]["variants"]:
            subset = [r for r in rows if r["value_index"] == value_index and r["variant"] == variant["label"]]
            entries = [e for e in sweep["entries"] if e["value_index"] == value_index and e["variant"] == variant["label"]]
            selected = [r for r in subset if r["selected"]]
            summary.append({"value_index": value_index, "value": value, "variant": variant["label"],
                            "run_count": len(entries), "start_count": len(subset), "failed_start_count": sum(not r["optimizer_converged"] for r in subset),
                            "failure_rate": sum(not r["optimizer_converged"] for r in subset) / len(subset) if subset else None,
                            "failed_run_count": sum(e["run"]["status"] != "success" for e in entries),
                            "accepted_start_count": sum(r["accepted"] for r in subset),
                            "rank_deficient_start_count": sum(r["full_column_rank"] is False for r in subset),
                            "selected_seed_position_rmse_m": _distribution([r["position_rmse_m"] for r in selected]),
                            "all_start_position_rmse_m": _distribution([r["position_rmse_m"] for r in subset]),
                            "all_start_map_rmse_m": _distribution([r["map_rmse_m"] for r in subset]),
                            "runtime_s": _distribution([r["runtime_s"] for r in subset]),
                            "max_distinct_low_residual_solutions_in_one_cell": max((groups[e["index"]]["distinct_low_residual_solution_count"] for e in entries), default=0)})
    return {"start_table": rows, "aggregates": summary, "solution_groups": list(groups.values()),
            "aggregation_convention": "All attempted starts enter failure denominators; geometry distributions include finite nonconverged starts; selected-seed distributions use the selected start. Exact geometry uses raw canonical/surveyed errors; noisy geometry uses proper planar rigid aligned joint errors. Acceptance thresholds are disclosed heuristics, independent of rank, and do not establish uniqueness. Solution groups are per identical-data cell, proper planar rigid aligned, RMS over all xyz coordinates; no cross-seed grouping."}


def _refresh_sweep(sweep):
    sweep.update(aggregate_sweep(sweep))
    for entry, group in zip(sweep["entries"], sweep["solution_groups"]):
        run = entry["run"]
        rows = [r for r in sweep["start_table"] if r["entry_index"] == entry["index"]]
        chosen = next((r for r in rows if r["selected"]), None)
        classifications = []
        for start, row in zip(run["starts"], rows):
            raw = start["diagnostics"].get("evaluation", {}).get("raw", {})
            exact_geometry = bool(raw and raw["position_max_error_m"] <= THRESHOLDS["exact_geometry_max_m"]
                                  and max(raw["beacon_errors_m"]) <= THRESHOLDS["exact_geometry_max_m"])
            exact_ranges = bool(start["estimate"] and start["diagnostics"]["max_abs_residual_m"] <= THRESHOLDS["exact_range_max_m"])
            classification = "failed" if start["estimate"] is None else "not_converged" if not start["success"] else "geometry_recovered" if exact_geometry else "converged_geometry_inaccurate"
            start["diagnostics"].update(geometric_recovery=exact_geometry, range_recovery=exact_ranges,
                                         recovery_classification=classification,
                                         exact_reference_geometry=row["exact_reference_geometry"],
                                         noisy_geometric_accuracy=row["noisy_geometric_accuracy"])
            classifications.append({"index": start["index"], "optimizer_converged": start["success"],
                                    "geometric_recovery": exact_geometry, "range_recovery": exact_ranges,
                                    "classification": classification})
        diagnostic = run["diagnostics"]
        diagnostic.update({k: v for k, v in group.items() if k != "entry_index"})
        diagnostic.update(solution_grouping_rms_threshold_m=THRESHOLDS["solution_grouping_rms_m"],
                          low_residual_max_abs_threshold_m=THRESHOLDS["exact_range_max_m"],
                          low_residual_criterion="Maximum absolute range residual <=1e-7 m" if not any(run["experiment"]["config"]["noise_std_m"]) else "Normalized residual RMS <=2 (disclosed heuristic; depends on assumed uncertainty)",
                          noisy_low_residual_normalized_rms_threshold=THRESHOLDS["noisy_normalized_residual_rms"],
                          solution_grouping="Proper planar rigid aligned geometry RMS; no scale or reflections",
                          acceptance_geometry_tolerance_m=THRESHOLDS["exact_geometry_max_m"],
                          acceptance_max_range_residual_m=THRESHOLDS["exact_range_max_m"],
                          start_recovery_outcomes=classifications,
                          geometric_recovery_count=sum(r["geometric_recovery"] for r in classifications),
                          range_recovery_count=sum(r["range_recovery"] for r in classifications),
                          geometric_recovery=bool(chosen and next(c["geometric_recovery"] for c in classifications if c["index"] == chosen["start_index"])),
                          failure_count=sum(not s["success"] for s in run["starts"]),
                          weak_condition_threshold=WEAK_CONDITION_THRESHOLD,
                          ambiguity="Full measurement rank is local only; finite multistart exploration does not prove global uniqueness")
        warnings = diagnostic.setdefault("warnings", [])
        for source, rank in [("Truth", diagnostic.get("truth_jacobian", {}))] + [(f"Start {s['index']}", s["diagnostics"].get("jacobian", {})) for s in run["starts"]]:
            rank_warning = f"{source} measurement Jacobian is rank deficient"
            if rank.get("full_column_rank") is False and rank_warning not in warnings:
                warnings.append(rank_warning)
            warning = f"{source} geometry is weakly conditioned (condition number exceeds 1000)"
            if rank.get("condition_number") and rank["condition_number"] > WEAK_CONDITION_THRESHOLD and warning not in warnings:
                warnings.append(warning)


def build_comparison(left_run, right_run, alignment="aligned", *, _validate=True):
    """Prepare fitted samples, disclosed interpolation, bounds and table; never solve."""
    if alignment not in ("raw", "aligned"):
        raise ValueError("alignment must be raw or aligned")
    for run in (left_run, right_run):
        _validate_payload(run)
        if "experiment" not in run:
            raise ValueError("Comparison requires saved run envelopes")
    elapsed = [np.asarray(r["experiment"]["truth"]["times_s"], dtype=float) for r in (left_run, right_run)]
    elapsed = [t - t[0] for t in elapsed]
    common = np.unique(np.concatenate(elapsed))
    views, table, coordinates = [], [], []
    for index, (run, times) in enumerate(zip((left_run, right_run), elapsed)):
        truth = copy.deepcopy(run["experiment"]["truth"])
        selected = next((s for s in run["starts"] if s["index"] == run.get("selected_start")), None)
        estimate = selected.get("estimate") if selected else None
        if estimate and run.get("schema_version") == "7.0":
            from .m7 import evaluate_geometry as evaluate_m7
            evaluation = evaluate_m7(estimate, truth, run.get("options"))
        elif estimate and run.get("schema_version") in ("4.0","5.0","6.0","7.0"):
            from .m4 import evaluate_geometry as evaluate_m4
            options = run.get("options", {})
            if run.get("schema_version") == "6.0":
                from .m6 import base_options as m6_base_options
                options = m6_base_options(options)
            if run.get("schema_version") in ("5.0", "6.0"):
                from .m5 import base_options
                options = base_options(options)
            evaluation = evaluate_m4(estimate, truth, options)
            if alignment == "raw" and run.get("options", {}).get("mode") == "joint":
                canonical = evaluation["truth_canonical_transform"]
                for key in ("trajectory", "beacons"):
                    truth[key] = (np.asarray(truth[key]) @ np.asarray(canonical["rotation_xyz"]) + np.asarray(canonical["translation_xyz_m"])).tolist()
        else:
            evaluation = evaluate_geometry(estimate, truth, run.get("options", {}).get("mode", "joint")) if estimate else None
        geometry = copy.deepcopy(evaluation["aligned_geometry"] if alignment == "aligned" and evaluation else estimate)
        transform = evaluation["alignment"] if alignment == "aligned" and evaluation else {"applied": False, "scale": 1., "reflection_allowed": False}
        initial = copy.deepcopy(selected.get("initial")) if selected else None
        if initial and transform.get("applied"):
            for key in ("trajectory", "beacons"):
                array = np.asarray(initial[key], dtype=float)
                if "rotation_xyz" in transform:
                    array = array @ np.asarray(transform["rotation_xyz"]) + np.asarray(transform["translation_xyz_m"])
                else:
                    array[:, :2] = array[:, :2] @ np.asarray(transform["rotation_xy"]) + np.asarray(transform["translation_xy_m"])
                    array[:, 2] += transform.get("gauge_translation_z_m", 0.)
                initial[key] = array.tolist()
        interpolated = []
        for t in common:
            if geometry is None or t < times[0] or t > times[-1]:
                interpolated.append(None)
            else:
                interpolated.append([float(np.interp(t, times, np.asarray(geometry["trajectory"])[:, axis])) for axis in range(3)])
        error = evaluation[alignment] if evaluation else {}
        diagnostics = selected.get("diagnostics", {}) if selected else {}
        views.append({"index": index, "id": run.get("id"), "times_elapsed_s": times.tolist(),
                      "truth": truth, "estimate": geometry, "initial": initial,
                      "alignment": transform, "position_errors_m": error.get("position_errors_m", []),
                      "residuals_m": diagnostics.get("residuals_m", []),
                      "interpolated_trajectory": interpolated,
                      "sample_kind": "interpolated M4 display samples; trajectory parameters are saved knots" if run.get("schema_version") in ("4.0","5.0","6.0","7.0") else "interpolated M3 display samples; trajectory parameters are saved knots" if run.get("schema_version") == "3.0" else "fitted epoch samples",
                      "color_quantity": "Euclidean matched-time position error in metres at saved display times" if run.get("schema_version") in ("3.0","4.0","5.0","6.0","7.0") else "Euclidean matched-time position error in metres at fitted epochs"})
        table.append({"side": "left" if index == 0 else "right", "id": run.get("id"), "status": run["status"],
                      "mode": run.get("options", {}).get("mode"), "samples": len(times), "starts": len(run["starts"]),
                      "selected_start": run.get("selected_start"), "position_rmse_m": error.get("position_rmse_m"),
                      "map_rmse_m": error.get("map_rmse_m"), "range_rmse_m": diagnostics.get("range_rmse_m"),
                      "runtime_s": (sum(s["solver"]["runtime_s"] for s in run["starts"])
                                    if run["starts"] and all(s.get("solver", {}).get("runtime_s") is not None for s in run["starts"]) else None),
                      "optimizer_converged": bool(selected and selected.get("success")),
                      "full_column_rank": diagnostics.get("jacobian", {}).get("full_column_rank")})
        for g in (truth, geometry, initial):
            if g:
                coordinates.extend(g["trajectory"]); coordinates.extend(g["beacons"])
    array = np.asarray(coordinates)
    lower, upper = array.min(axis=0), array.max(axis=0)
    center = (lower + upper) / 2
    half = max(float(np.max(upper - lower)) / 2 * 1.1, .5)
    bounds = {axis: [float(c - half), float(c + half)] for axis, c in zip(("x", "y", "z"), center)}
    result = {"schema_version": SCHEMA_VERSION, "artifact_type": "comparison", "runs": [copy.deepcopy(left_run), copy.deepcopy(right_run)],
              "alignment": alignment, "views": views, "table": table, "shared_bounds_m": bounds,
              "common_elapsed_times_s": common.tolist(), "time_reference": "Elapsed seconds from each run's first saved display time; no time warping" if any(r.get("schema_version") in ("3.0","4.0","5.0","6.0","7.0") for r in (left_run, right_run)) else "Elapsed seconds from each run's first fitted epoch; no time warping",
              "interpolation": "Piecewise linear rendering on union of saved display times, no extrapolation; M4 statistics use saved display samples, trajectory parameters are knots" if any(r.get("schema_version") in ("4.0","5.0","6.0","7.0") for r in (left_run, right_run)) else "Piecewise linear rendering on union of saved display times, no extrapolation; M3 statistics use saved display samples, trajectory parameters are knots" if any(r.get("schema_version") == "3.0" for r in (left_run, right_run)) else "Piecewise linear rendering on the union of elapsed epoch times, no extrapolation; statistics use original fitted samples only",
              "spatial_convention": "Shared metre axes and equal aspect ratio; model-valid proper planar/3D rigid alignment, scale=1, reflections forbidden" if any(r.get("schema_version") in ("4.0","5.0","6.0","7.0") for r in (left_run, right_run)) else "Shared metre axes and equal aspect ratio; proper planar rigid map-to-truth alignment only, scale=1, reflections forbidden"}
    same_data = left_run['experiment']['estimator_input'] == right_run['experiment']['estimator_input']
    left_initials = [a.get('initial') for a in left_run['starts']]
    right_initials = [a.get('initial') for a in right_run['starts']]
    same_starts = bool(left_initials) and all(a is not None for a in left_initials) and left_initials == right_initials
    result['pairing'] = {'identical_estimator_inputs': same_data, 'identical_physical_starts': same_starts,
                         'paired': same_data and same_starts,
                         'interpretation': 'Exact source-record equality; differing projected starts require separate recorded model-specific compatibility evidence.'}
    if _validate:
        validate_artifact(result)
    return result


def validate_artifact(data):
    """Strict schema/accounting validation without regenerating or solving runs."""
    try:
        _validate_artifact(data)
    except ExperimentFormatError:
        raise
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ExperimentFormatError(f"Invalid sweep/comparison format: {exc}") from exc


def _validate_artifact(data):
    _validate_json_values(data)
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ExperimentFormatError("Expected version 2.0 sweep/comparison")
    kind = data.get("artifact_type")
    if kind == "sweep":
        cfg = validate_sweep_config(data.get("config"))
        if cfg != data["config"]:
            raise ExperimentFormatError("Sweep config must be normalized")
        entries = data.get("entries")
        expected = [(vi, seed, pi) for vi in range(len(cfg["values"])) for seed in cfg["seeds"] for pi in range(len(cfg["variants"]))]
        if data.get("status") not in ("running", "complete", "failed"):
            raise ExperimentFormatError("Invalid sweep status")
        if not isinstance(entries, list) or len(entries) > len(expected) or (data["status"] == "complete" and len(entries) != len(expected)):
            raise ExperimentFormatError("Sweep must account for every attempted run")
        for index, (entry, identity) in enumerate(zip(entries, expected)):
            vi, seed, pi = identity
            if (entry.get("index"), entry.get("value_index"), entry.get("seed"), entry.get("variant_index")) != (index, vi, seed, pi) or entry.get("value") != cfg["values"][vi] or entry.get("variant") != cfg["variants"][pi]["label"]:
                raise ExperimentFormatError("Sweep entry identity disagrees with configuration")
            run = entry["run"]
            _validate_payload(run)
            if run["experiment"]["config"] != _normalise_config(_cell_config(cfg, cfg["values"][vi], seed)):
                raise ExperimentFormatError("Saved experiment configuration disagrees with sweep cell")
            variant = cfg["variants"][pi]
            expected_options = {**cfg["options"], "mode": variant["mode"], "max_nfev": variant["max_nfev"],
                                "seed": (cfg["options"]["seed"] + seed) % 2**32}
            if run.get("options") != expected_options:
                raise ExperimentFormatError("Saved solver options disagree with sweep variant")
            if len(run["starts"]) != cfg["options"]["starts"] or [s["index"] for s in run["starts"]] != list(range(cfg["options"]["starts"])):
                raise ExperimentFormatError("Sweep must account for every attempted start")
            first = entries[index - pi]["run"]
            if run["experiment"] != first["experiment"] or any((s["initial"] or {}).get("trajectory") != (ref["initial"] or {}).get("trajectory") for s, ref in zip(run["starts"], first["starts"])):
                raise ExperimentFormatError("Paired variants must share identical observations and trajectory starts")
            if variant["mode"] == first["options"]["mode"] and any((s["initial"] or {}).get("beacons") != (ref["initial"] or {}).get("beacons") for s, ref in zip(run["starts"], first["starts"])):
                raise ExperimentFormatError("Paired identical modes must share beacon starts")
            for start in run["starts"]:
                if start.get("status") not in ("success", "not_converged", "failed") or not isinstance(start.get("success"), bool):
                    raise ExperimentFormatError("Invalid saved start status")
                if start["success"] != (start["status"] == "success") or (start["status"] == "failed") != (start.get("estimate") is None):
                    raise ExperimentFormatError("Saved start status/geometry disagree")
        if not isinstance(data.get("thresholds"), dict) or set(data["thresholds"]) != set(THRESHOLDS) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0 for v in data["thresholds"].values()):
            raise ExperimentFormatError("Invalid disclosed thresholds")
        aggregate = aggregate_sweep(data)
        for key in ("start_table", "aggregates", "solution_groups"):
            if data.get(key) != aggregate[key]:
                raise ExperimentFormatError(f"Saved {key} disagrees with attempted runs")
    elif kind == "comparison":
        if data.get("alignment") not in ("raw", "aligned") or len(data.get("runs", [])) != 2 or len(data.get("views", [])) != 2 or len(data.get("table", [])) != 2:
            raise ExperimentFormatError("Comparison requires two runs and two views")
        for run, view in zip(data["runs"], data["views"]):
            _validate_payload(run)
            transform = view.get("alignment", {})
            if transform.get("scale") != 1. or transform.get("reflection_allowed") is not False:
                raise ExperimentFormatError("Comparison alignment must preserve scale and forbid reflections")
        reference = build_comparison(*data["runs"], alignment=data["alignment"], _validate=False)
        if "pairing" in data and data["pairing"] != reference["pairing"]:
            raise ExperimentFormatError("Saved pairing claim disagrees with source observations/physical starts")
        for key in ("views", "table", "shared_bounds_m", "common_elapsed_times_s", "time_reference", "interpolation", "spatial_convention"):
            # Early M3 comparison exports used the historical epoch wording.
            # Accept those exact labels while still validating all source data.
            legacy_labels = {
                "time_reference": "Elapsed seconds from each run's first fitted epoch; no time warping",
                "interpolation": "Piecewise linear rendering on the union of elapsed epoch times, no extrapolation; statistics use original fitted samples only"}
            if key in legacy_labels and any(run.get("schema_version") == "3.0" for run in data["runs"]) and data.get(key) == legacy_labels[key]:
                continue
            if data.get(key) != reference[key]:
                raise ExperimentFormatError(f"Saved comparison {key} disagrees with source runs")
    else:
        raise ExperimentFormatError("Unsupported artifact type")


def save_artifact(path, data):
    validate_artifact(data)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    _replace_with_retry(temporary, target)


def load_artifact(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ExperimentFormatError(f"Invalid JSON: {exc}") from exc
    validate_artifact(data)
    return data


def table_csv(artifact):
    """CSV export with a row for every start (sweep) or saved run (comparison)."""
    validate_artifact(artifact)
    rows = artifact["start_table"] if artifact["artifact_type"] == "sweep" else artifact["table"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else [])
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()
