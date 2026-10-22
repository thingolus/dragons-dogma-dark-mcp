"""Reviewed fixed recipes; no caller-supplied buttons, axes, pointers or scripts."""

MOVEMENT = {
    "p1_step_forward": {"actor": 0, "axis": "left_y", "value": 16000},
    "p1_step_right": {"actor": 0, "axis": "left_x", "value": 16000},
    "p2_step_forward": {"actor": 1, "axis": "left_y", "value": 16000},
}


def catalog():
    return {
        "recipes": [
            {
                "name": "observe_idle",
                "input": False,
                "duration": "0.1–120 seconds",
                "native_acceptance": "title observation verified",
            },
            {
                "name": "neutral_input",
                "input": True,
                "duration": "0.1–120 seconds",
                "native_acceptance": "loaded-world acceptance pending",
            },
            {
                "name": "dismiss_title",
                "input": True,
                "duration": "250 ms, once per session",
                "native_acceptance": "submission/release verified; UI progression unverified",
            },
            *[
                {
                    "name": name,
                    "input": True,
                    "duration": "300 ms scheduled input plus 200 ms observation and RPC latency, once per session; native provider expires 2 s after last refresh",
                    "parameters": spec,
                    "native_acceptance": "synthetic contracts only; real gameplay unverified",
                    "requires": "assigned controller, observed actor, loaded world, no menu, no physical pads, offline/developer guards",
                }
                for name, spec in MOVEMENT.items()
            ],
        ],
        "warning": "Movement can affect gameplay. Back up saves before a ready-game test. No combat or physical-controller acceptance.",
    }
