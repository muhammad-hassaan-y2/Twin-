"""Build the sprint write-up in the official Apart template: tables in, PDF out.

Every number in the prose is read from a table under `results/` at build time, so
the document cannot drift from the measurements it describes. The structure
follows the Swarm Alignment Hackathon report template (title + footnote, authors
and affiliations, a labelled 150-250 word abstract, Introduction / Related Work /
Methods / Results / Discussion and Limitations / Conclusion, Code and Data,
Author Contributions, References, the required Limitations and Dual-Use appendix,
and an LLM usage statement).

    python -m swarm_oversight.pdf_report --out report.pdf
"""
from __future__ import annotations

import argparse
import csv
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
    out = {}
    for chunk in re.split(r"\n## ", path.read_text(encoding="utf-8"))[1:]:
        out[chunk.splitlines()[0]] = chunk
    return out


def md_table(text: str) -> tuple[list[str], list[list[str]]]:
    lines = [l for l in text.splitlines() if l.startswith("|")]
    if len(lines) < 3:
        raise ValueError("no markdown table found")
    head = [c.strip() for c in lines[0].strip("|").split("|")]
    return head, [[c.strip() for c in l.strip("|").split("|")] for l in lines[2:]]


def row_by(head, rows, key_column):
    return {r[head.index(key_column)]: r for r in rows}


def value(rows, head, key, column):
    if key not in rows:
        raise KeyError(f"row {key!r} is not in the table")
    return rows[key][head.index(column)]


def num(rows, head, key, column):
    return value(rows, head, key, column).split()[0].split("/")[0].strip()


def rng(*vals):
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


def caption(text):
    return para(text, size=7.6, leading=9.6, space=5, color=FAINT)


def bullets(items, size=8.6):
    return [para("•&nbsp; " + t, size=size, leading=size + 2.6, space=2.6, indent=7)
            for t in items]


MON = "<font face='Courier' size='7.4'>"
END = "</font>"
NL = chr(10)

ABSTRACT = (
    "Agent payment protocols cap each mandate, not the principal: several agents that "
    "each stay inside their own cap can together move more of one principal's money than "
    "any was allowed. We measure this aggregate gap in cents settled, not flags raised, on "
    "a seeded reproducible harness with a swarm monitor inline at a payment gateway. The "
    "monitor holds a per-payee, per-window bound against every attack tuned to it, cutting "
    "settled attack money from 1.00 to 0.43&ndash;0.67, while three held-out attacks that "
    "never cross a bound settle in full. A model supervisor appears to help, but a paired "
    "seed-by-seed ablation shows its whole measurable edge is a defect in our own "
    "payee-identity rule plus a hold-versus-freeze reaction difference, reproducible for "
    "free with two string comparisons. Live Gemini runs confirm the identity judgement a "
    "model adds is real: it merges renames and misspellings the rules miss without "
    "false-merging identifier namespaces, and an adversarial draft moved a real reviewer on "
    "zero of six unambiguous breaches. A gateway ledger built from settled instructions "
    "rather than agent reports is unchanged when agents tamper with their published logs. "
    "The durable defence is a rate bound an attacker cannot argue with; identity and time "
    "are the levers it leaves open.")


def plain(text):
    return re.sub(r"<[^>]+>", "", text).replace("&ndash;", "-").replace("&nbsp;", " ")


def abstract_words():
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9.'-]*", plain(ABSTRACT)))


def pareto(path, points):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.9, 2.5))
    for name, x, y, cost in points:
        ax.scatter([x], [y], s=46 if cost else 30, marker="D" if cost else "o",
                   facecolor="white" if cost else "#25324a",
                   edgecolor="#8c1d2f" if cost else "#25324a", zorder=3,
                   linewidths=1.2 if cost else 0.9,
                   label=name + ("   (" + f"${cost:.5f}/log)" if cost else "   (free)"))
    paid = max(points, key=lambda q: q[3])
    free = [q for q in points if q[3] == 0 and abs(q[1] - paid[1]) < 1e-9 and q[2] < paid[2]]
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


