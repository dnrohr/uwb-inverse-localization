"""Versioned workspace adapters. Native engines and saved records stay authoritative."""
from __future__ import annotations

import copy
import json
import uuid
import csv
import io
from flask import request, jsonify, Response
from . import experiments, estimation, m3, m4, m5, m6, m7
from . import sweeps, m3_sweeps, m4_sweeps, m5_sweeps, m6_sweeps

ENGINES = {
    'planar': (experiments, estimation, 'Planar synchronized ranges', '1.0'),
    'timing': (m3, m3, 'Timestamp-aware trajectory', '3.0'),
    'spatial': (m4, m4, 'Spatial height models', '4.0'),
    'solver': (m5, m5, 'Solver and height parameterization', '5.0'),
    'robust': (m6, m6, 'Contaminated ranges and robust estimation', '6.0'),
    'survey': (m6, m7, 'Partial surveyed-world knowledge', '7.0'),
}
NUMERICAL = {'solver', 'height_parameterization', 'initialization', 'initialization_error_m',
             'algebraic_physical_tolerance', 'starts', 'seed', 'max_nfev'}
STUDIES = {'planar': (sweeps, '/api/sweeps'), 'timing': (m3_sweeps, '/api/m3/sweeps'),
           'spatial': (m4_sweeps, '/api/m4/sweeps'), 'solver': (m5_sweeps, '/api/m5/sweeps'),
           'robust': (m6_sweeps, '/api/m6/sweeps')}


def split(engine, config, options):
    config, options = copy.deepcopy(config), copy.deepcopy(options)
    sigma = config.pop('assumed_std_m', .05)
    return {'workspace_version': 1, 'engine': engine, 'physical': config,
            'observation_source': {'kind': 'generate'},
            'assumptions': {'assumed_std_m': sigma, **{k: v for k, v in options.items() if k not in NUMERICAL}},
            'numerical': {k: v for k, v in options.items() if k in NUMERICAL},
            'study': {'kind': 'single'}}


def normalize(draft):
    if not isinstance(draft, dict) or type(draft.get('workspace_version')) is not int or draft.get('workspace_version') != 1:
        raise ValueError('Expected workspace_version 1 configuration')
    if set(draft) - {'workspace_version', 'engine', 'physical', 'assumptions', 'numerical', 'observation_source', 'study'}:
        raise ValueError('Unsupported workspace configuration fields')
    engine = draft.get('engine')
    if engine not in ENGINES:
        raise ValueError('Choose an explicit supported numerical model')
    generator, fitter, _, _ = ENGINES[engine]
    for key in ('physical', 'assumptions', 'numerical', 'observation_source', 'study'):
        if not isinstance(draft.get(key, {}), dict):
            raise ValueError(f'{key} must be an object')
    assumptions = copy.deepcopy(draft.get('assumptions', {}))
    physical = copy.deepcopy(draft.get('physical', {}))
    if 'assumed_std_m' in physical:
        raise ValueError('Assumed uncertainty belongs in estimator assumptions')
    config = {**physical, 'assumed_std_m': assumptions.pop('assumed_std_m', .05)}
    numerical = draft.get('numerical', {})
    if set(numerical) - NUMERICAL or set(assumptions) & NUMERICAL:
        raise ValueError('Numerical method and physical assumptions must be separate')
    options = {**assumptions, **numerical}
    if engine == 'planar':
        config = experiments._normalise_config(config)
        # The existing sweep validator validates baseline options without solving.
        checked = sweeps.validate_sweep_config({'experiment': config, 'options': options,
                   'factor': 'noise_std_m', 'values': [0.], 'seeds': [7],
                   'variants': [{'label': 'configured', 'max_nfev': options.get('max_nfev', 2000)}]})
        options = checked['options']
    else:
        config = generator.normalize_config(config)
        options = fitter.validate_options(options)
    if options['starts'] > 12 or options['max_nfev'] > 5000:
        raise ValueError('Application limits: 12 starts and 5000 evaluations per start')
    if engine == 'survey' and 'survey' not in options:
        raise ValueError('Survey model requires an explicit world/metre survey declaration')
    if 'survey' in options:
        m7.normalize_survey(options['survey'], config['beacon_layout']['count'])
    source = copy.deepcopy(draft.get('observation_source', {'kind': 'generate'}))
    if source.get('kind') not in ('generate', 'saved') or set(source) - {'kind', 'key'}:
        raise ValueError('Observation source must be generate or saved with a Library key')
    if source['kind'] == 'saved' and not isinstance(source.get('key'), str):
        raise ValueError('Saved observation source requires its exact Library key')
    study = copy.deepcopy(draft.get('study', {'kind': 'single'}))
    if study.get('kind') not in ('single', 'parameter'):
        raise ValueError('Choose single fit or parameter study')
    result = split(engine, config, options)
    result.update(observation_source=source, study=study)
    return result, config, options


