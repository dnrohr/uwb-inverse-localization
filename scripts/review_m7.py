"""Independent M7 mathematics and retained-coverage audit; read-only science.

No expected range, covariance, information or whitening result calls an
implementation residual/Jacobian/uncertainty helper. Offline source loaders
are then separately exercised with generation and fitting prohibited.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_m7_review import (IndependentM7Review, prepare, expected_residual,
                                 finite_difference, independent_components)
from uwb import m6, m7


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def physical_range_matrix(run, selected):
    """Direct LOS and piecewise-linear weights for declared fixed-map coverage."""
    opts = run['options']; estimate = selected['estimate']
    assert opts['tag_height_model'] == 'fixed' and not opts.get('prior_sigma_m')
    assert opts['loss'] == 'gaussian' and not opts['survey']['priors']
    points = np.array(estimate['knot_trajectory'])
    beacons = np.array(estimate['beacons'])
    knots = np.array(estimate['knot_times_s'])
    data = run['experiment']['estimator_input']
    labels = selected['diagnostics']['uncertainty']['parameter_labels']
    expected_labels = [{'kind': 'tag', 'knots': [k], 'axis': axis, 'units': 'm'}
                       for k in range(len(knots)) for axis in ('x', 'y')]
    assert labels == expected_labels
    rows, residuals = [], []
    for obs in data['observations']:
        used = obs['assumed_time_s'] if opts['timing_model'] == 'timestamp_aware' else data['times_s'][obs['epoch']]
        interpolated = np.array([np.interp(used, knots, points[:, axis]) for axis in range(3)])
        delta = interpolated - beacons[obs['beacon_id']]
        length = np.linalg.norm(delta)
        weights = np.array([np.interp(used, knots, np.eye(len(knots))[k]) for k in range(len(knots))])
        rows.append([delta['xyz'.index(label['axis'])] / length / obs['sigma_m'] * weights[label['knots'][0]]
                     for label in labels])
        residuals.append((length - obs['range_m']) / obs['sigma_m'])
    return np.array(rows), np.array(residuals)


def audit_acceptance(path):
    report = json.loads(path.read_text(encoding='utf-8'))
    assert report['status'] == 'passed'
    actual_attempts = 0
    offline = 0
    covariance_errors = []
    diagnostics = {}
    for condition, summary in report['coverage'].items():
        rows = summary['trials']
        assert len(rows) == summary['requested_trials'] == 32
        assert len({r['seed'] for r in rows}) == len(rows)
        available = [r for r in rows if r['covered'] is not None]
        covered = sum(bool(r['covered']) for r in available)
        assert summary['intervals_available'] == len(available)
        assert summary['covered'] == covered
        assert summary['fraction'] == (covered / len(available) if available else None)
        assert all(r['interval_available'] == (r['covered'] is not None) for r in rows)
        for row in rows:
            run = json.loads((path.parent / 'runs' / f"{condition}_{row['seed']}.json").read_text(encoding='utf-8'))
            selected = next((s for s in run['starts'] if s['index'] == run['selected_start']), None)
            u = selected['diagnostics']['uncertainty'] if selected else {}
            assert bool(u.get('available')) == row['interval_available']
            if row['covered'] is not None:
                matrix, residuals = physical_range_matrix(run, selected)
                # Full physical inverse, not a gauge-fixed pseudoinverse.
                covariance = np.linalg.inv(matrix.T @ matrix)
                saved = np.asarray(u['covariance_m2'])
                error = float(np.max(np.abs(saved - covariance)))
                covariance_errors.append(error)
                np.testing.assert_allclose(saved, covariance, rtol=1e-8, atol=1e-12)
                np.testing.assert_allclose(selected['diagnostics']['residuals_normalized'], residuals, rtol=1e-9, atol=1e-11)
                geometry_error = selected['estimate']['knot_trajectory'][0][0] - run['experiment']['truth']['trajectory'][0][0]
                half_width = 1.959963984540054 * float(np.sqrt(covariance[0, 0]))
                assert bool(abs(geometry_error) <= half_width) == row['covered']
                assert abs(half_width - row['half_width_m']) < 1e-10
            else:
                assert u.get('covariance_m2') is None
        diagnostics[condition] = {'requested': len(rows), 'available': len(available), 'covered': covered,
                                  'unavailable': len(rows) - len(available), 'fraction': summary['fraction'],
                                  'wilson_95': summary['binomial_wilson_95'],
                                  'unavailable_counted_as_misses': False}
    # Each outcome validates/reopens/exports under an explicit no-fitting guard.
    with (patch.object(m6, 'generate_experiment', side_effect=AssertionError('offline generation forbidden')),
          patch.object(m7, 'solve_experiment', side_effect=AssertionError('offline solve forbidden')),
          patch.object(m7, 'fit_observations', side_effect=AssertionError('offline fitting forbidden'))):
        for item in report['runs']:
            source = ROOT / item['path']
            before = file_hash(source)
            run = m7.load_run(source)
            assert file_hash(source) == before
            assert len(run['starts']) == item['attempts']
            assert run['status'] == item['status']
            assert len(m7.table_csv(run).splitlines()) >= 2
            actual_attempts += len(run['starts'])
            offline += 1
    assert offline == report['run_count'] and actual_attempts == report['attempt_count']
    return {'path': path.relative_to(ROOT).as_posix(), 'runs': offline, 'attempts': actual_attempts,
            'coverage': diagnostics, 'independent_covariance_max_abs_error_m2': max(covariance_errors, default=None),
            'strict_offline_reopen_and_csv': offline, 'source_hashes_unchanged': True}


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = ROOT / 'evidence' / 'm7' / ('independent_review_' + stamp)
    out.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'recorded_at': datetime.now(timezone.utc).isoformat(),
              'scope': 'Independent mathematical/read-only review of survey, uncertainty, strict saved-record boundaries and retained coverage; not UI certification.',
              'source_hashes': {p: file_hash(ROOT / p) for p in ('uwb/m7.py', 'uwb/m7_service.py', 'scripts/validate_m7.py')},
              'findings': [
                  {'id': 'R1', 'severity': 'P2', 'description': 'Empty running/pending M7 envelopes initially accepted survey beacon7 for a four-beacon experiment and selected_start999 with no attempts.',
                   'initial_reproduction': 'Both malformed envelopes accepted by m7.validate_run before the fix.',
                   'resolution': 'Science owner moved _problem construction before early lifecycle return and rejects nonnull selection on empty starts; independent regression now required to pass.'},
                  {'id': 'R2', 'severity': 'P3', 'description': 'Omitted survey beacon_count originally raised raw TypeError before model validation.',
                   'resolution': 'Explicit ValueError requires count3–8; unseen beacons cannot safely be inferred.'},
                  {'id': 'R3', 'severity': 'none', 'description': 'Suspected free/soft below-beacon constraint hole was ruled out by existing inherited M4 option guard. M7 now also rejects all nonfixed tag models explicitly; no silent acceptance was reproduced.'}],
              'limitations': ['Full local rank and Gaussian covariance do not establish unique geometry; direct coplanar-reflection test retains equal-distance alternatives with finite local intervals.',
                              'Coverage uses only one predeclared coordinate in 32 independent datasets; no simultaneous, unconditional prior-posterior, robust or general real-world calibration is certified.',
                              'Declared misspecified-offset intervals are suppressed, so 0 available intervals is not 0% coverage.',
                              'The review does not certify global optimum recovery or all future survey geometries.']}
    output = io.StringIO(); started = time.perf_counter()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(IndependentM7Review)
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    (out / 'tests.txt').write_text(output.getvalue(), encoding='utf-8')
    report['tests'] = {'run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
                       'seconds': time.perf_counter() - started}
    # Retain numerical error measures as well as pass/fail assertions.
    errors = []
    for height in ('fixed', 'shared', 'soft', 'free'):
        for loss in ('gaussian', 'huber', 'soft_l1', 'cauchy'):
            problem, x, settings, obs = prepare(height, prior_sigma_m=.7, loss=loss, loss_scale_sigma=1.3)
            direct = lambda v: expected_residual(v, problem.parameter_labels, settings, obs)
            expected = finite_difference(direct, x)
            errors.append({'tag_height_model': height, 'loss': loss,
                           'residual_max_abs_error': float(np.max(np.abs(m7.residuals(x, problem) - direct(x)))),
                           'jacobian_max_abs_error_per_m': float(np.max(np.abs(m7.jacobian(x, problem) - expected)))})
    report['direct_objective_jacobian_checks'] = errors
    acceptance = []
    for path in sorted((ROOT / 'evidence' / 'm7').glob('acceptance_*/acceptance_summary.json')):
        if json.loads(path.read_text(encoding='utf-8')).get('status') == 'passed':
            acceptance.append(path)
    try:
        if not acceptance:
            raise ValueError('No completed retained M7 coverage study available to audit')
        report['retained_acceptance'] = audit_acceptance(acceptance[-1])
        report['status'] = 'passed' if result.wasSuccessful() else 'failed'
    except Exception as exc:
        report['status'] = 'failed'; report['error'] = f'{type(exc).__name__}: {exc}'
    report['source_hashes_unchanged_during_review'] = all(file_hash(ROOT / p) == h for p, h in report['source_hashes'].items())
    if not report['source_hashes_unchanged_during_review']:
        report['status'] = 'failed'; report['error'] = 'Production science changed during review; rerun against final source'
    (out / 'review.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'status': report['status'], 'output': str(out), 'error': report.get('error')}), flush=True)
    return report['status'] == 'passed'


if __name__ == '__main__':
    raise SystemExit(0 if main() else 1)
