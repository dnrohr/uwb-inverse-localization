"""Package retained investigation sources and all-attempt metrics without refitting."""
from pathlib import Path
import collections
import datetime
import hashlib
import json
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from uwb import m3_sweeps, m4_sweeps, m5_sweeps, m6_sweeps, m7


def package():
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')
    out = ROOT / 'evidence/m7' / f'investigations_{stamp}_{uuid.uuid4().hex[:8]}'
    out.mkdir(parents=True)
    report = {'status': 'incomplete', 'sources': [], 'errors': [],
              'interpretation': 'Reuses complete retained experiments. Full source JSON remains authoritative; no solving or generation. Ranges, geometry, rejection and rank are separate. Finite starts do not exhaust alternatives. Missing metrics are null.',
              'reproduction': 'Run this script for an offline source audit. To refit, use each source config with its recorded software versions, then reuse each saved physical initial geometry. Truth-near and oracle starts remain diagnostics.'}
    cases = [(3, 'timing', 'spacing_s.json', m3_sweeps),
             (4, 'geometry', 'coverage.json', m4_sweeps),
             (4, 'height', 'height_prior_sigma_m.json', m4_sweeps),
             (5, 'initialization', 'independent_basin.json', m5_sweeps),
             (5, 'weak_geometry', 'weak_geometry.json', m5_sweeps),
             (6, 'multipath', 'masking_informative_noisy.json', m6_sweeps)]
    for milestone, topic, name, module in cases:
        try:
            candidates = sorted((ROOT / f'evidence/m{milestone}').glob(f'acceptance_*/sweeps/{name}'))
            if not candidates:
                raise ValueError(f'Missing retained source {name}')
            source = candidates[-1]
            data = module.load_artifact(source)
            rows, statuses, pairs = [], collections.Counter(), []
            for entry in data['entries']:
                run = entry['run']
                for start in run['starts']:
                    diag = start.get('diagnostics', {})
                    ev = diag.get('evaluation', {})
                    error = ev.get('aligned' if run.get('options', {}).get('mode') == 'joint' else 'raw', {}) or {}
                    statuses[start['status']] += 1
                    rows.append({'entry': entry.get('index'), 'value': entry.get('value'),
                                 'seed': entry.get('seed'), 'variant': entry.get('variant', entry.get('model')),
                                 'attempt': start['index'], 'status': start['status'],
                                 'message': start.get('solver', {}).get('message', start.get('error')),
                                 'trajectory_rmse_m': error.get('position_rmse_m'),
                                 'map_rmse_m': error.get('map_rmse_m'),
                                 'range_rmse_m': diag.get('range_rmse_m'),
                                 'measurement_information': diag.get('jacobian'),
                                 'robust_information': diag.get('information'),
                                 'rejection_quality': diag.get('rejection_evaluation'),
                                 'initialization': run.get('options', {}).get('initialization'),
                                 'selected': start['index'] == run.get('selected_start')})
                reference = entry.get('initial_reference_entry')
                if reference is not None:
                    origin = data['entries'][reference]['run']
                    same_data = origin['experiment']['estimator_input'] == run['experiment']['estimator_input']
                    if not same_data:
                        raise ValueError('Recorded paired entries have different observations')
                    pairs.append({'entry': entry.get('index'), 'reference': reference,
                                  'identical_estimator_input': same_data,
                                  'physical_start_validation': 'Strict source artifact validator checked model-compatible projected starts'})
            report['sources'].append({'topic': topic, 'path': source.relative_to(ROOT).as_posix(),
                                      'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                                      'config': data['config'], 'runs': len(data['entries']),
                                      'attempts': len(rows), 'statuses': dict(statuses),
                                      'paired_start_checks': pairs, 'attempt_table': rows,
                                      'aggregates': data.get('aggregates'),
                                      'all_alternatives_retained': 'Every source attempt, initial geometry, estimate and source solution grouping remain in the linked full JSON'})
        except Exception as exc:
            report['errors'].append({'topic': topic, 'error': f'{type(exc).__name__}: {exc}'})
        (out / 'investigations.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    try:
        summaries = sorted((ROOT/'evidence/m7').glob('acceptance_*/acceptance_summary.json'))
        if not summaries: raise ValueError('M7 partial-survey demonstration summary is missing')
        source = summaries[-1]; summary = json.loads(source.read_text())
        if summary['status'] != 'passed': raise ValueError('Latest M7 survey demonstration is incomplete')
        rows, statuses = [], collections.Counter()
        for record in summary['runs']:
            path = ROOT/record['path']; run=m7.load_run(path)
            for start in run['starts']:
                d=start['diagnostics']; error=d.get('evaluation',{}).get('raw',{})
                statuses[start['status']]+=1
                rows.append({'label':record['label'],'source':record['path'],'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                             'attempt':start['index'],'status':start['status'],'message':start['solver']['message'],
                             'trajectory_rmse_m':error.get('position_rmse_m'),'map_rmse_m':error.get('map_rmse_m'),
                             'range_rmse_m':d.get('range_rmse_m'),'rejection_quality':d.get('rejection_evaluation'),
                             'uncertainty_available':d.get('uncertainty',{}).get('available'),
                             'survey_objective':d.get('survey_objective'),
                             'initialization':run['options']['initialization']})
        report['sources'].append({'topic':'partial_survey','path':source.relative_to(ROOT).as_posix(),
                                  'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'runs':len(summary['runs']),
                                  'attempts':len(rows),'statuses':dict(statuses),'attempt_table':rows,
                                  'coverage':summary['coverage'],'reflection':summary.get('reflection_check')})
    except Exception as exc:
        report['errors'].append({'topic':'partial_survey','error':f'{type(exc).__name__}: {exc}'})
    report['status'] = 'passed' if not report['errors'] else 'failed'
    report['total_attempts'] = sum(s['attempts'] for s in report['sources'])
    (out / 'investigations.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'output': str(out), 'status': report['status'], 'errors': report['errors']}))
    return report


if __name__ == '__main__':
    raise SystemExit(0 if package()['status'] == 'passed' else 1)
