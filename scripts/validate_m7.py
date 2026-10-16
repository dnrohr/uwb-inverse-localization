"""Retain survey experiments and independent-trial interval diagnostics."""
from pathlib import Path
import collections
import copy
import datetime
import json
import math
import sys
import uuid
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from uwb import m4, m6, m7

# Declared map/survey inputs, selected before generation, in world metres.
MAP = [[0., 0., 3.], [10., 0., 3.], [1., 8., 3.], [11., 9., 3.]]
FIXED = [{'beacon_id': i, 'mask': [True, True, True], 'mean_m': b} for i, b in enumerate(MAP)]
OPTIONS = {'mode': 'joint', 'tag_height_model': 'fixed', 'beacon_height_model': 'independent',
           'starts': 1, 'max_nfev': 1000, 'below_beacons': True,
           'survey': {'frame': 'world', 'units': 'm', 'fixed': FIXED, 'priors': []}}


def config(seed=7, noise=.02, **more):
    return {'samples': 8, 'duration_s': 7., 'seed': seed, 'noise_std_m': noise,
            'assumed_std_m': .02, 'beacon_layout': {'count': 4, 'coordinates_m': MAP}, **more}


def wilson(k, n):
    if not n: return None
    z = 1.959963984540054; p = k / n; den = 1 + z*z/n
    center = (p + z*z/(2*n))/den
    half = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/den
    return [center-half, center+half]


