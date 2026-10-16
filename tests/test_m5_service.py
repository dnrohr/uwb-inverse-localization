import tempfile,time,unittest,json
from pathlib import Path
from unittest.mock import patch
from app import create_app
from uwb import m5,m5_sweeps

class M5ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.client=create_app(self.temp.name).test_client()
    def tearDown(self):self.temp.cleanup()
    def wait(self,id):
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            job=self.client.get('/api/jobs/'+id).json
            if job['status']!='running':return job
            time.sleep(.02)
        self.fail('worker timeout')
    def test_run_offline_import_and_shared_comparison(self):
        ids=[]
        for solver in ('trf','lm'):
            resp=self.client.post('/api/m5/runs',json={'config':{'samples':8},'options':{'solver':solver,'height_parameterization':'q','tag_height_model':'fixed','starts':1}})
            self.assertEqual(resp.status_code,202,resp.json);id=resp.json['id'];ids.append(id)
            job=self.wait(id);self.assertEqual(job['status'],'complete',job)
            with patch.object(m5,'solve_experiment',side_effect=AssertionError('offline')),patch.object(m5,'generate_experiment',side_effect=AssertionError('offline')):
                self.assertEqual(self.client.get('/api/runs/'+id).json,job['run'])
                imp=self.client.post('/api/m5/import',json=job['run']);self.assertEqual(imp.status_code,200,imp.json)
        comparison=self.client.post('/api/comparisons',json={'run_ids':ids,'alignment':'aligned'})
        self.assertEqual(comparison.status_code,200,comparison.json)
        self.assertFalse(comparison.json['artifact']['views'][0]['estimate'] is None)
    def test_failed_initializer_and_all_sweep_attempts_saved(self):
        response=self.client.post('/api/m5/sweeps',json={'base_experiment':{'samples':8,'scenario':'straight_line'},'options':{'initialization':'algebraic','starts':2},'factor':'initialization_error_m','values':[0],'seeds':[7],'variants':[{'label':'invalid trf','options':{'solver':'trf'}},{'label':'invalid lm','options':{'solver':'lm'}}]})
        self.assertEqual(response.status_code,202,response.json);id=response.json['id'];job=self.wait(id)
        self.assertEqual(job['status'],'complete',job);self.assertEqual(len(job['artifact']['start_table']),4)
        self.assertTrue(all(row['status']=='failed' for row in job['artifact']['start_table']))
        self.assertEqual(self.client.get('/api/m5/sweeps/'+id).status_code,200)
        self.assertEqual(self.client.get('/api/m5/sweeps/'+id+'/csv').status_code,200)
    def test_unsupported_q_rejected_before_queue(self):
        response=self.client.post('/api/m5/runs',json={'config':{'samples':8},'options':{'height_parameterization':'q','tag_height_model':'free'}})
        self.assertEqual(response.status_code,400)

    def test_interrupted_unique_temporary_checkpoint_is_recovered(self):
        data = m5_sweeps.run_sweep({'base_experiment': {'samples': 8}, 'options': {'mode': 'known_map', 'starts': 1, 'max_nfev': 1},
            'factor': 'coverage', 'values': [1], 'seeds': [7], 'variants': [{'label': 'fixed', 'options': {'solver': 'trf'}}]})
        identifier = 'b'*32; data.update(id=identifier, status='running')
        folder = Path(self.temp.name)/'artifacts'
        (folder/(identifier+'.json')).write_text(json.dumps({'schema_version': '5.0', 'artifact_type': 'solver_sweep',
            'config': data['config'], 'entries': [], 'status': 'running'}))
        m5_sweeps.save_artifact(folder/(identifier+'.json.recovery.tmp'), data)
        response = self.client.get('/api/m5/sweeps/'+identifier)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['status'], 'failed')
        self.assertEqual(len(response.json['entries']), 1)
        self.assertIn('no implicit restart', response.json['error'])

    def test_persistence_failure_keeps_numerical_success_separate(self):
        from uwb.experiments import save_json
        failed_once=False
        def transient(path,data):
            nonlocal failed_once
            if data.get('status')=='success' and not failed_once:
                failed_once=True;raise OSError('controlled write failure')
            save_json(path,data)
        with patch('uwb.m5_service.save_json',side_effect=transient):
            response=self.client.post('/api/m5/runs',json={'config':{'samples':8},'options':{'mode':'known_map','tag_height_model':'fixed','starts':1}})
            job=self.wait(response.json['id'])
        self.assertEqual(job['status'],'failed');self.assertEqual(job['run']['status'],'success');self.assertEqual(job['run']['infrastructure_status'],'failed')

    def test_summary_cache_invalidates_after_file_change_and_details_validate(self):
        from uwb.experiments import save_json
        run=m5.solve_experiment(m5.generate_experiment({'samples':8}),{'tag_height_model':'fixed','starts':1})
        id='c'*32;run['id']=id;path=Path(self.temp.name)/(id+'.json');save_json(path,run)
        self.assertEqual(self.client.get('/api/runs').json[0]['status'],'success')
        run['reference_name']='changed summary';save_json(path,run)
        self.assertEqual(self.client.get('/api/runs').json[0]['reference_name'],'changed summary')
        run['starts'][0]['solver']['final_objective']=99.;path.write_text(json.dumps(run),encoding='utf-8')
        self.assertEqual(self.client.get('/api/runs').json[0]['status'],'unreadable')
        self.assertEqual(self.client.get('/api/runs/'+id).status_code,400)
