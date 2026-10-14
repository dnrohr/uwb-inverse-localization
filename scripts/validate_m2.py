"""Generate M2 evidence separately; never overwrite M0–M1 or user history."""
from pathlib import Path
import hashlib
import json
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uwb.experiments import generate_experiment, path_metadata, save_json, load_json
from uwb.estimation import solve_experiment
from uwb.sweeps import run_sweep, save_artifact, load_artifact, build_comparison, table_csv

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'evidence' / 'm2'


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    summary = {'paths': [], 'sweeps': [], 'comparisons': [], 'performance': [],
               'preservation': [], 'environment': 'Windows, Python project virtual environment; local wall clock measurements'}
    for kind in ('line', 'circle', 'arc', 'rectangle', 'figure_eight', 'waypoint'):
        config = {'path': {'type': kind}, 'samples': 32, 'duration_s': 20}
        experiment = generate_experiment(config)
        started = time.perf_counter()
        run = solve_experiment(experiment, {'starts': 3})
        run['path_motion'] = path_metadata(config)
        run['id'] = uuid.uuid5(uuid.NAMESPACE_URL, 'uwb-m2/path/' + kind).hex
        save_json(OUTPUT / 'path_runs' / (kind + '.json'), run)
        assert load_json(OUTPUT / 'path_runs' / (kind + '.json')) == run
        chosen = run['starts'][run['selected_start']]
        summary['paths'].append({'type': kind, 'status': run['status'], 'runtime_s': time.perf_counter()-started,
                                 'truth_rank': run['diagnostics']['truth_jacobian'],
                                 'selected_evaluation': chosen['diagnostics']['evaluation']['raw'],
                                 'distinct_solutions': run['diagnostics']['distinct_solution_count'],
                                 'motion': run['path_motion']})
        if kind in ('rectangle', 'figure_eight', 'waypoint'):
            assert chosen['diagnostics']['geometric_recovery'] and chosen['diagnostics']['range_recovery'], kind
        print('path', kind, run['status'], flush=True)
    sweeps = {}
    for factor, values in [('noise_std_m', [0, .05, .2]), ('path_scale', [.1, 1]),
                           ('samples', [8, 32, 100]), ('initial_error_m', [0, .5]),
                           ('assumed_std_m', [.02, .1])]:
        cfg = {'factor': factor, 'values': values, 'seeds': [7, 8],
               'experiment': {'samples': 24, 'noise_std_m': .05, 'path': {'type': 'rectangle'}},
               'options': {'starts': 2, 'seed': 19},
               'variants': [{'label': 'one_evaluation', 'max_nfev': 1}, {'label': 'baseline', 'max_nfev': 500}]}
        started = time.perf_counter()
        artifact = run_sweep(cfg)
        artifact['id'] = uuid.uuid5(uuid.NAMESPACE_URL, 'uwb-m2/sweep/' + factor).hex
        for entry in artifact['entries']:
            entry['run']['id'] = uuid.uuid5(uuid.NAMESPACE_URL, f"uwb-sweep/{artifact['id']}/{entry['index']}").hex
        save_artifact(OUTPUT / 'sweeps' / (factor + '.json'), artifact)
        assert load_artifact(OUTPUT / 'sweeps' / (factor + '.json')) == artifact
        (OUTPUT / 'sweeps' / (factor + '.csv')).write_text(table_csv(artifact), encoding='utf-8')
        counts = {'runs': len(artifact['entries']), 'starts': len(artifact['start_table']),
                  'failed_or_nonconverged_starts': sum(not r['optimizer_converged'] for r in artifact['start_table'])}
        summary['sweeps'].append({'factor': factor, 'runtime_s': time.perf_counter()-started,
                                  **counts, 'aggregates': artifact['aggregates']})
        assert counts['starts'] == len(values)*2*2*2
        for left, right in zip(artifact['entries'][::2], artifact['entries'][1::2]):
            assert left['run']['experiment'] == right['run']['experiment']
            assert [s['initial'] for s in left['run']['starts']] == [s['initial'] for s in right['run']['starts']]
        sweeps[factor] = artifact
        print('sweep', factor, counts, flush=True)
    noise = sweeps['noise_std_m']
    left = noise['entries'][5]['run']  # noisy seed7 baseline
    right = noise['entries'][7]['run'] # noisy seed8 baseline
    for name, pair in [('noisy_seeds', (left, right)),
                       ('failed_vs_success', (load_json(ROOT/'evidence/reference_runs/failed_initialization.json'), right))]:
        comparison = build_comparison(*pair, alignment='aligned')
        comparison['id'] = uuid.uuid5(uuid.NAMESPACE_URL, 'uwb-m2/comparison/' + name).hex
        save_artifact(OUTPUT/'comparisons'/(name+'.json'), comparison)
        assert load_artifact(OUTPUT/'comparisons'/(name+'.json')) == comparison
        summary['comparisons'].append({'name': name, 'table': comparison['table']})
    for samples in (32, 100):
        started = time.perf_counter()
        run = solve_experiment(generate_experiment({'samples': samples, 'noise_std_m': .05}), {'starts': 3})
        save_json(OUTPUT / 'benchmark_runs' / (str(samples) + '.json'), run)
        summary['performance'].append({'samples': samples, 'starts': 3, 'solver_wrapper_wall_s': time.perf_counter()-started,
                                        'nfev': [s['solver']['nfev'] for s in run['starts']], 'status': run['status']})
    for manifest in ('preserved_m0_m1_hashes.json', 'preserved_user_runs_hashes.json'):
        path = OUTPUT/manifest
        if path.exists():
            entries = json.loads(path.read_text(encoding='utf-8-sig'))
            for item in entries:
                unchanged = hashlib.sha256(Path(item['Path']).read_bytes()).hexdigest().upper() == item['Hash']
                assert unchanged, item['Path']
            summary['preservation'].append({'manifest': manifest, 'files': len(entries), 'unchanged': True})
    (OUTPUT/'acceptance_summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    main()
