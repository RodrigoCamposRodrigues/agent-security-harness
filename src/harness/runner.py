"""Runs (case, setting, rep) jobs against one target. Resumable, parallel and
capped in spend, because a real run costs money and takes about 30 s."""

import json
import multiprocessing
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from harness import checks
from harness.adapters import Adapter, make_adapter
from harness.cases import AttackCase
from harness.pricing import cost_usd
from harness.records import ResultRow, RunRecord
from harness.report import build_report


@dataclass(frozen=True)
class Job:
    case_id: str
    setting: str
    rep: int


@dataclass
class RunSummary:
    done: int
    errors: int
    skipped: int
    cost_usd: float
    stopped_by_cap: bool


def read_rows(path: Path) -> list[dict]:
    """A killed process can leave half a line; that line is skipped and its job re-runs."""
    if not Path(path).exists():
        return []
    rows = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _append(path: Path, row: dict) -> None:
    with open(path, "a+b") as f:
        f.seek(0, 2)
        if f.tell():
            f.seek(-1, 2)
            if f.read(1) != b"\n":
                f.write(b"\n")
        f.write((json.dumps(row, ensure_ascii=False) + "\n").encode())


def _execute(adapter: Adapter, case: AttackCase, setting: str, disabled: frozenset[str], rep: int,
             target: str, agent: str, model: str) -> dict:
    started = datetime.now().isoformat(timespec="seconds")
    t0 = time.monotonic()
    try:
        record = adapter.run(case, disabled, rep)
    except Exception as e:  # noqa: BLE001 - an API error must not end the batch
        record = RunRecord(case_id=case.id, setting=setting, rep=rep, outcome="error",
                           error=f"{type(e).__name__}: {e}"[:300], seconds=time.monotonic() - t0)
    record = record.model_copy(update={"case_id": case.id, "setting": setting, "rep": rep})
    if record.outcome == "error":
        verdict = checks.Verdict(None, None, None, {})
    else:
        verdict = checks.evaluate(case, record)
    clean = record.redacted()
    row = ResultRow(
        **clean.model_dump(), target=target, family=case.family, owasp=case.owasp, model=model, agent=agent,
        control=case.control, attack_success=verdict.attack_success, attempted=verdict.attempted,
        task_success=verdict.task_success, checks=verdict.checks,
        cost_usd=cost_usd(model, record.input_tokens, record.output_tokens), started_at=started,
    )
    return row.model_dump()


# One adapter per worker process: Playwright and uvicorn threads don't survive fork.
_worker: dict = {}


def _init_worker(target: str, agent: str, model: str) -> None:
    _worker["adapter"] = make_adapter(target, agent, model)
    _worker["args"] = (target, agent, model)


def _worker_run(case: AttackCase, setting: str, disabled: frozenset[str], rep: int) -> dict:
    return _execute(_worker["adapter"], case, setting, disabled, rep, *_worker["args"])


def _write_meta(out_dir: Path, adapter: Adapter, target: str, agent: str, model: str,
                settings: list[str], cases: list[AttackCase]) -> dict:
    path = out_dir / "meta.json"
    order = list(adapter.settings())
    old = json.loads(path.read_text()) if path.exists() else {}
    used = set(old.get("settings", [])) | set(settings)
    files = sorted({*old.get("case_files", []), *(str(c.source) for c in cases if c.source)})
    available = adapter.settings()
    enabled = {s: sorted(set(adapter.defences) - available[s]) for s in order if s in used}
    changed = [s for s, d in old.get("enabled_defences", {}).items() if s in enabled and d != enabled[s]]
    if changed:
        raise ValueError(f"setting(s) {', '.join(changed)} now mean different enabled defences than when {out_dir} "
                         f"was run ({old['enabled_defences']} vs {enabled}); use a new --out folder")
    meta = {
        "target": target, "model": model, "agent": agent,
        "settings": [s for s in order if s in used],
        "headline": [s for s in adapter.headline if s in used],
        "created": old.get("created", datetime.now().isoformat(timespec="seconds")),
        "case_files": files,
        "enabled_defences": enabled,
    }
    path.write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def run_jobs(target: str, agent: str, model: str, cases: list[AttackCase], settings: list[str], reps: int,
             out_dir: Path, workers: int = 1, max_usd: float = 5.0) -> RunSummary:
    checks.validate(cases)
    adapter = make_adapter(target, agent, model)
    try:
        available = adapter.settings()
        unknown = [s for s in settings if s not in available]
        if unknown:
            raise ValueError(f"unknown setting(s) {', '.join(unknown)}; valid: {', '.join(available)}")

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        meta = _write_meta(out_dir, adapter, target, agent, model, settings, cases)
        runs = out_dir / "runs.jsonl"
        existing = read_rows(runs)
        done_keys = {(r["case_id"], r["setting"], r["rep"]) for r in existing if r["outcome"] != "error"}
        # The cap covers what this folder already spent, so a resume can't silently double the budget.
        spent = sum(r.get("cost_usd") or 0.0 for r in existing)

        ordered = [s for s in available if s in settings]
        by_id = {c.id: c for c in cases}
        jobs = [Job(c.id, s, r) for c in cases for s in ordered for r in range(reps)]
        todo = [j for j in jobs if (j.case_id, j.setting, j.rep) not in done_keys]
        summary = RunSummary(0, 0, len(jobs) - len(todo), spent, False)

        def record(row: dict) -> None:
            _append(runs, row)
            summary.cost_usd += row["cost_usd"]
            if row["outcome"] == "error":
                summary.errors += 1
            else:
                summary.done += 1

        def over_cap() -> bool:
            if summary.cost_usd > max_usd:
                summary.stopped_by_cap = True
            return summary.stopped_by_cap

        if workers <= 1:
            for job in todo:
                if over_cap():
                    break
                record(_execute(adapter, by_id[job.case_id], job.setting, available[job.setting], job.rep,
                                target, agent, model))
            over_cap()
        else:
            ctx = multiprocessing.get_context("spawn")
            with ProcessPoolExecutor(workers, mp_context=ctx, initializer=_init_worker,
                                     initargs=(target, agent, model)) as pool:
                pending, queue = set(), list(todo)
                while queue or pending:
                    while queue and len(pending) < workers and not over_cap():
                        job = queue.pop(0)
                        pending.add(pool.submit(_worker_run, by_id[job.case_id], job.setting,
                                                available[job.setting], job.rep))
                    if not pending:
                        break
                    finished, pending = wait(pending, return_when=FIRST_COMPLETED)
                    for fut in finished:
                        record(fut.result())

        (out_dir / "report.md").write_text(build_report(read_rows(runs), by_id, meta))
        return summary
    finally:
        adapter.close()
