"""Disposable metadata-only history server for browser scale acceptance."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import create_app

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--count',type=int,choices=(0,10000),required=True)
    parser.add_argument('--port',type=int,required=True);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='uwb-m7-browser-') as folder:
        start=time.perf_counter()
        for i in range(args.count):
            identifier=f'{i:032x}'
            data={'schema_version':'6.0','id':identifier,'reference_name':f'Isolated metadata fixture {i:05d}',
                  'status':['success','failed','not_converged','running'][i%4],
                  'experiment':{'config':{'scenario':'informative','seed':i,'noise_std_m':[.02]*4},
                                'estimator_input':{'observations':[]}},
                  'options':{'mode':'joint','solver':'trf','loss':'gaussian','starts':1},
                  'starts':[], 'selected_start':None}
            (Path(folder)/(identifier+'.json')).write_text(json.dumps(data),encoding='utf-8')
        print(json.dumps({'fixture_count':args.count,'directory':folder,'creation_seconds':time.perf_counter()-start,
                          'scope':'Metadata-only synthetic records deliberately fail strict numerical Open; not user history'}),flush=True)
        create_app(folder).run(host='127.0.0.1',port=args.port,debug=False)
