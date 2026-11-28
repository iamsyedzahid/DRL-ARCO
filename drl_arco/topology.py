"""Network graph, directed-link indexing and Dijkstra next-hop computation."""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class Link:
    u: int
    v: int
    mbps: float
    delay_ms: float


class Topology:
    """Undirected link ``i`` maps to directed links ``2i`` (u->v) and ``2i+1`` (v->u)."""

    def __init__(self, cfg: dict[str, Any]):
        self.nodes = cfg["nodes"]
        self.n_nodes = len(self.nodes)
        self.links = [Link(*row) for row in cfg["links"]]
        self.n_links = len(self.links)
        self.n_dir = 2 * self.n_links
        self.reference_mbps = cfg["ospf_reference_mbps"]

        self.dir_index: dict[tuple[int, int], int] = {}
        for i, link in enumerate(self.links):
            self.dir_index[(link.u, link.v)] = 2 * i
            self.dir_index[(link.v, link.u)] = 2 * i + 1

        self.neighbors: list[list[int]] = [[] for _ in range(self.n_nodes)]
        for link in self.links:
            self.neighbors[link.u].append(link.v)
            self.neighbors[link.v].append(link.u)
        for hops in self.neighbors:
            hops.sort()
        self.max_degree = max(len(hops) for hops in self.neighbors)

        self.dir_mbps = np.repeat([link.mbps for link in self.links], 2).astype(float)
        self.dir_delay_ms = np.repeat([link.delay_ms for link in self.links], 2).astype(float)

        # port_table[n, p] = neighbor reached through port p of node n, or -1.
        self.port_table = np.full((self.n_nodes, self.max_degree), -1, dtype=np.int64)
        # port_link[n, p] = undirected link used by that port, or -1.
        self.port_link = np.full((self.n_nodes, self.max_degree), -1, dtype=np.int64)
        for n, hops in enumerate(self.neighbors):
            for p, hop in enumerate(hops):
                self.port_table[n, p] = hop
                self.port_link[n, p] = self.dir_index[(n, hop)] // 2

    def cost(self, link: Link) -> int:
        return max(1, round(self.reference_mbps / link.mbps))

    def links_of_node(self, node: int) -> list[int]:
        return [i for i, link in enumerate(self.links) if node in (link.u, link.v)]

    def is_up(self, u: int, v: int, link_up: np.ndarray) -> bool:
        index = self.dir_index.get((u, v))
        return index is not None and bool(link_up[index // 2])

    def spf(self, link_up: np.ndarray | None = None) -> np.ndarray:
        """Return ``fib[n, d]``: Dijkstra next hop from n to d, -1 if none or n == d.

        Ties go to the lowest neighbor id, so results are deterministic.
        """
        if link_up is None:
            link_up = np.ones(self.n_links, dtype=bool)
        adjacency: list[list[tuple[int, int]]] = [[] for _ in range(self.n_nodes)]
        for i, link in enumerate(self.links):
            if link_up[i]:
                cost = self.cost(link)
                adjacency[link.u].append((link.v, cost))
                adjacency[link.v].append((link.u, cost))

        fib = np.full((self.n_nodes, self.n_nodes), -1, dtype=np.int64)
        for dest in range(self.n_nodes):
            dist = [float("inf")] * self.n_nodes
            dist[dest] = 0
            heap = [(0, dest)]
            while heap:
                d, node = heapq.heappop(heap)
                if d > dist[node]:
                    continue
                for hop, cost in adjacency[node]:
                    if d + cost < dist[hop]:
                        dist[hop] = d + cost
                        heapq.heappush(heap, (d + cost, hop))
            for node in range(self.n_nodes):
                if node == dest or dist[node] == float("inf"):
                    continue
                candidates = [h for h, c in adjacency[node] if dist[h] + c == dist[node]]
                fib[node, dest] = min(candidates)
        return fib

    def path(self, fib: np.ndarray, src: int, dst: int) -> list[int]:
        """Follow a FIB from src towards dst; stops early at a dead end or a loop."""
        path = [src]
        seen = {src}
        while path[-1] != dst:
            hop = int(fib[path[-1], dst])
            if hop < 0 or hop in seen:
                break
            path.append(hop)
            seen.add(hop)
        return path

    def ns3_links_arg(self) -> str:
        return ",".join(f"{x.u}-{x.v}:{x.mbps:g}:{x.delay_ms:g}" for x in self.links)
