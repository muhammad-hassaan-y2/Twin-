"""A training corpus is a claim about what the firm does, so it is tested as one.

Two things would make this file worse than nothing. The first is a sentence that states a figure
no case produced: a model trained on it learns to dress up an invented threshold as law, which is
the one failure the rest of this subsystem is built to prevent. The second is a corpus that was
written rather than derived - a table of examples that happens to look like the firm's output and
stops describing it the moment a threshold moves. So the tests move the corpus's numbers and
watch the rows move with them, and remove one fact from a row and watch the checker catch the
sentence that rested on it.

The upload path is tested against a gateway that records what it was asked for and answers. The
guards around it - three environment variables and an explicit `--yes` - are tested in both
directions, because a script that trains by accident is not a script, and one that refuses
forever is not either.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

import pytest

from twin.audit.agents import Priors, QUESTIONS
from twin.audit.corpus import DATA_DIR
from twin.audit.finetune import (AUDIT_FEE_CENTS, PREFERENCE, SIDECAR, SUPERVISED, Opener, build,
                                 check, dumps, shift, sweep, train, write)
from twin.eval.grounding import ungrounded


class Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class Gateway:
    """Records every request and answers the way a fine-tuning endpoint has to."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, request: Any) -> Response:
        body = request.data or b""
        self.calls.append({"url": request.full_url, "body": body,
                           "headers": {k.lower(): v for k, v in request.headers.items()}})
        if request.full_url.endswith("/files"):
            return Response({"id": "file-abc123", "bytes": len(body), "purpose": "fine-tuning"})
        return Response({"id": "ftjob-9", "status": "queued",
                         "training_file": json.loads(body)["training_file"]})


def header(call: dict[str, Any], name: str) -> str:
    """A request header, read the way urllib wrote it - it capitalises what it is given."""
    return call["headers"].get(name.lower(), "")


@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    built = build()
    problems = check(built)
    assert problems == [], f"the shipped corpus does not check clean: {problems}"
    return built


@pytest.fixture()
def box():
    """A directory of the test's own; `tmp_path` cannot be created on this machine."""
    return Path(tempfile.mkdtemp(prefix="twin-finetune-"))


@pytest.fixture()
def monkey_env(monkeypatch):
    """The three settings a real run needs, pointed at a gateway that is not real."""
    monkeypatch.delenv("TWIN_FINE_TUNE_BASE", raising=False)
    monkeypatch.delenv("TWIN_FINE_TUNE_KEY", raising=False)
    monkeypatch.delenv("TWIN_FINE_TUNE_MODEL", raising=False)

    def configure(base: str = "https://fine-tune.test/v1", key: str = "k-test",
                  model: str = "gpt-test-mini") -> None:
        monkeypatch.setenv("TWIN_FINE_TUNE_BASE", base)
        monkeypatch.setenv("TWIN_FINE_TUNE_KEY", key)
        monkeypatch.setenv("TWIN_FINE_TUNE_MODEL", model)

    return configure


class Args:
    def __init__(self, directory: str, yes: bool) -> None:
        self.dir = directory
        self.yes = yes
        self.rows = 3


# --------------------------------------------------------------------- the rows themselves

def test_no_row_states_a_figure_its_case_never_produced(doc):
    """The whole point of the corpus, checked on every line rather than sampled."""
    offenders = []
    for row, provenance in zip(doc["supervised"], doc["meta"]["rows"]):
        said = row["messages"][2]["content"]
        silent = ungrounded(said, set(provenance["facts"]))
        if silent:
            offenders.append({"role": provenance["role"], "client": provenance["client"],
                              "figures": silent, "said": said})
    assert offenders == [], offenders
    # Control: take one fact away from the row that earned it and the sentence that quoted it
    # becomes the thing the checker exists to find.
    victim = next((i, row, meta) for i, (row, meta) in enumerate(
        zip(doc["supervised"], doc["meta"]["rows"]))
        if ungrounded(row["messages"][2]["content"], set()))
    index, _, meta = victim
    kept = set(meta["facts"])
    used = {token for token in ungrounded(doc["supervised"][index]["messages"][2]["content"], set())
            if token in kept}
    assert used, f"row {index} says no figure at all, so it proves nothing"
    stripped = {"supervised": doc["supervised"],
                "preference": doc["preference"],
                "meta": dict(doc["meta"], rows=[
                    dict(row, facts=sorted(set(row["facts"]) - used)) if i == index else row
                    for i, row in enumerate(doc["meta"]["rows"])])}
    caught = [warning for warning in check(stripped) if f"row {index}" in warning]
    assert caught, "removing a fact left the sentence that needed it unreported"


