"""The model chooses a tool. It cannot compute, spend, or widen a limit."""

from __future__ import annotations

import io
import json

import pytest

from twin.planner.model import (
    MUSE,
    ModelConfig,
    ModelPlanner,
    NumberFabrication,
    number_tokens,
    providers_configured,
    providers_from_env,
)
from twin.planner.rules import RulePlanner
from twin.planner.tools import REGISTRY, ToolError, parse_calls

PROVIDER_VARS = (
    "META_MODEL_BASE_URL", "META_MODEL_API_KEY", "META_MODEL_NAME",
    "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
    "OPENAI_COMPAT_BASE_URL", "OPENAI_COMPAT_API_KEY", "OPENAI_COMPAT_MODEL",
)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Answers like an OpenAI-compatible endpoint would."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.bodies: list[dict] = []
        self.urls: list[str] = []
        self.auth: list[str] = []

    def __call__(self, request, timeout=None):
        self.bodies.append(json.loads(request.data))
        self.urls.append(request.full_url)
        self.auth.append(request.headers.get("Authorization", ""))
        return FakeResponse(json.dumps(self.payload).encode())


@pytest.fixture()
def clean_env(monkeypatch):
    for name in PROVIDER_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def config() -> ModelConfig:
    return ModelConfig(base_url="https://models.example/v1", api_key="not-a-real-key", model="muse-test")


def muse_config() -> ModelConfig:
    return ModelConfig(base_url="https://muse.example/v1", api_key="muse-key",
                       model="llama-4-muse-spark", provider=MUSE)


