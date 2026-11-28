"""Feature 3: validate proposed forwarding tables before they reach the network."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from drl_arco.topology import Topology


@dataclass
class GuardReport:
    invalid_hops: int = 0   # next hops that are not a live neighbor
    loops_broken: int = 0   # forwarding cycles detected and removed


def _find_cycle(next_hop: np.ndarray, dest: int) -> list[int] | None:
    """Return one cycle in a destination's next-hop graph, or None if it has none."""
    state = [0] * len(next_hop)  # 0 = unvisited, 1 = on the current walk, 2 = finished
    state[dest] = 2
    for start in range(len(next_hop)):
        walk: list[int] = []
        node = start
        while node >= 0 and state[node] == 0:
            state[node] = 1
            walk.append(node)
            node = int(next_hop[node])
        if node >= 0 and state[node] == 1:
            return walk[walk.index(node):]
        for visited in walk:
            state[visited] = 2
    return None


def validate_fib(
    proposed: np.ndarray, spf: np.ndarray, topology: Topology, link_up: np.ndarray
) -> tuple[np.ndarray, GuardReport]:
    """Return a loop-free FIB that differs from ``proposed`` only where it must.

    Where Dijkstra finds no path, the destination is unreachable, so there is no
    route: forwarding there would only carry doomed packets across links that other
    flows need. Invalid hops revert to Dijkstra, then every node on a cycle reverts
    to Dijkstra and the check repeats. Each pass moves at least one node onto
    Dijkstra, whose own next-hop graph is acyclic, so the repair always terminates
    loop-free.
    """
    fib = proposed.copy()
    report = GuardReport()
    n = topology.n_nodes
    for node in range(n):
        for dest in range(n):
            if node == dest or spf[node, dest] < 0:
                fib[node, dest] = -1
                continue
            hop = int(fib[node, dest])
            if not (0 <= hop < n and topology.is_up(node, hop, link_up)):
                if hop != spf[node, dest]:
                    report.invalid_hops += 1
                fib[node, dest] = spf[node, dest]

    for dest in range(n):
        while True:
            cycle = _find_cycle(fib[:, dest], dest)
            if cycle is None:
                break
            report.loops_broken += 1
            for node in cycle:
                fib[node, dest] = spf[node, dest]
    return fib, report
