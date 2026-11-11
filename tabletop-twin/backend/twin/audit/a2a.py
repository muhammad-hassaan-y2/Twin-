"""Agent-to-agent communication, where sending a message is a transaction.

A message between two agents is not a log line both sides agree to ignore. It is a call into
the engagement contract, it costs gas, it is journalled, and it either changes the state of
an agreement or comes back with the name of the requirement it broke. That makes refusal
legible: an agent that wants a review done has to make an offer the reviewer's side can
accept, and an agent that wants an opinion signed has to wait for a human whose key is on
file. Nothing here enforces that by convention.

`ChainDown` is deliberately not caught. A chain that is not answering is this process's
problem, not an answer the agents can act on, and the firm falls back to its rules somewhere
else rather than pretending a message was sent. Neither is a `ChainError` about a write the
EVM would not accept: an agent with no account on this chain was not refused, it was never
heard, so the send raises and nothing is recorded either way.

The Postgres mirror is a projection for the panels and the API. The chain decides whether an
agreement exists; this table decides how fast somebody can ask about it. A row holds the state
the message it mirrors produced, which is not the state that agreement is in now - `agreements()`
answers that from the chain, and rewriting history to make the two tables say the same thing
would destroy the only record of what each agent actually tried to do.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from twin.audit.chain import Chain, Receipt, Refusal

# One verb, one state it is supposed to produce. `countersign` changes who has signed rather
# than what state the agreement is in, so it reaches for the state it was already in.
STATES = {
    "propose": "Proposed",
    "accept": "Accepted",
    "attest": "Attested",
    "countersign": "Attested",
    "settle": "Settled",
    "reject": "Rejected",
    "dispute": "Disputed",
}

VERBS = tuple(STATES)


def _payload(verb: str, agreement: str, by_role: str, fields: dict[str, Any]) -> dict[str, Any]:
    if verb == "propose":
        # A counterparty only means something when opening one, so it rides in with the
        # fields rather than standing as a parameter of the verbs it does not apply to.
        return {
            "from": by_role,
            "to": fields.get("to_role") or "",
            "terms": fields.get("terms", ""),
            "amount_cents": int(fields.get("amount_cents") or 0),
            "non_audit_cents": int(fields.get("non_audit_cents") or 0),
            "horizon_sec": int(fields.get("horizon_sec") or 3600),
        }
    if verb == "countersign":
        return {"id": agreement, "role": by_role}
    body: dict[str, Any] = {"id": agreement, "by_role": by_role}
    for name in ("evidence", "reason"):
        if fields.get(name):
            body[name] = fields[name]
    return body


@dataclass(frozen=True)
class Delivery:
    """One message and what the chain made of it."""

    verb: str
    ok: bool
    agreement: str
    state: str
    receipt: Receipt
    delivery_id: str
    refusal: Refusal | None = None

    @property
    def gas_used(self) -> int:
        return self.receipt.gas_used

    def as_dict(self) -> dict[str, Any]:
        return {
            "verb": self.verb,
            "ok": self.ok,
            "agreement": self.agreement,
            "state": self.state,
            "delivery_id": self.delivery_id,
            "refused": str(self.refusal) if self.refusal else "",
            "gas_used": self.receipt.gas_used,
            "tick": self.receipt.tick,
            "events": list(self.receipt.event_names),
        }


class Bus:
    """The one place an agent's message becomes a transaction and a mirror row."""

    def __init__(self, chain: Chain, store: Any = None, user_id: str = "", day: int = 0) -> None:
        self.chain = chain
        self.store = store
        self.user_id = user_id
        self.day = day

    # --------------------------------------------------------------------- send

    def send(self, verb: str, *, from_role: str, agreement: str = "", **fields: Any) -> Delivery:
        if verb not in VERBS:
            raise ValueError(f"not something an agent can say to another: {verb}")
        receipt = self.chain.write(verb, **_payload(verb, agreement, from_role, fields))
        delivery_id = uuid.uuid4().hex[:20]
        state = STATES[verb] if receipt.ok else "refused"
        message = {
            "delivery_id": delivery_id,
            "agreement": receipt.id or agreement or "",
            "verb": verb,
            "from_role": from_role,
            "to_role": fields.get("to_role") or "",
            "subject": fields.get("subject", ""),
            "terms": fields.get("terms", ""),
            "terms_hash": receipt.terms_hash,
            "evidence_hash": receipt.evidence_hash,
            "amount_cents": int(fields.get("amount_cents") or 0),
            "non_audit_cents": int(fields.get("non_audit_cents") or 0),
            "state": state,
            "refusal": str(receipt.refusal) if receipt.refusal else "",
            "reason": fields.get("reason", ""),
            "gas_used": receipt.gas_used,
            "tick": receipt.tick,
            "day": self.day,
            "seq": receipt.seq,
        }
        # The chain was asked first and the answer is in the receipt either way, so there is no
        # Python-side ceiling checked here. Two implementations of one number is how the two
        # of them eventually disagree, and the one in bytecode is the one that wins.
        self._mirror(message, refused=receipt.refusal is not None)
        return Delivery(
            verb=verb,
            ok=receipt.ok,
            agreement=message["agreement"],
            state=state,
            receipt=receipt,
            delivery_id=delivery_id,
            refusal=receipt.refusal,
        )

    def _mirror(self, message: dict[str, Any], refused: bool) -> None:
        if self.store is None or not self.user_id:
            return
        self.store.save_agent_message(self.user_id, message)
        if refused:
            # A refusal is a decision, and the ledger is where the app keeps decisions.
            self.store.append_log(self.user_id, self.day, "agent_refusal", {
                "verb": message["verb"],
                "from": message["from_role"],
                "to": message["to_role"],
                "agreement": message["agreement"],
                "refused": message["refusal"],
                "gas_used": message["gas_used"],
                "subject": message["subject"],
            })

    # --------------------------------------------------------------------- read

    def receive(self, role: str, after: int = 0) -> tuple[list[dict[str, Any]], int]:
        """Everything the chain emitted for one role since `after`.

        Cursors live in memory. After a restart the first read replays from the beginning of
        the rebuilt log, which repeats messages rather than losing them - the cheaper of the
        two by a wide margin, since the agreement each one names is idempotent to look at.
        """
        answer = self.chain.inbox(role, after)
        items = [_event(event) for event in answer.get("events") or []]
        return items, int(answer.get("cursor") or after)

    def transcript(self, limit: int = 40, role: str | None = None) -> list[dict[str, Any]]:
        if self.store is None or not self.user_id:
            return []
        return self.store.agent_messages(self.user_id, limit=limit, role=role)

    def agreements(self) -> list[dict[str, Any]]:
        return self.chain.agreements()

    def waiting_on_humans(self) -> list[dict[str, Any]]:
        """Agreements that are attested and waiting on a signature no machine can produce.

        This is the queue a person works through. An empty one with an unsettled opinion above
        it would mean the hold was bypassed, which is the failure the contract is there to
        make impossible rather than merely unlikely.
        """
        return [
            {
                "agreement": row.get("id"),
                "from_role": row.get("from_role"),
                "to_role": row.get("to_role"),
                "terms_hash": row.get("termsHash"),
                "evidence_hash": row.get("evidenceHash"),
                "amount_cents": int(row.get("amountCents") or 0),
            }
            for row in self.chain.agreements()
            if row.get("state") == "Attested"
        ]

    def status(self) -> dict[str, Any]:
        try:
            return {"on_chain": True, **self.chain.status()}
        except Exception as error:  # noqa: BLE001 - the panel needs to know, not to crash
            return {"on_chain": False, "why": str(error)}


def _event(event: dict[str, Any]) -> dict[str, Any]:
    args = event.get("args") or []
    named = event.get("roles") or []
    # `Proposed` leads with the array index, so its id is one along from every other
    # agreement event's. The registry's events name roles, not agreements, so they have none.
    slot = 1 if event.get("name") == "Proposed" else 0
    return {
        "seq": event.get("seq"),
        "tick": event.get("tick"),
        "contract": event.get("contract", ""),
        "name": event.get("name"),
        "agreement": args[slot] if event.get("contract") == "EngagementAgreement" and len(args) > slot else "",
        "roles": named,
        "args": args,
    }
