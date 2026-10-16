import copy
import json
import unittest
from unittest.mock import patch

import numpy as np

from uwb import m4


class M4NumericalTests(unittest.TestCase):
    def test_dynamic_count_clocks_noise_and_ranges(self):
        for count in range(3, 9):
            exp = m4.generate_experiment({"samples": 8, "beacon_layout": {"count": count, "geometry": "diverse"},
                 "truth_height": {"type": "spatial"}, "acquisition": {"beacon_order": list(reversed(range(count))), "spacing_s": .04, "timestamp_offset_s": .2, "delivery_latency_s": 3.}})
            obs = exp["estimator_input"]["observations"]
            self.assertEqual(len(obs), 8 * count)
            self.assertEqual([o["beacon_id"] for o in obs[:count]], list(reversed(range(count))))
            for o, p in zip(obs, exp["truth"]["ping_positions"]):
                self.assertAlmostEqual(o["range_m"], np.linalg.norm(np.asarray(p) - exp["truth"]["beacons"][o["beacon_id"]]))
                self.assertAlmostEqual(o["assumed_time_s"] - o["actual_time_s"], .2)
                self.assertAlmostEqual(o["delivery_time_s"] - o["actual_time_s"], 3.)
            self.assertEqual(len(exp["config"]["noise_std_m"]), count)

    def test_analytic_jacobians_for_every_supported_model(self):
        exp = m4.generate_experiment({"samples": 8, "beacon_layout": {"count": 5, "geometry": "diverse"}, "truth_height": {"type": "spatial"}, "acquisition": {"spacing_s": .07}})
        for mode in ("known_map", "joint"):
            for tag in ("fixed", "shared", "soft", "free"):
                for beacon in ("shared", "independent"):
                    with self.subTest(mode=mode, tag=tag, beacon=beacon):
                        opts = m4.validate_options({"mode": mode, "tag_height_model": tag, "beacon_height_model": beacon, "prior_sigma_m": .8, "height_prior_sigma_m": .3, "knot_spacing_s": 3.1})
                        p = m4._problem(exp, opts)
                        initial = m4._initial(p, np.random.default_rng(4), 0)
                        x = p.pack(initial["knot_trajectory"], initial["beacons"])
                        x += np.random.default_rng(8).normal(0., .03, len(x))
                        analytic = m4.jacobian(x, p); numeric = np.empty_like(analytic)
                        for i in range(len(x)):
                            step = np.zeros_like(x); step[i] = 1e-5
                            numeric[:, i] = (m4.residuals(x + step, p) - m4.residuals(x - step, p)) / 2e-5
                        np.testing.assert_allclose(analytic, numeric, rtol=3e-7, atol=3e-7)

    def test_coplanar_known_map_retains_reflection_and_below_selects_branch(self):
        exp = m4.generate_experiment({"samples": 8, "truth_height": {"type": "excursion", "amplitude_m": .4}})
        run = m4.solve_experiment(exp, {"mode": "known_map", "tag_height_model": "free", "starts": 2})
        below = m4.solve_experiment(exp, {"mode": "known_map", "tag_height_model": "free", "below_beacons": True, "starts": 2})
        for s in run["starts"]:
            self.assertLess(s["diagnostics"]["max_abs_residual_m"], 1e-7)
        self.assertLess(run["starts"][0]["diagnostics"]["evaluation"]["raw"]["position_max_error_m"], 1e-6)
        self.assertGreater(run["starts"][1]["diagnostics"]["evaluation"]["raw"]["position_rmse_m"], 5.)
        self.assertGreater(run["diagnostics"]["distinct_low_residual_solution_count"], 1)
        for s in below["starts"]:
            self.assertLess(s["diagnostics"]["evaluation"]["raw"]["position_max_error_m"], 1e-6)
            truth_departure = s["diagnostics"]["height"]["truth_planarity"]["rms_m"]
            self.assertGreater(truth_departure, .01)
            self.assertAlmostEqual(s["diagnostics"]["height"]["fit_planarity"]["rms_m"], truth_departure, places=7)
            self.assertFalse(below["diagnostics"]["constraints"]["height_prior_enabled"])

    def test_known_height_model_mismatch_and_separate_prior_information(self):
        exp = m4.generate_experiment({"samples": 8, "beacon_layout": {"count": 5, "geometry": "diverse"}, "truth_height": {"type": "excursion", "amplitude_m": .4}})
        free = m4.solve_experiment(exp, {"mode": "known_map", "tag_height_model": "free", "starts": 1})
        fixed = m4.solve_experiment(exp, {"mode": "known_map", "tag_height_model": "fixed", "starts": 1})
        soft = m4.solve_experiment(exp, {"mode": "known_map", "tag_height_model": "soft", "height_prior_sigma_m": .1, "prior_sigma_m": .5, "starts": 1})
        self.assertLess(free["starts"][0]["diagnostics"]["range_rmse_m"], 1e-7)
        self.assertGreater(fixed["starts"][0]["diagnostics"]["range_rmse_m"], .01)
        d = soft["starts"][0]["diagnostics"]
        self.assertGreater(d["height_prior_objective"], 0.)
        self.assertGreater(d["motion_prior_objective"], 0.)
        self.assertAlmostEqual(d["measurement_objective"] + d["prior_objective"], soft["starts"][0]["solver"]["final_objective"])
        self.assertEqual(d["jacobian"]["prior_residual_count"], 0)
        self.assertGreater(d["augmented_jacobian"]["prior_residual_count"], 0)

    def test_tilted_plane_is_distinct_from_warped_truth(self):
        tilted = m4.generate_experiment({"samples": 16, "truth_height": {"type": "tilted", "tilt_deg": 15.}})
        warped = m4.generate_experiment({"samples": 16, "truth_height": {"type": "spatial", "amplitude_m": .5}})
        plane = m4.plane_diagnostics(tilted["truth"]["trajectory"])
        warp = m4.plane_diagnostics(warped["truth"]["trajectory"])
        self.assertLess(plane["rms_m"], 1e-12)
        self.assertGreater(np.ptp(np.asarray(tilted["truth"]["trajectory"])[:, 2]), 1.)
        self.assertGreater(warp["rms_m"], .1)
        self.assertEqual(np.asarray(plane["plane_corners"]).shape, (4, 3))

    def test_joint_gauges_and_full_rank_independent_spatial_geometry(self):
        exp = m4.generate_experiment({"samples": 12, "beacon_layout": {"count": 6, "geometry": "diverse"}, "truth_height": {"type": "spatial"}})
        run = m4.solve_experiment(exp, {"tag_height_model": "free", "beacon_height_model": "independent", "initialization": "independent", "starts": 1})
        rank = run["diagnostics"]["truth_jacobian"]
        self.assertTrue(rank["full_column_rank"])
        d = run["starts"][0]["diagnostics"]
        self.assertLess(d["evaluation"]["raw"]["position_max_error_m"], 1e-5)
        self.assertLess(d["evaluation"]["aligned"]["position_max_error_m"], 1e-5)
        rotation = np.asarray(d["evaluation"]["alignment"]["rotation_xyz"])
        self.assertAlmostEqual(np.linalg.det(rotation), 1.)
        self.assertEqual(d["evaluation"]["alignment"]["scale"], 1.)
        beacons = np.asarray(run["starts"][0]["estimate"]["beacons"])
        np.testing.assert_allclose(beacons[0], 0., atol=1e-12)
        self.assertEqual(beacons[1, 1], 0.); self.assertEqual(beacons[1, 2], 0.); self.assertEqual(beacons[2, 2], 0.)
        self.assertGreater(beacons[1, 0], 0.); self.assertGreater(beacons[2, 1], 0.)

    def test_joint_shared_plane_free_tags_discloses_measurement_rank_loss(self):
        exp = m4.generate_experiment({"samples": 8, "truth_height": {"type": "spatial"}})
        run = m4.solve_experiment(exp, {"tag_height_model": "free", "beacon_height_model": "shared", "starts": 1})
        self.assertFalse(run["diagnostics"]["truth_jacobian"]["full_column_rank"])
        self.assertTrue(run["diagnostics"]["warnings"])
        soft = m4.solve_experiment(exp, {"tag_height_model": "soft", "fixed_tag_z_m": -3., "starts": 1})
        self.assertIn("not surveyed world z", soft["diagnostics"]["constraints"]["height_prior_plane"])

    def test_known_shared_height_is_estimated_joint_shared_height_is_gauge(self):
        exp = m4.generate_experiment({"samples": 8, "truth_height": {"offset_m": .7}})
        known = m4.solve_experiment(exp, {"mode": "known_map", "tag_height_model": "shared", "starts": 1})
        np.testing.assert_allclose(np.asarray(known["starts"][0]["estimate"]["trajectory"])[:, 2], .7, atol=1e-6)
        joint = m4.solve_experiment(exp, {"tag_height_model": "shared", "starts": 1})
        np.testing.assert_array_equal(np.asarray(joint["starts"][0]["estimate"]["trajectory"])[:, 2], 0.)
        self.assertIn("not recovered", joint["diagnostics"]["gauge"]["tag_shared_absolute_height"])
        self.assertLess(joint["starts"][0]["diagnostics"]["evaluation"]["aligned"]["position_max_error_m"], 1e-5)

    def test_truth_free_inputs_starts_and_delivery_invariance(self):
        exp = m4.generate_experiment({"samples": 8, "beacon_layout": {"count": 5, "geometry": "diverse"}, "truth_height": {"type": "spatial"}})
        changed = copy.deepcopy(exp)
        changed["truth"]["trajectory"] = (np.asarray(changed["truth"]["trajectory"]) + [1., 2., 3.]).tolist()
        changed["truth"]["beacons"] = (np.asarray(changed["truth"]["beacons"]) * 1.2).tolist()
        opts = {"tag_height_model": "free", "beacon_height_model": "independent", "starts": 1}
        first, second = [m4.solve_experiment(e, opts) for e in (exp, changed)]
        self.assertEqual(first["starts"][0]["initial"], second["starts"][0]["initial"])
        self.assertEqual(first["starts"][0]["estimate"], second["starts"][0]["estimate"])
        observations = copy.deepcopy(exp["estimator_input"]["observations"])
        for o in observations: o["actual_time_s"] += 1000.; o["delivery_time_s"] += 2000.
        plain = m4.fit_observations(observations, exp["estimator_input"]["times_s"], beacon_count=5, display_times_s=exp["truth"]["times_s"], **opts)
        self.assertEqual(first["starts"][0]["estimate"], plain[0]["estimate"])

    def test_all_missing_nonconvergence_invalid_initial_and_exceptions_retained(self):
        empty = m4.generate_experiment({"samples": 8, "beacon_layout": {"count": 3}, "acquisition": {"missing_probability": 1.}})
        failed = m4.solve_experiment(empty, {"mode": "known_map", "tag_height_model": "soft", "starts": 2})
        self.assertEqual(failed["status"], "failed"); self.assertEqual(len(failed["starts"]), 2)
        exp = m4.generate_experiment({"samples": 8})
        nonconverged = m4.solve_experiment(exp, {"starts": 2, "max_nfev": 1})
        self.assertTrue(all(s["status"] == "not_converged" and s["estimate"] for s in nonconverged["starts"]))
        initial = copy.deepcopy(nonconverged["starts"][0]["initial"]); initial["knot_trajectory"] = [[0., 0., 0.]]
        invalid = m4.solve_experiment(exp, {"starts": 1}, [initial])
        self.assertEqual(invalid["status"], "failed"); self.assertEqual(invalid["starts"][0]["initial"], initial)
        with patch("uwb.m4.least_squares", side_effect=RuntimeError("retained failure")):
            injected = m4.solve_experiment(exp, {"starts": 2})
        self.assertEqual(injected["diagnostics"]["failure_count"], 2)
        json.dumps(injected, allow_nan=False)

    def test_offline_compatible_starts_and_unsupported_bounds(self):
        exp = m4.generate_experiment({"samples": 8})
        source = m4.solve_experiment(exp, {"mode": "known_map", "tag_height_model": "fixed", "starts": 1})
        with patch("uwb.m4.solve_experiment", side_effect=AssertionError("offline")), patch("uwb.m4.generate_experiment", side_effect=AssertionError("offline")):
            for tag in ("shared", "soft", "free"):
                initial = m4.compatible_initial_geometries(source, exp, {**source["options"], "tag_height_model": tag})
                self.assertEqual(len(initial), 1)
                self.assertEqual(initial[0]["beacons"], source["starts"][0]["initial"]["beacons"])
        with self.assertRaisesRegex(ValueError, "coupled"):
            m4.validate_options({"tag_height_model": "free", "beacon_height_model": "independent", "below_beacons": True})
        collinear = m4.generate_experiment({"samples": 8, "beacon_layout": {"count": 4, "geometry": "collinear"}})
        run = m4.solve_experiment(collinear, {"tag_height_model": "free", "starts": 1, "max_nfev": 20})
        self.assertIn("noncollinear", run["diagnostics"]["evaluation_error"])
        self.assertEqual(len(run["starts"]), 1)

    def test_degenerate_evaluation_metadata_does_not_change_independent_fit(self):
        exp = m4.generate_experiment({"samples": 8, "beacon_layout": {"count": 5, "geometry": "diverse"}, "truth_height": {"type": "spatial"}})
        changed = copy.deepcopy(exp)
        changed["truth"]["beacons"][:3] = [[0., 0., 0.], [1., 0., 0.], [2., 0., 0.]]
        opts = {"tag_height_model": "free", "beacon_height_model": "independent", "starts": 1}
        a, b = [m4.solve_experiment(e, opts) for e in (exp, changed)]
        self.assertEqual(a["starts"][0]["initial"], b["starts"][0]["initial"])
        self.assertEqual(a["starts"][0]["estimate"], b["starts"][0]["estimate"])
        self.assertIsNone(b["diagnostics"]["truth_jacobian"])
        self.assertFalse(b["diagnostics"]["truth_interpolation_floor"]["available"])

    def test_height_model_projection_is_separate_from_time_interpolation(self):
        exp = m4.generate_experiment({"samples": 8, "truth_height": {"type": "spatial"}, "beacon_layout": {"count": 5, "geometry": "diverse"}})
        run = m4.solve_experiment(exp, {"mode": "known_map", "tag_height_model": "fixed", "starts": 1})
        self.assertGreater(run["diagnostics"]["truth_model_projection"]["knot_position_rmse_m"], .1)
        self.assertLess(run["diagnostics"]["truth_interpolation_only"]["display"]["position_rmse_m"], 1e-12)

    def test_joint_spatial_reflection_is_retained_and_proper_alignment_cannot_hide_it(self):
        exp = m4.generate_experiment({"samples": 8, "beacon_layout": {"count": 6, "geometry": "diverse"}, "truth_height": {"type": "spatial"}})
        opts = {"tag_height_model": "free", "beacon_height_model": "independent", "starts": 1}
        run = m4.solve_experiment(exp, opts)
        reflected = copy.deepcopy(run["starts"][0]["estimate"])
        for field in ("trajectory", "knot_trajectory", "ping_trajectory", "assumed_ping_trajectory", "beacons"):
            values = np.asarray(reflected[field]); values[:, 2] *= -1.; reflected[field] = values.tolist()
        mirror = m4.solve_experiment(exp, opts, [reflected])
        d = mirror["starts"][0]["diagnostics"]
        self.assertLess(d["max_abs_residual_m"], 1e-7)
        self.assertGreater(d["evaluation"]["raw"]["position_rmse_m"], 1.)
        self.assertGreater(d["evaluation"]["aligned"]["map_rmse_m"], .05)
        self.assertAlmostEqual(np.linalg.det(d["evaluation"]["alignment"]["rotation_xyz"]), 1.)

    def test_import_validation_enforces_models_grid_and_saved_interpolation(self):
        exp = m4.generate_experiment({"samples": 8})
        run = m4.solve_experiment(exp, {"mode": "known_map", "starts": 1})
        for modify in (lambda r: r["starts"][0]["estimate"]["trajectory"][0].__setitem__(0, 123.),
                       lambda r: r["starts"][0]["estimate"]["knot_trajectory"][0].__setitem__(2, .1),
                       lambda r: r["starts"][0]["estimate"]["knot_times_s"].__setitem__(0, -.1),
                       lambda r: r.update(status="failed", selected_start=None)):
            invalid = copy.deepcopy(run); modify(invalid)
            with self.assertRaises(ValueError): m4.validate_run(invalid)
        bad = copy.deepcopy(exp); del bad["truth"]["motion"]["times_s"]
        with self.assertRaises(ValueError): m4.validate_experiment(bad)


if __name__ == "__main__": unittest.main()
