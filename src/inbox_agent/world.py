"""The fake business behind the shared inbox. Loaded fresh from JSON for every run,
so nothing one run does can leak into the next."""

import json
from functools import cache
from importlib.resources import files
from typing import Literal

from pydantic import BaseModel


class Company(BaseModel):
    name: str
    domain: str
    inbox: str
    colleagues: dict[str, str]
    about: str


class Email(BaseModel):
    id: str
    sender: str
    to: str
    subject: str
    body: str
    received_at: str


class Order(BaseModel):
    id: str
    status: str
    items: list[str]
    total: float


class Customer(BaseModel):
    id: str
    name: str
    email: str
    phone: str
    address: str
    orders: list[Order]


class Supplier(BaseModel):
    id: str
    name: str
    domain: str
    email: str
    iban: str
    phone: str


class SentMessage(BaseModel):
    kind: Literal["send", "reply", "forward"]
    to: str
    subject: str
    body: str
    ref_email_id: str | None = None


class HeldAction(BaseModel):
    tool: str
    args: dict
    reason: str


class SupplierChange(BaseModel):
    supplier_id: str
    field: str
    old: str
    new: str
    source_email_id: str
    applied: bool


@cache
def _fixture(name: str) -> str:
    return (files("inbox_agent") / "fixtures" / name).read_text()


class World(BaseModel):
    company: Company
    emails: list[Email]
    customers: list[Customer]
    suppliers: list[Supplier]
    outbox: list[SentMessage] = []
    held: list[HeldAction] = []
    triage: dict[str, tuple[str, str]] = {}
    supplier_changes: list[SupplierChange] = []
    tool_log: list[dict] = []

    @classmethod
    def load(cls, extra_emails: list[dict] = ()) -> "World":
        company = Company(**json.loads(_fixture("company.json")))
        emails = [Email(**e) for e in json.loads(_fixture("emails.json"))]
        for i, extra in enumerate(extra_emails, start=1):
            emails.append(Email(id=f"x{i}", sender=extra["from"], to=company.inbox, subject=extra["subject"],
                                body=extra["body"], received_at=extra["received_at"]))
        return cls(
            company=company,
            emails=emails,
            customers=[Customer(**c) for c in json.loads(_fixture("customers.json"))],
            suppliers=[Supplier(**s) for s in json.loads(_fixture("suppliers.json"))],
        )

    @property
    def ground_truth(self) -> dict:
        return json.loads(_fixture("ground_truth.json"))

    def private_values(self) -> dict[str, str]:
        """Private value -> its owner (a customer's email, or a supplier's domain). Leak checks match on these."""
        values = {}
        for c in self.customers:
            values[c.phone] = c.email
            values[c.address] = c.email
        for s in self.suppliers:
            values[s.iban] = s.domain
        return values

    def is_company(self, address: str) -> bool:
        return address.strip().lower().endswith("@" + self.company.domain.lower())
