"""Synthetic finance slices: preserve provenance, reject ambiguity, replace stale harvests."""

from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from itertools import product
from pathlib import Path
from urllib.parse import parse_qsl

import pytest

from twin.audit import corpus, priors
from twin.audit.corpus import FINANCE_SLICES, Fetched, finance_rows
from twin.audit.priors import derive_finance


@pytest.fixture(params=FINANCE_SLICES, ids=[spec[0] for spec in FINANCE_SLICES])
def spec(request):
    return request.param


def slice_document(spec):
    name, code, query = spec
    monthly = name == "economic_sentiment_index"
    dimensions = {"freq": "M" if monthly else "A", **dict(parse_qsl(query)), "s_adj": "SA"}
    periods = ("2024-01", "2024-02") if monthly else ("2023", "2024")
    rows = []
    for index, (geo, period) in enumerate(product(("ZZ", "EU27_2020"), periods)):
        values = dict(dimensions, geo=geo, time=period)
        rows.append({
            "dataset": code, "title": f"Synthetic {name}", **values,
            **{f"{key}_label": f"Label {value}" for key, value in values.items()},
            "value": (0, -2.5, 7, 12.25)[index], "flags": "p" if index % 2 else "e",
        })
    url = f"https://example.invalid/{code}?{query}"
    return {"name": name, "code": code, "query": query, "url": url,
            "source_url": url + "&source=synthetic", "label": f"Synthetic {name}",
            "rows": rows, "error": ""}


@pytest.fixture
def doc(spec):
    return slice_document(spec)


def json_stat(doc):
    """Encode the fixture independently, with nontrivial row-major cell offsets."""
    rows = doc["rows"]
    names = [key for key in rows[0]
             if key not in {"dataset", "title", "value", "flags"} and not key.endswith("_label")]
    codes = {dim: sorted({row[dim] for row in rows}, reverse=True) for dim in names}
    positions = {dim: {code: index for index, code in enumerate(codes[dim])} for dim in names}
    payload = {
        "version": "2.0", "class": "dataset", "label": doc["label"],
        "id": names, "size": [len(codes[dim]) for dim in names],
        "dimension": {dim: {"category": {
            "index": positions[dim],
            "label": {row[dim]: row[f"{dim}_label"] for row in rows},
        }} for dim in names},
        "value": {}, "status": {},
    }
    for row in rows:
        offset = 0
        for dim in names:
            offset = offset * len(codes[dim]) + positions[dim][row[dim]]
        payload["value"][str(offset)] = row["value"]
        payload["status"][str(offset)] = row["flags"]
    return payload


def assert_rejected(name, doc):
    with pytest.raises(ValueError):
        finance_rows(name, doc)
    block = derive_finance({name: doc})[name]
    assert block["error"]
    assert block["series"] == {} and block["geos"] == 0 and block["eu"] == ""


def test_finance_rows_preserve_every_dimension_value_label_and_flag(spec, doc):
    before = deepcopy(doc)
    expected = sorted(doc["rows"], key=lambda row: (row["geo"], row["time"]))
    rows = finance_rows(spec[0], doc)
    assert rows == expected
    assert all(row is not original for row in rows for original in doc["rows"])
    for row in rows:
        for key, value in parse_qsl(spec[2]):
            assert row[key] == value
        assert row["freq"] and row["s_adj"] and row["flags"]
    assert doc == before


@pytest.mark.parametrize("reverse", [False, True], ids=["forward", "reverse"])
def test_derive_keeps_latest_per_geo_with_all_dimensions_and_provenance(spec, doc, reverse):
    if reverse:
        doc["rows"].reverse()
    before = deepcopy(doc)
    block = derive_finance({spec[0]: doc})[spec[0]]
    assert "error" not in block
    assert block["table"] == spec[1] and block["label"] == doc["label"]
    assert block["query"] == doc["query"] and block["url"] == doc["url"]
    assert block["source_url"] == doc["source_url"]
    assert block["geos"] == 2 and block["eu"] == "EU27_2020"
    assert set(block["series"]) == {"ZZ", "EU27_2020"}
    for geo, record in block["series"].items():
        latest = max((row for row in doc["rows"] if row["geo"] == geo), key=lambda row: row["time"])
        assert record == dict(latest, query=doc["query"], url=doc["url"], source_url=doc["source_url"])
    assert doc == before


