"""Retain an independent known-map vertical sensitivity check for M4."""
from pathlib import Path
from datetime import datetime, timezone
import json
import sys
import traceback
import uuid

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from uwb import m4


def write_new(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, allow_nan=False)
        stream.write("\n")


def check_case(label, tag_z_m, geometry="equal"):
    config = {"samples": 12, "duration_s": 6., "path": {"type": "rectangle"},
              "beacon_layout": {"count": 6, "geometry": geometry, "height_m": 3., "height_spread_m": 1.},
              "truth_height": {"type": "planar", "offset_m": tag_z_m},
              "noise_std_m": 0., "assumed_std_m": .05,
              "acquisition": {"spacing_s": 0., "jitter_s": 0., "timestamp_offset_s": 0., "timestamp_jitter_s": 0.}}
    options = m4.validate_options({"mode": "known_map", "tag_height_model": "free", "starts": 1,
                                   "below_beacons": False, "prior_sigma_m": 0.})
    experiment = m4.generate_experiment(config)
    truth, inputs = experiment["truth"], experiment["estimator_input"]
    problem = m4.build_problem(inputs["observations"], inputs["times_s"], beacon_count=6,
                               display_times_s=truth["times_s"], surveyed_beacons=truth["beacons"], **options)
    positions, beacons = np.asarray(truth["trajectory"]), np.asarray(truth["beacons"])
    np.testing.assert_allclose(problem.times_s, truth["times_s"], atol=1e-14, rtol=0.)
    parameters = problem.pack(positions, beacons)
    analytic = m4.measurement_jacobian(parameters, problem)
    # The synchronized surveyed/free model has explicit xyz parameters per
    # epoch. This derivative is assembled directly from synthetic coordinates,
    # independently of the core basis/interpolation/Jacobian implementation.
    independent = np.zeros((len(inputs["observations"]), 3 * len(positions)))
    vertical_metres = []
    for row, observation in enumerate(inputs["observations"]):
        epoch, beacon = observation["epoch"], observation["beacon_id"]
        delta = positions[epoch] - beacons[beacon]
        distance = np.linalg.norm(delta)
        independent[row, 3 * epoch:3 * epoch + 3] = delta / (distance * observation["sigma_m"])
        vertical_metres.append(float(delta[2] / distance))
    np.testing.assert_allclose(analytic, independent, rtol=2e-12, atol=2e-12)
    vertical_columns = analytic[:, 2::3]
    vertical_spectrum = np.linalg.svd(vertical_columns, compute_uv=False)
    finite_difference_error = 0.
    for column in range(2, len(parameters), 3):
        perturbation = np.zeros_like(parameters); perturbation[column] = 1e-5
        numeric = (m4.measurement_residuals(parameters + perturbation, problem) -
                   m4.measurement_residuals(parameters - perturbation, problem)) / 2e-5
        finite_difference_error = max(finite_difference_error, float(np.max(np.abs(numeric - analytic[:, column]))))
    if finite_difference_error >= 2e-7:
        raise AssertionError(f"{label}: vertical central derivative mismatch {finite_difference_error}")
    rank = m4.jacobian_diagnostics(parameters, problem)
    return {"label": label, "config": experiment["config"], "options": options,
            "supplied_surveyed_beacons_m": truth["beacons"], "supplied_truth_knots_m": positions.tolist(),
            "epoch_times_s": problem.times_s.tolist(), "sigma_m": .05,
            "derivative_drange_dz": vertical_metres,
            "vertical_derivative_rms": float(np.sqrt(np.mean(np.asarray(vertical_metres) ** 2))),
            "vertical_derivative_max_abs": float(np.max(np.abs(vertical_metres))),
            "vertical_jacobian_singular_values_normalized_per_m": vertical_spectrum.tolist(),
            "vertical_singular_min_normalized_per_m": float(vertical_spectrum[-1]),
            "full_measurement_jacobian": rank,
            "independent_analytic_max_abs_error": float(np.max(np.abs(analytic - independent))),
            "vertical_finite_difference_max_abs_error": finite_difference_error,
            "truth_range_residual_max_abs_m": float(np.max(np.abs(m4.measurement_residuals(parameters, problem) * problem.sigma_m)))}


def main():
    output = ROOT / "evidence" / "m4" / "height_sensitivity.json"
    record = {"schema_version": "4.0", "artifact_type": "height_sensitivity_check", "status": "running",
              "created_at_utc": datetime.now(timezone.utc).isoformat(), "cases": [],
              "independent_derivative": "dR/dz=(p_z-b_z)/R; normalized residual derivative divides by assumed sigma",
              "parameterization": "Known surveyed map; free xyz at synchronous epoch knots; no motion/height prior and no below-beacon bounds",
              "interpretation": ["These are local first-order sensitivities at supplied truth, not optimizer recovery experiments or uncertainty intervals.",
                                 "At the coplanar tag/beacon plane, vertical first derivatives vanish. Ranges still vary to second order away from the plane; Jacobian rank loss alone does not imply a continuous family of solutions.",
                                 "Near-plane nonzero derivatives can be weak despite full local rank; scaling, sigma and geometry are disclosed.",
                                 "Height-diverse beacon coordinates can supply vertical information at nominal plane height. Full local rank does not establish global uniqueness or eliminate reflected/other branches."]}
    try:
        for label, tag_z, geometry in (("on_beacon_plane", 3., "equal"), ("near_beacon_plane_0.1mm", 2.9999, "equal"),
                                       ("near_beacon_plane_5cm", 2.95, "equal"), ("separated_by_3m", 0., "equal"),
                                       ("height_diverse_at_nominal_plane", 3., "diverse")):
            record["cases"].append(check_case(label, tag_z, geometry))
        on, near, medium, separated, diverse = record["cases"]
        assert on["vertical_derivative_max_abs"] == 0.
        assert not on["full_measurement_jacobian"]["full_column_rank"]
        assert on["full_measurement_jacobian"]["rank"] == 24
        assert all(case["full_measurement_jacobian"]["full_column_rank"] for case in (near, medium, separated, diverse))
        assert separated["vertical_singular_min_normalized_per_m"] > 10000 * near["vertical_singular_min_normalized_per_m"]
        assert separated["full_measurement_jacobian"]["condition_number"] < near["full_measurement_jacobian"]["condition_number"] / 10000
        assert diverse["vertical_singular_min_normalized_per_m"] > 1000 * near["vertical_singular_min_normalized_per_m"]
        record["assertions"] = {"independent_derivative_matches_core": True, "central_vertical_differences_match": True,
                                "on_plane_rank": "24/36 with exactly zero vertical derivatives",
                                "separation_strengthens_vertical_min_singular_value_by_more_than": 10000,
                                "height_diversity_strengthens_vertical_min_singular_value_by_more_than": 1000,
                                "all_nonzero_separation_cases_full_rank_locally": True}
        record["status"] = "complete"
        # Never overwrite a prior check, including on a rerun.
        if output.exists():
            output = output.with_name("height_sensitivity_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8] + ".json")
        write_new(output, record)
        print(str(output.relative_to(ROOT)))
        for case in record["cases"]:
            rank = case["full_measurement_jacobian"]
            print(case["label"], f"rank={rank['rank']}/{rank['parameter_count']}",
                  f"vertical_min={case['vertical_singular_min_normalized_per_m']:.8g}", f"condition={rank['condition_number']}")
    except Exception:
        record["status"] = "failed"; record["error"] = traceback.format_exc()
        failure = output.with_name("height_sensitivity_failed_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8] + ".json")
        write_new(failure, record)
        raise


if __name__ == "__main__": main()
