"""Deterministic target for testing the harness itself, with no browser or LLM."""

from harness.cases import AttackCase
from harness.checks import register
from harness.records import RunRecord

# Keys that already raised, so `raise_on_rep` fails once and a resume succeeds.
_RAISED: set[tuple] = set()


class FakeAdapter:
    name = "fake"
    defences = ("guard",)
    headline = ("off", "on")

    def __init__(self, agent: str = "scripted", model: str = "scripted"):
        self.agent, self.model = agent, model

    def settings(self) -> dict[str, frozenset[str]]:
        return {"on": frozenset(), "off": frozenset({"guard"})}

    def run(self, case: AttackCase, disabled: frozenset[str], rep: int) -> RunRecord:
        params = case.task_params
        setting = next(s for s, d in self.settings().items() if d == disabled)
        key = (str(case.source), case.id, setting, rep)
        if params.get("raise_on_rep") == rep and key not in _RAISED:
            _RAISED.add(key)
            raise RuntimeError("simulated API error")
        tokens_in, tokens_out = params.get("tokens", [0, 0])
        return RunRecord(
            case_id=case.id, setting=setting, rep=rep, outcome="succeeded",
            state={"attack": setting in params.get("attack_on", [])},
            input_tokens=tokens_in, output_tokens=tokens_out,
        )

    def close(self) -> None:
        pass


@register("fake", "fake_attack")
def fake_attack(record: RunRecord) -> bool:
    return bool(record.state.get("attack"))


@register("fake", "fake_never")
def fake_never(record: RunRecord) -> bool:
    return False


@register("fake", "fake_state_equals")
def fake_state_equals(record: RunRecord, key: str, value) -> bool:
    return record.state.get(key) == value


@register("fake", "task_done")
def task_done(record: RunRecord) -> bool:
    return record.outcome == "succeeded"
