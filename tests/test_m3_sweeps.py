"""M3 paired sweep accounting, validation and offline reuse."""
import copy
import csv
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uwb.experiments import ExperimentFormatError
from uwb.m3_sweeps import run_sweep, validate_sweep_config, validate_artifact, save_artifact, load_artifact, table_csv


class TimingSweepTests(unittest.TestCase):
    def config(self, **changes):
        return {"base_experiment": {"samples": 8, "duration_s": 4},
                "options": {"starts": 1, "mode": "known_map", "initialization": "truth_near", "max_nfev": 30},
                "factor": "spacing_s", "values": [0., .05], "seeds": [7], **changes}

    def test_models_share_observations_and_starts(self):
        sweep = run_sweep(self.config())
        self.assertEqual(len(sweep["start_table"]), 4)
        for a, b in zip(sweep["entries"][::2], sweep["entries"][1::2]):
            self.assertEqual(a["run"]["experiment"], b["run"]["experiment"])
            self.assertEqual([s["initial"] for s in a["run"]["starts"]], [s["initial"] for s in b["run"]["starts"]])
        self.assertEqual({r["model"] for r in sweep["start_table"]}, {"timestamp_aware", "grouped"})
        self.assertIn("measurement_full_column_rank", sweep["start_table"][0])
        self.assertIn("prior_objective", sweep["start_table"][0])

    def test_reopen_and_csv_do_not_generate_or_solve(self):
        sweep = run_sweep(self.config(values=[0.]))
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/"sweep.json"
            save_artifact(target, sweep)
            with patch("uwb.m3_sweeps.m3.solve_experiment", side_effect=AssertionError("offline")), patch("uwb.m3_sweeps.m3.generate_experiment", side_effect=AssertionError("offline")):
                reopened = load_artifact(target)
                self.assertEqual(sweep, reopened)
                self.assertEqual(len(list(csv.DictReader(io.StringIO(table_csv(reopened))))), 2)
        changed = copy.deepcopy(sweep)
        changed["aggregates"][0]["start_count"] += 1
        with self.assertRaises(ExperimentFormatError):
            validate_artifact(changed)
        changed = copy.deepcopy(sweep)
        changed["entries"][1]["run"]["starts"][0]["initial"]["trajectory"][0][0] += 1
        with self.assertRaises(ExperimentFormatError):
            validate_artifact(changed)

    def test_all_failures_retained_in_progress_and_aggregate(self):
        progress = []
        with patch("uwb.m3_sweeps.m3.solve_experiment", side_effect=RuntimeError("controlled failure")):
            sweep = run_sweep(self.config(seeds=[7, 8]), on_progress=progress.append)
        self.assertEqual(len(sweep["entries"]), 8)
        self.assertEqual([len(p["entries"]) for p in progress], list(range(1, 9)))
        for snapshot in progress:
            validate_artifact(snapshot)
        self.assertTrue(all(r["classification"] == "failed" for r in sweep["start_table"]))
        self.assertTrue(all(a["nonconvergence_rate"] == 1 for a in sweep["aggregates"]))

    def test_factor_controls_and_limits(self):
        factors = {"speed_scale": [0., 1.], "spacing_s": [0., .05], "knot_spacing_s": [0., .5],
                   "timestamp_offset_s": [-.02, .02], "timestamp_jitter_s": [0., .02],
                   "missing_probability": [0., .2], "beacon_every_cycles": [1, 3]}
        for factor, values in factors.items():
            self.assertEqual(validate_sweep_config(self.config(factor=factor, values=values))["values"], values)
        for changes in ({"values": [0., 0.]}, {"seeds": [True]}, {"factor": "delivery_latency_s"},
                        {"values": [float("nan")]}, {"factor": "missing_probability", "values": [1.1]},
                        {"factor": "beacon_every_cycles", "values": [1.5]}, {"values": list(range(10)), "seeds": [1,2,3]}):
            with self.assertRaises(ValueError):
                validate_sweep_config(self.config(**changes))


if __name__ == "__main__":
    unittest.main()
