# Architecture

## Languages

| Language | Used for | Where |
|---|---|---|
| C++ | The ns-3 simulation, metric collection and applying routes | `ns3/scratch/drl-arco/` |
| Python | RL agent (PyTorch), MDP, loop guard, benchmark, GUI server | `drl_arco/` |
| HTML, CSS, JavaScript | The dashboard in the browser | `drl_arco/gui/static/` |
| YAML, Bash | Configuration and setup scripts | `configs/`, `scripts/` |

C++ and Python run as two separate programs, connected by ns3-gym's ZeroMQ and protobuf messages.

## How one decision step works

```
        ns-3 (C++)                                   Python
 ┌───────────────────────┐   queues, loss, delay ┌───────────────────────────┐
 │ 10 routers, 16 links  │ ────────────────────► │ RoutingEnv: state, reward │
 │ On-Off traffic        │   per-flow counters   │            │              │
 │ FlowMonitor           │                       │            ▼              │
 │ RoutingGymEnv         │                       │ Policy: DQN or Dijkstra   │
 │                       │   next hop per node   │            │              │
 │ static routes updated │ ◄──────────────────── │            ▼              │
 │                       │   and destination     │ Loop guard validates FIB  │
 └───────────────────────┘                       └─────────────┬─────────────┘
                                                               ▼
                                                     Dashboard, benchmark files
```

This repeats every 0.1 simulated seconds by default.

## The MDP

**State.** Five values for each of the 32 directed links: queue occupancy, utilization, loss rate, delay, and whether the link is believed up. The agent also gets the node and destination as one-hot vectors.

**Action.** A next hop for each (router, destination) pair, 90 decisions per step. One network, shared by all routers, scores each interface.

The proposal also mentions next-hop *probabilities*. The action here is one interface per destination, because ns-3's static routing table holds one next hop per host route. Traffic balances across destinations, not across packets of one flow.

**Reward.** The proposal's formula:

```
Reward = -(alpha * Delay + beta * PacketLoss + gamma * QueueOccupancy) + delta * Delivered
```

It is used in two ways:

- **Network-wide:** reported per step and used to choose the best checkpoint.
- **Per hop:** used for learning, with the same terms measured on the link a decision used, and the `delta` bonus when that hop reaches the destination. All 90 decisions sharing one global number gives very weak feedback about which decision helped.

The update follows the packet to the next router, as in Q-routing:

```
Q(s, n, d, port) <- r_hop + discount * max Q(s', next_router, d, port')
```

## Loop prevention

`drl_arco/safety/loop_guard.py` runs before any table reaches the network:

1. A next hop that is not a live neighbor is replaced by the Dijkstra next hop.
2. For each destination, it searches the next-hop graph for cycles. Every router on a cycle reverts to Dijkstra, and the search repeats.

Each repeat moves at least one router onto Dijkstra, and Dijkstra's graph has no cycles, so this always ends with a loop-free table. `tests/test_core.py` checks this on 300 random tables. During the first `cold_start_steps` steps the whole table is Dijkstra.

## Baseline: Dijkstra, not OSPF

ns-3 has no OSPF module. The baseline computes the routes OSPF would converge to, using OSPF's cost formula (`reference bandwidth / link bandwidth`). State this in your report.

Both policies learn about a failure after the same delay (`link_state_delay_steps`), so neither has an unfair advantage in reaction time.

## Two simulation backends

| | ns-3 | Surrogate |
|---|---|---|
| Model | Real packets, queues and protocol stack | Fluid approximation in Python |
| Runs on | Ubuntu or WSL2 | Anywhere |
| Use for | **Results in the report** | Developing the agent, GUI and tests |

Both implement `Backend` in `drl_arco/envs/base.py`, so the environment, agent, benchmark and GUI work the same with either. A model trained on the surrogate has not seen real ns-3 behavior, so retrain on ns-3 before reporting results.

Known differences:

- Surrogate jitter is the change in path delay between steps. ns-3's is per packet, so **compare jitter only within one backend**.
- The surrogate has no packet-level burstiness within a 0.1 s step.

## Modeling link failures in ns-3

A failed link keeps its interfaces up and drops every packet at the receiver with an error model. Taking the interface down instead would remove routes, so senders would fail before FlowMonitor counted the packets, overstating delivery.

For the same reason, a router with no route to a destination keeps its previous route. Packets are then lost where they can be counted.

## Why not the ns3gym Python package

ns3-gym's `Ns3Env` uses `np.float` and `np.int`, which NumPy removed in version 1.24, and depends on the retired `gym` package. `drl_arco/envs/ns3_bridge.py` speaks the same messages directly, and `scripts/gen_proto.py` generates the protobuf code to match the installed protobuf version. The C++ `opengym` module is used unchanged.

## Message format

**ns-3 to Python** (float box): `simTime`, then 4 values per directed link (queue, utilization, loss, delay), then 5 per flow (tx, rx, rxBytes, delaySum, jitterSum, as changes since the last step).

**Python to ns-3** (int32 box): `nextHop[n][d]` for every pair, then `linkUp[l]` for every link, then traffic scale in percent.

Changing this format means changing `routing-gym-env.cc` and `ns3_bridge.py` together.

## Licensing note

The project is MIT-licensed, except `ns3/`, which links against ns-3 and is GPL-2.0-only, and `drl_arco/envs/proto/messages.proto`, copied from ns3-gym under its GPL-2.0 license.
