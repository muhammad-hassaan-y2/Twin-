"""The voice is data. If the markdown changes, the twin changes, and no code does."""

from __future__ import annotations

from pathlib import Path

from twin.persona.persona import load_persona, parse_heartbeat

ROOT = Path(__file__).resolve().parents[1] / "twin" / "persona"


def test_the_heartbeat_steps_come_out_in_order():
    persona = load_persona()
    assert [s.index for s in persona.steps] == sorted(s.index for s in persona.steps)
    assert len(persona.steps) == 6


def test_each_step_has_a_slug_the_client_can_address():
    slugs = [s.slug for s in load_persona().steps]
    assert slugs == [
        "resolve-what-is-now-knowable",
        "look-downstream-for-the-first-time",
        "look-for-the-thin-spot",
        "test-one-thing-she-could-have-done",
        "check-the-money-it-was-told-to-move",
        "wind-down",
    ]


def test_the_prohibitions_are_parsed_out_of_the_prose():
    persona = load_persona()
    assert any("Invent a number" in line for line in persona.prohibitions)
    assert any("held pinch" in line for line in persona.prohibitions)


def test_the_voice_prompt_carries_the_personality_text():
    persona = load_persona()
    assert persona.name in persona.voice_prompt
    assert "lying awake" in persona.voice_prompt


def test_a_heartbeat_file_with_no_numbered_steps_yields_no_steps():
    assert parse_heartbeat("# Heartbeat\n\nJust prose, no steps.\n") == ()


def test_the_personality_and_heartbeat_files_are_read_from_the_package():
    assert (ROOT / "personality.md").exists()
    assert (ROOT / "heartbeat.md").exists()


def test_she_refuses_investing_and_advice_in_her_own_copy():
    text = (ROOT / "personality.md").read_text(encoding="utf-8")
    assert "investment" in text.lower()
    assert "as an AI" in text  # named in order to be banned
