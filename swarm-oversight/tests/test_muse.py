"""The live model client, tested without a network: the two transport seams
are replaced, so every line above them is the code that will really run."""
import json
import tempfile
from pathlib import Path

import pytest

from swarm_oversight.muse import BASE_URL, MODEL, Muse, Reply, cost_usd, first_json


class FakeMuse(Muse):
    """Answers from a queue; records the bodies it was asked to send."""

    def __init__(self, replies=None, events=None, errors=0, **kw):
        super().__init__(**kw)
        self.replies = list(replies or [{"choices": [{"message": {"content": '{"hold": true}'}}],
                                         "usage": {"prompt_tokens": 100,
                                                   "completion_tokens": 20}}])
        self.events = events or []
        self.errors = errors
        self.bodies, self.sse_bodies, self.paths = [], [], []

    def _post(self, path, body):
        if self.errors:
            self.errors -= 1
            raise RuntimeError(f"HTTP 429 from {path}")
        self.paths.append(path)
        self.bodies.append(body)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]

    def _sse(self, path, body):
        self.paths.append(path)
        self.sse_bodies.append(body)
        yield from self.events


def test_point_at_muse_by_default():
    assert BASE_URL == "https://api.meta.ai/v1"
    assert MODEL.startswith("muse-spark")
    m = Muse(api_key="k")
    assert m.base.endswith("/v1") and m.model == MODEL


def test_call_sends_an_openai_shaped_request_and_reads_usage():
    m = FakeMuse(replies=[{"choices": [{"message": {"content": "OK"}}],
                           "usage": {"prompt_tokens": 40, "completion_tokens": 6}}])
    r = m.call("hi", system="be short", seed=3)
    assert r.text == "OK" and (r.in_tokens, r.out_tokens) == (40, 6)
    assert m.paths == ["/chat/completions"]
    assert m.bodies[0]["messages"][0]["role"] == "system"
    assert m.bodies[0]["seed"] == 3
    assert r.cost_usd == pytest.approx(cost_usd(MODEL, 40, 6))


def test_an_endpoint_that_refuses_seed_is_asked_once_without_it(monkeypatch):
    import urllib.error

    sent, ok = [], {"choices": [{"message": {"content": "fine"}}], "usage": {}}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(ok).encode()

    def fake_urlopen(req, timeout=None):
        body = json.loads(req.data)
        sent.append(body)
        if "seed" in body:
            raise urllib.error.HTTPError(req.full_url, 400, "unknown field seed", {}, None)
        return Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    m = Muse(attempts=3)
    assert m.call("q", seed=7).text == "fine"
    assert "seed" in sent[0] and "seed" not in sent[1]   # retried, once, without it


def test_stream_yields_only_the_text_deltas():
    m = FakeMuse(events=[{"type": "response.created"},
                         {"type": "response.output_text.delta", "delta": "get "},
                         {"type": "response.reasoning", "delta": "ignore me"},
                         {"type": "response.output_text.delta", "delta": "paid"},
                         {"type": "response.completed"}])
    assert list(m.stream("plan it", system="s")) == ["get ", "paid"]
    assert m.paths == ["/responses"]
    assert m.sse_bodies[0]["stream"] is True
    assert m.sse_bodies[0]["input"][1]["content"] == "plan it"


def test_cost_is_the_public_preview_table_not_a_guess():
    assert cost_usd("muse-spark-1.3", 1_000_000, 0) == pytest.approx(1.25)
    assert cost_usd("muse-wonder-1.0", 0, 1_000_000) == pytest.approx(20.0)
    assert cost_usd("some-other-model", 5000, 5000) == 0.0


def test_first_json_takes_the_first_object_that_parses():
    assert first_json('noise {"a": 1} {"b": 2}') == {"a": 1}
    assert first_json('```json\n{"hold": false}\n```') == {"hold": False}
    assert first_json("no braces at all") == {}
    assert first_json('{"unbalanced') == {}


def test_total_cost_and_calls_add_up(monkeypatch):
    m = FakeMuse()
    m.trace = None
    for _ in range(3):
        m.call("q")
    assert m.total_calls == 3
    assert m.total_cost == pytest.approx(3 * cost_usd(MODEL, 100, 20))


def test_no_key_means_not_available(monkeypatch):
    for name in ("SWARM_LLM_API_KEY", "META_MODEL_API_KEY", "MUSE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert Muse.available() is False
    monkeypatch.setenv("MUSE_API_KEY", "abc")
    assert Muse.available() is True
    assert Muse.from_env().key == "abc"


def test_trace_file_records_every_call():
    # not pytest's tmp_path: this machine's temp dir denies the fixture setup
    path = Path(tempfile.mkdtemp()) / "calls.jsonl"
    m = FakeMuse(trace=path)
    m.call("question", tag="supervisor")
    row = json.loads(path.read_text(encoding="utf-8").strip())
    assert row["tag"] == "supervisor" and row["prompt"] == "question"
    assert row["model"] == MODEL and set(row) >= {"in_tokens", "cost_usd", "latency_s"}
