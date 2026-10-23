// Standalone callback observer. Copyright (c) 2026 Thingolus. MIT.
// Shares reviewed readers with tracing/world; never loads the co-op runtime.
let researchModule=null, researchRun=null, researchGeneration=0;
function researchCall(name){return new NativeFunction(researchModule.getExportByName(name),'uint',[],'mscdecl')();}
function snapshot(){
  return {stage:worldRun?.stage||0,generation:worldRun?.generation||0,
    native_errors:researchCall('ResearchErrors'),faults:0};
}
async function researchStop(){
  const r=researchRun;if(!r)return {cleanup:{sealed:true},world:{available:false}};
  if(r.stopping)return r.stopping;
  r.stopping=(async()=>{
  r.running=false;clearTimeout(r.timer);
  // Let in-flight onLeave callbacks finish before detaching their listener.
  const deadline=Date.now()+250;
  while(r.active&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,5));
  if(!r.detached){r.hook.detach();r.detached=true;Interceptor.flush();}
  // Frida may retire the trampoline after this JavaScript turn returns.
  await new Promise(resolve=>setTimeout(resolve,5));
  const restored=traceBytes(r.address,r.spec.bytes.length/2)===r.spec.bytes;
  return {world:worldLatest(),cleanup:{sealed:restored&&r.active===0,prefix_restored:restored,
    active_callbacks:r.active,errors:r.errors,samples:worldRun?.samples||0}};
  })();return r.stopping;
}
async function researchStart(durationMs){
  if(!researchModule||!Number.isInteger(durationMs)||durationMs<200||durationMs>10000)throw Error('invalid_capture');
  if(researchRun&&(researchRun.running||!(await researchStop()).cleanup.sealed))throw Error('observer_busy');
  const spec=REVIEWED_TRACES.native_stamina_apply,address=Process.mainModule.base.add(spec.rva);
  if(traceBytes(address,spec.bytes.length/2)!==spec.bytes)throw Error('signature_changed_or_hooked');
  worldRun={stage:0,generation:++researchGeneration,times:[0,0],party:[null,null],enemies:null,ids:new Map(),samples:0};
  const r={running:true,address,spec,active:0,errors:[],hook:null,timer:null,root:null,started:Date.now()};researchRun=r;
  r.hook=Interceptor.attach(address,{
    onEnter(){
      if(!r.running||Date.now()>r.started+durationMs)return;
      this.counted=true;r.active++;
      try{
        if(researchCall('ResearchHealthy')!==1||researchCall('ResearchErrors'))throw Error('offline_not_ready');
        const who=traceParty(this.context.eax);if(!who||!who.stage)return;
        const root=who.gs.toString()+':'+who.stage;
        if(r.root&&r.root!==root)throw Error('world_changed');
        r.root=root;worldRun.stage=who.stage;worldSample(this.context.eax);
      }catch(error){if(r.errors.length<8)r.errors.push(String(error).replace(/0x[0-9a-f]+/gi,'<address>'));}
    },
    onLeave(){if(this.counted)r.active--;}
  });
  r.timer=setTimeout(()=>researchStop(),durationMs);
  return {started:true,duration_ms:durationMs};
}
rpc.exports={
  researchBootstrap(path){
    if(Process.arch!=='ia32'||Process.pointerSize!==4||Process.mainModule.base.toString()!=='0x400000')throw Error('unsupported_build');
    if(Process.enumerateModules().some(m=>m.name.toLowerCase()==='ddcoop_runtime.dll'))throw Error('coop_runtime_present');
    researchModule=Module.load(path);
    if(researchCall('ResearchInitialize')!==1||researchCall('OfflineState')!==2)throw Error('offline_guard_failed');
    return {backend:'standalone',offline_transport:2,input_control:false};
  },
  researchStart,researchStop,
  researchStatus(){return {backend:'standalone',offline_transport:researchCall('OfflineState'),
    native_offline:researchCall('ResearchHealthy'),native_errors:researchCall('ResearchErrors'),input_control:false};}
};
