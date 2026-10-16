import copy
import json
import unittest
from unittest.mock import patch

import numpy as np

from uwb import m3
from uwb.estimation import solve_experiment as solve_m1
from uwb.experiments import generate_experiment as generate_m1


class M3NumericsTests(unittest.TestCase):
    def test_zero_spacing_reproduces_synchronous_measurements_and_fits(self):
        config = {"samples": 12, "noise_std_m": .02}
        old, new = generate_m1(config), m3.generate_experiment(config)
        np.testing.assert_allclose(new["truth"]["trajectory"], old["truth"]["trajectory"], atol=2e-14)
        np.testing.assert_allclose([o["range_m"] for o in new["estimator_input"]["observations"]],
                                   [o["range_m"] for o in old["estimator_input"]["observations"]], atol=2e-14)
        for mode in ("known_map", "joint"):
            options = {"mode": mode, "starts": 1}
            baseline, aware = solve_m1(old, options), m3.solve_experiment(new, options)
            grouped = m3.solve_experiment(new, {**options, "timing_model": "grouped"})
            for run in (aware, grouped):
                self.assertEqual(run["status"], "success")
                np.testing.assert_allclose(run["starts"][0]["initial"]["trajectory"], baseline["starts"][0]["initial"]["trajectory"], atol=2e-14)
                np.testing.assert_allclose(run["starts"][0]["estimate"]["trajectory"], baseline["starts"][0]["estimate"]["trajectory"], atol=2e-7)
                self.assertAlmostEqual(run["starts"][0]["solver"]["final_objective"], baseline["starts"][0]["solver"]["final_objective"], places=9)

    def test_actual_assumed_and_delivery_clocks_are_separate(self):
        config = {"samples": 8, "acquisition": {"beacon_order": [3, 1, 0, 2], "spacing_s": .1,
                  "jitter_s": .03, "timestamp_offset_s": .2, "timestamp_jitter_s": .04, "delivery_latency_s": 5.}}
        exp = m3.generate_experiment(config)
        observations = exp["estimator_input"]["observations"]
        self.assertEqual([o["beacon_id"] for o in observations[:4]], [3, 1, 0, 2])
        for index, o in enumerate(observations):
            self.assertAlmostEqual(o["delivery_time_s"] - o["actual_time_s"], 5.)
            self.assertLessEqual(abs(o["assumed_time_s"] - o["actual_time_s"] - .2), .04000001)
            position = np.asarray(exp["truth"]["ping_positions"][index])
            beacon = np.asarray(exp["truth"]["beacons"][o["beacon_id"]])
            self.assertAlmostEqual(o["range_m"], np.linalg.norm(position - beacon))
        problem = m3.build_problem(observations, exp["estimator_input"]["times_s"])
        changed = copy.deepcopy(observations)
        for o in changed:
            o["actual_time_s"] += 1000.; o["delivery_time_s"] += 2000.
        other = m3.build_problem(changed, exp["estimator_input"]["times_s"])
        np.testing.assert_array_equal(problem.times_s, other.times_s)
        np.testing.assert_array_equal(problem.weights, other.weights)

    def test_analytic_jacobian_with_prior_and_unequal_knot_intervals(self):
        exp = m3.generate_experiment({"samples": 8, "acquisition": {"spacing_s": .13, "timestamp_offset_s": -.2}})
        for mode in ("known_map", "joint"):
            for timing in ("timestamp_aware", "grouped"):
                p = m3.build_problem(exp["estimator_input"]["observations"], exp["estimator_input"]["times_s"],
                                     mode=mode, timing_model=timing, surveyed_beacons=exp["truth"]["beacons"] if mode == "known_map" else None,
                                     knot_spacing_s=2.3, prior_sigma_m=.7)
                x = p.pack(m3.truth_positions(exp["config"], p.times_s), exp["truth"]["beacons"])
                x += np.random.default_rng(4).normal(0., .1, len(x))
                actual = m3.jacobian(x, p)
                numeric = np.empty_like(actual)
                for column in range(len(x)):
                    step = np.zeros_like(x); step[column] = 1e-5
                    numeric[:, column] = (m3.residuals(x + step, p) - m3.residuals(x - step, p)) / 2e-5
                np.testing.assert_allclose(actual, numeric, rtol=2e-7, atol=2e-7)
                self.assertEqual(len(m3.measurement_residuals(x, p)), len(exp["estimator_input"]["observations"]))

    def test_stationary_spacing_and_delivery_latency_invariance(self):
        config = {"samples": 8, "motion": {"profile": "stationary"}}
        options = {"mode": "known_map", "starts": 1, "knot_spacing_s": 5.}
        original = m3.solve_experiment(m3.generate_experiment(config), options)
        spaced_exp = m3.generate_experiment({**config, "acquisition": {"spacing_s": .2}})
        spaced = m3.solve_experiment(spaced_exp, options)
        for run in (original, spaced):
            self.assertLess(run["starts"][0]["diagnostics"]["evaluation"]["raw"]["position_max_error_m"], 1e-7)
            self.assertEqual(run["diagnostics"]["timing_approximation"]["position_rmse_m"], 0.)
        delayed = m3.generate_experiment({**config, "acquisition": {"spacing_s": .2, "delivery_latency_s": 23.}})
        delayed_run = m3.solve_experiment(delayed, options)
        np.testing.assert_array_equal(spaced["starts"][0]["estimate"]["knot_trajectory"], delayed_run["starts"][0]["estimate"]["knot_trajectory"])
        self.assertEqual(spaced["starts"][0]["solver"]["final_objective"], delayed_run["starts"][0]["solver"]["final_objective"])

    def test_moving_comparison_reports_timing_and_representation_effects(self):
        exp = m3.generate_experiment({"samples": 12, "duration_s": 6., "path": {"type": "line"},
                                     "acquisition": {"spacing_s": .08}})
        options = {"mode": "known_map", "starts": 1, "knot_spacing_s": .6}
        aware = m3.solve_experiment(exp, options)
        grouped = m3.solve_experiment(exp, {**options, "timing_model": "grouped"}, initial_geometries=[aware["starts"][0]["initial"]])
        self.assertGreater(aware["diagnostics"]["timing_approximation"]["position_rmse_m"], .05)
        self.assertLess(aware["starts"][0]["diagnostics"]["range_rmse_m"], grouped["starts"][0]["diagnostics"]["range_rmse_m"])
        self.assertEqual(aware["diagnostics"]["trajectory_model"]["knot_times_s"], grouped["diagnostics"]["trajectory_model"]["knot_times_s"])
        self.assertIn("truth_interpolation_floor", aware["diagnostics"])
        variable = m3.generate_experiment({"motion": {"profile": "variable"}})
        speed = np.asarray(variable["truth"]["motion"]["signed_speed_m_s"])
        self.assertTrue(np.any(speed < 0.)); self.assertTrue(np.any(speed == 0.))
        self.assertTrue(np.any(np.asarray(variable["truth"]["motion"]["acceleration_m_s2"]) != 0.))

    def test_measurement_rank_and_prior_objective_remain_distinct(self):
        exp = m3.generate_experiment({"samples": 8, "acquisition": {"beacon_every_cycles": [1, 4, 4, 4]}})
        run = m3.solve_experiment(exp, {"mode": "known_map", "starts": 1, "prior_sigma_m": .3})
        diag = run["starts"][0]["diagnostics"]
        self.assertLess(diag["jacobian"]["rank"], diag["jacobian"]["parameter_count"])
        self.assertGreater(diag["augmented_jacobian"]["rank"], diag["jacobian"]["rank"])
        self.assertGreater(diag["prior_objective"], 0.)
        self.assertAlmostEqual(diag["prior_objective"] + diag["measurement_objective"], run["starts"][0]["solver"]["final_objective"])
        self.assertEqual(diag["jacobian"]["prior_residual_count"], 0)

    def test_independent_initialization_and_estimation_ignore_truth(self):
        exp = m3.generate_experiment({"samples": 8, "acquisition": {"spacing_s": .05}})
        changed = copy.deepcopy(exp)
        changed["truth"]["trajectory"] = (np.asarray(changed["truth"]["trajectory"]) + [1., 2., 0.]).tolist()
        changed["truth"]["beacons"] = (np.asarray(changed["truth"]["beacons"]) * 1.2).tolist()
        a, b = [m3.solve_experiment(e, {"starts": 1}) for e in (exp, changed)]
        self.assertEqual(a["starts"][0]["initial"], b["starts"][0]["initial"])
        self.assertEqual(a["starts"][0]["estimate"], b["starts"][0]["estimate"])

    def test_missingness_nonconvergence_and_exceptions_are_retained(self):
        empty = m3.generate_experiment({"samples": 8, "acquisition": {"missing_probability": 1.}})
        run = m3.solve_experiment(empty, {"starts": 2})
        self.assertEqual(run["status"], "failed"); self.assertEqual(len(run["starts"]), 2)
        self.assertTrue(all(start["initial"] is not None for start in run["starts"]))
        exp = m3.generate_experiment({"samples": 8})
        nonconverged = m3.solve_experiment(exp, {"starts": 2, "max_nfev": 1})
        self.assertEqual(nonconverged["status"], "not_converged")
        self.assertTrue(all(start["estimate"] is not None for start in nonconverged["starts"]))
        with patch("uwb.m3.least_squares", side_effect=RuntimeError("injected")):
            failed = m3.solve_experiment(exp, {"starts": 2})
        self.assertEqual(failed["diagnostics"]["failure_count"], 2)
        self.assertIn("injected", failed["starts"][1]["solver"]["message"])
        json.dumps(failed, allow_nan=False)

    def test_validation_and_assumed_time_domain_coverage(self):
        exp = m3.generate_experiment({"samples": 8, "acquisition": {"timestamp_offset_s": -2.}})
        p = m3.build_problem(exp["estimator_input"]["observations"], exp["estimator_input"]["times_s"])
        self.assertEqual(p.times_s[0], -2.)
        for bad in ({"motion": {"profile": "unknown"}}, {"acquisition": {"beacon_order": [0, 0, 2, 3]}},
                    {"acquisition": {"cycle_rate_hz": 100.}}, {"motion": {"speed_scale": float("nan")}}):
            with self.assertRaises(ValueError):
                m3.normalize_config(bad)
        with self.assertRaises(ValueError):
            m3.build_problem(exp["estimator_input"]["observations"], exp["estimator_input"]["times_s"], knot_spacing_s=.001)
        failed = {"schema_version": "3.0", "experiment": exp, "options": m3.validate_options(), "starts": [],
                  "diagnostics": {}, "selected_start": None, "status": "failed"}
        m3.validate_run(failed)

    def test_import_validation_rejects_clock_and_run_accounting_corruption(self):
        exp = m3.generate_experiment({"samples": 8})
        run = m3.solve_experiment(exp, {"mode": "known_map", "starts": 1})
        invalid = []
        bad = copy.deepcopy(exp); del bad["truth"]["motion"]["times_s"]; invalid.append(bad)
        bad = copy.deepcopy(exp); bad["truth"]["ping_times_s"][0] += .1; invalid.append(bad)
        bad = copy.deepcopy(exp); bad["estimator_input"]["observations"][0]["delivery_time_s"] = float("nan"); invalid.append(bad)
        bad = copy.deepcopy(exp); bad["config"]["motion"] = None; invalid.append(bad)
        for value in invalid:
            with self.assertRaises(ValueError):
                m3.validate_experiment(value)
        for mutate in (lambda r: r["starts"][0].update(success=False),
                       lambda r: r.update(selected_start=None),
                       lambda r: r["starts"][0].update(status="failed"),
                       lambda r: r["options"].update(starts=2),
                       lambda r: r["starts"][0]["estimate"]["knot_trajectory"][0].__setitem__(2, .1)):
            bad = copy.deepcopy(run); mutate(bad)
            with self.assertRaises(ValueError):
                m3.validate_run(bad)

    def test_compatible_starts_project_knots_without_truth_seeding(self):
        exp = m3.generate_experiment({"samples": 8, "acquisition": {"spacing_s": .1}})
        run = m3.solve_experiment(exp, {"mode": "known_map", "starts": 2})
        options = {**run["options"], "timing_model": "grouped"}
        same = m3.compatible_initial_geometries(run, exp, options)
        for original, projected in zip(run["starts"], same):
            for key in ("trajectory", "beacons", "knot_times_s", "knot_trajectory"):
                self.assertEqual(original["initial"][key], projected[key])
        options["knot_spacing_s"] = 4.
        projected = m3.compatible_initial_geometries(run, exp, options)
        rerun = m3.solve_experiment(exp, options, initial_geometries=projected)
        self.assertEqual(rerun["starts"][0]["initial"], projected[0])
        self.assertLess(len(projected[0]["knot_times_s"]), len(same[0]["knot_times_s"]))


if __name__ == "__main__":
    unittest.main()
