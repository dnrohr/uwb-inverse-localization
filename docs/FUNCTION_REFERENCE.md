# Function and HTTP reference

Generated from the current Python source by `scripts/build_user_docs.py`. The [user guide](USER_GUIDE.md) documents application features; [input reference](INPUT_REFERENCE.md) documents configuration variables. This appendix inventories every Python function, nested callback, method and HTTP decorator in `app.py` and `uwb/`, with exact source signatures. Leading-underscore functions and nested callbacks are implementation details, not stable user APIs. Follow source links for exact return structures and per-function validation.

## Python usage

```python
from uwb import m6

experiment = m6.generate_experiment({"noise_std_m": 0.02, "seed": 7})
run = m6.solve_experiment(experiment, {"loss": "huber", "starts": 2, "max_nfev": 500})
print(run["status"], run["selected_start"])
```

Generation returns an experiment; solving returns a run and does not itself save it. Use the native strict save/load helpers for persistence. Measurement-only `build_problem`/`fit_observations` deliberately receive no truth. Known-map coordinates and declared survey priors are explicit knowledge; solve wrappers separately evaluate against truth. Sweep calls perform fitting and may be expensive; validate settings first. Normalizers/validators may raise ValueError (including ExperimentFormatError); save/load can also raise filesystem errors.

## Shared argument vocabulary

Exact required/optional/keyword-only arguments and defaults are shown for each function below; `*` introduces keyword-only arguments. Repeated names have the following meaning; native option keys and all JSON configuration variables are in the input reference. `self` is the instance for a method.

| Argument | Meaning |
|---|---|
| `config` | Native physical generation settings, or native study settings in sweep modules; defaults and accepted fields are model-specific. |
| `options` | Native estimator/numerical options; workspace assumptions and numerical sections are merged before calling the native model. |
| `draft` | Complete version-1 workspace configuration object (see input reference). |
| `engine` | Explicit planar/timing/spatial/solver/robust/survey model key. |
| `experiment / exp` | Native experiment record: schema_version, normalized config, estimator_input, separate truth/reference and provenance. |
| `observations` | List of measured-range records with epoch, zero-based beacon_id, range_m, sigma_m and assumed_time_s; actual/delivery fields are retained provenance. |
| `times_s` | Strictly increasing finite estimator epoch/cycle times in seconds. Interpolation is constructed from these times and options. |
| `display_times_s` | Optional display/evaluation sampling times in seconds; separate from acquisition events and fitted knots. |
| `surveyed_beacons` | Explicit finite beacon-count × 3 map in metres for known-map mode; forbidden as hidden knowledge in joint fitting. |
| `beacon_count` | Explicit integer count, generally 3–8; required where missing observations prevent inferring the physical map size. |
| `initial_geometries` | Optional list of retained physical trajectory/beacon starts, one per configured attempt; subject to compatibility validation. |
| `parameters / x / x0 / u` | Parameter/start vectors in the function’s model coordinates; u denotes unconstrained LM coordinates. |
| `problem` | Validated RangeProblem/TrajectoryProblem/HeightProblem/SolverProblem, containing model-specific packing, interpolation, weights and constraints. |
| `mask` | Optional retained-observation Boolean mask for rejection; rows removed by acquisition/dropout are absent before this mask. |
| `augmented` | If true, include supported prior rows when inspecting local Jacobian rank. |
| `estimate / truth` | Physical trajectory/beacon geometry dictionaries for evaluation; truth is kept outside measurement-only fitting. |
| `run / left_run / right_run` | Complete validated saved-run records, including experiment, options and all attempts. |
| `artifact / sweep / data` | Native saved payload appropriate to the module; use strict native loaders/validators before inspection. |
| `alignment` | raw or aligned rigid comparison; scale remains 1. |
| `path` | Filesystem path to the native JSON destination/source; save operations create or replace files. |
| `on_progress` | Optional callable receiving the latest study artifact after a completed entry for checkpointing. |
| `fit_callback` | Optional alternate fitting callable used by the spatial evaluation wrapper; receives its measurement-only fit inputs. |
| `survey` | Explicit world/metre declaration with fixed/prior selected-coordinate blocks; see survey input reference. |
| `assumptions` | Optional uncertainty override object, not replacement measurement sigmas. |
| `start_index` | Zero-based saved attempt ordinal; None uses the run’s selected_start. |
| `converged` | Whether the inspected attempt converged; nonconvergence withholds conditional intervals. |
| `rtol / rank_rtol` | Relative singular-value tolerance used for local rank classification. |
| `lower / upper` | Coordinate bound arrays, with infinities for unbounded sides; LM rejects two-sided finite bounds. |
| `loss / scale / residual_sigma` | Robust loss key, positive scale in sigma units, and standardized range residual vector. |
| `app / directory / artifacts` | Flask application and local run/artifact storage directories for route registration. |
| `executor / jobs / lock / job_lock` | Shared background executor, job-state dictionary and synchronization locks. |
| `library / cache_path` | LibraryIndex used for authoritative source resolution, or optional disposable SQLite cache path. |
| `bundled_root / on_saved` | Optional reference-evidence directory or callback to invalidate saved-history metadata after writing. |
| `**options` | Model-specific native options expanded as keywords; accepted fields are in the input reference and exact normalized defaults. |
| `**params` | Library metadata query: q, type, status, model, source, sort, page, page_size, view and parent; see Library controls in the input reference. |
| `mode / initialization / starts / seed / max_nfev` | Native estimator controls with the same meanings as workspace assumptions/numerical fields; exact low-level defaults appear in the signature. |
| `timing_model / knot_spacing_s / prior_sigma_m` | Timing approximation, trajectory resolution in seconds and motion-prior SD in metres; equivalent workspace assumptions are documented in the input reference. |
| `cfg / opts / normalized` | Already normalized native generation settings, estimator options or workspace settings; obtain them with the matching normalizer. |
| `trajectory / beacons / points / initial` | Finite physical XYZ trajectory, beacon or point-cloud arrays in metres; initial is a retained starting geometry or model vector according to its caller. |
| `matrix / n / count` | Numerical matrix and parameter/row/point count required by the local linear-algebra helper. |
| `basis / tag_entries / beacon_entries` | Coordinate basis arrays and parameter-entry mappings used to propagate local uncertainty to physical geometry. |
| `identifier / ids / key` | Server-owned source/job identifier, ID collection, or exact authoritative Library key; do not substitute filesystem paths. |
| `decisions / records` | Fitted per-range weight/rejection decisions and separate injected contamination reference records for evaluation. |
| `project` | Allow supported projection of supplied physical geometry into the feasible model before packing; false validates it as supplied. |
| `schema / kind / envelope` | Native schema version, artifact kind and saved envelope used by lifecycle/import validation. |
| `normalize_config / validate_artifact` | Native normalization/strict-validation callables supplied to generic lifecycle validation. |
| `value` | Configuration subobject, numeric value or JSON node under normalization; function purpose identifies its expected shape. |
| `_validate` | Internal comparison validation switch; keep the default true when calling outside already validated internal paths. |

## app.py

