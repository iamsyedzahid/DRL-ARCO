"""DQN training loop. The best checkpoint is chosen by reward on held-out seeds."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from statistics import mean
from typing import Any

from drl_arco.agents.dqn import DqnAgent
from drl_arco.benchmark import run_episode
from drl_arco.envs.factory import make_env
from drl_arco.policies import DEFAULT_CHECKPOINT

EVAL_SEEDS = (900_001, 900_002)  # unused by training and by the benchmark
EVAL_EVERY = 10


class _GreedyAgentPolicy:
    name = "dqn"

    def __init__(self, agent: DqnAgent):
        self.agent = agent

    def begin_episode(self) -> None:
        self.agent.reset_episode()

    def propose(self, env, state):
        return self.agent.act(state, env.known_up)


def train(
    cfg: dict[str, Any],
    episodes: int,
    backend: str = "surrogate",
    seed: int = 0,
    checkpoint: str | Path = DEFAULT_CHECKPOINT,
    progress: Callable[[dict[str, Any]], None] | None = None,
    stop: threading.Event | None = None,
) -> dict[str, Any]:
    agent_cfg = cfg["agent"]
    scenarios = list(agent_cfg["train_scenarios"])
    envs = {name: make_env(cfg, name, backend) for name in scenarios}
    first = envs[scenarios[0]]
    agent = DqnAgent(cfg, first.topology, first.state_size, seed)
    best_eval = float("-inf")
    history: list[dict[str, Any]] = []

    try:
        for episode in range(episodes):
            if stop and stop.is_set():
                break
            fraction = min(episode / max(agent_cfg["epsilon_decay_episodes"], 1), 1.0)
            epsilon = agent_cfg["epsilon_start"] + fraction * (
                agent_cfg["epsilon_end"] - agent_cfg["epsilon_start"]
            )
            scenario = scenarios[episode % len(scenarios)]
            env = envs[scenario]
            state = env.reset(seed * 1000 + episode)
            agent.reset_episode()
            rewards: list[float] = []
            losses: list[float] = []
            done = False
            while not done and not (stop and stop.is_set()):
                proposal = agent.act(state, env.known_up, epsilon)
                result = env.step(proposal)
                agent.observe(state, result.fib, result.state, env.known_up,
                              env.hop_rewards(result.telemetry))
                for _ in range(agent_cfg["updates_per_step"]):
                    loss = agent.learn()
                    if loss is not None:
                        losses.append(loss)
                rewards.append(result.reward)
                state, done = result.state, result.done

            record: dict[str, Any] = {
                "episode": episode + 1,
                "episodes": episodes,
                "scenario": scenario,
                "epsilon": epsilon,
                "reward": mean(rewards) if rewards else 0.0,
                "loss": mean(losses) if losses else None,
                **env.metrics.summary(),
            }

            if (episode + 1) % EVAL_EVERY == 0 or episode + 1 == episodes:
                policy = _GreedyAgentPolicy(agent)
                scores = [run_episode(envs[name], policy, s)["reward"]
                          for name in scenarios for s in EVAL_SEEDS]
                record["eval_reward"] = mean(scores)
                if record["eval_reward"] > best_eval:
                    best_eval = record["eval_reward"]
                    agent.save(checkpoint, {"backend": backend, "episode": episode + 1,
                                            "eval_reward": best_eval})
            history.append(record)
            if progress:
                progress(record)
    finally:
        for env in envs.values():
            env.close()
    return {"history": history, "best_eval_reward": best_eval, "checkpoint": str(checkpoint)}
