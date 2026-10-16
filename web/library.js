(() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const storeKey = 'rangelab-library-v1';
  let saved = {}; try { saved = JSON.parse(sessionStorage.getItem(storeKey) || '{}'); } catch (_) {}
  const state = { view:'experiment', q:'', type:'all', status:'', model:'', source:'', sort:'newest', page:1, page_size:25, mode:'grouped', parent:'', selected:null, slots:[null,null], ...saved, items:[], dirty:true, request:0, detailRequest:0, ready:false };
  state.page_size = [25,50].includes(+state.page_size) ? +state.page_size : 25;
  let debounce, invalidationTimer, experimentScroll=0, origin=null;
  const persist = () => { const {items,dirty,request,detailRequest,ready,...prefs} = state; try { sessionStorage.setItem(storeKey,JSON.stringify(prefs)); } catch (_) {} };
  const api = (...args) => window.RangeLab.api(...args);
  const label = item => item?.label || item?.scenario || item?.id || 'Saved item';
  const shortDate = item => { const value=item.date || item.created_at; if (!value) return 'Date unavailable'; const d=new Date(value); return Number.isNaN(+d) ? String(value) : d.toLocaleString([], {year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}); };
  const settingsText = item => { const context=[item.cell?`cell ${item.cell.value ?? item.cell.value_index ?? '—'} · seed ${item.cell.seed ?? '—'}`:null,item.variant?(typeof item.variant==='object'?item.variant.label: item.variant):null].filter(Boolean).join(' · '); const s=item.settings; if(item.distinguishing_settings?.length)return [context,...item.distinguishing_settings].filter(Boolean).join(' · '); if (typeof s === 'string') return s; return [context,Object.entries(s || {}).filter(([,v])=>v!==null && v!==undefined && typeof v!=='object').slice(0,6).map(([k,v])=>`${k.replaceAll('_',' ')}: ${v}`).join(' · ')].filter(Boolean).join(' · ') || [item.model,item.solver,item.loss,item.seed!==undefined?`seed ${item.seed}`:null].filter(Boolean).join(' · ') || 'Settings in preview'; };
  function status(text, error=false) { $('#libraryStatus').textContent=text; $('#libraryStatus').classList.toggle('is-error',error); }
  function invalidate() { state.dirty=true; if (state.ready && state.view==='library') { clearTimeout(invalidationTimer); invalidationTimer=setTimeout(load,200); } }
  function show(view, focus=true) {
    if (!state.ready) return;
    const changed=state.view!==view;
    if (view==='library' && changed) {
      experimentScroll=window.scrollY; origin=document.activeElement;
      const playback=window.RangeLabM3?.playbackState?.(); window.RangeLabM3?.pausePlayback?.();
      if (playback && !playback.paused) $('#playbackNavigationState').textContent=`Playback paused at ping ${playback.selectedPing+1} while browsing Library.`;
    }
    state.view=view; $('#experimentView').hidden=view!=='experiment'; $('#libraryView').hidden=view!=='library';
    document.body.classList.toggle('library-active',view==='library');
    $('#experimentNav').setAttribute('aria-pressed',String(view==='experiment')); $('#libraryNav').setAttribute('aria-pressed',String(view==='library'));
    if (view==='library') { if (state.dirty || !state.items.length) load(); if (focus) $('#librarySearch').focus(); }
    else if (changed) { window.scrollTo(0,experimentScroll); if (focus) (origin?.isConnected ? origin : $('#libraryNav')).focus({preventScroll:true}); }
    persist();
  }
  function syncControls(){
    $('#librarySearch').value=state.q;
    for(const[key,id]of Object.entries({type:'libraryType',status:'libraryStatusSelect',model:'libraryModel',source:'librarySource',sort:'librarySort',mode:'libraryMode',page_size:'libraryPageSize'}))$('#'+id).value=state[key];
  }
  function enterParent(item){
    state.parentNavigation=Object.fromEntries(['q','type','status','model','source','sort','page','mode'].map(k=>[k,state[k]]));state.parentLabel=label(item);state.parent=item.key;
    Object.assign(state,{q:'',type:'run',status:'',model:'',source:'',sort:'newest',page:1,mode:'all'});syncControls();closePreview();load();
  }
  function leaveParent(){state.parent='';Object.assign(state,state.parentNavigation || {page:1});delete state.parentNavigation;delete state.parentLabel;syncControls();load();}
  function facetOptions(name, values) {
    const select=$(name==='status'?'#libraryStatusSelect':`#library${name[0].toUpperCase()+name.slice(1)}`), current=state[name];
    const list=Array.isArray(values)?values:Object.keys(values || {});
    select.innerHTML=`<option value="">All ${name==='status'?'statuses':`${name}s`}</option>`+list.map(raw=>{const v=typeof raw==='object' ? raw.value || raw.name : raw; return `<option value="${esc(v)}">${esc(String(v).replaceAll('_',' '))}</option>`;}).join('');
    if (current && ![...select.options].some(o=>o.value===current)) select.add(new Option(current,current)); select.value=current;
  }
  async function load() {
    if (!state.ready) return;
    const serial=++state.request; $('#libraryResults').setAttribute('aria-busy','true'); status('Loading indexed summaries…');
    const params=new URLSearchParams({q:state.q,type:state.type,status:state.status,model:state.model,source:state.source,sort:state.sort,page:state.page,page_size:state.page_size,view:state.mode}); if(state.parent)params.set('parent',state.parent);
    const started=performance.now();
    const progressTimer=setInterval(async()=>{try{const p=await api('/api/library/status');if(serial===state.request)status(`Index ${p.status || p.state || 'working'} · ${p.scanned ?? p.files ?? ''} records inspected. Source JSON remains authoritative.`);}catch(_){}},800);
    try {
      const data=await api(`/api/library?${params}`); if(serial!==state.request)return;
      state.items=data.items || []; state.page=data.page || 1; state.dirty=false;
      if(data.overall_total!==undefined || !state.parent)$('#libraryNavCount').textContent=`(${data.overall_total ?? data.total ?? 0})`;
      $('#libraryCounts').textContent=state.parent?`${data.filtered ?? state.items.length} matching · ${data.total ?? state.items.length} recorded children${state.parentLabel?` · ${state.parentLabel}`:''}`:`${data.filtered ?? state.items.length} matching ${state.mode==='grouped'?'groups':'items'} · ${data.total ?? state.items.length} ${state.mode==='grouped'?'groups':'items'} · ${data.overall_total ?? data.total ?? state.items.length} saved records`;
      const pages=data.pages || 1, from=state.items.length ? (state.page-1)*state.page_size+1 : 0;
      $('#libraryPageInfo').textContent=`${from}–${from?from+state.items.length-1:0} · Page ${state.page} of ${pages}`;
      $('#libraryPrevious').disabled=state.page<=1; $('#libraryNext').disabled=state.page>=pages;
      $('#libraryParentBack').hidden=!state.parent;
      for (const name of ['status','model','source']) facetOptions(name,data.facets?.[name] || data.facets?.[`${name}s`]);
      renderRows();
      const idx=data.index || {}; const info=typeof idx==='string' ? idx : idx.status || idx.state || 'ready';
      status(`Metadata index: ${info}. Summaries are not full-record validation; Open and exports validate source JSON. Cache refresh checks file timestamps and sizes each query; same-size edits with restored timestamps need Rebuild. ${idx.message || ''}`);
      $('#libraryView').dataset.queryRenderMs=(performance.now()-started).toFixed(2); persist();
    } catch(e) { if(serial===state.request) { status(`Library unavailable: ${e.message}. Use Refresh to retry.`,true); $('#libraryRows').innerHTML='<div class="library-empty">Could not read metadata. Your active experiment is retained.</div>'; } }
    finally { clearInterval(progressTimer); if(serial===state.request)$('#libraryResults').setAttribute('aria-busy','false'); }
  }
  function renderRows() {
    $('#libraryRows').innerHTML=state.items.length ? state.items.map((item,i)=>`<button type="button" class="library-row${state.selected?.key===item.key?' selected':''}" data-library-row="${i}" aria-pressed="${state.selected?.key===item.key}"><span class="library-row-main"><b>${esc(label(item))}</b><span>${esc(settingsText(item))}</span>${item.parent_key || item.parents?.length?'<small>Recorded source relationship</small>':''}</span><span class="library-kind">${esc(item.kind || item.artifact_type || 'run')}${item.child_count?`<small>${esc(item.child_count)} child runs</small>`:''}</span><span class="library-date">${esc(shortDate(item))}</span><span class="library-outcome">${esc(item.status || 'unavailable')}</span></button>`).join('') : '<div class="library-empty">No saved items match these filters. Try another search or All runs.</div>';
    document.querySelectorAll('[data-library-row]').forEach(row=>{
      row.addEventListener('click',()=>preview(state.items[+row.dataset.libraryRow]));
      row.addEventListener('keydown',e=>{const delta=e.key==='ArrowDown'?1:e.key==='ArrowUp'?-1:0;if(delta){e.preventDefault();const next=+row.dataset.libraryRow+delta;document.querySelector(`[data-library-row="${next}"]`)?.focus();}});
    });
  }
  async function preview(item) {
    state.selected=item; const serial=++state.detailRequest; renderRows(); renderPreview(item); persist();
    try { const data=await api(`/api/library/${encodeURIComponent(item.key)}`); if(serial!==state.detailRequest)return; state.selected=data.item || data; renderPreview(state.selected); persist(); }
    catch(e) { if(serial===state.detailRequest)$('#libraryPreviewNote').textContent=`Metadata preview unavailable: ${e.message}. Refresh to retry.`; }
  }
  function renderPreview(item) {
    $('#libraryPreview').hidden=false;
    const children=item.child_count || 0;
    $('#libraryPreview').innerHTML=`<div class="library-preview-head"><div><div class="eyebrow">METADATA PREVIEW</div><h2>${esc(label(item))}</h2></div><button type="button" id="libraryClosePreview" class="button button-quiet" aria-label="Close preview">Back</button></div><p id="libraryPreviewNote">Selection previews indexed metadata. Your scene and unsaved controls remain unchanged.</p><div class="library-preview-actions"><button id="libraryOpen" type="button" class="button button-primary">Open in viewer</button>${children || item.kind==='benchmark'?`<button id="libraryChildren" type="button" class="button button-quiet">${item.kind==='comparison'?'Show source runs':'Show child runs'}</button>`:''}${item.kind==='run'?'<button id="libraryUseA" type="button" class="button button-quiet">Use as A</button><button id="libraryUseB" type="button" class="button button-quiet">Use as B</button>':''}<button id="libraryExport" type="button" class="button button-quiet">Export source JSON</button><button id="libraryCopyId" type="button" class="button button-quiet">Copy ID</button></div><dl class="library-summary"><dt>Outcome</dt><dd>${esc(item.status || 'unavailable')}</dd><dt>Saved</dt><dd>${esc(shortDate(item))}</dd><dt>Attempts</dt><dd>${esc(JSON.stringify(item.attempt_counts || item.outcome_counts || 'unavailable'))}</dd><dt>Unattempted data cells</dt><dd>${esc(item.unattempted_data_cells ?? 'unavailable')}</dd><dt>Unattempted scheduled runs</dt><dd>${esc(item.unattempted ?? 'unavailable')} · variant/run combinations</dd><dt>Source</dt><dd>${esc(item.source || 'unavailable')}</dd><dt>Summary validation</dt><dd>${esc(item.summary_validation || 'Indexed metadata only')}</dd><dt>Original ID</dt><dd>${esc(item.id)}</dd></dl>${item.error?`<p class="library-error">${esc(item.error)}</p>`:''}${Array.isArray(item.attempts)&&item.attempts.length?`<div class="library-attempts"><h3>Retained attempts</h3>${item.attempts.map(a=>`<button type="button" class="button button-quiet" data-library-attempt="${esc(a.index)}">Start ${esc(a.index)} · ${esc(a.status)}${a.selected?' · selected':''}</button>${a.error?`<p>${esc(a.error)}</p>`:''}`).join('')}</div>`:''}<details class="library-metadata"><summary>Full indexed metadata and provenance</summary><pre>${esc(JSON.stringify(item,null,2))}</pre></details><p class="library-detail-help">Open retained runs or benchmarks to inspect every start, failure messages, complete settings, CSV tables and scene/chart PNG exports. No fitting occurs when opening saved results.</p>`;
    $('#libraryClosePreview').onclick=closePreview;
    $('#libraryOpen').onclick=()=>openItem(item);
    document.querySelectorAll('[data-library-attempt]').forEach(b=>b.onclick=()=>openItem({...item,start_index:+b.dataset.libraryAttempt}));
    $('#libraryExport').onclick=()=>exportItem(item);
    $('#libraryCopyId').onclick=async()=>{try{await navigator.clipboard.writeText(item.id);$('#libraryPreviewNote').textContent='ID copied.';}catch(_){$('#libraryPreviewNote').textContent=`ID: ${item.id}`;}};
    if($('#libraryChildren'))$('#libraryChildren').onclick=()=>enterParent(item);
    if($('#libraryUseA'))$('#libraryUseA').onclick=()=>setSlot(0,item);
    if($('#libraryUseB'))$('#libraryUseB').onclick=()=>setSlot(1,item);
    if(matchMedia('(max-width:700px)').matches)$('#libraryClosePreview').focus();
  }
  function closePreview() { const key=state.selected?.key;const rowIndex=state.items.findIndex(i=>i.key===key); state.selected=null; ++state.detailRequest; $('#libraryPreview').hidden=true; renderRows(); persist(); document.querySelector(`[data-library-row="${Math.max(0,rowIndex)}"]`)?.focus(); }
  function moduleFor(item) { const version=String(item.schema_version || '').split('.')[0]; return window[`RangeLabM${version}`] || window.RangeLabM2; }
  async function openItem(item) {
    const button=$('#libraryOpen'); if(button)button.disabled=true;
    try {
      if(!item.open_url)throw new Error(item.error || 'Unreadable source; strict Open is unavailable.');
      const data=await api(item.open_url); const value=data.run || data.artifact || data;
      show('experiment',false);
      if(item.kind==='comparison' || item.artifact_type==='comparison') { window.RangeLabM2.openArtifact(value); $('#m2Results').scrollIntoView({block:'start'}); }
      else if(item.kind==='benchmark') { moduleFor(item).openArtifact(value); const version=String(item.schema_version).split('.')[0]; const target=$(`#m${version}Workspace`) || $(`#m${version}Heading`) || $('#m2Results'); target.scrollIntoView({block:'start'}); }
      else {
        const run=item.comparison_side!==undefined && Array.isArray(value.runs)?value.runs[item.comparison_side]:item.parent_key && value.entries ? value.entries[item.entry_ordinal]?.run : value;
        if(!run || !run.experiment)throw new Error('Validated source has no recorded run at this entry.');
        if(item.run_id)run.id ||= item.run_id;
        const restoreModule=window[`RangeLabM${String(run.schema_version).split('.')[0]}`];restoreModule?.restoreRun?.(run);
        window.RangeLab.state.activeRun=run; window.RangeLab.state.selectedStart=item.start_index ?? null;
        window.RangeLab.renderRun(run); $('#scene').scrollIntoView({block:'center'});
      }
    } catch(e) { show('library',false); if($('#libraryPreviewNote'))$('#libraryPreviewNote').textContent=`Open failed: ${e.message}`; }
    finally { if(button)button.disabled=false; }
  }
  async function exportItem(item) {
    try {
      let url=item.export_json_url || item.open_url;
      if(!url){const v=String(item.schema_version).split('.')[0];url=item.kind==='run'?`/api/runs/${encodeURIComponent(item.run_id || item.id)}`:item.kind==='comparison'?`/api/comparisons/${encodeURIComponent(item.id)}`:`/api/${['3','4','5','6','7'].includes(v)?`m${v}/`:''}sweeps/${encodeURIComponent(item.id)}`;}
      const data=await api(url); let record=data.run || data.artifact || data;if(item.comparison_side!==undefined && Array.isArray(record.runs))record=record.runs[item.comparison_side];else if(item.parent_key && record.entries)record=record.entries[item.entry_ordinal]?.run || record; const link=document.createElement('a'); const blob=URL.createObjectURL(new Blob([JSON.stringify(record,null,2)],{type:'application/json'})); link.href=blob;link.download=`${item.id}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(blob),1000);
    } catch(e) { $('#libraryPreviewNote').textContent=`Export failed: ${e.message}`; }
  }
  function setSlot(index,item) { state.slots[index]={id:item.run_id || item.id,key:item.key,label:label(item),variant:item.variant,cell:item.cell,settings:{loss:item.settings?.loss},schema_version:item.schema_version,observation_fingerprint:item.observation_fingerprint,starts_fingerprint:item.starts_fingerprint}; $('#libraryPairing').textContent='Pairing unchecked. Compare validates saved observations and starts.';renderTray();persist(); }
  const slotLabel=s=>s?[label(s),s.variant || s.settings?.loss || String(s.id || '').slice(0,8),s.cell?.seed!==undefined?`seed ${s.cell.seed}`:null].filter(Boolean).join(' · '):'Choose a run in Library';
  function renderTray() {
    if(state.slots.every(Boolean)){const[a,b]=state.slots;$('#libraryPairing').textContent=a.observation_fingerprint&&a.observation_fingerprint===b.observation_fingerprint ? (a.starts_fingerprint&&a.starts_fingerprint===b.starts_fingerprint?'Metadata fingerprints match observations and physical starts; strict comparison validates source records.':'Metadata observations match; compatible physical starts remain unverified.'):'Observation identity is different or unverified; this is an unpaired comparison.';}
    $('#libraryTraySlots').innerHTML=state.slots.map((s,i)=>`<div class="library-slot"><b>${i?'B':'A'}</b><span title="${esc(slotLabel(s))}">${esc(slotLabel(s))}</span><button type="button" data-clear-slot="${i}" aria-label="Clear comparison ${i?'B':'A'}" ${s?'':'disabled'}>×</button></div>`).join('');
    document.querySelectorAll('[data-clear-slot]').forEach(b=>b.onclick=()=>{state.slots[+b.dataset.clearSlot]=null;renderTray();persist();});
    $('#libraryCompare').disabled=!state.slots.every(Boolean) || state.slots[0]?.key===state.slots[1]?.key;
  }
  function reportPairing(a,b) {
    if(!a || !b || !a.experiment || !b.experiment){if(state.slots.every(Boolean)){const[x,y]=state.slots;$('#libraryPairing').textContent=x.observation_fingerprint&&x.observation_fingerprint===y.observation_fingerprint?(x.starts_fingerprint&&x.starts_fingerprint===y.starts_fingerprint?'Retained source metadata matches observations and physical starts; strict source comparison saved.':'Retained observations match; compatible physical starts remain unverified.'):'Retained source comparison saved; paired observations and starts remain unverified.';}return;}
    const observations = r => r.experiment?.estimator_input;
    const initials = r => (r.starts || []).map(s=>s.initial);
    const obs=observations(a) && observations(b) && JSON.stringify(observations(a))===JSON.stringify(observations(b));
    const starts=initials(a).length>0 && initials(a).every(Boolean) && JSON.stringify(initials(a))===JSON.stringify(initials(b));
    $('#libraryPairing').textContent=obs&&starts?'Identical saved estimator inputs and physical starts verified.':`Pairing: ${obs?'identical estimator inputs':'different or unavailable estimator inputs'}; ${starts?'identical physical starts':'physical starts differ or compatibility is unverified'}.`;
    // Exact equality is conservative; transformed/projected starts need recorded model-specific pairing evidence.
  }
  function activeResult(run) { const el=$('#activeResultContext');if(el)el.textContent=run?`${run.reference_name || run.experiment?.config?.scenario || 'Saved result'} · ${run.status || 'saved'} · ${String(run.id || '').slice(0,8)}`:'No result open'; }
  function init() {
    const section=document.createElement('section');section.id='libraryView';section.hidden=true;section.className='library-view';section.setAttribute('aria-labelledby','libraryHeading');
    section.innerHTML=`<div class="library-heading"><div><div class="eyebrow">SAVED DATA</div><h1 id="libraryHeading">Library</h1><p>Runs, benchmarks and comparisons · retained source records</p></div><div class="library-heading-actions"><button id="libraryImport" type="button" class="button button-quiet">Import JSON</button><input id="libraryImportFile" type="file" accept="application/json,.json" hidden><button id="libraryRebuild" type="button" class="button button-quiet">Rebuild index</button><button id="libraryRefresh" type="button" class="button button-quiet">Refresh</button></div></div><form id="libraryFilters" class="library-filters"><label class="library-search">Search<input id="librarySearch" type="search" placeholder="Name, scenario, ID or settings…" autocomplete="off"></label><label>Type<select id="libraryType"><option value="all">All types</option><option value="run">Runs</option><option value="benchmark">Benchmarks / sweeps</option><option value="comparison">Comparisons</option></select></label><label>Status<select id="libraryStatusFilter"></select></label><label>Model<select id="libraryModel"></select></label><label>Source<select id="librarySource"></select></label><label>Sort<select id="librarySort"><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="name">Name</option><option value="status">Outcome</option></select></label><label>Show<select id="libraryMode"><option value="grouped">Parents + standalone</option><option value="all">All runs / items</option></select></label></form><div class="library-state-line"><span id="libraryCounts">Loading counts…</span><button id="libraryParentBack" type="button" class="text-button" hidden>← Back to all items</button></div><div id="libraryStatus" class="library-status" role="status" aria-live="polite">Index has not been queried.</div><div class="library-content"><div id="libraryResults" class="library-results" aria-label="Saved items"><div class="library-column-head" aria-hidden="true"><span>Name / settings</span><span>Kind</span><span>Saved</span><span>Outcome</span></div><div id="libraryRows"></div></div><aside id="libraryPreview" class="library-preview" aria-label="Selected item metadata" hidden></aside></div><div class="library-pagination"><label>Per page<select id="libraryPageSize"><option value="25">25</option><option value="50">50</option></select></label><span id="libraryPageInfo"></span><div><button id="libraryPrevious" type="button" class="button button-quiet">Previous</button><button id="libraryNext" type="button" class="button button-quiet">Next</button></div></div>`;
    $('#experimentView').before(section);
    // Status message and filter use distinct IDs.
    $('#libraryStatusFilter').id='libraryStatusSelect';
    const tray=document.createElement('section');tray.id='libraryTray';tray.className='library-tray';tray.setAttribute('aria-label','Persistent comparison tray');tray.innerHTML='<div id="libraryTraySlots" class="library-tray-slots"></div><div class="library-tray-actions"><button id="libraryCompare" type="button" class="button button-primary">Compare A / B</button><button type="button" data-open-library class="text-button">Choose runs</button></div><p id="libraryPairing">Pairing unchecked. Compare validates saved observations and starts.</p>';document.body.append(tray);
    // Facet lookup uses the dedicated status select rather than the status announcement.
    $('#librarySearch').value=state.q;
    for(const [key,id] of Object.entries({type:'libraryType',status:'libraryStatusSelect',model:'libraryModel',source:'librarySource',sort:'librarySort',mode:'libraryMode',page_size:'libraryPageSize'})){
      const el=$('#'+id);if(key==='status'||key==='model'||key==='source')el.innerHTML='<option value="">All</option>';el.value=state[key];el.addEventListener('change',()=>{state[key]=key==='page_size'?+el.value:el.value;state.page=1;persist();load();});
    }
    $('#libraryFilters').onsubmit=e=>{e.preventDefault();clearTimeout(debounce);state.q=$('#librarySearch').value;state.page=1;load();};
    $('#librarySearch').oninput=()=>{clearTimeout(debounce);debounce=setTimeout(()=>{state.q=$('#librarySearch').value;state.page=1;load();},250);};
    $('#libraryImport').onclick=()=>$('#libraryImportFile').click();
    $('#libraryImportFile').onchange=async e=>{const file=e.target.files?.[0];if(!file)return;try{const data=JSON.parse(await file.text());const record=data.run || data.artifact || data;const version=String(record.schema_version).split('.')[0];if(record.artifact_type==='experiment_config'&&version!=='7'){await window.RangeLab.importFile(file);show('experiment',false);return;}if(record.artifact_type==='experiment_config'&&version==='7'){window.RangeLabM7.importConfig(record);show('experiment',false);$('#m7Workspace').scrollIntoView({block:'start'});return;}const url=['3','4','5','6','7'].includes(version)?`/api/m${version}/import`:record.artifact_type?'/api/artifacts/import':'/api/import';await api(url,{method:'POST',body:JSON.stringify(record)});invalidate();status('Imported source JSON and retained a new saved record.');}catch(err){status(`Import failed: ${err.message}`,true);}finally{e.target.value='';}};
    $('#libraryRebuild').onclick=async()=>{status('Rebuilding metadata index; scientific source files remain unchanged.');$('#libraryRebuild').disabled=true;try{await api('/api/library/rebuild',{method:'POST'});await load();}catch(e){status(`Index rebuild failed: ${e.message}`,true);}finally{$('#libraryRebuild').disabled=false;}};
    $('#libraryRefresh').onclick=()=>{state.dirty=true;load();if(state.selected)preview(state.selected);};
    $('#libraryPrevious').onclick=()=>{state.page--;load();};$('#libraryNext').onclick=()=>{state.page++;load();};
    $('#libraryParentBack').onclick=leaveParent;
    $('#libraryNav').onclick=()=>show('library');$('#experimentNav').onclick=()=>show('experiment');
    document.addEventListener('click',e=>{if(e.target.closest('[data-open-library]'))show('library');});
    document.addEventListener('keydown',e=>{if(state.view==='library'&&e.key==='Escape'){e.preventDefault();if(!$('#libraryPreview').hidden)closePreview();else if(state.parent){leaveParent();}else show('experiment');}if((e.ctrlKey||e.metaKey)&&e.key==='k'){e.preventDefault();show('library');}});
    $('#libraryCompare').onclick=async()=>{show('experiment',false);$('#m2Results').scrollIntoView({block:'start'});await window.RangeLabM2.compareRuns();};
    state.ready=true;renderTray();activeResult(window.RangeLab.state.activeRun);const initial=state.view;state.view='experiment';show(initial,false);if(state.selected)renderPreview(state.selected);
  }
  window.RangeLabLibrary={invalidate,show,activeResult,runIds:()=>state.slots.map(s=>s?.id),runKeys:()=>state.slots.map(s=>s?.key),reportPairing,setComparisonRuns(runs,sources=[],comparisonId){runs.slice(0,2).forEach((r,i)=>{const key=comparisonId?`artifact:${comparisonId}:entry:${i}`:sources[i]?.key || (r.id?`run:${r.id}`:null);if(key)setSlot(i,{...r,label:r.label || r.reference_name || r.experiment?.config?.scenario || `Saved comparison source ${i+1}`,kind:'run',key});});},state};
  document.addEventListener('DOMContentLoaded',init);
})();
