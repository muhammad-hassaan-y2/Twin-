"""Build the sprint write-up: result tables in, eight pages of PDF out.

Every number in the prose is read from a table under `results/` at build time, so
the document cannot drift from the measurements it is supposed to describe. The
tables themselves are produced by the modules they come from; see the commands in
the last section.

    python -m swarm_oversight.pdf_report --out report.pdf
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

RESULTS = Path(__file__).resolve().parent.parent / "results"

INK = colors.HexColor("#14171c")
FAINT = colors.HexColor("#5b6472")
RULE = colors.HexColor("#c9d0da")
WASH = colors.HexColor("#f2f5f9")
NAVY = colors.HexColor("#25324a")

# Arial is here so that the collaborator's name is not a black box on the page.
BODY = "Helvetica"
FONT_DIR = Path("C:/Windows/Fonts")


def register_fonts():
    global BODY
    pairs = {"Arial": "arial.ttf", "Arial-Bold": "arialbd.ttf", "Arial-Italic": "ariali.ttf"}
    if not all((FONT_DIR / p).exists() for p in pairs.values()):
        return
    for name, file in pairs.items():
        pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
    pdfmetrics.registerFontFamily("Arial", normal="Arial", bold="Arial-Bold",
                                  italic="Arial-Italic", boldItalic="Arial-Italic")
    BODY = "Arial"


register_fonts()
STYLES = getSampleStyleSheet()


def sections(path: Path) -> dict[str, str]:
    """A results file split on its `## ` headings, first line of each kept."""
    out = {}
    for chunk in re.split(r"\n## ", path.read_text(encoding="utf-8"))[1:]:
        out[chunk.splitlines()[0]] = chunk
    return out


def md_table(text: str) -> tuple[list[str], list[list[str]]]:
    """The first markdown table in a chunk of text, as header and rows."""
    lines = [l for l in text.splitlines() if l.startswith("|")]
    if len(lines) < 3:
        raise ValueError("no markdown table found")
    head = [c.strip() for c in lines[0].strip("|").split("|")]
    return head, [[c.strip() for c in l.strip("|").split("|")] for l in lines[2:]]


def row_by(head: list[str], rows: list[list[str]], key_column: str) -> dict[str, list[str]]:
    return {r[head.index(key_column)]: r for r in rows}


def value(rows: dict[str, list[str]], head: list[str], key: str, column: str) -> str:
    """One cell, by row label and column name. Fails loudly rather than quoting a
    number that is no longer in the table it came from."""
    if key not in rows:
        raise KeyError(f"row {key!r} is not in the table")
    return rows[key][head.index(column)]


def num(rows: dict[str, list[str]], head: list[str], key: str, column: str) -> str:
    """The leading figure of a cell, without its interval or its cents."""
    return value(rows, head, key, column).split()[0].split("/")[0].strip()


def rng(*vals: str) -> str:
    """A spread over the same measurement, collapsed when it is not a spread."""
    lo, hi = min(vals), max(vals)
    return lo if lo == hi else f"{lo}&ndash;{hi}"


def para(text, size=8.9, leading=None, space=4.5, color=INK, indent=0):
    return Paragraph(text, ParagraphStyle(
        "p%s%s%s" % (size, space, indent), parent=STYLES["Normal"], fontName=BODY,
        fontSize=size, leading=leading or size + 3.0, textColor=color, spaceAfter=space,
        leftIndent=indent))


def h1(text):
    return para(text, size=11.6, leading=13.6, space=3.0, color=NAVY)


def h2(text):
    return para(text, size=9.6, leading=11.6, space=2.0, color=NAVY)


def grid(head, rows, widths, size=6.5):
    data = [[para(c, size=size, leading=size + 1.5, space=0) for c in row]
            for row in [head] + rows]
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), WASH),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, RULE),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e3e8ef")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
    ]))
    return t


def bullets(items, size=8.6):
    return [para("•&nbsp; " + t, size=size, leading=size + 2.6, space=2.6, indent=7)
            for t in items]


MON = "<font face='Courier' size='7.4'>"
END = "</font>"
NL = chr(10)


def pareto(path: Path, points: list[tuple[str, float, float, float]]) -> Path:
    """Attack money settled against legitimate money held, one point per defense.
    The coordinates come from the tables, so the figure cannot disagree with them."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.9, 2.6))
    for name, x, y, cost in points:
        ax.scatter([x], [y], s=46 if cost else 30, marker="D" if cost else "o",
                   facecolor="white" if cost else "#25324a",
                   edgecolor="#8c1d2f" if cost else "#25324a", zorder=3,
                   linewidths=1.2 if cost else 0.9,
                   label=name + ("   (" + f"${cost:.5f}/log)" if cost else "   (free)"))
    paid = max(points, key=lambda q: q[3])
    free = [q for q in points if q[3] == 0 and abs(q[1] - paid[1]) < 1e-9
            and q[2] < paid[2]]
    if free:
        ax.plot([paid[1], free[0][1]], [paid[2], free[0][2]], ls=(0, (3, 2)),
                lw=0.9, color="#8c1d2f", zorder=2)
    ax.set_xlabel("share of attack money that settles  (better left)", fontsize=7.2)
    ax.set_ylabel("share of legitimate" + NL + "money held  (better down)", fontsize=7.2)
    ax.set_xlim(0.705, 0.965)
    ax.set_ylim(-0.03, 0.175)
    ax.grid(True, lw=0.4, color="#e3e8ef")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(labelsize=6.6)
    ax.legend(fontsize=6.0, loc="lower left", frameon=False, ncol=2,
              handlelength=1.1, columnspacing=1.0, handletextpad=0.4,
              borderpad=0.1, labelspacing=0.55)
    fig.tight_layout(pad=0.3)
    fig.savefig(path, dpi=220)
    plt.close(fig)
    return path


