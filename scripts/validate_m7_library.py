"""Reproducible isolated Library timings; never changes scientific history.

Run: .venv/Scripts/python scripts/validate_m7_library.py
The 10k case contains small metadata fixtures, not 10k full numerical runs.
Cold current-history queries do read the real numerical JSON once for metadata;
warm queries are instrumented to fail if extraction tries to decode a source.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from uwb.library import LibraryIndex


def fixture(identifier, label='Informative metadata fixture'):
    return {'schema_version': '6.0', 'id': identifier, 'status': 'success', 'label': label,
            'experiment': {'config': {'scenario': 'informative', 'seed': 7},
                           'estimator_input': {'ranges_m': [[1, 2, 3]]}},
            'options': {'mode': 'joint', 'loss': 'cauchy'},
            'starts': [{'index': 0, 'status': 'success', 'initial': {'beacons': [[1, 2, 3]]}}]}


def elapsed(call):
    started = time.perf_counter()
    value = call()
    return value, round((time.perf_counter() - started) * 1000, 3)


def measure(directory, cache, name):
    index, constructor_ms = elapsed(lambda: LibraryIndex(directory, cache_path=cache))
    cold, cold_ms = elapsed(lambda: index.query(view='all'))
    timings, payloads = [], []
    with patch('uwb.library._summary', side_effect=AssertionError('Warm source JSON extraction forbidden')):
        for _ in range(7):
            response, ms = elapsed(lambda: index.query(view='all'))
            timings.append(ms)
            payloads.append(len(json.dumps(response, separators=(',', ':'), allow_nan=False).encode()))
            assert len(response['items']) <= 25
            assert response['index']['changed'] == 0
    bounded = index.query(view='all', page_size=100000)
    assert len(bounded['items']) <= 50
    grouped = index.query()
    result = {'name': name, 'constructor_ms': constructor_ms, 'cold_query_ms': cold_ms,
              'cold_scan_ms': cold['index']['scan_ms'], 'source_files': cold['index']['discovered'],
              'all_records': cold['total'], 'grouped_records': grouped['total'],
              'warm_ms': timings, 'warm_median_ms': statistics.median(timings),
              'warm_max_ms': max(timings), 'payload_bytes': payloads,
              'first_page_rows': len(cold['items']), 'max_page_rows': len(bounded['items']),
              'warm_under_500_ms': all(t < 500 for t in timings),
              'warm_source_decode_guard': 'passed', 'sqlite_bytes': cache.stat().st_size}
    print(json.dumps(result), flush=True)
    return index, result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', type=Path, default=ROOT / 'runs')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    token = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output = args.output_dir or ROOT / 'evidence' / 'm7' / ('library_' + token)
    output.mkdir(parents=True, exist_ok=False)
    report = {'recorded_at': datetime.now(timezone.utc).isoformat(), 'machine': sys.platform,
              'python': sys.version, 'scope': 'Backend metadata only; no browser/DOM/render or startup-bundle certification.',
              'cases': [], 'fixture_10000': 'Small schema-shaped metadata records, not numerically valid runs.',
              'freshness_limit': 'mtime_ns/ctime_ns/size inventory per request; timestamp-preserving same-size edits require rebuild.'}
    with tempfile.TemporaryDirectory(prefix='uwb_m7_library_') as temporary:
        base = Path(temporary)
        zero = base / 'zero'; zero.mkdir()
        _, result = measure(zero, base / 'zero.sqlite3', 'zero')
        report['cases'].append(result)
        _, result = measure(args.run_dir.resolve(), base / 'current.sqlite3', 'current_retained_history')
        report['cases'].append(result)
        many = base / '10000'; many.mkdir()
        started = time.perf_counter()
        for i in range(10000):
            identifier = f'{i:032x}'
            (many / (identifier + '.json')).write_text(json.dumps(fixture(identifier)), encoding='utf-8')
        report['fixture_write_ms'] = round((time.perf_counter() - started) * 1000, 3)
        index, result = measure(many, base / '10000.sqlite3', '10000_metadata_records')
        report['cases'].append(result)
        changed = many / ('0' * 32 + '.json')
        changed.write_text(json.dumps(fixture('0' * 32, 'Changed externally')), encoding='utf-8')
        response, ms = elapsed(lambda: index.query(q='Changed externally', view='all'))
        assert response['filtered'] == 1 and response['index']['changed'] == 1
        report['incremental_one_change'] = {'ms': ms, 'changed': 1, 'source_files': 10000}
        # Source corruption remains discoverable without changing its bytes.
        changed.write_text('{BROKEN SOURCE JSON', encoding='utf-8')
        response, ms = elapsed(lambda: index.query(status='unreadable', view='all'))
        assert response['filtered'] == 1
        report['source_corruption'] = {'ms': ms, 'unreadable': 1, 'source_bytes_preserved': changed.read_text() == '{BROKEN SOURCE JSON'}
        # No connection remains open between requests, so overwrite only this isolated cache.
        index.cache_path.write_bytes(b'corrupt metadata cache')
        response, ms = elapsed(lambda: index.query(view='all'))
        assert response['total'] == 10000 and 'cache_recovery' in response['index']
        report['cache_corruption_rebuild'] = {'ms': ms, 'records': response['total'],
                                             'source_corrupt_still_inspectable': index.query(status='unreadable', view='all')['filtered'] == 1,
                                             'recovery': response['index']['cache_recovery']}
    report['all_warm_requests_under_500_ms'] = all(c['warm_under_500_ms'] for c in report['cases'])
    (output / 'measurements.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Evidence: ' + str(output / 'measurements.json'), flush=True)


if __name__ == '__main__':
    main()
