#!/usr/bin/env python3
"""End-to-end ns-3 check: run a short real simulation and sanity-check the numbers.

Run from the repository root with the virtual environment active and NS3_HOME set.
Exit code 0 means Python and ns-3 talked and the network behaved plausibly.
"""

from __future__ import annotations

import copy
import sys

import numpy as np

from drl_arco.config import load_config
from drl_arco.envs.factory import make_env
from drl_arco.envs.ns3_bridge import availability

STEPS = 100


def main() -> int:
    ready, reason = availability()
    if not ready:
        print(f"FAIL: {reason}")
        return 1
    print(f"OK: {reason}")

    cfg = copy.deepcopy(load_config())
    cfg["sim"]["episode_steps"] = STEPS
    env = make_env(cfg, "bursty", "ns3")
    env.reset(1)
    busy_links = np.zeros(env.topology.n_dir, dtype=bool)
    for step in range(STEPS):
        if step == 50:
            env.set_link(7, False)
        result = env.step(None)
        busy_links |= result.telemetry.util > 0
    summary = env.metrics.summary()
    env.close()

    print(f"packets sent {env.metrics.tx:.0f}, received {env.metrics.rx:.0f}")
    print(f"PDR {100 * summary['pdr']:.2f}%  latency {summary['latency_ms']:.2f} ms  "
          f"throughput {summary['throughput_mbps']:.2f} Mbps  jitter {summary['jitter_ms']:.2f} ms")
    print(f"directed links that carried traffic: {int(busy_links.sum())}/{env.topology.n_dir}")

    checks = {
        "packets were sent": env.metrics.tx > 0,
        "packets were delivered": env.metrics.rx > 0,
        "PDR is below or at 100%": summary["pdr"] <= 1.0,
        "latency is above the 6 ms core path": summary["latency_ms"] > 6.0,
        "several links carried traffic": busy_links.sum() >= 4,
    }
    passed = True
    for name, ok in checks.items():
        print(f"{'OK' if ok else 'FAIL'}: {name}")
        passed = passed and ok
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
