"""Command line: ``python -m drl_arco {train,benchmark,gui}``."""

from __future__ import annotations

import argparse

from drl_arco.config import load_config


def _print_table(summary: list[dict]) -> None:
    print(f"{'scenario':<14}{'policy':<10}{'PDR %':>8}{'latency ms':>12}"
          f"{'Mbps':>8}{'jitter ms':>11}{'reward':>9}")
    for row in summary:
        print(f"{row['scenario']:<14}{row['policy']:<10}{100 * row['pdr']:>8.2f}"
              f"{row['latency_ms']:>12.2f}{row['throughput_mbps']:>8.2f}"
              f"{row['jitter_ms']:>11.2f}{row['reward']:>9.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="drl_arco", description=__doc__)
    parser.add_argument("--config", help="path to a YAML config")
    commands = parser.add_subparsers(dest="command", required=True)

    train_cmd = commands.add_parser("train", help="train the DQN agent")
    train_cmd.add_argument("--episodes", type=int, default=120)
    train_cmd.add_argument("--backend", choices=["surrogate", "ns3"], default="surrogate")
    train_cmd.add_argument("--seed", type=int, default=0)
    train_cmd.add_argument("--checkpoint", default=None)

    bench_cmd = commands.add_parser("benchmark", help="compare DQN against Dijkstra")
    bench_cmd.add_argument("--backend", choices=["surrogate", "ns3"], default="surrogate")
    bench_cmd.add_argument("--scenarios", nargs="+")
    bench_cmd.add_argument("--policies", nargs="+", default=["dijkstra", "dqn"])
    bench_cmd.add_argument("--seeds", type=int, default=10, help="number of seeds")
    bench_cmd.add_argument("--checkpoint", default=None)

    gui_cmd = commands.add_parser("gui", help="start the web dashboard")
    gui_cmd.add_argument("--host", default="127.0.0.1")
    gui_cmd.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()
    cfg = load_config(args.config)

    if args.command == "train":
        from drl_arco.policies import DEFAULT_CHECKPOINT
        from drl_arco.train import train

        def report(r: dict) -> None:
            evaluation = f"  eval {r['eval_reward']:.3f}" if "eval_reward" in r else ""
            print(f"episode {r['episode']:>4}/{r['episodes']}  {r['scenario']:<13}"
                  f"eps {r['epsilon']:.2f}  reward {r['reward']:.3f}  "
                  f"PDR {100 * r['pdr']:.1f}%{evaluation}", flush=True)

        outcome = train(cfg, args.episodes, args.backend, args.seed,
                        args.checkpoint or DEFAULT_CHECKPOINT, progress=report)
        print(f"best held-out reward {outcome['best_eval_reward']:.3f}, "
              f"saved to {outcome['checkpoint']}")
    elif args.command == "benchmark":
        from drl_arco.benchmark import benchmark_seeds, run_benchmark, save_results

        results = run_benchmark(
            cfg, args.scenarios or list(cfg["scenarios"]), args.policies,
            benchmark_seeds(args.seeds), args.backend, args.checkpoint,
        )
        _print_table(results["summary"])
        print(f"saved to {save_results(results)}")
    else:
        from drl_arco.gui.server import serve

        serve(cfg, args.host, args.port)


if __name__ == "__main__":
    main()
