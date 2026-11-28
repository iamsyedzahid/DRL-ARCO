"""Feature 4: traffic matrix and scheduled congestion and failure scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Flow:
    src: int
    dst: int
    peak_mbps: float
    on_s: float
    off_s: float


@dataclass(frozen=True)
class Event:
    time_s: float
    action: str
    target: float


@dataclass(frozen=True)
class Scenario:
    name: str
    scale: float
    events: tuple[Event, ...]


VALID_ACTIONS = {"link_down", "link_up", "node_down", "node_up", "scale"}


def load_flows(cfg: dict[str, Any]) -> list[Flow]:
    return [Flow(*row) for row in cfg["traffic"]["flows"]]


def load_scenario(cfg: dict[str, Any], name: str) -> Scenario:
    raw = cfg["scenarios"][name]
    events = tuple(sorted((Event(*e) for e in raw["events"]), key=lambda e: e.time_s))
    for event in events:
        if event.action not in VALID_ACTIONS:
            raise ValueError(f"scenario {name}: unknown action {event.action!r}")
    return Scenario(name=name, scale=raw["scale"], events=events)


def ns3_flows_arg(flows: list[Flow]) -> str:
    return ",".join(f"{f.src}-{f.dst}:{f.peak_mbps:g}:{f.on_s:g}:{f.off_s:g}" for f in flows)
