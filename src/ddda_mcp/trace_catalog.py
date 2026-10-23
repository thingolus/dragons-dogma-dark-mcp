"""Two reviewed read-only native function observers. MIT, Thingolus."""

from .common import ToolFailure
from .config import GAME_SHA256

TRACES = {
    "native_stamina_apply": {
        "rva": 0x781E30,
        "bytes": "83ec08538a5c241855568bf08baeec3d",
        "source": "research/observe_sprint_stamina.js",
        "kind": "stamina",
        "limitation": "Native stamina application events for validated party actors, not complete player vitals.",
    },
    "goblin_health_subtract": {
        "rva": 0x376F50,
        "bytes": "51578bf8f64730010f85c90000008b87b8010000f680fc0c0000010f85b60000",
        "source": "research/observe_fighter_damage.js",
        "kind": "health",
        "limitation": "Validated goblin/hobgoblin resource subtraction only; source attribution and complete combat coverage are not inferred.",
    },
}


def reviewed(source, name):
    if name not in TRACES:
        raise ToolFailure("trace_not_reviewed", "Choose a named reviewed function trace.")
    source.verify()
    spec = TRACES[name]
    text = source.read(spec["source"])
    if spec["bytes"] not in text.lower():
        raise ToolFailure("source_mismatch", "Reviewed trace signature is absent from pinned research.")
    symbol = next((s for s in source.symbols() if s["name"] == name), None)
    if (
        not symbol
        or symbol["research"].get("build_sha256") != GAME_SHA256
        or int(symbol["research"]["rva"], 16) != spec["rva"]
    ):
        raise ToolFailure("source_mismatch", "Reviewed symbol identity differs.")
    return {
        "symbol": name,
        **spec,
        "source_reference": source.reference(spec["source"]),
        "research": symbol["research"],
    }
