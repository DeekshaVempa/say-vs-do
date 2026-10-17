"""
Compares what the LLM extracted against a hand-labeled gold set.
This tells us whether the extraction step can be trusted before we
let its output drive a score that users will see.
"""
from difflib import SequenceMatcher

from src.load import normalize
from src.extract import estimate_cost

FIELDS_TO_CHECK = ["metric", "type", "target_period", "low", "high", "value", "direction", "reference_period"]
MATCH_THRESHOLD = 0.6


def quote_similarity(a, b):
    a, b = normalize(a), normalize(b)
    # If one quote is a shorter slice of the other, treat it as the same statement.
    # The LLM often trims or extends a quote by a few words.
    if a in b or b in a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def same_value(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 1e-6
    return str(a).strip().lower() == str(b).strip().lower()


def is_measurable(record):
    return record.get("type") != "vague" and bool(record.get("metric"))


def match_records(gold, predicted):
    # Greedy matching inside each transcript: for every gold statement,
    # take the most similar unused prediction from the same file. On a real
    # call the same promise is said by the CEO and again by the CFO, so the
    # labels can list those other sentences and any of them counts.
    used = set()
    pairs = []
    for g in gold:
        best_index, best_score = None, 0.0
        for i, p in enumerate(predicted):
            if i in used or p.get("source_file") != g["source_file"]:
                continue
            score = max(quote_similarity(q, p.get("quote", "")) for q in [g["quote"], *g.get("alt_quotes", [])])
            if score > best_score:
                best_index, best_score = i, score
        if best_index is not None and best_score >= MATCH_THRESHOLD:
            used.add(best_index)
            pairs.append((g, predicted[best_index]))
    return pairs


def compare(gold, predicted):
    pairs = match_records(gold, predicted)

    field_correct = {field: 0 for field in FIELDS_TO_CHECK}
    fully_correct = 0
    field_errors = []
    for g, p in pairs:
        wrong = [f for f in FIELDS_TO_CHECK if not same_value(g.get(f), p.get(f))]
        for field in FIELDS_TO_CHECK:
            if field not in wrong:
                field_correct[field] += 1
        if wrong:
            field_errors.append({"id": g["id"], "quote": g["quote"],
                                 "fields": {f: {"label": g.get(f), "model": p.get(f)} for f in wrong}})
        else:
            fully_correct += 1

    matched = len(pairs)
    matched_gold = {id(g) for g, _ in pairs}
    matched_pred = {id(p) for _, p in pairs}
    return {
        "gold_statements": len(gold),
        "predicted_statements": len(predicted),
        "matched": matched,
        "recall": round(matched / len(gold), 2) if gold else None,
        "precision": round(matched / len(predicted), 2) if predicted else None,
        "fully_correct_records": fully_correct,
        "field_accuracy": {f: round(c / matched, 2) if matched else None for f, c in field_correct.items()},
        # The actual failure cases, so the numbers above can be explained
        "field_errors": field_errors,
        "labeled_but_not_found": [g["quote"] for g in gold if id(g) not in matched_gold],
        "found_but_not_labeled": [p.get("quote") for p in predicted if id(p) not in matched_pred],
    }


def evaluate_extraction(gold, predicted, run_stats, duplicates_removed=0):
    input_tokens, output_tokens, cost = estimate_cost(run_stats)
    latencies = [s["latency_s"] for s in run_stats]

    overall = compare(gold, predicted)
    # Real transcripts are full of vague talk about demand and deal pipelines.
    # The scores only use measurable promises, so that is the number to watch.
    measurable = compare([g for g in gold if is_measurable(g)], [p for p in predicted if is_measurable(p)])
    for detail in ("field_errors", "labeled_but_not_found", "found_but_not_labeled"):
        overall.pop(detail)

    return {
        **overall,
        "measurable_only": measurable,
        "duplicates_removed": duplicates_removed,
        "quote_verified_rate": round(
            sum(1 for p in predicted if p.get("quote_verified")) / len(predicted), 2
        ) if predicted else None,
        "json_parse_failures": sum(1 for s in run_stats if not s["parse_ok"]),
        "truncated_responses": sum(1 for s in run_stats if s.get("stop_reason") == "max_tokens"),
        "avg_latency_s": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": cost,
    }
