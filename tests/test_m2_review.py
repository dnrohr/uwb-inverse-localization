"""Independent checks of numerical pairing and failure-accounting conventions."""
import unittest
from unittest.mock import patch

import numpy as np

from uwb.sweeps import run_sweep


class M2ReviewTests(unittest.TestCase):
    def configuration(self, **overrides):
        return {"values": [0], "seeds": [4], "experiment": {"samples": 8},
                "options": {"starts": 2},
                "variants": [{"label": "joint", "mode": "joint", "max_nfev": 1},
                             {"label": "surveyed", "mode": "known_map", "max_nfev": 1}], **overrides}

    def test_cross_mode_pairs_preserve_observations_and_trajectory_starts(self):
        sweep = run_sweep(self.configuration())
        left, right = [entry["run"] for entry in sweep["entries"]]
        self.assertEqual(left["experiment"], right["experiment"])
        self.assertEqual(left["options"]["seed"], right["options"]["seed"])
        for joint, surveyed in zip(left["starts"], right["starts"]):
            self.assertEqual(joint["initial"]["trajectory"], surveyed["initial"]["trajectory"])
            self.assertEqual(surveyed["initial"]["beacons"], right["experiment"]["truth"]["beacons"])
        self.assertEqual(sum(row["failed_start_count"] for row in sweep["aggregates"]), 4)
        self.assertEqual(len(sweep["start_table"]), 4)

    def test_whole_run_exceptions_keep_attempts_and_null_geometry_metrics(self):
        with patch("uwb.sweeps._solve_cell", side_effect=RuntimeError("review failure")):
            sweep = run_sweep(self.configuration())
        self.assertEqual(len(sweep["start_table"]), 4)
        for row in sweep["start_table"]:
            self.assertEqual(row["classification"], "failed")
            self.assertIsNone(row["position_rmse_m"])
            self.assertIsNone(row["range_rmse_m"])
            self.assertFalse(row["accepted"])
        for group in sweep["aggregates"]:
            self.assertEqual(group["failure_rate"], 1)
            self.assertEqual(group["failed_run_count"], 1)
            self.assertEqual(group["selected_seed_position_rmse_m"]["count"], 0)
            self.assertIsNone(group["all_start_position_rmse_m"]["median"])

    def test_zero_initial_error_preserves_small_positive_truth_coordinates(self):
        sweep = run_sweep(self.configuration(factor="initial_error_m", experiment={"samples": 8, "scenario": "nearly_collinear"}))
        joint = sweep["entries"][0]["run"]
        for start in joint["starts"]:
            np.testing.assert_array_equal(start["initial"]["beacons"], joint["experiment"]["truth"]["beacons"])
            np.testing.assert_array_equal(start["initial"]["trajectory"], joint["experiment"]["truth"]["trajectory"])

    def test_assumed_uncertainty_changes_weights_preserving_measurements_and_starts(self):
        sweep = run_sweep(self.configuration(factor="assumed_std_m", values=[0.05, 0.5],
                                            experiment={"samples": 8, "noise_std_m": 0.1}))
        low = sweep["entries"][0]["run"]
        high = sweep["entries"][2]["run"]
        left_records = low["experiment"]["estimator_input"]["observations"]
        right_records = high["experiment"]["estimator_input"]["observations"]
        self.assertEqual([obs["range_m"] for obs in left_records], [obs["range_m"] for obs in right_records])
        for left, right in zip(low["starts"], high["starts"]):
            self.assertEqual(left["initial"], right["initial"])
            self.assertAlmostEqual(left["solver"]["initial_objective"] / right["solver"]["initial_objective"], 100, places=10)


if __name__ == "__main__":
    unittest.main()
