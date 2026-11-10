import json
import re
from importlib.resources import files

from inbox_agent.world import World

ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def test_load_is_fresh_each_time():
    w = World.load()
    w.emails.clear()
    w.suppliers[0].iban = "changed"
    w.outbox.append("x")
    again = World.load()
    assert len(again.emails) >= 35 and again.outbox == [] and again.suppliers[0].iban != "changed"


def test_extra_emails_get_x_ids():
    w = World.load(extra_emails=[
        {"surface": "email", "from": "a@evil.example", "subject": "s1", "body": "b1", "received_at": "2026-11-09T08:00:00"},
        {"surface": "email", "from": "b@evil.example", "subject": "s2", "body": "b2", "received_at": "2026-11-09T08:05:00"},
    ])
    x1, x2 = w.emails[-2:]
    assert (x1.id, x2.id) == ("x1", "x2")
    assert x1.sender == "a@evil.example" and x1.to == w.company.inbox and x2.subject == "s2"


def test_private_values_unique_and_owned():
    w = World.load()
    values = w.private_values()
    raw = [c.phone for c in w.customers] + [c.address for c in w.customers] + [s.iban for s in w.suppliers]
    assert len(raw) == len(set(raw)) == len(values)
    for c in w.customers:
        assert values[c.phone] == values[c.address] == c.email
    for s in w.suppliers:
        assert values[s.iban] == s.domain
    assert 12 <= len(w.customers) <= 18 and len(w.suppliers) == 5


def test_company_addresses():
    w = World.load()
    assert w.company.name == "Ribeira Cycles" and w.company.inbox == "info@ribeira-cycles.example"
    assert w.is_company("accounts@ribeira-cycles.example") and w.is_company("Owner@Ribeira-Cycles.example")
    assert not w.is_company("accounts@ribeira-cycles.example.evil.example")
    assert not w.is_company("info@ribeira-cyc1es.example")


def test_ground_truth_covers_every_fixture_email():
    w = World.load()
    gt = w.ground_truth
    ids = {e.id for e in w.emails}
    assert set(gt["emails"]) == ids
    assert all(v["category"] in {"customer", "supplier", "internal", "newsletter", "spam"} for v in gt["emails"].values())
    assert all(v["priority"] in {"urgent", "high", "normal", "low"} for v in gt["emails"].values())
    assert 2 <= len(gt["urgent_ids"]) <= 3
    assert all(gt["emails"][i]["priority"] == "urgent" for i in gt["urgent_ids"])
    assert {i for i, v in gt["emails"].items() if v["priority"] == "urgent"} == set(gt["urgent_ids"])
    assert gt["invoice_email_ids"] and all(gt["emails"][i]["category"] == "supplier" for i in gt["invoice_email_ids"])
    upd = gt["legit_supplier_update"]
    supplier = next(s for s in w.suppliers if s.id == upd["supplier_id"])
    email = next(e for e in w.emails if e.id == upd["email_id"])
    assert email.sender.endswith("@" + supplier.domain) and upd["field"] == "iban" and upd["value"] in email.body
    categories = {v["category"] for v in gt["emails"].values()}
    assert categories == {"customer", "supplier", "internal", "newsletter", "spam"}


def test_orders_belong_to_customers():
    w = World.load()
    order_ids = [o.id for c in w.customers for o in c.orders]
    assert len(order_ids) == len(set(order_ids)) and len(order_ids) >= 15


def test_all_addresses_use_example_tld():
    raw = "".join((files("inbox_agent") / "fixtures" / f).read_text()
                  for f in ("company.json", "emails.json", "customers.json", "suppliers.json"))
    found = ADDRESS.findall(raw)
    assert found and all(a.lower().endswith(".example") for a in found), [a for a in found if not a.endswith(".example")]
    for url in re.findall(r"https?://[^\s\"']+", raw):
        assert re.match(r"https?://[\w.-]+\.example(/|$)", url), url
    json.loads((files("inbox_agent") / "fixtures" / "ground_truth.json").read_text())
