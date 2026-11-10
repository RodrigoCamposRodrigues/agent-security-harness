import pytest

from inbox_agent.tools import build_tools
from inbox_agent.world import World

NAMES = ["list_inbox", "read_email", "search_emails", "lookup_customer", "get_order", "get_supplier", "set_triage",
         "send_email", "reply", "forward", "update_supplier"]


@pytest.fixture
def world():
    return World.load()


def tools(world):
    return {t.name: t for t in build_tools(world)}


def test_exact_tool_set(world):
    assert sorted(tools(world)) == sorted(NAMES)


def test_list_inbox_and_filter(world):
    t = tools(world)
    assert "e07" in t["list_inbox"].invoke({}) and "e03" in t["list_inbox"].invoke({})
    filtered = t["list_inbox"].invoke({"filter": "atlantic-tyres"})
    assert "e09" in filtered and "e19" in filtered and "e03" not in filtered


def test_read_email_shows_headers_and_body(world):
    text = tools(world)["read_email"].invoke({"email_id": "e07"})
    assert "From: diogo.ramos@net.example" in text and "consumer arbitration centre" in text
    assert "not found" in tools(world)["read_email"].invoke({"email_id": "e99"}).lower()


def test_search_emails(world):
    out = tools(world)["search_emails"].invoke({"query": "rc-1002"})
    assert "e02" in out and "e40" in out and "e07" not in out


def test_lookup_customer_and_get_order(world):
    t = tools(world)
    by_email = t["lookup_customer"].invoke({"email_or_name": "diogo.ramos@net.example"})
    assert "Diogo Ramos" in by_email and "+351 915 400 104" in by_email and "RC-1004" in by_email
    assert "Diogo Ramos" in t["lookup_customer"].invoke({"email_or_name": "diogo ramos"})
    order = t["get_order"].invoke({"order_id": "RC-1004"})
    assert "awaiting payment" in order and "diogo.ramos@net.example" in order


def test_get_supplier(world):
    out = tools(world)["get_supplier"].invoke({"name": "atlantic"})
    assert "S2" in out and "PT50 0099 0002 0000 5520 3302 4" in out and "atlantic-tyres.example" in out


def test_set_triage_records_and_validates(world):
    t = tools(world)
    t["set_triage"].invoke({"email_id": "e07", "category": "customer", "priority": "urgent"})
    assert world.triage["e07"] == ("customer", "urgent")
    assert "invalid" in t["set_triage"].invoke({"email_id": "e07", "category": "other", "priority": "urgent"}).lower()


def test_send_email_records_outbox(world):
    tools(world)["send_email"].invoke({"to": "x@y.example", "subject": "s", "body": "b"})
    [m] = world.outbox
    assert (m.kind, m.to, m.subject, m.body, m.ref_email_id) == ("send", "x@y.example", "s", "b", None)


def test_reply_goes_to_original_sender(world):
    tools(world)["reply"].invoke({"email_id": "e02", "body": "On its way."})
    [m] = world.outbox
    assert m.kind == "reply" and m.to == "bruno.costa@mailbox.example" and m.ref_email_id == "e02"
    assert m.subject == "Re: Where is order RC-1002?"


def test_forward_includes_note_and_original(world):
    tools(world)["forward"].invoke({"email_id": "e03", "to": "accounts@ribeira-cycles.example", "note": "FYI"})
    [m] = world.outbox
    assert m.kind == "forward" and m.to == "accounts@ribeira-cycles.example"
    assert m.body.startswith("FYI") and "Invoice DC-2026-311" in m.body and "PT50 0099 0001" in m.body


def test_update_supplier_applies_change(world):
    out = tools(world)["update_supplier"].invoke(
        {"supplier_id": "S2", "field": "iban", "value": "PT50 1111", "source_email_id": "e19"})
    s2 = next(s for s in world.suppliers if s.id == "S2")
    assert s2.iban == "PT50 1111" and "updated" in out.lower()
    [change] = world.supplier_changes
    assert (change.old, change.new, change.applied, change.source_email_id) == (
        "PT50 0099 0002 0000 5520 3302 4", "PT50 1111", True, "e19")


def test_update_supplier_rejects_unknown_field(world):
    out = tools(world)["update_supplier"].invoke({"supplier_id": "S2", "field": "id", "value": "x", "source_email_id": "e19"})
    assert "cannot" in out.lower() and world.supplier_changes == []


def test_tool_log_records_calls(world):
    t = tools(world)
    t["read_email"].invoke({"email_id": "e01"})
    t["reply"].invoke({"email_id": "e01", "body": "Thanks!"})
    assert [e["tool"] for e in world.tool_log] == ["read_email", "reply"]
    assert world.tool_log[1]["args"] == {"email_id": "e01", "body": "Thanks!"}
    assert "Ana" in world.tool_log[0]["result"]
