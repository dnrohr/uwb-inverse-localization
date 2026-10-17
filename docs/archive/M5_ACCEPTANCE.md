# M5 acceptance record

**Status: PASSED for the defined M5 scope.** Numerical, backend persistence, desktop UI, and recorded visual checks passed. The evidence and limits below define the scope of that result; mobile layout and untested infrastructure failure cases are documented limitations.

## Acceptance checks

| Check | Evidence | Status |
| --- | --- | --- |
| Numerical model and analytic derivatives | `evidence/m5/independent_math_review.json`: seven independent checks passed, including direct-distance Jacobians, all supported `h` models, `h`/`q` scaling, algebraic initializer physics, and LM domain handling. | Passed for reviewed numerical scope |
| Revision 2 LM transforms | Independent review reconstructs the revision 1 boundary-touch defect and confirms the current revision 2 rejects bound starts, underflow, boundary roundoff, and overflow. Two historical revision 1 domain-invalid results remain preserved in the earlier review artifact. | Reviewed; historical failures retained |
| Acceptance sweeps and fixtures | `evidence/m5/acceptance_20261014_124422_c74e2389/acceptance_summary.json`: nine sweeps, 160 runs, 320 starts, plus eight fixtures with 16 starts. All 336 attempts remain represented. | Passed |
| Preservation | Current acceptance bundle reports 649 checked files and no changes. | Passed for the recorded check |
| Automated tests | `evidence/m5/test_results_final.txt` records the final-source suite with 127 tests passed in 11.541 seconds. The earlier delivery run remains in `evidence/m5/test_results_delivery.txt` (127 passed in 10.119 seconds). | Passed |
| Strict persistence and offline reuse | [`backend_final_audit.json`](../../evidence/m5/backend_final_audit.json): six service tests passed, 19 offline imports/reopens under no-solve/no-generate patches, all 649 preservation checks unchanged. The audit records checkpoint and permanent-write-failure limitations below. | Passed with documented limitations |
| UI and visual evidence | [`ui_validation.json`](../../evidence/m5/visual/ui_validation.json) records the desktop workflow, current shared-data LM/q/algebraic run `428d10d41e3d45cea46d9174d6440ab1`, TRF/h/algebraic run `4f1ab837c0ad4009ba707152b6d190c9`, comparison reopened after reload, zero console errors, and the limited 390×844 control/history check. `final_m5_controls.png`, `final_m5_attempts.png`, `final_m5_scene.png`, comparison/residual/geometry exports, and legacy M3/M4 screenshots were reviewed. | Passed for desktop workflow and stated narrow control check |
| Performance | `benchmark_attempt2.txt` points to 48 paired local timing records. `history_performance.json` records two warm listing measurements across 564 records. | Recorded; no general performance advantage claimed |
| Alternative backend decision | `second_implementation_decision.json` defers Ceres and Geomstats for M5, with explicit revisit conditions and no cross-backend performance claim. | Decision recorded; M5 remains on SciPy |

## Numerical acceptance results

The sweep bundle contains 336 attempts in total: 320 sweep starts and 16 fixture starts. Within the 320 sweep starts, 268 converged, one was nonconverged, and 51 failed. Forty of those failed starts were invalid algebraic initializer proposals. The eight extra fixture records include four forced nonconvergence attempts, two per solver. These categories are kept distinct; invalid proposals have no optimizer estimate and are not silently replaced by another initializer.

| Suite | Runs | Starts | Notes |
| --- | ---: | ---: | --- |
| Independent initialization basin | 24 | 48 | No failed or nonconverged starts in the saved cells |
| Truth-near initialization basin | 24 | 48 | No failed or nonconverged starts; truth-assisted diagnostic only |
| Range noise | 16 | 32 | No failed or nonconverged starts in the saved cells |
| Near-zero height | 16 | 32 | Four failed starts retained |
| Weak geometry | 16 | 32 | Five failed and one nonconverged start retained |
| Valid algebraic initializer | 16 | 32 | No failed starts in the saved cells |
| Degenerate algebraic initializer | 16 | 32 | Sixteen invalid proposals retained, among 18 failures |
| Noisy algebraic initializer | 16 | 32 | Sixteen invalid proposals retained |
| Noisy algebraic initializer, relaxed tolerance | 16 | 32 | Eight invalid proposals retained |

