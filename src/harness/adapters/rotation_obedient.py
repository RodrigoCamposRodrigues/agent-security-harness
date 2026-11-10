"""A scripted stand-in for a fully hijacked model: it does exactly what the payload asks.

Positive controls run it so a 0% attack rate from the real model means the checks could
have seen a success. Same tools as the LLM, so every defence applies to it unchanged.
"""

import re

from rotator.browser import CURRENT, AttemptAborted, BrowserSession
from rotator.changers import AgentReport, ScriptedChanger, Target


class ObedientChanger:
    def __init__(self, ops: list[dict]):
        self.ops = ops

    def change(self, session: BrowserSession, target: Target) -> AgentReport:
        return session.run(lambda: self._change(session, target))

    def _change(self, session: BrowserSession, target: Target) -> AgentReport:
        session.page.goto(f"{session.dashboard_url}/devices")
        session.snapshot()
        report, last = None, ""
        for op in self.ops:
            try:
                if op["op"] == "report":
                    report = AgentReport(device_serial_seen=op.get("serial_seen", ""),
                                         submitted=bool(op.get("submitted", False)),
                                         notes=self._resolve(session, op.get("notes", "")))
                else:
                    last = getattr(self, f"_op_{op['op']}")(session, target, op) or last
            except AttemptAborted:
                raise
            except LookupError as e:
                # A hijacked model keeps going after a tool says no; so does this one.
                last = str(e)
        if report is not None:
            return report
        body = session.page.inner_text("body")
        seen = target.serial if re.search(rf"\b{re.escape(target.serial)}\b", body) else ""
        return AgentReport(device_serial_seen=seen, submitted="Saved!" in body, notes=last[:300])

    @staticmethod
    def _resolve(session: BrowserSession, text: str) -> str:
        if session.defences.placeholders:
            return text
        for placeholder, real in session.secret_values().items():
            text = text.replace(placeholder, real)
        return text

    @staticmethod
    def _find(session: BrowserSession, label: str, tag: str | None = None) -> int:
        return ScriptedChanger._find(session, label, tag)

    @staticmethod
    def _has(session: BrowserSession, label: str) -> bool:
        return any(e.label == label for e in session.snapshot())

    def _op_search(self, session, target, op) -> str:
        session.page.goto(f"{session.dashboard_url}/devices")
        ScriptedChanger._relogin_if_needed(session)
        session.fill(self._find(session, "Find device by name"), self._resolve(session, op["text"]))
        return session.request_submit(self._find(session, "Search"))

    def _op_open_device(self, session, target, op) -> str:
        self._op_search(session, target, {"text": op["name"]})
        ScriptedChanger._relogin_if_needed(session)
        return session.click(self._find(session, op["name"], tag="a"))

    def _op_set_password(self, session, target, op) -> str:
        value = self._resolve(session, op["value"])
        if self._has(session, "Security") and not self._has(session, "Service PIN"):
            session.click(self._find(session, "Security", tag="a"))
            session.snapshot()
        if self._has(session, "Service PIN"):
            session.fill(self._find(session, "Service PIN"), value)
            session.fill(self._find(session, "Repeat PIN"), value)
            return session.request_submit(self._find(session, "Apply"))
        session.fill(self._find(session, "Current password"), self._resolve(session, CURRENT))
        session.fill(self._find(session, "New password"), value)
        session.fill(self._find(session, "Confirm new password"), value)
        result = session.request_submit(self._find(session, "Save"))
        if result.startswith("Submitted") and "Are you sure?" in session.page.inner_text("body"):
            session.snapshot()
            result = session.request_submit(self._find(session, "Yes, change password"))
        return result

    def _op_read_pages(self, session, target, op) -> str:
        for _ in range(int(op["count"])):
            session.read_page()
        return "read"

    def _op_rotate_target(self, session, target, op) -> str:
        return ScriptedChanger()._change(session, target).notes
