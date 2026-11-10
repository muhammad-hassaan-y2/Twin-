"""The law, searchable - so that a citation can be checked against the text it claims to quote.

This module exists because the firm's judgements are now made by a model. A model that reads the
case and the statute and says "this breaches Article 5(1), here is the sentence" is doing something
a Python function cannot do: it is weighing facts against words. But the same model will, about one
time in a hundred, name an article that does not exist and quote it perfectly accurately. So the
machine needs a way to ask the corpus itself.

Three things come out of this file and all three are checkable without a model:

* **retrieval** - a question in legal English, and the articles that answer it come back. The model
  is handed the retrieved text rather than a threshold typed in here, which is what "the agent
  reads the law" has to mean for the claim to be worth anything.
* **verification** - a quote is real if that exact sequence of words appears in the article it is
  attributed to. Nothing else about the sentence is argued with; the citation either resolves or it
  does not.
* **a Merkle root over every article** - `law.json` holds each article's hash and
  the root they fold into, which is the number a Solidity contract can be given so that *bytecode*
  refuses an article that is not in the law this firm was built on. The root goes on-chain; the
  words stay here, because a chain that stored the Official Journal would be a chain nobody runs.

`law.json` is derived and tracked, and contains no article text: hashes of somebody else's published
statute are not the statute. The text lives in the gitignored `.corpus` directory, and where that
directory is absent - a fresh clone, a machine that never harvested - this module still knows how
many articles the firm was built on and what their hashes are, but it cannot check a quote, and
says so instead of passing one through.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from twin.audit.corpus import CORPUS_DIR, DATA_DIR, corpus_place
from twin.audit.priors import load_statutes

LAW_FILE = DATA_DIR / "law.json"
MANIFEST_FILE = DATA_DIR / "manifest.json"

# A quote short enough to be an accident is not evidence. "the audit" is three words and appears
# somewhere in every statute; it vouches for nothing, so a citation that thin is refused outright.
MIN_QUOTE_CHARS = 24

# BM25 as Okazaki's parameterisation, fixed rather than tuned: a retriever that changes what it
# finds between runs is not a check, and nothing here has a corpus large enough to fit parameters to.
K1, B = 1.5, 0.75

QUOTE_SWAP = str.maketrans({"\u00a0": " ", "\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"',
                             "\u2013": "-", "\u2014": "-", "\u2026": "..."})

# Function words and nothing else. `audit`, `auditor` and `entity` are deliberately absent even
# though match_service throws them away: a search that cannot see the word "audit" is blind to the
# topic it is being asked about, and inverse document frequency already discounts a word that turns
# up in every article. Dropping it outright would be a second, silent penalty on the same word.
FUNCTION_WORDS = frozenset("""a an the of and or to for in on with by at from is are was were be been
being it its this that these those which who whom whose as such where when whether not no nor than
then there their they them we you your his her has have had shall may might can could must should
would will do does did more most other others any all both each other if but because before after
above below under upon per into out up down over about against within without also""".split())


def words(text: str) -> list[str]:
    """Every meaningful word, in order, with repeats kept - term frequency needs the repeats."""
    return [word for word in re.findall(r"[a-z]+", normalise(text).lower())
            if word not in FUNCTION_WORDS and len(word) > 2]


def normalise(text: str) -> str:
    """The form a quote is compared in, and the form every leaf hash is taken over.

    Whitespace is collapsed and typographic punctuation folded to ASCII before anything is
    compared or hashed, so that a publisher changing a line break cannot move a leaf, and a model
    that quotes with the right words and the wrong apostrophe is not refused for the apostrophe.
    """
    return re.sub(r"\s+", " ", text.translate(QUOTE_SWAP)).strip()


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def text_hash(text: str) -> str:
    return _sha256(normalise(text).encode("utf-8")).hex()


def leaf_hash(celex: str, article: str, sha_of_text: str) -> str:
    """sha256(celex NUL article NUL text-hash), reproduced byte for byte in Solidity and in the
    sidecar. The separators are explicit because "5" + "1" and "51" must not fold into one leaf.
    """
    raw = celex.encode() + b"\x00" + article.encode() + b"\x00" + bytes.fromhex(sha_of_text.removeprefix("0x"))
    return _sha256(raw).hex()


def merkle(leaves: list[str]) -> tuple[str, list[list[str]]]:
    """The root, and an inclusion proof per leaf, in the duplicate-the-last form.

    Both sides - this and the contract - must agree on the odd level, so the rule is stated once
    here and copied into Solidity as the same two lines: pad the level with its own last node, then
    pair from the left.
    """
    hashes = [bytes.fromhex(leaf.removeprefix("0x")) for leaf in leaves]
    levels: list[list[bytes]] = []
    current = list(hashes)
    while len(current) > 1:
        if len(current) % 2:
            current = current + [current[-1]]
        levels.append(current)
        current = [_sha256(current[index] + current[index + 1]) for index in range(0, len(current), 2)]
    root = ("0x" + current[0].hex()) if current else "0x" + ("00" * 32)
    proofs: list[list[str]] = []
    for position in range(len(hashes)):
        path: list[str] = []
        walker = position
        for level in levels:
            path.append("0x" + level[walker ^ 1].hex())
            walker >>= 1
        proofs.append(path)
    return root, proofs


@dataclass(frozen=True)
class Article:
    """One article of one statute, with whatever of it this machine actually has.

    `law_id` is the address. `(celex, article)` is not: the Accounting Directive's annexes print
    "Article 19" four separate times, so 299 harvested articles fold into 221 distinct references,
    and a citation that gives only the reference is ambiguous one time in four. The id is the
    article's position in this harvest, which is why it only means anything beside the root.
    """

    celex: str
    article: str
    statute: str
    position: int
    text_sha256: str
    leaf: str
    chars: int
    text: str = ""
    copies: int = 1

    @property
    def law_id(self) -> str:
        return f"law-{self.position}"

    @property
    def ref(self) -> str:
        return f"{self.celex} Article {self.article}"

    @property
    def has_text(self) -> bool:
        return bool(self.text)

    def excerpt(self, limit: int = 1200) -> str:
        flat = normalise(self.text)
        return flat[:limit] + ("..." if len(flat) > limit else "")


def ordered_articles(statutes: list[dict[str, Any]]) -> list[tuple[str, str, str, str]]:
    """(celex, title, article, text) for every article, in the one order the leaves are built in.

    Both the file of hashes and the loaded index walk this, so the text an index entry resolves to
    is the text whose hash is in that entry. Two hand-written orderings would be the way that breaks.
    """
    out: list[tuple[str, str, str, str]] = []
    for document in sorted(statutes, key=lambda doc: str(doc.get("celex", ""))):
        celex = str(document.get("celex", ""))
        title = str(document.get("title", ""))[:120]
        for entry in sorted(document.get("articles") or [],
                            key=lambda article: natural_key(article.get("article", ""))):
            out.append((celex, title, str(entry.get("article", "")).strip(), str(entry.get("text", ""))))
    return out


class CorpusIndex:
    """Every article the firm was built on, addressable, findable, and checkable against itself."""

    def __init__(self, law: dict[str, Any], statutes: list[dict[str, Any]] | None = None) -> None:
        self.law = law
        walk = ordered_articles(statutes or [])
        entries = list(law.get("articles") or [])
        copies: Counter = Counter((celex, number) for celex, _title, number, _text in walk)
        self.articles: list[Article] = []
        for position, entry in enumerate(entries):
            celex, number = entry.get("celex", ""), str(entry.get("article", ""))
            # The leaf at this position and the text at this position come from the same walk, so they
            # line up only while the corpus on disk is the corpus this file was built from. When it is
            # not, the text stays empty and every quote against it is refused rather than compared to
            # a neighbour's words.
            text = ""
            if position < len(walk) and walk[position][0] == celex and walk[position][2] == number:
                text = walk[position][3]
            self.articles.append(
                Article(celex=celex, article=number, statute=entry.get("statute", ""),
                        position=position, text_sha256=entry.get("text_sha256", ""),
                        leaf=entry.get("leaf", ""), chars=int(entry.get("chars") or 0),
                        text=text, copies=copies.get((celex, number), 1)))
        self._by_id = {article.law_id: article for article in self.articles}
        self._by_ref: dict[tuple[str, str], list[Article]] = {}
        for article in self.articles:
            self._by_ref.setdefault((article.celex, article.article), []).append(article)
        self._proofs = dict(zip(range(len(self.articles)), merkle([a.leaf for a in self.articles])[1]))
        self._tf: list[Counter] | None = None
        self._df: dict[str, int] = {}

    # ------------------------------------------------------------------------ loading

    @classmethod
    def load(cls, law_file: str | Path | None = None, corpus_dir: str | Path | None = None) -> "CorpusIndex":
        path = Path(law_file) if law_file else LAW_FILE
        if not path.exists():
            raise FileNotFoundError(
                f"{path} is not there yet: run `python -m twin.audit.index build` to hash the"
                " harvested corpus into the law the firm cites from"
            )
        directory = Path(corpus_dir) if corpus_dir else CORPUS_DIR
        return cls(json.loads(path.read_text(encoding="utf-8")), load_statutes(directory))

    @property
    def state(self) -> str:
        """`checked` when quotes can be verified here, `hashed` when only the hashes are present."""
        return "checked" if self.with_text else "hashed"

    @property
    def with_text(self) -> int:
        return sum(1 for article in self.articles if article.has_text)

    def counts(self) -> dict[str, Any]:
        return {
            "state": self.state, "articles": len(self.articles), "statutes": len(self.statutes()),
            "references": len(self._by_ref),
            "ambiguous": sum(1 for found in self._by_ref.values() if len(found) > 1),
            "with_text": self.with_text, "root": self.law.get("root", ""),
            "harvested_at": self.law.get("harvested_at", ""), "built_at": self.law.get("built_at", ""),
            "licence": self.law.get("licence", ""),
        }

    def statutes(self) -> list[dict[str, Any]]:
        return list(self.law.get("statutes") or [])

    # ------------------------------------------------------------------------ addressing

    def find(self, law_id: str) -> Article | None:
        return self._by_id.get(str(law_id).strip())

    def resolve(self, celex: str, article: str) -> list[Article]:
        """Every article printed under that reference. More than one for an annex repeat."""
        if not celex or not article:
            return []
        wanted = str(article).strip().lstrip("Article ").strip()
        return list(self._by_ref.get((celex.strip(), wanted), []))

    def get(self, celex: str, article: str) -> Article | None:
        """The article that reference names, but only where it names exactly one."""
        found = self.resolve(celex, article)
        return found[0] if len(found) == 1 else None

    def known(self, celex: str, article: str) -> bool:
        return bool(self.resolve(celex, article))

    def proof(self, cite: dict[str, Any]) -> dict[str, Any]:
        """What a contract needs to check a citation: the leaf, its position and the path to the root."""
        found, reason = self._resolve(cite)
        if found is None:
            return {"anchored": False, "reason": reason}
        return {"anchored": True, "law_id": found.law_id, "ref": found.ref, "index": found.position,
                "leaf": "0x" + found.leaf, "text_sha256": "0x" + found.text_sha256,
                "proof": self._proofs.get(found.position, []), "root": self.law.get("root", "")}

    # ------------------------------------------------------------------------ finding

    def _term_counts(self) -> list[Counter]:
        if self._tf is None:
            self._tf = [Counter(words(article.text)) for article in self.articles]
            self._df = {}
            for counter in self._tf:
                for term in counter:
                    self._df[term] = self._df.get(term, 0) + 1
        return self._tf

    def retrieve(self, query: str, k: int = 6) -> list[Article]:
        """The articles that answer a question, best first, by BM25 over the statute text.

        Nothing is filtered by topic, role or statute: the point is that the machine does not
        already know which article the answer is in. Ties break on the reference, so two runs on
        two machines return the same list from the same corpus.
        """
        terms = set(words(query))
        if not terms or not self.with_text:
            return []
        counts = self._term_counts()
        lengths = [sum(counter.values()) or 1 for counter in counts]
        average = sum(lengths) / len(lengths)
        documents = len(counts)
        scored: list[tuple[float, str, str, Article]] = []
        for index, counter in enumerate(counts):
            article = self.articles[index]
            score = 0.0
            for term in terms:
                frequency = counter.get(term, 0)
                if not frequency:
                    continue
                containing = self._df.get(term, 0)
                idf = math.log(1 + (documents - containing + 0.5) / (containing + 0.5))
                score += idf * (frequency * (K1 + 1)) / (
                    frequency + K1 * (1 - B + B * lengths[index] / average))
            if score > 0:
                scored.append((score, article.celex, article.article, article))
        scored.sort(key=lambda entry: (-entry[0], entry[1], natural_key(entry[2])))
        return [entry[3] for entry in scored[:k]]

    def passages(self, query: str, k: int = 6, limit: int = 0) -> list[dict[str, Any]]:
        """The retrieved text, in the shape a prompt is built from - address first, words second.

        The `law_id` travels with every passage because the prompt asks for it back. A model that was
        handed six articles and no ids would have to reproduce a reference exactly to be checkable,
        and the interesting failures are the ones where it does not.

        `limit` truncates, and the truncated text is what `shown` carries. It matters which of the two
        a quote is compared against: checked against the full article, a sentence the model remembered
        from the part that was never sent passes; checked against `shown`, only the words it was
        actually given can be quoted back.
        """
        return [{"law_id": a.law_id, "celex": a.celex, "article": a.article, "statute": a.statute,
                 "ref": a.ref, "copies": a.copies, "text_sha256": a.text_sha256, "text": a.text,
                 "shown": a.excerpt(limit) if limit else a.text}
                for a in self.retrieve(query, k)]

    # ------------------------------------------------------------------------ checking

    def _resolve(self, cite: dict[str, Any]) -> tuple[Article | None, str]:
        """The one article a citation points at, or the reason it does not point at exactly one.

        An id and a reference that disagree is a different failure from a reference that repeats, and
        both differ from a number nobody harvested. Each gets its own sentence because each wants a
        different fix.
        """
        celex = str(cite.get("celex", "")).strip()
        number = str(cite.get("article", "")).strip().lstrip("Article ").strip()
        claimed = f"{celex} Article {number}" if celex and number else ""
        wanted = str(cite.get("law_id", "")).strip()
        if wanted:
            found = self.find(wanted)
            if found is None:
                return None, f"{wanted} is not an article of this harvest"
            if claimed and found.ref != claimed:
                return None, f"the citation names {claimed}, but {wanted} is {found.ref}"
            return found, ""
        if not claimed:
            return None, "the citation gives neither an article id nor a statute and an article number"
        matches = self.resolve(celex, number)
        if len(matches) == 1:
            return matches[0], ""
        if matches:
            return None, (f"{claimed} appears {len(matches)} times in this harvest, so the reference alone"
                          " does not say which article is meant - cite the id")
        return None, f"{claimed} is not in the law this firm was built on"

    def cite_of(self, cite: dict[str, Any]) -> dict[str, str]:
        """A citation turned into the fields an engagement file stores about it.

        The text hash comes back with the reference, so a stored finding carries the address of the
        article it quotes *and* the digest of the text it was read out of - which is what a reader can
        line up against the Merkle root when the harvest is re-run. An id that resolves to nothing
        still returns a dict, because a finding has to be able to say what it pointed at.
        """
        found, reason = self._resolve(cite)
        if found is None:
            return {"law_id": str(cite.get("law_id", "")), "ref": "", "state": "unresolved", "why": reason}
        return {"law_id": found.law_id, "celex": found.celex, "article": found.article,
                "statute": found.statute, "ref": found.ref, "text_sha256": found.text_sha256,
                "leaf": found.leaf, "copies": str(found.copies), "state": "verified"}

    def verify(self, cite: dict[str, Any]) -> str:
        """'' when the citation is a real article of this harvest and the quote is inside it.

        The reason comes back rather than raising, because a judgement that fails this check is still
        a fact about the model worth journalling: "invented a sentence" and "quoted Article 9(2) and
        attributed it to 9(3)" are different failures and want different fixes.
        """
        found, reason = self._resolve(cite)
        if found is None:
            return reason
        if not found.has_text:
            return "the corpus text is not on this machine, so no quote could be checked against it"
        wanted = normalise(str(cite.get("quote", ""))).strip(' .')
        if len(wanted) < MIN_QUOTE_CHARS:
            return f"the quote is {len(wanted)} characters, too short to vouch for anything"
        if wanted.lower() in normalise(found.text).lower():
            return ""
        return f"that sentence does not appear in {found.ref}"

    def figures(self, cite: dict[str, Any]) -> set[str]:
        """Every number the cited article states, for the check that a model may quote the law's figures."""
        found, _reason = self._resolve(cite)
        if found is None or not found.has_text:
            return set()
        return set(re.findall(r"\d[\d.,]*", normalise(found.text)))


