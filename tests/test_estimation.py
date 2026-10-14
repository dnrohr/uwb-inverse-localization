import copy
import json
import unittest

import numpy as np

from uwb.estimation import (build_problem, evaluate_geometry, fit_observations,
                            jacobian, jacobian_diagnostics, residuals, solve_experiment)
from uwb.experiments import generate_experiment


class EstimationTests(unittest.TestCase):
    def test_exact_reference_recovers_geometry_and_ranges_in_both_modes(self):
        experiment = generate_experiment()
        for mode in ("known_map", "joint"):
            for initialization in ("independent", "truth_near"):
                with self.subTest(mode=mode, initialization=initialization):
                    run = solve_experiment(experiment, {"mode": mode, "initialization": initialization})
                    self.assertEqual(run["status"], "success")
                    chosen = run["starts"][run["selected_start"]]
                    diagnostics = chosen["diagnostics"]
                    self.assertLess(diagnostics["max_abs_residual_m"], 1e-7)
                    self.assertLess(diagnostics["evaluation"]["raw"]["position_max_error_m"], 1e-5)
                    self.assertLess(max(diagnostics["evaluation"]["raw"]["beacon_errors_m"]), 1e-5)
                    self.assertTrue(diagnostics["jacobian"]["full_column_rank"])
                    self.assertTrue(run["diagnostics"]["truth_jacobian"]["full_column_rank"])
                    self.assertEqual(len(run["starts"]), 3)
                    self.assertEqual(run["diagnostics"]["geometric_recovery_count"], 3)
                    self.assertEqual(run["diagnostics"]["distinct_low_residual_solution_count"], 1)
                    if mode == "joint" and initialization == "independent":
                        self.assertNotEqual(chosen["initial"]["beacons"], experiment["truth"]["beacons"])
                    # All starts, not just the winner, are retained and interpretable.
                    for start in run["starts"]:
                        self.assertEqual(len(start["initial"]["trajectory"]), 32)
                        self.assertIsNone(start["solver"]["iterations"])
                    json.dumps(run, allow_nan=False)

    def test_analytic_jacobian_agrees_with_central_finite_differences(self):
        experiment = generate_experiment({"samples": 12})
        inputs, truth = experiment["estimator_input"], experiment["truth"]
        for mode in ("joint", "known_map"):
            with self.subTest(mode=mode):
                problem = build_problem(inputs["observations"], inputs["times_s"], mode=mode,
                                        surveyed_beacons=truth["beacons"] if mode == "known_map" else None)
                x = problem.pack(truth["trajectory"], truth["beacons"])
                x += np.random.default_rng(4).normal(0, .1, x.shape)
                actual = jacobian(x, problem)
                numeric = np.zeros_like(actual)
                for column in range(len(x)):
                    step = np.zeros_like(x); step[column] = 1e-5
                    numeric[:, column] = (residuals(x + step, problem) - residuals(x - step, problem)) / 2e-5
                np.testing.assert_allclose(actual, numeric, rtol=2e-7, atol=2e-7)

    def test_straight_line_reports_rank_deficit_despite_small_residual(self):
        run = solve_experiment(generate_experiment({"scenario": "straight_line"}), {"starts": 2})
        truth_rank = run["diagnostics"]["truth_jacobian"]
        self.assertLess(truth_rank["rank"], truth_rank["parameter_count"])
        self.assertIsNone(truth_rank["condition_number"])
        self.assertTrue(run["diagnostics"]["warnings"])
        chosen = run["starts"][run["selected_start"]]
        self.assertLess(chosen["diagnostics"]["max_abs_residual_m"], 1e-7)
        self.assertFalse(chosen["diagnostics"]["geometric_recovery"])
        self.assertEqual(chosen["diagnostics"]["recovery_classification"], "converged_geometry_inaccurate")
        self.assertEqual(run["diagnostics"]["distinct_low_residual_solution_count"], 2)

    def test_weak_geometries_expose_worse_conditioning(self):
        ranks = {}
        for scenario in ("informative", "narrow_coverage", "nearly_collinear"):
            experiment = generate_experiment({"scenario": scenario})
            inputs, truth = experiment["estimator_input"], experiment["truth"]
            problem = build_problem(inputs["observations"], inputs["times_s"])
            ranks[scenario] = jacobian_diagnostics(problem.pack(truth["trajectory"], truth["beacons"]), problem)
        baseline = ranks["informative"]["condition_number"]
        for scenario in ("narrow_coverage", "nearly_collinear"):
            self.assertGreater(ranks[scenario]["condition_number"], 10 * baseline)

    def test_noise_and_per_beacon_uncertainty_remain_in_original_range_units(self):
        experiment = generate_experiment({"noise_std_m": .05, "assumed_std_m": [.03, .05, .1, .2], "seed": 13})
        run = solve_experiment(experiment, {"starts": 2})
        chosen = run["starts"][run["selected_start"]]
        self.assertTrue(chosen["success"])
        self.assertGreater(chosen["diagnostics"]["range_rmse_m"], .001)
        self.assertLess(chosen["diagnostics"]["range_rmse_m"], .1)
        problem = build_problem(experiment["estimator_input"]["observations"], experiment["estimator_input"]["times_s"])
        p, b = np.asarray(chosen["estimate"]["trajectory"]), np.asarray(chosen["estimate"]["beacons"])
        predicted = np.linalg.norm(p[problem.epochs] - b[problem.beacon_ids], axis=1)
        metres = predicted - problem.ranges_m
        np.testing.assert_allclose(chosen["diagnostics"]["residuals_m"], metres, atol=1e-14)
        np.testing.assert_allclose(chosen["diagnostics"]["residuals_normalized"], metres / problem.sigma_m)

    def test_independent_estimator_does_not_use_truth(self):
        experiment = generate_experiment({"samples": 12})
        changed = copy.deepcopy(experiment)
        changed["truth"]["trajectory"][0][0] += 2.
        changed["truth"]["beacons"][3][0] += 1.
        a = solve_experiment(experiment, {"starts": 1})
        b = solve_experiment(changed, {"starts": 1})
        self.assertEqual(a["starts"][0]["initial"], b["starts"][0]["initial"])
        self.assertEqual(a["starts"][0]["estimate"], b["starts"][0]["estimate"])
        self.assertNotEqual(a["starts"][0]["diagnostics"]["evaluation"], b["starts"][0]["diagnostics"]["evaluation"])

    def test_failed_and_not_converged_starts_are_retained(self):
        experiment = generate_experiment({"samples": 8})
        inputs, truth = experiment["estimator_input"], experiment["truth"]
        bad = copy.deepcopy(truth); bad["beacons"][1][0] = -1.
        outcomes = fit_observations(inputs["observations"], inputs["times_s"], starts=2, initial_geometries=[bad, truth], max_nfev=1)
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes[0]["status"], "failed")
        self.assertIn("positive", outcomes[0]["solver"]["message"])
        self.assertEqual(outcomes[0]["initial"], bad)
        limited = solve_experiment(experiment, {"starts": 1, "max_nfev": 1})
        self.assertEqual(limited["status"], "not_converged")
        self.assertIsNotNone(limited["starts"][0]["estimate"])
        self.assertEqual(limited["diagnostics"]["failure_count"], 1)
        json.dumps(limited, allow_nan=False)

    def test_gauge_and_inputs_are_explicitly_enforced(self):
        experiment = generate_experiment({"samples": 8})
        inputs = experiment["estimator_input"]
        with self.assertRaisesRegex(ValueError, "explicit"):
            build_problem(inputs["observations"], inputs["times_s"], mode="known_map")
        with self.assertRaisesRegex(ValueError, "must not"):
            build_problem(inputs["observations"], inputs["times_s"], surveyed_beacons=experiment["truth"]["beacons"])
        changed = copy.deepcopy(inputs["observations"])
        changed[0]["assumed_time_s"] += .1
        with self.assertRaisesRegex(ValueError, "synchronized"):
            build_problem(changed, inputs["times_s"])
        run = solve_experiment(experiment, {"starts": 1})
        b = np.asarray(run["starts"][0]["estimate"]["beacons"])
        np.testing.assert_array_equal(b[0, :2], [0, 0])
        self.assertEqual(b[1, 1], 0)
        self.assertTrue(b[1, 0] > 0 and b[2, 1] > 0 and b[0, 2] > 0)
        np.testing.assert_array_equal(b[:, 2], np.full(4, b[0, 2]))

    def test_alignment_uses_only_rigid_plane_symmetries_and_known_map_stays_fixed(self):
        truth = generate_experiment({"samples": 8})["truth"]
        rotation = np.array([[0., -1.], [1., 0.]])
        estimate = {"trajectory": np.asarray(truth["trajectory"]), "beacons": np.asarray(truth["beacons"])}
        for key in estimate:
            estimate[key][:, :2] = estimate[key][:, :2] @ rotation + [10, -4]
        result = evaluate_geometry(estimate, truth, "joint")
        self.assertLess(result["aligned"]["position_rmse_m"], 1e-12)
        self.assertEqual(result["alignment"]["scale"], 1.)
        self.assertFalse(result["alignment"]["reflection_allowed"])
        for key in estimate:
            estimate[key][:, :2] *= 1.1
        result = evaluate_geometry(estimate, truth, "joint")
        self.assertGreater(result["aligned"]["map_rmse_m"], .1)
        fixed = evaluate_geometry(estimate, truth, "known_map")
        self.assertEqual(fixed["raw"], fixed["aligned"])
        self.assertFalse(fixed["alignment"]["applied"])


if __name__ == "__main__":
    unittest.main()
