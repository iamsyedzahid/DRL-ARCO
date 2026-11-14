"""Build environments and backends by name."""

from __future__ import annotations

from typing import Any

from drl_arco.envs.routing_env import RoutingEnv
from drl_arco.envs.surrogate import SurrogateBackend
from drl_arco.topology import Topology
from drl_arco.traffic import load_flows, load_scenario


def make_env(cfg: dict[str, Any], scenario: str, backend: str = "surrogate") -> RoutingEnv:
    topology = Topology(cfg["topology"])
    flows = load_flows(cfg)
    if backend == "surrogate":
        impl = SurrogateBackend(cfg, topology, flows)
    elif backend == "ns3":
        from drl_arco.envs.ns3_bridge import Ns3Backend

        impl = Ns3Backend(cfg, topology, flows)
    else:
        raise ValueError(f"unknown backend {backend!r}")
    return RoutingEnv(cfg, topology, impl, load_scenario(cfg, scenario))