def study_payload(draft, config, options):
    engine, study = draft['engine'], draft['study']
    if engine not in STUDIES:
        raise ValueError('Partial survey has no native parameter-study engine; use explicit single fits on saved observations')
    if draft['observation_source']['kind'] != 'generate':
        raise ValueError('Parameter studies generate paired cells; saved observations support explicit single fits')
    if set(study) - {'kind', 'factor', 'values', 'seeds', 'variants'}:
        raise ValueError('Unsupported study fields')
    module, route = STUDIES[engine]
    if engine == 'planar' and study.get('factor') == 'initial_error_m' and options['initialization'] != 'truth_near':
        raise ValueError('The planar initialization-error study is truth-near diagnostic; select truth_near explicitly')
    body = {k: v for k, v in study.items() if k != 'kind'}
    body.update(options=options)
    body['experiment' if engine == 'planar' else 'base_experiment'] = config
    if engine == 'timing' and body.pop('variants', None) is not None:
        raise ValueError('Timing studies use the recorded timestamp-aware/grouped pair; custom variants are unsupported')
    return module.validate_sweep_config(body), route


def capabilities():
    models = {}
    for key, (generator, fitter, label, schema) in ENGINES.items():
        config = generator._normalise_config({}) if key == 'planar' else generator.normalize_config({})
        options = {} if key == 'planar' else fitter.validate_options({})
        if key == 'survey':
            options = m7.validate_options({**options, 'beacon_height_model': 'independent',
                       'survey': {'frame': 'world', 'units': 'm', 'fixed': [{'beacon_id': 0, 'mask': [True, True, True], 'mean_m': [0., 0., 3.]}], 'priors': []}})
        draft, _, _ = normalize(split(key, config, options))
        models[key] = {'label': label, 'native_schema': schema, 'defaults': draft,
                       'study_factors': list(STUDIES[key][0].FACTORS) if key in STUDIES else [],
                       'study_variants': 'fixed timestamp-aware/grouped pair' if key == 'timing' else 'native labeled variants'}
        models[key]['supported'] = {
            'beacon_count': [4, 4] if key in ('planar', 'timing') else [3, 8],
            'tag_height_models': ['fixed'] if key in ('planar', 'timing') else ['fixed', 'shared', 'soft', 'free'],
            'beacon_height_models': ['shared'] if key in ('planar', 'timing') else ['independent'] if key == 'survey' else ['shared', 'independent'],
            'solvers': ['trf'] if key in ('planar', 'timing', 'spatial') else ['trf', 'lm'],
            'height_coordinates': ['h'] if key in ('planar', 'timing', 'spatial', 'survey') else ['h', 'q'],
            'initializers': ['independent', 'truth_near', 'algebraic'] if key in ('solver', 'robust') else ['independent', 'truth_near'],
            'losses': list(m6.LOSSES) if key in ('robust', 'survey') else ['gaussian'],
            'timing_models': ['timestamp_aware', 'grouped'] if key != 'planar' else ['synchronized'],
            'combination_rules': [
                'q requires a supported single shared relative height; it is not a general free-height coordinate.',
                'Joint independent beacon heights and free/soft tag heights cannot use coupled below-every-beacon bounds.',
                'Partial survey requires joint world-frame physical h coordinates, independent beacon heights and no algebraic initializer.',
                'Conditional covariance is withheld for unsupported noise models, rank deficiency, active bounds and robust/rejected fits.',
            ]}
        if key in STUDIES:
            models[key]['default_variants'] = copy.deepcopy(getattr(STUDIES[key][0], 'DEFAULT_VARIANTS',
                [{'label': 'timestamp_aware'}, {'label': 'grouped'}] if key == 'timing' else
                [{'label': 'budget_200', 'max_nfev': 200}, {'label': 'budget_1000', 'max_nfev': 1000}]))
    return {'workspace_version': 1, 'models': models,
            'limits': {'starts': 12, 'max_nfev': 5000, 'study_runs': 40, 'study_attempts': 240},
            'disclosures': ['Convergence, residual quality, geometry and identifiability are distinct.',
                'Known-map coordinates are explicitly supplied survey knowledge.',
                'Truth-near initialization is diagnostic. Full local rank is not uniqueness.',
                'Local Gaussian intervals are conditional; robust curvature is not calibrated covariance.']}


