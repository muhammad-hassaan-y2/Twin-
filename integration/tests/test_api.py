"""The HTTP edge: bearer auth, fail-closed health, runs, lookups and named clearances.

Every test that pays uses the simulated rail. The edge is where a setting can be missing, so
the unconfigured service and the missing token are tested as answers, not as crashes.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from oversight_twin.api import SettlementService, create_app
from oversight_twin.pipeline import Pipeline
from swarm_oversight.monitor import Limits
from twin.payments.paypal import SandboxTransport

TOKEN = "test-token-not-a-secret"
OPEN = Limits(per_agent=10**9, per_payee=10**9, window=10, long_window=60, merge="both")


def build(transport, token=TOKEN):
    def factory(dataset_id: str, currency: str) -> Pipeline:
        return Pipeline(transport, dataset_id=dataset_id, payee="Ashgrove Audit LLP",
                        currency=currency, limits=OPEN, rail="simulated")

    service = SettlementService(factory, rail="simulated")
    return TestClient(create_app(token=token, service=service)), service


def auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def post_run(client, records, *, dataset="crm-2026", clearance=(), currency="USD"):
    return client.post("/v1/runs", headers=auth(), json={
        "dataset_id": dataset, "records": records,
        "clearance": list(clearance), "currency": currency})


def test_health_without_a_service_names_what_is_missing():
    client = TestClient(create_app(token=TOKEN, service=None, reason="OVERSIGHT_PAYEE is not set"))
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "unconfigured", "why": "OVERSIGHT_PAYEE is not set"}
    assert client.post("/v1/runs", headers=auth(), json={
        "dataset_id": "crm", "records": [{}]}).status_code == 503


def test_health_never_echoes_the_token():
    client, _ = build(SandboxTransport())
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["token_configured"] is True
    assert body["rail"] == "simulated"
    assert TOKEN not in response.text


@pytest.mark.parametrize("headers", [
    {}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN},
    {"Authorization": f"Basic {TOKEN}"},
], ids=["missing", "wrong", "scheme-less", "wrong-scheme"])
def test_a_run_without_a_valid_bearer_token_is_refused(base_record, headers):
    client, _ = build(SandboxTransport())
    response = client.post("/v1/runs", headers=headers, json={
        "dataset_id": "crm-2026", "records": [base_record()]})
    assert response.status_code == 401


def test_no_configured_token_refuses_everything(monkeypatch, base_record):
    monkeypatch.delenv("OVERSIGHT_API_TOKEN", raising=False)
    service = SettlementService(
        lambda dataset, currency: Pipeline(SandboxTransport(), dataset_id=dataset,
                                           payee="Firm", currency=currency,
                                           limits=OPEN, rail="simulated"),
        rail="simulated")
    client = TestClient(create_app(service=service))
    assert client.get("/health").json()["token_configured"] is False
    assert post_run(client, [base_record()]).status_code == 401


def test_the_token_can_come_from_the_environment(monkeypatch, base_record):
    monkeypatch.setenv("OVERSIGHT_API_TOKEN", TOKEN)
    service = SettlementService(
        lambda dataset, currency: Pipeline(SandboxTransport(), dataset_id=dataset,
                                           payee="Firm", currency=currency,
                                           limits=OPEN, rail="simulated"),
        rail="simulated")
    client = TestClient(create_app(service=service))
    assert post_run(client, [base_record()]).status_code == 200


def test_a_run_prices_instructions_and_charges_nothing(base_record):
    transport = SandboxTransport()
    client, _ = build(transport)
    response = post_run(client, [base_record()])
    assert response.status_code == 200
    report = response.json()
    assert report["dataset_id"] == "crm-2026"
    assert report["currency"] == "USD"
    assert report["quality"] == {"records": 1, "verified": 1, "review": 0, "blocked": 0,
                                 "issue_codes": {}}
    assert report["settlement"]["agreements"] == report["desks"]["payable"] > 0
    assert report["settlement"]["awaiting_human"] == report["settlement"]["agreements"]
    assert transport.charge_calls == 0


def test_clearing_by_name_pays_exactly_those_and_only_once(base_record):
    transport = SandboxTransport()
    client, _ = build(transport)
    report = post_run(client, [base_record()]).json()
    ids = [row["id"] for row in report["records"][0]["agreements"]]
    chosen = ids[:3]
    run_id = report["run_id"]

    cleared = client.post(f"/v1/runs/{run_id}/clear", headers=auth(),
                          json={"agreements": chosen})
    assert cleared.status_code == 200
    after = cleared.json()
    assert after["settlement"]["settled"] == 3
    assert after["settlement"]["settled_cents"] == 60_000
    assert transport.charge_calls == 3

    again = client.post(f"/v1/runs/{run_id}/clear", headers=auth(),
                        json={"agreements": chosen}).json()
    assert again["settlement"]["settled"] == 3
    assert again["settlement"]["settled_now_cents"] == 0
    assert transport.charge_calls == 3


def test_a_run_can_be_read_back_by_id(base_record):
    client, _ = build(SandboxTransport())
    report = post_run(client, [base_record()]).json()
    fetched = client.get(f"/v1/runs/{report['run_id']}", headers=auth())
    assert fetched.status_code == 200
    assert fetched.json()["run_id"] == report["run_id"]
    assert fetched.json()["records"][0]["external_id"] == "A1"


def test_unknown_runs_and_agreements_are_answers_not_crashes(base_record):
    client, _ = build(SandboxTransport())
    assert client.get("/v1/runs/nope", headers=auth()).status_code == 404
    assert client.post("/v1/runs/nope/clear", headers=auth(),
                       json={"agreements": ["x"]}).status_code == 404

    report = post_run(client, [base_record()]).json()
    foreign = client.post(f"/v1/runs/{report['run_id']}/clear", headers=auth(),
                          json={"agreements": ["crm-2026:A9:engagement-partner"]})
    assert foreign.status_code == 422
    assert "unknown agreement" in foreign.json()["detail"]


def test_one_dataset_cannot_spend_another_run(base_record):
    transport = SandboxTransport()
    client, _ = build(transport)
    first = post_run(client, [base_record()], dataset="alpha").json()
    second = post_run(client, [base_record()], dataset="beta").json()
    alpha_id = first["records"][0]["agreements"][0]["id"]
    beta_id = second["records"][0]["agreements"][0]["id"]
    assert alpha_id.startswith("alpha:A1:") and beta_id.startswith("beta:A1:")

    crossed = client.post(f"/v1/runs/{first['run_id']}/clear", headers=auth(),
                          json={"agreements": [beta_id]})
    assert crossed.status_code == 422
    assert transport.charge_calls == 0


@pytest.mark.parametrize("payload", [
    {"dataset_id": "crm", "records": []},
    {"dataset_id": "", "records": [{"client": "Acme"}]},
    {"dataset_id": "crm", "records": [{"client": "Acme"}], "currency": "usd"},
    {"dataset_id": "crm", "records": ["not-an-object"]},
], ids=["no-records", "empty-dataset", "lowercase-currency", "row-not-object"])
def test_a_bad_body_is_a_422(payload):
    client, _ = build(SandboxTransport())
    response = client.post("/v1/runs", headers=auth(), json=payload)
    assert response.status_code == 422


def test_an_empty_clearance_list_is_a_422(base_record):
    client, _ = build(SandboxTransport())
    report = post_run(client, [base_record()]).json()
    response = client.post(f"/v1/runs/{report['run_id']}/clear", headers=auth(),
                           json={"agreements": []})
    assert response.status_code == 422
