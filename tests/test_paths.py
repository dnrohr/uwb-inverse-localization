import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy.integrate import quad
from scipy.optimize import brentq

from uwb.experiments import generate_experiment, load_json, path_metadata, save_json


class PathTests(unittest.TestCase):
    def path(self, specification, **controls):
        return np.asarray(generate_experiment({"path": specification, **controls})["truth"]["trajectory"])

    def test_legacy_normalization_and_informative_samples_unchanged(self):
        experiment = generate_experiment({"samples": 9})
        self.assertEqual(set(experiment["config"]),
                         {"scenario", "samples", "duration_s", "noise_std_m", "assumed_std_m", "seed"})
        expected = [[1.5, 1.2], [4.65, 1.2], [7.8, 1.2], [8.5, 3.65], [8.5, 6.8],
                    [5.35, 6.8], [2.2, 6.8], [1.5, 4.35], [1.5, 1.2]]
        np.testing.assert_allclose(np.asarray(experiment["truth"]["trajectory"])[:, :2], expected, atol=1e-14)

    def test_line_transform_speed_and_duration(self):
        spec = {"type": "line", "size_m": [8, 2], "scale": 2, "center_m": [3, -4], "rotation_deg": 90}
        points = self.path(spec, samples=17, duration_s=8)
        np.testing.assert_allclose(points[:, 0], 3, atol=1e-14)
        np.testing.assert_allclose(points[:, 1], np.linspace(-12, 4, 17), atol=1e-14)
        np.testing.assert_array_equal(points[:, 2], 0)
        np.testing.assert_array_equal(points, self.path(spec, samples=17, duration_s=80))
        metadata = path_metadata({"path": spec, "samples": 17, "duration_s": 8})
        self.assertEqual(metadata["length_m"], 16)
        self.assertEqual(metadata["speed_m_s"], 2)

    def test_circles_and_signed_arcs_have_exact_angular_speed(self):
        for kind, sweep in (("circle", 360), ("arc", -240)):
            spec = {"type": kind, "size_m": [6, 6], "center_m": [2, 1], "start_angle_deg": 30}
            if kind == "arc":
                spec["arc_angle_deg"] = sweep
            points = self.path(spec, samples=31)
            angles = np.deg2rad(np.linspace(30, 30 + sweep, 31))
            expected = np.column_stack((2 + 3 * np.cos(angles), 1 + 3 * np.sin(angles)))
            np.testing.assert_allclose(points[:, :2], expected, atol=1e-14)
            self.assertAlmostEqual(path_metadata({"path": spec})["length_m"], 3 * abs(np.deg2rad(sweep)))

    def test_rectangle_and_waypoints_follow_arclength_across_corners(self):
        rectangle = self.path({"type": "rectangle", "size_m": [4, 2], "center_m": [0, 0]}, samples=13)
        expected = [[-2, -1], [-1, -1], [0, -1], [1, -1], [2, -1], [2, 0], [2, 1],
                    [1, 1], [0, 1], [-1, 1], [-2, 1], [-2, 0], [-2, -1]]
        np.testing.assert_allclose(rectangle[:, :2], expected, atol=1e-14)
        spec = {"type": "waypoint", "center_m": [0, 0], "waypoints_m": [[0, 0], [0, 0], [3, 0], [3, 4]]}
        points = self.path(spec, samples=8)
        expected = [[0, 0], [1, 0], [2, 0], [3, 0], [3, 1], [3, 2], [3, 3], [3, 4]]
        np.testing.assert_allclose(points[:, :2], expected, atol=1e-14)
        self.assertEqual(path_metadata({"path": spec})["length_m"], 7)

    def test_figure_eight_matches_independent_quadrature_arclength(self):
        # Independently integrate and invert analytic curve speed. Chord lengths
        # between samples are shorter near bends and cannot test true speed.
        speed = lambda theta: np.hypot(4 * np.cos(theta), 3 * np.cos(2 * theta))
        total = quad(speed, 0, 2 * np.pi, epsabs=1e-10)[0]
        expected = []
        for distance in np.linspace(0, total, 25):
            if distance == 0:
                theta = 0
            elif distance == total:
                theta = 2 * np.pi
            else:
                theta = brentq(lambda t: quad(speed, 0, t, epsabs=1e-10)[0] - distance, 0, 2 * np.pi)
            expected.append([4 * np.sin(theta), 1.5 * np.sin(2 * theta)])
        spec = {"type": "figure_eight", "center_m": [0, 0], "size_m": [8, 3]}
        np.testing.assert_allclose(self.path(spec, samples=25)[:, :2], expected, atol=5e-7)
        self.assertAlmostEqual(path_metadata({"path": spec})["length_m"], total, delta=2e-6)

    def test_custom_paths_have_exact_ranges_repeatable_noise_and_roundtrips(self):
        for kind in ("line", "circle", "arc", "rectangle", "figure_eight", "waypoint"):
            with self.subTest(kind=kind):
                experiment = generate_experiment({"path": {"type": kind}, "samples": 8})
                positions = np.asarray(experiment["truth"]["trajectory"])
                beacons = np.asarray(experiment["truth"]["beacons"])
                expected = np.linalg.norm(positions[:, None] - beacons[None], axis=2).ravel()
                actual = [obs["range_m"] for obs in experiment["estimator_input"]["observations"]]
                np.testing.assert_allclose(actual, expected, atol=1e-14)
                noisy_config = {"path": experiment["config"]["path"], "noise_std_m": 0.1, "seed": 2}
                self.assertEqual(generate_experiment(noisy_config)["estimator_input"],
                                 generate_experiment(noisy_config)["estimator_input"])
                with tempfile.TemporaryDirectory() as folder:
                    filename = Path(folder) / "custom.json"
                    save_json(filename, experiment)
                    self.assertEqual(load_json(filename), experiment)

    def test_invalid_control_bounds_and_shapes_rejected(self):
        invalid = [{"type": "unknown"}, {"scale": 0}, {"scale": float("nan")}, {"scale": True},
                   {"center_m": [0]}, {"center_m": [1001, 0]}, {"size_m": [0, 2]},
                   {"rotation_deg": 361}, {"type": "arc", "arc_angle_deg": 0},
                   {"type": "circle", "size_m": [2, 3]}, {"type": "rectangle", "arc_angle_deg": 20},
                   {"type": "waypoint", "waypoints_m": [[0, 0], [0, 0]]},
                   {"type": "waypoint", "waypoints_m": [[0, 0]]}]
        for spec in invalid:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                generate_experiment({"path": spec})
        for duration in (0.001, 3601, True):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                generate_experiment({"path": {}, "duration_s": duration})


if __name__ == "__main__":
    unittest.main()
