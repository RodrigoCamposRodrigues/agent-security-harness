import pytest

from harness.pricing import cost_usd
from harness.stats import fmt_rate, wilson


def test_wilson_zero_of_five():
    assert wilson(0, 5)[0] == 0.0
    assert wilson(0, 5)[1] == pytest.approx(0.4345, abs=1e-3)


def test_wilson_zero_of_twenty():
    assert wilson(0, 20)[1] == pytest.approx(0.161, abs=1e-3)


def test_wilson_all_success():
    assert wilson(5, 5)[0] == pytest.approx(0.5655, abs=1e-3)
    assert wilson(5, 5)[1] == 1.0


def test_wilson_empty():
    assert wilson(0, 0) == (0.0, 1.0)


def test_fmt_rate():
    assert fmt_rate(0, 5) == "0/5 (0–43%)"
    assert fmt_rate(5, 5) == "5/5 (57–100%)"
    assert fmt_rate(0, 0) == "–"


def test_cost_usd():
    assert cost_usd("gpt-6-luna", 1_000_000, 1_000_000) == pytest.approx(0.60)
    assert cost_usd("scripted", 1_000_000, 1_000_000) == 0.0


def test_cost_for_gpt_5_nano():
    assert cost_usd("gpt-5-nano", 1_000_000, 1_000_000) == pytest.approx(0.05 + 0.40)
