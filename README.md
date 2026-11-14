# DRL-ARCO

**Adaptive Packet Routing and Congestion Optimization Using Deep Reinforcement Learning in ns-3**

Shortest-path routing such as OSPF reacts slowly to bursty traffic, which causes queue build-up and packet loss. DRL-ARCO connects the ns-3 network simulator to a PyTorch Deep Q-Network that learns to choose next hops from live network state, and compares it with Dijkstra routing on a 10-node network.

**Team:** Syed Zahid Hussain (24K-0015) and Mahad Munawar (24I-0065)

## Features

| # | Feature | Owner | Code |
|---|---|---|---|
| 1 | MDP state extractor: queues, loss, throughput and delay from ns-3 | Zahid | [routing-gym-env.cc](ns3/scratch/drl-arco/routing-gym-env.cc), [routing_env.py](drl_arco/envs/routing_env.py) |
| 2 | Double DQN routing engine with experience replay | Mahad | [dqn.py](drl_arco/agents/dqn.py), [train.py](drl_arco/train.py) |
| 3 | Loop prevention and Dijkstra fallback | Mahad | [loop_guard.py](drl_arco/safety/loop_guard.py) |
| 4 | Bursty On-Off traffic, link failures and node failures | Mahad | [drl-arco.cc](ns3/scratch/drl-arco/drl-arco.cc), [default.yaml](configs/default.yaml) |
| 5 | Benchmarks: PDR, latency, throughput and jitter | Zahid | [benchmark.py](drl_arco/benchmark.py) |
| + | Web dashboard: live map, failure injection, training, benchmarks | Shared | [drl_arco/gui/](drl_arco/gui/) |

## The network

10 routers and 16 links. The 20 Mbps core (0-3-5-7) is the cheapest route, so shortest-path routing funnels traffic into it while the 10 Mbps outer paths stay idle.

```
          1 ──────── 4 ──────── 8
        ╱ │          │        ╱ │
       ╱  │          │       ╱  │
      0 ═ 3 ════════ 5 ════ 7   │
       ╲  │          │       ╲  │
        ╲ │          │        ╲ │
          2 ──────── 6 ──────── 9

      ═ 20 Mbps core    ─ 10 Mbps
```

Change it in [configs/default.yaml](configs/default.yaml).

## Setup

There are two ways to run the project:

| | Quick start | Full setup with ns-3 |
|---|---|---|
| **Runs on** | Windows, Linux or macOS | Ubuntu 22.04, native or in WSL2 |
| **Gives you** | Dashboard, training and tests on the built-in surrogate simulator | All of that, on real ns-3 |
| **Time** | About 5 minutes | About 1 hour |
| **Use for** | Development and trying things out | **Results for your report** |

### Quick start

You need Python 3.10 or newer.

**Windows (PowerShell):**

```powershell
cd D:\DRL-ARCO
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[dev]"
python scripts/gen_proto.py
```

If PowerShell blocks the activation script, run this once and try again: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