def test_the_rows_are_the_firm_moved_by_one_threshold(doc):
    """Change the law's number and the corpus has to change its sentences, or it was typed."""
    moved = build(shift(Priors.load(), "non_audit_fee_cap_percent"))
    said = [row["messages"][2]["content"] for row in moved["supervised"]]
    assert any("71% ceiling" in text for text in said), "the derived 70 became 71 in the file only"
    assert not any("70% ceiling" in text for text in said)
    assert len(moved["supervised"]) == len(doc["supervised"]), "the same cases, moved numbers"

    quiet = build(shift(Priors.load(), "materiality_percent_of_turnover"))
    assert quiet["meta"]["verdicts"] == doc["meta"]["verdicts"], "an absent rule cannot move"


def test_every_case_sits_on_a_boundary_it_was_derived_from():
    p = Priors.load()
    cap = p.value("non_audit_fee_cap_percent")
    initial = int(p.value("rotation_initial_max_years"))
    cases = sweep(p)
    fees = {case.non_audit_fee_cents for case in cases}
    assert int(AUDIT_FEE_CENTS * cap / 100.0) in fees, "no case sits exactly on the fee cap"
    assert int(AUDIT_FEE_CENTS * cap / 100.0) + 1 in fees, "and none crosses it by one cent"
    assert {case.years_auditing for case in cases} >= {initial, initial - 1}
    asked = [case.non_audit_services for case in cases if case.non_audit_services]
    assert any(len(words := service.split()) > 3 for pair in asked for service in pair), (
        "no case asks for something the prohibition plainly names")
    assert any(len(service.split()) == 1 for pair in asked for service in pair), (
        "no case asks the one-word question the firm escalates instead of deciding")


def test_the_corpus_covers_every_role_and_every_way_a_question_can_end(doc):
    rows = doc["meta"]["rows"]
    assert len(rows) == len(sweep(Priors.load())) * len(QUESTIONS)
    assert {row["role"] for row in rows} == {role for role, _ in QUESTIONS}
    verdicts = doc["meta"]["verdicts"]
    assert all(count > 0 for count in verdicts.values()), verdicts
    assert all(row["route"] == "rules" for row in rows), "a model wrote none of these sentences"
    silent = [row for row in rows if row["verdict"] == "silent"]
    assert len(silent) >= len(QUESTIONS), "one role in silence is an accident, not a taught answer"


def test_the_silence_is_taught_as_an_answer(doc):
    """A model has to learn that 'the law gives this firm no number' is the correct output."""
    materiality = [row for row, meta in zip(doc["supervised"], doc["meta"]["rows"])
                   if meta["role"] == "materiality-reviewer"]
    assert materiality, "the corpus lost the role the corpus cannot calibrate"
    assert all("no lawful number" in row["messages"][2]["content"] for row in materiality)
    assert len({row["messages"][2]["content"] for row in materiality}) == 1


# --------------------------------------------------------------------- what it is uploaded as

def test_the_lines_are_what_an_endpoint_accepts_and_the_provenance_is_elsewhere(doc):
    """A `meta` key inside a training line is a rejected file, so the sidecar carries it."""
    for row in doc["supervised"]:
        assert set(row) == {"messages"}
        assert [turn["role"] for turn in row["messages"]] == ["system", "user", "assistant"]
    for pair in doc["preference"]:
        assert set(pair) == {"prompt", "chosen", "rejected"}
        assert [turn["role"] for turn in pair["prompt"]["messages"]] == ["system", "user"]
        assert pair["chosen"]["role"] == pair["rejected"]["role"] == "assistant"
        offenders = ungrounded(pair["rejected"]["content"], set())
        assert offenders, f"the rejected answer invents nothing: {pair['rejected']['content']}"

    # Control: a pair whose two sides agree teaches nothing, and a rejected answer whose every
    # figure the case did produce is not a rejection at all. The checker has to name both, or the
    # preference file is decoration.
    first = doc["preference"][0]
    flat = {"supervised": doc["supervised"], "meta": doc["meta"],
            "preference": [dict(first, rejected=dict(first["rejected"],
                                                     content=first["chosen"]["content"]))]}
    assert any("both sides say the same thing" in warning for warning in check(flat))

    prompt = first["prompt"]["messages"][1]["content"]
    index = next(i for i, row in enumerate(doc["supervised"])
                 if row["messages"][1]["content"] == prompt)
    figures = set(doc["meta"]["rows"][index]["facts"])
    offender = ungrounded(first["rejected"]["content"], figures)[0]
    calm = next(token for token in ungrounded(first["chosen"]["content"], set()) if token != offender)
    rewritten = re.sub(rf"(?<!\d){re.escape(offender)}(?!\d)", calm, first["rejected"]["content"])
    assert rewritten != first["rejected"]["content"]
    harmless = {"supervised": doc["supervised"], "meta": doc["meta"],
                "preference": [dict(first, rejected=dict(first["rejected"], content=rewritten))]}
    assert any("states nothing the case denies" in warning for warning in check(harmless)), (
        check(harmless))

    orphan = {"supervised": doc["supervised"], "meta": doc["meta"],
              "preference": [dict(first, prompt={"messages": [
                  {"role": "system", "content": "SYSTEM"},
                  {"role": "user", "content": "a prompt this corpus never taught"}]})]}
    assert any("prompt is not a row" in warning for warning in check(orphan)), check(orphan)


