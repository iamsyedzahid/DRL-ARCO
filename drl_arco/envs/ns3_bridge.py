"""The ns-3 backend, speaking the ns3-gym wire protocol over ZeroMQ.

This replaces the ``ns3gym`` Python package, whose ``Ns3Env`` relies on ``np.float``
and ``np.int`` (removed in NumPy 1.24) and on the retired ``gym`` package. The C++
``opengym`` module and its message format are used unchanged.

Run ``python scripts/gen_proto.py`` once to create ``messages_pb2.py``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from drl_arco.envs.base import Telemetry
from drl_arco.topology import Topology
from drl_arco.traffic import Flow, ns3_flows_arg

LINK_FIELDS = 4   # queue, utilization, loss, delay_s
FLOW_FIELDS = 5   # tx, rx, rx_bytes, delay_sum, jitter_sum
RECV_TIMEOUT_MS = 120_000


class Ns3NotAvailable(RuntimeError):
    pass


def availability() -> tuple[bool, str]:
    """Report whether the ns-3 backend can start, with a reason if it cannot."""
    home = os.environ.get("NS3_HOME")
    if not home:
        return False, "NS3_HOME is not set (see docs/NS3_SETUP.md)"
    if not (Path(home) / "ns3").exists():
        return False, f"no ns3 launcher in NS3_HOME={home}"
    if not (Path(home) / "scratch" / "drl-arco" / "drl-arco.cc").exists():
        return False, "scenario not installed (run bash scripts/sync_ns3.sh)"
    try:
        import zmq  # noqa: F401

        from drl_arco.envs.proto import messages_pb2  # noqa: F401
    except ImportError as error:
        return False, f"missing Python dependency: {error}"
    return True, f"ns-3 found at {home}"


class Ns3Backend:
    name = "ns3"

    def __init__(self, cfg: dict[str, Any], topology: Topology, flows: list[Flow],
                 launch: bool = True):
        import zmq

        from drl_arco.envs.proto import messages_pb2 as pb

        self._zmq, self._pb = zmq, pb
        self.topology = topology
        self.flows = flows
        self.cfg = cfg
        self.launch = launch  # False lets tests drive the socket themselves
        self.process: subprocess.Popen | None = None
        self.context: Any = None
        self.socket: Any = None
        self.port = 0
        self.reply_owed = False
        self.finished = False
        self._last: Telemetry | None = None

    def scenario_args(self, seed: int) -> list[str]:
        sim = self.cfg["sim"]
        # One extra step gives the simulator room to finish the last interval.
        duration = (sim["episode_steps"] + 1) * sim["step_s"]
        return [
            f"--openGymPort={self.port}",
            f"--simSeed={seed}",
            f"--simTime={duration:g}",
            f"--stepTime={sim['step_s']:g}",
            f"--packetBytes={sim['packet_bytes']}",
            f"--queuePackets={sim['queue_packets']}",
            f"--links={self.topology.ns3_links_arg()}",
            f"--flows={ns3_flows_arg(self.flows)}",
        ]

    def _start_process(self, seed: int) -> None:
        ready, reason = availability()
        if not ready:
            raise Ns3NotAvailable(reason)
        home = os.environ["NS3_HOME"]
        command = " ".join(["drl-arco", *self.scenario_args(seed)])
        self.process = subprocess.Popen(
            [str(Path(home) / "ns3"), "run", "--no-build", command],
            cwd=home, stdout=subprocess.DEVNULL, start_new_session=True,
        )

    def _recv(self) -> bytes:
        if not self.socket.poll(RECV_TIMEOUT_MS):
            code = self.process.poll() if self.process else None
            raise TimeoutError(f"no message from ns-3 in {RECV_TIMEOUT_MS / 1000:g} s "
                               f"(process exit code: {code})")
        return self.socket.recv()

    def _decode_state(self, payload: bytes) -> Telemetry:
        pb = self._pb
        message = pb.EnvStateMsg()
        message.ParseFromString(payload)
        self.reply_owed = True
        self.finished = message.isGameOver
        if self.finished:
            self._send_stop()
            return self._last

        box = pb.BoxDataContainer()
        message.obsData.data.Unpack(box)
        values = np.asarray(box.floatData, dtype=np.float64)
        n_dir, n_flows = self.topology.n_dir, len(self.flows)
        expected = 1 + n_dir * LINK_FIELDS + n_flows * FLOW_FIELDS
        if values.size != expected:
            raise ValueError(f"ns-3 sent {values.size} values, expected {expected}")
        links = values[1:1 + n_dir * LINK_FIELDS].reshape(n_dir, LINK_FIELDS)
        flows = values[1 + n_dir * LINK_FIELDS:].reshape(n_flows, FLOW_FIELDS)
        self._last = Telemetry(
            float(values[0]), links[:, 0], links[:, 1], links[:, 2], links[:, 3],
            flows[:, 0], flows[:, 1], flows[:, 2], flows[:, 3], flows[:, 4],
        )
        return self._last

    def _send_stop(self) -> None:
        reply = self._pb.EnvActMsg()
        reply.stopSimReq = True
        self.socket.send(reply.SerializeToString())
        self.reply_owed = False

    def bind(self) -> int:
        """Open the listening socket and return its port."""
        zmq = self._zmq
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.port = self.socket.bind_to_random_port("tcp://127.0.0.1", 5001, 10000)
        return self.port

    def reset(self, seed: int) -> Telemetry:
        if self.launch or self.socket is None:
            self.close()
            self.bind()
        if self.launch:
            self._start_process(seed)

        pb = self._pb
        init = pb.SimInitMsg()
        init.ParseFromString(self._recv())
        ack = pb.SimInitAck()
        ack.done = True
        ack.stopSimReq = False
        self.socket.send(ack.SerializeToString())
        self.finished = False
        return self._decode_state(self._recv())

    def step(self, fib: np.ndarray, link_up: np.ndarray, scale: float) -> Telemetry:
        if self.finished:
            return self._last
        pb = self._pb
        box = pb.BoxDataContainer()
        box.dtype = pb.INT
        values = [*(int(v) for v in fib.ravel()), *(int(v) for v in link_up),
                  int(round(scale * 100))]
        box.shape.append(len(values))
        box.intData.extend(values)
        reply = pb.EnvActMsg()
        reply.actData.type = pb.Box
        reply.actData.data.Pack(box)
        reply.stopSimReq = False
        self.socket.send(reply.SerializeToString())
        self.reply_owed = False
        return self._decode_state(self._recv())

    def close(self) -> None:
        if self.socket is not None:
            if self.reply_owed:
                self._send_stop()
            self.socket.close()
            self.context.term()
            self.socket = self.context = None
        if self.process is not None:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, 9)
                self.process.wait()
            self.process = None
