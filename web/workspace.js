/* Unified drafts and read-only inspection; numerical engines keep native formats. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id), clone = v => structuredClone(v);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const api = (url, body) => window.RangeLab.api(url, body === undefined ? undefined : {method:'POST',body:JSON.stringify(body)});
  const state = {draft:null, capabilities:null, active:null, artifact:null, tab:'overview', busy:false, sourceKey:null, revision:0};
  const names = {scenario:'Reference geometry', samples:'Display samples / cycles',duration_s:'Duration (s)',seed:'Seed',noise_std_m:'Injected noise σ (m)',assumed_std_m:'Assumed range σ (m)',
    max_nfev:'Evaluation budget per start', starts:'Physical starts',mode:'Map knowledge',fixed_tag_z_m:'Tag-height datum / prior target (m)',prior_sigma_m:'Motion prior σ (m; 0 disables)',
    height_prior_sigma_m:'Height prior σ (m)',height_parameterization:'Height coordinate',initialization_error_m:'Physical start perturbation σ (m)',algebraic_physical_tolerance:'Algebraic consistency tolerance',
    knot_spacing_s:'Trajectory knot spacing (s; 0 uses cycle grid)',timing_model:'Estimator timing model', below_beacons:'Constrain tag below beacons',loss_scale_sigma:'Range loss scale (σ)',rejection_threshold_sigma:'Rejection threshold (σ)',weight_decision_threshold:'Decision flag threshold',
    timestamp_offset_s:'Supplied timestamp offset (s)',timestamp_jitter_s:'Supplied timestamp jitter (s)',delivery_latency_s:'Delivery latency (s)',spacing_s:'Within-cycle spacing (s)',cycle_rate_hz:'Cycle rate (Hz)',jitter_s:'Acquisition jitter (s)',
    geometry:'Layout geometry',count:'Beacon count',height_m:'Nominal beacon height (m)',height_spread_m:'Beacon height spread (m)',baseline_scale:'Horizontal baseline scale',coordinates_m:'Explicit beacon XYZ (m; optional)',offsets_m:'Per-beacon range offsets (m)',
    frame:'Coordinate frame',units:'Units',rank_rtol:'Relative rank tolerance',bound_tolerance_m:'Bound proximity tolerance (m)'};
  const choice = {
    scenario:['informative','straight_line','narrow_coverage','nearly_collinear'],mode:['joint','known_map'],
    tag_height_model:['fixed','shared','soft','free'],beacon_height_model:['shared','independent'],timing_model:['timestamp_aware','grouped'],solver:['trf','lm'],height_parameterization:['h','q'],initialization:['independent','truth_near','algebraic'],loss:['gaussian','huber','soft_l1','cauchy','hard_rejection'],
    'physical.path.type':['line','circle','arc','rectangle','figure_eight','waypoint'],
    'physical.motion.profile':['constant','variable','stationary'],
    'physical.beacon_layout.geometry':['equal','diverse','near_collinear','collinear'],
    'physical.truth_height.type':['planar','tilted','excursion','spatial']
  };
  const title = value => names[value] || String(value).replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase()).replace(/ M2$/,' (m²)').replace(/ M$/,' (m)').replace(/ S$/,' (s)').replace(/ Deg$/,' (degrees)');
  const label = value => ({joint:'Estimate map and trajectory',known_map:'Known surveyed map',truth_near:'Truth-near · diagnostic only',q:'q = h² (m²)',h:'h (m)',trf:'Bounded TRF',lm:'Strict-interior LM',gaussian:'Gaussian least squares',timestamp_aware:'Timestamp-aware',grouped:'Grouped simultaneous approximation'})[value] || title(value);
  const get = path => path.split('.').reduce((o,k)=>o?.[k],state.draft);
  function set(path,value) {const keys=path.split('.');let o=state.draft;keys.slice(0,-1).forEach(k=>o=o[k] ||= {});o[keys.at(-1)]=value;state.revision++;changed();}
  function message(text,error=false) {$('workspaceStatus').textContent=text;$('workspaceStatus').classList.toggle('is-error',error);}
  function changed() {
    $('workspaceDraftState').textContent=state.active ? 'Editable draft is separate from the displayed saved result. Run explicitly to produce a new result.' : 'Draft configuration · no result has been generated';
    $('workspaceSourceSummary').textContent=state.draft.observation_source.kind==='saved'?`Reusing exact saved observations: ${state.draft.observation_source.key}. Physical settings and saved σ must match the source.`:'New observations will be generated only when Run is selected.';
    $('workspaceRun').textContent=state.draft.study.kind==='parameter'?'Run study':'Run experiment';
    $('workspaceDraftJson').textContent=JSON.stringify(state.draft,null,2);
    try {sessionStorage.setItem('rangelab-workspace-draft-v1',JSON.stringify(state.draft));}catch(_){}
  }
  function field(path,value) {
    const key=path.split('.').at(-1),id='ws_'+path.replaceAll('.','_');
    const box=document.createElement('label');box.className='workspace-field';box.htmlFor=id;
    const caption=document.createElement('span');caption.textContent=title(key);box.append(caption);
    let input;
    const options=choice[path] || choice[key];
    if(options){input=document.createElement('select');const values=[...new Set([value,...options])].filter(x=>x!==undefined);input.innerHTML=values.map(v=>`<option value="${esc(v)}">${esc(label(v))}</option>`).join('');input.value=value;}
    else if(typeof value==='boolean'){input=document.createElement('input');input.type='checkbox';input.checked=value;}
    else if(Array.isArray(value)||value===null){input=document.createElement('textarea');input.rows=2;input.value=JSON.stringify(value);input.dataset.json='true';input.spellcheck=false;}
    else {input=document.createElement('input');input.type=typeof value==='number'?'number':'text';input.step='any';input.value=value;}
    input.id=id;input.dataset.path=path;input.setAttribute('aria-label',title(key));
    const apply=()=>{try {const v=input.dataset.json?JSON.parse(input.value):input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value;if(typeof v==='number'&&!Number.isFinite(v))throw Error('Enter a finite number');set(path,v);input.setCustomValidity('');}catch(e){input.setCustomValidity(e.message);input.reportValidity();}};input.addEventListener('input',apply);input.addEventListener('change',apply);input.addEventListener('blur',apply);
    box.append(input);return box;
  }
  function objectFields(target,path,value) {
    for(const [key,v] of Object.entries(value || {})) {
      if(path==='assumptions'&&key==='survey')continue;
      if(v && typeof v==='object'&&!Array.isArray(v)){const group=document.createElement('fieldset');group.className='workspace-subgroup';const legend=document.createElement('legend');legend.textContent=title(key);group.append(legend);objectFields(group,path+'.'+key,v);target.append(group);}
      else target.append(field(path+'.'+key,v));
    }
  }
  async function adoptCandidate(candidate){const result=await api('/api/workspace/validate',candidate);state.draft=result.configuration;renderForm();}
  function surveyEditor(target) {
    const survey=state.draft.assumptions.survey;if(!survey)return;
    const section=document.createElement('div');section.className='survey-editor';
    section.innerHTML='<p>Declared survey knowledge · world frame · means in metres · covariance in m². Fixed coordinates are constraints, separate from gauge conventions.</p><div class="survey-scroll"><table><thead><tr><th>Beacon</th><th>Knowledge</th><th>Axes</th><th>Mean XYZ (m)</th><th>Selected-axis covariance (m²)</th><th></th></tr></thead><tbody id="workspaceSurveyRows"></tbody></table></div><button type="button" id="workspaceAddSurvey" class="button button-quiet">Add survey row</button><details><summary>Advanced survey JSON</summary><label class="workspace-field">Exact declaration<textarea id="workspaceSurveyJson" rows="7" spellcheck="false"></textarea></label><button type="button" id="workspaceApplySurvey" class="button button-quiet">Apply survey JSON to draft</button></details><p class="note">Independent blocks only; within-block axis covariance is supported. Cross-beacon coupling and fixed/prior overlaps reject explicitly.</p>';
    target.append(section);
    const rows=()=>[...survey.fixed.map((r,i)=>({r,kind:'fixed',i})),...survey.priors.map((r,i)=>({r,kind:'priors',i}))];
    rows().forEach(({r,kind,i})=>{const tr=document.createElement('tr');tr.innerHTML=`<td><input aria-label="Beacon ID" type="number" min="0" value="${r.beacon_id}" data-col="beacon_id"></td><td><select aria-label="Knowledge type" data-col="kind"><option value="fixed">Fixed</option><option value="priors">Uncertain prior</option></select></td><td>${r.mask.map((v,a)=>`<label>${'XYZ'[a]}<input type="checkbox" aria-label="${'XYZ'[a]} selected" data-axis="${a}" ${v?'checked':''}></label>`).join('')}</td><td><textarea aria-label="Mean XYZ metres" data-col="mean_m" rows="2">${esc(JSON.stringify(r.mean_m))}</textarea></td><td><textarea aria-label="Selected-axis covariance square metres" data-col="covariance_m2" rows="2" ${kind==='fixed'?'disabled':''}>${esc(JSON.stringify(r.covariance_m2 || [[.01]]))}</textarea></td><td><button type="button" aria-label="Remove survey row">×</button></td>`;
      tr.querySelector('[data-col="kind"]').value=kind;
      tr.querySelector('button').onclick=()=>{survey[kind].splice(i,1);changed();renderForm();};
      tr.onchange=()=>{try {const next=clone(r);next.beacon_id=Number(tr.querySelector('[data-col="beacon_id"]').value);next.mask=[...tr.querySelectorAll('[data-axis]')].map(n=>n.checked);next.mean_m=JSON.parse(tr.querySelector('[data-col="mean_m"]').value);const newKind=tr.querySelector('[data-col="kind"]').value;if(newKind==='priors')next.covariance_m2=JSON.parse(tr.querySelector('[data-col="covariance_m2"]').value);else delete next.covariance_m2;survey[kind].splice(i,1);survey[newKind].push(next);changed();renderForm();}catch(e){message('Survey row: '+e.message,true);}};
      $('workspaceSurveyRows').append(tr);
    });
    $('workspaceSurveyJson').value=JSON.stringify(survey,null,2);
    $('workspaceAddSurvey').onclick=()=>{survey.fixed.push({beacon_id:0,mask:[true,false,false],mean_m:[0,0,0]});changed();renderForm();};
    $('workspaceApplySurvey').onclick=async()=>{try {const candidate=clone(state.draft);candidate.assumptions.survey=JSON.parse($('workspaceSurveyJson').value);await adoptCandidate(candidate);message('Survey JSON validated and applied to draft. No fitting performed.');}catch(e){message(e.message,true);}};
  }
  function renderForm() {
    const open=[...document.querySelectorAll('#workspaceGroups > details[open]')].map(n=>n.dataset.group);
    $('workspaceGroups').replaceChildren();
    const groups=['Geometry','Motion and acquisition','Measurement model','Estimator assumptions','Numerical method','Study design'];
    const targets=groups.map((name,i)=>{const d=document.createElement('details');d.dataset.group=name;d.open=open.length?open.includes(name):i===0;const summary=document.createElement('summary');summary.textContent=name;d.append(summary);const div=document.createElement('div');div.className='workspace-fields';d.append(div);$('workspaceGroups').append(d);return div;});
    const physical=state.draft.physical;
    for(const[key,v]of Object.entries(physical)) {const ix=['motion','acquisition'].includes(key)?1:['noise_std_m','contamination','seed'].includes(key)?2:0;if(v&&typeof v==='object'&&!Array.isArray(v)){const sub=document.createElement('fieldset');sub.innerHTML=`<legend>${esc(title(key))}</legend>`;objectFields(sub,'physical.'+key,v);targets[ix].append(sub);}else targets[ix].append(field('physical.'+key,v));}
    // Optional native geometry/path fields are explicit and editable, without changing defaults.
    const optional=document.createElement('details');optional.innerHTML='<summary>Optional path and explicit beacon coordinates</summary><p>Enter native path settings or a beacon XYZ array. Applying them changes only the draft.</p><textarea id="workspaceGeometryJson" rows="5" aria-label="Optional geometry JSON"></textarea><button id="workspaceApplyGeometry" type="button" class="button button-quiet">Apply optional geometry</button>';
    targets[0].append(optional);$('workspaceGeometryJson').value=JSON.stringify({path:physical.path || {type:'rectangle',center_m:[5,4],size_m:[7,5.6],scale:1,rotation_deg:0},...(physical.beacon_layout?{coordinates_m:physical.beacon_layout.coordinates_m || null}:{})},null,2);
    $('workspaceApplyGeometry').onclick=async()=>{try{const candidate=clone(state.draft),physical=candidate.physical;const value=JSON.parse($('workspaceGeometryJson').value);if(Object.keys(value).some(k=>!['path','coordinates_m'].includes(k)))throw Error('Only path and coordinates_m are supported here');if(value.path)physical.path=value.path;else delete physical.path;if(physical.beacon_layout){if(value.coordinates_m)physical.beacon_layout.coordinates_m=value.coordinates_m;else delete physical.beacon_layout.coordinates_m;}await adoptCandidate(candidate);message('Geometry validated and applied to draft.');}catch(e){message(e.message,true);}};
    objectFields(targets[3],'assumptions',state.draft.assumptions);surveyEditor(targets[3]);objectFields(targets[4],'numerical',state.draft.numerical);
    targets[3].prepend(Object.assign(document.createElement('p'),{className:'note',textContent:'Assumptions supplied to the estimator; synthetic truth and injected labels are not independent fitting inputs. Survey knowledge and coordinate gauge choices have distinct meanings.'}));
    renderStudy(targets[5]);$('workspaceEngine').value=state.draft.engine;$('workspaceObservationSource').value=state.draft.observation_source.kind;changed();
  }
  function renderStudy(target) {
    const study=state.draft.study,model=state.capabilities.models[state.draft.engine];
    const kind=document.createElement('label');kind.className='workspace-field';kind.innerHTML='<span>Execution</span><select id="workspaceStudyKind" aria-label="Execution"><option value="single">Single fit</option><option value="parameter">Parameter study</option></select>';target.append(kind);$('workspaceStudyKind').value=study.kind;
    $('workspaceStudyKind').onchange=()=>{state.draft.study={kind:$('workspaceStudyKind').value};if(state.draft.study.kind==='parameter'){state.draft.study.factor=model.study_factors[0];state.draft.study.values=state.draft.engine==='spatial'?[3,4]:state.draft.engine==='solver'?[0,1]:[0,.05];state.draft.study.seeds=[7,8];}changed();renderForm();};
    if(study.kind!=='parameter')return;
    if(!model.study_factors.length){target.append(Object.assign(document.createElement('p'),{textContent:'This model has no native parameter-study engine. Single fits can reuse saved observations.'}));return;}
    const row=document.createElement('label');row.className='workspace-field';row.innerHTML='<span>Swept factor</span><select id="workspaceFactor" aria-label="Swept factor">'+model.study_factors.map(k=>`<option value="${k}">${esc(title(k))}</option>`).join('')+'</select>';target.append(row);$('workspaceFactor').value=study.factor;$('workspaceFactor').onchange=()=>set('study.factor',$('workspaceFactor').value);
    target.append(field('study.values',study.values),field('study.seeds',study.seeds));
    const comparison=document.createElement('p');comparison.className='note';comparison.textContent='Compared variants: '+(study.variants || model.default_variants || []).map(v=>v.label+': '+JSON.stringify(v.options || (v.max_nfev?{max_nfev:v.max_nfev}:{}))).join(' · ');target.append(comparison);
    const variants=document.createElement('details');variants.innerHTML='<summary>Named estimator variants</summary><p>Use native variant definitions. Empty means the engine’s recorded default comparison. Timing always compares timestamp-aware and grouped models.</p><textarea id="workspaceVariants" rows="5" aria-label="Named estimator variants JSON"></textarea><button id="workspaceApplyVariants" class="button button-quiet" type="button">Apply variants</button>';target.append(variants);$('workspaceVariants').value=JSON.stringify(study.variants || (state.draft.engine==='timing'?null:model.default_variants) || null,null,2);$('workspaceApplyVariants').onclick=async()=>{try{const v=JSON.parse($('workspaceVariants').value),candidate=clone(state.draft);if(v===null)delete candidate.study.variants;else candidate.study.variants=v;await adoptCandidate(candidate);message('Named variants validated and applied to draft.');}catch(e){message(e.message,true);}};
  }
  function tab(name) {
    state.tab=name;document.querySelectorAll('[data-workspace-tab]').forEach(b=>{b.setAttribute('aria-selected',String(b.dataset.workspaceTab===name));b.tabIndex=b.dataset.workspaceTab===name?0:-1;});
    document.querySelectorAll('[data-workspace-pane]').forEach(p=>p.hidden=p.dataset.workspacePane!==name);
    requestAnimationFrame(()=>document.querySelectorAll('[data-workspace-pane]:not([hidden]) .js-plotly-plot').forEach(n=>window.Plotly?.Plots?.resize(n)));
  }
  function download(name,value,type='application/json'){let text=typeof value==='string'?value:JSON.stringify(value,null,2);if(type.startsWith('application/json'))text=text.replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));const u=URL.createObjectURL(new Blob([text],{type:type+';charset=utf-8'}));const a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}
  async function useConfiguration(reuse=false) {
    if(!state.active)return;
    try {const key=state.sourceKey || (state.active.id?'run:'+state.active.id:null);const body=reuse?{key,reuse:true}:{run:state.active};const r=await api('/api/workspace/configuration',body);state.draft=r.configuration;renderForm();message(reuse?'Draft now reuses the exact saved observations.':'Saved settings copied to the editable draft. The displayed result is unchanged.');}
    catch(e){renderForm();message('Configuration cannot be copied: '+e.message,true);}
  }
  function onRun(run) {
    if(!state.ready || !run)return;
    if(state.artifact?.entries&&!state.artifact.entries.some(e=>e.run===run)){state.artifact=null;$('workspaceStudySource').textContent='No study open.';$('workspaceStudySummary').textContent='No study open.';}
    state.comparison=null;document.body.classList.remove('workspace-comparing');state.active=run;
    document.querySelector('.m3-playback').hidden=false;document.querySelectorAll('[data-layer],#coordinateMode').forEach(n=>n.disabled=false);
    $('workspaceInspectA').hidden=$('workspaceInspectB').hidden=true;$('workspaceExportRun').textContent='Run JSON';
    if(state.sourceKey?.startsWith('run:') && state.sourceKey!=='run:'+run.id)state.sourceKey=run.id?'run:'+run.id:null;
    const ordinal=state.artifact?.entries?.findIndex(e=>e.run===run || e.run?.id&&e.run.id===run.id);
    if(ordinal>=0&&state.artifact?.id)state.sourceKey=`artifact:${state.artifact.id}:entry:${ordinal}`;
    const selected=window.RangeLab.state.start;
    $('workspaceResultTitle').textContent=`${run.experiment?.config?.scenario || 'Saved experiment'} · ${run.status} · ${String(run.id || 'embedded source').slice(0,8)}`;
    $('workspaceUseConfig').disabled=false;$('workspaceReuse').disabled=false;
    const select=$('workspaceAttempt');select.innerHTML=(run.starts||[]).map(s=>`<option value="${esc(s.index)}">Start ${esc(s.index)} · ${esc(s.status)}${s.error?' · '+esc(s.error):''}</option>`).join('');select.value=selected?.index ?? run.selected_start;select.disabled=!run.starts?.length;
    $('workspaceAttempts').innerHTML=`<h3>Active run physical starts · ${esc(String(run.id || 'embedded source').slice(0,8))}</h3>`+((run.starts||[]).length?`<div class="workspace-table-scroll"><table><thead><tr><th>Start</th><th>Outcome</th><th>Termination / failure</th></tr></thead><tbody>${run.starts.map(s=>`<tr><td><button class="text-button" type="button" data-workspace-start="${esc(s.index)}">${esc(s.index)}</button></td><td>${esc(s.status)}</td><td>${esc(s.error || s.solver?.message || 'Unavailable')}</td></tr>`).join('')}</tbody></table></div>`:`<p>${esc(run.error || 'No completed attempts recorded.')}</p>`);
    document.querySelectorAll('[data-workspace-start]').forEach(b=>b.onclick=()=>{window.RangeLab.state.selectedStart=+b.dataset.workspaceStart;window.RangeLab.renderRun(run);});
    $('workspaceProvenance').textContent=JSON.stringify({id:run.id,schema_version:run.schema_version,status:run.status,options:run.options,configuration:run.experiment?.config,units:run.experiment?.units,coordinate_convention:run.experiment?.coordinate_convention,run_diagnostics:run.diagnostics,software_versions:run.software_versions || run.experiment?.software_versions,source_id:run.source_id,workspace_configuration:run.workspace_configuration,selected_start:selected},null,2);
    const failure=run.error || selected?.error;$('workspaceFailure').textContent=failure || '';$('workspaceFailure').hidden=!failure;
    $('workspaceUnavailable').textContent=['6.0','7.0'].includes(run.schema_version)?'Conditional intervals are available only for supported assumptions and full free-coordinate rank. Inspect the selected saved start explicitly.':'Conditional intervals are unavailable for this historical representation; native rank and spectrum remain available.';
    // Hide irrelevant specialized plots instead of showing diagnostics from a previous result.
    document.querySelectorAll('[data-native-versions]').forEach(n=>{n.hidden=!n.dataset.nativeVersions.split(',').includes(run.schema_version);});
    refreshStudy();changed();
  }
  function openRun(run,key) {state.sourceKey=key || (run.id?'run:'+run.id:null);window.RangeLab.state.selectedStart=null;window.RangeLab.renderRun(run);}
  function openArtifact(artifact) {
    state.artifact=artifact;
    window.RangeLabLibrary?.show('experiment',false);
    const version=String(artifact.schema_version).split('.')[0];
    window[`RangeLabM${version}`]?.openArtifact?.(artifact);
    if(artifact.artifact_type!=='comparison'&&artifact.entries?.[0]?.run)openRun(artifact.entries[0].run,artifact.id?`artifact:${artifact.id}:entry:0`:null);
    const entries=artifact.entries || [],config=artifact.config || {},cells=Array.isArray(config.values)&&Array.isArray(config.seeds)?config.values.length*config.seeds.length:null,variantCount=Array.isArray(config.variants)?config.variants.length:artifact.artifact_type==='timing_sweep'?2:null,scheduled=cells!==null&&variantCount!==null?cells*variantCount:null,unattempted=scheduled!==null&&scheduled>=entries.length?scheduled-entries.length:'unavailable';
    const attemptedCells=entries.every(e=>e.value!==undefined&&e.seed!==undefined)?new Set(entries.map(e=>JSON.stringify([e.value,e.seed]))).size:null;
    $('workspaceStudySummary').textContent=`${artifact.status} · ${entries.length} recorded runs · ${entries.reduce((n,e)=>n+(e.run?.starts?.length || 0),0)} retained attempts · ${cells??'unavailable'} scheduled data cells · ${unattempted} unattempted runs · ${cells!==null&&attemptedCells!==null&&cells>=attemptedCells?cells-attemptedCells:'unavailable'} unattempted data cells. Every outcome remains in the table.`;
    $('workspaceStudySource').textContent=JSON.stringify({id:artifact.id,schema_version:artifact.schema_version,artifact_type:artifact.artifact_type,status:artifact.status,config:artifact.config,aggregate:artifact.aggregate,error:artifact.error,unattempted_cells:artifact.unattempted_cells,diagnostics:artifact.diagnostics},null,2);
    refreshStudy();tab('attempts');
  }
  function refreshStudy(){$('m2Results').hidden=!(state.artifact?.artifact_type==='sweep'||state.comparison);const engine={'2.0':'planar','3.0':'timing','4.0':'spatial','5.0':'solver','6.0':'robust'}[state.artifact?.schema_version];document.querySelectorAll('[data-study-engine]').forEach(n=>n.hidden=n.dataset.studyEngine!==engine);}

  async function submit(event) {
    event.preventDefault();if(state.busy)return;state.busy=true;$('workspaceRun').disabled=true;message('Validating explicit model and source…');
    const submitted=clone(state.draft);
    try {
      await api('/api/workspace/validate',submitted);
      const study=submitted.study.kind==='parameter',created=await api('/api/workspace/'+(study?'studies':'runs'),submitted);
      state.job=created.id;message(`Running ${study?'study':'experiment'} · ${state.capabilities.models[created.engine].label} · ${created.id.slice(0,8)}. Previous result remains available.`);
      for(let i=0;i<7200;i++) {
        const job=await api('/api/jobs/'+created.id);
        if(!['running','pending'].includes(job.status)) {
          if(job.artifact)openArtifact(job.artifact);
          else if(job.run)openRun(job.run,'run:'+created.id);
          message(`${study?'Study':'Experiment'} saved · ${job.artifact?.status || job.run?.status || job.status}${job.error?' · '+job.error:''}`,job.status==='failed');window.RangeLabLibrary.invalidate();break;
        }
        await new Promise(resolve=>setTimeout(resolve,500));
        if(i===7199)message('Job still running. Its saved request remains available in Library.');
      }
    }catch(e){message('Request failed: '+e.message,true);window.RangeLabLibrary.invalidate();}
    finally{state.busy=false;$('workspaceRun').disabled=false;}
  }
  function move(node,target){if(node)target.append(node);}
  function chart(id,pane,versions){const node=$(id)?.closest('.chart-card') || $(id);if(node){move(node,pane);if(versions)node.dataset.nativeVersions=versions;}}
  function layout() {
    const main=$('experimentView');
    const controls=document.createElement('aside');controls.id='workspaceControls';controls.className='workspace-controls panel';
    controls.innerHTML='<div class="workspace-control-heading"><h2>Experiment configuration</h2><button id="workspaceCloseControls" class="button button-quiet" type="button">Close</button></div><form id="workspaceForm"><label class="workspace-field">Numerical model<select id="workspaceEngine" aria-label="Numerical model"></select></label><p class="note">Model selection is explicit. Unsupported combinations reject without fallback.</p><label class="workspace-field">Observation source<select id="workspaceObservationSource" aria-label="Observation source" aria-describedby="workspaceSourceSummary"><option value="generate">Generate new observations</option><option value="saved">Reuse displayed saved observations</option></select></label><p id="workspaceSourceSummary" class="note"></p><div id="workspaceGroups"></div><div class="workspace-run-actions"><button id="workspaceRun" class="button button-primary" type="submit">Run experiment</button><button id="workspaceValidate" class="button button-quiet" type="button">Validate draft</button></div><p id="workspaceStatus" role="status" aria-live="polite">Loading model capabilities…</p></form>';
    const frame=document.createElement('section');frame.id='unifiedWorkspace';frame.className='unified-workspace';main.prepend(frame);frame.append(controls);
    const content=document.createElement('div');content.className='workspace-inspection';frame.append(content);
    const heading=document.createElement('div');heading.className='workspace-result-heading';heading.innerHTML='<div><div class="eyebrow">EXPERIMENT AND EVIDENCE</div><h1>RangeLab</h1><p id="workspaceResultTitle">Configure an experiment or open a saved result.</p></div><button id="workspaceToggleControls" type="button" class="button button-quiet">Configuration</button>';content.append(heading);
    const toolbar=document.createElement('div');toolbar.className='workspace-inspection-toolbar';toolbar.innerHTML='<label>Physical start<select id="workspaceAttempt" disabled></select></label><button id="workspaceUseConfig" type="button" class="button button-quiet" disabled>Use configuration</button><button id="workspaceReuse" type="button" class="button button-quiet" disabled>Reuse observations</button><button id="workspaceInspectA" type="button" class="button button-quiet" hidden>Inspect A</button><button id="workspaceInspectB" type="button" class="button button-quiet" hidden>Inspect B</button><button id="workspaceExportRun" type="button" class="button button-quiet">Run JSON</button><button id="workspaceExportCsv" type="button" class="button button-quiet">Complete CSV</button><button id="workspaceExportDraft" type="button" class="button button-quiet">Draft JSON</button>';content.append(toolbar);
    move(document.querySelector('.scene-panel'),content);
    const compareExports=document.createElement('span');compareExports.className='workspace-comparison-exports';toolbar.append(compareExports);
    for(const id of ['exportCompareJson','exportComparePng'])move($(id),compareExports);
    const comparePlaceholder=$('comparisonScene').closest('.chart-card');comparePlaceholder.hidden=true;
    move(document.querySelector('.m3-playback'),content);$('m3PlaybackTitle').textContent='Open or run an experiment to inspect individual pings.';
    const draft=document.createElement('p');draft.id='workspaceDraftState';draft.className='workspace-draft-state';content.append(draft);
    const failure=document.createElement('p');failure.id='workspaceFailure';failure.hidden=true;failure.className='warning-banner';content.append(failure);
    const tabs=document.createElement('div');tabs.className='workspace-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Result diagnostics');
    const tabNames={overview:'Overview',residuals:'Residuals',geometry:'Geometry and timing',information:'Observability and uncertainty',attempts:'Attempts and study results',provenance:'Configuration and provenance'};
    tabs.innerHTML=Object.entries(tabNames).map(([key,name])=>`<button id="workspaceTab_${key}" type="button" role="tab" aria-controls="workspacePane_${key}" data-workspace-tab="${key}">${name}</button>`).join('');content.append(tabs);
    const panes={};for(const key of Object.keys(tabNames)){const pane=document.createElement('section');pane.id='workspacePane_'+key;pane.dataset.workspacePane=key;pane.className='workspace-pane';pane.setAttribute('role','tabpanel');pane.setAttribute('aria-labelledby','workspaceTab_'+key);panes[key]=pane;content.append(pane);}
    move(document.querySelector('.evidence-heading'),panes.overview);move($('warningBanner'),panes.overview);move($('metrics'),panes.overview);
    for(const id of ['residualChart','residualBeaconChart','residualTimeChart'])chart(id,panes.residuals);
    for(const id of ['positionChart','mapChart','m3SpeedChart'])chart(id,panes.geometry);
    for(const id of ['m4HeightChart','m4PlaneChart'])chart(id,panes.geometry,'4.0,5.0,6.0,7.0');
    chart('spectrumChart',panes.information);move(document.querySelector('.diagnostics-panel'),panes.information);
    for(const id of ['m6ResidualChart','m6CoverageChart'])chart(id,panes.residuals,'6.0,7.0');
    const uncertainty=document.createElement('section');uncertainty.className='workspace-uncertainty';uncertainty.innerHTML='<h3>Conditional local uncertainty</h3><p id="workspaceUnavailable">Open a saved result to inspect supported uncertainty.</p>';panes.information.append(uncertainty);
    for(const id of ['m7InspectUncertainty','m7ExportUncertainty','m7UncertaintySummary','m7Information','m7ParameterUncertainty','m7Assumptions'])move($(id)?.closest('.m7-assumptions') || $(id),uncertainty);
    panes.attempts.innerHTML='<div id="workspaceAttempts">No attempts loaded.</div><h3>Study source and cell accounting</h3><p id="workspaceStudySummary">No study open.</p><details><summary>Complete study configuration and cell accounting</summary><pre id="workspaceStudySource">No study open.</pre></details>';
    // Native study renderers retain their tables, counts, charts and exports.
    move($('m2Results'),panes.attempts);
    for(const [engine,ids] of Object.entries({timing:['m3SweepChart','m3AllStarts','m3ExportJson','m3ExportCsv'],spatial:['m4SweepChart','m4AllStarts','m4ExportJson','m4ExportCsv','m4ExportPng'],solver:['m5Chart','m5GeometryChart','m5AttemptTable','m5ExportJson','m5ExportCsv'],robust:['m6BenchmarkChart','m6AttemptTable','m6ExportJson','m6ExportCsv','m6ExportObservationCsv']})){const group=document.createElement('section');group.dataset.studyEngine=engine;group.hidden=true;panes.attempts.append(group);for(const id of ids)move($(id)?.closest('.chart-card') || $(id),group);}
    for(const [id,versions] of [['m3NumericalDisclosure','3.0'],['m4Disclosure','4.0,5.0,6.0'],['m5Summary','5.0'],['m6Summary','6.0,7.0']]){const node=$(id);node.dataset.nativeVersions=versions;node.hidden=true;move(node,id==='m6Summary'?panes.residuals:panes.information);}
    const extra=document.createElement('details');extra.innerHTML='<summary>Detailed per-range decisions</summary>';move($('m6ObservationTable'),extra);panes.residuals.append(extra);
    panes.provenance.innerHTML='<h3>Original saved source and selected attempt</h3><pre id="workspaceProvenance">No result open.</pre><details><summary>Editable draft configuration</summary><pre id="workspaceDraftJson"></pre></details><label class="workspace-field">Import exact workspace draft JSON<textarea id="workspaceImportDraft" rows="5"></textarea></label><button id="workspaceApplyDraft" type="button" class="button button-quiet">Apply draft JSON</button>';
    // Historical modules remain read-only render adapters. Their unused form roots
    // are detached from the live document after initialization, not a second UI.
    const legacy=document.createElement('div');legacy.id='workspaceLegacyAdapters';legacy.hidden=true;main.append(legacy);
    [...main.children].filter(n=>n!==frame&&n!==legacy&&n.className!=='active-result-context').forEach(n=>legacy.append(n));
    legacy.querySelectorAll('form').forEach(form=>form.remove());
    // Keep internal render targets for native export handlers, out of keyboard/layout flow.
    document.querySelector('.top-context').textContent='Range-only localization and map recovery';
    document.querySelectorAll('[data-workspace-tab]').forEach(b=>{b.onclick=()=>tab(b.dataset.workspaceTab);b.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const all=[...tabs.children];let i=all.indexOf(b);i=e.key==='Home'?0:e.key==='End'?all.length-1:(i+(e.key==='ArrowRight'?1:-1)+all.length)%all.length;all[i].click();all[i].focus();}};});tab('overview');
    $('workspaceForm').onsubmit=submit;
    $('importFile').addEventListener('change',async e=>{e.stopImmediatePropagation();try{const file=e.target.files?.[0];if(file)await importSource(file);}catch(err){message('Import failed: '+err.message,true);}finally{e.target.value='';}},true);
    $('workspaceValidate').onclick=async()=>{try {const r=await api('/api/workspace/validate',state.draft);message(`Valid configuration · ${state.capabilities.models[r.engine].label}. No data generated or fit performed.`);}catch(e){message(e.message,true);}};
    $('workspaceAttempt').onchange=()=>{window.RangeLab.state.selectedStart=+$('workspaceAttempt').value;window.RangeLab.renderRun(state.active);};
    $('workspaceUseConfig').onclick=()=>useConfiguration();$('workspaceReuse').onclick=()=>useConfiguration(true);
    $('workspaceEngine').onchange=()=>{const next=$('workspaceEngine').value;state.draft=clone(state.capabilities.models[next].defaults);renderForm();message('Selected model defaults loaded into draft explicitly. Saved result unchanged.');};
    $('workspaceObservationSource').onchange=()=>{if($('workspaceObservationSource').value==='saved')useConfiguration(true);else {state.draft.observation_source={kind:'generate'};changed();}};
    $('workspaceInspectA').onclick=()=>inspectComparison(0);$('workspaceInspectB').onclick=()=>inspectComparison(1);
    $('workspaceExportRun').onclick=()=>{if(state.comparison){download('comparison-'+(state.comparison.id || 'source')+'.json',state.comparison);return;}if(state.active)download(`run-${state.active.id || 'source'}.json`,state.active);else message('Open a saved result first.',true);};
    $('workspaceExportDraft').onclick=()=>download('workspace-configuration.json',state.draft);
    $('workspaceExportCsv').onclick=async()=>{try{if(!state.active&&!state.comparison)throw Error('Choose a saved result');const r=await fetch('/api/workspace/export/csv',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(state.comparison?{artifact:state.comparison}:{run:state.active})});if(!r.ok)throw Error((await r.json()).error || 'Native CSV unavailable');download((state.comparison?'comparison-':'run-')+(state.comparison?.id || state.active?.id || 'source')+'.csv',await r.text(),'text/csv');}catch(e){message(e.message,true);}};
    $('workspaceApplyDraft').onclick=async()=>{try{const d=JSON.parse($('workspaceImportDraft').value);const r=await api('/api/workspace/validate',d);state.draft=r.configuration;renderForm();message('Validated draft imported. No source changed or solve performed.');}catch(e){message(e.message,true);}};
    $('exportConfigButton').onclick=()=>download('workspace-configuration.json',state.draft);
    $('exportLink').addEventListener('click',e=>{if(state.active||state.comparison){e.preventDefault();e.stopImmediatePropagation();download(state.comparison?'comparison.json':'run.json',state.comparison || state.active);}},true);
    const drawer=open=>{const panel=$('workspaceControls');panel.classList.toggle('drawer-open',open);content.inert=open;panel.setAttribute('role',open?'dialog':'complementary');panel.setAttribute('aria-label','Experiment configuration');if(open){panel.setAttribute('aria-modal','true');$('workspaceCloseControls').focus();}else{panel.removeAttribute('aria-modal');$('workspaceToggleControls').focus();}};
    $('workspaceToggleControls').onclick=()=>drawer(!$('workspaceControls').classList.contains('drawer-open'));$('workspaceCloseControls').onclick=()=>drawer(false);
    document.addEventListener('keydown',e=>{if(!$('workspaceControls').classList.contains('drawer-open'))return;if(e.key==='Escape'){e.preventDefault();drawer(false);}if(e.key==='Tab'){const nodes=[...$('workspaceControls').querySelectorAll('button,input,select,textarea,summary')].filter(n=>!n.disabled&&n.getClientRects().length);const first=nodes[0],last=nodes.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}});
    window.addEventListener('resize',()=>{if(innerWidth>1000&&$('workspaceControls').classList.contains('drawer-open'))drawer(false);});
  }
  function onComparison(artifact){
    if(!state.ready)return;state.comparison=artifact;window.RangeLabM3.pausePlayback();document.body.classList.add('workspace-comparing');document.querySelector('.m3-playback').hidden=true;
    document.querySelectorAll('[data-layer],#coordinateMode').forEach(n=>n.disabled=true);$('workspaceAttempt').disabled=true;$('workspaceUseConfig').disabled=$('workspaceReuse').disabled=true;
    $('workspaceInspectA').hidden=$('workspaceInspectB').hidden=false;$('workspaceExportRun').textContent='Comparison JSON';
    $('workspaceResultTitle').textContent='Two-run comparison · shared camera, metre scale and elapsed time';$('sceneSubtitle').textContent='A / B · '+artifact.alignment+' · use Inspect A or B for per-run diagnostics';
    const note=$('plotNotice');note.classList.add('hidden');$('pngButton').disabled=true;$('workspaceProvenance').textContent=JSON.stringify(artifact,null,2);
    $('m2Results').hidden=false;const pane=$('workspacePane_overview');if($('comparisonMetrics'))pane.append($('comparisonMetrics'));if($('compareNotice'))pane.append($('compareNotice'));tab('overview');
  }
  function inspectComparison(side){const a=state.comparison;if(!a?.runs?.[side])return;openRun(a.runs[side],a.id?`artifact:${a.id}:entry:${side}`:null);}
  async function importSource(file) {
    const parsed=JSON.parse(await file.text()),record=parsed.run || parsed.artifact || parsed;
    if(record.workspace_version===1){state.draft=(await api('/api/workspace/validate',record)).configuration;renderForm();message('Workspace draft imported without execution.');return;}
    if(record.artifact_type==='experiment_config'){state.draft=(await api('/api/workspace/configuration',{native_configuration:record})).configuration;renderForm();message('Native configuration copied to draft without execution.');return;}
    const version=String(record.schema_version).split('.')[0];const url=['3','4','5','6','7'].includes(version)?`/api/m${version}/import`:record.artifact_type?'/api/artifacts/import':'/api/import';
    const saved=await api(url,record),value=saved.run || saved.artifact || saved;
    if(value.artifact_type)openArtifact(value);else openRun(value,'run:'+(value.id||saved.id));
    window.RangeLabLibrary.invalidate();message('Validated source imported and saved without fitting. Draft unchanged.');
  }
  function humanText(root) {
    if(!root || !(root instanceof Node))return;
    const walk=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);const nodes=[];while(walk.nextNode())nodes.push(walk.currentNode);
    nodes.forEach(n=>{if(n.parentElement?.closest('pre,textarea,script,style,#workspaceLegacyAdapters'))return;const next=n.nodeValue.replace(/\bM[0-7]\s*[·+]\s*/g,'').replace(/\bM[0-7](?:_|\b)/g,m=>({M0:'baseline',M1:'planar',M2:'comparison',M3:'timing',M4:'geometry',M5:'solver',M6:'robust',M7:'survey'})[m.slice(0,2)]+(m.endsWith('_')?' ':'' ));if(next!==n.nodeValue)n.nodeValue=next;});
  }
  async function init() {
    layout();state.ready=true;
    try {state.capabilities=await api('/api/workspace/capabilities');$('workspaceEngine').innerHTML=Object.entries(state.capabilities.models).map(([k,v])=>`<option value="${k}">${esc(v.label)}</option>`).join('');
      let saved;try{saved=JSON.parse(sessionStorage.getItem('rangelab-workspace-draft-v1'));}catch(_){}
      state.draft=saved?.workspace_version===1?saved:clone(state.capabilities.models.robust.defaults);renderForm();
      const native=()=>({config:{...clone(state.draft.physical),assumed_std_m:clone(state.draft.assumptions.assumed_std_m)},options:Object.fromEntries(Object.entries({...clone(state.draft.assumptions),...clone(state.draft.numerical)}).filter(([key])=>key!=='assumed_std_m'))});
      window.RangeLabM2.formConfig=()=>native().config;window.RangeLabM3.formConfig=()=>native().config;window.RangeLabM3.formOptions=()=>native().options;window.RangeLabM4.formPayload=native;window.RangeLabM6.formPayload=native;window.RangeLabM7.formPayload=native;message('Ready. Changes edit the draft; Run explicitly creates a saved result.');
      if(window.RangeLab.state.activeRun)onRun(window.RangeLab.state.activeRun);
      humanText(document.body);new MutationObserver(records=>records.forEach(r=>{if(r.type==='characterData')humanText(r.target.parentElement);else r.addedNodes.forEach(n=>{if(n.nodeType===1)humanText(n);else if(n.nodeType===3)humanText(n.parentElement);});})).observe(document.body,{childList:true,subtree:true,characterData:true});
    }catch(e){message('Workspace initialization failed: '+e.message,true);}
  }
  window.RangeLabWorkspace={state,onRun,openRun,openArtifact,useConfiguration,tab,importSource,onComparison,download,comparisonTarget:()=>$('scene')};
  document.addEventListener('DOMContentLoaded',init);
})();
