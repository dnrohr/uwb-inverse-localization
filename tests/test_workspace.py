"""Contract checks for shared state, native dispatch and offline preservation."""
import copy
import csv
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from app import create_app
from uwb import workspace, m6, m7
from uwb import sweeps


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.app = create_app(self.directory)
        self.client = self.app.test_client()
        self.models = self.client.get('/api/workspace/capabilities').json['models']

    def tearDown(self):
        self.temp.cleanup()

    def draft(self, engine='robust'):
        d = copy.deepcopy(self.models[engine]['defaults'])
        d['physical']['samples'] = 8
        d['numerical'].update(starts=1, max_nfev=40)
        return d

    def wait(self, identifier):
        for _ in range(200):
            r = self.client.get('/api/jobs/' + identifier).json
            if r['status'] not in ('running', 'pending'):
                return r
            time.sleep(.02)
        self.fail('Job did not finish')

    def test_capability_normalization_never_generates_or_solves(self):
        with patch.object(m6, 'generate_experiment', side_effect=AssertionError('generated')), patch.object(m7, 'solve_experiment', side_effect=AssertionError('fit')):
            for engine in self.models:
                with self.subTest(engine=engine):
                    d = self.draft(engine)
                    r = self.client.post('/api/workspace/validate', json=d)
                    self.assertEqual(r.status_code, 200, r.json)
                    self.assertEqual(r.json['engine'], engine)
                    self.assertEqual(workspace.normalize(r.json['configuration'])[0], r.json['configuration'])
        self.assertEqual(list(self.directory.glob('*.json')), [])

    def test_native_parity_for_every_engine(self):
        for engine in self.models:
            with self.subTest(engine=engine):
                d = self.draft(engine)
                normalized, config, opts = workspace.normalize(d)
                generator, fitter, _, schema = workspace.ENGINES[engine]
                exp = generator.generate_experiment(config)
                expected = fitter.solve_experiment(exp, opts)
                created = self.client.post('/api/workspace/runs', json=d)
                self.assertEqual(created.status_code, 202, created.json)
                actual = self.wait(created.json['id'])['run']
                self.assertEqual(actual['schema_version'], schema)
                self.assertEqual(actual['experiment'], exp)
                self.assertEqual(actual['options'], opts)
                self.assertEqual(actual['status'], expected['status'])
                for a, b in zip(actual['starts'], expected['starts']):
                    self.assertEqual(a['initial'], b['initial'])
                    self.assertEqual(a['status'], b['status'])
                    if a.get('estimate'):
                        np.testing.assert_allclose(a['estimate']['trajectory'], b['estimate']['trajectory'], rtol=0, atol=1e-10)
                        self.assertEqual(a['diagnostics']['jacobian']['rank'], b['diagnostics']['jacobian']['rank'])
                self.assertEqual(actual['workspace_configuration'], normalized)

    def test_saved_reuse_and_complete_offline_csv(self):
        d = self.draft()
        run = self.wait(self.client.post('/api/workspace/runs', json=d).json['id'])['run']
        path = self.directory / (run['id'] + '.json')
        original = path.read_bytes()
        with patch.object(m6, 'generate_experiment', side_effect=AssertionError('regenerated')), patch.object(m6, 'solve_experiment', side_effect=AssertionError('refitted')):
            r = self.client.post('/api/workspace/configuration', json={'key':'run:'+run['id'], 'reuse':True})
            self.assertEqual(r.status_code, 200, r.json)
            reuse = r.json['configuration']
            self.assertEqual(self.client.post('/api/workspace/validate', json=reuse).status_code, 200)
            exported = self.client.post('/api/workspace/export/csv', json={'key':'run:'+run['id']})
            self.assertEqual(exported.status_code, 200)
            records = list(csv.DictReader(io.StringIO(exported.text)))
            self.assertEqual([json.loads(x['complete_record_json']) for x in records if x['record_type']=='attempt'], run['starts'])
            self.assertEqual([json.loads(x['complete_record_json']) for x in records if x['record_type']=='observation'],run['experiment']['estimator_input']['observations'])
            self.assertEqual(self.client.get('/api/runs/'+run['id']).status_code, 200)
        reuse['numerical']['max_nfev'] = 15
        with patch.object(m6, 'generate_experiment', side_effect=AssertionError('regenerated')):
            submitted = self.client.post('/api/workspace/runs', json=reuse)
            self.assertEqual(submitted.status_code, 202, submitted.json)
            new = self.wait(submitted.json['id'])['run']
            self.assertEqual(new['experiment'],run['experiment'])
        self.assertEqual(path.read_bytes(), original)
        reuse['physical']['seed'] += 1
        self.assertEqual(self.client.post('/api/workspace/validate',json=reuse).status_code, 400)

    def test_unsupported_combinations_never_fallback(self):
        d = self.draft('survey')
        d['numerical']['initialization'] = 'algebraic'
        self.assertEqual(self.client.post('/api/workspace/validate', json=d).status_code,400)
        d = self.draft('solver')
        d['numerical']['height_parameterization'] = 'q'
        d['assumptions']['tag_height_model'] = 'free'
        self.assertEqual(self.client.post('/api/workspace/validate', json=d).status_code,400)
        d = self.draft()
        d['physical']['assumed_std_m'] = .05
        self.assertEqual(self.client.post('/api/workspace/validate', json=d).status_code,400)
        d = self.draft()
        d['workspace_version'] = 2
        self.assertEqual(self.client.post('/api/workspace/validate', json=d).status_code,400)
        d=self.draft('planar');d['study']={'kind':'parameter','factor':'initial_error_m','values':[0,1],'seeds':[7]}
        self.assertEqual(self.client.post('/api/workspace/validate',json=d).status_code,400)
        d['numerical']['initialization']='truth_near'
        self.assertEqual(self.client.post('/api/workspace/validate',json=d).status_code,200)
        self.assertEqual(list(self.directory.glob('*.json')), [])

    def test_malformed_requests_and_native_configuration_import(self):
        for route in ('validate', 'runs', 'studies', 'configuration', 'export/csv'):
            self.assertEqual(self.client.post('/api/workspace/'+route, json=[]).status_code,400)
        d = self.draft()
        d['workspace_version'] = True
        self.assertEqual(self.client.post('/api/workspace/validate', json=d).status_code,400)
        for engine in self.models:
            d = self.draft(engine)
            _, config, options = workspace.normalize(d)
            record = {'artifact_type':'experiment_config','schema_version':workspace.ENGINES[engine][3],
                      'config':config,'options':options}
            response = self.client.post('/api/workspace/configuration',json={'native_configuration':record})
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual(response.json['configuration'],workspace.normalize(d)[0])

    def test_every_native_study_validates_without_generation(self):
        factors = {'planar':('noise_std_m',[0,.05]), 'timing':('spacing_s',[0,.01]),
                   'spatial':('beacon_count',[3,4]),'solver':('initialization_error_m',[0,1]),
                   'robust':('nlos_prevalence',[0,.05])}
        for engine,(factor,values) in factors.items():
            d = self.draft(engine)
            d['study']={'kind':'parameter','factor':factor,'values':values,'seeds':[7]}
            with patch.object(workspace.ENGINES[engine][0],'generate_experiment',side_effect=AssertionError('generated')):
                response=self.client.post('/api/workspace/validate',json=d)
            self.assertEqual(response.status_code,200,(engine,response.json))
            self.assertEqual(response.json['engine'],engine)
        d=self.draft('survey');d['study']={'kind':'parameter'}
        self.assertEqual(self.client.post('/api/workspace/validate',json=d).status_code,400)

    def test_descriptive_library_search_keeps_original_metadata(self):
        record={'id':'d'*32,'schema_version':'7.0','reference_name':'M7_invalid_physical_start',
                'experiment':{'config':{'scenario':'informative'}},'options':{},'status':'failed','starts':[]}
        path=self.directory/('d'*32+'.json');path.write_text(json.dumps(record));original=path.read_bytes()
        response=self.client.get('/api/library?q=survey+invalid+physical+start')
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['filtered'],1)
        self.assertEqual(response.json['items'][0]['reference_name'],record['reference_name'])
        self.assertEqual(path.read_bytes(),original)

    def test_request_failure_remains_inspectable(self):
        d = self.draft()
        with patch.object(m6, 'solve_experiment', side_effect=RuntimeError('infrastructure probe')):
            r = self.client.post('/api/workspace/runs',json=d)
            job = self.wait(r.json['id'])
        self.assertEqual(job['status'], 'failed')
        self.assertIn('infrastructure probe', job['run']['error'])
        saved = self.client.get('/api/runs/'+r.json['id'])
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertEqual(saved.json['workspace_configuration'], workspace.normalize(d)[0])

    def test_native_study_dispatch_and_pairing(self):
        d = self.draft()
        d['study'] = {'kind':'parameter','factor':'noise_std_m','values':[0.], 'seeds':[7],
            'variants':[{'label':'Gaussian','options':{'loss':'gaussian'}},{'label':'Huber','options':{'loss':'huber'}}]}
        r = self.client.post('/api/workspace/studies',json=d)
        self.assertEqual(r.status_code,202,r.json)
        artifact = self.wait(r.json['id'])['artifact']
        self.assertEqual(artifact['artifact_type'],'robust_sweep')
        self.assertEqual(len(artifact['entries']),2)
        a,b = [x['run'] for x in artifact['entries']]
        self.assertEqual(a['experiment']['estimator_input'], b['experiment']['estimator_input'])
        self.assertEqual(a['starts'][0]['initial'], b['starts'][0]['initial'])
        self.assertEqual(sum(len(x['run']['starts']) for x in artifact['entries']), 2)

    def test_embedded_comparison_sources_and_offline_export(self):
        d=self.draft()
        run=self.wait(self.client.post('/api/workspace/runs',json=d).json['id'])['run']
        other=copy.deepcopy(run)
        other['id']='b'*32
        comparison=sweeps.build_comparison(run,other,alignment='raw')
        comparison['id']='c'*32
        sweeps.save_artifact(self.directory/'artifacts'/('c'*32+'.json'),comparison)
        # A local file with the embedded source ID has different observations.
        divergent=copy.deepcopy(other)
        divergent['experiment']=m6.generate_experiment({**d['physical'],'assumed_std_m':.05,'seed':99})
        divergent['starts']=[];divergent['selected_start']=None;divergent['status']='failed'
        divergent['error']='different local source'
        (self.directory/('b'*32+'.json')).write_text(json.dumps(divergent))
        with patch.object(m6,'generate_experiment',side_effect=AssertionError('generated')),patch.object(m6,'solve_experiment',side_effect=AssertionError('fit')):
            response=self.client.post('/api/workspace/configuration',json={'key':'artifact:'+comparison['id']+':entry:1','reuse':True})
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual(response.json['configuration']['physical']['seed'],other['experiment']['config']['seed'])
            exported=self.client.post('/api/workspace/export/csv',json={'artifact':comparison})
            self.assertEqual(exported.status_code,200,exported.json)
            self.assertEqual(len(list(csv.DictReader(io.StringIO(exported.text)))),2)


if __name__ == '__main__':
    unittest.main()
