"""DQN agent, checkpoints, training loop and benchmark pipeline."""

import copy

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from drl_arco.agents.dqn import DqnAgent  # noqa: E402
from drl_arco.benchmark import aggregate, run_benchmark, save_results  # noqa: E402
from drl_arco.config import load_config  # noqa: E402
from drl_arco.envs.factory import make_env  # noqa: E402
from drl_arco.train import train  # noqa: E402


@pytest.fixture()
def cfg():
    config = copy.deepcopy(load_config())
    config["sim"]["episode_steps"] = 40
    config["guard"]["cold_start_steps"] = 2
    config["agent"]["warmup_steps"] = 5
    config["agent"]["hidden"] = [32]
    return config


def test_act_only_picks_live_neighbors(cfg):
    env = make_env(cfg, "light")
    state = env.reset(1)
    agent = DqnAgent(cfg, env.topology, env.state_size)
    up = np.ones(env.topology.n_links, dtype=bool)
    up[7] = False
    for epsilon in (0.0, 1.0):
        agent.reset_episode()
        fib = agent.act(state, up, epsilon)
        for node in range(10):
            for dest in range(10):
                if node != dest:
                    assert env.topology.is_up(node, int(fib[node, dest]), up)


def test_switch_margin_holds_the_current_route(cfg):
    env = make_env(cfg, "light")
    state = env.reset(1)
    agent = DqnAgent(cfg, env.topology, env.state_size)
    up = np.ones(env.topology.n_links, dtype=bool)
    agent.act(state, up)
    forced = np.zeros(agent.n_decisions, dtype=np.int64)
    agent.current_ports = forced.copy()
    agent.cfg = {**agent.cfg, "switch_margin": 1e9}
    fib = agent.act(state, up)
    expected = env.topology.port_table[agent.nodes, forced]
    assert np.array_equal(fib[agent.nodes, agent.dests], expected)


def test_learning_reduces_loss_on_a_fixed_batch(cfg):
    env = make_env(cfg, "bursty")
    agent = DqnAgent(cfg, env.topology, env.state_size)
    state = env.reset(1)
    for _ in range(30):
        result = env.step(agent.act(state, env.known_up, 0.2))
        agent.observe(state, result.fib, result.state, env.known_up,
                      env.hop_rewards(result.telemetry))
        state = result.state
    early = np.mean([agent.learn() for _ in range(10)])
    for _ in range(300):
        agent.learn()
    late = np.mean([agent.learn() for _ in range(10)])
    assert late < early


def test_checkpoint_round_trip_and_size_check(cfg, tmp_path):
    env = make_env(cfg, "light")
    state = env.reset(1)
    up = np.ones(env.topology.n_links, dtype=bool)
    a = DqnAgent(cfg, env.topology, env.state_size, seed=1)
    a.save(tmp_path / "x.pt", {"episode": 3})
    b = DqnAgent(cfg, env.topology, env.state_size, seed=2)
    assert b.load(tmp_path / "x.pt") == {"episode": 3}
    assert np.array_equal(a.act(state, up), b.act(state, up))
    with pytest.raises(ValueError):
        DqnAgent(cfg, env.topology, env.state_size + 1).load(tmp_path / "x.pt")


def test_train_then_benchmark_end_to_end(cfg, tmp_path):
    outcome = train(cfg, episodes=2, checkpoint=tmp_path / "c.pt")
    assert (tmp_path / "c.pt").exists()
    assert len(outcome["history"]) == 2
    results = run_benchmark(cfg, ["light"], ["dijkstra", "dqn"], [1, 2],
                            checkpoint=tmp_path / "c.pt")
    assert {row["policy"] for row in results["rows"]} == {"dijkstra", "dqn"}
    assert len(results["summary"]) == 2
    saved = save_results(results, tmp_path)
    assert saved.exists() and saved.with_suffix(".csv").exists()


def test_aggregate_computes_mean_and_std():
    base = {"scenario": "s", "policy": "p", "latency_ms": 0, "throughput_mbps": 0,
            "jitter_ms": 0, "reward": 0}
    summary = aggregate([{**base, "pdr": 0.5}, {**base, "pdr": 0.7}])
    assert summary[0]["pdr"] == pytest.approx(0.6)
    assert summary[0]["pdr_std"] == pytest.approx(0.1414, abs=1e-3)


def test_benchmark_seeds_never_overlap_training_or_held_out_seeds():
    from drl_arco.benchmark import benchmark_seeds
    from drl_arco.train import EVAL_SEEDS

    seeds = set(benchmark_seeds(100))
    largest_training_seed = 99 * 1000 + 5000  # seed 99, 5000 episodes
    assert min(seeds) > largest_training_seed
    assert not seeds & set(EVAL_SEEDS)
    assert min(EVAL_SEEDS) > largest_training_seed
