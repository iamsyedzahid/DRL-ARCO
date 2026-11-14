# Step-by-step project guide

How to do each part of the project, week by week. A working first version of every feature is already in the repository, so each step is to **understand it, run it, verify it on ns-3, and improve it**.

**Commands** assume you are in the repository folder with the virtual environment active. See the [README](../README.md#setup) if you have not set it up.

## Who owns what

| Feature | Owner | Main files |
|---|---|---|
| 1. MDP state extractor | Syed Zahid Hussain | `ns3/scratch/drl-arco/routing-gym-env.cc`, `drl_arco/envs/routing_env.py` |
| 2. DQN routing engine | Mahad Munawar | `drl_arco/agents/`, `drl_arco/train.py` |
| 3. Loop prevention and fallback | Mahad Munawar | `drl_arco/safety/loop_guard.py` |
| 4. Traffic and bottleneck generator | Mahad Munawar | `ns3/scratch/drl-arco/drl-arco.cc`, `drl_arco/traffic.py`, `configs/default.yaml` |
| 5. Benchmarking engine | Syed Zahid Hussain | `drl_arco/benchmark.py`, `results/` |
| GUI | Shared | `drl_arco/gui/` |

## Week 1: Environment and topology

**Both members**

1. Follow the [README setup](../README.md#setup) on both laptops.
2. Create the GitHub repository ([steps below](#github-workflow)) and make sure you can both push branches.
3. Run `pytest -q` and start the dashboard with `python -m drl_arco gui`.

**Zahid**

4. Follow [NS3_SETUP.md](NS3_SETUP.md) until `bash scripts/check_ns3.sh` passes.
5. Read `drl-arco.cc` and match each section to the topology in `configs/default.yaml`.

**Mahad**

6. Do the same ns-3 setup on your laptop.
7. Run a Dijkstra-only run in the dashboard. Note which links turn dark and explain why from the routes.

**Done when:** both laptops pass `bash scripts/check_ns3.sh`, and the first CI run on GitHub is green.

## Week 2: State extraction and traffic

**Zahid: Feature 1**

1. Read `RoutingGymEnv::GetObservation` in `routing-gym-env.cc`.
2. Check the numbers against a hand calculation. For a flow at a known rate, utilization should match `rate / capacity`.
3. To compare with ns-3's own view, add `p2p.EnablePcapAll("trace")` temporarily and inspect the capture in Wireshark.
4. Confirm the observation format described in [ARCHITECTURE.md](ARCHITECTURE.md#message-format).

**Mahad: Feature 4**

1. Compare the `traffic` and `scenarios` sections of `configs/default.yaml` with `drl-arco.cc`.
2. Run each scenario under Dijkstra and confirm congestion and failures appear when expected:

   ```bash
   python -m drl_arco benchmark --backend ns3 --policies dijkstra --seeds 3
   ```

3. **Tune the load.** The numbers in the config were tuned on the surrogate. If the ns-3 core is rarely congested or is hopelessly overloaded, adjust `scale` until `bursty` shows noticeable but not extreme loss, around 90-98% PDR under Dijkstra.
4. After changing flows or links, update the matching defaults in `drl-arco.cc`. `tests/test_config_sync.py` fails if they differ.

**Both:** review the reward weights in `configs/default.yaml`, and be ready to justify them.

**Done when:** all four scenarios behave as designed on ns-3 under Dijkstra.

## Week 3: The agent and training

**Mahad: Feature 2**

1. Read `drl_arco/agents/dqn.py`. Make sure you can explain the masking, Double DQN target and the per-hop reward.
2. Train on the surrogate as a quick check, which takes about 10-15 minutes on a laptop CPU:

   ```bash
   python -m drl_arco train --episodes 120
   python -m drl_arco benchmark --seeds 10
   ```

3. Train on ns-3, the real target. This takes much longer, so start with fewer episodes:

   ```bash
   python -m drl_arco train --backend ns3 --episodes 120 --checkpoint checkpoints/dqn_ns3.pt
   ```

4. Watch held-out reward in the Train tab. If it does not improve, try in this order: lower `lr`, more episodes, a larger `epsilon_decay_episodes`, a higher `switch_margin` if routes oscillate.

**Zahid:** help check that the training data is right. Print a few states and rewards from ns-3 and sanity-check them. Bad data looks exactly like a bad model.

**Done when:** the trained model beats or clearly matches Dijkstra on held-out seeds in at least the congested scenarios on ns-3.

## Week 4: Safety and failure testing

**Mahad: Feature 3**

1. Read `drl_arco/safety/loop_guard.py` and its tests in `tests/test_core.py`.
2. In the dashboard, run DQN on `node_failure` and watch **Loops broken** and **Invalid hops fixed**.
3. Fail links by clicking them, including several at once, and check that traffic reroutes and that routes never show a loop.
4. Try `cold_start_steps` at 0, 20 and 50 and record the effect at the start of each run.

**Zahid**

5. Add loop and fallback counts to your results table. They are already in the per-run data as `loops_broken`.
6. Run the failure scenarios on ns-3 and measure recovery: how long delivery stays low after a failure.

**Done when:** no forwarding loops survive validation under any failure scenario, and recovery is measured for both policies.

## Week 5: Benchmarks and report

**Zahid: Feature 5**

1. Freeze the config and the model. Do not tune after this point.
2. Run the final comparison, with seeds the model never trained on:

   ```bash
   python -m drl_arco benchmark --backend ns3 --seeds 20 --checkpoint checkpoints/dqn_ns3.pt
   ```

3. Report mean ± standard deviation for PDR, latency, throughput and jitter, from `results/benchmark_ns3.csv`.
4. Report honestly where DQN did not win. Light traffic, for example, leaves little to improve.

**Both**

5. Take dashboard screenshots with the **ns-3** badge showing.
6. Write the report. It should state:
   - Dijkstra with OSPF costs was the baseline, because ns-3 has no OSPF module.
   - The action is per destination, not per packet.
   - Final results are from ns-3, not the surrogate.

## Using the dashboard

```bash
python -m drl_arco gui
```

Then open <http://127.0.0.1:8000>.

| Tab | What to do |
|---|---|
| **Live network** | Choose simulator, policy and scenario, then **Start**. Click a link or router to fail or restore it. Move the **Traffic** slider to create congestion. Choose **From** and **To** to see the active route (orange) against Dijkstra's (dotted). |
| **Train** | Set episodes and **Start training**. This replaces `checkpoints/dqn.pt`. |
| **Benchmark** | Set seeds and **Run benchmark** to get charts and a table comparing DQN and Dijkstra. |

The badge at the top shows the simulator. A surrogate warning means those numbers are not for your report.

## GitHub workflow

**First-time setup (one member):**

1. On GitHub, click **New repository**, name it `DRL-ARCO`, leave it empty with no README, and create it.
2. In the project folder:

   ```bash
   git init -b main
   git add .
   git commit -m "Initial project skeleton"
   git remote add origin https://github.com/<your-account>/DRL-ARCO.git
   git push -u origin main
   ```

3. In **Settings > Collaborators**, invite your teammate.
4. Optional: in **Settings > Branches**, require a pull request and passing CI for `main`.

**Everyday work:**

```bash
git switch main && git pull
git switch -c feature/short-description
# make changes
pytest -q && ruff check .
git add <files>
git commit -m "Describe the change"
git push -u origin feature/short-description
```

Then open a pull request and have your teammate review it before merging. Suggested branch names: `feature/state-extractor`, `feature/dqn-tuning`, `feature/loop-guard`, `feature/traffic-scenarios`, `feature/benchmarking`.

**Track the plan:** create milestones **Week 1** to **Week 5** under **Issues > Milestones**, and open an issue for each task with the **Project task** template.
