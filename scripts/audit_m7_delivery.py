"""Reconcile M7 preservation, strict offline boundaries and retained evidence."""
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import app as service
from uwb import experiments, estimation, m3, m4, m5, m6, m7
from uwb import sweeps, m3_sweeps, m4_sweeps, m5_sweeps, m6_sweeps


def read(path): return json.loads((ROOT/path).read_text(encoding='utf-8'))
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def forbidden_work():
    stack=ExitStack()
    for module in (service,experiments,estimation,m3,m4,m5,m6,m7):
        for name in ('generate_experiment','solve_experiment','fit_observations','least_squares'):
            if hasattr(module,name):
                stack.enter_context(patch.object(module,name,side_effect=AssertionError('Offline workflow attempted '+name)))
    return stack


def offline_audit(report):
    candidates={}
    for path in sorted((ROOT/'runs').glob('*.json')):
        raw=json.loads(path.read_text(encoding='utf-8'))
        version=raw.get('schema_version'); status=raw.get('status')
        if 'experiment' in raw and version in ('1.0','3.0','4.0','5.0','6.0','7.0'):
            candidates.setdefault((version,status),path)
    families={}
    for path in sorted((ROOT/'runs/artifacts').glob('*.json')):
        raw=json.loads(path.read_text(encoding='utf-8'))
        if raw.get('entries') or raw.get('artifact_type')=='comparison':
            families.setdefault(raw.get('artifact_type'),path)
    assert {v for v,s in candidates}=={'1.0','3.0','4.0','5.0','6.0','7.0'}
    assert {'sweep','comparison','timing_sweep','geometry_sweep','solver_sweep','robust_sweep'} <= set(families)
    report['offline_runs']=[];report['offline_artifacts']=[]
    with tempfile.TemporaryDirectory(prefix='m7-offline-audit-') as folder, forbidden_work():
        client=service.create_app(folder).test_client()
        for (version,status),path in candidates.items():
            original=read(path.relative_to(ROOT)); fingerprint=digest(path)
            endpoint='/api/m7/import' if version=='7.0' else '/api/import'
            response=client.post(endpoint,json=original)
            assert response.status_code==200,(path,response.json)
            identifier=response.json['id']; reopened=client.get('/api/runs/'+identifier)
            assert reopened.status_code==200,(path,reopened.json)
            assert reopened.json['experiment']==original['experiment']
            assert reopened.json['starts']==original['starts']
            assert reopened.json.get('source_id')==original.get('source_id',original.get('id'))
            assert digest(path)==fingerprint
            if version=='7.0':
                assert client.get('/api/m7/runs/'+identifier+'/csv').status_code==200
                assert client.get('/api/m7/runs/'+identifier+'/uncertainty').status_code==200
            report['offline_runs'].append({'source':str(path.relative_to(ROOT)),'schema':version,'status':status,'sha256':fingerprint})
        loaders={'sweep':sweeps,'comparison':sweeps,'timing_sweep':m3_sweeps,
                 'geometry_sweep':m4_sweeps,'solver_sweep':m5_sweeps,'robust_sweep':m6_sweeps}
        for kind,path in families.items():
            source=read(path.relative_to(ROOT)); fingerprint=digest(path)
            version=source['schema_version']; prefix='/api/m'+version.split('.')[0] if version!='2.0' else '/api'
            endpoint=prefix+'/import' if version!='2.0' else '/api/artifacts/import'
            imported=client.post(endpoint,json=source)
            assert imported.status_code==200,(path,imported.json)
            identifier=imported.json['id']
            detail=prefix+('/comparisons/' if kind=='comparison' else '/sweeps/')+identifier
            opened=client.get(detail); assert opened.status_code==200,(path,opened.json)
            loaders[kind].validate_artifact(opened.json)
            csv_text=loaders[kind].table_csv(opened.json); assert isinstance(csv_text,str) and csv_text
            assert digest(path)==fingerprint
            report['offline_artifacts'].append({'source':str(path.relative_to(ROOT)),'kind':kind,'sha256':fingerprint,'csv_bytes':len(csv_text.encode())})


