"""What one run produced. Real secrets sit in `private`, which never reaches disk."""

from pydantic import BaseModel, Field

SECRET_MARK = "[secret]"


def _scrub(value, secrets: list[str]):
    if isinstance(value, str):
        for s in secrets:
            value = value.replace(s, SECRET_MARK)
        return value
    if isinstance(value, dict):
        return {_scrub(k, secrets): _scrub(v, secrets) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v, secrets) for v in value]
    return value


class RunRecord(BaseModel):
    case_id: str
    setting: str
    rep: int
    outcome: str
    error: str = ""
    actions: list[dict] = []
    state: dict = {}
    final: dict | str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    private: dict = Field(default_factory=dict, exclude=True)

    def redacted(self) -> "RunRecord":
        # Longest first, so a secret that contains another is replaced whole.
        secrets = sorted({s for s in self.private.get("secrets", []) if s}, key=len, reverse=True)
        return self.model_copy(update={
            "actions": _scrub(self.actions, secrets),
            "state": _scrub(self.state, secrets),
            "final": _scrub(self.final, secrets),
            "error": _scrub(self.error, secrets),
        })


class ResultRow(RunRecord):
    target: str
    family: str
    owasp: list[str]
    model: str
    agent: str
    control: bool
    attack_success: bool | None
    attempted: bool | None
    task_success: bool | None
    checks: dict[str, bool] = {}
    cost_usd: float = 0.0
    started_at: str
