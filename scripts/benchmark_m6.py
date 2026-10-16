"""Retain paired local solver and wrapper timings; no general speed ranking."""
import json
from pathlib import Path
import sys
import time
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uwb import m6
from uwb.experiments import save_json


def main():
    root=Path('evidence/m6')/('benchmark_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
    root.mkdir(parents=True)
    summary={'status':'incomplete','records':[], 'scope':{'wrapper':'perf_counter around solve_experiment, includes objective/diagnostic construction and offline validation, excludes generation and disk saving',
        'solver':'sum saved per-start runtime_s; includes hard-rejection pilot and second stage, excludes wrapper truth evaluation',
        'limits':'Local small fixtures, one start, three repeated paired seeded data realizations; no general solver ranking or throughput claim'}}
    def record(): (root/'performance_benchmark.json').write_text(json.dumps(summary,indent=2,allow_nan=False))
    record()
    try:
        for samples in (12,24):
            for count in (4,8):
                for repeat in range(3):
                    exp=m6.generate_experiment({'samples':samples,'seed':7+repeat,'noise_std_m':.03,
                        'beacon_layout':{'count':count},'contamination':{'nlos':{'prevalence':.08,'magnitude_m':1.5}}})
                    initials=m6.make_initial_geometries(exp,{'starts':1,'mode':'joint','tag_height_model':'fixed'})
                    for loss in ('gaussian','huber','cauchy','hard_rejection'):
                        begun=time.perf_counter()
                        run=m6.solve_experiment(exp,{'starts':1,'mode':'joint','tag_height_model':'fixed','loss':loss,'max_nfev':500},initials)
                        elapsed=time.perf_counter()-begun
                        name=f'{samples}_{count}_{repeat}_{loss}.json';save_json(root/name,run)
                        summary['records'].append({'samples':samples,'beacons':count,'repeat':repeat,'loss':loss,
                            'observation_count':len(exp['estimator_input']['observations']),
                            'parameter_count':run['starts'][0].get('diagnostics',{}).get('jacobian',{}).get('parameter_count'),
                            'wrapper_s':elapsed,'solver_s':sum(s['solver']['runtime_s'] for s in run['starts']),
                            'statuses':[s['status'] for s in run['starts']], 'nfev':[s['solver']['nfev'] for s in run['starts']], 'run':name})
                        record()
        summary['status']='complete';record();print(root)
    except Exception as exc:
        summary['error']=f'{type(exc).__name__}: {exc}';record();raise


if __name__=='__main__':main()