| Function / exact signature | Purpose |
|---|---|
| [`create_app`](../app.py#L20) — `create_app(run_dir=None)` | Create the local Flask application and register native/workspace/Library routes; run_dir selects the saved-history directory. |
| [`create_app.index`](../app.py#L41) — `create_app.index()` | Internal callback or route handler: index. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.plotly_bundle`](../app.py#L45) — `create_app.plotly_bundle()` | Internal callback or route handler: plotly bundle. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.scenarios`](../app.py#L49) — `create_app.scenarios()` | Internal callback or route handler: scenarios. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.path_for`](../app.py#L52) — `create_app.path_for(identifier)` | Internal callback or route handler: path for. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.artifact_path`](../app.py#L57) — `create_app.artifact_path(identifier)` | Internal callback or route handler: artifact path. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.save_pending`](../app.py#L61) — `create_app.save_pending(path, data)` | Internal callback or route handler: save pending. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.retain_sweep_runs`](../app.py#L66) — `create_app.retain_sweep_runs(data)` | Internal callback or route handler: retain sweep runs. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.execute_sweep`](../app.py#L99) — `create_app.execute_sweep(identifier, config)` | Internal callback or route handler: execute sweep. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.execute_sweep.checkpoint`](../app.py#L102) — `create_app.execute_sweep.checkpoint(data)` | Internal callback or route handler: checkpoint. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.submit_sweep`](../app.py#L137) — `create_app.submit_sweep()` | Internal callback or route handler: submit sweep. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.execute_m3`](../app.py#L151) — `create_app.execute_m3(identifier, experiment, options)` | Internal callback or route handler: execute m3. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.submit_m3`](../app.py#L194) — `create_app.submit_m3()` | Internal callback or route handler: submit m3. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.execute_m3_sweep`](../app.py#L212) — `create_app.execute_m3_sweep(identifier, config)` | Internal callback or route handler: execute m3 sweep. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.execute_m3_sweep.checkpoint`](../app.py#L216) — `create_app.execute_m3_sweep.checkpoint(data)` | Internal callback or route handler: checkpoint. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.submit_m3_sweep`](../app.py#L240) — `create_app.submit_m3_sweep()` | Internal callback or route handler: submit m3 sweep. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.list_m3_sweeps`](../app.py#L257) — `create_app.list_m3_sweeps()` | Internal callback or route handler: list m3 sweeps. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.reopen_m3_sweep`](../app.py#L273) — `create_app.reopen_m3_sweep(identifier)` | Internal callback or route handler: reopen m3 sweep. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.m3_csv`](../app.py#L303) — `create_app.m3_csv(identifier)` | Internal callback or route handler: m3 csv. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.import_m3`](../app.py#L308) — `create_app.import_m3()` | Internal callback or route handler: import m3. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.compare_saved`](../app.py#L325) — `create_app.compare_saved()` | Internal callback or route handler: compare saved. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.list_artifacts`](../app.py#L342) — `create_app.list_artifacts()` | Internal callback or route handler: list artifacts. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.reopen_artifact`](../app.py#L361) — `create_app.reopen_artifact(identifier)` | Internal callback or route handler: reopen artifact. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.reopen_artifact.disclose_interruption`](../app.py#L370) — `create_app.reopen_artifact.disclose_interruption(data)` | Internal callback or route handler: disclose interruption. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.import_artifact`](../app.py#L390) — `create_app.import_artifact()` | Internal callback or route handler: import artifact. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.execute`](../app.py#L402) — `create_app.execute(identifier, experiment, options)` | Internal callback or route handler: execute. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.submit`](../app.py#L419) — `create_app.submit()` | Internal callback or route handler: submit. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.job`](../app.py#L457) — `create_app.job(identifier)` | Internal callback or route handler: job. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.list_runs`](../app.py#L468) — `create_app.list_runs()` | Internal callback or route handler: list runs. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.reopen`](../app.py#L501) — `create_app.reopen(identifier)` | Internal callback or route handler: reopen. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.import_run`](../app.py#L519) — `create_app.import_run()` | Internal callback or route handler: import run. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.bad_request`](../app.py#L534) — `create_app.bad_request(exc)` | Internal callback or route handler: bad request. See its enclosing function and the HTTP route table for request/return context. |
| [`create_app.compare_library_sources`](../app.py#L550) — `create_app.compare_library_sources()` | Internal callback or route handler: compare library sources. See its enclosing function and the HTTP route table for request/return context. |

## uwb/estimation.py

| Function / exact signature | Purpose |
|---|---|
| [`RangeProblem.parameter_count`](../uwb/estimation.py#L30) — `RangeProblem.parameter_count(self)` | Return the number of free coordinates under the selected map/trajectory parameterization. |
| [`RangeProblem.unpack`](../uwb/estimation.py#L33) — `RangeProblem.unpack(self, parameters)` | Convert a model parameter vector into physical trajectory and beacon XYZ arrays. |
| [`RangeProblem.pack`](../uwb/estimation.py#L43) — `RangeProblem.pack(self, trajectory, beacons)` | Convert physical trajectory and beacon XYZ arrays into the problem coordinate vector, checking constraints; project permits supported feasibility projection. |
| [`build_problem`](../uwb/estimation.py#L62) — `build_problem(observations, times_s, *, mode='joint', surveyed_beacons=None)` | Build the model parameterization, interpolation, constraints and weighted measurement/prior inputs from observations and times. Truth is not an input. |
| [`residuals`](../uwb/estimation.py#L98) — `residuals(parameters, problem)` | Return the model objective residual vector; range terms use predicted minus measured range normalized by saved sigma, with applicable priors/transforms. |
| [`jacobian`](../uwb/estimation.py#L104) — `jacobian(parameters, problem)` | Return the analytic objective Jacobian including supported prior/robust/survey terms. |
| [`_linear_positions`](../uwb/estimation.py#L124) — `_linear_positions(problem, beacons)` | Known-map squared differences supply a seed, never the fitted objective. |
| [`_independent_initial`](../uwb/estimation.py#L134) — `_independent_initial(problem, rng, index)` | Internal independent initial helper. Uses `_linear_positions`, `beacons.tolist`, `float`, `len`, `max` among other calls. |
| [`jacobian_diagnostics`](../uwb/estimation.py#L151) — `jacobian_diagnostics(parameters, problem)` | Compute local singular values, rank and conditioning; augmented selects measurement-plus-prior information where supported. |
| [`fit_observations`](../uwb/estimation.py#L165) — `fit_observations(observations, times_s, *, mode='joint', surveyed_beacons=None, starts=3, seed=19, initial_geometries=None, max_nfev=2000)` | Fit measurement inputs with explicit options/optional declared survey and physical starts; return every attempt and its solver/diagnostic evidence. |
| [`_error_summary`](../uwb/estimation.py#L221) — `_error_summary(trajectory, beacons, truth_trajectory, truth_beacons)` | Internal error summary helper. Uses `float`, `map_error.tolist`, `np.linalg.norm`, `np.max`, `np.mean` among other calls. |
| [`evaluate_geometry`](../uwb/estimation.py#L229) — `evaluate_geometry(estimate, truth, mode)` | Compare fitted trajectory/beacons against separate truth in disclosed raw/rigid evaluation frames; preserve physical scale. |
| [`solve_experiment`](../uwb/estimation.py#L252) — `solve_experiment(experiment, options=None)` | Validate a native experiment, run its estimator, evaluate against separate synthetic truth, and return the complete saved-run structure. |

## uwb/experiments.py

| Function / exact signature | Purpose |
|---|---|
| [`_std_vector`](../uwb/experiments.py#L43) — `_std_vector(value: Any, name: str, *, allow_zero: bool) -> list[float]` | Internal std vector helper. Uses `ValueError`, `all`, `float`, `isinstance`, `len` among other calls. |
| [`_normalise_config`](../uwb/experiments.py#L57) — `_normalise_config(config: Mapping[str, Any] &#124; None) -> dict[str, Any]` | Internal normalise config helper. Uses `', '.join`, `ValueError`, `_bounded_number`, `_normalise_path`, `_std_vector` among other calls. |
| [`_bounded_number`](../uwb/experiments.py#L92) — `_bounded_number(value: Any, name: str, lower: float, upper: float) -> float` | Internal bounded number helper. Uses `ValueError`, `float`, `isinstance`, `math.isfinite`. |
| [`_pair`](../uwb/experiments.py#L101) — `_pair(value: Any, name: str, lower: float, upper: float) -> list[float]` | Internal pair helper. Uses `ValueError`, `_bounded_number`, `isinstance`, `len`. |
| [`_normalise_path`](../uwb/experiments.py#L107) — `_normalise_path(value: Any) -> dict[str, Any]` | Internal normalise path helper. Uses `', '.join`, `ValueError`, `_bounded_number`, `_pair`, `abs` among other calls. |
| [`_custom_path`](../uwb/experiments.py#L150) — `_custom_path(spec: Mapping[str, Any], count: int) -> tuple[np.ndarray, float]` | Return planar samples and traveled length, including closed-loop endpoint. size_m is full width/height; circle/arc use width as their diameter. Waypoints are local xy offsets before scale, rotation, and translation. Figure-eight arclength uses a fixed 16,385-point polyline approximation. |
| [`path_metadata`](../uwb/experiments.py#L188) — `path_metadata(config: Mapping[str, Any] &#124; None=None) -> dict[str, Any]` | Return path type, traveled arclength, speed and interpolation/approximation disclosures from config. |
| [`_informative_path`](../uwb/experiments.py#L214) — `_informative_path(count: int) -> np.ndarray` | Sample a spatially broad rectangle-like waypoint loop at constant speed. |
| [`_sample_polyline_at_constant_speed`](../uwb/experiments.py#L229) — `_sample_polyline_at_constant_speed(points: np.ndarray, count: int) -> np.ndarray` | Sample a piecewise-linear path evenly by traveled distance. |
| [`_trajectory`](../uwb/experiments.py#L241) — `_trajectory(scenario: str, count: int) -> np.ndarray` | Internal trajectory helper. Uses `AssertionError`, `_informative_path`, `_sample_polyline_at_constant_speed`, `max`, `np.column_stack` among other calls. |
| [`_beacons`](../uwb/experiments.py#L258) — `_beacons(scenario: str) -> np.ndarray` | Internal beacons helper. Uses `BEACON_MAP.copy`, `np.array`. |
| [`_package_versions`](../uwb/experiments.py#L267) — `_package_versions() -> dict[str, str &#124; None]` | Internal package versions helper. Uses `metadata.version`, `package.lower`, `platform.python_version`. |
| [`generate_experiment`](../uwb/experiments.py#L277) — `generate_experiment(config: Mapping[str, Any] &#124; None=None) -> dict[str, Any]` | Normalize generation settings and return a native synthetic experiment with separate estimator_input and truth/reference records; no fit. |
| [`_reject_constant`](../uwb/experiments.py#L323) — `_reject_constant(token: str) -> None` | Internal reject constant helper. Uses `ExperimentFormatError`. |
| [`_validate_experiment`](../uwb/experiments.py#L327) — `_validate_experiment(data: Any) -> None` | Internal validate experiment helper. Uses `ExperimentFormatError`, `_normalise_config`, `all`, `any`, `enumerate` among other calls. |
| [`_validate_json_values`](../uwb/experiments.py#L383) — `_validate_json_values(value: Any, location: str='$') -> None` | Reject values that JSON cannot represent strictly and portably. |
| [`_validate_payload`](../uwb/experiments.py#L404) — `_validate_payload(data: Any) -> None` | Accept either a standalone experiment or a saved run containing one. Run envelopes intentionally allow additional result and diagnostic fields; persistence must retain failed runs (including an empty ``starts`` list and an ``error`` message) so they can be inspected later. |
| [`_replace_with_retry`](../uwb/experiments.py#L484) — `_replace_with_retry(temporary: Path, target: Path) -> None` | Retry atomic replacement when a Windows reader briefly denies deletion. |
| [`save_json`](../uwb/experiments.py#L496) — `save_json(path: str &#124; Path, data: dict[str, Any]) -> None` | Validate finite native JSON and save through temporary-file replacement; path is the destination. |
| [`load_json`](../uwb/experiments.py#L507) — `load_json(path: str &#124; Path) -> dict[str, Any]` | Read strict native JSON from path and validate its payload; malformed/nonfinite/unsupported records fail. |

## uwb/library.py

| Function / exact signature | Purpose |
|---|---|
| [`_dict`](../uwb/library.py#L24) — `_dict(value)` | Internal dict helper. Uses `isinstance`. |
| [`_reject_constant`](../uwb/library.py#L28) — `_reject_constant(value)` | Internal reject constant helper. Uses `ValueError`. |
| [`_digest`](../uwb/library.py#L32) — `_digest(value)` | Internal digest helper. Uses `hashlib.sha256`, `hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest`, `json.dumps`, `json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode`. |
| [`_message`](../uwb/library.py#L39) — `_message(value)` | Internal message helper. Uses `str`. |
| [`_urls`](../uwb/library.py#L43) — `_urls(kind, identifier, schema, artifact_type)` | Internal urls helper. Uses `any`, `len`, `{'timing_sweep': '/api/m3/sweeps/', 'geometry_sweep': '/api/m4/sweeps/', 'solver_sweep': '/api/m5/sweeps/', 'robust_sweep': '/api/m6/sweeps/'}.get`. |
| [`_summary`](../uwb/library.py#L57) — `_summary(data, key, identifier, stamp, source_path)` | Internal summary helper. Uses `' · '.join`, `' ↔ '.join`, `', '.join`, `Counter`, `ValueError` among other calls. |
| [`LibraryIndex.__init__`](../uwb/library.py#L183) — `LibraryIndex.__init__(self, directory, *, cache_path=None, jobs=None, job_lock=None)` | Internal init helper. Uses `Path`, `RLock`. |
| [`LibraryIndex._connect`](../uwb/library.py#L192) — `LibraryIndex._connect(self)` | Internal connect helper. Uses `connection.close`, `connection.execute`, `connection.execute('PRAGMA quick_check').fetchone`, `connection.execute('PRAGMA user_version').fetchone`, `connection.executescript` among other calls. |
| [`LibraryIndex._recover_connection`](../uwb/library.py#L227) — `LibraryIndex._recover_connection(self)` | Internal recover connection helper. Uses `self._connect`, `self.cache_path.exists`, `self.cache_path.replace`, `self.cache_path.with_name`, `str` among other calls. |
| [`LibraryIndex._inventory`](../uwb/library.py#L237) — `LibraryIndex._inventory(self)` | Internal inventory helper. Uses `entry.is_file`, `entry.name.endswith`, `entry.stat`, `folder.exists`, `os.scandir`. |
| [`LibraryIndex._insert_file`](../uwb/library.py#L252) — `LibraryIndex._insert_file(self, db, relative, stamp)` | Internal insert file helper. Uses `(self.directory / relative).open`, `Path`, `ValueError`, `_dict`, `_summary` among other calls. |
| [`LibraryIndex._insert_item`](../uwb/library.py#L307) — `LibraryIndex._insert_item(self, db, summary, relative, stamp)` | Internal insert item helper. Uses `' '.join`, `db.execute`, `json.dumps`, `searchable.casefold`, `str` among other calls. |
| [`LibraryIndex._refresh`](../uwb/library.py#L314) — `LibraryIndex._refresh(self, db)` | Internal refresh helper. Uses `cached.get`, `datetime.now`, `datetime.now(timezone.utc).isoformat`, `db.execute`, `enumerate` among other calls. |
| [`LibraryIndex.rebuild`](../uwb/library.py#L338) — `LibraryIndex.rebuild(self)` | Rebuild the disposable Library cache from retained JSON; does not modify scientific source records. |
| [`LibraryIndex._active_ids`](../uwb/library.py#L349) — `LibraryIndex._active_ids(self)` | Internal active ids helper. Uses `self.jobs.items`, `v.get`. |
| [`LibraryIndex._decorate`](../uwb/library.py#L357) — `LibraryIndex._decorate(self, db, summary)` | Internal decorate helper. Uses `db.execute`, `self._active_ids`, `summary.get`, `summary.get('parent_key', '').removeprefix`. |
| [`LibraryIndex.query`](../uwb/library.py#L369) — `LibraryIndex.query(self, **params)` | Return bounded filtered/sorted/paginated metadata and facets; does not open strict scientific records or fit. |
| [`LibraryIndex._query_children`](../uwb/library.py#L441) — `LibraryIndex._query_children(self, db, parent, params, page, page_size)` | Internal query children helper. Uses `' AND '.join`, `clauses.append`, `db.execute`, `db.execute('SELECT COUNT(*) FROM children WHERE ' + where, values).fetchone`, `db.execute('SELECT COUNT(*) FROM children WHERE parent=?', (parent,)).fetchone` among other calls. |
| [`LibraryIndex._overall_total`](../uwb/library.py#L476) — `LibraryIndex._overall_total(db)` | Internal overall total helper. Uses `db.execute`, `db.execute("SELECT COUNT(*) FROM items WHERE NOT (instr(key, ':entry:')>0 AND EXISTS (SELECT 1 FROM items r WHERE r.key='run:' &#124;&#124; items.id))").fetchone`. |
| [`LibraryIndex.preview`](../uwb/library.py#L479) — `LibraryIndex.preview(self, key)` | Return indexed metadata/provenance for an exact Library key, or None if unknown. |
| [`register_library`](../uwb/library.py#L494) — `register_library(app, directory, *, jobs=None, job_lock=None)` | Register metadata query, preview, status and rebuild routes; return the LibraryIndex. |
| [`register_library.library_page`](../uwb/library.py#L500) — `register_library.library_page()` | Internal callback or route handler: library page. See its enclosing function and the HTTP route table for request/return context. |
| [`register_library.library_status`](../uwb/library.py#L509) — `register_library.library_status()` | Internal callback or route handler: library status. See its enclosing function and the HTTP route table for request/return context. |
| [`register_library.rebuild_library`](../uwb/library.py#L513) — `register_library.rebuild_library()` | Internal callback or route handler: rebuild library. See its enclosing function and the HTTP route table for request/return context. |
| [`register_library.library_preview`](../uwb/library.py#L521) — `register_library.library_preview(key)` | Internal callback or route handler: library preview. See its enclosing function and the HTTP route table for request/return context. |

## uwb/lifecycle.py

| Function / exact signature | Purpose |
|---|---|
| [`mark_import`](../uwb/lifecycle.py#L5) — `mark_import(data)` | Mark imported unfinished work conservatively; do not resume a job or alter retained optimizer outcomes. |
| [`validate_empty_sweep`](../uwb/lifecycle.py#L21) — `validate_empty_sweep(data, schema, kind, normalize_config, validate_artifact)` | Validate imported empty/incomplete sweep envelopes through the supplied native normalization and artifact validators. |

## uwb/m3.py

| Function / exact signature | Purpose |
|---|---|
| [`_format_errors`](../uwb/m3.py#L29) — `_format_errors(function)` | Internal format errors helper. Uses `ValueError`, `function`, `wraps`. |
| [`_format_errors.wrapped`](../uwb/m3.py#L31) — `_format_errors.wrapped(*args, **kwargs)` | Internal callback or route handler: wrapped. See its enclosing function and the HTTP route table for request/return context. |
| [`_number`](../uwb/m3.py#L39) — `_number(value, name, lower=0.0, upper=math.inf)` | Internal number helper. Uses `ValueError`, `float`, `isinstance`, `math.isfinite`. |
| [`normalize_config`](../uwb/m3.py#L49) — `normalize_config(config=None)` | Validate and fill native generation defaults; return normalized config, raising ValueError for unsupported or invalid fields. |
| [`validate_options`](../uwb/m3.py#L93) — `validate_options(options=None)` | Validate and fill native estimator/numerical defaults; return normalized options without generating data or fitting. |
| [`_path`](../uwb/m3.py#L114) — `_path(cfg, fraction)` | Continuous arclength path; open/closed paths stop at their endpoints. |
| [`_progress`](../uwb/m3.py#L150) — `_progress(cfg, times)` | Internal progress helper. Uses `clipped.copy`, `len`, `max`, `np.asarray`, `np.clip` among other calls. |
| [`truth_positions`](../uwb/m3.py#L176) — `truth_positions(config, times_s)` | Evaluate the synthetic trajectory at requested times for generation/evaluation; do not supply this output to independent fitting. |
| [`generate_experiment`](../uwb/m3.py#L181) — `generate_experiment(config=None)` | Normalize generation settings and return a native synthetic experiment with separate estimator_input and truth/reference records; no fit. |
| [`_array`](../uwb/m3.py#L235) — `_array(value, shape, name)` | Internal array helper. Uses `ValueError`, `np.all`, `np.asarray`, `np.isfinite`. |
| [`validate_experiment`](../uwb/m3.py#L243) — `validate_experiment(experiment)` | Strictly validate the native experiment representation, shapes and generation consistency; return the accepted experiment or raise ValueError. |
| [`_validate_observations`](../uwb/m3.py#L282) — `_validate_observations(observations, times)` | Internal validate observations helper. Uses `ValueError`, `_number`, `isinstance`, `len`, `np.finfo` among other calls. |
| [`_weights`](../uwb/m3.py#L295) — `_weights(knots, times)` | Internal weights helper. Uses `ValueError`, `len`, `np.any`, `np.arange`, `np.asarray` among other calls. |
| [`TrajectoryProblem.geometry`](../uwb/m3.py#L316) — `TrajectoryProblem.geometry(self, parameters)` | Evaluate physical trajectory and beacon geometry represented by a parameter vector. |
| [`build_problem`](../uwb/m3.py#L324) — `build_problem(observations, times_s, *, mode='joint', surveyed_beacons=None, timing_model='timestamp_aware', knot_spacing_s=0.0, prior_sigma_m=0.0, display_times_s=None)` | Build the model parameterization, interpolation, constraints and weighted measurement/prior inputs from observations and times. Truth is not an input. |
| [`measurement_residuals`](../uwb/m3.py#L364) — `measurement_residuals(parameters, problem)` | Return standardized range residuals only, excluding priors. |
| [`prior_residuals`](../uwb/m3.py#L370) — `prior_residuals(parameters, problem)` | Return motion prior residual rows separately from measurements. |
| [`residuals`](../uwb/m3.py#L375) — `residuals(parameters, problem)` | Return the model objective residual vector; range terms use predicted minus measured range normalized by saved sigma, with applicable priors/transforms. |
| [`measurement_jacobian`](../uwb/m3.py#L379) — `measurement_jacobian(parameters, problem)` | Return the analytic Jacobian of measurement residuals in this model coordinate system. |
| [`jacobian`](../uwb/m3.py#L397) — `jacobian(parameters, problem)` | Return the analytic objective Jacobian including supported prior/robust/survey terms. |
| [`jacobian_diagnostics`](../uwb/m3.py#L404) — `jacobian_diagnostics(parameters, problem, *, augmented=False)` | Compute local singular values, rank and conditioning; augmented selects measurement-plus-prior information where supported. |
| [`_initial`](../uwb/m3.py#L419) — `_initial(problem, rng, index)` | M1-compatible rectangular map and squared-difference position seed. |
| [`compatible_initial_geometries`](../uwb/m3.py#L447) — `compatible_initial_geometries(run, experiment, options=None)` | Validate and adapt retained physical starts for a compatible target experiment/model; reject unsupported pairing. |
| [`fit_observations`](../uwb/m3.py#L468) — `fit_observations(observations, times_s, *, display_times_s=None, surveyed_beacons=None, initial_geometries=None, **options)` | Fit measurement inputs with explicit options/optional declared survey and physical starts; return every attempt and its solver/diagnostic evidence. |
| [`solve_experiment`](../uwb/m3.py#L517) — `solve_experiment(experiment, options=None, *, initial_geometries=None)` | Validate a native experiment, run its estimator, evaluate against separate synthetic truth, and return the complete saved-run structure. |
| [`validate_run`](../uwb/m3.py#L607) — `validate_run(run)` | Strictly validate a saved native run and retained numerical/diagnostic consistency without rerunning optimization. |

## uwb/m3_sweeps.py

| Function / exact signature | Purpose |
|---|---|
| [`_cell`](../uwb/m3_sweeps.py#L24) — `_cell(config, value, seed)` | Internal cell helper. Uses `copy.deepcopy`, `experiment.setdefault`, `m3.normalize_config`, `m3.validate_options`. |
| [`validate_sweep_config`](../uwb/m3_sweeps.py#L39) — `validate_sweep_config(config=None)` | Normalize a bounded native single-factor study; validate factors, values, seeds, variants, pairing restrictions and workload before fitting. |
| [`_failed_run`](../uwb/m3_sweeps.py#L70) — `_failed_run(experiment, options, error, initials=None)` | Internal failed run helper. Uses `copy.deepcopy`, `experiment.get`, `range`, `type`. |
| [`run_sweep`](../uwb/m3_sweeps.py#L80) — `run_sweep(config=None, on_progress=None)` | Execute paired value/seed/variant cells; retain every outcome, aggregate evidence and invoke optional on_progress checkpoints. |
| [`_distribution`](../uwb/m3_sweeps.py#L111) — `_distribution(values)` | Internal distribution helper. Uses `float`, `len`, `math.isfinite`, `max`, `min` among other calls. |
| [`aggregate_sweep`](../uwb/m3_sweeps.py#L118) — `aggregate_sweep(artifact)` | Compute distributions, success/failure accounting and all-attempt study summaries from retained entries. |
| [`validate_artifact`](../uwb/m3_sweeps.py#L179) — `validate_artifact(data)` | Strictly validate saved native study/comparison structure, retained children and derived evidence without fitting. |
| [`save_artifact`](../uwb/m3_sweeps.py#L224) — `save_artifact(path, data)` | Validate and write a complete study/comparison artifact through temporary-file replacement. |
| [`load_artifact`](../uwb/m3_sweeps.py#L233) — `load_artifact(path)` | Load finite native study/comparison JSON and strictly validate it. |
| [`table_csv`](../uwb/m3_sweeps.py#L242) — `table_csv(artifact)` | Return native CSV text containing this module’s saved run, attempt, study or comparison table; per-observation study exports use their separate service route. |

## uwb/m4.py

| Function / exact signature | Purpose |
|---|---|
| [`_vector`](../uwb/m4.py#L25) — `_vector(value, count, name, positive=False)` | Internal vector helper. Uses `ValueError`, `isinstance`, `len`, `m3._number`. |
| [`normalize_config`](../uwb/m4.py#L34) — `normalize_config(config=None)` | Validate and fill native generation defaults; return normalized config, raising ValueError for unsupported or invalid fields. |
| [`validate_options`](../uwb/m4.py#L78) — `validate_options(options=None)` | Validate and fill native estimator/numerical defaults; return normalized options without generating data or fitting. |
| [`_proxy_config`](../uwb/m4.py#L98) — `_proxy_config(cfg)` | Internal proxy config helper. Uses `cfg.items`, `copy.deepcopy`. |
| [`beacon_coordinates`](../uwb/m4.py#L105) — `beacon_coordinates(cfg)` | Return generated or explicitly configured beacon XYZ coordinates from normalized physical config. |
| [`truth_positions`](../uwb/m4.py#L121) — `truth_positions(cfg, times_s)` | Evaluate the synthetic trajectory at requested times for generation/evaluation; do not supply this output to independent fitting. |
| [`generate_experiment`](../uwb/m4.py#L137) — `generate_experiment(config=None)` | Normalize generation settings and return a native synthetic experiment with separate estimator_input and truth/reference records; no fit. |
| [`_observations`](../uwb/m4.py#L174) — `_observations(observations, times, count)` | Internal observations helper. Uses `ValueError`, `isinstance`, `len`, `m3._number`, `seen.add` among other calls. |
| [`validate_experiment`](../uwb/m4.py#L188) — `validate_experiment(exp)` | Strictly validate the native experiment representation, shapes and generation consistency; return the accepted experiment or raise ValueError. |
| [`_spatial`](../uwb/m4.py#L225) — `_spatial(opts)` | Internal spatial helper. Uses . |
| [`_canonical`](../uwb/m4.py#L229) — `_canonical(trajectory, beacons, opts)` | Internal canonical helper. Uses `(-origin @ rotation).tolist`, `ValueError`, `_spatial`, `b[0].copy`, `np.asarray` among other calls. |
| [`gauge_metadata`](../uwb/m4.py#L256) — `gauge_metadata(opts)` | Describe the coordinate gauge and physical height constraints implied by estimator options. |
| [`HeightProblem.parameter_count`](../uwb/m4.py#L290) — `HeightProblem.parameter_count(self)` | Return the number of free coordinates under the selected map/trajectory parameterization. |
| [`HeightProblem.beacon_count`](../uwb/m4.py#L294) — `HeightProblem.beacon_count(self)` | Internal callback or route handler: beacon count. See its enclosing function and the HTTP route table for request/return context. |
| [`HeightProblem.unpack`](../uwb/m4.py#L297) — `HeightProblem.unpack(self, parameters)` | Convert a model parameter vector into physical trajectory and beacon XYZ arrays. |
| [`HeightProblem.pack`](../uwb/m4.py#L301) — `HeightProblem.pack(self, trajectory, beacons, *, project=False)` | Convert physical trajectory and beacon XYZ arrays into the problem coordinate vector, checking constraints; project permits supported feasibility projection. |
| [`HeightProblem.geometry`](../uwb/m4.py#L316) — `HeightProblem.geometry(self, parameters)` | Evaluate physical trajectory and beacon geometry represented by a parameter vector. |
| [`build_problem`](../uwb/m4.py#L324) — `build_problem(observations, times_s, *, beacon_count=None, display_times_s=None, surveyed_beacons=None, **options)` | Build the model parameterization, interpolation, constraints and weighted measurement/prior inputs from observations and times. Truth is not an input. |
| [`build_problem.column`](../uwb/m4.py#L353) — `build_problem.column(tag_entries=(), beacon_entries=(), lower=-np.inf, upper=np.inf)` | Internal callback or route handler: column. See its enclosing function and the HTTP route table for request/return context. |
| [`measurement_residuals`](../uwb/m4.py#L399) — `measurement_residuals(parameters, problem)` | Return standardized range residuals only, excluding priors. |
| [`prior_components`](../uwb/m4.py#L404) — `prior_components(parameters, problem)` | Return separately named motion and height prior residual vectors. |
| [`residuals`](../uwb/m4.py#L411) — `residuals(parameters, problem)` | Return the model objective residual vector; range terms use predicted minus measured range normalized by saved sigma, with applicable priors/transforms. |
| [`measurement_jacobian`](../uwb/m4.py#L416) — `measurement_jacobian(parameters, problem)` | Return the analytic Jacobian of measurement residuals in this model coordinate system. |
| [`jacobian`](../uwb/m4.py#L424) — `jacobian(parameters, problem)` | Return the analytic objective Jacobian including supported prior/robust/survey terms. |
| [`jacobian_diagnostics`](../uwb/m4.py#L430) — `jacobian_diagnostics(parameters, problem, *, augmented=False)` | Compute local singular values, rank and conditioning; augmented selects measurement-plus-prior information where supported. |
| [`_project_geometry`](../uwb/m4.py#L443) — `_project_geometry(problem, p, b)` | Internal project geometry helper. Uses `_canonical`, `problem.geometry`, `problem.pack`. |
| [`_initial`](../uwb/m4.py#L448) — `_initial(problem, rng, index)` | Internal initial helper. Uses `_project_geometry`, `_spatial`, `float`, `len`, `max` among other calls. |
| [`fit_observations`](../uwb/m4.py#L484) — `fit_observations(observations, times_s, *, beacon_count=None, display_times_s=None, surveyed_beacons=None, initial_geometries=None, **options)` | Fit measurement inputs with explicit options/optional declared survey and physical starts; return every attempt and its solver/diagnostic evidence. |
| [`plane_diagnostics`](../uwb/m4.py#L518) — `plane_diagnostics(points)` | Fit a point-cloud reference plane and report normal, deviation and degeneracy evidence. |
| [`_error`](../uwb/m4.py#L532) — `_error(p, b, tp, tb)` | Internal error helper. Uses `be.tolist`, `float`, `np.linalg.norm`, `np.max`, `np.mean` among other calls. |
| [`evaluate_geometry`](../uwb/m4.py#L538) — `evaluate_geometry(estimate, truth, options=None)` | Compare fitted trajectory/beacons against separate truth in disclosed raw/rigid evaluation frames; preserve physical scale. |
| [`_problem`](../uwb/m4.py#L565) — `_problem(exp, opts)` | Internal problem helper. Uses `build_problem`. |
| [`compatible_initial_geometries`](../uwb/m4.py#L570) — `compatible_initial_geometries(run, experiment, options=None)` | Validate and adapt retained physical starts for a compatible target experiment/model; reject unsupported pairing. |
| [`solve_experiment`](../uwb/m4.py#L597) — `solve_experiment(exp, options=None, initial_geometries=None, *, fit_callback=None)` | Validate a native experiment, run its estimator, evaluate against separate synthetic truth, and return the complete saved-run structure. |
| [`validate_run`](../uwb/m4.py#L712) — `validate_run(run)` | Strictly validate a saved native run and retained numerical/diagnostic consistency without rerunning optimization. |

Re-exported native aliases: `MAX_KNOTS = m3.MAX_KNOTS`. They retain the referenced function signature and behavior.

## uwb/m4_service.py

| Function / exact signature | Purpose |
|---|---|
| [`register_m4_routes`](../uwb/m4_service.py#L12) — `register_m4_routes(app, directory, artifacts, executor, jobs, lock, *, bundled_root=None)` | Register native model routes with shared local history, background executor, job state and optional bundled reference records. |
| [`register_m4_routes.run_path`](../uwb/m4_service.py#L13) — `register_m4_routes.run_path(identifier)` | Internal callback or route handler: run path. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m4_routes.artifact_path`](../uwb/m4_service.py#L18) — `register_m4_routes.artifact_path(identifier)` | Internal callback or route handler: artifact path. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m4_routes.pending`](../uwb/m4_service.py#L21) — `register_m4_routes.pending(path, data)` | Internal callback or route handler: pending. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m4_routes.retain_runs`](../uwb/m4_service.py#L26) — `register_m4_routes.retain_runs(data)` | Internal callback or route handler: retain runs. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m4_routes.execute`](../uwb/m4_service.py#L33) — `register_m4_routes.execute(identifier, experiment, options)` | Internal callback or route handler: execute. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m4_routes.submit_m4`](../uwb/m4_service.py#L57) — `register_m4_routes.submit_m4()` | Internal callback or route handler: submit m4. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m4_routes.execute_sweep`](../uwb/m4_service.py#L73) — `register_m4_routes.execute_sweep(identifier, config)` | Internal callback or route handler: execute sweep. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m4_routes.execute_sweep.checkpoint`](../uwb/m4_service.py#L77) — `register_m4_routes.execute_sweep.checkpoint(data)` | Internal callback or route handler: checkpoint. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m4_routes.submit_m4_sweep`](../uwb/m4_service.py#L101) — `register_m4_routes.submit_m4_sweep()` | Internal callback or route handler: submit m4 sweep. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m4_routes.list_m4_sweeps`](../uwb/m4_service.py#L114) — `register_m4_routes.list_m4_sweeps()` | Internal callback or route handler: list m4 sweeps. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m4_routes.read_sweep`](../uwb/m4_service.py#L129) — `register_m4_routes.read_sweep(identifier)` | Internal callback or route handler: read sweep. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m4_routes.reopen_m4_sweep`](../uwb/m4_service.py#L158) — `register_m4_routes.reopen_m4_sweep(identifier)` | Internal callback or route handler: reopen m4 sweep. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m4_routes.export_m4_csv`](../uwb/m4_service.py#L162) — `register_m4_routes.export_m4_csv(identifier)` | Internal callback or route handler: export m4 csv. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m4_routes.import_m4`](../uwb/m4_service.py#L166) — `register_m4_routes.import_m4()` | Internal callback or route handler: import m4. See its enclosing function and the HTTP route table for request/return context. |

## uwb/m4_sweeps.py

| Function / exact signature | Purpose |
|---|---|
| [`_cell`](../uwb/m4_sweeps.py#L21) — `_cell(config, value, seed)` | Internal cell helper. Uses `acquisition.pop`, `copy.deepcopy`, `experiment.get`, `experiment.setdefault`, `isinstance` among other calls. |
| [`_variant_options`](../uwb/m4_sweeps.py#L45) — `_variant_options(options, variant, factor)` | Internal variant options helper. Uses `m4.validate_options`. |
| [`validate_sweep_config`](../uwb/m4_sweeps.py#L49) — `validate_sweep_config(config=None)` | Normalize a bounded native single-factor study; validate factors, values, seeds, variants, pairing restrictions and workload before fitting. |
| [`_failed_run`](../uwb/m4_sweeps.py#L113) — `_failed_run(experiment, options, error, initials=None)` | Internal failed run helper. Uses `copy.deepcopy`, `experiment.get`, `range`, `type`. |
| [`run_sweep`](../uwb/m4_sweeps.py#L122) — `run_sweep(config=None, on_progress=None)` | Execute paired value/seed/variant cells; retain every outcome, aggregate evidence and invoke optional on_progress checkpoints. |
| [`_distribution`](../uwb/m4_sweeps.py#L162) — `_distribution(values)` | Internal distribution helper. Uses `float`, `len`, `math.isfinite`, `max`, `min` among other calls. |
| [`aggregate_sweep`](../uwb/m4_sweeps.py#L168) — `aggregate_sweep(artifact)` | Compute distributions, success/failure accounting and all-attempt study summaries from retained entries. |
| [`validate_artifact`](../uwb/m4_sweeps.py#L245) — `validate_artifact(data)` | Strictly validate saved native study/comparison structure, retained children and derived evidence without fitting. |
| [`save_artifact`](../uwb/m4_sweeps.py#L291) — `save_artifact(path, data)` | Validate and write a complete study/comparison artifact through temporary-file replacement. |
| [`load_artifact`](../uwb/m4_sweeps.py#L300) — `load_artifact(path)` | Load finite native study/comparison JSON and strictly validate it. |
| [`table_csv`](../uwb/m4_sweeps.py#L309) — `table_csv(artifact)` | Return native CSV text containing this module’s saved run, attempt, study or comparison table; per-observation study exports use their separate service route. |

## uwb/m5.py

| Function / exact signature | Purpose |
|---|---|
| [`generate_experiment`](../uwb/m5.py#L26) — `generate_experiment(config=None)` | Normalize generation settings and return a native synthetic experiment with separate estimator_input and truth/reference records; no fit. |
| [`_m4_experiment`](../uwb/m5.py#L32) — `_m4_experiment(exp)` | Internal m4 experiment helper. Uses `copy.deepcopy`. |
| [`validate_experiment`](../uwb/m5.py#L39) — `validate_experiment(exp)` | Strictly validate the native experiment representation, shapes and generation consistency; return the accepted experiment or raise ValueError. |
| [`base_options`](../uwb/m5.py#L46) — `base_options(options)` | Return validated underlying-engine options with this model extension removed. |
| [`validate_options`](../uwb/m5.py#L54) — `validate_options(options=None)` | Validate and fill native estimator/numerical defaults; return normalized options without generating data or fitting. |
| [`SolverProblem.__getattr__`](../uwb/m5.py#L87) — `SolverProblem.__getattr__(self, name)` | Internal getattr helper. Uses `getattr`. |
| [`SolverProblem.physical_parameters`](../uwb/m5.py#L90) — `SolverProblem.physical_parameters(self, parameters)` | Convert solver h/q coordinates to the underlying physical metre parameter vector. |
| [`SolverProblem.unpack`](../uwb/m5.py#L100) — `SolverProblem.unpack(self, parameters)` | Convert a model parameter vector into physical trajectory and beacon XYZ arrays. |
| [`SolverProblem.geometry`](../uwb/m5.py#L103) — `SolverProblem.geometry(self, parameters)` | Evaluate physical trajectory and beacon geometry represented by a parameter vector. |
| [`SolverProblem.pack`](../uwb/m5.py#L106) — `SolverProblem.pack(self, trajectory, beacons, *, project=False)` | Convert physical trajectory and beacon XYZ arrays into the problem coordinate vector, checking constraints; project permits supported feasibility projection. |
| [`SolverProblem.disclosure`](../uwb/m5.py#L115) — `SolverProblem.disclosure(self)` | Return height coordinate, bounds, physical units and objective/branch metadata for this solver problem. |
| [`build_problem`](../uwb/m5.py#L128) — `build_problem(observations, times_s, *, beacon_count=None, display_times_s=None, surveyed_beacons=None, **options)` | Build the model parameterization, interpolation, constraints and weighted measurement/prior inputs from observations and times. Truth is not an input. |
| [`measurement_residuals`](../uwb/m5.py#L148) — `measurement_residuals(parameters, problem)` | Return standardized range residuals only, excluding priors. |
| [`prior_components`](../uwb/m5.py#L152) — `prior_components(parameters, problem)` | Return separately named motion and height prior residual vectors. |
| [`residuals`](../uwb/m5.py#L156) — `residuals(parameters, problem)` | Return the model objective residual vector; range terms use predicted minus measured range normalized by saved sigma, with applicable priors/transforms. |
| [`measurement_jacobian`](../uwb/m5.py#L161) — `measurement_jacobian(parameters, problem)` | Return the analytic Jacobian of measurement residuals in this model coordinate system. |
| [`jacobian`](../uwb/m5.py#L177) — `jacobian(parameters, problem)` | Return the analytic objective Jacobian including supported prior/robust/survey terms. |
| [`jacobian_diagnostics`](../uwb/m5.py#L187) — `jacobian_diagnostics(parameters, problem, *, augmented=False)` | Compute local singular values, rank and conditioning; augmented selects measurement-plus-prior information where supported. |
| [`BoundTransform.__init__`](../uwb/m5.py#L206) — `BoundTransform.__init__(self, lower, upper)` | Internal init helper. Uses `ValueError`, `np.any`, `np.isfinite`. |
| [`BoundTransform.encode`](../uwb/m5.py#L211) — `BoundTransform.encode(self, x)` | Map strictly interior physical coordinates into unconstrained logarithmic LM coordinates; reject boundary starts. |
| [`BoundTransform.decode`](../uwb/m5.py#L219) — `BoundTransform.decode(self, u)` | Map unconstrained LM coordinates to physical values and diagonal derivative; reject overflow or lost strict interior. |
| [`_initial`](../uwb/m5.py#L230) — `_initial(problem, rng, index)` | Internal initial helper. Uses `m4._initial`, `problem.geometry`, `problem.pack`. |
| [`_perturb`](../uwb/m5.py#L236) — `_perturb(problem, initial, rng)` | Internal perturb helper. Uses `len`, `np.isfinite`, `np.maximum`, `np.minimum`, `np.where` among other calls. |
| [`_algebraic`](../uwb/m5.py#L246) — `_algebraic(problem, observations, times_s)` | Internal algebraic helper. Uses `m5_algebraic.propose_initialization`. |
| [`fit_observations`](../uwb/m5.py#L251) — `fit_observations(observations, times_s, *, beacon_count=None, display_times_s=None, surveyed_beacons=None, initial_geometries=None, **options)` | Fit measurement inputs with explicit options/optional declared survey and physical starts; return every attempt and its solver/diagnostic evidence. |
| [`fit_observations.fun`](../uwb/m5.py#L294) — `fit_observations.fun(u)` | Internal callback or route handler: fun. See its enclosing function and the HTTP route table for request/return context. |
| [`fit_observations.derivative`](../uwb/m5.py#L295) — `fit_observations.derivative(u)` | Internal callback or route handler: derivative. See its enclosing function and the HTTP route table for request/return context. |
| [`_problem`](../uwb/m5.py#L323) — `_problem(exp, opts)` | Internal problem helper. Uses `build_problem`. |
| [`solve_experiment`](../uwb/m5.py#L328) — `solve_experiment(exp, options=None, initial_geometries=None)` | Validate a native experiment, run its estimator, evaluate against separate synthetic truth, and return the complete saved-run structure. |
| [`solve_experiment.fitter`](../uwb/m5.py#L336) — `solve_experiment.fitter(observations, times_s, **kwargs)` | Internal callback or route handler: fitter. See its enclosing function and the HTTP route table for request/return context. |
| [`make_initial_geometries`](../uwb/m5.py#L360) — `make_initial_geometries(exp, options=None)` | Create retained physical trajectory/beacon starts for explicit options, before conversion into solver coordinates. |
| [`compatible_initial_geometries`](../uwb/m5.py#L382) — `compatible_initial_geometries(run, experiment, options=None)` | Validate and adapt retained physical starts for a compatible target experiment/model; reject unsupported pairing. |
| [`_same_diagnostics`](../uwb/m5.py#L388) — `_same_diagnostics(saved, expected)` | Internal same diagnostics helper. Uses `_same_diagnostics`, `all`, `expected.items`, `isinstance`, `len` among other calls. |
| [`validate_run`](../uwb/m5.py#L396) — `validate_run(run)` | Strictly validate a saved native run and retained numerical/diagnostic consistency without rerunning optimization. |

Re-exported native aliases: `MAX_KNOTS = m4.MAX_KNOTS`; `FLOOR = m4.FLOOR`; `normalize_config = m4.normalize_config`. They retain the referenced function signature and behavior.

## uwb/m5_algebraic.py

| Function / exact signature | Purpose |
|---|---|
| [`_Failure.__init__`](../uwb/m5_algebraic.py#L19) — `_Failure.__init__(self, code, message, status='failed')` | Internal init helper. Uses `super`, `super().__init__`. |
| [`_number`](../uwb/m5_algebraic.py#L24) — `_number(value, name)` | Internal number helper. Uses `_Failure`, `float`, `isinstance`, `math.isfinite`. |
| [`_rank`](../uwb/m5_algebraic.py#L30) — `_rank(matrix)` | Internal rank helper. Uses `float`, `int`, `len`, `np.count_nonzero`, `np.linalg.svd` among other calls. |
| [`_coefficient_names`](../uwb/m5_algebraic.py#L41) — `_coefficient_names(values)` | Internal coefficient names helper. Uses `dict`, `map`, `zip`. |
| [`propose_initialization`](../uwb/m5_algebraic.py#L45) — `propose_initialization(observations, times_s, beacon_count, options=None)` | Build an algebraic physical-start proposal and diagnostic evidence from supported complete synchronous planar/shared-height measurements. |

## uwb/m5_service.py

| Function / exact signature | Purpose |
|---|---|
| [`register_m5_routes`](../uwb/m5_service.py#L12) — `register_m5_routes(app, directory, artifacts, executor, jobs, lock, *, bundled_root=None)` | Register native model routes with shared local history, background executor, job state and optional bundled reference records. |
| [`register_m5_routes.run_path`](../uwb/m5_service.py#L15) — `register_m5_routes.run_path(identifier)` | Internal callback or route handler: run path. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m5_routes.artifact_path`](../uwb/m5_service.py#L20) — `register_m5_routes.artifact_path(identifier)` | Internal callback or route handler: artifact path. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m5_routes.pending`](../uwb/m5_service.py#L23) — `register_m5_routes.pending(path, data)` | Internal callback or route handler: pending. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m5_routes.retain_runs`](../uwb/m5_service.py#L28) — `register_m5_routes.retain_runs(data)` | Internal callback or route handler: retain runs. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m5_routes.execute`](../uwb/m5_service.py#L35) — `register_m5_routes.execute(identifier, experiment, options)` | Internal callback or route handler: execute. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m5_routes.submit_m5`](../uwb/m5_service.py#L59) — `register_m5_routes.submit_m5()` | Internal callback or route handler: submit m5. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m5_routes.execute_sweep`](../uwb/m5_service.py#L75) — `register_m5_routes.execute_sweep(identifier, config)` | Internal callback or route handler: execute sweep. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m5_routes.execute_sweep.checkpoint`](../uwb/m5_service.py#L79) — `register_m5_routes.execute_sweep.checkpoint(data)` | Internal callback or route handler: checkpoint. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m5_routes.submit_m5_sweep`](../uwb/m5_service.py#L103) — `register_m5_routes.submit_m5_sweep()` | Internal callback or route handler: submit m5 sweep. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m5_routes.list_m5_sweeps`](../uwb/m5_service.py#L116) — `register_m5_routes.list_m5_sweeps()` | Internal callback or route handler: list m5 sweeps. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m5_routes.read_sweep`](../uwb/m5_service.py#L131) — `register_m5_routes.read_sweep(identifier)` | Internal callback or route handler: read sweep. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m5_routes.reopen_m5_sweep`](../uwb/m5_service.py#L160) — `register_m5_routes.reopen_m5_sweep(identifier)` | Internal callback or route handler: reopen m5 sweep. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m5_routes.export_m5_csv`](../uwb/m5_service.py#L164) — `register_m5_routes.export_m5_csv(identifier)` | Internal callback or route handler: export m5 csv. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m5_routes.import_m5`](../uwb/m5_service.py#L168) — `register_m5_routes.import_m5()` | Internal callback or route handler: import m5. See its enclosing function and the HTTP route table for request/return context. |

## uwb/m5_sweeps.py

| Function / exact signature | Purpose |
|---|---|
| [`_cell`](../uwb/m5_sweeps.py#L22) — `_cell(config, value, seed)` | Internal cell helper. Uses `acquisition.pop`, `copy.deepcopy`, `experiment.get`, `experiment.setdefault`, `isinstance` among other calls. |
| [`_variant_options`](../uwb/m5_sweeps.py#L41) — `_variant_options(options, variant, factor)` | Internal variant options helper. Uses `m4.validate_options`. |
| [`validate_sweep_config`](../uwb/m5_sweeps.py#L45) — `validate_sweep_config(config=None)` | Normalize a bounded native single-factor study; validate factors, values, seeds, variants, pairing restrictions and workload before fitting. |
| [`_failed_run`](../uwb/m5_sweeps.py#L109) — `_failed_run(experiment, options, error, initials=None)` | Internal failed run helper. Uses `copy.deepcopy`, `experiment.get`, `range`, `type`. |
| [`run_sweep`](../uwb/m5_sweeps.py#L118) — `run_sweep(config=None, on_progress=None)` | Execute paired value/seed/variant cells; retain every outcome, aggregate evidence and invoke optional on_progress checkpoints. |
| [`_distribution`](../uwb/m5_sweeps.py#L148) — `_distribution(values)` | Internal distribution helper. Uses `float`, `len`, `math.isfinite`, `max`, `min` among other calls. |
| [`aggregate_sweep`](../uwb/m5_sweeps.py#L154) — `aggregate_sweep(artifact)` | Compute distributions, success/failure accounting and all-attempt study summaries from retained entries. |
| [`validate_artifact`](../uwb/m5_sweeps.py#L167) — `validate_artifact(data)` | Strictly validate saved native study/comparison structure, retained children and derived evidence without fitting. |
| [`save_artifact`](../uwb/m5_sweeps.py#L215) — `save_artifact(path, data)` | Validate and write a complete study/comparison artifact through temporary-file replacement. |
| [`load_artifact`](../uwb/m5_sweeps.py#L224) — `load_artifact(path)` | Load finite native study/comparison JSON and strictly validate it. |
| [`table_csv`](../uwb/m5_sweeps.py#L233) — `table_csv(artifact)` | Return native CSV text containing this module’s saved run, attempt, study or comparison table; per-observation study exports use their separate service route. |

## uwb/m6.py

| Function / exact signature | Purpose |
|---|---|
| [`normalize_config`](../uwb/m6.py#L25) — `normalize_config(config=None)` | Validate and fill native generation defaults; return normalized config, raising ValueError for unsupported or invalid fields. |
| [`_base_config`](../uwb/m6.py#L62) — `_base_config(config)` | Internal base config helper. Uses `config.items`, `copy.deepcopy`. |
| [`_contaminate`](../uwb/m6.py#L66) — `_contaminate(source, cfg)` | Internal contaminate helper. Uses `bool`, `copy.deepcopy`, `enumerate`, `exp.update`, `float` among other calls. |
| [`generate_experiment`](../uwb/m6.py#L119) — `generate_experiment(config=None)` | Normalize generation settings and return a native synthetic experiment with separate estimator_input and truth/reference records; no fit. |
| [`_legacy_experiment`](../uwb/m6.py#L126) — `_legacy_experiment(exp)` | Internal legacy experiment helper. Uses `_base_config`, `copy.deepcopy`, `result.pop`, `result.update`. |
| [`validate_experiment`](../uwb/m6.py#L134) — `validate_experiment(exp)` | Strictly validate the native experiment representation, shapes and generation consistency; return the accepted experiment or raise ValueError. |
| [`base_options`](../uwb/m6.py#L152) — `base_options(options)` | Return validated underlying-engine options with this model extension removed. |
| [`validate_options`](../uwb/m6.py#L157) — `validate_options(options=None)` | Validate and fill native estimator/numerical defaults; return normalized options without generating data or fitting. |
| [`loss_statistics`](../uwb/m6.py#L169) — `loss_statistics(residual_sigma, loss, scale)` | Return robust influence weights and signed exact scalar curvature from standardized residuals, loss name and scale. |
| [`range_transform`](../uwb/m6.py#L190) — `range_transform(residual_sigma, loss, scale)` | Return signed square-root loss residuals and their derivative, preserving the exact robust range objective. |
| [`_objective_vectors`](../uwb/m6.py#L212) — `_objective_vectors(x, problem, opts, mask=None)` | Internal objective vectors helper. Uses `len`, `m5.jacobian`, `m5.jacobian(x, problem).copy`, `m5.measurement_residuals`, `m5.prior_components` among other calls. |
| [`build_problem`](../uwb/m6.py#L223) — `build_problem(observations, times_s, *, beacon_count=None, display_times_s=None, surveyed_beacons=None, **options)` | Build the model parameterization, interpolation, constraints and weighted measurement/prior inputs from observations and times. Truth is not an input. |
| [`residuals`](../uwb/m6.py#L232) — `residuals(parameters, problem, mask=None)` | Return the model objective residual vector; range terms use predicted minus measured range normalized by saved sigma, with applicable priors/transforms. |
| [`jacobian`](../uwb/m6.py#L236) — `jacobian(parameters, problem, mask=None)` | Return the analytic objective Jacobian including supported prior/robust/survey terms. |
| [`_optimize`](../uwb/m6.py#L245) — `_optimize(problem, opts, x0, mask=None)` | Internal optimize helper. Uses `ValueError`, `_objective_vectors`, `derivative`, `fun`, `int` among other calls. |
| [`_optimize.fun`](../uwb/m6.py#L246) — `_optimize.fun(x)` | Internal callback or route handler: fun. See its enclosing function and the HTTP route table for request/return context. |
| [`_optimize.derivative`](../uwb/m6.py#L248) — `_optimize.derivative(x)` | Internal callback or route handler: derivative. See its enclosing function and the HTTP route table for request/return context. |
| [`_optimize.lm_fun`](../uwb/m6.py#L257) — `_optimize.lm_fun(u)` | Internal callback or route handler: lm fun. See its enclosing function and the HTTP route table for request/return context. |
| [`_optimize.lm_jac`](../uwb/m6.py#L259) — `_optimize.lm_jac(u)` | Internal callback or route handler: lm jac. See its enclosing function and the HTTP route table for request/return context. |
| [`_information`](../uwb/m6.py#L270) — `_information(matrix, problem, *, prior_count=0, description)` | Internal information helper. Uses `float`, `int`, `len`, `max`, `np.abs` among other calls. |
| [`_fit_diagnostics`](../uwb/m6.py#L284) — `_fit_diagnostics(x, problem, opts, mask=None, pilot=None)` | Internal fit diagnostics helper. Uses `(mr * problem.sigma_m).tolist`, `_information`, `bool`, `coverage_rows`, `curvature.tolist` among other calls. |
| [`_fit_diagnostics.coverage_rows`](../uwb/m6.py#L311) — `_fit_diagnostics.coverage_rows(ids, n)` | Internal callback or route handler: coverage rows. See its enclosing function and the HTTP route table for request/return context. |
| [`_metadata`](../uwb/m6.py#L332) — `_metadata(problem, opts)` | Internal metadata helper. Uses `problem.disclosure`. |
| [`fit_observations`](../uwb/m6.py#L347) — `fit_observations(observations, times_s, *, beacon_count=None, display_times_s=None, surveyed_beacons=None, initial_geometries=None, **options)` | Fit measurement inputs with explicit options/optional declared survey and physical starts; return every attempt and its solver/diagnostic evidence. |
| [`_m5_experiment`](../uwb/m6.py#L423) — `_m5_experiment(exp)` | Internal m5 experiment helper. Uses `_legacy_experiment`. |
| [`_problem`](../uwb/m6.py#L428) — `_problem(exp, opts)` | Internal problem helper. Uses `_m5_experiment`, `base_options`, `len`, `m5._problem`. |
| [`make_initial_geometries`](../uwb/m6.py#L435) — `make_initial_geometries(exp, options=None)` | Create retained physical trajectory/beacon starts for explicit options, before conversion into solver coordinates. |
| [`compatible_initial_geometries`](../uwb/m6.py#L440) — `compatible_initial_geometries(run, experiment, options=None)` | Validate and adapt retained physical starts for a compatible target experiment/model; reject unsupported pairing. |
| [`rejection_evaluation`](../uwb/m6.py#L447) — `rejection_evaluation(decisions, records)` | Compare fitted rejection decisions against separate injected NLOS reference records for evaluation only. |
| [`_robust_disclosure`](../uwb/m6.py#L460) — `_robust_disclosure(opts)` | Internal robust disclosure helper. Uses . |
| [`solve_experiment`](../uwb/m6.py#L470) — `solve_experiment(exp, options=None, initial_geometries=None)` | Validate a native experiment, run its estimator, evaluate against separate synthetic truth, and return the complete saved-run structure. |
| [`solve_experiment.fitter`](../uwb/m6.py#L478) — `solve_experiment.fitter(observations, times_s, **kwargs)` | Internal callback or route handler: fitter. See its enclosing function and the HTTP route table for request/return context. |
| [`validate_run`](../uwb/m6.py#L512) — `validate_run(run)` | Strictly validate a saved native run and retained numerical/diagnostic consistency without rerunning optimization. |

Re-exported native aliases: `MAX_KNOTS = m5.MAX_KNOTS`; `measurement_residuals = m5.measurement_residuals`; `measurement_jacobian = m5.measurement_jacobian`; `prior_components = m5.prior_components`. They retain the referenced function signature and behavior.

## uwb/m6_service.py

| Function / exact signature | Purpose |
|---|---|
| [`register_m6_routes`](../uwb/m6_service.py#L12) — `register_m6_routes(app, directory, artifacts, executor, jobs, lock, *, bundled_root=None)` | Register native model routes with shared local history, background executor, job state and optional bundled reference records. |
| [`register_m6_routes.run_path`](../uwb/m6_service.py#L15) — `register_m6_routes.run_path(identifier)` | Internal callback or route handler: run path. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m6_routes.artifact_path`](../uwb/m6_service.py#L20) — `register_m6_routes.artifact_path(identifier)` | Internal callback or route handler: artifact path. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m6_routes.pending`](../uwb/m6_service.py#L23) — `register_m6_routes.pending(path, data)` | Internal callback or route handler: pending. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m6_routes.retain_runs`](../uwb/m6_service.py#L28) — `register_m6_routes.retain_runs(data)` | Internal callback or route handler: retain runs. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m6_routes.execute`](../uwb/m6_service.py#L35) — `register_m6_routes.execute(identifier, experiment, options)` | Internal callback or route handler: execute. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m6_routes.submit_m6`](../uwb/m6_service.py#L59) — `register_m6_routes.submit_m6()` | Internal callback or route handler: submit m6. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m6_routes.execute_sweep`](../uwb/m6_service.py#L75) — `register_m6_routes.execute_sweep(identifier, config)` | Internal callback or route handler: execute sweep. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m6_routes.execute_sweep.checkpoint`](../uwb/m6_service.py#L79) — `register_m6_routes.execute_sweep.checkpoint(data)` | Internal callback or route handler: checkpoint. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m6_routes.submit_m6_sweep`](../uwb/m6_service.py#L103) — `register_m6_routes.submit_m6_sweep()` | Internal callback or route handler: submit m6 sweep. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m6_routes.list_m6_sweeps`](../uwb/m6_service.py#L116) — `register_m6_routes.list_m6_sweeps()` | Internal callback or route handler: list m6 sweeps. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m6_routes.read_sweep`](../uwb/m6_service.py#L131) — `register_m6_routes.read_sweep(identifier)` | Internal callback or route handler: read sweep. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m6_routes.reopen_m6_sweep`](../uwb/m6_service.py#L160) — `register_m6_routes.reopen_m6_sweep(identifier)` | Internal callback or route handler: reopen m6 sweep. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m6_routes.export_m6_csv`](../uwb/m6_service.py#L164) — `register_m6_routes.export_m6_csv(identifier)` | Internal callback or route handler: export m6 csv. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m6_routes.import_m6`](../uwb/m6_service.py#L168) — `register_m6_routes.import_m6()` | Internal callback or route handler: import m6. See its enclosing function and the HTTP route table for request/return context. |

## uwb/m6_sweeps.py

| Function / exact signature | Purpose |
|---|---|
| [`_cell`](../uwb/m6_sweeps.py#L21) — `_cell(config, value, seed)` | Internal cell helper. Uses `contamination.setdefault`, `copy.deepcopy`, `experiment.setdefault`, `factor.startswith`, `m4.normalize_config` among other calls. |
| [`_variant_options`](../uwb/m6_sweeps.py#L38) — `_variant_options(options, variant, factor)` | Internal variant options helper. Uses `m4.validate_options`. |
| [`validate_sweep_config`](../uwb/m6_sweeps.py#L42) — `validate_sweep_config(config=None)` | Normalize a bounded native single-factor study; validate factors, values, seeds, variants, pairing restrictions and workload before fitting. |
| [`_failed_run`](../uwb/m6_sweeps.py#L97) — `_failed_run(experiment, options, error, initials=None)` | Internal failed run helper. Uses `copy.deepcopy`, `experiment.get`, `range`, `type`. |
| [`run_sweep`](../uwb/m6_sweeps.py#L106) — `run_sweep(config=None, on_progress=None)` | Execute paired value/seed/variant cells; retain every outcome, aggregate evidence and invoke optional on_progress checkpoints. |
| [`_distribution`](../uwb/m6_sweeps.py#L136) — `_distribution(values)` | Internal distribution helper. Uses `float`, `len`, `math.isfinite`, `max`, `min` among other calls. |
| [`aggregate_sweep`](../uwb/m6_sweeps.py#L142) — `aggregate_sweep(artifact)` | Compute distributions, success/failure accounting and all-attempt study summaries from retained entries. |
| [`validate_artifact`](../uwb/m6_sweeps.py#L204) — `validate_artifact(data)` | Strictly validate saved native study/comparison structure, retained children and derived evidence without fitting. |
| [`save_artifact`](../uwb/m6_sweeps.py#L258) — `save_artifact(path, data)` | Validate and write a complete study/comparison artifact through temporary-file replacement. |
| [`load_artifact`](../uwb/m6_sweeps.py#L267) — `load_artifact(path)` | Load finite native study/comparison JSON and strictly validate it. |
| [`table_csv`](../uwb/m6_sweeps.py#L276) — `table_csv(artifact)` | Return native CSV text containing this module’s saved run, attempt, study or comparison table; per-observation study exports use their separate service route. |

## uwb/m7.py

| Function / exact signature | Purpose |
|---|---|
| [`normalize_survey`](../uwb/m7.py#L26) — `normalize_survey(survey, beacon_count=None)` | Validate explicit world/metre fixed and uncertain coordinate blocks, axis masks, IDs, non-overlap and positive-definite covariance. |
| [`normalize_uncertainty`](../uwb/m7.py#L75) — `normalize_uncertainty(value=None)` | Normalize the explicit independent-Gaussian known-sigma local-uncertainty assumptions and tolerances. |
| [`validate_options`](../uwb/m7.py#L89) — `validate_options(options=None)` | Validate and fill native estimator/numerical defaults; return normalized options without generating data or fitting. |
| [`base_options`](../uwb/m7.py#L110) — `base_options(options)` | Return validated underlying-engine options with this model extension removed. |
| [`build_problem`](../uwb/m7.py#L114) — `build_problem(observations, times_s, *, beacon_count=None, display_times_s=None, surveyed_beacons=None, **options)` | Build the model parameterization, interpolation, constraints and weighted measurement/prior inputs from observations and times. Truth is not an input. |
| [`survey_residuals`](../uwb/m7.py#L171) — `survey_residuals(x, problem)` | Return whitened uncertain-survey residual rows for selected world coordinates; exact fixed coordinates were eliminated. |
| [`residuals`](../uwb/m7.py#L175) — `residuals(x, problem, mask=None)` | Return the model objective residual vector; range terms use predicted minus measured range normalized by saved sigma, with applicable priors/transforms. |
| [`jacobian`](../uwb/m7.py#L185) — `jacobian(x, problem, mask=None)` | Return the analytic objective Jacobian including supported prior/robust/survey terms. |
| [`information`](../uwb/m7.py#L196) — `information(matrix, n, rtol=1e-08)` | Return matrix singular spectrum, relative-tolerance rank and conditioning for n parameters. |
| [`conditional_uncertainty`](../uwb/m7.py#L206) — `conditional_uncertainty(x, problem, *, converged=True, mask=None)` | Compute supported conditional local Gaussian parameter/geometry intervals, or return available=false and explicit withheld reasons. |
| [`conditional_uncertainty.propagate`](../uwb/m7.py#L256) — `conditional_uncertainty.propagate(basis)` | Internal callback or route handler: propagate. See its enclosing function and the HTTP route table for request/return context. |
| [`_diagnostics`](../uwb/m7.py#L267) — `_diagnostics(x, problem, converged, mask=None)` | Internal diagnostics helper. Uses `(r * problem.sigma_m).tolist`, `bool`, `conditional_uncertainty`, `coverage_rows`, `float` among other calls. |
| [`_diagnostics.coverage_rows`](../uwb/m7.py#L282) — `_diagnostics.coverage_rows(ids, count)` | Internal callback or route handler: coverage rows. See its enclosing function and the HTTP route table for request/return context. |
| [`_optimize`](../uwb/m7.py#L301) — `_optimize(problem, x0, opts, mask=None)` | Internal optimize helper. Uses `ValueError`, `int`, `jacobian`, `least_squares`, `len` among other calls. |
| [`_optimize.fun`](../uwb/m7.py#L311) — `_optimize.fun(u)` | Internal callback or route handler: fun. See its enclosing function and the HTTP route table for request/return context. |
| [`_optimize.jac`](../uwb/m7.py#L312) — `_optimize.jac(u)` | Internal callback or route handler: jac. See its enclosing function and the HTTP route table for request/return context. |
| [`_independent_initial`](../uwb/m7.py#L324) — `_independent_initial(problem, rng)` | Internal independent initial helper. Uses `'xyz'.index`, `declared[a].append`, `enumerate`, `float`, `len` among other calls. |
| [`fit_observations`](../uwb/m7.py#L344) — `fit_observations(observations, times_s, *, beacon_count=None, display_times_s=None, surveyed_beacons=None, initial_geometries=None, **options)` | Fit measurement inputs with explicit options/optional declared survey and physical starts; return every attempt and its solver/diagnostic evidence. |
| [`_problem`](../uwb/m7.py#L391) — `_problem(exp, opts)` | Internal problem helper. Uses `_source_model_limits`, `build_problem`. |
| [`_source_model_limits`](../uwb/m7.py#L399) — `_source_model_limits(exp, opts=None)` | Declared generation metadata only, never per-observation labels/truth. |
| [`summarize_uncertainty`](../uwb/m7.py#L423) — `summarize_uncertainty(run, start_index=None, assumptions=None)` | Strictly inspect a saved robust/survey attempt offline with optional uncertainty assumptions; does not fit. |
| [`make_initial_geometries`](../uwb/m7.py#L470) — `make_initial_geometries(exp, options=None)` | Create retained physical trajectory/beacon starts for explicit options, before conversion into solver coordinates. |
| [`_run_diagnostics`](../uwb/m7.py#L489) — `_run_diagnostics(opts, starts)` | Internal run diagnostics helper. Uses `copy.deepcopy`, `sum`. |
| [`evaluate_geometry`](../uwb/m7.py#L506) — `evaluate_geometry(estimate, truth, options=None)` | Compare fitted trajectory/beacons against separate truth in disclosed raw/rigid evaluation frames; preserve physical scale. |
| [`_evaluation_diagnostics`](../uwb/m7.py#L520) — `_evaluation_diagnostics(exp, start)` | Internal evaluation diagnostics helper. Uses `bool`, `copy.deepcopy`, `evaluate_geometry`, `m6.rejection_evaluation`, `max` among other calls. |
| [`solve_experiment`](../uwb/m7.py#L540) — `solve_experiment(exp, options=None, initial_geometries=None)` | Validate a native experiment, run its estimator, evaluate against separate synthetic truth, and return the complete saved-run structure. |
| [`validate_run`](../uwb/m7.py#L568) — `validate_run(run)` | Strictly validate a saved native run and retained numerical/diagnostic consistency without rerunning optimization. |
| [`save_run`](../uwb/m7.py#L630) — `save_run(path, run)` | Validate and atomically save a native survey run to path. |
| [`load_run`](../uwb/m7.py#L638) — `load_run(path)` | Load and strictly validate a native survey run from path. |
| [`table_csv`](../uwb/m7.py#L642) — `table_csv(run)` | Return native CSV text containing this module’s saved run, attempt, study or comparison table; per-observation study exports use their separate service route. |

## uwb/m7_service.py

| Function / exact signature | Purpose |
|---|---|
| [`register_m7`](../uwb/m7_service.py#L17) — `register_m7(app, directory, executor=None, jobs=None, lock=None, *, on_saved=None)` | Register survey fitting, import/export, comparison and uncertainty routes with optional shared job state and save callback. |
| [`register_m7.path_for`](../uwb/m7_service.py#L28) — `register_m7.path_for(identifier)` | Internal callback or route handler: path for. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m7.save`](../uwb/m7_service.py#L33) — `register_m7.save(identifier, run)` | Internal callback or route handler: save. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m7.read`](../uwb/m7_service.py#L40) — `register_m7.read(identifier)` | Internal callback or route handler: read. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m7.execute`](../uwb/m7_service.py#L59) — `register_m7.execute(identifier, experiment, options, initial, envelope)` | Internal callback or route handler: execute. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m7.submit_m7`](../uwb/m7_service.py#L77) — `register_m7.submit_m7()` | Internal callback or route handler: submit m7. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m7.reopen_m7`](../uwb/m7_service.py#L107) — `register_m7.reopen_m7(identifier)` | Internal callback or route handler: reopen m7. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m7.uncertainty_m7`](../uwb/m7_service.py#L111) — `register_m7.uncertainty_m7(identifier)` | Internal callback or route handler: uncertainty m7. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m7.json_m7`](../uwb/m7_service.py#L116) — `register_m7.json_m7(identifier)` | Internal callback or route handler: json m7. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m7.csv_m7`](../uwb/m7_service.py#L120) — `register_m7.csv_m7(identifier)` | Internal callback or route handler: csv m7. See its enclosing function and the HTTP route table for request/return context. |
| [`register_m7.import_m7`](../uwb/m7_service.py#L126) — `register_m7.import_m7()` | Internal callback or route handler: import m7. See its enclosing function and the HTTP route table for request/return context. |

## uwb/sweeps.py

| Function / exact signature | Purpose |
|---|---|
| [`_integer`](../uwb/sweeps.py#L34) — `_integer(value, name, lower, upper)` | Internal integer helper. Uses `ValueError`, `isinstance`. |
| [`validate_sweep_config`](../uwb/sweeps.py#L40) — `validate_sweep_config(config)` | Normalize a bounded native single-factor study; validate factors, values, seeds, variants, pairing restrictions and workload before fitting. |
| [`_cell_config`](../uwb/sweeps.py#L125) — `_cell_config(config, value, seed)` | Internal cell config helper. Uses `copy.deepcopy`, `experiment.setdefault`. |
| [`_initials`](../uwb/sweeps.py#L136) — `_initials(experiment, config, value, seed)` | Internal initials helper. Uses `_independent_initial`, `any`, `beacons.tolist`, `build_problem`, `initials.append` among other calls. |
| [`_solve_cell`](../uwb/sweeps.py#L158) — `_solve_cell(experiment, options, initials)` | Internal solve cell helper. Uses `build_problem`, `copy.deepcopy`, `evaluate_geometry`, `experiment['software_versions'].copy`, `fit_observations` among other calls. |
| [`run_sweep`](../uwb/sweeps.py#L186) — `run_sweep(config=None, on_progress=None)` | Execute paired value/seed/variant cells; retain every outcome, aggregate evidence and invoke optional on_progress checkpoints. |
| [`_distribution`](../uwb/sweeps.py#L237) — `_distribution(values)` | Internal distribution helper. Uses `float`, `len`, `max`, `min`, `np.median` among other calls. |
| [`aggregate_sweep`](../uwb/sweeps.py#L245) — `aggregate_sweep(sweep)` | Compute distributions, success/failure accounting and all-attempt study summaries from retained entries. |
| [`_refresh_sweep`](../uwb/sweeps.py#L312) — `_refresh_sweep(sweep)` | Internal refresh sweep helper. Uses `aggregate_sweep`, `any`, `bool`, `classifications.append`, `diagnostic.get` among other calls. |
| [`build_comparison`](../uwb/sweeps.py#L358) — `build_comparison(left_run, right_run, alignment='aligned', *, _validate=True)` | Strictly compare two saved runs in raw or scale-preserving rigid alignment; retain source, pairing and metric evidence. |
| [`validate_artifact`](../uwb/sweeps.py#L453) — `validate_artifact(data)` | Strictly validate saved native study/comparison structure, retained children and derived evidence without fitting. |
| [`_validate_artifact`](../uwb/sweeps.py#L463) — `_validate_artifact(data)` | Internal validate artifact helper. Uses `(ref['initial'] or {}).get`, `(s['initial'] or {}).get`, `ExperimentFormatError`, `_cell_config`, `_normalise_config` among other calls. |
| [`save_artifact`](../uwb/sweeps.py#L534) — `save_artifact(path, data)` | Validate and write a complete study/comparison artifact through temporary-file replacement. |
| [`load_artifact`](../uwb/sweeps.py#L543) — `load_artifact(path)` | Load finite native study/comparison JSON and strictly validate it. |
| [`table_csv`](../uwb/sweeps.py#L552) — `table_csv(artifact)` | Return native CSV text containing this module’s saved run, attempt, study or comparison table; per-observation study exports use their separate service route. |

## uwb/workspace.py

| Function / exact signature | Purpose |
|---|---|
| [`split`](../uwb/workspace.py#L28) — `split(engine, config, options)` | Separate native config/options into a version-1 workspace draft; move assumed sigma into assumptions and numerical settings into numerical. |
| [`normalize`](../uwb/workspace.py#L38) — `normalize(draft)` | Validate a version-1 workspace draft and return (normalized draft, native config, native options); no generation or fit. |
| [`study_payload`](../uwb/workspace.py#L88) — `study_payload(draft, config, options)` | Translate a normalized workspace study into validated native study settings and its submission route. |
| [`capabilities`](../uwb/workspace.py#L107) — `capabilities()` | Return six engine defaults, supported features, native schemas, study factors/default variants and application limits. |
| [`register_workspace`](../uwb/workspace.py#L146) — `register_workspace(app, directory, executor, jobs, lock, library)` | Register workspace validation/configuration/export/submission routes using the shared history, worker and Library index. |
| [`register_workspace.body_object`](../uwb/workspace.py#L147) — `register_workspace.body_object()` | Internal callback or route handler: body object. See its enclosing function and the HTTP route table for request/return context. |
| [`register_workspace.source_run`](../uwb/workspace.py#L153) — `register_workspace.source_run(key)` | Internal callback or route handler: source run. See its enclosing function and the HTTP route table for request/return context. |
| [`register_workspace.resolve`](../uwb/workspace.py#L174) — `register_workspace.resolve(draft)` | Internal callback or route handler: resolve. See its enclosing function and the HTTP route table for request/return context. |
| [`register_workspace.get_capabilities`](../uwb/workspace.py#L189) — `register_workspace.get_capabilities()` | Internal callback or route handler: get capabilities. See its enclosing function and the HTTP route table for request/return context. |
| [`register_workspace.workspace_csv`](../uwb/workspace.py#L193) — `register_workspace.workspace_csv()` | Internal callback or route handler: workspace csv. See its enclosing function and the HTTP route table for request/return context. |
| [`register_workspace.workspace_validate`](../uwb/workspace.py#L221) — `register_workspace.workspace_validate()` | Internal callback or route handler: workspace validate. See its enclosing function and the HTTP route table for request/return context. |
| [`register_workspace.configuration_from_source`](../uwb/workspace.py#L229) — `register_workspace.configuration_from_source()` | Internal callback or route handler: configuration from source. See its enclosing function and the HTTP route table for request/return context. |
| [`register_workspace.execute`](../uwb/workspace.py#L255) — `register_workspace.execute(identifier, normalized, experiment, options)` | Internal callback or route handler: execute. See its enclosing function and the HTTP route table for request/return context. |
| [`register_workspace.workspace_submit`](../uwb/workspace.py#L275) — `register_workspace.workspace_submit()` | Internal callback or route handler: workspace submit. See its enclosing function and the HTTP route table for request/return context. |
| [`register_workspace.workspace_submit_study`](../uwb/workspace.py#L295) — `register_workspace.workspace_submit_study()` | Internal callback or route handler: workspace submit study. See its enclosing function and the HTTP route table for request/return context. |

## HTTP routes

GET routes read metadata/native sources, export records, or poll jobs. POST route purpose follows the linked handler; run/sweep/study submissions perform explicit new computation, while validate, import, comparison and uncertainty routes use retained/configured data as described in the guide. Errors normally return JSON error text and HTTP 400; unknown IDs/keys return 404; background failures remain visible in saved records and job status. Consult handlers for exact payloads.

The current shared entry points are GET `/api/workspace/capabilities`, POST `/api/workspace/validate`, `/api/workspace/configuration`, `/api/workspace/runs`, `/api/workspace/studies`, `/api/workspace/export/csv`, GET `/api/jobs/<identifier>` and the Library routes. Run/study submissions return a job ID (HTTP 202); poll jobs until completion/failure. Validate returns normalized configuration/native options, and native study settings when applicable. The [workspace API document](WORKSPACE.md) describes payload semantics.

| Method | Route expression | Handler |
|---|---|---|
| GET | `'/'` | [`create_app.index`](../app.py#L41) |
| GET | `'/vendor/plotly.min.js'` | [`create_app.plotly_bundle`](../app.py#L45) |
| GET | `'/api/scenarios'` | [`create_app.scenarios`](../app.py#L49) |
| POST | `'/api/sweeps'` | [`create_app.submit_sweep`](../app.py#L137) |
| POST | `'/api/m3/runs'` | [`create_app.submit_m3`](../app.py#L194) |
| POST | `'/api/m3/sweeps'` | [`create_app.submit_m3_sweep`](../app.py#L240) |
| GET | `'/api/m3/sweeps'` | [`create_app.list_m3_sweeps`](../app.py#L257) |
| GET | `'/api/m3/sweeps/<identifier>'` | [`create_app.reopen_m3_sweep`](../app.py#L273) |
| GET | `'/api/m3/sweeps/<identifier>/csv'` | [`create_app.m3_csv`](../app.py#L303) |
| POST | `'/api/m3/import'` | [`create_app.import_m3`](../app.py#L308) |
| POST | `'/api/comparisons'` | [`create_app.compare_saved`](../app.py#L325) |
| GET | `'/api/sweeps'` | [`create_app.list_artifacts`](../app.py#L342) |
| GET | `'/api/comparisons'` | [`create_app.list_artifacts`](../app.py#L342) |
| GET | `'/api/sweeps/<identifier>'` | [`create_app.reopen_artifact`](../app.py#L361) |
| GET | `'/api/comparisons/<identifier>'` | [`create_app.reopen_artifact`](../app.py#L361) |
| POST | `'/api/artifacts/import'` | [`create_app.import_artifact`](../app.py#L390) |
| POST | `'/api/runs'` | [`create_app.submit`](../app.py#L419) |
| GET | `'/api/jobs/<identifier>'` | [`create_app.job`](../app.py#L457) |
| GET | `'/api/runs'` | [`create_app.list_runs`](../app.py#L468) |
| GET | `'/api/runs/<identifier>'` | [`create_app.reopen`](../app.py#L501) |
| POST | `'/api/import'` | [`create_app.import_run`](../app.py#L519) |
| POST | `'/api/library/compare'` | [`create_app.compare_library_sources`](../app.py#L550) |
| GET | `'/api/library'` | [`register_library.library_page`](../uwb/library.py#L500) |
| GET | `'/api/library/status'` | [`register_library.library_status`](../uwb/library.py#L509) |
| POST | `'/api/library/rebuild'` | [`register_library.rebuild_library`](../uwb/library.py#L513) |
| GET | `'/api/library/<key>'` | [`register_library.library_preview`](../uwb/library.py#L521) |
| POST | `'/api/m4/runs'` | [`register_m4_routes.submit_m4`](../uwb/m4_service.py#L57) |
| POST | `'/api/m4/sweeps'` | [`register_m4_routes.submit_m4_sweep`](../uwb/m4_service.py#L101) |
| GET | `'/api/m4/sweeps'` | [`register_m4_routes.list_m4_sweeps`](../uwb/m4_service.py#L114) |
| GET | `'/api/m4/sweeps/<identifier>'` | [`register_m4_routes.reopen_m4_sweep`](../uwb/m4_service.py#L158) |
| GET | `'/api/m4/sweeps/<identifier>/csv'` | [`register_m4_routes.export_m4_csv`](../uwb/m4_service.py#L162) |
| POST | `'/api/m4/import'` | [`register_m4_routes.import_m4`](../uwb/m4_service.py#L166) |
| POST | `'/api/m5/runs'` | [`register_m5_routes.submit_m5`](../uwb/m5_service.py#L59) |
| POST | `'/api/m5/sweeps'` | [`register_m5_routes.submit_m5_sweep`](../uwb/m5_service.py#L103) |
| GET | `'/api/m5/sweeps'` | [`register_m5_routes.list_m5_sweeps`](../uwb/m5_service.py#L116) |
| GET | `'/api/m5/sweeps/<identifier>'` | [`register_m5_routes.reopen_m5_sweep`](../uwb/m5_service.py#L160) |
| GET | `'/api/m5/sweeps/<identifier>/csv'` | [`register_m5_routes.export_m5_csv`](../uwb/m5_service.py#L164) |
| POST | `'/api/m5/import'` | [`register_m5_routes.import_m5`](../uwb/m5_service.py#L168) |
| POST | `'/api/m6/runs'` | [`register_m6_routes.submit_m6`](../uwb/m6_service.py#L59) |
| POST | `'/api/m6/sweeps'` | [`register_m6_routes.submit_m6_sweep`](../uwb/m6_service.py#L103) |
| GET | `'/api/m6/sweeps'` | [`register_m6_routes.list_m6_sweeps`](../uwb/m6_service.py#L116) |
| GET | `'/api/m6/sweeps/<identifier>'` | [`register_m6_routes.reopen_m6_sweep`](../uwb/m6_service.py#L160) |
| GET | `'/api/m6/sweeps/<identifier>/csv'` | [`register_m6_routes.export_m6_csv`](../uwb/m6_service.py#L164) |
| POST | `'/api/m6/import'` | [`register_m6_routes.import_m6`](../uwb/m6_service.py#L168) |
| POST | `'/api/m7/runs'` | [`register_m7.submit_m7`](../uwb/m7_service.py#L77) |
| GET | `'/api/m7/runs/<identifier>'` | [`register_m7.reopen_m7`](../uwb/m7_service.py#L107) |
| GET | `'/api/m7/runs/<identifier>/uncertainty'` | [`register_m7.uncertainty_m7`](../uwb/m7_service.py#L111) |
| GET | `'/api/m7/runs/<identifier>/json'` | [`register_m7.json_m7`](../uwb/m7_service.py#L116) |
| GET | `'/api/m7/runs/<identifier>/csv'` | [`register_m7.csv_m7`](../uwb/m7_service.py#L120) |
| POST | `'/api/m7/import'` | [`register_m7.import_m7`](../uwb/m7_service.py#L126) |
| GET | `'/api/workspace/capabilities'` | [`register_workspace.get_capabilities`](../uwb/workspace.py#L189) |
| POST | `'/api/workspace/export/csv'` | [`register_workspace.workspace_csv`](../uwb/workspace.py#L193) |
| POST | `'/api/workspace/validate'` | [`register_workspace.workspace_validate`](../uwb/workspace.py#L221) |
| POST | `'/api/workspace/configuration'` | [`register_workspace.configuration_from_source`](../uwb/workspace.py#L229) |
| POST | `'/api/workspace/runs'` | [`register_workspace.workspace_submit`](../uwb/workspace.py#L275) |
| POST | `'/api/workspace/studies'` | [`register_workspace.workspace_submit_study`](../uwb/workspace.py#L295) |

## Browser modules

| Module | Responsibilities / entry points |
|---|---|
| `web/workspace.js` | Shared draft rendering/validation, submit/poll lifecycle, source import/adoption, result layout/tabs, comparison inspection and drawer. Public `RangeLabWorkspace`: state, onRun, openRun, openArtifact, useConfiguration, tab, importSource, onComparison, download, comparisonTarget. |
| `web/app.js` | Shared API client, selected run/start, base scene layers/camera, baseline diagnostics and exports. |
| `web/library.js` | Metadata search/filter/page/preview, authoritative source opening, A/B selection, index refresh/rebuild and navigation state. |
| `web/m2.js`–`web/m7.js` | Native retained-result render adapters, study/comparison tables/charts/exports, ping playback and survey/uncertainty inspection. Their historical forms are detached by the shared workspace. |
| `web/help.js` | `RangeLabHelp.description(node,catalog)` resolves exact path, control ID, survey or layer explanations; `attach(root,catalog)` idempotently adds title and aria-describedby without replacing existing descriptions. Init decorates dynamically added fields and shows/dismisses hover/focus help. |
| `web/input-help.json` | Shared GUI explanations used to generate the input reference; exact full paths distinguish similarly named fields. |

Scripts under `scripts/` are development, validation, benchmarking, audit or packaging tools; tests under `tests/` verify behavior. They are not additional GUI features. Read their module help before running evidence-generation scripts.
