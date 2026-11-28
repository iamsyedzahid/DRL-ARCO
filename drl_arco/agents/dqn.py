"""Feature 2: a shared Double DQN that picks the next hop per (node, destination).

Every router shares one network. Its input is the network state plus one-hot node and
destination; its output is one Q-value per interface. A transition follows the packet:
taking port p at node n for destination d moves to the neighbor y, so

    Q(s, n, d, p) <- r_hop + discount * max_p' Q(s', y, d, p')     (0 future if y == d)

where r_hop applies the proposal's reward formula to the link used. Attributing reward
to the hop taken, as in Q-routing, gives far clearer feedback than one global number
shared by 90 simultaneous decisions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from drl_arco.agents.replay import ReplayBuffer
from drl_arco.topology import Topology


class QNetwork(nn.Module):
    def __init__(self, input_size: int, hidden: list[int], outputs: int):
        super().__init__()
        layers: list[nn.Module] = []
        size = input_size
        for width in hidden:
            layers += [nn.Linear(size, width), nn.ReLU()]
            size = width
        layers.append(nn.Linear(size, outputs))
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class DqnAgent:
    def __init__(self, cfg: dict[str, Any], topology: Topology, state_size: int, seed: int = 0):
        self.cfg = cfg["agent"]
        self.delivery_bonus = cfg["reward"]["delta"]
        self.topology = topology
        self.state_size = state_size
        torch.manual_seed(seed)
        self.rng = np.random.default_rng(seed)

        n = topology.n_nodes
        self.nodes, self.dests = map(
            np.ravel, np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
        )
        keep = self.nodes != self.dests
        self.nodes, self.dests = self.nodes[keep], self.dests[keep]
        self.n_decisions = len(self.nodes)
        self.eye = torch.eye(n)

        input_size = state_size + 2 * n
        hidden = list(self.cfg["hidden"])
        self.q = QNetwork(input_size, hidden, topology.max_degree)
        self.target = QNetwork(input_size, hidden, topology.max_degree)
        self.target.load_state_dict(self.q.state_dict())
        self.optimizer = torch.optim.Adam(self.q.parameters(), lr=self.cfg["lr"])
        self.loss_fn = nn.SmoothL1Loss()
        self.replay = ReplayBuffer(self.cfg["replay_steps"], state_size,
                                   topology.n_links, self.n_decisions)
        self.port_table = torch.as_tensor(topology.port_table)
        self.port_link = torch.as_tensor(topology.port_link)
        self.current_ports: np.ndarray | None = None

    def _inputs(self, states: torch.Tensor, nodes: torch.Tensor,
                dests: torch.Tensor) -> torch.Tensor:
        return torch.cat([states, self.eye[nodes], self.eye[dests]], dim=1)

    def _mask(self, nodes: torch.Tensor, link_up: torch.Tensor) -> torch.Tensor:
        """True for ports that exist and whose link is believed up."""
        links = self.port_link[nodes]
        exists = links >= 0
        if link_up.dim() == 1:
            link_up = link_up.unsqueeze(0).expand(len(nodes), -1)
        up = torch.gather(link_up, 1, links.clamp(min=0))
        return exists & up

    @torch.no_grad()
    def act(self, state: np.ndarray, link_up: np.ndarray, epsilon: float = 0.0) -> np.ndarray:
        """Return a proposed FIB. Dead-end entries are -1 for the guard to repair."""
        nodes = torch.as_tensor(self.nodes)
        dests = torch.as_tensor(self.dests)
        batch = torch.as_tensor(state).unsqueeze(0).expand(self.n_decisions, -1)
        q = self.q(self._inputs(batch, nodes, dests))
        mask = self._mask(nodes, torch.as_tensor(link_up))
        q = q.masked_fill(~mask, -1e9)
        best = q.argmax(dim=1).numpy()
        mask_np = mask.numpy()

        # Hold the current next hop unless a port is clearly better. This damps the
        # oscillation of every router jumping to the same quiet path at once.
        margin = self.cfg["switch_margin"]
        if self.current_ports is not None and margin > 0:
            q_np = q.numpy()
            rows = np.arange(self.n_decisions)
            current = self.current_ports
            valid = (current >= 0) & mask_np[rows, np.clip(current, 0, None)]
            current_q = q_np[rows, np.clip(current, 0, None)]
            hold = valid & (q_np[rows, best] < current_q + margin)
            best = np.where(hold, current, best)

        if epsilon > 0:
            explore = self.rng.random(self.n_decisions) < epsilon
            for i in np.flatnonzero(explore):
                options = np.flatnonzero(mask_np[i])
                if options.size:
                    best[i] = self.rng.choice(options)

        self.current_ports = best.copy()
        fib = np.full((self.topology.n_nodes, self.topology.n_nodes), -1, dtype=np.int64)
        hops = self.topology.port_table[self.nodes, best]
        hops = np.where(mask_np.any(axis=1), hops, -1)
        fib[self.nodes, self.dests] = hops
        return fib

    def reset_episode(self) -> None:
        self.current_ports = None

    def observe(self, state: np.ndarray, fib: np.ndarray, next_state: np.ndarray,
                next_up: np.ndarray, hop_rewards: np.ndarray) -> None:
        """Store the routes actually applied, so guard repairs are learned from too."""
        hops = fib[self.nodes, self.dests]
        ports = np.full(self.n_decisions, -1, dtype=np.int8)
        rewards = np.zeros(self.n_decisions, dtype=np.float32)
        dir_index = self.topology.dir_index
        for i, (node, dest, hop) in enumerate(zip(self.nodes, self.dests, hops)):
            if hop < 0:
                continue
            ports[i] = self.topology.neighbors[node].index(int(hop))
            rewards[i] = hop_rewards[dir_index[(int(node), int(hop))]]
            if hop == dest:
                rewards[i] += self.delivery_bonus
        self.replay.add(state, next_state, next_up, ports, rewards)

    def learn(self) -> float | None:
        if self.replay.size < self.cfg["warmup_steps"]:
            return None
        steps, decisions = self.replay.sample(self.cfg["batch_size"], self.rng)
        if steps.size == 0:
            return None
        r = self.replay
        states = torch.as_tensor(r.states[steps])
        next_states = torch.as_tensor(r.next_states[steps])
        next_up = torch.as_tensor(r.next_up[steps])
        ports = torch.as_tensor(r.ports[steps, decisions]).long()
        rewards = torch.as_tensor(r.rewards[steps, decisions])
        nodes = torch.as_tensor(self.nodes[decisions])
        dests = torch.as_tensor(self.dests[decisions])

        q = self.q(self._inputs(states, nodes, dests)).gather(1, ports.unsqueeze(1)).squeeze(1)
        with torch.no_grad():
            hops = self.port_table[nodes, ports]
            mask = self._mask(hops, next_up)
            inputs = self._inputs(next_states, hops, dests)
            online = self.q(inputs).masked_fill(~mask, -1e9)
            choice = online.argmax(dim=1, keepdim=True)
            future = self.target(inputs).gather(1, choice).squeeze(1)
            terminal = (hops == dests) | ~mask.any(dim=1)
            target = rewards + self.cfg["discount"] * future * (~terminal).float()

        loss = self.loss_fn(q, target)
        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.q.parameters(), 10.0)
        self.optimizer.step()

        tau = self.cfg["target_tau"]
        with torch.no_grad():
            for online_p, target_p in zip(self.q.parameters(), self.target.parameters()):
                target_p.mul_(1 - tau).add_(tau * online_p)
        return loss.item()

    def save(self, path: str | Path, meta: dict[str, Any] | None = None) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        torch.save({"q": self.q.state_dict(), "state_size": self.state_size,
                    "meta": meta or {}}, path)

    def load(self, path: str | Path) -> dict[str, Any]:
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        if checkpoint["state_size"] != self.state_size:
            raise ValueError(f"checkpoint {path} was trained on a different network size")
        self.q.load_state_dict(checkpoint["q"])
        self.target.load_state_dict(checkpoint["q"])
        return checkpoint["meta"]
