"""The one place the HTTP edge decides whether a chain is answering.

The firm itself needs nothing from outside: `agents.Firm.review` reads the derived thresholds and
answers twenty-six questions, and it does that with no key, no node process and no database. What it
cannot do alone is turn an answer into an agreement somebody is bound by, and that is the only
reason this module exists. It holds one connection and one decision — is there a contract, and are
the twenty-six roles on it — and remembers the answer, because a request that re-asked would either
hang a panel behind a dead sidecar or burn gas re-registering a role the registry already knows.

With no chain the review still runs and still says what it thinks; `agreements` comes back empty
with the reason attached. A service that quietly returned an empty agreement list would look
exactly like a firm that opened none, and those are different facts.
"""

from __future__ import annotations

import dataclasses
import os
import threading
from typing import Any

from twin.audit.a2a import Bus
from twin.audit.agents import Case, Firm, Priors
from twin.audit.chain import Chain, describe, roster
from twin.audit.corpus import corpus_place
from twin.audit.finetune import sweep

# A boot is not the place to wait twenty seconds for a node process that may never come.
PROBE_TIMEOUT_SEC = 2.0
# Once it has answered, though, one review is a run of transactions and each one costs real gas.
# A timeout is a statement about the call being made, so the connection a review uses is not
# the one the probe used, even though it is the same sidecar.
WORK_TIMEOUT_SEC = 20.0


def engagements(priors: Priors | None = None) -> tuple[Case, ...]:
    """The engagements this firm can be asked about, every figure of which came from the corpus.

    These are not real clients. They are the distances the derived thresholds make interesting -
    exactly on a ceiling, one cent past it, one year short of a rotation - so that a review can be
    asked about the boundary rather than about a number somebody typed into a form.
    """
    return sweep(priors or Priors.load())


def engagement_card(index: int, case: Case) -> dict[str, Any]:
    """One engagement, in the shapes a panel and a form both need."""
    return {"index": index, "client": case.client, "facts": dataclasses.asdict(case)}


def threshold_cards(priors: Priors) -> list[dict[str, Any]]:
    """Every number the firm quotes, with the provision it was read out of."""
    cards = []
    for name, prior in sorted((priors.doc.get("priors") or {}).items()):
        cards.append({
            "name": name,
            "value": prior.get("value"),
            "state": prior.get("state"),
            "celex": prior.get("celex") or "",
            "article": prior.get("article") or "",
        })
    return cards


