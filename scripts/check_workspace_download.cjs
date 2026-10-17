// Browser-independent check for lossless JSON download serialization.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let blob;
const context={window:{},document:{addEventListener(){},createElement(){return{click(){}};}},
  structuredClone,Blob,URL:{createObjectURL(value){blob=value;return'blob:test';},revokeObjectURL(){}},setTimeout(){}};
vm.createContext(context);vm.runInContext(fs.readFileSync('web/workspace.js','utf8'),context);
(async()=>{
  const payload={objective:'.5*c²*sum rho((range_residual/sigma/c)²)',units:'m²',label:'σ · Ω → 😀',value:1.25};
  for(const value of [payload,JSON.stringify(payload)]){
    context.window.RangeLabWorkspace.download('run.json',value);
    const text=await blob.text();assert([...text].every(c=>c.charCodeAt(0)<128));
    assert.deepEqual(JSON.parse(text),payload);assert.equal(blob.type,'application/json;charset=utf-8');
  }
  console.log(JSON.stringify({passed:true,checks:['object JSON round trip','preformatted JSON round trip','objective superscript preservation','surrogate pair preservation','ASCII transport with explicit UTF-8 MIME']},null,2));
})().catch(error=>{console.error(error);process.exitCode=1;});
