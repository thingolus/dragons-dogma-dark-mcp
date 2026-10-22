// Exercise the actual shipped agent through a minimal synthetic Frida ABI.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let inputCalls = 0, statusSize = 132, statusVersion = 2;
class Pointer {
  constructor(buffer, offset=0) { this.buffer=buffer; this.offset=offset; }
  add(n) { return new Pointer(this.buffer,this.offset+n); }
  readU32() { return this.buffer.readUInt32LE(this.offset); }
  readS32() { return this.buffer.readInt32LE(this.offset); }
  readU64() { return this.buffer.readBigUInt64LE(this.offset); }
  readFloat() { return this.buffer.readFloatLE(this.offset); }
  writeU8(n) { this.buffer.writeUInt8(n,this.offset); }
  writeU32(n) { this.buffer.writeUInt32LE(n,this.offset); }
  writeByteArray(bytes) { Buffer.from(bytes).copy(this.buffer,this.offset); }
}
const context = {
  Process:{arch:'ia32',pointerSize:4, mainModule:{base:{toString:()=> '0x400000'}},
           getModuleByName:()=>({getExportByName:name=>name})},
  Memory:{alloc:n=>new Pointer(Buffer.alloc(n))},
  NativeFunction:function(name) {
    if(name==='CoopGetStatus') return (p,size)=>{
      assert.equal(size,132); p.writeU32(statusSize); p.add(4).writeU32(statusVersion);
      p.add(8).writeU32(2);p.add(24).writeU32(2);p.add(28).writeU32(1);p.add(52).writeU32(1);
      return 1;
    };
    if(name==='CoopGetPerformanceStatus') return (p,size)=>{
      assert.equal(size,2448);p.writeU32(2448);p.add(4).writeU32(1);
      p.buffer.writeBigUInt64LE(9007199254740993n,16); return 1;
    };
    if(name==='CoopSetTestPads') return (p,count)=>{ assert.equal(count,4);inputCalls++;return 1; };
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
console.log('agent contract passed: inert load, no-input reads, ABI refusal, exact uint64, explicit input only');
