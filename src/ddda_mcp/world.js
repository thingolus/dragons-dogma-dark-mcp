// Callback-only copied world inspector. MIT, Thingolus and contributors.
// Layouts: observe_mage_healing, party_inventory_snapshot, grab_registry at pinned source.
let worldRun=null,worldIdentity=0;
function worldFinite(p,o){const v=p.add(o).readFloat();if(!Number.isFinite(v))throw Error('nonfinite_world');return v;}
function worldLife(actor){
  const n=actor.add(0x1d0c).readU32(),list=actor.add(0x1d18).readPointer();
  if(!n||n>64||!traceReadable(list,n*4))return null;
  const node=list.readPointer();
  if(!traceReadable(node,0x1b8)||!node.add(0x1b4).readPointer().equals(actor))return null;
  const out={hp:worldFinite(node,8),hp_max:worldFinite(node,12)};
  if(actor.add(0x1d0c).readU32()!==n||!actor.add(0x1d18).readPointer().equals(list)||!list.readPointer().equals(node)||!node.add(0x1b4).readPointer().equals(actor))return null;
  return out;
}
function worldInventory(role){
  const manager=ptr('0x18fa4d4').readPointer(),offset=role*0x11e8+0x178;
  if(!traceReadable(manager,offset+0x18))return {available:false};
  const container=manager.add(offset),count=container.add(8).readU32(),table=container.add(0x14).readPointer();
  if(count>256||(count&&!traceReadable(table,count*4)))return {available:false};
  const items=[];
  for(let i=0;i<count;i++){
    const entry=table.add(i*4).readPointer();if(!traceReadable(entry,0x24))return {available:false};
    const item={item_id:entry.add(0x10).readS16(),quantity:entry.add(0x12).readU16()};
    if(!table.add(i*4).readPointer().equals(entry))return {available:false};items.push(item);
  }
  if(!ptr('0x18fa4d4').readPointer().equals(manager)||container.add(8).readU32()!==count||!container.add(0x14).readPointer().equals(table))return {available:false};
  return {available:true,items};
}
function worldId(r,actor,signature){
  const key=actor.toString(),old=r.ids.get(key);
  if(old&&old.signature===signature){old.seen=Date.now();return old.id;}
  if(r.ids.size>=256)r.ids.clear();
  const value={id:'actor-'+(++worldIdentity),signature,seen:Date.now()};r.ids.set(key,value);return value.id;
}
function worldEnemies(r,position){
  const manager=ptr('0x18fa4d8').readPointer();if(!traceReadable(manager,0x34))return {available:false};
  const count=manager.add(0x24).readU32(),table=manager.add(0x30).readPointer();
  if(count>4096||(count&&!traceReadable(table,count*4)))return {available:false};
  const rows=[],scanned=Math.min(count,256);
  for(let i=0;i<scanned&&rows.length<24;i++){
    const entry=table.add(i*4).readPointer();if(!traceReadable(entry,0x54))continue;
    if(entry.add(0x50).readS32()>=1||!entry.add(0x4c).readU8()||entry.add(0x4d).readU8()===1)continue;
    const actor=entry.add(0x48).readPointer();if(!traceReadable(actor,0x585c))continue;
    const flags=actor.add(0x206d).readU8();if(!(flags&8))continue;
    const vt=actor.readU32(),pos=[0xe0,0xe4,0xe8].map(o=>worldFinite(actor,o));
    const distance=Math.hypot(...pos.map((v,j)=>v-position[j]));if(distance>3000)continue;
    const category=actor.add(0x1fc0).readU32(),type=actor.add(0x5858).readU32();
    const resources=[0x15a4610,0x15b9b98].includes(vt)?worldLife(actor):null;
    if(!table.add(i*4).readPointer().equals(entry)||!entry.add(0x48).readPointer().equals(actor)||actor.readU32()!==vt)continue;
    rows.push({id:worldId(r,actor,`${vt}:${type}`),type,category,position:pos,distance,resources});
  }
  if(!ptr('0x18fa4d8').readPointer().equals(manager)||manager.add(0x24).readU32()!==count||!manager.add(0x30).readPointer().equals(table))return {available:false};
  return {available:true,rows,registry_count:count,scanned,truncated:count>scanned||rows.length===24,radius_game_units:3000};
}
function worldSample(actor){
  const r=worldRun;if(!r)return;
  const who=traceParty(actor);if(!who||who.stage!==r.stage)return;
  const now=Date.now();if(now-r.times[who.role]<200)return;r.times[who.role]=now;
  const s=snapshot();if(s.stage!==r.stage||s.generation!==r.generation||s.native_errors||s.faults)return;
  const position=[0xe0,0xe4,0xe8].map(o=>worldFinite(actor,o));
  const resources=worldLife(actor),inventory=worldInventory(who.role);
  const row={id:worldId(r,actor,`${who.role}:${who.info}`),role:who.role,observed_ms:now,
    action:who.action,position,vocation:who.info.add(0x10).readU8(),primary_weapon:who.info.add(0x14).readU32(),
    resources:resources?{...resources,stamina:worldFinite(who.info,0x2a8),hp_white:worldFinite(who.info,0x2a4)}:null,inventory};
  const enemies=worldEnemies(r,position),end=traceParty(actor);
  if(!end||!end.gs.equals(who.gs)||!end.info.equals(who.info)||end.stage!==who.stage||snapshot().generation!==r.generation)return;
  r.party[who.role]=row;r.enemies={...enemies,observed_ms:now,origin_role:who.role,origin_position:position,
    scope:'Nearby registry candidates around the last sampled party actor; hostility is not established.'};r.samples++;
  for(const [key,value] of r.ids)if(now-value.seen>1000)r.ids.delete(key);
}
function worldLatest(){
  const r=worldRun;if(!r)return {available:false};const now=Date.now();
  return {available:true,stage:r.stage,generation:r.generation,samples:r.samples,
    party:r.party.map(p=>p?{...p,age_ms:now-p.observed_ms}:null),enemies:r.enemies?{...r.enemies,age_ms:now-r.enemies.observed_ms}:null,
    quests:{available:false,reason:'No reviewed quest-state layout; checkpoint labels are not quest observations.'},
    identity_scope:'Opaque IDs within this capture and observed lifetime; address reuse between callbacks cannot be excluded.'};
}
async function worldStart(durationMs){
  const started=await traceStart('native_stamina_apply',durationMs,true),s=snapshot();
  worldRun={stage:s.stage,generation:s.generation,times:[0,0],party:[null,null],enemies:null,ids:new Map(),samples:0};
  traceRun.world=true;return started;
}
async function worldStop(){const cleanup=await traceStop();return {world:worldLatest(),cleanup};}
Object.assign(rpc.exports,{worldStart,worldStop,worldLatest});
