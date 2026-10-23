// Reviewed developer-provider ownership. MIT, Thingolus and contributors.
// Only copied runtime values and CoopSetTestPads are used outside native callbacks.
let controlRun = null;
const CONTROL_ACTIONS = {
  forward:{ly:16000},backward:{ly:-16000},left:{lx:-16000},right:{lx:16000},
  light_attack:{buttons:0x4000},heavy_attack:{buttons:0x8000},jump:{buttons:0x1000},
  interact:{buttons:0x2000},sheath:{lt:255},grab:{rt:255},
  dodge:{buttons:0x1200,ly:22000},menu:{buttons:0x10},inventory:{buttons:0x20},
  menu_up:{buttons:1},menu_down:{buttons:2},confirm:{buttons:0x1000},cancel:{buttons:0x2000},neutral:{}
};
function controlPads(role=-1, action={}, connected=true) {
  const p=Memory.alloc(80);p.writeByteArray(new Uint8Array(80));
  const packet=nextInputPacket();
  if(connected)for(let i=0;i<2;i++){
    const pad=p.add(i*20);pad.writeU8(1);pad.add(4).writeU32(packet);
    if(i===role){pad.add(8).writeU16(action.buttons||0);pad.add(10).writeS16(action.lx||0);
      pad.add(12).writeS16(action.ly||0);pad.add(18).writeU8(action.lt||0);pad.add(19).writeU8(action.rt||0);}
  }
  if(call('CoopSetTestPads','int',['pointer','uint'])(p,4)!==1)throw Error('provider_refused');
}
function controlGuard(s) {
  if(s.runtime!==2||s.guard_transport!==2||s.transport!==2||s.native_offline!==1||
    s.native_errors||s.faults||s.developer_input!==1||!s.stage||!s.generation)throw Error('control_guard');
}
function controlRelease(reason='requested') {
  const r=controlRun;
  if(r){clearInterval(r.timer);r.running=false;r.reason=reason;r.action=null;}
  controlPads(-1,{},false);
  return {released:true,reason,provider_acknowledged:true,engine_release_verified:false};
}
function controlStatus(){
  const r=controlRun;
  return r?{running:r.running,phase:r.phase,reason:r.reason||null,deadline_ms:r.deadline,
    action:r.action?.name||null,errors:r.errors.slice()}: {running:false,phase:'unclaimed'};
}
function controlClaim(){
  if(controlRun?.running)throw Error('control_busy');
  const s=snapshot();controlGuard(s);
  if(s.menu_gated||!((s.p1===-1&&s.p2===-1)||(s.p1===0&&s.p2===1)))throw Error('assignment_or_menu_conflict');
  const now=Date.now(),r={running:true,phase:s.p1===0?'ready':'neutral',started:now,
    phaseStarted:now,deadline:now+30000,stage:s.stage,generation:s.generation,
    timer:null,action:null,errors:[],frames:s.actors.map(a=>a.frames),advanced:now,last:now};
  controlRun=r;controlPads();
  r.timer=setInterval(()=>{
    try{
      const t=Date.now(),v=snapshot();controlGuard(v);
      if(t<r.last||t>r.deadline||t>r.started+120000)throw Error('control_expired');r.last=t;
      if(v.stage!==r.stage)throw Error('stage_changed');
      if(r.phase==='ready'){
        if(v.p1!==0||v.p2!==1||v.generation!==r.generation)throw Error('assignment_changed');
        if(!v.menu_gated){
          if(v.actors.every((a,i)=>a.observed===1&&a.frames>r.frames[i])){r.frames=v.actors.map(a=>a.frames);r.advanced=t;}
          if(t-r.advanced>1500)throw Error('callbacks_stalled');
        }else r.advanced=t;
        const a=r.action;
        if(a&&t<a.until){
          if(v.menu_gated&&!a.menu)throw Error('menu_changed');
          // RB precedes RB+A for the researched Strider evasion request.
          controlPads(a.role,a.name==='dodge'&&t<a.started+200?{buttons:0x200}:CONTROL_ACTIONS[a.name]);
        }else{r.action=null;controlPads();}
      }else{
        if(v.menu_gated)throw Error('menu_during_join');
        const elapsed=t-r.phaseStarted;
        if(r.phase==='neutral'&&elapsed>=400){r.phase='p1';r.phaseStarted=t;}
        else if(r.phase==='p1'&&v.p1===0){r.phase='release';r.phaseStarted=t;}
        else if(r.phase==='release'&&elapsed>=400){r.phase='p2';r.phaseStarted=t;}
        else if(r.phase==='p2'&&v.p1===0&&v.p2===1){r.phase='ready';r.generation=v.generation;r.advanced=t;}
        if(t-r.started>7000)throw Error('join_timeout');
        controlPads(r.phase==='p1'?0:r.phase==='p2'?1:-1,{buttons:0x10});
      }
    }catch(error){r.errors.push(String(error));try{controlRelease('guard');}catch(_){r.errors.push('release_failed');}}
  },50);
  return controlStatus();
}
function controlAction(name,role,durationMs){
  if(!Object.hasOwn(CONTROL_ACTIONS,name)||![0,1].includes(role)||!Number.isInteger(durationMs)||durationMs<50||durationMs>1000)throw Error('invalid_action');
  const r=controlRun,s=snapshot();controlGuard(s);
  if(!r?.running||r.phase!=='ready'||r.action||s.stage!==r.stage||s.generation!==r.generation||s.p1!==0||s.p2!==1)throw Error('control_unavailable');
  const menu=['menu','inventory','menu_up','menu_down','confirm','cancel'].includes(name);
  if((s.menu_gated&&!menu)||(menu&&role!==0))throw Error('action_context');
  if(name==='dodge'){
    if(durationMs<350)throw Error('dodge_requires_350ms');
    const w=typeof worldLatest==='function'?worldLatest():null,p=w?.party?.[role];
    if(!p||w.stage!==s.stage||w.generation!==s.generation||p.age_ms>1000||p.vocation!==2||p.primary_weapon!==0x04000000)throw Error('dodge_requires_observed_strider_daggers');
  }
  const now=Date.now();r.deadline=Math.min(now+30000,r.started+120000);
  r.action={name,role,menu,started:now,until:now+durationMs};
  return {accepted:true,action:name,role,duration_ms:durationMs,semantic_effect:'unverified'};
}
Object.assign(rpc.exports,{controlClaim,controlAction,controlRelease,controlStatus});
