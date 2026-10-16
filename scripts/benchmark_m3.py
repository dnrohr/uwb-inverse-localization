"""Retain every M3 benchmark attempt in a unique evidence directory."""
from pathlib import Path
import json
import sys
import time
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uwb.m3_sweeps import run_sweep, save_artifact


def main():
    output = Path(__file__).resolve().parents[1]/'evidence'/'m3'/('benchmark_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for samples in (16, 32):
        for repeat in range(2):
            started = time.perf_counter()
            artifact = run_sweep({'base_experiment': {'samples': samples, 'noise_std_m': .05, 'acquisition': {'spacing_s': .05}},
                                  'options': {'starts': 2, 'max_nfev': 150, 'mode': 'known_map'},
                                  'factor': 'spacing_s', 'values': [.05], 'seeds': [7+repeat]})
            save_artifact(output/f'{samples}_repeat{repeat}.json', artifact)
            records.append({'samples': samples, 'repeat': repeat, 'wrapper_wall_s': time.perf_counter()-started,
                            'rows': artifact['start_table'], 'aggregates': artifact['aggregates']})
            print(samples, repeat, records[-1]['wrapper_wall_s'], flush=True)
    (output/'performance_benchmark.json').write_text(json.dumps(records, indent=2, allow_nan=False), encoding='utf-8')
    print(output, flush=True)


if __name__ == '__main__':
    main()
