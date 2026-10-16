"""Cross-version offline boundaries and authoritative Library source comparison."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import create_app
from uwb import m6, m7, sweeps
from uwb.experiments import save_json


class M7IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        coordinates = [[4.,2.,3.],[14.,2.,3.],[5.,10.,3.],[15.,11.,3.]]
        exp = m6.generate_experiment({'samples':8,'beacon_layout':{'coordinates_m':coordinates}})
        cls.fixture_run = m7.solve_experiment(exp, {'mode':'joint','tag_height_model':'fixed',
            'beacon_height_model':'independent','starts':1,'max_nfev':200,
            'survey':{'frame':'world','units':'m','fixed':[
                {'beacon_id':i,'mask':[True,True,True],'mean_m':b} for i,b in enumerate(coordinates)],'priors':[]}})

    def test_survey_world_comparison_and_strict_offline_import(self):
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(folder); client=app.test_client()
            with (patch.object(m7,'solve_experiment',side_effect=AssertionError('offline')),
                  patch.object(m6,'generate_experiment',side_effect=AssertionError('offline'))):
                identifiers=[]
                for _ in range(2):
                    response=client.post('/api/m7/import',json=self.fixture_run)
                    self.assertEqual(response.status_code,200,response.json)
                    identifier=response.json['id']; identifiers.append(identifier)
                    reopened=client.get('/api/runs/'+identifier)
                    self.assertEqual(reopened.status_code,200,reopened.json)
                    self.assertEqual(reopened.json['experiment'],self.fixture_run['experiment'])
                    self.assertEqual(client.get('/api/m7/runs/'+identifier+'/csv').status_code,200)
                comparison=client.post('/api/library/compare',json={'keys':['run:'+i for i in identifiers],'alignment':'aligned'})
                self.assertEqual(comparison.status_code,200,comparison.json)
                artifact=comparison.json['artifact']
                self.assertTrue(artifact['pairing']['paired'])
                self.assertEqual(artifact['views'][0]['truth']['beacons'],self.fixture_run['experiment']['truth']['beacons'])
                self.assertFalse(artifact['views'][0]['alignment']['applied'])
                corrupt=copy.deepcopy(artifact);corrupt['pairing']['identical_estimator_inputs']=False
                with self.assertRaises(ValueError): sweeps.validate_artifact(corrupt)

    def test_summary_preview_never_calls_full_record_validator(self):
        with tempfile.TemporaryDirectory() as folder:
            identifier='c'*32;save_json(Path(folder)/(identifier+'.json'),self.fixture_run)
            client=create_app(folder).test_client()
            with patch.object(m7,'validate_run',side_effect=AssertionError('metadata listing must not validate numerical data')):
                response=client.get('/api/library?view=all')
                self.assertEqual(response.status_code,200,response.json)
                self.assertEqual(len(response.json['items']),1)
                self.assertEqual(client.get('/api/library/run:'+identifier).status_code,200)

    def test_import_keeps_supplied_identifier_and_original_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            client=create_app(folder).test_client()
            source=copy.deepcopy(self.fixture_run)
            source.update(id='a'*32,source='declared original source',reference_name='Original label')
            response=client.post('/api/m7/import',json=source)
            self.assertEqual(response.status_code,200,response.json)
            saved=response.json['run']
            self.assertNotEqual(saved['id'],source['id'])
            self.assertEqual(saved['source_id'],source['id'])
            self.assertEqual(saved['source'],source['source'])
            self.assertEqual(saved['reference_name'],source['reference_name'])
            summary=client.get('/api/library').json['items'][0]
            self.assertEqual(summary['source'],'imported')


if __name__=='__main__': unittest.main()
