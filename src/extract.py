"""
Uses Claude to pull forward-looking guidance out of earnings call transcripts
and turn each statement into a structured record we can score later.
"""
import json
import time

from config import METRICS, MODEL, EFFORT, INPUT_PRICE_PER_MTOK, OUTPUT_PRICE_PER_MTOK

SYSTEM_PROMPT = """You extract management guidance from Indian company earnings call transcripts.
You return only a JSON array. No prose, no markdown, no code fences."""


def build_prompt(transcript):
    metric_lines = "\n".join(f"- {name}: {desc}" for name, desc in METRICS.items())

    return f"""Company: {transcript['company']}
This call discusses results for period: {transcript['call_period']}
Indian fiscal years run April to March. Q1FY26 is Apr-Jun 2025, Q4FY26 is Jan-Mar 2026.

Find every forward-looking statement made by management (not analysts) about future business performance.
Ignore descriptions of past results.

For each statement return an object with these keys:
- "quote": the exact words from the transcript, copied verbatim. Keep it to one sentence or less.
- "metric": one of the metric names below, or null if it does not fit any of them
- "type": one of "range", "at_least", "at_most", "point", "direction", "vague"
- "low": number or null
- "high": number or null
- "value": number or null
- "direction": "up", "down", or null
- "target_period": the period the promise is about, like "Q3FY26" or "FY26", or null
- "reference_period": for "direction" only, the period being compared against, else null

Rules for "type":
- "X to Y percent" is "range" with low=X and high=Y
- "at least X" or "above X" is "at_least" with low=X
- "below X" or "at most X" is "at_most" with high=X
- "around X" or "to X" is "point" with value=X
- "will improve / recover / be lower than <period>" is "direction", and reference_period is that period
- anything with no measurable target, or a metric not in the list, is "vague" with metric null

Metrics:
{metric_lines}

Transcript:
{transcript['text']}"""


def parse_json_array(raw):
    # Models sometimes wrap JSON in code fences even when told not to,
    # so strip those before parsing instead of failing the whole run.
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned)


def extract_from_transcript(client, transcript):
    start = time.time()
    # No temperature here: Sonnet 5.5 rejects non-default sampling settings.
    # Thinking is on by default and its tokens count toward max_tokens, so
    # leave plenty of room or the JSON gets cut off halfway.
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": EFFORT},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(transcript)}],
    )
    latency = time.time() - start

    raw = "".join(block.text for block in response.content if block.type == "text")
    stats = {
        "file": transcript["file"],
        "latency_s": round(latency, 2),
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "stop_reason": response.stop_reason,
        "parse_ok": True,
    }

    try:
        records = parse_json_array(raw)
        if not isinstance(records, list):
            raise ValueError("expected a JSON array")
    except ValueError:  # JSONDecodeError is a ValueError too
        # Log it and move on. One bad transcript should not kill the batch.
        print(f"  Could not parse JSON for {transcript['file']} (stop_reason={response.stop_reason})")
        stats["parse_ok"] = False
        return [], stats

    records = [r for r in records if isinstance(r, dict)]

    stem = transcript["file"].replace(".txt", "")
    for i, record in enumerate(records, start=1):
        record["id"] = f"{stem}_llm{i}"
        record["company"] = transcript["company"]
        record["call_period"] = transcript["call_period"]
        record["source_file"] = transcript["file"]

    return records, stats


def run_extraction(transcripts):
    # Imported here so the default (no LLM) run works without the package installed.
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    all_records = []
    all_stats = []

    for transcript in transcripts:
        print(f"  Extracting {transcript['file']} ...")
        records, stats = extract_from_transcript(client, transcript)
        all_records.extend(records)
        all_stats.append(stats)

    return all_records, all_stats


def estimate_cost(stats):
    input_tokens = sum(s["input_tokens"] for s in stats)
    output_tokens = sum(s["output_tokens"] for s in stats)
    cost = (input_tokens * INPUT_PRICE_PER_MTOK + output_tokens * OUTPUT_PRICE_PER_MTOK) / 1_000_000
    return input_tokens, output_tokens, round(cost, 4)
