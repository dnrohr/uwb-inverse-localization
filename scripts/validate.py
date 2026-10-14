"""Reproducible M0/M1 acceptance suite and saved reference runs."""
from pathlib import Path
import json
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uwb.experiments import generate_experiment, save_json, load_json
from uwb.estimation import solve_experiment, fit_observations, build_problem, jacobian_diagnostics


def main():
    output = Path(__file__).resolve().parents[1] / 'evidence' / 'reference_runs'
    output.mkdir(parents=True, exist_ok=True)
    cases = [
        ('exact_joint_independent', 'informative', 0.0, 'joint', 'independent'),
        ('exact_joint_truth_near', 'informative', 0.0, 'joint', 'truth_near'),
        ('exact_known_map', 'informative', 0.0, 'known_map', 'independent'),
        ('noisy_joint_seed7', 'informative', 0.05, 'joint', 'independent'),
        ('noisy_joint_seed8', 'informative', 0.05, 'joint', 'independent'),
        ('straight_line', 'straight_line', 0.0, 'joint', 'independent'),
        ('narrow_coverage', 'narrow_coverage', 0.0, 'joint', 'independent'),
        ('nearly_collinear', 'nearly_collinear', 0.0, 'joint', 'independent'),
        ('forced_nonconvergence', 'informative', 0.0, 'joint', 'independent'),
    ]
    summary = []
    for name, scenario, noise, mode, init in cases:
        config = dict(scenario=scenario, noise_std_m=noise, seed=8 if name.endswith('seed8') else 7)
        experiment = generate_experiment(config)
        assert experiment['estimator_input'] == generate_experiment(config)['estimator_input']
        options = dict(mode=mode, initialization=init, starts=3, seed=19)
        if name == 'forced_nonconvergence':
            options['max_nfev'] = 1
        started = time.perf_counter()
        run = solve_experiment(experiment, options)
        path = output / (name + '.json')
        save_json(path, run)
        assert load_json(path) == run
        selected = run['starts'][run['selected_start']]
        if name.startswith('exact_'):
            evaluation = selected['diagnostics']['evaluation']['raw']
            assert evaluation['position_max_error_m'] < 1e-5, name
            assert max(evaluation['beacon_errors_m']) < 1e-5, name
            assert selected['diagnostics']['max_abs_residual_m'] < 1e-7, name
            assert run['diagnostics']['truth_jacobian']['full_column_rank'], name
        if name == 'straight_line':
            assert not run['diagnostics']['truth_jacobian']['full_column_rank']
            assert run['diagnostics']['distinct_solution_count'] > 1
        if name == 'forced_nonconvergence':
            assert all(not s['success'] for s in run['starts'])
        summary.append({'case': name, 'status': run['status'],
                        'selected_start': run['selected_start'],
                        'wall_time_s': time.perf_counter() - started,
                        'diagnostics': run['diagnostics'],
                        'selected_diagnostics': run['starts'][run['selected_start']]['diagnostics']})
        print(name, run['status'], f'{time.perf_counter() - started:.3f}s', flush=True)
    experiment = generate_experiment()
    truth = experiment['truth']
    invalid = {'trajectory': truth['trajectory'], 'beacons': [row[:] for row in truth['beacons']]}
    invalid['beacons'][1][0] = -10.0
    inputs = experiment['estimator_input']
    outcomes = fit_observations(inputs['observations'], inputs['times_s'], starts=1,
                                initial_geometries=[invalid])
    assert outcomes[0]['status'] == 'failed' and outcomes[0]['estimate'] is None
    problem = build_problem(inputs['observations'], inputs['times_s'])
    failed = {'schema_version': '1.0', 'experiment': experiment,
              'options': {'mode': 'joint', 'initialization': 'truth_near', 'starts': 1, 'seed': 19,
                          'diagnostic_note': 'Explicit truth-derived fixture with deliberately invalid negative d; no solver fit'},
              'status': 'failed', 'selected_start': None, 'starts': outcomes,
              'diagnostics': {'truth_jacobian': jacobian_diagnostics(problem.pack(truth['trajectory'], truth['beacons']), problem),
                              'failure_count': 1, 'warnings': ['Deliberately invalid negative-baseline diagnostic; no estimate exists']}}
    save_json(output / 'failed_initialization.json', failed)
    assert load_json(output / 'failed_initialization.json') == failed
    summary.append({'case': 'failed_initialization', 'status': 'failed', 'diagnostics': failed['diagnostics'],
                    'selected_start': None, 'selected_diagnostics': None})
    (output.parent / 'acceptance_summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    main()
