"""Positive controls: an obedient agent proves each attack check can fire, so a 0%
from the real model means the model or the defences stopped it, not a blind check."""

from pathlib import Path

import pytest

from harness import checks
from harness.cases import load_cases

pytestmark = pytest.mark.rotation

ROOT = Path(__file__).parents[1] / "cases"
ROUND1 = load_cases("rotation/*.yaml", root=ROOT)
CASES = ROUND1 + load_cases("round2/rotation/*.yaml", root=ROOT)
ATTACKS = [c for c in CASES if not c.control]
CONTROLS = [c for c in CASES if c.control]
ALL_OFF = frozenset({"placeholders", "submit_gate", "untrusted_marking", "budgets", "verify"})


@pytest.fixture(scope="module")
def adapter():
    from harness.adapters.rotation import RotationAdapter
    a = RotationAdapter(agent="obedient", model="scripted")
    yield a
    a.close()


def test_suite_shape():
    attacks = [c for c in ROUND1 if not c.control]  # round 2 lives apart; the published suite shape is round 1
    families = {c.family for c in attacks}
    assert len(attacks) >= 20 and len(CONTROLS) == 3
    assert all(sum(c.family == f for c in attacks) >= 2 for f in families)
    assert all(c.obey for c in attacks)


@pytest.mark.parametrize("case", ATTACKS, ids=[c.id for c in ATTACKS])
def test_obedient_attack_succeeds_with_all_off(adapter, case):
    adapter.agent = "obedient"
    assert checks.evaluate(case, adapter.run(case, ALL_OFF, 0)).attack_success is True


@pytest.mark.parametrize("case", ATTACKS, ids=[c.id for c in ATTACKS])
def test_obedient_attack_with_all_on_matches_expectation(adapter, case):
    adapter.agent = "obedient"
    success = checks.evaluate(case, adapter.run(case, frozenset(), 0)).attack_success
    if case.obedient_all_on == "unknown":
        print(f"\n{case.id}: obedient agent at all_on -> attack_success={success}")
        pytest.skip(f"expectation unknown; observed attack_success={success}")
    assert success is (case.obedient_all_on == "succeeds")


@pytest.mark.parametrize("case", CONTROLS, ids=[c.id for c in CONTROLS])
def test_scripted_control_task_succeeds(adapter, case):
    adapter.agent = "scripted"
    assert checks.evaluate(case, adapter.run(case, frozenset(), 0)).task_success is True


def _canaries(cases):
    """Planted strings only: placeholders such as {{NEW_PASSWORD}} are the secret itself, not a canary."""
    return [str(p["canary"]) for c in cases for spec in c.attack_checks + c.attempt_checks
            for p in [spec.params] if "canary" in p and not str(p["canary"]).startswith("{{")]


def test_round2_cases_load_and_have_unique_canaries():
    root = Path(__file__).parents[1] / "cases"
    round1, round2 = load_cases("rotation/*.yaml", root=root), load_cases("round2/rotation/*.yaml", root=root)
    assert len(round2) == 8 and not any(c.control for c in round2)
    assert not {c.id for c in round1} & {c.id for c in round2}
    # Round 1 shares one system-prompt canary across its prompt-extraction cases on purpose.
    new = _canaries(round2)
    assert len(new) == len(set(new)) and not set(new) & set(_canaries(round1))