**Linux, macOS or WSL:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[dev]"
python scripts/gen_proto.py
```

**Check it and start the dashboard:**

```bash
pytest -q
python -m drl_arco gui
```

Open <http://127.0.0.1:8000>, keep the policy on **DQN agent**, and click **Start**.

### Full setup with ns-3

ns-3 does not run directly on Windows for this project, so Windows users need WSL2. In short:

1. **Windows only:** turn on CPU virtualization in the BIOS.
2. **Windows only:** in an Administrator terminal, run `wsl --install --no-distribution` and restart. Then in a normal terminal, run `wsl --install -d Ubuntu-22.04`.
3. Inside Ubuntu, copy or clone the project to your home folder, then:

   ```bash
   bash scripts/install_ns3.sh
   echo 'export NS3_HOME="$HOME/ns-allinone/ns-3.40"' >> ~/.bashrc
   source ~/.bashrc

   python3 -m venv .venv
   source .venv/bin/activate
   pip install torch --index-url https://download.pytorch.org/whl/cpu
   pip install -e ".[ns3,dev]"
   python scripts/gen_proto.py

   bash scripts/check_ns3.sh
   ```

**Follow [docs/NS3_SETUP.md](docs/NS3_SETUP.md) for the full steps and troubleshooting.**

## Usage

Add `--backend ns3` to use ns-3 instead of the surrogate.

```bash
python -m drl_arco gui                     # dashboard at http://127.0.0.1:8000
python -m drl_arco train --episodes 120    # train; saves checkpoints/dqn.pt
python -m drl_arco benchmark --seeds 10    # compare; saves to results/
```

### Dashboard

- **Live network:** watch link load, queues and routes as they change. Click a link or router to fail or restore it, and drag the slider to add traffic.
- **Train:** train the agent and watch its learning curves.
- **Benchmark:** compare DQN and Dijkstra with charts and a results table.

The badge at the top always shows which simulator produced the numbers on screen.

## Results

From real ns-3 (ns-3.40). Each policy ran the same 20 seeds, none used in training, in every scenario. DQN results average three models trained on different seeds.

**Spreads:** Dijkstra's ± is the standard deviation across the 20 seeds. DQN's ± is the standard deviation between the three models' averages, so it shows how much results depend on the training run.

| Scenario | Policy | PDR % | Latency (ms) | Throughput (Mbps) | Jitter (ms) |
|---|---|---|---|---|---|
| Light | Dijkstra | 99.97 ± 0.01 | **8.61 ± 0.05** | 12.35 ± 0.43 | 0.141 ± 0.008 |
| | DQN | 99.97 ± 0.00 | 8.72 ± 0.09 | 12.35 ± 0.00 | 0.128 ± 0.020 |
| Moderate\* | Dijkstra | 93.87 ± 0.98 | 18.65 ± 1.10 | 21.96 ± 0.67 | **0.235 ± 0.010** |
| | DQN | **99.88 ± 0.03** | **11.72 ± 0.33** | **23.37 ± 0.01** | 0.356 ± 0.024 |
| Bursty | Dijkstra | 86.88 ± 1.26 | 29.77 ± 1.77 | 25.43 ± 0.70 | **0.276 ± 0.013** |
| | DQN | **97.97 ± 0.19** | **19.76 ± 1.02** | **28.68 ± 0.05** | 1.341 ± 0.334 |
| Link failure | Dijkstra | 92.61 ± 1.22 | 28.64 ± 2.41 | 22.88 ± 0.68 | **0.305 ± 0.016** |
| | DQN | **97.32 ± 0.53** | **19.98 ± 0.46** | **24.04 ± 0.13** | 0.458 ± 0.107 |
| Node failure | Dijkstra | 92.03 ± 1.33 | 36.49 ± 4.16 | 22.73 ± 0.68 | **0.363 ± 0.039** |
| | DQN | **97.23 ± 0.36** | **23.47 ± 0.82** | **24.02 ± 0.09** | 0.590 ± 0.198 |

\* Not used in training.

- **Congestion and failures:** every model beat Dijkstra on delivery, latency and throughput in all 20 seeds of every congested and failure scenario (240 of 240 paired runs for each metric). That includes `moderate`, which the agent never trained on.
- **Light traffic:** there is nothing to gain. Delivery and throughput tie, and latency is up to 0.17 ms higher.
- **Jitter is DQN's weakness:** it is higher in every congested scenario, about 5 times Dijkstra's under bursty traffic, and that held in every bursty run. Raising `switch_margin` to hold routes longer did not reduce it.
- **Training runs differ most in jitter:** bursty jitter ranges from 1.08 to 1.72 ms across the three models, while delivery stays within 0.4 points.
- **Loop guard:** across the three models it breaks 1.3–2.5 forwarding loops per step under failures and under 1 elsewhere, so it is needed for the agent to work.

Raw results are in `results/final_*.json` and `.csv`, which are kept out of Git.

## Project status

| Part | Status |
|---|---|
| Python: agent, loop guard, environment, benchmark, dashboard | Working, covered by tests |
| ns-3 scenario and Python bridge | Built on ns-3.40; checks, training, benchmarks and the dashboard all run end to end |
| Results | Final: 3 trained models × 20 seeds × 5 scenarios on ns-3 |

## Repository layout

```
├── configs/default.yaml        Topology, traffic, scenarios, hyper-parameters
├── ns3/scratch/drl-arco/       C++ scenario, copied into ns-3 by the scripts
├── drl_arco/
│   ├── agents/                 Double DQN and replay buffer
│   ├── envs/                   MDP, ns-3 bridge, surrogate simulator
│   ├── safety/                 Loop guard
│   ├── gui/                    Dashboard server and web page
│   ├── benchmark.py            Evaluation pipeline
│   ├── policies.py             DQN and Dijkstra policies
│   └── train.py                Training loop
├── scripts/                    ns-3 install, sync and check; protobuf generation
├── tests/                      Test suite
├── docs/
│   ├── NS3_SETUP.md            ns-3 installation
│   ├── STEP_BY_STEP.md         Week-by-week guide for each feature, and Git workflow
│   └── ARCHITECTURE.md         Design decisions and message format
├── checkpoints/                Trained models
└── results/                    Benchmark output (not committed)
```

## Documentation

- [Step-by-step project guide](docs/STEP_BY_STEP.md): what each member does each week, and how
- [ns-3 setup](docs/NS3_SETUP.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Contributing](CONTRIBUTING.md)

## References

1. ns-3 Consortium, ns-3 Network Simulator, <https://www.nsnam.org/>.
2. P. Gawlowicz and A. Zubow, "ns-3 meets OpenAI Gym: The Playground for Machine Learning in Networking Research," ACM MSWiM, 2019.
3. V. Mnih et al., "Human-level control through deep reinforcement learning," Nature, vol. 518, no. 7540, pp. 529-533, 2015.
4. Z. Xu et al., "Experience-Driven Networking: A Deep Reinforcement Learning based Approach," IEEE INFOCOM, 2018.
5. J. Boyan and M. Littman, "Packet Routing in Dynamically Changing Networks: A Reinforcement Learning Approach," NeurIPS, 1993.

## License

MIT, except `ns3/` and `messages.proto`, which are GPL-2.0 because of their ties to ns-3 and ns3-gym. See [LICENSE](LICENSE).