def test_the_files_on_disk_are_this_build_and_not_an_edit(box, doc):
    """Someone can hand-tune a training file; that is the edit this comparison is for."""
    paths = write(doc, box)
    assert set(paths) == {"supervised", "preference", "sidecar"}
    assert paths["supervised"].read_text(encoding="utf-8").count("\n") == len(doc["supervised"])
    shipped = Path(DATA_DIR) / SUPERVISED
    assert shipped.read_text(encoding="utf-8") == dumps(doc["supervised"]), (
        "finetune-supervised.jsonl is stale: run python -m twin.audit.finetune build")
    assert (Path(DATA_DIR) / PREFERENCE).read_text(encoding="utf-8") == dumps(doc["preference"])
    sidecar = json.loads((Path(DATA_DIR) / SIDECAR).read_text(encoding="utf-8"))
    assert sidecar["counts"] == doc["meta"]["counts"]
    assert sidecar["trained_here"] is False
    assert sidecar["corpus"] == Priors.load().doc["derived_from"]
    assert sidecar["corpus"]["corpus_dir"] == "backend/.corpus"
    assert json.dumps(sidecar).count("Hassaan") == 0, "a person's home directory is not provenance"

    edited = write(doc, box)
    line = edited["supervised"].read_text(encoding="utf-8").split("\n")[0]
    edited["supervised"].write_text(line.replace("10 of at most", "12 of at most") + "\n",
                                    encoding="utf-8")
    assert edited["supervised"].read_text(encoding="utf-8") != dumps(doc["supervised"])


# ------------------------------------------------------------------------ the job that is not run

def test_nothing_uploads_until_this_machine_says_so(monkey_env, box):
    gateway: Opener = Gateway()
    paths = write(build(), box)

    assert train(Args(str(box), False), gateway) == 2
    assert gateway.calls == [], "an unconfigured machine still reached for the network"

    monkey_env()
    assert train(Args(str(box), False), gateway) == 2
    assert gateway.calls == [], "the endpoint was configured, which is not the same as consent"

    # Control: with both, exactly two files go up and exactly two jobs start.
    assert train(Args(str(box), True), gateway) == 0
    urls = [call["url"] for call in gateway.calls]
    assert urls == ["https://fine-tune.test/v1/files", "https://fine-tune.test/v1/fine_tuning/jobs",
                    "https://fine-tune.test/v1/files", "https://fine-tune.test/v1/fine_tuning/jobs"]
    methods = [json.loads(call["body"])["method"]["type"] for call in gateway.calls
               if call["url"].endswith("/jobs")]
    assert methods == ["supervised", "dpo"]
    assert json.loads(gateway.calls[1]["body"])["training_file"] == "file-abc123"
    assert json.loads(gateway.calls[1]["body"])["model"] == "gpt-test-mini"
    head = gateway.calls[0]["body"][:400].decode("utf-8")
    assert "name=\"purpose\"" in head and "fine-tuning" in head
    assert "filename=\"finetune-supervised.jsonl\"" in head
    assert header(gateway.calls[0], "content-type").startswith("multipart/form-data; boundary=")
    assert header(gateway.calls[0], "authorization") == "Bearer k-test"
    assert header(gateway.calls[1], "content-type") == "application/json"
    assert paths["supervised"].read_bytes() in gateway.calls[0]["body"], "the bytes must be the file"
    # The corpus on disk is unchanged by having been offered: this script cannot train locally.
    assert paths["supervised"].read_text(encoding="utf-8") == dumps(build()["supervised"])


def test_an_endpoint_that_names_no_file_starts_no_job(monkey_env, box):
    """A 200 with no id in it is not a success, and a second upload after it is not an option."""
    monkey_env()
    write(build(), box)

    def silent(request: Any) -> Response:
        return Response({"ok": True})

    assert train(Args(str(box), True), silent) == 1

    calls: list[str] = []

    def half(request: Any) -> Response:
        calls.append(request.full_url)
        if request.full_url.endswith("/files"):
            return Response({"id": "file-abc123"})
        raise OSError("the gateway closed")

    assert train(Args(str(box), True), half) == 1
    assert len([url for url in calls if url.endswith("/files")]) == 1


def test_the_preview_reads_like_a_firm_not_like_a_fixture(doc):
    """A human has to be able to tell whether this corpus is worth a training run."""
    for row in doc["supervised"][:12]:
        said = row["messages"][2]["content"]
        assert said and said[-1] in ".;", said
        assert len(said) <= 320, f"a line of an engagement file this long is a paragraph: {said}"
