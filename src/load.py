import json

import pandas as pd

from config import TRANSCRIPT_DIR, ACTUALS_PATH

# Real transcripts use curly quotes and en dashes. The model often types the
# plain version back, which should not make a real quote look fake.
PUNCTUATION = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                             "–": "-", "—": "-", " ": " "})

# The fields that define a promise. Two records from the same call with the
# same values here are the same promise said twice.
PROMISE_FIELDS = ["metric", "type", "low", "high", "value", "direction", "target_period", "reference_period"]


def normalize(text):
    # Collapse whitespace and lowercase so line breaks or casing
    # do not cause a real quote to look fake.
    return " ".join(str(text).translate(PUNCTUATION).split()).lower()


def parse_header(text):
    # Each transcript starts with "Key: value" lines followed by a blank line.
    header = {}
    for line in text.splitlines():
        if not line.strip():
            break
        if ":" in line:
            key, value = line.split(":", 1)
            header[key.strip().lower()] = value.strip()
    return header


def load_transcripts(transcript_dir=TRANSCRIPT_DIR):
    transcripts = []
    for path in sorted(transcript_dir.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        header = parse_header(text)
        transcripts.append({
            "file": path.name,
            "company": header["company"],
            "call_period": header["period"],
            "call_date": header["date"],
            "note": header.get("note", ""),
            "text": text,
        })
    return transcripts


def load_actuals(path=ACTUALS_PATH):
    return pd.read_csv(path)


def load_guidance(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def verify_quotes(guidance, transcripts):
    """
    Mark each guidance record with whether its quote really appears in the
    source transcript. Anything we cannot trace back to the source does not
    get scored, because Prism's promise is that every answer is checkable.
    """
    text_by_file = {t["file"]: normalize(t["text"]) for t in transcripts}
    for record in guidance:
        source_text = text_by_file.get(record.get("source_file"), "")
        quote = record.get("quote") or ""
        record["quote_verified"] = bool(quote) and normalize(quote) in source_text
    return guidance


def missing_alt_quotes(guidance, transcripts):
    # Hand labels can list other sentences where management repeats the same
    # promise. Those are typed by hand too, so they get the same check.
    text_by_file = {t["file"]: normalize(t["text"]) for t in transcripts}
    return [
        (g["id"], alt) for g in guidance for alt in g.get("alt_quotes", [])
        if normalize(alt) not in text_by_file.get(g["source_file"], "")
    ]


def add_call_dates(guidance, transcripts):
    # The date management said it, taken from the transcript header, so the
    # report can show when a promise was made and not just which quarter.
    date_by_file = {t["file"]: t["call_date"] for t in transcripts}
    for record in guidance:
        record["call_date"] = date_by_file.get(record.get("source_file"))
    return guidance


def dedupe_within_call(guidance, transcripts):
    """
    On a real call the CEO states the guidance, the CFO repeats it, and it
    comes up again in Q&A. That is one promise, not three, so keep only the
    first time each one is said. Vague statements are left alone, since they
    have no fields to compare.
    """
    text_by_file = {t["file"]: normalize(t["text"]) for t in transcripts}

    def position(record):
        found = text_by_file.get(record.get("source_file"), "").find(normalize(record.get("quote") or ""))
        return found if found >= 0 else float("inf")

    def promise_key(record):
        values = []
        for field in PROMISE_FIELDS:
            value = record.get(field)
            # 3 and 3.0 are the same target
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value = float(value)
            values.append(value)
        return (record.get("source_file"), *values)

    first_said = {}
    for i, record in enumerate(guidance):
        if record.get("type") == "vague" or not record.get("metric"):
            continue
        key = promise_key(record)
        if key not in first_said or position(record) < position(guidance[first_said[key]]):
            first_said[key] = i

    # Keep the original order so nothing else in the output moves around.
    return [
        record for i, record in enumerate(guidance)
        if record.get("type") == "vague" or not record.get("metric") or first_said[promise_key(record)] == i
    ]
