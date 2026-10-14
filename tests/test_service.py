import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from uwb.experiments import generate_experiment, save_json


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = create_app(self.temp.name).test_client()

    def tearDown(self):
        self.temp.cleanup()

    def test_reopen_never_calls_solver(self):
        identifier = 'a' * 32
        run = {'schema_version': '1.0', 'experiment': generate_experiment(),
               'options': {'mode': 'joint'}, 'starts': [], 'status': 'failed', 'error': 'test preserved failure'}
        save_json(Path(self.temp.name) / (identifier + '.json'), run)
        with patch('app.solve_experiment', side_effect=AssertionError('Must not solve')):
            result = self.client.get('/api/runs/' + identifier)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json, run)
            self.assertEqual(len(self.client.get('/api/runs').json), 1)

    def test_invalid_configuration_and_import(self):
        result = self.client.post('/api/runs', json={'config': {'samples': 1}})
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.client.post('/api/import', json={}).status_code, 400)
        for options in ({'seed': float('nan')}, {'unknown': 1}, {'seed': -1}, {'starts': 1.5}):
            self.assertEqual(self.client.post('/api/runs', json={'options': options}).status_code, 400)

    def test_import_failure_is_reviewable(self):
        run = {'schema_version': '1.0', 'experiment': generate_experiment(),
               'options': {'mode': 'joint'}, 'starts': [], 'status': 'failed', 'error': 'preserved failure'}
        with patch('app.solve_experiment', side_effect=AssertionError('Must not solve')):
            result = self.client.post('/api/import', json=run)
            self.assertEqual(result.status_code, 200)
            reopened = self.client.get('/api/runs/' + result.json['id'])
            self.assertEqual(reopened.json['error'], 'preserved failure')

    def test_malformed_run_import_cannot_break_saved_history(self):
        base = {'schema_version': '1.0', 'experiment': generate_experiment(),
                'starts': [], 'status': 'failed'}
        for changes in ({'options': None}, {'starts': [None]},
                        {'starts': [{'index': 0, 'estimate': {'trajectory': [], 'beacons': []}}]},
                        {'selected_start': 5}):
            result = self.client.post('/api/import', json={**base, **changes})
            self.assertEqual(result.status_code, 400, changes)
        self.assertEqual(self.client.get('/api/runs').json, [])

    def test_standalone_experiment_and_invalid_file_do_not_break_history(self):
        save_json(Path(self.temp.name) / 'experiment.json', generate_experiment())
        self.assertEqual(self.client.get('/api/runs').json, [])
        (Path(self.temp.name) / 'broken.json').write_text('invalid JSON')
        result = self.client.get('/api/runs')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json[0]['status'], 'unreadable')


if __name__ == '__main__':
    unittest.main()
