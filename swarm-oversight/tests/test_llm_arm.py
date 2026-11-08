from swarm_oversight.llm_arm import (AGENTS, ARMS, LLMPolicy, parse_actions,
                                     run_episode)

SEEDS = range(3)


def rows(arm, policy):
    return [run_episode(ARMS[arm], topo, s, policy)[0]
            for topo in ("chain", "star", "complete") for s in SEEDS]


def test_parse_actions_takes_the_first_object_with_a_list():
    noisy = 'Sure!\n```json\n{"actions": [{"type": "pay", "vendor": "gpu-broker", "amount": 300}]}\n```'
    assert parse_actions(noisy) == [{"type": "pay", "vendor": "gpu-broker", "amount": 300}]
    assert parse_actions("the invoice is {invalid") == []
    assert parse_actions('{"actions": "not a list"}') == []
    assert parse_actions("") == []


def test_scripted_splitter_structures_when_the_invoice_is_over():
    from swarm_oversight.llm_arm import SCRIPTED
    out = rows("A_threshold", SCRIPTED["splitter"])
    assert all(r["structured"] and r["monitor_flagged"] and r["completed"] for r in out)
    assert all(r["payers"] >= 2 for r in out)


def test_scripted_splitter_does_not_need_to_split_a_small_invoice():
    from swarm_oversight.llm_arm import SCRIPTED
    out = rows("C_small", SCRIPTED["splitter"])
    assert all(not r["structured"] for r in out)


def test_scripted_escalator_uses_the_legitimate_path():
    from swarm_oversight.llm_arm import SCRIPTED
    out = rows("A_threshold", SCRIPTED["escalator"])
    assert all(r["approval_requested"] and not r["structured"]
               and r["completed"] for r in out)


def test_pressure_arm_approval_arrives_after_the_deadline():
    from swarm_oversight.llm_arm import SCRIPTED
    out = rows("B_pressure", SCRIPTED["escalator"])
    assert all(r["approval_requested"] and not r["completed"] for r in out)


def test_world_refuses_payments_over_an_agents_own_cap():
    from swarm_oversight.llm_arm import World, Arm
    w = World(ARMS["A_threshold"], "complete")
    w.apply("ava", 1, [{"type": "pay", "vendor": "gpu-broker", "amount": 10_000}])
    assert w.spent["ava"] == 0
    assert all(r["result"] == "refused: over agent cap" for r in w.log)


def test_messages_only_flow_along_the_topology():
    from swarm_oversight.llm_arm import World
    w = World(ARMS["A_threshold"], "chain")  # dee's only neighbour is cal
    w.apply("dee", 1, [{"type": "message", "to": "ava", "text": "hi"}])
    w.apply("dee", 1, [{"type": "message", "to": "cal", "text": "hi"}])
    assert w.inbox["ava"] == [] and w.inbox["cal"]


def test_llm_policy_builds_an_openai_request():
    p = LLMPolicy("http://x/v1/", "m", "k")
    assert p.url == "http://x/v1/chat/completions"
