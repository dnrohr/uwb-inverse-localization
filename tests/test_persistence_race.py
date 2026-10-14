"""Windows atomic-save contention must not discard completed sweep attempts."""
import copy
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from app import create_app
from uwb.experiments import generate_experiment, load_json, save_json
from uwb.sweeps import load_artifact, run_sweep, save_artifact

# Patching the persistence module's time.sleep also patches the shared time
# module; retain real polling delay so worker tests cannot spin on the mock.
_poll_sleep = time.sleep


class AtomicReplaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.experiment = generate_experiment({"samples": 8})
        cls.sweep = run_sweep({"factor": "noise_std_m", "values": [0.], "seeds": [7],
                              "experiment": {"samples": 8}, "options": {"starts": 1},
                              "variants": [{"label": "one", "max_nfev": 1}]})

    def test_transient_permission_errors_retry_both_atomic_save_paths(self):
        original_replace = Path.replace
        for save, load, payload in ((save_json, load_json, self.experiment),
                                    (save_artifact, load_artifact, self.sweep)):
            with self.subTest(save=save.__name__), tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / "data.json"
                attempts = []

                def temporarily_locked(source, destination):
                    attempts.append((source, destination))
                    if len(attempts) <= 2:
                        raise PermissionError("Reader denies Windows delete sharing")
                    return original_replace(source, destination)

                with patch.object(Path, "replace", temporarily_locked), patch("uwb.experiments.time.sleep") as sleep:
                    save(target, payload)
                self.assertEqual(len(attempts), 3)
                self.assertEqual(sleep.call_count, 2)
                self.assertEqual(load(target), payload)
                self.assertFalse(target.with_suffix(".json.tmp").exists())

    def test_permanent_permission_error_keeps_prior_target_and_complete_temp(self):
        for save, load, payload in ((save_json, load_json, self.experiment),
                                    (save_artifact, load_artifact, self.sweep)):
            with self.subTest(save=save.__name__), tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / "data.json"
                save(target, payload)
                prior = target.read_bytes()
                updated = copy.deepcopy(payload)
                if save is save_json:
                    updated = generate_experiment({"samples": 8, "seed": 8, "noise_std_m": .05})
                else:
                    updated["id"] = "a" * 32
                with patch.object(Path, "replace", side_effect=PermissionError("Permanent lock")) as replace, patch("uwb.experiments.time.sleep") as sleep:
                    with self.assertRaises(PermissionError):
                        save(target, updated)
                self.assertEqual(replace.call_count, 30)
                self.assertEqual(sleep.call_count, 29)
                self.assertEqual(target.read_bytes(), prior)
                self.assertEqual(load(target.with_suffix(".json.tmp")), updated)


