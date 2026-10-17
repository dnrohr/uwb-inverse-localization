(() => {
  'use strict';
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const state = { runs: [], activeRun: null, selectedStart: null, camera: null, pollTimer: null, toastTimer: null, sceneTraces: [], truth: null, start: null, runMeta: null };
  const colors = { teal: '#0b817b', coral: '#e88569', amber: '#bc8740', purple: '#7458a8', grid: '#e5ebea', text: '#829293' };

  const api = async (url, options = {}) => {
    const response = await fetch(url, { headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers }, ...options });
    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`;
      try { const payload = await response.json(); message = payload.error || payload.message || message; } catch (_) { /* response may be text */ }
      throw new Error(message);
    }
    return response.json();
  };
  const toRows = value => Array.isArray(value) ? value : [];
  const xyz = value => Array.isArray(value) && value.length >= 3 && value.slice(0, 3).every(Number.isFinite) ? value.slice(0, 3) : null;
  const points = value => toRows(value).map(xyz).filter(Boolean);
  function transformPoint(p, alignment) {
    if (!alignment?.applied) return p.slice();
    if (Array.isArray(alignment.rotation_xyz) && Array.isArray(alignment.translation_xyz_m)) {
      return [0, 1, 2].map(j => p.reduce((sum, value, i) => sum + value * alignment.rotation_xyz[i][j], 0) + alignment.translation_xyz_m[j]);
    }
    const r = alignment.rotation_xy, t = alignment.translation_xy_m;
    if (!r || !t) return p.slice();
    return [p[0]*r[0][0]+p[1]*r[1][0]+t[0], p[0]*r[0][1]+p[1]*r[1][1]+t[1], p[2]+(alignment.gauge_translation_z_m || 0)];
  }
  const number = value => value === null || value === undefined || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);
  const fmt = (value, digits = 4) => Number.isFinite(value) ? (value !== 0 && Math.abs(value) < 10 ** (-digits) ? value.toExponential(2) : value.toFixed(digits)) : '—';
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  function showToast(message) {
    const toast = $('#toast'); toast.textContent = message; toast.classList.add('visible');
    clearTimeout(state.toastTimer); state.toastTimer = setTimeout(() => toast.classList.remove('visible'), 2800);
  }
  function setStatus(status, label) {
    const node = $('#runStatus');
    const kind = status === 'complete' ? 'complete' : status === 'failed' ? 'failed' : status === 'running' ? 'running' : 'idle';
    node.className = `status-pill status-${kind}`;
    node.innerHTML = `<span class="status-dot"></span><span>${escapeHtml(label || (status === 'complete' ? 'Run complete' : status === 'failed' ? 'Run failed' : status === 'running' ? 'Solving…' : 'Waiting for run'))}</span>`;
  }
  function scenarioLabel(id) {
    return ({ informative: 'Informative motion', straight_line: 'Straight line', narrow_coverage: 'Narrow coverage', nearly_collinear: 'Nearly collinear beacons' })[id] || String(id || 'Experiment');
  }
  function pathLabel(type) { return type ? `${String(type).replace(/_/g, ' ').replace(/\b\w/g, char => char.toUpperCase())} path` : null; }
  function runLabel(run) { const customPath = pathLabel(run.path_type || run.experiment?.config?.path?.type); return `${run.reference_name ? `${String(run.reference_name).replace(/_/g, ' ')} · ` : ''}${customPath || scenarioLabel(run.scenario)} · ${run.mode === 'known_map' ? 'Known map' : 'Joint map'}`; }

  async function refreshRuns() { window.RangeLabLibrary?.invalidate(); }
  function renderRuns() { window.RangeLabLibrary?.activeResult(state.activeRun); }
  async function startRun(event) {
    event.preventDefault();
    const submit = $('#runButton');
    let config;
    try { config = window.RangeLabM2.formConfig(); }
    catch (error) { showToast(error.message); return; }
    const options = { mode: $('#mode').value, initialization: $('#init').value, starts: +$('#starts').value, seed: +$('#initSeed').value };
    submit.disabled = true; submit.innerHTML = '<span>◌</span> Starting…'; setStatus('running', 'Submitting run');
    try {
      const result = await api('/api/runs', { method: 'POST', body: JSON.stringify({ config, options }) });
      const id = result.id || result.run_id;
      if (!id) throw new Error('Run was accepted but no identifier was returned.');
      const placeholder = { id, status: 'running', scenario: config.scenario, mode: options.mode };
      state.runs = [placeholder, ...state.runs.filter(item => item.id !== id)]; renderRuns(id);
      setStatus('running', 'Solver running'); $('#sceneSubtitle').textContent = `Solving ${scenarioLabel(config.scenario)} · ${options.mode === 'known_map' ? 'Known map' : 'Joint map'} · ${state.activeRun ? 'previous result remains visible until completion' : 'awaiting fitted geometry'}`;
      if (state.pollTimer) clearInterval(state.pollTimer);
      let polls = 0;
      state.pollTimer = setInterval(async () => {
        polls++;
        try {
          const job = await api(`/api/jobs/${encodeURIComponent(id)}`);
          if (job.status === 'complete') {
            clearInterval(state.pollTimer); state.pollTimer = null;
            let run = job.run || await api(`/api/runs/${encodeURIComponent(id)}`); run.id ||= id; run.status ||= 'complete';
            try { state.activeRun = run; state.selectedStart = null; await refreshRuns(id); renderRun(run); }
            catch (renderError) { console.error('Run display failed:', renderError); showToast(`Run saved, but display failed: ${renderError.message}`); }
            submit.disabled = false; submit.innerHTML = '<span>▶</span> Run estimator';
          } else if (job.status === 'failed') {
            clearInterval(state.pollTimer); state.pollTimer = null;
            let failedRun = job.run;
            if (!failedRun) { try { failedRun = await api(`/api/runs/${encodeURIComponent(id)}`); } catch (_) { /* keep the job failure summary */ } }
            state.activeRun = failedRun ? { ...failedRun, id: failedRun.id || id, status: failedRun.status || 'failed', error: job.error || failedRun.error } : { ...placeholder, status: 'failed', error: job.error };
            state.selectedStart = null; await refreshRuns(id); renderRun(state.activeRun); submit.disabled = false; submit.innerHTML = '<span>▶</span> Run estimator';
          } else { setStatus('running', polls % 4 === 0 ? 'Solver still running' : 'Solver running'); }
          if (polls > 1800) { clearInterval(state.pollTimer); state.pollTimer = null; setStatus('running', 'Polling paused · run continues'); submit.disabled = false; submit.innerHTML = '<span>▶</span> Run estimator'; }
        } catch (error) { clearInterval(state.pollTimer); state.pollTimer = null; submit.disabled = false; submit.innerHTML = '<span>▶</span> Run estimator'; setStatus('failed', 'Could not read job status'); showToast(error.message); }
      }, 1000);
    } catch (error) { setStatus('failed', 'Run could not start'); submit.disabled = false; submit.innerHTML = '<span>▶</span> Run estimator'; showToast(error.message); }
  }

  async function loadRun(id) {
    try {
      if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
      $('#runButton').disabled = false; $('#runButton').innerHTML = '<span>▶</span> Run estimator';
      const run = await api(`/api/runs/${encodeURIComponent(id)}`); run.id ||= id; state.activeRun = run; state.selectedStart = null;
      renderRun(run); renderRuns(id);
    } catch (error) { showToast(`Could not open saved run: ${error.message}`); }
  }

  function pickStart(run, selected = null) {
    const starts = toRows(run && run.starts);
    if (!starts.length) return null;
    if (selected !== null && selected !== undefined) return starts.find(start => String(start.index) === String(selected)) || starts[0];
    const preferred = run.selected_start;
    return starts.find(start => String(start.index) === String(preferred)) || starts.find(start => start.success || start.status === 'complete') || starts[0];
  }
  function renderRun(run) {
    if (!run) return;
    window.RangeLabLibrary?.activeResult(run);
    state.activeRun = run; state.truth = run.experiment && run.experiment.truth || {};
    state.selectedStart = state.selectedStart ?? (pickStart(run) && pickStart(run).index);
    state.start = pickStart(run, state.selectedStart); state.runMeta = run;
    const rawStatus = run.status || 'complete';
    const status = rawStatus === 'success' || rawStatus === 'not_converged' ? 'complete' : rawStatus;
    const initLabel = run.options?.initialization === 'truth_near' ? 'Truth-near diagnostic' : run.options?.initialization === 'algebraic' ? 'Algebraic initialization · measurement only' : 'Independent initialization';
    setStatus(status, status === 'complete' ? `${rawStatus === 'success' ? 'Converged' : rawStatus === 'not_converged' ? 'Not converged' : 'Run complete'} · ${initLabel}` : status === 'failed' ? 'Run failed · outcome retained' : 'Run running');
    const mode = run.options && run.options.mode || run.mode || 'joint';
    const scenario = run.experiment && run.experiment.config && run.experiment.config.scenario || run.scenario || '';
    $('#sceneSubtitle').textContent = `${scenarioLabel(scenario)} · ${mode === 'known_map' ? 'Known surveyed map' : 'Joint map · raw frame'} · ${initLabel} · ${toRows(run.starts).length || 0} start${toRows(run.starts).length === 1 ? '' : 's'}`;
    const warningList = toRows(run.diagnostics && run.diagnostics.warnings);
    const warningBanner = $('#warningBanner');
    warningBanner.innerHTML = warningList.length ? `<strong>Run warnings:</strong> ${warningList.map(escapeHtml).join(' · ')}` : '';
    warningBanner.classList.toggle('hidden', !warningList.length);
    updateExport(run);
    $('#pngButton').disabled = !window.Plotly || !$('#scene').data;
    drawScene(run, state.start); drawMetrics(run, state.start); drawCharts(run, state.start); drawDiagnostics(run, state.start);
    window.RangeLabM7?.onRun(run, state.start);
    window.RangeLabWorkspace?.onRun(run);
  }

  function updateExport(run) {
    const link = $('#exportLink');
    if (!run || !run.experiment) { link.classList.add('disabled'); link.setAttribute('aria-disabled', 'true'); link.removeAttribute('href'); return; }
    const blob = new Blob([JSON.stringify(run, null, 2)], { type: 'application/json' });
    if (link.dataset.objectUrl) URL.revokeObjectURL(link.dataset.objectUrl);
    const url = URL.createObjectURL(blob); link.dataset.objectUrl = url; link.href = url; link.download = `uwb-${String(run.id || 'run').replace(/[^\w.-]/g, '_')}.json`; link.classList.remove('disabled'); link.setAttribute('aria-disabled', 'false');
  }

  function arrAttr(obj, names) {
    for (const name of names) { if (obj && obj[name] !== undefined && obj[name] !== null) return obj[name]; }
    return null;
  }
  function computePositionErrors(run, start, alignChoice = false) {
    const truth = run.experiment && run.experiment.truth || {};
    const t = points(truth.trajectory);
    const times = toRows(truth.times_s);
    const estimates = points(start && start.estimate && start.estimate.trajectory);
    const diags = start && start.diagnostics || {};
    const evalData = diags.evaluation || {};
    const selectedEvaluation = alignChoice ? evalData.aligned || {} : evalData.raw || {};
    const direct = arrAttr(diags, ['position_errors_m', 'trajectory_errors_m', 'position_error_m', 'trajectory_error_m']) ?? arrAttr(selectedEvaluation, ['position_errors_m']);
    if (Array.isArray(direct)) return { values: direct.map(number), times: times.length === direct.length ? times : direct.map((_, i) => i), label: 'reported' };
    if (direct && typeof direct === 'object') {
      const value = arrAttr(direct, ['values_m', 'errors_m', 'values', 'errors']); const timeValues = arrAttr(direct, ['times_s', 'times']);
      if (Array.isArray(value)) return { values: value.map(number), times: Array.isArray(timeValues) ? timeValues : value.map((_, i) => i), label: 'reported' };
      const rmse = number(direct.position_rmse_m);
      if (rmse !== null) return { aggregateRmse: rmse, times, values: [], label: 'reported RMSE only' };
    }
    const alignedData = evalData.aligned || {};
    const aligned = points(alignedData.aligned_geometry && alignedData.aligned_geometry.trajectory) || [];
    const compare = alignChoice && aligned.length === t.length ? aligned : estimates;
    if (t.length && compare.length === t.length) return { values: t.map((p, i) => Math.hypot(...p.map((v, axis) => v - compare[i][axis]))), times: times.length === t.length ? times : t.map((_, i) => i), label: alignChoice ? 'aligned' : 'raw coordinate difference' };
    return null;
  }
  function computeMapErrors(run, start) {
    const truth = points(run.experiment && run.experiment.truth && run.experiment.truth.beacons);
    const estimate = points(start && start.estimate && start.estimate.beacons);
    const evalData = start && start.diagnostics && start.diagnostics.evaluation || {};
    const selectedEvaluation = $('#coordinateMode').value === 'aligned' ? evalData.aligned || {} : evalData.raw || {};
    const direct = arrAttr(start && start.diagnostics || {}, ['beacon_errors_m', 'map_errors_m', 'beacon_error_m']) ?? arrAttr(selectedEvaluation, ['beacon_errors_m']);
    if (Array.isArray(direct)) return direct.map((value, i) => ({ id: i, value: number(value) }));
    if (direct && typeof direct === 'object') {
      const values = arrAttr(direct, ['values_m', 'errors_m', 'values']);
      if (Array.isArray(values)) return values.map((value, i) => ({ id: i, value: number(value) }));
    }
    const mapDiagnostics = selectedEvaluation.beacon_errors_m;
    if (mapDiagnostics && typeof mapDiagnostics === 'object' && !Array.isArray(mapDiagnostics)) {
      const values = arrAttr(mapDiagnostics, ['values_m', 'errors_m', 'values']);
      if (Array.isArray(values)) return values.map((value, i) => ({ id: i, value: number(value) }));
    }
    if (truth.length && estimate.length === truth.length && $('#coordinateMode').value !== 'aligned') return truth.map((p, i) => ({ id: i, value: Math.hypot(...p.map((v, axis) => v - estimate[i][axis])) }));
    return null;
  }
  function measurementResiduals(run, start) {
    const experiment = run.experiment || {}; const truth = experiment.truth || {}; const input = experiment.estimator_input || {};
    const observations = toRows(input.observations);
    const diagnostic = start && start.diagnostics || {};
    const direct = arrAttr(diagnostic, ['residuals_m', 'range_residuals_m', 'signed_residuals_m']);
    if (Array.isArray(direct)) return { values: direct.map(number).filter(v => v !== null), source: 'reported' };
    if (Array.isArray(diagnostic.residuals_normalized)) {
      const inputRows = toRows(input.observations);
      const sigmas = inputRows.map(row => number(row.sigma_m));
      return { values: diagnostic.residuals_normalized.map((value, index) => { const normalized = number(value); const sigma = sigmas[index]; return normalized !== null && sigma !== null ? normalized * sigma : normalized; }).filter(v => v !== null), source: 'reported normalized × σ' };
    }
    if (observations.length) {
      const trajectory = points(start && start.estimate && start.estimate.trajectory);
      const beacons = points(start && start.estimate && start.estimate.beacons);
      const truthTrajectory = points(truth.trajectory); const truthBeacons = points(truth.beacons);
      const knownMap = ((run.options && run.options.mode) || run.mode) === 'known_map';
      const map = knownMap ? truthBeacons : beacons;
      const times = toRows(input.times_s); const trajectoryTimes = toRows(start && start.estimate && start.estimate.times_s || truth.times_s);
      const signed = [];
      for (const obs of observations) {
        const epoch = number(obs.epoch); const beaconId = number(obs.beacon_id); const range = number(obs.range_m);
        if (epoch === null || beaconId === null || range === null || epoch < 0 || beaconId < 0) continue;
        const pointIndex = epoch;
        const point = trajectory[pointIndex]; const beacon = map[beaconId] || map[beaconId - 1];
        if (point && beacon) signed.push(Math.hypot(...point.map((v, axis) => v - beacon[axis])) - range);
      }
      if (signed.length) return { values: signed, source: 'computed from fit' };
    }
    return null;
  }
  function residualRecords(run, start) {
    const experiment = run.experiment || {}; const input = experiment.estimator_input || {}; const truth = experiment.truth || {};
    const observations = toRows(input.observations); const trajectory = points(start && start.estimate && start.estimate.trajectory);
    const mode = ((run.options && run.options.mode) || run.mode) === 'known_map' ? 'known_map' : 'joint';
    const beacons = mode === 'known_map' ? points(truth.beacons) : points(start && start.estimate && start.estimate.beacons);
    const observationTimes = toRows(input.times_s); const trajectoryTimes = toRows(start && start.estimate && start.estimate.times_s || truth.times_s);
    const direct = start && start.diagnostics && start.diagnostics.residuals_m;
    const normalized = start && start.diagnostics && start.diagnostics.residuals_normalized;
    return observations.map((observation, index) => {
      const epoch = number(observation.epoch), beaconId = number(observation.beacon_id), observed = number(observation.range_m);
      if (epoch === null || beaconId === null || observed === null) return null;
      const point = trajectory[epoch], beacon = beacons[beaconId] || beacons[beaconId - 1];
      const predicted = point && beacon ? Math.hypot(...point.map((v, axis) => v - beacon[axis])) : null;
      const residual = Array.isArray(direct) ? number(direct[index]) : predicted === null ? null : predicted - observed;
      const sigma = number(observation.sigma_m);
      const nres = Array.isArray(normalized) ? number(normalized[index]) : (residual !== null && sigma ? residual / sigma : null);
      const time = number(observation.time_s) ?? number(observation.timestamp_s) ?? number(observation.assumed_time_s) ?? number(observationTimes[index]) ?? number(trajectoryTimes[epoch]) ?? epoch;
      return { epoch, beaconId, residual, normalized: nres, time };
    }).filter(Boolean);
  }
  function scalarDiagnostics(run, start) {
    const root = run.diagnostics || {}; const d = start && start.diagnostics || {};
    const solver = start && start.solver || {};
    const jac = d.jacobian || {};
    const rank = arrAttr(d, ['jacobian_rank', 'rank']) ?? arrAttr(jac, ['rank']) ?? arrAttr(root, ['jacobian_rank', 'rank']);
    const params = arrAttr(d, ['parameter_count', 'n_parameters']) ?? arrAttr(jac, ['parameter_count']) ?? arrAttr(root, ['parameter_count', 'n_parameters']);
    const singular = arrAttr(d, ['singular_values_scaled', 'scaled_singular_values', 'singular_values']) ?? arrAttr(jac, ['singular_values_scaled', 'scaled_singular_values', 'singular_values']) ?? arrAttr(jac, ['singular_values']) ?? arrAttr(root, ['singular_values_scaled', 'scaled_singular_values', 'singular_values']);
    const evalData = d.evaluation || {}; const rawEval = evalData.raw || {};
    const pos = arrAttr(d, ['trajectory_rmse_m', 'position_rmse_m', 'trajectory_error_rmse_m']) ?? arrAttr(rawEval, ['position_rmse_m']) ?? arrAttr(evalData.aligned || {}, ['position_rmse_m']) ?? arrAttr(root, ['trajectory_rmse_m', 'position_rmse_m']);
    const map = arrAttr(d, ['map_rmse_m', 'beacon_rmse_m']) ?? arrAttr(rawEval, ['map_rmse_m']) ?? arrAttr(evalData.aligned || {}, ['map_rmse_m']) ?? arrAttr(root, ['map_rmse_m', 'beacon_rmse_m']);
    const res = arrAttr(d, ['range_rmse_m', 'residual_rmse_m', 'range_residual_rmse_m']) ?? arrAttr(root, ['range_rmse_m', 'residual_rmse_m', 'range_residual_rmse_m']) ?? arrAttr(solver, ['residual_rmse_m']);
    const solverData = { ...solver, ...(start && start.diagnostics && start.diagnostics.solver || {}) };
    return { rank: number(rank), params: number(params), singular: Array.isArray(singular) ? singular.map(number).filter(x => x !== null) : null, pos: number(pos), map: number(map), residual: number(res), solver: solverData, root, d, jac };
  }
  function showMetricCards(values) {
    const cards = $$('.metric-card', $('#metrics'));
    const data = [values.pos, values.map, values.residual, values.rank];
    const labels = [values.posLabel || 'Matched samples · reported alignment', values.mapLabel || 'Estimated beacons', values.residualLabel || 'Predicted minus observed', 'Measurement-only · scaled'];
    cards.forEach((card, i) => {
      const value = data[i]; const numeric = typeof value === 'number' && Number.isFinite(value);
      $('.metric-value', card).innerHTML = `${numeric ? (i === 3 ? escapeHtml(String(value)) : fmt(value)) : '—'}${i < 3 ? ' <small>m</small>' : ''}`;
      $('.metric-foot', card).textContent = labels[i];
    });
  }
  function drawMetrics(run, start) {
    const mode = ((run.options && run.options.mode) || run.mode) === 'known_map' ? 'known_map' : 'joint';
    const aligned = mode === 'joint' && $('#coordinateMode').value === 'aligned';
    const d = scalarDiagnostics(run, start); const errors = computePositionErrors(run, start, aligned); const maps = computeMapErrors(run, start); const residuals = measurementResiduals(run, start);
    const evalData = d.d.evaluation || {};
    const chosenEval = aligned ? (evalData.aligned || {}) : (evalData.raw || {});
    let pos = number(arrAttr(chosenEval, ['position_rmse_m'])) ?? (aligned ? d.pos : null); let posLabel = aligned ? 'Rigidly aligned · no scale fit' : mode === 'known_map' ? 'Surveyed coordinate frame' : 'Raw frame · frame-dependent';
    if (pos === null && errors && errors.aggregateRmse !== undefined) { pos = errors.aggregateRmse; posLabel = 'Reported aggregate RMSE'; }
    else if (pos === null && errors && errors.values.length) { const valid = errors.values.filter(Number.isFinite); pos = valid.length ? Math.sqrt(valid.reduce((sum, v) => sum + v * v, 0) / valid.length) : null; posLabel = errors.label === 'raw coordinate difference' ? 'Raw frame difference · frame-dependent' : `${errors.values.length} matched samples · ${errors.label}`; }
    let mapError = number(arrAttr(chosenEval, ['map_rmse_m'])) ?? (aligned ? d.map : null);
    if (mapError === null && maps && maps.length) { const valid = maps.map(item => item.value).filter(Number.isFinite); mapError = valid.length ? Math.sqrt(valid.reduce((sum, v) => sum + v * v, 0) / valid.length) : null; }
    let residual = d.residual;
    if (residual === null && residuals && residuals.values.length) residual = Math.sqrt(residuals.values.reduce((sum, v) => sum + v * v, 0) / residuals.values.length);
    const mapLabel = mode === 'known_map' ? 'Surveyed map · no map fit' : aligned ? 'Rigidly aligned · no scale fit' : 'Raw frame · frame-dependent';
    showMetricCards({ pos, map: mode === 'known_map' ? null : mapError, residual, rank: d.rank, posLabel, mapLabel });
  }

  function plotLayout(extra = {}) {
    return { margin: { l: 4, r: 4, t: 4, b: 4 }, paper_bgcolor: '#ffffff', plot_bgcolor: '#ffffff', font: { family: 'Inter, Segoe UI, sans-serif', color: '#627577', size: 10 }, showlegend: true, legend: { orientation: 'h', maxheight: .22, x: 0.01, y: 0.99, yanchor:'top', bgcolor: 'rgba(255,255,255,.78)', bordercolor: '#edf0f0', borderwidth: 1, font: { size: 9 } }, ...extra };
  }
  function reactChart(target, data, layout, config) {
    if (!target.data) target.innerHTML = '';
    return Plotly.react(target, data, layout, config);
  }
  function sceneLayout() {
    const scene = { xaxis: { title: { text: 'X (m)' }, showbackground: true, backgroundcolor: '#fbfcfc', gridcolor: colors.grid, zerolinecolor: '#dce5e4', showspikes: false }, yaxis: { title: { text: 'Y (m)' }, showbackground: true, backgroundcolor: '#fbfcfc', gridcolor: colors.grid, zerolinecolor: '#dce5e4', showspikes: false }, zaxis: { title: { text: 'Z (m)' }, showbackground: true, backgroundcolor: '#fbfcfc', gridcolor: colors.grid, zerolinecolor: '#dce5e4', showspikes: false }, aspectmode: 'data' };
    if (state.camera) scene.camera = state.camera;
    return plotLayout({ uirevision: 'uwb-scene-stable', scene, hoverlabel: { bgcolor: '#fff', bordercolor: '#dfe8e7', font: { size: 10 } } });
  }
  function beaconTrace(beacons, name, color, symbol, group, visible = true) {
    if (!beacons.length) return null;
    return { type: 'scatter3d', mode: 'markers+text', name, legendgroup: group, visible, x: beacons.map(p => p[0]), y: beacons.map(p => p[1]), z: beacons.map(p => p[2]), text: beacons.map((_, i) => `B${i}`), textposition: 'top center', textfont: { size: 10, color }, marker: { size: 5.5, color, symbol, line: { color: '#fff', width: 1 } }, hovertemplate: '%{text}<br>(%{x:.3f}, %{y:.3f}, %{z:.3f}) m<extra>' + name + '</extra>' };
  }
  function pathTrace(path, name, color, dash, group, visible = true, markers = false) {
    if (!path.length) return null;
    const trace = { type: 'scatter3d', mode: markers ? 'markers' : 'lines', name, legendgroup: group, visible, x: path.map(p => p[0]), y: path.map(p => p[1]), z: path.map(p => p[2]), hovertemplate: '(%{x:.3f}, %{y:.3f}, %{z:.3f}) m<extra>' + name + '</extra>' };
    if (markers) trace.marker = { size: 3, color };
    else trace.line = { color, width: 4, dash };
    return trace;
  }
  function planeTrace(pointsList, name, color, group) {
    if (pointsList.length < 3) return null;
    return { type: 'mesh3d', name, legendgroup: group, visible: false, x: pointsList.map(p => p[0]), y: pointsList.map(p => p[1]), z: pointsList.map(p => p[2]), i: [0, 0], j: [1, 2], k: [2, 3], color, opacity: .16, flatshading: true, hoverinfo: 'skip', showlegend: false };
  }
  function planeRectangle(path, z) {
    if (!path || path.length < 2) return [];
    const xs = path.map(p => p[0]), ys = path.map(p => p[1]);
    let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const pad = Math.max((x1 - x0) * .06, (y1 - y0) * .06, .15);
    x0 -= pad; x1 += pad; y0 -= pad; y1 += pad;
    return [[x0, y0, z], [x1, y0, z], [x1, y1, z], [x0, y1, z]];
  }
  function togglePlotLayer(layer, visible) {
    if (!$('#scene').data) return;
    const traces = state.sceneTraces.filter(trace => trace._layer === layer);
    const indices = traces.map(trace => state.sceneTraces.indexOf(trace));
    if (indices.length) Plotly.restyle($('#scene'), { visible }, indices);
  }
  function line3d(a, b, color, name, group, dash = 'solid') {
    return { type: 'scatter3d', mode: 'lines', name, legendgroup: group, showlegend: false, x: [a[0], b[0], null], y: [a[1], b[1], null], z: [a[2], b[2], null], line: { color, width: 3, dash }, hoverinfo: 'skip' };
  }
  function drawScene(run, start) {
    if (!window.Plotly) { state.sceneTraces = []; $('#pngButton').disabled = true; $('#scene').innerHTML = '<div class="scene-empty"><b>Plotly is unavailable</b><span>Check that /vendor/plotly.min.js is being served.</span></div>'; return; }
    const target = $('#scene'); let truth = points(state.truth.trajectory), truthBeacons = points(state.truth.beacons);
    target.dataset.generation = String(Number(target.dataset.generation || 0) + 1);
    const estimate = points(start && start.estimate && start.estimate.trajectory); const estimateBeacons = points(start && start.estimate && start.estimate.beacons);
    const initial = points(start && start.initial && start.initial.trajectory); const initialBeacons = points(start && start.initial && start.initial.beacons);
    const mode = ((run.options && run.options.mode) || run.mode) === 'known_map' ? 'known_map' : 'joint';
    const rawEstimate = estimate;
    const evaluation = start && start.diagnostics && start.diagnostics.evaluation || {};
    const aligned = start && start.aligned_estimate || evaluation.aligned_geometry;
    if (mode !== 'joint' || !aligned || run.schema_version === '7.0') $('#coordinateMode').value = 'raw';
    const coordMode = $('#coordinateMode').value;
    const useAligned = coordMode === 'aligned' && mode === 'joint' && aligned;
    const canonical = ['4.0','5.0','6.0'].includes(run.schema_version) && mode === 'joint' && !useAligned ? evaluation.truth_canonical_transform || run.diagnostics?.truth_canonical_transform : null;
    const truthTransform = p => canonical ? transformPoint(p, {...canonical, applied:true}) : p;
    truth = truth.map(truthTransform); truthBeacons = truthBeacons.map(truthTransform);
    const shownEstimate = useAligned ? points(aligned.trajectory || aligned.estimated_trajectory) : rawEstimate;
    const shownBeacons = mode === 'known_map' ? truthBeacons : (useAligned ? points(aligned.beacons || aligned.estimated_beacons) : estimateBeacons);
    let shownInitial = initial, shownInitialBeacons = initialBeacons;
    if (useAligned && evaluation.alignment) {
      const transform = p => transformPoint(p, evaluation.alignment);
      shownInitial = initial.map(transform); shownInitialBeacons = initialBeacons.map(transform);
    }
    if (mode === 'joint') { $('#coordinateMode').disabled = false; $('#coordinateMode').options[1].disabled = !aligned || run.schema_version === '7.0'; }
    else { $('#coordinateMode').value = 'raw'; $('#coordinateMode').options[1].disabled = true; $('#coordinateMode').disabled = true; }
    const scenario = run.experiment && run.experiment.config && run.experiment.config.scenario;
    const motion = run.path_motion || {};
    const pathInfo = motion.length_m !== undefined ? ` · ${fmt(motion.length_m, 2)} m path · ${fmt(motion.speed_m_s, 2)} m/s · ${fmt(Math.max(0, (run.experiment?.config?.samples || 0) - 1) / (run.experiment?.config?.duration_s || 1), 2)} samples/s` : '';
    const pathTitle = run.experiment?.config?.path?.type ? pathLabel(run.experiment.config.path.type) : null;
    $('#sceneSubtitle').textContent = `${pathTitle || scenarioLabel(scenario)} · ${run.schema_version==='7.0'?'Joint map · surveyed world frame':mode === 'known_map' ? 'Known surveyed map' : `Joint map · ${coordMode} frame`} · ${run.options?.initialization === 'truth_near' ? 'Truth-near diagnostic' : run.options?.initialization === 'algebraic' ? 'Algebraic initialization · measurement only' : 'Independent initialization'} · ${toRows(run.starts).length} starts${pathInfo}`;
    const notice = $('#plotNotice'); const alignment = evaluation.alignment || {};
    const runWarnings = toRows(run.diagnostics && run.diagnostics.warnings);
    if (run.schema_version === '7.0') { notice.textContent = 'Surveyed world frame: only declared fixed coordinates and survey priors constrain the fit. Remaining rigid freedoms are retained in rank; no canonical transform, scale or reflection fit is applied.'; notice.classList.remove('hidden'); }
    else if (mode === 'joint' && coordMode === 'raw') { notice.textContent = ['4.0','5.0','6.0'].includes(run.schema_version) ? 'Raw estimator frame: truth is converted to the declared gauge. Absolute joint-map world height requires a datum; no scale or reflection fit is applied.' : 'Raw coordinates: joint-map geometric errors depend on frame until aligned.'; notice.classList.remove('hidden'); }
    else if (mode === 'joint' && coordMode === 'aligned') { notice.textContent = `Rigid alignment · scale fixed to 1 · reflections ${alignment.reflection_allowed === false ? 'disallowed' : 'resolved by model convention'}. ${['4.0','5.0','6.0'].includes(run.schema_version) ? alignment.description || '' : ''}`; notice.classList.remove('hidden'); }
    else if (runWarnings.length) { notice.textContent = runWarnings.join(' · '); notice.classList.remove('hidden'); }
    else notice.classList.add('hidden');
    const traces = [];
    const add = (trace, layer) => { if (trace) { trace._layer = layer; traces.push(trace); } };
    add(pathTrace(truth, 'Ground truth · trajectory', colors.teal, 'solid', 'truth'), 'truth');
    add(pathTrace(truth, 'Ground truth · samples', colors.teal, 'solid', 'truth', true, true), 'truth');
    add(beaconTrace(truthBeacons, 'Ground truth · beacons', colors.teal, 'circle', 'truth'), 'truth');
    add(pathTrace(shownEstimate, useAligned ? 'Estimate · aligned' : 'Estimate · raw', colors.coral, 'dash', 'estimate'), 'estimate');
    add(pathTrace(shownEstimate, ['3.0','4.0','5.0','6.0','7.0'].includes(run.schema_version) ? 'Estimate · interpolated display samples' : 'Estimated samples', colors.coral, 'solid', 'estimate', true, true), 'estimate');
    if (['3.0','4.0','5.0','6.0','7.0'].includes(run.schema_version) && start?.estimate?.knot_trajectory) {
      const knots = points(start.estimate.knot_trajectory).map(p => {
        if (!useAligned || !evaluation.alignment?.applied) return p;
        return transformPoint(p, evaluation.alignment);
      });
      add(pathTrace(knots, 'Fitted trajectory knots', colors.coral, 'solid', 'estimate', true, true), 'estimate');
    }
    if (mode !== 'known_map') add(beaconTrace(shownBeacons, useAligned ? 'Estimated beacons · aligned' : 'Estimated beacons · raw', colors.coral, 'diamond', 'estimate'), 'estimate');
    add(pathTrace(shownInitial, 'Initial trajectory', colors.amber, 'dot', 'initial'), 'initial');
    add(pathTrace(shownInitial, 'Initial samples', colors.amber, 'dot', 'initial', true, true), 'initial');
    add(beaconTrace(shownInitialBeacons, 'Initial beacons', colors.amber, 'x', 'initial'), 'initial');
    const errors = computePositionErrors(run, start, useAligned);
    if (truth.length && shownEstimate.length === truth.length && errors && errors.label !== 'raw coordinate difference') {
      for (let i = 0; i < truth.length; i += Math.max(1, Math.ceil(truth.length / 20))) add(line3d(truth[i], shownEstimate[i], colors.purple, 'Sampled position error vectors', 'errors', 'dot'), 'errors');
    }
    const observations = toRows(run.experiment && run.experiment.estimator_input && run.experiment.estimator_input.observations);
    if (observations.length && shownEstimate.length) {
      const map = mode === 'known_map' ? truthBeacons : shownBeacons;
      const total = observations.length; const step = Math.max(1, Math.ceil(total / 45));
      for (let i = 0; i < total; i += step) {
        const obs = observations[i]; const epoch = number(obs.epoch); const beaconId = number(obs.beacon_id);
        if (epoch === null || beaconId === null) continue;
        let p = ['3.0','4.0','5.0','6.0','7.0'].includes(run.schema_version) ? xyz(start?.estimate?.ping_trajectory?.[i]) : shownEstimate[epoch];
        if (p && ['3.0','4.0','5.0','6.0','7.0'].includes(run.schema_version) && useAligned && evaluation.alignment?.applied) {
          p = transformPoint(p, evaluation.alignment);
        }
        const b = map[beaconId] || map[beaconId - 1];
        const decision = start?.diagnostics?.observation_decisions?.[i];
        if (p && b) {
          const color = decision?.rejected ? '#c13943' : decision?.weight < .999 ? '#db931e' : '#a9bcc0';
          const name = decision?.rejected ? 'Rejected fit ranges · red' : decision?.weight < .999 ? 'Downweighted fit ranges · amber' : 'Retained fit ranges · gray';
          add(line3d(p, b, color, run.schema_version === '6.0' ? name : 'Sampled fit range rays', 'rays', 'solid'), 'rays');
          if (run.schema_version === '6.0' && (decision?.rejected || decision?.weight < .999)) {
            add({x:[p[0]],y:[p[1]],z:[p[2]],type:'scatter3d',mode:'markers',name:'Trajectory at downweighted/rejected ping',showlegend:false,marker:{color,size:6,symbol:'circle'},hovertemplate:'Trajectory at affected ping<extra></extra>'}, 'rays');
            const knots = start.estimate.knot_trajectory || [], times = start.estimate.knot_times_s || [];
            let k = times.findIndex((t, j) => j < times.length - 1 && obs.assumed_time_s >= t && obs.assumed_time_s <= times[j + 1]);
            if (k >= 0 && knots[k] && knots[k + 1]) {
              const a = useAligned ? transformPoint(knots[k], evaluation.alignment) : knots[k];
              const c = useAligned ? transformPoint(knots[k + 1], evaluation.alignment) : knots[k + 1];
              const affected = line3d(a, c, color, 'Knot segment supporting affected ping · sampled', 'rays', 'solid');
              affected.line.width = 7; add(affected, 'rays');
            }
          }
        }
      }
    }
    const height = start?.diagnostics?.height || run.diagnostics?.height || {};
    add(planeTrace(['4.0','5.0','6.0'].includes(run.schema_version) ? points(height.truth_planarity?.plane_corners).map(truthTransform) : planeRectangle(truth, 0), ['4.0','5.0','6.0'].includes(run.schema_version) ? 'Truth tag best-fit plane' : 'Tag reference plane', '#c7dfda', 'tagPlane'), 'tagPlane');
    const beaconZ = truthBeacons.length ? truthBeacons.reduce((sum, p) => sum + p[2], 0) / truthBeacons.length : 0;
    add(planeTrace(['4.0','5.0','6.0'].includes(run.schema_version) ? points(height.truth_beacon_planarity?.plane_corners).map(truthTransform) : planeRectangle(truthBeacons, beaconZ), ['4.0','5.0','6.0'].includes(run.schema_version) ? 'Truth beacon best-fit plane' : 'Beacon reference plane', '#a9c9c1', 'beaconPlane'), 'beaconPlane');
    // One trace per segment layer keeps toggles responsive instead of issuing
    // dozens of separate WebGL redraws for sampled rays and error vectors.
    for (const layer of ['errors', 'rays']) {
      const segments = traces.filter(trace => trace._layer === layer);
      if (run.schema_version === '6.0' && layer === 'rays') {
        const groups = new Map();
        for (const segment of segments) {
          const key = `${segment.name}/${segment.line?.color || segment.marker?.color}`;
          if (!groups.has(key)) groups.set(key, {...segment, x:[], y:[], z:[]});
          const combined = groups.get(key); combined.x.push(...segment.x); combined.y.push(...segment.y); combined.z.push(...segment.z);
        }
        for (let i = traces.length - 1; i >= 0; i--) if (traces[i]._layer === layer) traces.splice(i, 1);
        traces.push(...groups.values()); continue;
      }
      if (segments.length > 1) {
        const combined = { ...segments[0], x: [], y: [], z: [] };
        for (const segment of segments) {
          combined.x.push(...segment.x); combined.y.push(...segment.y); combined.z.push(...segment.z);
        }
        for (let i = traces.length - 1; i >= 0; i--) if (traces[i]._layer === layer) traces.splice(i, 1);
        traces.push(combined);
      }
    }
    if (!traces.length) { state.sceneTraces = []; if (target.data) Plotly.purge(target); state.sceneCameraHandler = null; $('#pngButton').disabled = true; target.innerHTML = '<div class="scene-empty"><div class="empty-glyph">⌖</div><b>No geometry in this run</b><span>Raw run data is available in diagnostics.</span></div>'; return; }
    state.sceneTraces = traces;
    const defaults = { truth: true, estimate: true, initial: false, errors: false, rays: false, tagPlane: false, beaconPlane: false };
    for (const trace of traces) {
      const checkbox = $(`[data-layer="${trace._layer}"]`);
      trace.visible = checkbox ? checkbox.checked : defaults[trace._layer];
    }
    const allCoordinates = [...truth, ...truthBeacons, ...estimate, ...estimateBeacons, ...shownEstimate, ...shownBeacons, ...initial, ...initialBeacons, ...shownInitial, ...shownInitialBeacons, ...planeRectangle(truth, 0), ...planeRectangle(truthBeacons, truthBeacons.length ? truthBeacons.reduce((sum, p) => sum + p[2], 0) / truthBeacons.length : 0)];
    const ranges = [0, 1, 2].map(axis => {
      const vals = allCoordinates.map(point => point[axis]);
      if (!vals.length) return [-1, 1];
      let low = Math.min(...vals), high = Math.max(...vals); const pad = Math.max((high - low) * .08, .1); return [low - pad, high + pad];
    });
    const layout = sceneLayout();
    if (run.schema_version === '6.0' && window.innerWidth > 700) layout.annotations = [{xref:'paper',yref:'paper',x:.01,y:.01,xanchor:'left',yanchor:'bottom',showarrow:false,font:{size:10,color:'#536768'},bgcolor:'rgba(255,255,255,.88)',text:'Sampled fit rays: gray w ≥ 0.999; amber 0 &lt; w &lt; 0.999; red w = 0.<br>Thick knot segments support affected pings. Injected labels never set these colors.'}];
    ['xaxis', 'yaxis', 'zaxis'].forEach((axis, i) => { layout.scene[axis].range = ranges[i]; layout.scene[axis].autorange = false; });
    target.querySelectorAll('.scene-empty').forEach(node => node.remove());
    const sceneStarted = performance.now();
    Plotly.react(target, traces, layout, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ['toImage', 'sendDataToCloud', 'sendChartToCloud'], scrollZoom: true }).then(() => {
      target.dataset.renderMs = (performance.now() - sceneStarted).toFixed(2);
      if (!state.sceneCameraHandler && typeof target.on === 'function') {
        state.sceneCameraHandler = () => { const camera = target._fullLayout && target._fullLayout.scene && target._fullLayout.scene.camera; if (camera) { state.camera = JSON.parse(JSON.stringify(camera)); target.dataset.camera = JSON.stringify(state.camera); } };
        target.on('plotly_relayout', state.sceneCameraHandler);
      }
      const scene = target._fullLayout && target._fullLayout.scene;
      if (scene && scene.camera) state.camera = scene.camera;
      if (state.camera) target.dataset.camera = JSON.stringify(state.camera);
      $('#pngButton').disabled = false;
      if (window.RangeLabM3 && state.activeRun === run) window.RangeLabM3.onRun(run);
      if (window.RangeLabM4 && state.activeRun === run) window.RangeLabM4.onRun(run);
      if (window.RangeLabM5 && state.activeRun === run) window.RangeLabM5.onRun(run);
      if (window.RangeLabM6 && state.activeRun === run) window.RangeLabM6.onRun(run);
    }).catch(error => { console.error('Scene drawing failed:', error); showToast(`Scene could not render: ${error.message}`); });
  }

  const SMALL_LAYOUT = { margin: { l: 36, r: 8, t: 3, b: 27 }, paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { family: 'Inter, Segoe UI, sans-serif', size: 9, color: '#829293' }, xaxis: { gridcolor: '#edf0f0', zerolinecolor: '#dfe6e6', linecolor: '#e8eded', tickfont: { size: 8 } }, yaxis: { gridcolor: '#edf0f0', zerolinecolor: '#dfe6e6', linecolor: '#e8eded', tickfont: { size: 8 } }, showlegend: false, hoverlabel: { bgcolor: '#fff', bordercolor: '#dfe8e7' } };
  function emptyChart(id, message = 'Run data needed') { const target = $(id); if (target.data && window.Plotly) Plotly.purge(target); target.innerHTML = `<div class="chart-empty">${escapeHtml(message)}</div>`; }
  function drawCharts(run, start) {
    if (!window.Plotly) return;
    ['#positionChart', '#mapChart', '#residualChart', '#residualBeaconChart', '#spectrumChart', '#residualTimeChart'].forEach(selector => { const chart = $(selector); if (chart) { if (!chart.data) chart.innerHTML = ''; else chart.querySelectorAll('.chart-empty').forEach(node => node.remove()); } });
    const mode = ((run.options && run.options.mode) || run.mode) === 'known_map' ? 'known_map' : 'joint';
    $('#positionChartSubtitle').textContent = mode === 'known_map' ? 'Surveyed frame · matched-time distance' : $('#coordinateMode').value === 'aligned' ? 'Rigidly aligned · no scale fit · m' : 'Raw frame · frame-dependent · m';
    $('#mapChartSubtitle').textContent = mode === 'known_map' ? 'Surveyed beacons · no map fit' : $('#coordinateMode').value === 'aligned' ? 'Rigidly aligned · no scale fit · m' : 'Raw frame · frame-dependent · m';
    const errors = computePositionErrors(run, start, $('#coordinateMode').value === 'aligned');
    if (errors && errors.values.length) {
      Plotly.react($('#positionChart'), [{ x: errors.times, y: errors.values, type: 'scatter', mode: 'lines', line: { color: colors.teal, width: 2 }, fill: 'tozeroy', fillcolor: 'rgba(11,129,123,.08)', hovertemplate: 't=%{x:.3f} s<br>%{y:.4f} m<extra></extra>' }], { ...SMALL_LAYOUT, xaxis: { ...SMALL_LAYOUT.xaxis, title: { text: 'Time (s)', font: { size: 8 } } }, yaxis: { ...SMALL_LAYOUT.yaxis, title: { text: 'm', font: { size: 8 } }, rangemode: 'tozero' } }, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ['toImage', 'sendDataToCloud', 'sendChartToCloud'] });
    } else emptyChart('#positionChart', 'No matched position errors reported');
    const maps = computeMapErrors(run, start);
    if (maps && maps.length) Plotly.react($('#mapChart'), [{ x: maps.map(item => `B${item.id}`), y: maps.map(item => item.value), type: 'bar', marker: { color: colors.coral, line: { color: '#d97558', width: .5 } }, hovertemplate: '%{x}<br>%{y:.4f} m<extra></extra>' }], { ...SMALL_LAYOUT, xaxis: { ...SMALL_LAYOUT.xaxis, title: { text: 'Beacon', font: { size: 8 } } }, yaxis: { ...SMALL_LAYOUT.yaxis, title: { text: 'm', font: { size: 8 } }, rangemode: 'tozero' } }, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ['toImage', 'sendDataToCloud', 'sendChartToCloud'] });
    else emptyChart('#mapChart', 'Map error unavailable for this run');
    const residuals = measurementResiduals(run, start);
    if (residuals && residuals.values.length) {
      const values = residuals.values;
      Plotly.react($('#residualChart'), [{ x: values, type: 'histogram', nbinsx: Math.min(24, Math.max(7, Math.ceil(Math.sqrt(values.length)))), marker: { color: '#829fa5', line: { color: '#fff', width: 1 } }, hovertemplate: '%{x:.4f} m<br>%{y} ranges<extra></extra>' }], { ...SMALL_LAYOUT, bargap: .08, xaxis: { ...SMALL_LAYOUT.xaxis, title: { text: 'Signed residual (m)', font: { size: 8 } }, zerolinecolor: '#9eaeaf', zerolinewidth: 1.5 }, yaxis: { ...SMALL_LAYOUT.yaxis, title: { text: 'Count', font: { size: 8 } }, rangemode: 'tozero' } }, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ['toImage', 'sendDataToCloud', 'sendChartToCloud'] });
    } else emptyChart('#residualChart', 'No residual series reported');
    const records = residualRecords(run, start).filter(item => item.residual !== null);
    if (records.length) {
      const grouped = new Map(); records.forEach(record => { if (!grouped.has(record.beaconId)) grouped.set(record.beaconId, []); grouped.get(record.beaconId).push(record.residual); });
      const traces = [...grouped.entries()].map(([id, values]) => ({ y: values, type: 'box', name: `B${id}`, boxpoints: 'outliers', marker: { size: 3 }, hovertemplate: `B${id}<br>%{y:.4f} m<extra></extra>` }));
      Plotly.react($('#residualBeaconChart'), traces, { ...SMALL_LAYOUT, showlegend: false, boxmode: 'group', yaxis: { ...SMALL_LAYOUT.yaxis, title: { text: 'Signed residual (m)', font: { size: 8 } }, zerolinecolor: '#9eaeaf' }, xaxis: { ...SMALL_LAYOUT.xaxis, title: { text: 'Beacon ID', font: { size: 8 } } } }, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ['toImage', 'sendDataToCloud', 'sendChartToCloud'] });
      const normalizedRecords = records.filter(item => item.normalized !== null);
      if (normalizedRecords.length) Plotly.react($('#residualTimeChart'), [{ x: normalizedRecords.map(item => item.time), y: normalizedRecords.map(item => item.normalized), type: 'scatter', mode: 'markers', marker: { size: 4, color: normalizedRecords.map(item => item.beaconId), colorscale: 'Viridis', showscale: false }, hovertemplate: 't=%{x:.3f} s<br>normalized=%{y:.3f}<extra></extra>' }], { ...SMALL_LAYOUT, xaxis: { ...SMALL_LAYOUT.xaxis, title: { text: 'Time (s)', font: { size: 8 } } }, yaxis: { ...SMALL_LAYOUT.yaxis, title: { text: 'Normalized residual (σ)', font: { size: 8 } }, zerolinecolor: '#9eaeaf' } }, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ['toImage', 'sendDataToCloud', 'sendChartToCloud'] });
      else emptyChart('#residualTimeChart', 'Assumed uncertainty unavailable');
    } else { emptyChart('#residualBeaconChart', 'No per-measurement residuals'); emptyChart('#residualTimeChart', 'No time-indexed residuals'); }
    const diag = scalarDiagnostics(run, start); const spectrum = diag.singular;
    const truthSpectrum = arrAttr((run.diagnostics || {}).truth_jacobian || {}, ['singular_values_scaled', 'scaled_singular_values', 'singular_values']);
    const spectra = [];
    if (Array.isArray(truthSpectrum)) spectra.push({ x: truthSpectrum.map((_, i) => i + 1), y: truthSpectrum.map(v => Math.max(number(v) || 1e-16, 1e-16)), type: 'scatter', mode: 'lines+markers', name: 'At truth', line: { color: colors.teal, width: 2 }, marker: { size: 3 } });
    if (spectrum && spectrum.length) spectra.push({ x: spectrum.map((_, i) => i + 1), y: spectrum.map(v => Math.max(v, 1e-16)), type: 'scatter', mode: 'lines+markers', name: 'At solution', line: { color: '#7962a4', width: 2 }, marker: { size: 3 } });
    if (spectra.length) Plotly.react($('#spectrumChart'), spectra, { ...SMALL_LAYOUT, showlegend: spectra.length > 1, legend: { orientation: 'h', x: .02, y: 1.12, font: { size: 8 } }, yaxis: { ...SMALL_LAYOUT.yaxis, type: 'log', title: { text: 'Scaled σ · log', font: { size: 8 } } }, xaxis: { ...SMALL_LAYOUT.xaxis, title: { text: 'Index', font: { size: 8 } }, dtick: Math.max(1, Math.ceil(Math.max(...spectra.map(series => series.y.length)) / 12)) } }, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ['toImage', 'sendDataToCloud', 'sendChartToCloud'] });
    else emptyChart('#spectrumChart', 'Scaled singular values unavailable');
  }

  function valueText(obj, keys, suffix = '') {
    const raw = arrAttr(obj, keys);
    if (raw === undefined || raw === null) return '—';
    if (typeof raw === 'number') return `${fmt(raw, 5)}${suffix}`;
    return escapeHtml(typeof raw === 'string' ? raw : JSON.stringify(raw));
  }
  function drawDiagnostics(run, start) {
    const content = $('#diagnosticsContent');
    const starts = toRows(run.starts); const d = scalarDiagnostics(run, start);
    if (!starts.length && run.status === 'failed') { content.innerHTML = `<p class="diag-fail">${escapeHtml(run.error || 'The run failed before producing start outcomes.')}</p><details class="raw-json"><summary>View raw run JSON</summary><pre>${escapeHtml(JSON.stringify(run, null, 2))}</pre></details>`; return; }
    const options = starts.map(item => `<option value="${escapeHtml(item.index)}" ${String(item.index) === String(start && start.index) ? 'selected' : ''}>Start ${escapeHtml(item.index)} · ${escapeHtml(item.status || (item.success ? 'success' : 'failed'))}</option>`).join('');
    const summary = run.diagnostics || {};
    const solver = d.solver || {};
    const rank = d.rank; const params = d.params;
    const solverEntries = [
      ['Termination', arrAttr(solver, ['termination_reason', 'message', 'status']) ?? (start && start.status)],
      ['Success', arrAttr(solver, ['success']) ?? (start && start.success)],
      ['Iterations', arrAttr(solver, ['iterations', 'iteration_count'])],
      ['Iterations note', arrAttr(solver, ['iterations_note'])],
      ['Function evaluations', arrAttr(solver, ['nfev', 'function_evaluations', 'evaluations'])],
      ['Jacobian evaluations', arrAttr(solver, ['njev', 'jacobian_evaluations'])],
      ['Runtime', arrAttr(solver, ['runtime_s', 'wall_time_s', 'elapsed_s'])],
      ['Initial objective', arrAttr(solver, ['initial_objective', 'initial_cost', 'cost_initial'])],
      ['Final objective', arrAttr(solver, ['final_objective', 'final_cost', 'cost_final', 'cost'])],
      ['Measurement count', arrAttr(d.d, ['measurement_count', 'n_measurements']) ?? arrAttr(d.jac, ['measurement_count']) ?? arrAttr(summary, ['measurement_count', 'n_measurements'])],
      ['Parameter count', params], ['Numerical rank', rank],
      ['Rank tolerance', arrAttr(d.d, ['rank_tolerance', 'rank_tol']) ?? arrAttr(d.jac, ['relative_tolerance', 'rank_tolerance', 'rank_tol']) ?? arrAttr(summary, ['rank_tolerance', 'rank_tol'])],
      ['Scaled Jacobian condition', arrAttr(d.jac, ['condition_number'])],
      ['Full column rank', arrAttr(d.jac, ['full_column_rank'])]
    ];
    const values = solverEntries.map(([label, value]) => `<div class="diag-box"><b>${escapeHtml(label)}</b><span>${value === undefined || value === null ? '—' : escapeHtml(typeof value === 'number' ? fmt(value, label === 'Runtime' ? 4 : 6) : String(value))}</span></div>`).join('');
    const truthJac = summary.truth_jacobian || {};
    const selectedDiagnostics = start && start.diagnostics || {};
    const recoveryBoxes = [
      ['Truth Jacobian rank', `${truthJac.rank ?? '—'} / ${truthJac.parameter_count ?? '—'}`],
      ['Geometric recovery · selected', selectedDiagnostics.geometric_recovery === undefined ? '—' : String(selectedDiagnostics.geometric_recovery)],
      ['Range recovery · selected', selectedDiagnostics.range_recovery === undefined ? '—' : String(selectedDiagnostics.range_recovery)],
      ['Distinct solutions · all starts', summary.distinct_solution_count ?? '—'],
      ['Low residual solutions · all starts', summary.distinct_low_residual_solution_count ?? '—'],
      ['Outcome', start && start.diagnostics && start.diagnostics.recovery_classification || '—']
    ].map(([label, value]) => `<div class="diag-box"><b>${escapeHtml(label)}</b><span>${escapeHtml(String(value))}</span></div>`).join('');
    const rows = starts.map(item => {
      const itemD = scalarDiagnostics(run, item); const itemSolver = itemD.solver || {};
      const result = item.success === true || item.status === 'complete' || item.status === 'success';
      const stateLabel = item.status || (item.success ? 'success' : 'failed');
      return `<tr><td>${escapeHtml(item.index)}</td><td class="${result ? 'diag-pass' : 'diag-fail'}">${escapeHtml(stateLabel)}</td><td>${escapeHtml(String(item.success ?? '—'))}</td><td>${fmt(number(arrAttr(itemSolver, ['final_objective', 'final_cost', 'cost_final', 'cost'])))}</td><td>${fmt(number(arrAttr(itemSolver, ['runtime_s', 'wall_time_s', 'elapsed_s'])))}</td><td>${escapeHtml(String(itemD.rank ?? '—'))}${itemD.params !== null ? ` / ${escapeHtml(String(itemD.params))}` : ''}</td></tr>`;
    }).join('');
    const runNotes = arrAttr(summary, ['warnings']);
    content.innerHTML = `${starts.length > 1 && !window.RangeLabWorkspace ? `<div class="start-selector"><label for="startSelect">Inspect outcome</label><select id="startSelect">${options}</select></div>` : ''}<div class="diagnostics-table-wrap"><table class="diagnostics-table"><thead><tr><th>START</th><th>OUTCOME</th><th>SUCCESS</th><th>FINAL OBJECTIVE</th><th>RUNTIME (S)</th><th>RANK / PARAMS</th></tr></thead><tbody>${rows || '<tr><td colspan="6">No per-start outcomes were saved.</td></tr>'}</tbody></table></div><div class="diag-columns">${values}${recoveryBoxes}</div>${summary.ambiguity ? `<p style="margin-top:10px">${escapeHtml(summary.ambiguity)}</p>` : ''}${runNotes ? `<p style="margin-top:10px">${escapeHtml(Array.isArray(runNotes) ? runNotes.join(' · ') : runNotes)}</p>` : ''}${starts.length ? '' : '<p style="margin-top:10px">This run contains no start records. Raw data follows.</p>'}<details class="raw-json"><summary>View raw run JSON</summary><pre>${escapeHtml(JSON.stringify(run, null, 2))}</pre></details>`;
    const selector = $('#startSelect', content);
    if (selector) selector.addEventListener('change', () => { state.selectedStart = selector.value; state.start = pickStart(run, state.selectedStart); drawScene(run, state.start); drawMetrics(run, state.start); drawCharts(run, state.start); drawDiagnostics(run, state.start); window.RangeLabM7?.onRun(run, state.start); });
  }

  function setCamera(view) {
    const cameras = {
      reset: { eye: { x: 1.55, y: 1.45, z: 1.25 }, up: { x: 0, y: 0, z: 1 } },
      perspective: { eye: { x: 1.55, y: 1.45, z: 1.25 }, up: { x: 0, y: 0, z: 1 } },
      top: { eye: { x: 0, y: 0, z: 2.5 }, up: { x: 0, y: 1, z: 0 } },
      side: { eye: { x: 0, y: -2.5, z: .25 }, up: { x: 0, y: 0, z: 1 } }
    };
    state.camera = cameras[view] || cameras.reset;
    if ($('#scene').data) Plotly.relayout($('#scene'), { 'scene.camera': state.camera });
    $$('.view-button').forEach(button => button.classList.toggle('active', button.dataset.view === view));
  }

  async function importRun(file) {
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      const payload = parsed.run || parsed;
      if (payload && payload.artifact_type === 'experiment_config' && payload.config) {
        const config = payload.config, options = payload.options || {}, path = config.path;
        for (const [key, id] of Object.entries({ scenario: 'scenario', samples: 'samples', duration_s: 'duration', noise_std_m: 'noise', assumed_std_m: 'sigma', seed: 'seed' })) if (config[key] !== undefined && $(`#${id}`)) $(`#${id}`).value = config[key];
        if (path) {
          $('#usePath').checked = true; $('#pathType').value = path.type;
          $('#pathCenterX').value = path.center_m?.[0] ?? 5; $('#pathCenterY').value = path.center_m?.[1] ?? 4;
          $('#pathWidth').value = path.size_m?.[0] ?? 7; $('#pathHeight').value = path.size_m?.[1] ?? path.size_m?.[0] ?? 5.6;
          $('#pathScale').value = path.scale ?? 1; $('#pathRotation').value = path.rotation_deg ?? 0;
          $('#arcStart').value = path.start_angle_deg ?? 0; $('#arcSweep').value = path.arc_angle_deg ?? 180;
          if (path.waypoints_m) $('#waypoints').value = path.waypoints_m.map(point => point.join(',')).join('\n');
        } else $('#usePath').checked = false;
        $('#mode').value = options.mode || 'joint'; $('#init').value = options.initialization || 'independent';
        $('#starts').value = options.starts ?? 3; $('#initSeed').value = options.seed ?? 19;
        $('#usePath').dispatchEvent(new Event('change')); $('#pathType').dispatchEvent(new Event('change'));
        showToast('Experiment configuration loaded.'); return;
      }
      if (payload && ['sweep', 'comparison'].includes(payload.artifact_type)) {
        const response = await api('/api/artifacts/import', { method: 'POST', body: JSON.stringify(payload) });
        if (window.RangeLabM2) window.RangeLabM2.refresh();
        showToast('Artifact imported and saved.'); return;
      }
      if (!payload || !payload.experiment || !payload.experiment.truth || !payload.experiment.estimator_input) throw new Error('This JSON does not look like a saved run or M2 artifact.');
      const response = await api('/api/import', { method: 'POST', body: JSON.stringify(payload) });
      const run = response.run || response; run.id ||= response.id; state.activeRun = run; state.selectedStart = null;
      renderRun(run); await refreshRuns(run.id); showToast('Run imported and saved.');
    } catch (error) { showToast(`Import failed: ${error.message}`); }
    finally { $('#importFile').value = ''; }
  }

  function setupEvents() {
    $('#runForm').addEventListener('submit', startRun);
    $('#init').addEventListener('change', () => $('#truthNearNote').classList.toggle('hidden', $('#init').value !== 'truth_near'));
    $$('[data-layer]').forEach(input => input.addEventListener('change', () => togglePlotLayer(input.dataset.layer, input.checked)));
    $$('.view-button').forEach(button => button.addEventListener('click', () => setCamera(button.dataset.view)));
    $('#coordinateMode').addEventListener('change', () => { if (state.activeRun) { drawScene(state.activeRun, state.start); drawMetrics(state.activeRun, state.start); drawCharts(state.activeRun, state.start); } });
    $('#pngButton').addEventListener('click', async () => {
      if (!$('#scene').data) return;
      try { await Plotly.downloadImage($('#scene'), { format: 'png', filename: `uwb-${state.activeRun && state.activeRun.id || 'scene'}`, width: 1500, height: 1000, scale: 1 }); }
      catch (error) { showToast(`Could not export scene image: ${error.message}`); }
    });
    $('#importButton').addEventListener('click', () => $('#importFile').click());
    $('#importFile').addEventListener('change', event => importRun(event.target.files && event.target.files[0]));
  }

  async function init() {
    setupEvents();
    try {
      const scenarios = await api('/api/scenarios');
      const values = Array.isArray(scenarios) ? scenarios : scenarios.scenarios || [];
      if (values.length) {
        const select = $('#scenario'); const current = select.value;
        select.innerHTML = values.map(item => {
          const id = typeof item === 'string' ? item : item.id;
          const title = typeof item === 'string' ? scenarioLabel(item) : item.label || item.name || scenarioLabel(item.id);
          return `<option value="${escapeHtml(id)}">${escapeHtml(title)}</option>`;
        }).join('');
        if (values.some(item => (typeof item === 'string' ? item : item.id) === current)) select.value = current;
      }
    } catch (error) { console.warn('Scenario list unavailable; using built-in defaults.', error); }
    await refreshRuns();
  }
  window.RangeLab = { importFile:importRun, state, renderRun, refreshRuns, acceptRunSummaries(runs, selectedId) { state.runs = runs; renderRuns(selectedId || state.activeRun?.id); }, openRun: loadRun, api, pickStart, setSelectedStart(index) { state.selectedStart = index; } };
  document.addEventListener('DOMContentLoaded', init);
})();
