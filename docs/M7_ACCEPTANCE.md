# M7 acceptance record

**Status: PASSED for the documented M7 scope, October 15, 2026 (America/New_York).** The [requirement audit](../evidence/m7/final_audit.json) reconciles numerical, independent review, offline lifecycle, preservation, performance and actual browser evidence. Limitations below remain part of acceptance.

## Requirement-to-evidence reconciliation

| Item | Evidence and measured result |
|---|---|
| M7.1 Partial survey | `uwb/m7.py`, [numerical contracts](M7_NUMERICS.md), numerical/service tests and independent review. Selected fixed XYZ masks are eliminated; correlated axes within a survey prior block are supported. The declared world frame has no added canonical gauge. Unsupported cross-beacon/coupled constraints, shared beacon heights, q and algebraic survey starts reject explicitly. No-survey M6 equivalence and truth/label isolation pass. |
| M7.2 Conditional uncertainty | [Independent mathematics](../evidence/m7/independent_math_review.json) reconstructs distance/interpolation derivatives, whitening, nullspaces and covariance without using implementation Jacobians as expected values. Information from original/weighted ranges, survey, motion/height priors and robust curvature stays separate. Covariance is withheld for unsupported assumptions, rank loss, active bounds, robust/rejection selection or declared mismatch. The preselected marginal interval covered31/32 independent assumed-model trials, Wilson95% interval[0.8426,0.9945];32 offset-model diagnostics have no reported interval. |
| M7.3 Reproducible investigations | [Packaged sources](../evidence/m7/investigations_20261015_190554_b32717f8/investigations.json) link262 attempts across timing, geometry, height, initialization, weak geometry, multipath and partial survey. The final M7 bundle has75 runs/94 attempts:90 success,3 nonconverged,1 failed. Survey variants share observations and world physical starts. Two explicitly oracle reflected starts retain zero range residual and0m versus6m world trajectory RMSE. Every configuration, source, start, outcome and software version remains available. |
| M7.4 Unified Library | [Live UI evidence](../evidence/m7/visual/ui_validation.json) plus static/VM and integration tests. One dedicated Library replaces all inline histories. Search/filter/sort,25-row pages/max50, recorded child traversal, all-attempt inspection, preview versus strict Open, persistent source-aware A/B, imports and exports work. A retained mixed benchmark kept all32 rows after inspecting one of11 non-successful attempts. Cameras, selected ping, layers, comparison alignment, unsaved seed and survey text survived navigation; playback stayed paused. |
| M7.5 Scale and bounded access | [Backend measurements](../evidence/m7/library_20261015T185641Z/measurements.json), [browser measurements](../evidence/m7/visual/browser_measurements_final.json) and [startup scope](../evidence/m7/startup_measurements.json). Empty/current/10k Experiment pages all measured10,627px high at1280×720, with zero inline history rows. Library page height stayed viewport-bounded and rendered25 rows (50 maximum); the10k Library contained242 DOM descendants, rather than10k hidden rows. Source/cache corruption, external incremental edits and strict Open failures are tested. |

## Tests, independent review and retained sources

The final integrated suite passed **208 tests in155.728s**, retaining the158-test baseline. See [full test output](../evidence/m7/test_results_final_208.txt). Final presentation/provenance changes also passed eight focused Library tests, three integration tests,43 service tests and the final Node lifecycle/control regression harnesses. Five independently authored integration/source-authority tests pass. No broader UI assertion is inferred solely from those VM tests.

The final independent mathematical review is retained at `evidence/m7/independent_review_20261016T021842Z/review.json` and copied to `independent_math_review.json` for convenience. It passed eight independent tests and strictly reopened75 runs/94 attempts; all32 nominal covariance matrices were independently reconstructed. The [integration review](../evidence/m7/integration_review.json) records repairs for empty-request validation, imported comparison sources, interrupted-child filters, count denominators, survey-unit imports and settings restoration. No reproduced finding remains open.

The final numerical bundle is `evidence/m7/acceptance_20261015_190356_30ad31d9/`. Older provisional M7 bundles remain untouched as historical development attempts and may lack the final strict solver-contract metadata; they are not substituted for current acceptance. No M0–M6 numerical schema was migrated or regenerated. Complete source JSON remains authoritative; new import copies retain supplied IDs/provenance while receiving safe local IDs.

