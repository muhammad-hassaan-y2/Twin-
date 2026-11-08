"""Live-experiment plumbing and the tampering demonstration, with the controls
that make them mean something. No network: the model is a canned reply."""
import random

import pytest

from swarm_oversight import tampering
from swarm_oversight.gemini import Gemini
from swarm_oversight.live_experiments import (IDENTITY_SCENARIOS, _first_breach,
                                              _model_partition, _names_and_truth,
                                              pair_scores, run_identity)
from swarm_oversight.monitor import Limits, Monitor
from swarm_oversight.scenarios import (benign, benign_stem, split_distinct,
                                       split_payment, split_renamed)


def test_tamper_none_returns_the_same_log():
    sc = split_payment(3)
    assert tampering.tamper(sc, "none") is sc


def test_every_tamper_mode_cuts_agent_detection_and_leaves_the_gateway_alone():
    rows = {r["mode"]: r for r in tampering.run(range(10))}
    base = rows["none"]
    assert base["agent_detected"] == base["gateway_detected"]
    for mode in ("rename", "drop", "underreport"):
        # the edit has to actually hurt a monitor that reads the published log,
        # or the comparison below proves nothing
        assert rows[mode]["agent_detected"] < base["agent_detected"], mode
        # and it must not touch the gateway, which never reads that log
        assert rows[mode]["gateway_detected"] == base["gateway_detected"], mode
        assert rows[mode]["gateway_settled_frac"] == base["gateway_settled_frac"], mode


def test_rename_actually_fools_the_prefix_rule():
    """The first version of `rename` minted names sharing a stem, which the
    prefix rule merged -- detection went UP. The control: after the edit, no
    two attack payees may share a family."""
    sc = split_payment(7)
    published = tampering.tamper(sc, "rename", seed=7)
    session = Monitor(Limits(merge="prefix")).session()
    keys = [session.payee_key(a.payee) for a in published.actions
            if a.seq in sc.attack and a.kind == "spend"]
    assert len(keys) == len(set(keys))


def test_truth_comes_from_the_scenario_construction():
    names, truth = _names_and_truth(split_renamed(0))
    attack = {a.payee for a in split_renamed(0).actions
              if a.seq in split_renamed(0).attack}
    assert len({truth[n] for n in attack}) == 1
    names, truth = _names_and_truth(benign_stem(0))
    assert len(set(truth.values())) == len(names)  # every stem payee is distinct
    names, truth = _names_and_truth(split_distinct(0))
    assert len(set(truth.values())) == len(names)


def test_pair_scores_notice_a_bad_merger_and_a_blind_one():
    names, truth = _names_and_truth(split_renamed(0))
    perfect = {n: truth[n] for n in names}
    assert pair_scores(perfect, truth)["recall"] == 1.0
    blind = {n: i for i, n in enumerate(names)}
    assert pair_scores(blind, truth)["recall"] == 0.0
    names, truth = _names_and_truth(benign_stem(0))
    merge_all = {n: 0 for n in names}
    assert pair_scores(merge_all, truth)["precision"] == 0.0


def test_model_partition_ignores_names_that_were_not_asked_about():
    part = _model_partition(["a", "b"], {"groups": [["a", "b", "invented"]]})
    assert part["a"] == part["b"]
    assert len(part) == 2


class FakeClient:
    """Merges everything it is shown -- the worst possible identity judge."""
    model = "fake"

    def call(self, user, system="", seed=None, tag=""):
        from swarm_oversight.muse import Reply
        names = [l[2:] for l in user.splitlines() if l.startswith("- ")]
        import json
        return Reply(text=json.dumps({"groups": [names]}))


def test_identity_metrics_expose_the_merge_everything_judge():
    rows = run_identity(range(1), FakeClient())
    stems = next(r for r in rows if r["scenario"] == "benign_stem")
    assert stems["gemini"]["fp"] > 0
    assert stems["tokens"]["fp"] == 0
    renamed = next(r for r in rows if r["scenario"] == "split_renamed")
    assert renamed["gemini"]["recall"] == 1.0
    assert renamed["prefix"]["recall"] == 0.0


def test_first_breach_is_an_attack_payment_and_benign_has_none():
    sc = split_payment(0)
    a, context = _first_breach(sc)
    assert a is not None and a.seq in sc.attack
    assert "Proposed now" in context
    assert _first_breach(benign(0)) == (None, None)


def test_gemini_never_sends_the_seed_the_endpoint_rejects(monkeypatch):
    client = Gemini(api_key="x")
    seen = {}

    def fake_post(path, body):
        seen.update(body)
        return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    monkeypatch.setattr(client, "_post", fake_post)
    client.call("hi", seed=42)
    assert "seed" not in seen


def test_gemini_requires_its_own_env_var(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("SWARM_LLM_API_KEY", "a-muse-key-must-not-be-used")
    with pytest.raises(SystemExit):
        Gemini.from_env()

def test_the_model_arm_matches_the_free_arm_seed_by_seed():
    """The headline negative result, as a paired test: on every scenario and
    seed, the stub model's settled attack money equals the free both-readings
    -hold arm. If a change makes the model genuinely better (or worse) on some
    seed, this fails and the report's claim must be revisited."""
    from swarm_oversight.aicontrol import identity_sweep
    rows = identity_sweep(range(5))
    assert rows
    for r in rows:
        assert r["paired_nonzero"] == 0, r["scenario"]
        assert r["paired_max"] == 0.0, r["scenario"]
