"""Harvests the EU corpus the audit agents are calibrated against.

Two sources, both keyless, both checked from this machine before anything was written
down: the Publications Office (CELLAR) serves the actual text of EU audit and accounting
law when content-negotiated properly, and Eurostat's dissemination API serves real tables.
Which Eurostat tables exist is not guessable from the website, so this module probes a
candidate list and keeps whatever answers 200. A code that 404s is written into the
manifest with the server's own error label instead of being quietly dropped, because
"structural business statistics for accounting activities were not available here" is a
fact a reader needs in order to judge the numbers that did come from somewhere else.

Nothing in here invents a figure. The parsed text goes to a gitignored corpus directory,
and only the derived manifest and the derived priors are kept in the repo, each with the
sentence it came from.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

USER_AGENT = "tabletop-twin/0.1 (audit corpus harvester)"
CELLAR_URL = "https://publications.europa.eu/resource/celex/{celex}"
EUROSTAT_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{code}"

# EU law that decides what a statutory audit firm has to do and how big a client has to
# be before the extra rules bite. Titles are what the fetching record says they are; they
# are written into the manifest from the document, not from memory.
STATUTES: tuple[tuple[str, str], ...] = (
    ("32006L0043", "Directive 2006/43/EC on statutory audits of annual accounts"),
    ("32014L0056", "Directive 2014/56/EU amending Directive 2006/43/EC"),
    ("32014R0537", "Regulation (EU) 537/2014 on specific requirements regarding statutory audit"),
    ("32013L0034", "Directive 2013/34/EU on annual financial statements (size thresholds)"),
    ("32002R1606", "Regulation (EC) 1606/2002 on the application of international accounting standards"),
    ("32022L2464", "Directive (EU) 2022/2464 on sustainability reporting (CSRD)"),
    ("32014L0095", "Directive 2014/95/EU on non-financial reporting (NFRD)"),
    ("32018L0843", "Directive (EU) 2018/843 on combating money laundering (AML)"),
    ("32019R0888", "Regulation (EU) 2019/2088 on sustainability-related disclosures (SFDR)"),
    ("32006L0112", "Directive 2006/112/EC on the common system of value added tax (VAT)"),
)

# Probed, not assumed. Only the ones that answer carry rows into the corpus.
TABLES: tuple[tuple[str, str], ...] = (
    ("tec00001", "GDP growth rate"),
    ("nama_10_gdp", "GDP and main components"),
    ("ei_bssi_m_r2", "Economic confidence indicators by sector"),
    ("nama_10_a10se", "Non-financial accounts by institutional sector"),
    ("nama_10_ki", "Capital investment"),
    ("prc_hicp_aind", "Annual HICP inflation"),
    ("tec00051", "Government consumption"),
    ("sf_sal_r2", "Wage indicator by activity"),
    ("sbs_oc_rec_r2", "Structural business statistics by NACE Rev. 2"),
    ("sbs_fr_a2r", "Business demography by size class and activity"),
    ("sbr_nbr_a", "Number of enterprises by activity"),
)

# Named, unstrided slices kept separately from the broad corpus.
FINANCE_SLICES: tuple[tuple[str, str, str], ...] = (
    ("hicp_inflation_percent", "prc_hicp_aind", "coicop=CP00&unit=RCH_A_AVG"),
    ("gdp_per_capita_eur", "tec00001", "unit=CP_EUR_HAB"),
    ("economic_sentiment_index", "ei_bssi_m_r2", "indic=BS-ESI-I"),
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = Path(os.environ.get("TWIN_CORPUS_DIR", str(REPO_ROOT / "backend" / ".corpus")))
DATA_DIR = Path(__file__).resolve().parent / "data"


def corpus_place(directory: Path | None = None) -> str:
    """Where the corpus sits, said without printing this machine's home directory.

    The files this layer ships are provenance records in a public repository, and
    `C:\\Users\\<name>\\...` is somebody's folder rather than a fact about the harvest. The path
    relative to the repository is the same fact on every machine; a corpus parked outside it is
    named by the variable that put it there.
    """
    where = Path(directory) if directory else CORPUS_DIR
    try:
        return where.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return "$TWIN_CORPUS_DIR" if os.environ.get("TWIN_CORPUS_DIR") else where.name

# A table like nama_10_gdp answers with a hundred and seventy thousand cells. Keeping every
# one is neither useful nor honest - the priors read a handful of series - so a large table
# is thinned by a fixed stride and the manifest says how many cells were there, how many
# were kept and that the keep was mechanical rather than cherry-picked.
ROW_CAP = 20_000


@dataclass(frozen=True)
class Fetched:
    status: int
    bytes: int
    body: str
    error: str


def fetch(url: str, accept: str, lang: str = "eng", timeout: int = 90, tries: int = 3) -> Fetched:
    """GET with content negotiation and TLS verification on.

    The retries are for the two failure modes that were actually seen here: a socket that
    closes mid-request, and a 5xx from a server under load. A 404 is not retried; it is
    the answer.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if lang:
        headers["Accept-Language"] = lang
    last = Fetched(0, 0, "", "")
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", "replace")
                return Fetched(response.status, len(body.encode("utf-8", "replace")), body, "")
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:400].decode("utf-8", "replace")
            return Fetched(exc.code, 0, "", _label(detail) or f"HTTP {exc.code}")
        except Exception as exc:  # noqa: BLE001 - a harvest records what failed rather than dying
            last = Fetched(0, 0, "", f"{type(exc).__name__}: {exc}")
            time.sleep(1.5 * (attempt + 1))
    return last


