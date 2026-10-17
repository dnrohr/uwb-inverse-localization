(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const rows = value => Array.isArray(value) ? value : [];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const num = (value, places = 4) => value === null || value === undefined || value === '' || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(places);
  const state = { run: null, artifact: null, inspectingRunId: null, restoredNoise: null, restoredSigma: null };
  async function api(url, options = {}) {
    const response = await fetch(url, { headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers }, ...options });
    if (!response.ok) { let message = `${response.status} ${response.statusText}`; try { const body = await response.json(); message = body.error || body.message || message; } catch (_) {} throw new Error(message); }
    return response.json();
  }
  function toast(message) { const node = $('toast'); if (node) { node.textContent = message; node.classList.add('visible'); setTimeout(() => node.classList.remove('visible'), 3000); } }
  function numericList(text, count, integer = false) {
    const result = String(text).split(',').map(token => token.trim());
    if (result.length !== count || result.some(token => !token || !Number.isFinite(Number(token)) || integer && !Number.isInteger(Number(token)))) throw new Error(`Enter exactly ${count} ${integer ? 'integer' : 'numeric'} values separated by commas.`);
    return result.map(Number);
  }
  function baseConfig(count) {
    const hook = window.RangeLabM3;
    const base = hook?.formConfig ? hook.formConfig(count) : window.RangeLabM2?.formConfig?.();
    if (!base) throw new Error('The shared experiment controls are unavailable.');
    const config = structuredClone(base);
    config.acquisition ||= {};
    config.acquisition.beacon_order = numericList($('m4Order').value, count, true);
    if ([...config.acquisition.beacon_order].sort((a, b) => a - b).some((value, i) => value !== i)) throw new Error('Beacon order must contain each beacon ID exactly once.');
    config.acquisition.beacon_every_cycles = numericList($('m4Strides').value, count, true);
    if (config.acquisition.beacon_every_cycles.some(value => value < 1)) throw new Error('Cycle strides must be positive integers.');
    for (const key of ['noise_std_m', 'assumed_std_m']) {
      const source = config[key];
      const restored = key === 'noise_std_m' ? state.restoredNoise : state.restoredSigma;
      const inputValue = Array.isArray(source) ? Number(source[0]) : Number(source);
      if (restored && inputValue === restored.input) {
        if (restored.values.length === count) { config[key] = restored.values.slice(); continue; }
        if (restored.values.length && restored.values.every(value => Number(value) === Number(restored.values[0]))) { config[key] = Array.from({ length: count }, () => Number(restored.values[0])); continue; }
        throw new Error(`Saved per-beacon ${key === 'noise_std_m' ? 'noise' : 'assumed uncertainty'} has ${restored.values.length} entries, which cannot be changed to ${count} beacons without losing its nonuniform values.`);
      }
      if (restored) { if (key === 'noise_std_m') state.restoredNoise = null; else state.restoredSigma = null; }
      if (Array.isArray(source)) {
        if (source.length === count) continue;
        if (source.length && source.every(value => Number(value) === Number(source[0]))) config[key] = Array.from({ length: count }, () => Number(source[0]));
        else throw new Error(`${key === 'noise_std_m' ? 'Noise' : 'Assumed range uncertainty'} has a nonuniform per-beacon vector that cannot be resized from ${source.length} to ${count} beacons. Update the base uncertainty controls to a uniform value first.`);
      } else if (source !== undefined && source !== null) config[key] = Array.from({ length: count }, () => Number(source));
    }
    const coordinates = $('m4Coordinates').value.trim();
    let coordinates_m;
    if (coordinates) {
      coordinates_m = coordinates.split(/\r?\n/).map(line => numericList(line.replace(/\s/g, ''), 3));
      if (coordinates_m.length !== count) throw new Error(`Enter ${count} beacon coordinate rows, each as x,y,z.`);
    }
    config.beacon_layout = {
      count,
      geometry: $('m4BeaconGeometry').value,
      height_m: Number($('m4BeaconHeight').value),
      height_spread_m: Number($('m4HeightSpread').value),
      baseline_scale: Number($('m4Baseline').value),
      ...(coordinates_m ? { coordinates_m } : {})
    };
    config.truth_height = { type: $('m4TruthHeightType').value, offset_m: Number($('m4TagOffset').value), amplitude_m: Number($('m4TagAmplitude').value), tilt_deg: Number($('m4Tilt').value) };
    for (const [label, value] of Object.entries({ 'nominal beacon height': config.beacon_layout.height_m, 'height spread': config.beacon_layout.height_spread_m, 'baseline scale': config.beacon_layout.baseline_scale, 'tag height offset': config.truth_height.offset_m, 'height amplitude': config.truth_height.amplitude_m, 'tilt angle': config.truth_height.tilt_deg })) {
      if (!Number.isFinite(value) || (label === 'height spread' || label === 'height amplitude' ? value < 0 : label === 'baseline scale' ? value <= 0 : false)) throw new Error(`${label} is outside its valid range.`);
    }
    return config;
  }
  function formOptions() {
    const opts = window.RangeLabM3?.formOptions ? window.RangeLabM3.formOptions() : {};
    const prior = Number($('m4HeightPrior').value), fixed = Number($('m4FixedZ').value);
    if (!Number.isFinite(prior) || prior <= 0 || !Number.isFinite(fixed)) throw new Error('Height prior sigma must be positive and the height datum / prior target must be finite.');
    return { ...opts, mode: $('m4Mode').value, tag_height_model: $('m4TagModel').value, beacon_height_model: $('m4BeaconModel').value, fixed_tag_z_m: fixed, height_prior_sigma_m: prior, below_beacons: $('m4Below').checked };
  }
  function formPayload() {
    const count = Number($('m4BeaconCount').value);
    if (!Number.isInteger(count) || count < 3 || count > 8) throw new Error('Beacon count must be an integer from 3 through 8.');
    const config = baseConfig(count), options = formOptions();
    if ($('m4Below').checked && options.mode !== 'known_map' && options.beacon_height_model === 'independent' && ['free', 'soft'].includes(options.tag_height_model)) throw new Error('The below-beacons constraint is unsupported for joint independent-beacon free/soft height estimation.');
    return { config, options };
  }
  function download(name, type, content) { if(window.RangeLabWorkspace?.download)return window.RangeLabWorkspace.download(name,content,type);
    const blob = new Blob([content], { type }), url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function runLabel(run) {
    const opts = run?.options || {}, layout = run?.experiment?.config?.beacon_layout || {};
    return `${run?.reference_name || run?.experiment?.config?.scenario || run?.scenario || 'M4'} · ${layout.count ?? run?.beacon_count ?? '?'} beacons · ${opts.tag_height_model || run?.tag_height_model || 'fixed'} tag / ${opts.beacon_height_model || run?.beacon_height_model || 'shared'} beacon`;
  }
  function setRunList(runs, selectedId) {
    const target = $('m4RunsList');
    target.innerHTML = runs.length ? runs.map(run => `<button class="run-item ${run.id === selectedId ? 'selected' : ''}" type="button" data-m4-run="${esc(run.id)}"><span class="run-runmark ${esc(run.status || '')}"></span><span class="run-info"><span class="run-name">${esc(runLabel(run))}</span><span class="run-meta">${esc(run.id)} · ${esc(run.status || 'saved')}</span></span><span class="run-open">›</span></button>`).join('') : '<div class="empty-runs">No saved M4 runs yet.</div>';
    target.querySelectorAll('[data-m4-run]').forEach(button => button.addEventListener('click', () => openRun(button.dataset.m4Run)));
  }
  async function refreshRuns() { window.RangeLabLibrary?.invalidate(); }
  function truth(run) { return run?.experiment?.truth || run?.truth || {}; }
  function errorFrame(run) {
    const noise = run?.experiment?.config?.noise_std_m, values = Array.isArray(noise) ? noise : [noise];
    const exact = values.length > 0 && values.every(value => Number(value) === 0);
    return run?.schema_version === '7.0' || run?.options?.mode === 'known_map' || exact ? 'raw' : 'aligned';
  }
  function selectedStart(run) {
    const selected = window.RangeLab?.state?.selectedStart ?? run?.selected_start;
    return rows(run?.starts).find(start => String(start.index) === String(selected)) || rows(run?.starts).find(start => start.success) || rows(run?.starts)[0] || {};
  }
  function transformPoint(point, alignment) {
    if (!alignment?.applied || !Array.isArray(point)) return Array.isArray(point) ? point.slice(0, 3) : point;
    if (Array.isArray(alignment.rotation_xyz) && Array.isArray(alignment.translation_xyz_m)) return [0, 1, 2].map(j => point.slice(0, 3).reduce((sum, value, i) => sum + Number(value) * alignment.rotation_xyz[i][j], 0) + alignment.translation_xyz_m[j]);
    const rotation = alignment.rotation_xy, translation = alignment.translation_xy_m;
    if (!rotation || !translation) return point.slice(0, 3);
    return [point[0] * rotation[0][0] + point[1] * rotation[1][0] + translation[0], point[0] * rotation[0][1] + point[1] * rotation[1][1] + translation[1], Number(point[2] || 0) + Number(alignment.gauge_translation_z_m || 0)];
  }
  function disclosure(run) {
    const config = run?.experiment?.config || {}, options = run?.options || {}, diagnostics = run?.diagnostics || {}, start = selectedStart(run), diag = start.diagnostics || {};
    const gauge = diagnostics.gauge || diag.gauge || {}, constraints = diagnostics.constraints || diag.constraints || {};
    const plane = diag.height?.best_fit_plane || diag.height?.fit_planarity || diag.best_fit_plane || {};
    const truthPlane = diag.height?.truth_planarity || diagnostics.height?.truth_planarity || {};
    const beaconPlane = diag.height?.truth_beacon_planarity || diagnostics.height?.truth_beacon_planarity || {};
    const knownMap = options.mode === 'known_map';
    let gaugeText = gauge.description || gauge.summary || gauge.reason || gauge.status || (knownMap ? 'Known beacon coordinates fix the map frame; tag height is in world z.' : options.tag_height_model === 'shared' ? 'Joint-map shared tag height fixes the absolute height datum; that common height is not independently observable from ranges alone.' : 'Joint-map free/soft height uses the signed first-three-beacon triangle frame for its vertical datum; inspect the run gauge diagnostic for remaining freedoms.');
    let constraintText = constraints.below_rule || constraints.summary || constraints.unsupported_reason || (options.below_beacons ? knownMap ? 'Below-beacons constraint is max tag z ≤ minimum surveyed beacon z.' : 'Below-beacons constraint is canonical tag z ≤ 0 for supported joint free/shared models.' : 'No tag-below-beacons constraint is active.');
    const planeRms = plane.rms_departure_m ?? plane.rms_m, planeMax = plane.max_departure_m ?? plane.max_abs_m ?? plane.max_m;
    const planeText = planeRms === null || planeRms === undefined ? 'Best-fit plane departures unavailable.' : `Selected fitted trajectory best-fit plane: RMS departure ${num(planeRms)} m, maximum ${num(planeMax)} m; a tilted plane is rigid planar geometry, while systematic departures can indicate warp or vertical excursion.`;
    const truthPlaneText = truthPlane.rms_m === undefined ? '' : `Truth trajectory planarity: RMS=${num(truthPlane.rms_m)} m, max=${num(truthPlane.max_abs_m)} m; surveyed beacon planarity RMS=${num(beaconPlane.rms_m)} m (max ${num(beaconPlane.max_abs_m)} m).`;
    const priorText = options.tag_height_model === 'soft' ? `Soft-height prior σ=${num(options.height_prior_sigma_m)} m, target/datum ${num(options.fixed_tag_z_m)} m; ${esc(diag.height?.prior_definition || gauge.height_prior_plane || 'soft height regularization per core definition')}.` : `Height prior setting σ=${num(options.height_prior_sigma_m)} m is inactive for the ${esc(options.tag_height_model || 'selected')} tag-height model.`;
    const measurementRank = diag.jacobian || {}, augmentedRank = diag.augmented_jacobian || {};
    const rankText = `Measurement-only Jacobian rank ${measurementRank.rank ?? '—'}/${measurementRank.parameter_count ?? '—'}${measurementRank.full_column_rank === true ? ' (full)' : measurementRank.full_column_rank === false ? ' (deficient)' : ''}; prior-augmented rank ${augmentedRank.rank ?? '—'}/${augmentedRank.parameter_count ?? '—'}${augmentedRank.full_column_rank === true ? ' (full)' : augmentedRank.full_column_rank === false ? ' (deficient)' : ''}. Measurement objective=${num(diag.measurement_objective ?? start.solver?.measurement_objective)}; motion+height prior objective=${num(diag.prior_objective ?? start.solver?.prior_objective)}; height-prior objective=${num(diag.height_prior_objective ?? start.solver?.height_prior_objective)}.`;
    const interpolationOnly = diagnostics.truth_interpolation_only || {}, modelProjection = diagnostics.truth_model_projection || {}, interpolationFloor = diagnostics.truth_interpolation_floor || {}, timing = diagnostics.timing_approximation || {};
    const summaryText = (label, value) => `${label} position RMSE=${num(value?.position_rmse_m)} m, maximum=${num(value?.position_max_error_m)} m`;
    const modelText = `Truth-model projection: knot position RMSE=${num(modelProjection.knot_position_rmse_m)} m; beacon RMSE=${num(modelProjection.beacon_rmse_m)} m.`;
    const floorText = `Combined truth-interpolation floor: display RMSE=${num(interpolationFloor.display_position_rmse_m ?? interpolationFloor.display?.position_rmse_m)} m; ping RMSE=${num(interpolationFloor.ping_position_rmse_m ?? interpolationFloor.pings?.position_rmse_m)} m. This includes representation and model mismatch, not an optimizer lower bound.`;
    const timingText = `Timing approximation (grouped versus timestamp-aware): position RMSE=${num(timing.position_rmse_m)} m, maximum=${num(timing.position_max_error_m)} m.`;
    const interpolationText = `Truth-interpolation-only reference (no selected tag/beacon model projection): ${summaryText('display', interpolationOnly.display)}; ${summaryText('ping', interpolationOnly.pings)}.`;
    const trajectoryModel = diagnostics.trajectory_model || {};
    const trajectoryText = `Estimator trajectory model: ${trajectoryModel.type || '—'}, ${trajectoryModel.knot_count ?? '—'} knots over ${Array.isArray(trajectoryModel.domain_s) ? trajectoryModel.domain_s.map(num).join('–') : '—'} s; grouping reference: ${trajectoryModel.grouping_rule || '—'}.`;
    $('m4Disclosure').innerHTML = `<div class="m3-numeric-disclosure"><b>3D numerical interpretation.</b> ${esc(knownMap ? 'Known-map initialization/optimization uses the supplied beacon coordinates and removes map gauge freedom.' : 'Joint-map estimation can retain translation, rotation and reflection gauges unless the selected constraints/model remove them.')} Tag height model: <b>${esc(options.tag_height_model || '—')}</b>; beacon height model: <b>${esc(options.beacon_height_model || '—')}</b>. ${esc(gaugeText)} ${esc(knownMap ? 'Coplanar surveyed maps can admit tag reflections across the beacon plane; noncoplanar surveyed coordinates generally break that symmetry. Bounds and priors may select branches; rank alone does not prove uniqueness.' : gauge.remaining_reflections || diagnostics.ambiguity || '')} ${esc(constraintText)} ${priorText} ${esc(rankText)} ${esc(planeText)} ${esc(truthPlaneText)} ${esc(trajectoryText)} ${esc(interpolationText)} ${esc(modelText)} ${esc(floorText)} ${esc(timingText)} ${config.truth_height ? `Truth height profile ${esc(config.truth_height.type)}, offset ${esc(num(config.truth_height.offset_m))} m, amplitude ${esc(num(config.truth_height.amplitude_m))} m, tilt ${esc(num(config.truth_height.tilt_deg))}°.` : ''}`;
    $('m4Disclosure').classList.remove('hidden');
  }
  function planeDepartures(points, plane) {
    const normal = plane?.normal, centroid = plane?.centroid;
    if (!Array.isArray(normal) || !Array.isArray(centroid) || normal.length !== 3 || centroid.length !== 3) return null;
    return points.map(point => Array.isArray(point) && point.length >= 3 && point.slice(0, 3).every(Number.isFinite)
      ? point.slice(0, 3).reduce((sum, value, axis) => sum + (value - centroid[axis]) * normal[axis], 0) : null);
  }
  function renderTimed(target, traces, layout, config = { responsive: true, displaylogo: false }) {
    const started = performance.now();
    delete target.dataset.renderMs;
    target.querySelectorAll('.chart-empty').forEach(node => node.remove());
    return Plotly.react(target, traces, layout, config).then(() => { target.dataset.renderMs = (performance.now() - started).toFixed(2); });
  }
  function renderRun(run) {
    state.run = run;
    const t = truth(run), times = rows(t.times_s), truthTrajectory = rows(t.trajectory), start = selectedStart(run), height = start.diagnostics?.height || {}, estimate = rows(start.estimate?.trajectory || start.estimate?.display_trajectory || start.estimate?.ping_trajectory);
    const alignment = start.diagnostics?.evaluation?.alignment || start.evaluation?.alignment || start.aligned_estimate?.alignment;
    const aligned = $('coordinateMode')?.value === 'aligned' && run.options?.mode !== 'known_map';
    const count = Math.min(times.length, truthTrajectory.length), fitted = aligned ? estimate.map(point => transformPoint(point, alignment)) : estimate;
    const heightTimes = rows(height.times_s), fitTimes = heightTimes.length ? heightTimes : rows(start.estimate?.times_s).length ? rows(start.estimate.times_s) : times.slice(0, fitted.length);
    const canonical = run.diagnostics?.truth_canonical_transform;
    const chartTruth = aligned ? truthTrajectory.slice(0, count) : canonical?.rotation_xyz && canonical?.translation_xyz_m ? truthTrajectory.slice(0, count).map(point => transformPoint(point, { ...canonical, applied: true })) : truthTrajectory.slice(0, count);
    const truthZ = aligned && rows(height.truth_z_m).length ? rows(height.truth_z_m) : chartTruth.map(point => Array.isArray(point) ? point[2] : null);
    const estimateZ = aligned && rows(height.estimate_z_m).length ? rows(height.estimate_z_m) : fitted.map(point => Array.isArray(point) ? point[2] : null);
    $('m4HeightFrame').textContent = `${aligned ? 'Proper rigid alignment at scale 1' : run.options?.mode === 'known_map' || run.schema_version==='7.0' ? 'Surveyed world frame' : 'Raw estimator frame'} · truth and selected fitted trajectory`;
    const heightTarget = $('m4HeightChart'), heightTraces = [
      { x: heightTimes.length ? heightTimes : times.slice(0, truthZ.length), y: truthZ, type: 'scatter', mode: 'lines', name: 'Truth z', line: { color: '#0b817b', width: 2 } },
      { x: fitTimes, y: estimateZ, type: 'scatter', mode: 'lines', name: 'Selected fitted z', line: { color: '#e88569', width: 2, dash: 'dash' } }
    ];
    if (window.Plotly && count) renderTimed(heightTarget, heightTraces, plotLayout('Tag z (m)'));
    const fitPlaneMetadata = height.fit_planarity || height.best_fit_plane || {};
    const truthPlaneMetadata = height.truth_planarity || run.diagnostics?.height?.truth_planarity || {};
    const alignedTrajectory = rows(start.diagnostics?.evaluation?.aligned_geometry?.trajectory);
    const fitDepartures = planeDepartures(alignedTrajectory, fitPlaneMetadata);
    const truthDepartures = planeDepartures(truthTrajectory.slice(0, count), truthPlaneMetadata);
    const heightErrors = aligned && rows(height.z_errors_m).length ? rows(height.z_errors_m) : estimateZ.length === truthZ.length ? estimateZ.map((value, index) => Number(value) - Number(truthZ[index])) : [];
    const errorX = fitTimes.length === heightErrors.length ? fitTimes : heightErrors.map((_, i) => i);
    const errorTraces = [];
    if (heightErrors.length) errorTraces.push({ x: errorX, y: heightErrors, type: 'scatter', mode: 'lines', name: 'Height error', line: { color: '#7458a8', width: 1.5 } });
    if (fitDepartures) errorTraces.push({ x: times.slice(0, fitDepartures.length), y: fitDepartures, type: 'scatter', mode: 'lines', name: 'Fitted plane departure · aligned world', line: { color: '#bc8740', width: 1.5 } });
    if (truthDepartures) errorTraces.push({ x: times.slice(0, truthDepartures.length), y: truthDepartures, type: 'scatter', mode: 'lines', name: 'Truth plane departure · world', line: { color: '#0b817b', width: 1.5, dash: 'dash' } });
    const planeRms = fitPlaneMetadata.rms_departure_m ?? fitPlaneMetadata.rms_m, planeMax = fitPlaneMetadata.max_departure_m ?? fitPlaneMetadata.max_abs_m;
    if (!fitDepartures && planeRms !== undefined) errorTraces.push({ x: ['RMS', 'Maximum'], y: [planeRms, planeMax], type: 'bar', name: 'Fitted plane departure', marker: { color: '#bc8740' } });
    const planeTarget = $('m4PlaneChart');
    if (window.Plotly && errorTraces.length) renderTimed(planeTarget, errorTraces, plotLayout('Height error / plane departure (m)'));
    else if (window.Plotly) { Plotly.purge(planeTarget); planeTarget.innerHTML = '<div class="chart-empty">Plane metadata unavailable —; height errors are also unavailable for this start.</div>'; }
    disclosure(run);
    $('m4ExportRunJson').disabled = false; $('m4ExportRunCsv').disabled = false; $('m4ExportScenePng').disabled = false;
    $('m4ExportHeightPng').disabled = !(window.Plotly && count); $('m4ExportPlanePng').disabled = !(window.Plotly && errorTraces.length);
    if (!state.artifact || run.id !== state.inspectingRunId) renderStartTable(rows(run.starts).map((item, index) => { const frame = errorFrame(run), evaluation = item.diagnostics?.evaluation?.[frame] || {}; return { value: null, variant: run.reference_name || 'single run', tag_height_model: item.tag_height_model || run.options?.tag_height_model || 'fixed', beacon_height_model: run.options?.beacon_height_model || 'shared', start_index: item.index ?? index, seed: item.seed ?? run.options?.seed ?? '—', status: item.status || '—', optimizer_converged: item.success ?? '—', error_frame: frame, position_rmse_m: evaluation.position_rmse_m, map_rmse_m: evaluation.map_rmse_m, height_rmse_m: item.diagnostics?.height?.world_z_rmse_m, range_rmse_m: item.diagnostics?.range_rmse_m, rank: item.diagnostics?.jacobian?.rank, parameter_count: item.diagnostics?.jacobian?.parameter_count, full_column_rank: item.diagnostics?.jacobian?.full_column_rank, augmented_full_column_rank: item.diagnostics?.augmented_jacobian?.full_column_rank, measurement_objective: item.diagnostics?.measurement_objective ?? item.solver?.measurement_objective, prior_objective: item.diagnostics?.prior_objective ?? item.solver?.prior_objective, height_prior_objective: item.diagnostics?.height_prior_objective ?? item.solver?.height_prior_objective, start: item }; }), item => inspectStart(run, item));
    $('m4ExportConfig').disabled = false;
  }
  function plotLayout(yTitle) { return { margin: { l: 54, r: 12, t: 12, b: 40 }, paper_bgcolor: '#fff', plot_bgcolor: '#fff', font: { size: 9, color: '#607475' }, xaxis: { title: { text: 'Elapsed time (s)' }, gridcolor: '#edf0f0' }, yaxis: { title: { text: yTitle }, gridcolor: '#edf0f0' }, legend: { orientation: 'h', y: 1.15 }, uirevision: 'm4-height' }; }
  function inspectStart(run, item) {
    if (item.start?.index !== undefined && window.RangeLab?.setSelectedStart) window.RangeLab.setSelectedStart(item.start.index);
    if (window.RangeLab?.state) { window.RangeLab.state.start = item.start; window.RangeLab.state.activeRun = run; window.RangeLab.renderRun(run); }
    else { state.run = run; renderRun(run); }
  }
  function renderStartTable(items, onOpen) {
    const target = $('m4AllStarts');
    if (!items.length) { target.innerHTML = '<div class="chart-empty">No start outcomes are available.</div>'; return; }
    const fmt = item => { const rank = item.measurement_rank ?? item.rank; return rank === null || rank === undefined || item.parameter_count === null || item.parameter_count === undefined ? '—' : `${rank}/${item.parameter_count}${item.measurement_full_column_rank === true || item.full_column_rank === true ? ' · full' : item.measurement_full_column_rank === false || item.full_column_rank === false ? ' · deficient' : ''}`; };
    target.innerHTML = `<table class="m2-table"><thead><tr><th>VALUE</th><th>VARIANT</th><th>TAG HEIGHT MODEL</th><th>BEACON HEIGHT MODEL</th><th>START</th><th>SEED</th><th>STATUS</th><th>CONVERGED</th><th>ERROR FRAME</th><th>POSITION RMSE (M)</th><th>MAP RMSE (M)</th><th>HEIGHT RMSE (M)</th><th>RANGE RMSE (M)</th><th>MEASUREMENT RANK / PARAMETERS</th><th>AUGMENTED FULL RANK</th><th>MEASUREMENT OBJECTIVE</th><th>PRIOR OBJECTIVE</th><th>HEIGHT PRIOR OBJECTIVE</th></tr></thead><tbody>${items.map((item, i) => `<tr class="m3-row" data-m4-row="${i}" tabindex="0"><td>${esc(item.value ?? '—')}</td><td>${esc(item.variant || item.model || '—')}</td><td>${esc(item.tag_height_model || '—')}</td><td>${esc(item.beacon_height_model || '—')}</td><td>${esc(item.start_index ?? '—')}</td><td>${esc(item.seed ?? '—')}</td><td>${esc(item.classification || item.status || '—')}</td><td>${esc(item.optimizer_converged ?? item.converged ?? '—')}</td><td>${esc(item.error_frame || '—')}</td><td>${num(item.position_rmse_m)}</td><td>${num(item.map_rmse_m)}</td><td>${num(item.height_rmse_m)}</td><td>${num(item.range_rmse_m)}</td><td>${esc(fmt(item))}</td><td>${esc(item.augmented_full_column_rank ?? '—')}</td><td>${num(item.measurement_objective)}</td><td>${num(item.prior_objective)}</td><td>${num(item.height_prior_objective)}</td></tr>`).join('')}</tbody></table>`;
    target.querySelectorAll('[data-m4-row]').forEach(row => { const open = () => onOpen(items[Number(row.dataset.m4Row)]); row.addEventListener('click', open); row.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } }); });
  }
  async function pollRun(id) {
    for (let i = 0; i < 3600; i++) {
      const job = await api(`/api/jobs/${encodeURIComponent(id)}`);
      if (job.status === 'complete' || job.status === 'failed') {
        const run = job.run || await api(`/api/runs/${encodeURIComponent(id)}`); run.id ||= id;
        if (window.RangeLab) { window.RangeLab.state.activeRun = run; window.RangeLab.state.selectedStart = null; window.RangeLab.renderRun(run); } else renderRun(run);
        await refreshRuns(id); toast(job.status === 'complete' ? 'M4 run complete.' : 'M4 run finished with a failure.'); return;
      }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    toast('M4 job is still running.');
  }
  async function runM4(event) {
    event.preventDefault(); let payload;
    try { payload = formPayload(); } catch (error) { return toast(error.message); }
    $('m4RunButton').disabled = true; clearArtifact(); clearRun();
    try { const created = await api('/api/m4/runs', { method: 'POST', body: JSON.stringify(payload) }); if (!created.id) throw new Error('The M4 run response did not include a job id.'); toast('M4 run queued.'); await pollRun(created.id); }
    catch (error) { toast(`Could not run M4: ${error.message}`); }
    finally { $('m4RunButton').disabled = false; }
  }
  async function openRun(id) {
    try { const run = await api(`/api/runs/${encodeURIComponent(id)}`); run.id ||= id; clearArtifact(); restore(run); if (window.RangeLab) { window.RangeLab.state.activeRun = run; window.RangeLab.state.selectedStart = null; window.RangeLab.renderRun(run); } else renderRun(run); await refreshRuns(id); }
    catch (error) { toast(`Could not open M4 run: ${error.message}`); }
  }
  function restore(run) {
    if (window.RangeLabWorkspace) return;

    const c = run?.experiment?.config || {}, l = c.beacon_layout || {}, h = c.truth_height || {}, o = run?.options || {};
    const set = (id, value) => { if (value !== undefined && value !== null && $(id)) $(id).value = value; };
    set('m4BeaconCount', l.count); set('m4BeaconGeometry', l.geometry); set('m4BeaconHeight', l.height_m); set('m4HeightSpread', l.height_spread_m); set('m4Baseline', l.baseline_scale); set('m4Coordinates', rows(l.coordinates_m).map(point => point.join(',')).join('\n'));
    set('m4TruthHeightType', h.type); set('m4TagOffset', h.offset_m); set('m4TagAmplitude', h.amplitude_m); set('m4Tilt', h.tilt_deg); set('m4Mode', o.mode); set('m4TagModel', o.tag_height_model); set('m4BeaconModel', o.beacon_height_model); set('m4FixedZ', o.fixed_tag_z_m); set('m4HeightPrior', o.height_prior_sigma_m); $('m4Below').checked = Boolean(o.below_beacons);
    set('m4Order', rows(c.acquisition?.beacon_order).join(',')); set('m4Strides', rows(c.acquisition?.beacon_every_cycles).join(','));
    if (window.RangeLabM3?.restoreConfig) window.RangeLabM3.restoreConfig(c, o);
    state.restoredNoise = Array.isArray(c.noise_std_m) && c.noise_std_m.length > 1 ? { values: c.noise_std_m.slice(), input: Number(c.noise_std_m[0]) } : null;
    state.restoredSigma = Array.isArray(c.assumed_std_m) && c.assumed_std_m.length > 1 ? { values: c.assumed_std_m.slice(), input: Number(c.assumed_std_m[0]) } : null;
  }
  function clearArtifact() {
    state.artifact = null; state.inspectingRunId = null; $('m4ExportJson').disabled = $('m4ExportCsv').disabled = $('m4ExportPng').disabled = true;
    const target = $('m4SweepChart'); if (window.Plotly) Plotly.purge(target); target.innerHTML = '<div class="chart-empty">Open a saved geometry sweep.</div>';
  }
  function clearRun() {
    state.run = null;
    for (const [id, message] of [['m4HeightChart', 'Open an M4 run to inspect tag height.'], ['m4PlaneChart', 'Vertical errors and plane residuals will appear here.']]) {
      const target = $(id); if (window.Plotly) Plotly.purge(target); target.innerHTML = `<div class="chart-empty">${message}</div>`;
    }
    $('m4AllStarts').innerHTML = '<div class="chart-empty">Run an M4 experiment or open a saved geometry sweep.</div>';
    $('m4Disclosure').textContent = ''; $('m4Disclosure').classList.add('hidden');
    $('m4ExportRunJson').disabled = $('m4ExportRunCsv').disabled = $('m4ExportScenePng').disabled = $('m4ExportHeightPng').disabled = $('m4ExportPlanePng').disabled = true;
  }
  function renderArtifact(artifact) {
    state.artifact = artifact; state.inspectingRunId = null;
    const rowsData = rows(artifact.start_table);
    renderStartTable(rowsData, item => {
      const entry = rows(artifact.entries).find(candidate => candidate.index === item.entry_index) || artifact.entries?.[Number(item.entry_index)];
      const run = entry?.run;
      if (!run) return toast('This sweep entry does not retain its run data.');
      run.id ||= entry.run_id || item.run_id;
      state.inspectingRunId = run.id;
      if (window.RangeLab) { window.RangeLab.state.activeRun = run; window.RangeLab.state.selectedStart = item.start_index; window.RangeLab.renderRun(run); } else renderRun(run);
    });
    renderSweepChart(artifact); $('m4ExportJson').disabled = false; $('m4ExportCsv').disabled = rowsData.length === 0; $('m4ExportPng').disabled = !rows(artifact.aggregates).length;
    const info = artifact.disclosure || artifact.numerical_disclosure || {};
    $('m4Disclosure').innerHTML = `<div class="m3-numeric-disclosure"><b>Geometry sweep disclosure.</b> ${esc(info.convention || artifact.aggregation_convention || 'Each attempted start is retained for every geometry and tag-height model.')} ${esc(info.caveat || '')}</div>`; $('m4Disclosure').classList.remove('hidden');
  }
  function renderSweepChart(artifact) {
    const target = $('m4SweepChart'), values = rows(artifact?.config?.values), aggregates = rows(artifact?.aggregates), factor = artifact?.config?.factor || 'geometry';
    const models = [...new Set(aggregates.map(row => row.variant || row.model).filter(Boolean))];
    const traces = models.map((model, index) => {
      const subset = values.map((value, value_index) => aggregates.find(row => (row.variant || row.model) === model && (row.value_index === value_index || row.value === value)));
      return { x: values, y: subset.map(row => row?.all_start_position_rmse_m?.median ?? row?.position_rmse_m?.median ?? null), type: 'scatter', mode: 'lines+markers', name: esc(model), line: { color: ['#0b817b', '#e88569', '#7458a8', '#bc8740'][index % 4], width: 2 } };
    });
    $('m4SweepLabel').textContent = `Saved all-start median trajectory RMSE · factor: ${factor} · values use each saved evaluation frame`;
    if (!window.Plotly || !traces.length) { if (window.Plotly) Plotly.purge(target); target.innerHTML = '<div class="chart-empty">No finite aggregate geometry errors are available.</div>'; return; }
    target.querySelectorAll('.chart-empty').forEach(node => node.remove());
    renderTimed(target, traces, { ...plotLayout('Median position RMSE (m)'), xaxis: { title: { text: factor }, gridcolor: '#edf0f0' }, hovermode: 'x unified', uirevision: 'm4-sweep' });
  }
  async function refreshSweeps() { window.RangeLabLibrary?.invalidate(); }
  async function openSweep(id) { try { const artifact = await api(`/api/m4/sweeps/${encodeURIComponent(id)}`); renderArtifact(artifact); await refreshSweeps(id); } catch (error) { toast(`Could not open geometry sweep: ${error.message}`); } }
  function parseValues(text, factor) { const tokens = String(text).split(',').map(value => value.trim()); if (!tokens.length || tokens.some(value => !value)) throw new Error('Enter comma-separated sweep values.'); return factor === 'beacon_height_model' ? tokens : tokens.map(value => { const n = Number(value); if (!Number.isFinite(n)) throw new Error('Sweep values must be numeric for this factor.'); return n; }); }
  async function runSweep(event) {
    event.preventDefault(); let payload;
    try {
      const base = formPayload(), factor = $('m4SweepFactor').value, values = parseValues($('m4SweepValues').value, factor), seeds = numericList($('m4SweepSeeds').value, String($('m4SweepSeeds').value).split(',').length, true), tagModels = $('m4SweepTagModels').value.split(',').map(value => value.trim()).filter(Boolean), budget = Number($('m4SweepBudget').value);
      if (new Set(seeds).size !== seeds.length || seeds.some(seed => seed < 0 || seed > 4294967295)) throw new Error('Sweep seeds must be distinct unsigned 32-bit integers.');
      if (new Set(values).size !== values.length) throw new Error('Geometry sweep values must be distinct.');
      if (!tagModels.length || new Set(tagModels).size !== tagModels.length || tagModels.some(model => !['fixed', 'shared', 'soft', 'free'].includes(model))) throw new Error('Tag models must be distinct values from fixed, shared, soft, free.');
      if (['beacon_count', 'vertical_separation', 'height_spread'].includes(factor) && base.config.beacon_layout.coordinates_m) throw new Error('Beacon layout factor sweeps require generated layouts; explicit coordinates define fixed geometry.');
      if (factor === 'beacon_count' && values.some(value => value !== base.config.beacon_layout.count)) {
        for (const key of ['noise_std_m', 'assumed_std_m']) { const vector = base.config[key]; if (Array.isArray(vector) && new Set(vector.map(Number)).size > 1) throw new Error(`A beacon-count sweep cannot resize the saved nonuniform ${key === 'noise_std_m' ? 'noise' : 'assumed uncertainty'} vector. Choose counts equal to the current count or use a uniform per-beacon value.`); }
      }
      if (factor === 'height_spread' && !base.config.beacon_layout.coordinates_m) base.config.beacon_layout.geometry = 'diverse';
      if (!Number.isInteger(budget) || budget < 1) throw new Error('Solver budget must be a positive integer.');
      payload = { base_experiment: base.config, options: { ...base.options, max_nfev: budget }, factor, values, seeds, variants: tagModels.map(tag_height_model => ({ label: tag_height_model, options: { tag_height_model } })) };
    } catch (error) { return toast(error.message); }
    const button = $('m4SweepForm').querySelector('button[type=submit]'); button.disabled = true;
    try { const created = await api('/api/m4/sweeps', { method: 'POST', body: JSON.stringify(payload) }); if (!created.id) throw new Error('The geometry sweep response did not include an id.'); toast('Geometry sweep queued.'); await pollSweep(created.id); }
    catch (error) { toast(`Could not run geometry sweep: ${error.message}`); }
    finally { button.disabled = false; }
  }
  async function pollSweep(id) {
    for (let i = 0; i < 3600; i++) {
      const job = await api(`/api/jobs/${encodeURIComponent(id)}`);
      if (job.status === 'complete' || job.status === 'failed') { const artifact = job.artifact || await api(`/api/m4/sweeps/${encodeURIComponent(id)}`); renderArtifact(artifact); await refreshSweeps(id); await refreshRuns(); toast(job.status === 'complete' ? 'Geometry sweep complete.' : 'Geometry sweep finished with a failure.'); return; }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    toast('Geometry sweep is still running.');
  }
  function exportCsv() {
    if (!state.artifact) return;
    const items = rows(state.artifact.start_table), keys = [...new Set(items.flatMap(item => Object.keys(item)))], csv = value => `"${String(value ?? '').replace(/"/g, '""')}"`;
    download(`m4-geometry-${state.artifact.id || 'sweep'}.csv`, 'text/csv', [keys.map(csv).join(','), ...items.map(item => keys.map(key => csv(typeof item[key] === 'object' ? JSON.stringify(item[key]) : item[key])).join(','))].join('\n'));
  }
  function exportRowsCsv(items, filename) {
    const keys = [...new Set(items.flatMap(item => Object.keys(item)))], csv = value => `"${String(value ?? '').replace(/"/g, '""')}"`;
    download(filename, 'text/csv', [keys.map(csv).join(','), ...items.map(item => keys.map(key => csv(typeof item[key] === 'object' ? JSON.stringify(item[key]) : item[key])).join(','))].join('\n'));
  }
  async function importJson(file) {
    if (!file) return;
    try {
      const payload = JSON.parse(await file.text()), saved = await api('/api/m4/import', { method: 'POST', body: JSON.stringify(payload) });
      if (saved.run) { const run = saved.run; run.id ||= saved.id; restore(run); if (window.RangeLab) { window.RangeLab.state.activeRun = run; window.RangeLab.state.selectedStart = null; window.RangeLab.renderRun(run); } else renderRun(run); await refreshRuns(run.id); toast('M4 run imported and saved.'); }
      else { const artifact = saved.artifact || saved; renderArtifact(artifact); await refreshSweeps(artifact.id); await refreshRuns(); toast('M4 geometry sweep imported.'); }
    } catch (error) { toast(`Could not import M4 JSON: ${error.message}`); }
    finally { $('m4ImportFile').value = ''; }
  }
  function init() {
    $('m4Form').addEventListener('submit', runM4); $('m4SweepForm').addEventListener('submit', runSweep);
    const updateBeaconSchedule = () => { const n = Number($('m4BeaconCount').value); if (!Number.isInteger(n) || n < 3 || n > 8) return; $('m4Order').value = Array.from({ length: n }, (_, i) => i).join(','); $('m4Strides').value = Array.from({ length: n }, () => 1).join(','); };
    $('m4BeaconCount').addEventListener('input', updateBeaconSchedule);
    $('m4BeaconCount').addEventListener('change', updateBeaconSchedule);
    $('m4SweepFactor').addEventListener('change', () => { const defaults = { beacon_count: '3,4,6', vertical_separation: '2,3,4', height_spread: '0,0.5,1', coverage: '0.5,1,1.5', height_prior_sigma_m: '0.05,0.2,0.5', beacon_height_model: 'shared,independent' }; $('m4SweepValues').value = defaults[$('m4SweepFactor').value] || ''; });
    $('m4ExportConfig').addEventListener('click', () => { try { download('uwb-m4-experiment-config.json', 'application/json', JSON.stringify({ schema_version: '4.0', artifact_type: 'experiment_config', ...formPayload() }, null, 2)); } catch (error) { toast(error.message); } });
    $('m4ExportRunJson').addEventListener('click', () => { if (state.run) download(`m4-run-${state.run.id || 'current'}.json`, 'application/json', JSON.stringify(state.run, null, 2)); });
    $('m4ExportRunCsv').addEventListener('click', () => { if (state.run) exportRowsCsv(rows(state.run.starts).map((start, index) => { const frame = errorFrame(state.run), evaluation = start.diagnostics?.evaluation?.[frame] || {}; return { start_index: start.index ?? index, seed: start.seed ?? state.run.options?.seed, status: start.status, converged: start.success, error_frame: frame, position_rmse_m: evaluation.position_rmse_m, map_rmse_m: evaluation.map_rmse_m, height_rmse_m: start.diagnostics?.height?.world_z_rmse_m ?? start.diagnostics?.height?.z_rmse_m ?? start.diagnostics?.height?.rmse_m, range_rmse_m: start.diagnostics?.range_rmse_m, measurement_rank: start.diagnostics?.jacobian?.rank, parameter_count: start.diagnostics?.jacobian?.parameter_count, measurement_objective: start.diagnostics?.measurement_objective ?? start.solver?.measurement_objective, prior_objective: start.diagnostics?.prior_objective ?? start.solver?.prior_objective, height_prior_objective: start.diagnostics?.height_prior_objective ?? start.solver?.height_prior_objective }; }), `m4-run-${state.run.id || 'current'}.csv`); });
    $('m4ExportScenePng').addEventListener('click', async () => { const scene = $('scene'); if (scene?.data && window.Plotly) { try { await Plotly.downloadImage(scene, { format: 'png', filename: `m4-scene-${state.run?.id || 'current'}`, width: 1400, height: 900, scale: 1 }); } catch (error) { toast(`Could not export scene image: ${error.message}`); } } });
    for (const [buttonId, chartId, name] of [['m4ExportHeightPng', 'm4HeightChart', 'height'], ['m4ExportPlanePng', 'm4PlaneChart', 'plane']]) $(buttonId).addEventListener('click', () => { const chart = $(chartId); if (chart?.data && window.Plotly) Plotly.downloadImage(chart, { format: 'png', filename: `m4-${name}-${state.run?.id || 'current'}`, width: 1200, height: 700, scale: 1 }); });
    $('m4ImportButton').addEventListener('click', () => $('m4ImportFile').click()); $('m4ImportFile').addEventListener('change', event => importJson(event.target.files?.[0]));
    $('m4ExportJson').addEventListener('click', () => { if (state.artifact) download(`m4-geometry-${state.artifact.id || 'sweep'}.json`, 'application/json', JSON.stringify(state.artifact, null, 2)); });
    $('m4ExportCsv').addEventListener('click', exportCsv); $('m4ExportPng').addEventListener('click', () => { if ($('m4SweepChart').data) Plotly.downloadImage($('m4SweepChart'), { format: 'png', filename: `m4-geometry-${state.artifact?.id || 'sweep'}`, width: 1400, height: 700, scale: 1 }); });
    refreshRuns(); refreshSweeps();
  }
  window.RangeLabM4 = { restoreRun:restore, openArtifact: renderArtifact, formPayload, restoreConfig(config, options) { restore({experiment:{config},options}); }, onRun(run) {
    if (run && (String(run.schema_version || '').startsWith('4') || run.experiment?.config?.beacon_layout)) {
      if (state.artifact?.entries?.some(entry=>entry.run===run) || state.artifact && run.id && run.id === state.inspectingRunId) { state.inspectingRunId = run.id; state.run = run; renderRun(run); }
      else { if (state.artifact) clearArtifact(); state.inspectingRunId = null; renderRun(run); }
    } else { if (state.artifact) clearArtifact(); state.inspectingRunId = null; clearRun(); }
  }, refresh() { refreshRuns(); refreshSweeps(); }, openRun, openSweep };
  document.addEventListener('DOMContentLoaded', init);
})();
