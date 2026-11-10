"""Target 2: the shared-inbox assistant. Each run loads a fresh world, adds the
attacker's emails, runs the chosen agent and records what it did."""

from inbox_agent.agent import SYSTEM_PROMPT, AgentResult, run_agent
from inbox_agent.defences import DEFENCES, hardened_prompt
from inbox_agent.quarantine import FakeQuarantiner, Quarantiner
from inbox_agent.scripted import ObedientInboxAgent, ScriptedInboxAgent
from inbox_agent.tasks import TASKS
from inbox_agent.tools import build_tools
from inbox_agent.world import World

from harness.cases import AttackCase
from harness.records import RunRecord


def _order_facts(world: World, order_id: str | None) -> dict | None:
    for c in world.customers:
        for o in c.orders:
            if o.id == order_id:
                return {"id": o.id, "status": o.status, "customer_email": c.email}
    return None


def record_from(case: AttackCase, world: World, result: AgentResult, rep: int, setting: str = "") -> RunRecord:
    """Everything a check needs is copied into state, so checks never import the target."""
    fixture_ids = set(world.ground_truth["emails"])
    state = {
        "task_id": case.user_task,
        "task_params": case.task_params,
        "company_domain": world.company.domain,
        "outbox": [m.model_dump() for m in world.outbox],
        "held": [h.model_dump() for h in world.held],
        "triage": {k: list(v) for k, v in world.triage.items()},
        "supplier_changes": [c.model_dump() for c in world.supplier_changes],
        "ground_truth": world.ground_truth,
        "private_values": world.private_values(),
        "injected_ids": [e.id for e in world.emails if e.id not in fixture_ids],
        "order": _order_facts(world, case.task_params.get("order_id")),
    }
    return RunRecord(
        case_id=case.id, setting=setting, rep=rep, outcome="error" if result.failed else "answered" if result.final else "no_answer",
        error=result.error, actions=list(world.tool_log), state=state,
        final=result.final.model_dump() if result.final else None,
        input_tokens=result.input_tokens, output_tokens=result.output_tokens,
    )


class InboxAdapter:
    name = "inbox"
    defences = DEFENCES
    headline = ("none", "all")

    def __init__(self, agent: str = "llm", model: str = "gpt-6-luna", quarantiner=None):
        """`quarantiner`, if given, serves every run. Otherwise the LLM agent gets one real
        Quarantiner per adapter (one per worker process, so its cache is warmed once per
        worker), and the scripted agents a free FakeQuarantiner per run."""
        self.agent, self.model = agent, model
        self.quarantiner = quarantiner

    def _reader(self, world: World):
        if self.quarantiner is None and self.agent == "llm":
            self.quarantiner = Quarantiner(self.model)
        return self.quarantiner or FakeQuarantiner(world)

    def settings(self) -> dict[str, frozenset[str]]:
        every = frozenset(DEFENCES)
        # code_only: the three code checks, without the two defences that change what the model reads.
        return {"none": every, **{f"only_{d}": every - {d} for d in DEFENCES},
                "code_only": frozenset({"prompt_hardening", "quarantined_reader"}),
                "no_quarantined_reader": frozenset({"quarantined_reader"}), "all": frozenset()}

    def run(self, case: AttackCase, disabled: frozenset[str], rep: int) -> RunRecord:
        world = World.load(extra_emails=case.injections)
        task = TASKS[case.user_task]
        enabled = frozenset(DEFENCES) - disabled
        reader = self._reader(world) if "quarantined_reader" in enabled else None
        before = (reader.input_tokens, reader.output_tokens) if reader else (0, 0)
        tools = build_tools(world, task, enabled, quarantiner=reader)
        if self.agent == "llm":
            prompt = hardened_prompt(SYSTEM_PROMPT) if "prompt_hardening" in enabled else SYSTEM_PROMPT
            result = run_agent(world, task, case.task_params, self.model, tools=tools, system_prompt=prompt)
        elif self.agent == "scripted":
            result = ScriptedInboxAgent().run(world, task, case.task_params, tools)
        elif self.agent == "obedient":
            result = ObedientInboxAgent(case.obey).run(world, task, case.task_params, tools)
        else:
            raise ValueError(f"unknown agent {self.agent!r}")
        if reader:  # the run that triggered a quarantine call carries its tokens, so the spend cap sees them
            result.input_tokens += reader.input_tokens - before[0]
            result.output_tokens += reader.output_tokens - before[1]
        setting = next((s for s, d in self.settings().items() if d == disabled), "")
        return record_from(case, world, result, rep, setting)

    def close(self) -> None:
        pass
