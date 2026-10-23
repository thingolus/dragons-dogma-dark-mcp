// Exercise the actual shipped agent through a minimal synthetic Frida ABI.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let inputCalls = 0, statusSize = 132, statusVersion = 2, stage = 0, lastButtons = 0;
let generation = 0, observed = 0, menu = 0, physical = 0, offline = 1, lastPads;
let developer = 1, deathAccepted = 1, deathVersion = 1, deathCalls = 0, deathMissing = false;
const groups = JSON.parse(process.argv[3]);
let copiedAccepted = 1, copiedVersionOffset = 0, copiedCalls = 0;
class Pointer {
  constructor(buffer, offset=0) { this.buffer=buffer; this.offset=offset; }
  add(n) { return new Pointer(this.buffer,this.offset+n); }
  readU32() { return this.buffer.readUInt32LE(this.offset); }
  readS32() { return this.buffer.readInt32LE(this.offset); }
  readU64() { return this.buffer.readBigUInt64LE(this.offset); }
  readFloat() { return this.buffer.readFloatLE(this.offset); }
  writeU8(n) { this.buffer.writeUInt8(n,this.offset); }
  writeU32(n) { this.buffer.writeUInt32LE(n,this.offset); }
  writeU16(n) { this.buffer.writeUInt16LE(n,this.offset); }
  writeS16(n) { this.buffer.writeInt16LE(n,this.offset); }
  writeByteArray(bytes) { Buffer.from(bytes).copy(this.buffer,this.offset); }
}
const context = {
  REVIEWED_GROUPS:groups,
  Process:{arch:'ia32',pointerSize:4, mainModule:{base:{toString:()=> '0x400000'}},
           getModuleByName:()=>({getExportByName:name=>{if(deathMissing && name==='CoopSharedLifeDownDebugStatus')throw Error('missing');return name;}})},
  Memory:{alloc:n=>new Pointer(Buffer.alloc(n))},
  NativeFunction:function(name) {
    const spec=Object.values(groups).find(g=>g.export===name);
    if(spec) return (p,count)=>{
      copiedCalls++;
      assert.equal(p.buffer.length,spec.size);
      assert.equal(count,spec.words_arg?spec.size/4:spec.size);
      p.writeU32(spec.size);p.add(4).writeU32(spec.version+copiedVersionOffset);
      return copiedAccepted;
    };
    if(name==='OfflineState') return ()=>2;
    if(name==='CoopGetStatus') return (p,size)=>{
      assert.equal(size,132); p.writeU32(statusSize); p.add(4).writeU32(statusVersion);
      p.add(8).writeU32(2);p.add(24).writeU32(2);p.add(28).writeU32(offline);p.add(52).writeU32(developer);
      p.add(40).writeU32(stage);
      p.add(12).writeU32(2); p.add(16).writeU32(3);
      p.add(44).writeU32(generation); p.add(48).writeU32(physical); p.add(56).writeU32(menu);
      p.add(60).writeU32(observed); p.add(96).writeU32(observed);
      return 1;
    };
    if(name==='CoopGetPerformanceStatus') return (p,size)=>{
      assert.equal(size,2448);p.writeU32(2448);p.add(4).writeU32(1);
      p.buffer.writeBigUInt64LE(9007199254740993n,16); return 1;
    };
    if(name==='CoopSharedLifeDownDebugStatus') return (p,count)=>{
      deathCalls++;assert.equal(count,520);assert.equal(p.buffer.length,2080);
      [2080,deathVersion,64,8,0,0,0,0].forEach((n,i)=>p.add(i*4).writeU32(n));
      for(let row=0;row<8;row++) for(const col of [4,14,15,16,17,18,19,20,36])
        p.add((8+row*64+col)*4).writeU32(0xdecafbad);
      return deathAccepted;
    };
    if(name==='CoopSetTestPads') return (p,count)=>{ assert.equal(count,4);lastPads=Buffer.from(p.buffer);lastButtons=p.buffer.readUInt16LE(8);inputCalls++;return 1; };
    throw Error('Unexpected native call: '+name);
  },
  rpc:{exports:{}}, Uint8Array,
  setInterval:()=>{throw Error('Agent must not start a timer on import');}
};
vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),context);
assert.equal(inputCalls,0);
assert.equal(context.rpc.exports.snapshot().version,2);
assert.equal(inputCalls,0);
assert.equal(context.rpc.exports.performance().frequency,'9007199254740993');
assert.equal(inputCalls,0);
statusVersion=99; assert.throws(()=>context.rpc.exports.snapshot(),/abi_mismatch/);
statusVersion=2; statusSize=128; assert.throws(()=>context.rpc.exports.snapshot(),/abi_mismatch/);
statusSize=132;
assert.throws(()=>context.rpc.exports.neutral('true'),/invalid_parameters/);
context.rpc.exports.neutral(true);context.rpc.exports.neutral(false);assert.equal(inputCalls,2);
context.rpc.exports.titleStart(true);assert.equal(lastButtons,0x10);
stage=220;assert.throws(()=>context.rpc.exports.titleStart(true),/not_title_state/);
context.rpc.exports.titleStart(false);assert.equal(lastButtons,0);
assert.throws(()=>context.rpc.exports.movementPulse('arbitrary',220,1),/invalid_parameters/);
assert.throws(()=>context.rpc.exports.movementPulse('p1_step_forward',220,1),/input_admission_failed/);
generation=1;observed=1;
let previousPacket=0;
for (const [name,slot,offset] of [['p1_step_forward',2,12],['p1_step_right',2,10],['p2_step_forward',3,12]]) {
  context.rpc.exports.movementPulse(name,220,1);
  const packet=lastPads.readUInt32LE(slot*20+4);assert.ok(packet>previousPacket);previousPacket=packet;
  assert.equal(lastPads.readInt16LE(slot*20+offset),16000);
  for(let i=0;i<4;i++) assert.equal(lastPads.readUInt16LE(i*20+8),0);
}
for (const guard of ['menu','physical','offline','generation']) {
  const count=inputCalls;
  if(guard==='menu')menu=1;if(guard==='physical')physical=1;if(guard==='offline')offline=0;if(guard==='generation')generation=2;
  assert.throws(()=>context.rpc.exports.movementPulse('p1_step_forward',220,1),/input_admission_failed/);
  assert.equal(inputCalls,count);
  menu=physical=0;offline=generation=1;
}
context.rpc.exports.neutral(false);assert.ok(lastPads.every(b=>b===0));
const priorInputs=inputCalls;
const death=context.rpc.exports.deathRefusals();
assert.equal(death.length,520);assert.ok(!death.includes(0xdecafbad));assert.equal(inputCalls,priorInputs);
developer=0;const priorDeaths=deathCalls;
assert.throws(()=>context.rpc.exports.deathRefusals(),/diagnostic_admission_failed/);assert.equal(deathCalls,priorDeaths);
developer=1;deathMissing=true;assert.throws(()=>context.rpc.exports.deathRefusals(),/diagnostic_unavailable/);
deathMissing=false;deathAccepted=0;assert.throws(()=>context.rpc.exports.deathRefusals(),/diagnostic_refused/);
deathAccepted=1;deathVersion=2;assert.throws(()=>context.rpc.exports.deathRefusals(),/abi_mismatch/);
assert.equal(inputCalls,priorInputs);
for(const [name,spec] of Object.entries(groups)) {
  const words=context.rpc.exports.copiedGroup(name);
  assert.equal(words.length,spec.size/4);assert.equal(words[1],spec.version);
}
assert.equal(inputCalls,priorInputs);
assert.throws(()=>context.rpc.exports.copiedGroup('arbitrary'),/diagnostic_unavailable/);
developer=0;const priorCopied=copiedCalls;
assert.throws(()=>context.rpc.exports.copiedGroup('shared_life'),/diagnostic_admission_failed/);
assert.equal(copiedCalls,priorCopied);developer=1;
copiedAccepted=0;assert.throws(()=>context.rpc.exports.copiedGroup('shared_life'),/diagnostic_refused/);
copiedAccepted=1;copiedVersionOffset=1;
assert.throws(()=>context.rpc.exports.copiedGroup('shared_life'),/abi_mismatch/);
assert.equal(inputCalls,priorInputs);
console.log('agent contract passed: inert load, no-input reads, ABI refusal, exact uint64, explicit input only, redacted death diagnostics');