In exact-data independent-basin fixtures, median position errors across the four solver/coordinate variants are on the order of `1e-15 m`; this measures those exact fixtures only. In weak-geometry cells, median position errors reach approximately `5.9–7.1 m`, even when median range error is about `1 mm`. These results show why range fit and geometry accuracy are reported separately. They do not imply general performance across unseen geometries or data.

The independent review passed these seven checks: distance-Jacobian scaling; supported `h` model Jacobians; algebraic physics support; LM domains and failures; truth independence and pairing; native projection and failed seeds; and retention of acceptance artifacts. It found that the `q` range derivative can remain finite at zero although the inverse `q`-to-`h` map is singular. It also confirms that coordinate-dependent rank and conditioning are local diagnostics and do not establish global uniqueness.

The positive shared-height branch also changes native model projection when canonical truth is on the negative branch. The saved negative-height fixture has truth at `z = -3 m`; both `h` and `q` project to the positive branch, producing `3.000002 m` map displacement, while the M4 projection is `0 m`. The reflected positive geometry still matches ranges to `1.8e-15 m`. The projection distance is a model-convention diagnostic, not an optimizer lower bound. See `evidence/m5/extra_runs/negative_shared_height_branch_2a247bbb.json` and the independent review evidence.

The final backend audit is [`backend_final_audit.json`](../../evidence/m5/backend_final_audit.json); the overall evidence pointer is [`final_audit.json`](../../evidence/m5/final_audit.json). The audit confirms strict offline import/reopen without solving or regenerating source experiments. Recovery currently requires a readable main artifact, and dedicated injection tests for sweep-checkpoint write failure and permanent double-write failure were not run. Sweep summary listing reads its envelope without full validation; detail, import and export validate the complete artifact. The summary cache keys on file modification time and size, not a content hash.

The current build also retained edge cases in live runs: a near-zero case requested 32 starts and retained all 32 as success or failure; the degenerate algebraic case requested 32 starts, retained 16 valid and 16 invalid initializer results, and converged 14. Invalid proposals were not replaced with another initializer.

## Performance record and limits

The local solver benchmark uses paired noisy observations and physical starts, four solver/coordinate variants, sizes of 4 or 8 beacons and 12 or 24 samples, and three repeats per case (48 records total). Wrapper timing includes fitting, diagnostic evaluation, and validation, while excluding JSON disk saving. Every recorded start succeeded. Across the 12 records per variant, median wrapper times were TRF/h `0.06536 s`, TRF/q `0.06297 s`, LM/h `0.04844 s`, and LM/q `0.05043 s`. The data are retained in `evidence/m5/benchmark_20261014_123003_fc71f42c/performance_benchmark.json`; the raw benchmark pointer is `evidence/m5/benchmark_attempt2.txt`. These measurements describe this small local workload and do not establish a general TRF/LM speed ranking.

The separate history benchmark reports 564 readable records in 0.082 s and 0.045 s across two warm requests. Summary listing uses a file modification-time and size cache; detail and import still validate full content. No broader storage or throughput claim is inferred from these two timings.

## Scope and limitations

- The desktop workflow passed visual checks for controls, attempt inspection, residual and geometry charts, exports, comparison, scene/playback, JSON import after reload, and legacy M3/M4 reopening. Single browser-local timings were 250.5 ms for the scene, 230.1 ms for comparison, and 32.4–107.7 ms for charts/sweep redraws; these are individual samples, not throughput guarantees.
- At 390×844, M5 controls fit and long run/sweep histories scroll within the M5 panel. The complete page still has horizontal overflow (`documentWidth` 832 px for a 390 px viewport); this check does not certify a mobile-wide layout.
- Checkpoint recovery requires a readable existing main artifact. Dedicated fault injection for sweep checkpoint-write failure and permanent double-write failure remains untested; the audit records that the latest snapshot stays in job memory while persistence retries. These are explicit evidence limits, not hidden acceptance assumptions.
- M5 acceptance does not authorize or imply an M6 implementation.
