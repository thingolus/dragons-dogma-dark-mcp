const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
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
const ctx={rpc:{exports:{}},Date:{now:()=>now},snapshot:()=>JSON.parse(JSON.stringify(state)),
 Memory:{alloc:n=>new BufferPointer(Buffer.alloc(n))},Uint8Array,nextInputPacket:()=>now,
 call:()=>p=>{writes++;last=Buffer.from(p.b);return 1;},
 setInterval:fn=>{tick=fn;return 1;},clearInterval:()=>{tick=null;}};
vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
assert.equal(writes,0);assert.equal(tick,undefined);
ctx.controlClaim();assert.equal(last[0],1);assert.equal(last[20],1);
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
state.p1=0;state.p2=1;ctx.controlClaim();advance(31000);
assert.equal(ctx.controlStatus().running,false);assert.equal(last[0],0);
assert(ctx.controlStatus().errors.some(e=>e.includes('expired')));
console.log('control contract passed');
