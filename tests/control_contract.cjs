const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
async function main(){
let now=1000,tick,writes=0,last;
class BufferPointer{
 constructor(b,o=0){this.b=b;this.o=o;}add(n){return new BufferPointer(this.b,this.o+n);}
 writeByteArray(a){this.b.set(a,this.o);}writeU8(n){this.b.writeUInt8(n,this.o);}
 writeU32(n){this.b.writeUInt32LE(n,this.o);}writeU16(n){this.b.writeUInt16LE(n,this.o);}
 writeS16(n){this.b.writeInt16LE(n,this.o);}
}
const state={runtime:2,guard_transport:2,transport:2,native_offline:1,native_errors:0,faults:0,
 developer_input:1,stage:220,generation:1,menu_gated:0,p1:-1,p2:-1,physical_mask:1,
 actors:[{observed:1,frames:1},{observed:1,frames:1}]};
let progressing=true;
const menuFields=['generation','blocked','native_known','native_gameplay','lifetime_state'];
let menu={lifetime_state:1,blocked:0,native_known:1,native_gameplay:1};
const ctx={REVIEWED_GROUPS:{inventory_menu:{fields:menuFields}},rpc:{exports:{copiedGroup:()=>menuFields.map(k=>k==='generation'?(menu.generation??state.generation):menu[k])}},Date:{now:()=>now},snapshot:()=>JSON.parse(JSON.stringify(state)),
 Memory:{alloc:n=>new BufferPointer(Buffer.alloc(n))},Uint8Array,nextInputPacket:()=>now,
 call:()=>p=>{writes++;last=Buffer.from(p.b);return 1;},
 setTimeout:fn=>{now+=100;if(progressing)state.actors[0].frames++;fn();},
 setInterval:fn=>{tick=fn;return 1;},clearInterval:()=>{tick=null;}};
vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
assert.equal(writes,0);assert.equal(tick,undefined);
await ctx.controlClaim();assert.equal(last[0],1);assert.equal(last[20],1);
function advance(ms=400){now+=ms;state.actors.forEach(a=>a.frames++);tick();}
advance();assert.equal(last.readUInt16LE(8),0x10);
state.p1=0;state.generation++;advance();assert.equal(last.readUInt16LE(8),0);
advance();assert.equal(last.readUInt16LE(28),0x10);
state.p2=1;state.generation++;advance();assert.equal(ctx.controlStatus().phase,'ready');
assert.throws(()=>ctx.controlAction('raw_memory',0,250),/invalid_action/);
ctx.controlAction('forward',0,250);advance(50);assert.equal(last.readInt16LE(12),16000);
advance(300);assert.equal(last.readInt16LE(12),0);assert.equal(ctx.controlStatus().action,null);
for(const [name,offset,value] of [['run_forward',12,32767],['run_backward',12,-32767],['run_left',10,-32767],['run_right',10,32767],['camera_left',14,-16000],['camera_right',14,16000],['camera_up',16,16000],['camera_down',16,-16000],['jump_forward',12,32767]]){
  ctx.controlAction(name,1,1000);advance(50);
  assert.equal(last.readInt16LE(20+offset),value);assert.equal(last.readInt16LE(offset),0);
  if(name==='jump_forward')assert.equal(last.readUInt16LE(28),0x1000);
  advance(1000);assert.equal(last.readInt16LE(20+offset),0);
  assert.throws(()=>ctx.controlAction(name,1,1001),/invalid_action/);
  state.menu_gated=1;assert.throws(()=>ctx.controlAction(name,1,1000),/action_context/);state.menu_gated=0;
}
assert.throws(()=>ctx.controlAction('dodge',0,350),/strider/);
assert.throws(()=>ctx.controlAction('dodge',0,100),/350ms/);
state.generation++;advance();assert.equal(ctx.controlStatus().running,false);assert.equal(last[0],0);
assert.equal(last[20],0);assert.equal(tick,null);
state.p1=0;state.p2=1;await ctx.controlClaim();advance(31000);
assert.equal(ctx.controlStatus().running,false);assert.equal(last[0],0);
assert(ctx.controlStatus().errors.some(e=>e.includes('expired')));
// Solo owns only slot 0; the main pawn remains disconnected for native AI.
state.p1=-1;state.p2=-1;
const beforeInvalid=writes;
await assert.rejects(ctx.controlClaim('unknown'),/invalid_control_mode/);
assert.equal(writes,beforeInvalid);
await ctx.controlClaim('solo');assert.equal(last[0],1);assert.equal(last[20],0);
advance();assert.equal(last.readUInt16LE(8),0x10);
state.p1=0;state.generation++;advance();
assert.equal(ctx.controlStatus().phase,'ready');assert.equal(ctx.controlStatus().mode,'solo');
assert.equal(last.readUInt16LE(8),0);assert.equal(last[20],0);
assert.throws(()=>ctx.controlAction('forward',1,250),/role_not_controlled/);
ctx.controlAction('forward',0,250);advance(50);
assert.equal(last.readInt16LE(12),16000);assert.equal(last[20],0);
advance(300);assert.equal(last.readInt16LE(12),0);assert.equal(last[20],0);
state.p2=1;advance();assert.equal(ctx.controlStatus().running,false);
assert.equal(last[0],0);assert.equal(last[20],0);
await assert.rejects(ctx.controlClaim('solo'),/assignment_or_menu_conflict/);
state.p1=-1;state.p2=-1;await ctx.controlClaim('solo');advance(31000);
assert.equal(ctx.controlStatus().running,false);assert.equal(last[0],0);assert.equal(last[20],0);
// P2's downed gate must not prevent freshly observed solo P1 movement.
state.menu_gated=1;state.p1=0;state.p2=-1;
await ctx.controlClaim('solo');advance(50);
ctx.controlAction('forward',0,250);advance(50);
assert.equal(last.readInt16LE(12),16000);assert.equal(last[20],0);
// A real canonical menu, stale callback, or mismatched generation revokes it.
menu.native_gameplay=0;advance(50);
assert.equal(ctx.controlStatus().running,false);assert.equal(last[0],0);
const beforeRefusals=writes;
await assert.rejects(ctx.controlClaim('solo'),/assignment_or_menu_conflict/);
menu.native_gameplay=1;menu.blocked=1;
await assert.rejects(ctx.controlClaim('solo'),/assignment_or_menu_conflict/);
menu.blocked=0;menu.native_known=0;
await assert.rejects(ctx.controlClaim('solo'),/assignment_or_menu_conflict/);
menu.native_known=1;
for(const lifetime of [0,2,3]){menu.lifetime_state=lifetime;await assert.rejects(ctx.controlClaim('solo'),/assignment_or_menu_conflict/);}
menu.lifetime_state=1;menu.generation=state.generation+1;
await assert.rejects(ctx.controlClaim('solo'),/assignment_or_menu_conflict/);
delete menu.generation;progressing=false;
await assert.rejects(ctx.controlClaim('solo'),/assignment_or_menu_conflict/);
assert.equal(writes,beforeRefusals);
progressing=true;await ctx.controlClaim('solo');advance(50);
ctx.controlAction('forward',0,1000);now+=150;tick();
assert.equal(ctx.controlStatus().running,false);assert.equal(last[0],0);
// Native modals may leave the aggregate bit clear: no fresh callback, no claim.
state.menu_gated=0;progressing=false;
const beforeUngatedModal=writes;
await assert.rejects(ctx.controlClaim('solo'),/assignment_or_menu_conflict/);
progressing=true;menu.lifetime_state=2;
await assert.rejects(ctx.controlClaim('solo'),/assignment_or_menu_conflict/);
assert.equal(writes,beforeUngatedModal);
menu.lifetime_state=1;state.menu_gated=1;
// A release while a gated claim waits must cancel admission without new input.
let resumeClaim;ctx.setTimeout=fn=>{resumeClaim=fn;};
const pendingClaim=ctx.controlClaim('solo');
await assert.rejects(ctx.controlClaim('solo'),/control_busy/);
ctx.controlRelease();const afterCancel=writes;
now+=100;state.actors[0].frames++;resumeClaim();
await assert.rejects(pendingClaim,/control_claim_cancelled/);
assert.equal(writes,afterCancel);assert.equal(last[0],0);
// The exception cannot admit pair control.
await assert.rejects(ctx.controlClaim('pair'),/assignment_or_menu_conflict/);
console.log('control contract passed');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
