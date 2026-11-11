"""The fine-tuning corpus this firm can hand a model, and the one job that would use it.

Nothing in here trains a weight. `python -m twin.audit.finetune build` writes two JSONL files
and a sidecar of provenance; `train` uploads them to an endpoint that has to be configured on
purpose - `TWIN_FINE_TUNE_BASE`, `TWIN_FINE_TUNE_KEY`, `TWIN_FINE_TUNE_MODEL` - and then only
with `--yes`. This repository has never completed a training run, and the sidecar says so in
`trained_here` rather than letting a reader infer it from the files' existence.

What the corpus teaches is deliberately narrow. The twenty-six agents already decide from derived
citations, and the only thing a model is asked for in `agents.py` is one sentence of prose about
figures it was handed. So every row is exactly that call: the case's figures, the verdict the
rules reached, and the article the verdict came from on one side; the firm's own sentence on the
other. The preference file pairs each of those with the same case read against a threshold that
was off by one - the failure this project cannot tolerate, because a plausible threshold in
prose is indistinguishable from a real one to whoever reads it.

Every threshold in a row is derived. They come from `priors.json`, which is itself a derivation
from the harvested statutes, and each case sits exactly on, one year past, or one cent over one
of them, so the boundaries are arithmetic rather than a set of examples that happen to look
right. A client's own fee figures are the exception and are labelled where they are used: those
are facts a case brings, not law.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from twin.audit.agents import CLEAR, BREACH, HOLD, SILENT, Case, Firm, Priors, QUESTIONS
from twin.audit.corpus import DATA_DIR, STOPWORDS
from twin.eval.grounding import collect, ungrounded
from twin.planner.model import number_tokens

SUPERVISED = "finetune-supervised.jsonl"
PREFERENCE = "finetune-preference.jsonl"
SIDECAR = "finetune.meta.json"

FILES_URL = "/files"
JOBS_URL = "/fine_tuning/jobs"

SYSTEM = (
    "You are one agent of an EU statutory audit firm writing one line of an engagement file. The"
    " verdict has already been reached by the firm's rules and is given to you; the figures it was"
    " computed from are given to you, and so is the article of EU law the rule was read out of."
    " Say in one sentence what those figures mean for this client. Use no figure that is not in"
    " FACTS, restate no threshold that is not in FACTS, and where the law gives this firm no"
    " number, say that instead of supplying one."
)

# A client's engagement letter and the firm's own fee book: facts a case brings, not rules it is
# judged against. Every threshold a row quotes is derived; these two only decide what the derived
# percentage is a percentage of.
AUDIT_FEE_CENTS = 200_000
FIRM_TOTAL_CENTS = 4_000_000

ANSWERS = dict(QUESTIONS)


def _years(value: float | None) -> int:
    return int(value) if value else 0


def _haystack(priors: Priors, letter: str) -> str:
    """The words `match_service` reads for one category, in the order the statute prints them."""
    for category in priors.services.get("categories") or []:
        if category.get("letter") == letter:
            parts = [category.get("text", "")] + [sub.get("text", "") for sub in category["subs"]]
            return " ".join(parts)
    return ""


def ask_service(priors: Priors, letter: str, words: int = 5) -> str:
    """A service request phrased in the prohibition's own words, taken from the derived list.

    A hand-typed example would test this file's guess about what Article 5(1) says. Slicing the
    words out of the category the corpus actually printed tests the matcher.
    """
    keep = [word for word in re.findall(r"[a-z]+", _haystack(priors, letter).lower())
            if word not in STOPWORDS and len(word) > 2]
    return " ".join(dict.fromkeys(keep[:words]))


def thin_request(priors: Priors) -> str:
    """One word that exactly one category uses, so the matcher has one thing to grab and no more.

    This is the case the firm escalates rather than decides: a request that shares a single word
    with the prohibition is neither forbidden nor cleared, and the corpus has plenty of such words.
    """
    seen: dict[str, int] = {}
    for category in priors.services.get("categories") or []:
        words = {word for word in re.findall(r"[a-z]+", _haystack(priors, category["letter"]).lower())
                 if word not in STOPWORDS and len(word) > 2}
        for word in words:
            seen[word] = seen.get(word, 0) + 1
    alone = sorted(word for word, count in seen.items() if count == 1)
    return alone[0] if alone else ""


def sweep(priors: Priors) -> tuple[Case, ...]:
    """The clients a firm actually argues about, each placed on a derived boundary.

    One case per interesting distance from one threshold: exactly on it, one past it, and on the
    side the rule does not reach. A corpus of comfortably-clear cases would teach the shape of an
    audit sentence and none of its arithmetic.
    """
    initial = _years(priors.value("rotation_initial_max_years"))
    tendered = _years(priors.value("rotation_tendered_max_years"))
    outer = _years(priors.value("rotation_with_tender_max_years"))
    partner = _years(priors.value("key_partner_rotation_years"))
    cooling = _years(priors.value("partner_cooling_off_years"))
    comeback = _years(priors.value("auditor_return_cooldown_years"))
    retention = _years(priors.value("aml_record_retention_years"))
    cap = priors.value("non_audit_fee_cap_percent") or 0.0
    dependence = priors.value("fee_dependence_percent") or 0.0
    presumed = priors.value("participation_presumed_percent") or 0.0
    large = priors.band("large undertakings")
    sheet = float(large.get("balance_sheet_total_eur") or 0.0)
    turnover = float(large.get("net_turnover_eur") or 0.0)
    heads = float(large.get("average_employees") or 0.0)

    at_cap = int(AUDIT_FEE_CENTS * cap / 100.0)
    at_dependence = int(FIRM_TOTAL_CENTS * dependence / 100.0)
    booked = ask_service(priors, "c")
    thin = thin_request(priors)

    base = dict(is_pie=True, audit_fee_cents=AUDIT_FEE_CENTS,
                firm_total_fees_cents=FIRM_TOTAL_CENTS, turnover_eur=turnover / 2.0,
                balance_sheet_eur=sheet / 2.0, employees=heads / 2.0,
                partner_years=max(partner - 1, 0), years_since_previous=max(cooling, 1),
                non_audit_fee_cents=at_cap // 2, firm_fee_from_client_cents=at_dependence // 2,
                kyc_checked_years_ago=max(retention - 1, 0), file_retention_years=retention,
                # The six later desks ask about the firm's own conduct rather than the client's
                # accounts, so the standing facts are the boring ones: a fee agreed in advance, one
                # year of non-audit work, the report published and the register entry complete. Each
                # case that is interesting on one of those six says so by moving it.
                fee_arrangement="fixed in advance", non_audit_years=1,
                months_since_year_end=2, transparency_published=True, transparency_kept_years=6,
                audit_report_issued=True, committee_report_issued=True,
                register_status="registered", register_particulars=("a", "b", "c"))
    three = (AUDIT_FEE_CENTS,) * 3
    return (
        Case(client="Nordwind Textil AG", **{**base, "years_auditing": initial}),
        Case(client="Nordwind Textil AG", **{**base, "years_auditing": tendered + 1,
                                             "tender_held": True,
                                             "register_particulars": ("a", "c"),
                                             "audit_report_issued": False,
                                             "committee_report_issued": False}),
        Case(client="Nordwind Textil AG", **{**base, "years_auditing": outer + 1,
                                             "tender_held": True, "non_audit_years": 3,
                                             "prior_audit_fees_cents": three,
                                             "prior_non_audit_fees_cents": (at_cap // 2,) * 3}),
        Case(client="Halbe Druckerei GmbH", **{**base, "is_pie": False, "years_auditing": initial,
                                               "previously_audited": True,
                                               "years_since_previous": max(comeback - 1, 0)}),
        Case(client="Vantage Logistics NV", **{**base, "years_auditing": max(initial - 1, 0),
                                               "previously_audited": True,
                                               "years_since_previous": max(cooling - 1, 0),
                                               "fee_arrangement": "contingent on the outcome of the"
                                                                  " transaction"}),
        Case(client="Sable Health Holdings SA", **{**base, "years_auditing": max(initial - 2, 0),
                                                   "non_audit_fee_cents": at_cap,
                                                   "register_status": ""}),
        Case(client="Sable Health Holdings SA", **{**base, "years_auditing": max(initial - 2, 0),
                                                   "non_audit_fee_cents": at_cap + 1,
                                                   "committee_report_issued": False}),
        Case(client="Sable Health Holdings SA", **{**base, "years_auditing": max(initial - 2, 0),
                                                   "firm_fee_from_client_cents": at_dependence + 1,
                                                   "sustainability_assurance": True}),
        Case(client="Meridian Utilities PLC", **{**base, "years_auditing": max(initial - 2, 0),
                                                 "is_group": True,
                                                 "parent_holding_percent": presumed,
                                                 "turnover_eur": turnover * 2.0,
                                                 "balance_sheet_eur": sheet * 2.0,
                                                 "employees": heads * 2.0, "non_audit_years": 4,
                                                 "prior_audit_fees_cents": three,
                                                 "prior_non_audit_fees_cents": (at_cap + 1,) * 3}),
        Case(client="Meridian Utilities PLC", **{**base, "years_auditing": max(initial - 2, 0),
                                                 "is_group": True,
                                                 "parent_holding_percent": presumed / 2.0,
                                                 "non_audit_years": 3,
                                                 "prior_audit_fees_cents": (AUDIT_FEE_CENTS,),
                                                 "prior_non_audit_fees_cents": (at_cap,)}),
        Case(client="Kestrel Foods BV", **{**base, "years_auditing": max(initial - 2, 0),
                                           "non_audit_services": (booked,) if booked else (),
                                           "non_audit_fee_cents": at_cap // 2,
                                           "sustainability_assurance": True}),
        Case(client="Kestrel Foods BV", **{**base, "years_auditing": max(initial - 2, 0),
                                           "non_audit_services": (thin,) if thin else (),
                                           "sustainability_assurance": True,
                                           "fee_arrangement": ""}),
        Case(client="Aldermen Property Trust", **{**base, "years_auditing": max(initial - 2, 0),
                                                  "kyc_checked_years_ago": retention + 1,
                                                  "file_retention_years": max(retention - 1, 0),
                                                  "months_since_year_end": 6,
                                                  "transparency_published": False}),
        Case(client="Aldermen Property Trust", **{**base, "years_auditing": max(initial - 2, 0),
                                                  "kyc_checked_years_ago": max(retention - 1, 0),
                                                  "file_retention_years": retention,
                                                  "transparency_kept_years": 0,
                                                  "register_status": "lapsed"}),
    )


def user_prompt(finding: Any, case: Case) -> str:
    """The whole of what the agent was given, in the order it was given it."""
    facts = json.dumps(dict(finding.numbers, verdict=finding.verdict), sort_keys=True,
                       ensure_ascii=False)
    return (f"ROLE: {finding.role}\nASK: {finding.asks}\nCLIENT: {case.client}\n"
            f"PUBLIC-INTEREST ENTITY: {str(case.is_pie).lower()}\n"
            f"VERDICT: {finding.verdict}\nFACTS: {facts}\n"
            f"CITATION: {json.dumps(finding.cite, sort_keys=True, ensure_ascii=False)}")


def facts_of(finding: Any) -> set[str]:
    """Every figure this row is allowed to say, including the ones inside its own citation."""
    return (collect(dict(finding.numbers, verdict=finding.verdict))
            | number_tokens(json.dumps(finding.cite, sort_keys=True))
            | number_tokens(finding.role))


def shift(priors: Priors, name: str) -> Priors:
    """The same corpus read wrong by one unit, for the sentence that must never be preferred.

    The wrong threshold is derived from the right one rather than typed, so nothing a person
    invented here reaches a training file - and the case's own figures stay the honest ones.
    """
    doc = json.loads(json.dumps(priors.doc))
    prior = (doc.get("priors") or {}).get(name)
    if not prior or prior.get("value") is None:
        return priors
    prior["value"] = float(prior["value"]) + 1.0
    prior["quote"] = ""
    prior["state"] = "calibrated"
    return Priors(doc)


def stated_names(priors: Priors, finding: Any) -> list[str]:
    """Which derived thresholds this sentence prints, so a pair can move exactly one of them.

    Two priors can carry the same figure - the presumed holding and the tendered ceiling are both
    twenty - and moving the one the sentence did not use changes nothing, which the builder
    notices and reports rather than pairing anyway.
    """
    names = []
    for name in sorted(priors.doc.get("priors") or {}):
        value = priors.value(name)
        if value is None:
            continue
        said = f"{value:g}"
        if re.search(rf"(?<![\d.,]){re.escape(said)}(?![\d])", finding.sentence):
            names.append(name)
    return names


def build(priors: Priors | None = None) -> dict[str, Any]:
    """The three files' contents, in the order they will be written.

    Every row is produced by the same `Firm.review` the panels call, on the rule route, so the
    corpus cannot drift from the firm it describes.
    """
    p = priors or Priors.load()
    firm = Firm(p)
    cases = sweep(p)
    supervised: list[dict[str, Any]] = []
    preference: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    pairs: dict[str, int] = {}
    for case in cases:
        for finding in firm.review(case):
            prompt = user_prompt(finding, case)
            supervised.append({"messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": finding.sentence}]})
            rows.append({"role": finding.role, "client": case.client, "verdict": finding.verdict,
                         "route": finding.route, "cite": dict(finding.cite),
                         "facts": sorted(facts_of(finding))})
            allowed = facts_of(finding)
            stated = stated_names(p, finding)
            pair = None
            for name in stated:
                wrong = ANSWERS[finding.role](case, shift(p, name))
                if wrong.sentence != finding.sentence and ungrounded(wrong.sentence, allowed):
                    pair = (name, wrong)
                    break
            if pair is None:
                if stated:
                    skipped.append({"role": finding.role, "client": case.client, "priors": stated,
                                    "why": "moving any of them leaves a sentence the case grounds"})
                continue
            name, wrong = pair
            pairs[name] = pairs.get(name, 0) + 1
            preference.append({
                "prompt": {"messages": [{"role": "system", "content": SYSTEM},
                                        {"role": "user", "content": prompt}]},
                "chosen": {"role": "assistant", "content": finding.sentence},
                "rejected": {"role": "assistant", "content": wrong.sentence},
            })
    return {
        "supervised": supervised,
        "preference": preference,
        "meta": {
            "counts": {"supervised": len(supervised), "preference": len(preference),
                       "cases": len(cases), "roles": len(QUESTIONS), "skipped": len(skipped)},
            "verdicts": {verdict: sum(1 for row in rows if row["verdict"] == verdict)
                         for verdict in (CLEAR, BREACH, HOLD, SILENT)},
            "corpus": p.doc.get("derived_from", {}),
            "pair_coverage": dict(sorted(pairs.items())),
            "prohibition": {"celex": p.services.get("celex", ""),
                            "article": p.services.get("article", ""),
                            "categories": len(p.services.get("categories") or [])},
            "trained_here": False,
            "format": {"supervised": "one messages array per line, uploaded with purpose=fine-tuning",
                       "preference": "prompt/chosen/rejected per line, method type dpo"},
            "note": "No weight on this machine was updated by anything in this directory. `train` "
                    "uploads these files to an endpoint you configure yourself, and refuses to do "
                    "anything at all when it is not configured.",
            "skipped": skipped,
            "rows": rows,
        },
    }


def check(doc: dict[str, Any]) -> list[str]:
    """What would make this corpus not worth sending to a training run."""
    problems: list[str] = []
    rows, meta = doc["supervised"], doc["meta"]["rows"]
    if len(rows) != len(meta):
        problems.append(f"{len(rows)} sentences for {len(meta)} rows of provenance")
        return problems
    allowed: dict[str, set[str]] = {}
    for index, (row, provenance) in enumerate(zip(rows, meta)):
        if set(row) != {"messages"}:
            problems.append(f"row {index}: keys {sorted(row)} - a sidecar field would be rejected")
            continue
        messages = row["messages"]
        if [turn.get("role") for turn in messages] != ["system", "user", "assistant"]:
            problems.append(f"row {index}: not a system/user/assistant turn")
            continue
        figures = set(provenance["facts"])
        allowed[messages[1]["content"]] = figures
        offenders = ungrounded(messages[2]["content"], figures)
        if offenders:
            problems.append(f"row {index} ({provenance['role']}): figures no fact produced "
                            f"{offenders}")
        if not messages[2]["content"].strip():
            problems.append(f"row {index} ({provenance['role']}): nothing was said")
    for index, pair in enumerate(doc["preference"]):
        if set(pair) != {"prompt", "chosen", "rejected"}:
            problems.append(f"pair {index}: keys {sorted(pair)}")
            continue
        turns = [turn.get("role") for turn in pair["prompt"].get("messages", [])]
        if turns != ["system", "user"]:
            problems.append(f"pair {index}: a prompt of {turns}")
            continue
        if pair["chosen"].get("role") != "assistant" or pair["rejected"].get("role") != "assistant":
            problems.append(f"pair {index}: both sides have to be the assistant's answer")
            continue
        if pair["chosen"]["content"] == pair["rejected"]["content"]:
            problems.append(f"pair {index}: both sides say the same thing")
            continue
        figures = allowed.get(pair["prompt"]["messages"][1]["content"])
        if figures is None:
            problems.append(f"pair {index}: its prompt is not a row this corpus teaches")
        elif not ungrounded(pair["rejected"]["content"], figures):
            problems.append(f"pair {index}: the rejected sentence states nothing the case denies")
    return problems


def dumps(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows)


def write(doc: dict[str, Any], where: Path | None = None) -> dict[str, Path]:
    out = Path(where) if where else DATA_DIR
    out.mkdir(parents=True, exist_ok=True)
    paths = {"supervised": out / SUPERVISED, "preference": out / PREFERENCE,
             "sidecar": out / SIDECAR}
    paths["supervised"].write_text(dumps(doc["supervised"]), encoding="utf-8")
    paths["preference"].write_text(dumps(doc["preference"]), encoding="utf-8")
    paths["sidecar"].write_text(json.dumps(doc["meta"], indent=1, ensure_ascii=False,
                                           sort_keys=True) + "\n", encoding="utf-8")
    return paths


# --------------------------------------------------------------------- the one job

Opener = Callable[[urllib.request.Request], Any]


def _post(url: str, body: bytes, headers: dict[str, str], opener: Opener) -> dict[str, Any]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with opener(request) as answer:
        raw = answer.read().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw[:400]}


def upload(path: Path, base: str, key: str, opener: Opener = urllib.request.urlopen) -> str:
    """The documented file upload: multipart, purpose=fine-tuning, and the id the server hands back.

    Not a body shape of our own invention - `/files` takes the bytes, so this sends the bytes and
    keeps whatever name the server gives them, because a job can only cite a file by that name.
    """
    boundary = "twin-audit-finetune"
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\n"
            f"fine-tuning\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{path.name}\"\r\nContent-Type: application/json\r\n\r\n")
    body = head.encode("utf-8") + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")
    answer = _post(base.rstrip("/") + FILES_URL, body, {
        "Authorization": f"Bearer {key}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }, opener)
    if not answer.get("id"):
        raise RuntimeError(f"{base}{FILES_URL} took the corpus and named no file: {answer}")
    return str(answer["id"])


def create_job(file_id: str, base: str, key: str, model: str, method: str,
               opener: Opener = urllib.request.urlopen) -> dict[str, Any]:
    body = json.dumps({"model": model, "training_file": file_id,
                       "method": {"type": method}}).encode("utf-8")
    answer = _post(base.rstrip("/") + JOBS_URL, body, {
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
    }, opener)
    if not answer.get("id"):
        raise RuntimeError(f"{base}{JOBS_URL} took the file and started no job: {answer}")
    return answer


def settings() -> tuple[str, str, str]:
    return (os.environ.get("TWIN_FINE_TUNE_BASE", ""),
            os.environ.get("TWIN_FINE_TUNE_KEY", ""),
            os.environ.get("TWIN_FINE_TUNE_MODEL", ""))


def train(args: argparse.Namespace, opener: Opener = urllib.request.urlopen) -> int:
    """Send the two corpora to a fine-tuning endpoint - if this machine was set up to mean it."""
    base, key, model = settings()
    missing = [name for name, value in zip(("TWIN_FINE_TUNE_BASE", "TWIN_FINE_TUNE_KEY",
                                            "TWIN_FINE_TUNE_MODEL"), (base, key, model)) if not value]
    if missing:
        print(f"nothing was uploaded: {', '.join(missing)} not set. This repository has never"
              f" trained a model and will not start one by accident.")
        return 2
    if not args.yes:
        print(f"would upload {SUPERVISED} and {PREFERENCE} from {args.dir} to {base} as {model}"
              f" and create two jobs. Say --yes to mean it.")
        return 2
    where = Path(args.dir)
    jobs: list[tuple[str, dict[str, Any]]] = []
    try:
        jobs.append(("supervised", create_job(upload(where / SUPERVISED, base, key, opener),
                                              base, key, model, "supervised", opener)))
        if (where / PREFERENCE).read_text(encoding="utf-8").strip():
            jobs.append(("dpo", create_job(upload(where / PREFERENCE, base, key, opener),
                                           base, key, model, "dpo", opener)))
    except (urllib.error.URLError, OSError, RuntimeError) as error:
        print(f"the endpoint answered badly and nothing was trained locally: {error}")
        return 1
    for kind, job in jobs:
        print(f"{kind}: job {job.get('id')} status {job.get('status')} on {model}")
    print("no weight on this machine changed; those jobs run wherever that endpoint runs.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m twin.audit.finetune")
    parser.add_argument("command", nargs="?", default="build",
                        choices=("build", "check", "preview", "train"))
    parser.add_argument("--dir", default=str(DATA_DIR), help="where the corpus is written")
    parser.add_argument("--rows", type=int, default=3, help="how many rows `preview` prints")
    parser.add_argument("--yes", action="store_true", help="actually upload, for train")
    args = parser.parse_args(argv)

    if args.command == "train":
        return train(args)

    doc = build()
    problems = check(doc)
    counts = doc["meta"]["counts"]
    if args.command == "check":
        for warning in problems:
            print(f"  ! {warning}")
        print(f"{counts['supervised']} sentences, {counts['preference']} preference pairs from "
              f"{counts['cases']} cases x {counts['roles']} roles")
        print(f"verdicts: {doc['meta']['verdicts']}")
        return 1 if problems else 0

    if args.command == "preview":
        for row in doc["supervised"][:args.rows]:
            print(json.dumps(row, ensure_ascii=False, sort_keys=True)[:600])
        return 0

    paths = write(doc)
    print(f"problems: {len(problems)}")
    for warning in problems:
        print(f"  ! {warning}")
    for name, path in paths.items():
        print(f"  {name:11s} -> {path} ({path.stat().st_size} bytes)")
    print(f"verdicts: {doc['meta']['verdicts']}")
    print(f"preference pairs skipped: {counts['skipped']}")
    print("trained_here: False - no weight on this machine was updated by any of this")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
