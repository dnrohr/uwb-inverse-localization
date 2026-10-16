"""Create fresh, checkpointed M4 evidence without changing prior history."""
from pathlib import Path
import copy
import hashlib
import json
import sys
import time
import traceback
import uuid
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uwb import m4
from uwb.m4_sweeps import run_sweep, save_artifact, load_artifact, table_csv
ROOT = Path(__file__).resolve().parents[1]


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream: json.dump(data, stream, indent=2, allow_nan=False)


def chosen(run):
    return next((s for s in run['starts'] if s['index'] == run['selected_start']), None)


def fingerprint():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('evidence','runs')
            for p in (ROOT/folder).rglob('*') if p.is_file() and not p.is_relative_to(ROOT/'evidence'/'m4')}


def execute(output, name, config, options, initials=None):
    experiment = m4.generate_experiment(config)
    try:
        run = m4.solve_experiment(experiment, options, initial_geometries=initials)
    except Exception as exc:
        write(output/'failed_attempts'/(name+'.json'), {'experiment':experiment,'options':options,'initial_geometries':initials,'error':f'{type(exc).__name__}: {exc}'})
        raise
    write(output/'demo_runs'/(name+'.json'), run)
    m4.validate_run(run)
    print('fixture', name, run['status'], flush=True)
    return run


