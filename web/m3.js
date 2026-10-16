(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const rows = value => Array.isArray(value) ? value : [];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const num = (value, places = 4) => value === null || value === undefined || value === '' || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(places);
  const state = { run: null, observations: [], pingPoints: [], sweeps: [], activeSweep: null, inspectingSweepRunId: null, overlayIndex: null, overlayPromise: null, selectedPing: 0, timer: null, restoredNoise: null, restoredAssumedSigma: null };
  async function api(url, options = {}) {
    const response = await fetch(url, { headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers }, ...options });
    if (!response.ok) { let message = `${response.status} ${response.statusText}`; try { const body = await response.json(); message = body.error || body.message || message; } catch (_) {} throw new Error(message); }
    return response.json();
  }
  function toast(message) { const node = $('toast'); if (!node) return; node.textContent = message; node.classList.add('visible'); setTimeout(() => node.classList.remove('visible'), 3000); }
  function list(text, integer = false) {
    const values = String(text).split(',').map(token => token.trim());
    if (!values.length || values.some(token => !token || !Number.isFinite(Number(token)) || (integer && !Number.isInteger(Number(token))))) throw new Error('Enter comma-separated numeric values.');
    return values.map(Number);
  }
  function controls() {
    const base = window.RangeLabM2?.formConfig?.();
    if (!base) throw new Error('The base M2 experiment controls are unavailable.');
    const order = list($('m3Order').value, true), strides = list($('m3Strides').value, true);
    if (order.length !== 4 || [...order].sort().some((value, i) => value !== i)) throw new Error('Beacon order must contain 0, 1, 2, 3 exactly once.');
    if (strides.length !== 4 || strides.some(value => value < 1)) throw new Error('Enter four positive integer per-beacon cycle strides.');
    const config = {
      ...base,
      motion: { profile: $('m3Motion').value, speed_scale: +$('m3Speed').value },
      acquisition: { cycle_rate_hz: +$('m3CycleRate').value, spacing_s: +$('m3PingSpacing').value, jitter_s: +$('m3AcqJitter').value, beacon_order: order, beacon_every_cycles: strides, timestamp_offset_s: +$('m3TimestampOffset').value, timestamp_jitter_s: +$('m3TimestampJitter').value, delivery_latency_s: +$('m3Latency').value, missing_probability: +$('m3Missing').value }
    };
    if (state.restoredNoise && Number(base.noise_std_m) === state.restoredNoise.input) config.noise_std_m = state.restoredNoise.values.slice();
    else state.restoredNoise = null;
    if (state.restoredAssumedSigma && Number(base.assumed_std_m) === state.restoredAssumedSigma.input) config.assumed_std_m = state.restoredAssumedSigma.values.slice();
    else state.restoredAssumedSigma = null;
    for (const [label, value] of [['speed scale', config.motion.speed_scale], ['cycle rate', config.acquisition.cycle_rate_hz], ['ping spacing', config.acquisition.spacing_s], ['acquisition jitter', config.acquisition.jitter_s], ['timestamp jitter', config.acquisition.timestamp_jitter_s], ['delivery latency', config.acquisition.delivery_latency_s]]) if (!Number.isFinite(value) || value < 0 || label === 'cycle rate' && value === 0) throw new Error(`${label} must be a valid nonnegative value.`);
    if (config.motion.speed_scale > 10) throw new Error('Speed scale must be from 0 to 10.');
    if (!Number.isFinite(config.acquisition.timestamp_offset_s) || config.acquisition.missing_probability < 0 || config.acquisition.missing_probability > 1) throw new Error('Timestamp offset must be finite and missing probability must be between 0 and 1.');
    return config;
  }
  function options() {
    const knot = +$('m3KnotSpacing').value, prior = +$('m3PriorSigma').value;
    if (!Number.isFinite(knot) || knot < 0 || !Number.isFinite(prior) || prior < 0) throw new Error('Knot spacing and prior sigma must be nonnegative.');
    return { mode: document.getElementById('mode')?.value || 'joint', initialization: document.getElementById('init')?.value || 'independent', starts: Number(document.getElementById('starts')?.value || 1), seed: Number(document.getElementById('initSeed')?.value || 19), max_nfev: Number($("m3MaxNfev").value), timing_model: $('m3TimingModel').value, knot_spacing_s: knot, prior_sigma_m: prior };
  }
  function pingPosition(run, observation, index) {
    const truth = run?.experiment?.truth || run?.truth || {};
    const candidates = [truth.ping_positions, truth.grouped_positions];
    for (const source of candidates) {
      const value = rows(source)[index];
      if (Array.isArray(value) && value.length >= 2 && Number.isFinite(+value[0])) return value.slice(0, 3).map(Number);
      if (Array.isArray(value?.position_m)) return value.position_m.slice(0, 3).map(Number);
      if (Array.isArray(value?.position)) return value.position.slice(0, 3).map(Number);
    }
    const trajectory = rows(truth.trajectory), times = rows(truth.times_s);
    const epoch = Number(observation?.epoch);
    if (Number.isInteger(epoch) && Array.isArray(trajectory[epoch])) return trajectory[epoch].slice(0, 3).map(Number);
    const time = Number(observation?.actual_time_s);
    if (Number.isFinite(time) && times.length === trajectory.length && times.length) {
      let hi = times.findIndex(t => Number(t) >= time);
      if (hi < 0) hi = times.length - 1;
      if (!hi) return trajectory[0].slice(0, 3).map(Number);
      const lo = hi - 1, f = (time - times[lo]) / Math.max(1e-12, times[hi] - times[lo]);
      return trajectory[lo].slice(0, 3).map((x, j) => x + f * (trajectory[hi][j] - x));
    }
    return null;
  }
  function observationsFor(run) {
    const experiment = run?.experiment || {};
    const observations = rows(experiment.estimator_input?.observations || experiment.observations || run?.observations);
    return observations.map((observation, i) => ({ observation, index: i, position: pingPosition(run, observation, i) })).filter(item => item.position);
  }
  function renderSpeed(run, observations) {
    if (!window.Plotly) return;
    const started = performance.now();
    const motion = run?.experiment?.truth?.motion || run?.truth?.motion || {};
    const times = rows(motion.times_s), speed = rows(motion.speed_m_s);
    const pts = observations.map(({ observation }) => Number(observation.actual_time_s)).filter(Number.isFinite);
    const traces = [{ x: times, y: speed, type: 'scatter', mode: 'lines', name: ['4.0','5.0','6.0','7.0'].includes(run.schema_version) ? 'Planar along-path speed (vertical motion excluded)' : 'Tag speed', line: { color: '#0b817b', width: 2 }, hovertemplate: 't=%{x:.3f} s<br>speed=%{y:.3f} m/s<extra></extra>' }];
    if (pts.length) traces.push({ x: pts, y: pts.map(() => 0), type: 'scatter', mode: 'markers', name: 'Ping times', marker: { color: '#e88569', size: 5, symbol: 'line-ns' }, hovertemplate: 'Ping at t=%{x:.4f} s<extra></extra>' });
    if (!times.length || !speed.length) {
      const truth = run?.experiment?.truth || {};
      const trajectory = rows(truth.trajectory), t = rows(truth.times_s);
      const derived = trajectory.slice(1).map((p, i) => Math.hypot(...p.slice(0, 3).map((v, j) => v - trajectory[i][j])) / Math.max(1e-12, Number(t[i + 1]) - Number(t[i])));
      if (derived.length) traces[0] = { x: t.slice(1), y: derived, type: 'scatter', mode: 'lines', name: ['4.0','5.0','6.0','7.0'].includes(run.schema_version) ? 'Planar along-path speed (vertical motion excluded)' : 'Tag speed', line: { color: '#0b817b', width: 2 } };
    }
    const target = $('m3SpeedChart'); target.querySelectorAll('.chart-empty').forEach(node => node.remove());
    Plotly.react(target, traces, { margin: { l: 43, r: 8, t: 8, b: 32 }, paper_bgcolor: '#fff', plot_bgcolor: '#fff', font: { size: 9, color: '#607475' }, xaxis: { title: { text: 'Actual time (s)' }, gridcolor: '#edf0f0' }, yaxis: { title: { text: ['4.0','5.0','6.0','7.0'].includes(run.schema_version) ? 'Planar speed (m/s)' : 'Speed (m/s)' }, rangemode: 'tozero', gridcolor: '#edf0f0' }, showlegend: false, uirevision: 'm3-speed' }, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ['toImage', 'sendDataToCloud', 'sendChartToCloud'] }).then(() => { target.dataset.renderMs = (performance.now() - started).toFixed(2); });
  }
  function coordinates(position) { return Array.isArray(position) ? position.slice(0, 3).map(Number) : null; }
  function sceneBeacon(run, observation) {
    const beacons = rows(run?.experiment?.truth?.beacons || run?.truth?.beacons);
    const id = Number(observation?.beacon_id);
    if (Number.isInteger(id) && Array.isArray(beacons[id])) return coordinates(beacons[id]);
    return null;
  }
  function groupedPosition(run, observation, pingIndex) {
    const truth = run?.experiment?.truth || {};
    const exact = rows(truth.grouped_positions)[pingIndex];
    if (Array.isArray(exact) && exact.length >= 2) return coordinates(exact);
    const times = rows(truth.times_s), trajectory = rows(truth.trajectory), epochTimes = rows(run?.experiment?.estimator_input?.times_s);
    const epoch = Number(observation?.epoch);
    let time = Number.isInteger(epoch) && epochTimes[epoch] !== undefined ? Number(epochTimes[epoch]) : Number(observation?.assumed_time_s);
    if (!Number.isFinite(time) || !times.length || times.length !== trajectory.length) return null;
    let hi = times.findIndex(t => Number(t) >= time);
    if (hi < 0) hi = times.length - 1;
    if (!hi) return coordinates(trajectory[0]);
    const lo = hi - 1, f = Math.max(0, Math.min(1, (time - times[lo]) / Math.max(1e-12, Number(times[hi]) - Number(times[lo]))));
    return trajectory[lo].slice(0, 3).map((v, j) => v + f * (trajectory[hi][j] - v));
  }
  function estimatedPing(run, observation, pingIndex) {
    const selected = window.RangeLab?.state?.selectedStart ?? run.selected_start;
    const start = rows(run?.starts).find(item => String(item.index) === String(selected)) || rows(run?.starts).find(item => item.success) || rows(run?.starts)[0];
    const points = rows(start?.estimate?.ping_trajectory || start?.estimate?.trajectory);
    const point = points[pingIndex];
    if (!Array.isArray(point) || point.length < 2) return null;
    const result = coordinates(point), aligned = $('coordinateMode')?.value === 'aligned' && run.options?.mode !== 'known_map';
    const transform = start?.diagnostics?.evaluation?.alignment || start?.evaluation?.alignment || start?.aligned_estimate?.alignment;
    if (aligned && transform?.applied && Array.isArray(transform.rotation_xyz) && Array.isArray(transform.translation_xyz_m)) {
      return [0, 1, 2].map(j => result.reduce((sum, value, i) => sum + value * transform.rotation_xyz[i][j], 0) + transform.translation_xyz_m[j]);
    }
    if (aligned && transform?.applied && Array.isArray(transform.rotation_xy) && Array.isArray(transform.translation_xy_m)) {
      const [x, y] = result, rotation = transform.rotation_xy, translation = transform.translation_xy_m;
      result[0] = x * rotation[0][0] + y * rotation[1][0] + translation[0];
      result[1] = x * rotation[0][1] + y * rotation[1][1] + translation[1];
      result[2] += transform.gauge_translation_z_m || 0;
    }
    return result;
  }
  function updatePing(index) {
    if (!state.pingPoints.length) return;
    state.selectedPing = Math.max(0, Math.min(state.pingPoints.length - 1, Number(index) || 0));
    $('m3PingSlider').value = state.selectedPing;
    const item = state.pingPoints[state.selectedPing], observation = item.observation, scene = $('scene');
    const selected = window.RangeLab?.pickStart(state.run, window.RangeLab?.state?.selectedStart);
    const canonical = ['4.0','5.0','6.0'].includes(state.run?.schema_version) && state.run.options?.mode === 'joint' && $('coordinateMode')?.value !== 'aligned' ? selected?.diagnostics?.evaluation?.truth_canonical_transform || state.run.diagnostics?.truth_canonical_transform : null;
    const truthPoint = point => point && canonical ? [0,1,2].map(j => point.reduce((sum,value,i)=>sum+value*canonical.rotation_xyz[i][j],0)+canonical.translation_xyz_m[j]) : point;
    const p = truthPoint(item.position), beacon = truthPoint(sceneBeacon(state.run, observation));
    const grouped = truthPoint(groupedPosition(state.run, observation, item.index));
    const tagLabel = `Tag at ${num(observation.actual_time_s, 4)} s`;
    let rayEnd = p;
    if (beacon && Number.isFinite(Number(observation.range_m))) {
      const delta = p.map((value, axis) => value - beacon[axis]), length = Math.hypot(...delta);
      if (length > 1e-12) rayEnd = beacon.map((value, axis) => value + delta[axis] * Number(observation.range_m) / length);
    }
    const rayTrace = { type: 'scatter3d', mode: 'lines+markers', name: 'Measured range ray', x: beacon ? [beacon[0], rayEnd[0]] : [], y: beacon ? [beacon[1], rayEnd[1]] : [], z: beacon ? [beacon[2] || 0, rayEnd[2] || 0] : [], line: { color: '#e88569', width: 5 }, marker: { color: ['#4579ad', '#e88569'], size: [6, 5], symbol: ['diamond', 'circle'] }, text: beacon ? [`Beacon ${observation.beacon_id}`, `Measured endpoint · ${num(observation.range_m, 3)} m`] : [], hovertemplate: '%{text}<br>(%{x:.3f}, %{y:.3f}, %{z:.3f}) m<extra></extra>' };
    const actualTrace = { type: 'scatter3d', mode: 'markers', name: 'Actual tag position', x: [p[0]], y: [p[1]], z: [p[2] || 0], marker: { color: '#0b817b', size: 8, symbol: 'circle', line: { color: '#fff', width: 1 } }, text: [tagLabel], hovertemplate: '%{text}<br>(%{x:.3f}, %{y:.3f}, %{z:.3f}) m<extra></extra>' };
    const estimate = estimatedPing(state.run, observation, item.index);
    const groupedTrace = { type: 'scatter3d', mode: 'markers', name: 'Grouped common position', x: grouped ? [grouped[0]] : [], y: grouped ? [grouped[1]] : [], z: grouped ? [grouped[2] || 0] : [], marker: { color: '#bc8740', size: 7, symbol: 'diamond' }, text: ['Assumed epoch common position'], hovertemplate: '%{text}<br>(%{x:.3f}, %{y:.3f}, %{z:.3f}) m<extra></extra>' };
    const modelName = state.run?.options?.timing_model === 'grouped' ? 'Grouped fitted ping position' : 'Timestamp-aware fitted ping position';
    const estimateTrace = { type: 'scatter3d', mode: 'markers', name: modelName, x: estimate ? [estimate[0]] : [], y: estimate ? [estimate[1]] : [], z: estimate ? [estimate[2] || 0] : [], marker: { color: '#7458a8', size: 7, symbol: 'x' }, text: [modelName], hovertemplate: '%{text}<br>(%{x:.3f}, %{y:.3f}, %{z:.3f}) m<extra></extra>' };
    if (window.Plotly && scene?.data) {
      const started = performance.now(), pingIndex = state.selectedPing, generation = scene.dataset.generation;
      let action;
      if (state.overlayIndex === null) {
        state.overlayIndex = scene.data?.length || 0;
        const add = () => scene.dataset.generation === generation ? Plotly.addTraces(scene, [rayTrace, actualTrace, groupedTrace, estimateTrace]) : undefined;
        action = state.overlayPromise ? state.overlayPromise.then(add) : add();
      } else {
        const overlayTraces = [rayTrace, actualTrace, groupedTrace, estimateTrace];
        const update = { x: overlayTraces.map(trace => trace.x), y: overlayTraces.map(trace => trace.y), z: overlayTraces.map(trace => trace.z), text: overlayTraces.map(trace => trace.text) };
        const overlayIndex = state.overlayIndex;
        const restyle = () => scene.dataset.generation === generation ? Plotly.restyle(scene, update, [overlayIndex, overlayIndex + 1, overlayIndex + 2, overlayIndex + 3]) : undefined;
        action = state.overlayPromise ? state.overlayPromise.then(restyle) : restyle();
      }
      state.overlayPromise = Promise.resolve(action).catch(error => { if (scene.dataset.generation === generation) toast(`Ping overlay could not render: ${error.message}`); });
      state.overlayPromise.then(() => { if (scene.dataset.generation === generation && state.selectedPing === pingIndex) { scene.dataset.pingIndex = String(pingIndex); scene.dataset.pingRenderMs = (performance.now() - started).toFixed(2); } });
    }
    const assumed = Number(observation.assumed_time_s), actual = Number(observation.actual_time_s), delivery = Number(observation.delivery_time_s);
    const cycleTime = Number(rows(state.run?.experiment?.estimator_input?.times_s)[Number(observation.epoch)]);
    $('m3PingLabel').textContent = `${state.selectedPing + 1} / ${state.pingPoints.length} · B${observation.beacon_id ?? '?'}`;
    $('m3PingDetail').textContent = `Actual tag position (${p.slice(0, 3).map(v => num(v, 3)).join(', ')}) m · actual ${num(actual, 4)} s · assumed ${num(assumed, 4)} s · delivered ${num(delivery, 4)} s · range ${num(observation.range_m, 4)} m · common cycle ${num(cycleTime, 4)} s at (${grouped ? grouped.map(v => num(v, 3)).join(', ') : '—'}) m${beacon ? ` · receiver B${observation.beacon_id} at (${beacon.map(v => num(v, 3)).join(', ')}) m` : ''}`;
    $('m3Prev').disabled = state.selectedPing <= 0; $('m3Next').disabled = state.selectedPing >= state.pingPoints.length - 1;
  }
  function allStartRows(run) {
    return rows(run?.starts).map((start, index) => {
      const d = start.diagnostics || {}, evals = d.evaluation || {};
      const exact = rows(run?.experiment?.config?.noise_std_m).every(value => Number(value) === 0), frame = run?.options?.mode === 'known_map' || exact ? 'raw' : 'aligned';
      const measures = evals[frame] || evals.raw || {};
      return { value: null, model: start.timing_model || run.options?.timing_model || 'timestamp_aware', start_index: start.index ?? index, seed: start.seed ?? run?.options?.seed ?? '—', status: start.status || (start.success ? 'success' : 'failed'), optimizer_converged: d.optimizer_converged ?? start.optimizer_converged ?? start.success ?? start.converged ?? '—', error_frame: frame, position_rmse_m: d.position_rmse_m ?? measures.position_rmse_m, range_rmse_m: d.range_rmse_m ?? d.range_residual_rmse_m ?? measures.range_rmse_m, measurement_rank: d.jacobian?.rank ?? d.measurement_rank, parameter_count: d.jacobian?.parameter_count ?? d.parameter_count, full_column_rank: d.jacobian?.full_column_rank ?? d.measurement_full_column_rank ?? d.full_column_rank, augmented_full_column_rank: d.augmented_jacobian?.full_column_rank ?? d.augmented_full_column_rank, prior_objective: d.prior_objective ?? evals.prior?.objective, measurement_objective: d.measurement_objective ?? measures.objective, interpolation_ping_rmse_m: run?.diagnostics?.truth_interpolation_floor?.ping_position_rmse_m, timing_approximation_position_rmse_m: d.timing_approximation?.position_rmse_m ?? run?.diagnostics?.timing_approximation?.position_rmse_m, start };
    });
  }
  function renderRows(items, onOpen) {
    const target = $('m3AllStarts');
    if (!items.length) { target.innerHTML = '<div class="chart-empty">No start outcomes are available.</div>'; return; }
    const rankLabel = item => item.measurement_rank === null || item.measurement_rank === undefined || item.parameter_count === null || item.parameter_count === undefined ? '—' : `${item.measurement_rank}/${item.parameter_count} · ${item.full_column_rank === true ? 'full' : item.full_column_rank === false ? 'deficient' : 'rank'}`;
    target.innerHTML = `<table class="m2-table"><thead><tr><th>VALUE</th><th>MODEL</th><th>START</th><th>SEED</th><th>STATUS</th><th>CONVERGED</th><th>ERROR FRAME</th><th>POSITION RMSE (M)</th><th>RANGE RMSE (M)</th><th>MEASUREMENT RANK / PARAMETERS</th><th>AUGMENTED FULL RANK</th><th>PRIOR OBJECTIVE</th><th>MEASUREMENT OBJECTIVE</th><th>INTERPOLATION FLOOR (M)</th><th>MODEL TIMING ERROR (M)</th></tr></thead><tbody>${items.map((item, i) => `<tr class="m3-row" data-m3-row="${i}" tabindex="0"><td>${esc(item.value ?? '—')}</td><td>${esc(item.model || item.variant || '—')}</td><td>${esc(item.start_index ?? '—')}</td><td>${esc(item.seed ?? '—')}</td><td>${esc(item.classification || item.status || '—')}</td><td>${esc(item.optimizer_converged ?? item.converged ?? '—')}</td><td>${esc(item.error_frame || '—')}</td><td>${num(item.position_rmse_m)}</td><td>${num(item.range_rmse_m)}</td><td>${esc(rankLabel(item))}</td><td>${esc(item.augmented_full_column_rank ?? '—')}</td><td>${num(item.prior_objective)}</td><td>${num(item.measurement_objective)}</td><td>${num(item.interpolation_ping_rmse_m)}</td><td>${num(item.timing_approximation_position_rmse_m)}</td></tr>`).join('')}</tbody></table>`;
    target.querySelectorAll('[data-m3-row]').forEach(row => { const open = () => onOpen(items[Number(row.dataset.m3Row)]); row.addEventListener('click', open); row.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } }); });
  }
  function disclosure(runOrArtifact) {
    const details = runOrArtifact?.numerical_disclosure || runOrArtifact?.disclosure || runOrArtifact?.diagnostics || {};
    const truth = runOrArtifact?.experiment?.truth || {};
    const config = runOrArtifact?.experiment?.config || {};
    const floor = details.truth_interpolation_floor || runOrArtifact?.run?.diagnostics?.truth_interpolation_floor;
    const timing = details.timing_approximation || runOrArtifact?.run?.diagnostics?.timing_approximation;
    const trajectory = details.trajectory_model || runOrArtifact?.run?.diagnostics?.trajectory_model;
    const noise = config.noise_std_m, exact = Array.isArray(noise) ? noise.length > 0 && noise.every(value => Number(value) === 0) : Number(noise) === 0;
    const frame = runOrArtifact?.artifact_type === 'timing_sweep' ? 'Saved per-run frame: exact-data and known-map use raw coordinates; noisy joint-map runs use proper rigid alignment at scale 1.' : `Position-error frame: ${runOrArtifact?.options?.mode === 'known_map' || exact ? 'raw' : 'proper rigid alignment at scale 1'}; measurement rank is computed from range data alone.`;
    $('m3NumericalDisclosure').innerHTML = `<div class="m3-numeric-disclosure"><b>Numerical interpretation.</b> ${esc(details.convention || details.objective_convention || 'Range fit, trajectory recovery, measurement-only observability, and motion-prior contribution are separate quantities.')} ${esc(frame)} ${floor ? `Piecewise-linear interpolation floor at actual pings: ${esc(num(floor.ping_position_rmse_m))} m (representation discrepancy, not an optimization lower bound).` : ''} ${timing ? `Cycle-start approximation error: ${esc(num(timing.position_rmse_m))} m RMSE.` : ''} ${trajectory ? `Trajectory model: ${esc(trajectory.type || 'piecewise_linear')}, ${esc(trajectory.knot_count)} knots over ${esc(rows(trajectory.domain_s).map(value => num(value, 3)).join('–'))} s; knot rule: ${esc(trajectory.knot_rule || '')}; reference: ${esc(trajectory.grouping_rule || '')}; prior σ=${esc(num(trajectory.prior_sigma_m))} m; prior: ${esc(trajectory.prior_definition || '')}.` : ''} ${config.motion?.profile ? `Truth motion profile: ${esc(config.motion.profile)}.` : ''} ${esc(details.caveat || details.ambiguity || '')}</div>`;
    $('m3NumericalDisclosure').classList.remove('hidden');
  }
  function showRun(run, preserveSweep = false, playbackOnly = false) {
    const previousId = state.run?.id, previousPing = state.selectedPing;
    if (previousId && previousId !== run.id) pausePlayback();
    state.run = run; state.observations = rows(run?.experiment?.estimator_input?.observations || run?.experiment?.observations || run?.observations);
    state.pingPoints = observationsFor(run);
    $('m3PlaybackTitle').textContent = `${run.id ? String(run.id).slice(0, 12) : 'M3 run'} · ${state.pingPoints.length} observed pings`;
    $('m3PingSlider').min = 0; $('m3PingSlider').max = Math.max(0, state.pingPoints.length - 1); $('m3PingSlider').disabled = state.pingPoints.length === 0;
    $('m3Play').disabled = $('m3Pause').disabled = state.pingPoints.length === 0;
    $('m3Prev').disabled = $('m3Next').disabled = state.pingPoints.length === 0;
    state.overlayIndex = null; state.overlayPromise = null;
    renderSpeed(run, state.pingPoints);
    if (!preserveSweep && !playbackOnly) {
      const starts = allStartRows(run);
      renderRows(starts, item => {
        if (item.start?.index !== undefined) window.RangeLab?.setSelectedStart(item.start.index);
        if (item.start && window.RangeLab?.state) window.RangeLab.state.start = item.start;
        const active = window.RangeLab?.state?.activeRun;
        if (active && window.RangeLab?.renderRun) window.RangeLab.renderRun(active);
        else if (active) showRun(active);
      });
    }
    // Keep the sweep's complete all-start table and factor chart visible while
    // replacing the numeric disclosure with the selected model/run details.
    if (!playbackOnly) disclosure(run);
    if (state.pingPoints.length) updatePing(previousId && previousId === run.id ? Math.min(previousPing, state.pingPoints.length - 1) : 0);
  }
  function pausePlayback() { if (state.timer) clearInterval(state.timer); state.timer = null; }
  function clearPlayback() {
    pausePlayback(); state.run = null; state.observations = []; state.pingPoints = []; state.overlayIndex = null; state.overlayPromise = null; state.selectedPing = 0;
    $('m3PlaybackTitle').textContent = 'Open an M3 run to inspect ping timing.'; $('m3PingLabel').textContent = 'No ping selected';
    $('m3PingDetail').textContent = 'The active ping will show its actual position, receiving beacon, measured range and timestamp.';
    $('m3PingSlider').value = 0; $('m3PingSlider').max = 0; $('m3PingSlider').disabled = true;
    $('m3Play').disabled = $('m3Pause').disabled = $('m3Prev').disabled = $('m3Next').disabled = true;
    if (window.Plotly) Plotly.purge($('m3SpeedChart'));
    $('m3SpeedChart').innerHTML = '<div class="chart-empty">Motion speed and ping events will appear here.</div>';
    $('m3AllStarts').innerHTML = '<div class="chart-empty">Run an M3 experiment or open a saved timing sweep.</div>';
    $('m3NumericalDisclosure').textContent = ''; $('m3NumericalDisclosure').classList.add('hidden');
  }
  function clearSweepView() {
    state.activeSweep = null; state.inspectingSweepRunId = null;
    $('m3ExportJson').disabled = $('m3ExportCsv').disabled = $('m3ExportChart').disabled = true;
    if (window.Plotly) Plotly.purge($('m3SweepChart'));
    $('m3SweepChart').innerHTML = '<div class="chart-empty">Open a saved timing sweep to compare models.</div>';
  }
  async function pollRun(id) {
    for (let i = 0; i < 3600; i++) {
      const job = await api(`/api/jobs/${encodeURIComponent(id)}`);
      if (job.status === 'complete' || job.status === 'failed') {
        const run = job.run || await api(`/api/runs/${encodeURIComponent(id)}`); run.id ||= id; run.status ||= job.status;
        if (window.RangeLab) { window.RangeLab.state.activeRun = run; window.RangeLab.state.selectedStart = null; window.RangeLab.renderRun(run); }
        else showRun(run);
        await refreshRuns(id);
        toast(job.status === 'complete' ? 'M3 run complete.' : 'M3 run finished with a failure.');
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    toast('M3 job is still running.');
  }
  async function runM3(event) {
    event.preventDefault(); let config;
    try { config = controls(); } catch (error) { return toast(error.message); }
    clearSweepView();
    const submit = $('m3RunButton'); submit.disabled = true;
    try {
      const created = await api('/api/m3/runs', { method: 'POST', body: JSON.stringify({ config, options: options() }) });
      if (!created.id) throw new Error('The M3 run response did not include a job id.');
      toast('M3 run queued.'); await refreshRuns(created.id); await pollRun(created.id);
    } catch (error) { toast(`Could not run M3: ${error.message}`); }
    finally { submit.disabled = false; }
  }
  async function refreshRuns() { window.RangeLabLibrary?.invalidate(); }
  async function openRun(id) {
    try {
      const run = await api(`/api/runs/${encodeURIComponent(id)}`); run.id ||= id;
      clearSweepView();
      restoreControls(run);
      if (window.RangeLab) { window.RangeLab.state.activeRun = run; window.RangeLab.state.selectedStart = null; window.RangeLab.renderRun(run); }
      else showRun(run);
      await refreshRuns(id);
    } catch (error) { toast(`Could not open M3 run: ${error.message}`); }
  }
  function restoreControls(run) {
    const config = run?.experiment?.config || {}, motion = config.motion || {}, acquisition = config.acquisition || {}, options = run?.options || {};
    $('m3MaxNfev').value = options.max_nfev || 2000;
    const set = (id, value) => { if (value !== undefined && value !== null && $(id)) $(id).value = value; };
    set('scenario', config.scenario); set('samples', config.samples); set('duration', config.duration_s); set('seed', config.seed);
    const noise = Array.isArray(config.noise_std_m) ? config.noise_std_m : [config.noise_std_m], sigma = Array.isArray(config.assumed_std_m) ? config.assumed_std_m : [config.assumed_std_m];
    const noiseValue = noise.length ? noise[0] : undefined, sigmaValue = sigma.length ? sigma[0] : undefined;
    set('noise', noiseValue); set('sigma', sigmaValue);
    state.restoredNoise = noise.length > 1 ? { values: noise, input: Number(noiseValue) } : null;
    state.restoredAssumedSigma = sigma.length > 1 ? { values: sigma, input: Number(sigmaValue) } : null;
    set('mode', options.mode); set('init', options.initialization); set('starts', options.starts); set('initSeed', options.seed);
    set('m3Motion', motion.profile); set('m3Speed', motion.speed_scale); set('m3CycleRate', acquisition.cycle_rate_hz); set('m3PingSpacing', acquisition.spacing_s); set('m3AcqJitter', acquisition.jitter_s);
    set('m3Order', Array.isArray(acquisition.beacon_order) ? acquisition.beacon_order.join(',') : undefined); set('m3Strides', Array.isArray(acquisition.beacon_every_cycles) ? acquisition.beacon_every_cycles.join(',') : undefined);
    set('m3TimestampOffset', acquisition.timestamp_offset_s); set('m3TimestampJitter', acquisition.timestamp_jitter_s); set('m3Latency', acquisition.delivery_latency_s); set('m3Missing', acquisition.missing_probability);
    set('m3TimingModel', options.timing_model); set('m3KnotSpacing', options.knot_spacing_s); set('m3PriorSigma', options.prior_sigma_m);
    if (config.path) {
      $('usePath').checked = true; $('pathType').value = config.path.type || 'line';
      set('pathCenterX', config.path.center_m?.[0]); set('pathCenterY', config.path.center_m?.[1]); set('pathWidth', config.path.size_m?.[0]); set('pathHeight', config.path.size_m?.[1]); set('pathScale', config.path.scale); set('pathRotation', config.path.rotation_deg);
      set('arcStart', config.path.start_angle_deg); set('arcSweep', config.path.arc_angle_deg);
      if (config.path.waypoints_m) set('waypoints', config.path.waypoints_m.map(point => point.join(',')).join('\n'));
      $('usePath').dispatchEvent(new Event('change')); $('pathType').dispatchEvent(new Event('change'));
    } else { $('usePath').checked = false; $('usePath').dispatchEvent(new Event('change')); }
  }
  function exportConfig() {
    try { download('uwb-m3-experiment-config.json', 'application/json', JSON.stringify({ schema_version: '3.0', artifact_type: 'experiment_config', config: controls(), options: options() }, null, 2)); }
    catch (error) { toast(error.message); }
  }
  function summarizeArtifact(artifact) {
    const entries = rows(artifact.entries), result = [];
    if (rows(artifact.start_table).length) {
      for (const row of artifact.start_table) result.push(row);
    } else for (const entry of entries) for (const model of ['timestamp_aware', 'grouped']) {
      const run = entry[model] || entry.runs?.[model] || entry.run?.[model];
      for (const item of allStartRows(run)) result.push({ ...item, value: entry.value, model, entry_index: entry.index, run_id: run?.id });
    }
    return result;
  }
  function renderArtifact(artifact) {
    state.activeSweep = artifact;
    state.inspectingSweepRunId = null;
    renderSweepChart(artifact);
    const items = summarizeArtifact(artifact);
    renderRows(items, item => {
      const entry = rows(artifact.entries).find(e => e.index === item.entry_index) || artifact.entries?.[Number(item.entry_index)];
      const run = entry?.run || entry?.runs?.[item.model] || entry?.[item.model] || entry?.runs?.timestamp_aware || entry?.timestamp_aware;
      if (run?.experiment) {
        run.id ||= item.run_id || entry.run_id;
        state.inspectingSweepRunId = run.id;
        if (window.RangeLab) { window.RangeLab.state.activeRun = run; window.RangeLab.state.selectedStart = item.start_index; window.RangeLab.renderRun(run); }
        else showRun(run, true);
      } else toast('This sweep start does not contain a retained run.');
    });
    const info = artifact.numerical_disclosure || artifact.disclosure || {};
    $('m3NumericalDisclosure').innerHTML = `<div class="m3-numeric-disclosure"><b>Sweep disclosure.</b> ${esc(info.convention || artifact.aggregation_convention || 'Each attempted start is retained, including failures. Position, range fit, measurement observability and motion-prior contribution are separate.')} ${esc(info.caveat || artifact.recovery_note || '')}</div>`;
    $('m3NumericalDisclosure').classList.remove('hidden');
    $('m3ExportJson').disabled = false; $('m3ExportCsv').disabled = !items.length;
  }
  function renderSweepChart(artifact) {
    const target = $('m3SweepChart'), aggregates = rows(artifact?.aggregates), values = rows(artifact?.config?.values);
    const factor = artifact?.config?.factor || 'factor';
    const factorLabels = { spacing_s: 'Ping spacing (s)', speed_scale: 'Speed scale', knot_spacing_s: 'Knot spacing (s)', timestamp_offset_s: 'Timestamp offset (s)', timestamp_jitter_s: 'Timestamp jitter (s)', missing_probability: 'Missing probability', beacon_every_cycles: 'Beacon 3 cycle stride' };
    $('m3SweepChartLabel').textContent = 'Median saved all-start display-trajectory RMSE · raw for exact/known-map; noisy joint rigid-aligned at scale 1';
    const colors = { timestamp_aware: '#0b817b', grouped: '#e88569' };
    const traces = ['timestamp_aware', 'grouped'].map(model => {
      const subset = values.map((value, vi) => {
        const summary = aggregates.find(item => item.model === model && (item.value_index === vi || item.value === value));
        return { value, summary, dist: summary?.all_start_position_rmse_m };
      });
      return { x: subset.map(item => item.value), y: subset.map(item => item.dist?.median ?? null), type: 'scatter', mode: 'lines+markers', name: model === 'timestamp_aware' ? 'Timestamp aware' : 'Cycle-start grouped', line: { color: colors[model], width: 2 }, marker: { size: 7 }, customdata: subset.map(item => [item.dist?.count ?? '', item.summary?.run_count ?? '']), hovertemplate: `${esc(factorLabels[factor] || factor)}=%{x}<br>median position RMSE=%{y:.4f} m<br>finite starts=%{customdata[0]}<br>runs=%{customdata[1]}<extra>%{fullData.name}</extra>` };
    });
    const hasData = traces.some(trace => trace.y.some(value => Number.isFinite(value)));
    $('m3ExportChart').disabled = !hasData;
    if (!window.Plotly || !hasData) {
      if (window.Plotly) Plotly.purge(target);
      target.innerHTML = '<div class="chart-empty">No finite aggregate position errors are available to plot; start outcomes remain listed below.</div>';
      return;
    }
    target.querySelectorAll('.chart-empty').forEach(node => node.remove());
    const started = performance.now();
    Plotly.react(target, traces, { margin: { l: 55, r: 12, t: 12, b: 44 }, paper_bgcolor: '#fff', plot_bgcolor: '#fff', font: { size: 9, color: '#607475' }, xaxis: { title: { text: factorLabels[factor] || factor }, gridcolor: '#edf0f0' }, yaxis: { title: { text: 'Median display-trajectory RMSE (m)' }, rangemode: 'tozero', gridcolor: '#edf0f0' }, legend: { orientation: 'h', y: 1.16 }, hovermode: 'x unified', uirevision: 'm3-sweep-chart' }, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ['toImage', 'sendDataToCloud', 'sendChartToCloud'] }).then(() => { target.dataset.renderMs = (performance.now() - started).toFixed(2); });
  }
  async function refreshSweeps() { window.RangeLabLibrary?.invalidate(); }
  async function openSweep(id) {
    try { const response = await api(`/api/m3/sweeps/${encodeURIComponent(id)}`); const artifact = response.artifact || response; renderArtifact(artifact); await refreshSweeps(id); }
    catch (error) { toast(`Could not open timing sweep: ${error.message}`); }
  }
  async function createSweep(event) {
    event.preventDefault(); let config, values, seeds;
    try { config = controls(); values = list($('m3SweepValues').value); seeds = list($('m3SweepSeeds').value, true); }
    catch (error) { return toast(error.message); }
    if (!values.length || !seeds.length || seeds.some(value => value < 0)) return toast('Provide values and nonnegative integer seeds.');
    const body = { base_experiment: config, options: options(), factor: $('m3SweepFactor').value, values, seeds };
    try {
      const created = await api('/api/m3/sweeps', { method: 'POST', body: JSON.stringify(body) });
      if (!created.id) throw new Error('Sweep response did not include a job id.');
      toast('Paired timing sweep queued.'); await refreshSweeps(created.id);
      let polls = 0;
      const timer = setInterval(async () => {
        try {
          const job = await api(`/api/jobs/${encodeURIComponent(created.id)}`); polls++;
          if (job.status === 'complete' || job.status === 'failed') { clearInterval(timer); await openSweep(created.id); await refreshRuns(); toast(job.status === 'complete' ? 'Timing sweep complete.' : 'Timing sweep stopped with an error.'); }
          else if (polls > 3600) clearInterval(timer);
        } catch (error) { clearInterval(timer); toast(`Sweep status unavailable: ${error.message}`); }
      }, 1000);
    } catch (error) { toast(`Could not start timing sweep: ${error.message}`); }
  }
  function download(filename, type, text) { const url = URL.createObjectURL(new Blob([text], { type })), link = document.createElement('a'); link.href = url; link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
  function exportCsv() {
    if (!state.activeSweep) return;
    const items = summarizeArtifact(state.activeSweep), keys = [...new Set(items.flatMap(item => Object.keys(item)))], csv = value => `"${String(value ?? '').replace(/"/g, '""')}"`;
    download(`m3-sweep-${state.activeSweep.id || 'saved'}.csv`, 'text/csv', [keys.map(csv).join(','), ...items.map(item => keys.map(key => csv(typeof item[key] === 'object' ? JSON.stringify(item[key]) : item[key])).join(','))].join('\n'));
  }
  function exportSweepChart() {
    if ($('m3SweepChart')?.data && window.Plotly) Plotly.downloadImage($('m3SweepChart'), { format: 'png', filename: `m3-sweep-${state.activeSweep?.id || 'aggregate'}`, width: 1400, height: 700, scale: 1 });
  }
  async function importArtifact(file) {
    if (!file) return;
    try {
      const artifact = JSON.parse(await file.text());
      const response = await api('/api/m3/import', { method: 'POST', body: JSON.stringify(artifact) });
      if (response.run) {
        const run = response.run; run.id ||= response.id;
        clearSweepView();
        restoreControls(run);
        if (window.RangeLab) { window.RangeLab.state.activeRun = run; window.RangeLab.state.selectedStart = null; window.RangeLab.renderRun(run); }
        else showRun(run);
        await refreshRuns(run.id); toast('M3 run imported and saved.'); return;
      }
      const saved = response.artifact || response;
      if (saved.entries || saved.start_table) { renderArtifact(saved); await refreshSweeps(saved.id); }
      else await refreshSweeps(response.id);
      toast('M3 artifact imported.');
    } catch (error) { toast(`Could not import M3 artifact: ${error.message}`); }
    finally { $('m3ImportFile').value = ''; }
  }
  function init() {
    $('m3Form').addEventListener('submit', runM3); $('m3SweepForm').addEventListener('submit', createSweep);
    $('m3PingSlider').addEventListener('input', event => updatePing(event.target.value));
    $('m3Prev').addEventListener('click', () => updatePing(state.selectedPing - 1)); $('m3Next').addEventListener('click', () => updatePing(state.selectedPing + 1));
    $('m3Play').addEventListener('click', () => { pausePlayback(); state.timer = setInterval(() => { if (state.selectedPing >= state.pingPoints.length - 1) pausePlayback(); else updatePing(state.selectedPing + 1); }, 350); });
    $('m3Pause').addEventListener('click', pausePlayback);
    $('m3ImportButton').addEventListener('click', () => $('m3ImportFile').click()); $('m3ImportFile').addEventListener('change', event => importArtifact(event.target.files?.[0]));
    $('m3ExportConfig').addEventListener('click', exportConfig);
    $('m3ExportCsv').addEventListener('click', exportCsv); $('m3ExportChart').addEventListener('click', exportSweepChart); $('m3ExportJson').addEventListener('click', () => { if (state.activeSweep) download(`m3-sweep-${state.activeSweep.id || 'saved'}.json`, 'application/json', JSON.stringify(state.activeSweep, null, 2)); });
    refreshRuns(); refreshSweeps();
  }
  window.RangeLabM3 = { restoreRun:restoreControls, openArtifact: renderArtifact, pausePlayback, playbackState() { return { paused: !state.timer, selectedPing: state.selectedPing }; }, formConfig: controls, formOptions: options, restoreConfig(config, opts) {
    const legacy = JSON.parse(JSON.stringify(config));
    legacy.acquisition = {...legacy.acquisition, beacon_order:[0,1,2,3], beacon_every_cycles:[1,1,1,1]};
    for (const key of ['noise_std_m','assumed_std_m']) if (Array.isArray(legacy[key]) && legacy[key].length !== 4) legacy[key] = legacy[key][0];
    restoreControls({experiment:{config:legacy},options:{...opts,initialization:opts?.initialization === "algebraic" ? "independent" : opts?.initialization}});
  }, onRun(run) {
    if (['4.0','5.0','6.0','7.0'].includes(run?.schema_version)) { showRun(run, false, true); return; }
    if (run && (run.schema_version === '3.0' || run.experiment?.config?.acquisition)) {
      const preserveSweep = Boolean(state.activeSweep && run.id && run.id === state.inspectingSweepRunId);
      if (!preserveSweep) clearSweepView();
      showRun(run, preserveSweep);
    } else { clearSweepView(); clearPlayback(); }
  }, refresh() { refreshRuns(); refreshSweeps(); }, openRun, openSweep };
  document.addEventListener('DOMContentLoaded', init);
})();
