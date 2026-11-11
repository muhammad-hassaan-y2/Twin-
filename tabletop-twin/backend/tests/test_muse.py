"""The Muse route driven over a real socket by a gateway that answers like Meta's.

No credential of the user's is involved: the key here is a string in a test and the
endpoint is a process on localhost. What is being proved is Meta's own API surface —
``/v1/responses`` first, ``/chat/completions`` as the compatible fallback — and the
failure semantics around it: a bearer header, a refusal that is not asked twice, a
rate limit that names a wait, parallel tool calls in one reply, and a stream whose
sentences are each checked before any of them is shown.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from fake_muse import CHAT_PATH, MODEL, RESPONSES_PATH, FakeMuse, read_sse
from twin.api import main
from twin.planner.muse import function_calls, text_of
from twin.planner.model import (
    CHAT,
    MUSE,
    MUSE_BASE_URL,
    MUSE_MODEL,
    RESPONSES,
    ModelConfig,
    ModelPlanner,
    number_tokens,
    providers_from_env,
    route_details,
    safe_release,
)
from twin.planner.tools import REGISTRY
from twin.store import drop_schema, schema_name
from twin.world.session import Session

CONTEXT = {"horizon_days": 90, "events": [], "chasable": [], "cancellable": []}

FACTS = [{"forecast": {"pinch_day": 77, "shortfall_day": None, "median_low_dollars": 255.0,
                       "dry_run_percent": 12, "runs": 2000}}]


@pytest.fixture()
def muse(monkeypatch):
    """A live gateway, plus an environment that points exactly one endpoint at it."""
    for name in ("META_MODEL_BASE_URL", "META_MODEL_API_KEY", "META_MODEL_NAME", "MODEL_API_KEY",
                 "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
                 "OPENAI_COMPAT_BASE_URL", "OPENAI_COMPAT_API_KEY", "OPENAI_COMPAT_MODEL"):
        monkeypatch.delenv(name, raising=False)
    fake = FakeMuse()
    base = fake.start()
    monkeypatch.setenv("MODEL_API_KEY", "muse-key")
    monkeypatch.setenv("META_MODEL_BASE_URL", base)
    try:
        yield fake
    finally:
        fake.stop()


def stopwatch(planner: ModelPlanner) -> tuple[ModelPlanner, list]:
    """The same endpoint and the same credential provenance, but a recorder instead of a wait."""
    sleeps: list[float] = []
    return ModelPlanner(planner.config, sleeper=sleeps.append), sleeps


def spoken(sentences: list[str]) -> str:
    return "".join(sentences)


# ---------------------------------------------------------------- the two shapes


def test_a_key_and_the_published_defaults_are_the_whole_configuration(muse):
    planner = ModelPlanner.from_env()
    assert planner.provider == MUSE
    assert planner.config.model == MODEL
    assert planner.config.api == RESPONSES
    assert planner.config.base_url == muse.url
    # Before anyone has been asked anything, the route is still an intention.
    assert planner.last_route == ""
    assert planner.route == f"muse:{MODEL}"


def test_planning_goes_to_the_agentic_endpoint_with_metas_field_names(muse):
    muse.responses_tool(("forecast", {"horizon_days": 90}))
    planner = ModelPlanner.from_env()
    calls = planner.plan("will the river hold", CONTEXT)
    assert [c.tool for c in calls] == ["forecast"]
    assert muse.paths == [f"POST {RESPONSES_PATH}"]
    assert muse.headers[0]["authorization"] == "Bearer muse-key"
    body = muse.last_body
    assert body["input"] == "will the river hold"
    assert "instructions" in body and "messages" not in body
    assert body["tool_choice"] == "auto"
    assert body["parallel_tool_calls"] is True
    assert body["max_output_tokens"] == 512
    assert "stream" not in body
    # Meta's responses shape declares a function flat, not nested under "function".
    assert {t["name"] for t in body["tools"]} == set(REGISTRY)
    assert all(t["type"] == "function" and "function" not in t for t in body["tools"])
    assert planner.last_route == f"muse:{MODEL}"


def test_one_reply_can_ask_for_several_tools_at_once(muse):
    muse.responses_tool(("forecast", {"horizon_days": 90}), ("highlight", {"target": "driest"}))
    calls = ModelPlanner.from_env().plan("where does it hurt most", CONTEXT)
    assert [c.tool for c in calls] == ["forecast", "highlight"]
    assert muse.calls == 1


def test_a_function_call_the_twin_has_not_got_is_refused_before_it_runs(muse):
    muse.responses_tool(("execute_payment", {"amount_cents": 5000}))
    planner = ModelPlanner.from_env()
    calls = planner.plan("just pay the studio", CONTEXT)
    assert calls[0].tool == "forecast"
    assert planner.last_route.startswith("rules (")
    assert "not a tool" in planner.last_route


def test_a_gateway_that_refuses_the_responses_shape_is_asked_in_the_compatible_one(muse):
    muse.refuse(400, detail="tools: unsupported definition shape")
    muse.tool("fork", {"label": "cancel the print club", "cancel_event_ids": ["sub-plates"]})
    planner = ModelPlanner.from_env()
    calls = planner.plan("drop the print club", CONTEXT)
    assert [c.tool for c in calls] == ["fork"]
    assert muse.paths == [f"POST {RESPONSES_PATH}", f"POST {CHAT_PATH}"]
    assert {t["function"]["name"] for t in muse.last_body["tools"]} == set(REGISTRY)
    assert planner.last_route == f"muse:{MODEL} via {CHAT}"


def test_a_gateway_that_refuses_the_first_answer_is_not_asked_in_both_shapes_at_once(muse):
    # 401 is a judgement about the credential, so a second shape would only spend more.
    muse.refuse(401, detail="Invalid API key provided")
    planner = ModelPlanner.from_env()
    planner.plan("will the river hold", CONTEXT)
    assert muse.calls == 1


def test_the_generic_route_is_asked_in_the_only_shape_it_promises(monkeypatch):
    for name in ("META_MODEL_BASE_URL", "META_MODEL_API_KEY", "META_MODEL_NAME", "MODEL_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "https://models.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "some-claude")
    config = providers_from_env()[0]
    assert config.api == CHAT
    assert config.endpoints() == [CHAT]


def test_the_catalogue_decides_the_shape_a_model_is_asked_in(monkeypatch):
    monkeypatch.setenv("META_MODEL_API_KEY", "k")
    monkeypatch.setenv("META_MODEL_NAME", "muse-wonder-1.0")
    assert providers_from_env()[0].endpoints() == [RESPONSES, CHAT]
    monkeypatch.setenv("META_MODEL_BASE_URL", "https://muse.example/v1")
    assert providers_from_env()[0].endpoints() == [RESPONSES, CHAT]


def test_a_model_published_for_images_is_never_asked_to_run_the_table(muse):
    config = ModelConfig(base_url=muse.url, api_key="muse-key", model="muse-image-1.0",
                         provider=MUSE, api=RESPONSES, supplied={"api_key": "MODEL_API_KEY"})
    planner = ModelPlanner(config)
    calls = planner.plan("will the river hold", CONTEXT)
    assert calls[0].tool == "forecast"
    assert muse.calls == 0
    assert "images" in planner.last_route
    assert "writing text" in planner.last_route


def test_a_model_name_the_catalogue_has_never_heard_of_is_still_tried(muse):
    # An unchecked map refuses nothing: a model Meta published after this code was
    # written is not a reason to stop answering.
    config = ModelConfig(base_url=muse.url, api_key="muse-key", model="muse-spark-9.9",
                         provider=MUSE, api=RESPONSES, supplied={"api_key": "MODEL_API_KEY"})
    muse.refuse(400, detail="no such model")
    muse.tool("forecast", {})
    planner = ModelPlanner(config)
    planner.plan("will the river hold", CONTEXT)
    assert muse.calls == 2


# --------------------------------------------------------------------- streaming


def test_narration_arrives_one_verified_sentence_at_a_time(muse):
    muse.stream("The floor is 255 dollars.", " Day 77 is the pinch.")
    seen: list[str] = []
    planner = ModelPlanner.from_env()
    said = planner.narrate("what now", FACTS, on_delta=seen.append)
    assert seen == ["The floor is 255 dollars.", " Day 77 is the pinch."]
    assert said == spoken(seen)
    assert muse.paths == [f"POST {RESPONSES_PATH}"]
    assert muse.last_body["stream"] is True
    assert muse.last_body["max_output_tokens"] == 160
    assert "FACTS" in json.dumps(muse.last_body["input"])
    assert planner.last_route == f"muse:{MODEL}"


def test_a_sentence_is_held_until_its_number_is_finished(muse):
    # "25" and "5" are one figure until the sentence carrying it is complete, so
    # nothing is spoken until the period arrives.
    muse.stream("The median floor is 25", "5 dollars over 2,000 runs.")
    seen: list[str] = []
    planner = ModelPlanner.from_env()
    said = planner.narrate("what now", FACTS, on_delta=seen.append)
    assert seen == ["The median floor is 255 dollars over 2,000 runs."]
    assert said == "The median floor is 255 dollars over 2,000 runs."
    assert planner.last_route == f"muse:{MODEL}"


def test_a_stream_that_invents_a_figure_freezes_the_caption_and_is_replaced(muse):
    muse.stream("The floor is 255 dollars.", " You need 9,000 more by Friday.")
    seen: list[str] = []
    planner = ModelPlanner.from_env()
    said = planner.narrate("what now", FACTS, on_delta=seen.append)
    assert seen == ["The floor is 255 dollars."]
    assert "9,000" not in said and "9000" not in said
    assert "255" in said
    assert planner.last_route.startswith("rules (narration fell back")
    assert "9000" in planner.last_route


def test_the_finished_reply_is_what_gets_checked_not_the_fragments(muse):
    muse.stream("The floor is 255 dollars.", final="The floor is 300 dollars.")
    seen: list[str] = []
    planner = ModelPlanner.from_env()
    planner.narrate("what now", FACTS, on_delta=seen.append)
    assert seen == ["The floor is 255 dollars."]
    assert planner.last_route.startswith("rules (narration fell back")


def test_a_stream_with_no_words_in_it_counts_as_no_answer(muse):
    muse.stream()
    planner = ModelPlanner.from_env()
    said = planner.narrate("what now", FACTS)
    assert said and planner.last_route.startswith("rules (")


def test_safe_release_only_hands_over_whole_trusted_sentences():
    given = number_tokens('{"median_low_dollars": 255.0, "pinch_day": 77}')
    release, safe = safe_release("The floor is 255 dollars at day 77", given)
    assert release == "" and safe is True
    release, safe = safe_release("The floor is 255 dollars.", given)
    assert release == "The floor is 255 dollars." and safe is True
    release, safe = safe_release("The floor is 255 dollars. It is 9,000 short.", given)
    assert release == "The floor is 255 dollars." and safe is False


# --------------------------------------------------------------- failure meanings


def test_the_wire_carries_the_bearer_key_and_the_tool_catalogue(muse):
    muse.responses_tool(("forecast", {"horizon_days": 90}))
    planner = ModelPlanner.from_env()
    calls = planner.plan("will the river hold", CONTEXT)
    assert [c.tool for c in calls] == ["forecast"]
    assert muse.tools_asked_for == set(REGISTRY)
    assert muse.last_body["model"] == MODEL


def test_a_refused_credential_is_not_asked_twice(muse):
    muse.refuse(401, detail="Invalid API key provided")
    planner = ModelPlanner.from_env()
    calls = planner.plan("will the river hold", CONTEXT)
    assert calls[0].tool == "forecast"
    assert muse.calls == 1
    assert "401" in planner.last_route
    # It says which variable was wrong without repeating what was in it.
    assert "MODEL_API_KEY" in planner.last_route
    assert "muse-key" not in planner.last_route


def test_a_wrong_key_value_is_refused_on_the_wire(muse):
    config = ModelConfig(base_url=muse.url, api_key="the-wrong-one", model=MODEL, provider=MUSE,
                         api=RESPONSES, supplied={"api_key": "META_MODEL_API_KEY"})
    planner = ModelPlanner(config)
    planner.plan("will the river hold", CONTEXT)
    assert muse.calls == 1
    assert muse.rejected == ["Bearer the-wrong-one"]
    assert "401" in planner.last_route


def test_a_rate_limit_waits_the_pause_it_asked_for_and_asks_once_more(muse):
    muse.refuse(429, detail="Too many requests", retry_after="0.75")
    muse.responses_tool(("highlight", {"target": "driest"}))
    planner, sleeps = stopwatch(ModelPlanner.from_env())
    calls = planner.plan("where does it hurt most", CONTEXT)
    assert [c.tool for c in calls] == ["highlight"]
    assert sleeps == [0.75]
    assert muse.calls == 2
    assert planner.last_route == f"muse:{MODEL}"


def test_a_wait_that_would_block_the_table_is_capped(muse):
    muse.refuse(429, retry_after="3600")
    muse.responses_tool(("forecast", {}))
    config = ModelConfig(base_url=muse.url, api_key="muse-key", model=MODEL, provider=MUSE,
                         api=RESPONSES, max_retry_sec=0.25, supplied={"api_key": "MODEL_API_KEY"})
    planner, sleeps = stopwatch(ModelPlanner(config))
    planner.plan("will the river hold", CONTEXT)
    assert sleeps == [0.25]


def test_a_rate_limit_that_survives_the_repair_attempt_falls_back_to_rules(muse):
    muse.refuse(429, detail="Too many requests", retry_after="0", times=2)
    planner, _ = stopwatch(ModelPlanner.from_env())
    calls = planner.plan("will the river hold", CONTEXT)
    assert calls[0].tool == "forecast"
    assert muse.calls == 2
    assert "asked twice" in planner.last_route
    assert planner.last_route.startswith("rules (HTTP 429")


def test_an_overloaded_gateway_is_given_one_more_attempt(muse):
    muse.refuse(503, detail="gateway is overloaded")
    muse.responses_narration("The floor is 255 dollars at day 77 across 2,000 runs.")
    planner, _ = stopwatch(ModelPlanner.from_env())
    said = planner.narrate("what now", FACTS)
    assert "255" in said
    assert muse.calls == 2
    assert planner.last_route == f"muse:{MODEL}"


def test_an_answer_that_is_not_json_never_becomes_a_number(muse):
    muse.gibberish(text="<html>502 Bad Gateway</html>")
    planner = ModelPlanner.from_env()
    calls = planner.plan("will the river hold", CONTEXT)
    assert calls[0].tool == "forecast"
    assert "not JSON" in planner.last_route
    assert "502" not in planner.last_route


def test_a_gateway_that_hangs_up_after_the_work_is_reported_as_unreachable(muse):
    muse.silence()
    planner = ModelPlanner.from_env()
    calls = planner.plan("will the river hold", CONTEXT)
    assert calls[0].tool == "forecast"
    assert muse.host in planner.last_route
    assert "did not answer" in planner.last_route


def test_a_model_name_that_does_not_exist_is_asked_in_each_shape_once(muse):
    # A 404 is read as "this shape is not here", so the other shape is tried — but the
    # asking stops after the two of them, and the name nobody recognises is spoken.
    config = ModelConfig(base_url=muse.url, api_key="muse-key", model="muse-imagined-9",
                         provider=MUSE, api=RESPONSES,
                         supplied={"api_key": "MODEL_API_KEY", "model": "META_MODEL_NAME"})
    planner = ModelPlanner(config)
    calls = planner.plan("will the river hold", CONTEXT)
    assert muse.paths == [f"POST {RESPONSES_PATH}", f"POST {CHAT_PATH}"]
    assert muse.calls == 2
    assert calls[0].tool == "forecast"
    assert "muse-imagined-9" in planner.last_route
    assert planner.last_route.startswith("rules (")


def test_narration_that_only_repeats_computed_numbers_is_kept(muse):
    muse.responses_narration("The floor is 255 dollars at day 77 across 2,000 runs.")
    planner = ModelPlanner.from_env()
    said = planner.narrate("what now", FACTS)
    assert said.startswith("The floor is 255")
    assert planner.last_route == f"muse:{MODEL}"


def test_narration_that_invents_a_dollar_figure_is_rejected_on_the_wire(muse):
    muse.responses_narration("You will need about 9,000 dollars by Friday.")
    planner = ModelPlanner.from_env()
    said = planner.narrate("what now", FACTS)
    assert "9,000" not in said and "9000" not in said
    assert "255" in said
    assert "9000" in planner.last_route
    assert planner.last_route.startswith("rules (narration fell back")


def test_a_fact_block_reaches_the_model_as_written_numbers(muse):
    muse.responses_narration("The floor is 255 dollars at day 77 across 2,000 runs.")
    ModelPlanner.from_env().narrate("what now", FACTS)
    prompt = json.dumps(muse.last_body)
    assert "255.0" in prompt and "pinch_day" in prompt
    assert "9000" not in prompt


def test_a_model_that_chooses_the_tool_but_not_the_words_is_reported_as_both(muse):
    muse.responses_tool(("forecast", {"horizon_days": 90}))
    muse.responses_narration("You will need about 9,000 dollars by Friday.")
    answer = Session.build().ask("will the river hold")
    # Two steps, possibly two routes: recording only the last would hide that Muse
    # chose the tool, and recording only the first would claim words it never said.
    assert answer["route"] == f"muse:{MODEL}"
    assert answer["narration_route"].startswith("rules (narration fell back")
    assert "9,000" not in answer["said"] and "255" in answer["said"]
    assert answer["calls"] == ["forecast"]


def test_a_world_streams_the_pieces_as_the_model_phrases_them(muse):
    muse.responses_tool(("forecast", {"horizon_days": 90}))
    muse.stream("The river holds. ", "The pinch is close.")
    pieces: list[str] = []
    answer = Session.build().ask("will the river hold", on_delta=pieces.append)
    # One piece per finished sentence: a clause is not shown until its number, if any,
    # has arrived and been checked.
    assert len(pieces) == 2
    assert spoken(pieces) == answer["said"] == "The river holds. The pinch is close."
    assert answer["narration_route"] == f"muse:{MODEL}"


def test_a_stream_frozen_mid_sentence_leaves_the_world_a_verified_line(muse):
    muse.responses_tool(("forecast", {"horizon_days": 90}))
    muse.stream("The river holds. ", "You need 9,000 more by Friday.")
    pieces: list[str] = []
    answer = Session.build().ask("will the river hold", on_delta=pieces.append)
    # The safe sentence was shown while it arrived; the invented one never was, and what
    # the world writes down is the rule planner's sentence instead of the remainder.
    assert spoken(pieces).strip() == "The river holds."
    assert "9,000" not in answer["said"] and "9000" not in answer["said"]
    assert answer["narration_route"].startswith("rules (narration fell back")


# ----------------------------------------------------------------- over the wire


@pytest.fixture()
def table(muse, monkeypatch):
    """The same gateway with an HTTP edge in front of it, and an account to speak for."""
    name = schema_name()
    monkeypatch.setenv("TWIN_DB_SCHEMA", name)
    main.reset_state()
    client = TestClient(main.app)
    made = client.post("/v1/signup", json={"email": "ada@acme.io", "name": "Ada",
                                          "password": "tabletop-2026"})
    try:
        yield client, {"Authorization": f"Bearer {made.json()['token']}"}
    finally:
        main.reset_state()
        drop_schema(name)


def streamed(client, bearer: dict, intent: str) -> list[tuple[str, dict]]:
    with client.stream("POST", "/v1/ask/stream", headers=bearer, json={"intent": intent}) as reply:
        assert reply.status_code == 200
        assert reply.headers["content-type"].startswith("text/event-stream")
        return read_sse(reply.iter_lines())


def test_muse_narration_reaches_the_panel_in_pieces_not_all_at_once(table, muse):
    muse.responses_tool(("forecast", {"horizon_days": 90}))
    muse.stream("The river holds. ", "The pinch is close.")
    frames = streamed(*table, "will I run out by day 40")
    assert [name for name, _ in frames] == ["delta", "delta", "done"]
    deltas = [payload["text"] for name, payload in frames if name == "delta"]
    said = frames[-1][1]["said"]
    # The table sees two arrivals that add up to the one sentence the world kept.
    assert len(deltas) == 2 and "".join(deltas) == said
    assert frames[-1][1]["narration_route"] == f"muse:{MODEL}"


def test_a_frozen_stream_on_the_wire_ends_with_a_sentence_that_was_checked(table, muse):
    muse.responses_tool(("forecast", {"horizon_days": 90}))
    muse.stream("The river holds. ", "You need 9,000 more by Friday.")
    frames = streamed(*table, "will I run out by day 40")
    assert [name for name, _ in frames] == ["delta", "done"]
    said = frames[-1][1]["said"]
    assert "9,000" not in said and "9000" not in said
    assert frames[-1][1]["narration_route"].startswith("rules (narration fell back")


# ------------------------------------------------------------------- the report


def test_the_route_is_described_without_a_single_request(muse):
    [route] = route_details()
    assert route["provider"] == MUSE
    assert route["model"] == MODEL
    assert route["api"] == RESPONSES
    assert route["api_alternatives"] == [RESPONSES, CHAT]
    assert route["host"] == muse.host
    assert route["endpoint"] == f"{muse.url}/responses"
    assert route["supplied_by"] == {"api_key": "MODEL_API_KEY", "base_url": "META_MODEL_BASE_URL", "model": ""}
    assert route["assumed"] == ["model"]
    assert route["preferred"] is True
    assert route["catalogue"]["published"] is True
    assert route["unusable"] == ""
    # Saying this cost nothing: the gateway that could answer it was never called.
    assert muse.calls == 0
    assert "muse-key" not in json.dumps(route)


def test_the_generic_endpoint_is_still_offered_beside_muse(muse, monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://other.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "other-key")
    monkeypatch.setenv("LLM_MODEL", "some-claude")
    routes = route_details()
    assert [r["provider"] for r in routes] == [MUSE, "openai-compatible"]
    assert [r["preferred"] for r in routes] == [True, False]
    assert routes[1]["host"] == "other.example"
    assert routes[1]["api"] == CHAT
    assert routes[1]["catalogue"]["published"] is False


def test_muse_is_reachable_by_its_published_defaults_alone(monkeypatch):
    for name in ("META_MODEL_BASE_URL", "META_MODEL_API_KEY", "META_MODEL_NAME", "MODEL_API_KEY",
                 "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
                 "OPENAI_COMPAT_BASE_URL", "OPENAI_COMPAT_API_KEY", "OPENAI_COMPAT_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MODEL_API_KEY", "someone-elses-key")
    [route] = route_details()
    assert route["host"] == "api.meta.ai"
    assert route["endpoint"] == f"{MUSE_BASE_URL}/responses"
    assert route["model"] == MUSE_MODEL


def test_a_responses_reply_with_no_function_call_reads_as_empty():
    """`choices` is a chat field, so a responses payload has none and must never be indexed blindly.

    This crashed the first time a Muse reply arrived as prose instead of a tool call, which is
    ordinary behaviour when `tool_choice` is only "auto".
    """
    assert function_calls({"output": []}) == []
    assert text_of({"output": [{"type": "message",
                                "content": [{"type": "output_text", "text": "hello"}]}]}) == "hello"
    assert text_of({"output": []}) == ""
    assert function_calls({"output": [{"type": "message", "content": "words"}]}) == []
