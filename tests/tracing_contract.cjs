// Exercise shipped observer callbacks with synthetic native memory, never a game.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const regions=[];
function allocate(address,size){const r={address,buffer:Buffer.alloc(size)};regions.push(r);return new P(address);}
class P {
  constructor(address){this.address=address;}
  add(n){return new P(this.address+n);}
  equals(p){return this.address===p.address;}
  compare(p){return Math.sign(this.address-p.address);}
  isNull(){return this.address===0;}
  region(){const r=regions.find(r=>this.address>=r.address&&this.address<r.address+r.buffer.length);if(!r)throw Error('unreadable');return r;}
  readU32(){const r=this.region();return r.buffer.readUInt32LE(this.address-r.address);}
  readU8(){const r=this.region();return r.buffer.readUInt8(this.address-r.address);}
  readFloat(){const r=this.region();return r.buffer.readFloatLE(this.address-r.address);}
  readPointer(){return new P(this.readU32());}
  readByteArray(n){const r=this.region();return r.buffer.subarray(this.address-r.address,this.address-r.address+n);}
  u32(offset,n){const r=this.region();r.buffer.writeUInt32LE(n,this.address-r.address+offset);}
  f32(offset,n){const r=this.region();r.buffer.writeFloatLE(n,this.address-r.address+offset);}
}
const specs={native_stamina_apply:{rva:0x781e30,bytes:'83ec08538a5c241855568bf08baeec3d',kind:'stamina'},
 goblin_health_subtract:{rva:0x376f50,bytes:'51578bf8f64730010f85c90000008b87b8010000f680fc0c0000010f85b60000',kind:'health'}};
for(const spec of Object.values(specs))allocate(0x400000+spec.rva,64).region().buffer.set(Buffer.from(spec.bytes,'hex'));
const gs=allocate(0x20000000,0xa8200),actor=allocate(0x30000000,0x6000),stack=allocate(0x50000000,32);
allocate(0x18fa4bc,4).u32(0,gs.address);gs.u32(0,0x155db00);gs.u32(0x34,220);
actor.u32(0,0x15e90d0);actor.u32(0x32bc,actor.address);actor.u32(0x3dec,gs.address+0xa76d0);
actor.u32(0x206d,2);actor.u32(0x2dd4,5);gs.f32(0xa76d0+0x2a8,99.5);stack.f32(4,-.5);
let listener,attachments=0,detaches=0,timers=0;
const healthy={runtime:2,guard_transport:2,transport:2,native_offline:1,native_errors:0,faults:0,developer_input:1,stage:220,generation:1};
const context={REVIEWED_TRACES:specs,Uint8Array,Date,ptr:x=>new P(Number(x)),snapshot:()=>({...healthy}),
 Process:{mainModule:{base:new P(0x400000)},getCurrentThreadId:()=>77,
 findRangeByAddress:p=>{try{const r=p.region();return {base:new P(r.address),size:r.buffer.length,protection:'rw-'};}catch{return null;}}},
 Interceptor:{attach:(address,callbacks)=>{attachments++;listener=callbacks;return {detach:()=>{detaches++;}};},flush:()=>{}},
 setTimeout:()=>{timers++;return 1;},clearTimeout:()=>{}}
vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),context);
assert.equal(attachments,0);assert.equal(timers,0);
assert.throws(()=>context.traceStart('arbitrary_native_function',500),/invalid_trace/);
healthy.native_offline=0;assert.throws(()=>context.traceStart('native_stamina_apply',500),/admission/);healthy.native_offline=1;
const prefix=new P(0xb81e30),original=Buffer.from(prefix.readByteArray(16));prefix.u32(0,0xe9);
assert.throws(()=>context.traceStart('native_stamina_apply',500),/signature/);prefix.region().buffer.set(original);
context.traceStart('native_stamina_apply',30000);
assert.throws(()=>context.traceStart('native_stamina_apply',500),/trace_busy/);
for(let i=0;i<260;i++){const invocation={context:{eax:actor,esp:stack}};listener.onEnter.call(invocation);listener.onLeave.call(invocation);}
let result=context.traceStop();assert.equal(result.sealed,true);assert.equal(result.rows.length,256);assert.equal(result.omitted,4);
assert.equal(result.rows[0].stamina_before,99.5);assert.equal(result.rows[0].requested_delta,-.5);
assert.equal(result.rows[0].role,0);assert.equal(detaches,1);context.traceStop();assert.equal(detaches,1);
assert(!JSON.stringify(result).includes(String(actor.address)));assert(!JSON.stringify(result).includes('pointer'));
const enemy=allocate(0x40000000,0x2000),life=allocate(0x41000000,0x200),table=allocate(0x42000000,4);
enemy.u32(0,0x15a4610);enemy.u32(0x1d0c,1);enemy.u32(0x1d18,table.address);table.u32(0,life.address);
life.u32(0x1b4,enemy.address);life.f32(8,100);life.f32(12,200);stack.f32(4,10);
context.traceStart('goblin_health_subtract',30000);
let invocation={context:{eax:life,esp:stack}};listener.onEnter.call(invocation);life.f32(8,90);listener.onLeave.call(invocation);
invocation={context:{eax:life,esp:stack}};listener.onEnter.call(invocation);table.u32(0,0);listener.onLeave.call(invocation);
result=context.traceStop();assert(result.sealed);assert.equal(result.rows[0].applied_damage,10);assert.equal(result.rows[1].lifetime_changed,true);
assert.equal(result.active_callbacks,0);assert.equal(detaches,2);
console.log('tracing contract passed');
