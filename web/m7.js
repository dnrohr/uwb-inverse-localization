(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const api=(...args)=>window.RangeLab.api(...args);
  const state={run:null,start:null,summary:null,importedExperiment:null};
  const download=(name,value,type='application/json')=>{if(window.RangeLabWorkspace?.download)return window.RangeLabWorkspace.download(name,value,type);const url=URL.createObjectURL(new Blob([typeof value==='string'?value:JSON.stringify(value,null,2)],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  const fmt=v=>typeof v==='number'&&Number.isFinite(v)?v.toPrecision(5):'unavailable';
  function message(text,error=false){$('m7Status').textContent=text;$('m7Status').classList.toggle('is-error',error);}
  function validateSurveyDeclaration(survey,beaconCount=8){
    if(!survey || typeof survey!=='object' || Array.isArray(survey) || Object.keys(survey).some(k=>!['frame','units','fixed','priors'].includes(k)))throw new Error('Unsupported survey declaration fields; coupled cross-beacon constraints are unavailable.');
    if(survey.frame!=='world' || survey.units!=='m')throw new Error('Survey must explicitly declare frame world and units m; coordinate conversion is unavailable.');
    const occupied=new Set();
    for(const kind of ['fixed','priors']){
      const rows=survey[kind]===undefined?[]:survey[kind];if(!Array.isArray(rows)||rows.length>24)throw new Error('Survey rows must be arrays with at most 24 entries.');
      for(const row of rows){
        const fields=kind==='fixed'?['beacon_id','mask','mean_m']:['beacon_id','mask','mean_m','covariance_m2'];
        if(!row || typeof row!=='object' || Array.isArray(row) || Object.keys(row).length!==fields.length || fields.some(k=>!Object.hasOwn(row,k)))throw new Error('Unsupported or missing survey row fields.');
        if(!Number.isInteger(row.beacon_id)||row.beacon_id<0||row.beacon_id>=beaconCount)throw new Error('Invalid survey beacon ID for this configuration.');
        if(!Array.isArray(row.mask)||row.mask.length!==3||row.mask.some(v=>typeof v!=='boolean')||!row.mask.some(Boolean))throw new Error('Survey masks require three booleans and at least one selected axis.');
        if(!Array.isArray(row.mean_m)||row.mean_m.length!==3||row.mean_m.some(v=>typeof v!=='number'||!Number.isFinite(v)))throw new Error('Survey means require three finite metre coordinates.');
        row.mask.forEach((selected,axis)=>{if(selected){const key=`${row.beacon_id}:${axis}`;if(occupied.has(key))throw new Error('Survey fixed/prior coordinates overlap; combine coupled axes in one prior block.');occupied.add(key);}});
        if(kind==='priors'){
          const n=row.mask.filter(Boolean).length,c=row.covariance_m2;
          if(!Array.isArray(c)||c.length!==n||c.some(r=>!Array.isArray(r)||r.length!==n||r.some(v=>typeof v!=='number'||!Number.isFinite(v))))throw new Error('Survey covariance must be a finite selected-axis square matrix in m².');
          const lower=Array.from({length:n},()=>Array(n).fill(0));
          for(let i=0;i<n;i++)for(let j=0;j<=i;j++){if(Math.abs(c[i][j]-c[j][i])>1e-14+1e-12*Math.abs(c[j][i]))throw new Error('Survey covariance must be symmetric.');let sum=c[i][j];for(let k=0;k<j;k++)sum-=lower[i][k]*lower[j][k];if(i===j){if(!(sum>0))throw new Error('Survey covariance must be positive definite; exact coordinates use fixed.');lower[i][j]=Math.sqrt(sum);}else lower[i][j]=sum/lower[j][j];}
        }
      }
    }
    if(!occupied.size)throw new Error('Declare at least one fixed or uncertain survey coordinate.');
  }
  function payload(){
    const shared=window.RangeLabM6.formPayload(),fixed=JSON.parse($('m7Fixed').value),priors=JSON.parse($('m7Priors').value);
    if(!Array.isArray(fixed)||!Array.isArray(priors)||!fixed.length&&!priors.length)throw new Error('Declare at least one fixed coordinate or uncertain survey prior. Inputs remain independent of hidden truth.');
    const options={...shared.options,mode:'joint',beacon_height_model:'independent',height_parameterization:'h',tag_height_model:$('m7TagModel').value,below_beacons:$('m7Below').checked,solver:$('m7Solver').value,initialization:$('m7Initialization').value,loss:$('m7Loss').value,survey:{frame:'world',units:'m',fixed,priors},uncertainty:{enabled:$('m7UncertaintyEnabled').checked,range_model:'independent_gaussian_known_sigma',rank_rtol:+$('m7RankTolerance').value,bound_tolerance_m:+$('m7BoundTolerance').value}};
    if(options.below_beacons&&options.tag_height_model!=='fixed')throw new Error('Survey below-beacon constraints currently support the fixed tag-height model only.');
    if($('m7Source').value==='imported'){if(!state.importedExperiment)throw new Error('Imported observation source is unavailable.');return{experiment:state.importedExperiment,options};}
    if($('m7Source').value==='active'){
      const active=window.RangeLab.state.activeRun;
      if(!active?.experiment||!['6.0','7.0'].includes(active.schema_version))throw new Error('Open a saved M6 or M7 source run to reuse its retained observations.');
      return {experiment:active.experiment,options};
    }
    return {config:shared.config,options};
  }
  function importConfig(record){
    if(record.artifact_type!=='experiment_config'||!record.options?.survey)throw new Error('Expected an M7 declared configuration.');
    const config=record.config || record.experiment?.config;if(!config)throw new Error('Configuration has no experiment settings.');
    validateSurveyDeclaration(record.options.survey,config.beacon_layout?.count || 8);
    const uncertainty=record.options.uncertainty;if(uncertainty && (typeof uncertainty!=='object' || Array.isArray(uncertainty) || Object.keys(uncertainty).some(k=>!['enabled','range_model','rank_rtol','bound_tolerance_m'].includes(k)) || uncertainty.range_model!==undefined && uncertainty.range_model!=='independent_gaussian_known_sigma'))throw new Error('Unsupported uncertainty declaration; assumptions cannot be silently replaced.');
    const declarations={mode:['joint'],beacon_height_model:['independent'],height_parameterization:['h'],tag_height_model:['fixed','shared','soft','free'],solver:['trf','lm'],initialization:['independent','truth_near'],loss:['gaussian','huber','soft_l1','cauchy','hard_rejection']};
    for(const[key,allowed]of Object.entries(declarations))if(record.options[key]!==undefined&&!allowed.includes(record.options[key]))throw new Error(`Unsupported imported survey ${key}; no fallback is applied.`);
    if(uncertainty){if(uncertainty.enabled!==undefined&&typeof uncertainty.enabled!=='boolean')throw new Error('Uncertainty enabled must be boolean.');for(const[key,min,max]of [['rank_rtol',1e-12,1e-4],['bound_tolerance_m',1e-12,1e-3]])if(uncertainty[key]!==undefined&&(typeof uncertainty[key]!=='number'||!Number.isFinite(uncertainty[key])||uncertainty[key]<min||uncertainty[key]>max))throw new Error(`Unsupported uncertainty ${key}.`);}
    window.RangeLabM6.restoreConfig(config,record.options);
    const o=record.options,u=o.uncertainty || {};
    $('m7Fixed').value=JSON.stringify(o.survey.fixed || [],null,2);$('m7Priors').value=JSON.stringify(o.survey.priors || [],null,2);
    for(const [id,key]of Object.entries({m7TagModel:'tag_height_model',m7Solver:'solver',m7Initialization:'initialization',m7Loss:'loss'}))if(o[key]!==undefined)$(id).value=o[key];
    $('m7Below').checked=!!o.below_beacons;$('m7UncertaintyEnabled').checked=u.enabled!==false;$('m7RankTolerance').value=u.rank_rtol??1e-8;$('m7BoundTolerance').value=u.bound_tolerance_m??1e-7;
    state.importedExperiment=record.experiment || null;
    if(state.importedExperiment){if(![...$('m7Source').options].some(x=>x.value==='imported'))$('m7Source').add(new Option('Reuse observations from imported configuration','imported'));$('m7Source').value='imported';}else $('m7Source').value='controls';
    message('Declared configuration loaded without fitting or data generation.');
  }
  async function submit(e){
    e.preventDefault();let body;try{body=payload();}catch(err){message(err.message,true);return;}
    $('m7Run').disabled=true;message('Submitting declared survey experiment…');
    try{
      const created=await api('/api/m7/runs',{method:'POST',body:JSON.stringify(body)});
      let run=created.run;if(!run){for(let n=0;n<3600;n++){const job=await api(`/api/jobs/${encodeURIComponent(created.id)}`);if(['complete','failed'].includes(job.status)){run=job.run||await api(`/api/m7/runs/${encodeURIComponent(created.id)}`);break;}message(`Survey solver running · ${n+1}s. All outcomes will be retained.`);await new Promise(r=>setTimeout(r,1000));}}
      if(!run)throw new Error('Polling reached its time limit; the saved job can be inspected in Library.');
      run.id ||= created.id;window.RangeLab.state.selectedStart=null;window.RangeLab.renderRun(run);window.RangeLabLibrary.invalidate();message(`Saved survey run · ${run.status}. Every attempted start remains inspectable.`);
    }catch(err){message(`Survey run failed: ${err.message}`,true);window.RangeLabLibrary.invalidate();}
    finally{$('m7Run').disabled=false;}
  }
  function parameterLabel(label,index){if(!label)return `Parameter ${index}`;if(label.kind==='beacon')return `Beacon ${label.beacon_id} · ${label.axis}`;if(label.kind==='tag')return `Tag knots ${(label.knots||[]).join(', ')} · ${label.axis}`;return `${label.kind || 'Physical parameter'} ${index}`;}
  function renderSummary(u){
    state.summary=u;
    $('m7UncertaintySummary').innerHTML=`<b>${u.available?'Conditional local covariance available':'Conditional covariance unavailable'}</b><p>${esc((u.unavailable_reasons||[]).join(' · ') || u.interpretation || 'Inspect the recorded assumptions below.')}</p>`;
    const information=Object.entries(u.information||{});
    $('m7Information').innerHTML=information.length?`<table class="m2-table"><thead><tr><th>INFORMATION SOURCE</th><th>ROWS</th><th>RANK / FREE PARAMETERS</th><th>CONDITION</th></tr></thead><tbody>${information.map(([name,i])=>`<tr><td>${esc(name.replaceAll('_',' '))}</td><td>${esc(i.row_count??'unavailable')}</td><td>${esc(i.rank??'unavailable')} / ${esc(i.parameter_count??'unavailable')}</td><td>${fmt(i.condition_number)}</td></tr>`).join('')}</tbody></table>`:'<p>Information spectra unavailable for this outcome.</p>';
    const sd=u.standard_deviation_m,half=u.marginal_95_half_width_m;
    $('m7ParameterUncertainty').innerHTML=Array.isArray(sd)?`<table class="m2-table"><thead><tr><th>FREE PHYSICAL COORDINATE</th><th>SD (m)</th><th>MARGINAL 95% HALF WIDTH (m)</th></tr></thead><tbody>${sd.map((v,i)=>`<tr><td>${esc(parameterLabel(u.parameter_labels?.[i],i))}</td><td>${fmt(v)}</td><td>${fmt(half?.[i])}</td></tr>`).join('')}</tbody></table>`:'<p>No finite intervals are assigned to unsupported or unobservable directions.</p>';
    const disclosures={method:u.method,coordinate_frame:u.coordinate_frame,parameter_units:u.parameter_units,covariance_units:u.covariance_units,assumptions:u.assumptions,fixed_coordinate_count:u.fixed_coordinate_count,fixed_coordinates_are:u.fixed_coordinates_are,survey_model:u.survey_model,prior_model:u.prior_model,jacobian_definition:u.jacobian_definition,interval_definition:u.interval_definition,interpretation:u.interpretation,limitations:u.limitations,linearization_parameters_m:u.linearization_parameters_m,information:u.information};
    $('m7Assumptions').textContent=JSON.stringify(disclosures,null,2);$('m7ExportUncertainty').disabled=false;
  }
  function onRun(run,start){
    if(!$('m7Workspace'))return;
    state.run=run;state.start=start;
    if(run?.schema_version!=='7.0')state.restoredSource=null;
    if(!window.RangeLabWorkspace && run?.schema_version==='7.0' && state.restoredSource!==(run.id || run)){
      state.restoredSource=run.id || run;
      window.RangeLabM6.restoreConfig(run.experiment.config,run.options);
      const o=run.options,u=o.uncertainty || {};
      $('m7Fixed').value=JSON.stringify(o.survey?.fixed || [],null,2);$('m7Priors').value=JSON.stringify(o.survey?.priors || [],null,2);
      for(const[id,key]of Object.entries({m7TagModel:'tag_height_model',m7Solver:'solver',m7Initialization:'initialization',m7Loss:'loss'}))if(o[key]!==undefined)$(id).value=o[key];
      $('m7Below').checked=!!o.below_beacons;$('m7UncertaintyEnabled').checked=u.enabled!==false;$('m7RankTolerance').value=u.rank_rtol??1e-8;$('m7BoundTolerance').value=u.bound_tolerance_m??1e-7;$('m7Source').value='active';
    }
    const supported=['6.0','7.0'].includes(run?.schema_version);
    $('m7InspectUncertainty').disabled=!supported||!run.id;$('m7ExportRun').disabled=!supported;$('m7ExportCsv').disabled=run?.schema_version!=='7.0'||!run.id;
    $('m7Active').textContent=supported?`Active saved schema ${run.schema_version} · ${run.status} · start ${start?.index??'unavailable'}`:'Open a saved M6 or M7 run to inspect conditional uncertainty.';
    if(run?.schema_version==='7.0'&&start?.diagnostics?.uncertainty)renderSummary(start.diagnostics.uncertainty);
    else{state.summary=null;$('m7ExportUncertainty').disabled=true;$('m7UncertaintySummary').textContent=supported?'Use Inspect saved uncertainty for an explicit offline calculation at this saved start. No solve or data generation occurs.':'Conditional uncertainty is available for M6/M7 source records.';$('m7Information').innerHTML='';$('m7ParameterUncertainty').innerHTML='';$('m7Assumptions').textContent='';}
    $('m7Attempts').innerHTML=supported?(run.starts||[]).map(s=>`<button type="button" class="button button-quiet" data-m7-start="${esc(s.index)}">Start ${esc(s.index)} · ${esc(s.status)}</button><span>${esc(s.solver?.message||s.error||'')}</span>`).join(''):'';
    document.querySelectorAll('[data-m7-start]').forEach(b=>b.onclick=()=>{window.RangeLab.state.selectedStart=+b.dataset.m7Start;window.RangeLab.renderRun(run);});
  }
  async function inspect(){if(!state.run?.id)return;message('Validating saved source and calculating local information…');$('m7InspectUncertainty').disabled=true;try{const summary=await api(`/api/m7/runs/${encodeURIComponent(state.run.id)}/uncertainty?start=${state.start?.index??state.run.selected_start??0}`);renderSummary(summary);message('Offline conditional summary ready. Saved observations and source run remain unchanged.');}catch(e){message(`Uncertainty inspection failed: ${e.message}`,true);}finally{$('m7InspectUncertainty').disabled=false;}}
  function init(){
    const panel=document.createElement('section');panel.id='m7Workspace';panel.className='m7-workspace panel';panel.setAttribute('aria-labelledby','m7Heading');
    panel.innerHTML=`<div class="m2-results-head"><div><div class="eyebrow">M7 · SURVEY KNOWLEDGE AND CONDITIONAL UNCERTAINTY</div><h2 id="m7Heading">Partial survey investigation</h2><p>Declare world-coordinate knowledge separately from gauge conventions. Every outcome is retained.</p></div><button type="button" data-open-library class="button button-quiet">Open Library</button></div><div class="m7-grid"><form id="m7Form" class="m7-form"><p class="m7-disclosure">Survey fitting uses joint map + trajectory, independent beacon heights and physical metre coordinates h. Fixed coordinates are eliminated constraints. Unspecified rigid freedoms remain visible in rank. No canonical gauge is added.</p><label for="m7Source">Observation source</label><select id="m7Source"><option value="controls">Generate new data from current M4 / M6 controls</option><option value="active">Reuse active M6 / M7 saved observations</option></select><div class="field-row"><div><label for="m7TagModel">Tag-height model</label><select id="m7TagModel"><option value="fixed">Fixed height</option><option value="shared">Shared estimated height</option><option value="soft">Soft height prior</option><option value="free">Free 3D knots</option></select></div><div><label for="m7Solver">Solver</label><select id="m7Solver"><option value="trf">Bounded TRF</option><option value="lm">Strict-interior LM</option></select></div></div><div class="field-row"><div><label for="m7Initialization">Initialization</label><select id="m7Initialization"><option value="independent">Independent · truth-free</option><option value="truth_near">Truth-near diagnostic</option></select></div><div><label for="m7Loss">Range loss</label><select id="m7Loss"><option value="gaussian">Gaussian</option><option value="huber">Huber</option><option value="soft_l1">Soft L1</option><option value="cauchy">Cauchy</option><option value="hard_rejection">Hard rejection</option></select></div></div><label class="m7-check"><input id="m7Below" type="checkbox"> Constrain tag below beacons · fixed-height model only</label><div class="m7-frame">Survey frame: <b>world</b> · means: <b>metres</b> · covariance: <b>m²</b> · mask order: <b>X, Y, Z</b></div><label for="m7Fixed">Fixed beacon coordinates · JSON array</label><textarea id="m7Fixed" rows="4" spellcheck="false">[]</textarea><p class="m7-example">Row format: {"beacon_id":0,"mask":[true,true,false],"mean_m":[0,0,0]}. Only selected axes are fixed. Enter independently declared survey values.</p><label for="m7Priors">Uncertain survey priors · JSON array</label><textarea id="m7Priors" rows="5" spellcheck="false">[]</textarea><p class="m7-example">Add covariance_m2 for selected axes, e.g. [[0.01,0],[0,0.01]] for X/Y. Blocks are independent across rows; within-block axis covariance is supported. Cross-beacon covariance and fixed/prior overlaps are rejected.</p><label class="m7-check"><input id="m7UncertaintyEnabled" type="checkbox" checked> Conditional local uncertainty · independent Gaussian ranges with known saved sigma</label><div class="field-row"><div><label for="m7RankTolerance">Relative rank tolerance</label><input id="m7RankTolerance" type="number" min="1e-12" max="1e-4" step="any" value="1e-8"></div><div><label for="m7BoundTolerance">Bound proximity tolerance (m)</label><input id="m7BoundTolerance" type="number" min="1e-12" max="1e-3" step="any" value="1e-7"></div></div><p class="m7-disclosure">Remaining acquisition, noise, contamination, loss scales, height prior, start count and evaluation budget use the M4 / M6 controls above. Unsupported survey constraints fail explicitly; algebraic starts and shared beacon heights are unavailable here.</p><button id="m7Run" type="submit" class="button button-primary">Run declared survey experiment</button><button id="m7ExportConfig" type="button" class="button button-quiet">Export declared configuration</button><button id="m7Import" type="button" class="button button-quiet">Import run / configuration JSON</button><input id="m7ImportFile" type="file" accept="application/json,.json" hidden></form><div class="m7-evidence"><div id="m7Status" class="library-status" role="status" aria-live="polite">Enter declared knowledge, or open an existing M6 / M7 result from Library.</div><p id="m7Active">No M6 / M7 source selected.</p><div class="m7-actions"><button id="m7InspectUncertainty" type="button" class="button button-quiet" disabled>Inspect saved uncertainty</button><button id="m7ExportRun" type="button" class="button button-quiet" disabled>Run JSON</button><button id="m7ExportCsv" type="button" class="button button-quiet" disabled>Complete CSV</button><button id="m7ExportUncertainty" type="button" class="button button-quiet" disabled>Uncertainty JSON</button></div><div id="m7Attempts" class="m7-attempts"></div><div id="m7UncertaintySummary" class="note">Local intervals require supported assumptions and full free-coordinate rank.</div><h3>Information sources</h3><div id="m7Information" class="m2-table-wrap"></div><h3>Conditional free-coordinate intervals</h3><div id="m7ParameterUncertainty" class="m2-table-wrap"></div><details class="m7-assumptions"><summary>Assumptions, Jacobians, rank thresholds and linearization</summary><pre id="m7Assumptions"></pre></details><p class="m7-disclosure">Full local rank is not uniqueness. Intervals exclude undiscovered/reflected geometries. Robust weights and positive robust curvature are conditioning diagnostics; they are not calibrated covariance. Active bounds, selection, contamination, correlation, quantization and model mismatch can invalidate Gaussian intervals. This interface makes no coverage calibration claim.</p></div></div>`;
    document.querySelector('#experimentView .page-footer').before(panel);
    $('m7Import').onclick=()=>$('m7ImportFile').click();$('m7ImportFile').onchange=async e=>{try{const f=e.target.files?.[0];if(!f)return;const raw=JSON.parse(await f.text()),record=raw.run || raw;if(record.artifact_type==='experiment_config')importConfig(record);else{const saved=await api('/api/m7/import',{method:'POST',body:JSON.stringify(record)});const run=saved.run || saved;run.id ||= saved.id;window.RangeLab.state.selectedStart=null;window.RangeLab.renderRun(run);window.RangeLabLibrary.invalidate();message('M7 source imported and retained without fitting.');}}catch(err){message(`Import failed: ${err.message}`,true);}finally{e.target.value='';}};
    $('m7Form').onsubmit=submit;$('m7InspectUncertainty').onclick=inspect;
    $('m7ExportUncertainty').onclick=()=>{if(state.summary)download(`uncertainty-${state.run?.id||'saved'}-start${state.start?.index??0}.json`,state.summary);};
    $('m7ExportRun').onclick=()=>{if(state.run)download(`m7-source-${state.run.id||'embedded'}.json`,state.run);};
    $('m7ExportCsv').onclick=async()=>{try{const r=await fetch(`/api/m7/runs/${encodeURIComponent(state.run.id)}/csv`);if(!r.ok)throw new Error((await r.json()).error||r.statusText);download(`m7-${state.run.id}.csv`,await r.text(),'text/csv');}catch(e){message(e.message,true);}};
    $('m7ExportConfig').onclick=()=>{try{download('m7-declared-configuration.json',{schema_version:'7.0',artifact_type:'experiment_config',...payload()});}catch(e){message(e.message,true);}};
    onRun(window.RangeLab.state.activeRun,window.RangeLab.state.start);
  }
  window.RangeLabM7={onRun,formPayload:payload,importConfig,inspect};document.addEventListener('DOMContentLoaded',init);
})();
