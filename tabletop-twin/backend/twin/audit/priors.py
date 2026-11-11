"""Derives the audit agents' thresholds from the harvested text.

Every number here is found in a fetched sentence, and carries the sentence with it. That
is the whole point of this module: a rule the firm enforces but cannot quote is a rule
somebody invented. Where the corpus does not state a figure - materiality is an auditing
standard's judgement, not a number in a regulation - the prior comes back unset and says
so, and the agent that would have used it runs on a documented default that is labelled
uncalibrated instead of quietly looking like law.

`python -m twin.audit.calibrate` rebuilds `data/priors.json` from whatever is in the
corpus directory, so the numbers move when the law is amended and nobody has to remember
to edit a constant.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from twin.audit.corpus import (
    CORPUS_DIR, DATA_DIR, FINANCE_SLICES, corpus_place, finance_rows, measures, sentences,
)

UNCALIBRATED = "uncalibrated"


@dataclass(frozen=True)
class Rule:
    """A number the firm enforces, described by the words that surround it.

    Keywords select sentences rather than article numbers, because the consolidated text
    renumbers what an amendment inserted. Anchoring on a phrase survives that; anchoring on
    "Article 9" would have found the wrong rule.
    """

    name: str
    keywords: tuple[str, ...]
    measure: str
    within: int = 320
    requires: tuple[str, ...] = ()
    adjacent: str = ""
    pick: str = "mode"
    note: str = ""

    def matches(self, sentence: str) -> bool:
        low = sentence.lower()
        if not all(k in low for k in self.keywords):
            return False
        return all(k in low for k in self.requires)


@dataclass(frozen=True)
class Provision:
    """A rule the corpus states in words and not in a number, found the same way.

    The rotation ceiling and the four-month deadline come out of `Rule` because they are figures.
    "Fees for the provision of statutory audits to public-interest entities shall not be contingent
    fees" is not: there is nothing to measure, and yet the firm still has to be able to say which
    sentence in which article it is refusing the fee arrangement under. A provision is that
    sentence, selected by the words around it and stored with its reference, so a role that enforces
    a rule with no number in it cites the text the way one with a number does.
    """

    name: str
    keywords: tuple[str, ...]
    within: int = 420

    def matches(self, sentence: str) -> bool:
        low = sentence.lower()
        return all(k in low for k in self.keywords)


@dataclass(frozen=True)
class Prior:
    name: str
    value: float | None
    unit: str
    celex: str
    article: str
    quote: str
    hits: int
    distinct: list[float] = field(default_factory=list)
    note: str = ""

    @property
    def calibrated(self) -> bool:
        return self.value is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "value": self.value, "unit": self.unit, "celex": self.celex,
            "article": self.article, "quote": self.quote, "hits": self.hits,
            "distinct": self.distinct, "note": self.note,
            "state": "calibrated" if self.calibrated else UNCALIBRATED,
        }


# What an auditing firm actually has to obey, as numbers.
RULES: tuple[Rule, ...] = (
    Rule("rotation_initial_max_years", ("initial engagement", "shall exceed"), "duration_years",
         pick="max",
         note="Article 17's ceiling on how long one firm may hold one listed or public-interest client. "
              "Keyed on 'shall exceed' because the derogation two paragraphs down also names the initial "
              "engagement and a maximum duration, and states neither of them as the rule."),
    Rule("rotation_with_tender_max_years", ("tender", "maximum duration"), "duration_years",
         pick="max",
         note="The outer ceiling on how long one firm may hold one public-interest client, reached only "
              "where the tender involved more than one firm or voluntary early tendering. One sentence "
              "states both the 20-year tier and this bound, and only the larger is an absolute limit."),
    Rule("rotation_tendered_max_years", ("public tendering process", "maximum duration"),
         "duration_years", pick="min",
         note="The extension an ordinary competitive tender buys. The same sentence states it as the "
              "smaller of two figures, so the rule that wants it says 'min'."),
    Rule("key_partner_rotation_years", ("key audit partner", "rotate"), "duration_years",
         pick="max",
         note="How long the signing partner may keep signing for the same client."),
    Rule("partner_cooling_off_years", ("not participate again",), "duration_years",
         note="How long a key audit partner of a public-interest entity must stay off the audit before "
              "returning to it. The Regulation states it as a plain 'before three years have elapsed', "
              "with no 'at least' in the sentence at all, so keying on that phrase would have missed it."),
    Rule("auditor_return_cooldown_years", ("before a period of at least",), "duration_years",
         pick="min",
         note="The Directive's floor for any statutory auditor returning to an audit they worked on. The "
              "sentence gives a band - one year generally, two where the audited entity is a "
              "public-interest entity - and the Regulation's three years is stricter for the partner of "
              "such an entity, so each agent asks the text for the one that fits its client."),
    Rule("non_audit_fee_cap_percent", ("total fees", "non-audit services"), "percent",
         note="The cap on what a firm may charge the same client for everything except the audit."),
    Rule("fee_dependence_percent", ("total fees received from a public-interest entity",), "percent",
         note="Share of a firm's fees from one client that counts as dependence and must be addressed."),
    Rule("delegation_period_years", ("delegated acts", "conferred"), "duration_years",
         note="How long the Commission's power to write the auditing standards lasts."),
    Rule("size_balance_sheet_ceiling_eur", ("shall not exceed", "balance sheet total"), "amount_eur",
         adjacent="for the balance sheet total",
         note="The most a Member State may raise its own small-undertaking balance-sheet line."),
    Rule("size_net_turnover_ceiling_eur", ("shall not exceed", "net turnover"), "amount_eur",
         adjacent="for the net turnover",
         note="The same ceiling applied to the turnover line."),
    Rule("participation_presumed_percent", ("participating interest", "presumed"), "percent",
         note="The holding that makes one undertaking the other's parent for group-audit purposes."),
    Rule("reporting_entity_employee_floor", ("public-interest entities exceeding", "employees"), "count",
         note="Headcount at which a public-interest entity owes the sustainability statement at all."),
    Rule("aml_record_retention_years", ("beneficial owner",), "duration_years",
         pick="min",
         note="The floor on how long the register the KYC agent checks against keeps its data. "
              "The sentence gives a band - 'at least five years and no more than 10' - and the floor "
              "is the number an agent can rely on."),
    Rule("non_audit_lookback_years", ("provides", "non-audit services", "consecutive financial years"),
         "duration_financial_years",
         note="How many consecutive financial years of non-audit work bring Article 4(2)'s ceiling "
              "into play - and the number of years whose audit fees that ceiling is averaged over. "
              "The same sentence states both, so one prior carries both duties, and the role that uses "
              "it says which of the two it is applying."),
    Rule("transparency_report_deadline_months", ("transparency report",), "duration_months",
         note="How long after the end of the financial year a firm auditing public-interest entities "
              "has to publish its annual transparency report. The only span in months in that article, "
              "which is why the measure does the filtering rather than a keyword."),
    Rule("transparency_report_available_years", ("transparency report", "available"), "duration_years",
         pick="min",
         note="How long that report has to stay on the website once published. 'at least' again marks "
              "the number an agent may rely on, and the sentence is the only one in Article 13 that "
              "carries both words."),
    # Materiality is an auditor's judgement under an auditing standard, not a figure in EU
    # law. It is listed so the run proves the absence rather than hiding it.
    Rule("materiality_percent_of_turnover", ("materiality",), "percent",
         note="No EU statute in the corpus states a materiality percentage."),
    # Original 2006 VAT snapshot, not current national tax compliance.
    Rule("vat_standard_rate_min_percent", ("standard rate may not be less than",), "percent",
         pick="min",
         note="Original 2006 Article 97 snapshot: the quoted period ends on 31 December 2010; "
              "not current tax compliance or national certification."),
    Rule("vat_reduced_rate_min_percent", ("reduced rates shall be fixed as a percentage",), "percent",
         pick="min",
         note="Original 2006 Article 99 general floor; derogations can allow lower or zero rates. "
              "Not current tax compliance or national certification."),
)

# What the firm enforces that has no figure in it. Same corpus, same provenance, one sentence each.
PROVISIONS: tuple[Provision, ...] = (
    Provision("contingent_audit_fees", ("contingent fees", "statutory audits to public-interest entities")),
    # The Directive's own fee article says "cannot be based on any form of contingency", not
    # "contingent", so it needs its second set of words - and its first limb, that the audit fee be
    # uninfluenced by the additional services sold to the same client, is why this role exists at all
    # for a client the Regulation does not reach.
    Provision("contingent_audit_fees_directive", ("fees for statutory audits", "contingency")),
    Provision("additional_report_to_committee",
              ("additional report to the audit committee", "not later than"), within=520),
    # Read wide for the same reason as the one below: the particulars are lettered (a), (b) and (c),
    # and an entry cut at 420 characters asks the firm about two of the three.
    Provision("public_register_particulars", ("public register", "shall contain at least"), within=700),
    # The clause naming which Article 5(1) points the prohibition repeats sits past the end of a
    # 420-character window, and a provision cut off before its list is a prohibition with no
    # contents, so this one is read wider than the rest.
    Provision("sustainability_service_prohibition",
              ("assurance of sustainability reporting",
               "prohibited non-audit services referred to in points"), within=760),
)


def load_statutes(corpus: Path | None = None) -> list[dict[str, Any]]:
    directory = (corpus or CORPUS_DIR) / "statutes"
    if not directory.exists():
        return []
    out = []
    for path in sorted(directory.glob("*.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return out


# Euro-area aggregates are not interchangeable with the EU aggregate.
EU_AGGREGATES = ("EU27_2020", "EU28")


def load_finance(corpus: Path | None = None) -> dict[str, Any]:
    """Read only supported slice files, keeping malformed inputs unavailable."""
    directory = (corpus or CORPUS_DIR) / "finance"
    out: dict[str, Any] = {}
    for name, code, query in FINANCE_SLICES:
        path = directory / f"{name}.json"
        if not path.exists():
            continue
        try:
            out[name] = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            out[name] = {"name": name, "code": code, "query": query, "rows": [], "error": str(exc)}
    return out


def derive_finance(series: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keep latest validated cells and provenance; ambiguous slices remain unavailable."""
    series = series if series is not None else load_finance()
    out: dict[str, Any] = {}
    for name, code, query in FINANCE_SLICES:
        if name not in series:
            continue
        doc = series[name]
        block: dict[str, Any] = {"table": code, "label": "", "query": query,
                                 "eu": "", "geos": 0, "series": {}}
        out[name] = block
        try:
            rows = finance_rows(name, doc)
        except ValueError as exc:
            block["error"] = str(exc)
            continue
        block.update(label=doc.get("label", ""), query=doc["query"])
        for key in ("url", "source_url"):
            if key in doc:
                block[key] = doc[key]
        by_geo = block["series"]
        for row in rows:
            geo, period = row["geo"], row["time"]
            if geo not in by_geo or period > by_geo[geo]["time"]:
                record = dict(row, query=doc["query"])
                for key in ("url", "source_url"):
                    if key in doc:
                        record.setdefault(key, doc[key])
                by_geo[geo] = record
        block.update(eu=next((g for g in EU_AGGREGATES if g in by_geo), ""), geos=len(by_geo))
    return out