def register_workspace(app, directory, executor, jobs, lock, library):
    def body_object():
        body = request.get_json()
        if not isinstance(body, dict):
            raise ValueError('Expected a JSON object')
        return body

    def source_run(key):
        item = library.preview(key)
        if not item or item.get('kind') != 'run' or item.get('status') == 'unreadable':
            raise ValueError('Choose a readable saved Library run')
        path = (directory / item['source_path']).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError('Invalid source path')
        if 'entry_ordinal' in item:
            raw = json.loads(path.read_text(encoding='utf-8'))
            family = raw.get('artifact_type')
            module = {'timing_sweep': m3_sweeps, 'geometry_sweep': m4_sweeps,
                      'solver_sweep': m5_sweeps, 'robust_sweep': m6_sweeps}.get(family, sweeps)
            raw = module.load_artifact(path)
            if 'comparison_side' in item:
                return raw['runs'][item['comparison_side']]
            ordinal = item['entry_ordinal']
            if not 0 <= ordinal < len(raw.get('entries', [])) or not raw['entries'][ordinal].get('run'):
                raise ValueError('Recorded source entry is unavailable; refresh Library')
            return raw['entries'][ordinal]['run']
        return experiments.load_json(path)

    def resolve(draft):
        normalized, config, options = normalize(draft)
        source = normalized['observation_source']
        exp = None
        if source['kind'] == 'saved':
            run = source_run(source['key'])
            exp = copy.deepcopy(run['experiment'])
            generator = ENGINES[normalized['engine']][0]
            validator = experiments._validate_experiment if normalized['engine'] == 'planar' else generator.validate_experiment
            validator(exp)  # No silent schema conversion or regeneration.
            if config != exp['config']:
                raise ValueError('Saved source config is immutable; use its exact physical settings and assumed sigma, or generate new observations')
        return normalized, config, options, exp

    @app.get('/api/workspace/capabilities')
    def get_capabilities():
        return jsonify(capabilities())

    @app.post('/api/workspace/export/csv')
    def workspace_csv():
        body = body_object()
        if 'artifact' in body:
            artifact = body['artifact']
            sweeps.validate_artifact(artifact)
            return Response(sweeps.table_csv(artifact), mimetype='text/csv')
        run = source_run(body['key']) if 'key' in body else body.get('run')
        experiments._validate_payload(run)
        output = io.StringIO(newline='')
        writer = csv.DictWriter(output, fieldnames=['record_type', 'index', 'status', 'beacon_id',
            'actual_time_s', 'assumed_time_s', 'range_m', 'sigma_m', 'complete_record_json'])
        writer.writeheader()
        writer.writerow({'record_type': 'source', 'status': run.get('status'),
                         'complete_record_json': json.dumps({k: v for k, v in run.items() if k not in ('experiment', 'starts')}, allow_nan=False)})
        exp = run['experiment']
        writer.writerow({'record_type': 'experiment', 'complete_record_json': json.dumps({k: v for k, v in exp.items() if k != 'estimator_input'}, allow_nan=False)})
        inputs = exp.get('estimator_input', {})
        writer.writerow({'record_type': 'estimator_input', 'complete_record_json': json.dumps({k: v for k, v in inputs.items() if k != 'observations'}, allow_nan=False)})
        for i, obs in enumerate(inputs.get('observations', [])):
            writer.writerow({'record_type': 'observation', 'index': i,
                **{k: obs.get(k) for k in ['beacon_id', 'actual_time_s', 'assumed_time_s', 'range_m', 'sigma_m']},
                'complete_record_json': json.dumps(obs, allow_nan=False)})
        for i, start in enumerate(run.get('starts', [])):
            writer.writerow({'record_type': 'attempt', 'index': start.get('index', i), 'status': start.get('status'),
                             'complete_record_json': json.dumps(start, allow_nan=False)})
        return Response(output.getvalue(), mimetype='text/csv')

    @app.post('/api/workspace/validate')
    def workspace_validate():
        normalized, config, options, _ = resolve(body_object())
        study = None
        if normalized['study']['kind'] == 'parameter':
            study, _ = study_payload(normalized, config, options)
        return jsonify(configuration=normalized, engine=normalized['engine'], native_options=options, native_study=study)

    @app.post('/api/workspace/configuration')
    def configuration_from_source():
        body = body_object()
        if 'native_configuration' in body:
            record = body['native_configuration']
            if not isinstance(record, dict) or record.get('artifact_type') != 'experiment_config':
                raise ValueError('Expected a native experiment configuration')
            engine = {'1.0': 'planar', '2.0': 'planar', '3.0': 'timing', '4.0': 'spatial',
                      '5.0': 'solver', '6.0': 'robust', '7.0': 'survey'}.get(record.get('schema_version'))
            if not engine or not isinstance(record.get('config'), dict):
                raise ValueError('Configuration cannot be represented; retain the original JSON and use a supported native record')
            normalized, _, _ = normalize(split(engine, record['config'], record.get('options', {})))
            return jsonify(configuration=normalized)
        run = source_run(body['key']) if 'key' in body else copy.deepcopy(body.get('run'))
        # Validate source-shaped embedded records too; this never fits.
        experiments._validate_payload(run)
        engine = {'1.0': 'planar', '3.0': 'timing', '4.0': 'spatial', '5.0': 'solver', '6.0': 'robust', '7.0': 'survey'}.get(run.get('schema_version'))
        if not engine:
            raise ValueError('Saved schema has no editable workspace adapter')
        draft = split(engine, run['experiment']['config'], run.get('options', {}))
        if body.get('reuse'):
            if 'key' not in body:
                raise ValueError('Reusing observations requires an authoritative Library key')
            draft['observation_source'] = {'kind': 'saved', 'key': body['key']}
        normalized, _, _ = normalize(draft)
        return jsonify(configuration=normalized)

    def execute(identifier, normalized, experiment, options):
        engine = normalized['engine']
        path = directory / f'{identifier}.json'
        envelope = json.loads(path.read_text(encoding='utf-8'))
        try:
            run = ENGINES[engine][1].solve_experiment(experiment, options)
            run.update(id=identifier, workspace_configuration=normalized)
            experiments.save_json(path, run)
            with lock:
                jobs[identifier] = {'status': 'complete', 'run': run}
        except Exception as exc:
            envelope.update(status='failed', error=f'{type(exc).__name__}: {exc}')
            try:
                experiments.save_json(path, envelope)
            except Exception as persistence:
                envelope['persistence_error'] = str(persistence)
            with lock:
                jobs[identifier] = {'status': 'failed', 'run': envelope, 'error': envelope['error']}

    @app.post('/api/workspace/runs')
    def workspace_submit():
        normalized, config, options, exp = resolve(body_object())
        if normalized['study']['kind'] != 'single':
            raise ValueError('Use the study endpoint for parameter studies')
        engine = normalized['engine']
        if exp is None:
            exp = ENGINES[engine][0].generate_experiment(config)
        if engine == 'survey':
            m7._problem(exp, options)
        identifier = uuid.uuid4().hex
        envelope = {'id': identifier, 'schema_version': ENGINES[engine][3], 'status': 'running',
                    'experiment': exp, 'options': options, 'starts': [], 'selected_start': None,
                    'diagnostics': {}, 'workspace_configuration': normalized}
        experiments.save_json(directory / f'{identifier}.json', envelope)
        with lock:
            jobs[identifier] = {'status': 'running'}
        executor.submit(execute, identifier, normalized, exp, options)
        return jsonify(id=identifier, engine=engine, configuration=normalized), 202

    @app.post('/api/workspace/studies')
    def workspace_submit_study():
        normalized, config, options, _ = resolve(body_object())
        if normalized['study']['kind'] != 'parameter':
            raise ValueError('Choose a parameter study')
        body, route = study_payload(normalized, config, options)
        # Invoke the native service within its own request context, preserving its
        # checkpointing, paired starts, strict persistence and job lifecycle.
        endpoint, values = app.url_map.bind('').match(route, method='POST')
        with app.test_request_context(route, method='POST', json=body):
            response = app.make_response(app.view_functions[endpoint](**values))
            payload = response.get_json()
        payload.update(engine=normalized['engine'], configuration=normalized)
        return jsonify(payload), response.status_code
