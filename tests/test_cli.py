import json
from pathlib import Path

from harness.cli import main

FAKE = str(Path(__file__).parent / "data" / "cases" / "fake")


def test_run_writes_results_dir(tmp_path, capsys):
    out = tmp_path / "res"
    code = main(["run", "--target", "fake", "--setting", "off", "--setting", "on", "--cases", FAKE,
                 "--reps", "2", "--dry-run", "--out", str(out)])
    assert code == 0
    assert len((out / "runs.jsonl").read_text().splitlines()) == 8
    assert json.loads((out / "meta.json").read_text())["agent"] == "scripted"
    assert "| on " in (out / "report.md").read_text()
    printed = capsys.readouterr().out
    assert str(out) in printed and "done 8" in printed


def test_default_out_dir_uses_label(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["run", "--target", "fake", "--setting", "on", "--cases", FAKE, "--reps", "1", "--label", "smoke"]) == 0
    [d] = list((tmp_path / "results").iterdir())
    assert d.name.endswith("-fake-smoke")


def test_unknown_setting_exits_2(tmp_path, capsys):
    code = main(["run", "--target", "fake", "--setting", "sideways", "--cases", FAKE, "--out", str(tmp_path / "x")])
    assert code == 2
    assert "on, off" in capsys.readouterr().err
    assert not (tmp_path / "x" / "runs.jsonl").exists()


def test_ablate_runs_every_setting(tmp_path):
    out = tmp_path / "abl"
    assert main(["ablate", "--target", "fake", "--cases", FAKE, "--reps", "1", "--out", str(out)]) == 0
    assert json.loads((out / "meta.json").read_text())["settings"] == ["on", "off"]


def test_report_rebuilds_from_jsonl(tmp_path):
    out = tmp_path / "res"
    main(["run", "--target", "fake", "--setting", "off", "--cases", FAKE, "--reps", "1", "--out", str(out)])
    (out / "report.md").unlink()
    assert main(["report", str(out)]) == 0
    assert "## Headline" in (out / "report.md").read_text()


def test_list_prints_cases_and_settings(capsys):
    assert main(["list", "--target", "fake", "--cases", FAKE]) == 0
    printed = capsys.readouterr().out
    assert "fake-attack" in printed and "LLM01" in printed and "fake-control" in printed
    assert "on" in printed and "off" in printed


def test_exit_3_when_stopped_by_cap(tmp_path):
    cases = tmp_path / "c"
    cases.mkdir()
    text = (Path(FAKE) / "attack.yaml").read_text().replace('{attack_on: ["off"]}', "{tokens: [1000000, 0]}")
    (cases / "a.yaml").write_text(text)
    code = main(["run", "--target", "fake", "--setting", "on", "--cases", str(cases), "--reps", "3",
                 "--max-usd", "0.05", "--out", str(tmp_path / "o")])
    assert code == 3


def test_tests_never_trace_to_langsmith(tmp_path):
    """cli.main loads .env; the test process must still never send traces out."""
    import os
    main(["list", "--target", "rotation"])
    assert os.environ.get("LANGSMITH_TRACING", "").lower() != "true"
    assert os.environ.get("LANGCHAIN_TRACING_V2", "").lower() != "true"
