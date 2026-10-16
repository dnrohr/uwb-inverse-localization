"""Paired modest-size timing samples; no optimizer is selected by speed alone."""
import json,time,uuid,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from uwb import m5
from uwb.experiments import save_json

def main():
    folder=Path('evidence/m5')/('benchmark_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
    records=[]
    for count in [4,8]:
        for samples in [12,24]:
            exp=m5.generate_experiment({'samples':samples,'noise_std_m':.05,'beacon_layout':{'count':count,'geometry':'equal'}})
            opts={'mode':'joint','tag_height_model':'fixed','starts':2,'max_nfev':1000};starts=m5.make_initial_geometries(exp,opts)
            for repeat in range(3):
                for solver in ['trf','lm']:
                    for parameter in ['h','q']:
                        begun=time.perf_counter();run=m5.solve_experiment(exp,{**opts,'solver':solver,'height_parameterization':parameter},starts);elapsed=time.perf_counter()-begun
                        save_json(folder/f'{count}b_{samples}samples_r{repeat}_{solver}_{parameter}.json',run)
                        records.append({'repeat':repeat,'count':count,'samples':samples,'solver':solver,'height_parameterization':parameter,'wrapper_wall_s':elapsed,'status':run['status'],'start_runtimes_s':[s['solver']['runtime_s'] for s in run['starts']],'start_statuses':[s['status'] for s in run['starts']]})
                        (folder/'performance_benchmark.json').write_text(json.dumps({'records':records,'scope':'Same noisy observations and physical starts per size; wrapper includes fitting, diagnostic evaluation and validation; excludes JSON disk save; no accuracy guarantee'},indent=2),encoding='utf-8')
    print(folder)
if __name__=='__main__':main()
