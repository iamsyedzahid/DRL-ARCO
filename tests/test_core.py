"""Topology, loop guard, surrogate backend and environment behavior."""

import numpy as np
import pytest

from drl_arco.config import load_config
from drl_arco.envs.factory import make_env
from drl_arco.safety.loop_guard import validate_fib
from drl_arco.topology import Topology


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def topology(cfg):
    return Topology(cfg["topology"])


def has_cycle(fib, dest):
    for start in range(len(fib)):
        node, seen = start, set()
        while node != dest and node >= 0:
            if node in seen:
                return True
            seen.add(node)
            node = int(fib[node, dest])
    return False


def test_topology_has_ten_connected_nodes(topology):
    assert topology.n_nodes == 10
    fib = topology.spf()
    for src in range(10):
        for dst in range(10):
            assert topology.path(fib, src, dst)[-1] == dst


def test_spf_prefers_the_core(topology):
    assert topology.path(topology.spf(), 0, 7) == [0, 3, 5, 7]


def test_spf_avoids_failed_link(topology):
    up = np.ones(topology.n_links, dtype=bool)
    up[7] = False  # 3-5
    path = topology.path(topology.spf(up), 0, 7)
    assert path[0] == 0 and path[-1] == 7
    assert (3, 5) not in zip(path, path[1:])


def test_guard_breaks_an_explicit_loop(topology):
    up = np.ones(topology.n_links, dtype=bool)
    spf = topology.spf(up)
    proposed = spf.copy()
    proposed[0, 7], proposed[3, 7] = 3, 0  # 0 -> 3 -> 0
    fib, report = validate_fib(proposed, spf, topology, up)
    assert report.loops_broken == 1
    assert not has_cycle(fib, 7)
    assert topology.path(fib, 0, 7)[-1] == 7


def test_guard_rejects_hop_over_down_or_absent_link(topology):
    up = np.ones(topology.n_links, dtype=bool)
    up[2] = False  # 0-3
    spf = topology.spf(up)
    proposed = spf.copy()
    proposed[0, 7] = 3  # link is down
    proposed[1, 7] = 9  # not a neighbor
    fib, report = validate_fib(proposed, spf, topology, up)
    assert report.invalid_hops == 2
    assert fib[0, 7] == spf[0, 7] and fib[1, 7] == spf[1, 7]


def test_guard_leaves_a_valid_table_untouched(topology):
    up = np.ones(topology.n_links, dtype=bool)
    spf = topology.spf(up)
    fib, report = validate_fib(spf, spf, topology, up)
    assert np.array_equal(fib, spf)
    assert report.loops_broken == report.invalid_hops == 0


def test_guard_gives_no_route_to_an_unreachable_destination(topology):
    up = np.ones(topology.n_links, dtype=bool)
    for link in topology.links_of_node(7):  # router 7 fails
        up[link] = False
    spf = topology.spf(up)
    proposed = spf.copy()
    proposed[3, 7], proposed[5, 7] = 5, 4  # live hops, but towards a dead router
    fib, _ = validate_fib(proposed, spf, topology, up)
    assert np.all(fib[:, 7] == -1)


def test_guard_output_is_always_loop_free_and_reachable(topology):
    rng = np.random.default_rng(1)
    for _ in range(300):
        up = rng.random(topology.n_links) > 0.15
        spf = topology.spf(up)
        proposed = rng.integers(-1, 10, size=(10, 10))
        for n, hops in enumerate(topology.neighbors):
            for d in range(10):
                if rng.random() < 0.8:
                    proposed[n, d] = rng.choice(hops)
        fib, _ = validate_fib(proposed, spf, topology, up)
        for dest in range(10):
            assert not has_cycle(fib, dest)
            for node in range(10):
                if node != dest and fib[node, dest] >= 0:
                    assert topology.is_up(node, int(fib[node, dest]), up)
                if spf[node, dest] >= 0:  # reachable under Dijkstra stays reachable
                    assert topology.path(fib, node, dest)[-1] == dest


def run_dijkstra(cfg, scenario, seed=1):
    env = make_env(cfg, scenario)
    env.reset(seed)
    results = []
    done = False
    while not done:
        result = env.step(None)
        results.append(result)
        done = result.done
    return env, results


def test_surrogate_conserves_packets_and_stays_in_bounds(cfg):
    env, results = run_dijkstra(cfg, "bursty")
    for result in results:
        t = result.telemetry
        assert np.all(t.flow_rx <= t.flow_tx + 1e-6)
        assert np.all((t.queue >= 0) & (t.queue <= 1))
        assert np.all((t.util >= 0) & (t.util <= 1))
        assert np.all((t.loss >= 0) & (t.loss <= 1))
    summary = env.metrics.summary()
    assert 0 < summary["pdr"] <= 1
    assert summary["latency_ms"] > 0


def test_same_seed_is_reproducible_and_a_new_seed_differs(cfg):
    a = run_dijkstra(cfg, "bursty", 7)[0].metrics.summary()
    b = run_dijkstra(cfg, "bursty", 7)[0].metrics.summary()
    c = run_dijkstra(cfg, "bursty", 8)[0].metrics.summary()
    assert a == b
    assert a != c


def test_more_traffic_means_more_loss(cfg):
    light = run_dijkstra(cfg, "light")[0].metrics.summary()
    bursty = run_dijkstra(cfg, "bursty")[0].metrics.summary()
    assert light["pdr"] > bursty["pdr"]


def test_failure_is_detected_only_after_the_configured_delay(cfg):
    delay = cfg["sim"]["link_state_delay_steps"]
    env = make_env(cfg, "link_failure")
    env.reset(1)
    fail_step = int(10 / cfg["sim"]["step_s"])
    seen = {}
    for step in range(fail_step + delay + 2):
        env.step(None)
        seen[step] = bool(env.known_up[7])
    assert seen[fail_step + delay - 1] is True
    assert seen[fail_step + delay] is False


def test_failure_scenario_loses_more_than_no_failure(cfg):
    failed = run_dijkstra(cfg, "node_failure")[0].metrics.summary()
    healthy_cfg = {**cfg, "scenarios": {**cfg["scenarios"],
                                        "node_failure": {"scale": 0.8, "events": []}}}
    healthy = run_dijkstra(healthy_cfg, "node_failure")[0].metrics.summary()
    assert failed["pdr"] < healthy["pdr"]


def test_cold_start_uses_dijkstra_even_when_given_a_proposal(cfg):
    env = make_env(cfg, "light")
    env.reset(1)
    bad = np.full((10, 10), 1)
    result = env.step(bad)
    assert result.cold_start
    assert np.array_equal(result.fib, env.spf)


def test_reward_prefers_delivery(cfg):
    env = make_env(cfg, "light")
    env.reset(1)
    t = env.step(None).telemetry
    while t.flow_tx.sum() == 0:
        t = env.step(None).telemetry
    good = env.reward(t)
    t.flow_rx = t.flow_rx * 0.5
    t.flow_delay_s = t.flow_delay_s * 0.5  # same per-packet delay, half delivered
    assert env.reward(t) < good
