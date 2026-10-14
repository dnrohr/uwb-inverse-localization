"""Independent structural checks beyond a solver's termination status."""
import unittest

import numpy as np

from uwb.estimation import build_problem, evaluate_geometry, jacobian, jacobian_diagnostics, residuals
from uwb.experiments import generate_experiment


class MathematicalReviewTests(unittest.TestCase):
    def test_heterogeneous_weights_and_shuffled_rows_match_finite_differences(self):
        experiment = generate_experiment({"samples": 8, "assumed_std_m": [0.03, 0.11, 0.2, 0.07]})
        observations = list(reversed(experiment["estimator_input"]["observations"]))
        for mode in ("joint", "known_map"):
            problem = build_problem(observations, experiment["truth"]["times_s"], mode=mode,
                                    surveyed_beacons=experiment["truth"]["beacons"] if mode == "known_map" else None)
            parameters = problem.pack(experiment["truth"]["trajectory"], experiment["truth"]["beacons"])
            parameters[:16] += np.linspace(-0.12, 0.08, 16)
            step = 1e-5
            columns = []
            for column in range(len(parameters)):
                delta = np.zeros_like(parameters)
                delta[column] = step
                columns.append((residuals(parameters + delta, problem) - residuals(parameters - delta, problem)) / (2 * step))
            np.testing.assert_allclose(jacobian(parameters, problem), np.column_stack(columns), rtol=2e-8, atol=2e-8)

    def test_straight_line_has_continuum_inside_positive_gauge(self):
        experiment = generate_experiment({"scenario": "straight_line", "samples": 8})
        problem = build_problem(experiment["estimator_input"]["observations"], experiment["truth"]["times_s"])
        trajectory = np.asarray(experiment["truth"]["trajectory"])
        beacons = np.asarray(experiment["truth"]["beacons"])
        original = problem.pack(trajectory, beacons)
        # Increase h^2 by q while redistributing perpendicular offsets. Translate
        # the resulting geometry horizontally to retain b0.y=b1.y=0.
        k, q = trajectory[0, 1], 1.0
        changed_trajectory, changed_beacons = trajectory.copy(), beacons.copy()
        changed_trajectory[:, 1] = np.sqrt(k * k - q)
        offsets = beacons[:, 1] - k
        changed_beacons[:, 1] = np.sqrt(k * k - q) + np.sign(offsets) * np.sqrt(offsets * offsets - q)
        changed_beacons[:, 2] = np.sqrt(beacons[:, 2] ** 2 + q)
        changed = problem.pack(changed_trajectory, changed_beacons)
        np.testing.assert_allclose(residuals(changed, problem), residuals(original, problem), atol=8e-14)
        self.assertGreater(np.max(np.abs(changed - original)), 0.1)
        self.assertEqual(jacobian_diagnostics(original, problem)["rank"], problem.parameter_count - 1)
        self.assertGreater(evaluate_geometry({"trajectory": changed_trajectory.tolist(), "beacons": changed_beacons.tolist()},
                                            experiment["truth"], "joint")["aligned"]["map_rmse_m"], 0.1)

    def test_proper_planar_alignment_preserves_ranges_and_recovers_rigid_frame(self):
        truth = generate_experiment({"samples": 8})["truth"]
        rotation = np.array([[np.cos(0.7), -np.sin(0.7)], [np.sin(0.7), np.cos(0.7)]])
        trajectory, beacons = np.array(truth["trajectory"]), np.array(truth["beacons"])
        for points in (trajectory, beacons):
            points[:, :2] = points[:, :2] @ rotation + [3.2, -1.4]
        estimate = {"trajectory": trajectory.tolist(), "beacons": beacons.tolist()}
        result = evaluate_geometry(estimate, truth, "joint")
        aligned = result["aligned_geometry"]
        before = np.linalg.norm(trajectory[:, None] - beacons[None], axis=2)
        after = np.linalg.norm(np.array(aligned["trajectory"])[:, None] - np.array(aligned["beacons"])[None], axis=2)
        np.testing.assert_allclose(before, after, atol=5e-15)
        self.assertLess(result["aligned"]["position_max_error_m"], 1e-13)
        self.assertAlmostEqual(np.linalg.det(result["alignment"]["rotation_xy"]), 1.0)
        self.assertGreater(result["raw"]["position_rmse_m"], 1.0)

    def test_alignment_does_not_hide_scale_reflection_height_or_tilt(self):
        truth = generate_experiment({"samples": 8})["truth"]
        for transform in ("scale", "reflection", "height", "tilt"):
            with self.subTest(transform=transform):
                trajectory, beacons = np.array(truth["trajectory"]), np.array(truth["beacons"])
                for points in (trajectory, beacons):
                    if transform == "scale":
                        points *= 1.2
                    elif transform == "reflection":
                        points[:, 1] *= -1
                    elif transform == "height":
                        points[:, 2] += 0.6
                    else:
                        points[:] = points @ np.array([[1, 0, 0], [0, np.cos(0.3), -np.sin(0.3)], [0, np.sin(0.3), np.cos(0.3)]])
                estimate = {"trajectory": trajectory.tolist(), "beacons": beacons.tolist()}
                result = evaluate_geometry(estimate, truth, "joint")
                self.assertGreater(result["aligned"]["position_rmse_m"] + result["aligned"]["map_rmse_m"], 0.1)
                known = evaluate_geometry(estimate, truth, "known_map")
                self.assertFalse(known["alignment"]["applied"])
                self.assertEqual(known["raw"], known["aligned"])

    def test_uniform_uncertainty_rescaling_preserves_rank_and_condition(self):
        diagnostics = []
        for sigma in (0.05, 0.5):
            experiment = generate_experiment({"samples": 8, "assumed_std_m": sigma})
            problem = build_problem(experiment["estimator_input"]["observations"], experiment["truth"]["times_s"])
            parameters = problem.pack(experiment["truth"]["trajectory"], experiment["truth"]["beacons"])
            diagnostics.append(jacobian_diagnostics(parameters, problem))
        self.assertEqual(diagnostics[0]["rank"], diagnostics[1]["rank"])
        self.assertAlmostEqual(diagnostics[0]["condition_number"], diagnostics[1]["condition_number"], places=10)
        np.testing.assert_allclose(diagnostics[0]["singular_values"], 10 * np.array(diagnostics[1]["singular_values"]), rtol=1e-13)


if __name__ == "__main__":
    unittest.main()
