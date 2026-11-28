"""Experience replay. Each stored step holds one transition per (node, dest) decision."""

from __future__ import annotations

import numpy as np


class ReplayBuffer:
    def __init__(self, capacity: int, state_size: int, n_links: int, n_decisions: int):
        self.capacity = capacity
        self.n_decisions = n_decisions
        self.states = np.zeros((capacity, state_size), dtype=np.float32)
        self.next_states = np.zeros((capacity, state_size), dtype=np.float32)
        self.next_up = np.zeros((capacity, n_links), dtype=bool)
        self.ports = np.zeros((capacity, n_decisions), dtype=np.int8)     # -1 = no action
        self.rewards = np.zeros((capacity, n_decisions), dtype=np.float32)
        self.cursor = 0
        self.size = 0

    def add(self, state: np.ndarray, next_state: np.ndarray, next_up: np.ndarray,
            ports: np.ndarray, rewards: np.ndarray) -> None:
        i = self.cursor
        self.states[i] = state
        self.next_states[i] = next_state
        self.next_up[i] = next_up
        self.ports[i] = ports
        self.rewards[i] = rewards
        self.cursor = (i + 1) % self.capacity
        self.size = min(self.size + 1, self.capacity)

    def sample(self, batch: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
        """Pick random (step, decision) pairs that actually took an action."""
        steps = rng.integers(0, self.size, batch)
        decisions = rng.integers(0, self.n_decisions, batch)
        keep = self.ports[steps, decisions] >= 0
        return steps[keep], decisions[keep]