def test_equivalent_filter_order_is_accepted_and_original_query_preserved(spec, doc):
    doc["query"] = "&".join(reversed(doc["query"].split("&")))
    assert finance_rows(spec[0], doc)
    block = derive_finance({spec[0]: doc})[spec[0]]
    assert block["query"] == doc["query"]
    assert all(row["query"] == doc["query"] for row in block["series"].values())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, False, "12.25", "", None],
                         ids=["nan", "positive-infinity", "negative-infinity", "true", "false",
                              "numeric-string", "empty-string", "null"])
def test_non_numeric_or_nonfinite_values_invalidate_the_entire_slice(spec, doc, value):
    doc["rows"][0]["value"] = value
    assert_rejected(spec[0], doc)


@pytest.mark.parametrize("fault", ["missing-query", "non-string-query", "empty-query", "wrong-query",
                                   "extra-filter", "duplicate-filter", "malformed-query",
                                   "wrong-code", "wrong-row-dataset", "wrong-name", "source-error"])
def test_identity_and_query_mismatches_cannot_become_finance_priors(spec, doc, fault):
    if fault == "missing-query":
        del doc["query"]
    elif fault == "non-string-query":
        doc["query"] = None
    elif fault == "empty-query":
        doc["query"] = ""
    elif fault == "wrong-query":
        key = parse_qsl(spec[2])[0][0]
        doc["query"] = f"{key}=WRONG"
    elif fault == "extra-filter":
        doc["query"] += "&unexpected=VALUE"
    elif fault == "duplicate-filter":
        doc["query"] += "&" + spec[2].split("&")[0]
    elif fault == "malformed-query":
        doc["query"] = "not-a-query"
    elif fault == "wrong-code":
        doc["code"] = "other_dataset"
    elif fault == "wrong-row-dataset":
        doc["rows"][0]["dataset"] = "other_dataset"
    elif fault == "wrong-name":
        doc["name"] = "unsupported_slice"
    else:
        doc["error"] = "source refused despite stale rows"
    assert_rejected(spec[0], doc)


@pytest.mark.parametrize("spec,dimension", [(spec, key) for spec in FINANCE_SLICES
                                           for key, _ in parse_qsl(spec[2])],
                         ids=[f"{spec[0]}-{key}" for spec in FINANCE_SLICES for key, _ in parse_qsl(spec[2])])
@pytest.mark.parametrize("missing", [False, True], ids=["wrong-value", "missing-value"])
def test_each_requested_dimension_must_be_present_and_match(spec, dimension, missing):
    doc = slice_document(spec)
    if missing:
        del doc["rows"][0][dimension]
    else:
        doc["rows"][0][dimension] = "WRONG"
    assert_rejected(spec[0], doc)


@pytest.mark.parametrize("field", ["value", "flags", "freq"])
@pytest.mark.parametrize("reverse", [False, True], ids=["forward", "reverse"])
def test_conflicting_same_geo_period_cells_are_rejected_in_either_order(spec, doc, field, reverse):
    # A conflict in an older period must not be hidden by a newer, otherwise valid cell.
    for original in (doc["rows"][0], doc["rows"][1]):
        changed = deepcopy(doc)
        conflict = dict(original)
        conflict[field] = original[field] + 1 if field == "value" else "different"
        changed["rows"].append(conflict)
        if reverse:
            changed["rows"].reverse()
        assert_rejected(spec[0], changed)


