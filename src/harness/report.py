"""Markdown report rebuilt from runs.jsonl, so the published numbers always
come from the raw rows and never from a hand-edited table."""

from collections import defaultdict

from harness.cases import AttackCase
from harness.owasp import CATEGORIES
from harness.stats import fmt_rate


def _latest(rows: list[dict]) -> list[dict]:
    # A retried job appends a new row; the newest one is the truth.
    by_key = {}
    for r in rows:
        by_key[(r["case_id"], r["setting"], r["rep"])] = r
    return list(by_key.values())


def _rate(rows: list[dict], field: str) -> tuple[int, int]:
    values = [r[field] for r in rows if r.get(field) is not None]
    return sum(bool(v) for v in values), len(values)


def _table(header: list[str], lines: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(line) + " |" for line in lines]
    return "\n".join(out)


def build_report(rows: list[dict], cases: dict[str, AttackCase], meta: dict) -> str:
    rows = [r for r in _latest(rows) if r["case_id"] in cases]
    by_setting: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_setting[r["setting"]].append(r)

    def ok(rs: list[dict]) -> list[dict]:
        return [r for r in rs if r["outcome"] != "error"]

    total_cost = sum(r.get("cost_usd") or 0.0 for r in rows)
    parts = [
        f"# Attack report: {meta['target']}",
        "",
        f"- Target: {meta['target']}",
        f"- Model: {meta['model']}",
        f"- Agent: {meta['agent']}",
        f"- Date: {meta['created']}",
        f"- Total runs: {len(rows)}",
        f"- Total cost: ${total_cost:.2f}",
        "",
        "Rates are `k/n (95% Wilson interval)`. Error rows are excluded from every rate.",
        "",
        "## Headline",
        "",
    ]

    headline = []
    for s in meta["settings"]:
        rs = by_setting.get(s, [])
        attacks = [r for r in ok(rs) if not r["control"]]
        controls = [r for r in ok(rs) if r["control"]]
        errors = sum(r["outcome"] == "error" for r in rs)
        headline.append([
            s,
            fmt_rate(*_rate(attacks, "attack_success")),
            fmt_rate(*_rate(attacks, "attempted")),
            fmt_rate(*_rate(attacks, "task_success")),
            fmt_rate(*_rate(controls, "task_success")),
            str(errors),
        ])
    parts += [_table(["Setting", "Attack success", "Attempt", "Task under attack", "Task (controls)", "Errors"], headline), ""]

    parts += ["## By OWASP category", ""]
    cited = sorted({o for c in cases.values() for o in c.owasp if CATEGORIES[o].in_scope},
                   key=list(CATEGORIES).index)
    owasp_lines = []
    for oid in cited:
        line = [oid, CATEGORIES[oid].name]
        for s in meta["headline"]:
            rs = [r for r in ok(by_setting.get(s, [])) if not r["control"] and oid in cases[r["case_id"]].owasp]
            line.append(fmt_rate(*_rate(rs, "attack_success")))
        owasp_lines.append(line)
    parts += [_table(["ID", "Name", *meta["headline"]], owasp_lines), ""]

    parts += ["## By case", "", "Attack successes per setting; control cases show task successes.", ""]
    case_lines = []
    for cid, c in sorted(cases.items()):
        line = [cid, c.family]
        for s in meta["settings"]:
            rs = [r for r in ok(by_setting.get(s, [])) if r["case_id"] == cid]
            k, n = _rate(rs, "task_success" if c.control else "attack_success")
            line.append(f"{k}/{n}" if n else "–")
        case_lines.append(line)
    parts += [_table(["Case", "Family", *meta["settings"]], case_lines), ""]

    parts += ["## Not covered", ""]
    parts += [f"- **{c.id} {c.name}**: {c.reason}" for c in CATEGORIES.values() if not c.in_scope]
    return "\n".join(parts) + "\n"
