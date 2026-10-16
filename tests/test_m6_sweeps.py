import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uwb import m6, m6_sweeps


class M6SweepTests(unittest.TestCase):
    def config(self):
        return {'base_experiment': {'samples':8, 'contamination': {'nlos': {'magnitude_m':1.5}}},
                'options': {'starts':2, 'max_nfev':30}, 'factor':'nlos_prevalence',
                'values':[.1], 'seeds':[7,8], 'variants':[
                    {'label':'Gaussian', 'options':{'loss':'gaussian'}},
                    {'label':'Huber', 'options':{'loss':'huber'}}]}

    def test_pairing_offline_roundtrip_and_tamper(self):
        artifact = m6_sweeps.run_sweep(self.config())
        self.assertEqual(len(artifact['start_table']), 8)
        for left, right in zip(artifact['entries'][::2], artifact['entries'][1::2]):
            self.assertEqual(left['run']['experiment'], right['run']['experiment'])
            self.assertEqual([s['initial'] for s in left['run']['starts']], [s['initial'] for s in right['run']['starts']])
        self.assertNotEqual(artifact['entries'][0]['run']['experiment']['config']['contamination']['seed'], artifact['entries'][2]['run']['experiment']['config']['contamination']['seed'])
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'sweep.json'
            with patch.object(m6, 'generate_experiment', side_effect=AssertionError('offline')), patch.object(m6, 'solve_experiment', side_effect=AssertionError('offline')):
                m6_sweeps.save_artifact(target, artifact)
                self.assertEqual(m6_sweeps.load_artifact(target), artifact)
                self.assertEqual(len(m6_sweeps.table_csv(artifact).splitlines()), 9)
        bad = copy.deepcopy(artifact)
        bad['start_table'][0]['false_rejections'] = 999
        with self.assertRaises(ValueError): m6_sweeps.validate_artifact(bad)
        bad = copy.deepcopy(artifact)
        bad['entries'][1]['initial_reference_entry'] = None
        with self.assertRaises(ValueError): m6_sweeps.validate_artifact(bad)
        bad = copy.deepcopy(artifact)
        bad['entries'][1]['initial_reference_entry'] = -1
        with self.assertRaises(ValueError): m6_sweeps.validate_artifact(bad)
        bad = copy.deepcopy(artifact)
        bad['entries'][1]['run']['experiment']['estimator_input']['observations'][0]['range_m'] += .1
        with self.assertRaises(ValueError): m6_sweeps.validate_artifact(bad)

    def test_failed_cells_and_checkpoint_prefix_accounting(self):
        config = self.config()
        config.update(seeds=[7], values=[0, .1])
        config['base_experiment']['contamination']['dropout_probability'] = 1
        snapshots = []
        artifact = m6_sweeps.run_sweep(config, snapshots.append)
        self.assertEqual(len(artifact['start_table']),8)
        self.assertTrue(all(r['status']=='failed' for r in artifact['start_table']))
        self.assertTrue(all(a['nonconvergence_rate']==1 for a in artifact['aggregates']))
        self.assertEqual(len(snapshots),4)
        partial = snapshots[0]
        m6_sweeps.validate_artifact(partial)
        partial['status']='complete'
        with self.assertRaises(ValueError): m6_sweeps.validate_artifact(partial)

    def test_reject_variants_that_break_physical_pairing(self):
        for override in ('seed','starts','initialization','timing_model','prior_sigma_m','fixed_tag_z_m'):
            config=self.config()
            config['variants'][1]['options'][override]=1
            with self.assertRaises(ValueError): m6_sweeps.validate_sweep_config(config)
        for factor, value in [('dropout_probability',1.1), ('burst_duration_cycles',1.5), ('nlos_magnitude_m',-1)]:
            config=self.config(); config.update(factor=factor,values=[value])
            with self.assertRaises(ValueError): m6_sweeps.validate_sweep_config(config)
