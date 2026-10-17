"""Rebuild the input/function references and locally served HTML user guide.

Run from the repository root with .venv/Scripts/python.exe scripts/build_user_docs.py.
Uses the same field help as the GUI, normalized engine defaults, and Python ASTs;
does not generate measurements, fit data, or modify saved runs.
"""
from __future__ import annotations

import ast
import html
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from uwb.workspace import capabilities


PURPOSE = {
    'create_app': 'Create the local Flask application and register native/workspace/Library routes; run_dir selects the saved-history directory.',
    'generate_experiment': 'Normalize generation settings and return a native synthetic experiment with separate estimator_input and truth/reference records; no fit.',
    'normalize_config': 'Validate and fill native generation defaults; return normalized config, raising ValueError for unsupported or invalid fields.',
    'validate_options': 'Validate and fill native estimator/numerical defaults; return normalized options without generating data or fitting.',
    'base_options': 'Return validated underlying-engine options with this model extension removed.',
    'build_problem': 'Build the model parameterization, interpolation, constraints and weighted measurement/prior inputs from observations and times. Truth is not an input.',
    'fit_observations': 'Fit measurement inputs with explicit options/optional declared survey and physical starts; return every attempt and its solver/diagnostic evidence.',
    'solve_experiment': 'Validate a native experiment, run its estimator, evaluate against separate synthetic truth, and return the complete saved-run structure.',
    'validate_experiment': 'Strictly validate the native experiment representation, shapes and generation consistency; return the accepted experiment or raise ValueError.',
    'validate_run': 'Strictly validate a saved native run and retained numerical/diagnostic consistency without rerunning optimization.',
    'save_json': 'Validate finite native JSON and save through temporary-file replacement; path is the destination.',
    'load_json': 'Read strict native JSON from path and validate its payload; malformed/nonfinite/unsupported records fail.',
    'path_metadata': 'Return path type, traveled arclength, speed and interpolation/approximation disclosures from config.',
    'truth_positions': 'Evaluate the synthetic trajectory at requested times for generation/evaluation; do not supply this output to independent fitting.',
    'beacon_coordinates': 'Return generated or explicitly configured beacon XYZ coordinates from normalized physical config.',
    'gauge_metadata': 'Describe the coordinate gauge and physical height constraints implied by estimator options.',
    'residuals': 'Return the model objective residual vector; range terms use predicted minus measured range normalized by saved sigma, with applicable priors/transforms.',
    'measurement_residuals': 'Return standardized range residuals only, excluding priors.',
    'prior_residuals': 'Return motion prior residual rows separately from measurements.',
    'prior_components': 'Return separately named motion and height prior residual vectors.',
    'measurement_jacobian': 'Return the analytic Jacobian of measurement residuals in this model coordinate system.',
    'jacobian': 'Return the analytic objective Jacobian including supported prior/robust/survey terms.',
    'jacobian_diagnostics': 'Compute local singular values, rank and conditioning; augmented selects measurement-plus-prior information where supported.',
    'evaluate_geometry': 'Compare fitted trajectory/beacons against separate truth in disclosed raw/rigid evaluation frames; preserve physical scale.',
    'plane_diagnostics': 'Fit a point-cloud reference plane and report normal, deviation and degeneracy evidence.',
    'make_initial_geometries': 'Create retained physical trajectory/beacon starts for explicit options, before conversion into solver coordinates.',
    'compatible_initial_geometries': 'Validate and adapt retained physical starts for a compatible target experiment/model; reject unsupported pairing.',
    'propose_initialization': 'Build an algebraic physical-start proposal and diagnostic evidence from supported complete synchronous planar/shared-height measurements.',
    'loss_statistics': 'Return robust influence weights and signed exact scalar curvature from standardized residuals, loss name and scale.',
    'range_transform': 'Return signed square-root loss residuals and their derivative, preserving the exact robust range objective.',
    'rejection_evaluation': 'Compare fitted rejection decisions against separate injected NLOS reference records for evaluation only.',
    'normalize_survey': 'Validate explicit world/metre fixed and uncertain coordinate blocks, axis masks, IDs, non-overlap and positive-definite covariance.',
    'normalize_uncertainty': 'Normalize the explicit independent-Gaussian known-sigma local-uncertainty assumptions and tolerances.',
    'survey_residuals': 'Return whitened uncertain-survey residual rows for selected world coordinates; exact fixed coordinates were eliminated.',
    'information': 'Return matrix singular spectrum, relative-tolerance rank and conditioning for n parameters.',
    'conditional_uncertainty': 'Compute supported conditional local Gaussian parameter/geometry intervals, or return available=false and explicit withheld reasons.',
    'summarize_uncertainty': 'Strictly inspect a saved robust/survey attempt offline with optional uncertainty assumptions; does not fit.',
    'save_run': 'Validate and atomically save a native survey run to path.',
    'load_run': 'Load and strictly validate a native survey run from path.',
    'validate_sweep_config': 'Normalize a bounded native single-factor study; validate factors, values, seeds, variants, pairing restrictions and workload before fitting.',
    'run_sweep': 'Execute paired value/seed/variant cells; retain every outcome, aggregate evidence and invoke optional on_progress checkpoints.',
    'aggregate_sweep': 'Compute distributions, success/failure accounting and all-attempt study summaries from retained entries.',
    'build_comparison': 'Strictly compare two saved runs in raw or scale-preserving rigid alignment; retain source, pairing and metric evidence.',
    'validate_artifact': 'Strictly validate saved native study/comparison structure, retained children and derived evidence without fitting.',
    'save_artifact': 'Validate and write a complete study/comparison artifact through temporary-file replacement.',
    'load_artifact': 'Load finite native study/comparison JSON and strictly validate it.',
    'table_csv': 'Return native CSV text containing this module’s saved run, attempt, study or comparison table; per-observation study exports use their separate service route.',
    'mark_import': 'Mark imported unfinished work conservatively; do not resume a job or alter retained optimizer outcomes.',
    'validate_empty_sweep': 'Validate imported empty/incomplete sweep envelopes through the supplied native normalization and artifact validators.',
    'split': 'Separate native config/options into a version-1 workspace draft; move assumed sigma into assumptions and numerical settings into numerical.',
    'normalize': 'Validate a version-1 workspace draft and return (normalized draft, native config, native options); no generation or fit.',
    'study_payload': 'Translate a normalized workspace study into validated native study settings and its submission route.',
    'capabilities': 'Return six engine defaults, supported features, native schemas, study factors/default variants and application limits.',
    'register_workspace': 'Register workspace validation/configuration/export/submission routes using the shared history, worker and Library index.',
    'register_library': 'Register metadata query, preview, status and rebuild routes; return the LibraryIndex.',
    'register_m7': 'Register survey fitting, import/export, comparison and uncertainty routes with optional shared job state and save callback.',
    'parameter_count': 'Return the number of free coordinates under the selected map/trajectory parameterization.',
    'pack': 'Convert physical trajectory and beacon XYZ arrays into the problem coordinate vector, checking constraints; project permits supported feasibility projection.',
    'unpack': 'Convert a model parameter vector into physical trajectory and beacon XYZ arrays.',
    'geometry': 'Evaluate physical trajectory and beacon geometry represented by a parameter vector.',
    'physical_parameters': 'Convert solver h/q coordinates to the underlying physical metre parameter vector.',
    'disclosure': 'Return height coordinate, bounds, physical units and objective/branch metadata for this solver problem.',
    'encode': 'Map strictly interior physical coordinates into unconstrained logarithmic LM coordinates; reject boundary starts.',
    'decode': 'Map unconstrained LM coordinates to physical values and diagonal derivative; reject overflow or lost strict interior.',
    'refresh': 'Inventory source JSON and update disposable indexed metadata, preserving authoritative source files.',
    'query': 'Return bounded filtered/sorted/paginated metadata and facets; does not open strict scientific records or fit.',
    'preview': 'Return indexed metadata/provenance for an exact Library key, or None if unknown.',
    'rebuild': 'Rebuild the disposable Library cache from retained JSON; does not modify scientific source records.',
}

