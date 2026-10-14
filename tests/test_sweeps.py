"""Numerical pairing, accounting and offline persistence checks for M2."""
import copy
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from uwb.estimation import solve_experiment
from uwb.experiments import ExperimentFormatError, generate_experiment
from uwb.sweeps import (aggregate_sweep, build_comparison, load_artifact,
                        run_sweep, save_artifact, table_csv, validate_artifact,
                        validate_sweep_config)


class SweepTests(unittest.TestCase):
    def config(self, **overrides):
        return {"factor": "noise_std_m", "values": [0., .05], "seeds": [7],
                "experiment": {"samples": 8},
                "options": {"starts": 2, "initialization": "truth_near"},
                "variants": [{"label": "short", "max_nfev": 1},
                             {"label": "full", "max_nfev": 200}], **overrides}

    def test_paired_budget_starts_observations_and_replay_are_identical(self):
        first = run_sweep(self.config())
        second = run_sweep(self.config())
        for offset in (0, 2):
            left, right = [e["run"] for e in first["entries"][offset:offset+2]]
            self.assertEqual(left["experiment"], right["experiment"])
            self.assertEqual([s["initial"] for s in left["starts"]], [s["initial"] for s in right["starts"]])
        for a, b in zip(first["entries"], second["entries"]):
            self.assertEqual(a["run"]["experiment"], b["run"]["experiment"])
            for sa, sb in zip(a["run"]["starts"], b["run"]["starts"]):
                self.assertEqual(sa["initial"], sb["initial"])
                self.assertEqual(sa["estimate"], sb["estimate"])
        exact, noisy = [first["entries"][i]["run"]["experiment"] for i in (0, 2)]
        distances = np.array([o["range_m"] for o in exact["estimator_input"]["observations"]])
        errors = np.array([o["range_m"] for o in noisy["estimator_input"]["observations"]]) - distances
        expected = np.random.default_rng(7).normal(0., .05, (8, 4)).ravel()
        np.testing.assert_allclose(errors, expected, atol=1e-15)
        self.assertEqual(first["aggregates"][0]["failure_rate"], 1.)
        self.assertTrue(all(r["exact_reference_geometry"] for r in first["start_table"] if r["variant"] == "full" and r["exact_data"]))
        self.assertTrue(all(not r["exact_reference_geometry"] for r in first["start_table"] if not r["exact_data"]))

    def test_all_five_single_factors_preserve_other_controls(self):
        factors = {"noise_std_m": [0., .1], "path_scale": [.5, 1.],
                   "samples": [8, 12], "initial_error_m": [0., .2], "assumed_std_m": [.05, .5]}
        for factor, values in factors.items():
            with self.subTest(factor=factor):
                sweep = run_sweep(self.config(factor=factor, values=values,
                    experiment={"samples": 8, "path": {"type": "rectangle"}},
                    options={"starts": 1, "mode": "known_map", "initialization": "independent"},
                    variants=[{"label": "baseline", "max_nfev": 100}]))
                left, right = [e["run"] for e in sweep["entries"]]
                self.assertEqual(left["experiment"]["truth"]["beacons"], right["experiment"]["truth"]["beacons"])
                if factor in ("assumed_std_m", "initial_error_m"):
                    self.assertEqual([o["range_m"] for o in left["experiment"]["estimator_input"]["observations"]],
                                     [o["range_m"] for o in right["experiment"]["estimator_input"]["observations"]])
                if factor == "assumed_std_m":
                    self.assertEqual(left["starts"][0]["initial"], right["starts"][0]["initial"])
                if factor == "initial_error_m":
                    self.assertEqual(left["starts"][0]["initial"]["trajectory"], left["experiment"]["truth"]["trajectory"])
                    self.assertEqual(sweep["config"]["options"]["initialization"], "truth_near")
                if factor == "path_scale":
                    a, b = [np.asarray(r["experiment"]["truth"]["trajectory"])[:, :2] for r in (left, right)]
                    np.testing.assert_allclose(a - [5.,4.], .5 * (b - [5.,4.]))

    def test_modes_share_positions_with_explicit_survey_projection(self):
        sweep = run_sweep(self.config(values=[0.], options={"starts": 2, "initialization": "independent"},
                    variants=[{"label": "joint", "mode": "joint"}, {"label": "surveyed", "mode": "known_map"}]))
        joint, surveyed = [e["run"] for e in sweep["entries"]]
        self.assertEqual(joint["experiment"], surveyed["experiment"])
        for a, b in zip(joint["starts"], surveyed["starts"]):
            self.assertEqual(a["initial"]["trajectory"], b["initial"]["trajectory"])
            self.assertEqual(b["initial"]["beacons"], surveyed["experiment"]["truth"]["beacons"])
        self.assertNotEqual(joint["starts"][0]["initial"]["beacons"], joint["experiment"]["truth"]["beacons"])
        self.assertIn("projects", sweep["pairing"]["map_constraint"])

    def test_every_failure_seed_and_start_is_retained_and_checkpointed(self):
        snapshots = []
        with patch("uwb.sweeps.fit_observations", side_effect=RuntimeError("controlled failure")):
            sweep = run_sweep(self.config(seeds=[7, 8]), on_progress=snapshots.append)
        self.assertEqual(len(sweep["entries"]), 8)
        self.assertEqual(len(sweep["start_table"]), 16)
        self.assertEqual([len(s["entries"]) for s in snapshots], list(range(1, 9)))
        self.assertTrue(all(s["status"] == "running" for s in snapshots))
        for snapshot in snapshots:
            validate_artifact(snapshot)
        for row in sweep["aggregates"]:
            self.assertEqual(row["failed_run_count"], 2)
            self.assertEqual(row["start_count"], 4)
            self.assertEqual(row["failure_rate"], 1.)
            self.assertEqual(row["all_start_position_rmse_m"]["count"], 0)
        self.assertTrue(all(e["run"]["selected_start"] is None for e in sweep["entries"]))
        with patch("uwb.sweeps._initials", side_effect=RuntimeError("seed failure")):
            failed = run_sweep(self.config(values=[0.]))
        self.assertEqual(len(failed["start_table"]), 4)
        self.assertTrue(all(s["initial"] is None for e in failed["entries"] for s in e["run"]["starts"]))

    def test_rank_loss_and_alternate_low_residual_solutions_remain_visible(self):
        sweep = run_sweep(self.config(values=[0.], experiment={"scenario": "straight_line", "samples": 16},
                    options={"starts": 2, "initialization": "independent"}, variants=[{"label": "full", "max_nfev": 1000}]))
        self.assertTrue(all(r["truth_full_column_rank"] is False for r in sweep["start_table"]))
        self.assertEqual(sweep["solution_groups"][0]["distinct_low_residual_solution_count"], 2)
        self.assertTrue(all(r["low_residual"] for r in sweep["start_table"]))
        self.assertTrue(all(not r["exact_reference_geometry"] for r in sweep["start_table"]))

    def test_strict_roundtrip_never_solves_or_regenerates_and_detects_tampering(self):
        sweep = run_sweep(self.config(values=[0.], variants=[{"label": "full", "max_nfev": 100}]))
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "sweep.json"
            save_artifact(target, sweep)
            with patch("uwb.sweeps.fit_observations", side_effect=AssertionError("must not solve")), patch("uwb.sweeps.generate_experiment", side_effect=AssertionError("must not regenerate")):
                self.assertEqual(load_artifact(target), sweep)
            target.write_text('{"schema_version":"2.0","artifact_type":"sweep","x":NaN}', encoding="utf-8")
            with self.assertRaises(ExperimentFormatError):
                load_artifact(target)
        changed = copy.deepcopy(sweep)
        changed["entries"][0]["run"]["starts"].pop()
        with self.assertRaises(ExperimentFormatError):
            validate_artifact(changed)
        changed = copy.deepcopy(sweep)
        changed["aggregates"][0]["failed_start_count"] += 1
        with self.assertRaises(ExperimentFormatError):
            validate_artifact(changed)
        table = list(csv.DictReader(io.StringIO(table_csv(sweep))))
        self.assertEqual(len(table), 2)
        self.assertEqual(aggregate_sweep(sweep)["start_table"], sweep["start_table"])
        json.dumps(sweep, allow_nan=False)

    def test_limits_and_invalid_controls_are_rejected_before_any_solve(self):
        bad = [self.config(options={"starts": 13}), self.config(values=list(range(10)), seeds=list(range(10))),
               self.config(factor="samples", values=[8.5]), self.config(values=[0., float("inf")]),
               self.config(values=[1e308]), self.config(factor="initial_error_m", values=[101.]),
               self.config(factor="assumed_std_m", values=[1e-300]), self.config(values=[0., 0.]),
               self.config(variants=[{"label":"bad", "initialization":"truth_near"}]),
               self.config(factor="path_scale", values=[1.], experiment={"scenario":"straight_line"})]
        with patch("uwb.sweeps.fit_observations", side_effect=AssertionError("must not solve")):
            for config in bad:
                with self.subTest(config=config), self.assertRaises(ValueError):
                    run_sweep(config)
        normalized = validate_sweep_config(self.config())
        self.assertEqual(validate_sweep_config(normalized), normalized)


class ComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.left = solve_experiment(generate_experiment({"samples": 8, "duration_s": 4.}), {"mode":"known_map", "starts":1})
        cls.right = solve_experiment(generate_experiment({"samples": 12, "duration_s": 2., "noise_std_m": .05}), {"mode":"known_map", "starts":1})

    def test_common_elapsed_reference_shared_metric_bounds_and_no_extrapolation(self):
        comparison = build_comparison(self.left, self.right)
        self.assertEqual(comparison["common_elapsed_times_s"][0], 0.)
        self.assertEqual(comparison["common_elapsed_times_s"][-1], 4.)
        self.assertIsNone(comparison["views"][1]["interpolated_trajectory"][-1])
        self.assertEqual(len(comparison["views"][0]["position_errors_m"]), 8)
        self.assertEqual(len(comparison["views"][1]["position_errors_m"]), 12)
        spans = [b[1]-b[0] for b in comparison["shared_bounds_m"].values()]
        np.testing.assert_allclose(spans, spans[0])
        self.assertTrue(all(v["alignment"]["scale"] == 1. for v in comparison["views"]))
        self.assertEqual(comparison["table"][0]["position_rmse_m"], self.left["starts"][0]["diagnostics"]["evaluation"]["raw"]["position_rmse_m"])

    def test_scale_cannot_be_hidden_by_alignment_or_tampered_comparison(self):
        run = solve_experiment(generate_experiment({"samples":8}), {"starts":1, "initialization":"truth_near"})
        scaled = copy.deepcopy(run)
        for key in ("trajectory", "beacons"):
            scaled["starts"][0]["estimate"][key] = (2 * np.asarray(scaled["starts"][0]["estimate"][key])).tolist()
        comparison = build_comparison(run, scaled)
        self.assertGreater(comparison["table"][1]["map_rmse_m"], 1.)
        changed = copy.deepcopy(comparison)
        changed["views"][1]["alignment"]["scale"] = .5
        with self.assertRaises(ExperimentFormatError):
            validate_artifact(changed)
        changed = copy.deepcopy(comparison)
        changed["table"][1]["map_rmse_m"] = 0.
        with self.assertRaises(ExperimentFormatError):
            validate_artifact(changed)

    def test_saved_comparison_reopens_without_solve_and_failed_runs_are_reviewable(self):
        failed = copy.deepcopy(self.right)
        failed["status"] = "failed"
        failed["selected_start"] = None
        failed["starts"][0].update(status="failed", success=False, estimate=None)
        failed["starts"][0]["solver"]["runtime_s"] = None
        comparison = build_comparison(self.left, failed, alignment="raw")
        self.assertIsNone(comparison["views"][1]["estimate"])
        self.assertIsNone(comparison["table"][1]["position_rmse_m"])
        self.assertIsNone(comparison["table"][1]["runtime_s"])
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "comparison.json"
            save_artifact(target, comparison)
            with patch("uwb.sweeps.fit_observations", side_effect=AssertionError("must not solve")):
                self.assertEqual(load_artifact(target), comparison)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(table_csv(comparison))))), 2)
        failed["starts"] = []
        self.assertIsNone(build_comparison(self.left, failed)["table"][1]["runtime_s"])


if __name__ == "__main__":
    unittest.main()
