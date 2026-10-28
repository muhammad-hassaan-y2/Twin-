"""Load the persona from markdown so the voice is data, not string literals.

``personality.md`` makes the twin sound like a person. ``heartbeat.md`` is the
ordered list of things it does without being asked. Both are parsed into a shape
the planner and the tick can use, so changing the voice never touches code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class HeartbeatStep:
    index: int
    title: str
    body: str

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    personality: str
    heartbeat: str
    steps: tuple[HeartbeatStep, ...] = ()
    prohibitions: tuple[str, ...] = field(default_factory=tuple)

    @property
    def voice_prompt(self) -> str:
        """The block a model is allowed to imitate, and nothing else."""
        return (
            f"You are {self.name}, a cash-flow twin. Speak only in this voice.\n\n"
            f"{self.personality}\n\n"
            "Rules of speech: one action per reply, never more than one number per"
            " sentence, never a number you were not given."
        )

    def step(self, slug: str) -> HeartbeatStep | None:
        for step in self.steps:
            if step.slug == slug:
                return step
        return None


def load_persona(directory: Path | None = None, persona_id: str = "juno-reyes") -> Persona:
    root = directory or HERE
    personality = (root / "personality.md").read_text(encoding="utf-8")
    heartbeat = (root / "heartbeat.md").read_text(encoding="utf-8")
    return Persona(
        id=persona_id,
        name=_title(personality) or "the twin",
        personality=personality.strip(),
        heartbeat=heartbeat.strip(),
        steps=parse_heartbeat(heartbeat),
        prohibitions=_bullets(personality, "What she will not do"),
    )


def parse_heartbeat(text: str) -> tuple[HeartbeatStep, ...]:
    """Every numbered heading in heartbeat.md becomes a tick step, in order."""
    steps: list[HeartbeatStep] = []
    match = re.search(r"^# Heartbeat.*?(?=^## )", text, re.S | re.M)
    blocks = re.split(r"^## ", text, flags=re.M)[1:]
    for block in blocks:
        title, _, body = block.partition("\n")
        head = title.strip()
        if not re.match(r"^\d+\.", head):
            continue
        if match is None:  # pragma: no cover - guard against an empty preamble
            continue
        steps.append(HeartbeatStep(index=int(re.match(r"^(\d+)\.", head).group(1)), title=head.split(". ", 1)[1], body=body.strip()))
    return tuple(sorted(steps, key=lambda s: s.index))


def _title(markdown: str) -> str | None:
    match = re.search(r"^# (.+)$", markdown, re.M)
    if not match:
        return None
    name = match.group(1).strip()
    return name.removesuffix("'s twin").strip()


def _bullets(markdown: str, heading: str) -> tuple[str, ...]:
    pattern = rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, markdown, re.S | re.M)
    if not match:
        return ()
    return tuple(line.lstrip("- ").strip() for line in match.group(1).splitlines() if line.startswith("- "))
