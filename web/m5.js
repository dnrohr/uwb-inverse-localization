(() => {
  'use strict';
  const $ = id => document.getElementById(id), arr = value => Array.isArray(value) ? value : [];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const state = { run: null, artifact: null, runs: [], inspectingArtifact: false };
  async function api(url, options = {}) {
    const response = await fetch(url, { headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers }, ...options });
    if (!response.ok) { let message = `${response.status} ${response.statusText}`; try { const body = await response.json(); message = body.error || body.message || message; } catch (_) {} throw new Error(message); }
    return response.json();
  }
  function toast(message) { const node = $('toast'); if (node) { node.textContent = message; node.classList.add('visible'); setTimeout(() => node.classList.remove('visible'), 3000); } }
  function download(name, type, content) { if(window.RangeLabWorkspace?.download)return window.RangeLabWorkspace.download(name,content,type); const blob = new Blob([content], { type: `${type};charset=utf-8` }), url = URL.createObjectURL(blob), link = document.createElement('a'); link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
  function csv(items, filename) { const keys = [...new Set(items.flatMap(item => Object.keys(item)))], quote = value => `"${String(value ?? '').replace(/"/g, '""')}"`; download(filename, 'text/csv', [keys.map(quote).join(','), ...items.map(item => keys.map(key => quote(typeof item[key] === 'object' ? JSON.stringify(item[key]) : item[key])).join(','))].join('\n')); }
  function payload() {
    const shared = window.RangeLabM4?.formPayload?.();
    if (!shared) throw new Error('M4 shared experiment controls are unavailable.');
    const initializationError = Number($('m5InitError').value);
    if (!Number.isFinite(initializationError) || initializationError < 0) throw new Error('Initialization error must be finite and nonnegative.');
    const options = { ...shared.options, solver: $('m5Solver').value, height_parameterization: $('m5Parameterization').value, initialization: $('m5Initialization').value, initialization_error_m: initializationError, algebraic_physical_tolerance:Number($("m5AlgebraicTolerance").value) };
    return { config: shared.config, options };
  }
  function domainValid(start) {
    if (!start?.estimate) return null;
    const solver = start.solver || {}, x = solver.final_parameters, bounds = solver.parameterization;
    if (!Array.isArray(x) || !bounds) return null;
    const strict = solver.method?.endsWith('/lm');
    return x.every((value,i) => (bounds.bounds_lower[i] === null || (strict ? value > bounds.bounds_lower[i] : value >= bounds.bounds_lower[i])) && (bounds.bounds_upper[i] === null || (strict ? value < bounds.bounds_upper[i] : value <= bounds.bounds_upper[i])));
  }
  function runAttempts(run) {
    const config = run?.experiment?.config || {}, noise = config.noise_std_m, exact = (Array.isArray(noise) ? noise : [noise]).every(value => Number(value) === 0), frame = run?.options?.mode === 'known_map' || exact ? 'raw' : 'aligned';
    return arr(run?.starts).map((start, index) => {
      const diag = start.diagnostics || {}, evaluation = diag.evaluation?.[frame] || {}, jacobian = diag.jacobian || {}, solver = start.solver || {};
      const initializer = diag.algebraic_initializer;
      const initializerStatus = initializer?.status ?? diag.initializer?.status;
      return { start_index: start.index ?? index, seed: start.seed ?? run.options?.seed, solver: run.options?.solver,
        height_parameterization: run.options?.height_parameterization, initialization: run.options?.initialization, initialization_error_m: run.options?.initialization_error_m,
        message:solver.message,initializer_error:initializer?.error,initializer_status: initializerStatus, initializer_valid: initializerStatus === 'success',
        native_measurement_rank:diag.native_jacobian?.rank,native_condition_number:diag.native_jacobian?.condition_number,physical_condition_number:jacobian.condition_number,augmented_rank:diag.augmented_jacobian?.rank,measurement_objective:solver.measurement_objective,prior_objective:solver.prior_objective,solver_domain_valid:domainValid(start), converged: start.success, status: start.status, error_frame: frame,
        position_rmse_m: evaluation.position_rmse_m, map_rmse_m: evaluation.map_rmse_m,
        range_rmse_m: diag.range_rmse_m, measurement_rank: jacobian.rank, parameter_count: jacobian.parameter_count,
        runtime_s: solver.runtime_s, start_record: start };
    });
  }
  function attempts(value, kind) { return kind === 'artifact' ? value.start_table.map(row => ({...row,solver_domain_valid:domainValid(value.entries[row.entry_index]?.run?.starts?.[row.start_index]),native_measurement_rank:value.entries[row.entry_index]?.run?.starts?.[row.start_index]?.diagnostics?.native_jacobian?.rank,native_condition_number:value.entries[row.entry_index]?.run?.starts?.[row.start_index]?.diagnostics?.native_jacobian?.condition_number,message:value.entries[row.entry_index]?.run?.starts?.[row.start_index]?.solver?.message})) : runAttempts(value); }
  function renderAttempts(items, onSelect) {
    if (!items.length) { $('m5AttemptTable').innerHTML = '<div class="chart-empty">No attempted starts were retained.</div>'; return; }
    const cols = ['variant','value','seed','start_index','solver','height_parameterization','initialization','initialization_error_m','initializer_status','initializer_valid','optimizer_converged','converged','solver_domain_valid','status','error_frame','position_rmse_m','map_rmse_m','height_rmse_m','range_rmse_m','measurement_rank','native_measurement_rank','native_condition_number','physical_condition_number','augmented_rank','parameter_count','measurement_objective','prior_objective','runtime_s','initializer_error','message'];
    const keys = cols.filter(k => items.some(row => row[k] !== undefined));
    $('m5AttemptTable').innerHTML = `<table class="m2-table"><thead><tr>${keys.map(k => `<th>${esc(k.replaceAll('_',' '))}</th>`).join('')}</tr></thead><tbody>${items.map((row, index) => `<tr class="m5-attempt-row" data-m5-attempt="${index}" tabindex="0">${keys.map(k => `<td>${esc(typeof row[k] === 'object' ? JSON.stringify(row[k]) : row[k] ?? '—')}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
    $('m5AttemptTable').querySelectorAll('[data-m5-attempt]').forEach(node => { const select = () => onSelect?.(items[Number(node.dataset.m5Attempt)]); node.addEventListener('click', select); node.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(); } }); });
    const valid = items.filter(row => row.initializer_valid === true || row.initializer_status === 'success').length, invalid = items.filter(row => ['invalid','failed','unsupported'].includes(row.initializer_status)).length, converged = items.filter(row => (row.optimizer_converged ?? row.converged) === true).length;
    $('m5Summary').textContent = `${items.length} attempted starts · ${valid} initializer-valid · ${invalid} invalid/unsupported initializer · ${converged} reported converged · ${items.filter(row => (row.optimizer_converged ?? row.converged) === true && row.solver_domain_valid === true).length} converged within the stated solver domain. Every attempt remains in the table.`;
  }
  function renderChart(artifact) {
    const target = $('m5Chart'), geometry = $('m5GeometryChart'), rows = attempts(artifact, 'artifact'), variants = [...new Set(rows.map(row => row.variant))];
    const started = performance.now(), geometryStarted = performance.now();
    if (!window.Plotly) { target.innerHTML = geometry.innerHTML = '<div class="chart-empty">Plotly is unavailable.</div>'; return; }
    const traces = variants.map(name => { const group = rows.filter(row => row.variant === name && row.range_rmse_m !== null && row.range_rmse_m !== undefined); return { type:'box', name, y:group.map(row => Number(row.range_rmse_m)).filter(Number.isFinite), boxpoints:'all', jitter:.3, pointpos:0 }; }).filter(trace => trace.y.length);
    Plotly.react(target, traces, { title:{text:'Finite range residuals by variant · unavailable failed residuals excluded',font:{size:12}}, margin:{l:75,r:15,t:50,b:70}, yaxis:{title:{text:'Range residual RMSE (m)'},gridcolor:'#edf0f0'}, xaxis:{title:{text:'Solver / parameterization / initializer variant'},gridcolor:'#edf0f0'}, paper_bgcolor:'white',plot_bgcolor:'white',font:{family:'Inter, sans-serif',size:10,color:'#536768'},boxmode:'group',showlegend:false }, {responsive:true,displaylogo:false}).then(() => { target.dataset.renderMs = (performance.now() - started).toFixed(2); });
    const values = arr(artifact.config?.values), aggregates = arr(artifact.aggregates), labels = arr(artifact.config?.variants).map(variant => variant.label);
    const geometryTraces = labels.map(label => {
      const group = aggregates.filter(row => row.variant === label).sort((a,b) => Number(a.value_index) - Number(b.value_index));
      return { type:'scatter', mode:'lines+markers', name:label, x:group.map(row => row.value), y:group.map(row => row.all_start_position_rmse_m?.median ?? null), connectgaps:false };
    });
    Plotly.react(geometry, geometryTraces, { title:{text:'All-start median geometric error · available estimates',font:{size:12}}, margin:{l:75,r:15,t:65,b:65}, xaxis:{title:{text:artifact.config?.factor || 'Swept factor'},gridcolor:'#edf0f0'}, yaxis:{title:{text:'All-start median position RMSE (m)'},gridcolor:'#edf0f0',rangemode:'tozero'}, paper_bgcolor:'white',plot_bgcolor:'white',font:{family:'Inter, sans-serif',size:10,color:'#536768'},legend:{orientation:'h',y:1.06},showlegend:true }, {responsive:true,displaylogo:false}).then(() => { geometry.dataset.renderMs = (performance.now() - geometryStarted).toFixed(2); });
    $('m5ChartLabel').textContent = 'Finite residuals by variant; unavailable failed-attempt residuals are excluded, with every attempt retained in the table';
    $('m5GeometryChartLabel').textContent = `All-start median position RMSE by variant · factor: ${artifact.config?.factor || 'swept input'}`;
    $('m5SweepPng').disabled = traces.length === 0; $('m5GeometryPng').disabled = geometryTraces.length === 0;
  }
  function restoreControls(run) {
    if (window.RangeLabWorkspace) return;

    const config = run?.experiment?.config || {}, options = run?.options || {};
    window.RangeLabM4?.restoreConfig?.(config, options);
    $('m5Solver').value = options.solver || 'trf'; $('m5Parameterization').value = options.height_parameterization || 'h'; $('m5Initialization').value = options.initialization || 'independent'; $('m5InitError').value = options.initialization_error_m ?? 0; $('m5AlgebraicTolerance').value = options.algebraic_physical_tolerance ?? 1e-7;
  }
  function inspectRunStart(run, item) {
    if (!window.RangeLab) return;
    restoreControls(run); window.RangeLab.state.activeRun = run; window.RangeLab.state.selectedStart = item.start_index;
    window.RangeLab.renderRun(run);
  }
  function inspectArtifactStart(artifact, item) {
    const entry = arr(artifact.entries)[Number(item.entry_index)], run = entry?.run;
    if (run) { state.inspectingArtifact = true; try { inspectRunStart(run, item); } finally { state.inspectingArtifact = false; } }
  }
  function render(value, kind, displayScene = false) {
    if (kind === 'run' && displayScene) state.artifact = null;
    state[kind] = value; const rows = attempts(value, kind);
    renderAttempts(rows, kind === 'artifact' ? item => inspectArtifactStart(value, item) : item => inspectRunStart(value, item));
    const sourceRuns = kind === 'artifact' ? arr(value.entries).map(e => e.run) : [value];
    const historical = sourceRuns.some(run => arr(run?.starts).some(start => start.solver?.method?.endsWith('/lm') && (start.solver.bounds_transform_revision || 1) < 2));
    const projection = kind === 'run' ? value.diagnostics?.native_model_projection : null;
    if (projection?.available) $('m5Summary').textContent += ` Native model projection before optimization: knot RMS ${Number(projection.knot_position_rmse_m).toPrecision(3)} m, map RMS ${Number(projection.map_rmse_m).toPrecision(3)} m. M4 representation diagnostics precede the M5 shared-height branch restriction; these discrepancies are not optimizer lower bounds.`;
    if (historical) $('m5Summary').textContent += ' Historical LM record: the original transform could round onto bounds; its stored convergence flag does not certify the strict-interior claim. Repaired runs use transform revision 2.';

    $('m5ExportRunJson').disabled = $('m5ExportRunCsv').disabled = $('m5ExportPng').disabled = !state.run;
    $('m5ExportJson').disabled = $('m5ExportCsv').disabled = !state.artifact;
    $('m5SweepPng').disabled = $('m5GeometryPng').disabled = !state.artifact;
    if (kind === 'artifact') renderChart(value);
    else if (displayScene && window.RangeLab && value) { restoreControls(value); window.RangeLab.state.activeRun = value; window.RangeLab.state.selectedStart = null; window.RangeLab.renderRun(value); }
  }
  function isM5(run) { return String(run?.schema_version || '').startsWith('5') || run?.artifact_type?.startsWith?.('m5_'); }
  async function refreshRuns() { window.RangeLabLibrary?.invalidate(); }
  async function openRun(id) { try { const run = await api(`/api/runs/${encodeURIComponent(id)}`); run.id ||= id; render(run, 'run', true); await refreshRuns(id); } catch (error) { toast(`Could not open M5 run: ${error.message}`); } }
  async function refreshSweeps() { window.RangeLabLibrary?.invalidate(); }
  async function openSweep(id) { try { const artifact = await api(`/api/m5/sweeps/${encodeURIComponent(id)}`); render(artifact, 'artifact'); await refreshSweeps(id); } catch (error) { toast(`Could not open M5 benchmark: ${error.message}`); } }
  async function poll(id, type) {
    for (let i = 0; i < 3600; i++) {
      const job = await api(`/api/jobs/${encodeURIComponent(id)}`);
      if (job.status === 'complete' || job.status === 'failed') {
        const value = job.run || job.artifact || await api(type === 'run' ? `/api/runs/${encodeURIComponent(id)}` : `/api/m5/sweeps/${encodeURIComponent(id)}`);
        if (type === 'run') { value.id ||= id; render(value, 'run', true); await refreshRuns(id); }
        else { render(value, 'artifact'); await refreshSweeps(id); await refreshRuns(); }
        toast(job.status === 'complete' ? 'M5 job complete.' : 'M5 job finished with a failure.'); return;
      }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    toast('M5 job is still running.');
  }
  async function submitRun(event) {
    event.preventDefault(); let body;
    try { body = payload(); } catch (error) { return toast(error.message); }
    $('m5RunButton').disabled = true;
    try { const created = await api('/api/m5/runs', { method:'POST', body:JSON.stringify(body) }); if (!created.id) throw new Error('The M5 run response did not include a job id.'); toast('M5 run queued.'); await poll(created.id, 'run'); }
    catch (error) { toast(`Could not run M5: ${error.message}`); } finally { $('m5RunButton').disabled = false; }
  }
  async function submitSweep(event) {
    event.preventDefault(); let base, variants, seeds;
    try { base = payload(); variants = JSON.parse($('m5Variants').value); if (!Array.isArray(variants) || !variants.length || variants.some(v => !v.label || !v.options)) throw new Error('Enter a JSON array of variants, each with an explicit label and options object.'); seeds = $('m5Seeds').value.split(',').map(v => Number(v.trim())); if (!seeds.length || seeds.some(v => !Number.isInteger(v) || v < 0 || v > 4294967295)) throw new Error('Measurement seeds must be unsigned 32-bit integers.'); }
    catch (error) { return toast(error.message); }
    const button = $('m5SweepForm').querySelector('button[type=submit]'); button.disabled = true;
    const values = $('m5SweepValues').value.split(',').map(value => Number(value.trim())), factor = $('m5SweepFactor').value;
    if (!values.length || values.some(value => !Number.isFinite(value) || value < 0)) { button.disabled = false; return toast('Sweep values must be finite, nonnegative numbers.'); }
    try { const created = await api('/api/m5/sweeps', { method:'POST', body:JSON.stringify({ base_experiment:base.config, options:base.options, factor, values, seeds, variants }) }); if (!created.id) throw new Error('The M5 benchmark response did not include a job id.'); toast('Paired benchmark queued.'); await poll(created.id, 'sweep'); }
    catch (error) { toast(`Could not run M5 benchmark: ${error.message}`); } finally { button.disabled = false; }
  }
  async function importFile(file) { if (!file) return; try { const saved = await api('/api/m5/import', { method:'POST', body:JSON.stringify(JSON.parse(await file.text())) }); if (saved.run) { const run = saved.run; run.id ||= saved.id; render(run,'run',true); await refreshRuns(run.id); } else { const artifact = saved.artifact || saved; render(artifact,'artifact'); await refreshSweeps(artifact.id); await refreshRuns(); } toast('M5 artifact imported and saved.'); } catch (error) { toast(`Could not import M5 JSON: ${error.message}`); } }
  function exportRunCsv() { if (state.run) csv(runAttempts(state.run), `m5-run-${state.run.id || 'current'}.csv`); }
  function exportArtifactCsv() { if (state.artifact) csv(state.artifact.start_table, `m5-benchmark-${state.artifact.id || 'current'}.csv`); }
  function init() {
    $('m5Form').addEventListener('submit', submitRun); $('m5SweepForm').addEventListener('submit', submitSweep);
    $('m5ExportRunJson').addEventListener('click', () => state.run && download(`m5-run-${state.run.id || 'current'}.json`,'application/json',JSON.stringify(state.run,null,2)));
    $('m5ExportRunCsv').addEventListener('click', exportRunCsv); $('m5ExportJson').addEventListener('click', () => state.artifact && download(`m5-benchmark-${state.artifact.id || 'current'}.json`,'application/json',JSON.stringify(state.artifact,null,2)));
    $('m5ExportCsv').addEventListener('click', exportArtifactCsv); $('m5SweepPng').addEventListener('click', () => { if ($('m5Chart').data && window.Plotly) Plotly.downloadImage($('m5Chart'),{format:'png',filename:`m5-residuals-${state.artifact?.id || 'current'}`,width:1400,height:700,scale:1}); });
    $('m5GeometryPng').addEventListener('click', () => { if ($('m5GeometryChart').data && window.Plotly) Plotly.downloadImage($('m5GeometryChart'),{format:'png',filename:`m5-geometry-${state.artifact?.id || 'current'}`,width:1400,height:700,scale:1}); });
    $('m5ExportPng').addEventListener('click', async () => { const scene = $('scene'); if (scene?.data && window.Plotly) await Plotly.downloadImage(scene,{format:'png',filename:`m5-scene-${state.run?.id || 'current'}`,width:1400,height:900,scale:1}); });
    $('m5ImportButton').addEventListener('click', () => $('m5ImportFile').click()); $('m5ImportFile').addEventListener('change', e => importFile(e.target.files?.[0]).finally(() => { e.target.value = ''; }));
    $('m5ImportSweep').addEventListener('click', () => $('m5SweepImportFile').click()); $('m5SweepImportFile').addEventListener('change', e => importFile(e.target.files?.[0]).finally(() => { e.target.value = ''; }));
    refreshRuns(); refreshSweeps();
  }
  window.RangeLabM5 = { restoreRun:restoreControls, openArtifact(artifact) { render(artifact, 'artifact'); }, onRun(run) { if (!isM5(run)) { $('m5ExportPng').disabled = true; return; } if (state.artifact?.entries?.some(entry => entry.run === run)) { state.run = run; $('m5ExportRunJson').disabled = $('m5ExportRunCsv').disabled = $('m5ExportPng').disabled = false; return; } if (state.artifact) { state.artifact = null; $('m5ExportJson').disabled = $('m5ExportCsv').disabled = $('m5SweepPng').disabled = $('m5GeometryPng').disabled = true; } render(run, 'run'); }, refresh() { refreshRuns(); refreshSweeps(); }, openRun, openSweep };
  document.addEventListener('DOMContentLoaded', init);
})();
