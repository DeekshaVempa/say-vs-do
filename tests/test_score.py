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
from src.load import normalize, dedupe_within_call
from src.fetch_sec import parse_transcript, period_from_date

ACTUALS = pd.DataFrame([
    {"company": "Test Co", "period": "Q1FY26", "metric": "ebitda_margin_pct", "value": 12.0, "source": "test"},
    {"company": "Test Co", "period": "Q2FY26", "metric": "ebitda_margin_pct", "value": 13.0, "source": "test"},
    {"company": "Test Co", "period": "Q2FY26", "metric": "nim_pct", "value": 3.45, "source": "test"},
    {"company": "Test Co", "period": "Q2FY26", "metric": "gross_npa_pct", "value": 2.4, "source": "test"},
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
    # Margin went from 12.0 in Q1 to 13.0 in Q2
    up = make_guidance(type="direction", direction="up", reference_period="Q1FY26")
    down = make_guidance(type="direction", direction="down", reference_period="Q1FY26")
    assert score_one(up, ACTUALS)["verdict"] == "kept"
    # Said margins would fall, they rose: wrong forecast, but good news
    assert score_one(down, ACTUALS)["verdict"] == "beat"
    # Said Q1 would be up on Q2, it was down: a real miss
    up_but_fell = make_guidance(type="direction", direction="up", target_period="Q1FY26", reference_period="Q2FY26")
    assert score_one(up_but_fell, ACTUALS)["verdict"] == "missed"


def test_beat_depends_on_which_way_is_good():
    # Margin of 13.0 above a 11 to 12.5 range is a beat, below 14 to 15 is a miss
    assert score_one(make_guidance(low=11, high=12.5), ACTUALS)["verdict"] == "beat"
    assert score_one(make_guidance(low=14, high=15), ACTUALS)["verdict"] == "missed"
    # For bad loans lower is better, so 2.4 under a 2.5 to 3 range is a beat
    npa = make_guidance(metric="gross_npa_pct", low=2.5, high=3.0)
    assert score_one(npa, ACTUALS)["verdict"] == "beat"
    assert score_one(make_guidance(metric="gross_npa_pct", low=1.5, high=2.0), ACTUALS)["verdict"] == "missed"


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


def test_beat_counts_for_delivery_but_not_credibility():
    scored = pd.DataFrame([
        {"company": "X", "verdict": "kept", "gap_pp": 0.0},
        {"company": "X", "verdict": "beat", "gap_pp": 1.0},
        {"company": "X", "verdict": "missed", "gap_pp": -1.0},
    ])
    row = company_scoreboard(scored).iloc[0]
    assert row["credibility_score"] == round((1 + 1) / (3 + 2), 2)   # only the kept one
    assert row["delivery_score"] == round((2 + 1) / (3 + 2), 2)      # kept and beat


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


def test_quote_matching_accepts_any_labeled_mention():
    # The model quoted the CFO, the label quoted the CEO; same promise
    gold = [make_guidance(quote="The new guidance is 2% to 3% growth in constant currency terms.",
                          alt_quotes=["Hence, we have revised our revenue guidance to 2% to 3%."])]
    predicted = [make_guidance(quote="Hence, we have revised our revenue guidance to 2% to 3%.")]
    assert len(match_records(gold, predicted)) == 1


def test_normalize_treats_curly_and_straight_quotes_alike():
    assert normalize("financial year ’26 – strong") == normalize("Financial year '26 - strong")


def test_repeated_promise_in_one_call_counts_once():
    text = "Company: X\n\nCEO: Guidance is 1% to 3%. CFO: To repeat, guidance is 1% to 3%."
    transcripts = [{"file": "x.txt", "text": text}]
    first = make_guidance(id="a", quote="To repeat, guidance is 1% to 3%.", low=1, high=3.0)
    second = make_guidance(id="b", quote="Guidance is 1% to 3%.", low=1.0, high=3)
    vague = make_guidance(id="c", type="vague", metric=None)
    kept = dedupe_within_call([first, second, vague, dict(vague, id="d")], transcripts)
    # The earlier mention wins, and vague statements are never merged
    assert [g["id"] for g in kept] == ["b", "c", "d"]


SEC_HTML = """
<P><B>Infosys Limited Earnings Conference Call</B></P><P><B>April 18, 2024</B></P>
<P>CORPORATE PARTICIPANTS</P><P><B>Salil Parekh</B></P><P>Chief Executive Officer</P>
<P>analystS</P><P><B>Ankur Rudra</B></P><P>JPMorgan</P>
<TABLE><TR><TD><B>Moderator</B></TD></TR></TABLE><P>Welcome to the call.</P>
<P><B>Salil
Parekh</B></P><P>Our guidance for FY '25 is 1% to 3%.</P><P>Margins 20% to 22%.</P>
"""


def test_sec_transcript_parsing():
    parsed = parse_transcript(SEC_HTML)
    # No quarter in this title, so it comes from the call date
    assert parsed["period"] == "Q4FY24" and parsed["date"] == "2024-04-18"
    assert parsed["participants"]["Management"] == "Salil Parekh (Chief Executive Officer)"
    assert parsed["participants"]["Others"] == "Ankur Rudra (JPMorgan)"
    assert parsed["turns"] == [("Moderator", "Welcome to the call."),
                               ("Salil Parekh", "Our guidance for FY '25 is 1% to 3%. Margins 20% to 22%.")]


def test_period_from_call_date_uses_indian_fiscal_year():
    assert period_from_date(2025, 7) == "Q1FY26"
    assert period_from_date(2025, 10) == "Q2FY26"
    assert period_from_date(2026, 1) == "Q3FY26"
    assert period_from_date(2026, 4) == "Q4FY26"


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
