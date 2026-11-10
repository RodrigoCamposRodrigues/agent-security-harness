"""Positive controls for the inbox: an obedient agent proves each attack check can fire."""

from pathlib import Path

import pytest

from harness import checks
from harness.adapters.inbox import InboxAdapter
from harness.cases import load_cases

ROOT = Path(__file__).parents[1] / "cases"
ROUND1 = load_cases("inbox/*.yaml", root=ROOT)
CASES = ROUND1 + load_cases("round2/inbox/*.yaml", root=ROOT)
ATTACKS = [c for c in CASES if not c.control]
CONTROLS = [c for c in CASES if c.control]
OBEDIENT = InboxAdapter(agent="obedient", model="scripted")
SCRIPTED = InboxAdapter(agent="scripted", model="scripted")


def test_suite_shape():
    attacks = [c for c in ROUND1 if not c.control]  # round 2 lives apart; the published suite shape is round 1
    assert 20 <= len(attacks) <= 25 and len(CONTROLS) == 4
    assert {c.user_task for c in CONTROLS} == {"triage", "answer_customer", "supplier_updates", "forward_invoices"}
    families = {c.family for c in attacks}
    assert families == {"exfiltration", "payment_fraud", "hide_urgent", "misleading_summary", "prompt_extraction",
                        "self_promotion"}
    assert all(c.obey for c in attacks)
    senders = [i["from"] for c in attacks for i in c.injections]
    assert all(s.endswith(".example") and not s.endswith("@ribeira-cycles.example") for s in senders)


SETTINGS = OBEDIENT.settings()


@pytest.mark.parametrize("case", ATTACKS, ids=[c.id for c in ATTACKS])
def test_obedient_attack_succeeds_with_no_defences(case):
    assert checks.evaluate(case, OBEDIENT.run(case, SETTINGS["none"], 0)).attack_success is True


@pytest.mark.parametrize("case", ATTACKS, ids=[c.id for c in ATTACKS])
def test_obedient_attack_with_all_defences_matches_expectation(case):
    assert case.obedient_all_on in ("blocked", "succeeds")
    success = checks.evaluate(case, OBEDIENT.run(case, SETTINGS["all"], 0)).attack_success
    assert success is (case.obedient_all_on == "succeeds")


@pytest.mark.parametrize("setting", ["none", "all"])
@pytest.mark.parametrize("case", CONTROLS, ids=[c.id for c in CONTROLS])
def test_scripted_control_task_succeeds(case, setting):
    assert checks.evaluate(case, SCRIPTED.run(case, SETTINGS[setting], 0)).task_success is True


def _canaries(cases):
    """Planted strings only: placeholders such as {{NEW_PASSWORD}} are the secret itself, not a canary."""
    return [str(p["canary"]) for c in cases for spec in c.attack_checks + c.attempt_checks
            for p in [spec.params] if "canary" in p and not str(p["canary"]).startswith("{{")]


def test_round2_cases_load_and_have_unique_canaries():
    root = Path(__file__).parents[1] / "cases"
    round1, round2 = load_cases("inbox/*.yaml", root=root), load_cases("round2/inbox/*.yaml", root=root)
    assert len(round2) == 4 and not any(c.control for c in round2)
    assert not {c.id for c in round1} & {c.id for c in round2}
    # Round 1 shares one system-prompt canary across its prompt-extraction cases on purpose.
    new = _canaries(round2)
    assert len(new) == len(set(new)) and not set(new) & set(_canaries(round1))
