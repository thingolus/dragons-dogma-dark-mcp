"""Generated host-side SDK extensions; no native memory overlays. MIT, Thingolus."""

from .control import ACTIONS
from .experiments import ExperimentPlan
from .gameplay_data import GameplayRecording, backend_capabilities
from .gameplay_events import EVENT_KINDS


def catalog():
    return {
        "version": 1,
        "namespace": "ddda::observations_v1",
        "identity": "Capture-scoped or session-scoped opaque IDs; session IDs require a lifetime incarnation.",
        "events": list(EVENT_KINDS),
        "frames": "Bounded copied actors, resources, inventory, menu availability and sequence/time domains.",
        "commands": "Allowlisted fixed inputs and typed future item/target operations; no dispatch implementation here.",
        "backends": {b: backend_capabilities(b) for b in ("coop", "standalone")},
        "native_acceptance": "unverified",
        "native_stream_available": False,
        "legacy_sdk": "ddda_sdk.hpp and PartySample v1 remain unchanged.",
    }


def schemas():
    return {
        "recording": GameplayRecording.model_json_schema(),
        "experiment": ExperimentPlan.model_json_schema(),
    }


def header():
    # Generated from the existing allowlist so additions cannot silently diverge.
    actions = ", ".join(sorted(ACTIONS))
    return HEADER.replace("@FIXED_ACTIONS@", actions)


HEADER = r"""// Copyright (c) 2026 Thingolus. MIT. Host-side types, not a native game ABI.
#pragma once
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <type_traits>

namespace ddda::observations_v1 {
inline constexpr std::uint32_t schema_version = 1;
enum class Scope : std::uint32_t { capture, session };
struct EntityRef {
    std::array<char, 65> key{}, epoch{};
    Scope scope = Scope::capture;
    std::uint32_t incarnation = 0;
    bool has_incarnation = false;
};
inline bool token(const std::array<char, 65>& s) {
    auto alpha = [](char c) { return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z'); };
    if (!alpha(s[0])) return false;
    for (unsigned i = 1; i <= 64; ++i) {
        if (!s[i]) return true;
        if (i == 64 || !(alpha(s[i]) || (s[i] >= '0' && s[i] <= '9') ||
                        s[i] == '_' || s[i] == '.' || s[i] == ':' || s[i] == '-')) return false;
    }
    return false;
}
inline bool valid(const EntityRef& e) {
    return token(e.key) && token(e.epoch) && (e.scope == Scope::capture || e.scope == Scope::session) &&
           (e.scope != Scope::session || e.has_incarnation);
}
inline bool same_entity(const EntityRef& a, const EntityRef& b) {
    return valid(a) && valid(b) && a.scope == b.scope && a.has_incarnation == b.has_incarnation &&
           (!a.has_incarnation || a.incarnation == b.incarnation) &&
           std::strcmp(a.key.data(), b.key.data()) == 0 && std::strcmp(a.epoch.data(), b.epoch.data()) == 0;
}
enum Availability : std::uint32_t { position = 1, hp = 2, hp_max = 4, stamina = 8, action = 16, vocation = 32 };
struct ActorSample {
    EntityRef entity{};
    std::uint32_t available = 0, role = std::numeric_limits<std::uint32_t>::max();
    float xyz[3]{}, health = 0, maximum_health = 0, endurance = 0;
    std::uint32_t action_id = 0, vocation_id = 0;
};
inline bool valid(const ActorSample& s) {
    if (!valid(s.entity) || (s.available & ~63u) || (s.role > 1 && s.role != UINT32_MAX)) return false;
    if (s.available & position) for (float v : s.xyz) if (!std::isfinite(v)) return false;
    if ((s.available & hp) && (!std::isfinite(s.health) || s.health < 0)) return false;
    if ((s.available & hp_max) && (!std::isfinite(s.maximum_health) || s.maximum_health < 0)) return false;
    if ((s.available & stamina) && (!std::isfinite(s.endurance) || s.endurance < 0)) return false;
    return true;
}
struct Item { std::int32_t id = 0; std::uint32_t quantity = 0; };
struct Inventory {
    std::array<Item, 256> items{};
    std::uint32_t count = 0;
    bool complete = false;
};
inline bool valid(const Inventory& s) {
    if (s.count > s.items.size()) return false;
    for (unsigned i = 0; i < s.count; ++i) if (s.items[i].id < -32768 || s.items[i].id > 32767) return false;
    return true;
}
enum class EventKind : std::uint32_t { hp_decreased, hp_increased, zero_hp_to_positive, inventory_delta, action_changed };
struct Event {
    EntityRef entity{};
    EventKind kind = EventKind::hp_decreased;
    std::uint32_t from_sequence = 0, to_sequence = 0;
    double before = 0, after = 0;
    std::int32_t item_id = 0;
    // No attacker/source field: these are sample differences, not attributed native events.
};
inline bool valid(const Event& e) {
    if (!valid(e.entity) || e.to_sequence <= e.from_sequence || !std::isfinite(e.before) ||
        !std::isfinite(e.after) || e.before < 0 || e.after < 0 || e.before == e.after) return false;
    switch(e.kind) {
        case EventKind::hp_decreased: return e.after < e.before;
        case EventKind::hp_increased: return e.after > e.before;
        case EventKind::zero_hp_to_positive: return e.before == 0 && e.after > 0;
        case EventKind::inventory_delta:
            return e.item_id >= -32768 && e.item_id <= 32767 && std::floor(e.before) == e.before &&
                   std::floor(e.after) == e.after && e.before <= 256.0 * UINT32_MAX && e.after <= 256.0 * UINT32_MAX;
        case EventKind::action_changed:
            return std::floor(e.before) == e.before && std::floor(e.after) == e.after &&
                   e.before <= UINT32_MAX && e.after <= UINT32_MAX;
    }
    return false;
}
enum class Action : std::uint32_t { @FIXED_ACTIONS@, use_item, interact_target, approach_target };
enum class Backend : std::uint32_t { coop, standalone, offline_replay };
struct Command {
    Action action = Action::neutral;
    std::uint32_t role = 0, duration_ms = 350;
    std::int32_t item_id = 0;
    bool has_item = false, has_target = false;
    EntityRef target{};
};
inline bool valid(const Command& c) {
    if (c.role > 1 || c.duration_ms < 50 || c.duration_ms > 1000 ||
        static_cast<unsigned>(c.action) > static_cast<unsigned>(Action::approach_target)) return false;
    if ((c.action == Action::use_item) != c.has_item) return false;
    if (c.has_item && (c.item_id < -32768 || c.item_id > 32767)) return false;
    const bool targeted = c.action == Action::interact_target || c.action == Action::approach_target;
    return c.has_target == targeted && (!targeted || valid(c.target));
}
inline bool supported(Backend b, const Command& c) {
    if (!valid(c)) return false;
    if (b == Backend::offline_replay) return true; // Simulation only, never native acceptance.
    return b == Backend::coop && static_cast<unsigned>(c.action) < static_cast<unsigned>(Action::use_item);
}
static_assert(std::is_standard_layout_v<ActorSample> && std::is_standard_layout_v<Event>);
// There is intentionally no game pointer, raw write, callback hook or dispatch function in this header.
}
"""

