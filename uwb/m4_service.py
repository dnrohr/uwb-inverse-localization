"""Local M4 jobs and artifact endpoints; legacy handlers remain independent."""
from pathlib import Path
import json
import uuid

from flask import jsonify, request, Response
from . import m4, m4_sweeps
from .lifecycle import validate_empty_sweep, mark_import
from .experiments import save_json, load_json, _replace_with_retry


def register_m4_routes(app, directory, artifacts, executor, jobs, lock, *, bundled_root=None):
    def run_path(identifier):
        if not isinstance(identifier, str) or len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
            raise ValueError('Invalid identifier')
        return directory/(identifier+'.json')

    def artifact_path(identifier):
        return artifacts/run_path(identifier).name

    def pending(path, data):
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(data, allow_nan=False), encoding='utf-8')
        _replace_with_retry(temporary, path)

    def retain_runs(data):
        for entry in data.get('entries', []):
            run = entry.get('run')
            if run:
                run['id'] = uuid.uuid5(uuid.NAMESPACE_URL, f"uwb-m4/sweep/{data['id']}/{entry['index']}").hex
                save_json(run_path(run['id']), run)

    def execute(identifier, experiment, options):
        run = {'schema_version': '4.0', 'id': identifier, 'status': 'running',
               'experiment': experiment, 'options': options, 'starts': [], 'diagnostics': {}}
        try:
            run = m4.solve_experiment(experiment, options)
            run['id'] = identifier
            save_json(run_path(identifier), run)
            with lock:
                jobs[identifier] = {'status': 'complete', 'run': run}
        except Exception as exc:
            run['error'] = f'{type(exc).__name__}: {exc}'
            if run.get('selected_start') is None:
                run['status'] = 'failed'
            else:
                run['infrastructure_status'] = 'failed'
                run.setdefault('diagnostics', {}).setdefault('warnings', []).append(run['error'])
            try:
                save_json(run_path(identifier), run)
            except (OSError, ValueError) as error:
                run['persistence_error'] = str(error)
            with lock:
                jobs[identifier] = {'status': 'failed', 'run': run, 'error': run['error']}

    @app.post('/api/m4/runs')
    def submit_m4():
        body = request.get_json()
        if not isinstance(body, dict) or not isinstance(body.get('config', {}), dict) or not isinstance(body.get('options', {}), dict):
            raise ValueError('Expected configuration and options objects')
        options = m4.validate_options(body.get('options', {}))
        if options['starts'] > 12 or options['max_nfev'] > 5000:
            raise ValueError('Application limits: 12 starts and 5000 evaluations per start')
        experiment = m4.generate_experiment(body.get('config', {}))
        identifier = uuid.uuid4().hex
        save_json(run_path(identifier), {'schema_version': '4.0', 'id': identifier,
                  'experiment': experiment, 'options': options, 'starts': [], 'diagnostics': {}, 'status': 'running'})
        with lock:
            jobs[identifier] = {'status': 'running'}
        executor.submit(execute, identifier, experiment, options)
        return jsonify(id=identifier), 202

    def execute_sweep(identifier, config):
        latest = {'schema_version': '4.0', 'artifact_type': 'geometry_sweep', 'id': identifier,
                  'status': 'running', 'config': config, 'entries': []}
        try:
            def checkpoint(data):
                nonlocal latest
                data['id'] = identifier
                latest = data
                retain_runs(data)
                m4_sweeps.save_artifact(artifact_path(identifier), data)
                with lock:
                    jobs[identifier] = {'status': 'running', 'completed_runs': len(data['entries'])}
            latest = m4_sweeps.run_sweep(config, on_progress=checkpoint)
            latest['id'] = identifier
            retain_runs(latest)
            m4_sweeps.save_artifact(artifact_path(identifier), latest)
            with lock:
                jobs[identifier] = {'status': 'complete', 'artifact': latest}
        except Exception as exc:
            latest.update(status='failed', error=f'{type(exc).__name__}: {exc}')
            try:
                pending(artifact_path(identifier), latest)
            except OSError as error:
                latest['persistence_error'] = str(error)
            with lock:
                jobs[identifier] = {'status': 'failed', 'artifact': latest, 'error': latest['error']}

    @app.post('/api/m4/sweeps')
    def submit_m4_sweep():
        config = m4_sweeps.validate_sweep_config(request.get_json())
        if config['options']['starts'] > 12 or config['options']['max_nfev'] > 5000:
            raise ValueError('Application limits: 12 starts and 5000 evaluations per start')
        identifier = uuid.uuid4().hex
        pending(artifact_path(identifier), {'schema_version': '4.0', 'artifact_type': 'geometry_sweep',
                'id': identifier, 'status': 'running', 'config': config, 'entries': []})
        with lock:
            jobs[identifier] = {'status': 'running'}
        executor.submit(execute_sweep, identifier, config)
        return jsonify(id=identifier), 202

    @app.get('/api/m4/sweeps')
    def list_m4_sweeps():
        rows = []
        for path in sorted(artifacts.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                if data.get('artifact_type') != 'geometry_sweep':
                    continue
                with lock:
                    active = jobs.get(path.stem)
                rows.append({'id': path.stem, 'factor': data['config']['factor'], 'entry_count': len(data.get('entries', [])), 'start_count': len(data.get('start_table', [])),
                    'status': 'interrupted' if data.get('status') == 'running' and active is None else data.get('status')})
            except (ValueError, OSError, KeyError):
                continue
        return jsonify(rows)

    def read_sweep(identifier):
        path = artifact_path(identifier)
        if not path.exists():
            raise ValueError('Unknown geometry sweep')
        with lock:
            active = jobs.get(identifier)
        if active and active.get('artifact'):
            return active['artifact']
        raw = json.loads(path.read_text(encoding='utf-8'))
        candidates = list(path.parent.glob(path.name+'.*.tmp'))
        fixed = path.with_suffix('.json.tmp')
        if fixed.exists():
            candidates.append(fixed)
        for temporary in sorted(candidates, key=lambda p: p.stat().st_mtime):
            try:
                data = m4_sweeps.load_artifact(temporary)
                if len(data.get('entries', [])) >= len(raw.get('entries', [])):
                    raw = data
            except (ValueError, OSError):
                pass
        if raw.get('entries'):
            m4_sweeps.validate_artifact(raw)
        else:
            validate_empty_sweep(raw, '4.0', 'geometry_sweep', m4_sweeps.validate_sweep_config, m4_sweeps.validate_artifact)
        if raw.get('status') == 'running' and active is None:
            raw.update(status='failed', saved_status='running', error='Interrupted geometry sweep; completed attempts retained, no implicit restart.')
        return raw

    @app.get('/api/m4/sweeps/<identifier>')
    def reopen_m4_sweep(identifier):
        return jsonify(read_sweep(identifier))

    @app.get('/api/m4/sweeps/<identifier>/csv')
    def export_m4_csv(identifier):
        return Response(m4_sweeps.table_csv(read_sweep(identifier)), mimetype='text/csv')

    @app.post('/api/m4/import')
    def import_m4():
        data = request.get_json()
        if not isinstance(data, dict) or data.get('schema_version') != '4.0':
            raise ValueError('Expected a version 4.0 run or geometry sweep')
        mark_import(data)
        identifier = uuid.uuid4().hex
        data['id'] = identifier
        if data.get('artifact_type') == 'geometry_sweep':
            m4_sweeps.validate_artifact(data)
            retain_runs(data)
            m4_sweeps.save_artifact(artifact_path(identifier), data)
            return jsonify(id=identifier, artifact=data)
        m4.validate_run(data)
        save_json(run_path(identifier), data)
        return jsonify(id=identifier, run=data)

    if bundled_root:
        summaries = sorted(Path(bundled_root).glob('acceptance_*/acceptance_summary.json'))
        if summaries:
            root = summaries[-1].parent
            for source in (root/'demo_runs').glob('*.json'):
                identifier = uuid.uuid5(uuid.NAMESPACE_URL, 'uwb-m4/demo/'+source.stem).hex
                if not run_path(identifier).exists():
                    run = load_json(source)
                    run.update(id=identifier, reference_name='M4_'+source.stem)
                    save_json(run_path(identifier), run)
            for source in (root/'sweeps').glob('*.json'):
                identifier = uuid.uuid5(uuid.NAMESPACE_URL, 'uwb-m4/sweep/'+source.stem).hex
                if not artifact_path(identifier).exists():
                    data = m4_sweeps.load_artifact(source)
                    data['id'] = identifier
                    retain_runs(data)
                    m4_sweeps.save_artifact(artifact_path(identifier), data)

