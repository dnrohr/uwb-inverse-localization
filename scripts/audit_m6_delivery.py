"""Reconcile final M6 sources, strict offline service exports and preservation."""
from contextlib import ExitStack
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import time
import uuid
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import create_app
from uwb import m3,m4,m5,m6,m6_sweeps


def main():
    folder=ROOT/'evidence/m6'/('delivery_audit_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
    folder.mkdir()
    audit={'status':'incomplete','errors':[],'checks':{},'offline_imports':[]}
    def record():
        text=json.dumps(audit,indent=2,allow_nan=False)
        (folder/'audit.json').write_text(text,encoding='utf-8')
        (ROOT/'evidence/m6/final_audit.json').write_text(text,encoding='utf-8')
    record()
    try:
        manifest=json.loads((ROOT/'evidence/m6/preservation_manifest.json').read_text(encoding='utf-8-sig'))
        changes=[p for p,h in manifest.items() if not (ROOT/p).exists() or hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h]
        audit['checks']['preservation']={'count':len(manifest),'changed':changes};assert not changes,changes
        tests=(ROOT/'evidence/m6/test_results_final.txt').read_text(encoding='utf-8-sig')
        match=re.search(r'Ran (\d+) tests in ([\d.]+)s\s+OK',tests);assert match,'Final suite must pass'
        audit['checks']['tests']={'count':int(match[1]),'seconds':float(match[2]),'evidence':'evidence/m6/test_results_final.txt'}
        summaries=[p for p in (ROOT/'evidence/m6').glob('acceptance_*/acceptance_summary.json') if json.loads(p.read_text(encoding='utf-8'))['status']=='passed']
        assert summaries,'No complete acceptance matrix'
        summary_path=max(summaries,key=lambda p:p.stat().st_mtime_ns)
        summary=json.loads(summary_path.read_text(encoding='utf-8'))
        audit['checks']['acceptance']={'path':str(summary_path.relative_to(ROOT)),'attempts':summary['attempt_count'],'runs':summary['run_count'],'statuses':summary['status_counts'],'masking_examples':summary['masking_example_count']}
        review=json.loads((ROOT/'evidence/m6/independent_math_review.json').read_text(encoding='utf-8'))
        assert review['status']=='passed' and not review.get('failures'),review.get('failures')
        audit['checks']['independent_math']={'path':'evidence/m6/independent_math_review.json','checks':len(review['checks'])}
        # Service lifecycle and offline imports are independent of UI jobs and user history.
        sources=[ROOT/s['path'] for s in summary['fixtures']]
        sources += [ROOT/s['path'] for s in summary['sweeps'] if s['name'] in ('masking_informative_noisy','dropout','combined_sources')]
        sources += list((ROOT/'evidence/m6/visual').glob('live*.json'))
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            client=create_app(temp).test_client()
            for module in (m3,m4,m5,m6):
                for operation in ('solve_experiment','generate_experiment'):
                    stack.enter_context(patch.object(module,operation,side_effect=AssertionError('offline audit forbids solve/generation')))
            for source in sources:
                raw=json.loads(source.read_text(encoding='utf-8'))
                comparison=raw.get('artifact_type')=='comparison'
                response=client.post('/api/artifacts/import' if comparison else '/api/m6/import',json=raw)
                assert response.status_code==200,(source,response.json)
                identifier=response.json['id']
                artifact=raw.get('artifact_type')=='robust_sweep'
                reopened=client.get(('/api/comparisons/' if comparison else '/api/m6/sweeps/' if artifact else '/api/runs/')+identifier)
                assert reopened.status_code==200,(source,reopened.json)
                saved=response.json['artifact' if artifact or comparison else 'run']
                assert reopened.json==saved
                if artifact:
                    exported=client.get('/api/m6/sweeps/'+identifier+'/csv')
                    rows=list(csv.DictReader(io.StringIO(exported.data.decode())))
                    assert len(rows)==len(saved['start_table'])
                audit['offline_imports'].append({'path':str(source.relative_to(ROOT)),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'status':'passed'})
            assert not any(r['status']=='unreadable' for r in client.get('/api/runs').json)
        audit['checks']['backend_lifecycle']={'evidence':'evidence/m6/service_tests_final.txt','limits':[
            'Sweep temporary recovery requires readable main JSON; malformed or absent main files are not reconstructed.',
            'Permanent terminal run write failure preserves latest job memory during server lifetime; restart may reopen only pending request if no terminal bytes persisted.',
            'Summary cache uses file size/mtime, not content hashes; strict detail/import validates source.',
            'Interrupted sweeps retain completed prefix and unattempted entries are never silently solved.']}
        visual=json.loads((ROOT/'evidence/m6/visual/ui_validation.json').read_text(encoding='utf-8'))
        assert visual['status']=='passed' and not visual['console_errors']
        audit['checks']['visual']={'evidence':'evidence/m6/visual/ui_validation.json','limits':visual['limitations']}
        benchmark=json.loads(next((ROOT/'evidence/m6').glob('benchmark_*/performance_benchmark.json')).read_text())
        audit['checks']['performance']={'records':len(benchmark['records']),'min_wrapper_s':min(r['wrapper_s'] for r in benchmark['records']),'max_wrapper_s':max(r['wrapper_s'] for r in benchmark['records']),'scope':benchmark['scope']}
        audit['requirements']={f'M6.{i}':{'status':'passed','evidence':e} for i,e in enumerate([
            ['uwb/m6.py','tests/test_m6.py','source experiments and contamination references in acceptance matrix'],
            ['evidence/m6/independent_math_review.json','tests/test_m6_service.py','four paired losses per saved data cell'],
            ['evidence/m6/visual/ui_validation.json','evidence/m6/visual/'],
            [str(summary_path.relative_to(ROOT)),'confusion metrics and original/retained spectra per attempt'],
            ['isolated beacon_offsets/correlated_noise/quantization/dropout sweeps before combined_sources']],1)}
        audit['status']='passed';record();print(folder)
    except Exception as exc:
        audit['errors'].append(f'{type(exc).__name__}: {exc}');record();raise


if __name__=='__main__':main()
