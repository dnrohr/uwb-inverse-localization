(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const finite = value => value === null || value === undefined || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);
  const displayNumber = value => { const number = finite(value); return number === null ? '—' : number !== 0 && Math.abs(number) < 1e-4 ? number.toExponential(2) : number.toFixed(4); };
  const rows = value => Array.isArray(value) ? value : [];
  const palette = ['#0b817b', '#e88569'];
  const state = { sweeps: [], activeSweep: null, runs: [], comparison: null, activeComparison: null, comparisonCamera: null, comparisonCameraHandler: null, chartData: null };
  async function api(url, options = {}) {
    const response = await fetch(url, { headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers }, ...options });
    if (!response.ok) { let message = `${response.status} ${response.statusText}`; try { const payload = await response.json(); message = payload.error || payload.message || message; } catch (_) {} throw new Error(message); }
    return response.json();
  }
  function toast(message) { const node = $('#toast'); node.textContent = message; node.classList.add('visible'); setTimeout(() => node.classList.remove('visible'), 3000); }
  function clearChartPlaceholder(target) { if (!target.data) target.innerHTML = ''; else target.querySelectorAll('.chart-empty').forEach(node => node.remove()); }
  function formConfig() {
    const config = { scenario: $('#scenario').value, samples: +$('#samples').value, duration_s: +$('#duration').value, noise_std_m: +$('#noise').value, assumed_std_m: +$('#sigma').value, seed: +$('#seed').value };
    if ($('#usePath').checked) {
      const path = { type: $('#pathType').value, center_m: [+$('#pathCenterX').value, +$('#pathCenterY').value], size_m: [+$('#pathWidth').value, +$('#pathHeight').value], scale: +$('#pathScale').value, rotation_deg: +$('#pathRotation').value };
      if (path.type === 'circle' || path.type === 'arc') path.size_m = [path.size_m[0], path.size_m[0]];
      if (path.type === 'line') path.size_m[1] = 1; // Only width defines a line.
      if (path.type === 'circle' || path.type === 'arc') path.start_angle_deg = +$('#arcStart').value;
      if (path.type === 'arc') path.arc_angle_deg = +$('#arcSweep').value;
      if (path.type === 'waypoint') {
        const points = $('#waypoints').value.trim().split(/\n+/).map(line => line.split(/[,\s]+/).map(Number));
        if (points.length < 2 || points.length > 100 || points.some(point => point.length !== 2 || !point.every(Number.isFinite))) throw new Error('Waypoints need 2–100 local x,y pairs.');
        path.waypoints_m = points; delete path.size_m;
      }
      config.path = path;
    }
    return config;
  }
  function selectedOptions() { return { mode: $('#mode').value, initialization: $('#init').value, starts: +$('#starts').value, seed: +$('#initSeed').value }; }
  function parseList(value, integer = false) {
    const tokens = value.split(',').map(token => token.trim());
    if (!tokens.length || tokens.some(token => !token || !Number.isFinite(Number(token)) || (integer && !Number.isInteger(Number(token))))) throw new Error('Every list item must be a valid number.');
    return tokens.map(Number);
  }
  function sweepSummary(sweep) { return `${sweep.factor || sweep.kind || 'Sweep'} · ${sweep.status || 'saved'} · ${String(sweep.id || '').slice(0, 8)}`; }
  async function refreshSweeps() { window.RangeLabLibrary?.invalidate(); }
  function attemptRecords(sweep) {
    const entries = rows(sweep.entries || sweep.attempts || sweep.results);
    const startRows = rows(sweep.start_table);
    if (startRows.length) return startRows.map(row => {
      const entry = entries.find(item => item.index === row.entry_index) || entries[row.entry_index] || {};
      return { entry, run: entry.run || {}, row, value: row.value, entryIndex: row.entry_index, attemptIndex: row.start_index };
    });
    return entries.flatMap((entry, entryIndex) => {
      const attempts = rows(entry.attempts || entry.runs || (entry.run ? [entry.run] : []));
      return attempts.flatMap((run, attemptIndex) => rows((run.run || run).starts).map(start => ({ entry, run: run.run || run, row: start, value: entry.value, entryIndex, attemptIndex: start.index })));
    });
  }
  function metric(run, names) {
    const start = rows(run && run.starts).find(item => item.index === run.selected_start) || rows(run && run.starts).find(item => item.success) || rows(run && run.starts)[0];
    const diag = (start && start.diagnostics) || {};
    const evals = diag.evaluation || {};
    for (const name of names) {
      const value = finite(diag[name] ?? evals.raw?.[name] ?? evals[name] ?? run?.aggregate?.[name]);
      if (value !== null) return value;
    }
    return null;
  }
  function aggregateForSweep(sweep) {
    const records = attemptRecords(sweep);
    const groups = new Map();
    records.forEach(record => {
      const key = `${record.value ?? record.entryIndex} / ${record.row?.variant || record.entry.variant || ''}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(record);
    });
    return [...groups.entries()].map(([value, items]) => {
      const rmses = items.map(item => finite(item.row?.position_rmse_m) ?? metric(item.run, ['position_rmse_m', 'trajectory_rmse_m'])).filter(x => x !== null);
      const residuals = items.map(item => finite(item.row?.range_rmse_m) ?? metric(item.run, ['range_residual_rmse_m', 'residual_rmse_m'])).filter(x => x !== null);
      const successful = items.filter(item => item.row ? item.row.optimizer_converged : ['success', 'complete', 'not_converged'].includes(item.run?.status)).length;
      return { value: finite(items[0]?.row?.value ?? items[0]?.entry.value) ?? value, variant: items[0]?.row?.variant || items[0]?.entry.variant || '', count: items.length, successful, rmse: rmses.length ? rmses.reduce((a, b) => a + b, 0) / rmses.length : null, residual: residuals.length ? residuals.reduce((a, b) => a + b, 0) / residuals.length : null };
    });
  }
  function renderSweep(sweep) {
    state.activeSweep = sweep;
    const records = attemptRecords(sweep), aggregate = aggregateForSweep(sweep);
    const plannedRuns = (sweep.config?.values?.length || 0) * (sweep.config?.seeds?.length || 0) * (sweep.config?.variants?.length || 0);
    $('#m2Subtitle').textContent = `${sweep.config?.factor || sweep.factor || sweep.kind || 'Parameter'} sweep · ${sweep.status || 'saved'} · ${rows(sweep.entries).length}/${plannedRuns} runs attempted · ${records.length} saved starts`;
    $('#sweepDisclosure').innerHTML = `${sweep.error ? `<b>Sweep stopped:</b> ${esc(sweep.error)} ${esc(sweep.recovery_note || '')}<br>` : ''}<b>Thresholds and aggregation.</b> ${esc(sweep.aggregation_convention || 'All attempted starts enter failure rates; finite nonconverged fits remain in error distributions.')} ${esc(JSON.stringify(sweep.thresholds || {}))}<br><b>Pairing.</b> ${esc(sweep.pairing?.scope || '')} ${esc(sweep.pairing?.map_constraint || '')}`;
    $('#sweepDisclosure').classList.toggle('hidden', !records.length && !sweep.error);
    const distributions = rows(sweep.aggregates);
    const maxSolutions = item => Math.max(0, ...rows(sweep.entries).filter(entry => entry.value === item.value && entry.variant === item.variant).map(entry => rows(sweep.solution_groups).find(group => group.entry_index === entry.index)?.distinct_solution_count || 0));
    $('#sweepVariability').innerHTML = distributions.length ? `<table class="m2-table"><thead><tr><th>VALUE</th><th>VARIANT</th><th>RUNS</th><th>STARTS</th><th>FAILED STARTS</th><th>FAILURE RATE</th><th>SELECTED POSITION MEDIAN (M)</th><th>ALL POSITION MEDIAN (M)</th><th>POSITION P90 (M)</th><th>MAP MEDIAN (M)</th><th>MAP P90 (M)</th><th>RANK DEFICIENT</th><th>MAX DISTINCT / DATA CELL</th><th>MAX LOW-RESIDUAL / DATA CELL</th></tr></thead><tbody>${distributions.map(item => `<tr><td>${esc(item.value)}</td><td>${esc(item.variant)}</td><td>${esc(item.run_count)}</td><td>${esc(item.start_count)}</td><td>${esc(item.failed_start_count)}</td><td>${finite(item.failure_rate) === null ? '—' : `${(item.failure_rate * 100).toFixed(1)}%`}</td><td>${displayNumber(item.selected_seed_position_rmse_m?.median)}</td><td>${displayNumber(item.all_start_position_rmse_m?.median)}</td><td>${displayNumber(item.all_start_position_rmse_m?.p90)}</td><td>${displayNumber(item.all_start_map_rmse_m?.median)}</td><td>${displayNumber(item.all_start_map_rmse_m?.p90)}</td><td>${esc(item.rank_deficient_start_count)}</td><td>${esc(maxSolutions(item))}</td><td>${esc(item.max_distinct_low_residual_solutions_in_one_cell)}</td></tr>`).join('')}</tbody></table>` : '';
    $('#sweepTable').innerHTML = records.length ? `<table class="m2-table"><thead><tr><th>VALUE</th><th>VARIANT</th><th>SEED</th><th>RUN · START</th><th>CLASSIFICATION</th><th>CONVERGED</th><th>POSITION RMSE (M)</th><th>RANGE RMSE (M)</th><th>RANK</th></tr></thead><tbody>${records.map((item, index) => { const run = item.run || {}; const r = item.row || {}; const seed = r.seed ?? run.experiment?.config?.seed ?? item.entry.seed ?? '—'; const runId = run.id || item.entry.run_id || 'queued'; return `<tr class="attempt-row" data-record="${index}" tabindex="0"><td>${esc(item.value ?? '—')}</td><td>${esc(r.variant || item.entry.variant || '—')}</td><td>${esc(seed)}</td><td title="${esc(runId)}">${esc(String(runId).slice(0, 8))} · ${esc(r.start_index ?? item.attemptIndex ?? '—')}</td><td>${esc(r.classification || r.status || run.status || 'saved')}</td><td>${esc(r.optimizer_converged ?? '—')}</td><td>${displayNumber(r.position_rmse_m)}</td><td>${displayNumber(r.range_rmse_m)}</td><td>${esc(r.full_column_rank ?? '—')}</td></tr>`; }).join('')}</tbody></table>` : '<div class="chart-empty">No saved attempts in this sweep.</div>';
    document.querySelectorAll('.attempt-row').forEach(row => { const open = () => inspectAttempt(records[+row.dataset.record]); row.addEventListener('click', open); row.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } }); });
    state.chartData = aggregate;
    const report = rows(sweep.aggregates);
    if (window.Plotly && (report.length || aggregate.length)) {
      clearChartPlaceholder($('#sweepChart'));
      const dataset = report.length ? report : aggregate;
      const variants = [...new Set(dataset.map(item => item.variant || 'all'))];
      const traces = variants.map((variant, i) => { const subset = dataset.filter(item => (item.variant || 'all') === variant); const distribution = item => item.selected_seed_position_rmse_m || item.all_start_position_rmse_m; return { x: subset.map(item => item.value), y: subset.map(item => distribution(item)?.median ?? item.rmse), type: 'scatter', mode: 'lines+markers', name: `${variant} · median position RMSE`, line: { color: palette[i % palette.length], width: 2 }, marker: { size: 7 }, customdata: subset.map(item => [distribution(item)?.p90 ?? '', item.failure_rate ?? (item.count ? 1 - item.successful / item.count : '')]), hovertemplate: 'value=%{x}<br>median RMSE=%{y:.4f} m<br>p90=%{customdata[0]}<br>failure rate=%{customdata[1]}<extra>%{fullData.name}</extra>' }; });
      traces.push(...variants.map((variant, i) => { const subset = dataset.filter(item => (item.variant || 'all') === variant); return { x: subset.map(item => item.value), y: subset.map(item => item.failure_rate ?? (item.count ? 1 - item.successful / item.count : null)), type: 'scatter', mode: 'lines+markers', name: `${variant} · failure rate`, yaxis: 'y2', line: { color: palette[i % palette.length], dash: 'dot', width: 1.5 }, marker: { size: 5 }, hovertemplate: 'value=%{x}<br>failure rate=%{y:.1%}<extra>%{fullData.name}</extra>' }; }));
      const chartStarted = performance.now();
      Plotly.react($('#sweepChart'), traces, { margin: { l: 50, r: 50, t: 20, b: 42 }, paper_bgcolor: '#ffffff', plot_bgcolor: '#ffffff', font: { size: 10, color: '#516466' }, xaxis: { title: { text: sweep.config?.factor || sweep.factor || sweep.kind || 'Value' }, gridcolor: '#edf0f0' }, yaxis: { title: { text: 'Position RMSE (m)' }, gridcolor: '#edf0f0', rangemode: 'tozero' }, yaxis2: { title: { text: 'Failure rate' }, overlaying: 'y', side: 'right', range: [0, 1], tickmode: 'array', tickvals: [0, .25, .5, .75, 1], ticktext: ['0%', '25%', '50%', '75%', '100%'], showgrid: false }, legend: { orientation: 'h', y: 1.15 }, hovermode: 'x unified' }, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ['toImage', 'sendDataToCloud', 'sendChartToCloud'] }).then(() => {
        const chart = $('#sweepChart'); chart.dataset.renderMs = (performance.now() - chartStarted).toFixed(2);
        if (chart.removeAllListeners) chart.removeAllListeners('plotly_click');
        chart.on('plotly_click', event => {
          const point = event.points?.[0]; if (!point) return;
          const variant = variants[point.curveNumber % variants.length] || variants[0];
          const row = rows(sweep.start_table).find(item => Number(item.value) === Number(point.x) && item.variant === variant && item.selected) || rows(sweep.start_table).find(item => Number(item.value) === Number(point.x) && item.variant === variant);
          if (row) { const entry = rows(sweep.entries).find(item => item.index === row.entry_index); if (entry) inspectAttempt({ entry, run: entry.run, row }); }
        });
      });
    }
    $('#exportSweepCsv').disabled = !records.length;
    $('#exportSweepJson').disabled = !records.length; $('#exportSweepChart').disabled = !records.length;
  }
  function inspectAttempt(record) {
    const run = record && record.run;
    if (!run || !run.experiment) return toast('This attempt has not produced a saved run yet.');
    const lab = window.RangeLab; if (!lab) return;
    run.id ||= record.entry.run_id;
    lab.setSelectedStart(record.row?.start_index ?? run.selected_start ?? null);
    lab.renderRun(run);
    const start = rows(run.starts).find(item => String(item.index) === String(record.row?.start_index ?? run.selected_start));
    if (start && $('#startSelect')) { $('#startSelect').value = start.index; $('#startSelect').dispatchEvent(new Event('change')); }
    document.querySelector('#scene').scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  async function loadSweep(id) {
    try { const sweep = await api(`/api/sweeps/${encodeURIComponent(id)}`); const artifact = sweep.artifact || sweep; renderSweep(artifact); await refreshSweeps(id); }
    catch (error) { toast(`Could not open sweep: ${error.message}`); }
  }
  async function createSweep(event) {
    event.preventDefault();
    let values, seeds;
    try { values = parseList($('#sweepValues').value, $('#sweepParameter').value === 'samples'); seeds = parseList($('#sweepSeeds').value, true); }
    catch (error) { return toast(error.message); }
    if (!values.length || !seeds.length) return toast('Enter numeric sweep values and at least one integer seed.');
    const options = { ...selectedOptions(), max_nfev: 2000 };
    const variants = $('#sweepBudget').value === 'paired' ? [{ label: 'quick · 200 evals', max_nfev: 200 }, { label: 'full · 2000 evals', max_nfev: 2000 }] : [{ label: 'full · 2000 evals', max_nfev: 2000 }];
    let experiment;
    try { experiment = formConfig(); } catch (error) { return toast(error.message); }
    const body = { factor: $('#sweepParameter').value, values, seeds, experiment, options, variants };
    if (body.factor === 'path_scale' && !body.experiment.path) return toast('Enable a custom path before sweeping path scale.');
    try {
      const created = await api('/api/sweeps', { method: 'POST', body: JSON.stringify(body) }); toast('Sweep queued.'); await refreshSweeps(created.id);
      if (created.id) {
        await loadSweep(created.id);
        let polls = 0;
        const timer = setInterval(async () => {
          try {
            const job = await api(`/api/jobs/${encodeURIComponent(created.id)}`); polls++;
            if (job.status === 'complete' || job.status === 'failed') { clearInterval(timer); await loadSweep(created.id); await refreshRunList(); toast(job.status === 'complete' ? 'Sweep complete.' : 'Sweep stopped with an error.'); }
            else if (polls % 10 === 0) await refreshSweeps(created.id);
            if (polls > 3600) clearInterval(timer);
          } catch (error) { clearInterval(timer); toast(`Sweep status unavailable: ${error.message}`); }
        }, 1000);
      }
    }
    catch (error) { toast(`Could not start sweep: ${error.message}`); }
  }
  function pointList(value) { return rows(value).map(p => Array.isArray(p) && p.slice(0, 3).every(v => finite(v) !== null) ? p.slice(0, 3).map(Number) : null).filter(Boolean); }
  function updateRunSelectors() { /* A/B slots are owned by the Library. */ }
  async function refreshRunList() { window.RangeLabLibrary?.invalidate(); }
  async function refreshComparisons() { window.RangeLabLibrary?.invalidate(); }
  function drawComparison(artifact) {
    const views = rows(artifact.views);
    if (views.length !== 2) throw new Error('Saved comparison does not contain two fitted views.');
    const a = views.map((view, i) => {
      const estimate = pointList(view.estimate?.trajectory), errors = rows(view.position_errors_m).map(finite);
      const count = Math.min(estimate.length, errors.length);
      return { label: artifact.runs?.[i]?.reference_name || (view.id ? String(view.id).slice(0, 8) : `Run ${i + 1}`), truth: pointList(view.truth?.trajectory), estimate: estimate.slice(0, count), interpolated: rows(view.interpolated_trajectory), errors: errors.slice(0, count), times: rows(view.times_elapsed_s).slice(0, count).map(finite), truthGeometry: view.truth, fitGeometry: view.estimate, m3: ["3.0","4.0","5.0","6.0","7.0"].includes(artifact.runs?.[i]?.schema_version) };
    });
    const maxError = Math.max(1e-9, ...a.flatMap(run => run.errors).filter(value => value !== null));
    const traces = [];
    a.forEach((run, index) => {
      traces.push({ type: 'scatter3d', mode: 'lines', name: `${run.label} · ground truth`, x: run.truth.map(p => p[0]), y: run.truth.map(p => p[1]), z: run.truth.map(p => p[2]), line: { color: palette[index], width: 3 }, hovertemplate: `${esc(run.label)} truth<br>(%{x:.3f}, %{y:.3f}, %{z:.3f}) m<extra></extra>` });
      const interpolated = run.interpolated.length ? run.interpolated : run.estimate;
      traces.push({ type: 'scatter3d', mode: 'lines', name: `${run.label} · fit path`, x: interpolated.map(p => p?.[0] ?? null), y: interpolated.map(p => p?.[1] ?? null), z: interpolated.map(p => p?.[2] ?? null), line: { color: palette[index], width: 2, dash: 'dash' }, hovertemplate: `${esc(run.label)} fit path<br>(%{x:.3f}, %{y:.3f}, %{z:.3f}) m<extra></extra>` });
      traces.push({ type: 'scatter3d', mode: 'markers', name: `${run.label} · ${run.m3 ? "display samples" : "fitted epochs"}`, x: run.estimate.map(p => p[0]), y: run.estimate.map(p => p[1]), z: run.estimate.map(p => p[2]), marker: { size: 4, color: run.errors, cmin: 0, cmax: maxError, colorscale: 'Viridis', showscale: index === 1, colorbar: { title: { text: 'Position error (m)' } } }, customdata: run.errors.map((value, i) => [value, run.times[i]]), hovertemplate: `${esc(run.label)} ${run.m3 ? "interpolated display sample" : "fitted epoch"}<br>t=%{customdata[1]:.3f} s<br>(%{x:.3f}, %{y:.3f}, %{z:.3f}) m<br>error=%{customdata[0]:.4f} m<extra></extra>` });
      const truthBeacons = pointList(run.truthGeometry?.beacons), fitBeacons = pointList(run.fitGeometry?.beacons);
      if (truthBeacons.length) traces.push({ type: 'scatter3d', mode: 'markers+text', name: `${run.label} · truth beacons`, x: truthBeacons.map(p => p[0]), y: truthBeacons.map(p => p[1]), z: truthBeacons.map(p => p[2]), text: truthBeacons.map((_, i) => `B${i}`), textposition: 'top center', marker: { size: 6, color: palette[index], symbol: 'circle' }, hovertemplate: `${esc(run.label)} truth %{text}<br>(%{x:.3f}, %{y:.3f}, %{z:.3f}) m<extra></extra>` });
      if (fitBeacons.length) traces.push({ type: 'scatter3d', mode: 'markers+text', name: `${run.label} · fit beacons`, x: fitBeacons.map(p => p[0]), y: fitBeacons.map(p => p[1]), z: fitBeacons.map(p => p[2]), text: fitBeacons.map((_, i) => `B${i}`), textposition: 'bottom center', marker: { size: 5, color: palette[index], symbol: 'diamond', line: { color: '#fff', width: 1 } }, hovertemplate: `${esc(run.label)} fit %{text}<br>(%{x:.3f}, %{y:.3f}, %{z:.3f}) m<extra></extra>` });
    });
    const bounds = artifact.shared_bounds_m || {};
    const range = axis => bounds[axis] || [-1, 1];
    clearChartPlaceholder($('#comparisonScene')); const sceneStarted = performance.now();
    const comparisonLayout = { margin: { l: 2, r: 2, t: 5, b: 2 }, paper_bgcolor: '#ffffff', showlegend: true, font: { color: '#44595b', size: 10 }, legend: { orientation: 'h', y: 1.08, font: { size: 10 } }, scene: { bgcolor: '#ffffff', xaxis: { title: { text: 'X (m)' }, range: range('x'), autorange: false }, yaxis: { title: { text: 'Y (m)' }, range: range('y'), autorange: false }, zaxis: { title: { text: 'Z (m)' }, range: range('z'), autorange: false }, aspectmode: 'data', ...(state.comparisonCamera ? { camera: state.comparisonCamera } : {}) }, uirevision: 'm2-comparison-shared-camera' };
    Plotly.react($('#comparisonScene'), traces, comparisonLayout, { responsive: true, displaylogo: false, scrollZoom: true, modeBarButtonsToRemove: ['toImage', 'sendDataToCloud', 'sendChartToCloud'] }).then(() => {
      const scene = $('#comparisonScene'); scene.dataset.renderMs = (performance.now() - sceneStarted).toFixed(2);
      if (!state.comparisonCameraHandler && typeof scene.on === 'function') {
        state.comparisonCameraHandler = () => { const camera = scene._fullLayout?.scene?.camera; if (camera) { state.comparisonCamera = JSON.parse(JSON.stringify(camera)); scene.dataset.camera = JSON.stringify(camera); } };
        scene.on('plotly_relayout', state.comparisonCameraHandler);
      }
      const camera = scene._fullLayout?.scene?.camera; if (camera) { state.comparisonCamera = JSON.parse(JSON.stringify(camera)); scene.dataset.camera = JSON.stringify(camera); }
    });
    const chartTraces = a.map((run, index) => ({ x: run.times, y: run.errors, type: 'scatter', mode: 'lines+markers', name: run.label, line: { color: palette[index], width: 2 }, marker: { size: 6 }, customdata: run.estimate.map((p, i) => [p[0], p[1], p[2]]), hovertemplate: 't=%{x:.3f} s<br>error=%{y:.4f} m<br>fit=(%{customdata[0]:.3f}, %{customdata[1]:.3f}, %{customdata[2]:.3f})<extra>%{fullData.name}</extra>' }));
    clearChartPlaceholder($('#comparisonChart'));
    Plotly.react($('#comparisonChart'), chartTraces, { margin: { l: 50, r: 10, t: 12, b: 40 }, paper_bgcolor: '#ffffff', plot_bgcolor: '#ffffff', font: { size: 10, color: '#516466' }, xaxis: { title: { text: 'Elapsed time (s)' }, gridcolor: '#edf0f0' }, yaxis: { title: { text: 'Position error (m)' }, gridcolor: '#edf0f0', rangemode: 'tozero' }, legend: { orientation: 'h', y: 1.12 } }, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ['toImage', 'sendDataToCloud', 'sendChartToCloud'] });
    $('#exportComparePng').disabled = false; $('#exportCompareChart').disabled = false; $('#exportCompareJson').disabled = false;
    $('#comparisonMetrics').innerHTML = `<table class="m2-table"><thead><tr><th>RUN</th><th>STATUS</th><th>MODE</th><th>SAMPLES</th><th>STARTS</th><th>SELECTED</th><th>POSITION RMSE (M)</th><th>MAP RMSE (M)</th><th>RANGE RMSE (M)</th><th>RUNTIME (S)</th><th>CONVERGED</th><th>FULL RANK</th></tr></thead><tbody>${rows(artifact.table).map((item, i) => `<tr><td title="${esc(item.id)}">${esc(String(item.id || a[i]?.label).slice(0, 8))}</td><td>${esc(item.status)}</td><td>${esc(item.mode)}</td><td>${esc(item.samples)}</td><td>${esc(item.starts)}</td><td>${esc(item.selected_start ?? '—')}</td><td>${displayNumber(item.position_rmse_m)}</td><td>${displayNumber(item.map_rmse_m)}</td><td>${displayNumber(item.range_rmse_m)}</td><td>${displayNumber(item.runtime_s)}</td><td>${esc(item.optimizer_converged)}</td><td>${esc(item.full_column_rank ?? '—')}</td></tr>`).join('')}</tbody></table>`;
    const hasKnownMap = rows(artifact.runs).some(run => run.options?.mode === 'known_map');
    const surveyRuns=rows(artifact.runs).filter(run=>run.schema_version==='7.0').length;
    const labels = surveyRuns===2?'Both survey fits stay in their declared world frame; no truth alignment is fitted.':surveyRuns===1?'The survey fit stays in its declared world frame. The other fit uses its recorded model alignment policy.':artifact.alignment === 'aligned' ? (hasKnownMap ? 'Joint-map fits use independent proper rigid alignment to truth at scale 1; known-map runs stay in their surveyed frame.' : 'Each joint-map fit uses proper rigid alignment to truth at scale 1; reflections are forbidden.') : 'Raw coordinates shown; joint-map errors depend on the frame.';
    $('#compareNotice').textContent = `${labels} Fit markers show matched-time Euclidean position error on a shared 0–${displayNumber(maxError)} m scale. Scene lines use saved rendering interpolation; time-chart points and error statistics use ${a.some(run => run.m3) ? "saved display samples (M3–M7), fitted epochs (M0–M2)" : "original fitted epochs"} only. ${artifact.time_reference || ''}`; $('#compareNotice').classList.remove('hidden');
  }
  async function compareRuns() {
    const [aId, bId] = window.RangeLabLibrary?.runIds() || []; const keys = window.RangeLabLibrary?.runKeys() || []; const alignment = $('#compareAlignment').value;
    if (keys.length === 2 && keys.every(Boolean)) {
      if(keys[0] === keys[1]) return toast('Choose two different saved source records.');
      try { const saved=await api('/api/library/compare',{method:'POST',body:JSON.stringify({keys,alignment})});state.activeComparison=saved.artifact || saved;drawComparison(state.activeComparison);window.RangeLabLibrary?.reportPairing(...(state.activeComparison.runs || []));await refreshComparisons(saved.id);$('#m2Subtitle').textContent='Saved comparison · validated retained Library source records'; } catch(error) { toast(`Could not compare retained sources: ${error.message}`); }
      return;
    }
    if (!aId || !bId || aId === bId) return toast('Choose two different saved runs.');
    try {
      const [a, b] = await Promise.all([api(`/api/runs/${encodeURIComponent(aId)}`), api(`/api/runs/${encodeURIComponent(bId)}`)]);
      a.id ||= aId; b.id ||= bId;
      window.RangeLabLibrary?.reportPairing(a, b);
      const saved = await api('/api/comparisons', { method: 'POST', body: JSON.stringify({ run_ids: [aId, bId], alignment }) });
      state.activeComparison = saved.artifact || saved; drawComparison(state.activeComparison); await refreshComparisons(saved.id);
      $('#m2Subtitle').textContent = `Saved comparison · ${aId.slice(0, 8)} vs ${bId.slice(0, 8)} · ${alignment}`;
    } catch (error) { toast(`Could not compare runs: ${error.message}`); }
  }
  async function openComparison(id) {
    if (!id) return;
    try {
      const stored = await api(`/api/comparisons/${encodeURIComponent(id)}`); const artifact = stored.artifact || stored; state.activeComparison = artifact;
      if (artifact.runs?.length === 2) { window.RangeLabLibrary?.setComparisonRuns(artifact.runs,artifact.library_sources,artifact.id); $('#compareAlignment').value = artifact.alignment || 'raw'; }
      drawComparison(artifact);
    } catch (error) { toast(`Could not open comparison: ${error.message}`); }
  }
  function download(name, mime, contents) { const url = URL.createObjectURL(new Blob([contents], { type: mime })); const link = document.createElement('a'); link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
  function exportSweepCsv() {
    if (!state.activeSweep) return;
    const records = attemptRecords(state.activeSweep);
    const fields = Object.keys(records[0]?.row || {});
    const lines = [['sweep_id', 'factor', 'run_id', ...fields].join(',')];
    const csv = value => `"${String(value ?? '').replace(/"/g, '""')}"`;
    records.forEach(item => lines.push([state.activeSweep.id, state.activeSweep.config?.factor, item.run?.id, ...fields.map(key => item.row[key])].map(csv).join(',')));
    download(`sweep-${state.activeSweep.id}.csv`, 'text/csv', lines.join('\n'));
  }
  function syncPathControls() {
    const enabled = $('#usePath').checked;
    $('#pathFields').classList.toggle('hidden', !enabled);
    $('#pathFields').querySelectorAll('input, select, textarea').forEach(input => { input.disabled = !enabled; });
    $('#arcFields').classList.toggle('hidden', !['circle', 'arc'].includes($('#pathType').value));
    $('#arcSweepField').classList.toggle('hidden', $('#pathType').value !== 'arc');
    $('#waypointFields').classList.toggle('hidden', $('#pathType').value !== 'waypoint');
    const circular = ['circle', 'arc'].includes($('#pathType').value);
    $('#pathWidth').disabled = !enabled || $('#pathType').value === 'waypoint';
    $('#pathHeight').disabled = !enabled || circular || ['line', 'waypoint'].includes($('#pathType').value);
    $('#arcStart').disabled = !enabled || !circular;
    $('#arcSweep').disabled = !enabled || $('#pathType').value !== 'arc';
    $('#waypoints').disabled = !enabled || $('#pathType').value !== 'waypoint';
    if (circular) $('#pathHeight').value = $('#pathWidth').value;
  }
  function init() {
    $('#usePath').addEventListener('change', syncPathControls); $('#pathType').addEventListener('change', syncPathControls); syncPathControls();
    $('#pathWidth').addEventListener('input', syncPathControls);
    $('#sweepForm').addEventListener('submit', createSweep); $('#compareButton').addEventListener('click', compareRuns); $('#exportSweepCsv').addEventListener('click', exportSweepCsv);
    $('#savedComparisons').addEventListener('change', () => openComparison($('#savedComparisons').value));
    $('#exportComparePng').addEventListener('click', () => { if ($('#comparisonScene').data) Plotly.downloadImage($('#comparisonScene'), { format: 'png', filename: 'uwb-run-comparison', width: 1500, height: 1000, scale: 1 }); });
    $('#exportCompareChart').addEventListener('click', () => { if ($('#comparisonChart').data) Plotly.downloadImage($('#comparisonChart'), { format: 'png', filename: 'uwb-comparison-position-error', width: 1400, height: 700, scale: 1 }); });
    $('#exportSweepChart').addEventListener('click', () => { if ($('#sweepChart').data) Plotly.downloadImage($('#sweepChart'), { format: 'png', filename: 'uwb-sweep-aggregate', width: 1400, height: 700, scale: 1 }); });
    $('#exportSweepJson').addEventListener('click', () => { if (state.activeSweep) download(`sweep-${state.activeSweep.id}.json`, 'application/json', JSON.stringify(state.activeSweep, null, 2)); });
    $('#exportCompareJson').addEventListener('click', () => { if (state.activeComparison) download(`comparison-${state.activeComparison.id || 'saved'}.json`, 'application/json', JSON.stringify(state.activeComparison, null, 2)); });
    $('#exportConfigButton').addEventListener('click', () => { const config = formConfig(), active = window.RangeLab?.state?.activeRun; const sameConfig = active?.experiment?.config && JSON.stringify(active.experiment.config) === JSON.stringify(config); download('uwb-experiment-config.json', 'application/json', JSON.stringify({ schema_version: '1.0', artifact_type: 'experiment_config', config, options: { ...selectedOptions(), max_nfev: 2000 }, path_motion: sameConfig ? active.path_motion || null : null, sampling_density_hz: Math.max(0, config.samples - 1) / config.duration_s }, null, 2)); });
    refreshSweeps(); refreshRunList(); refreshComparisons();
  }
  window.RangeLabM2 = { openArtifact(artifact) { if(artifact.artifact_type==='comparison'){state.activeComparison=artifact;$('#compareAlignment').value=artifact.alignment || 'raw';drawComparison(artifact);if(artifact.runs?.length===2)window.RangeLabLibrary?.setComparisonRuns(artifact.runs,artifact.library_sources,artifact.id);}else renderSweep(artifact); }, openSweep: loadSweep, openComparison, compareRuns, formConfig, acceptRuns: refreshRunList, refresh() { refreshSweeps(); refreshRunList(); refreshComparisons(); } };
  document.addEventListener('DOMContentLoaded', init);
})();
