// Owned-session crash diagnostics. Copyright (c) 2026 Thingolus. MIT.
// Raw addresses stay inside this adapter; reports contain module-relative offsets.
let diagnosticExceptionCount=0;
function diagnosticLocation(address){
  const module=Process.findModuleByAddress(address);
  if(!module)return {module:null,rva:null,symbol:null};
  let symbol=null;
  try{symbol=DebugSymbol.fromAddress(address).name||null;}catch(_){}
  return {module:module.name,rva:address.sub(module.base).toUInt32(),symbol:symbol?.slice(0,160)||null};
}
function diagnosticStack(context){
  try{return {method:'accurate_unwind',frames:Thread.backtrace(context,Backtracer.ACCURATE).slice(0,32).map(diagnosticLocation)};}
  catch(_){return {method:'unavailable',frames:[]};}
}
function diagnosticSnapshot(){
  const threads=Process.enumerateThreads().slice(0,16).map(t=>({id:t.id,state:t.state,
    current:t.context?diagnosticLocation(t.context.pc):null,
    stack:t.context?diagnosticStack(t.context):{method:'unavailable',frames:[]}}));
  return {kind:'thread_snapshot',captured_ms:Date.now(),threads,
    modules:Process.enumerateModules().slice(0,256).map(m=>({name:m.name,bytes:m.size})),
    scope:'One observed thread snapshot; blocked or idle threads do not establish a hang.'};
}
function diagnosticInstall(){
  Process.setExceptionHandler(details=>{
    if(++diagnosticExceptionCount<=4){
      const memory=details.memory?{operation:details.memory.operation,location:diagnosticLocation(details.memory.address)}:null;
      send({kind:'ddda_native_exception',type:details.type,location:diagnosticLocation(details.address),
        memory,stack:diagnosticStack(details.context),thread:Process.getCurrentThreadId(),captured_ms:Date.now(),
        modules:Process.enumerateModules().slice(0,256).map(m=>({name:m.name,bytes:m.size}))});
    }
    return false; // Preserve normal native exception handling; never swallow faults.
  });
  return {installed:true,exception_policy:'observe_and_propagate'};
}
Object.assign(rpc.exports,{diagnosticInstall,diagnosticSnapshot});
