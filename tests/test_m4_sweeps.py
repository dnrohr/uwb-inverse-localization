"""M4 paired-model accounting, bounded controls, projection and offline reuse."""
import copy
import csv
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uwb.experiments import ExperimentFormatError
from uwb.m4_sweeps import aggregate_sweep, run_sweep, validate_sweep_config, validate_artifact, save_artifact, load_artifact, table_csv


class GeometrySweepTests(unittest.TestCase):
    def config(self, **changes):
        return {'base_experiment': {'samples': 8, 'duration_s': 4},
                'options': {'starts': 1, 'mode': 'known_map', 'initialization': 'independent', 'max_nfev': 30},
                'factor': 'vertical_separation', 'values': [2., 3.], 'seeds': [7],
                'variants': [{'label': 'fixed', 'options': {'tag_height_model': 'fixed'}},
                             {'label': 'free', 'options': {'tag_height_model': 'free'}}], **changes}

    def test_models_share_data_and_compatible_projected_starts(self):
        from uwb import m4
        artifact = run_sweep(self.config())
        self.assertEqual(len(artifact['start_table']), 4)
        for a, b in zip(artifact['entries'][::2], artifact['entries'][1::2]):
            self.assertEqual(a['run']['experiment'], b['run']['experiment'])
            expected = m4.compatible_initial_geometries(a['run'], b['run']['experiment'], b['run']['options'])
            self.assertEqual(expected, [s['initial'] for s in b['run']['starts']])
        row = artifact['start_table'][0]
        for field in ('height_rmse_m', 'plane_departure_rmse_m', 'measurement_full_column_rank', 'augmented_full_column_rank', 'height_prior_objective'):
            self.assertIn(field, row)

    def test_dynamic_counts_generate_the_actual_retained_ranges(self):
        from uwb import m4
        import numpy as np
        for count in (3, 8):
            experiment = m4.generate_experiment({'samples':8,'beacon_layout':{'count':count,'geometry':'diverse'},'truth_height':{'type':'excursion'}})
            observations = experiment['estimator_input']['observations']
            self.assertEqual(len(observations), count*8)
            self.assertEqual({o['beacon_id'] for o in observations}, set(range(count)))
            positions = np.asarray(experiment['truth']['ping_positions'])
            beacons = np.asarray(experiment['truth']['beacons'])
            expected = np.linalg.norm(positions - beacons[[o['beacon_id'] for o in observations]], axis=1)
            np.testing.assert_allclose([o['range_m'] for o in observations], expected, atol=1e-12)

    def test_joint_height_gauge_projection_is_retained_without_survey_truth(self):
        from uwb import m4
        artifact = run_sweep(self.config(values=[3.], options={'mode':'joint','starts':1,'initialization':'independent','max_nfev':1}))
        first, second = [e['run'] for e in artifact['entries']]
        expected = m4.compatible_initial_geometries(first, second['experiment'], second['options'])
        self.assertEqual(expected, [s['initial'] for s in second['starts']])
        self.assertNotEqual(first['starts'][0]['initial']['knot_trajectory'],second['starts'][0]['initial']['knot_trajectory'])
        self.assertEqual(len(artifact['start_table']), 2)

    def test_offline_reopen_export_and_tamper_detection(self):
        artifact = run_sweep(self.config(values=[3.]))
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'artifact.json'
            save_artifact(target, artifact)
            with patch('uwb.m4_sweeps.m4.solve_experiment', side_effect=AssertionError('offline')), patch('uwb.m4_sweeps.m4.generate_experiment', side_effect=AssertionError('offline')):
                self.assertEqual(load_artifact(target), artifact)
                self.assertEqual(len(list(csv.DictReader(io.StringIO(table_csv(artifact))))), 2)
        tampered = copy.deepcopy(artifact)
        tampered['entries'][1]['run']['starts'][0]['initial']['trajectory'][0][0] += 1
        with self.assertRaises(ExperimentFormatError): validate_artifact(tampered)
        tampered = copy.deepcopy(artifact)
        tampered['aggregates'][0]['start_count'] += 1
        with self.assertRaises(ExperimentFormatError): validate_artifact(tampered)

    def test_older_tables_remain_valid_without_additive_diagnostics(self):
        artifact = run_sweep(self.config(values=[3.]))
        for entry in artifact['entries']:
            entry['run']['diagnostics'].pop('truth_interpolation_only', None)
            entry['run']['diagnostics'].pop('truth_model_projection', None)
        artifact.update(aggregate_sweep(artifact))
        self.assertNotIn('interpolation_only_display_rmse_m', artifact['start_table'][0])
        with patch('uwb.m4_sweeps.m4.solve_experiment', side_effect=AssertionError('offline')):
            validate_artifact(artifact)
            self.assertEqual(len(list(csv.DictReader(io.StringIO(table_csv(artifact))))), 2)

    def test_every_failure_is_retained_and_checkpointed(self):
        progress = []
        with patch('uwb.m4_sweeps.m4.solve_experiment', side_effect=RuntimeError('controlled failure')):
            artifact = run_sweep(self.config(seeds=[7,8]), on_progress=progress.append)
        self.assertEqual(len(artifact['entries']), 8)
        self.assertEqual([len(p['entries']) for p in progress], list(range(1,9)))
        for snapshot in progress: validate_artifact(snapshot)
        self.assertTrue(all(r['classification'] == 'failed' for r in artifact['start_table']))
        self.assertTrue(all(a['nonconvergence_rate'] == 1 for a in artifact['aggregates']))

    def test_projection_exception_retains_every_target_start(self):
        with patch('uwb.m4_sweeps.m4.compatible_initial_geometries', side_effect=RuntimeError('projection failed')):
            artifact = run_sweep(self.config(values=[3.]))
        self.assertEqual(len(artifact['start_table']), 2)
        failed = artifact['entries'][1]
        self.assertEqual(failed['pairing_error'], 'RuntimeError: projection failed')
        self.assertEqual(failed['run']['status'], 'failed')
        self.assertTrue(all(s['initial'] is None and s['estimate'] is None for s in failed['run']['starts']))
        validate_artifact(artifact)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(table_csv(artifact))))), 2)

    def test_factor_boundaries_and_incompatible_controls(self):
        factors = {'beacon_count':[3,8], 'vertical_separation':[1.,4.], 'height_spread':[0.,1.], 'coverage':[.5,2.],
                   'height_prior_sigma_m':[.05,1.], 'beacon_height_model':['shared','independent']}
        for factor, values in factors.items():
            self.assertEqual(validate_sweep_config(self.config(factor=factor, values=values))['values'], values)
        for changes in ({'values':[1.,1.]}, {'seeds':[True]}, {'factor':'beacon_count','values':[2]},
                        {'factor':'beacon_height_model','values':['unknown']}, {'values':[float('nan')]},
                        {'values':list(range(10)), 'seeds':[1,2,3]},
                        {'variants':[{'label':'x','options':{'starts':2}}]},
                        {'factor':'beacon_count','values':[3], 'base_experiment':{'beacon_layout':{'coordinates_m':[[0,0,3],[10,0,3],[0,10,3],[10,10,3]]}}},
                        {'factor':'coverage','values':[1.], 'base_experiment':{'scenario':'straight_line'}}):
            with self.assertRaises(ValueError): validate_sweep_config(self.config(**changes))


if __name__ == '__main__': unittest.main()
