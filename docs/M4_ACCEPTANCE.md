# M4 acceptance and evidence

M4 adds variable 3D beacon maps and tag-height models to the existing moving-tag experiment viewer. This record maps the requested behavior to the retained numerical, service, mathematical-review and visual evidence. The integrated application was numerically checked, independently mathematically reviewed, and visually verified on the local Windows viewer.

## Acceptance mapping

| Requirement | Evidence and result |
| --- | --- |
| Beacon count, generated geometry, explicit coordinates, beacon height diversity, and planar/tilted/excursion/spatial truth | `tests/test_m4.py::test_dynamic_count_clocks_noise_and_ranges`, `test_tilted_plane_is_distinct_from_warped_truth`; acceptance artifacts under [`acceptance_20261014_065254_8317a25a`](../evidence/m4/acceptance_20261014_065254_8317a25a/). |
| Fixed/shared/soft/free tag height and shared/independent beacon-height models; known-map and joint-map gauges | `tests/test_m4.py::test_analytic_jacobians_for_every_supported_model`, `test_known_shared_height_is_estimated_joint_shared_height_is_gauge`, `test_joint_gauges_and_full_rank_independent_spatial_geometry`; see [`independent_math_review.json`](../evidence/m4/independent_math_review.json). |
| Range-only observability, reflections, below-beacon bounds, rank and prior disclosures | `test_coplanar_known_map_retains_reflection_and_below_selects_branch`, `test_joint_shared_plane_free_tags_discloses_measurement_rank_loss`, and `test_joint_spatial_reflection_is_retained_and_proper_alignment_cannot_hide_it`; the acceptance summary records both `coplanar_reflection_ambiguity` and `below_branch_without_planarity` invariants as passed. |
| Height-model mismatch, time interpolation, ping evaluation and asynchronous timing effects kept distinct | `test_height_model_projection_is_separate_from_time_interpolation`, plus the retained `truth_interpolation_only`, `truth_model_projection`, `truth_interpolation_floor` and `timing_approximation` diagnostics in the saved fixtures and sweep tables. |
| Six paired geometry sweep factors, shared observations and projected starts, all-start retention, checkpoints, CSV and offline import/reopen | [`tests/test_m4_sweeps.py`](../tests/test_m4_sweeps.py) and [`tests/test_m4_service.py`](../tests/test_m4_service.py), including `test_models_share_data_and_compatible_projected_starts`, `test_every_failure_is_retained_and_checkpointed`, `test_sweep_attempts_csv_checkpoint_and_offline_reopen`, and `test_offline_reopen_export_and_tamper_detection`. Reopening/import paths are tested with solve and generation functions patched to fail if invoked. |
| Error/failure outcomes and infrastructure persistence failures remain inspectable | `test_all_missing_nonconvergence_invalid_initial_and_exceptions_retained`, `test_projection_exception_retains_every_target_start`, and service worker/checkpoint recovery tests. A forced one-evaluation fixture remains explicitly nonconverged. |
| M0–M3 evidence/history is preserved | The final acceptance summary reports 409 pre-existing evidence/history files checked and unchanged. [`preservation_manifest.json`](../evidence/m4/preservation_manifest.json) records the preservation check. |

## Reproduction commands

From the repository root in PowerShell, launch the existing app on an isolated local port:

```powershell
.\.venv\Scripts\python.exe app.py --port 5053
```

