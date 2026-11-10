from harness.cases import AttackCase
from harness.report import build_report


def case(id_, control=False, owasp=("LLM01",)):
    return AttackCase(
        id=id_, title=id_, target="fake", family="control" if control else "direct_instruction",
        goal="g", owasp=list(owasp), user_task="t",
        injections=[] if control else [{"surface": "x"}],
    )


CASES = {"atk": case("atk"), "ctl": case("ctl", control=True, owasp=())}
META = {"target": "fake", "model": "m", "agent": "llm", "settings": ["s_on", "s_off"],
        "headline": ["s_off", "s_on"], "created": "2026-11-09T10:00:00"}


def row(case_id, setting, rep, *, attack=None, attempted=None, task=None, outcome="succeeded", cost=0.01):
    control = CASES[case_id].control
    error = outcome == "error"
    return {
        "case_id": case_id, "setting": setting, "rep": rep, "outcome": outcome,
        "control": control, "owasp": CASES[case_id].owasp,
        "attack_success": None if error or control else attack,
        "attempted": None if error or control else attempted,
        "task_success": None if error else task, "cost_usd": cost,
    }


def headline_line(report, setting):
    section = report.split("## Headline")[1].split("##")[0]
    return next(l for l in section.splitlines() if l.startswith(f"| {setting} "))


def test_report_headline_rates():
    rows = [
        row("atk", "s_off", 0, attack=True, attempted=True, task=False),
        row("atk", "s_off", 1, attack=True, attempted=True, task=True),
        row("atk", "s_on", 0, attack=False, attempted=True, task=True),
        row("atk", "s_on", 1, attack=False, attempted=False, task=True),
        row("ctl", "s_off", 0, task=True),
        row("ctl", "s_on", 0, task=False),
    ]
    report = build_report(rows, CASES, META)
    off = headline_line(report, "s_off")
    assert "2/2 (34–100%)" in off.split("|")[2]
    assert "1/2" in off.split("|")[4] and "1/1" in off.split("|")[5]
    on = headline_line(report, "s_on")
    cells = [c.strip() for c in on.split("|")]
    assert cells[2].startswith("0/2") and cells[3].startswith("1/2") and cells[4].startswith("2/2")
    assert cells[5].startswith("0/1") and cells[6] == "0"
    assert report.index("| s_on ") < report.index("| s_off ")
    assert "Total runs: 6" in report


def test_report_excludes_errors_and_counts_them():
    rows = [
        row("atk", "s_off", 0, attack=True, attempted=True, task=True),
        row("atk", "s_off", 1, outcome="error"),
    ]
    off = headline_line(build_report(rows, CASES, META), "s_off")
    cells = [c.strip() for c in off.split("|")]
    assert cells[2].startswith("1/1") and cells[6] == "1"


def test_report_last_row_wins_for_same_key():
    rows = [
        row("atk", "s_off", 0, outcome="error"),
        row("atk", "s_off", 0, attack=True, attempted=True, task=True),
    ]
    cells = [c.strip() for c in headline_line(build_report(rows, CASES, META), "s_off").split("|")]
    assert cells[2].startswith("1/1") and cells[6] == "0"


def test_report_by_owasp_uses_headline_settings():
    rows = [row("atk", "s_off", 0, attack=True, attempted=True, task=True)]
    report = build_report(rows, CASES, META)
    section = report.split("## By OWASP category")[1].split("##")[0]
    assert "| s_off | s_on |" in section
    line = next(l for l in section.splitlines() if "LLM01" in l)
    assert "1/1" in line and "Prompt Injection" in line
    assert "ASI01" not in section


def test_report_by_case_shows_counts():
    rows = [row("atk", "s_off", 0, attack=True, attempted=True, task=True),
            row("ctl", "s_off", 0, task=True)]
    section = build_report(rows, CASES, META).split("## By case")[1].split("##")[0]
    atk = next(l for l in section.splitlines() if l.startswith("| atk "))
    assert "1/1" in atk
    ctl = next(l for l in section.splitlines() if l.startswith("| ctl "))
    assert "1/1" in ctl


def test_report_lists_not_covered_categories():
    report = build_report([], CASES, META)
    section = report.split("## Not covered")[1]
    assert "LLM04" in section and "pinned dependencies" in section
    assert "LLM01" not in section
