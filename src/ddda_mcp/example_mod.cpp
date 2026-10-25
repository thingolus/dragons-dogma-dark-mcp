// Minimal native mod: consume copied events without reading game memory.
// Copyright (c) 2026 Thingolus. MIT.
#include "native_sdk.hpp"
#include <windows.h>
#include <cstdio>
// Invoke from your mod's worker. There is one queue consumer per process.
// Do not call initialization/teardown from DllMain or a native game callback.
extern "C" __declspec(dllexport) int __cdecl SampleStart() {
    return (ResearchHealthy()==1 || ResearchInitialize()==1) && DdSdkStart()==1;
}
extern "C" __declspec(dllexport) int __cdecl SampleStop() {
    return DdSdkStop();
}
extern "C" __declspec(dllexport) unsigned __cdecl SamplePoll() {
    ddda::NativeEvent events[64];unsigned n=DdSdkReadEvents(events,64);
    for(unsigned i=0;i<n;i++){
        const auto& e=events[i];if(e.size!=sizeof(e)||e.version!=1)continue;
        if(e.kind==static_cast<unsigned>(ddda::EventKind::hp_changed)){
            char text[128];std::snprintf(text,sizeof(text),"DDDA SDK: role %u HP %.2f -> %.2f\n",e.role,e.before,e.after);OutputDebugStringA(text);
        }
    }
    return n;
}
