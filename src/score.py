"""
Checks each piece of guidance against what the company actually reported,
then rolls the results up into a credibility score per company.
"""
import pandas as pd

from config import DEFAULT_POINT_TOLERANCE_PP, POINT_TOLERANCE_PP, LOWER_IS_BETTER

# What each guidance type needs before it can be checked.
REQUIRED_FIELDS = {
    "range": ["low", "high"],
    "at_least": ["low"],
    "at_most": ["high"],
    "point": ["value"],
    "direction": ["direction", "reference_period"],
}


def is_complete(g):
    # Hand labels are always complete, LLM output is not. A missing number or
    # a "12%" string where a number should be gets flagged instead of crashing
    # the run or being guessed at.
    if not g.get("target_period"):
        return False
    for field in REQUIRED_FIELDS.get(g.get("type"), []):
        value = g.get(field)
        if field in ("low", "high", "value"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return False
        elif field == "direction":
            if value not in ("up", "down"):
                return False
        elif not value:
            return False
    return True


def get_actual(actuals, company, period, metric):
    rows = actuals[
        (actuals["company"] == company)
        & (actuals["period"] == period)
        & (actuals["metric"] == metric)
    ]
    if rows.empty:
        return None, None
    row = rows.iloc[0]
    return float(row["value"]), row["source"]


def target_label(g):
    # Human readable version of the promise, used in the report.
    t = g.get("type")
    if t == "range":
        return f"{g.get('low')} to {g.get('high')}%"
    if t == "at_least":
        return f"at least {g.get('low')}%"
    if t == "at_most":
        return f"at most {g.get('high')}%"
    if t == "point":
        return f"around {g.get('value')}%"
    if t == "direction":
        word = "higher" if g.get("direction") == "up" else "lower"
        return f"{word} than {g.get('reference_period')}"
    return "no measurable target"


def target_anchor(g):
    # The single number we measure the gap against.
    t = g["type"]
    if t == "range":
        return (g["low"] + g["high"]) / 2
    if t == "at_least":
        return g["low"]
    if t == "at_most":
        return g["high"]
    if t == "point":
        return g["value"]
    return None


def score_one(g, actuals):
    result = {
        "id": g["id"],
        "company": g["company"],
        "call_period": g["call_period"],
        "call_date": g.get("call_date"),
        "source_file": g["source_file"],
        "quote": g.get("quote"),
        "metric": g.get("metric"),
        "type": g.get("type"),
        "target_period": g.get("target_period"),
        "target": target_label(g),
        "actual": None,
        "actual_source": None,
        "verdict": None,
        "gap_pp": None,
    }

    if not g.get("quote_verified", False):
        # A quote we cannot find in the transcript might be a hallucination.
        result["verdict"] = "unverified_quote"
        return result

    if g.get("type") == "vague" or not g.get("metric"):
        result["verdict"] = "vague"
        return result

    if not is_complete(g):
        result["verdict"] = "incomplete"
        return result

    actual, source = get_actual(actuals, g["company"], g["target_period"], g["metric"])
    if actual is None:
        result["verdict"] = "no_data"
        return result

    result["actual"] = actual
    result["actual_source"] = source
    t = g["type"]

    if t == "range":
        kept = g["low"] <= actual <= g["high"]
    elif t == "at_least":
        kept = actual >= g["low"]
    elif t == "at_most":
        kept = actual <= g["high"]
    elif t == "point":
        tolerance = POINT_TOLERANCE_PP.get(g["metric"], DEFAULT_POINT_TOLERANCE_PP)
        kept = abs(actual - g["value"]) <= tolerance
    elif t == "direction":
        reference, _ = get_actual(actuals, g["company"], g["reference_period"], g["metric"])
        if reference is None:
            result["verdict"] = "no_data"
            return result
        if g["direction"] == "up":
            kept = actual > reference
        else:
            kept = actual < reference
        result["target"] = f"{target_label(g)} ({reference}%)"
    else:
        result["verdict"] = "vague"
        return result

    result["verdict"] = "kept" if kept else "missed"

    # Gap vs target in percentage points. Positive means the company did
    # better than promised, negative means it fell short.
    anchor = target_anchor(g)
    if anchor is not None:
        gap = actual - anchor
        if g["metric"] in LOWER_IS_BETTER:
            gap = -gap
        result["gap_pp"] = round(gap, 2)

    return result


def score_all(guidance, actuals):
    return pd.DataFrame([score_one(g, actuals) for g in guidance])


def company_scoreboard(scored):
    rows = []
    for company, group in scored.groupby("company"):
        kept = int((group["verdict"] == "kept").sum())
        missed = int((group["verdict"] == "missed").sum())
        scorable = kept + missed

        # Laplace smoothing: (kept + 1) / (scorable + 2).
        # With so few promises per company, 1 out of 1 should not look as
        # trustworthy as 6 out of 6. This pulls small samples toward 50%.
        adjusted = (kept + 1) / (scorable + 2)

        gaps = group["gap_pp"].dropna()
        rows.append({
            "company": company,
            "promises_scored": scorable,
            "kept": kept,
            "missed": missed,
            "vague": int((group["verdict"] == "vague").sum()),
            "no_data": int((group["verdict"] == "no_data").sum()),
            "unverified": int((group["verdict"] == "unverified_quote").sum()),
            "incomplete": int((group["verdict"] == "incomplete").sum()),
            "raw_score": round(kept / scorable, 2) if scorable else None,
            "credibility_score": round(adjusted, 2),
            "avg_gap_pp": round(gaps.mean(), 2) if len(gaps) else None,
        })

    board = pd.DataFrame(rows)
    return board.sort_values("credibility_score", ascending=False).reset_index(drop=True)