# ------------------------------------------------------------------------ building

def natural_key(article: str) -> tuple:
    """`17a` after `17`, and both before `18` - the order the Official Journal prints them in."""
    match = re.match(r"(\d+)([a-z]*)", str(article).strip())
    return (int(match.group(1)), match.group(2)) if match else (10_000, str(article))


def _manifest_field(name: str) -> str:
    if not MANIFEST_FILE.exists():
        return ""
    try:
        return str(json.loads(MANIFEST_FILE.read_text(encoding="utf-8")).get(name, ""))
    except json.JSONDecodeError:
        return ""


def build(statutes: list[dict[str, Any]] | None = None, corpus_dir: str | Path | None = None) -> dict[str, Any]:
    """Hash every article on disk into the law file, in a fixed order, with the root over them."""
    where = Path(corpus_dir) if corpus_dir else CORPUS_DIR
    documents = statutes if statutes is not None else load_statutes(where)
    entries: list[dict[str, Any]] = []
    for celex, title, number, text in ordered_articles(documents):
        sha = text_hash(text)
        entries.append({"celex": celex, "article": number, "statute": title, "text_sha256": sha,
                        "leaf": leaf_hash(celex, number, sha), "chars": len(normalise(text))})
    root, proofs = merkle([entry["leaf"] for entry in entries])
    for entry, path in zip(entries, proofs):
        entry["proof_steps"] = len(path)
    return {
        "note": "Hashes of the harvested EU articles the firm cites, and the Merkle root over them."
                " Derived by `python -m twin.audit.index build`; no article text is in this file.",
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "harvested_at": _manifest_field("harvested_at"),
        "licence": _manifest_field("licence"),
        "corpus_dir": corpus_place(where),
        "count": len(entries),
        "references": len({(entry["celex"], entry["article"]) for entry in entries}),
        "root": root,
        "statutes": [{"celex": celex, "title": next((e["statute"] for e in entries if e["celex"] == celex), ""),
                      "articles": sum(1 for e in entries if e["celex"] == celex)}
                     for celex in sorted({entry["celex"] for entry in entries})],
        "articles": entries,
    }


