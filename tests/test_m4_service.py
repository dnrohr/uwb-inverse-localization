"""M4 delivery checks: dynamic geometry, offline inspection and recovery."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from app import create_app
from uwb import m4, m4_sweeps
from uwb.experiments import load_json, save_json


class M4ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = create_app(self.temp.name).test_client()

    def tearDown(self):
        self.temp.cleanup()

    def wait(self, identifier):
        deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            job = self.client.get('/api/jobs/'+identifier).json
            if job['status'] != 'running':
                return job
            time.sleep(.02)
        self.fail('M4 worker did not finish')

    def test_dynamic_map_run_offline_import_reopen_and_comparison(self):
        ids = []
        for tag in ('fixed', 'free'):
            response = self.client.post('/api/m4/runs', json={
                'config': {'samples': 8, 'beacon_layout': {'count': 6, 'geometry': 'diverse'},
                           'truth_height': {'type': 'spatial', 'amplitude_m': .3}},
                'options': {'mode': 'known_map', 'tag_height_model': tag, 'starts': 1, 'max_nfev': 50}})
            self.assertEqual(response.status_code, 202, response.json)
            identifier = response.json['id']; ids.append(identifier)
            job = self.wait(identifier)
            self.assertEqual(job['status'], 'complete', job)
            self.assertEqual(len(job['run']['experiment']['truth']['beacons']), 6)
            with patch('uwb.m4_service.m4.solve_experiment', side_effect=AssertionError('offline')), \
                 patch('uwb.m4_service.m4.generate_experiment', side_effect=AssertionError('offline')):
                self.assertEqual(self.client.get('/api/runs/'+identifier).json, job['run'])
                imported = self.client.post('/api/import', json=job['run'])
                self.assertEqual(imported.status_code, 200, imported.json)
                self.assertEqual(imported.json['run']['experiment'], job['run']['experiment'])
        comparison = self.client.post('/api/comparisons', json={'run_ids': ids, 'alignment': 'aligned'})
        self.assertEqual(comparison.status_code, 200, comparison.json)
        self.assertIn('M4', comparison.json['artifact']['views'][0]['sample_kind'])
        self.assertEqual(self.client.get('/api/comparisons/'+comparison.json['id']).json, comparison.json['artifact'])

    def test_spatial_joint_comparison_uses_proper_xyz_and_common_frame(self):
        run = m4.solve_experiment(m4.generate_experiment({'samples': 10,
            'beacon_layout': {'count': 6, 'geometry': 'diverse'}, 'truth_height': {'type': 'spatial'}}),
            {'mode': 'joint', 'tag_height_model': 'free', 'beacon_height_model': 'independent',
             'initialization': 'truth_near', 'starts': 1, 'max_nfev': 100})
        identifier = 'a'*32
        save_json(Path(self.temp.name)/(identifier+'.json'), run)
        for frame in ('raw', 'aligned'):
            response = self.client.post('/api/comparisons', json={'run_ids': [identifier, identifier], 'alignment': frame})
            self.assertEqual(response.status_code, 200, response.json)
            view = response.json['artifact']['views'][0]
            import numpy as np
            np.testing.assert_allclose(view['truth']['beacons'], view['estimate']['beacons'], atol=1e-5)
            if frame == 'aligned':
                self.assertIn('rotation_xyz', view['alignment'])
                self.assertEqual(view['alignment']['scale'], 1)
                self.assertFalse(view['alignment']['reflection_allowed'])

    def test_sweep_attempts_csv_checkpoint_and_offline_reopen(self):
        response = self.client.post('/api/m4/sweeps', json={
            'base_experiment': {'samples': 8, 'noise_std_m': .03,
                'beacon_layout': {'count': 5, 'geometry': 'diverse'}, 'truth_height': {'type': 'spatial'}},
            'options': {'mode': 'known_map', 'starts': 1, 'max_nfev': 1},
            'factor': 'height_spread', 'values': [0, .5], 'seeds': [7],
            'variants': [{'label': 'fixed', 'options': {'tag_height_model': 'fixed'}},
                         {'label': 'free', 'options': {'tag_height_model': 'free'}}]})
        self.assertEqual(response.status_code, 202, response.json)
        identifier = response.json['id']; job = self.wait(identifier)
        self.assertEqual(job['status'], 'complete', job)
        data = job['artifact']
        self.assertEqual(len(data['entries']), 4)
        self.assertEqual(len(data['start_table']), 4)
        self.assertTrue(any(row['status'] == 'not_converged' for row in data['start_table']))
        with patch('uwb.m4_service.m4.solve_experiment', side_effect=AssertionError('offline')), \
             patch('uwb.m4_service.m4.generate_experiment', side_effect=AssertionError('offline')):
            self.assertEqual(self.client.get('/api/m4/sweeps/'+identifier).json, data)
            self.assertEqual(self.client.get('/api/m4/sweeps/'+identifier+'/csv').status_code, 200)
            imported = self.client.post('/api/m4/import', json=data)
            self.assertEqual(imported.status_code, 200, imported.json)
            self.assertNotEqual(imported.json['id'], identifier)
        restarted = create_app(self.temp.name).test_client()
        self.assertEqual(restarted.get('/api/m4/sweeps/'+identifier).json, data)

    def test_invalid_input_and_unsupported_bounds_before_queue(self):
        with patch('uwb.m4_service.m4.solve_experiment', side_effect=AssertionError('not queued')):
            for body in ({'config': {'beacon_layout': {'count': 9}}}, {'options': {'tag_height_model': 'unsupported'}},
                         {'options': {'mode': 'joint', 'tag_height_model': 'free', 'beacon_height_model': 'independent', 'below_beacons': True}}):
                self.assertEqual(self.client.post('/api/m4/runs', json=body).status_code, 400)

    def test_worker_failure_retention_and_optimizer_persistence_separation(self):
        with patch('uwb.m4_service.m4.solve_experiment', side_effect=RuntimeError('controlled infrastructure failure')):
            response = self.client.post('/api/m4/runs', json={'config': {'samples': 8}, 'options': {'starts': 1}})
            job = self.wait(response.json['id'])
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(load_json(Path(self.temp.name)/(response.json['id']+'.json')), job['run'])
        real_save = save_json; failed_once = False
        def transient(path, data):
            nonlocal failed_once
            if data.get('status') == 'success' and not failed_once:
                failed_once = True
                raise OSError('controlled write failure')
            real_save(path, data)
        with patch('uwb.m4_service.save_json', side_effect=transient):
            response = self.client.post('/api/m4/runs', json={'config': {'samples': 8}, 'options': {'mode': 'known_map', 'tag_height_model': 'fixed', 'starts': 1}})
            job = self.wait(response.json['id'])
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['run']['status'], 'success')
        self.assertEqual(job['run']['infrastructure_status'], 'failed')

    def test_interrupted_unique_temporary_checkpoint_is_recovered(self):
        data = m4_sweeps.run_sweep({'base_experiment': {'samples': 8}, 'options': {'mode': 'known_map', 'starts': 1, 'max_nfev': 1},
            'factor': 'coverage', 'values': [1], 'seeds': [7], 'variants': [{'label': 'fixed', 'options': {'tag_height_model': 'fixed'}}]})
        identifier = 'b'*32; data.update(id=identifier, status='running')
        folder = Path(self.temp.name)/'artifacts'
        (folder/(identifier+'.json')).write_text(json.dumps({'schema_version': '4.0', 'artifact_type': 'geometry_sweep',
            'config': data['config'], 'entries': [], 'status': 'running'}))
        m4_sweeps.save_artifact(folder/(identifier+'.json.recovery.tmp'), data)
        response = self.client.get('/api/m4/sweeps/'+identifier)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['status'], 'failed')
        self.assertEqual(len(response.json['entries']), 1)
        self.assertIn('no implicit restart', response.json['error'])


if __name__ == '__main__':
    unittest.main()
