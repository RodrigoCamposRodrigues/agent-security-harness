"""Attack cases live in YAML, one per file, so adding an attack needs no code."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ValidationError, field_validator

from harness.owasp import CATEGORIES


class CheckSpec(BaseModel):
    name: str
    params: dict = {}


class AttackCase(BaseModel):
    id: str
    title: str
    target: Literal["rotation", "inbox", "fake"]
    family: str
    goal: str
    owasp: list[str]
    user_task: str
    task_params: dict = {}
    injections: list[dict] = []
    attack_checks: list[CheckSpec] = []
    attempt_checks: list[CheckSpec] = []
    obey: list[dict] = []
    obedient_all_on: Literal["blocked", "succeeds", "unknown"] = "unknown"
    source: Path | None = None

    @field_validator("owasp")
    @classmethod
    def _known_owasp(cls, ids: list[str]) -> list[str]:
        unknown = [i for i in ids if i not in CATEGORIES]
        if unknown:
            raise ValueError(f"unknown OWASP id(s): {', '.join(unknown)}")
        return ids

    @property
    def control(self) -> bool:
        return not self.injections


def _load_one(path: Path) -> AttackCase:
    try:
        data = yaml.safe_load(path.read_text())
        return AttackCase(**data, source=path)
    except (ValidationError, yaml.YAMLError, TypeError) as e:
        raise ValueError(f"{path}: {e}") from e


def load_cases(pattern: str, root: Path = Path("cases")) -> list[AttackCase]:
    cases = [_load_one(p) for p in sorted(Path(root).glob(pattern))]
    seen: dict[str, Path] = {}
    for case in cases:
        if case.id in seen:
            raise ValueError(f"duplicate case id {case.id!r} in {seen[case.id]} and {case.source}")
        seen[case.id] = case.source
    return sorted(cases, key=lambda c: c.id)
