"""PayPal-centred settlement joining the twin and principal-wide oversight."""
from __future__ import annotations

import sys
from pathlib import Path

# Twin-/integration/oversight_twin/__init__.py -> parents[2] is the repo root.
_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "tabletop-twin" / "backend", _ROOT / "swarm-oversight"):
    _s = str(_p)
    if _p.is_dir() and _s not in sys.path:
        sys.path.insert(0, _s)

from .bridge import Oversight, OversightTransport, SwarmOversight, record_action
from .hub import Agreement, HumanGate, PayPalHub, Settlement, firm_agreements

__all__ = ["Oversight", "OversightTransport", "SwarmOversight", "record_action",
           "Agreement", "HumanGate", "PayPalHub", "Settlement", "firm_agreements"]