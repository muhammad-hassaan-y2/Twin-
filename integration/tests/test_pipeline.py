"""The CRM pipeline: prices what the firm binds, pays only after named clearance.

Every guard is shown to matter by removing it: drop the quality check and a contradictory
VAT pair is audited; drop clearance and nothing moves; widen the bound and the whole
engagement leaves. No PostgreSQL, no network, no model.
"""
from __future__ import annotations

import pytest

from oversight_twin.pipeline import Pipeline, parse_record
from swarm_oversight.monitor import Limits
from twin.payments.paypal import PayPalConfig, PayPalTransport, SandboxTransport

OPEN = Limits(per_agent=10**9, per_payee=10**9, window=10, long_window=60, merge="both")


def pipeline(transport, *, limits=OPEN, **changes):
    return Pipeline(transport, dataset_id="crm-2026", payee="Ashgrove Audit LLP",
                    limits=limits, rail="simulated", **changes)


def instruction_ids(report, index=0):
    return [row["id"] for row in report["records"][index]["agreements"]]


def test_binding_desks_are_priced_but_nothing_moves_before_clearance(base_record):
    transport = SandboxTransport()
    pipe = pipeline(transport)
    report = pipe.run([base_record()])
    record = report["records"][0]
    _, case, _ = parse_record(base_record(), priors=pipe.priors)
    hold_roles = {finding.role for finding in pipe.firm.review(case)
                  if finding.verdict == "hold"}
    flagged = {row["role"] for row in record["agreements"] if row["review_required"]}
    priced = {row["role"] for row in record["agreements"]}
    assert record["quality"] == "verified"
    assert report["desks"]["findings"] == 26
    assert record["payable"] == len(record["agreements"]) > 0
    assert all(row["state"] == "awaiting_human" for row in record["agreements"])
    assert flagged == hold_roles & priced
    assert flagged
    assert transport.charge_calls == 0
    assert report["settlement"]["settled_cents"] == 0


def test_named_clearance_settles_exactly_those_instructions(base_record):
    transport = SandboxTransport()
    pipe = pipeline(transport)
    report = pipe.run([base_record()])
    ids = instruction_ids(report)
    cleared = ids[:2]
    after = pipe.clear(report["run_id"], cleared)
    states = {row["id"]: row["state"] for row in after["records"][0]["agreements"]}
    assert all(states[key] == "succeeded" for key in cleared)
    assert all(states[key] == "awaiting_human" for key in ids[2:])
    assert transport.charge_calls == 2
    assert after["settlement"]["settled_now_cents"] == 2 * 20_000
    assert after["settlement"]["settled_cents"] == 2 * 20_000


def test_a_repeat_run_does_not_charge_again(base_record):
    transport = SandboxTransport()
    pipe = pipeline(transport)
    report = pipe.run([base_record()])
    pipe.clear(report["run_id"], instruction_ids(report))
    charges = transport.charge_calls
    again = pipe.run([base_record()])
    assert again["records"][0]["state"] == "settled"
    assert again["settlement"]["settled_cents"] == charges * 20_000
    assert again["settlement"]["settled_now_cents"] == 0
    assert transport.charge_calls == charges


def test_changed_terms_under_a_priced_agreement_are_a_conflict(base_record):
    transport = SandboxTransport()
    pipe = pipeline(transport)
    report = pipe.run([base_record()])
    pipe.clear(report["run_id"], instruction_ids(report))
    charges = transport.charge_calls
    changed = pipe.run([base_record(audit_fee_cents=21_000)])
    assert changed["records"][0]["state"] == "conflict"
    assert "agreement_terms_changed" in changed["quality"]["issue_codes"]
    assert transport.charge_calls == charges


@pytest.mark.parametrize("changes,code", [
    ({"audit_fee_cents": -1}, "negative_number"),
    ({"is_pie": "maybe"}, "invalid_type"),
    ({"turnover_eur": float("nan")}, "invalid_type"),
    ({"client": ""}, "missing_field"),
    ({"standard_vat_rate_percent": 5.0, "reduced_vat_rate_percent": 9.0}, "vat_rate_order_invalid"),
    ({"firm_fee_from_client_cents": 200_000}, "fees_exceed_firm_total"),
    ({"standard_vat_rate_percent": 120.0}, "number_out_of_range"),
], ids=["negative-fee", "bad-boolean", "not-finite", "missing-client", "vat-order",
        "fees-exceed-total", "rate-out-of-range"])