ARGUMENTS = {
    'config': 'Native physical generation settings, or native study settings in sweep modules; defaults and accepted fields are model-specific.',
    'options': 'Native estimator/numerical options; workspace assumptions and numerical sections are merged before calling the native model.',
    'draft': 'Complete version-1 workspace configuration object (see input reference).',
    'engine': 'Explicit planar/timing/spatial/solver/robust/survey model key.',
    'experiment / exp': 'Native experiment record: schema_version, normalized config, estimator_input, separate truth/reference and provenance.',
    'observations': 'List of measured-range records with epoch, zero-based beacon_id, range_m, sigma_m and assumed_time_s; actual/delivery fields are retained provenance.',
    'times_s': 'Strictly increasing finite estimator epoch/cycle times in seconds. Interpolation is constructed from these times and options.',
    'display_times_s': 'Optional display/evaluation sampling times in seconds; separate from acquisition events and fitted knots.',
    'surveyed_beacons': 'Explicit finite beacon-count × 3 map in metres for known-map mode; forbidden as hidden knowledge in joint fitting.',
    'beacon_count': 'Explicit integer count, generally 3–8; required where missing observations prevent inferring the physical map size.',
    'initial_geometries': 'Optional list of retained physical trajectory/beacon starts, one per configured attempt; subject to compatibility validation.',
    'parameters / x / x0 / u': 'Parameter/start vectors in the function’s model coordinates; u denotes unconstrained LM coordinates.',
    'problem': 'Validated RangeProblem/TrajectoryProblem/HeightProblem/SolverProblem, containing model-specific packing, interpolation, weights and constraints.',
    'mask': 'Optional retained-observation Boolean mask for rejection; rows removed by acquisition/dropout are absent before this mask.',
    'augmented': 'If true, include supported prior rows when inspecting local Jacobian rank.',
    'estimate / truth': 'Physical trajectory/beacon geometry dictionaries for evaluation; truth is kept outside measurement-only fitting.',
    'run / left_run / right_run': 'Complete validated saved-run records, including experiment, options and all attempts.',
    'artifact / sweep / data': 'Native saved payload appropriate to the module; use strict native loaders/validators before inspection.',
    'alignment': 'raw or aligned rigid comparison; scale remains 1.',
    'path': 'Filesystem path to the native JSON destination/source; save operations create or replace files.',
    'on_progress': 'Optional callable receiving the latest study artifact after a completed entry for checkpointing.',
    'fit_callback': 'Optional alternate fitting callable used by the spatial evaluation wrapper; receives its measurement-only fit inputs.',
    'survey': 'Explicit world/metre declaration with fixed/prior selected-coordinate blocks; see survey input reference.',
    'assumptions': 'Optional uncertainty override object, not replacement measurement sigmas.',
    'start_index': 'Zero-based saved attempt ordinal; None uses the run’s selected_start.',
    'converged': 'Whether the inspected attempt converged; nonconvergence withholds conditional intervals.',
    'rtol / rank_rtol': 'Relative singular-value tolerance used for local rank classification.',
    'lower / upper': 'Coordinate bound arrays, with infinities for unbounded sides; LM rejects two-sided finite bounds.',
    'loss / scale / residual_sigma': 'Robust loss key, positive scale in sigma units, and standardized range residual vector.',
    'app / directory / artifacts': 'Flask application and local run/artifact storage directories for route registration.',
    'executor / jobs / lock / job_lock': 'Shared background executor, job-state dictionary and synchronization locks.',
    'library / cache_path': 'LibraryIndex used for authoritative source resolution, or optional disposable SQLite cache path.',
    'bundled_root / on_saved': 'Optional reference-evidence directory or callback to invalidate saved-history metadata after writing.',
    '**options': 'Model-specific native options expanded as keywords; accepted fields are in the input reference and exact normalized defaults.',
    '**params': 'Library metadata query: q, type, status, model, source, sort, page, page_size, view and parent; see Library controls in the input reference.',
    'mode / initialization / starts / seed / max_nfev': 'Native estimator controls with the same meanings as workspace assumptions/numerical fields; exact low-level defaults appear in the signature.',
    'timing_model / knot_spacing_s / prior_sigma_m': 'Timing approximation, trajectory resolution in seconds and motion-prior SD in metres; equivalent workspace assumptions are documented in the input reference.',
    'cfg / opts / normalized': 'Already normalized native generation settings, estimator options or workspace settings; obtain them with the matching normalizer.',
    'trajectory / beacons / points / initial': 'Finite physical XYZ trajectory, beacon or point-cloud arrays in metres; initial is a retained starting geometry or model vector according to its caller.',
    'matrix / n / count': 'Numerical matrix and parameter/row/point count required by the local linear-algebra helper.',
    'basis / tag_entries / beacon_entries': 'Coordinate basis arrays and parameter-entry mappings used to propagate local uncertainty to physical geometry.',
    'identifier / ids / key': 'Server-owned source/job identifier, ID collection, or exact authoritative Library key; do not substitute filesystem paths.',
    'decisions / records': 'Fitted per-range weight/rejection decisions and separate injected contamination reference records for evaluation.',
    'project': 'Allow supported projection of supplied physical geometry into the feasible model before packing; false validates it as supplied.',
    'schema / kind / envelope': 'Native schema version, artifact kind and saved envelope used by lifecycle/import validation.',
    'normalize_config / validate_artifact': 'Native normalization/strict-validation callables supplied to generic lifecycle validation.',
    'value': 'Configuration subobject, numeric value or JSON node under normalization; function purpose identifies its expected shape.',
    '_validate': 'Internal comparison validation switch; keep the default true when calling outside already validated internal paths.',
}


