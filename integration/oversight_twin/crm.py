"""CRM and tool exports in, audit outcomes back out.

The adapters read files, not a vendor API: a CRM export and a hand-built tool dump are the same
shape once they are rows. Provenance is the file's own name, never this machine's path. Outcomes
are appended as JSON lines so a CRM sync can read one row per engagement without replaying a run.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class CrmBatch:
    dataset_id: str
    records: list[dict[str, Any]]
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {"dataset_id": self.dataset_id, "records": len(self.records), "source": self.source}


class CrmSource(Protocol):
    def fetch(self) -> CrmBatch:
        ...


class JsonCrm:
    """A list of records, or an object with a `records` list and optional `dataset_id`."""

    def __init__(self, path: str | Path, dataset_id: str | None = None) -> None:
        self.path = Path(path)
        self.dataset_id = dataset_id

    def fetch(self) -> CrmBatch:
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(doc, list):
            records, dataset_id = doc, self.dataset_id
        elif isinstance(doc, dict) and isinstance(doc.get("records"), list):
            records, dataset_id = doc["records"], self.dataset_id or doc.get("dataset_id")
        else:
            raise ValueError(f"{self.path.name} must hold a list of records or a records object")
        if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
            raise ValueError(f"{self.path.name} must hold objects, one per engagement")
        dataset_id = dataset_id or self.path.stem
        return CrmBatch(dataset_id, records, self.path.name)


class CsvCrm:
    """One row per engagement. List cells are split on semicolons."""

    REQUIRED_COLUMNS = ("external_id", "client")

    def __init__(self, path: str | Path, dataset_id: str | None = None) -> None:
        self.path = Path(path)
        self.dataset_id = dataset_id

    def fetch(self) -> CrmBatch:
        with self.path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = tuple(name.strip() for name in reader.fieldnames or ())
            missing = [name for name in self.REQUIRED_COLUMNS if name not in fields]
            if missing:
                raise ValueError(f"{self.path.name} is missing column(s): {', '.join(missing)}")
            records = [{name.strip(): value for name, value in row.items()} for row in reader]
        return CrmBatch(self.dataset_id or self.path.stem, records, self.path.name)


def outcome_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The part of a run a CRM needs, one row per engagement."""
    rows = []
    for record in report["records"]:
        rows.append({
            "run_id": report["run_id"],
            "dataset_id": report["dataset_id"],
            "external_id": record["external_id"],
            "status": record["state"],
            "quality": record["quality"],
            "issue_codes": sorted({issue["code"] for issue in record["issues"]}),
            "verdicts": record["verdicts"],
            "payable": record["payable"],
            "settled_cents": record["settled_cents"],
            "agreements": [
                {"id": agreement["id"], "role": agreement["role"], "state": agreement["state"],
                 "provider_ref": agreement["provider_ref"],
                 "review_required": agreement["review_required"]}
                for agreement in record["agreements"]
            ],
        })
    return sorted(rows, key=lambda row: row["external_id"])


def write_outcomes(path: str | Path, report: dict[str, Any]) -> int:
    """Append one JSON line per engagement; return how many were written."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = outcome_rows(report)
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return len(rows)


def sync(source: CrmSource, pipeline: Any, outcomes_path: str | Path, *,
         clearance: list[str] | None = None) -> tuple[dict[str, Any], int]:
    """Fetch, audit, settle what was cleared, and append the CRM's view of the result."""
    batch = source.fetch()
    if batch.dataset_id != pipeline.dataset_id:
        raise ValueError(f"batch belongs to {batch.dataset_id!r}, not {pipeline.dataset_id!r}")
    report = pipeline.run(batch.records, clearance=clearance)
    return report, write_outcomes(outcomes_path, report)
