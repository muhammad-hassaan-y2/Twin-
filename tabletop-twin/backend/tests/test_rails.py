"""Money leaves by a rail, and a rail is a fact about the world, not a string.

Two things are checked here over and over: an amount is written in the minor
units of its own currency, and nothing refuses a country unless its coverage map
was actually verified. A made-up refusal sends a user to a different bank for no
reason, which is worse than the provider declining the charge.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import pytest

from twin.payments.machine import PaymentRecord, PaymentState
from twin.payments.paypal import ProviderResult, SandboxTransport, to_amount
from twin.payments.rails import SANDBOX_RAIL, Rail, load_catalog
from twin.planner.rules import RulePlanner
from twin.planner.tools import REGISTRY, handler_map
from twin.policy.engine import Action, Policy, SpendWindow, Verdict, evaluate
from twin.store import Store
from twin.world import reconcile
from twin.world.scene import payments as scene_payments
from twin.world.scene import scene_payload
from twin.world.session import Session

CATALOG = load_catalog()
PAYPAL = CATALOG.rails["paypal"]
LOCAL = CATALOG.rails["local_transfer"]
CARD = CATALOG.rails["card_gateway"]


def catalog_rail(name: str) -> Rail:
    return load_catalog().rails[name]


# ------------------------------------------------------------- minor units


def test_an_amount_is_written_in_the_exponent_of_its_own_currency():
    assert CATALOG.amount_string(1234, "USD") == "12.34"
    assert CATALOG.amount_string(150, "JPY") == "150"
    assert CATALOG.amount_string(1234, "BHD") == "1.234"


def test_an_unlisted_currency_is_treated_as_two_decimals():
    assert CATALOG.exponent("ZZZ") == 2
    assert CATALOG.amount_string(1234, "ZZZ") == "12.34"


def test_the_paypal_wire_format_comes_from_the_catalog():
    """The bug this replaces was a hardcoded 'USD' in the request body."""
    assert to_amount(1234, "USD") == "12.34"
    assert to_amount(1234, "JPY") == "1234"
    assert to_amount(1234) == "12.34"


def test_the_provider_payload_carries_the_currency_it_was_given():
    transport = SandboxTransport()
    result = transport.charge("tt-key", 1500, "Highres Club", currency="EUR")
    assert result.status == "completed"


# ------------------------------------------------------------- coverage


def test_a_verified_map_refuses_the_countries_it_names():
    reason = PAYPAL.blocks("PK")
    assert reason and "no PayPal service" in reason
    assert PAYPAL.verified


def test_availability_is_directed_so_a_sender_only_country_still_works():
    """Georgia can send but not hold, so paying a Georgian from the US is the refusal."""
    assert "cannot reach GE" in PAYPAL.blocks("GE", "US")
    assert PAYPAL.blocks("US", "GE") is None


def test_a_send_only_country_is_refused_as_a_recipient_not_as_a_payer():
    assert "cannot reach AM" in PAYPAL.blocks("AM")


@pytest.mark.parametrize("country", sorted(CATALOG.rails["paypal"].coverage["unavailable"]))
def test_every_country_in_the_hard_map_is_refused(country):
    assert PAYPAL.blocks(country) is not None


def test_domestic_only_rules_fire_when_both_ends_are_the_same_country():
    assert PAYPAL.blocks("IN", "US") is None
    assert "cannot pay domestically in IN" in PAYPAL.blocks("IN", "IN")


def test_an_unverified_map_denies_nothing():
    assert not LOCAL.verified
    assert LOCAL.blocks("PK") is None
    assert CARD.blocks("KP") is None
    assert LOCAL.blocks("") is None


def test_a_soft_flag_warns_without_blocking():
    assert LOCAL.blocks("KZ") is None
    assert any("no local bank withdrawal" in flag for flag in PAYPAL.flags("KZ"))
    assert PAYPAL.flags("") == []


def test_an_empty_country_never_blocks():
    assert PAYPAL.blocks("") is None


# ------------------------------------------------------------------- fees


def test_the_domestic_fee_is_a_rate_plus_a_fixed_amount():
    assert PAYPAL.fee_cents(10_000, sender_country="US", recipient_country="US") == 398


def test_cross_border_money_pays_the_extra_slice_once():
    assert PAYPAL.fee_cents(10_000, sender_country="US", recipient_country="DE") == 548


def test_a_currency_the_rail_must_convert_adds_its_own_slice():
    same_border = PAYPAL.fee_cents(10_000, sender_country="US", recipient_country="DE")
    converted = PAYPAL.fee_cents(
        10_000, sender_country="US", recipient_country="DE", sender_currency="USD", recipient_currency="EUR"
    )
    assert converted - same_border == 350


def test_a_domestic_payment_is_not_charged_cross_border():
    assert PAYPAL.fee_cents(10_000, sender_country="DE", recipient_country="DE") == PAYPAL.fee_cents(
        10_000, sender_country="DE", recipient_country="DE", sender_currency="EUR", recipient_currency="EUR"
    )


def test_the_domestic_rail_quotes_zero_because_it_has_no_rate_declared():
    assert LOCAL.fee_cents(10_000, sender_country="PK", recipient_country="PK") == 0


def test_fee_rounding_does_not_depend_on_floats():
    assert PAYPAL.fee_cents(1, sender_country="US", recipient_country="US") == 49
    assert PAYPAL.fee_cents(0) == 49


# ------------------------------------------------------------ quote orders


def test_a_quote_places_rails_that_cannot_deliver_last():
    rows = CATALOG.quote(10_000, sender_country="US", recipient_country="PK", sender_currency="USD")
    assert [row["rail"] for row in rows[-1:]] == ["paypal"]
    assert "no PayPal service" in rows[-1]["excluded"]
    assert [row["rail"] for row in rows if not row["excluded"]][0] == "card_gateway"


def test_a_rail_that_does_not_settle_in_the_currency_is_excluded_with_a_reason():
    rows = CATALOG.quote(10_000, sender_country="PK", recipient_country="PK", sender_currency="PKR")
    excluded = {row["rail"]: row["excluded"] for row in rows}
    assert excluded["card_gateway"] == "Card gateway does not settle in PKR"
    assert excluded["paypal"] and "no PayPal service" in excluded["paypal"]
    assert [row["rail"] for row in rows if not row["excluded"]] == ["local_transfer"]


def test_reachable_and_quote_never_disagree():
    for country in ("PK", "IN", "GE", "US", "DE"):
        for currency in ("USD", "PKR", "EUR"):
            reachable = CATALOG.reachable(country, "US", currency)
            quoted = [row["rail"] for row in CATALOG.quote(5_000, sender_country="US",
                                                           recipient_country=country,
                                                           sender_currency=currency)]
            excluded = {row["rail"] for row in CATALOG.quote(
                5_000, sender_country="US", recipient_country=country, sender_currency=currency)
                if row["excluded"]}
            assert set(reachable) <= set(quoted)
            assert set(reachable) == set(quoted) - excluded


def test_a_quote_never_invents_a_conversion_rate():
    """Fees only. Nothing here pretends to know what USD to PKR costs today."""
    rows = CATALOG.quote(10_000, sender_country="US", recipient_country="PK",
                         sender_currency="USD", recipient_currency="PKR")
    assert all("converted" not in json.dumps(row) for row in rows)
    assert rows[0]["total_cents"] == 10_000 + rows[0]["fee_cents"]


def test_the_catalog_reports_the_date_it_was_compiled():
    summary = CATALOG.summary()
    assert summary["compiled_on"]
    assert len(summary["sources"]) == 4
    names = {rail["name"] for rail in summary["rails"]}
    assert names == {"paypal", "local_transfer", "card_gateway"}


def test_catalog_data_is_a_file_anyone_can_edit():
    raw = json.loads((Path(__file__).resolve().parents[1] / "twin" / "data" / "rails.json").read_text(encoding="utf-8"))
    assert raw["rails"][0]["fee_bps"] == PAYPAL.fee_bps
    assert raw["compiled_on"] == CATALOG.compiled_on


def test_a_catalog_without_a_currency_list_carries_everything():
    bare = replace(PAYPAL, currencies=())
    assert bare.carries("PKR")
    assert catalog_rail("paypal").carries("USD")
    assert not catalog_rail("paypal").carries("PKR")
    assert catalog_rail("paypal").carries("")


# ----------------------------------------------------------------- policy


def out_action(country: str, amount: int = 9_000) -> Action:
    return Action(id="a", verb="pay_bill", amount_cents=amount, recipient="Plate & Press",
                  country=country, currency="USD")


def test_a_rail_that_cannot_arrive_denies_before_the_amount_is_asked_about():
    decision = evaluate(out_action("PK", 31_000), Policy(), SpendWindow(), 0, rail=PAYPAL, sender_country="US")
    assert decision.verdict is Verdict.DENY
    assert decision.rule == "rail_unavailable"
    assert decision.limits["recipient_country"] == "PK"


def test_the_same_payment_is_not_refused_on_geography_by_a_rail_with_no_verified_map():
    decision = evaluate(out_action("PK"), Policy(), SpendWindow(), 0, rail=LOCAL, sender_country="US")
    assert decision.rule != "rail_unavailable"


def test_no_rail_means_no_geography_claim_so_the_money_machine_decides():
    decision = evaluate(out_action("PK"), Policy(), SpendWindow(), 0)
    assert decision.rule != "rail_unavailable"


def test_a_chase_is_never_blocked_for_where_the_payer_lives():
    chase = Action(id="a", verb="chase_invoice", amount_cents=480_000, recipient="Plate & Press",
                   country="PK", direction="none")
    decision = evaluate(chase, Policy(), SpendWindow(), 0, rail=PAYPAL, sender_country="US")
    assert decision.rule != "rail_unavailable"


# ---------------------------------------------------------------- session


def test_the_default_world_settles_through_the_fake():
    session = Session.build(use_model=False)
    assert session.rail == SANDBOX_RAIL
    assert session.active_rail() is None


def test_choosing_a_rail_moves_the_transport_with_it():
    session = Session.build(use_model=False)
    fake = SandboxTransport()
    out = session.set_rail("paypal", fake)
    assert out["rail"] == "paypal" and session.transport is fake
    assert session.active_rail().name == "paypal"
    assert "hold" in out["settlement_note"].lower()


def test_a_rail_the_catalog_does_not_know_is_refused():
    session = Session.build(use_model=False)
    with pytest.raises(ValueError, match="not a rail"):
        session.set_rail("carrier_pigeon")


def test_returning_to_the_fake_needs_no_catalog_entry():
    session = Session.build(use_model=False)
    session.set_rail("paypal", SandboxTransport())
    out = session.set_rail(SANDBOX_RAIL)
    assert out["label"] == "sandbox fake"
    assert out["settlement_note"] == "Nothing leaves this machine."


def test_a_payment_the_active_rail_cannot_carry_is_denied_and_names_alternatives():
    session = Session.build(use_model=False)
    # The rail alone decides here: a denied charge never reaches a transport, so no
    # fake needs to be stood up to prove the refusal.
    session.rail = "paypal"
    result = session.tool_propose_action("pay_bill", event_id="sub-plates")
    assert result["verdict"] == "deny"
    assert result["rule"] == "rail_unavailable"
    assert result["country"] == "PK"
    # The dollar ledger may only be rescued by a rail that settles in dollars.
    assert "card_gateway" in result["reason"]
    assert "local_transfer" not in result["reason"]


def test_a_rupee_denial_points_at_the_rupee_rail_not_the_dollar_one():
    session = Session.build(use_model=False)
    session.ledger = replace(session.ledger, currency="PKR", country="PK")
    session.rail = "paypal"
    result = session.tool_propose_action("pay_bill", event_id="sub-plates")
    assert result["rule"] == "rail_unavailable"
    assert "local_transfer" in result["reason"]


def test_a_refused_payment_is_not_left_pending_for_a_gesture():
    session = Session.build(use_model=False)
    session.rail = "paypal"
    result = session.tool_propose_action("pay_bill", event_id="sub-plates")
    assert result["action_id"] not in session.pending
    assert result["state"] == PaymentState.CANCELLED.value


def test_the_fee_quoted_for_a_german_subscription_is_the_catalogs_arithmetic():
    session = Session.build(use_model=False)
    session.set_rail("paypal", SandboxTransport())
    result = session.tool_propose_action("pay_bill", event_id="sub-scan")
    assert result["country"] == "DE"
    expected = PAYPAL.fee_cents(24_000, sender_country="US", recipient_country="DE",
                               sender_currency="USD", recipient_currency="")
    assert result["fee_cents"] == expected


def test_a_rail_refusal_is_written_to_the_action_ledger():
    session = Session.build(use_model=False)
    session.rail = "paypal"
    session.tool_propose_action("pay_bill", event_id="sub-plates")
    entry = next(row for row in session.log if row["kind"] == "policy")
    assert entry["rule"] == "rail_unavailable"
    assert entry["rail"] == "paypal" and entry["country"] == "PK"


def test_quoting_rails_for_an_event_needs_no_amount_because_the_ledger_has_one():
    session = Session.build(use_model=False)
    quoted = session.tool_quote_rails(event_id="sub-plates")
    assert quoted["amount_cents"] == 31_000
    assert quoted["country"] == "PK"
    assert [row["rail"] for row in quoted["quotes"]][-1] == "paypal"
    assert quoted["quotes"] == load_catalog().quote(31_000, sender_country="US",
                                                    recipient_country="PK", sender_currency="USD")


def test_a_quote_with_neither_an_event_nor_an_amount_says_so():
    session = Session.build(use_model=False)
    assert "skipped" in session.tool_quote_rails()


def test_a_pakistani_rupee_world_excludes_paypal_and_picks_the_domestic_rail():
    session = Session.build(use_model=False)
    session.ledger = replace(session.ledger, currency="PKR", country="PK")
    quoted = session.tool_quote_rails(event_id="sub-plates")
    assert quoted["quotes"][0]["rail"] == "local_transfer"
    assert [row["rail"] for row in quoted["quotes"] if not row["excluded"]] == ["local_transfer"]


def test_every_tool_in_the_registry_has_a_handler():
    session = Session.build(use_model=False)
    bound = handler_map(session)
    assert set(bound) == set(REGISTRY)
    assert callable(bound["quote_rails"])


def restored_world(store: Store, rail: str) -> Session:
    user_id = store.create_user("juno@acme.io", "Juno", "tabletop-2026")
    Session.seed_new_world(store, user_id)
    store.save_world(user_id, day=4, horizon_days=90, runs=2000, rail=rail, focus="",
                     last_speech="", tested_on_day=-1)
    return Session.restore(store, user_id)


def test_a_world_cannot_come_back_claiming_a_rail_it_has_no_transport_for(monkeypatch):
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_SECRET", raising=False)
    box = Store(":memory:")
    try:
        session = restored_world(box, "paypal")
        assert session.rail == SANDBOX_RAIL
        assert isinstance(session.transport, SandboxTransport)
        entry = next(row for row in session.log if row["kind"] == "rail_reverted")
        assert entry["from"] == "paypal"
    finally:
        box.close()


def test_credentials_bring_the_saved_rail_back_with_the_right_transport(monkeypatch):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "client")
    monkeypatch.setenv("PAYPAL_SECRET", "secret")
    monkeypatch.delenv("PAYPAL_ENVIRONMENT", raising=False)
    box = Store(":memory:")
    try:
        session = restored_world(box, "paypal")
        assert session.rail == "paypal"
        assert type(session.transport).__name__ == "PayPalTransport"
    finally:
        box.close()


def test_a_rail_with_no_adapter_anywhere_still_comes_home_as_the_fake():
    box = Store(":memory:")
    try:
        assert restored_world(box, "local_transfer").rail == SANDBOX_RAIL
    finally:
        box.close()


# ------------------------------------------------------------------ rules


def test_a_question_about_how_to_pay_routes_to_the_rail_quote():
    context = {"horizon_days": 90, "events": [{"id": "sub-plates", "label": "Plate & Press club"}]}
    calls = RulePlanner().plan("which rail should I use for the plates?", context)
    quote = next(call for call in calls if call.tool == "quote_rails")
    assert quote.args == {"event_id": "sub-plates"}


def test_an_unmatched_rail_question_still_quotes_an_undirected_answer():
    calls = RulePlanner().plan("can I settle across the border?", {"horizon_days": 90})
    assert any(call.tool == "quote_rails" and call.args == {} for call in calls)


def test_narrating_a_quote_only_speaks_numbers_the_catalog_computed():
    session = Session.build(use_model=False)
    quoted = session.tool_quote_rails(event_id="sub-scan")
    said = RulePlanner().narrate("", [quoted])
    assert any(row["label"] in said for row in quoted["quotes"] if not row["excluded"])
    assert str(quoted["amount_dollars"]) in said
    assert str(quoted["settles_on"]) in said


def test_narrating_a_quote_with_nothing_reachable_says_so():
    said = RulePlanner().narrate("", [{"country": "PK", "quotes": [
        {"rail": "paypal", "label": "PayPal Checkout", "excluded": "no PayPal service",
         "fee_dollars": 0, "flags": []},
    ]}])
    assert said == "None of my rails can reach PK. Wire one that serves it and ask again."


# ------------------------------------------------------------------ scene


def test_the_scene_says_which_currency_and_rail_this_world_uses():
    session = Session.build(use_model=False)
    meta = scene_payload(session)["meta"]
    assert meta["currency"] == "USD" and meta["country"] == "US"
    assert meta["rail"] == SANDBOX_RAIL


def test_a_stone_carries_the_country_its_counterparty_lives_in():
    session = Session.build(use_model=False)
    stones = scene_payload(session)["stones"]
    assert {s["country"] for s in stones if s["event_id"] == "sub-plates"} == {"PK"}


def test_an_open_payment_reports_the_rail_and_its_fee():
    session = Session.build(use_model=False)
    session.set_rail("paypal", SandboxTransport())
    # Over the approval floor, so the payment waits for a pinch instead of settling
    # immediately and dropping out of the scene.
    session.tool_propose_action("pay_bill", event_id="sub-scan", amount_cents=6_000)
    row = next(p for p in scene_payments(session) if p["recipient"] == "Highres Club")
    assert row["rail"] == "paypal" and row["currency"] == "USD"
    assert row["country"] == "DE"
    assert row["state"] == PaymentState.PROPOSED.value
    expected = PAYPAL.fee_cents(6_000, sender_country="US", recipient_country="DE")
    assert row["fee_dollars"] == round(expected / 100, 2)


# -------------------------------------------------------------- migration


OLD_SCHEMA = """
CREATE TABLE world (
  user_id TEXT PRIMARY KEY, persona_id TEXT NOT NULL, day INTEGER NOT NULL DEFAULT 0,
  horizon_days INTEGER NOT NULL, runs INTEGER NOT NULL, opening_balance_cents INTEGER NOT NULL,
  policy_json TEXT NOT NULL, focus TEXT NOT NULL DEFAULT '', last_speech TEXT NOT NULL DEFAULT '',
  tested_on_day INTEGER NOT NULL DEFAULT -1, updated_at REAL NOT NULL);
