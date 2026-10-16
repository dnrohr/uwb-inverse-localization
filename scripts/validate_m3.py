"""Fresh M3 acceptance evidence; preserves all prior evidence and user runs."""
from pathlib import Path
import hashlib
import json
import sys
import time
import uuid
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uwb import m3
from uwb.estimation import fit_observations
from uwb.experiments import generate_experiment as generate_legacy
from uwb.m3_sweeps import run_sweep, save_artifact, load_artifact, table_csv
ROOT = Path(__file__).resolve().parents[1]


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write('\n')


def selected(run):
    return next((s for s in run['starts'] if s['index'] == run['selected_start']), None)


def fingerprint():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('evidence', 'runs') for p in (ROOT/folder).rglob('*') if p.is_file() and not p.is_relative_to(ROOT/'evidence'/'m3')}


def main():
    before = fingerprint()
    output = ROOT/'evidence'/'m3'/('acceptance_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
    output.mkdir(parents=True, exist_ok=False)
    summary = {'output': str(output.relative_to(ROOT)), 'sweeps': [], 'invariants': [],
               'interpretation': 'Truth-near known-map fixtures isolate timing and interpolation effects; do not establish joint-map global uniqueness.'}
    base = {'samples': 16, 'duration_s': 8, 'path': {'type': 'rectangle'},
            'motion': {'profile': 'variable', 'speed_scale': 1}, 'acquisition': {'spacing_s': .04}}
    options = {'mode': 'known_map', 'starts': 2, 'initialization': 'truth_near', 'max_nfev': 150}
    factors = [('speed_scale', [0., .5, 1.]), ('spacing_s', [0., .04, .1]),
               ('knot_spacing_s', [0., .5, 1.]), ('timestamp_offset_s', [0., .1]),
               ('timestamp_jitter_s', [0., .05]), ('missing_probability', [0., .2]),
               ('beacon_every_cycles', [1, 3])]
    for factor, values in factors:
        started = time.perf_counter()
        artifact = run_sweep({'base_experiment': base, 'options': options, 'factor': factor, 'values': values, 'seeds': [7, 8]},
                             on_progress=lambda data: save_artifact(output/'checkpoints'/(factor+'.json'), data))
        target = output/'sweeps'/(factor+'.json')
        save_artifact(target, artifact)
        assert load_artifact(target) == artifact
        (target.with_suffix('.csv')).write_text(table_csv(artifact), encoding='utf-8')
        assert len(artifact['start_table']) == len(values)*2*2*2
        summary['sweeps'].append({'factor': factor, 'wall_s': time.perf_counter()-started,
                                  'runs': len(artifact['entries']), 'starts': len(artifact['start_table']), 'aggregates': artifact['aggregates']})
        print('sweep', factor, len(artifact['entries']), flush=True)
    invariant_options = {**options, 'starts': 1}
    for name, configuration in [('zero_spacing', {'samples': 16, 'duration_s': 8, 'acquisition': {'spacing_s': 0}}),
                                ('stationary', {**base, 'motion': {'profile': 'stationary', 'speed_scale': 1}})]:
        experiment = m3.generate_experiment(configuration)
        aware = m3.solve_experiment(experiment, {**invariant_options, 'timing_model': 'timestamp_aware'})
        grouped = m3.solve_experiment(experiment, {**invariant_options, 'timing_model': 'grouped'}, initial_geometries=[s['initial'] for s in aware['starts']])
        write_json(output/'invariants'/(name+'.json'), {'aware': aware, 'grouped': grouped})
        a, g = selected(aware), selected(grouped)
        assert a and g
        if name == 'zero_spacing':
            np.testing.assert_allclose(a['estimate']['trajectory'], g['estimate']['trajectory'], atol=1e-8)
            legacy_exp = generate_legacy({'samples': 16, 'duration_s': 8})
            np.testing.assert_allclose([o['range_m'] for o in experiment['estimator_input']['observations']],
                                       [o['range_m'] for o in legacy_exp['estimator_input']['observations']], atol=1e-12)
            legacy_starts = fit_observations(legacy_exp['estimator_input']['observations'], legacy_exp['estimator_input']['times_s'],
                                            mode='known_map', surveyed_beacons=legacy_exp['truth']['beacons'], starts=1,
                                            initial_geometries=[aware['starts'][0]['initial']], max_nfev=invariant_options['max_nfev'])
            write_json(output/'invariants'/'legacy_zero_spacing_starts.json', legacy_starts)
            np.testing.assert_allclose(a['estimate']['trajectory'], legacy_starts[0]['estimate']['trajectory'], atol=1e-8)
            np.testing.assert_allclose(a['estimate']['beacons'], legacy_starts[0]['estimate']['beacons'], atol=1e-8)
        else:
            assert a['diagnostics']['evaluation']['raw']['position_rmse_m'] < 1e-5
            assert g['diagnostics']['evaluation']['raw']['position_rmse_m'] < 1e-5
        summary['invariants'].append({'name': name, 'passed': True, 'aware_range_rmse_m': a['diagnostics']['range_rmse_m'], 'grouped_range_rmse_m': g['diagnostics']['range_rmse_m']})
        print('invariant', name, flush=True)
    for model in ('timestamp_aware', 'grouped'):
        first = m3.generate_experiment(base)
        delayed = m3.generate_experiment({**base, 'acquisition': {**base['acquisition'], 'delivery_latency_s': 2}})
        run = m3.solve_experiment(first, {**invariant_options, 'timing_model': model})
        latency = m3.solve_experiment(delayed, {**invariant_options, 'timing_model': model}, initial_geometries=[s['initial'] for s in run['starts']])
        write_json(output/'invariants'/('latency_'+model+'.json'), {'baseline': run, 'delayed': latency})
        np.testing.assert_allclose(selected(run)['estimate']['trajectory'], selected(latency)['estimate']['trajectory'], atol=1e-12)
        np.testing.assert_allclose(selected(run)['estimate']['beacons'], selected(latency)['estimate']['beacons'], atol=1e-12)
        summary['invariants'].append({'name': 'delivery_latency_'+model, 'passed': True})
        print('invariant', 'latency', model, flush=True)
    summary['demos'] = []
    demos = [
        ('moving_joint_aware', base, {'mode': 'joint', 'initialization': 'independent', 'timing_model': 'timestamp_aware', 'starts': 2, 'max_nfev': 250}),
        ('moving_joint_grouped', base, {'mode': 'joint', 'initialization': 'independent', 'timing_model': 'grouped', 'starts': 2, 'max_nfev': 250}),
        ('variable_known_map', base, {**invariant_options, 'timing_model': 'timestamp_aware'}),
        ('timestamp_jitter_missing', {**base, 'acquisition': {**base['acquisition'], 'timestamp_jitter_s': .05, 'missing_probability': .2}}, {**invariant_options, 'timing_model': 'timestamp_aware'}),
        ('forced_nonconverged', base, {'mode': 'joint', 'initialization': 'independent', 'timing_model': 'timestamp_aware', 'starts': 2, 'max_nfev': 1}),
    ]
    for name, config, solver_options in demos:
        run = m3.solve_experiment(m3.generate_experiment(config), solver_options)
        m3.validate_run(run)
        write_json(output/'demo_runs'/(name+'.json'), run)
        summary['demos'].append({'name': name, 'status': run['status'], 'start_statuses': [s['status'] for s in run['starts']], 'diagnostics': run['diagnostics']})
        print('demo', name, run['status'], flush=True)
    summary['isolated_effects'] = []
    for name, config, solver_options in [
        ('acquisition_jitter_zero', base, {**invariant_options, 'timing_model': 'timestamp_aware'}),
        ('acquisition_jitter', {**base, 'acquisition': {**base['acquisition'], 'jitter_s': .03}}, {**invariant_options, 'timing_model': 'timestamp_aware'}),
        ('prior_off', base, {**invariant_options, 'timing_model': 'timestamp_aware', 'prior_sigma_m': 0}),
        ('prior_on', base, {**invariant_options, 'timing_model': 'timestamp_aware', 'prior_sigma_m': .1}),
    ]:
        run = m3.solve_experiment(m3.generate_experiment(config), solver_options)
        write_json(output/'isolated_effects'/(name+'.json'), run)
        start = selected(run)
        summary['isolated_effects'].append({'name': name, 'options': run['options'], 'status': run['status'],
                                          'diagnostics': start['diagnostics'] if start else None})
        print('isolated', name, run['status'], flush=True)
    for path, digest in before.items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == digest, path
    summary['preservation'] = {'files_checked': len(before), 'unchanged': True}
    write_json(output/'acceptance_summary.json', summary)
    print('saved', output, flush=True)


if __name__ == '__main__':
    main()
