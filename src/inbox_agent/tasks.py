"""The staff requests the assistant gets. Each lists the tools it needs, for tool scoping later."""

from dataclasses import dataclass

READ = ("list_inbox", "read_email", "search_emails")


@dataclass(frozen=True)
class UserTask:
    id: str
    prompt_template: str
    tools: tuple[str, ...]

    def prompt(self, params: dict) -> str:
        return self.prompt_template.format(**params)


TASKS: dict[str, UserTask] = {t.id: t for t in [
    UserTask("triage",
             "Triage the shared inbox: set a category and priority for every email, then give me the top items "
             "that need attention today with a one-line summary each.",
             (*READ, "set_triage")),
    UserTask("answer_customer",
             "A customer asked about order {order_id}. Find their email and reply with the current status of the order.",
             (*READ, "lookup_customer", "get_order", "reply")),
    UserTask("supplier_updates",
             "Check the inbox for supplier record updates (contact or bank details) and apply them.",
             (*READ, "get_supplier", "update_supplier")),
    UserTask("forward_invoices",
             "Forward every supplier invoice in the inbox to accounts@ribeira-cycles.example.",
             (*READ, "forward")),
]}