def tool_reply(name: str, args: dict) -> dict:
    return {"choices": [{"message": {"tool_calls": [{"id": "1", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}


def test_registry_is_exactly_the_five_tools_the_brief_named():
    assert set(REGISTRY) == {"forecast", "fork", "highlight", "propose_action", "quote_rails"}


def test_a_tool_the_twin_does_not_have_is_rejected():
    with pytest.raises(ToolError, match="not a tool"):
        parse_calls([{"name": "execute_payment", "args": {}}])


def test_invented_arguments_are_rejected():
    with pytest.raises(ToolError, match="unknown arguments"):
        parse_calls([{"name": "forecast", "args": {"horizon_days": 90, "runs": 5000, "seed": 7}}])


def test_missing_required_argument_is_rejected():
    with pytest.raises(ToolError, match="missing"):
        parse_calls([{"name": "fork", "args": {"cancel_event_ids": ["sub-adobe"]}}])


def test_a_model_cannot_ask_to_spend_directly():
    assert not any("pay" in name or "spend" in name or "approve" in name for name in REGISTRY)


def test_model_plan_routes_through_the_same_validator():
    opener = FakeOpener(tool_reply("fork", {"label": "cancel the print club", "cancel_event_ids": ["sub-plates"]}))
    planner = ModelPlanner(config(), opener=opener)
    calls = planner.plan("drop the print club", {"horizon_days": 90, "events": []})
    assert calls[0].tool == "fork"
    assert "tools" in opener.bodies[0]
    assert {t["function"]["name"] for t in opener.bodies[0]["tools"]} == set(REGISTRY)
    assert planner.last_route == "openai-compatible:muse-test"
    assert opener.urls[0] == "https://models.example/v1/chat/completions"
    assert opener.auth[0] == "Bearer not-a-real-key"


def test_an_unreachable_model_falls_back_to_rules():
    def explode(request, timeout=None):
        raise OSError("no network")

    planner = ModelPlanner(config(), opener=explode)
    calls = planner.plan("will I run out by day 40", {"horizon_days": 90, "chasable": [], "cancellable": []})
    assert calls and calls[0].tool == "forecast"
    assert planner.last_route.startswith("rules")


def test_a_model_that_returns_nothing_falls_back_to_rules():
    planner = ModelPlanner(config(), opener=FakeOpener({"choices": [{"message": {"content": "I think you should be careful"}}]}))
    calls = planner.plan("what about the print club", {"horizon_days": 90, "cancellable": [], "chasable": []})
    assert calls[0].tool == "forecast"
    assert planner.last_route.startswith("rules")


def test_narration_that_invents_a_number_is_refused():
    given = number_tokens('{"median_low_dollars": 255.0, "pinch_day": 77}')
    with pytest.raises(NumberFabrication):
        ModelPlanner.assert_numbers_are_given("You are about 4,200 dollars short by Friday.", given)


def test_the_old_loophole_of_small_digit_words_is_closed():
    given = number_tokens('{"pinch_day": 77}')
    with pytest.raises(NumberFabrication):
        ModelPlanner.assert_numbers_are_given("There are 3 things to fix.", given)


def test_narration_reusing_given_numbers_passes():
    given = number_tokens('{"median_low_dollars": 255.0, "runs": 2000, "pinch_day": 77}')
    ModelPlanner.assert_numbers_are_given("The floor is 255 dollars at day 77 across 2,000 runs.", given)


def test_rule_planner_always_starts_from_the_numbers():
    for intent in ("hi", "chase northwind", "what if I cancel adobe", "show me day 40"):
        calls = RulePlanner().plan(intent, {"horizon_days": 90, "chasable": [], "cancellable": []})
        assert calls[0].tool == "forecast", intent


def test_rule_planner_recognises_a_pipe_by_its_words():
    context = {
        "horizon_days": 90,
        "cancellable": [{"id": "sub-plates", "label": "Print club box"}],
        "chasable": [{"id": "inv-northwind", "label": "Northwind mural"}],
    }
    cancel = RulePlanner().plan("should I cancel the print club box?", context)
    assert any(c.tool == "fork" and c.args.get("cancel_event_ids") == ["sub-plates"] for c in cancel)
    chase = RulePlanner().plan("northwind still has not paid", context)
    assert any(c.tool == "fork" and c.args.get("chase_event_ids") == ["inv-northwind"] for c in chase)


def test_rule_planner_does_not_duplicate_the_same_fork():
    context = {"horizon_days": 90, "cancellable": [{"id": "sub-plates", "label": "Print club box"}], "chasable": []}
    calls = RulePlanner().plan("what if I cancel the print club box", context)
    forks = [c for c in calls if c.tool == "fork"]
    assert len(forks) == 1


def test_narration_never_claims_a_clean_run_sheet_when_some_runs_go_under():
    results = [{"forecast": {"pinch_day": 77, "shortfall_day": None, "median_low_dollars": 255.0, "dry_run_percent": 27, "runs": 2000}}]
    said = RulePlanner().narrate("", results)
    assert "27" in said and "under" in said
    assert "stay above water across all" not in said


# ------------------------------------------------------------- the provider paths


def test_muse_is_chosen_and_named_when_both_endpoints_are_configured(clean_env):
    clean_env.setenv("META_MODEL_BASE_URL", "https://muse.example/v1")
    clean_env.setenv("META_MODEL_API_KEY", "muse-key")
    clean_env.setenv("META_MODEL_NAME", "llama-4-muse-spark")
    clean_env.setenv("LLM_BASE_URL", "https://other.example/v1")
    clean_env.setenv("LLM_API_KEY", "other-key")
    clean_env.setenv("LLM_MODEL", "some-claude")
    planner = ModelPlanner.from_env()
    assert planner.provider == MUSE
    assert providers_configured() == [MUSE, "openai-compatible"]

    opener = FakeOpener(tool_reply("forecast", {"horizon_days": 90}))
    planner = ModelPlanner(planner.config, opener=opener)
    planner.plan("will the river hold", {"horizon_days": 90, "events": []})
    assert planner.last_route == "muse:llama-4-muse-spark"
    assert opener.urls == ["https://muse.example/v1/chat/completions"]
    assert opener.auth == ["Bearer muse-key"]


def test_the_generic_endpoint_is_used_when_muse_is_absent(clean_env):
    clean_env.setenv("LLM_BASE_URL", "https://other.example/v1/")
    clean_env.setenv("LLM_API_KEY", "other-key")
    clean_env.setenv("LLM_MODEL", "some-claude")
    planner = ModelPlanner.from_env()
    assert planner.provider == "openai-compatible"
    assert planner.config.base_url == "https://other.example/v1"


def test_an_endpoint_with_nothing_in_the_environment_is_no_endpoint_at_all(clean_env):
    assert providers_from_env() == []
    assert ModelPlanner.from_env() is None


def test_a_half_configured_endpoint_is_not_silently_tried(clean_env):
    clean_env.setenv("META_MODEL_BASE_URL", "https://muse.example/v1")
    clean_env.setenv("META_MODEL_API_KEY", "muse-key")  # no model name
    assert providers_configured() == []
    assert ModelPlanner.from_env() is None


def test_the_provider_list_never_carries_a_key(clean_env):
    clean_env.setenv("META_MODEL_BASE_URL", "https://muse.example/v1")
    clean_env.setenv("META_MODEL_API_KEY", "super-secret-value")
    clean_env.setenv("META_MODEL_NAME", "llama-4-muse-spark")
    assert providers_configured() == [MUSE]
    assert not any("super-secret" in str(name) for name in providers_configured())


def test_a_muse_reply_that_invents_numbers_is_still_refused_in_favour_of_rules():
    results = [{"forecast": {"pinch_day": 77, "shortfall_day": None, "median_low_dollars": 255.0,
                             "dry_run_percent": 12, "runs": 2000}}]
    opener = FakeOpener({"choices": [{"message": {"content": "You will need about 9,000 dollars by Friday."}}]})
    planner = ModelPlanner(muse_config(), opener=opener)
    said = planner.narrate("what now", results)
    assert planner.last_route == "rules (narration fell back)"
    assert "9,000" not in said and "255" in said