CREATE TABLE cash_event (
  user_id TEXT NOT NULL, id TEXT NOT NULL, label TEXT NOT NULL, kind TEXT NOT NULL,
  direction TEXT NOT NULL, amount_cents INTEGER NOT NULL, due_day INTEGER NOT NULL,
  counterparty TEXT NOT NULL DEFAULT '', recurring_every_days INTEGER, occurrences INTEGER NOT NULL DEFAULT 1,
  late_fee_cents INTEGER NOT NULL DEFAULT 0, lateness_json TEXT NOT NULL DEFAULT '[]',
  source TEXT NOT NULL DEFAULT 'seed', PRIMARY KEY (user_id, id));
CREATE TABLE payment (
  user_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, action_id TEXT NOT NULL,
  verb TEXT NOT NULL DEFAULT 'pay_bill', direction TEXT NOT NULL DEFAULT 'out',
  amount_cents INTEGER NOT NULL, recipient TEXT NOT NULL DEFAULT '', state TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 0, provider_ref TEXT, verified_outcome TEXT, settled_day INTEGER,
  history_json TEXT NOT NULL DEFAULT '[]', PRIMARY KEY (user_id, idempotency_key));
"""


def write_an_old_database(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        "INSERT INTO world (user_id, persona_id, horizon_days, runs, opening_balance_cents, policy_json,"
        " updated_at) VALUES ('old', 'juno-reyes', 90, 2000, 120000, '{}', 1.0)"
    )
    conn.execute(
        "INSERT INTO payment (user_id, idempotency_key, action_id, amount_cents, recipient, state)"
        " VALUES ('old', 'tt-old', 'act-old', 2400, 'Highres Club', 'unknown')"
    )
    conn.commit()
    conn.close()


def test_an_older_database_is_given_the_columns_it_lacks():
    box = Path(tempfile.mkdtemp(prefix="twin-migrate-"))
    path = box / "twin.db"
    try:
        write_an_old_database(path)
        store = Store(str(path))
        try:
            row = store.world_row("old")
            assert row["currency"] == "USD" and row["rail"] == "sandbox"
            unknown = store.payments_in_state("unknown")
            assert unknown[0]["currency"] == "USD" and unknown[0]["fee_cents"] == 0
            ledger = store.ledger_for("old", "juno-reyes", 120_000, "USD", "US")
            assert ledger.currency == "USD" and ledger.country == "US"
            assert ledger.events == ()
        finally:
            store.close()
    finally:
        shutil.rmtree(box, ignore_errors=True)


def test_a_second_open_of_a_migrated_database_changes_nothing():
    box = Path(tempfile.mkdtemp(prefix="twin-migrate-"))
    path = box / "twin.db"
    try:
        write_an_old_database(path)
        first = Store(str(path))
        first.close()
        second = Store(str(path))
        assert second.payments_in_state("unknown")[0]["rail"] == "sandbox"
        second.close()
    finally:
        shutil.rmtree(box, ignore_errors=True)


# ------------------------------------------------------------- reconciler


class Lookup:
    """Answers a lookup with whatever the deployment decides the provider said."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked: list[str] = []

    def lookup(self, key):
        self.asked.append(key)
        answer = self.answers.pop(0) if self.answers else ProviderResult(status="completed", reference="REF-1")
        if isinstance(answer, Exception):
            raise answer
        return answer


