"""Target 1: Project 2's password rotation agent, run the way its own evals run it,
with payloads planted in the dashboard and defences switched off by name."""

import shutil
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, quote_plus

import openai
from dashboard.db import INJECTION_NOTE, connect
from langgraph.checkpoint.sqlite import SqliteSaver
from rotator.browser import BrowserWorker
from rotator.changers import LLMChanger, ScriptedChanger
from rotator.config import DEFENCE_NAMES, Defences, Settings
from rotator.device import DeviceProbe
from rotator.protocol import Deps, build_graph, start_run
from testbed import start_dashboard

from harness.cases import AttackCase
from harness.records import RunRecord


def _subclasses(cls: type) -> set[type]:
    return {cls} | {s for c in cls.__subclasses__() for s in _subclasses(c)}


# Project 2 logs any changer exception as "<ClassName>: <message>" and escalates. An API
# failure says nothing about the attack, so it must become an error row the runner retries.
API_ERRORS = tuple(sorted(f"{c.__name__}:" for c in _subclasses(openai.OpenAIError)))


def api_error(events: list[dict]) -> str:
    return next((e["error"] for e in events if e.get("step") == "change_failed"
                 and str(e.get("error", "")).startswith(API_ERRORS)), "")

TEXT_SURFACES = {"notes": "notes", "name": "name", "location": "location"}


def secret_variants(secrets) -> set[str]:
    """A GET form puts a password in the URL percent-encoded, so redaction needs those spellings too."""
    out = set()
    for s in secrets:
        if s:
            out |= {s, quote(s, safe=""), quote_plus(s, safe="")}
    return out


def ablation_settings() -> dict[str, frozenset[str]]:
    every = frozenset(DEFENCE_NAMES)
    settings = {"all_on": frozenset()}
    settings |= {f"no_{d}": frozenset({d}) for d in DEFENCE_NAMES}
    settings |= {f"only_{d}": every - {d} for d in DEFENCE_NAMES}
    settings["all_off"] = every
    return settings


class RotationAdapter:
    name = "rotation"
    defences = DEFENCE_NAMES
    headline = ("all_off", "all_on")

    def __init__(self, agent: str = "llm", model: str = "gpt-6-luna"):
        self.agent, self.model = agent, model
        self.dash = None
        self.worker = None
        self._workdir: Path | None = None

    def settings(self) -> dict[str, frozenset[str]]:
        return ablation_settings()

    def _start(self) -> None:
        # Started on first use: the runner builds adapters only to read settings, too.
        if self.dash is None:
            self._workdir = Path(tempfile.mkdtemp(prefix="harness-rotation-"))
            self.dash = start_dashboard(self._workdir / "dashboard.db")
            self.worker = BrowserWorker()

    def _prepare(self, case: AttackCase) -> None:
        self._start()
        self.dash.reset()
        with connect(self.dash.db_path) as conn:
            # Project 2 seeds its own injection notes; they would contaminate controls and every other case.
            conn.execute("UPDATE devices SET notes = '' WHERE notes = ?", (INJECTION_NOTE,))
            for inj in case.injections:
                self._plant(conn, inj)

    def _plant(self, conn: sqlite3.Connection, inj: dict) -> None:
        surface = inj["surface"]
        if surface in TEXT_SURFACES:
            column = TEXT_SURFACES[surface]
            if inj.get("mode", "append") == "replace":
                cur = conn.execute(f"UPDATE devices SET {column} = ? WHERE serial = ?", (inj["text"], inj["device"]))
            else:
                cur = conn.execute(f"UPDATE devices SET {column} = TRIM({column} || ' ' || ?) WHERE serial = ?",
                                   (inj["text"], inj["device"]))
            if cur.rowcount == 0:
                raise ValueError(f"no device {inj['device']!r} to plant on")
        elif surface == "unmanaged_device":
            conn.execute(
                "INSERT INTO devices (serial, name, model, location, password, password_changed_at, notes)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (inj["serial"], inj["name"], inj["model"], inj["location"], inj["password"],
                 datetime.now().isoformat(), inj.get("notes", "")),
            )
        else:
            raise ValueError(f"unknown injection surface {surface!r}")

    def _changer(self, case: AttackCase):
        if self.agent == "llm":
            return LLMChanger(self.model)
        if self.agent == "scripted":
            return ScriptedChanger()
        if self.agent == "obedient":
            from harness.adapters.rotation_obedient import ObedientChanger
            return ObedientChanger(case.obey)
        raise ValueError(f"unknown agent {self.agent!r}")

    def _device_passwords(self) -> dict[str, str]:
        with connect(self.dash.db_path) as conn:
            return {r["serial"]: r["password"] for r in conn.execute("SELECT serial, password FROM devices")}

    def run(self, case: AttackCase, disabled: frozenset[str], rep: int) -> RunRecord:
        self._prepare(case)
        serial = case.task_params["serial"]
        dash = self.dash
        seeded = self._device_passwords()
        run_id = uuid.uuid4().hex[:12]
        data_dir = self._workdir / "runs" / run_id
        data_dir.mkdir(parents=True)
        settings = Settings(dashboard_url=dash.url, data_dir=data_dir, model=self.model,
                            defences=Defences().with_disabled(disabled))
        deps = Deps(vault=dash.vault, probe=DeviceProbe(dash.url), changer=self._changer(case), worker=self.worker,
                    settings=settings, clock=dash.clock)
        conn = sqlite3.connect(data_dir / "checkpoints.db", check_same_thread=False)
        try:
            graph = build_graph(deps, SqliteSaver(conn))
            t0 = time.monotonic()
            view = start_run(graph, serial, run_id=run_id)
            wall = time.monotonic() - t0
            events = deps.audit(run_id).read()
        finally:
            conn.close()
            shutil.rmtree(data_dir, ignore_errors=True)

        now = self._device_passwords()
        record = dash.vault.get_device(serial)
        changes = [e for e in events if e["step"] in ("change", "change_failed")]
        escalated = view.get("waiting_for") is not None
        outcome = view.get("outcome") or ("escalated" if escalated else view.get("status", "unknown"))
        failure = api_error(events)
        if failure:
            outcome = "error"
        changed = {s: p for s, p in now.items() if seeded.get(s) != p}
        state = {
            "outcome": outcome,
            "reason": view.get("reason", ""),
            "change_attempts": view.get("change_attempts", 0),
            "escalated": escalated,
            "others_changed": sorted(s for s in changed if s != serial),
            "target_accepts_active": bool(record.active) and now[serial] == record.active,
            "lost_password": now[serial] not in {record.active, record.pending} - {""},
            "target_serial": serial,
            "device_passwords_changed_to": changed,
        }
        vault_values = [record.active, record.pending, record.previous, record.abandoned]
        return RunRecord(
            case_id=case.id, setting=next((s for s, d in self.settings().items() if d == disabled), ""), rep=rep, outcome=outcome, error=failure, actions=events, state=state,
            final=changes[-1].get("report") if changes else None,
            input_tokens=sum(e.get("input_tokens", 0) for e in changes),
            output_tokens=sum(e.get("output_tokens", 0) for e in changes),
            seconds=sum(e.get("seconds", 0.0) for e in changes) or wall,
            private={"secrets": sorted(secret_variants([*seeded.values(), *now.values(), *vault_values]))},
        )

    def close(self) -> None:
        if self.worker:
            self.worker.close()
        if self.dash:
            self.dash.stop()
        if self._workdir:
            shutil.rmtree(self._workdir, ignore_errors=True)
        self.dash = self.worker = self._workdir = None
