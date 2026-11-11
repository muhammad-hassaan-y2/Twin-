"""Fictional persona data and the loader that turns it into a ledger.

Nothing here is a real account. The file names a person, her ledger, her limits,
and four weeks of predictions she already made and that already resolved.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from twin.domain.events import Ledger, ledger_from_dict
from twin.policy.engine import Policy, policy_from_dict

HERE = Path(__file__).resolve().parent


def ledger_path(persona_id: str = "juno-reyes") -> Path:
    return HERE / f"{persona_id}.json"


def load_persona_ledger(path: Path | None = None) -> tuple[Ledger, Policy, list[dict]]:
    raw = json.loads((path or ledger_path()).read_text(encoding="utf-8"))
    ledger = ledger_from_dict(raw)
    policy = policy_from_dict(raw.get("policy", {}))
    if policy.allowed_recipients:
        # Whoever is on the ledger is payable; the allowlist never has to be edited by hand.
        policy = replace(policy, allowed_recipients=policy.allowed_recipients | {e.counterparty for e in ledger.events if e.counterparty})
    history = list(raw.get("history", {}).get("predictions", ()))
    return ledger, policy, history
