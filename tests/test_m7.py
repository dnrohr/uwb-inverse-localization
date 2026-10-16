import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from uwb import m4, m6, m7


class M7Tests(unittest.TestCase):
    def custom(self, survey=None, **changes):
        # Arbitrary noncanonical world coordinates, a synchronous planar path.
        beacons = np.array([[11., -3., 2.], [16., -2., 3.], [14., 4., 2.5], [9., 2., 4.]])
        points = np.array([[12., 0., 0.], [13., .7, 0.], [14., 1., 0.]])
        times = [0., 1., 2.]
        obs = [{"epoch": k, "beacon_id": b, "assumed_time_s": float(k), "range_m": float(np.linalg.norm(p - beacon)), "sigma_m": .05}
               for k, p in enumerate(points) for b, beacon in enumerate(beacons)]
        if survey is None:
            survey = {"frame": "world", "units": "m", "fixed": [
                {"beacon_id": b, "mask": [True] * 3, "mean_m": beacon.tolist()} for b, beacon in enumerate(beacons)], "priors": []}
        opts = {"mode": "joint", "beacon_height_model": "independent", "tag_height_model": "fixed", "starts": 1, "survey": survey, **changes}
        problem = m7.build_problem(obs, times, beacon_count=4, **opts)
        return problem, problem.pack(points, beacons), points, beacons, obs, times, opts

    def source(self, **changes):
        return m6.generate_experiment({"samples": 8, "noise_std_m": .02, "assumed_std_m": .02, **changes})

    def source_options(self, exp, **changes):
        return {"mode": "joint", "beacon_height_model": "independent", "starts": 1,
                "initialization": "truth_near", "initialization_error_m": .01,
                "survey": {"frame": "world", "units": "m", "fixed": [
                    {"beacon_id": b, "mask": [True] * 3, "mean_m": exp["truth"]["beacons"][b]} for b in range(3)], "priors": []}, **changes}

    def test_world_fixed_coordinates_eliminated_without_canonical_gauge(self):
        p, x, points, beacons, *_ = self.custom()
        self.assertEqual(p.parameter_count, 6)
        np.testing.assert_array_equal(p.unpack(x)[1], beacons)
        self.assertEqual(len(p.survey_matrix), 0)
        np.testing.assert_allclose(m7.residuals(x, p), 0., atol=1e-13)
        self.assertTrue(np.all(np.isneginf(p.lower)))

    def test_independent_los_jacobian_and_analytic_covariance(self):
        problem, x, points, beacons, obs, *_ = self.custom()
        expected = np.zeros((len(obs), len(x)))
        for i, row in enumerate(obs):
            delta = points[row["epoch"]] - beacons[row["beacon_id"]]
            expected[i, 2 * row["epoch"]:2 * row["epoch"] + 2] = delta[:2] / np.linalg.norm(delta) / row["sigma_m"]
        np.testing.assert_allclose(m7.jacobian(x, problem), expected, atol=1e-13)
        uncertainty = m7.conditional_uncertainty(x, problem)
        self.assertTrue(uncertainty["available"])
        covariance = np.linalg.inv(expected.T @ expected)
        np.testing.assert_allclose(uncertainty["covariance_m2"], covariance, atol=1e-15)
        np.testing.assert_array_equal(uncertainty["beacon_standard_deviation_m"], np.zeros((4, 3)))
        self.assertEqual(uncertainty["fixed_coordinate_count"], 12)

    def test_selected_coordinates_and_coupled_prior_whitening(self):
        _, _, points, beacons, *_ = self.custom()
        survey = {"frame": "world", "units": "m", "fixed": [
            {"beacon_id": 0, "mask": [True, False, True], "mean_m": beacons[0].tolist()}],
            "priors": [{"beacon_id": 1, "mask": [True, True, False], "mean_m": [15.5, -1.7, 0.],
                        "covariance_m2": [[.09, .03], [.03, .16]]}]}
        problem, x, *_ = self.custom(survey)
        self.assertEqual(problem.parameter_count, 6 + 12 - 2)
        discrepancy = beacons[1, :2] - [15.5, -1.7]
        covariance = np.array([[.09, .03], [.03, .16]])
        independent_cost = .5 * discrepancy @ np.linalg.solve(covariance, discrepancy)
        self.assertAlmostEqual(.5 * np.sum(m7.survey_residuals(x, problem) ** 2), independent_cost, places=12)
        self.assertEqual(len(problem.survey_matrix), 2)
        # A fixed coordinate never becomes an extra prior or range row.
        self.assertEqual(len(m7.residuals(x, problem)), 14)

    def test_derivatives_across_height_models_losses_and_priors(self):
        _, _, _, beacons, *_ = self.custom()
        survey = {"frame": "world", "units": "m", "fixed": [], "priors": [
            {"beacon_id": b, "mask": [True] * 3, "mean_m": beacon.tolist(), "covariance_m2": [[.09, .01, 0.], [.01, .16, 0.], [0., 0., .25]]}
            for b, beacon in enumerate(beacons)]}
        for height in ("fixed", "shared", "soft", "free"):
            for loss in ("gaussian", "huber", "soft_l1", "cauchy"):
                problem, x, *_ = self.custom(survey, tag_height_model=height, prior_sigma_m=.4, loss=loss)
                x = x + np.random.default_rng(23).normal(0., .03, len(x))
                step = 1e-6
                finite = np.column_stack([(m7.residuals(x + step * e, problem) - m7.residuals(x - step * e, problem)) / (2 * step) for e in np.eye(len(x))])
                np.testing.assert_allclose(m7.jacobian(x, problem), finite, atol=1e-7, rtol=2e-7, err_msg=height + "/" + loss)

    def test_remaining_rigid_freedoms_never_get_pseudoinverse_covariance(self):
        _, _, _, beacons, *_ = self.custom()
        partial = {"frame": "world", "units": "m", "fixed": [{"beacon_id": 0, "mask": [True, False, False], "mean_m": beacons[0].tolist()}]}
        problem, x, *_ = self.custom(partial)
        summary = m7.conditional_uncertainty(x, problem)
        self.assertFalse(summary["available"])
        self.assertFalse(summary["information"]["augmented"]["full_column_rank"])
        self.assertIsNone(summary["covariance_m2"])
        self.assertIn("remaining gauge/nullspace", " ".join(summary["unavailable_reasons"]))

    def test_survey_information_can_fill_rank_without_changing_range_information(self):
        _, _, _, beacons, *_ = self.custom()
        priors = {"frame": "world", "units": "m", "fixed": [], "priors": [
            {"beacon_id": b, "mask": [True] * 3, "mean_m": xyz.tolist(), "covariance_m2": (np.eye(3) * .04).tolist()} for b, xyz in enumerate(beacons)]}
        problem, x, *_ = self.custom(priors)
        summary = m7.conditional_uncertainty(x, problem)
        info = summary["information"]
        self.assertFalse(info["original_measurement"]["full_column_rank"])
        self.assertTrue(info["augmented"]["full_column_rank"])
        self.assertTrue(summary["available"])
        self.assertEqual(info["survey"]["row_count"], 12)
        self.assertEqual(info["motion_prior"]["row_count"], 0)

    def test_robust_nonconverged_and_active_bounds_suppress_covariance(self):
        for loss in ("huber", "soft_l1", "cauchy", "hard_rejection"):
            p, x, *_ = self.custom(loss=loss)
            self.assertFalse(m7.conditional_uncertainty(x, p)["available"])
        p, x, *_ = self.custom()
        self.assertFalse(m7.conditional_uncertainty(x, p, converged=False)["available"])
        p.lower[0] = x[0]
        self.assertFalse(m7.conditional_uncertainty(x, p)["available"])

    def test_reject_invalid_units_masks_covariance_duplicates_and_unsupported_models(self):
        p, _, _, _, _, _, options = self.custom()
        for field, value in (("units", "cm"), ("frame", "canonical")):
            bad = copy.deepcopy(options); bad["survey"][field] = value
            with self.assertRaises(ValueError): m7.validate_options(bad)
        for mask in ([1, True, False], [False] * 3, [True]):
            bad = copy.deepcopy(options); bad["survey"]["fixed"][0]["mask"] = mask
            with self.assertRaises(ValueError): m7.validate_options(bad)
        bad = copy.deepcopy(options); bad["survey"]["fixed"].append(copy.deepcopy(bad["survey"]["fixed"][0]))
        with self.assertRaises(ValueError): m7.validate_options(bad)
        for covariance in ([[0.]], [[-.1]], [[.1, .2], [0., .1]]):
            axes = len(covariance)
            bad = copy.deepcopy(options); bad["survey"]["fixed"] = []
            bad["survey"]["priors"] = [{"beacon_id": 0, "mask": [True] * axes + [False] * (3 - axes), "mean_m": [0.] * 3, "covariance_m2": covariance}]
            with self.assertRaises(ValueError): m7.validate_options(bad)
        for changes in ({"beacon_height_model": "shared"}, {"height_parameterization": "q"}, {"initialization": "algebraic"},
                        {"mode": "known_map"}, {"tag_height_model": "shared", "below_beacons": True}):
            with self.assertRaises(ValueError): m7.validate_options({**options, **changes})

    def test_trf_lm_exact_physical_starts_and_failure_retention(self):
        p, x, points, beacons, obs, times, options = self.custom()
        initial = p.geometry(x + .1)
        for solver in ("trf", "lm"):
            start = m7.fit_observations(obs, times, beacon_count=4, initial_geometries=[initial], **{**options, "solver": solver})[0]
            self.assertTrue(start["success"], start["solver"])
            np.testing.assert_allclose(start["estimate"]["knot_trajectory"], points, atol=1e-8)
        broken = copy.deepcopy(initial); broken["beacons"][0][0] += 1.
        start = m7.fit_observations(obs, times, beacon_count=4, initial_geometries=[broken], **options)[0]
        self.assertEqual(start["status"], "failed")
        self.assertIsNone(start["estimate"])
        self.assertIn("violates", start["solver"]["message"])

    def test_truth_and_label_annotations_do_not_enter_fitter(self):
        p, x, _, _, obs, times, options = self.custom()
        dirty = [{**o, "actual_time_s": 1e9, "delivery_time_s": -1e9, "nlos": True, "clean_range_m": -1e99, "truth": [999.] * 3} for o in obs]
        initial = [p.geometry(x + .1)]
        a = m7.fit_observations(obs, times, beacon_count=4, initial_geometries=initial, **options)[0]
        b = m7.fit_observations(dirty, times, beacon_count=4, initial_geometries=initial, **options)[0]
        self.assertEqual(a["estimate"], b["estimate"])
        self.assertEqual(a["solver"]["final_objective"], b["solver"]["final_objective"])

    def test_no_survey_is_exact_m6_delegate(self):
        exp = self.source(); options = {"mode": "joint", "starts": 1}
        initial = m6.make_initial_geometries(exp, options)
        a = m6.solve_experiment(exp, options, initial)
        b = m7.solve_experiment(exp, {**options, "survey": None}, initial)
        self.assertEqual(b["schema_version"], "6.0")
        self.assertEqual(a["options"], b["options"])
        self.assertEqual(a["starts"][0]["estimate"], b["starts"][0]["estimate"])
        self.assertEqual(a["starts"][0]["diagnostics"], b["starts"][0]["diagnostics"])

    def test_strict_offline_roundtrip_and_corruption_rejection(self):
        exp = self.source(); run = m7.solve_experiment(exp, self.source_options(exp))
        self.assertEqual(run["status"], "success")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "run.json"
            with patch.object(m6, "generate_experiment", side_effect=AssertionError("offline")), patch.object(m7, "fit_observations", side_effect=AssertionError("offline")):
                m7.save_run(path, run)
                self.assertEqual(m7.load_run(path), run)
                self.assertGreater(len(m7.table_csv(run).splitlines()), 10)
                self.assertTrue(m7.summarize_uncertainty(run)["available"])
        mutations = [lambda r: r["starts"][0]["solver"].__setitem__("final_objective", 999.),
                     lambda r: r["starts"][0]["diagnostics"]["uncertainty"]["covariance_m2"][0].__setitem__(0, 99.),
                     lambda r: r["starts"][0]["estimate"]["beacons"][0].__setitem__(0, 999.),
                     lambda r: r["diagnostics"]["gauge"].__setitem__("canonical_constraints", True),
                     lambda r: r["starts"][0]["diagnostics"]["evaluation"]["alignment"].__setitem__("applied", True)]
        for mutate in mutations:
            bad = copy.deepcopy(run); mutate(bad)
            with self.assertRaises(ValueError): m7.validate_run(bad)

    def test_world_evaluation_does_not_hide_reflection_or_translation(self):
        _, _, points, beacons, *_ = self.custom()
        truth = {"trajectory": points.tolist(), "beacons": beacons.tolist()}
        reflected = {"trajectory": (-points).tolist(), "beacons": (-beacons).tolist()}
        evaluation = m7.evaluate_geometry(reflected, truth)
        self.assertFalse(evaluation["alignment"]["applied"])
        self.assertEqual(evaluation["raw"], evaluation["aligned"])
        self.assertGreater(evaluation["raw"]["position_rmse_m"], 20.)

    def test_legacy_known_map_summary_and_joint_gauge_guard(self):
        exp = self.source()
        known = m6.solve_experiment(exp, {"mode": "known_map", "starts": 1})
        with patch.object(m6, "solve_experiment", side_effect=AssertionError("offline")), patch.object(m6, "generate_experiment", side_effect=AssertionError("offline")):
            summary = m7.summarize_uncertainty(known)
        self.assertTrue(summary["available"])
        joint = m6.solve_experiment(exp, {"mode": "joint", "starts": 1})
        summary = m7.summarize_uncertainty(joint)
        self.assertFalse(summary["available"])
        self.assertIn("canonical gauge", " ".join(summary["unavailable_reasons"]))

    def test_declared_misspecification_and_nonconvergence_stay_inspectable(self):
        exp = self.source(contamination={"offsets_m": .2})
        run = m7.solve_experiment(exp, self.source_options(exp, max_nfev=1))
        self.assertEqual(run["status"], "not_converged")
        summary = run["starts"][0]["diagnostics"]["uncertainty"]
        self.assertFalse(summary["available"])
        self.assertIn("contamination", " ".join(summary["unavailable_reasons"]))
        m7.validate_run(run)

    def test_empty_lifecycle_records_still_validate_request_and_selection(self):
        exp = self.source()
        envelope = {"schema_version": "7.0", "status": "running", "experiment": exp,
                    "options": m7.validate_options(self.source_options(exp)), "starts": [], "selected_start": None, "diagnostics": {}}
        m7.validate_run(envelope)
        bad = copy.deepcopy(envelope); bad["selected_start"] = 999
        with self.assertRaises(ValueError): m7.validate_run(bad)
        bad = copy.deepcopy(envelope); bad["options"]["survey"]["fixed"][0]["beacon_id"] = 7
        with self.assertRaises(ValueError): m7.validate_run(bad)

    def test_hard_rejection_pilot_mask_is_saved_without_label_selection(self):
        exp = self.source(contamination={"nlos": {"prevalence": .1, "magnitude_m": .7}})
        options = self.source_options(exp, loss="hard_rejection")
        run = m7.solve_experiment(exp, options)
        start = run["starts"][0]
        self.assertIsNotNone(start["estimate"], start["solver"])
        pilot = start["diagnostics"]["rejection_pilot"]
        expected_mask = np.abs(pilot["residuals_normalized"]) <= run["options"]["rejection_threshold_sigma"]
        np.testing.assert_array_equal(pilot["retained_mask"], expected_mask)
        self.assertFalse(start["diagnostics"]["uncertainty"]["available"])
        m7.validate_run(run)

    def test_fixed_tag_below_bounds_and_invalid_survey_height(self):
        _, _, _, beacons, *_ = self.custom()
        survey = {"frame": "world", "units": "m", "fixed": [{"beacon_id": 0, "mask": [True] * 3, "mean_m": beacons[0].tolist()}]}
        problem, x, *_ = self.custom(survey, below_beacons=True)
        for j, label in enumerate(problem.parameter_labels):
            if label["kind"] == "beacon" and label["axis"] == "z": self.assertEqual(problem.lower[j], m4.FLOOR)
        survey["fixed"][0]["mean_m"][2] = -1.
        with self.assertRaises(ValueError): self.custom(survey, below_beacons=True)


if __name__ == "__main__":
    unittest.main()