def test_exact_duplicates_are_deduplicated_without_losing_the_latest_cell(spec, doc):
    expected_rows = finance_rows(spec[0], doc)
    expected_priors = derive_finance({spec[0]: doc})
    doc["rows"].extend(deepcopy(doc["rows"]))
    assert finance_rows(spec[0], doc) == expected_rows
    assert derive_finance({spec[0]: doc}) == expected_priors


@pytest.mark.parametrize("fault", ["empty", "not-a-list", "not-a-row", "missing-geo", "missing-time"])
def test_empty_or_malformed_rows_cannot_leave_a_partial_series(spec, doc, fault):
    if fault == "empty":
        doc["rows"] = []
    elif fault == "not-a-list":
        doc["rows"] = {}
    elif fault == "not-a-row":
        doc["rows"].append(None)
    else:
        doc["rows"][0]["geo" if fault == "missing-geo" else "time"] = ""
    assert_rejected(spec[0], doc)


def test_unsupported_slices_are_excluded_without_muting_supported_ones():
    documents = {spec[0]: slice_document(spec) for spec in FINANCE_SLICES}
    expected = derive_finance(documents)
    unsupported = dict(slice_document(FINANCE_SLICES[0]), name="unsupported_slice")
    with pytest.raises(ValueError, match="unsupported"):
        finance_rows("unsupported_slice", unsupported)
    documents["unsupported_slice"] = unsupported
    assert derive_finance(documents) == expected
    assert derive_finance({"unsupported_slice": unsupported}) == {}
    assert derive_finance({}) == {}


def test_euro_area_is_not_substituted_for_an_eu_aggregate(spec, doc):
    from twin.audit.agents import Priors

    for row in doc["rows"]:
        if row["geo"] == "EU27_2020":
            row["geo"] = "EA20"
            row["geo_label"] = "Euro area"
    finance = derive_finance({spec[0]: doc})
    assert finance[spec[0]]["eu"] == ""
    source = Priors({"finance": finance})
    assert source.finance(spec[0], "EA20")["geo"] == "EA20"
    assert source.finance(spec[0], "absent-country") == {}


@pytest.fixture
def isolated_harvest(monkeypatch):
    # tmp_path is broken on this host; neither the corpus nor tracked manifests may be touched.
    with tempfile.TemporaryDirectory(prefix="twin-finance-tests-") as directory:
        root = Path(directory)
        for module in (corpus, priors):
            monkeypatch.setattr(module, "CORPUS_DIR", root / "corpus")
            monkeypatch.setattr(module, "DATA_DIR", root / "data")

        def no_network(*args, **kwargs):
            pytest.fail("finance regressions must never contact an external service")

        monkeypatch.setattr(corpus, "fetch", no_network)
        monkeypatch.setattr(corpus.urllib.request, "urlopen", no_network)
        yield root


def expected_url(spec):
    return corpus.EUROSTAT_URL.format(code=spec[1]) + f"?format=JSON&lang=EN&{spec[2]}&lastTimePeriod=5"


def fetched_json(payload):
    body = json.dumps(payload)
    return Fetched(200, len(body.encode("utf-8")), body, "")


def fake_fetch(monkeypatch, replies):
    calls = []

    def fetch(url, accept, lang="eng", **kwargs):
        assert accept == "application/json" and lang == ""
        calls.append(url)
        assert url in replies, "only the requested finance slices may be fetched"
        return replies[url]

    monkeypatch.setattr(corpus, "fetch", fetch)
    return calls


