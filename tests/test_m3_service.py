"""M3 service integration: retained history and offline reopening."""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from uwb import m3, m3_sweeps
from uwb.experiments import save_json, load_json


class M3ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = create_app(self.temp.name).test_client()

    def tearDown(self):
        self.temp.cleanup()

    def wait(self, identifier):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = self.client.get('/api/jobs/' + identifier).json
            if job['status'] != 'running':
                return job
            time.sleep(.02)
        self.fail('M3 worker did not finish')

    def test_run_reopen_import_comparison_without_solving(self):
        ids = []
        for model in ('timestamp_aware', 'grouped'):
            response = self.client.post('/api/m3/runs', json={
                'config': {'samples': 8, 'duration_s': 4, 'acquisition': {'spacing_s': .03}},
                'options': {'mode': 'known_map', 'starts': 1, 'max_nfev': 40, 'timing_model': model}})
            self.assertEqual(response.status_code, 202, response.json)
            identifier = response.json['id']; ids.append(identifier)
            job = self.wait(identifier)
            self.assertEqual(job['status'], 'complete', job)
            data = job['run']
            with patch('app.m3.solve_experiment', side_effect=AssertionError('offline')), \
                 patch('app.m3.generate_experiment', side_effect=AssertionError('offline')):
                self.assertEqual(self.client.get('/api/runs/' + identifier).json, data)
                imported = self.client.post('/api/import', json=data)
                self.assertEqual(imported.status_code, 200, imported.json)
                self.assertEqual(imported.json['run']['experiment'], data['experiment'])
        comparison = self.client.post('/api/comparisons', json={'run_ids': ids, 'alignment': 'aligned'})
        self.assertEqual(comparison.status_code, 200, comparison.json)
        self.assertIn('interpolated M3', comparison.json['artifact']['views'][0]['sample_kind'])
        self.assertTrue(all(r['schema_version'] == '3.0' for r in self.client.get('/api/runs').json))

    def test_sweep_checkpoint_csv_import_and_reopen(self):
        response = self.client.post('/api/m3/sweeps', json={
            'base_experiment': {'samples': 8, 'duration_s': 4},
            'options': {'mode': 'known_map', 'starts': 1, 'max_nfev': 1},
            'factor': 'spacing_s', 'values': [0, .02], 'seeds': [7]})
        self.assertEqual(response.status_code, 202, response.json)
        identifier = response.json['id']; job = self.wait(identifier)
        self.assertEqual(job['status'], 'complete', job)
        data = job['artifact']
        self.assertEqual(len(data['start_table']), 4)
        self.assertTrue(any(row['status'] == 'not_converged' for row in data['start_table']))
        self.assertEqual(len(self.client.get('/api/runs').json), 4)
        with patch('app.m3.solve_experiment', side_effect=AssertionError('offline')), \
             patch('app.m3.generate_experiment', side_effect=AssertionError('offline')):
            self.assertEqual(self.client.get('/api/m3/sweeps/' + identifier).json, data)
            self.assertEqual(self.client.get('/api/m3/sweeps/' + identifier + '/csv').status_code, 200)
            imported = self.client.post('/api/m3/import', json=data)
            self.assertEqual(imported.status_code, 200, imported.json)
            self.assertNotEqual(imported.json['id'], identifier)
            self.assertEqual(imported.json['artifact']['entries'][0]['run']['experiment'], data['entries'][0]['run']['experiment'])
        restarted = create_app(self.temp.name).test_client()
        self.assertEqual(restarted.get('/api/m3/sweeps/' + identifier).json, data)

    def test_invalid_config_before_worker_and_failure_retention(self):
        with patch('app.m3.solve_experiment', side_effect=AssertionError('not queued')):
            for body in ({'config': {'acquisition': {'beacon_order': [0, 0, 2, 3]}}},
                         {'options': {'prior_sigma_m': -1}}, {'config': {'seed': True}}):
                self.assertEqual(self.client.post('/api/m3/runs', json=body).status_code, 400)
        with patch('app.m3.solve_experiment', side_effect=RuntimeError('retained service failure')):
            response = self.client.post('/api/m3/runs', json={'config': {'samples': 8}, 'options': {'starts': 1}})
            job = self.wait(response.json['id'])
            self.assertEqual(job['status'], 'failed')
            saved = load_json(Path(self.temp.name) / (response.json['id'] + '.json'))
            self.assertEqual(saved['experiment'], job['run']['experiment'])
            self.assertIn('retained service failure', saved['error'])

    def test_persistence_failure_keeps_optimizer_outcome(self):
        real_save = save_json
        failed_once = False
        def transient(path, data):
            nonlocal failed_once
            if data.get('status') == 'success' and not failed_once:
                failed_once = True
                raise OSError('controlled write failure')
            real_save(path, data)
        with patch('app.save_json', side_effect=transient):
            response = self.client.post('/api/m3/runs', json={
                'config': {'samples': 8}, 'options': {'mode': 'known_map', 'starts': 1}})
            job = self.wait(response.json['id'])
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['run']['status'], 'success')
        self.assertEqual(job['run']['infrastructure_status'], 'failed')
        self.assertTrue(job['run']['starts'][0]['success'])
        self.assertEqual(load_json(Path(self.temp.name)/(response.json['id']+'.json')), job['run'])

    def test_restart_recovers_complete_unique_temporary_checkpoint(self):
        data = m3_sweeps.run_sweep({'base_experiment': {'samples': 8},
            'options': {'mode': 'known_map', 'starts': 1, 'max_nfev': 1},
            'factor': 'spacing_s', 'values': [0], 'seeds': [7]})
        identifier = 'a' * 32
        data.update(id=identifier, status='running')
        folder = Path(self.temp.name)/'artifacts'
        target = folder/(identifier+'.json')
        target.write_text(json.dumps({'schema_version': '3.0', 'artifact_type': 'timing_sweep',
            'config': data['config'], 'entries': [], 'id': identifier, 'status': 'running'}))
        m3_sweeps.save_artifact(folder/(identifier+'.json.recovery.tmp'), data)
        response = self.client.get('/api/m3/sweeps/'+identifier)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(len(response.json['entries']), 2)
        self.assertEqual(response.json['status'], 'failed')
        self.assertEqual(response.json['saved_status'], 'running')
        self.assertIn('no implicit restart', response.json['error'])


if __name__ == '__main__':
    unittest.main()
