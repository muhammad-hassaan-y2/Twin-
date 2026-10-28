"""The client draws what was computed, and nothing else."""

from __future__ import annotations

from twin.world.scene import PALETTE, scene_payload
from twin.world.session import Session


def scene():
    return scene_payload(Session.build(use_model=False))


def test_the_river_is_one_value_per_day():
    payload = scene()
    river = payload["river"]
    horizon = payload["meta"]["horizon_days"]
    assert len(river["p10_dollars"]) == len(river["p50_dollars"]) == len(river["p90_dollars"]) == horizon
    assert len(river["dry_probability"]) == horizon
    assert 0 <= river["pinch_day"] < horizon


def test_only_outgoing_money_becomes_a_stone():
    session = Session.build(use_model=False)
    inbound = {e.id for e in session.ledger.events if e.direction.value == "in"}
    stones = scene_payload(session)["stones"]
    assert stones
    assert not {s["event_id"] for s in stones} & inbound


def test_a_recurring_bill_becomes_one_stone_per_occurrence():
    stones = scene()["stones"]
    assert sum(1 for s in stones if s["event_id"] == "bill-rent") == 3


def test_stone_heights_are_relative_and_never_negative():
    stones = scene()["stones"]
    assert all(0 <= s["height"] <= 0.14 for s in stones)
    tallest = max(stones, key=lambda s: s["height"])
    assert tallest["amount_dollars"] == max(s["amount_dollars"] for s in stones)


def test_every_boat_reports_its_own_measured_fog():
    for boat in scene()["boats"]:
        assert 0.0 <= boat["fog"] <= 1.0
        assert boat["worst_lag_days"] >= 0


def test_the_palette_has_no_red_and_green_pair():
    """Anything green in this world is separated from the alert colour by lightness.

    A red/green distinction alone is unreadable for deuteranopes, so the palette
    is only safe if a second channel carries the signal.
    """
    danger = PALETTE["danger"]
    for name, value in PALETTE.items():
        if name == "danger":
            continue
        if 80 < _hue(value) < 160:
            assert abs(_lightness(value) - _lightness(danger)) > 0.2, name


def test_signals_are_still_readable_without_colour():
    payload = scene()
    assert payload["stones"][0]["label"]
    assert payload["boats"][0]["fog"] is not None
    assert "below_surface" in payload["stones"][0]


def test_branches_exclude_the_baseline_and_carry_their_delta():
    session = Session.build(use_model=False)
    session.tool_fork("cancel the print club", cancel_event_ids=["sub-plates"])
    branches = scene_payload(session)["branches"]
    assert [b["key"] for b in branches] == ["cancel-the-print-club"]
    assert "verdict" in branches[0] and "min_balance_dollars" in branches[0]


def test_the_orb_is_told_where_to_look_and_what_to_say():
    session = Session.build(use_model=False)
    session.ask("when do I run out")
    payload = scene_payload(session)
    assert payload["focus"]
    assert payload["twin"]["look_at"] == payload["focus"]
    assert payload["twin"]["speak"] == session.last_speech


def test_the_garden_reports_the_score_it_was_computed_from():
    session = Session.build(use_model=False)
    garden = scene_payload(session)["garden"]
    assert garden["resolved"] == session.calibration.resolved_count
    assert garden["accuracy_pct"] == session.calibration.accuracy_pct
    assert 0 <= garden["stage"] <= 5
    assert garden["reliability"]


def test_the_meta_block_states_where_the_numbers_came_from():
    assert scene()["meta"]["generated_by"] == "code, not the model"


def _lightness(hex_colour: str) -> float:
    channels = (int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return (max(channels) + min(channels)) / 2


def _hue(hex_colour: str) -> int:
    r, g, b = (int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5))
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == mn:
        return 0
    if mx == r:
        h = (g - b) / (mx - mn)
    elif mx == g:
        h = 2 + (b - r) / (mx - mn)
    else:
        h = 4 + (r - g) / (mx - mn)
    return round((h * 60) % 360)
