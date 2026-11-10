import pytest

from harness import checks
from harness.cases import AttackCase, CheckSpec
from harness.records import RunRecord


def make_case(**kw):
    base = dict(id="c", title="t", target="fake", family="f", goal="g", owasp=[], user_task="fake",
                injections=[{"surface": "fake"}])
    return AttackCase(**{**base, **kw})


def rec(**kw):
    return RunRecord(case_id="c", setting="off", rep=0, outcome="succeeded", **kw)


def test_evaluate_any_attack_check_true():
    case = make_case(attack_checks=[CheckSpec(name="fake_attack"), CheckSpec(name="fake_never")])
    v = checks.evaluate(case, rec(state={"attack": True}))
    assert v.attack_success is True
    assert v.checks == {"fake_attack": True, "fake_never": False, "task_done": True}
    assert checks.evaluate(case, rec(state={"attack": False})).attack_success is False


def test_attempted_true_when_attack_succeeds():
    case = make_case(attack_checks=[CheckSpec(name="fake_attack")], attempt_checks=[CheckSpec(name="fake_never")])
    assert checks.evaluate(case, rec(state={"attack": True})).attempted is True
    assert checks.evaluate(case, rec(state={"attack": False})).attempted is False


def test_attempt_check_alone_sets_attempted():
    case = make_case(attack_checks=[CheckSpec(name="fake_never")],
                     attempt_checks=[CheckSpec(name="fake_attack")])
    v = checks.evaluate(case, rec(state={"attack": True}))
    assert v.attack_success is False and v.attempted is True


def test_control_case_has_no_attack_verdict():
    v = checks.evaluate(make_case(injections=[]), rec())
    assert v.attack_success is None and v.attempted is None and v.task_success is True


def test_check_params_are_passed():
    case = make_case(attack_checks=[CheckSpec(name="fake_state_equals", params={"key": "x", "value": 3})])
    assert checks.evaluate(case, rec(state={"x": 3})).attack_success is True


def test_validate_names_file_and_check(tmp_path):
    case = make_case(attack_checks=[CheckSpec(name="nope")], source=tmp_path / "bad.yaml")
    with pytest.raises(ValueError, match=r"bad\.yaml.*nope"):
        checks.validate([case])


def test_redacted_replaces_secrets_everywhere():
    r = rec(
        actions=[{"step": "fill", "value": "pw-AAA and more"}],
        state={"passwords": {"dev": "pw-BBB"}, "list": ["x pw-AAA"]},
        final={"notes": "pw-BBB"},
        error="leaked pw-AAA",
        private={"secrets": ["pw-AAA", "pw-BBB", ""]},
    )
    red = r.redacted()
    dumped = red.model_dump_json()
    assert "pw-AAA" not in dumped and "pw-BBB" not in dumped
    assert red.actions[0]["value"] == "[secret] and more"
    assert red.final == {"notes": "[secret]"}
    assert "private" not in r.model_dump()
    assert r.actions[0]["value"] == "pw-AAA and more"
