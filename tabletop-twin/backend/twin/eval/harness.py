"""Runs the corpus and turns it into numbers worth arguing about.

Three things come out of a run: whether every case landed on its known answer, whether
every case noticed the absence of the guard it watches, and how much of the code's
own decision vocabulary the corpus actually reaches. The third is the one that keeps
this file honest — a new rule nobody wrote a scenario for shows up as an uncovered name
rather than as a passing score.

The corpus is two worlds scored by one rule: the payment twin in `cases.py` and the audit firm
in `firm.py`. They share the scoring because they share the claim being scored, which is not
"this function returns that" but "this code, put in a situation with a right answer, gave it" —
and neither world is allowed a passing score until its guard has also been removed once and
noticed.
"""

from __future__ import annotations

import inspect
import json
import re
import sys
from typing import Callable

from twin.audit.agents import Priors
from twin.eval.cases import CASES, Case, Check, Run
from twin.eval.firm import FIRM_CASES, enforced_provisions, enforced_thresholds
from twin.policy import engine as policy_engine
from twin.safety import guardrails


def engine_rules() -> list[str]:
    """Every rule name the policy engine can answer with, read out of the code that answers."""
    source = inspect.getsource(policy_engine.evaluate)
    return sorted(set(re.findall(r'action\.id,\s*"([a-z_]+)"', source)))


def guardrail_rules() -> list[str]:
    return sorted(guardrails.RULES)


def threshold_rules() -> list[str]:
    """Use the same numerical and worded rule vocabulary for coverage's numerator and denominator."""
    return sorted(enforced_thresholds() | enforced_provisions(Priors.load()))


def run_case(case: Case, *, control: bool = False) -> dict:
    """One scenario, guarded or not. A scenario that crashes is a failed scenario, not a stack trace."""
    run = Run.fresh()
    restore: Callable[[], None] | None = None
    failed: Exception | None = None
    checks: list[Check] = []
    if control and case.control is not None:
        restore = case.control(run)
    try:
        checks = list(case.run(run))
    except Exception as exc:  # the report has to say which scenario blew up and why
        failed = exc
        checks = [Check("the scenario ran", "a list of checks", f"{type(exc).__name__}: {exc}")]
    finally:
        if restore is not None:
            restore()
    return {
        "slug": case.slug,
        "promise": case.promise,
        "kind": case.kind,
        "control": control,
        "checks": [check.to_dict() for check in checks],
        "passed": all(check.ok for check in checks) and failed is None,
        "rules": sorted(run.rules),
        "spoken": len(run.spoken),
    }


def report(cases: tuple[Case, ...] = CASES + FIRM_CASES) -> dict:
    """The whole corpus, its negative controls, and the metrics that fall out of both."""
    clean = [run_case(case) for case in cases]
    teeth: dict[str, dict] = {}
    for case in cases:
        if case.kind != "guard" or case.control is None:
            continue
        controlled = run_case(case, control=True)
        teeth[case.slug] = {
            "caught": not controlled["passed"],
            "failed_checks": [
                check["name"] for check in controlled["checks"]
                if not check["ok"]
            ],
        }

    rules_seen = sorted({rule for row in clean for rule in row["rules"]})
    reachable = sorted(set(engine_rules()) | set(guardrail_rules()) | set(threshold_rules()))
    missed = sorted(set(reachable) - set(rules_seen))
    hollow = sorted(slug for slug, row in teeth.items() if not row["caught"])
    broken = sorted(row["slug"] for row in clean if not row["passed"])

    return {
        "cases": clean,
        "controls": teeth,
        "metrics": {
            "cases": len(clean),
            "cases_passed": len(clean) - len(broken),
            "checks": sum(len(row["checks"]) for row in clean),
            "checks_passed": sum(sum(1 for check in row["checks"] if check["ok"]) for row in clean),
            "guard_cases": len(teeth),
            "guard_cases_with_teeth": len(teeth) - len(hollow),
            "hollow_cases": hollow,
            "broken_cases": broken,
            "rules_reachable": reachable,
            "rules_reached": rules_seen,
            "rules_missed": missed,
            "rule_coverage_pct": round(100 * len(rules_seen) / len(reachable)) if reachable else 0,
        },
    }


def render(result: dict) -> str:
    """The score, in the order a reviewer reads it: what is wrong, then what was checked."""
    metrics = result["metrics"]
    lines = [
        f"cases {metrics['cases_passed']}/{metrics['cases']}   "
        f"checks {metrics['checks_passed']}/{metrics['checks']}   "
        f"teeth {metrics['guard_cases_with_teeth']}/{metrics['guard_cases']}   "
        f"rules reached {metrics['rule_coverage_pct']}% ({len(metrics['rules_reached'])}/{len(metrics['rules_reachable'])})",
    ]
    if metrics["broken_cases"]:
        lines.append("FAILED: " + ", ".join(metrics["broken_cases"]))
    if metrics["hollow_cases"]:
        lines.append("HOLLOW (its guard went missing and nothing noticed): " + ", ".join(metrics["hollow_cases"]))
    if metrics["rules_missed"]:
        lines.append("NOT REACHED BY ANY SCENARIO: " + ", ".join(metrics["rules_missed"]))
    lines.append("")
    for row in result["cases"]:
        flag = "ok " if row["passed"] else "FAIL"
        control = result["controls"].get(row["slug"])
        teeth = "" if control is None else ("  control caught it" if control["caught"] else "  CONTROL MISSED IT")
        lines.append(f"{flag} {row['slug']}  [{row['kind']}]{teeth}")
        for check in row["checks"]:
            if check["ok"]:
                continue
            lines.append(f"      {check['name']}: wanted {check['expected']!r}, got {check['actual']!r}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    if as_json:
        argv = [arg for arg in argv if arg != "--json"]
    if argv and argv[0] in {"-h", "--help"}:
        print("usage: python -m twin.eval [--json]\n  runs every scenario, guarded and unguarded, and prints the score")
        return 0
    result = report()
    print(json.dumps(result, indent=2, sort_keys=True, default=str) if as_json else render(result))
    metrics = result["metrics"]
    return 0 if (metrics["cases_passed"] == metrics["cases"]
                 and metrics["hollow_cases"] == []
                 and metrics["rules_missed"] == []) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