CONTRACT_TEST = r"""#include "ddda_observations.hpp"
#include <limits>
using namespace ddda::observations_v1;
int main() {
    EntityRef e;
    if (valid(e)) return 1;
    std::strcpy(e.key.data(), "pawn"); std::strcpy(e.epoch.data(), "session-one");
    e.scope = Scope::session;
    if (valid(e)) return 2;
    e.has_incarnation = true; e.incarnation = 1;
    if (!valid(e)) return 3;
    auto next = e; next.incarnation = 2;
    if (same_entity(e, next)) return 4;
    next = e; std::strcpy(next.epoch.data(), "other-session");
    if (same_entity(e, next)) return 5;
    ActorSample sample; sample.entity = e; sample.available = hp;
    sample.health = std::numeric_limits<float>::quiet_NaN();
    if (valid(sample)) return 6;
    sample.available = 0; // Unknown data is not a zero-health observation.
    if (!valid(sample)) return 7;
    Inventory inventory; inventory.count = 257;
    if (valid(inventory)) return 8;
    Event event; event.entity = e; event.to_sequence = 1; event.before = 10; event.after = 8;
    if (!valid(event)) return 9;
    event.kind = EventKind::zero_hp_to_positive;
    if (valid(event)) return 10;
    event.before = 0; event.after = 1;
    if (!valid(event)) return 11;
    Command command;
    if (!supported(Backend::coop, command) || supported(Backend::standalone, command)) return 12;
    command.action = Action::use_item;
    if (valid(command)) return 13;
    command.has_item = true; command.item_id = 43;
    if (!valid(command) || supported(Backend::coop, command) ||
        !supported(Backend::offline_replay, command)) return 14;
    command.action = Action::interact_target; command.has_item = false; command.has_target = true; command.target = e;
    if (!valid(command)) return 15;
    command.duration_ms = 1001;
    if (valid(command)) return 16;
    return 0;
}
"""