def window(sentence: str, start: int, within: int) -> str:
    """The sentence, shortened for a panel without ever cutting the number out of it.

    A quote is the proof, and a proof that stopped short of the figure it vouches for proves
    nothing: the twenty-four-year ceiling sits at the far end of the sentence that states it.
    """
    limit = within or 320
    if len(sentence) <= limit:
        return sentence
    head = max(0, min(start - limit // 4, len(sentence) - limit))
    return sentence[head:head + limit]


def find(rule: Rule, statutes: list[dict[str, Any]]) -> Prior:
    """Search every article of every fetched statute for the number this rule names."""
    hits: list[dict[str, Any]] = []
    for document in statutes:
        for article in document.get("articles", []):
            text = article.get("text", "")
            if rule.within and len(text) > 400_000:
                continue
            for sentence in sentences(text):
                if not rule.matches(sentence):
                    continue
                for number in measures(sentence):
                    if number["measure"] != rule.measure:
                        continue
                    if number["value"] != number["value"]:  # NaN
                        continue
                    hits.append({
                        "celex": document["celex"], "article": article["article"],
                        "value": number["value"], "unit": number["unit"],
                        "start": number.get("start", 0), "end": number.get("end", 0),
                        "sentence": sentence,
                    })
    if not hits:
        return Prior(rule.name, None, rule.measure, "", "", "", 0, [], rule.note)
    distinct = sorted({h["value"] for h in hits})
    if rule.adjacent:
        # "shall not exceed EUR 6 000 000 for the balance sheet total and EUR 12 000 000 for
        # the net turnover" is one sentence with two ceilings. The rule that wants the second
        # one asks for the number sitting just before its own words.
        near = []
        for hit in hits:
            position = hit["sentence"].lower().find(rule.adjacent)
            if position >= 0 and hit["end"] <= position:
                near.append((position - hit["end"], hit))
        if not near:
            return Prior(rule.name, None, rule.measure, "", "", "", len(hits), distinct,
                         rule.note + f" (no number found immediately before '{rule.adjacent}')")
        chosen = min(near, key=lambda pair: pair[0])[1]
        return Prior(rule.name, chosen["value"], rule.measure, chosen["celex"], chosen["article"],
                     window(chosen["sentence"], chosen["start"], rule.within), len(hits),
                     distinct, rule.note)
    # How a rule reads a passage that contains several numbers of its kind. "a maximum
    # period of seven years" and "at least four years" are both durations, and the one that
    # is a ceiling is not the one that is a floor, so each rule says which it is.
    if rule.pick == "max":
        best = max(distinct)
    elif rule.pick == "min":
        best = min(distinct)
    else:
        counts: dict[float, int] = {}
        for hit in hits:
            counts[hit["value"]] = counts.get(hit["value"], 0) + 1
        # The most-repeated reading wins; ties go to the larger number, because in this
        # corpus the general rule is the longer period and the derogation is the shorter one.
        best = max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
    chosen = next(h for h in hits if h["value"] == best)
    return Prior(rule.name, best, rule.measure, chosen["celex"], chosen["article"],
                 window(chosen["sentence"], chosen["start"], rule.within), len(hits), distinct,
                 rule.note)


BAND_NAMES = ("micro-undertakings", "small undertakings", "medium-sized undertakings",
              "large undertakings", "small groups", "medium-sized groups", "large groups")
EURO = re.compile(r"EUR\s*([\d][\d .,]{2,15})", re.I)
HEADCOUNT = re.compile(r"employees[^.\n]{0,40}?:\s*(\d{1,4})", re.I)


def derive_bands(statutes: list[dict[str, Any]]) -> dict[str, Any]:
    """The EU size ladder, read out of the article that defines it.

    Article 3 of the Accounting Directive prints each class as a label followed by three
    criteria in a fixed order - balance sheet total, net turnover, average employees. A
    keyword search cannot separate "small" from "medium" here because the amounts sit in
    their own fragment lines, so this walks forward from each label instead. The order is
    recorded as it was found rather than assumed, and the raw list of amounts travels with
    the band so a reader can check which number got called what.
    """
    for document in statutes:
        for article in document.get("articles", []):
            text = article.get("text", "")
            if "categories of undertakings" not in text.lower():
                continue
            low = text.lower()
            bands: dict[str, Any] = {}
            for name in BAND_NAMES:
                start = low.find(name)
                if start < 0:
                    continue
                window = text[start:start + 620]
                amounts = [float(m.replace(" ", "").replace("\u00a0", "").replace(",", "."))
                           for m in EURO.findall(window)]
                head = HEADCOUNT.search(window)
                bands[name] = {
                    "balance_sheet_total_eur": amounts[0] if amounts else None,
                    "net_turnover_eur": amounts[1] if len(amounts) > 1 else None,
                    "average_employees": float(head.group(1)) if head else None,
                    "amounts_in_order": amounts[:4],
                    "celex": document["celex"], "article": article["article"],
                    "quote": re.sub(r"\s+", " ", window)[:300],
                }
            return {"source": document["celex"], "article": article["article"], "bands": bands}
    return {"source": "", "article": "", "bands": {}}


SERVICES_INTRO = "prohibited non-audit services shall mean"
LETTER = re.compile(r"^\(([a-z]+)\)$")
# A range in Article 5(3) repeats the letter before its end point - "(a) (iv) to (a) (vii)" -
# so the optional second "(a)" has to be allowed for or the middle of the range is lost.
POINT = re.compile(
    r"\(([a-z])\)"
    r"(?:\s*\(([ivx]+)\)"
    r"(?:\s+to\s+(?:\([a-z]\)\s*)?\(([ivx]+)\))?"
    r")?"
)
ROMAN = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii")


def derive_services(statutes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The services an auditor may not sell to an entity it audits, read out of Article 5.

    The Audit Regulation prints the prohibition as a lettered list inside one article, so this
    walks that list instead of carrying a copy of it. Two neighbouring sentences come back with
    it because both change what an answer means: 5(3) lets a Member State derogate for named
    sub-points, and 5(4) sends every service the list does not prohibit to the audit committee.
    Between them they are why the firm's independence agent can refuse a job but cannot approve
    one.
    """
    for document in (statutes if statutes is not None else load_statutes()):
        for article in document.get("articles", []):
            text = article.get("text", "")
            low = text.lower()
            if SERVICES_INTRO not in low or "prohibition of the provision of non-audit services" not in low:
                continue
            categories: list[dict[str, Any]] = []
            category: dict[str, Any] | None = None
            sub: dict[str, Any] | None = None
            wanted = "a"
            for line in text[low.find(SERVICES_INTRO):].splitlines():
                stripped = line.strip().strip("\t")
                if not stripped or stripped.lower().startswith(SERVICES_INTRO):
                    continue
                if re.match(r"^2\.\s", stripped):
                    break
                marker = LETTER.match(stripped)
                if marker and marker.group(1) == wanted:
                    category = {"letter": wanted, "title": "", "subs": [], "text": ""}
                    categories.append(category)
                    sub, wanted = None, chr(ord(wanted) + 1)
                    continue
                if category is None:
                    continue
                if marker and marker.group(1) in ROMAN:
                    sub = {"letter": marker.group(1), "text": ""}
                    category["subs"].append(sub)
                    continue
                target = sub if sub is not None else category
                target["text"] = (target["text"] + " " + stripped).strip()
                if target is category and not category["title"]:
                    category["title"] = stripped.rstrip(";:.")
            if not categories:
                continue
            derogation = next((s for s in sentences(text) if "by way of derogation" in s.lower() and "points" in s.lower()), "")
            # Only the list of points is a list of points. The sentence runs on into the three
            # conditions the derogation is subject to, and those are lettered (a), (b) and (c)
            # too - reading them as services would mark bookkeeping derogable.
            where = derogation.lower().find("referred to in points")
            tail = derogation[where + len("referred to in points"):] if where >= 0 else ""
            stop = tail.lower().find("provided that")
            named = tail[:stop].strip(" ,.") if stop >= 0 else tail.strip(" ,.")
            points: dict[str, list[str]] = {}
            for letter, first, last in POINT.findall(named):
                span = ROMAN[ROMAN.index(first):ROMAN.index(last) + 1] if last else ([first] if first else [])
                points.setdefault(letter, []).extend(span)
            return {
                "celex": document["celex"], "article": article["article"],
                "categories": categories,
                # The chapeau says whose audits the list binds, which is the difference between
                # a prohibition and a policy preference for everything else the firm audits.
                "scope": next((s for s in sentences(text)
                               if "shall not directly or indirectly provide" in s.lower()), ""),
                "derogation": {
                    "quote": derogation, "points_text": named,
                    "points": {k: sorted(set(v), key=ROMAN.index) for k, v in sorted(points.items())},
                },
                "approval": next((s for s in sentences(text)
                                  if "subject to the approval of the audit committee" in s.lower()), ""),
            }
    return {"celex": "", "article": "", "categories": [], "scope": "",
            "derogation": {"quote": "", "points_text": "", "points": {}}, "approval": ""}


RANGE_POINT = re.compile(r"\(([a-z])\)\s+to\s+\(([a-z])\)")
# A list item's letter stands alone - "(a) name, address..." - while the plural in
# "registration(s)" is glued to the word it inflects. The lookbehind is what keeps the second kind
# out of an expanded point list without hard-coding which articles have plurals in them.
SINGLE_POINT = re.compile(r"(?<![A-Za-z0-9])\(([a-z])\)(?=\s)")
# The two ways this corpus introduces a list of points: by pointing at one ("referred to in points
# (b) and (c)"), or by printing it after a colon ("shall contain at least the following
# information: (a) name, address and registration number").
CROSS_REFERENCE = "referred to in points"
POINT_ANCHORS = (CROSS_REFERENCE, "the following information:", "the following details:")


def points_clause(sentence: str) -> str:
    """The lettered part of a provision, or '' when it has none."""
    low = sentence.lower()
    for anchor in POINT_ANCHORS:
        where = low.find(anchor)
        if where < 0:
            continue
        tail = sentence[where + len(anchor):]
        # A cross-reference ends where the article it borrows from begins; a colon introduces the
        # list itself, and the list runs to the end of the sentence.
        stop = tail.lower().find(" of the ") if anchor == CROSS_REFERENCE else -1
        return tail[:stop] if stop >= 0 else tail
    return ""


def expand_points(clause: str) -> list[str]:
    """'(b) and (c) and points (e) to (k)' read as the letters it names, smallest first.

    Ranges are taken out before the singles are collected, or '(e) to (k)' would also contribute
    its two end letters as stand-alone points - which changes nothing here but would matter in a
    clause that mixed a range with the letter it ends on.
    """
    letters: set[str] = set()
    rest = clause
    for first, last in RANGE_POINT.findall(rest):
        if len(first) == len(last) == 1 and first <= last:
            letters.update(chr(code) for code in range(ord(first), ord(last) + 1))
        rest = rest.replace(f"({first}) to ({last})", " ")
    letters.update(letter for letter in SINGLE_POINT.findall(rest) if len(letter) == 1)
    return sorted(letters)


def derive_provisions(statutes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One quoted sentence per provision, with the article it came from.

    The first match in statute order wins and every later one is counted, because a provision that
    appears twice is a provision whose wording drifted between the Regulation and the Directive, and
    a reader should be able to see that from the file rather than from this code.
    """
    documents = statutes if statutes is not None else load_statutes()
    ordered = sorted(documents, key=lambda doc: str(doc.get("celex", "")))
    out: dict[str, Any] = {}
    for provision in PROVISIONS:
        found: dict[str, Any] | None = None
        hits = 0
        for document in ordered:
            for article in document.get("articles", []):
                for sentence in sentences(article.get("text", "")):
                    if not provision.matches(sentence):
                        continue
                    hits += 1
                    if found is None:
                        found = {"celex": str(document.get("celex", "")),
                                 "article": str(article.get("article", "")),
                                 "quote": " ".join(sentence.split())[:provision.within]}
        entry = dict(found or {"celex": "", "article": "", "quote": ""})
        entry["state"] = "quoted" if found else "not_in_corpus"
        entry["hits"] = hits
        clause = points_clause(entry["quote"])
        if clause:
            entry["points_text"] = " ".join(clause.split())[:120]
            entry["points"] = expand_points(clause)
        out[provision.name] = entry
    return out


def derive(statutes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    statutes = statutes if statutes is not None else load_statutes()
    priors = [find(rule, statutes) for rule in RULES]
    return {
        "derived_from": {
            "statutes": len(statutes),
            "articles": sum(len(s.get("articles", [])) for s in statutes),
            "corpus_dir": corpus_place(),
        },
        "uncalibrated": [p.name for p in priors if not p.calibrated],
        "priors": {p.name: p.to_dict() for p in priors},
        "provisions": derive_provisions(statutes),
        "size_bands": derive_bands(statutes),
        "non_audit_services": derive_services(statutes),
        "finance": derive_finance(),
    }


def main(argv: list[str]) -> int:
    if argv and argv[0] in {"-h", "--help"}:
        print("usage: python -m twin.audit.calibrate [--json]\n"
              "  re-derives every audit threshold from the harvested statute text")
        return 0
    result = derive()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "priors.json").write_text(
        json.dumps(result, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    if "--json" in argv:
        print(json.dumps(result, indent=1, ensure_ascii=False))
    else:
        for name, prior in sorted(result["priors"].items()):
            flag = "ok " if prior["state"] == "calibrated" else "-- "
            where = f"{prior['celex']} art {prior['article']}" if prior["celex"] else "not in the corpus"
            print(f"{flag}{name:34s} {str(prior['value']):>12} {prior['unit']:14s} {where}"
                  f"  ({prior['hits']} hits, {len(prior['distinct'])} distinct)")
        print(f"\nuncalibrated: {result['uncalibrated'] or 'none'}")
        bands = result["size_bands"]
        print(f"size ladder from {bands['source']} art {bands['article']}:")
        for name, band in bands["bands"].items():
            print(f"  {name:28s} balance sheet {str(band['balance_sheet_total_eur']):>14}"
                  f"  turnover {str(band['net_turnover_eur']):>14}  employees {band['average_employees']}")
        services = result["non_audit_services"]
        letters = ", ".join(c["letter"] for c in services["categories"])
        print(f"\nprohibited non-audit services from {services['celex']} art {services['article']}: "
              f"{len(services['categories'])} categories ({letters})")
        for category in services["categories"]:
            print(f"  ({category['letter']}) {category['title'][:74]}")
        print(f"  5(3) derogation covers {services['derogation']['points'] or 'nothing'}")
        print(f"  5(4) approval sentence: {'found' if services['approval'] else 'NOT FOUND'}")
    return 0 if result["priors"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