def test_bad_rows_are_blocked_before_review(base_record, changes, code):
    transport = SandboxTransport()
    report = pipeline(transport).run([base_record(**changes)])
    assert report["quality"]["blocked"] == 1
    assert report["quality"]["issue_codes"][code] >= 1
    assert report["records"][0]["agreements"] == []
    assert transport.charge_calls == 0


def test_negative_control_without_the_quality_gate_a_contradiction_is_audited(base_record):
    contradiction = {"standard_vat_rate_percent": 5.0, "reduced_vat_rate_percent": 9.0}
    strict = pipeline(SandboxTransport()).run([base_record(**contradiction)])
    assert strict["quality"]["blocked"] == 1

    loose = pipeline(SandboxTransport(), quality=lambda case, priors: [])
    audited = loose.run([base_record(**contradiction)])
    assert audited["quality"]["blocked"] == 0
    assert audited["records"][0]["payable"] > 0


def test_duplicate_engagement_ids_block_the_whole_batch(base_record):
    transport = SandboxTransport()
    report = pipeline(transport).run([base_record(), base_record(client="Other GmbH")])
    assert report["quality"]["blocked"] == 2
    assert report["quality"]["issue_codes"]["duplicate_external_id"] == 2
    assert transport.charge_calls == 0


def test_the_aggregate_bound_refuses_at_the_payee_ceiling(base_record):
    transport = SandboxTransport()
    tight = Limits(per_agent=10**9, per_payee=100_000, window=10, long_window=60, merge="both")
    pipe = pipeline(transport, limits=tight)
    report = pipe.run([base_record()])
    ids = instruction_ids(report)
    after = pipe.clear(report["run_id"], ids)
    assert after["settlement"]["settled"] == 5
    assert after["settlement"]["settled_cents"] == 100_000
    assert after["settlement"]["failed"] == len(ids) - 5
    refused = [row for row in after["records"][0]["agreements"] if row["state"] == "failed"]
    assert "swarm oversight refused" in refused[0]["note"]
    assert transport.charge_calls == 5


def test_a_zero_fee_engagement_opens_no_instruction(base_record):
    transport = SandboxTransport()
    report = pipeline(transport).run([base_record(audit_fee_cents=0)])
    record = report["records"][0]
    assert record["state"] == "no_payment"
    assert record["agreements"] == []
    assert "zero_audit_fee" in report["quality"]["issue_codes"]
    assert transport.charge_calls == 0


def test_missing_jurisdiction_is_review_not_a_guess(base_record):
    transport = SandboxTransport()
    report = pipeline(transport).run([base_record(client_geo="")])
    record = report["records"][0]
    assert record["quality"] == "review"
    assert "jurisdiction_missing" in report["quality"]["issue_codes"]
    assert record["payable"] > 0
    assert transport.charge_calls == 0


def test_the_pipeline_settles_through_the_real_paypal_transport(base_record, paypal):
    config = PayPalConfig(client_id=paypal.client_id, secret=paypal.secret,
                          test_server_url=paypal.url)
    pipe = Pipeline(PayPalTransport(config), dataset_id="crm-2026",
                    payee="Ashgrove Audit LLP", limits=OPEN, rail="paypal")
    report = pipe.run([base_record()])
    ids = instruction_ids(report)
    assert ids
    assert paypal.create_calls == 0

    after = pipe.clear(report["run_id"], ids)
    assert after["settlement"]["settled"] == len(ids)
    assert after["settlement"]["settled_cents"] == 20_000 * len(ids)
    assert paypal.captured_cents == 20_000 * len(ids)
    assert all(row["provider_ref"] for row in after["records"][0]["agreements"])


def test_a_dataset_must_name_its_payee_and_currency():
    transport = SandboxTransport()
    with pytest.raises(ValueError):
        Pipeline(transport, dataset_id="crm", payee=" ", limits=OPEN)
    with pytest.raises(ValueError):
        Pipeline(transport, dataset_id="crm", payee="Firm", limits=OPEN, currency="usd")
    with pytest.raises(ValueError):
        Pipeline(transport, dataset_id="crm", payee="Firm", limits=None)
