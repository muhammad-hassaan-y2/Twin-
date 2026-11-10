"""The integration layer between the two projects in this repository.

tabletop-twin settles one principal's money through a real payment state machine
and a transport (PayPal Orders v2, or a deterministic sandbox). swarm-oversight
measures the aggregate gap: per-mandate ceilings do not bind the principal across
mandates. This package joins them at the settlement seam without editing either
baseline -- importing it puts both on the path so the bridge can import
``twin.payments`` and ``swarm_oversight`` from a checkout, no installation needed.
"""
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

__all__ = ["Oversight", "OversightTransport", "SwarmOversight", "record_action"]