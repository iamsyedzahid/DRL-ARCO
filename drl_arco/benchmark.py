"""Feature 5: paired evaluation of routing policies, with CSV and JSON output.

Every policy runs on the same scenarios and seeds, so results compare like with like.
"""

from __future__ import annotations

import csv
import json
import threading
from collections.abc import Callable
from pathlib import Path
from statistics import mean, stdev
from typing import Any

from drl_arco.config import REPO_ROOT
from drl_arco.envs.factory import make_env
from drl_arco.envs.routing_env import RoutingEnv
from drl_arco.policies import Policy, make_policy

RESULTS_DIR = REPO_ROOT / "results"
METRICS = ("pdr", "latency_ms", "throughput_mbps", "jitter_ms")
# Far above the seeds training uses (seed * 1000 + episode), so evaluation runs are unseen.
BENCHMARK_SEED_BASE = 1_000_000


def benchmark_seeds(count: int) -> list[int]:
    return list(range(BENCHMARK_SEED_BASE, BENCHMARK_SEED_BASE + count))


def run_episode(env: RoutingEnv, policy: Policy, seed: int,
                stop: threading.Event | None = None) -> dict[str, float]:
    state = env.reset(seed)
    policy.begin_episode()
    reward_total = 0.0
    done = False
    while not done and not (stop and stop.is_set()):
        result = env.step(policy.propose(env, state))
        state, done = result.state, result.done
        reward_total += result.reward
    summary = env.metrics.summary()
    summary["reward"] = reward_total / max(env.step_count, 1)
    summary["loops_broken"] = env.guard_totals.loops_broken
    return summary


def aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mean and sample standard deviation per scenario and policy."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["scenario"], row["policy"]), []).append(row)
    summary = []
    for (scenario, policy), members in groups.items():
        entry: dict[str, Any] = {"scenario": scenario, "policy": policy, "runs": len(members)}
        for metric in (*METRICS, "reward"):
            values = [m[metric] for m in members]
            entry[metric] = mean(values)
            entry[f"{metric}_std"] = stdev(values) if len(values) > 1 else 0.0
        summary.append(entry)
    return summary


def run_benchmark(
    cfg: dict[str, Any],
    scenarios: list[str],
    policies: list[str],
    seeds: list[int],
    backend: str = "surrogate",
    checkpoint: str | Path | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
    stop: threading.Event | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    total = len(scenarios) * len(policies) * len(seeds)
    for scenario in scenarios:
        for policy_name in policies:
            env = make_env(cfg, scenario, backend)
            try:
                policy = make_policy(policy_name, cfg, env, checkpoint)
                for seed in seeds:
                    if stop and stop.is_set():
                        break
                    row = {"backend": backend, "scenario": scenario, "policy": policy_name,
                           "seed": seed, **run_episode(env, policy, seed, stop)}
                    rows.append(row)
                    if progress:
                        progress({"done": len(rows), "total": total, "last": row})
            finally:
                env.close()
    return {"backend": backend, "rows": rows, "summary": aggregate(rows)}


def save_results(results: dict[str, Any], directory: Path = RESULTS_DIR) -> Path:
    """Write results to disk, keeping ns-3 and surrogate results in separate files."""
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"benchmark_{results['backend']}"
    (directory / f"{stem}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    with open(directory / f"{stem}.csv", "w", newline="", encoding="utf-8") as handle:
        if results["rows"]:
            writer = csv.DictWriter(handle, fieldnames=list(results["rows"][0]))
            writer.writeheader()
            writer.writerows(results["rows"])
    return directory / f"{stem}.json"
