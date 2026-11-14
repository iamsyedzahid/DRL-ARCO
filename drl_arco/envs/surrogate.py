"""A fast fluid-model network for development and tests when ns-3 is unavailable.

This is an approximation, not ns-3. It models On-Off sources and finite FIFO queues
per interval rather than individual packets. Use it to develop and smoke-test; report
results from the ns-3 backend.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from drl_arco.envs.base import Telemetry
from drl_arco.topology import Topology
from drl_arco.traffic import Flow

_FIXED_POINT_PASSES = 3


class SurrogateBackend:
    name = "surrogate"

    def __init__(self, cfg: dict[str, Any], topology: Topology, flows: list[Flow]):
        self.topology = topology
        self.flows = flows
        self.dt = cfg["sim"]["step_s"]
        self.packet_bits = cfg["sim"]["packet_bytes"] * 8
        self.queue_bits = cfg["sim"]["queue_packets"] * self.packet_bits
        self.capacity_bps = topology.dir_mbps * 1e6
        self.prop_s = topology.dir_delay_ms / 1000
        self.rng = np.random.default_rng(0)
        self.backlog = np.zeros(topology.n_dir)
        self.on = np.zeros(len(flows), dtype=bool)
        self.last_delay = np.zeros(len(flows))
        self.time_s = 0.0

    def reset(self, seed: int) -> Telemetry:
        self.rng = np.random.default_rng(seed)
        self.backlog = np.zeros(self.topology.n_dir)
        self.on = self.rng.random(len(self.flows)) < 0.5
        self.last_delay = np.full(len(self.flows), np.nan)
        self.time_s = 0.0
        return self._empty()

    def _empty(self) -> Telemetry:
        zeros_dir = np.zeros(self.topology.n_dir)
        zeros_flow = np.zeros(len(self.flows))
        return Telemetry(
            self.time_s, zeros_dir.copy(), zeros_dir.copy(), zeros_dir.copy(), self.prop_s.copy(),
            zeros_flow.copy(), zeros_flow.copy(), zeros_flow.copy(), zeros_flow.copy(),
            zeros_flow.copy(),
        )

    def _advance_sources(self) -> None:
        for i, flow in enumerate(self.flows):
            mean = flow.on_s if self.on[i] else flow.off_s
            if self.rng.random() < 1 - np.exp(-self.dt / mean):
                self.on[i] = not self.on[i]

    def _route(self, fib: np.ndarray, flow: Flow) -> tuple[list[int], bool]:
        """Return a flow's directed links and whether the walk reaches its destination."""
        hops: list[int] = []
        node, seen = flow.src, {flow.src}
        while node != flow.dst:
            hop = int(fib[node, flow.dst])
            if hop < 0 or hop in seen:
                return hops, False
            hops.append(self.topology.dir_index[(node, hop)])
            seen.add(hop)
            node = hop
        return hops, True

    def step(self, fib: np.ndarray, link_up: np.ndarray, scale: float) -> Telemetry:
        self._advance_sources()
        self.time_s += self.dt

        routes = [self._route(fib, flow) for flow in self.flows]
        rates = np.array(
            [f.peak_mbps * 1e6 * scale * on for f, on in zip(self.flows, self.on)]
        )
        dir_up = np.repeat(link_up, 2)
        capacity_bits = self.capacity_bps * self.dt

        # Upstream losses reduce downstream load, so iterate to a fixed point.
        loss = np.where(dir_up, 0.0, 1.0)
        offered = np.zeros(self.topology.n_dir)
        for _ in range(_FIXED_POINT_PASSES):
            offered = np.zeros(self.topology.n_dir)
            for (hops, _), rate in zip(routes, rates):
                surviving = rate * self.dt
                for d in hops:
                    offered[d] += surviving
                    surviving *= 1 - loss[d]
            excess = self.backlog + offered - capacity_bits - self.queue_bits
            with np.errstate(divide="ignore", invalid="ignore"):
                loss = np.where(offered > 0, np.clip(excess, 0, None) / offered, 0.0)
            loss = np.where(dir_up, np.clip(loss, 0, 1), 1.0)

        accepted = offered * (1 - loss)
        carried = np.minimum(self.backlog + accepted, capacity_bits)
        self.backlog = np.clip(self.backlog + accepted - carried, 0, self.queue_bits)
        self.backlog[~dir_up] = 0.0

        link_delay = self.prop_s + (self.backlog + self.packet_bits) / self.capacity_bps

        n_flows = len(self.flows)
        tx, rx, rx_bytes = np.zeros(n_flows), np.zeros(n_flows), np.zeros(n_flows)
        delay_sum, jitter_sum = np.zeros(n_flows), np.zeros(n_flows)
        for i, ((hops, reached), rate) in enumerate(zip(routes, rates)):
            tx[i] = rate * self.dt / self.packet_bits
            if not reached or tx[i] == 0:
                continue
            survival = float(np.prod(1 - loss[hops])) if hops else 1.0
            rx[i] = tx[i] * survival
            rx_bytes[i] = rx[i] * self.packet_bits / 8
            if rx[i] <= 0:
                continue
            delay = float(link_delay[hops].sum())
            delay_sum[i] = delay * rx[i]
            if not np.isnan(self.last_delay[i]):
                jitter_sum[i] = abs(delay - self.last_delay[i]) * rx[i]
            self.last_delay[i] = delay

        return Telemetry(
            self.time_s,
            self.backlog / self.queue_bits,
            np.minimum(carried / capacity_bits, 1.0) * dir_up,
            loss,
            link_delay,
            tx, rx, rx_bytes, delay_sum, jitter_sum,
        )

    def close(self) -> None:
        pass
