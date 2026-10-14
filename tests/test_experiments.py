import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from uwb.experiments import ExperimentFormatError, generate_experiment, load_json, save_json


class ExperimentTests(unittest.TestCase):
    def test_generated_ranges_match_independent_distances(self):
        experiment = generate_experiment({"samples": 12, "noise_std_m": 0.0})
        path = np.asarray(experiment["truth"]["trajectory"])
        beacons = np.asarray(experiment["truth"]["beacons"])
        expected = np.linalg.norm(path[:, None, :] - beacons[None, :, :], axis=2)
        for record in experiment["estimator_input"]["observations"]:
            self.assertAlmostEqual(record["range_m"], expected[record["epoch"], record["beacon_id"]], places=13)

    def test_fixed_seed_reproduces_observations(self):
        config = {"samples": 16, "noise_std_m": [0.05, 0.1, 0.0, 0.2], "seed": 41}
        left = generate_experiment(config)
        right = generate_experiment(config)
        self.assertEqual(left["estimator_input"], right["estimator_input"])
        self.assertEqual(left["truth"], right["truth"])

    def test_all_reference_scenarios_generate(self):
        for scenario in ("informative", "straight_line", "narrow_coverage", "nearly_collinear"):
            with self.subTest(scenario=scenario):
                experiment = generate_experiment({"scenario": scenario, "samples": 8})
                self.assertEqual(len(experiment["truth"]["trajectory"]), 8)
                self.assertEqual(len(experiment["truth"]["beacons"]), 4)
                self.assertEqual(len(experiment["estimator_input"]["observations"]), 32)
        nearly = generate_experiment({"scenario": "nearly_collinear", "samples": 8})
        self.assertEqual([b[1] for b in nearly["truth"]["beacons"]], [0.0, 0.0, 0.004, 0.006])

    def test_narrow_coverage_samples_are_constant_speed(self):
        path = np.asarray(generate_experiment({"scenario": "narrow_coverage", "samples": 32})["truth"]["trajectory"])
        dense_u = np.linspace(-1.0, 1.0, 1001)
        dense_path = np.column_stack(
            (4.5 + 0.35 * dense_u, 3.5 + 0.25 * np.sin(np.pi * dense_u), np.zeros_like(dense_u))
        )
        dense_distance = np.concatenate(
            ([0.0], np.cumsum(np.linalg.norm(np.diff(dense_path, axis=0), axis=1)))
        )
        # x is strictly increasing on this reference path, so interpolate the
        # dense-polyline arc coordinate at each emitted sample.
        sample_distance = np.interp(path[:, 0], dense_path[:, 0], dense_distance)
        step_lengths = np.diff(sample_distance)
        self.assertLess(np.ptp(step_lengths) / np.mean(step_lengths), 1e-10)

    def test_noise_is_independent_and_uses_per_beacon_scales(self):
        config = {"samples": 32, "noise_std_m": [0.02, 0.08, 0.2, 0.5], "seed": 5}
        experiment = generate_experiment(config)
        truth = np.asarray(experiment["truth"]["trajectory"])
        beacons = np.asarray(experiment["truth"]["beacons"])
        expected = np.linalg.norm(truth[:, None, :] - beacons[None, :, :], axis=2)
        measured = np.zeros_like(expected)
        for record in experiment["estimator_input"]["observations"]:
            measured[record["epoch"], record["beacon_id"]] = record["range_m"]
        residual = measured - expected
        # Independent streams across beacon columns should not be duplicates or
        # perfectly correlated, and empirical spread should reflect scale order.
        self.assertTrue(np.all(np.std(residual, axis=0) > 0.0))
        self.assertGreater(np.std(residual[:, 3]), np.std(residual[:, 0]))
        self.assertLess(abs(np.corrcoef(residual.T)[0, 3]), 0.7)

    def test_round_trip_preserves_data_and_float_values(self):
        experiment = generate_experiment({"scenario": "narrow_coverage", "samples": 11, "noise_std_m": 0.01})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "experiment.json"
            save_json(path, experiment)
            loaded = load_json(path)
        self.assertEqual(loaded, experiment)

    def test_failed_run_round_trip_preserves_empty_starts_and_error(self):
        run = {
            "schema_version": "1.0",
            "id": "failed-run",
            "status": "failed",
            "experiment": generate_experiment({"samples": 8}),
            "options": {"mode": "joint", "starts": 3},
            "starts": [],
            "error": "RuntimeError: deliberately failed",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failed-run.json"
            save_json(path, run)
            loaded = load_json(path)
        self.assertEqual(loaded, run)
        self.assertEqual(loaded["starts"], [])
        self.assertEqual(loaded["error"], run["error"])

    def test_strict_json_rejects_nonfinite_values(self):
        experiment = generate_experiment({"samples": 8})
        experiment["estimator_input"]["observations"][0]["range_m"] = float("nan")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            with self.assertRaises(ExperimentFormatError):
                save_json(path, experiment)
            path.write_text('{"x": NaN}', encoding="utf-8")
            with self.assertRaises(ExperimentFormatError):
                load_json(path)

    def test_estimator_input_does_not_include_truth(self):
        experiment = generate_experiment()
        self.assertEqual(set(experiment["estimator_input"]), {"times_s", "observations"})
        self.assertNotIn("truth", experiment["estimator_input"])


if __name__ == "__main__":
    unittest.main()