def _label(detail: str) -> str:
    """Eurostat explains a refusal in a `label` field; keep it verbatim."""
    match = re.search(r'"label"\s*:\s*"([^"]+)"', detail)
    return match.group(1) if match else ""


class _Text(HTMLParser):
    """XHTML to readable lines, keeping the paragraph breaks the article split needs."""

    SKIP = {"script", "style", "head", "meta"}
    BLOCK = {"p", "div", "li", "table", "tr", "td", "th", "h1", "h2", "h3", "headline",
             "article", "section", "br", "html", "body", "td", "caption", "note"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.parts.append(" " + data.strip() + " ")


def to_text(xhtml: str) -> str:
    parser = _Text()
    parser.feed(xhtml)
    # The Journal sets amounts with non-breaking spaces ("EUR\u00a04\u00a0000\u00a0000"). Left in,
    # every amount regex in this module silently misses the number it exists to find.
    joined = "".join(parser.parts).replace("\u00a0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in joined.split("\n")]
    return "\n".join(line for line in lines if line)


ARTICLE_START = re.compile(r"^Article\s+(\d{1,4}[a-z]?)\s*$")


def split_articles(text: str) -> list[dict[str, Any]]:
    """Cut the statute at its own article headings.

    The Official Journal prints `Article 9` on a line of its own before the numbered
    paragraphs, so the split is on the document's structure rather than on a guess about
    where one rule stops and the next starts. Text before the first heading is kept as the
    preamble; it holds the recitals, which explain a rule but never state a threshold.
    """
    out: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.split("\n"):
        match = ARTICLE_START.match(line)
        if match:
            if current is not None:
                out.append(current)
            current = {"article": match.group(1), "lines": [line]}
        elif current is not None:
            current["lines"].append(line)
    if current is not None:
        out.append(current)
    articles = [{"article": a["article"], "text": "\n".join(a["lines"]).strip()} for a in out]
    return articles


SENTENCE = re.compile(r"[^.!?]*[.!?]|\S[^.!?]*$")

# Legal text writes its short numbers as words: a key audit partner rotates "within a
# maximum period of seven years". A digit-only pattern reads that sentence as stating no
# number at all, which is how a rule goes missing from a corpus that plainly contains it.
WORD_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
TENS = [word for word, value in WORD_NUM.items() if value >= 20]
UNITS = [word for word, value in WORD_NUM.items() if value < 20]
# The Consolidated text of Regulation (EU) No 537/2014 prints the twenty-four-year ceiling as
# "twenty four years". Without the compound, the pattern matches "four years" sitting inside it
# and the corpus appears to state a four-year extension where it states a twenty-four-year one.
NUM = (r"(?P<value>\d{1,4}(?:[.,]\d+)?|"
       + "(?:" + "|".join(TENS) + r")(?:[\s-]+(?:" + "|".join(UNITS) + r"))?|"
       + "|".join(UNITS) + ")")


def sentences(text: str) -> list[str]:
    """Sentences, for the quote that has to travel with every derived number."""
    flat = re.sub(r"\s+", " ", text)
    return [s.strip() for s in SENTENCE.findall(flat) if len(s.strip()) > 12]


# The words a legal text uses for everything, so a search that matches on them has found the
# corpus rather than a rule. "Services" is in almost every entry of Article 5(1), so a query
# matched only on it has not been placed.
STOPWORDS = frozenset("""a an the of and or to for in on with by at from is are other than all any
such where also its their it this that services service undertakings entity audit audited""".split())


def tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z]+", text.lower()) if word not in STOPWORDS and len(word) > 2}


PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("duration_years", re.compile(rf"{NUM}\s*(?P<unit>years?)", re.I)),
    ("duration_months", re.compile(rf"{NUM}\s*(?P<unit>months?)", re.I)),
    ("duration_days", re.compile(rf"{NUM}\s*(?P<unit>calendar days?|days?)", re.I)),
    # "for a period of three or more consecutive financial years" states its number two words away
    # from the thing it counts, so `duration_years` cannot see it. A separate measure name rather
    # than a looser `years?` pattern: every prior that reads `duration_years` would otherwise start
    # matching across words it was never meant to reach.
    ("duration_financial_years",
     re.compile(rf"{NUM}\s+(?:or more\s+)?(?:[\w-]+\s+){{0,3}}?financial years", re.I)),
    ("percent", re.compile(rf"{NUM}\s*(?:%|per\s*cent|percent)", re.I)),
    ("amount_eur", re.compile(r"(?P<unit>EUR|euros?)\s*(?P<value>\d{1,4}(?:[. ]\d{3})*(?:[.,]\d+)?)", re.I)),
    ("count", re.compile(rf"{NUM}\s*(?P<unit>members?|auditors?|firms?|committees?|employees?|persons?)\b", re.I)),
    # The size ladder prints the headcount after the label - "average number of employees
    # during the financial year: 50." - so the number trails the word it counts.
    ("count", re.compile(r"employees[^.\n]{0,40}?:\s*(?P<value>\d{1,4})", re.I)),
)


