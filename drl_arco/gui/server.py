"""Web dashboard: a Flask server, one background job at a time, live updates over SSE.

Binds to localhost by default. It has no authentication, so do not expose it publicly.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request, send_from_directory

from drl_arco.benchmark import RESULTS_DIR, benchmark_seeds, run_benchmark, save_results
from drl_arco.config import REPO_ROOT
from drl_arco.envs.factory import make_env
from drl_arco.envs.ns3_bridge import availability
from drl_arco.envs.routing_env import RoutingEnv, StepResult
from drl_arco.policies import DEFAULT_CHECKPOINT, make_policy
from drl_arco.topology import Topology
from drl_arco.traffic import load_flows

STATIC_DIR = Path(__file__).parent / "static"
CHECKPOINT_DIR = REPO_ROOT / "checkpoints"
SUBSCRIBER_BUFFER = 256


def _rounded(values, digits: int = 3) -> list[float]:
    return [round(float(v), digits) for v in values]


class Dashboard:
    """Owns the running job and fans its events out to connected browsers."""

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.topology = Topology(cfg["topology"])
        self.flows = load_flows(cfg)
        self.lock = threading.Lock()
        self.subscribers: list[queue.Queue] = []
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.job: str | None = None
        self.env: RoutingEnv | None = None
        self.steps_per_second = 10.0
        self.pending_controls: list[tuple[str, int | float, bool]] = []

    # Event fan-out
    def subscribe(self) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue(SUBSCRIBER_BUFFER)
        with self.lock:
            self.subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self.lock:
            self.subscribers.remove(subscriber)

    def publish(self, kind: str, payload: dict[str, Any]) -> None:
        message = f"event: {kind}\ndata: {json.dumps(payload)}\n\n"
        with self.lock:
            for subscriber in self.subscribers:
                try:
                    subscriber.put_nowait(message)
                except queue.Full:  # a slow browser skips frames rather than stalling the run
                    pass

    # Job management
    def _start(self, name: str, target, *args) -> tuple[bool, str]:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return False, f"{self.job} is already running"
            self.stop_event.clear()
            self.pause_event.clear()
            self.pending_controls = []
            self.job = name
            self.thread = threading.Thread(target=self._guarded, args=(name, target, args),
                                           daemon=True)
            self.thread.start()
        return True, "started"

    def _guarded(self, name: str, target, args) -> None:
        self.publish("job", {"job": name, "state": "running"})
        try:
            target(*args)
            state = "stopped" if self.stop_event.is_set() else "finished"
            self.publish("job", {"job": name, "state": state})
        except Exception as error:  # shown to the user rather than dying silently in a thread
            self.publish("job", {"job": name, "state": "error", "error": str(error)})
        finally:
            self.env = None
            self.job = None

    def stop(self) -> None:
        self.stop_event.set()
        self.pause_event.clear()

    def status(self) -> dict[str, Any]:
        return {"job": self.job, "paused": self.pause_event.is_set()}

    # Live run
    def start_run(self, options: dict[str, Any]) -> tuple[bool, str]:
        return self._start("run", self._run, options)

    def _frame(self, env: RoutingEnv, result: StepResult) -> dict[str, Any]:
        t = result.telemetry
        tx, rx = float(t.flow_tx.sum()), float(t.flow_rx.sum())
        return {
            "step": env.step_count,
            "episode_steps": env.episode_steps,
            "time_s": round(env.step_count * env.dt, 2),
            "queue": _rounded(t.queue),
            "util": _rounded(t.util),
            "loss": _rounded(t.loss),
            "link_up": [bool(v) for v in env.link_up],
            "known_up": [bool(v) for v in env.known_up],
            "node_down": [bool(v) for v in env.node_failed],
            "scale": round(env.scale, 2),
            "reward": round(result.reward, 4),
            "cold_start": result.cold_start,
            "fib": result.fib.tolist(),
            "spf": env.spf.tolist(),
            "guard": {"loops_broken": env.guard_totals.loops_broken,
                      "invalid_hops": env.guard_totals.invalid_hops},
            "events": result.fired,
            "metrics": {k: round(v, 4) for k, v in env.metrics.summary().items()},
            "instant": {
                "pdr": round(min(rx / tx, 1.0), 4) if tx > 0 else None,
                "latency_ms": round(1000 * float(t.flow_delay_s.sum()) / rx, 3) if rx > 0 else None,
                "throughput_mbps": round(float(t.flow_rx_bytes.sum()) * 8 / 1e6 / env.dt, 3),
                "jitter_ms": round(1000 * float(t.flow_jitter_s.sum()) / rx, 3) if rx > 0 else None,
            },
        }

    def _run(self, options: dict[str, Any]) -> None:
        env = make_env(self.cfg, options["scenario"], options.get("backend", "surrogate"))
        try:
            policy = make_policy(options["policy"], self.cfg, env, options.get("checkpoint"))
            state = env.reset(int(options.get("seed", 1)))
            policy.begin_episode()
            self.env = env
            self.publish("run_start", {"policy": options["policy"], "scenario": options["scenario"],
                                       "backend": env.backend.name})
            done = False
            while not done and not self.stop_event.is_set():
                if self.pause_event.is_set():
                    time.sleep(0.05)
                    continue
                started = time.monotonic()
                with self.lock:
                    controls, self.pending_controls = self.pending_controls, []
                for kind, target, up in controls:
                    if kind == "link":
                        env.set_link(int(target), up)
                    elif kind == "node":
                        env.set_node(int(target), up)
                    else:
                        env.set_scale(float(target))
                result = env.step(policy.propose(env, state))
                state, done = result.state, result.done
                self.publish("frame", self._frame(env, result))
                wait = 1 / self.steps_per_second - (time.monotonic() - started)
                if wait > 0:
                    time.sleep(wait)
        finally:
            env.close()

    def control(self, kind: str, target: int | float, up: bool = True) -> bool:
        """Queue a control for the run thread, which applies it between steps."""
        if self.job != "run":
            return False
        with self.lock:
            self.pending_controls.append((kind, target, up))
        return True

    # Training and benchmark
    def start_training(self, options: dict[str, Any]) -> tuple[bool, str]:
        return self._start("train", self._train, options)

    def _train(self, options: dict[str, Any]) -> None:
        from drl_arco.train import train

        outcome = train(
            self.cfg, int(options.get("episodes", 120)), options.get("backend", "surrogate"),
            int(options.get("seed", 0)), DEFAULT_CHECKPOINT,
            progress=lambda record: self.publish("train", record), stop=self.stop_event,
        )
        self.publish("train_done", {"best_eval_reward": outcome["best_eval_reward"]})

    def start_benchmark(self, options: dict[str, Any]) -> tuple[bool, str]:
        return self._start("benchmark", self._benchmark, options)

    def _benchmark(self, options: dict[str, Any]) -> None:
        seeds = benchmark_seeds(int(options.get("seeds", 5)))
        results = run_benchmark(
            self.cfg, options.get("scenarios") or list(self.cfg["scenarios"]),
            ["dijkstra", "dqn"], seeds, options.get("backend", "surrogate"),
            progress=lambda p: self.publish("benchmark_progress",
                                            {k: p[k] for k in ("done", "total")}),
            stop=self.stop_event,
        )
        if results["rows"]:
            save_results(results)
        self.publish("benchmark", results)


def create_app(cfg: dict[str, Any]) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.json.sort_keys = False
    dashboard = Dashboard(cfg)
    app.dashboard = dashboard  # type: ignore[attr-defined]

    def outcome(result: tuple[bool, str]):
        ok, message = result
        return jsonify({"ok": ok, "message": message}), (200 if ok else 409)

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/static/<path:name>")
    def static_file(name: str):
        return send_from_directory(STATIC_DIR, name)

    @app.get("/api/config")
    def config():
        topology = dashboard.topology
        ns3_ready, ns3_reason = availability()
        return jsonify({
            "nodes": topology.nodes,
            "links": [{"id": i, "u": x.u, "v": x.v, "mbps": x.mbps, "delay_ms": x.delay_ms}
                      for i, x in enumerate(topology.links)],
            "flows": [vars(f) for f in dashboard.flows],
            "scenarios": list(cfg["scenarios"]),
            "backends": {"surrogate": {"ready": True, "reason": "built-in approximation"},
                         "ns3": {"ready": ns3_ready, "reason": ns3_reason}},
            "checkpoint": DEFAULT_CHECKPOINT.exists(),
            "status": dashboard.status(),
        })

    @app.get("/api/stream")
    def stream():
        subscriber = dashboard.subscribe()

        def events():
            try:
                yield ": connected\n\n"
                while True:
                    try:
                        yield subscriber.get(timeout=15)
                    except queue.Empty:
                        yield ": keep-alive\n\n"
            finally:
                dashboard.unsubscribe(subscriber)

        return Response(events(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def body() -> dict[str, Any]:
        return request.get_json(silent=True) or {}

    def backend_problem(options: dict[str, Any]):
        if options.get("backend") == "ns3":
            ready, reason = availability()
            if not ready:
                return jsonify({"ok": False, "message": f"ns-3 unavailable: {reason}"}), 400
        return None

    @app.post("/api/run/start")
    def run_start():
        options = body()
        if options.get("scenario") not in cfg["scenarios"]:
            return jsonify({"ok": False, "message": "unknown scenario"}), 400
        if options.get("policy") not in ("dijkstra", "dqn"):
            return jsonify({"ok": False, "message": "unknown policy"}), 400
        if options["policy"] == "dqn" and not DEFAULT_CHECKPOINT.exists():
            return jsonify({"ok": False, "message": "no trained model yet: use the Train tab"}), 400
        return backend_problem(options) or outcome(dashboard.start_run(options))

    @app.post("/api/run/pause")
    def run_pause():
        paused = bool(body().get("paused", True))
        (dashboard.pause_event.set if paused else dashboard.pause_event.clear)()
        return jsonify({"ok": True, "paused": paused})

    @app.post("/api/stop")
    def stop():
        dashboard.stop()
        return jsonify({"ok": True})

    @app.post("/api/run/speed")
    def run_speed():
        dashboard.steps_per_second = min(max(float(body().get("steps_per_second", 10)), 0.5), 100)
        return jsonify({"ok": True})

    @app.post("/api/run/link")
    def run_link():
        options = body()
        link = int(options.get("link", -1))
        if not 0 <= link < dashboard.topology.n_links:
            return jsonify({"ok": False, "message": "unknown link"}), 400
        done = dashboard.control("link", link, bool(options.get("up")))
        return jsonify({"ok": done}), (200 if done else 409)

    @app.post("/api/run/node")
    def run_node():
        options = body()
        node = int(options.get("node", -1))
        if not 0 <= node < dashboard.topology.n_nodes:
            return jsonify({"ok": False, "message": "unknown node"}), 400
        done = dashboard.control("node", node, bool(options.get("up")))
        return jsonify({"ok": done}), (200 if done else 409)

    @app.post("/api/run/scale")
    def run_scale():
        scale = float(body().get("scale", 1.0))
        if not 0 <= scale <= 3:
            return jsonify({"ok": False, "message": "scale must be 0 to 3"}), 400
        done = dashboard.control("scale", scale)
        return jsonify({"ok": done}), (200 if done else 409)

    @app.post("/api/train/start")
    def train_start():
        options = body()
        return backend_problem(options) or outcome(dashboard.start_training(options))

    @app.post("/api/benchmark/start")
    def benchmark_start():
        options = body()
        if not DEFAULT_CHECKPOINT.exists():
            return jsonify({"ok": False, "message": "no trained model yet: use the Train tab"}), 400
        return backend_problem(options) or outcome(dashboard.start_benchmark(options))

    @app.get("/api/benchmark/latest")
    def benchmark_latest():
        backend = request.args.get("backend", "surrogate")
        if backend not in ("surrogate", "ns3"):
            return jsonify({"ok": False, "message": "unknown backend"}), 400
        path = RESULTS_DIR / f"benchmark_{backend}.json"
        if not path.exists():
            return jsonify({"rows": [], "summary": [], "backend": backend})
        return Response(path.read_text(encoding="utf-8"), mimetype="application/json")

    return app


def serve(cfg: dict[str, Any], host: str, port: int) -> None:
    print(f"DRL-ARCO dashboard: http://{host}:{port}")
    create_app(cfg).run(host=host, port=port, threaded=True, debug=False)