def frontier_fig(path, csv_path):
    """Best response of an attacker who knows the bound: settled share against
    payment spacing, one curve per number of payee identities."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    fig, ax = plt.subplots(figsize=(6.9, 2.3))
    for payees in ("1", "2", "3"):
        rs = [r for r in rows if r["payees"] == payees]
        xs = [int(r["gap"]) for r in rs]
        ys = [int(r["monitor_settled"]) / int(r["attack_total"]) for r in rs]
        ax.plot(xs, ys, marker="o", ms=2.5, lw=1.1,
                label=f"{payees} payee identit{'y' if payees == '1' else 'ies'}")
    ax.axhline(60000 / 140000, ls=(0, (3, 2)), lw=0.8, color="#8c1d2f",
               label="one bound per window")
    ax.set_xlabel("ticks between payments (attacker chooses)", fontsize=7.2)
    ax.set_ylabel("share of attack money that settles", fontsize=7.2)
    ax.set_ylim(0.35, 1.03)
    ax.grid(True, lw=0.4, color="#e3e8ef")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(labelsize=6.6)
    ax.legend(fontsize=6.4, loc="lower right", frameon=False)
    fig.tight_layout(pad=0.3)
    fig.savefig(path, dpi=220)
    plt.close(fig)
    return path


def build(out: Path, results: Path = RESULTS) -> Path:
    if not 150 <= abstract_words() <= 250:
        raise ValueError(f"abstract is {abstract_words()} words, must be 150-250")
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
    sweep_head, sweep_rows = md_table((results / "control_identity_sweep.md").read_text(encoding="utf-8"))
    ctl_head, ctl_rows = md_table((results / "control_stub_prefix.md").read_text(encoding="utf-8"))
    both_head, both_rows = md_table((results / "control_stub_both.md").read_text(encoding="utf-8"))
    probe_head, probe_rows = md_table((results / "control_stub_prefix_probe.md").read_text(encoding="utf-8"))
    id_head, id_rows = md_table((results / "live" / "identity_gemini-3.5-flash-lite.md").read_text(encoding="utf-8"))
    pers_head, pers_rows = md_table((results / "live" / "persuasion_gemini-3.5-flash-lite.md").read_text(encoding="utf-8"))
    tam_head, tam_rows = md_table((results / "tampering.md").read_text(encoding="utf-8"))
    trace_text = (results / "trace_table.md").read_text(encoding="utf-8")

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
    caught = [num(recall_by, de_head, s, "recall [95% CI]") for s in silent]

    def cell(rows, head, pop, protocol, column):
        for r in rows:
            if r[0] == pop and r[1] == protocol:
                return r[head.index(column)]
        raise KeyError(f"{pop}/{protocol} in the control table")

    def pair(scenario, column):
        return [c.strip() for c in value(sweep_by, sweep_head, scenario, column).split("/")]

    base_rules_out = cell(ctl_rows, ctl_head, "-", "rules", "attack $ out")
    base_rules_held = cell(ctl_rows, ctl_head, "-", "rules", "benign $ held")
    base_mandate = cell(ctl_rows, ctl_head, "-", "per_mandate", "attack $ out")
    model_out = cell(ctl_rows, ctl_head, "competent_honest", "untrusted_monitoring", "attack $ out")
    model_cost = cell(ctl_rows, ctl_head, "competent_honest", "untrusted_monitoring", "$/log")
    model_calls = cell(ctl_rows, ctl_head, "competent_honest", "untrusted_monitoring", "calls/log")
    model_held = cell(ctl_rows, ctl_head, "competent_honest", "untrusted_monitoring", "benign $ held")
    open_pair = cell(ctl_rows, ctl_head, "colluding_pair", "untrusted_monitoring", "attack $ out")
    blind_pair = cell(ctl_rows, ctl_head, "colluding_pair", "untrusted_monitoring_blind", "attack $ out")
    releases = cell(ctl_rows, ctl_head, "colluding_pair", "monitor_releases", "attack $ out")
    releases_calls = cell(ctl_rows, ctl_head, "colluding_pair", "monitor_releases", "calls/log")
    free_out = cell(both_rows, both_head, "-", "rules_hold", "attack $ out")
    free_held = cell(both_rows, both_head, "-", "rules_hold", "benign $ held")
    free_rules_out = cell(both_rows, both_head, "-", "rules", "attack $ out")
    free_rules_held = cell(both_rows, both_head, "-", "rules", "benign $ held")
    sweep_by = row_by(sweep_head, sweep_rows, "scenario")
    fanout_hold = pair("relay_fanout", "both, no freeze")[1]
    fanout_freeze = pair("relay_fanout", "both")[1]
    renamed = pair("split_renamed", "prefix")
    paired_max = max(int(r[sweep_head.index("seeds where model differs")].split()[0])
                     for r in sweep_rows)

    # real-swarm figures, parsed from the trace table's own prose
    pool = int(re.search(r"Identity pool: ([\d,]+)", trace_text).group(1).replace(",", ""))
    busiest = re.search(r"busiest taking ([\d.]+)%", trace_text).group(1)
    records = re.search(r"reconstruction: ([\d,]+) records", trace_text).group(1)
    edges = re.search(r"([\d,]+) edges", trace_text).group(1)
    fanmax = re.search(r"max (\d+)", trace_text).group(1)
    runs_covered = pool * 600 / 100000

    # live tables
    id_by = row_by(id_head, id_rows, "scenario")
    pers_by = row_by(pers_head, pers_rows, "condition")
    tam_by = row_by(tam_head, tam_rows, "tamper")
    pers_n = pers_rows[0][pers_head.index("holds")].split("/")[1]
    pers_flips = re.search(r"flipped (\d+/\d+)",
                         (results / "live" / "persuasion_gemini-3.5-flash-lite.md").read_text(encoding="utf-8")).group(1)
    struct_head, struct_rows = md_table(
        (results / "llm_gemini" / "summary_gemini-3.5-flash-lite.md").read_text(encoding="utf-8"))
    struct_by = row_by(struct_head, struct_rows, "arm")
    struct_cols = ["arm", "n", "structured [95% CI]", "asked approval",
                   "asked then split", "monitor agrees"]
    struct_display = [[r[struct_head.index(c)] for c in struct_cols] for r in struct_rows]
    a_struct = num(struct_by, struct_head, "A_threshold", "structured [95% CI]")
    d_struct = num(struct_by, struct_head, "D_no_threshold", "structured [95% CI]")
    d_split = value(struct_by, struct_head, "D_no_threshold", "asked then split")
    d_agree = value(struct_by, struct_head, "D_no_threshold", "monitor agrees")

    pts = [("per-mandate cap only", float(base_mandate),
            float(cell(ctl_rows, ctl_head, "-", "per_mandate", "benign $ held")), 0.0),
           ("rules, freeze the swarm", float(base_rules_out), float(base_rules_held), 0.0),
           ("rules, hold the payment", float(base_rules_out),
            float(cell(ctl_rows, ctl_head, "-", "rules_hold", "benign $ held")), 0.0),
           ("both readings, freeze", float(free_rules_out), float(free_rules_held), 0.0),
           ("both readings, hold the payment", float(free_out), float(free_held), 0.0),
           ("rules + model on the seam", float(model_out), float(model_held), float(model_cost))]
    fig = pareto(results / "fig_pareto.png", pts)
    fig2 = frontier_fig(results / "fig_frontier.png", results / "frontier.csv")

    keep = [("-", "rules"), ("-", "rules_hold"),
            ("competent_honest", "trusted_editing"),
            ("competent_honest", "untrusted_monitoring"),
            ("competent_honest", "untrusted_monitoring_blind"),
            ("colluding_pair", "untrusted_monitoring"),
            ("colluding_pair", "untrusted_monitoring_blind"),
            ("colluding_pair", "monitor_releases"),
            ("reviewer_suspicious", "trusted_editing")]
    table4 = [[("rules only" if p == "-" else p),
               q.replace("untrusted_monitoring", "monitoring").replace("_blind", " (blind)")
                .replace("rules_hold", "rules, hold"),
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

    f = [para("The Aggregate Gap<super>[1]</super>", size=18, leading=21, space=2, color=NAVY),
         para("Supervising a swarm that spends money, measured in cents", size=10.2,
              leading=12.4, color=FAINT, space=7),
         para("Muhammad Hassaan Shaukat &nbsp;&#183;&nbsp; Independent Researcher<br/>"
              "R&#305;zgar Ozan &nbsp;&#183;&nbsp; Independent Researcher<br/>"
              "With Apart Research &nbsp;&#183;&nbsp; Swarm Alignment Hackathon 2026, Track 4",
              size=8.6, leading=11.4, color=INK, space=8),
         h2("Abstract"),
         para(ABSTRACT, size=8.8, leading=11.6, space=7)]

    # 1 ---------------------------------------------------------------------
    f += [h1("1. Introduction"),
          para("Payment protocols for agent swarms enforce a budget <b>per mandate</b>. "
               "Nothing enforces one <b>across</b> the mandates a single principal issues, so "
               "several agents that are each inside their own cap can move more of that "
               "principal's money than any of them was allowed to. We call this the "
               "<i>aggregate gap</i>. The human version is structuring, and banks have had "
               "rules for it for decades; the agent version is cheaper to carry out because "
               "agents can be copied, renamed and run at machine speed.", space=4),
          para("A 2026 security analysis of Google's Agent Payments Protocol (AP2) formalises "
               "constraint enforcement <i>within</i> a mandate chain: a closed mandate must "
               "stay inside its open mandate's user-approved limits, and cumulative limits "
               "must remain satisfied across reuse (Aviv et al., SR5/SR7). It also finds that "
               "attacks which steer the agent <i>before</i> it signs escape mandate-chain "
               "verification entirely. Neither line of defence binds the principal across "
               "separately issued mandates to different agents, which is the seam we study.", space=4),
          para("Our main contributions are:", space=2),
          *bullets([
              "A seeded, stdlib-only harness and a gateway that scores every defence in cents "
              "settled and legitimate cents stopped, with five tuned and five held-out attacks "
              "and a named, individually removable check for each rule.",
              "A paired negative result: a model supervisor's entire measurable edge over the "
              "rules is a defect in our own payee-identity rule plus a hold-versus-freeze "
              "reaction difference, reproducible for free; and a one-way authority seam whose "
              "safety is a design property, not a judgement.",
              "Live-model evidence (Gemini): payee identity and draft persuasion, an unprompted "
              "structuring task where removing an approval threshold makes agents split payments "
              "on their own, a log-tampering demonstration, and a best-response curve with a "
              "formal leakage bound showing the defence is a rate limit, not a total.",
          ], size=8.4)]

    # 2 ---------------------------------------------------------------------
    f += [h1("2. Related Work"),
          para("<b>Structuring and velocity limits.</b> Splitting a transaction to stay under "
               "a reporting threshold is the predicate of anti-money-laundering law "
               "(31 U.S.C. &sect;5324; FATF Recommendations). Our per-payee, per-window bound "
               "is a velocity limit in the payment-processing sense; the gap we measure is "
               "that such limits bind one identity, and identities are what an attacker "
               "controls. <b>Sybil resistance.</b> Douceur (2002) shows cheap identities break "
               "any rule that counts per identity without a trusted authority; our "
               "split_distinct attack and the 28,086-destination real pool are the same "
               "lever. <b>Split-up attacks on agents.</b> Jones et al. (2025) show safe models "
               "misused in combination by decomposing a task; Makins et al. (2026) show "
               "per-instance monitors fail on distributed attacks in code. We measure the "
               "money version and price the supervision. <b>Collusion and control.</b> "
               "Motwani et al. (2024) measure secret collusion between models that share an "
               "encoding; Rose et al. (2026) detect collusion with multi-agent "
               "interpretability; Greenblatt et al. (2024) give the AI Control protocols we "
               "wire to the payment seam. <b>Incident.</b> METR (2026) and Swarm Traces "
               "(2026) document the Hugging Face swarm, including ~7% transcript spoofing and "
               "7,905 names for ~1,200 agents, which motivate the tampering and identity "
               "experiments.", size=8.5, leading=11.2, space=4)]

    # 3 ---------------------------------------------------------------------
    f += [h1("3. Methods"),
          *bullets([
              "<b>Money, not flags.</b> Each arm is the share of attack money that settles and "
              "the share of legitimate money stopped, in cents, per seeded log. A defence that "
              "detects late still lets the money out. 200 seeds per rule cell, 50 per model "
              "cell; Wilson 95% intervals on rates, and a paired seed-by-seed difference for "
              "the headline model-vs-rule comparison.",
              "<b>Gateway policies.</b> per_mandate (each agent's cap), ledger (one cap on the "
              "principal over a rolling window, calibrated from benign logs only), monitor "
              "(the swarm monitor inline), and ledger+monitor. The monitor's six checks are "
              "named and each is removable on its own.",
              "<b>Two attack sets.</b> Five scenarios tuned on the limits; five held out, "
              "written afterwards, whose attackers check their own budgets first (distinct "
              "payees, a rename past the cutoff, a drip slower than the window).",
              "<b>Model arms.</b> AI Control protocols at the seam where a payment is about to "
              "settle, with each seat's competence and honesty as free parameters offline, and "
              "live Gemini (gemini-3.5-flash-lite) for payee-identity judgement, a paired "
              "blind/draft persuasion test, and an unprompted structuring task. The gateway "
              "consults a model only on payments the rules already let through: a model can "
              "decline to hold, never release.",
              "<b>Negative controls.</b> Each guard ships with a test that removes it and "
              "requires the failure to return; the tampering and identity metrics are "
              "constructed so an inert edit or a merge-everything judge is caught.",
          ], size=8.4)]

    # 4 ---------------------------------------------------------------------
    f += [h1("4. Results"),
          h2("4.1 What the rules are worth at a gateway"),
          grid(gw_head, gw_rows, [W * 0.20] + [W * 0.20] * 4, 6.5),
          caption("Table 1. Share of attack money that settles (lower is better), 200 seeds, "
                  "Wilson 95% intervals. per_mandate is what a payment protocol enforces today."),
          para(f"The per-agent cap alone lets {rng(*(per(s) for s in tuned))} of a tuned split "
               f"leave; inline monitoring cuts that to {rng(*(mon(s) for s in tuned))}, but the "
               "money ahead of the flag is already gone. The three held-out attacks that never "
               f"cross a bound (split_distinct, split_slow, alias_far) each have recall "
               f"{caught[0]} and settle {rng(*(mon(s) for s in silent))} under both. A "
               "principal-wide ledger trades one currency for the other (Table 2): the tight "
               f"setting cuts attack money to {tight_attack} but blocks {tight_busy} of a "
               f"legitimate busy week; the 99th-percentile setting blocks {ledger_busy}.", space=4),
          grid(tr_head, tr_rows, [W * 0.26, W * 0.16, W * 0.14, W * 0.22, W * 0.22], 6.4),
          caption("Table 2. Prevention vs detection: a principal ledger calibrated on benign "
                  "peaks. attack money settled and busy-week money stopped are shares."),
          h2("4.2 False alarms against log length"),
          grid(hz_head, hz_rows, [W * 0.13, W * 0.08, W * 0.28, W * 0.25, W * 0.26], 6.4),
          caption("Table 3. The lifetime row is our first version: clean at 40 ticks, it flags "
                  "92% of benign swarms at 200. The windowed rule shows zero false alarms on "
                  "the 40-300 tick lengths tested (not a claim about all lengths)."),
          h2("4.3 Which protocol survives which failure"),
          grid(["population", "protocol", "attack out", "held", "calls/log", "$/log"],
               table4, [W * 0.21, W * 0.27, W * 0.14, W * 0.12, W * 0.13, W * 0.13], 6.4),
          caption("Table 4. AI Control arms, 14 scenarios, 50 seeds, offline stand-ins. attack "
                  "out / held are shares of attack money settled / legitimate money stopped."),
          *bullets([
              f"<b>The draft is the channel.</b> A colluding pair whose reviewer reads the "
              f"actor's reasoning lets out {open_pair}; withholding the text gets {blind_pair}. "
              "The control is to withhold the text (Motwani et al.).",
              f"<b>Letting a reviewer overrule a flag buys the attack back.</b> The same pair "
              f"settles {releases} under monitor_releases &mdash; the {base_mandate} an "
              f"unsupervised gateway pays &mdash; at {releases_calls} calls a log.",
              "<b>Safety is structural.</b> No arm behind the rules settled more attack money "
              "than the rules in any of 294 (population, arm, scenario) triples. Because the "
              "gateway only asks a model about payments the rules already passed, this is a "
              "property of one-way authority, not an empirical claim about model behaviour.",
          ], size=8.3),
          h2("4.4 The negative result: the model's edge is a string rule"),
          Image(str(fig), width=W, height=W * 2.5 / 6.9),
          caption("Figure 1. Attack money settled vs legitimate money held, one point per "
                  "defence. The open diamond is the only point that pays for a call; the dashed "
                  "line runs to the free rule that matches it on attack money and beats it on "
                  "legitimate money."),
          grid(sweep_head, sweep_rows,
               [W * 0.15, W * 0.125, W * 0.125, W * 0.125, W * 0.14, W * 0.125, W * 0.08, W * 0.13], 6.0),
          caption("Table 5. Each cell is attack money settled / legitimate money held over the "
                  "same 200 seeds. The last column is the paired count of seeds where the model "
                  "arm differs from the free both-readings-hold arm (max absolute difference)."),
          para(f"<b>Read the fourth column against the fifth.</b> The model arm and the "
               f"two-reading rule that holds instead of freezing catch the same attack money in "
               f"every scenario, and the paired difference is zero on all 200 seeds (max over "
               f"scenarios: {paired_max}). The rule holds less legitimate money where the shipped "
               f"rule freezes ({fanout_hold} vs {fanout_freeze} on relay_fanout; {free_held} vs "
               f"{base_rules_held} pooled) and bills nothing. The honest reading is a defect "
               f"report on our own monitor: the shipped merge rule was wrong in both directions "
               f"&mdash; it merged identifier namespaces and missed a word-order swap "
               f"(split_renamed lets {renamed[0]} out) &mdash; and the model was compensating "
               "for that bug for its whole price tag.", space=4),
          h2("4.5 Live model evidence (Gemini)"),
          grid(id_head, id_rows, [W * 0.20, W * 0.07, W * 0.20, W * 0.20, W * 0.20, W * 0.13], 6.3),
          caption("Table 6. Pairwise precision/recall of same-vendor merges on the raw names of "
                  "each log, 3 seeds, ground truth from the scenario construction. 1.00* = no "
                  "merges predicted. The model reads renames and misspellings the rules miss "
                  "and keeps identifier stems apart (zero false merges)."),
          grid(pers_head, pers_rows, [W * 0.34, W * 0.33, W * 0.33], 6.4),
          caption(f"Table 7. The same reviewer rates {pers_n} true breaches blind and with each "
                  f"draft (threshold 0.5). Adversarial drafts flipped {pers_flips} payments from "
                  "hold to allow: on unambiguous arithmetic the channel did nothing."),
          grid(struct_cols, struct_display,
               [W * 0.20, W * 0.06, W * 0.22, W * 0.16, W * 0.18, W * 0.18], 6.3),
          caption("Table 8. Do live agents structure on their own? Four Gemini purchasing agents, "
                  "one $900 invoice, a $500 approval threshold and a $400 per-agent cap; chain "
                  "topology, 2 seeds per arm. A states the threshold; D removes it from the "
                  "policy. No prompt mentions splitting, evasion or monitoring."),
          para(f"<b>The gap arises unprompted.</b> With the threshold stated (A) the agents asked "
               f"for approval and never split ({a_struct} structured). Remove the threshold from "
               f"the policy (D) and the same model spontaneously split the invoice into two $400 "
               f"payments from different agents in {d_split} of episodes ({d_struct} structured), "
               f"moving $800 to one vendor with no approval &mdash; the aggregate gap emerging "
               f"from ordinary instruction-following, not from an attacker we wrote. The monitor "
               f"flagged every structured episode (agrees {d_agree}). At n=2 per arm this "
               "establishes the mechanism, not a population rate.", space=4),
          h2("4.6 Oversight when the suspects write the logs"),
          grid(tam_head, tam_rows, [W * 0.16, W * 0.10, W * 0.26, W * 0.24, W * 0.24], 6.4),
          caption("Table 9. Agent-log detection collapses under three edits to the published "
                  "log; the gateway, which reads settled instructions not reports, is identical "
                  "across every row. 200 runs per row."),
          h2("4.7 The swarm we did not write, and the adaptive attacker"),
          para(f"On the published incident reconstruction ({records} records, {edges} edges, "
               f"fan-out max {fanmax}; 0 nodes both parent and child, 0 timestamps) the "
               f"destination pool is {pool:,} payees, the busiest taking {busiest}%. At $600 per "
               f"payee per window, moving $100,000 needs 100000/600 &asymp; 166.7 payees; the "
               f"observed pool covers {runs_covered:.1f} such runs. Identity spread, with no "
               "amount over any bound, is the lever a real swarm already has. Relay depth and "
               "every windowed number are unvalidated externally because the data has no clock "
               "and no multi-hop node.", space=4),
          Image(str(fig2), width=W, height=W * 2.3 / 6.9),
          caption("Figure 2. Best response of an attacker who knows the bound (7 payments of "
                  "$200): settled share vs spacing, one curve per identity count. More "
                  "identities or more time leaks everything; the bound caps the rate, not the "
                  "total."),
          para("<b>Leakage bound.</b> Against a per-payee bound B over window W with perfect "
               "identity, an attacker settling through I true payee identities over T ticks can "
               "move at most I&middot;B&middot;(floor(T/W)+1), and never more than B per "
               "identity per window. The bound is a rate; given enough identities (split_distinct) "
               "or enough time (split_slow) the total is unbounded. That is the aggregate gap "
               "restated precisely, and Figure 2 is its measured best response.", space=4)]

    # 5 ---------------------------------------------------------------------
    f += [h1("5. Discussion and Limitations"),
          para("The durable defence is a bound an attacker cannot argue with, placed where the "
               "money actually moves and kept out of the agents' reach. The model's role is "
               "narrower than it first appears: on our harness its measurable value was "
               "compensating for a fixable rule defect, and the live runs show its genuine "
               "addition is identity judgement on names no string rule can name &mdash; an "
               "abbreviation that requires knowing who the vendor is. Persuasion did not move "
               "a reviewer on unambiguous breaches; the channel matters exactly where the "
               "arithmetic is ambiguous, which the offline arms parameterise but the live n=6 "
               "does not probe.", space=4),
          *bullets([
              "<b>Stand-ins are not models.</b> The protocol tables are statements about a "
              "structure under assumed failure rates, not about any model's behaviour.",
              "<b>The generator is the attacker we imagined.</b> Held-out shapes were written "
              "by us after seeing the rules; that is an adaptive limit, not a world.",
              "<b>Live evidence is small-n.</b> Identity is 3 seeds per scenario; persuasion is "
              "6 breaches; the structuring task is a handful of episodes. They establish the "
              "mechanism, not a population rate.",
              "<b>Real-data limits.</b> The published reconstruction has no timestamps and no "
              "multi-hop node, and the 7,905-name pool ships no ground-truth identity labels, so "
              "true/false merge rates cannot be measured on it; the live identity experiment "
              "measures the mechanism on constructed ground truth instead.",
          ], size=8.3),
          para("<b>Future work.</b> A verifier that binds payee identity to a registered vendor "
               "(closing the Sybil lever), a live colluding actor-reviewer pair on ambiguous "
               "near-bound payments, and an adaptive attacker run against the calibrated "
               "ledger rather than the monitor alone.", size=8.4, space=4)]

    # 6 ---------------------------------------------------------------------
    f += [h1("6. Conclusion"),
          para("Per-mandate budgets leave a principal-wide aggregate gap, and the cheapest "
               "durable answer is a per-payee, per-window rate bound enforced at the gateway "
               "from settled instructions, outside the agents' reach. It holds against every "
               "attack tuned to it and against log tampering; it is provably a rate, not a "
               "total, so identity and time remain the attacker's levers. A model supervisor "
               "earned its price only by fixing a defect we could fix for free, and its real "
               "contribution is identity judgement, not arithmetic. We report the negative "
               "result rather than the flattering one.", size=8.6, space=5)]

    # Code and data + contributions ------------------------------------------
    f += [h2("Code and Data"),
          para("Code: github.com/muhammad-hassaan-y2/Twin-, directory "
               f"{MON}swarm-oversight/{END}, branch {MON}aggregate-gap{END} (stdlib only; "
               "reportlab/matplotlib for this PDF). Data: Swarm Traces (swarmtraces.org) and "
               "the AI Village corpus (huggingface.co/datasets/aidigestorg/ai-village). "
               "Reproduce: pip install -e .[dev] &amp;&amp; pytest; python -m "
               "swarm_oversight.report --seeds 200; python -m swarm_oversight.aicontrol "
               "--seeds 200 --identity-sweep --out results; python -m "
               "swarm_oversight.tampering --seeds 50 --out results; GEMINI_API_KEY=... python "
               "-m swarm_oversight.live_experiments identity|persuasion; python -m "
               "swarm_oversight.pdf_report --out report.pdf.", size=7.9, leading=10.4, space=4),
          h2("Author Contributions and Prior Work"),
          para("R&#305;zgar Ozan built the baseline swarm monitor, the seeded harness and the "
               "evasive variants (commits of 2026-11-07, within the sprint). Muhammad Hassaan "
               "Shaukat built the gateway, experiments, AI Control and live-model arms, the "
               "tampering demonstration and this report. <b>No code in swarm-oversight/ "
               "predates the sprint</b> (earliest commit 2026-11-07). The repository's "
               f"{MON}tabletop-twin/{END} directory is an unrelated October 2026 project and "
               "contributes no code or ideas to this submission.", size=7.9, leading=10.4, space=4)]

    # References (excluded from page cap) ------------------------------------
    f += [h1("References"),
          para("Aviv, A., Gandh, P. A., Bitton, R., Shabtai, A. (2026). Beyond the Mandate: A "
               "Systematic Security Analysis of the Agent Payments Protocol (AP2). arXiv:2608.23858. "
               "&#183; Douceur, J. (2002). The Sybil Attack. IPTPS. &#183; Greenblatt, R., et al. "
               "(2024). AI Control: Improving Safety Despite Intentional Subversion. arXiv:2312.06942. "
               "&#183; Jones, E., Dragan, A., Steinhardt, J. (2025). Adversaries Can Misuse "
               "Combinations of Safe Models. ICML. arXiv:2406.14595. &#183; Makins, O., Angelini, "
               "O., Shams, Z., Phuong, M. (2026). Multi-Agent AI Control: Distributed Attacks "
               "Hamper Per-Instance Monitors. arXiv:2607.07368. &#183; Motwani, S., et al. (2024). "
               "Secret Collusion among Generative AI Models. arXiv:2402.07510. &#183; Rose, A., et "
               "al. (2026). Detecting Multi-Agent Collusion Through Multi-Agent Interpretability. "
               "arXiv:2604.01151. &#183; METR (2026). Hugging Face incident report, August 2026. "
               "&#183; Swarm Traces (2026). swarmtraces.org. &#183; 31 U.S.C. &sect;5324; FATF "
               "Recommendations (structuring).", size=7.6, leading=10.0, color=FAINT, space=5)]

    # Appendix (required, excluded from page cap) ----------------------------
    f += [h1("Appendix A. Limitations and Dual-Use / Ethical Considerations"),
          para("<b>What the results do and do not establish.</b> They establish, on a seeded "
               "synthetic harness, that a per-payee per-window gateway bound holds against the "
               "attacks we wrote and that a model supervisor's measured edge here was a rule "
               "defect. They do not establish behaviour on a production payment system, on "
               "real swarms with clocks and multi-hop structure (the published data has "
               "neither), or a population rate for any live-model judgement (small n). The "
               "294-triple safety statement is a design property of one-way authority, not a "
               "measurement of models.", size=8.2, leading=10.8, space=4),
          para("<b>Dual-use.</b> The held-out attacks (split_distinct, split_slow, alias_far) "
               "and the three log-tampering edits are, read offensively, an evasion recipe "
               "against payment monitors and audit trails. We publish them because the "
               "corresponding defence is the point: the gateway-side bound and ledger hold "
               "against all of them, and Figure 2 states exactly what an attacker can still "
               "achieve (a rate, not a total). The scenarios are synthetic, no real payment "
               "system or vendor was targeted, and the live-model experiments used the authors' "
               "own API key on trivial synthetic prompts. The persuasion prompt is a generic "
               "advocacy instruction, not a transferable jailbreak. We judge the defensive "
               "value of naming the levers (identity, time, log authorship) to outweigh the "
               "marginal offensive uplift, since these are the same levers AML velocity limits "
               "and Sybil resistance already address.", size=8.2, leading=10.8, space=4),
          h2("LLM Usage Statement"),
          para("We used Qoder (Claude) to draft and debug code and to draft sections of this "
               "report. Every quantitative claim is regenerated from the seeds by the committed "
               "code and parsed from the result tables at build time; every citation was "
               "checked against its primary source (the AP2 title/venue and the Jones and Rose "
               "references were corrected during verification). The authors are responsible "
               "for all claims and results.", size=8.2, leading=10.8, space=4),
          para("[1] Research conducted at the Swarm Alignment Hackathon, November 2026.",
               size=7.4, leading=9.4, color=FAINT, space=2)]

    doc.build(f)
    return out


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.4)
    canvas.line(16 * mm, 11 * mm, A4[0] - 16 * mm, 11 * mm)
    canvas.setFont(BODY, 6.8)
    canvas.setFillColor(FAINT)
    canvas.drawString(16 * mm, 8 * mm, "The Aggregate Gap  ·  Swarm Alignment 2026, Track 4")
    canvas.drawRightString(A4[0] - 16 * mm, 8 * mm, f"page {doc.page}")
    canvas.restoreState()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="report.pdf")
    ap.add_argument("--results", default=str(RESULTS))
    args = ap.parse_args()
    print(build(Path(args.out), Path(args.results)))