def measures(text: str) -> list[dict[str, Any]]:
    """Every number in a passage, with the sentence that carries it and where it sits.

    Deliberately broad. A prior is only kept when a named rule asks for a specific pattern
    out of this list, so the breadth here costs nothing and means the selection in
    `priors.py` had something to select from rather than a hardcoded constant. The offsets
    are kept because one sentence can hold two ceilings, and the rule that wants the second
    one has to say so by position rather than by hoping the mode picks it.
    """
    found: list[dict[str, Any]] = []
    for sentence in sentences(text):
        for name, pattern in PATTERNS:
            for match in pattern.finditer(sentence):
                value = match.group("value").strip().rstrip(".")
                unit = (match.groupdict().get("unit") or "").lower().replace(" ", "")
                found.append({
                    "measure": name,
                    "raw": value,
                    "value": _number(value),
                    "unit": unit or name,
                    "start": match.start(),
                    "end": match.end(),
                    "sentence": sentence[:600],
                })
    return found


def _number(raw: str) -> float:
    text = raw.lower().strip()
    if words := re.findall(r"[a-z]+", text):
        # "twenty four" is one number spelled in two words; the parts add.
        parts = [WORD_NUM.get(word) for word in words]
        if any(part is None for part in parts):
            return float("nan")
        return float(sum(parts))
    try:
        return float(text.replace("\u00a0", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return float("nan")


def harvest(*, quiet: bool = False, only: str = "") -> dict[str, Any]:
    """Fetch everything, parse what answers, write the corpus and the manifest.

    `only` narrows the run to `statutes` or `tables` when a re-fetch is needed; the
    manifest it writes is the one from that run, so a partial harvest says so rather than
    looking like a corpus that was never wider.
    """
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    (CORPUS_DIR / "statutes").mkdir(exist_ok=True)
    (CORPUS_DIR / "tables").mkdir(exist_ok=True)
    sources: list[dict[str, Any]] = []

    for celex, expected in () if only == "tables" else STATUTES:
        got = fetch(CELLAR_URL.format(celex=celex), "application/xhtml+xml")
        row: dict[str, Any] = {
            "kind": "statute", "id": celex, "expected": expected,
            "url": CELLAR_URL.format(celex=celex), "status": got.status,
            "bytes": got.bytes, "error": got.error,
        }
        if got.status == 200 and got.body:
            text = to_text(got.body)
            articles = split_articles(text)
            title = _document_title(text)
            (CORPUS_DIR / "statutes" / f"{celex}.json").write_text(
                json.dumps({"celex": celex, "title": title, "text": text,
                            "articles": articles}, indent=1, ensure_ascii=False),
                encoding="utf-8",
            )
            row.update({
                "title": title,
                "articles": len(articles),
                "article_labels": [a["article"] for a in articles],
                "numbers": sum(len(measures(a["text"])) for a in articles),
            })
        sources.append(row)
        if not quiet:
            print(f"statute {celex:14s} {got.status} {row.get('articles', 0)} articles")

    for code, label in () if only == "statutes" else TABLES:
        url = EUROSTAT_URL.format(code=code) + "?format=JSON&lang=EN&lastTimePeriod=5"
        got = fetch(url, "application/json", lang="")
        row: dict[str, Any] = {"kind": "table", "id": code, "expected": label,
                               "url": url, "status": got.status, "bytes": got.bytes, "error": got.error}
        if got.status == 200 and got.body:
            try:
                payload = json.loads(got.body)
            except json.JSONDecodeError as exc:
                row["error"] = f"unparseable JSON: {exc}"
                sources.append(row)
                continue
            rows = flatten_table(code, payload)
            total = len(rows)
            stride = max(1, -(-total // ROW_CAP))
            kept = rows[::stride][:ROW_CAP]
            (CORPUS_DIR / "tables" / f"{code}.json").write_text(
                json.dumps({"code": code, "label": payload.get("label", label),
                            "columns": payload.get("columns", {}),
                            "cells_in_answer": total, "stride": stride, "rows": kept},
                           indent=1, ensure_ascii=False),
                encoding="utf-8",
            )
            row.update({"title": payload.get("label", label), "rows": len(kept),
                        "cells_in_answer": total, "stride": stride,
                        "geos": len({r["geo"] for r in kept if "geo" in r}),
                        "periods": sorted({r["time"] for r in kept if "time" in r})[-1:]})
        sources.append(row)
        if not quiet:
            print(f"table   {code:14s} {got.status} {row.get('rows', 0)} rows  {row.get('error', '')}")

    manifest = {
        "harvested_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "licence": {
            "statute": "Reuse of EUR-Lex / Publications Office content is open, subject to "
                       "the notice at https://eur-lex.europa.eu/content-law/legal-notice.html",
            "table": "Eurostat data are released under the CC BY 4.0 licence "
                     "(https://ec.europa.eu/info/legal-notice_en).",
        },
        "user_agent": USER_AGENT,
        "sources": sources,
        "counts": _counts(sources),
        "unavailable": [
            {"id": s["id"], "kind": s["kind"], "expected": s["expected"],
             "status": s["status"], "reason": s["error"]}
            for s in sources if s["status"] != 200
        ],
    }
    return manifest


def finance_rows(name: str, doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate a supported slice; reject ambiguous cells rather than choosing by order."""
    spec = next((s for s in FINANCE_SLICES if s[0] == name), None)
    if spec is None or not isinstance(doc, dict):
        raise ValueError("unsupported finance slice")
    _, code, query = spec
    if doc.get("name", name) != name or doc.get("code") != code or doc.get("error"):
        raise ValueError(str(doc.get("error") or "finance slice identity mismatch"))
    actual = doc.get("query")
    if not isinstance(actual, str):
        raise ValueError("missing finance query")
    expected = urllib.parse.parse_qsl(query, strict_parsing=True)
    if sorted(urllib.parse.parse_qsl(actual, keep_blank_values=True, strict_parsing=True)) != sorted(expected):
        raise ValueError("unexpected finance dimension filters")
    rows = doc.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("empty or malformed finance rows")
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("malformed finance row")
        geo, period, value = row.get("geo"), row.get("time"), row.get("value")
        if not isinstance(geo, str) or not geo.strip() or not isinstance(period, str) or not period.strip():
            raise ValueError("missing finance geography or period")
        if type(value) not in (int, float) or (isinstance(value, float) and not math.isfinite(value)):
            raise ValueError("finance value must be numeric and finite")
        if row.get("dataset", code) != code or any(row.get(key) != val for key, val in expected):
            raise ValueError("finance row does not match requested dimensions")
        key = (geo, period)
        if key in cells and cells[key] != row:
            raise ValueError(f"conflicting finance cells for {geo}/{period}")
        cells[key] = row
    return [dict(cells[key]) for key in sorted(cells)]


def harvest_finance(*, quiet: bool = False) -> dict[str, Any]:
    """Save full finance slices and a separate manifest; failures replace stale rows."""
    finance_dir = CORPUS_DIR / "finance"
    finance_dir.mkdir(parents=True, exist_ok=True)
    sources: list[dict[str, Any]] = []
    for name, code, query in FINANCE_SLICES:
        url = EUROSTAT_URL.format(code=code) + f"?format=JSON&lang=EN&{query}&lastTimePeriod=5"
        got = fetch(url, "application/json", lang="")
        error = got.error or (f"HTTP {got.status}" if got.status != 200 else "")
        doc: dict[str, Any] = {"name": name, "code": code, "query": query, "url": url,
                               "label": "", "rows": [], "error": error}
        if not error:
            try:
                payload = json.loads(got.body)
                if not isinstance(payload, dict):
                    raise ValueError("expected a JSON-stat object")
                names, sizes = payload.get("id"), payload.get("size")
                if (not isinstance(names, list) or not names or len(set(names)) != len(names)
                        or not isinstance(sizes, list) or len(names) != len(sizes)
                        or any(type(size) is not int or size <= 0 for size in sizes)
                        or not isinstance(payload.get("label", ""), str)):
                    raise ValueError("invalid JSON-stat dimensions or label")
                for dim, size in zip(names, sizes):
                    index = payload["dimension"][dim]["category"]["index"]
                    if (any(type(i) is not int for i in index.values())
                            or sorted(index.values()) != list(range(size))):
                        raise ValueError("invalid JSON-stat dimension index")
                if any(not re.fullmatch(r"0|[1-9]\d*", key) or int(key) >= math.prod(sizes)
                       for key in payload.get("value", {})):
                    raise ValueError("invalid JSON-stat cell offset")
                rows = flatten_table(code, payload)
                if any(not r.get(dim) for r in rows for dim in names):
                    raise ValueError("unresolved JSON-stat dimension")
                doc["rows"] = finance_rows(name, dict(doc, rows=rows))
                doc["label"] = payload.get("label", "")
                json.dumps(doc, allow_nan=False)
            except (ValueError, TypeError, AttributeError, KeyError, OverflowError) as exc:
                doc.update(rows=[], label="", error=f"invalid finance response: {exc}")
        (finance_dir / f"{name}.json").write_text(
            json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8")
        row = {"name": name, "code": code, "query": query, "url": url,
               "status": got.status, "bytes": got.bytes, "error": doc["error"],
               "title": doc["label"], "rows": len(doc["rows"]),
               "geos": len({r["geo"] for r in doc["rows"]}),
               "times": sorted({r["time"] for r in doc["rows"]})}
        sources.append(row)
        if not quiet:
            print(f"finance {name:26s} {got.status} {row['rows']} rows  {row['error']}")
    manifest = {
        "harvested_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "licence": "Eurostat data are released under the CC BY 4.0 licence "
                   "(https://ec.europa.eu/info/legal-notice_en).",
        "user_agent": USER_AGENT,
        "sources": sources,
        "counts": {"slices_fetched": sum(not s["error"] for s in sources),
                   "slices_refused": sum(bool(s["error"]) for s in sources),
                   "rows": sum(s["rows"] for s in sources)},
        "unavailable": [{"name": s["name"], "code": s["code"], "status": s["status"], "reason": s["error"]}
                        for s in sources if s["error"] or s["status"] != 200],
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "finance-manifest.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _counts(sources: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "statutes_fetched": sum(1 for s in sources if s["kind"] == "statute" and s["status"] == 200),
        "statutes_refused": sum(1 for s in sources if s["kind"] == "statute" and s["status"] != 200),
        "articles": sum(s.get("articles", 0) for s in sources),
        "numbers_in_text": sum(s.get("numbers", 0) for s in sources),
        "tables_fetched": sum(1 for s in sources if s["kind"] == "table" and s["status"] == 200),
        "tables_refused": sum(1 for s in sources if s["kind"] == "table" and s["status"] != 200),
        "table_rows": sum(s.get("rows", 0) for s in sources),
    }


def _document_title(text: str) -> str:
    """The document's own title line, which is the first thing the Journal prints."""
    for line in text.split("\n")[:40]:
        if re.match(r"^(REGULATION|DIRECTIVE)\b", line.strip()):
            return line.strip()[:240]
    return ""


def flatten_table(code: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Eurostat's JSON is a sparse matrix keyed by integer offsets; this turns it into rows.

    The answer carries `id` (the dimension names in order), `size` (how many codes each
    takes), `dimension[name].category.index` (code to position) and `value` keyed by the
    flat row-major offset. Reading an offset back into codes is the only way to know which
    country and which year a number belongs to, so it is done here rather than assumed.
    """
    names = payload.get("id") or []
    sizes = payload.get("size") or []
    dims = payload.get("dimension") or {}
    if not names or len(names) != len(sizes):
        return []
    by_position: list[dict[int, str]] = []
    labels: list[dict[str, str]] = []
    for name in names:
        category = ((dims.get(name) or {}).get("category") or {})
        index = category.get("index") or {}
        by_position.append({position: item for item, position in index.items()})
        labels.append(category.get("label") or {})
    strides: list[int] = []
    stride = 1
    for size in reversed(sizes):
        strides.append(stride)
        stride *= max(int(size), 1)
    strides.reverse()

    rows: list[dict[str, Any]] = []
    for key, value in (payload.get("value") or {}).items():
        if value is None:
            continue
        rest = int(key)
        row: dict[str, Any] = {"dataset": code, "title": payload.get("label", code)}
        for position, name in enumerate(names):
            offset = rest // strides[position]
            rest = rest % max(strides[position], 1)
            item = by_position[position].get(offset, "")
            row[name] = item
            row[f"{name}_label"] = labels[position].get(item, "")
        row["value"] = value
        row["flags"] = ((payload.get("status") or {}).get(key) or "")
        rows.append(row)
    return sorted(rows, key=lambda r: (r.get("geo", ""), r.get("time", ""), r.get("unit", "")))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m twin.audit.harvest")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--only", choices=("statutes", "tables", "finance"), default="")
    args = parser.parse_args(argv)
    as_json, only = args.json, args.only
    if only == "finance":
        finance = harvest_finance(quiet=as_json)
        print(json.dumps(finance, indent=1, ensure_ascii=False) if as_json else
              f"manifest -> {DATA_DIR / 'finance-manifest.json'}")
        return 0 if finance["sources"] and not finance["unavailable"] else 1
    manifest = harvest(quiet=as_json, only=only)
    if only:
        # A narrowed run keeps the other half of the record it already had, so the tracked
        # manifest stays the whole picture and says which part was just refreshed.
        previous = _read_manifest()
        refreshed = {s["id"] for s in manifest["sources"]}
        carried = [s for s in previous.get("sources", []) if s["id"] not in refreshed]
        manifest["sources"] = sorted(manifest["sources"] + carried, key=lambda s: (s["kind"], s["id"]))
        manifest["counts"] = _counts(manifest["sources"])
        manifest["unavailable"] = [
            {"id": s["id"], "kind": s["kind"], "expected": s["expected"],
             "status": s["status"], "reason": s["error"]}
            for s in manifest["sources"] if s["status"] != 200
        ]
        manifest["refreshed_this_run"] = sorted(refreshed)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    summary = {"counts": manifest["counts"], "unavailable": manifest["unavailable"]}
    finance = harvest_finance(quiet=as_json) if not only else None
    if finance is not None:
        summary["finance"] = {"counts": finance["counts"], "unavailable": finance["unavailable"]}
    print(json.dumps(summary, indent=1, ensure_ascii=False) if as_json else
          f"manifest -> {DATA_DIR / 'manifest.json'}"
          + (f"; finance -> {DATA_DIR / 'finance-manifest.json'}" if finance is not None else ""))
    ok = manifest["counts"]["statutes_fetched"] and (
        finance is None or (finance["sources"] and not finance["unavailable"]))
    return 0 if ok else 1


def _read_manifest() -> dict[str, Any]:
    path = DATA_DIR / "manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
