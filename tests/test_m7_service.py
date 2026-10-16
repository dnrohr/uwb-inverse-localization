import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask, jsonify

from uwb import m6, m7
from uwb.m7_service import register_m7


class M7ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.jobs = {}
        self.app = Flask(__name__)
        @self.app.errorhandler(ValueError)
        def invalid(exc): return jsonify(error=str(exc)), 400
        register_m7(self.app, self.directory, jobs=self.jobs)
        self.client = self.app.test_client()
        self.exp = m6.generate_experiment({"samples": 8, "noise_std_m": .02, "assumed_std_m": .02})
        self.options = {"mode": "joint", "beacon_height_model": "independent", "starts": 1,
                        "initialization": "truth_near", "initialization_error_m": .01,
                        "survey": {"frame": "world", "units": "m", "fixed": [
                            {"beacon_id": b, "mask": [True] * 3, "mean_m": self.exp["truth"]["beacons"][b]} for b in range(3)], "priors": []}}

    def tearDown(self):
        self.temporary.cleanup()

    def submit(self, **changes):
        response = self.client.post("/api/m7/runs", json={"experiment": self.exp, "options": self.options, **changes})
        self.assertEqual(response.status_code, 202, response.json)
        return response.json["id"]

    def test_saved_source_reuse_and_offline_detail_uncertainty_export_import(self):
        with patch.object(m6, "generate_experiment", side_effect=AssertionError("reuse never generates")):
            identifier = self.submit()
        run = self.jobs[identifier]["run"]
        self.assertEqual(run["experiment"], self.exp)
        self.assertEqual(run["status"], "success")
        with patch.object(m7, "solve_experiment", side_effect=AssertionError("offline never solves")), patch.object(m6, "generate_experiment", side_effect=AssertionError("offline never generates")):
            self.assertEqual(self.client.get(f"/api/m7/runs/{identifier}").json, run)
            self.assertTrue(self.client.get(f"/api/m7/runs/{identifier}/uncertainty").json["available"])
            self.assertEqual(self.client.get(f"/api/m7/runs/{identifier}/json").json, run)
            self.assertEqual(self.client.get(f"/api/m7/runs/{identifier}/csv").status_code, 200)
            imported = self.client.post("/api/m7/import", json=run)
            self.assertEqual(imported.status_code, 200, imported.json)
            self.assertNotEqual(imported.json["id"], identifier)
            self.assertEqual(imported.json["run"]["source_id"], identifier)
            self.assertEqual(imported.json["run"]["starts"], run["starts"])

    def test_offline_corrupt_import_rejected_without_history_mutation(self):
        identifier = self.submit(); run = copy.deepcopy(self.jobs[identifier]["run"])
        run["starts"][0]["diagnostics"]["survey_objective"] = 123.
        before = set(self.directory.glob("*.json"))
        response = self.client.post("/api/m7/import", json=run)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(before, set(self.directory.glob("*.json")))

    def test_bad_models_and_dual_source_rejected_before_queue(self):
        for changes in ({"beacon_height_model": "shared"}, {"mode": "known_map"}, {"height_parameterization": "q"}):
            response = self.client.post("/api/m7/runs", json={"experiment": self.exp, "options": {**self.options, **changes}})
            self.assertEqual(response.status_code, 400, response.json)
        response = self.client.post("/api/m7/runs", json={"config": {}, "experiment": self.exp, "options": self.options})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(self.jobs), 0)

    def test_nonconverged_run_preserved_and_covariance_unavailable(self):
        identifier = self.submit(options={**self.options, "max_nfev": 1})
        run = self.jobs[identifier]["run"]
        self.assertEqual(run["status"], "not_converged")
        self.assertIsNotNone(run["starts"][0]["estimate"])
        self.assertFalse(self.client.get(f"/api/m7/runs/{identifier}/uncertainty").json["available"])

    def test_no_survey_submission_preserves_legacy_record(self):
        identifier = self.submit(options={"mode": "known_map", "starts": 1})
        run = self.jobs[identifier]["run"]
        self.assertEqual(run["schema_version"], "6.0")
        self.assertTrue(self.client.get(f"/api/m7/runs/{identifier}/uncertainty").json["available"])

    def test_interrupted_request_is_reopened_without_resolving(self):
        identifier = "a" * 32
        initial = m7.make_initial_geometries(self.exp, self.options)
        envelope = {"schema_version": "7.0", "id": identifier, "status": "running", "experiment": self.exp,
                    "options": m7.validate_options(self.options), "starts": [], "selected_start": None, "diagnostics": {},
                    "requested_initial_geometries": initial}
        m7.save_run(self.directory / (identifier + ".json"), envelope)
        with patch.object(m7, "solve_experiment", side_effect=AssertionError("interrupted does not solve")):
            response = self.client.get(f"/api/m7/runs/{identifier}")
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(response.json["status"], "interrupted")
            self.assertEqual(response.json["requested_initial_geometries"], initial)
            self.assertFalse(self.client.get(f"/api/m7/runs/{identifier}/uncertainty").json["available"])
        self.assertEqual(json.loads((self.directory / (identifier + ".json")).read_text())["status"], "running")

    def test_storage_failure_keeps_optimizer_success_separate(self):
        original = m7.save_run
        failed = False
        def transient(path, run):
            nonlocal failed
            if run["status"] == "success" and not failed:
                failed = True
                raise OSError("injected final write failure")
            return original(path, run)
        with patch.object(m7, "save_run", side_effect=transient):
            identifier = self.submit()
        self.assertEqual(self.jobs[identifier]["status"], "failed")
        run = self.jobs[identifier]["run"]
        self.assertEqual(run["status"], "success")
        self.assertEqual(run["infrastructure_status"], "failed")
        self.assertEqual(self.client.get(f"/api/m7/runs/{identifier}").status_code, 200)


if __name__ == "__main__": unittest.main()
