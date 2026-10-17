# M6 acceptance record

M6 delivers controlled contamination and robust fitting in the local application. Numerical, independent mathematical, service, persistence and desktop visual checks are recorded under `evidence/m6/`. The requirement-level reconciliation is [final_audit.json](../../evidence/m6/final_audit.json); the precise scope and recovery limits below apply.

## Launch and reproduce

```powershell
.\.venv\Scripts\python.exe app.py --port 5056
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\validate_m6.py
.\.venv\Scripts\python.exe scripts\benchmark_m6.py
.\.venv\Scripts\python.exe scripts\review_m6.py evidence/m6/acceptance_20261014_172009_b09e8830 evidence/m6/benchmark_20261014_172044_0a5af126
.\.venv\Scripts\python.exe scripts\audit_m6_delivery.py
```

Open [the M6 viewer](http://127.0.0.1:5056). Earlier user servers were preserved; port 5054 was owned by an existing Python application and was never stopped. M6 validation used its own verified process on 5056. Startup copies the accepted M6 fixtures/sweeps once into local history, without solving. M0–M5 formats and evidence remain available. No push or external publication was performed.

## Recorded checks

| Requirement | Evidence | Result |
| --- | --- | --- |
| M6.1 labeled positive NLOS, isolated outliers, bursts; configurable onset, magnitude, duration and beacons | `uwb/m6.py`, `tests/test_m6.py`, acceptance source experiments and separate contamination references | Deterministic replay and additive component accounting checked; fitting excludes labels and clean ranges |
| M6.2 Gaussian, robust losses and explicit rejection; unchanged priors and bounds | [independent review](../../evidence/m6/independent_math_review.json), numerical and service tests | Seven independent review checks passed; all losses use the disclosed original-range objective and solver domains |
| M6.3 decisions, residuals, affected segments, coverage and information | [UI record](../../evidence/m6/visual/ui_validation.json), scene/residual/coverage PNGs | Desktop workflow and saved artifacts visually inspected; colors, marker sizes and thresholds disclosed |
| M6.4 rejection metrics with geometric error, failures, variability and masking | [acceptance matrix](../../evidence/m6/acceptance_20261014_172009_b09e8830/acceptance_summary.json), independent review | Every attempt retained; 63 small-original-residual/distorted-geometry examples, including 46 with both trajectory and map error |
| M6.5 isolated offsets, correlation, quantization and dropout before combinations | `beacon_offsets`, `correlated_noise`, `quantization`, `dropout`, then `combined_sources` sweeps in acceptance matrix | Individual sources and combined limitations recorded |
| Preservation | `preservation_manifest.json`, final audit | 1,195 original evidence/history file hashes checked |
| Tests | [final suite](../../evidence/m6/test_results_final.txt), [service suite](../../evidence/m6/service_tests_final.txt) | 158 tests passed in 27.131 s; eight targeted service checks also passed |
| Offline persistence, imports and exports | Final audit, service tests, live JSON/CSV/PNG exports | Reopen/import under forbidden solve/generation patches; corruption, pairing, temporary recovery and storage failures checked |

The 127-test starting baseline passed in 9.391 s. Earlier M6 integration runs also passed (152 tests in 27.998 s and 158 tests in 35.767 s); the final-source repeat passed 158 in 27.131 s. Tests and evidence were run locally while other acceptance work could be active; timings are descriptive.

## Numerical outcomes and interpretation

The completed matrix contains **14 sweeps and 24 fixtures: 248 runs and 496 final attempts**. Of those attempts, **460 converged, 19 were nonconverged and 17 failed**. The explicit hard-rejection runs separately retain 120 nested Gaussian pilot stages: 114 converged and six were nonconverged. These pilot stages are not added to the 496 final-attempt denominator. Every pilot status, residual and frozen mask remains in its source run.

Two paired measurement seeds, two starts and four loss variants are used in each sweep cell, with 12 display samples and a 300-evaluation budget per optimization stage. The matrix includes exact/noisy informative, weak and straight-line joint geometry, surveyed-map fits, bursts, isolated error sources, combined contamination and asynchronous/spatial/prior/failure fixtures. Soft L1 and TRF/LM `h`/`q` equivalence are covered separately by direct numerical and independent tests. These are reproducible small experiments, not population-wide guarantees.

For informative noisy joint geometry with NLOS onset probability 0.15, all-start median errors were:

| Estimator | Trajectory RMSE (m) | Map RMSE (m) |
| --- | ---: | ---: |
| Gaussian | 0.475 | 0.426 |
| Huber | 0.582 | 0.891 |
| Cauchy | 0.686 | 0.140 |
| Hard rejection | 0.825 | 0.329 |

These noisy joint aggregates use each run's saved proper rigid aligned error frame. Cauchy improved the map while worsening trajectory error in this cell. On the surveyed noisy cell, trajectory medians were 0.493, 0.431, 0.685 and 0.607 m respectively. Surveyed map error is zero by declared knowledge. Robustness is therefore evaluated as gains and losses in several quantities; no general improvement is claimed.

The independent audit found 63 finite estimates with original all-range RMSE below 0.05 m but raw canonical trajectory or map RMSE above 0.25 m. Forty-six had both trajectory and map errors above that threshold. Eight clean straight-line runs retained sampled alternative exact-range geometries from their two starts. The weak noisy contaminated cases had median trajectory errors around six metres. These are demonstrations of masking and sampled alternatives, not proof that all solution branches were found. Rank is first-order sensitivity; full local rank does not prove uniqueness, and rank loss alone does not prove a continuous ambiguity.

The independent review reopened all 496 attempts under the final source without refitting, mutation or derived-table migration. Direct normalized range disagreement was zero; the maximum independently reconstructed information-spectrum disagreement was approximately `5.68e-13`. Separate checks reconstructed loss values/derivatives, unchanged motion/height priors, label isolation, all-data versus weighted information, native bounds, exact/noisy M5 equivalence and metric denominators. Earlier failed review attempts remain in their unique folders.

## Working application and exported evidence

The live desktop workflow generated a Cauchy experiment and a six-attempt Gaussian/Cauchy/rejection benchmark, reopened saved history after reload, inspected individual attempts without losing the six-row table, and imported a retained failed fixture. The failed fixture preserves both failed attempts, messages and unavailable metrics; its CSV has 96 source rows with attempt status. Shared comparisons use identical saved observations and physical starts, with proper rigid alignment only. Scrubbing and playback preserve the scene camera and comparison alignment. Saved imports do not queue numerical work.

The live rejection example retained 30 of 48 positive-weight ranges and reduced first-order rank from 24 to 16. Its decision precision was 0.333 and recall 1.000, with 12 false positives. That illustrates information loss and false rejection; it does not establish better geometry. The Cauchy example retained all 48 ranges with effective weight sum 36.082; nine were flagged by the disclosed continuous-weight rule. Synthetic NLOS labels remain distinct from those estimator decisions.

Exported scene, residual, coverage, benchmark and comparison PNGs were opened and visually inspected. Visual inspection found and corrected repeated legend entries, missing Plotly 7 axis-title objects and mismatched marker-size disclosure. The retained evidence includes the earlier screenshots/exports and the corrected final exports. Main rays are sampled; the complete decisions/source records remain in JSON and CSV. UI measurements and final screenshot paths are in the UI record. A recorded final 48-observation scene render took 446.1 ms, residual chart 31.5 ms and coverage chart 20.0 ms; these are browser-local single samples excluding solve/network time.

## Performance and limits

[Performance evidence](../../evidence/m6/benchmark_20261014_172044_0a5af126/performance_benchmark.json) contains 48 paired one-start runs: 12/24 display samples, 4/8 beacons, three seeded repetitions and four estimators. All 48 converged in those fixtures. Wrapper wall times ranged from **0.188 to 0.585 s**, including solving, diagnostics and validation, excluding generation and disk saving. Saved solver timings include the hard-rejection pilot where applicable. Independent review confirmed shared data/starts and every benchmark outcome. These local measurements under concurrent acceptance activity do not imply a general speed ranking. The first startup-copy check imported the 248-run acceptance bundle and listed 15 M6 sweeps (14 bundled plus one live) in 112.58 s; `startup_bundle_validation.json` records that one-time cost. History loading validates cold records before caching; initial loading can take substantially longer than subsequent warm requests. Two warm requests across 840 saved runs took 0.097/0.089 s with no unreadable records (`history_performance.json`).

M6 retains all M4/M5 supported model, gauge, bound, timing and initializer restrictions. Algebraic proposals require complete synchronized supported data and never silently fall back. Symmetric losses do not estimate physical NLOS biases. Assumed uncertainty is not automatically inflated for correlation or quantization, and the reported weighted information is conditional local sensitivity, not a calibrated covariance or independence guarantee. No Ceres/Geomstats port or M7 feature was added.

Sweeps checkpoint completed runs. A single run retains its accepted request before fitting and outcomes when the wrapper completes; a terminated optimizer's internal state is not checkpointed. Restart discloses pending work as interrupted without resuming it. Temporary sweep recovery requires readable main JSON. Terminal outcomes remain inspectable in live job memory after write failures, but permanent storage failure may leave only a pending request after restart. Full mobile layout still has inherited overflow and is not certified. Maximum-size throughput and real UWB deployment performance are not established.