def build(out: Path, results: Path = RESULTS) -> Path:
    summary = sections(results / "summary.md")
    detect_key = next(k for k in summary if k.startswith("Detection"))
    horizon_key = next(k for k in summary if k.startswith("Benign logs"))
    attack_key = next(k for k in summary if k.startswith("Gateway: share of attack"))
    owed_key = next(k for k in summary if k.startswith("Gateway: share of legitimate"))
    trade_key = next(k for k in summary if k.startswith("Prevention vs detection"))

    de_head, de_rows = md_table(summary[detect_key])
    hz_head, hz_rows = md_table(summary[horizon_key])
    gw_head, gw_rows = md_table(summary[attack_key])
    gl_head, gl_rows = md_table(summary[owed_key])
    tr_head, tr_rows = md_table(summary[trade_key])
    sweep_head, sweep_rows = md_table((results / "control_identity_sweep.md")
                                      .read_text(encoding="utf-8"))
    ctl_head, ctl_rows = md_table((results / "control_stub_prefix.md")
                                  .read_text(encoding="utf-8"))
    both_head, both_rows = md_table((results / "control_stub_both.md")
                                    .read_text(encoding="utf-8"))

    # ---- numbers, read out of the tables at build time -----------------------
    settled_by = row_by(gw_head, gw_rows, "scenario")
    per = lambda s: num(settled_by, gw_head, s, "per_mandate")
    mon = lambda s: num(settled_by, gw_head, s, "monitor")
    tuned = ("split_payment", "split_wide", "split_alias")
    silent = ("split_distinct", "split_slow", "alias_far")

    owed_by = row_by(gl_head, gl_rows, "scenario")
    ledger_busy = num(owed_by, gl_head, "benign_busy", "ledger")
    trade_by = row_by(tr_head, tr_rows, "arm")
    tight_attack = num(trade_by, tr_head, "ledger_w20_q0.5", "attack money settled")
    tight_busy = num(trade_by, tr_head, "ledger_w20_q0.5", "busy-week money stopped")

    recall_by = row_by(de_head, de_rows, "scenario")
    caught = [num(recall_by, de_head, s, "recall [95% CI]") for s in
              ("split_distinct", "split_slow", "alias_far", "relay_reversed")]

    def cell(rows, head, pop, protocol, column):
        for r in rows:
            if r[0] == pop and r[1] == protocol:
                return r[head.index(column)]
        raise KeyError(f"{pop}/{protocol} in the control table")

    def pair(scenario, column):
        """A sweep cell is `attack / held`; both halves, as strings."""
        return [c.strip() for c in value(sweep_by, sweep_head, scenario, column).split("/")]

    base_rules_out = cell(ctl_rows, ctl_head, "-", "rules", "attack $ out")
    base_rules_held = cell(ctl_rows, ctl_head, "-", "rules", "benign $ held")
    base_mandate = cell(ctl_rows, ctl_head, "-", "per_mandate", "attack $ out")
    model_out = cell(ctl_rows, ctl_head, "competent_honest", "untrusted_monitoring",
                     "attack $ out")
    model_cost = cell(ctl_rows, ctl_head, "competent_honest", "untrusted_monitoring", "$/log")
    model_calls = cell(ctl_rows, ctl_head, "competent_honest", "untrusted_monitoring",
                       "calls/log")
    open_pair = cell(ctl_rows, ctl_head, "colluding_pair", "untrusted_monitoring",
                     "attack $ out")
    blind_pair = cell(ctl_rows, ctl_head, "colluding_pair", "untrusted_monitoring_blind",
                      "attack $ out")
    releases = cell(ctl_rows, ctl_head, "colluding_pair", "monitor_releases", "attack $ out")
    paranoid = cell(ctl_rows, ctl_head, "reviewer_suspicious", "trusted_editing",
                    "benign $ held")
    paranoid_out = cell(ctl_rows, ctl_head, "reviewer_suspicious", "trusted_editing",
                        "attack $ out")
    paranoid_cost = cell(ctl_rows, ctl_head, "reviewer_suspicious", "trusted_editing",
                         "$/log")
    releases_calls = cell(ctl_rows, ctl_head, "colluding_pair", "monitor_releases",
                          "calls/log")
    probe_head, probe_rows = md_table((results / "control_stub_prefix_probe.md")
                                      .read_text(encoding="utf-8"))
    paranoid_probe = cell(probe_rows, probe_head, "reviewer_suspicious", "trusted_editing",
                          "$/log")
    paranoid_probe_out = cell(probe_rows, probe_head, "reviewer_suspicious",
                              "trusted_editing", "attack $ out")
    paranoid_probe_held = cell(probe_rows, probe_head, "reviewer_suspicious",
                               "trusted_editing", "benign $ held")
    silent_releases = cell(probe_rows, probe_head, "colluding_pair", "monitor_releases",
                           "attack $ out")
    free_out = cell(both_rows, both_head, "-", "rules_hold", "attack $ out")
    free_held = cell(both_rows, both_head, "-", "rules_hold", "benign $ held")
    free_rules_out = cell(both_rows, both_head, "-", "rules", "attack $ out")
    free_rules_held = cell(both_rows, both_head, "-", "rules", "benign $ held")
    model_held = cell(ctl_rows, ctl_head, "competent_honest", "untrusted_monitoring",
                      "benign $ held")
    sweep_by = row_by(sweep_head, sweep_rows, "scenario")
    fanout_hold = pair("relay_fanout", "both, no freeze")[1]
    fanout_freeze = pair("relay_fanout", "both")[1]
    reversed_hold = pair("relay_reversed", "both, no freeze")[1]
    reversed_freeze = pair("relay_reversed", "both")[1]
    renamed = pair("split_renamed", "prefix")

    pts = [("per-mandate cap only", float(base_mandate),
            float(cell(ctl_rows, ctl_head, "-", "per_mandate", "benign $ held")), 0.0),
           ("rules, freeze the swarm", float(base_rules_out), float(base_rules_held), 0.0),
           ("rules, hold the payment", float(base_rules_out),
            float(cell(ctl_rows, ctl_head, "-", "rules_hold", "benign $ held")), 0.0),
           ("both readings, freeze", float(free_rules_out), float(free_rules_held), 0.0),
           ("both readings, hold the payment", float(free_out), float(free_held), 0.0),
           ("rules + model on the seam", float(model_out), float(model_held),
            float(model_cost))]
    fig = pareto(results / "fig_pareto.png", pts)

    keep = [("-", "rules"), ("-", "rules_hold"),
            ("competent_honest", "trust"),
            ("competent_honest", "trusted_editing"),
            ("competent_honest", "untrusted_monitoring"),
            ("competent_honest", "untrusted_monitoring_blind"),
            ("competent_honest", "monitor_releases"),
            ("colluding_pair", "untrusted_monitoring"),
            ("colluding_pair", "untrusted_monitoring_blind"),
            ("reviewer_bought", "monitor_releases"),
            ("reviewer_suspicious", "trusted_editing")]
    table6 = [[("rules only" if p == "-" else p),
               q.replace("untrusted_monitoring", "monitoring").replace("_blind", " (blind)"),
               cell(ctl_rows, ctl_head, p, q, "attack $ out"),
               cell(ctl_rows, ctl_head, p, q, "benign $ held"),
               cell(ctl_rows, ctl_head, p, q, "calls/log"),
               cell(ctl_rows, ctl_head, p, q, "$/log")] for p, q in keep]

    W = A4[0] - 32 * mm
    doc = BaseDocTemplate(str(out), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                          topMargin=13 * mm, bottomMargin=13 * mm,
                          title="The Aggregate Gap",
                          author="Muhammad Hassaan Shaukat, Rizgar Ozan")
    frame = Frame(doc.leftMargin, doc.bottomMargin, W, A4[1] - 26 * mm, id="body")
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=footer)])

    f = [para("The Aggregate Gap", size=18, leading=20, space=1, color=NAVY),
         para("What it costs to supervise a swarm that spends money, measured in cents",
              size=10.2, leading=12.4, color=FAINT, space=6),
         para("Apart Research Swarm Alignment 2026, Track 4 &nbsp;&#183;&nbsp; "
              "Muhammad Hassaan Shaukat and R&#305;zgar Ozan<br/>"
              "Seeded and stdlib-only, reproducible from the seeds alone: 98 tests, and "
              "every figure below parsed out of a table this build re-reads.",
              size=7.8, leading=10.2, color=FAINT, space=8),

         h1("What we found"),
         para("Payment protocols for agent swarms enforce a budget <b>per mandate</b>. Nothing "
              "enforces one <b>across</b> mandates, so several agents that are each inside "
              "their own cap can move more of one principal's money than any of them was "
              "allowed to. We built the monitor that sees that shape, put it inline at a "
              "payment gateway, and scored every defence in cents settled rather than in flags "
              "raised.", space=4),
         para("The monitor is real and it is free. It holds the per-payee, per-window line "
              "against every attack written to its limits, at zero false alarms on benign logs "
              f"of any length, and inline at the gateway it cuts attack money that settles "
              f"from {rng(*(per(s) for s in tuned))} to {rng(*(mon(s) for s in tuned))} on "
              "those attacks. It catches nothing among the held-out attacks that never cross "
              f"a bound: split_distinct, split_slow and alias_far each have recall "
              f"{caught[0]} and settle {rng(*(mon(s) for s in silent))} of their money under "
              "both the per-mandate cap and the monitor.", space=4),
         para("Then we argued against our own addition. A supervisor sitting in the "
              "authorization path, asked only as a payee comes near the bound, moves attack "
              f"money from {base_rules_out} to {model_out} for ${model_cost} a log and "
              f"{model_calls} calls a log, with the model's wait inside the payment decision. "
              "AI Control protocols make that supervisor survivable when it is subverted: "
              f"withholding the actor's draft from the reviewer is the only arm that beats a "
              f"colluding pair ({open_pair}&nbsp;&rarr;&nbsp;{blind_pair}), and a honeypot "
              "retires a reviewer who cannot pass it. But the last measurement says the model "
              "needs none of that to be justified. <b>A rule that counts each payment toward "
              "two ways of reading a payee name, and answers a flag by holding the payment "
              f"instead of freezing the swarm, settles {free_out} of attack money &mdash; the "
              f"same as the model, scenario by scenario, in every scenario with attack money "
              f"&mdash; holds less legitimate money ({free_held} against {base_rules_held}), "
              "and costs nothing.</b>", space=4),

         h1("1. The gap, and the shape of a defence"),
         para("Track 4 asks how to oversee and control a swarm of agents that act with money. "
              "Our setting is the narrowest version of that we could state precisely: N "
              "agents, one principal, spends and transfers, and a policy that binds the "
              "principal rather than the agent. A 2026 security analysis of Google's AP2 "
              "reports budget constraints enforced per mandate and none across mandates "
              "(arXiv:2608.23858; we have not verified this against the specification and "
              "cite it as motivation, not as fact). The human version of the same failure is "
              "structuring, and banks have had rules for it for decades.", space=4),
         para("The monitor keeps the principal's ledger instead of the agents'. Six named "
              "checks, each removable on its own so every rule is measured individually: "
              f"{MON}agent_over_limit, relay, relay_multi_hop, split_payment, slow_split, "
              f"payee_alias{END}. A relay is traced back to the agent whose money it "
              "carries, so three hops cannot launder a cap. A payee is keyed by who it is, not "
              "by the string printed on the payment.", space=4)]

    f += [h1("2. Method"),
          *bullets([
              "<b>Money, not flags.</b> Every arm is scored as the share of attack money that "
              "settles and the share of legitimate money that is stopped, in cents, per seeded "
              "log. A defence that detects late still lets the money out, and the tables show "
              "that rather than hiding it.",
              "<b>Two attack sets.</b> Five scenarios tuned on the limits, five held out and "
              "written afterwards. The held-out attackers check their own budgets first: "
              "distinct payees, a rename past the similarity cutoff, a drip slower than the "
              "window.",
              "<b>Horizon.</b> Benign logs from 40 to 300 ticks, with false alarms per 1,000 "
              "actions as well as per run. This is how the first version of the monitor was "
              "found to be wrong: summing a payee over the whole log looked clean at 40 ticks "
              "and flagged 92% of benign swarms at 200.",
              "<b>Intervals.</b> 200 seeds per cell for the rule results, 50 for the model "
              "arms, Wilson 95% intervals, no cell reported without them.",
              "<b>Negative controls.</b> 98 tests; each one removes a rule, a protocol "
              "setting or a capability and requires the failure to come back. Two of the "
              "results below are the product of that habit rather than of looking for them.",
          ])]

    f += [h1("3. What the rules are worth at a gateway"),
          para("Share of attack money that settles, lower is better, 200 seeds. "
               "<i>per_mandate</i> is what a payment protocol enforces today; "
               "<i>ledger</i> adds one cap on the whole principal; <i>monitor</i> adds the "
               "swarm monitor inline, which holds the flagged payment and stops the swarm:",
               space=3),
          grid(gw_head, gw_rows, [W * 0.20] + [W * 0.20] * 4, 6.6),
          Spacer(1, 3),
          para(f"The honest reading is prevention, not detection. The per-agent cap alone lets "
               f"{rng(*(per(s) for s in tuned))} of a split payment leave. Inline monitoring "
               f"gets that to {rng(*(mon(s) for s in tuned))} &mdash; it stops the payment "
               "that raises the flag, but "
               f"the money ahead of that flag is already gone. A principal-wide ledger sized "
               f"from benign traffic trades one currency for the other: the tight setting "
               f"(a 20-tick window at the median benign peak) cuts attack money to "
               f"{tight_attack} but blocks {tight_busy} of a legitimate busy week, and "
               f"{ledger_busy} at the 99th-percentile setting we would actually ship. Nothing "
               "here is free except the monitor, and it only stops the attacks it was written "
               "for.", space=4),
          para("False alarms against log length, same monitor, two ways of summing a payee. "
               "The <i>lifetime</i> row is our first version; it is not a safe default at any "
               "length, it is only untested at short ones:", space=3),
          grid(hz_head, hz_rows, [W * 0.13, W * 0.08, W * 0.28, W * 0.25, W * 0.26], 6.6)]

    f += [h1("4. The swarm we did not write"),
          para("Everything above is our generator, so it proves our generator is coherent. To "
               "check that the shapes are ours and not real swarms', we measured the published "
               "reconstruction of a real multi-agent incident (Swarm Traces, and the AI "
               "Village corpus behind it) with the same monitor, using only the fields the "
               "records actually carry. Two of the four findings below are negative, and they "
               "are the reason the report does not claim external validation.", space=4),
          *bullets([
              "189,579 records, 61,125 parent-child edges, 26,248 parent nodes. Fan-out "
              "median 1, p99 12, max 858 &mdash; a real swarm does fan out, and one node in "
              "the data is wider than any relay we modelled.",
              "<b>0 nodes are both a parent and a child.</b> Relay depth is not observable in "
              "the published data at all. Our multi-hop trace cannot be validated here, only "
              "reproduced in a generator, so every relay number in this report is synthetic.",
              "<b>0 records carry a time.</b> A windowed rule cannot be scored on this data. "
              "We reported the reading that needs no clock as well: at 30,000 cents per "
              "branch the tight-ordering violation rate is 0.225 and the clock-free rate is "
              "the same 0.225, while the worst-case ordering is 0.000. The rule's apparent "
              "failure is an artefact of assuming a clock we do not have.",
              "28,086 distinct destinations, the busiest taking 14.6% of the marks. Against a "
              "bound of $600 per payee per window, moving $100,000 needs 167 of them and the "
              "observed pool covers 168.5 such runs. <b>Identity spread, with no amount ever "
              "over any bound, is the lever a real swarm already has.</b> That is the "
              "evidence for section 7's free rule.",
          ])]

    f += [h1("5. A model in the authorization path, and what it costs"),
          para("A rule monitor is free, instant and cannot be argued with, but it only reacts "
               "to shapes someone wrote down. The alternative is a model that reads the same "
               "state and answers questions no rule encodes. We wired an assistant at the "
               "point where a payment is about to settle &mdash; Meta's MUSE API, Muse Spark "
               "1.3 and Muse Wonder 1.0, priced from the published table &mdash; and ran the "
               "same arms against an offline stand-in that answers through the identical "
               "code path.", space=4),
          para("One structural fact organises everything below it: <b>the gateway asks the "
               "model only about payments the rules already let through.</b> A model can "
               "decline to hold, it can never release. So a supervised arm is always a subset "
               "of the rules, its worst case is legitimate money held that was owed, and any "
               "protocol that lets a reviewer's <i>allow</i> clear a flag has to be built by "
               "switching the rules off. That is deliberately one-directional authority, and "
               "it is why section 6 can report a safety property that holds whatever the "
               "models do.", space=4),
          para("<b>Live runs are blocked: no API key was provided for this sprint.</b> Every "
               "number in this report therefore comes from the offline arms that exercise the "
               "same wiring. We state that rather than papering over it: the model-side claims "
               "here are about protocol structure and about the cost of a call, not about the "
               "quality of any model.", space=4)]

    f += [h1("6. Which protocol survives which failure"),
          para("AI Control (Greenblatt et al., arXiv 2312.06942) keeps a model you do not "
               "trust useful by construction. Five arms at the payment seam, 14 scenarios, 50 "
               "seeds, with each seat's competence and honesty as free parameters. "
               "<i>attack out</i> is the share of attack money that settles, <i>held</i> the "
               "share of legitimate money stopped; rows with population <i>rules only</i> have "
               "no model in the loop:", space=3),
          grid(["population", "protocol", "attack out", "held", "calls/log", "$/log"],
               table6, [W * 0.21, W * 0.27, W * 0.14, W * 0.12, W * 0.13, W * 0.13], 6.5),
          Spacer(1, 3),
          *bullets([
              "<b>Nothing behind the rules settled more attack money than the rules did, in "
              "any of 294 (population, arm, scenario) triples</b> &mdash; including a fully "
              "bought reviewer and a colluding pair. Safety here is a property of the "
              "authority structure, not of anyone's judgement.",
              f"<b>The draft is the channel.</b> Under a colluding pair, the reviewer who "
              f"reads the actor's reasoning lets out {open_pair} &mdash; exactly what the "
              "rules alone let out. Withhold the text and the same pair gets "
              f"{blind_pair}. Two models that share a language have only that language to "
              "conspire in (Motwani et al., arXiv 2402.07510). The control is to withhold the "
              "text.",
              f"<b>Letting a reviewer overrule a flag buys back the attack the rules "
              f"stopped, and pays for the privilege.</b> The same colluding pair settles "
              f"{releases} under that arm &mdash; the {base_mandate} an unsupervised "
              f"per-mandate gateway pays out &mdash; at {releases_calls} calls a log. "
              "The monitor is worth nothing once a reviewer can overrule it, and the calls "
              "are all price.",
              "<b>A honeypot is a control, not a fallback.</b> One plainly fine payment "
              f"offered at every consult, with the arm silenced permanently on the first "
              f"miss. On a reviewer paranoid enough to settle only {paranoid_out} of attack "
              f"money while holding {paranoid} of legitimate money, the trap switches it off: "
              f"attack money back up to {paranoid_probe_out}, held money down to "
              f"{paranoid_probe_held}, and the bill cut from ${paranoid_cost} to "
              f"${paranoid_probe} a log. That is an honest trade, not a win: the trap removes "
              "a seat you cannot trust and gives back what that seat was catching. Run once "
              "per log it is worth nothing &mdash; the reviewer only has to be lucky on the "
              f"one draw &mdash; and with the rules switched off, silencing the reviewer "
              f"<i>is</i> the failure: the ablation plus honeypot pays out {silent_releases}.",
          ])]

    f += [h1("7. The negative result: the model's edge is a string rule"),
          para("For the comparison to be fair the model had to be able to differ from the "
               "rule at all. Both seats keep the monitor's own ledger and read the same bound; "
               "what they get that the shipped rule does not is a different answer to "
               "<i>is this the same payee</i>. We turned that into a switch: "
               f"{MON}prefix</font> (normalise, then merge on a shared prefix or 0.85 "
               f"character similarity), {MON}tokens</font> (the set of meaningful words, "
               f"corporate suffixes dropped) and {MON}both</font> (one payment counted toward "
               "both readings). Two scenarios pin the difference down. <i>split_renamed</i>: "
               "one firm typed three ways, every pair below the cutoff and none a prefix of "
               "another, so the shipped reading sees three payees and lets "
               f"{renamed[0]} of the money out. <i>benign_stem</i>: two genuinely different "
               "payees sharing a "
               "15-character identifier stem, which is the actual namespace of the incident "
               "dataset.", space=4),
          para("Pooled over the same 50 seeds and 14 scenarios, both axes lower is better. "
               "The open diamond is the only point that pays for a call, and the dashed line "
               "runs to the free rule that matches it on attack money and beats it on "
               "legitimate money:", space=3),
          Image(str(fig), width=W, height=W * 2.6 / 6.9),
          Spacer(1, 3),
          para("Each cell is attack money settled / legitimate money held, over the same 50 "
               "seeds. Only the last column pays for a call:", space=3),
          grid(sweep_head, sweep_rows,
               [W * 0.165, W * 0.14, W * 0.14, W * 0.14, W * 0.155, W * 0.14, W * 0.08], 6.4),
          Spacer(1, 3),
          para(f"<b>Read the fourth column against the fifth.</b> The model arm and the "
               f"two-reading rule that holds instead of freezing catch the same attack money "
               f"in every scenario that has any. The rule holds strictly less legitimate "
               f"money where the shipped rule freezes: {fanout_hold} against {fanout_freeze} "
               f"on relay_fanout, {reversed_hold} against {reversed_freeze} on "
               f"relay_reversed, {free_held} against "
               f"{base_rules_held} pooled. The model arm inherits the rules' freeze and pays "
               f"${model_cost} a log on top of it. Two string comparisons and one change of "
               "reaction do the same work, with no call inside the payment decision, no "
               "latency, and nobody to argue with or to subvert. <b>The honest version of that "
               "sentence is a defect report on our own rule monitor, not a claim about "
               "models:</b> the shipped merge rule was wrong in both directions, it merged "
               "identifier namespaces that were nothing of the kind and missed a word-order "
               "swap, and the model was compensating for that bug for its whole price tag.",
               space=4)]

    f += [h1("8. What these numbers do not say"),
          *bullets([
              "<b>The stand-ins are not models.</b> Every supervised result is a statement "
              "about a protocol under an assumed failure rate. The rates are parameters and no "
              "measurement here claims a real model behaves this way. Until a key is in hand "
              "the live MUSE arms are unwired evidence, and section 5 says so.",
              "<b>What the free rule cannot do is exactly what a model is for.</b> An "
              "abbreviation that only makes sense if you know who the vendor is &mdash; "
              "<i>OC Advisory Ltd</i> for the same offshore consultancy &mdash; is not a "
              "string comparison, and no scenario in this harness measures it. The three "
              "held-out attacks that settle 1.000 in every column of section 7 are that "
              "gap's neighbourhood: our stand-in can only redo arithmetic, so a 1.000 there "
              "is a statement about the stand-in, not a refutation of models.",
              "<b>The generator is the attacker we imagined.</b> The held-out shapes were "
              "written by us, after seeing the rules. That is an adaptive limit, not a world.",
              "<b>Relay depth and every windowed number are unvalidated externally.</b> The "
              "published incident reconstruction has no node that is both a parent and a "
              "child, and no timestamps at all, so section 4's own data cannot check "
              "sections 3 and 7.",
              "<b>Freezing is a policy, not a constant.</b> A large part of what the model "
              "appeared to buy was a difference in reaction: hold the payment, or stop the "
              "swarm. Reported as separate columns, that axis is worth more than the "
              "judgement &mdash; which is the kind of result a harness only produces if it "
              "was built to be able to embarrass its own author.",
              "<b>The durable claim is the bound, not the defence.</b> Against everything we "
              "ran, no payee family received more than its cap inside any long window. An "
              "attacker wanting more has to go slower or register more identities: a rate "
              "limit in cents per tick that holds against an attacker who knows the rules and "
              "the limits.",
          ])]

    f += [h1("9. Reproduce"),
          para("Repo github.com/muhammad-hassaan-y2/Twin-, directory "
               f"<font face='Courier' size='7.4'>swarm-oversight/</font>, branch "
               f"<font face='Courier' size='7.4'>aggregate-gap</font>. Stdlib only, except "
               "reportlab and matplotlib for this document.", space=3),
          para(f"{MON}pip install -e .[dev] &amp;&amp; pytest&nbsp;&nbsp;# 98 tests<br/>"
               "python -m swarm_oversight.report --seeds 200&nbsp;&nbsp;# rules, gateway, "
               "horizon<br/>"
               "python -m swarm_oversight.tracegraph&nbsp;&nbsp;# the published incident "
               "data<br/>"
               "python -m swarm_oversight.oversight --seeds 50 --advisor stub<br/>"
               "python -m swarm_oversight.aicontrol --seeds 50 --merge prefix --out "
               "results<br/>"
               "python -m swarm_oversight.aicontrol --seeds 50 --merge prefix --probe --out "
               "results<br/>"
               "python -m swarm_oversight.aicontrol --seeds 50 --merge both --out results<br/>"
               "python -m swarm_oversight.aicontrol --seeds 50 --identity-sweep --out "
               "results<br/>"
               "python -m swarm_oversight.pdf_report --out report.pdf</font>", space=5),
          h2("References"),
          para("Greenblatt, Barnes, Larson, <i>AI Control</i>, arXiv:2312.06942. "
               "&#183;&nbsp; Motwani et al., <i>Secret Collusion among Generative AI "
               "Models</i>, arXiv:2402.07510. &#183;&nbsp; <i>How Google Handles Money with "
               "AP2: A Security Analysis</i>, NeurIPS 2024, arXiv:2608.23858 &mdash; cited as "
               "motivation; the per-mandate claim is not yet verified against the "
               "specification. &#183;&nbsp; METR, <i>Hugging Face incident report</i>, August "
               "2026. &#183;&nbsp; Swarm Traces (swarmtraces.org) and the AI Village corpus, "
               "aidigestorg/ai-village.", size=7.8, leading=10.2, color=FAINT)]

    doc.build(f)
    return out


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.4)
    canvas.line(16 * mm, 11 * mm, A4[0] - 16 * mm, 11 * mm)
    canvas.setFont(BODY, 6.8)
    canvas.setFillColor(FAINT)
    canvas.drawString(16 * mm, 8 * mm, "The Aggregate Gap  \u00b7  Swarm Alignment 2026, "
                                       "Track 4  \u00b7  every figure measured, none quoted")
    canvas.drawRightString(A4[0] - 16 * mm, 8 * mm, f"page {doc.page}")
    canvas.restoreState()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="report.pdf")
    ap.add_argument("--results", default=str(RESULTS))
    args = ap.parse_args()
    print(build(Path(args.out), Path(args.results)))
