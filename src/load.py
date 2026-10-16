import json

import pandas as pd

from config import TRANSCRIPT_DIR, ACTUALS_PATH


def normalize(text):
    # Collapse whitespace and lowercase so line breaks or casing
    # do not cause a real quote to look fake.
    return " ".join(str(text).split()).lower()


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


def load_transcripts():
    transcripts = []
    for path in sorted(TRANSCRIPT_DIR.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        header = parse_header(text)
        transcripts.append({
            "file": path.name,
            "company": header["company"],
            "call_period": header["period"],
            "call_date": header["date"],
            "text": text,
        })
    return transcripts


def load_actuals():
    return pd.read_csv(ACTUALS_PATH)


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


def add_call_dates(guidance, transcripts):
    # The date management said it, taken from the transcript header, so the
    # report can show when a promise was made and not just which quarter.
    date_by_file = {t["file"]: t["call_date"] for t in transcripts}
    for record in guidance:
        record["call_date"] = date_by_file.get(record.get("source_file"))
    return guidance
