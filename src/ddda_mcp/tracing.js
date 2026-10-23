// Read-only callbacks adapted from pinned Thingolus research (MIT).
// Definitions only: no hooks or timers until a reviewed trace is explicitly started.
let traceRun = null;
function traceBytes(address, n) {
  return Array.from(new Uint8Array(address.readByteArray(n))).map(x=>x.toString(16).padStart(2,'0')).join('');
}
function traceReadable(p,n) {
  if(p.isNull()) return false;
  const r=Process.findRangeByAddress(p);
  return !!r && r.protection.includes('r') && p.add(n).compare(r.base.add(r.size)) <= 0;
}
function traceParty(actor) {
  if(!traceReadable(actor,0x585c) || !actor.add(0x32bc).readPointer().equals(actor)) return null;
  const gs=ptr('0x18fa4bc').readPointer();
  if(!traceReadable(gs,0xa7ec0+0x2ac) || gs.readU32()!==0x155db00) return null;
  const info=actor.add(0x3dec).readPointer();
  const role=info.equals(gs.add(0xa76d0))?0:info.equals(gs.add(0xa7ec0))?1:-1;
  if(role<0 || actor.readU32()!==(role===0?0x15e90d0:0x15e8468)) return null;
  const flags=actor.add(0x206d).readU8();
  if(role===0?!(flags&2):(!(flags&4)||actor.add(0x5854).readU32()!==0)) return null;
  return {actor,gs,info,role,stage:gs.add(0x34).readU32(),action:actor.add(0x2dd4).readU32()};
}
function traceLife(life) {
  if(!traceReadable(life,0x1b8)) return null;
  const actor=life.add(0x1b4).readPointer();
  if(!traceReadable(actor,0x1d1c) || ![0x15a4610,0x15b9b98].includes(actor.readU32())) return null;
  const count=actor.add(0x1d0c).readU32(), table=actor.add(0x1d18).readPointer();
  if(count<1 || count>64 || !traceReadable(table,count*4)) return null;
  let index=-1; for(let i=0;i<count;i++) if(table.add(i*4).readPointer().equals(life)){index=i;break;}
  if(index<0) return null;
  const current=life.add(8).readFloat(),maximum=life.add(12).readFloat();
  if(!Number.isFinite(current)||!Number.isFinite(maximum))return null;
  if(!life.add(0x1b4).readPointer().equals(actor)||actor.add(0x1d0c).readU32()!==count||!actor.add(0x1d18).readPointer().equals(table)||!table.add(index*4).readPointer().equals(life))return null;
  return {actor,table,count,index,current,maximum,part:life.add(4).readU32()};
}
async function traceStop() {
  const r=traceRun;if(!r)return {running:false,sealed:true,rows:[]};
  if(r.stopping)return r.stopping;
  r.stopping=(async()=>{
  r.running=false;clearTimeout(r.timer);
  const deadline=Date.now()+250;
  while(r.active&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,5));
  if(!r.detached){r.hook.detach();r.detached=true;Interceptor.flush();}
  await new Promise(resolve=>setTimeout(resolve,5));
  const restored=traceBytes(r.address,r.spec.bytes.length/2)===r.spec.bytes;
  return {running:false,sealed:restored&&r.active===0,prefix_restored:restored,active_callbacks:r.active,
    symbol:r.name,rows:r.rows,omitted:r.omitted,errors:r.errors,started_ms:r.started,stopped_ms:Date.now()};
  })();return r.stopping;
}
async function traceStart(name,durationMs) {
  if(!Object.hasOwn(REVIEWED_TRACES,name)||!Number.isInteger(durationMs)||durationMs<100||durationMs>30000)throw Error('invalid_trace');
  if(traceRun && (traceRun.running || traceRun.active || !(await traceStop()).sealed))throw Error('trace_busy');
  const s=snapshot(), spec=REVIEWED_TRACES[name], address=Process.mainModule.base.add(spec.rva);
  if(s.runtime!==2||s.guard_transport!==2||s.transport!==2||s.native_offline!==1||s.native_errors||s.faults||s.developer_input!==1||!s.stage||!s.generation)throw Error('trace_admission_failed');
  if(traceBytes(address,spec.bytes.length/2)!==spec.bytes)throw Error('trace_signature_changed_or_already_hooked');
  const r={name,spec,address,running:true,active:0,rows:[],omitted:0,errors:[],started:Date.now(),hook:null,timer:null};
  traceRun=r;
  try {
    r.hook=Interceptor.attach(address,{
      onEnter(){
        if(!r.running || Date.now()>r.started+durationMs)return;
        this.counted=true;r.active++;
        if(r.rows.length>=256){r.omitted++;return;}
        try {
          const row={time_ms:Date.now(),thread:Process.getCurrentThreadId(),kind:spec.kind};
          if(r.world){worldSample(this.context.eax);return;}
          const value=this.context.esp.add(4).readFloat();
          if(!Number.isFinite(value))throw Error('nonfinite_argument');
          if(spec.kind==='stamina'){
            const who=traceParty(this.context.eax);if(!who||who.stage!==s.stage)return;
            const stamina=who.info.add(0x2a8).readFloat(),end=traceParty(who.actor);
            if(!end||!end.gs.equals(who.gs)||!end.info.equals(who.info)||end.stage!==who.stage||!Number.isFinite(stamina))return;
            Object.assign(row,{role:who.role,stage:who.stage,action:who.action,requested_delta:value,stamina_before:stamina});
          }else{
            const life=this.context.eax,before=traceLife(life);if(!before)return;
            this.life=life;this.before=before;
            Object.assign(row,{part:before.part,main_resource:before.index===0,hp_before:before.current,hp_max:before.maximum,requested_damage:value});
          }
          this.row=row;r.rows.push(row);
        }catch(_){if(r.errors.length<8)r.errors.push('callback_read_failed');}
      },
      onLeave(){if(!this.counted)return;
        try {
          if(this.row&&this.life){const after=traceLife(this.life),before=this.before;
            if(after&&after.actor.equals(before.actor)&&after.table.equals(before.table)&&after.count===before.count&&after.index===before.index&&after.part===before.part){
              this.row.hp_after=after.current;this.row.applied_damage=before.current-after.current;
            }else this.row.lifetime_changed=true;
          }
        }catch(_){if(r.errors.length<8)r.errors.push('callback_read_failed');}
        finally {r.active--;}
      }
    });
    r.timer=setTimeout(()=>{traceStop().catch(()=>r.errors.push('deadline_cleanup_failed'));},durationMs);
    return {started:true,symbol:name,duration_ms:durationMs};
  }catch(error){r.running=false;if(r.hook)r.hook.detach();throw error;}
}
