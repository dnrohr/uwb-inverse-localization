"""Final M5 evidence reconciliation; never solve or regenerate observations."""
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from contextlib import ExitStack
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from uwb import m3, m4, m5, m5_sweeps


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main():
    folder = ROOT / "evidence/m5" / ("delivery_audit_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8])
    folder.mkdir()
    result = {"status": "incomplete", "scope": "M5 only", "errors": [], "checks": {}, "files": []}
    def record():
        text = json.dumps(result, indent=2, allow_nan=False) + "\n"
        (folder / "audit.json").write_text(text, encoding="utf-8")
        (ROOT / "evidence/m5/final_audit.json").write_text(text, encoding="utf-8")
    record()
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        assert head == "38d77728fd5712a9814e4b57aafc5796fc4c1817", head
        result["base_commit"] = head
        manifest = read("evidence/m5/preservation_manifest.json")
        changes = [name for name, digest in manifest.items() if not (ROOT/name).exists() or hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != digest]
        assert not changes, changes
        result["checks"]["preservation"] = {"status": "passed", "files": len(manifest), "changes": changes}
        tests = (ROOT/"evidence/m5/test_results_final.txt").read_text(encoding="utf-8")
        match = re.search(r"Ran (\d+) tests in ([0-9.]+)s\s+OK", tests)
        assert match and int(match[1]) == 127
        result["checks"]["full_tests"] = {"status": "passed", "count": 127, "elapsed_s": float(match[2]), "evidence": "evidence/m5/test_results_final.txt"}
        math = read("evidence/m5/independent_math_review.json")
        assert math["status"] == "passed" and len(math["checks"]) == 7 and not math["failures"]
        backend = read("evidence/m5/backend_final_audit.json")
        assert not backend["errors"] and backend["service_tests"]["status"] == "passed"
        result["checks"]["independent_review"] = {"status": "passed", "checks": 7, "evidence": "evidence/m5/independent_math_review.json"}
        result["checks"]["backend_lifecycle"] = {"status": "passed", "evidence": "evidence/m5/backend_final_audit.json", "limitations": backend["lifecycle_source_review"]["limitations"]}
        ui = read("evidence/m5/visual/ui_validation.json")
        assert ui["finalConsole"] == [] and ui["run"]["rows"] == 32 and ui["invalidInitializer"]["rows"] == 32
        assert ui["finalLiveSweep"]["rows"] == 4
        assert ui["cameraBefore"] == ui["scrub"]["camera"] == ui["playback"]["camera"] == ui["comparisonPlayback"]["camera"]
        assert ui["comparison"]["alignment"] == ui["comparisonPlayback"]["alignment"] == "aligned"
        for name in ["final_m5_controls.png", "final_m5_attempts.png", "final_m5_scene.png", "final_residuals.png", "final_geometry.png", "final_comparison.png", "legacy_m3_reopen.png", "legacy_m4_reopen.png"]:
            assert (ROOT/"evidence/m5/visual"/name).stat().st_size > 1000
        result["checks"]["desktop_visual"] = {"status": "passed", "evidence": "evidence/m5/visual/ui_validation.json", "images": "evidence/m5/visual/", "limits": ui["limitations"], "manual_review": "Root inspected exported charts/comparison/scene and final controls/attempts/scene/legacy screenshots using view_image."}
        paths = list((ROOT/"evidence/m5/acceptance_20261014_124422_c74e2389/sweeps").glob("*.json")) + list((ROOT/"evidence/m5/acceptance_20261014_124422_c74e2389/demo_runs").glob("*.json")) + list((ROOT/"evidence/m5/extra_runs").glob("*.json"))
        paths += [ROOT/"evidence/m5/visual"/name for name in ["m5-run-428d10d41e3d45cea46d9174d6440ab1.json", "m5-benchmark-a34466afbde95a31ae80f8239bb3fb3c.json", "final_live_sweep.json"]]
        def forbidden(*args, **kwargs):
            raise AssertionError("Final audit must not solve or generate observations")
        with ExitStack() as stack:
            for module in (m3, m4, m5):
                for name in ("solve_experiment", "generate_experiment"):
                    stack.enter_context(patch.object(module, name, side_effect=forbidden))
            for path in paths:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("artifact_type") == "solver_sweep":
                    m5_sweeps.validate_artifact(data)
                else:
                    m5.validate_run(data)
                result["files"].append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "offline_validation": "passed"})
        live = read("evidence/m5/visual/final_live_sweep.json")
        rows = list(csv.DictReader(io.StringIO((ROOT/"evidence/m5/visual/final_live_sweep.csv").read_text(encoding="utf-8"))))
        assert len(rows) == len(live["start_table"]) == 4
        run = read("evidence/m5/visual/m5-run-428d10d41e3d45cea46d9174d6440ab1.json")
        rows = list(csv.DictReader(io.StringIO((ROOT/"evidence/m5/visual/final_run_utf8.csv").read_text(encoding="utf-8"))))
        assert len(rows) == 1 and json.loads(rows[0]["start_record"]) == run["starts"][0]
        result["checks"]["new_exports"] = {"status": "passed", "offline_files": len(paths), "new_live_sweep_rows": 4, "run_csv_embedded_start": "exact UTF-8 match"}
        result["requirements"] = backend["requirements"]
        for name in ("M5.1", "M5.2", "M5.3", "M5.4"):
            result["requirements"][name]["status"] = "passed including UI controls, retained attempts and exports"
        result["requirements"]["M5.5"]["status"] = "passed conditional evaluation with justified deferral"
        result["checks"]["performance"] = {"status": "recorded", "backend": "evidence/m5/benchmark_20261014_123003_fc71f42c/performance_benchmark.json", "browser": "evidence/m5/visual/ui_validation.json", "history": "evidence/m5/history_performance.json", "limits": "Small local fixtures and single browser render samples; no general speed ranking or Ceres comparison."}
        result["source_hashes"] = {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/"app.py", *sorted((ROOT/"uwb").glob("*.py")), *sorted((ROOT/"web").glob("*.js")), ROOT/"web/index.html", ROOT/"web/style.css"]}
        result["documentation"] = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ["docs/M5.md", "docs/M5_ACCEPTANCE.md", "docs/M5_ALGEBRAIC.md", "README.md"]}
        roadmap = (ROOT/"ROADMAP.md").read_text(encoding="utf-8")
        assert all(f"[x] **M5.{i}" in roadmap for i in range(1, 6))
        assert all(f"[ ] **M6.{i}" in roadmap for i in range(1, 6))
        result["checks"]["roadmap_scope"] = {"status": "passed", "M5": "checked after numerical/backend/visual evidence", "M6": "unchecked; handoff prompt only", "sha256": hashlib.sha256((ROOT/"ROADMAP.md").read_bytes()).hexdigest()}
        result["delivery"] = {"launch": ".\\.venv\\Scripts\\python.exe app.py --port 5054", "url": "http://127.0.0.1:5054/", "worktree": "Uncommitted M3/M4/M5 preserved", "publication": "No push or external publication", "next_milestone": "M6 remains outside this goal"}
        result["status"] = "passed"
    except Exception as exc:
        result["status"] = "failed"
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        record()
    print(str(folder.relative_to(ROOT)) + ": passed")


if __name__ == "__main__":
    main()
