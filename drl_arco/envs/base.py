"""The contract shared by the ns-3 backend and the surrogate backend."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass
class Telemetry:
    """One decision interval of measurements. Flow values are per-step deltas."""

    time_s: float
    queue: np.ndarray        # (n_dir) occupancy, 0-1
    util: np.ndarray         # (n_dir) utilization, 0-1
    loss: np.ndarray         # (n_dir) share of packets lost on the link, 0-1
    delay_s: np.ndarray      # (n_dir) propagation plus queueing delay
    flow_tx: np.ndarray      # (n_flows) packets sent
    flow_rx: np.ndarray      # (n_flows) packets received
    flow_rx_bytes: np.ndarray
    flow_delay_s: np.ndarray   # (n_flows) sum of end-to-end delays
    flow_jitter_s: np.ndarray  # (n_flows) sum of delay variation


class Backend(Protocol):
    name: str

    def reset(self, seed: int) -> Telemetry: ...

    def step(self, fib: np.ndarray, link_up: np.ndarray, scale: float) -> Telemetry: ...

    def close(self) -> None: ...