def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out=ROOT/'evidence/m7'/('delivery_audit_'+stamp+'_'+uuid.uuid4().hex[:8]);out.mkdir(parents=True)
    report={'status':'incomplete','errors':[],'recorded_utc':datetime.now(timezone.utc).isoformat(),'requirements':{}}
    try:
        manifest=read('evidence/m7/preservation_manifest.json')
        changed=[p for p,h in manifest['files'].items() if not (ROOT/p).is_file() or digest(ROOT/p)!=h]
        live_logs=read('evidence/m7/live_log_preservation.json')
        appended=[]
        for item in live_logs:
            path=item['path'];length=item['original_prefix_bytes']
            if path in changed and path in ('evidence/m5/server_final_ui_stderr.txt','evidence/m6/server_final_stderr.txt'):
                data=(ROOT/path).read_bytes()
                assert length and hashlib.sha256(data[:length]).hexdigest()==manifest['files'][path]
                appended.append({'path':path,'original_prefix_bytes':length,'appended_bytes':len(data)-length,
                                 'original_sha256':manifest['files'][path],'current_sha256':digest(ROOT/path)})
        unexplained=[p for p in changed if p not in {r['path'] for r in appended}]
        report['preservation']={'checked':len(manifest['files']),'exact_hashes_unchanged':len(manifest['files'])-len(changed),
                                'append_only_live_logs':appended,'unexplained_changes':unexplained,
                                'interpretation':'All original scientific bytes retained. Active preserved servers appended logs; their original prefixes match the initial SHA256 exactly.'}
        assert not unexplained,unexplained
        log=(ROOT/'evidence/m7/test_results_final_208.txt').read_text(encoding='utf-8-sig')
        match=re.search(r'Ran (\d+) tests in ([\d.]+)s',log)
        assert match and '\nOK' in log and not re.search(r'\nFAILED|\nERROR:',log)
        report['tests']={'count':int(match[1]),'seconds':float(match[2]),'log':'evidence/m7/test_results_final_208.txt',
                         'final_metadata_focus':'evidence/m7/library_final_focused.txt','final_import_focus':'evidence/m7/integration_final.txt'}
        review_paths=sorted((ROOT/'evidence/m7').glob('independent_review_*/review.json'))
        math=read(review_paths[-1].relative_to(ROOT));assert math['status']=='passed'
        assert math['source_hashes']['uwb/m7.py']==digest(ROOT/'uwb/m7.py')
        report['independent_math_review']=str(review_paths[-1].relative_to(ROOT))
        acceptance=read('evidence/m7/acceptance_20261015_190356_30ad31d9/acceptance_summary.json')
        assert acceptance['status']=='passed' and acceptance['run_count']==75 and acceptance['attempt_count']==94
        assert all(acceptance['survey_pairing'][k] for k in ('identical_observations','identical_world_physical_starts'))
        with forbidden_work():
            for record in acceptance['runs']:m7.load_run(ROOT/record['path'])
        report['numerical_acceptance']={'source':'evidence/m7/acceptance_20261015_190356_30ad31d9/acceptance_summary.json','runs':75,'attempts':94,
            'status_counts':{s:sum(r['statuses'].get(s,0) for r in acceptance['runs']) for s in ('success','not_converged','failed')},
            'coverage':{k:{x:v[x] for x in ('requested_trials','intervals_available','covered','fraction','binomial_wilson_95')} for k,v in acceptance['coverage'].items()}}
        package_paths=sorted((ROOT/'evidence/m7').glob('investigations_*/investigations.json'))
        package=read(package_paths[-1].relative_to(ROOT));assert package['status']=='passed'
        assert {'timing','geometry','height','initialization','weak_geometry','multipath','partial_survey'}=={s['topic'] for s in package['sources']}
        report['investigations']={'source':str(package_paths[-1].relative_to(ROOT)),'attempts':package['total_attempts']}
        offline_audit(report)
        visual=read('evidence/m7/visual/ui_validation.json');assert visual['status']=='passed'
        for capture in visual['inspected_images']:assert (ROOT/'evidence/m7/visual'/capture).is_file()
        report['visual']='evidence/m7/visual/ui_validation.json'
        integration=read('evidence/m7/integration_review.json');assert integration['status']=='passed_after_repairs'
        report['integration_review']='evidence/m7/integration_review.json'
        for path in ('docs/archive/M7.md','docs/archive/M7_ACCEPTANCE.md','docs/science/SURVEY_UNCERTAINTY.md','README.md'):
            assert (ROOT/path).is_file() and (ROOT/path).stat().st_size>500
        roadmap=(ROOT/'docs/archive/ROADMAP.md').read_text(encoding='utf-8')
        assert len(re.findall(r'^- \[x\] \*\*M7\.[1-5]',roadmap,re.M))==5
        assert 'Status: PASSED' in (ROOT/'docs/archive/M7_ACCEPTANCE.md').read_text(encoding='utf-8')
        assert 'app.py --port 5057' in (ROOT/'README.md').read_text(encoding='utf-8')
        report['delivery_documents']=['docs/archive/M7.md','docs/archive/M7_ACCEPTANCE.md','docs/science/SURVEY_UNCERTAINTY.md','README.md','docs/archive/ROADMAP.md']
        for item,scope in {
            'M7.1':'Partial masks, fixed elimination, survey covariance, world frames and unsupported constraints',
            'M7.2':'Conditional uncertainty with independently reconstructed Jacobian/covariance, information sources and finite-sample trial denominators',
            'M7.3':'Seven reproducible investigation topics, all94 new attempts plus168 retained study attempts and paired source checks',
            'M7.4':'Unified Library, bounded DOM, authoritative sources, preview/Open, A/B, state preservation, keyboard and responsive inspection',
            'M7.5':'Metadata cache/index, bounded queries, incremental/corruption behavior, cold/warm/startup/browser measurements'
        }.items():report['requirements'][item]={'status':'passed','scope':scope}
        report['limitations']=visual['limitations']+[
            'Survey support is physical h with independent beacon heights; unsupported shared/coupled constraints reject explicitly.',
            'Local covariance is conditional, not global uniqueness or generally calibrated robust uncertainty.',
            'Cold index building remains material; warm targets do not certify first-ever bundle-copy speed.',
            'Single-run optimizer internal state is not checkpointed; sweep recovery requires readable main JSON; no permanent-write durability guarantee.',
            'Historical provisional M7 development evidence remains unchanged; current strict contract is represented by the cited final bundle.'
        ]
        report['status']='passed'
    except Exception as exc:
        report['status']='failed';report['errors'].append(f'{type(exc).__name__}: {exc}')
    (out/'audit.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    if report['status']=='passed':
        (ROOT/'evidence/m7/final_audit.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'status':report['status'],'output':str(out),'errors':report['errors']}))
    return report['status']=='passed'


if __name__=='__main__':raise SystemExit(0 if main() else 1)