class SweepCheckpointTests(unittest.TestCase):
    def config(self, variants=3):
        return {"factor": "noise_std_m", "values": [0.], "seeds": [7],
                "experiment": {"samples": 8}, "options": {"starts": 1},
                "variants": [{"label": f"variant_{index}", "max_nfev": 1} for index in range(variants)]}

    def wait_for_terminal(self, client, identifier, *, persistence_error=False):
        deadline = time.monotonic() + 3.
        while time.monotonic() < deadline:
            response = client.get("/api/jobs/" + identifier)
            self.assertEqual(response.status_code, 200)
            job = response.json
            if job["status"] != "running" and (not persistence_error or "persistence_error" in job):
                return job
            _poll_sleep(.01)
        self.fail(f"Sweep remained running after persistence failure: {job}")

    def test_second_checkpoint_failure_preserves_latest_attempts_and_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            client = create_app(folder).test_client()
            snapshots = []

            def fail_second_checkpoint(path, data):
                snapshots.append(copy.deepcopy(data))
                if len(snapshots) == 2:
                    raise PermissionError("Artifact checkpoint temporarily unavailable")
                save_artifact(path, data)

            with patch("app.save_artifact", side_effect=fail_second_checkpoint):
                response = client.post("/api/sweeps", json=self.config())
                self.assertEqual(response.status_code, 202, response.json)
                identifier = response.json["id"]
                job = self.wait_for_terminal(client, identifier)
            self.assertEqual(job["status"], "failed")
            self.assertEqual(len(job["artifact"]["entries"]), 2)
            self.assertEqual(len(job["artifact"]["start_table"]), 2)
            self.assertEqual([e["run"]["status"] for e in job["artifact"]["entries"]], ["not_converged", "not_converged"])
            with patch("app.load_artifact", side_effect=AssertionError("Terminal failed snapshot must remain readable without disk access")):
                self.assertEqual(client.get("/api/sweeps/" + identifier).json, job["artifact"])
            self.assertEqual(len(client.get("/api/runs").json), 2)
            self.assertEqual(snapshots[0]["entries"][0]["run"]["id"], snapshots[1]["entries"][0]["run"]["id"])
            for entry in job["artifact"]["entries"]:
                expected = uuid.uuid5(uuid.NAMESPACE_URL, f"uwb-sweep/{identifier}/{entry['index']}").hex
                self.assertEqual(entry["run"]["id"], expected)
                self.assertEqual(load_json(Path(folder) / (expected + ".json")), entry["run"])

    def test_repeated_callbacks_and_final_save_reuse_one_id_per_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            client = create_app(folder).test_client()
            writes = []

            def record_write(path, data):
                writes.append((Path(path).stem, data["id"]))
                save_json(path, data)

            with patch("app.save_json", side_effect=record_write):
                response = client.post("/api/sweeps", json=self.config())
                self.assertEqual(response.status_code, 202, response.json)
                identifier = response.json["id"]
                job = self.wait_for_terminal(client, identifier)
            self.assertEqual(job["status"], "complete")
            entry_ids = [e["run"]["id"] for e in job["artifact"]["entries"]]
            self.assertEqual(len(entry_ids), 3)
            self.assertEqual(len(set(entry_ids)), 3)
            self.assertEqual({path for path, _ in writes}, set(entry_ids))
            self.assertTrue(all(path == recorded for path, recorded in writes))
            self.assertEqual(len(list(Path(folder).glob("*.json"))), 3)
            self.assertEqual(len(client.get("/api/runs").json), 3)
            self.assertEqual([sum(path == entry for path, _ in writes) for entry in entry_ids], [4, 3, 2])

    def test_permanent_artifact_lock_reports_terminal_job_with_latest_snapshot(self):
        original_replace = Path.replace
        with tempfile.TemporaryDirectory() as folder:
            client = create_app(folder).test_client()

            def permanently_locked_updates(source, destination):
                destination = Path(destination)
                if destination.parent.name == "artifacts" and destination.exists():
                    raise PermissionError("Permanent artifact reader lock")
                return original_replace(source, destination)

            with patch.object(Path, "replace", permanently_locked_updates), patch("uwb.experiments.time.sleep"):
                response = client.post("/api/sweeps", json=self.config(2))
                self.assertEqual(response.status_code, 202, response.json)
                identifier = response.json["id"]
                job = self.wait_for_terminal(client, identifier, persistence_error=True)
            self.assertEqual(job["status"], "failed")
            self.assertEqual(len(job["artifact"]["entries"]), 1)
            self.assertEqual(len(job["artifact"]["start_table"]), 1)
            self.assertIn("persistence_error", job)
            self.assertEqual(client.get("/api/sweeps/" + identifier).json, job["artifact"])
            # Original pending target remains intact; complete recovery copy survives.
            temporary = Path(folder) / "artifacts" / (identifier + ".json.tmp")
            self.assertEqual(load_artifact(temporary)["entries"], job["artifact"]["entries"])
            # A fresh process has no in-memory jobs; it must recover the validated temp.
            fresh = create_app(folder).test_client()
            reopened = fresh.get("/api/sweeps/" + identifier)
            self.assertEqual(reopened.status_code, 200, reopened.json)
            self.assertEqual(reopened.json["entries"], job["artifact"]["entries"])
            self.assertEqual(reopened.json["status"], "failed")

    def test_imported_sweep_persists_server_owned_ids_before_reopen(self):
        sweep = run_sweep(self.config(1))
        supplied_id = "a" * 32
        sweep["entries"][0]["run"]["id"] = supplied_id
        with tempfile.TemporaryDirectory() as folder:
            client = create_app(folder).test_client()
            with patch("app.run_sweep", side_effect=AssertionError("Import must not solve")):
                response = client.post("/api/artifacts/import", json=sweep)
            self.assertEqual(response.status_code, 200, response.json)
            imported = response.json["artifact"]
            owned_id = imported["entries"][0]["run"]["id"]
            self.assertNotEqual(owned_id, supplied_id)
            self.assertEqual(load_artifact(Path(folder) / "artifacts" / (imported["id"] + ".json")), imported)
            fresh = create_app(folder).test_client()
            self.assertEqual(fresh.get("/api/sweeps/" + imported["id"]).json, imported)
            self.assertEqual(load_json(Path(folder) / (owned_id + ".json")), imported["entries"][0]["run"])


if __name__ == "__main__":
    unittest.main()
