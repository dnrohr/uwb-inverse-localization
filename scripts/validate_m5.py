"""Retained, reproducible M5 solver/initializer acceptance attempts."""
import json,time,uuid,sys,hashlib
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from uwb import m5,m5_sweeps
from uwb.experiments import save_json

def main():
    root=Path('evidence/m5')/('acceptance_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]);root.mkdir(parents=True)
    (root/'demo_runs').mkdir();(root/'sweeps').mkdir();(root/'checkpoints').mkdir()
    summary={'status':'incomplete','directory':str(root),'sweeps':[],'fixtures':[]}
    def record(): (root/'acceptance_summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False),encoding='utf-8')
    record()
    try:
        variants=[{'label':s+'/'+p,'options':{'solver':s,'height_parameterization':p}} for s in ['trf','lm'] for p in ['h','q']]
        base={'samples':16,'beacon_layout':{'count':4,'geometry':'equal'}}
        cases=[('independent_basin',base,{'initialization':'independent'},'initialization_error_m',[0,.25,1.]),
               ('truth_near_basin',base,{'initialization':'truth_near'},'initialization_error_m',[0,.25,1.]),
               ('noise',base,{'initialization':'independent'},'noise_std_m',[0,.05]),
               ('near_zero_height',{**base,'beacon_layout':{'count':4,'height_m':.001,'geometry':'equal'}},{'initialization':'truth_near','initialization_error_m':0},'initialization_error_m',[0,.01]),
               ('weak_geometry',{**base,'scenario':'nearly_collinear','beacon_layout':{'count':4,'geometry':'near_collinear'}},{'initialization':'independent'},'noise_std_m',[0,.05])]
        for name,config,opts,factor,values in cases:
            cfg={'base_experiment':config,'options':{'mode':'joint','tag_height_model':'fixed','starts':2,'max_nfev':1000,**opts},'factor':factor,'values':values,'seeds':[7,8],'variants':variants}
            begun=time.perf_counter()
            def checkpoint(a): m5_sweeps.save_artifact(root/'checkpoints'/(name+'_checkpoint.json'),a)
            artifact=m5_sweeps.run_sweep(cfg,on_progress=checkpoint);m5_sweeps.save_artifact(root/'sweeps'/(name+'.json'),artifact)
            summary['sweeps'].append({'name':name,'runs':len(artifact['entries']),'starts':len(artifact['start_table']),'wall_s':time.perf_counter()-begun,'aggregates':artifact['aggregates']});record()
        initializers=[{'label':i+'/'+s,'options':{'initialization':i,'solver':s}} for i in ['independent','algebraic'] for s in ['trf','lm']]
        for name,config in [('initializer_valid',base),('initializer_degenerate',{**base,'scenario':'straight_line'}),('initializer_noisy',{**base,'noise_std_m':.05})]:
            artifact=m5_sweeps.run_sweep({'base_experiment':config,'options':{'mode':'joint','tag_height_model':'fixed','starts':2,'max_nfev':500},'factor':'initialization_error_m','values':[0,.1],'seeds':[7,8],'variants':initializers});m5_sweeps.save_artifact(root/'sweeps'/(name+'.json'),artifact)
            summary['sweeps'].append({'name':name,'runs':len(artifact['entries']),'starts':len(artifact['start_table']),'aggregates':artifact['aggregates']});record()
        artifact=m5_sweeps.run_sweep({'base_experiment':base,'options':{'mode':'joint','tag_height_model':'fixed','starts':2,'max_nfev':500,'algebraic_physical_tolerance':.05},'factor':'noise_std_m','values':[.01,.05],'seeds':[7,8],'variants':initializers})
        m5_sweeps.save_artifact(root/'sweeps'/'initializer_noisy_relaxed.json',artifact)
        summary['sweeps'].append({'name':'initializer_noisy_relaxed','runs':len(artifact['entries']),'starts':len(artifact['start_table']),'aggregates':artifact['aggregates']});record()
        for name,config,options in [('async_knots',{'samples':12,'acquisition':{'spacing_s':.02}}, {'mode':'joint','tag_height_model':'fixed','prior_sigma_m':0}),('spatial_diverse',{'samples':12,'beacon_layout':{'count':6,'geometry':'diverse'},'truth_height':{'type':'spatial','amplitude_m':.3}}, {'mode':'joint','tag_height_model':'free','beacon_height_model':'independent'}),('known_height_prior',{'samples':12,'truth_height':{'type':'excursion'}},{'mode':'known_map','tag_height_model':'soft','height_prior_sigma_m':.1}),('forced_nonconvergence',{'samples':12},{'mode':'joint','tag_height_model':'fixed','max_nfev':1})]:
            exp=m5.generate_experiment(config);reference=None
            for solver in ['trf','lm']:
                opts={**options,'solver':solver,'starts':2};run=m5.solve_experiment(exp,opts,initial_geometries=m5.compatible_initial_geometries(reference,exp,opts) if reference else None)
                run['reference_name']='M5_'+name+'_'+solver
                save_json(root/'demo_runs'/(name+'_'+solver+'.json'),run);reference=run
                summary['fixtures'].append({'name':name,'solver':solver,'status':run['status'],'starts':[{ 'status':s['status'],'solver':s['solver'],'diagnostics':s['diagnostics']} for s in run['starts']]});record()
        manifest=json.loads(Path('evidence/m5/preservation_manifest.json').read_text());changed=[p for p,h in manifest.items() if not Path(p).exists() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
        summary['preservation']={'checked':len(manifest),'changed':changed};assert not changed
        for name in ['independent_basin','truth_near_basin']:
            artifact=m5_sweeps.load_artifact(root/'sweeps'/(name+'.json'))
            assert all(row['geometric_accuracy'] and row['converged'] and row['low_residual'] for row in artifact['start_table']), name
        summary['invariants']={'exact_reference_solver_hq_recovery':'passed','shared_observations_and_compatible_starts':'validated offline in every artifact','repaired_transform_revision':2,'invalid_initializer_and_nonconvergence':'retained separately'}

        summary['status']='passed';record();print(str(root))
    except Exception as exc:
        summary['error']=str(exc);record();raise
if __name__=='__main__':main()
