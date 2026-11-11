"""Shared fixtures for the integration tests.

`tmp_path` is unusable on this host, so scratch files get a temporary directory of their own.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

BASE = {
    "external_id": "A1", "client": "Acme GmbH", "audit_fee_cents": 20_000,
    "non_audit_fee_cents": 1_000, "is_pie": True, "years_auditing": 3,
    "partner_years": 2, "tender_held": True, "firm_fee_from_client_cents": 1_000,
    "firm_total_fees_cents": 100_000, "kyc_checked_years_ago": 1,
    "non_audit_services": ["tax"], "client_geo": "DE",
    "standard_vat_rate_percent": 19.0, "reduced_vat_rate_percent": 7.0,
    "supply_in_reduced_category": False,
}


@pytest.fixture
def base_record():
    def make(**changes):
        row = dict(BASE)
        row.update(changes)
        return row
    return make


@pytest.fixture
def scratch():
    directory = tempfile.mkdtemp(prefix="oversight-tests-")
    try:
        yield Path(directory)
    finally:
        shutil.rmtree(directory, ignore_errors=True)
