"""Routing policies compared by the benchmark and the GUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import numpy as np

from drl_arco.config import REPO_ROOT
from drl_arco.envs.routing_env import RoutingEnv

DEFAULT_CHECKPOINT = REPO_ROOT / "checkpoints" / "dqn.pt"


class Policy(Protocol):
    name: str

    def begin_episode(self) -> None: ...

    def propose(self, env: RoutingEnv, state: np.ndarray) -> np.ndarray | None: ...


class DijkstraPolicy:
    """The baseline: OSPF-style link costs with delayed link-state knowledge.

    ns-3 ships no OSPF module, so this computes the routes OSPF would converge to.
    """

    name = "dijkstra"

    def begin_episode(self) -> None:
        pass

    def propose(self, env: RoutingEnv, state: np.ndarray) -> None:
        return None


class DqnPolicy:
    name = "dqn"

    def __init__(self, cfg: dict[str, Any], env: RoutingEnv,
                 checkpoint: str | Path = DEFAULT_CHECKPOINT):
        from drl_arco.agents.dqn import DqnAgent

        self.agent = DqnAgent(cfg, env.topology, env.state_size)
        self.meta = self.agent.load(checkpoint)
        self.agent.q.eval()

    def begin_episode(self) -> None:
        self.agent.reset_episode()

    def propose(self, env: RoutingEnv, state: np.ndarray) -> np.ndarray:
        return self.agent.act(state, env.known_up)


def make_policy(name: str, cfg: dict[str, Any], env: RoutingEnv,
                checkpoint: str | Path | None = None) -> Policy:
    if name == "dijkstra":
        return DijkstraPolicy()
    if name == "dqn":
        return DqnPolicy(cfg, env, checkpoint or DEFAULT_CHECKPOINT)
    raise ValueError(f"unknown policy {name!r}")
