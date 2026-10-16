import copy
import json
import unittest
from unittest.mock import patch

import numpy as np

from uwb import m4, m5, m6


class M6Tests(unittest.TestCase):
    def experiment(self, **changes):
        return m6.generate_experiment({"samples": 12, **changes})

    def test_clean_input_and_gaussian_equivalence_to_m5(self):
        exp = self.experiment(noise_std_m=.02)
        source = exp["contamination_reference"]["source_experiment"]
        self.assertEqual(source["estimator_input"], exp["estimator_input"])
        options = {"starts": 1, "mode": "joint", "height_parameterization": "q"}
        initial = m6.make_initial_geometries(exp, options)
        a = m5.solve_experiment(source, options, initial)["starts"][0]
        b = m6.solve_experiment(exp, options, initial)["starts"][0]
        np.testing.assert_allclose(a["estimate"]["trajectory"], b["estimate"]["trajectory"], atol=1e-10)
        self.assertAlmostEqual(a["solver"]["final_objective"], b["solver"]["final_objective"], places=10)

    def test_scalar_loss_objective_and_derivatives(self):
        values = np.array([-14., -2.3, -.4, -1e-12, 0., .7, 4., 50.])
        scale = 1.8; epsilon = 1e-6
        z = (values / scale) ** 2
        for loss in ("gaussian", "huber", "soft_l1", "cauchy"):
            transformed, derivative = m6.range_transform(values, loss, scale)
            if loss == "gaussian": rho = z
            elif loss == "huber": rho = np.where(z <= 1, z, 2 * np.sqrt(z) - 1)
            elif loss == "soft_l1": rho = 2 * (np.sqrt(1 + z) - 1)
            else: rho = np.log1p(z)
            np.testing.assert_allclose(transformed ** 2, scale ** 2 * rho, atol=1e-12)
            finite = (m6.range_transform(values + epsilon, loss, scale)[0] - m6.range_transform(values - epsilon, loss, scale)[0]) / (2 * epsilon)
            np.testing.assert_allclose(derivative, finite, atol=1e-8)
            weight, _ = m6.loss_statistics(values, loss, scale)
            np.testing.assert_allclose(transformed * derivative, values * weight, atol=1e-12)

    def test_robust_jacobian_and_priors_stay_quadratic(self):
        exp = self.experiment(contamination={"offsets_m": .2})
        opts = {"starts": 1, "mode": "known_map", "tag_height_model": "soft", "prior_sigma_m": .4}
        initial = m6.make_initial_geometries(exp, opts)[0]
        for loss in ("huber", "soft_l1", "cauchy"):
            problem = m6._problem(exp, m6.validate_options({**opts, "loss": loss}))
            x = problem.pack(initial["knot_trajectory"], initial["beacons"])
            step = 1e-6
            finite = np.column_stack([(m6.residuals(x + step * e, problem) - m6.residuals(x - step * e, problem)) / (2 * step) for e in np.eye(len(x))])
            np.testing.assert_allclose(m6.jacobian(x, problem), finite, atol=2e-7, rtol=2e-7)
            count = len(problem.ranges_m)
            np.testing.assert_array_equal(m6.residuals(x, problem)[count:], m5.residuals(x, problem)[count:])
            np.testing.assert_array_equal(m6.jacobian(x, problem)[count:], m5.jacobian(x, problem)[count:])

    def test_independent_noise_sources_deterministic_and_additive(self):
        contamination = {"seed": 9, "nlos": {"prevalence": .13, "magnitude_m": 1.2, "burst_duration_cycles": 3, "affected_beacons": [1]},
                         "offsets_m": [0., .1, -.1, .2], "correlated_noise_std_m": .03, "correlation": .75,
                         "quantization_m": .02, "dropout_probability": .25}
        exp = self.experiment(noise_std_m=.01, contamination=contamination)
        again = self.experiment(noise_std_m=.01, contamination=contamination)
        self.assertEqual(exp["contamination_reference"], again["contamination_reference"])
        records = exp["contamination_reference"]["records"]
        self.assertTrue(any(r["dropped"] for r in records))
        self.assertTrue(any(r["nlos"] for r in records))
        for record in records:
            self.assertAlmostEqual(record["range_m"], sum(record[k] for k in ("clean_range_m", "white_noise_m", "offset_m", "correlated_noise_m", "nlos_bias_m", "quantization_error_m")), places=12)
            if record["beacon_id"] != 1: self.assertFalse(record["nlos"])
            self.assertEqual(record["dropped"], record["retained_index"] is None)
        without_nlos = self.experiment(noise_std_m=.01, contamination={**contamination, "nlos": {"prevalence": 0.}})
        for a, b in zip(records, without_nlos["contamination_reference"]["records"]):
            self.assertEqual(a["dropped"], b["dropped"])
            self.assertEqual(a["correlated_noise_m"], b["correlated_noise_m"])

    def test_isolated_and_burst_definitions_and_timing_preserved(self):
        opts = {"seed": 4, "nlos": {"prevalence": .2, "affected_beacons": [0]}}
        one = self.experiment(contamination=opts)
        three = self.experiment(contamination={**opts, "nlos": {**opts["nlos"], "burst_duration_cycles": 3}})
        isolated = one["contamination_reference"]["records"]
        bursts = three["contamination_reference"]["records"]
        for i, record in enumerate(isolated):
            if record["nlos"]:
                for next_epoch in range(record["epoch"], min(record["epoch"] + 3, 12)):
                    self.assertTrue(next(r for r in bursts if r["epoch"] == next_epoch and r["beacon_id"] == 0)["nlos"])
        for a, b in zip(one["estimator_input"]["observations"], three["estimator_input"]["observations"]):
            for key in ("actual_time_s", "assumed_time_s", "delivery_time_s"):
                self.assertEqual(a[key], b[key])

    def test_fitter_does_not_read_truth_labels_or_actual_delivery_times(self):
        exp = self.experiment(contamination={"nlos": {"prevalence": .1}})
        options = {"starts": 1, "loss": "cauchy"}
        observations = exp["estimator_input"]["observations"]
        kwargs = {"beacon_count": 4, "display_times_s": exp["truth"]["times_s"], **options}
        first = m6.fit_observations(observations, exp["estimator_input"]["times_s"], **kwargs)[0]
        poisoned = copy.deepcopy(observations)
        for row in poisoned:
            row.update(actual_time_s="unused", delivery_time_s={"unread": True}, nlos=object(), clean_range_m=object())
        second = m6.fit_observations(poisoned, exp["estimator_input"]["times_s"], **kwargs)[0]
        self.assertEqual(first["estimate"], second["estimate"])
        self.assertEqual(first["diagnostics"], second["diagnostics"])

    def test_solvers_and_coordinates_have_identical_objective_from_paired_starts(self):
        exp = self.experiment(noise_std_m=.01)
        initial = m6.make_initial_geometries(exp, {"starts": 1})
        objectives = []
        for solver, coordinate in (("trf", "h"), ("lm", "h"), ("trf", "q"), ("lm", "q")):
            run = m6.solve_experiment(exp, {"starts": 1, "solver": solver, "height_parameterization": coordinate, "loss": "soft_l1"}, initial)
            start = run["starts"][0]
            self.assertIsNotNone(start["estimate"], start["solver"]["message"])
            objectives.append(start["solver"]["initial_objective"])
            self.assertEqual(start["solver"]["loss"], "soft_l1")
        np.testing.assert_allclose(objectives, objectives[0], atol=1e-10)

    def test_frozen_rejection_residuals_information_and_metrics(self):
        exp = self.experiment(contamination={"nlos": {"prevalence": .12, "magnitude_m": 1.}})
        run = m6.solve_experiment(exp, {"starts": 1, "loss": "hard_rejection"})
        start = run["starts"][0]; diag = start["diagnostics"]
        self.assertIsNotNone(start["estimate"], start["solver"]["message"])
        pilot = diag["rejection_pilot"]
        mask = np.abs(pilot["residuals_normalized"]) <= 3.
        self.assertGreater(np.sum(~mask), 0)
        self.assertEqual([row["weight"] for row in diag["observation_decisions"]], mask.astype(float).tolist())
        self.assertEqual(len(diag["residuals_m"]), len(exp["estimator_input"]["observations"]))
        problem = m6._problem(exp, run["options"]); x = np.array(start["solver"]["final_parameters"])
        original = m4.measurement_jacobian(problem.physical_parameters(x), problem.physical)
        scale = diag["information"]["original_measurement"]["parameter_scale_m"]
        np.testing.assert_allclose(diag["information"]["retained_measurement"]["singular_values"], np.linalg.svd(original * mask[:, None] * scale, compute_uv=False), atol=1e-10)
        metric = diag["rejection_evaluation"]
        self.assertEqual(sum(metric[k] for k in ("true_positive", "false_positive", "false_negative", "true_negative")), len(mask))
        self.assertLessEqual(diag["information"]["retained_measurement"]["rank"], int(np.sum(mask)))

    def test_undefined_metrics_and_missing_selection(self):
        exp = self.experiment(contamination={"dropout_probability": .2})
        run = m6.solve_experiment(exp, {"starts": 1})
        metric = run["starts"][0]["diagnostics"]["rejection_evaluation"]
        self.assertIsNone(metric["precision"]); self.assertIsNone(metric["recall"])
        self.assertEqual(metric["false_positive_rate"], 0.)
        self.assertEqual(metric["dropped_count_excluded"], sum(r["dropped"] for r in exp["contamination_reference"]["records"]))

    def test_complete_dropout_and_lm_rejection_failure_keep_attempts(self):
        exp = self.experiment(contamination={"dropout_probability": 1.})
        run = m6.solve_experiment(exp, {"starts": 2})
        self.assertEqual(run["status"], "failed"); self.assertEqual(len(run["starts"]), 2)
        for start in run["starts"]:
            self.assertIsNone(start["estimate"])
            self.assertIn("No retained observations", start["solver"]["message"])
        exp = self.experiment(contamination={"nlos": {"prevalence": .1}})
        failed = m6.solve_experiment(exp, {"starts": 2, "solver": "lm", "loss": "hard_rejection", "rejection_threshold_sigma": 1e-6})
        self.assertEqual(failed["status"], "failed")
        for start in failed["starts"]:
            self.assertIn("rejection_pilot", start["diagnostics"])

    def test_nonconvergence_and_invalid_initializer_retained(self):
        run = m6.solve_experiment(self.experiment(), {"starts": 2, "max_nfev": 1})
        self.assertEqual(run["status"], "not_converged")
        self.assertTrue(all(s["estimate"] is not None and not s["success"] for s in run["starts"]))
        run = m6.solve_experiment(self.experiment(scenario="straight_line"), {"starts": 2, "initialization": "algebraic"})
        self.assertEqual(run["status"], "failed")
        self.assertTrue(all(s["diagnostics"]["algebraic_initializer"]["status"] != "success" for s in run["starts"]))

    def test_offline_roundtrip_and_tamper_detection(self):
        run = m6.solve_experiment(self.experiment(contamination={"nlos": {"prevalence": .1}}), {"starts": 1, "loss": "huber"})
        with patch.object(m6, "solve_experiment", side_effect=AssertionError("no solve")), patch.object(m6, "generate_experiment", side_effect=AssertionError("no generation")):
            m6.validate_run(json.loads(json.dumps(run, allow_nan=False)))
        for field in ("labels", "residual", "weight", "precision", "information", "objective", "geometry"):
            bad = copy.deepcopy(run); start = bad["starts"][0]
            if field == "labels": bad["experiment"]["contamination_reference"]["records"][0]["nlos"] ^= True
            elif field == "residual": start["diagnostics"]["residuals_m"][0] += .1
            elif field == "weight": start["diagnostics"]["observation_decisions"][0]["weight"] = .01
            elif field == "precision": start["diagnostics"]["rejection_evaluation"]["true_positive"] += 1
            elif field == "information": start["diagnostics"]["information"]["retained_measurement"]["rank"] += 1
            elif field == "objective": start["solver"]["final_objective"] += 1.
            else: start["solver"]["final_parameters"][0] += .1
            with self.assertRaises(ValueError, msg=field): m6.validate_run(bad)

    def test_config_option_support_and_pairing(self):
        for bad in ({"loss": "oracle"}, {"loss_scale_sigma": 0.}, {"weight_decision_threshold": 1.1}, {"loss": "huber", "height_parameterization": "q", "tag_height_model": "free"}):
            with self.assertRaises(ValueError): m6.validate_options(bad)
        for bad in ({"correlation": 1.}, {"nlos": {"affected_beacons": [4]}}, {"nlos": {"burst_duration_cycles": 1.2}}, {"seed": True}, {"offsets_m": [1, 2]}):
            with self.assertRaises(ValueError): self.experiment(contamination=bad)
        exp = self.experiment(); run = m6.solve_experiment(exp, {"starts": 1})
        paired = m6.compatible_initial_geometries(run, exp, {**run["options"], "loss": "cauchy", "height_parameterization": "q"})
        np.testing.assert_allclose(paired[0]["trajectory"], run["starts"][0]["initial"]["trajectory"], atol=1e-10)

    def test_pending_and_infrastructure_failed_envelopes_remain_readable(self):
        exp = self.experiment(); options = m6.validate_options({"starts": 2})
        pending = {"schema_version": "6.0", "experiment": exp, "options": options,
                   "status": "running", "starts": [], "diagnostics": {}}
        m6.validate_run(json.loads(json.dumps(pending)))
        failed = {**pending, "status": "failed", "selected_start": None, "error": "RuntimeError: wrapper unavailable"}
        m6.validate_run(failed)
        failed = copy.deepcopy(failed)
        failed["starts"] = [{"index": i, "status": "failed", "success": False, "initial": None, "estimate": None,
                             "solver": {"message": failed["error"]}, "diagnostics": {}} for i in range(2)]
        m6.validate_run(failed)
        bad = copy.deepcopy(failed); bad["starts"][0]["solver"] = {}
        with self.assertRaises(ValueError): m6.validate_run(bad)
        bad = copy.deepcopy(failed); bad["options"]["loss"] = "oracle"
        with self.assertRaises(ValueError): m6.validate_run(bad)
        bad = copy.deepcopy(failed); bad["starts"].pop()
        with self.assertRaises(ValueError): m6.validate_run(bad)

    def test_error_message_does_not_bypass_finite_outcome_validation(self):
        run = m6.solve_experiment(self.experiment(), {"starts": 1})
        run.update(error="OSError: terminal write unavailable", infrastructure_status="failed")
        m6.validate_run(run)
        bad = copy.deepcopy(run); bad["diagnostics"].pop("robust_estimation")
        with self.assertRaises(ValueError): m6.validate_run(bad)
        bad = copy.deepcopy(run); bad["starts"][0]["solver"]["final_objective"] += 1.
        with self.assertRaises(ValueError): m6.validate_run(bad)


if __name__ == "__main__":
    unittest.main()