def assert_manifest_matches_files(manifest, replies):
    saved = json.loads((corpus.DATA_DIR / "finance-manifest.json").read_text(encoding="utf-8"))
    assert saved == manifest
    assert manifest["harvested_at"] and manifest["user_agent"] == corpus.USER_AGENT
    assert "CC BY 4.0" in manifest["licence"]
    assert [row["name"] for row in manifest["sources"]] == [spec[0] for spec in FINANCE_SLICES]
    documents = {}
    unavailable = []
    for spec, source in zip(FINANCE_SLICES, manifest["sources"]):
        name, code, query = spec
        doc = json.loads((corpus.CORPUS_DIR / "finance" / f"{name}.json").read_text(encoding="utf-8"))
        documents[name] = doc
        assert doc["name"] == name and doc["code"] == code and doc["query"] == query
        assert doc["url"] == expected_url(spec)
        assert source == {
            "name": name, "code": code, "query": query, "url": expected_url(spec),
            "status": replies[expected_url(spec)].status, "bytes": replies[expected_url(spec)].bytes,
            "error": doc["error"], "title": doc["label"], "rows": len(doc["rows"]),
            "geos": len({row["geo"] for row in doc["rows"]}),
            "times": sorted({row["time"] for row in doc["rows"]}),
        }
        if doc["error"]:
            assert doc["rows"] == []
            unavailable.append({"name": name, "code": code, "status": source["status"],
                                "reason": doc["error"]})
    assert manifest["unavailable"] == unavailable
    assert manifest["counts"] == {
        "slices_fetched": len(FINANCE_SLICES) - len(unavailable), "slices_refused": len(unavailable),
        "rows": sum(len(doc["rows"]) for doc in documents.values()),
    }
    return documents


@pytest.mark.parametrize("refused", [None, *(spec[0] for spec in FINANCE_SLICES)])
def test_harvest_saves_unstrided_cells_and_a_truthful_manifest(isolated_harvest, monkeypatch, refused):
    documents = {spec[0]: slice_document(spec) for spec in FINANCE_SLICES}
    replies = {expected_url(spec): (Fetched(503, 0, "", "synthetic unavailable") if spec[0] == refused
                                   else fetched_json(json_stat(documents[spec[0]])))
               for spec in FINANCE_SLICES}
    calls = fake_fetch(monkeypatch, replies)
    monkeypatch.setattr(corpus, "ROW_CAP", 1)  # Broad-table thinning must not touch finance slices.
    manifest = corpus.harvest_finance(quiet=True)
    assert calls == [expected_url(spec) for spec in FINANCE_SLICES]
    saved = assert_manifest_matches_files(manifest, replies)
    for name, doc in saved.items():
        if name == refused:
            assert doc["error"] == "synthetic unavailable" and doc["rows"] == []
        else:
            assert doc["error"] == ""
            assert doc["rows"] == sorted(documents[name]["rows"], key=lambda row: (row["geo"], row["time"]))
            assert doc["label"] == documents[name]["label"]
    assert priors.load_finance() == saved
    derived = derive_finance()
    for name, block in derived.items():
        if name == refused:
            assert block["error"] and not block["series"]
        else:
            assert block["geos"] == 2 and not block.get("error")
            assert all(row["url"] == saved[name]["url"] for row in block["series"].values())


def bad_response(spec, fault):
    if fault == "http":
        return Fetched(503, 0, "", "")
    if fault == "transport":
        return Fetched(0, 0, "", "synthetic connection failure")
    if fault == "empty-body":
        return Fetched(200, 0, "", "")
    if fault == "invalid-json":
        return Fetched(200, 1, "{", "")
    if fault == "non-object":
        return fetched_json([])
    doc = slice_document(spec)
    if fault == "wrong-filter":
        dimension = parse_qsl(spec[2])[0][0]
        for row in doc["rows"]:
            row[dimension] = "WRONG"
    elif fault == "missing-filter":
        dimension = parse_qsl(spec[2])[0][0]
        for row in doc["rows"]:
            del row[dimension]
            del row[f"{dimension}_label"]
    payload = json_stat(doc)
    if fault == "empty-values":
        payload["value"] = {}
    elif fault == "null-values":
        payload["value"] = {key: None for key in payload["value"]}
    elif fault == "bad-index":
        payload["dimension"]["geo"]["category"]["index"] = {"ZZ": 0, "EU27_2020": 0}
    elif fault == "bad-size":
        payload["size"][0] = True
    elif fault == "duplicate-dimension":
        payload["id"][1] = payload["id"][0]
    elif fault == "bad-offset":
        payload["value"]["999999"] = 1
    elif fault == "bad-label":
        payload["label"] = []
    elif fault in {"nan", "infinity", "boolean", "string"}:
        payload["value"][next(iter(payload["value"]))] = {
            "nan": float("nan"), "infinity": float("inf"), "boolean": True, "string": "12.25",
        }[fault]
    return fetched_json(payload)


