"""
Run with: python -m pytest tests/
These cover the scoring rules, since a bug there silently changes every score.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.score import score_one, company_scoreboard
from src.evaluate import match_records
from src.extract import parse_json_array, extract_from_transcript

ACTUALS = pd.DataFrame([
    {"company": "Test Co", "period": "Q1FY26", "metric": "ebitda_margin_pct", "value": 12.0, "source": "test"},
    {"company": "Test Co", "period": "Q2FY26", "metric": "ebitda_margin_pct", "value": 13.0, "source": "test"},
    {"company": "Test Co", "period": "Q2FY26", "metric": "nim_pct", "value": 3.45, "source": "test"},
])


def make_guidance(**overrides):
    g = {
        "id": "t1", "company": "Test Co", "call_period": "Q1FY26", "source_file": "x.txt",
        "quote": "something", "quote_verified": True, "metric": "ebitda_margin_pct",
        "type": "range", "low": None, "high": None, "value": None,
        "direction": None, "target_period": "Q2FY26", "reference_period": None,
    }
    g.update(overrides)
    return g


def test_range_kept_and_missed():
    assert score_one(make_guidance(low=12.5, high=13.5), ACTUALS)["verdict"] == "kept"
    assert score_one(make_guidance(low=14, high=15), ACTUALS)["verdict"] == "missed"


def test_point_uses_metric_tolerance():
    # NIM tolerance is 0.1pp, so 3.45 vs 3.6 is a miss but 3.45 vs 3.5 is kept
    assert score_one(make_guidance(metric="nim_pct", type="point", value=3.6), ACTUALS)["verdict"] == "missed"
    assert score_one(make_guidance(metric="nim_pct", type="point", value=3.5), ACTUALS)["verdict"] == "kept"


def test_direction_compares_to_reference_period():
    up = make_guidance(type="direction", direction="up", reference_period="Q1FY26")
    down = make_guidance(type="direction", direction="down", reference_period="Q1FY26")
    assert score_one(up, ACTUALS)["verdict"] == "kept"
    assert score_one(down, ACTUALS)["verdict"] == "missed"


def test_unverified_quote_is_never_scored():
    result = score_one(make_guidance(low=12.5, high=13.5, quote_verified=False), ACTUALS)
    assert result["verdict"] == "unverified_quote"


def test_missing_actual_is_no_data():
    assert score_one(make_guidance(low=1, high=2, target_period="Q4FY26"), ACTUALS)["verdict"] == "no_data"


def test_smoothing_ranks_small_samples_lower():
    scored = pd.DataFrame([
        {"company": "One", "verdict": "kept", "gap_pp": None},
        *[{"company": "Six", "verdict": "kept", "gap_pp": None} for _ in range(6)],
    ])
    board = company_scoreboard(scored)
    assert list(board["company"]) == ["Six", "One"]


def test_quote_matching_handles_trimmed_quotes():
    gold = [make_guidance(quote="EBIT margin for Q2 should be at least 21 percent")]
    predicted = [make_guidance(quote="so EBIT margin for Q2 should be at least 21 percent.")]
    assert len(match_records(gold, predicted)) == 1


def test_incomplete_llm_record_is_flagged_not_crashed():
    # The kind of thing the LLM gets wrong: a range with a missing end,
    # or the number left as a string.
    assert score_one(make_guidance(low=12.5, high=None), ACTUALS)["verdict"] == "incomplete"
    assert score_one(make_guidance(type="point", value="13%"), ACTUALS)["verdict"] == "incomplete"
    assert score_one(make_guidance(type="direction", direction="flat", reference_period="Q1FY26"), ACTUALS)["verdict"] == "incomplete"


def test_parse_json_with_code_fence():
    raw = '```json\n[{"quote": "hi"}]\n```'
    assert parse_json_array(raw) == [{"quote": "hi"}]


class FakeClient:
    # Stands in for anthropic.Anthropic() so the request can be checked offline.
    def __init__(self, text):
        self.text = text
        self.sent = None
        self.messages = self

    def create(self, **kwargs):
        self.sent = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.text)],
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
            stop_reason="end_turn",
        )


TRANSCRIPT = {"file": "x_Q1FY26.txt", "company": "Test Co", "call_period": "Q1FY26", "text": "..."}


def test_extraction_request_and_record_tagging():
    client = FakeClient('[{"quote": "margin should be 13 percent"}, "junk"]')
    records, stats = extract_from_transcript(client, TRANSCRIPT)
    # Sonnet 5.5 returns a 400 if temperature is set
    assert "temperature" not in client.sent
    assert len(records) == 1  # the non-object item is dropped
    assert records[0]["id"] == "x_Q1FY26_llm1"
    assert records[0]["source_file"] == "x_Q1FY26.txt"
    assert stats["parse_ok"] and stats["stop_reason"] == "end_turn"


def test_extraction_survives_non_array_json():
    records, stats = extract_from_transcript(FakeClient('{"guidance": []}'), TRANSCRIPT)
    assert records == [] and not stats["parse_ok"]
