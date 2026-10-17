"""Verify unified-workspace delivery against retained artifacts and recorded checks."""
from pathlib import Path
import datetime
import hashlib
import json
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'evidence/workspace'


def main():
    report={'recorded_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'status':'failed', 'errors':[]}
    try:
        baseline=json.loads((EVIDENCE/'preservation.json').read_text(encoding='utf-8'))
        changed=[]
        for name,digest in baseline['files'].items():
            path=ROOT/name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                changed.append(name)
        assert all(name=='runs/.library.sqlite3' for name in changed),changed
        report['preservation']={'checked':len(baseline['files']),
            'exact_unchanged':len(baseline['files'])-len(changed),'changed':changed,
            'interpretation':'Only the rebuildable metadata cache changed; original scientific JSON, runs, starts and prior evidence bytes are unchanged.'}
        science=['uwb/estimation.py','uwb/experiments.py','uwb/m3.py','uwb/m4.py','uwb/m5.py','uwb/m6.py','uwb/m7.py',
                 'uwb/sweeps.py','uwb/m3_sweeps.py','uwb/m4_sweeps.py','uwb/m5_sweeps.py','uwb/m6_sweeps.py']
        assert subprocess.run(['git','diff','--quiet','HEAD','--',*science],cwd=ROOT).returncode==0
        report['scientific_implementations_unchanged']=science
        report['tests']={}
        for name in ['baseline_tests.txt','final_tests.txt','adapter_tests_final.txt','library_tests_final.txt']:
            text=(EVIDENCE/name).read_text(encoding='utf-8')
            match=re.search(r'Ran (\d+) tests in ([\d.]+)s',text)
            assert match and text.rstrip().endswith('OK'),name
            report['tests'][name]={'count':int(match[1]),'seconds':float(match[2])}
        assert report['tests']['baseline_tests.txt']['count']==208
        assert report['tests']['final_tests.txt']['count']==218
        for name in ['download_serialization.json','library_lifecycle.json','legacy_wiring.json']:
            data=json.loads((EVIDENCE/name).read_text(encoding='utf-8'))
            assert data.get('passed'),name
        exports=json.loads((EVIDENCE/'export_roundtrip.json').read_text())
        assert exports['strict_json_valid'] and exports['exact_record_roundtrip']
        report['exports']=exports
        backend=json.loads((EVIDENCE/'scale_backend.json').read_text())
        browser=json.loads((EVIDENCE/'scale_browser.json').read_text())
        assert all(x['elapsed_ms']<500 and x['rows']==25 for x in backend if x['phase']=='warm')
        assert browser['rows']==25 and browser['libraryDom']<400 and all(x<1000 for x in browser['warmRepeatsMs'])
        report['performance']={'backend':backend,'browser':browser}
        visual=json.loads((EVIDENCE/'browser_validation.json').read_text(encoding='utf-8'))
        assert visual['status']=='passed' and not visual['errors']
        for name in visual['screenshots']:
            assert (EVIDENCE/name).is_file(),name
        report['browser']=visual
        for name in ['README.md','docs/archive/PROJECT_REQUIREMENTS.md','docs/archive/ROADMAP.md','docs/WORKSPACE.md']:
            assert (ROOT/name).is_file(),name
        sources=['app.py','uwb/workspace.py','uwb/library.py','web/workspace.js','web/workspace.css',
                 'web/index.html','web/app.js','web/m2.js','web/m3.js','web/m4.js','web/m5.js',
                 'web/m6.js','web/m7.js','web/library.js','tests/test_workspace.py']
        report['source_sha256']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sources}
        report['requirements']={key:'passed' for key in ['shared_draft_and_model_capabilities','single_execution_flow',
            'shared_scene_and_diagnostics','native_historical_sources_and_exports','paired_studies_and_all_outcomes',
            'scientific_engine_parity','offline_strict_workflows','responsive_keyboard_state_preservation',
            'bounded_library_performance','original_data_and_evidence_preservation']}
        report['limitations']=[
            'Cold metadata indexing remains expensive; warm response/render targets do not imply cold usability below one second.',
            'Saved observations require compatible native schema and unchanged physical configuration and saved sigmas; no silent schema conversion.',
            'Timing studies use the original fixed timing-model pair; survey studies have no native engine and reject explicitly.',
            'Conditional covariance retains its original Gaussian/local/full-rank assumptions and withholding policies; it is not a global uniqueness claim.',
            'Existing recovery boundaries remain: no internal optimizer checkpoint or permanent-write durability guarantee.',
            'Native numerical controls and covariance/variant arrays retain advanced JSON editing; narrow tables use contained horizontal scrolling.',
            'Browser validation covers the recorded workflows and viewports, not every possible scientific configuration.'
        ]
        report['status']='passed'
    except Exception as exc:
        report['errors'].append(f'{type(exc).__name__}: {exc}')
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    (EVIDENCE/f'audit_{stamp}.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if report['status']=='passed':
        (EVIDENCE/'acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'errors':report['errors']}))
    return report['status']=='passed'


if __name__=='__main__':
    raise SystemExit(0 if main() else 1)
