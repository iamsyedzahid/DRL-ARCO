"""Dashboard API behavior, using Flask's test client."""

import copy
import time

import pytest

pytest.importorskip("flask")
pytest.importorskip("torch")

from drl_arco.config import load_config  # noqa: E402
from drl_arco.gui import server  # noqa: E402


@pytest.fixture()
def app():
    cfg = copy.deepcopy(load_config())
    cfg["sim"]["episode_steps"] = 2000
    application = server.create_app(cfg)
    application.dashboard.steps_per_second = 100
    yield application
    application.dashboard.stop()
    thread = application.dashboard.thread
    if thread:
        thread.join(timeout=5)


def wait_for(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_config_describes_the_ten_node_network(app):
    data = app.test_client().get("/api/config").get_json()
    assert len(data["nodes"]) == 10
    assert len(data["links"]) == 16
    assert data["backends"]["surrogate"]["ready"] is True
    assert "bursty" in data["scenarios"]


def test_page_and_assets_are_served(app):
    client = app.test_client()
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/../server.py").status_code == 404


def test_rejects_bad_requests(app):
    client = app.test_client()
    bad = {"scenario": "nope", "policy": "dijkstra"}
    assert client.post("/api/run/start", json=bad).status_code == 400
    bad_policy = {"scenario": "light", "policy": "x"}
    assert client.post("/api/run/start", json=bad_policy).status_code == 400
    assert client.post("/api/run/link", json={"link": 99, "up": False}).status_code == 400
    assert client.post("/api/run/scale", json={"scale": 50}).status_code == 400
    assert client.get("/api/benchmark/latest?backend=../../x").status_code == 400


def test_ns3_request_without_ns3_explains_why(app, monkeypatch):
    monkeypatch.setattr(server, "availability", lambda: (False, "NS3_HOME is not set"))
    response = app.test_client().post(
        "/api/run/start", json={"scenario": "light", "policy": "dijkstra", "backend": "ns3"})
    assert response.status_code == 400
    assert "NS3_HOME" in response.get_json()["message"]


def test_run_streams_frames_and_applies_controls(app):
    dashboard = app.dashboard
    subscriber = dashboard.subscribe()
    client = app.test_client()
    assert client.post("/api/run/start",
                       json={"scenario": "light", "policy": "dijkstra"}).status_code == 200
    assert wait_for(lambda: dashboard.env is not None)
    # Only one job may run at a time.
    assert client.post("/api/run/start",
                       json={"scenario": "light", "policy": "dijkstra"}).status_code == 409

    assert client.post("/api/run/link", json={"link": 7, "up": False}).status_code == 200
    assert wait_for(lambda: dashboard.env is not None and dashboard.env.link_failed[7])

    assert client.post("/api/run/node", json={"node": 5, "up": False}).status_code == 200
    assert wait_for(lambda: dashboard.env is not None and dashboard.env.node_failed[5])

    assert client.post("/api/run/scale", json={"scale": 1.5}).status_code == 200
    assert wait_for(lambda: dashboard.env is not None and dashboard.env.scale == 1.5)

    client.post("/api/stop")
    assert wait_for(lambda: dashboard.job is None)
    messages = []
    while not subscriber.empty():
        messages.append(subscriber.get())
    assert any(m.startswith("event: frame") for m in messages)
    assert any('"state": "stopped"' in m for m in messages)
    dashboard.unsubscribe(subscriber)


def test_job_error_reaches_the_browser(app, monkeypatch):
    dashboard = app.dashboard
    subscriber = dashboard.subscribe()

    def explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(server, "make_env", explode)
    app.test_client().post("/api/run/start", json={"scenario": "light", "policy": "dijkstra"})
    assert wait_for(lambda: dashboard.job is None)
    messages = []
    while not subscriber.empty():
        messages.append(subscriber.get())
    assert any('"state": "error"' in m and "boom" in m for m in messages)
    dashboard.unsubscribe(subscriber)