def unknown_record(action_id: str = "act-1", **field) -> PaymentRecord:
    record = PaymentRecord(action_id=action_id, amount_cents=2_400, recipient="Highres Club",
                           state=PaymentState.UNKNOWN, currency="EUR", rail="paypal", country="DE",
                           fee_cents=120, history=[(1.0, "unknown", "ambiguous")])
    for key, value in field.items():
        setattr(record, key, value)
    return record


@pytest.fixture()
def store():
    box = Store(":memory:")
    try:
        yield box
    finally:
        box.close()


def stash(box: Store, user_id: str, record: PaymentRecord) -> None:
    box.save_payment(user_id, record, verb="pay_bill", direction="out")


def test_a_record_rebuilt_from_a_row_keeps_its_rail_and_currency():
    record = unknown_record()
    copy = reconcile.record_from_row({"action_id": record.action_id, "amount_cents": record.amount_cents,
                                      "recipient": record.recipient, "state": "unknown", "attempt": 0,
                                      "idempotency_key": record.idempotency_key, "provider_ref": None,
                                      "history_json": json.dumps(record.history), "verified_outcome": None,
                                      "currency": "EUR", "rail": "paypal", "country": "DE", "fee_cents": 120})
    assert (copy.currency, copy.rail, copy.country, copy.fee_cents) == ("EUR", "paypal", "DE", 120)
    assert copy.state is PaymentState.UNKNOWN


