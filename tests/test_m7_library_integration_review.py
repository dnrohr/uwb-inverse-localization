"""Independent source-authority and strict offline Library boundary checks.

These small fixtures intentionally contain an embedded run and a different
local run with the same recorded ID. No similarity heuristic may substitute
one authoritative source for the other.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import create_app
from uwb import m3_sweeps, m4, m4_sweeps, m5, m5_sweeps, m6, m6_sweeps, m7, sweeps
from uwb.experiments import save_json
from uwb.library import LibraryIndex


class LibrarySourceAuthorityReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = m6_sweeps.run_sweep({"base_experiment": {"samples": 8},
            "options": {"mode": "known_map", "starts": 1, "max_nfev": 1},
            "factor": "nlos_prevalence", "values": [0], "seeds": [7],
            "variants": [{"label": "Gaussian", "options": {"loss": "gaussian"}}]})
        cls.local = m6.solve_experiment(m6.generate_experiment({"samples": 8, "seed": 23, "noise_std_m": .01}),
                                       {"mode": "known_map", "starts": 1, "max_nfev": 1})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.folder = Path(self.temp.name)
        (self.folder / "artifacts").mkdir()
        self.run_id, self.parent_id = "a" * 32, "b" * 32
        parent = copy.deepcopy(self.parent); parent["id"] = self.parent_id
        parent["entries"][0]["run"]["id"] = self.run_id
        local = copy.deepcopy(self.local); local.update(id=self.run_id, reference_name="Deliberately distinct local source")
        self.parent_path = self.folder / "artifacts" / (self.parent_id + ".json")
        self.local_path = self.folder / (self.run_id + ".json")
        m6_sweeps.save_artifact(self.parent_path, parent); save_json(self.local_path, local)
        self.client = create_app(self.folder).test_client()
        self.child_key = "artifact:" + self.parent_id + ":entry:0"
        self.local_key = "run:" + self.run_id

    def tearDown(self): self.temp.cleanup()

    def test_compare_uses_selected_parent_source_and_distinct_local_copy_offline(self):
        with (patch.object(m6, "generate_experiment", side_effect=AssertionError("offline generation")),
              patch.object(m4, "least_squares", side_effect=AssertionError("offline fit")),
              patch.object(m5, "least_squares", side_effect=AssertionError("offline fit")),
              patch.object(m6, "least_squares", side_effect=AssertionError("offline fit")),
              patch.object(m7, "least_squares", side_effect=AssertionError("offline fit"))):
            grouped = self.client.get("/api/library").json
            self.assertEqual(grouped["total"], 1)  # one parent group, no guessed duplicate removal
            self.assertEqual(grouped["overall_total"], 2)  # actual retained sources, separate from groups
            self.assertEqual(self.client.get("/api/library?view=all").json["total"], 2)
            child = self.client.get("/api/library/" + self.child_key).json
            self.assertEqual(child["source_path"], "artifacts/" + self.parent_id + ".json")
            self.assertEqual(child["open_url"], "/api/m6/sweeps/" + self.parent_id)
            self.assertEqual(self.client.get(child["open_url"]).status_code, 200)
            response = self.client.post("/api/library/compare", json={"keys": [self.child_key, self.local_key]})
            self.assertEqual(response.status_code, 200, response.json)
            artifact = response.json["artifact"]
            self.assertEqual(artifact["runs"][0]["experiment"], self.parent["entries"][0]["run"]["experiment"])
            self.assertEqual(artifact["runs"][1]["experiment"], self.local["experiment"])
            self.assertFalse(artifact["pairing"]["paired"])
            self.assertEqual(artifact["library_sources"][0]["entry_ordinal"], 0)

    def test_corrupt_parent_child_never_falls_back_to_valid_same_id_copy(self):
        raw = json.loads(self.parent_path.read_text())
        raw["entries"][0]["run"]["starts"][0]["solver"]["final_objective"] += 999.
        self.parent_path.write_text(json.dumps(raw), encoding="utf-8")
        preview = self.client.get("/api/library/" + self.child_key)
        self.assertEqual(preview.status_code, 200)
        self.assertIn("unchecked", preview.json["summary_validation"])
        self.assertEqual(self.client.get(preview.json["open_url"]).status_code, 400)
        self.assertEqual(self.client.get("/api/runs/" + self.run_id).status_code, 200)
        compared = self.client.post("/api/library/compare", json={"keys": [self.child_key, self.local_key]})
        self.assertEqual(compared.status_code, 400, compared.json)

    def test_corrupt_local_copy_does_not_hide_valid_embedded_source(self):
        raw = json.loads(self.local_path.read_text())
        raw["starts"][0]["solver"]["final_objective"] += 999.
        self.local_path.write_text(json.dumps(raw), encoding="utf-8")
        self.assertEqual(self.client.get("/api/runs/" + self.run_id).status_code, 400)
        child = self.client.get("/api/library/" + self.child_key).json
        self.assertEqual(self.client.get(child["open_url"]).status_code, 200)
        compared = self.client.post("/api/library/compare", json={"keys": [self.child_key, self.child_key]})
        self.assertEqual(compared.status_code, 200, compared.json)
        self.assertTrue(compared.json["artifact"]["pairing"]["paired"])

    def test_each_sweep_family_rejects_invalid_empty_failure_but_keeps_valid_interruption(self):
        families = [("2.0", "sweep", sweeps, "/api/sweeps/"),
                    ("3.0", "timing_sweep", m3_sweeps, "/api/m3/sweeps/"),
                    ("4.0", "geometry_sweep", m4_sweeps, "/api/m4/sweeps/"),
                    ("5.0", "solver_sweep", m5_sweeps, "/api/m5/sweeps/"),
                    ("6.0", "robust_sweep", m6_sweeps, "/api/m6/sweeps/")]
        for i, (schema, kind, module, prefix) in enumerate(families):
            identifier = f"{100 + i:032x}"; path = self.folder / "artifacts" / (identifier + ".json")
            bad = {"schema_version": schema, "artifact_type": kind, "id": identifier, "status": "failed", "entries": [], "config": {}}
            path.write_text(json.dumps(bad), encoding="utf-8")
            response = self.client.get(prefix + identifier)
            self.assertEqual(response.status_code, 400, (schema, response.json))
            valid = {**bad, "status": "running", "config": module.validate_sweep_config({})}
            original = json.dumps(valid).encode(); path.write_bytes(original)
            response = self.client.get(prefix + identifier)
            self.assertEqual(response.status_code, 200, (schema, response.json))
            self.assertEqual(response.json.get("saved_status"), "running", (schema, response.json))
            self.assertIn("Interrupted", response.json["error"])
            self.assertEqual(path.read_bytes(), original)

    def test_imported_comparison_embedded_sources_remain_selectable_offline(self):
        left = copy.deepcopy(self.local); right = copy.deepcopy(left)
        left["id"] = "c" * 32; right["id"] = "d" * 32
        source = sweeps.build_comparison(left, right)
        imported = self.client.post("/api/artifacts/import", json=source)
        self.assertEqual(imported.status_code, 200, imported.json)
        identifier = imported.json["id"]
        children = self.client.get("/api/library?parent=artifact:" + identifier).json
        self.assertEqual(children["total"], 2)
        self.assertEqual({r["comparison_side"] for r in children["items"]}, {0, 1})
        keys = [r["key"] for r in children["items"]]
        with patch.object(m6, "solve_experiment", side_effect=AssertionError("offline")), patch.object(m6, "generate_experiment", side_effect=AssertionError("offline")):
            compared = self.client.post("/api/library/compare", json={"keys": keys, "alignment": "raw"})
            self.assertEqual(compared.status_code, 200, compared.json)
            self.assertTrue(compared.json["artifact"]["pairing"]["paired"])
            self.assertEqual(compared.json["artifact"]["runs"][0]["experiment"], left["experiment"])


if __name__ == "__main__": unittest.main()