def write_law(law: dict[str, Any], path: str | Path | None = None) -> Path:
    target = Path(path) if path else LAW_FILE
    target.write_text(json.dumps(law, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    return target


def check(corpus_dir: str | Path | None = None) -> dict[str, Any]:
    """Re-hash what is on disk and say where it disagrees with the tracked law file.

    This is the one command that turns "the harvest cannot be reproduced" from a sentence in a
    README into a non-zero exit: an article whose text moved has a different leaf, and every figure
    derived from it is now a claim about a document that is not there any more. Position is compared,
    not reference, because the references repeat and the positions do not.
    """
    law = json.loads(LAW_FILE.read_text(encoding="utf-8")) if LAW_FILE.exists() else {}
    tracked = list(law.get("articles") or [])
    fresh = build(corpus_dir=corpus_dir)
    present = fresh["articles"]
    moved = [f"{entry['celex']} art {entry['article']}" for entry, other in zip(tracked, present)
             if entry["leaf"] != other["leaf"]]
    return {
        "tracked": len(tracked), "on_disk": len(present),
        "size_changed": len(tracked) != len(present),
        "text_moved": moved[:12], "moved_count": len(moved),
        "root_matches": fresh.get("root") == law.get("root"),
    }


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "stats"
    if command == "build":
        law = build()
        path = write_law(law)
        print(f"{law['count']} articles over {len(law['statutes'])} statutes, {law['references']} distinct"
              f" references -> {path}")
        print(f"root {law['root']}")
        if not law["count"]:
            print("nothing was hashed: the corpus directory is empty, so run"
                  " `python -m twin.audit.corpus harvest` first")
            return 1
        return 0
    if command == "check":
        report = check()
        for key, value in report.items():
            print(f"{key}: {value}" if not isinstance(value, list)
                  else f"{key}: {len(value)} -> {value[:6]}")
        return 0 if report["root_matches"] and not report["moved_count"] else 1
    if command == "find":
        query = " ".join(argv[2:]) or "rotation of the audit firm"
        index = CorpusIndex.load()
        for found in index.retrieve(query, 8):
            print(f"{found.law_id:>8} {found.celex} art {found.article:>5}"
                  f"{' (x%d)' % found.copies if found.copies > 1 else '      '}  {found.excerpt(120)}")
        return 0
    if command == "verify":
        index = CorpusIndex.load()
        cite = {"law_id": argv[2] if argv[2].startswith("law-") else "",
                "celex": argv[2] if not argv[2].startswith("law-") else "",
                "article": argv[3], "quote": " ".join(argv[4:])}
        reason = index.verify(cite)
        print(reason or f"verified in {cite['law_id'] or cite['celex'] + ' article ' + cite['article']}")
        return 0 if not reason else 1
    index = CorpusIndex.load()
    print(json.dumps(index.counts(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
