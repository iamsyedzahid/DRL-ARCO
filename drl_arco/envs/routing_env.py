"""Feature 1 (Python half): the MDP around a backend.

Handles scenario events, delayed link-state knowledge, FIB validation, state
extraction, reward and the benchmark counters.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from drl_arco.envs.base import Backend, Telemetry
from drl_arco.safety.loop_guard import GuardReport, validate_fib
from drl_arco.topology import Topology
from drl_arco.traffic import Scenario

LINK_FEATURES = 5


@dataclass
class Metrics:
    """Cumulative packet counters that produce the four benchmark metrics."""

    tx: float = 0.0
    rx: float = 0.0
    rx_bytes: float = 0.0
    delay_s: float = 0.0
    jitter_s: float = 0.0
    elapsed_s: float = 0.0

    def add(self, t: Telemetry, dt: float) -> None:
        self.tx += float(t.flow_tx.sum())
        self.rx += float(t.flow_rx.sum())
        self.rx_bytes += float(t.flow_rx_bytes.sum())
        self.delay_s += float(t.flow_delay_s.sum())
        self.jitter_s += float(t.flow_jitter_s.sum())
        self.elapsed_s += dt

    def summary(self) -> dict[str, float]:
        return {
            "pdr": min(self.rx / self.tx, 1.0) if self.tx else 0.0,
            "latency_ms": 1000 * self.delay_s / self.rx if self.rx else 0.0,
            "throughput_mbps": self.rx_bytes * 8 / 1e6 / self.elapsed_s if self.elapsed_s else 0.0,
            "jitter_ms": 1000 * self.jitter_s / self.rx if self.rx else 0.0,
        }


@dataclass
class StepResult:
    state: np.ndarray
    reward: float
    done: bool
    fib: np.ndarray
    telemetry: Telemetry
    guard: GuardReport
    cold_start: bool
    fired: list[str] = field(default_factory=list)


class RoutingEnv:
    def __init__(self, cfg: dict[str, Any], topology: Topology, backend: Backend,
                 scenario: Scenario):
        self.cfg = cfg
        self.topology = topology
        self.backend = backend
        self.scenario = scenario
        self.dt = cfg["sim"]["step_s"]
        self.episode_steps = cfg["sim"]["episode_steps"]
        self.delay_steps = cfg["sim"]["link_state_delay_steps"]
        self.cold_start_steps = cfg["guard"]["cold_start_steps"]
        self.reward_cfg = cfg["reward"]
        self.state_size = topology.n_dir * LINK_FEATURES
        self._reset_counters()

    def _reset_counters(self) -> None:
        self.step_count = 0
        self.metrics = Metrics()
        self.scale = self.scenario.scale
        self.link_failed = np.zeros(self.topology.n_links, dtype=bool)
        self.node_failed = np.zeros(self.topology.n_nodes, dtype=bool)
        self.pending = deque(self.scenario.events)
        all_up = np.ones(self.topology.n_links, dtype=bool)
        self.history = deque([all_up.copy() for _ in range(self.delay_steps + 1)],
                             maxlen=self.delay_steps + 1)
        self.known_up = all_up.copy()
        self.spf = self.topology.spf(self.known_up)
        self.fib = self.spf.copy()
        self.guard_totals = GuardReport()

    @property
    def link_up(self) -> np.ndarray:
        """Ground truth: a link is up unless it or either endpoint has failed."""
        up = ~self.link_failed
        for i, link in enumerate(self.topology.links):
            if self.node_failed[link.u] or self.node_failed[link.v]:
                up[i] = False
        return up

    def reset(self, seed: int) -> np.ndarray:
        self._reset_counters()
        self.telemetry = self.backend.reset(seed)
        return self.extract_state(self.telemetry)

    def extract_state(self, t: Telemetry) -> np.ndarray:
        """Normalize per-interface measurements into the policy's input vector."""
        delay = np.clip(t.delay_s * 1000 / self.reward_cfg["delay_scale_ms"], 0, 2)
        known = np.repeat(self.known_up, 2).astype(float)
        return np.stack([t.queue, t.util, t.loss, delay, known], axis=1).ravel().astype(np.float32)

    def reward(self, t: Telemetry) -> float:
        """The proposal's reward, from network-wide values for this interval."""
        r = self.reward_cfg
        tx, rx = float(t.flow_tx.sum()), float(t.flow_rx.sum())
        delivered = min(rx / tx, 1.0) if tx > 0 else 1.0
        delay_ms = 1000 * float(t.flow_delay_s.sum()) / rx if rx > 0 else 0.0
        return (
            -(r["alpha"] * delay_ms / r["delay_scale_ms"]
              + r["beta"] * (1 - delivered)
              + r["gamma"] * float(t.queue.mean()))
            + r["delta"] * delivered
        )

    def hop_rewards(self, t: Telemetry) -> np.ndarray:
        """The same formula per directed link, used for hop-by-hop Q-learning."""
        r = self.reward_cfg
        delay = t.delay_s * 1000 / r["delay_scale_ms"]
        return -(r["alpha"] * delay + r["beta"] * t.loss + r["gamma"] * t.queue)

    # Manual controls, used by the GUI and by scenario events.
    def set_link(self, link: int, up: bool) -> None:
        self.link_failed[link] = not up

    def set_node(self, node: int, up: bool) -> None:
        self.node_failed[node] = not up

    def set_scale(self, scale: float) -> None:
        self.scale = scale

    def _fire_events(self) -> list[str]:
        fired = []
        now = self.step_count * self.dt
        while self.pending and self.pending[0].time_s <= now + 1e-9:
            event = self.pending.popleft()
            if event.action == "scale":
                self.set_scale(float(event.target))
            elif event.action.startswith("link"):
                self.set_link(int(event.target), event.action == "link_up")
            else:
                self.set_node(int(event.target), event.action == "node_up")
            fired.append(f"{event.action} {event.target:g}")
        return fired

    def step(self, proposed: np.ndarray | None) -> StepResult:
        """Advance one interval. ``proposed`` of None means plain Dijkstra."""
        fired = self._fire_events()
        self.history.append(self.link_up.copy())
        self.known_up = self.history[0]
        self.spf = self.topology.spf(self.known_up)

        cold_start = self.step_count < self.cold_start_steps
        report = GuardReport()
        if proposed is None or cold_start:
            self.fib = self.spf.copy()
        else:
            self.fib, report = validate_fib(proposed, self.spf, self.topology, self.known_up)
        self.guard_totals.invalid_hops += report.invalid_hops
        self.guard_totals.loops_broken += report.loops_broken

        self.telemetry = self.backend.step(self.fib, self.link_up, self.scale)
        self.metrics.add(self.telemetry, self.dt)
        self.step_count += 1
        return StepResult(
            state=self.extract_state(self.telemetry),
            reward=self.reward(self.telemetry),
            done=self.step_count >= self.episode_steps,
            fib=self.fib,
            telemetry=self.telemetry,
            guard=report,
            cold_start=cold_start,
            fired=fired,
        )

    def close(self) -> None:
        self.backend.close()