## Preservation and offline boundaries

The expanded starting manifest inventories **1,665 files**, including909 saved-history files. Final verification found1,663 exact unchanged hashes. The other two files are logs of the existing5054/5056 servers: their original8,662/4,434-byte prefixes still match the starting SHA256 exactly, and only new request logs were appended. No observation, label, physical start, run, comparison, benchmark or acceptance result changed. See [live-log prefix proof](../evidence/m7/live_log_preservation.json) and the preservation section of the final audit.

The final offline audit imported/reopened16 run categories across schemas1/3/4/5/6/7 and six sweep/comparison families, with fitting, generation and optimizer functions patched to fail if called. Source hashes and observations/attempts remained unchanged. It validated complete JSON/CSV outputs. Independent source-authority tests prove that a corrupt parent does not fall back to a divergent local copy and that self-contained imported comparison sources remain selectable without original local run files.

A new local Library comparison, three imported survey demonstrations and one explicit live survey fit were retained during browser acceptance. Counts therefore legitimately grew; source-file counts and indexed embedded-source counts have different denominators. No fixture history was written into user history. Existing5054/5056 processes remained intact; application validation used5057 and isolated temporary fixture servers.

## Browser and export acceptance

Actual screenshots cover1360×900 desktop Library, normal compact1280×720 Library with10k metadata records, and390×844 Library including preview/actions and a populated A/B tray. There is no horizontal overflow on these checked Library surfaces. Search and pagination remain reachable; the narrow preview uses its own primary scroller. Enter opens metadata preview and Escape returns focus to the originating row. Back restores parent navigation/filter state. Full Experiment mobile layout is **not certified**.

The [UI record](../evidence/m7/visual/ui_validation.json) links screenshots and exact DOM measurements. A live declared-survey fit on saved observations completed successfully, persisted schema7 output, displayed the surveyed world frame and conditional covariance, and subsequently retained its ping/camera/layers/unsaved controls across Library navigation. The exported M7 JSON validated, its CSV retained all32 source observation rows, and survey-scene, comparison-scene and mixed-benchmark-chart PNGs were downloaded, opened and visually inspected. Main browser error logs were empty; an intentionally invalid metadata fixture produced a visible strict-Open error without fitting.

## Performance and limits

| Scope | Measured result |
|---|---|
| Backend warm metadata, empty/current/10k fixture | Median1.05/19.04/76.91ms; maximum2.40/22.98/83.28ms; seven warm queries each |
| Original cold metadata scan, current909 files /10k fixture | 24.2s /121.1s; cold source reads remain material |
| Later existing-history cache rebuild with OS caches warm | 4.10s; this is not first-ever application startup |
| Incremental10k-fixture external file update | 101.65ms; unreadable source remained inspectable |
| Final-source10k browser cold / warm fetch+DOM | 113.19s /93.3,84.3,88.5ms |
| Current desktop/mobile warm Library | 32.2/31.5ms in the recorded views |
| App construction with bundles already present | 799,141,150ms; excludes Python interpreter/browser/index startup and first bundle copy |

Warm first-page backend responses meet the500ms target and warm usable Library measurements meet1s on this machine. These are local workload measurements, not throughput or larger-corpus guarantees. The10k fixtures are deliberately metadata-shaped, not numerically valid experiment sets. Index freshness uses mtime/ctime/size; same-size timestamp-restored edits require **Rebuild index**. A metadata summary is not full mathematical validation.

Partial survey and local uncertainty do not guarantee the right basin or unique geometry. The paired survey demonstration reduced median world errors while worsening range fit; full22/22 local rank still accompanied large world error. See [measured gains and losses](M7.md). Conditional intervals omit undiscovered alternatives and are not general robust covariance or unconditional prior-posterior coverage. The32-trial marginal result has substantial finite-sample uncertainty.

Single-run optimizer state is not checkpointed. Sweep recovery still requires readable main JSON; permanent storage failure can leave only a pending request after restart. No permanent-write durability, real UWB deployment, optional Ceres/Geomstats implementation or complete mobile-app certification is claimed. All work remains local and uncommitted; no push or external publication occurred.
