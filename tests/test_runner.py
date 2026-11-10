import json
import shutil
from pathlib import Path

import pytest

from harness.cases import load_cases
from harness.runner import read_rows, run_jobs

FAKE = Path(__file__).parent / "data" / "cases" / "fake"


def cases_dir(tmp_path, extra: dict[str, str] | None = None):
    d = tmp_path / "cases"
    shutil.copytree(FAKE, d)
    for name, text in (extra or {}).items():
        (d / name).write_text(text)
    return d


def run(tmp_path, d, **kw):
    args = dict(target="fake", agent="scripted", model="gpt-6-luna", cases=load_cases("*.yaml", root=d),
                settings=["on", "off"], reps=3, out_dir=tmp_path / "out")
    return run_jobs(**{**args, **kw})


def test_runs_every_job_and_writes_report(tmp_path):
    summary = run(tmp_path, cases_dir(tmp_path))
    rows = read_rows(tmp_path / "out" / "runs.jsonl")
    assert len(rows) == 12 and summary.done == 12 and summary.errors == 0
    assert (tmp_path / "out" / "report.md").exists()
    meta = json.loads((tmp_path / "out" / "meta.json").read_text())
    assert meta["settings"] == ["on", "off"] and meta["headline"] == ["off", "on"]
    attack = {(r["setting"], r["rep"]): r["attack_success"] for r in rows if r["case_id"] == "fake-attack"}
    assert attack[("off", 0)] is True and attack[("on", 0)] is False
    control = [r for r in rows if r["case_id"] == "fake-control"]
    assert all(r["control"] and r["attack_success"] is None and r["task_success"] for r in control)
    assert [(r["case_id"], r["setting"], r["rep"]) for r in rows][:4] == [
        ("fake-attack", "on", 0), ("fake-attack", "on", 1), ("fake-attack", "on", 2), ("fake-attack", "off", 0)]


def test_resume_skips_done_jobs(tmp_path):
    d = cases_dir(tmp_path)
    run(tmp_path, d)
    again = run(tmp_path, d)
    assert again.skipped == 12 and again.done == 0
    assert len(read_rows(tmp_path / "out" / "runs.jsonl")) == 12


def test_resume_ignores_truncated_last_line(tmp_path):
    d = cases_dir(tmp_path)
    run(tmp_path, d, reps=1, settings=["on"])
    path = tmp_path / "out" / "runs.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n" + '{"case_id": "x"')
    assert len(read_rows(path)) == 1
    again = run(tmp_path, d, reps=1, settings=["on"])
    assert again.done == 1 and again.skipped == 1
    rows = read_rows(path)
    assert sorted(r["case_id"] for r in rows) == ["fake-attack", "fake-control"]


def test_adapter_exception_becomes_error_row_and_is_retried(tmp_path):
    flaky = (FAKE / "attack.yaml").read_text().replace("fake-attack", "fake-flaky").replace(
        "{attack_on: [\"off\"]}", "{attack_on: [\"off\"], raise_on_rep: 1}")
    d = cases_dir(tmp_path, {"flaky.yaml": flaky})
    first = run(tmp_path, d, settings=["off"])
    rows = read_rows(tmp_path / "out" / "runs.jsonl")
    errors = [r for r in rows if r["outcome"] == "error"]
    assert first.errors == 1 and len(errors) == 1
    assert errors[0]["case_id"] == "fake-flaky" and errors[0]["rep"] == 1
    assert errors[0]["error"].startswith("RuntimeError:") and errors[0]["attack_success"] is None
    second = run(tmp_path, d, settings=["off"])
    assert second.done == 1 and second.skipped == 8
    retried = [r for r in read_rows(tmp_path / "out" / "runs.jsonl") if (r["case_id"], r["rep"]) == ("fake-flaky", 1)]
    assert [r["outcome"] for r in retried] == ["error", "succeeded"]


def test_unknown_check_name_fails_before_running(tmp_path):
    bad = (FAKE / "attack.yaml").read_text().replace("fake-attack", "fake-bad").replace("name: fake_attack", "name: nope")
    d = cases_dir(tmp_path, {"bad.yaml": bad})
    with pytest.raises(ValueError, match=r"bad\.yaml"):
        run(tmp_path, d)
    assert not (tmp_path / "out" / "runs.jsonl").exists()


def test_unknown_setting_rejected(tmp_path):
    with pytest.raises(ValueError, match="on, off"):
        run(tmp_path, cases_dir(tmp_path), settings=["sideways"])


def test_spend_cap_stops_cleanly(tmp_path):
    pricey = (FAKE / "attack.yaml").read_text().replace("{attack_on: [\"off\"]}", "{attack_on: [\"off\"], tokens: [1000000, 0]}")
    d = tmp_path / "cases"
    d.mkdir()
    (d / "a.yaml").write_text(pricey)
    summary = run(tmp_path, d, max_usd=0.25)
    assert summary.stopped_by_cap and summary.done == 3
    assert summary.cost_usd == pytest.approx(0.30)
    assert (tmp_path / "out" / "report.md").exists()
    again = run(tmp_path, d, max_usd=0.25)
    assert again.stopped_by_cap and again.done == 0


def test_parallel_workers_match_sequential(tmp_path):
    d = cases_dir(tmp_path)
    run(tmp_path, d, out_dir=tmp_path / "seq")
    run(tmp_path, d, out_dir=tmp_path / "par", workers=2)

    def verdicts(name):
        return sorted((r["case_id"], r["setting"], r["rep"], r["attack_success"], r["task_success"])
                      for r in read_rows(tmp_path / name / "runs.jsonl"))

    assert verdicts("par") == verdicts("seq")


def test_meta_records_enabled_defences_and_refuses_a_changed_meaning(tmp_path):
    d = cases_dir(tmp_path)
    run(tmp_path, d)
    meta_path = tmp_path / "out" / "meta.json"
    meta = json.loads(meta_path.read_text())
    assert meta["enabled_defences"] == {"on": ["guard"], "off": []}
    meta["enabled_defences"]["on"] = ["guard", "new_defence"]  # as if a defence was added after this folder ran
    meta_path.write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="enabled defences"):
        run(tmp_path, d)
