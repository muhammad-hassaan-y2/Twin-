"""Write every table behind the write-up, from the seeds alone.

    python -m swarm_oversight.report --seeds 200 --out results

Writes one CSV per experiment and summary.md with 95% intervals (Wilson for
rates, normal for means). Ledger caps are calibrated on seeds 10000+, which
no evaluation run uses.
"""
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

from . import experiments as ex
from .gateway import calibrate_ledger
from .monitor import Limits


def _csv(path: Path, rows: list[dict]) -> None:
    keys: list[str] = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def _f(x, nd: int = 2) -> str:
    if x is None:
        return "-"
    return f"{x:.{nd}f}" if isinstance(x, float) else str(x)


def _ci(m, lo, hi, nd: int = 2) -> str:
    return "-" if m is None else f"{m:.{nd}f} [{lo:.{nd}f}, {hi:.{nd}f}]"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=200)
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    seeds = range(args.seeds)
    calib = range(10_000, 10_000 + args.seeds)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    lim = Limits()
    cap = calibrate_ledger(calib, window=lim.long_window)

    det = ex.detection(seeds)
    abl = ex.ablation(seeds)
    hor = ex.horizon(seeds)
    gw = ex.gateway(seeds, cap)
    trade = ex.ledger_tradeoff(seeds, calib)
    fr = ex.frontier(cap=cap)
    vis = ex.visibility(seeds)
    for name, rows in (("detection", det), ("ablation", abl), ("horizon", hor),
                       ("gateway", gw), ("ledger_tradeoff", trade),
                       ("frontier", fr), ("visibility", vis)):
        _csv(out / f"{name}.csv", rows)

    md = [f"# Results ({args.seeds} seeds per cell)", "",
          f"Limits: {lim}.", f"Principal ledger cap: {cap.cap} cents per "
          f"{cap.window} ticks (99th percentile of benign peaks, seeds "
          f"{calib.start}-{calib.stop - 1}).", ""]

    md += ["## Detection: tuned vs held-out", "",
           "| split | scenario | recall [95% CI] | false alarm [95% CI] | latency | caught by |",
           "| --- | --- | --- | --- | --- | --- |"]
    md += [f"| {r['split']} | {r['scenario']} | {_ci(r['recall'], r['recall_lo'], r['recall_hi'])} "
           f"| {_ci(r['false_alarm'], r['false_alarm_lo'], r['false_alarm_hi'])} "
           f"| {_f(r['mean_latency'])} | {r['caught_by'] or '-'} |" for r in det]

    arms = list(dict.fromkeys(r["arm"] for r in abl))
    scen = list(dict.fromkeys(r["scenario"] for r in abl))
    cell = {(r["arm"], r["scenario"]): r["recall"] for r in abl}
    md += ["", "## Ablation: recall with one check removed", "",
           "| arm | " + " | ".join(scen) + " |", "| --- " * (len(scen) + 1) + "|"]
    md += [f"| {a} | " + " | ".join(_f(cell[(a, s)]) for s in scen) + " |" for a in arms]

    md += ["", "## Benign logs of growing length", "",
           "| payee total | ticks | swarm false-alarm runs [95% CI] | swarm flags / 1000 actions "
           "| runs where an agent exhausted its lifetime budget |",
           "| --- | --- | --- | --- | --- |"]
    md += [f"| {r['payee_total']} | {r['ticks']} | "
           f"{_ci(r['swarm_false_alarm_runs'], r['lo'], r['hi'])} | "
           f"{_f(r['swarm_flags_per_1000_actions'])} | {_f(r['agent_budget_exhausted_runs'])} |"
           for r in hor]

    pols = list(dict.fromkeys(r["policy"] for r in gw))
    md += ["", "## Gateway: share of attack money that settled (lower is better)", "",
           "| scenario | " + " | ".join(pols) + " |", "| --- " * (len(pols) + 1) + "|"]
    for s in dict.fromkeys(r["scenario"] for r in gw if r["kind"] == "attack"):
        md.append(f"| {s} | " + " | ".join(
            _ci(r["mean"], r["lo"], r["hi"]) for p in pols for r in gw
            if r["policy"] == p and r["scenario"] == s) + " |")
    md += ["", "## Gateway: share of legitimate money stopped (lower is better)", "",
           "| scenario | " + " | ".join(pols) + " |", "| --- " * (len(pols) + 1) + "|"]
    for s in dict.fromkeys(r["scenario"] for r in gw if r["kind"] == "benign"):
        md.append(f"| {s} | " + " | ".join(
            f"{_ci(r['mean'], r['lo'], r['hi'], 3)} (runs: {r['runs_with_a_stop']:.2f})"
            for p in pols for r in gw if r["policy"] == p and r["scenario"] == s) + " |")

    md += ["", "## Prevention vs detection", "",
           "| arm | cap | window | attack money settled | busy-week money stopped |",
           "| --- | --- | --- | --- | --- |"]
    md += [f"| {r['arm']} | {_f(r['cap'])} | {_f(r['window'])} | "
           f"{_f(r['attack_settled_frac'])} | {_f(r['benign_busy_stopped_frac'], 3)} |"
           for r in trade]

    md += ["", "## Evasion frontier (7 x 20,000 cents, no background)", "",
           "| payees | gap | per_mandate settled | monitor settled | ledger settled "
           "| monitor: most to one payee in any window | bound |", "| --- " * 7 + "|"]
    md += [f"| {r['payees']} | {r['gap']} | {r['per_mandate_settled']} | {r['monitor_settled']} "
           f"| {r.get('ledger_settled', '-')} | {r['monitor_peak_to_one_payee']} "
           f"| {r['per_payee_bound']} |" for r in fr]

    varms = list(dict.fromkeys(r["arm"] for r in vis))
    vscen = list(dict.fromkeys(r["scenario"] for r in vis))
    vcell = {(r["arm"], r["scenario"]): r["recall"] for r in vis}
    md += ["", "## Partial visibility: recall", "",
           "| arm | " + " | ".join(vscen) + " |", "| --- " * (len(vscen) + 1) + "|"]
    md += [f"| {a} | " + " | ".join(_f(vcell[(a, s)]) for s in vscen) + " |" for a in varms]

    md += ["", f"_Generated in {time.time() - t0:.0f}s._", ""]
    (out / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {out}/summary.md and 7 CSVs in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