@pytest.mark.parametrize("fault", ["http", "transport", "empty-body", "invalid-json", "non-object",
                                   "empty-values", "null-values", "wrong-filter", "missing-filter",
                                   "bad-index", "bad-size", "duplicate-dimension", "bad-offset",
                                   "bad-label", "nan", "infinity", "boolean", "string"])
def test_failed_empty_or_malformed_harvest_replaces_stale_rows(isolated_harvest, monkeypatch, fault):
    replies = {expected_url(spec): fetched_json(json_stat(slice_document(spec))) for spec in FINANCE_SLICES}
    calls = fake_fetch(monkeypatch, replies)
    first = corpus.harvest_finance(quiet=True)
    assert first["counts"]["slices_fetched"] == len(FINANCE_SLICES)
    assert all(block["series"] for block in derive_finance().values())

    replies.update({expected_url(spec): bad_response(spec, fault) for spec in FINANCE_SLICES})
    manifest = corpus.harvest_finance(quiet=True)
    assert calls == [expected_url(spec) for spec in FINANCE_SLICES] * 2
    saved = assert_manifest_matches_files(manifest, replies)
    assert manifest["counts"] == {"slices_fetched": 0, "slices_refused": len(FINANCE_SLICES), "rows": 0}
    assert len(manifest["unavailable"]) == len(FINANCE_SLICES)
    assert all(doc["error"] and doc["rows"] == [] and doc["label"] == "" for doc in saved.values())
    assert priors.load_finance() == saved
    derived = derive_finance()
    assert set(derived) == {spec[0] for spec in FINANCE_SLICES}
    assert all(block["error"] and block["series"] == {} for block in derived.values())


@pytest.mark.parametrize("only_finance", [False, True], ids=["full-harvest", "only-finance"])
@pytest.mark.parametrize("as_json", [False, True], ids=["normal-cli", "json-cli"])
@pytest.mark.parametrize("failed", [False, True], ids=["success", "finance-failure"])
def test_cli_dispatches_finance_and_reports_its_exit_status(isolated_harvest, monkeypatch, capsys,
                                                          only_finance, as_json, failed):
    replies = {expected_url(spec): (bad_response(spec, "http") if failed
                                   else fetched_json(json_stat(slice_document(spec)))) for spec in FINANCE_SLICES}
    calls = fake_fetch(monkeypatch, replies)
    broad_calls = []
    broad_manifest = {"sources": [], "counts": {"statutes_fetched": 1}, "unavailable": []}

    def harvest(*, quiet, only):
        assert not only_finance, "--only finance must not fetch statutes or broad tables"
        broad_calls.append((quiet, only))
        return deepcopy(broad_manifest)

    monkeypatch.setattr(corpus, "harvest", harvest)
    argv = (["--only", "finance"] if only_finance else []) + (["--json"] if as_json else [])
    result = corpus.main(argv)
    assert result == (1 if failed else 0)
    assert calls == [expected_url(spec) for spec in FINANCE_SLICES]
    assert broad_calls == ([] if only_finance else [(as_json, "")])
    saved = json.loads((corpus.DATA_DIR / "finance-manifest.json").read_text(encoding="utf-8"))
    assert_manifest_matches_files(saved, replies)
    output = capsys.readouterr().out
    if as_json:
        summary = json.loads(output)
        assert (summary if only_finance else summary["finance"])["counts"] == saved["counts"]
    else:
        assert "finance-manifest.json" in output
    broad_path = corpus.DATA_DIR / "manifest.json"
    if only_finance:
        assert not broad_path.exists()
    else:
        assert json.loads(broad_path.read_text(encoding="utf-8")) == broad_manifest
