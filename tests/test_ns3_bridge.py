"""Exercises the Python bridge against a fake simulator using the real wire protocol.

The fake plays the C++ side: a ZeroMQ REQ socket sending real ns3-gym protobuf messages.
This covers the Python half of the bridge; it does not replace running real ns-3.
"""

import threading

import numpy as np
import pytest

zmq = pytest.importorskip("zmq")
pb = pytest.importorskip("drl_arco.envs.proto.messages_pb2")

from drl_arco.config import load_config  # noqa: E402
from drl_arco.envs.ns3_bridge import FLOW_FIELDS, LINK_FIELDS, Ns3Backend  # noqa: E402
from drl_arco.topology import Topology  # noqa: E402
from drl_arco.traffic import load_flows  # noqa: E402


class FakeSimulator(threading.Thread):
    """Sends an init message then `steps` states, recording each action it gets."""

    def __init__(self, port, n_values, steps):
        super().__init__(daemon=True)
        self.port, self.n_values, self.steps = port, n_values, steps
        self.actions = []
        self.stopped_by_agent = False
        self.init_acked = False

    def _state(self, value, over=False):
        box = pb.BoxDataContainer()
        box.dtype = pb.FLOAT
        box.shape.append(self.n_values)
        box.floatData.extend([value] * self.n_values)
        message = pb.EnvStateMsg()
        message.obsData.type = pb.Box
        message.obsData.data.Pack(box)
        message.isGameOver = over
        return message.SerializeToString()

    def run(self):
        context = zmq.Context()
        socket = context.socket(zmq.REQ)
        socket.setsockopt(zmq.LINGER, 0)
        socket.connect(f"tcp://127.0.0.1:{self.port}")
        socket.send(pb.SimInitMsg().SerializeToString())
        ack = pb.SimInitAck()
        ack.ParseFromString(socket.recv())
        self.init_acked = ack.done
        for step in range(self.steps):
            socket.send(self._state(float(step)))
            reply = pb.EnvActMsg()
            reply.ParseFromString(socket.recv())
            if reply.stopSimReq:
                self.stopped_by_agent = True
                break
            action = pb.BoxDataContainer()
            reply.actData.data.Unpack(action)
            self.actions.append(list(action.intData))
        else:
            socket.send(self._state(0.0, over=True))
            socket.recv()
        socket.close()
        context.term()


@pytest.fixture()
def setup():
    cfg = load_config()
    topology = Topology(cfg["topology"])
    flows = load_flows(cfg)
    backend = Ns3Backend(cfg, topology, flows, launch=False)
    n_values = 1 + topology.n_dir * LINK_FIELDS + len(flows) * FLOW_FIELDS
    yield backend, topology, flows, n_values
    backend.close()


def test_exchange_encodes_the_action_and_decodes_the_state(setup):
    backend, topology, flows, n_values = setup
    fake = FakeSimulator(backend.bind(), n_values, steps=5)
    fake.start()
    first = backend.reset(1)
    assert fake.init_acked
    assert first.queue.shape == (topology.n_dir,)
    assert first.flow_tx.shape == (len(flows),)

    fib = topology.spf()
    up = np.ones(topology.n_links, dtype=bool)
    up[3] = False
    second = backend.step(fib, up, 0.8)
    assert second.time_s == 1.0

    action = fake.actions[0]
    assert len(action) == 100 + topology.n_links + 1
    assert action[:100] == [int(v) for v in fib.ravel()]
    assert action[100 + 3] == 0 and action[100] == 1
    assert action[-1] == 80


def test_close_asks_the_simulator_to_stop(setup):
    backend, *_, n_values = setup
    fake = FakeSimulator(backend.bind(), n_values, steps=50)
    fake.start()
    backend.reset(1)
    backend.close()
    fake.join(timeout=5)
    assert fake.stopped_by_agent


def test_simulation_end_is_handled(setup):
    backend, topology, _, n_values = setup
    fake = FakeSimulator(backend.bind(), n_values, steps=2)
    fake.start()
    backend.reset(1)
    fib = topology.spf()
    up = np.ones(topology.n_links, dtype=bool)
    backend.step(fib, up, 1.0)
    backend.step(fib, up, 1.0)  # simulator reports game over here
    assert backend.finished
    assert backend.step(fib, up, 1.0) is not None  # further steps are harmless


def test_wrong_observation_size_is_an_error(setup):
    backend, *_ = setup
    fake = FakeSimulator(backend.bind(), 3, steps=1)
    fake.start()
    with pytest.raises(ValueError, match="expected"):
        backend.reset(1)
    backend.reply_owed = True  # the fake is still waiting for its reply


def test_scenario_args_describe_the_config(setup):
    backend, topology, *_ = setup
    args = backend.scenario_args(4)
    assert "--simSeed=4" in args
    assert f"--links={topology.ns3_links_arg()}" in args
    assert "--simTime=30.1" in args