def flatten(value, prefix=''):
    for key, item in value.items():
        path = f'{prefix}.{key}' if prefix else key
        if isinstance(item, dict):
            yield from flatten(item, path)
        else:
            yield path, item


def cell(value):
    return str(value).replace('|', '&#124;').replace('\n', ' ')


def build_inputs(catalog, models):
    lines = ['# Input reference', '', 'Generated by `scripts/build_user_docs.py` from the GUI help catalog and normalized model defaults. Rebuild after changing either. See [the user guide](USER_GUIDE.md) for workflows and examples.', '',
             '## Configuration envelope', '', '| Key | Meaning |', '|---|---|',
             '| `workspace_version` | Integer `1`; selects the shared draft format, distinct from native run schema_version. |',
             '| `engine` | Explicit `planar`, `timing`, `spatial`, `solver`, `robust` or `survey`. Selecting a different GUI model loads its defaults. |',
             '| `physical`, `assumptions`, `numerical` | Objects holding the generation, fitting and algorithm fields below. |',
             '| `observation_source.kind` | `generate` (default) or `saved`; saved requires exact compatible physical config and retained sigmas. |',
             '| `observation_source.key` | Exact authoritative Library key for saved reuse, e.g. `run:<id>` or an artifact child key returned by Library. Required for saved; not embedded observations. |',
             '| `study.kind` | `single` (default) or `parameter`. Parameter requires generate and a native study engine. |',
             '| `study.factor` | Model-supported factor key; see study-factor table in the guide. |',
             '| `study.variants` | Native uniquely labeled variant array, or omitted for defaults; timing forbids custom variants. See guide examples. |', '']
    defaults = {}
    for model, info in models.items():
        for path, value in flatten(info['defaults']):
            defaults.setdefault(path, {})[model] = value
    for group in ['physical', 'assumptions', 'numerical', 'study']:
        lines += [f'## {group.title()} fields', '', '| Exact input path | Meaning, units and accepted values | Normalized defaults and models |', '|---|---|---|']
        for path, text in catalog['paths'].items():
            if not path.startswith(group + '.'):
                continue
            grouped = {}
            for model, value in defaults.get(path, {}).items():
                grouped.setdefault(json.dumps(value, ensure_ascii=False), []).append(model)
            default = '; '.join(f"{', '.join(keys)}: `{value}`" for value, keys in grouped.items()) or 'Optional; only present when added. See explanation and model restrictions.'
            lines.append(f'| `{path}` | {cell(text)} | {cell(default)} |')
        lines += ['']
    lines += ['## Survey declaration', '', '`assumptions.survey` contains `frame: "world"`, `units: "m"`, `fixed: []` and `priors: []`. The survey default fixes beacon 0 XYZ to `[0,0,3]`; priors defaults to empty. Each array supports at most 24 rows. Partial survey requires at least one selected coordinate overall. No fixed/prior overlaps or duplicate selected coordinates are accepted.', '', '| Row key | Meaning |', '|---|---|']
    for key, text in catalog['survey'].items():
        lines.append(f'| `{ "mask" if key == "axis" else key}` | {cell(text)} |')
    lines += ['', 'The table Knowledge selector moves rows between `fixed` and `priors`; `kind` is a GUI selector, not a field inside a saved survey row. Prior covariance dimensions match the number of selected axes; unselected mean entries still must be finite.', '', '## Other interface inputs', '', '| Control ID | Behavior |', '|---|---|']
    for key, text in catalog['ids'].items():
        lines.append(f'| `{key}` | {cell(text)} |')
    lines += ['', '## Scene layers', '', '| Layer | Behavior |', '|---|---|']
    for key, text in catalog['layers'].items():
        lines.append(f'| `{key}` | {cell(text)} |')
    lines += ['', '## Optional field applicability', '', 'Custom `physical.path` fields are available in all six models. Explicit `physical.beacon_layout.coordinates_m` is available in spatial, solver, robust and survey. Survey rows and `assumptions.uncertainty` are exposed by survey defaults. Parameter-study values/seeds require a model with a native study engine (all except survey). Single-run robust and known-map uncertainty inspection is an explicit supported saved-result operation, separate from editing the survey draft.', '', '## Limits and native formats', '', 'The GUI allows 1–12 starts and 1–5000 evaluations per start. Studies allow at most 40 runs and 240 starts, with native factor/variant rules. Numeric fields are finite; JSON rejects NaN/Infinity. Some lower-level Python APIs permit larger budgets than the app. The normalized defaults below describe the app, not a promise that every cross-product of dropdown values is supported.', '', 'Native run schemas: planar 1.0; planar study/comparison 2.0; timing 3.0; spatial 4.0; solver 5.0; robust 6.0; survey 7.0 (retaining a schema-6 source experiment). Native `config` contains assumed_std_m; the workspace moves this into assumptions. Native estimator options merge workspace assumptions except assumed_std_m with numerical.', '', '## Complete default drafts', '', 'These are normalized defaults for each explicit model. The GUI initially uses robust or the retained browser-session draft. Optional custom paths/coordinates and parameter-study fields appear only after being added.']
    for model, info in models.items():
        lines += ['', f'### {model}', '', '```json', json.dumps(info['defaults'], indent=2, ensure_ascii=False), '```']
    (ROOT / 'docs/INPUT_REFERENCE.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def function_entries(tree):
    def visit(node, prefix=''):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + child.name
                if not isinstance(child, ast.ClassDef):
                    yield name, child
                yield from visit(child, name + '.')
            else:
                yield from visit(child, prefix)
    yield from visit(tree)


def purpose(name, node):
    leaf = name.split('.')[-1]
    if leaf in PURPOSE:
        return PURPOSE[leaf]
    doc = ast.get_docstring(node)
    if doc:
        return ' '.join(doc.split())
    if leaf.startswith('register_'):
        return 'Register native model routes with shared local history, background executor, job state and optional bundled reference records.'
    if '.' in name and not leaf.startswith('_'):
        return 'Internal callback or route handler: ' + leaf.replace('_', ' ') + '. See its enclosing function and the HTTP route table for request/return context.'
    calls = sorted({ast.unparse(n.func) for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))})
    return 'Internal ' + leaf.strip('_').replace('_', ' ') + ' helper. Uses ' + ', '.join('`' + s + '`' for s in calls[:5]) + (' among other calls.' if len(calls) > 5 else '.')