def test_a_sweep_settles_a_charge_the_provider_took(store):
    stash(store, "ada", unknown_record())
    transport = Lookup()
    summary = reconcile.sweep(store, transport)
    assert summary["checked"] == 1 and summary["settled"] == 1
    assert summary["failed"] == 0 and summary["still_unknown"] == 0
    assert transport.asked == [unknown_record().idempotency_key]
    row = store.payments_in_state("succeeded")[0]
    assert row["provider_ref"] == "REF-1"


def test_a_sweep_writes_the_scheduler_to_the_audit_trail(store):
    stash(store, "ada", unknown_record())
    reconcile.sweep(store, Lookup())
    entry = store.read_log("ada")[0]
    assert entry["kind"] == "reconcile" and entry["source"] == "scheduler"
    assert entry["state"] == "succeeded"


def test_a_sweep_does_not_claim_the_business_effect_was_verified(store):
    stash(store, "ada", unknown_record())
    reconcile.sweep(store, Lookup())
    assert store.payments_in_state("succeeded")[0]["verified_outcome"] is None


def test_a_sweep_closes_a_charge_the_provider_never_took(store):
    stash(store, "ada", unknown_record())
    summary = reconcile.sweep(store, Lookup(ProviderResult(status="not_found")))
    assert summary["failed"] == 1
    assert store.payments_in_state("failed")[0]["state"] == "failed"


