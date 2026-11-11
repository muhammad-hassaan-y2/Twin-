"""Adapters from CRM exports and tool dumps, and the outcome writeback.

The adapters are deliberately dumb: they read rows and name the file they came from. The
pipeline is what validates, so a test here checks shapes and provenance, and the sync test
checks that a cleared instruction is the only one that reaches the rail.
"""
from __future__ import annotations

import csv
import json

import pytest

from oversight_twin.crm import CsvCrm, JsonCrm, outcome_rows, sync, write_outcomes
from oversight_twin.pipeline import Pipeline
from swarm_oversight.monitor import Limits
from twin.payments.paypal import SandboxTransport

OPEN = Limits(per_agent=10**9, per_payee=10**9, window=10, long_window=60, merge="both")


def pipe(transport, dataset_id="crm-2026"):
    return Pipeline(transport, dataset_id=dataset_id, payee="Ashgrove Audit LLP",
                    limits=OPEN, rail="simulated")


def dump_json(path, rows):
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def dump_csv(path, row):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow({key: str(value) for key, value in row.items()})
    return path


def test_json_list_names_its_file_and_nothing_else(scratch, base_record):
    path = dump_json(scratch / "engagements.json", [base_record()])
    batch = JsonCrm(path).fetch()
    assert batch.dataset_id == "engagements"
    assert batch.source == "engagements.json"
    assert str(scratch) not in batch.source
    assert batch.records == [base_record()]


def test_json_object_carries_its_own_dataset_name(scratch, base_record):
    path = dump_json(scratch / "export.json", {"dataset_id": "fy26",
                                               "records": [base_record()]})
    batch = JsonCrm(path).fetch()
    assert (batch.dataset_id, batch.records) == ("fy26", [base_record()])
    assert JsonCrm(path, dataset_id="override").fetch().dataset_id == "override"


def test_a_json_file_that_is_not_rows_is_refused(scratch, base_record):
    path = dump_json(scratch / "bad.json", {"rows": [base_record()]})
    with pytest.raises(ValueError):
        JsonCrm(path).fetch()


def test_csv_list_cells_are_split_and_the_row_still_audits(scratch, base_record):
    row = base_record(non_audit_services="tax;payroll", register_particulars="name;address")
    batch = CsvCrm(dump_csv(scratch / "crm.csv", row), dataset_id="crm-2026").fetch()
    assert batch.source == "crm.csv"
    assert batch.records[0]["non_audit_services"] == "tax;payroll"

    report = pipe(SandboxTransport()).run(batch.records)
    record = report["records"][0]
    assert record["quality"] == "verified"
    assert record["payable"] > 0


def test_csv_without_an_engagement_key_is_refused(scratch):
    path = scratch / "partial.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("client,audit_fee_cents\nAcme GmbH,20000\n")
    with pytest.raises(ValueError, match="external_id"):
        CsvCrm(path).fetch()


def test_sync_appends_one_outcome_per_engagement_and_charges_nothing_uncleared(
        scratch, base_record):
    source = JsonCrm(dump_json(scratch / "engagements.json", [
        base_record(), base_record(external_id="A2", client="Beta AG")]),
        dataset_id="crm-2026")
    transport = SandboxTransport()
    outcomes = scratch / "out" / "outcomes.jsonl"
    report, written = sync(source, pipe(transport), outcomes)

    assert written == 2
    lines = outcomes.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert transport.charge_calls == 0
    first = json.loads(lines[0])
    assert first["external_id"] == "A1"
    assert first["payable"] > 0
    assert first["status"] == "awaiting_human"
    assert "binding" not in first
    assert first["run_id"] == report["run_id"]


def test_sync_pays_only_the_instruction_named_in_clearance(scratch, base_record):
    source = JsonCrm(dump_json(scratch / "engagements.json", [base_record()]),
                     dataset_id="crm-2026")
    transport = SandboxTransport()
    pipeline = pipe(transport)
    outcomes = scratch / "outcomes.jsonl"

    first, _ = sync(source, pipeline, outcomes)
    target = first["records"][0]["agreements"][0]["id"]
    assert transport.charge_calls == 0

    second, _ = sync(source, pipeline, outcomes, clearance=[target])
    assert transport.charge_calls == 1
    assert second["settlement"]["settled"] == 1
    assert second["settlement"]["settled_now_cents"] == 20_000


def test_sync_refuses_a_batch_from_another_dataset(scratch, base_record):
    source = JsonCrm(dump_json(scratch / "other.json", [base_record()]),
                     dataset_id="someone-elses")
    outcomes = scratch / "outcomes.jsonl"
    with pytest.raises(ValueError, match="someone-elses"):
        sync(source, pipe(SandboxTransport()), outcomes)
    assert not outcomes.exists()


def test_write_outcomes_reports_what_it_wrote(scratch, base_record):
    transport = SandboxTransport()
    report = pipe(transport).run([base_record()])
    rows = outcome_rows(report)
    assert [row["external_id"] for row in rows] == ["A1"]
    assert rows[0]["settled_cents"] == 0
    assert write_outcomes(scratch / "nested" / "runs.jsonl", report) == 1
    again = json.loads((scratch / "nested" / "runs.jsonl").read_text(encoding="utf-8"))
    assert again["run_id"] == report["run_id"]
