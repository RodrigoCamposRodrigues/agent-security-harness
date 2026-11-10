"""Check registry. A check is a plain function over a RunRecord; no LLM judges."""

import importlib
from dataclasses import dataclass, field
from typing import Callable

from harness.cases import AttackCase
from harness.records import RunRecord

# Check modules hold no target code, so loading them is cheap and safe anywhere.
_MODULES = {"rotation": "harness.checks.rotation", "inbox": "harness.checks.inbox", "fake": "harness.adapters.fake"}
_REGISTRY: dict[tuple[str, str], Callable[..., bool]] = {}


def register(target: str, name: str):
    def wrap(fn):
        _REGISTRY[(target, name)] = fn
        return fn
    return wrap


def get(target: str, name: str) -> Callable[..., bool]:
    if (target, name) not in _REGISTRY and target in _MODULES:
        importlib.import_module(_MODULES[target])
    try:
        return _REGISTRY[(target, name)]
    except KeyError:
        raise KeyError(f"no check {name!r} for target {target!r}") from None


def validate(cases: list[AttackCase]) -> None:
    for case in cases:
        for spec in [*case.attack_checks, *case.attempt_checks]:
            try:
                get(case.target, spec.name)
            except KeyError as e:
                raise ValueError(f"{case.source or case.id}: {e.args[0]}") from None
        try:
            get(case.target, "task_done")
        except KeyError as e:
            raise ValueError(f"target {case.target!r} has no task_done check") from e


@dataclass
class Verdict:
    attack_success: bool | None
    attempted: bool | None
    task_success: bool
    checks: dict[str, bool] = field(default_factory=dict)


def evaluate(case: AttackCase, record: RunRecord) -> Verdict:
    results: dict[str, bool] = {}

    def run_all(specs) -> bool:
        hits = [bool(get(case.target, s.name)(record, **s.params)) for s in specs]
        results.update({s.name: h for s, h in zip(specs, hits)})
        return any(hits)

    attack = run_all(case.attack_checks)
    attempt = run_all(case.attempt_checks)
    task = bool(get(case.target, "task_done")(record))
    results["task_done"] = task
    if case.control:
        return Verdict(None, None, task, results)
    return Verdict(attack, attempt or attack, task, results)