def main():
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')
    out = ROOT/'evidence/m7'/f'acceptance_{stamp}_{uuid.uuid4().hex[:8]}'
    out.mkdir(parents=True); (out/'runs').mkdir()
    report = {'status': 'running', 'runs': [], 'errors': [], 'coverage': {},
              'survey_source': 'Explicit MAP constant and masks declared before generation; never extracted from hidden truth',
              'coverage_design': '32 independent seeded datasets per condition; one preselected coordinate (first knot x) per trial. Fixed known map, planar tag, no motion/height priors. Marginal 95% interval, not simultaneous coverage or uniqueness.'}
    def checkpoint():
        (out/'acceptance_summary.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    def retain(label, exp, opts, initial=None):
        run = m7.solve_experiment(exp, opts, initial)
        run['reference_name'] = 'M7_' + label
        path = out/'runs'/(label+'.json'); m7.save_run(path, run)
        report['runs'].append({'label': label, 'path': path.relative_to(ROOT).as_posix(), 'status': run['status'],
                               'attempts': len(run['starts']), 'statuses': dict(collections.Counter(s['status'] for s in run['starts']))})
        checkpoint(); return run
    try:
        source = m6.generate_experiment(config())
        partial = copy.deepcopy(OPTIONS); partial['starts'] = 3
        partial['survey']['fixed'] = FIXED[:2]
        partial_run=retain('selected_fixed_coordinates', source, partial)
        shared_starts=[s['initial'] for s in partial_run['starts']]
        uncertain = copy.deepcopy(partial)
        uncertain['survey']['priors'] = [{'beacon_id': i, 'mask': [True,True,True], 'mean_m': MAP[i],
                                         'covariance_m2': [[.04, .01, 0], [.01,.04,0], [0,0,.01]]} for i in (2,3)]
        uncertain_run=retain('uncertain_survey', source, uncertain, shared_starts)
        biased = copy.deepcopy(uncertain); biased['survey']['priors'][0]['mean_m'] = [2.,9.,3.]
        biased_run=retain('biased_survey_diagnostic', source, biased, shared_starts)
        weak = copy.deepcopy(partial); weak['survey']['fixed'] = FIXED[:1]
        retain('remaining_rigid_freedom', source, weak, shared_starts)
        capped = copy.deepcopy(partial); capped['max_nfev'] = 1
        retain('forced_nonconvergence', source, capped, shared_starts)
        robust = copy.deepcopy(uncertain); robust['loss'] = 'cauchy'
        retain('robust_uncertainty_unavailable', source, robust, shared_starts)
        report['survey_pairing']={'labels':['selected_fixed_coordinates','uncertain_survey','biased_survey_diagnostic'],
            'identical_observations':all(r['experiment']['estimator_input']==partial_run['experiment']['estimator_input'] for r in [uncertain_run,biased_run]),
            'identical_world_physical_starts':all([s['initial'] for s in r['starts']]==shared_starts for r in [uncertain_run,biased_run]),
            'interpretation':'Declared survey information is varied on identical saved observations and world physical starts. Biased priors are deliberately misspecified diagnostics.'}
        exact = m6.generate_experiment(config(noise=0.))
        retain('exact_informative_partial', exact, partial)
        retain('exact_straight_line_partial', m6.generate_experiment(config(noise=0.,scenario='straight_line')), partial)
        retain('noisy_narrow_coverage_partial', m6.generate_experiment(config(scenario='narrow_coverage')), partial)
        reflected = copy.deepcopy(OPTIONS)
        reflected.update(tag_height_model='free', below_beacons=False, initialization='truth_near',starts=2)
        problem = m7._problem(exact,m7.validate_options(reflected))
        positions=m4.truth_positions(exact['config'],problem.times_s)
        original=problem.geometry(problem.pack(positions,MAP))
        mirror=copy.deepcopy(original)
        mirror['knot_trajectory']=[[x,y,6-z] for x,y,z in mirror['knot_trajectory']]
        mirror['trajectory']=[[x,y,6-z] for x,y,z in mirror['trajectory']]
        reflection=retain('coplanar_reflection_oracle_diagnostic',exact,reflected,[original,mirror])
        report['reflection_check']={'oracle_initialization':True,
            'maximum_original_residuals_m':[max(abs(r) for r in s['diagnostics']['residuals_m']) for s in reflection['starts']],
            'world_trajectory_rmse_m':[s['diagnostics']['evaluation']['raw']['position_rmse_m'] for s in reflection['starts']],
            'interpretation':'Both supplied truth-near reflected branches retained. No alignment, scaling or reflection removes the world geometry error.'}
        invalid=copy.deepcopy(original); invalid['beacons'][2][2]=-1.
        failure=copy.deepcopy(partial);failure['starts']=1
        retain('invalid_physical_start',exact,failure,[invalid])
        for condition in ('assumed_model', 'misspecified_offset'):
            trials = []
            for seed in range(100, 132):
                cfg = config(seed)
                if condition == 'misspecified_offset': cfg['contamination'] = {'offsets_m': [.1,0,0,0]}
                exp = m6.generate_experiment(cfg)
                run = retain(f'{condition}_{seed}', exp, OPTIONS)
                selected = next((s for s in run['starts'] if s['index']==run['selected_start']), None)
                u = selected['diagnostics']['uncertainty'] if selected else {}
                row = {'seed': seed, 'status': run['status'], 'interval_available': u.get('available', False), 'covered': None}
                if selected and u.get('available'):
                    labels = u['parameter_labels']; index = next(i for i,l in enumerate(labels) if l['kind']=='tag' and l['knots']==[0] and l['axis']=='x')
                    error = selected['estimate']['knot_trajectory'][0][0] - exp['truth']['trajectory'][0][0]
                    half = u['marginal_95_half_width_m'][index]
                    row.update(error_m=error, half_width_m=half, covered=abs(error)<=half)
                else: row['unavailable_reasons'] = u.get('unavailable_reasons')
                trials.append(row)
            available = [t for t in trials if t['covered'] is not None]; covered = sum(t['covered'] for t in available)
            report['coverage'][condition] = {'trials': trials, 'requested_trials':32, 'intervals_available':len(available),
                'covered':covered, 'fraction':covered/len(available) if available else None,
                'binomial_wilson_95':wilson(covered,len(available)),
                'interpretation': 'Finite-sample calibration diagnostic under the assumed model' if condition=='assumed_model' else 'Declared misspecification suppresses intervals; unavailable is not failed coverage or zero uncertainty'}
            checkpoint()
        report['status'] = 'passed'
    except Exception as exc:
        report['status']='failed'; report['errors'].append(f'{type(exc).__name__}: {exc}')
    report['run_count'] = len(report['runs']); report['attempt_count'] = sum(r['attempts'] for r in report['runs'])
    checkpoint(); print(json.dumps({'output':str(out), 'status':report['status'], 'errors':report['errors']}))
    return report['status']=='passed'


if __name__ == '__main__':
    raise SystemExit(0 if main() else 1)
