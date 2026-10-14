"""Local-only experiment server. Solves execute outside HTTP request handlers."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
import uuid
import json

from flask import Flask, jsonify, request, send_from_directory, Response
from plotly.offline import get_plotlyjs
from uwb.experiments import generate_experiment, save_json, load_json, path_metadata, _replace_with_retry
from uwb.estimation import solve_experiment
from uwb.sweeps import (run_sweep, validate_sweep_config, build_comparison,
                        save_artifact, load_artifact, validate_artifact)

ROOT = Path(__file__).resolve().parent


def create_app(run_dir=None):
    app = Flask(__name__, static_folder=str(ROOT / 'web'), static_url_path='')
    app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
    directory = Path(run_dir or ROOT / 'runs')
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = directory / 'artifacts'
    artifacts.mkdir(parents=True, exist_ok=True)
    # Bundled acceptance runs are copied once, never solved during startup.
    if run_dir is None:
        for reference in (ROOT / 'evidence' / 'reference_runs').glob('*.json'):
            identifier = uuid.uuid5(uuid.NAMESPACE_URL, 'uwb-reference/' + reference.stem).hex
            target = directory / (identifier + '.json')
            if not target.exists():
                data = load_json(reference)
                data['id'] = identifier
                data['reference_name'] = reference.stem
                save_json(target, data)
    executor = ThreadPoolExecutor(max_workers=1)
    jobs, lock = {}, Lock()

    @app.get('/')
    def index():
        return send_from_directory(ROOT / 'web', 'index.html')

    @app.get('/vendor/plotly.min.js')
    def plotly_bundle():
        return Response(get_plotlyjs(), mimetype='application/javascript')

    @app.get('/api/scenarios')
    def scenarios():
        return jsonify(['informative', 'straight_line', 'narrow_coverage', 'nearly_collinear'])

    def path_for(identifier):
        if not isinstance(identifier, str) or len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
            raise ValueError('Invalid run identifier')
        return directory / (identifier + '.json')

    def artifact_path(identifier):
        path_for(identifier)  # Validate before using any supplied path component.
        return artifacts / (identifier + '.json')

    def save_pending(path, data):
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(data, allow_nan=False), encoding='utf-8')
        _replace_with_retry(temporary, path)

    def retain_sweep_runs(data):
        for entry in data.get('entries', []):
            run = entry.get('run')
            if run:
                # Server-owned IDs prevent imports from overwriting unrelated history.
                run['id'] = uuid.uuid5(uuid.NAMESPACE_URL,
                                     f"uwb-sweep/{data['id']}/{entry['index']}").hex
                save_json(path_for(run['id']), run)

    if run_dir is None:
        for reference in (ROOT / 'evidence' / 'm2' / 'path_runs').glob('*.json'):
            data = load_json(reference)
            data.setdefault('id', uuid.uuid5(uuid.NAMESPACE_URL, 'uwb-m2/path/' + reference.stem).hex)
            data['reference_name'] = 'M2_' + reference.stem
            if not path_for(data['id']).exists():
                save_json(path_for(data['id']), data)
        for folder in ('sweeps', 'comparisons'):
            for reference in (ROOT / 'evidence' / 'm2' / folder).glob('*.json'):
                data = load_artifact(reference)
                data.setdefault('id', uuid.uuid5(uuid.NAMESPACE_URL, 'uwb-m2/' + folder + '/' + reference.stem).hex)
                if not artifact_path(data['id']).exists():
                    retain_sweep_runs(data)
                    save_artifact(artifact_path(data['id']), data)

    def execute_sweep(identifier, config):
        latest = None
        try:
            def checkpoint(data):
                nonlocal latest
                data['id'] = identifier
                latest = data
                retain_sweep_runs(data)
                save_artifact(artifact_path(identifier), data)
                with lock:
                    jobs[identifier] = {'status': 'running',
                                        'completed_runs': len(data.get('entries', []))}
            data = run_sweep(config, on_progress=checkpoint)
            data['id'] = identifier
            latest = data
            retain_sweep_runs(data)
            save_artifact(artifact_path(identifier), data)
            with lock:
                jobs[identifier] = {'status': 'complete', 'artifact': data}
        except Exception as exc:
            # Preserve the accepted input even if the numerical wrapper itself fails.
            path = artifact_path(identifier)
            data = latest or (json.loads(path.read_text(encoding='utf-8')) if path.exists() else {
                'schema_version': '2.0', 'artifact_type': 'sweep', 'id': identifier,
                'config': config, 'entries': []})
            data.update(status='failed', error=f'{type(exc).__name__}: {exc}')
            with lock:
                jobs[identifier] = {'status': 'failed', 'artifact': data, 'error': data['error']}
            try:
                save_pending(artifact_path(identifier), data)
            except OSError as persistence_error:
                # The atomic temporary file still contains the complete snapshot.
                data['persistence_error'] = f'{type(persistence_error).__name__}: {persistence_error}'
                with lock:
                    jobs[identifier] = {'status': 'failed', 'artifact': data, 'error': data['error'],
                                        'persistence_error': data['persistence_error']}

    @app.post('/api/sweeps')
    def submit_sweep():
        body = request.get_json()
        if not isinstance(body, dict):
            raise ValueError('Expected a sweep configuration object')
        config = validate_sweep_config(body)
        identifier = uuid.uuid4().hex
        pending = {'schema_version': '2.0', 'artifact_type': 'sweep', 'id': identifier,
                   'status': 'running', 'config': config, 'entries': []}
        save_pending(artifact_path(identifier), pending)
        with lock:
            jobs[identifier] = {'status': 'running'}
        executor.submit(execute_sweep, identifier, config)
        return jsonify(id=identifier), 202

    @app.post('/api/comparisons')
    def compare_saved():
        body = request.get_json()
        if not isinstance(body, dict) or not isinstance(body.get('run_ids'), list) or len(body['run_ids']) != 2:
            raise ValueError('Select exactly two saved run IDs')
        runs = []
        for identifier in body['run_ids']:
            path = path_for(identifier)
            if not path.exists():
                raise ValueError('Unknown saved run')
            runs.append(load_json(path))
        data = build_comparison(*runs, alignment=body.get('alignment', 'aligned'))
        data['id'] = uuid.uuid4().hex
        save_artifact(artifact_path(data['id']), data)
        return jsonify(id=data['id'], artifact=data)

    @app.get('/api/sweeps')
    @app.get('/api/comparisons')
    def list_artifacts():
        kind = 'sweep' if request.path.endswith('sweeps') else 'comparison'
        rows = []
        for path in sorted(artifacts.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                if data.get('artifact_type') == kind:
                    with lock:
                        active_job = jobs.get(path.stem)
                    status = 'interrupted' if data.get('status') == 'running' and active_job is None else data.get('status', 'complete')
                    rows.append({'id': path.stem, 'status': status,
                                 'factor': data.get('config', {}).get('factor'), 'kind': kind,
                                 'label': ' ↔ '.join(str(run.get('reference_name') or str(run.get('id') or 'run')[:8]) for run in data.get('runs', [])) + (f" · {data.get('alignment')}" if kind == 'comparison' else '')})
            except (ValueError, OSError):
                continue
        return jsonify(rows)

    @app.get('/api/sweeps/<identifier>')
    @app.get('/api/comparisons/<identifier>')
    def reopen_artifact(identifier):
        path = artifact_path(identifier)
        if not path.exists():
            return jsonify(error='Unknown saved artifact'), 404
        with lock:
            latest_job = jobs.get(identifier)
        if latest_job and latest_job.get('status') == 'failed' and isinstance(latest_job.get('artifact'), dict):
            return jsonify(latest_job['artifact'])
        raw = json.loads(path.read_text(encoding='utf-8'))
        def disclose_interruption(data):
            if data.get('status') == 'running' and latest_job is None:
                data = dict(data)
                data.update(status='failed', saved_status='running',
                            error='Interrupted sweep: no worker is running. Completed attempts remain saved; unattempted cells have not been solved.')
            return data
        temporary = path.with_suffix('.json.tmp')
        if temporary.exists():
            try:
                checkpoint = load_artifact(temporary)
                if len(checkpoint.get('entries', [])) >= len(raw.get('entries', [])):
                    return jsonify(disclose_interruption(checkpoint))
            except (ValueError, OSError):
                pass  # An incomplete temp file cannot replace validated saved data.
        if raw.get('status') in ('running', 'failed') and not raw.get('entries'):
            return jsonify(disclose_interruption(raw))
        return jsonify(disclose_interruption(load_artifact(path)))

    @app.post('/api/artifacts/import')
    def import_artifact():
        data = request.get_json()
        if not isinstance(data, dict) or data.get('artifact_type') not in ('sweep', 'comparison'):
            raise ValueError('Expected a saved sweep or comparison')
        identifier = uuid.uuid4().hex
        data['id'] = identifier
        validate_artifact(data)
        retain_sweep_runs(data)
        save_artifact(artifact_path(identifier), data)
        return jsonify(id=identifier, artifact=data)

    def execute(identifier, experiment, options):
        try:
            run = solve_experiment(experiment, options)
            run['id'] = identifier
            run['path_motion'] = path_metadata(experiment['config'])
            save_json(path_for(identifier), run)
            with lock:
                jobs[identifier] = {'status': 'complete', 'run': run}
        except Exception as exc:
            run = {'schema_version': '1.0', 'id': identifier, 'status': 'failed',
                   'experiment': experiment, 'options': options, 'starts': [],
                   'error': f'{type(exc).__name__}: {exc}'}
            save_json(path_for(identifier), run)
            with lock:
                jobs[identifier] = {'status': 'failed', 'run': run, 'error': run['error']}

    @app.post('/api/runs')
    def submit():
        body = request.get_json()
        if not isinstance(body, dict):
            raise ValueError('Expected configuration and options as a JSON object')
        config, options = body.get('config', {}), body.get('options', {})
        if not isinstance(config, dict) or not isinstance(options, dict):
            raise ValueError('Configuration and options must be objects')
        json.dumps(body, allow_nan=False)
        if set(options) - {'mode', 'initialization', 'starts', 'seed', 'max_nfev'}:
            raise ValueError('Unsupported solver option')
        seed = options.get('seed', 19)
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError('Initialization seed must be a nonnegative integer')
        if options.get('mode', 'joint') not in ('joint', 'known_map'):
            raise ValueError('Unsupported map mode')
        if options.get('initialization', 'independent') not in ('independent', 'truth_near'):
            raise ValueError('Unsupported initialization')
        starts = options.get('starts', 3)
        if isinstance(starts, bool) or not isinstance(starts, int) or not 1 <= starts <= 12:
            raise ValueError('Use 1 through 12 starts')
        evaluations = options.get('max_nfev', 2000)
        if isinstance(evaluations, bool) or not isinstance(evaluations, int) or not 1 <= evaluations <= 5000:
            raise ValueError('Use 1 through 5000 objective evaluations per start')
        experiment = generate_experiment(config)
        cfg = experiment['config']
        if not .01 <= cfg['duration_s'] <= 3600:
            raise ValueError('Application duration is 0.01 through 3600 seconds')
        if any(s > 100 for s in cfg['noise_std_m']) or any(not 1e-6 <= s <= 1000 for s in cfg['assumed_std_m']):
            raise ValueError('Application noise is 0–100 m; assumed sigma is 1e-6–1000 m')
        identifier = uuid.uuid4().hex
        save_json(path_for(identifier), {'schema_version': '1.0', 'id': identifier,
                  'experiment': experiment, 'options': options, 'starts': [], 'status': 'running'})
        with lock:
            jobs[identifier] = {'status': 'running'}
        executor.submit(execute, identifier, experiment, options)
        return jsonify(id=identifier), 202

    @app.get('/api/jobs/<identifier>')
    def job(identifier):
        path_for(identifier)
        with lock:
            result = jobs.get(identifier)
        if result is None:
            return jsonify(error='Unknown job'), 404
        return jsonify(result)

    @app.get('/api/runs')
    def list_runs():
        rows = []
        for path in sorted(directory.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = load_json(path)
            except (ValueError, OSError) as exc:
                rows.append({'id': path.stem, 'status': 'unreadable', 'scenario': 'Invalid saved file',
                             'mode': 'unknown', 'error': str(exc)})
                continue
            if 'experiment' not in data:
                continue  # Standalone generator exports are not fitted run envelopes.
            rows.append({'id': path.stem, 'status': data.get('status'),
                         'scenario': data['experiment']['config']['scenario'],
                         'path_type': data['experiment']['config'].get('path', {}).get('type'),
                         'reference_name': data.get('reference_name'),
                         'mode': data.get('options', {}).get('mode', 'joint')})
        return jsonify(rows)

    @app.get('/api/runs/<identifier>')
    def reopen(identifier):
        path = path_for(identifier)
        if not path.exists():
            return jsonify(error='Unknown saved run'), 404
        return jsonify(load_json(path))

    @app.post('/api/import')
    def import_run():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError('Expected a saved-run JSON object')
        if data.get('schema_version') != '1.0' or not isinstance(data.get('experiment'), dict):
            raise ValueError('Expected a version 1.0 saved run with experiment')
        if not isinstance(data.get('starts'), list):
            raise ValueError('Saved run must contain per-start outcomes')
        identifier = uuid.uuid4().hex
        data['id'] = identifier
        save_json(path_for(identifier), data)
        return jsonify(id=identifier, run=data)

    @app.errorhandler(ValueError)
    def bad_request(exc):
        return jsonify(error=str(exc)), 400

    return app


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5050)
    args = parser.parse_args()
    create_app().run(host='127.0.0.1', port=args.port, debug=False)
