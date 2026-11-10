"""`harness run | ablate | report | list`."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from harness.adapters import make_adapter
from harness.cases import AttackCase, load_cases
from harness.report import build_report
from harness.runner import read_rows, run_jobs

CASES_ROOT = Path("cases")


def _load(target: str, pattern: str | None) -> list[AttackCase]:
    pattern = pattern or f"{target}/*.yaml"
    given = Path(pattern)
    if given.is_dir():
        cases = load_cases("*.yaml", root=given)
    elif given.is_file():
        cases = load_cases(given.name, root=given.parent)
    else:
        cases = load_cases(pattern, root=CASES_ROOT)
    wrong = [c.id for c in cases if c.target != target]
    if wrong:
        raise ValueError(f"cases for another target: {', '.join(wrong)}")
    if not cases:
        raise ValueError(f"no cases match {pattern!r}")
    return cases


def _run(args, settings: list[str]) -> int:
    agent = "scripted" if args.dry_run else args.agent
    cases = _load(args.target, args.cases)
    label = args.label or "_".join(settings)
    out = Path(args.out) if args.out else Path("results") / f"{datetime.now():%Y%m%d-%H%M}-{args.target}-{label}"
    summary = run_jobs(args.target, agent, args.model, cases, settings, args.reps, out,
                       workers=args.workers, max_usd=args.max_usd)
    print(f"done {summary.done}, errors {summary.errors}, skipped {summary.skipped}, "
          f"cost ${summary.cost_usd:.2f}{', stopped by spend cap' if summary.stopped_by_cap else ''}")
    print(out)
    return 3 if summary.stopped_by_cap else 0


def _settings_of(target: str) -> list[str]:
    adapter = make_adapter(target, "scripted", "scripted")
    try:
        return list(adapter.settings())
    finally:
        adapter.close()


def cmd_run(args) -> int:
    valid = _settings_of(args.target)
    unknown = [s for s in args.setting if s not in valid]
    if unknown:
        print(f"unknown setting(s) {', '.join(unknown)}; valid: {', '.join(valid)}", file=sys.stderr)
        return 2
    return _run(args, args.setting)


def cmd_ablate(args) -> int:
    return _run(args, _settings_of(args.target))


def cmd_report(args) -> int:
    out = Path(args.dir)
    meta = json.loads((out / "meta.json").read_text())
    cases: dict[str, AttackCase] = {}
    for f in meta.get("case_files", []):
        for c in load_cases(Path(f).name, root=Path(f).parent):
            cases[c.id] = c
    (out / "report.md").write_text(build_report(read_rows(out / "runs.jsonl"), cases, meta))
    print(out / "report.md")
    return 0


def cmd_list(args) -> int:
    for c in _load(args.target, args.cases):
        kind = "control" if c.control else c.family
        print(f"{c.id:32} {kind:24} {','.join(c.owasp)}")
    print("settings:", ", ".join(_settings_of(args.target)))
    return 0


def _run_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--target", required=True)
    p.add_argument("--cases", help="glob under cases/, or a path to a folder or file")
    p.add_argument("--reps", type=int, default=5)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--agent", choices=["llm", "scripted", "obedient"], default="llm")
    p.add_argument("--dry-run", action="store_true", help="same as --agent scripted: no LLM, no cost")
    p.add_argument("--model", default="gpt-6-luna")
    p.add_argument("--max-usd", type=float, default=5.0)
    p.add_argument("--out")
    p.add_argument("--label")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="harness")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run cases at chosen defence settings")
    _run_options(run)
    run.add_argument("--setting", action="append", required=True)
    run.set_defaults(fn=cmd_run)

    ablate = sub.add_parser("ablate", help="run cases at every defence setting of the target")
    _run_options(ablate)
    ablate.set_defaults(fn=cmd_ablate)

    report = sub.add_parser("report", help="rebuild report.md from runs.jsonl")
    report.add_argument("dir")
    report.set_defaults(fn=cmd_report)

    lst = sub.add_parser("list", help="list cases and settings")
    lst.add_argument("--target", required=True)
    lst.add_argument("--cases")
    lst.set_defaults(fn=cmd_list)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
