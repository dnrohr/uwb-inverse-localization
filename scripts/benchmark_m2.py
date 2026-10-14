"""Local solver timings with every measured attempt retained."""
from pathlib import Path
import json
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uwb.experiments import generate_experiment, save_json
from uwb.estimation import solve_experiment

output = Path(__file__).resolve().parents[1] / 'evidence' / 'm2'
records = []
for samples in (32, 100):
    for repeat in range(2):
        experiment = generate_experiment({'samples': samples, 'noise_std_m': .05})
        start = time.perf_counter()
        run = solve_experiment(experiment, {'starts': 3, 'seed': 19})
        wall = time.perf_counter() - start
        path = output / 'benchmark_runs' / f'{samples}_repeat{repeat}.json'
        save_json(path, run)
        records.append({'samples': samples, 'starts': 3, 'repeat': repeat,
                        'wrapper_wall_s': wall, 'status': run['status'],
                        'nfev': [s['solver']['nfev'] for s in run['starts']],
                        'artifact': str(path.relative_to(output))})
        print(samples, repeat, f'{wall:.3f}s', flush=True)
(output / 'performance_benchmark.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