Open [the local viewer](http://127.0.0.1:5053) and use the separate **M4 · 3D beacon and tag geometry** panel. Configure the common motion/acquisition/range controls, then choose 3–8 beacons, a generated layout or explicit coordinates, truth-height profile, known-map or joint estimation, tag-height model, beacon-height model and optional below-beacon constraint. Run one M4 experiment or a paired geometry sweep. The sweep factors are beacon count, nominal beacon height (`vertical_separation`), height spread, path coverage, height-prior sigma and beacon-height model. Saved runs and artifacts can be reopened or imported without another solve.

Run the automated checks and evidence generators with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\validate_m4.py
.\.venv\Scripts\python.exe scripts\benchmark_m4.py
```

The final integrated test record is [`test_results_delivery.txt`](../evidence/m4/test_results_delivery.txt): 110 tests passed in 8.446 s. The M4 service-specific suite is [`service_tests_attempt1.txt`](../evidence/m4/service_tests_attempt1.txt): 6 tests passed. Validation and benchmarks create uniquely named folders under `evidence/m4/` rather than overwriting prior evidence.

## Measured numerical and performance results

The completed acceptance run contains six sweeps (56 runs, 112 starts) and 16 saved standalone runs (13 fixture summaries plus the three reflection/bound demonstrations). All 112 sweep starts converged, while 64 met the declared exact-geometry threshold. The forced nonconvergence fixture remains retained. The exact threshold is maximum trajectory and beacon error at most `1e-5 m`; the exact range-residual threshold is `1e-7 m`. Convergence, measurement residual, local rank and geometry acceptance are separate outcomes.

The noncoplanar known-map free-height fixture recovered position to `1.74e-15 m` RMS. A tilted planar truth had `0.984 m` world-z span but `4.52e-16 m` plane-departure RMS; the warped spatial fixture had `0.217 m` plane-departure RMS. The below-beacon constraint selected one reflected branch without requiring a planar tag path. In the independent mathematical review, analytic Jacobians for all 16 supported mode/tag/beacon model combinations agreed with directional central differences to at most `4.88e-8` absolute discrepancy.

These figures illustrate observable cases, not a general accuracy guarantee. A joint free-tag fit with four coplanar beacons retained measurement rank `39/41`; a collinear map retained `27/28`. For the reviewed synthetic shared-height spatial maps, 3–5 beacons remained locally rank deficient for some configurations while the tested 6–8 beacon cases were locally full rank. Rank depends on the selected geometry and parameterization and does not prove global uniqueness. Exact range fits can also be geometrically wrong or reflected.

The measured paired known-map benchmark used `0.05 m` range noise and `0.02 s` ping spacing. Whole-wrapper run times for 3 beacons at 12/24 samples were `0.178/0.353 s`; for 8 beacons they were `0.192/0.343 s`. These are this machine's Python wrapper timings, including generation and output construction, not browser render or latency guarantees. [`history_performance.json`](../evidence/m4/history_performance.json) recorded a 1.459 s list request for 268 retained runs.

## Visual evidence and remaining gates

The retained images demonstrate a tilted truth/fitted height trace, signed height/plane-departure series, joint 3D beacon geometry, reflection ambiguity, and a below-bound fit that remains warped:

- [Tag height against time](../evidence/m4/visual/tilted_height.png)
- [Height error and plane departures](../evidence/m4/visual/tilted_plane_errors.png)
- [Joint independent-height 3D scene](../evidence/m4/visual/joint_independent_3d.jpg)
- [Coplanar reflection branch](../evidence/m4/visual/coplanar_reflection.jpg)
- [Below-beacon bound preserves warp](../evidence/m4/visual/below_bound_preserves_warp.jpg)
- [Planar reference planes](../evidence/m4/visual/reference_planes.jpg)

The final browser review exercised new known-map tilted-plane and joint spatial runs from independent initialization, six-beacon playback, an editable eight-beacon map, a fresh four-run paired sweep, saved sweep reopening, selection of each retained attempt without clearing the 32-row table, JSON/CSV/PNG exports, local JSON imports, and the shared saved-run comparison. The eight-beacon exported configuration normalizes to exactly the saved run configuration/options. The fresh paired sweep retains identical estimator inputs across all four runs. The prior-sigma setting in that workflow fixture is inactive for its fixed/free variants; the scientific prior-strength sweep uses soft models in the main acceptance artifacts.

Current-build evidence is in [`visual/`](../evidence/m4/visual/): `m4_controls_final.jpg`, `sweep_all_attempts.jpg`, `fresh_sweep_workspace.jpg`, `fresh_custom_map_sweep.json`, `beacon_count_sweep.{json,csv,png}`, `comparison_live.json`, `custom_eight_config.json`, `custom_eight_live_run.json`, and `custom_eight_scene.png`. Height/plane exports and the scene PNG were opened and inspected. Scene export initially timed out using a detached data-URL link; `scene_export_attempt1.json` retains that failure. Switching to Plotly's download helper produced the inspected scene successfully. The earlier local count/order validation attempt is likewise retained and its input/change wiring corrected.

`camera_playback_import.json` verifies identical Side camera before/after scrubbing imported 3D results; `animation_preservation.json` records playback advancing from ping 1 to 41/72 with the camera and selected aligned comparison setting preserved. `legacy_m3_reopen.json` and its screenshot verify an existing grouped M3 result and its receiver/range/timing/speed controls still reopen. Browser error/warning logs were empty during that check. Unsupported joint free/independent-height below bounds give the explicit message in `unsupported_bound.json` before queueing.

Measured M4 height/plane chart renders were 36.0/21.1 ms; the reopened sweep chart took 27.8 ms; a reopened 3D scene took 149.7 ms; recorded animated ping updates were 16.7–19.8 ms. These measurements apply to the normal desktop viewport and these saved configurations. Mobile layout and maximal-size performance are not certified. The speed chart is labeled planar speed and excludes vertical motion.

[`height_sensitivity.json`](../evidence/m4/height_sensitivity.json) additionally checks vertical derivatives independently: zero first-order vertical information at a coplanar beacon plane, weak information at tiny separation, and improved local sensitivity with diverse heights. Zero derivatives do not imply absence of second-order information or prove a continuous ambiguity.

## Interpretation limits

Joint range-only geometry has rigid-frame gauges and distance-reflection ambiguities. Alignment uses proper rigid transforms and does not remove reflections, scale, height error or tilt. In joint soft/free models the height reference is the signed first-three-beacon plane; it is not surveyed world z. A soft-height prior and below-beacon bounds add assumptions, not measurements. Shared joint tag height fixes a gauge rather than recovering an absolute height. Unsupported combinations of below-beacon bounds and independent beacon heights with free/soft joint tag heights are rejected before queueing.

Truth interpolation, height-model projection and grouped/timestamp-aware timing approximation are reported separately when available. They explain representation/model mismatch but are not rigorous lower bounds on optimizer error. Missing evaluation metadata is represented as unavailable, not zero. For more detail on schemas, sweep limits, aggregation and numerical conventions, see [M4 geometry and height-model sweeps](M4.md).

The requirement-level completion and offline export/preservation audit is saved in [`final_audit.json`](../evidence/m4/final_audit.json). M4 roadmap items were checked only after this evidence was recorded. The working-tree changes remain local and uncommitted; no external publication was performed.