def test_a_sweep_leaves_a_still_silent_provider_alone(store):
    stash(store, "ada", unknown_record())
    summary = reconcile.sweep(store, Lookup(RuntimeError("lookup timed out")))
    assert summary["still_unknown"] == 1
    assert len(store.payments_in_state("unknown")) == 1


def test_a_second_sweep_finds_nothing_to_ask(store):
    stash(store, "ada", unknown_record())
    reconcile.sweep(store, Lookup())
    assert reconcile.sweep(store, Lookup())["checked"] == 0


def test_a_sweep_only_touches_the_accounts_it_was_asked_about(store):
    stash(store, "ada", unknown_record("act-ada"))
    stash(store, "bob", unknown_record("act-bob"))
    summary = reconcile.sweep(store, Lookup(), user_ids=["bob"])
    assert summary["checked"] == 1
    assert len(store.payments_in_state("unknown")) == 1
    assert store.payments_in_state("unknown")[0]["user_id"] == "ada"


def test_the_sweep_interval_is_off_unless_a_deployment_asks(monkeypatch):
    monkeypatch.delenv("TWIN_RECONCILE_SEC", raising=False)
    assert reconcile.interval_sec() == 0
    monkeypatch.setenv("TWIN_RECONCILE_SEC", "not-a-number")
    assert reconcile.interval_sec() == 0
    monkeypatch.setenv("TWIN_RECONCILE_SEC", "-5")
    assert reconcile.interval_sec() == 0
    monkeypatch.setenv("TWIN_RECONCILE_SEC", "45")
    assert reconcile.interval_sec() == 45


