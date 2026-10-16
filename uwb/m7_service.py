"""Partial-survey requests and strict offline uncertainty/export endpoints."""
from __future__ import annotations

import copy
import json
import threading
import uuid
from pathlib import Path

from flask import jsonify, request, Response

from . import m6, m7
from .experiments import save_json
from .lifecycle import mark_import


def register_m7(app, directory, executor=None, jobs=None, lock=None, *, on_saved=None):
    """Register alongside existing routes; source JSON remains authoritative.

    If executor is absent requests execute synchronously (useful for embedding).
    Shared executor/jobs/lock give the existing /api/jobs lifecycle. on_saved is
    an optional metadata-cache notification called after each successful save.
    """
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    jobs = {} if jobs is None else jobs
    lock = threading.RLock() if lock is None else lock

    def path_for(identifier):
        if not isinstance(identifier, str) or len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier):
            raise ValueError("Invalid identifier")
        return directory / (identifier + ".json")

    def save(identifier, run):
        if run["schema_version"] == m7.SCHEMA_VERSION:
            m7.save_run(path_for(identifier), run)
        else:
            save_json(path_for(identifier), run)
        if on_saved is not None: on_saved(path_for(identifier))

    def read(identifier):
        with lock:
            active = jobs.get(identifier)
        if active and active.get("run"):
            run = copy.deepcopy(active["run"])
        else:
            path = path_for(identifier)
            if not path.is_file(): raise ValueError("Unknown run")
            run = json.loads(path.read_text(encoding="utf-8"))
        if run.get("schema_version") == m7.SCHEMA_VERSION:
            m7.validate_run(run)
        elif run.get("schema_version") == m6.SCHEMA_VERSION:
            m6.validate_run(run)
        else:
            raise ValueError("M7 endpoints support saved M6/M7 runs")
        if run["status"] in ("pending", "running") and active is None:
            run.update(status="interrupted", saved_status=run["status"], error="Saved request was interrupted; no internal optimizer state or automatic restart")
        return run

    def execute(identifier, experiment, options, initial, envelope):
        run = envelope
        try:
            run = m7.solve_experiment(experiment, options, initial)
            run["id"] = identifier
            save(identifier, run)
            with lock: jobs[identifier] = {"status": "complete", "run": run}
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if run.get("selected_start") is not None:
                run.update(infrastructure_status="failed", error=error)
            else:
                run.update(status="failed", error=error)
            try: save(identifier, run)
            except (OSError, ValueError) as storage_error: run["persistence_error"] = str(storage_error)
            with lock: jobs[identifier] = {"status": "failed", "run": run, "error": error}

    @app.post("/api/m7/runs")
    def submit_m7():
        body = request.get_json()
        if not isinstance(body, dict) or set(body) - {"config", "experiment", "options", "initial_geometries"}:
            raise ValueError("Expected config or saved experiment, options and optional initial_geometries")
        if "config" in body and "experiment" in body: raise ValueError("Choose config generation or saved experiment reuse")
        if not isinstance(body.get("options", {}), dict): raise ValueError("Expected options object")
        options = m7.validate_options(body.get("options"))
        if options["starts"] > 12 or options["max_nfev"] > 5000: raise ValueError("Application limits: 12 starts and 5000 evaluations")
        if "experiment" in body:
            experiment = copy.deepcopy(body["experiment"])
            m6.validate_experiment(experiment)
        else:
            if not isinstance(body.get("config", {}), dict): raise ValueError("Expected config object")
            experiment = m6.generate_experiment(body.get("config"))
        initial = body.get("initial_geometries")
        if initial is not None and (not isinstance(initial, list) or len(initial) != options["starts"]):
            raise ValueError("Supply one physical initial geometry per requested attempt")
        if "survey" in options: m7._problem(experiment, options)  # validate frame/count/constraint support before enqueue
        identifier = uuid.uuid4().hex
        envelope = {"schema_version": m7.SCHEMA_VERSION if "survey" in options else m6.SCHEMA_VERSION,
                    "id": identifier, "status": "running", "experiment": experiment, "options": options,
                    "starts": [], "selected_start": None, "diagnostics": {},
                    "requested_initial_geometries": copy.deepcopy(initial)}
        save(identifier, envelope)
        with lock: jobs[identifier] = {"status": "running"}
        if executor is None: execute(identifier, experiment, options, initial, envelope)
        else: executor.submit(execute, identifier, experiment, options, initial, envelope)
        return jsonify(id=identifier), 202

    @app.get("/api/m7/runs/<identifier>")
    def reopen_m7(identifier):
        return jsonify(read(identifier))

    @app.get("/api/m7/runs/<identifier>/uncertainty")
    def uncertainty_m7(identifier):
        index = request.args.get("start", type=int)
        return jsonify(m7.summarize_uncertainty(read(identifier), index))

    @app.get("/api/m7/runs/<identifier>/json")
    def json_m7(identifier):
        return Response(json.dumps(read(identifier), allow_nan=False, indent=2), mimetype="application/json")

    @app.get("/api/m7/runs/<identifier>/csv")
    def csv_m7(identifier):
        run = read(identifier)
        if run["schema_version"] != m7.SCHEMA_VERSION: raise ValueError("Use existing M6 CSV exporter for a legacy run")
        return Response(m7.table_csv(run), mimetype="text/csv")

    @app.post("/api/m7/import")
    def import_m7():
        data = copy.deepcopy(request.get_json())
        if not isinstance(data, dict) or data.get("schema_version") != m7.SCHEMA_VERSION:
            raise ValueError("M7 import requires a saved schema7.0 survey run")
        m7.validate_run(data)
        mark_import(data)
        if "id" in data:
            data.setdefault("source_id", data["id"])
        identifier = uuid.uuid4().hex; data["id"] = identifier
        save(identifier, data)
        return jsonify(id=identifier, run=data)

    return {"read_run": read, "save_run": save}


# Explicit alias matches the milestone service naming convention.
register_m7_routes = register_m7

