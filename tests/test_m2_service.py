"""M2 service checks: persistence, failed attempts, and read-only reopening."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from uwb.experiments import generate_experiment, save_json
from uwb.estimation import solve_experiment
from uwb.sweeps import run_sweep, save_artifact


class M2ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = create_app(self.temp.name).test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_comparison_import_and_reopen_never_solve(self):
        for identifier, noise in [('a' * 32, 0), ('b' * 32, .05)]:
            run = solve_experiment(generate_experiment({'samples': 8, 'noise_std_m': noise}), {'starts': 1})
            run['id'] = identifier
            save_json(Path(self.temp.name) / (identifier + '.json'), run)
        with patch('app.solve_experiment', side_effect=AssertionError('Must not solve')), \
             patch('app.run_sweep', side_effect=AssertionError('Must not sweep')):
            response = self.client.post('/api/comparisons', json={'run_ids': ['a' * 32, 'b' * 32], 'alignment': 'aligned'})
            self.assertEqual(response.status_code, 200, response.json)
            data = response.json['artifact']
            self.assertEqual(self.client.get('/api/comparisons/' + data['id']).json, data)
            imported = self.client.post('/api/artifacts/import', json=data)
            self.assertEqual(imported.status_code, 200, imported.json)
            self.assertEqual(len(self.client.get('/api/comparisons').json), 2)
            self.assertEqual(self.client.post('/api/comparisons', json={'run_ids': ['../escape', 'b' * 32]}).status_code, 400)

    def test_sweep_worker_retains_nonconvergence_and_reopens_without_solve(self):
        cfg = {'factor': 'noise_std_m', 'values': [0, .05], 'seeds': [7],
               'experiment': {'samples': 8}, 'options': {'starts': 1},
               'variants': [{'label': 'one evaluation', 'max_nfev': 1},
                            {'label': 'baseline', 'max_nfev': 200}]}
        result = self.client.post('/api/sweeps', json=cfg)
        self.assertEqual(result.status_code, 202, result.json)
        identifier = result.json['id']
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            job = self.client.get('/api/jobs/' + identifier).json
            if job['status'] != 'running':
                break
            time.sleep(.02)
        self.assertEqual(job['status'], 'complete', job)
        data = job['artifact']
        self.assertEqual(len(data['entries']), 4)
        self.assertEqual(len(self.client.get('/api/runs').json), 4)
        statuses = [entry['run']['status'] for entry in data['entries']]
        self.assertIn('not_converged', statuses)
        with patch('app.run_sweep', side_effect=AssertionError('Must not sweep')):
            self.assertEqual(self.client.get('/api/sweeps/' + identifier).json, data)
            imported = self.client.post('/api/artifacts/import', json=data)
            self.assertEqual(imported.status_code, 200, imported.json)

    def test_invalid_sweep_is_rejected_before_queueing(self):
        with patch('app.run_sweep', side_effect=AssertionError('Must not sweep')):
            for config in ({'factor': 'unsupported'}, {'factor': 'noise_std_m', 'values': [float('nan')]},
                           {'factor': 'noise_std_m', 'values': [0, .1], 'seeds': list(range(100))}):
                self.assertEqual(self.client.post('/api/sweeps', json=config).status_code, 400)
        self.assertEqual(self.client.get('/api/sweeps').json, [])

    def test_artifact_import_cannot_overwrite_existing_run_ids(self):
        identifier = 'a' * 32
        original = {'schema_version': '1.0', 'experiment': generate_experiment(),
                    'starts': [], 'status': 'failed', 'error': 'Existing saved observation'}
        path = Path(self.temp.name) / (identifier + '.json')
        save_json(path, original)
        before = path.read_bytes()
        sweep = run_sweep({'factor': 'noise_std_m', 'values': [0], 'seeds': [7],
                           'experiment': {'samples': 8}, 'options': {'starts': 1},
                           'variants': [{'label': 'one', 'max_nfev': 1}]})
        sweep['entries'][0]['run']['id'] = identifier
        with patch('app.run_sweep', side_effect=AssertionError('Must not solve')):
            response = self.client.post('/api/artifacts/import', json=sweep)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertNotEqual(response.json['artifact']['entries'][0]['run']['id'], identifier)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.client.get('/api/sweeps/' + response.json['id']).json,
                         response.json['artifact'])

    def test_single_run_limits_and_invalid_comparison_ids(self):
        for config in ({'duration_s': 3601}, {'noise_std_m': 101}, {'assumed_std_m': 1e-7}):
            self.assertEqual(self.client.post('/api/runs', json={'config': config}).status_code, 400)
        for ids in ([None, 'a' * 32], [1, 'a' * 32]):
            self.assertEqual(self.client.post('/api/comparisons', json={'run_ids': ids}).status_code, 400)

    def test_reopen_interrupted_sweep_discloses_no_worker_without_solving(self):
        snapshots = []
        run_sweep({'values': [0, .05], 'seeds': [7], 'experiment': {'samples': 8},
                   'options': {'starts': 1}, 'variants': [{'label': 'one', 'max_nfev': 1}]},
                  on_progress=snapshots.append)
        snapshot = snapshots[0]
        snapshot['id'] = 'c' * 32
        path = Path(self.temp.name) / 'artifacts' / (snapshot['id'] + '.json')
        save_artifact(path, snapshot)
        original = path.read_bytes()
        with patch('app.run_sweep', side_effect=AssertionError('Must not solve')):
            reopened = self.client.get('/api/sweeps/' + snapshot['id']).json
        self.assertEqual(reopened['status'], 'failed')
        self.assertEqual(reopened['saved_status'], 'running')
        self.assertEqual(reopened['entries'], snapshot['entries'])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.client.get('/api/sweeps').json[0]['status'], 'interrupted')


if __name__ == '__main__':
    unittest.main()
