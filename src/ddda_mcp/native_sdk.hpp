// Dragons Dogma Dark MCP native SDK v1. Copyright (c) 2026 Thingolus. MIT.
#pragma once
#include <cstdint>
#if defined(_WIN32)
#if defined(DDDA_SDK_BUILD)
#define DDDA_EXPORT extern "C" __declspec(dllexport)
#else
#define DDDA_EXPORT extern "C" __declspec(dllimport)
#endif
#define DDDA_CALL __cdecl
#else
#define DDDA_EXPORT extern "C"
#define DDDA_CALL
#endif
namespace ddda {
enum class EventKind : std::uint32_t { sample=1, stamina_request=2, hp_changed=3, inventory_delta=4, actor_replaced=5 };
// No pointers, strings, raw addresses, STL objects or caller-owned lifetimes.
// HP and inventory changes are sampled deltas, not causal engine events.
struct NativeEvent {
    std::uint32_t size=sizeof(NativeEvent), version=1, sequence=0, kind=0;
    std::uint32_t role=0, stage=0, incarnation=0, available=0;
    float position[3]{}, hp=0, hp_max=0, stamina=0, requested_delta=0, before=0, after=0;
    std::uint32_t action=0, vocation=0;
    std::int32_t item_id=-1;
    std::uint32_t quantity=0;
};
static_assert(sizeof(NativeEvent)==84);
struct NativeStatus {
    std::uint32_t size=sizeof(NativeStatus), version=1, running=0, queued=0;
    std::uint32_t dropped=0, errors=0, sampled_callbacks=0, active_callbacks=0;
    // Rejected try-lock attempts include callbacks outside the sampled party.
    // This is sampling contention, not a count of queued events lost.
    std::uint32_t contended_callbacks=0;
};
static_assert(sizeof(NativeStatus)==36);
}
// Start verifies the executable hash, offline bridge and exact hook signature.
// Read drains up to 512 events. Call from a worker, never a game callback.
// Stop returns 1 only after the original bytes and callback quiescence verify.
// Keep the module loaded until the process exits even after Stop.
// Stop disables the hook but retains its trampoline for in-flight return paths.
DDDA_EXPORT int DDDA_CALL ResearchInitialize();
DDDA_EXPORT int DDDA_CALL ResearchHealthy();
DDDA_EXPORT unsigned DDDA_CALL ResearchErrors();
DDDA_EXPORT int DDDA_CALL DdSdkStart();
DDDA_EXPORT int DDDA_CALL DdSdkStop();
DDDA_EXPORT unsigned DDDA_CALL DdSdkReadEvents(ddda::NativeEvent*, unsigned capacity);
DDDA_EXPORT int DDDA_CALL DdSdkStatus(ddda::NativeStatus*);
