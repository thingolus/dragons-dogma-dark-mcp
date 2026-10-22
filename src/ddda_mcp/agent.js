// Copied-value diagnostics adapted from DDDA Local Coop, by Thingolus and
// project contributors (MIT). No timers, hooks, or input writes on load.
'use strict';
let inputPacket = 0;
function nextInputPacket() { inputPacket = (inputPacket + 1) >>> 0; return inputPacket; }
function runtime() {
  if (Process.arch !== 'ia32' || Process.pointerSize !== 4 || Process.mainModule.base.toString() !== '0x400000')
    throw Error('unsupported_build');
  return Process.getModuleByName('ddcoop_runtime.dll');
}
function call(name, result, args) {
  return new NativeFunction(runtime().getExportByName(name), result, args, 'mscdecl');
}
function snapshot() {
  const buffer = Memory.alloc(132);
  if (call('CoopGetStatus', 'int', ['pointer', 'uint'])(buffer, 132) !== 1 ||
      buffer.readU32() !== 132 || buffer.add(4).readU32() !== 2) throw Error('abi_mismatch');
  const keys = ['size','version','runtime','p1','p2','session','transport','native_offline',
                'native_errors','faults','stage','generation','physical_mask','developer_input','menu_gated'];
  const result = {};
  keys.forEach((key, index) => result[key] = buffer.add(index * 4).readS32());
  // The copied transport/native fields are populated by game callbacks and may
  // still be zero at the title screen. Read the pinned transport guard directly.
  result.guard_transport = call('OfflineState', 'int', [])();
  result.actors = [0,1].map(index => {
    const p = buffer.add(60 + index * 36);
    return { observed:p.readU32(), action:p.add(4).readU32(), movement:p.add(8).readU32(),
      held:p.add(12).readU32(), frames:p.add(16).readU32(),
      position:[20,24,28].map(offset => p.add(offset).readFloat()), angle:p.add(32).readFloat() };
  });
  return result;
}
function performance() {
  const p = Memory.alloc(2448);
  if (call('CoopGetPerformanceStatus','int',['pointer','uint'])(p,2448) !== 1 ||
      p.readU32() !== 2448 || p.add(4).readU32() !== 1) throw Error('abi_mismatch');
  return {size:2448,version:1,state:p.add(8).readU32(),coverage_mask:p.add(12).readU32(),
    frequency:p.add(16).readU64().toString(),admitted_roots:p.add(24).readU64().toString(),
    completed_roots:p.add(32).readU64().toString(),active_roots:p.add(40).readU64().toString(),
    clock_failures:p.add(48).readU64().toString(),start_failures:p.add(56).readU64().toString(),
    coverage:'Existing callback-span instrumentation only; reading does not begin or seal collection.'};
}
function deathRefusals() {
  const s = snapshot();
  if (s.runtime !== 2 || s.guard_transport !== 2 || s.native_errors !== 0 ||
      s.faults !== 0 || s.developer_input !== 1) throw Error('diagnostic_admission_failed');
  let address;
  try { address = runtime().getExportByName('CoopSharedLifeDownDebugStatus'); }
  catch (_) { throw Error('diagnostic_unavailable: runtime lacks down-refusal export'); }
  const p = Memory.alloc(2080);
  if (new NativeFunction(address,'int',['pointer','uint'],'mscdecl')(p,520) !== 1)
    throw Error('diagnostic_refused');
  const words = Array.from({length:520}, (_, i) => p.add(i*4).readU32());
  if (words[0] !== 2080 || words[1] !== 1 || words[2] !== 64 || words[3] !== 8 ||
      words[4] > 8 || words[5] >= 8) throw Error('abi_mismatch');
  // Strip caller and opaque game addresses before crossing the adapter boundary.
  for (let row=0; row<8; row++)
    for (const column of [4,14,15,16,17,18,19,20,36]) words[8+row*64+column]=0;
  return words;
}
function neutralInput(connected) {
  const s = snapshot();
  if (s.runtime !== 2 || s.developer_input !== 1 || s.transport !== 2 || s.guard_transport !== 2 || s.native_offline !== 1 || s.native_errors !== 0 || s.faults !== 0)
    throw Error('input_admission_failed');
  const p = Memory.alloc(80);
  p.writeByteArray(new Uint8Array(80));
  const packet = nextInputPacket();
  if (connected) [0,1].forEach(i => {p.add(i*20).writeU8(1);p.add(i*20+4).writeU32(packet);});
  if (call('CoopSetTestPads','int',['pointer','uint'])(p,4) !== 1) throw Error('input_refused');
  return true;
}
rpc.exports = {
  snapshot, performance, deathRefusals,
  movementPulse(recipe, stage, generation) {
    const definitions = {p1_step_forward:[0,12],p1_step_right:[0,10],p2_step_forward:[1,12]};
    if (!Object.hasOwn(definitions, recipe) || !Number.isInteger(stage) || !Number.isInteger(generation))
      throw Error('invalid_parameters');
    const s = snapshot(), actor = definitions[recipe][0], slot = actor === 0 ? s.p1 : s.p2;
    if (s.runtime !== 2 || s.developer_input !== 1 || s.transport !== 2 || s.guard_transport !== 2 ||
        s.native_offline !== 1 || s.native_errors !== 0 || s.faults !== 0 || s.physical_mask !== 0 ||
        s.menu_gated !== 0 || stage === 0 || generation <= 0 || s.stage !== stage ||
        s.generation !== generation || s.actors[actor].observed !== 1 || slot < 0 || slot > 3 ||
        (s.p1 >= 0 && s.p1 === s.p2)) throw Error('input_admission_failed');
    const p = Memory.alloc(80); p.writeByteArray(new Uint8Array(80));
    const packet = nextInputPacket();
    [s.p1,s.p2].filter(i => i >= 0 && i <= 3).forEach(i => {
      p.add(i*20).writeU8(1); p.add(i*20+4).writeU32(packet);
    });
    p.add(slot*20+definitions[recipe][1]).writeS16(16000);
    if (call('CoopSetTestPads','int',['pointer','uint'])(p,4) !== 1) throw Error('input_refused');
    return true;
  },
  titleStart(pressed) {
    if (typeof pressed !== 'boolean') throw Error('invalid_parameters');
    const s = snapshot();
    if (s.runtime !== 2 || s.guard_transport !== 2 || s.developer_input !== 1 || s.native_errors !== 0 || s.faults !== 0)
      throw Error('input_admission_failed');
    if (pressed && (s.stage !== 0 || s.generation !== 0 || s.actors.some(a => a.observed !== 0)))
      throw Error('not_title_state');
    const p = Memory.alloc(80); p.writeByteArray(new Uint8Array(80));
    if (pressed) {p.writeU8(1);p.add(4).writeU32(nextInputPacket());p.add(8).writeU16(0x10);}
    if (call('CoopSetTestPads','int',['pointer','uint'])(p,4) !== 1) throw Error('input_refused');
    return true;
  },
  neutral(connected) { if (typeof connected !== 'boolean') throw Error('invalid_parameters'); return neutralInput(connected); },
  bootstrap(runtimePath) {
    if (Process.arch !== 'ia32' || Process.mainModule.base.toString() !== '0x400000') throw Error('unsupported_build');
    const module = Module.load(runtimePath);
    if (new NativeFunction(module.getExportByName('CoopInitialize'),'int',[],'mscdecl')() !== 1 ||
        new NativeFunction(module.getExportByName('OfflineState'),'int',[],'mscdecl')() !== 2)
      throw Error('offline_guard_failed');
    const ws = Process.getModuleByName('ws2_32.dll');
    const startup = new NativeFunction(ws.getExportByName('WSAStartup'),'int',['uint','pointer'],'stdcall');
    const socket = new SystemFunction(ws.getExportByName('socket'),'uint',['int','int','int'],'stdcall');
    const cleanup = new NativeFunction(ws.getExportByName('WSACleanup'),'int',[],'stdcall');
    if (startup(0x202,Memory.alloc(512)) !== 0) throw Error('offline_self_test_failed');
    let result;
    try { result=socket(2,1,6); } finally { cleanup(); }
    if (result.value !== 0xffffffff || result.lastError !== 10050) throw Error('offline_self_test_failed');
    return snapshot();
  }
};