class FirmService:
    """This process's chain connection: opened once, described to whoever asks."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._chain: Chain | None = None
        self._why = ""
        self._registration: list[dict[str, Any]] = []
        self._asked = False

    def chain(self) -> Chain | None:
        """The sidecar, or None with a reason that says why there is not one."""
        if not self._asked:
            with self._lock:
                if not self._asked:
                    self._open()
        return self._chain

    def _open(self) -> None:
        self._asked = True
        url = os.environ.get("TWIN_CHAIN_URL", "").strip()
        if not url:
            # No default here on purpose. A sidecar left running by another project would
            # otherwise become this app's agreement history without anybody choosing it.
            self._why = "TWIN_CHAIN_URL is not set, so this app never asks for a chain"
            return
        probe = Chain(url=url, token=os.environ.get("TWIN_CHAIN_TOKEN", ""),
                      timeout_sec=PROBE_TIMEOUT_SEC)
        try:
            probe.status()
        except Exception as error:  # noqa: BLE001 - a dead sidecar is an answer, not a crash
            self._why = f"{probe.url} did not answer: {error}"
            return
        chain = Chain(url=url, token=probe.token, timeout_sec=WORK_TIMEOUT_SEC)
        self._chain = chain
        try:
            self._registration = describe(chain.register_roles())
        except Exception as error:  # noqa: BLE001 - same reason; the review still runs
            self._why = f"{chain.url} is up but the roster could not be hired: {error}"
            return
        refused = [row for row in self._registration if not row["ok"]]
        if refused:
            self._why = f"{len(refused)} of {len(self._registration)} roles were refused"

    def reset(self) -> None:
        """Forget the connection. Tests come through here when they change the environment."""
        with self._lock:
            self._asked = False
            self._chain = None
            self._why = ""
            self._registration = []

    def status(self) -> dict[str, Any]:
        """What the firm is standing on right now, said in the order a panel reads it."""
        chain = self.chain()
        answer: dict[str, Any] = {"on_chain": chain is not None, "why": self._why}
        if chain is None:
            return answer
        try:
            answer["chain"] = chain.status()
            roles = chain.roles()
            answer["roles_on_chain"] = [row["role"] for row in roles.get("agents") or []
                                        if row.get("known")]
        except Exception as error:  # noqa: BLE001 - it answered at boot, it may not be answering now
            self._chain = None
            self._asked = False
            answer["on_chain"] = False
            answer["why"] = f"{chain.url} stopped answering: {error}"
            return answer
        answer["registration"] = self._registration
        return answer

    def health(self) -> dict[str, Any]:
        """What the boot probe found, said without asking the sidecar again.

        Health is polled by a client that is still loading. A reply that re-probed would put a
        network round trip in front of every panel, and a chain that came up after boot is
        reported by `status()`, which does ask.
        """
        return {
            "on_chain": self.chain() is not None,
            "why": self._why,
            "hired": sum(1 for row in self._registration if row["ok"]),
            "refused": sum(1 for row in self._registration if not row["ok"]),
        }

    def bus(self, store: Any, user_id: str, day: int) -> Bus | None:
        """A bus that mirrors into this world's ledger, if there is a chain to write through.

        The store is handed in rather than reached for. The edge owns the one connection every
        request writes through; this module only knows how to carry a message once it has one.
        """
        chain = self.chain()
        if chain is None:
            return None
        return Bus(chain, store=store, user_id=user_id, day=day)

    def review(self, case: Case, store: Any, user_id: str, day: int) -> dict[str, Any]:
        """Twenty-six answers, and the agreements they are entitled to open."""
        firm = Firm.from_env()
        bus = self.bus(store, user_id, day)
        if bus is None:
            findings = firm.review(case)
            return {
                "client": case.client,
                "route": firm.describe(),
                "findings": [finding.as_dict() for finding in findings],
                "counts": {verdict: sum(1 for f in findings if f.verdict == verdict)
                           for verdict in ("clear", "hold", "breach", "silent")},
                "agreements": [],
                "waiting_on_humans": [],
                "chain": {"on_chain": False, "why": self._why},
                "why_no_agreements": ("no agreement was opened because no contract was reached; "
                                      "the findings above are the firm's own and do not need one"),
            }
        summary = firm.transact(case, bus)
        summary["chain"] = {"on_chain": True, "why": self._why}
        return summary

    def inbox(self, role: str, after: int) -> dict[str, Any]:
        chain = self.chain()
        if chain is None:
            return {"role": role, "messages": [], "cursor": after,
                    "chain": {"on_chain": False, "why": self._why}}
        items, cursor = Bus(chain).receive(role, after)
        return {"role": role, "messages": items, "cursor": cursor,
                "chain": {"on_chain": True, "why": self._why}}

    def agreements(self) -> dict[str, Any]:
        chain = self.chain()
        if chain is None:
            return {"agreements": [], "waiting_on_humans": [],
                    "chain": {"on_chain": False, "why": self._why}}
        bus = Bus(chain)
        return {"agreements": bus.agreements(), "waiting_on_humans": bus.waiting_on_humans(),
                "chain": {"on_chain": True, "why": self._why}}


def brief(priors: Priors | None = None) -> dict[str, Any]:
    """What the subsystem is, in one reply: who is hired, on what numbers, standing on what."""
    p = priors or Priors.load()
    doc = p.doc
    return {
        "roles": roster().get("agents") or [],
        "engagements": len(engagements(p)),
        "thresholds": threshold_cards(p),
        "uncalibrated": doc.get("uncalibrated") or [],
        "provenance": {
            "derived_from": doc.get("derived_from") or {},
            "corpus_dir": corpus_place(),
        },
        "model_route": Firm.from_env().describe(),
        "chain": service().status(),
    }


_service = FirmService()


def service() -> FirmService:
    return _service


def reset() -> None:
    _service.reset()
