"""Offline metadata-index contracts; all fixture history is isolated."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask

from uwb.library import LibraryIndex, register_library


def fixture(identifier, *, status='success', label='Informative', seed=7):
    # Deliberately not a strict numerical run: browsing must not imply validation.
    return {'schema_version': '6.0', 'id': identifier, 'label': label, 'status': status,
            'experiment': {'config': {'scenario': 'informative', 'seed': seed},
                           'estimator_input': {'ranges_m': [[1, 2, seed]]}},
            'options': {'mode': 'joint', 'loss': 'cauchy', 'seed': seed},
            'starts': [{'index': 0, 'status': status, 'initial': {'beacons': [[1, 2, 3]]},
                        'solver': {'message': 'retained ' + status}}], 'selected_start': 0}


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        (self.directory / 'artifacts').mkdir()
        self.index = LibraryIndex(self.directory)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, identifier, data=None, *, artifact=False):
        path = (self.directory / 'artifacts' if artifact else self.directory) / (identifier + '.json')
        path.write_text(json.dumps(data or fixture(identifier)), encoding='utf-8')
        return path

    def test_zero_bounded_queries_filters_and_stable_sort(self):
        self.assertEqual(self.index.query()['total'], 0)
        for i in range(64):
            identifier = f'{i:032x}'
            self.save(identifier, fixture(identifier, status='failed' if i % 2 else 'success',
                                          label='Alpha' if i % 2 else 'Beta'))
        result = self.index.query(sort='name')
        self.assertEqual((result['total'], result['filtered'], len(result['items'])), (64, 64, 25))
        self.assertEqual(len(self.index.query(page_size='100000')['items']), 50)
        selected = self.index.query(q='alpha', status='failed', model='joint', source='saved', sort='name')
        self.assertEqual(selected['filtered'], 32)
        ids = [r['id'] for r in selected['items']]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(self.index.query(page=999)['page'], 3)
        self.assertEqual(self.index.query(q='nothing')['filtered'], 0)
        for args in ({'page': 'bad'}, {'sort': 'SQL injection'}, {'type': 'missing'}, {'view': 'invalid'}):
            with self.assertRaises(ValueError):
                self.index.query(**args)

    def test_interrupted_child_filter_uses_live_parent_worker_state(self):
        identifier = 'e' * 32
        self.save(identifier, {'schema_version':'6.0','artifact_type':'robust_sweep','status':'running',
                              'config':{},'entries':[{'index':0,'run':fixture('f'*32,status='running')}]},artifact=True)
        jobs={}
        index=LibraryIndex(self.directory,jobs=jobs)
        key='artifact:'+identifier
        self.assertEqual(index.query(parent=key,status='interrupted')['filtered'],1)
        self.assertEqual(index.query(parent=key,status='running')['filtered'],0)
        jobs[identifier]={'status':'running'}
        self.assertEqual(index.query(parent=key,status='running')['filtered'],1)
        self.assertEqual(index.query(parent=key,status='interrupted')['filtered'],0)

    def test_incremental_external_edits_deletions_and_no_warm_json_reads(self):
        path = self.save('a' * 32)
        self.index.query()
        with patch('uwb.library._summary', side_effect=AssertionError('Warm query decoded source JSON')):
            for _ in range(3):
                self.assertEqual(self.index.query()['index']['changed'], 0)
            self.assertEqual(self.index.preview('run:' + 'a' * 32)['id'], 'a' * 32)
        self.save('a' * 32, fixture('a' * 32, label='Changed externally'))
        result = self.index.query(q='Changed externally')
        self.assertEqual((result['filtered'], result['index']['changed']), (1, 1))
        self.save('b' * 32)
        self.assertEqual(self.index.query()['total'], 2)
        path.unlink()
        self.assertEqual(self.index.query()['total'], 1)
        self.assertIsNone(self.index.preview('run:' + 'a' * 32))

    def test_recorded_parent_grouping_embedded_children_and_attempt_metadata(self):
        run_id, parent_id = 'a' * 32, 'b' * 32
        run = fixture(run_id, status='failed')
        self.save(run_id, run)
        # Similar labels never infer a relationship to this independent record.
        self.save('c' * 32, fixture('c' * 32, status='failed'))
        parent = {'id': parent_id, 'schema_version': '6.0', 'artifact_type': 'robust_sweep',
                  'status': 'complete', 'config': {'factor': 'noise_std_m', 'values': [0, 1],
                     'seeds': [7], 'variants': [{'label': 'Cauchy'}, {'label': 'Gaussian'}]},
                  'entries': [{'index': 0, 'value_index': 0, 'value': 0, 'seed': 7,
                               'variant': 'Cauchy', 'variant_index': 0, 'run': run},
                              {'index': 1, 'value_index': 0, 'value': 0, 'seed': 7,
                               'variant': 'Gaussian', 'variant_index': 1, 'run': fixture('d' * 32)}]}
        self.save(parent_id, parent, artifact=True)
        grouped = self.index.query()
        self.assertEqual(grouped['total'], 2)
        self.assertEqual(grouped['overall_total'], 4)
        self.assertEqual(self.index.query(view='all')['total'], 4)
        preview = self.index.preview('artifact:' + parent_id)
        self.assertEqual(preview['status'], 'mixed')
        self.assertEqual(preview['attempt_counts'], {'failed': 1, 'success': 1})
        self.assertEqual(preview['unattempted'], 2)
        children = self.index.query(parent='artifact:' + parent_id, page_size=1)
        self.assertEqual((children['total'], len(children['items'])), (2, 1))
        self.assertEqual(children['overall_total'], 4)
        self.assertEqual(children['facets']['status'], ['failed', 'success'])
        self.assertEqual(self.index.query(parent='artifact:' + parent_id, sort='status')['items'][0]['status'], 'failed')
        child = children['items'][0]
        self.assertEqual(child['run_id'], run_id)
        self.assertEqual(child['cell'], {'value_index': 0, 'value': 0, 'seed': 7})
        self.assertEqual(child['attempts'][0]['error'], 'retained failed')
        self.assertEqual(self.index.preview(child['key'])['parent_key'], 'artifact:' + parent_id)
        self.assertEqual(self.index.preview('run:' + run_id)['parents'], ['artifact:' + parent_id])

    def test_unreadable_source_cache_corruption_and_rebuild_preserve_json(self):
        good = self.save('a' * 32)
        broken = self.directory / ('b' * 32 + '.json')
        broken.write_text('{BROKEN', encoding='utf-8')
        semantic = self.save('c' * 32, {'schema_version': '6.0', 'experiment': {}, 'status': {}})
        nan = self.directory / ('d' * 32 + '.json')
        nan.write_text('{"schema_version":"6.0","experiment":{},"status":NaN}', encoding='utf-8')
        before = {p.name: p.read_bytes() for p in (good, broken, semantic, nan)}
        self.assertEqual(self.index.query(status='unreadable')['filtered'], 3)
        self.index.cache_path.write_bytes(b'corrupt sqlite bytes')
        result = self.index.query()
        self.assertEqual(result['total'], 4)
        self.assertIn('cache_recovery', result['index'])
        self.assertEqual(len(list(self.directory.glob('.library.sqlite3.corrupt.*'))), 1)
        self.index.rebuild()
        self.assertEqual(self.index.query()['index']['changed'], 4)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (good, broken, semantic, nan)})

    def test_imported_comparison_retains_embedded_sources_without_local_copies(self):
        parent_id = 'e' * 32
        left = fixture('a' * 32, label='Retained left', status='failed')
        right = fixture('b' * 32, label='Retained right')
        right.pop('id')  # Original comparison sources need not have server IDs.
        comparison = {'schema_version': '2.0', 'artifact_type': 'comparison',
                      'id': parent_id, 'runs': [left, right], 'alignment': 'aligned'}
        path = self.save(parent_id, comparison, artifact=True)
        before = path.read_bytes()
        parent_key = 'artifact:' + parent_id
        grouped = self.index.query()
        self.assertEqual((grouped['total'], grouped['overall_total']), (1, 3))
        self.assertNotIn(left['id'], grouped['items'][0]['label'])
        self.assertEqual(grouped['items'][0]['child_count'], 2)
        self.assertEqual(grouped['items'][0]['attempt_counts'], {'failed': 1, 'success': 1})
        self.assertEqual(self.index.query(view='all', type='run')['filtered'], 2)
        children = self.index.query(parent=parent_key, page_size=1, page=2)
        self.assertEqual((children['total'], children['overall_total']), (2, 3))
        right_preview = children['items'][0]
        self.assertEqual(right_preview['comparison_side'], 1)
        self.assertEqual(right_preview['entry_ordinal'], 1)
        self.assertIsNone(right_preview['run_id'])
        self.assertEqual(right_preview['open_url'], '/api/comparisons/' + parent_id)
        self.assertEqual(right_preview['parent_open_url'], right_preview['open_url'])
        self.assertEqual(self.index.preview(parent_key + ':entry:0')['label'], 'Retained left')
        # A divergent local copy cannot replace the retained embedded source.
        self.save('a' * 32, fixture('a' * 32, label='Externally changed local source'))
        all_rows = self.index.query(view='all')
        self.assertEqual(all_rows['total'], 3)
        self.assertEqual(self.index.query()['total'], 2)
        self.assertEqual(self.index.preview(parent_key + ':entry:0')['label'], 'Retained left')
        self.assertEqual(self.index.preview('run:' + 'a' * 32)['label'], 'Externally changed local source')
        self.assertEqual(self.index.preview('run:' + 'a' * 32)['parents'], [parent_key])
        with patch('uwb.library._summary', side_effect=AssertionError('Warm comparison decode')):
            self.assertEqual(self.index.query(parent=parent_key)['total'], 2)
        self.assertEqual(path.read_bytes(), before)

    def test_running_interrupted_and_source_fingerprints(self):
        active_id, interrupted_id = 'a' * 32, 'b' * 32
        self.save(active_id, fixture(active_id, status='running'))
        self.save(interrupted_id, fixture(interrupted_id, status='running'))
        jobs = {active_id: {'status': 'running'}}
        index = LibraryIndex(self.directory, jobs=jobs)
        self.assertEqual(index.query(status='interrupted')['filtered'], 1)
        self.assertEqual(index.query(status='running')['filtered'], 1)
        rows = index.query()['items']
        self.assertEqual({r['status'] for r in rows}, {'running', 'interrupted'})
        self.assertEqual(rows[0]['observation_fingerprint'], rows[1]['observation_fingerprint'])
        self.assertEqual(rows[0]['starts_fingerprint'], rows[1]['starts_fingerprint'])
        self.save(interrupted_id, fixture(interrupted_id, seed=8))
        rows = index.query()['items']
        self.assertNotEqual(rows[0]['observation_fingerprint'], rows[1]['observation_fingerprint'])

    def test_metadata_endpoints_do_not_validate_or_solve_and_strict_open_rejects(self):
        from app import create_app
        identifier = 'a' * 32
        self.save(identifier)
        app = create_app(self.directory)
        if 'library_index' not in app.extensions:
            register_library(app, self.directory)
        client = app.test_client()
        with (patch('app.solve_experiment', side_effect=AssertionError('offline solve')),
             patch('app.generate_experiment', side_effect=AssertionError('offline generation')),
              patch('uwb.m6.validate_run', side_effect=ValueError('Strict invalid numerical fixture'))):
            self.assertEqual(client.get('/api/library').status_code, 200)
            result = client.get('/api/library/run:' + identifier)
            self.assertEqual(result.status_code, 200)
            self.assertIn('unchecked', result.json['summary_validation'])
            self.assertEqual(client.get(result.json['open_url']).status_code, 400)
            self.assertEqual(client.get('/api/library?sort=invalid').status_code, 400)
            self.assertEqual(client.get('/api/library/run:missing').status_code, 404)
            self.assertEqual(client.post('/api/library/rebuild').status_code, 200)

    def test_10000_metadata_fixture_is_bounded_and_warm_avoids_source_decodes(self):
        for i in range(10000):
            self.save(f'{i:032x}', fixture(f'{i:032x}'))
        cold = self.index.query()
        self.assertEqual(cold['total'], 10000)
        with patch('uwb.library._summary', side_effect=AssertionError('Warm source decode')):
            warm = self.index.query(page=200)
            self.assertEqual((len(warm['items']), warm['page_size'], warm['pages']), (25, 25, 400))
            self.assertLess(len(json.dumps(warm)), 100000)


if __name__ == '__main__':
    unittest.main()