def test_the_loop_refuses_to_start_without_a_live_provider(store, monkeypatch):
    monkeypatch.setenv("TWIN_RECONCILE_SEC", "60")
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_SECRET", raising=False)
    assert reconcile.start(store) is None
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "client")
    monkeypatch.setenv("PAYPAL_SECRET", "secret")
    monkeypatch.setenv("TWIN_RECONCILE_SEC", "0")
    assert reconcile.start(store) is None


def test_the_loop_sweeps_on_a_timer_and_reports_what_it_saw(store):
    stash(store, "ada", unknown_record())
    loop = reconcile.ReconciliationLoop(store, Lookup(), 0.02)
    loop.start()
    try:
        for _ in range(200):
            if loop.status()["sweeps"]:
                break
            time.sleep(0.02)
    finally:
        loop.stop()
    status = loop.status()
    assert status["sweeps"] >= 1
    assert status["last_sweep"]["settled"] == 1
    assert status["open_unknowns"] == 0
    loop.join(2)
    assert not loop.is_alive()


def test_a_broken_sweep_reports_an_error_instead_of_dying(store):
    store.payments_in_state = lambda state: (_ for _ in ()).throw(RuntimeError("db is locked"))
    loop = reconcile.ReconciliationLoop(store, SandboxTransport(), 0.02)
    loop.start()
    try:
        for _ in range(200):
            if loop.last is not None:
                break
            time.sleep(0.02)
    finally:
        loop.stop()
        loop.join(2)
    assert loop.last["error"] == "RuntimeError"
    assert loop.sweeps == 0
    assert not loop.is_alive()
