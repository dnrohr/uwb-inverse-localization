"""Independent mathematical expectations (no estimator residual/Jacobian helpers).

Geometry, time interpolation, range distances, robust scalar objectives,
Gaussian whitening, rigid null vectors, and matrix inverses are constructed
here directly. Production helpers are used only on the actual side of checks.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from uwb import m6, m7


TIMES = np.array([0., 1., 2.5, 4.])
POINTS = np.array([[2., 1., .2], [3., 2., .4], [4., 3., .1], [5., 4., .5]])
BEACONS = np.array([[0., 0., 3.], [8., -1., 4.], [-2., 7., 2.5], [9., 8., 3.5]])
COV = np.array([[.04, .01, .005], [.01, .09, .02], [.005, .02, .16]])


def survey(*, fixed_all=False):
    if fixed_all:
        return {'frame': 'world', 'units': 'm', 'fixed': [
            {'beacon_id': b, 'mask': [True] * 3, 'mean_m': row.tolist()} for b, row in enumerate(BEACONS)], 'priors': []}
    return {'frame': 'world', 'units': 'm', 'fixed': [], 'priors': [
        {'beacon_id': b, 'mask': [True] * 3, 'mean_m': (row + [.1, -.05, .2]).tolist(),
         'covariance_m2': COV.tolist()} for b, row in enumerate(BEACONS)]}


def observations(points=POINTS, beacons=BEACONS):
    output = []
    for epoch, time in enumerate(TIMES):
        for b in range(4):
            assumed = float(time + (.07 * b if epoch < 3 else 0.))
            position = np.array([np.interp(assumed, TIMES, points[:, a]) for a in range(3)])
            distance = float(np.linalg.norm(position - beacons[b]))
            output.append({'epoch': epoch, 'beacon_id': b, 'assumed_time_s': assumed,
                           'range_m': distance + (.06 if b % 2 else -.03), 'sigma_m': .03 + .01 * b})
    return output


def prepare(height='free', selected=None, **options):
    selected = copy.deepcopy(selected or survey())
    settings = {'mode': 'joint', 'beacon_height_model': 'independent', 'tag_height_model': height,
                'starts': 1, 'survey': selected, 'fixed_tag_z_m': .3,
                'height_prior_sigma_m': .6, **options}
    obs = observations()
    problem = m7.build_problem(obs, TIMES.tolist(), beacon_count=4, **settings)
    # Parameter values from public labels, independently of pack/unpack/bases.
    values = []
    for label in problem.parameter_labels:
        a = 'xyz'.index(label['axis'])
        values.append(POINTS[label['knots'][0], a] if label['kind'] == 'tag'
                      else BEACONS[label['beacon_id'], a])
    return problem, np.array(values), settings, obs


def geometry(parameters, labels, settings):
    points = np.zeros_like(POINTS)
    points[:, 2] = settings['fixed_tag_z_m']
    beacons = np.zeros_like(BEACONS)
    for row in settings['survey']['fixed']:
        for a, chosen in enumerate(row['mask']):
            if chosen:
                beacons[row['beacon_id'], a] = row['mean_m'][a]
    for value, label in zip(parameters, labels):
        a = 'xyz'.index(label['axis'])
        if label['kind'] == 'tag':
            points[label['knots'], a] = value
        else:
            beacons[label['beacon_id'], a] = value
    return points, beacons


def independent_components(parameters, labels, settings, obs):
    points, beacons = geometry(parameters, labels, settings)
    measured = []
    for row in obs:
        used = row['assumed_time_s'] if settings.get('timing_model', 'timestamp_aware') == 'timestamp_aware' else TIMES[row['epoch']]
        p = np.array([np.interp(used, TIMES, points[:, a]) for a in range(3)])
        measured.append((np.linalg.norm(p - beacons[row['beacon_id']]) - row['range_m']) / row['sigma_m'])
    motion = []
    if settings.get('prior_sigma_m'):
        for k in range(1, len(TIMES) - 1):
            left, right = TIMES[k] - TIMES[k - 1], TIMES[k + 1] - TIMES[k]
            motion.extend((points[k] - (right * points[k - 1] + left * points[k + 1]) / (left + right)) / settings['prior_sigma_m'])
    height = (points[:, 2] - settings['fixed_tag_z_m']) / settings['height_prior_sigma_m'] if settings['tag_height_model'] == 'soft' else []
    priors = []
    for row in settings['survey']['priors']:
        axes = np.flatnonzero(row['mask'])
        discrepancy = beacons[row['beacon_id'], axes] - np.asarray(row['mean_m'])[axes]
        priors.extend(np.linalg.solve(np.linalg.cholesky(row['covariance_m2']), discrepancy))
    return np.asarray(measured), np.asarray(motion), np.asarray(height), np.asarray(priors)


def expected_residual(parameters, labels, settings, obs):
    raw, motion, height, priors = independent_components(parameters, labels, settings, obs)
    scale = settings.get('loss_scale_sigma', 1.)
    u = np.square(raw / scale)
    loss = settings.get('loss', 'gaussian')
    if loss == 'gaussian':
        transformed = raw
    else:
        rho = {'cauchy': lambda: np.log1p(u),
               'huber': lambda: np.where(u <= 1., u, 2 * np.sqrt(u) - 1),
               'soft_l1': lambda: 2 * (np.sqrt(1 + u) - 1)}[loss]()
        transformed = np.sign(raw) * scale * np.sqrt(rho)
    return np.r_[transformed, motion, height, priors]


def finite_difference(function, parameters, step=2e-6):
    return np.column_stack([(function(parameters + step * e) - function(parameters - step * e)) / (2 * step)
                            for e in np.eye(len(parameters))])


class IndependentM7Review(unittest.TestCase):
    def test_direct_world_distances_whitening_motion_height_and_loss_derivatives(self):
        for height in ('fixed', 'shared', 'soft', 'free'):
            for loss in ('gaussian', 'cauchy', 'huber', 'soft_l1'):
                problem, x, settings, obs = prepare(height, prior_sigma_m=.7, loss=loss, loss_scale_sigma=1.3)
                direct = lambda v: expected_residual(v, problem.parameter_labels, settings, obs)
                np.testing.assert_allclose(m7.residuals(x, problem), direct(x), atol=1e-12)
                independent_j = finite_difference(direct, x)
                np.testing.assert_allclose(m7.jacobian(x, problem), independent_j, atol=1e-7, rtol=2e-7)
                nr = len(obs)
                # Non-Gaussian transformations affect only measurement rows.
                raw = independent_components(x, problem.parameter_labels, settings, obs)
                np.testing.assert_allclose(m7.residuals(x, problem)[nr:], np.r_[raw[1], raw[2], raw[3]], atol=1e-13)

    def test_selected_nonadjacent_axes_and_mahalanobis_cost(self):
        selected = {'frame': 'world', 'units': 'm', 'fixed': [
            {'beacon_id': 0, 'mask': [True, False, True], 'mean_m': BEACONS[0].tolist()}],
            'priors': [{'beacon_id': 1, 'mask': [True, False, True],
                        'mean_m': [7.7, 999., 4.2], 'covariance_m2': [[.04, .012], [.012, .09]]}]}
        problem, x, settings, obs = prepare('free', selected)
        self.assertEqual(problem.parameter_count, 24 - 2)
        raw = independent_components(x, problem.parameter_labels, settings, obs)
        discrepancy = BEACONS[1, [0, 2]] - [7.7, 4.2]
        expected = .5 * discrepancy @ np.linalg.solve([[.04, .012], [.012, .09]], discrepancy)
        self.assertAlmostEqual(.5 * np.sum(m7.survey_residuals(x, problem) ** 2), expected, places=12)
        self.assertEqual(len(raw[3]), 2)
        self.assertEqual(len(m7.residuals(x, problem)), len(obs) + 2)
        _, actual_b = problem.unpack(x)
        self.assertEqual(actual_b[0, 0], 0.)
        self.assertEqual(actual_b[0, 2], 3.)

    def test_gaussian_information_covariance_and_rigid_nullspace(self):
        problem, x, settings, obs = prepare('free')
        direct = lambda v: expected_residual(v, problem.parameter_labels, settings, obs)
        matrix = finite_difference(direct, x)
        ranges = matrix[:len(obs)]
        # Every common infinitesimal translation/rotation preserves distances.
        points, beacons = geometry(x, problem.parameter_labels, settings)
        for axis in np.eye(3):
            for rotation in (False, True):
                vector = []
                for label in problem.parameter_labels:
                    coordinate = points[label['knots'][0]] if label['kind'] == 'tag' else beacons[label['beacon_id']]
                    delta = np.cross(axis, coordinate) if rotation else axis
                    vector.append(delta['xyz'.index(label['axis'])])
                self.assertLess(float(np.linalg.norm(ranges @ vector)), 3e-7)
        covariance = np.linalg.inv(matrix.T @ matrix)
        summary = m7.conditional_uncertainty(x, problem)
        self.assertTrue(summary['available'])
        self.assertLess(summary['information']['original_measurement']['rank'], len(x))
        self.assertEqual(summary['information']['survey']['row_count'], 12)
        self.assertEqual(summary['information']['augmented']['rank'], len(x))
        np.testing.assert_allclose(summary['covariance_m2'], covariance, atol=2e-9, rtol=2e-7)
        np.testing.assert_allclose(summary['standard_deviation_m'], np.sqrt(np.diag(covariance)), atol=2e-9)

    def test_unobservable_and_robust_covariance_guards_with_prior_information_separate(self):
        selected = {'frame': 'world', 'units': 'm', 'fixed': [], 'priors': [
            {'beacon_id': 0, 'mask': [True, False, False], 'mean_m': BEACONS[0].tolist(), 'covariance_m2': [[.04]]}]}
        problem, x, *_ = prepare('free', selected)
        summary = m7.conditional_uncertainty(x, problem)
        self.assertFalse(summary['available'])
        self.assertIsNone(summary['covariance_m2'])
        self.assertLess(summary['information']['augmented']['rank'], len(x))
        for loss in ('cauchy', 'huber', 'soft_l1', 'hard_rejection'):
            problem, x, *_ = prepare('soft', prior_sigma_m=.7, loss=loss)
            summary = m7.conditional_uncertainty(x, problem)
            self.assertFalse(summary['available'])
            self.assertEqual(summary['information']['motion_prior']['row_count'], 6)
            self.assertEqual(summary['information']['height_prior']['row_count'], 4)
            self.assertEqual(summary['information']['survey']['row_count'], 12)
            self.assertIn('Robust/rejection', ' '.join(summary['unavailable_reasons']))

    def test_reflection_remains_despite_full_local_rank(self):
        beacons = BEACONS.copy(); beacons[:, 2] = 3.
        points = POINTS.copy()
        obs = observations(points, beacons)
        selected = {'frame': 'world', 'units': 'm', 'fixed': [
            {'beacon_id': i, 'mask': [True] * 3, 'mean_m': b.tolist()} for i, b in enumerate(beacons)], 'priors': []}
        problem = m7.build_problem(obs, TIMES.tolist(), beacon_count=4, mode='joint',
                                   tag_height_model='free', beacon_height_model='independent', survey=selected)
        left = np.array([points[l['knots'][0], 'xyz'.index(l['axis'])] for l in problem.parameter_labels])
        reflected = points.copy(); reflected[:, 2] = 6 - reflected[:, 2]
        right = np.array([reflected[l['knots'][0], 'xyz'.index(l['axis'])] for l in problem.parameter_labels])
        np.testing.assert_allclose(m7.residuals(left, problem), m7.residuals(right, problem), atol=1e-12)
        self.assertTrue(m7.conditional_uncertainty(left, problem)['available'])
        self.assertTrue(m7.conditional_uncertainty(right, problem)['available'])
        self.assertGreater(float(np.linalg.norm(left - right)), 10)

    def test_constraint_rejection_and_missing_count_are_explicit(self):
        problem, x, settings, obs = prepare('fixed', survey(fixed_all=True))
        for change in ({'tag_height_model': 'free', 'below_beacons': True},
                       {'tag_height_model': 'soft', 'below_beacons': True},
                       {'tag_height_model': 'shared', 'below_beacons': True},
                       {'height_parameterization': 'q'}, {'initialization': 'algebraic'},
                       {'beacon_height_model': 'shared'}):
            with self.assertRaises(ValueError):
                m7.validate_options({**settings, **change})
        with self.assertRaises(ValueError):
            m7.build_problem(obs, TIMES.tolist(), **settings)
        illegal = copy.deepcopy(settings)
        illegal['survey']['priors'] = [{'beacon_id': [0, 1], 'mask': [True] * 3,
                                      'mean_m': [0.] * 3, 'covariance_m2': np.eye(3).tolist()}]
        with self.assertRaises(ValueError):
            m7.validate_options(illegal)

    def test_truth_annotation_isolation_and_no_survey_baseline(self):
        problem, x, settings, obs = prepare('fixed', survey(fixed_all=True), max_nfev=100)
        points, beacons = geometry(x + .01, problem.parameter_labels, settings)
        initial = [{'knot_trajectory': points.tolist(), 'beacons': beacons.tolist()}]
        dirty = [{**o, 'clean_range_m': -1e9, 'actual_time_s': -1e9, 'delivery_time_s': 1e9,
                  'contamination_label': 'evil', 'truth': [1e99] * 3} for o in obs]
        first = m7.fit_observations(obs, TIMES.tolist(), beacon_count=4, initial_geometries=initial, **settings)[0]
        second = m7.fit_observations(dirty, TIMES.tolist(), beacon_count=4, initial_geometries=initial, **settings)[0]
        self.assertEqual(first['estimate'], second['estimate'])
        self.assertEqual(first['solver']['final_objective'], second['solver']['final_objective'])
        exp = m6.generate_experiment({'samples': 8, 'noise_std_m': .02, 'assumed_std_m': .02})
        opts = {'mode': 'known_map', 'starts': 1, 'max_nfev': 100}
        baseline = m6.solve_experiment(exp, opts)
        extension = m7.solve_experiment(exp, opts)
        self.assertEqual(baseline['options'], extension['options'])
        self.assertEqual(baseline['starts'][0]['estimate'], extension['starts'][0]['estimate'])
        self.assertEqual(baseline['starts'][0]['diagnostics'], extension['starts'][0]['diagnostics'])

    def test_empty_envelopes_validate_survey_count_and_selected_start(self):
        exp = m6.generate_experiment({'samples': 8})
        opts = m7.validate_options({'mode': 'joint', 'beacon_height_model': 'independent',
            'survey': {'frame': 'world', 'units': 'm', 'fixed': [
                {'beacon_id': 7, 'mask': [True, False, False], 'mean_m': [0.] * 3}], 'priors': []}})
        envelope = {'schema_version': '7.0', 'experiment': exp, 'options': opts, 'status': 'running',
                    'starts': [], 'selected_start': None, 'diagnostics': {}}
        with self.assertRaises(ValueError):
            m7.validate_run(envelope)
        envelope['options']['survey']['fixed'][0]['beacon_id'] = 0
        envelope['selected_start'] = 999
        with self.assertRaises(ValueError):
            m7.validate_run(envelope)


if __name__ == '__main__':
    unittest.main()
