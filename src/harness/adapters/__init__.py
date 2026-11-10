"""Adapter protocol: the only door between the harness and a target agent."""

import importlib
from typing import Protocol

from harness.cases import AttackCase
from harness.records import RunRecord

_ADAPTERS = {
    "fake": "harness.adapters.fake:FakeAdapter",
    "rotation": "harness.adapters.rotation:RotationAdapter",
    "inbox": "harness.adapters.inbox:InboxAdapter",
}


class Adapter(Protocol):
    name: str
    defences: tuple[str, ...]
    headline: tuple[str, ...]

    def settings(self) -> dict[str, frozenset[str]]: ...
    def run(self, case: AttackCase, disabled: frozenset[str], rep: int) -> RunRecord: ...
    def close(self) -> None: ...


def make_adapter(target: str, agent: str, model: str) -> Adapter:
    """Constructing an adapter must be cheap: heavy resources start on the first run."""
    module, cls = _ADAPTERS[target].split(":")
    return getattr(importlib.import_module(module), cls)(agent=agent, model=model)
