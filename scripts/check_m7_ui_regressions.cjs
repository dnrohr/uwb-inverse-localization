const fs=require('fs'),vm=require('vm'),assert=require('assert');
// Focused runtime regressions with a select-aware DOM double; no browser/solver.
const nodes=new Map(),listeners={},restores=[];
class Element {
 constructor(id=''){this.id=id;this.options=[];this._value='';this.checked=false;this.classList={toggle(){}};this.dataset={};if(id)nodes.set(id,this);}
 set id(v){this._id=v;if(v)nodes.set(v,this);}get id(){return this._id;}
 set value(v){v=String(v);this._value=this.options.length&&!this.options.some(x=>x.value===v)?'':v;}
 get value(){return this._value;}
 set innerHTML(html){this._html=html;
  for(const m of html.matchAll(/<([a-z0-9]+)\b[^>]*\bid="([^"]+)"[^>]*>/g)){const e=nodes.get(m[2])||new Element(m[2]);const value=m[0].match(/\bvalue="([^"]*)"/);if(value)e.value=value[1];e.checked=/\bchecked\b/.test(m[0]);}
  for(const m of html.matchAll(/<select\b[^>]*\bid="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)){const e=nodes.get(m[1]);e.options=[...m[2].matchAll(/<option value="([^"]*)"[^>]*>/g)].map(x=>({value:x[1]}));e.value=e.options[0]?.value||'';}
 }
 get innerHTML(){return this._html||'';}before(){}add(o){this.options.push(o);}addEventListener(){}setAttribute(){}focus(){}scrollIntoView(){}
}
const document={getElementById:id=>nodes.get(id),createElement:()=>new Element(),querySelector:s=>s==='#experimentView .page-footer'?new Element():nodes.get(s.slice(1)),querySelectorAll:()=>[],addEventListener:(name,fn)=>{listeners[name]=fn}};
let sharedMarker='initial',apiCalls=0;
const window={RangeLab:{state:{activeRun:null,start:null},api:async()=>{apiCalls++;throw new Error('Offline regression forbids API/solve');}},RangeLabM6:{restoreConfig:(config,options)=>{sharedMarker=config.marker;restores.push({marker:config.marker,loss:options.loss});},formPayload:()=>({config:{marker:sharedMarker},options:{starts:2}})},RangeLabLibrary:{invalidate(){}}};
const context={window,document,console,URL,Blob,setTimeout,Option:class{constructor(text,value){this.text=text;this.value=value}}};vm.createContext(context);vm.runInContext(fs.readFileSync('web/m7.js','utf8'),context);listeners.DOMContentLoaded();
const survey={frame:'world',units:'m',fixed:[{beacon_id:0,mask:[true,true,true],mean_m:[0,0,2]}],priors:[]};
const options={mode:'joint',tag_height_model:'fixed',solver:'trf',initialization:'independent',loss:'soft_l1',below_beacons:false,survey,uncertainty:{enabled:true,rank_rtol:1e-8,bound_tolerance_m:1e-7}};
const attempt={index:0,status:'success',solver:{message:'retained'},diagnostics:{}};
const a={id:'sourceA7',schema_version:'7.0',status:'success',experiment:{config:{marker:'A'}},options,starts:[attempt],selected_start:0};
const b={id:'sourceB6',schema_version:'6.0',status:'success',experiment:{config:{marker:'B'}},options:{loss:'gaussian'},starts:[attempt],selected_start:0};
function open(run){window.RangeLab.state.activeRun=run;window.RangeLab.state.start=attempt;window.RangeLabM7.onRun(run,attempt);}
open(a);assert(nodes.get('m7Loss').options.some(o=>o.value==='soft_l1'));assert.strictEqual(nodes.get('m7Loss').value,'soft_l1');assert.strictEqual(window.RangeLabM7.formPayload().options.loss,'soft_l1');assert.strictEqual(sharedMarker,'A');
nodes.get('m7Fixed').value='["unsaved"]';const restoreCount=restores.length;open(a);assert.strictEqual(restores.length,restoreCount);assert.strictEqual(nodes.get('m7Fixed').value,'["unsaved"]');
window.RangeLabM6.restoreConfig(b.experiment.config,b.options);open(b);assert.strictEqual(sharedMarker,'B');open(a);assert.strictEqual(sharedMarker,'A');assert.strictEqual(nodes.get('m7Loss').value,'soft_l1');assert.deepStrictEqual(JSON.parse(nodes.get('m7Fixed').value),survey.fixed);
const imported={artifact_type:'experiment_config',schema_version:'7.0',config:{marker:'Imported'},options};window.RangeLabM7.importConfig(imported);assert.strictEqual(nodes.get('m7Loss').value,'soft_l1');assert.strictEqual(window.RangeLabM7.formPayload().options.loss,'soft_l1');assert.strictEqual(apiCalls,0);
const rejected=[];const beforeRestoreCount=restores.length,beforeFixed=nodes.get('m7Fixed').value;
for(const [name,invalid] of [['wrong frame',{...survey,frame:'canonical'}],['wrong units',{...survey,units:'cm'}],['undeclared frame',(({frame,...rest})=>rest)(survey)],['unsupported coupling',{...survey,cross_beacon_covariance_m2:[[1]]}],['unknown row field',{...survey,fixed:[{...survey.fixed[0],coordinate_frame:'canonical'}]}],['invalid covariance',{...survey,fixed:[],priors:[{beacon_id:0,mask:[true,true,false],mean_m:[0,0,0],covariance_m2:[[1,2],[2,1]]}]}]]){
 assert.throws(()=>window.RangeLabM7.importConfig({...imported,options:{...options,survey:invalid}}));rejected.push(name);
 assert.strictEqual(restores.length,beforeRestoreCount);assert.strictEqual(nodes.get('m7Fixed').value,beforeFixed);
}
const librarySource=fs.readFileSync('web/library.js','utf8');const line=librarySource.split('\n').find(x=>x.includes('<dt>Unattempted data cells</dt>'));assert(line);const template=line.slice(line.indexOf('`')+1,line.lastIndexOf('`'));
const item={kind:'benchmark',id:'retained',label:'fixture',unattempted:6,unattempted_data_cells:2};
const rendered=vm.runInNewContext('`'+template+'`',{item,children:0,esc:String,label:x=>x.label,shortDate:()=> 'fixture date'});
assert(rendered.includes('<dt>Unattempted data cells</dt><dd>2</dd>'));assert(rendered.includes('<dt>Unattempted scheduled runs</dt><dd>6 · variant/run combinations</dd>'));
console.log(JSON.stringify({passed:true,scope:'Node VM select-aware DOM double; browser acceptance separate',checks:['saved soft_l1 preserved and resubmitted','imported soft_l1 config preserved and resubmitted','A7 to B6 to same A7 restores shared and survey controls','same source redraw preserves unsaved survey edits','unattempted data cells and scheduled variant runs have distinct denominators','offline import/inspection made zero API/solve calls','unsupported survey frame/units/coupling rejected before control mutation'],rejected_imports:rejected,restores},null,2));
