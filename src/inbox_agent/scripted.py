"""Scripted agents with no LLM. The correct one is the positive control for task
checks; the obedient one does whatever the attacker asked, for attack checks."""

from inbox_agent.agent import AgentResult, FinalAnswer, TopItem
from inbox_agent.tasks import UserTask
from inbox_agent.tools import build_tools
from inbox_agent.world import World

PRIORITY_ORDER = {"urgent": 0, "high": 1, "normal": 2, "low": 3}


def _call(tools: dict, world: World, name: str, args: dict) -> str:
    if name not in tools:
        result = f"Refused: tool {name} is not available."
        world.tool_log.append({"tool": name, "args": args, "result": result})
        return result
    return tools[name].invoke(args)


class ScriptedInboxAgent:
    def run(self, world: World, task: UserTask, params: dict, tools: list | None = None) -> AgentResult:
        tools = {t.name: t for t in (tools if tools is not None else build_tools(world))}
        return AgentResult(getattr(self, f"_{task.id}")(tools, world, params))

    def _triage(self, tools, world, params) -> FinalAnswer:
        gt = world.ground_truth["emails"]
        for e in world.emails:
            if e.id in gt:
                _call(tools, world, "set_triage", {"email_id": e.id, **gt[e.id]})
        ranked = sorted((i for i in gt if gt[i]["priority"] in ("urgent", "high")),
                        key=lambda i: PRIORITY_ORDER[gt[i]["priority"]])[:5]
        subjects = {e.id: e.subject for e in world.emails}
        items = [TopItem(email_id=i, priority=gt[i]["priority"], one_line=subjects[i]) for i in ranked]
        return FinalAnswer(summary=f"Triaged {len(gt)} emails.", top_items=items)

    def _answer_customer(self, tools, world, params) -> FinalAnswer:
        order_id = params["order_id"]
        customer = next(c for c in world.customers if any(o.id == order_id for o in c.orders))
        order = next(o for o in customer.orders if o.id == order_id)
        _call(tools, world, "get_order", {"order_id": order_id})
        asked = [e for e in world.emails if e.sender == customer.email and order_id in f"{e.subject} {e.body}"]
        body = f"Hello {customer.name.split()[0]},\n\nYour order {order_id} is currently: {order.status}.\n\nRibeira Cycles"
        if asked:
            _call(tools, world, "reply", {"email_id": asked[0].id, "body": body})
        else:
            _call(tools, world, "send_email", {"to": customer.email, "subject": f"Your order {order_id}", "body": body})
        return FinalAnswer(summary=f"Told {customer.name} that {order_id} is {order.status}.", top_items=[])

    def _supplier_updates(self, tools, world, params) -> FinalAnswer:
        upd = world.ground_truth["legit_supplier_update"]
        _call(tools, world, "read_email", {"email_id": upd["email_id"]})
        result = _call(tools, world, "update_supplier", {"supplier_id": upd["supplier_id"], "field": upd["field"],
                                                         "value": upd["value"], "source_email_id": upd["email_id"]})
        return FinalAnswer(summary=result, top_items=[])

    def _forward_invoices(self, tools, world, params) -> FinalAnswer:
        accounts = world.company.colleagues["accounts"]
        for eid in world.ground_truth["invoice_email_ids"]:
            _call(tools, world, "forward", {"email_id": eid, "to": accounts, "note": "Invoice for processing."})
        return FinalAnswer(summary="Forwarded the invoices to accounts.", top_items=[])


class ObedientInboxAgent:
    """Ops: {"tool": name, "args": {...}} calls a tool; {"final": {...}} sets the answer."""

    def __init__(self, obey: list[dict]):
        self.obey = obey

    def run(self, world: World, task: UserTask, params: dict, tools: list | None = None) -> AgentResult:
        tool_list = tools if tools is not None else build_tools(world)
        by_name = {t.name: t for t in tool_list}
        final = None
        for op in self.obey:
            if "final" in op:
                final = FinalAnswer(**op["final"])
            else:
                _call(by_name, world, op["tool"], op.get("args", {}))
        if final is None:
            final = ScriptedInboxAgent().run(world, task, params, tool_list).final
        return AgentResult(final)
