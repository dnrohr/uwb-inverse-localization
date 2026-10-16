"""Retain M4 numerical benchmark attempts in a fresh directory."""
from pathlib import Path
import json
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from uwb.m4_sweeps import run_sweep,save_artifact


def main():
    output=Path(__file__).resolve().parents[1]/'evidence'/'m4'/('benchmark_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
    output.mkdir(parents=True,exist_ok=False)
    records=[]
    for count in (3,8):
        for samples in (12,24):
            started=time.perf_counter()
            artifact=run_sweep({'base_experiment':{'samples':samples,'noise_std_m':.05,'beacon_layout':{'count':count,'geometry':'diverse','height_spread_m':1},'truth_height':{'type':'excursion','amplitude_m':.3},'acquisition':{'spacing_s':.02}},
                                'options':{'mode':'known_map','starts':2,'initialization':'independent','max_nfev':150},
                                'factor':'height_prior_sigma_m','values':[.2],'seeds':[7],
                                'variants':[{'label':'fixed','options':{'tag_height_model':'fixed'}},{'label':'free','options':{'tag_height_model':'free'}}]},
                               on_progress=lambda data:save_artifact(output/'checkpoints'/f'{count}_{samples}.json',data))
            save_artifact(output/f'{count}_{samples}.json',artifact)
            records.append({'beacons':count,'samples':samples,'wrapper_wall_s':time.perf_counter()-started,'start_table':artifact['start_table'],'aggregates':artifact['aggregates']})
            print(count,samples,records[-1]['wrapper_wall_s'],flush=True)
    (output/'performance_benchmark.json').write_text(json.dumps(records,indent=2,allow_nan=False),encoding='utf-8')
    print(output,flush=True)


if __name__=='__main__':main()