def main():
    before = fingerprint()
    output = ROOT/'evidence'/'m4'/('acceptance_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
    output.mkdir(parents=True, exist_ok=False)
    summary = {'output':str(output.relative_to(ROOT)), 'sweeps':[], 'fixtures':[], 'invariants':[],
               'interpretation':'Every attempt is retained. Full measurement rank is local; height priors and branch constraints are assumptions.'}
    try:
        base = {'samples':12,'duration_s':6,'path':{'type':'rectangle'}, 'beacon_layout':{'count':6,'geometry':'diverse','height_spread_m':1},
                'truth_height':{'type':'excursion','amplitude_m':.35}}
        opts = {'mode':'known_map','starts':2,'initialization':'independent','max_nfev':150}
        variants = [{'label':'fixed','options':{'tag_height_model':'fixed'}},{'label':'free','options':{'tag_height_model':'free'}}]
        factors = [('beacon_count',[3,4,6,8]),('vertical_separation',[1.,3.]),('height_spread',[0.,1.]),('coverage',[.5,2.]),('height_prior_sigma_m',[.05,1.]),('beacon_height_model',['shared','independent'])]
        for factor, values in factors:
            models = variants
            if factor == 'height_prior_sigma_m': models = [{'label':'soft','options':{'tag_height_model':'soft'}},{'label':'free','options':{'tag_height_model':'free'}}]
            current = {'base_experiment':base,'options':opts,'factor':factor,'values':values,'seeds':[7,8],'variants':models}
            if factor == 'beacon_height_model':
                current['base_experiment'] = {**base,'beacon_layout':{'count':6,'geometry':'equal'},'truth_height':{'type':'planar'}}
                current['options'] = {**opts,'mode':'joint','initialization':'truth_near','max_nfev':300}
                current['variants'] = [{'label':'fixed','options':{'tag_height_model':'fixed'}},{'label':'shared_tag','options':{'tag_height_model':'shared'}}]
            start = time.perf_counter()
            artifact = run_sweep(current, on_progress=lambda data: save_artifact(output/'checkpoints'/(factor+'.json'),data))
            target = output/'sweeps'/(factor+'.json')
            save_artifact(target, artifact)
            assert load_artifact(target) == artifact
            target.with_suffix('.csv').write_text(table_csv(artifact),encoding='utf-8')
            summary['sweeps'].append({'factor':factor,'wall_s':time.perf_counter()-start,'runs':len(artifact['entries']),'starts':len(artifact['start_table']),'aggregates':artifact['aggregates']})
            print('sweep',factor,len(artifact['entries']),flush=True)
        simple = {'samples':12,'duration_s':6,'path':{'type':'rectangle'},'beacon_layout':{'count':4,'geometry':'equal','height_m':3},'truth_height':{'type':'excursion','amplitude_m':.35}}
        free_opts = {'mode':'known_map','tag_height_model':'free','starts':1,'initialization':'truth_near','max_nfev':300}
        low = execute(output,'coplanar_lower_branch',simple,free_opts)
        reflected = copy.deepcopy([s['initial'] for s in low['starts']])
        for initial in reflected:
            for key in ('trajectory','knot_trajectory','ping_trajectory','assumed_ping_trajectory'):
                if key in initial:
                    for point in initial[key]: point[2] = 6-point[2]
        high = execute(output,'coplanar_reflected_branch',simple,free_opts,reflected)
        # Persist both branches before testing their observational equivalence.
        assert chosen(low) and chosen(high)
        assert chosen(low)['diagnostics']['max_abs_residual_m'] < 1e-7
        assert chosen(high)['diagnostics']['max_abs_residual_m'] < 1e-7
        assert chosen(high)['diagnostics']['evaluation']['raw']['position_rmse_m'] > 1
        summary['invariants'].append({'name':'coplanar_reflection_ambiguity','passed':True})
        below = execute(output,'below_beacons_nonplanar',simple,{**free_opts,'initialization':'independent','below_beacons':True,'starts':2})
        assert chosen(below)['diagnostics']['evaluation']['raw']['position_max_error_m'] < 1e-5
        assert np.ptp(np.array(chosen(below)['estimate']['trajectory'])[:,2]) > .1
        assert chosen(below)['diagnostics']['height']['best_fit_plane']['rms_departure_m'] > .01
        summary['invariants'].append({'name':'below_branch_without_planarity','passed':True})
        demos = [
            ('noncoplanar_height_recovery',base,{**free_opts,'initialization':'independent','starts':2}),
            ('tilted_plane',{**base,'truth_height':{'type':'tilted','tilt_deg':8}},free_opts),
            ('warped_spatial',{**base,'truth_height':{'type':'spatial','amplitude_m':.6}},free_opts),
            ('planar_mismatch',base,{**free_opts,'tag_height_model':'fixed','initialization':'independent','starts':2}),
            ('soft_height_prior',base,{**free_opts,'tag_height_model':'soft','height_prior_sigma_m':.05}),
            ('joint_shared_recovery',{**base,'beacon_layout':{'count':6,'geometry':'equal'},'truth_height':{'type':'planar'}},{'mode':'joint','tag_height_model':'fixed','beacon_height_model':'shared','starts':2,'initialization':'independent','max_nfev':1000}),
            ('joint_independent_recovery',{**base,'truth_height':{'type':'planar'}},{'mode':'joint','tag_height_model':'fixed','beacon_height_model':'independent','starts':2,'initialization':'independent','max_nfev':1000}),
            ('joint_free_shared_coplanar',{**base,'beacon_layout':{'count':4,'geometry':'equal'},'truth_height':{'type':'spatial','amplitude_m':.6}},{'mode':'joint','tag_height_model':'free','beacon_height_model':'shared','starts':2,'initialization':'truth_near','max_nfev':200}),
            ('joint_free_independent_noncoplanar',{**base,'truth_height':{'type':'spatial','amplitude_m':.6}},{'mode':'joint','tag_height_model':'free','beacon_height_model':'independent','starts':2,'initialization':'truth_near','max_nfev':300}),
            ('collinear_rank_loss',{**base,'beacon_layout':{'count':3,'geometry':'collinear'},'truth_height':{'type':'planar'}},{'mode':'joint','tag_height_model':'fixed','starts':2,'initialization':'truth_near','max_nfev':150}),
            ('async_three_beacons',{**base,'beacon_layout':{'count':3,'geometry':'diverse','height_spread_m':1},'motion':{'profile':'variable'},'acquisition':{'spacing_s':.04}}, {**free_opts,'initialization':'independent','starts':2}),
            ('async_eight_beacons',{**base,'beacon_layout':{'count':8,'geometry':'diverse','height_spread_m':1},'motion':{'profile':'variable'},'acquisition':{'spacing_s':.04}}, {**free_opts,'initialization':'independent','starts':2}),
            ('forced_nonconverged',base,{'mode':'joint','tag_height_model':'fixed','starts':2,'initialization':'independent','max_nfev':1}),
        ]
        retained = {}
        for name, config, options in demos:
            run = execute(output,name,config,options)
            retained[name] = run
            start = chosen(run)
            summary['fixtures'].append({'name':name,'status':run['status'],'options':run['options'],'diagnostics':run['diagnostics'],
                                        'selected_diagnostics':start['diagnostics'] if start else None,'start_statuses':[s['status'] for s in run['starts']]})
        assert chosen(retained['noncoplanar_height_recovery'])['diagnostics']['evaluation']['raw']['position_max_error_m'] < 1e-5
        assert retained['collinear_rank_loss']['diagnostics']['truth_jacobian']['full_column_rank'] is False
        assert all(s['status']=='not_converged' for s in retained['forced_nonconverged']['starts'])
        for path,digest in before.items(): assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest,path
        summary['preservation'] = {'files_checked':len(before),'unchanged':True}
        write(output/'acceptance_summary.json',summary)
        print('saved',output,flush=True)
    except Exception:
        write(output/'incomplete_summary.json',{**summary,'error':traceback.format_exc()})
        raise


if __name__ == '__main__': main()