def build_functions():
    lines = ['# Function and HTTP reference', '', 'Generated from the current Python source by `scripts/build_user_docs.py`. The [user guide](USER_GUIDE.md) documents application features; [input reference](INPUT_REFERENCE.md) documents configuration variables. This appendix inventories every Python function, nested callback, method and HTTP decorator in `app.py` and `uwb/`, with exact source signatures. Leading-underscore functions and nested callbacks are implementation details, not stable user APIs. Follow source links for exact return structures and per-function validation.', '',
             '## Python usage', '', '```python', 'from uwb import m6', '', 'experiment = m6.generate_experiment({"noise_std_m": 0.02, "seed": 7})', 'run = m6.solve_experiment(experiment, {"loss": "huber", "starts": 2, "max_nfev": 500})', 'print(run["status"], run["selected_start"])', '```', '', 'Generation returns an experiment; solving returns a run and does not itself save it. Use the native strict save/load helpers for persistence. Measurement-only `build_problem`/`fit_observations` deliberately receive no truth. Known-map coordinates and declared survey priors are explicit knowledge; solve wrappers separately evaluate against truth. Sweep calls perform fitting and may be expensive; validate settings first. Normalizers/validators may raise ValueError (including ExperimentFormatError); save/load can also raise filesystem errors.', '',
             '## Shared argument vocabulary', '', 'Exact required/optional/keyword-only arguments and defaults are shown for each function below; `*` introduces keyword-only arguments. Repeated names have the following meaning; native option keys and all JSON configuration variables are in the input reference. `self` is the instance for a method.', '', '| Argument | Meaning |', '|---|---|']
    for name, text in ARGUMENTS.items():
        lines.append(f'| `{name}` | {text} |')
    routes = []
    files = [ROOT / 'app.py', *sorted((ROOT / 'uwb').glob('*.py'))]
    for path in files:
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        entries = list(function_entries(tree))
        if not entries:
            continue
        rel = path.relative_to(ROOT).as_posix()
        lines += ['', f'## {rel}', '', '| Function / exact signature | Purpose |', '|---|---|']
        for name, node in entries:
            sig = f'{name}({ast.unparse(node.args)})'
            if node.returns:
                sig += ' -> ' + ast.unparse(node.returns)
            lines.append(f'| [`{name}`](../{rel}#L{node.lineno}) — `{cell(sig)}` | {cell(purpose(name, node))} |')
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr in ('get', 'post', 'route', 'delete', 'put', 'patch') and decorator.args:
                    routes.append((decorator.func.attr.upper(), ast.unparse(decorator.args[0]), rel, name, node.lineno))
        aliases = [f'`{ast.unparse(node)}`' for node in tree.body if isinstance(node, ast.Assign) and isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name) and node.value.value.id in ('m3', 'm4', 'm5', 'm6', 'm7')]
        if aliases:
            lines += ['', 'Re-exported native aliases: ' + '; '.join(aliases) + '. They retain the referenced function signature and behavior.']
    lines += ['', '## HTTP routes', '', 'GET routes read metadata/native sources, export records, or poll jobs. POST route purpose follows the linked handler; run/sweep/study submissions perform explicit new computation, while validate, import, comparison and uncertainty routes use retained/configured data as described in the guide. Errors normally return JSON error text and HTTP 400; unknown IDs/keys return 404; background failures remain visible in saved records and job status. Consult handlers for exact payloads.', '',
              'The current shared entry points are GET `/api/workspace/capabilities`, POST `/api/workspace/validate`, `/api/workspace/configuration`, `/api/workspace/runs`, `/api/workspace/studies`, `/api/workspace/export/csv`, GET `/api/jobs/<identifier>` and the Library routes. Run/study submissions return a job ID (HTTP 202); poll jobs until completion/failure. Validate returns normalized configuration/native options, and native study settings when applicable. The [workspace API document](WORKSPACE.md) describes payload semantics.', '', '| Method | Route expression | Handler |', '|---|---|---|']
    for method, route, rel, name, line in routes:
        lines.append(f'| {method} | `{cell(route)}` | [`{name}`](../{rel}#L{line}) |')
    lines += ['', '## Browser modules', '', '| Module | Responsibilities / entry points |', '|---|---|',
              '| `web/workspace.js` | Shared draft rendering/validation, submit/poll lifecycle, source import/adoption, result layout/tabs, comparison inspection and drawer. Public `RangeLabWorkspace`: state, onRun, openRun, openArtifact, useConfiguration, tab, importSource, onComparison, download, comparisonTarget. |',
              '| `web/app.js` | Shared API client, selected run/start, base scene layers/camera, baseline diagnostics and exports. |',
              '| `web/library.js` | Metadata search/filter/page/preview, authoritative source opening, A/B selection, index refresh/rebuild and navigation state. |',
              '| `web/m2.js`–`web/m7.js` | Native retained-result render adapters, study/comparison tables/charts/exports, ping playback and survey/uncertainty inspection. Their historical forms are detached by the shared workspace. |',
              '| `web/help.js` | `RangeLabHelp.description(node,catalog)` resolves exact path, control ID, survey or layer explanations; `attach(root,catalog)` idempotently adds title and aria-describedby without replacing existing descriptions. Init decorates dynamically added fields and shows/dismisses hover/focus help. |',
              '| `web/input-help.json` | Shared GUI explanations used to generate the input reference; exact full paths distinguish similarly named fields. |', '', 'Scripts under `scripts/` are development, validation, benchmarking, audit or packaging tools; tests under `tests/` verify behavior. They are not additional GUI features. Read their module help before running evidence-generation scripts.']
    (ROOT / 'docs/FUNCTION_REFERENCE.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def inline(text):
    # Small, escaped renderer for the Markdown subset used by these local docs.
    parts = re.split(r'(`[^`]+`|\[[^\]]+\]\([^)]+\))', text)
    out = []
    for part in parts:
        if part.startswith('`') and part.endswith('`'):
            out.append('<code>' + html.escape(part[1:-1].replace('&#124;', '|')) + '</code>')
        elif (match := re.fullmatch(r'\[([^\]]+)\]\(([^)]+)\)', part)):
            label, url = match.groups()
            if url.endswith('.md') and not url.startswith(('http:', 'https:', '../')):
                url = Path(url).stem.lower().replace('_', '-') + '.html'
            if url.startswith(('http://', 'https://', '#')) or re.fullmatch(r'[a-z0-9-]+\.html', url):
                out.append(f'<a href="{html.escape(url, quote=True)}">{inline(label)}</a>')
            else:
                out.append(inline(label))
        else:
            out.append(re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', html.escape(part)))
    return ''.join(out)


def render(markdown):
    output, code, listing, table = [], None, None, False
    for line in markdown.splitlines() + ['']:
        if line.startswith('```'):
            if code is None:
                code = []
            else:
                output.append('<pre><code>' + html.escape('\n'.join(code)) + '</code></pre>'); code = None
            continue
        if code is not None:
            code.append(line); continue
        if not line.startswith('|') and table:
            output.append('</tbody></table></div>'); table = False
        item = re.match(r'^(?:- |\d+\. )(.*)', line)
        if not item and listing:
            output.append(f'</{listing}>'); listing = None
        if line.startswith('|'):
            cells = [c.strip() for c in line.strip('|').split('|')]
            if all(re.fullmatch(r'[-:]+', c) for c in cells):
                continue
            tag = 'td' if table else 'th'
            if not table:
                output.append('<div class="table-wrap"><table><tbody>'); table = True
            output.append('<tr>' + ''.join(f'<{tag}>{inline(c)}</{tag}>' for c in cells) + '</tr>')
        elif line.startswith('#'):
            heading, title = line.split(' ', 1); level = len(heading)
            anchor = re.sub(r'[^\w -]', '', title.lower()).replace(' ', '-')
            output.append(f'<h{level} id="{anchor}">{inline(title)}</h{level}>')
        elif item:
            if not listing:
                listing = 'ul' if line.startswith('- ') else 'ol'; output.append(f'<{listing}>')
            output.append('<li>' + inline(item.group(1)) + '</li>')
        elif line:
            output.append('<p>' + inline(line) + '</p>')
    return '\n'.join(output)


def build_html():
    # Include the existing scientific/workspace docs so local guide links work.
    for filename in ('USER_GUIDE.md', 'INPUT_REFERENCE.md', 'FUNCTION_REFERENCE.md', 'WORKSPACE.md', 'science/MATH_REVIEW.md', 'science/SURVEY_UNCERTAINTY.md'):
        path = ROOT / 'docs' / filename
        name = path.stem.lower().replace('_', '-')
        body = render(path.read_text(encoding='utf-8'))
        title = html.escape(path.stem.replace('_', ' ').title())
        page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RangeLab — {title}</title>
<style>body{{font:16px/1.65 system-ui,sans-serif;color:#203343;background:#f4f6f8;margin:0}}main{{max-width:1120px;margin:auto;padding:28px}}nav{{position:sticky;top:0;padding:12px 24px;background:#fff;border-bottom:1px solid #ccd6de;z-index:1;display:flex;gap:22px;flex-wrap:wrap}}a{{color:#07677a}}h1,h2,h3{{line-height:1.25;scroll-margin-top:80px}}h2{{margin-top:2.5em}}code{{font-size:.88em;background:#e5ebef;padding:2px 4px;border-radius:3px;overflow-wrap:anywhere}}pre{{background:#172b3a;color:#edf5fa;padding:18px;overflow:auto;border-radius:6px}}pre code{{background:none;color:inherit;padding:0;overflow-wrap:normal}}.table-wrap{{overflow-x:auto}}table{{border-collapse:collapse;background:white;width:100%;font-size:14px}}td,th{{border:1px solid #cdd8df;padding:10px;text-align:left;vertical-align:top}}th{{background:#dfeaf0}}li{{margin:.45em 0}}@media print{{nav{{position:static}}body{{background:white}}main{{padding:0}}pre{{white-space:pre-wrap}}}}</style></head>
<body><nav aria-label="Documentation"><a href="/">← Experiment</a><a href="/user-guide.html">User guide</a><a href="/input-reference.html">All inputs</a><a href="/function-reference.html">Functions and API</a></nav><main>{body}</main></body></html>
'''
        (ROOT / 'web' / f'{name}.html').write_text(page, encoding='utf-8')


if __name__ == '__main__':
    help_catalog = json.loads((ROOT / 'web/input-help.json').read_text(encoding='utf-8'))
    build_inputs(help_catalog, capabilities()['models'])
    build_functions()
    build_html()
    print('Built input/function references and local HTML documentation; no fits performed.')
